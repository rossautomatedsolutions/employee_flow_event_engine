from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.analysis.event_study import EventStudyConfig, run_event_study
from src.analysis.research_summary import write_research_summary_report
from src.analysis.strategy import (
    CrossSectionConfig,
    StrategyConfig,
    assign_cross_sectional_groups,
    filter_event_panel,
    simulate_strategy,
)
from src.data.price_loader import PriceDataProvider, build_price_loader, persist_prices
from src.data.sec_parser import FilingDocument, load_filing_documents_from_fixtures, parse_many_espp_hints
from src.events.espp_event_extractor import ESPPEvent, estimate_event_dates_with_audit

LOGGER = logging.getLogger("pipeline.event_study")


@dataclass(slots=True)
class TickerConfig:
    ticker: str
    market_cap: float
    employees: int


@dataclass(slots=True)
class ExperimentConfig:
    tickers: list[TickerConfig]
    benchmark: str
    start_date: date
    end_date: date
    output_dir: Path
    price_source: str
    price_data_path: Path | None
    filing_fixture_dir: Path | None
    review_file: Path | None
    event_study: EventStudyConfig
    strategy: StrategyConfig
    cross_section: CrossSectionConfig


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


def _mock_filings(ticker: str, start_year: int, end_year: int) -> list[FilingDocument]:
    filings = []
    for year in range(start_year, end_year + 1):
        text = (
            "The employee stock purchase plan (ESPP) has six-month offering periods. "
            "The purchase date is the last day of the period, around June 30 and December 31."
        )
        filings.append(
            FilingDocument(
                ticker=ticker,
                filing_type="10-K",
                filing_date=date(year, 2, 15),
                text=text,
                source_id=f"mock_{ticker.lower()}_{year}_10k",
                source_kind="mock",
            )
        )
    return filings


def _load_filings_for_ticker(config: ExperimentConfig, ticker: str) -> list[FilingDocument]:
    if config.filing_fixture_dir is not None:
        docs = load_filing_documents_from_fixtures(config.filing_fixture_dir, ticker=ticker)
        if docs:
            LOGGER.info("[%s] loaded %s local filing fixture(s)", ticker, len(docs))
            return docs
        LOGGER.warning(
            "[%s] no local filing fixtures found under %s; falling back to mock filings",
            ticker,
            config.filing_fixture_dir,
        )
    return _mock_filings(ticker, config.start_date.year, config.end_date.year)


def _persist_date_audit(output_dir: Path, audit_frames: list[pd.DataFrame]) -> None:
    audit_columns = [
        "ticker",
        "filing_type",
        "filing_date",
        "source_fixture_path",
        "source_id",
        "source_snippet",
        "candidate_month_day",
        "assigned_event_date",
        "derivation_rule",
        "confidence",
        "fallback_anchor_used",
        "event_review_id",
        "review_status",
        "reviewed_event_date",
        "review_note",
        "effective_event_date",
        "included_in_event_study",
    ]
    if audit_frames:
        audit = pd.concat(audit_frames, ignore_index=True)
        audit = audit.reindex(columns=audit_columns).sort_values(
            ["ticker", "assigned_event_date", "candidate_month_day", "source_id"],
            ignore_index=True,
        )
    else:
        audit = pd.DataFrame(columns=audit_columns)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output_dir / "espp_date_audit.csv", index=False)


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value!r}. Expected YYYY-MM-DD") from exc


def _build_price_data_provider(config: ExperimentConfig) -> PriceDataProvider:
    return build_price_loader(price_source=config.price_source, price_data_path=config.price_data_path)


def _load_config(config_path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(config_path.read_text())

    tickers = [
        TickerConfig(
            ticker=str(item["ticker"]),
            market_cap=float(item["market_cap"]),
            employees=int(item["employees"]),
        )
        for item in raw["tickers"]
    ]

    event_cfg = raw.get("event_study", {})
    strategy_cfg = raw.get("strategy", {})
    cross_cfg = raw.get("cross_section", {})

    return ExperimentConfig(
        tickers=tickers,
        benchmark=str(raw["benchmark"]),
        start_date=_parse_date(raw["start_date"], "start_date"),
        end_date=_parse_date(raw["end_date"], "end_date"),
        output_dir=Path(raw.get("output_dir", "artifacts/first_pass")),
        price_source=str(raw.get("price_source", "yfinance")),
        price_data_path=Path(raw["price_data_path"]) if raw.get("price_data_path") else None,
        filing_fixture_dir=Path(raw["filings"]["fixture_dir"]) if raw.get("filings", {}).get("fixture_dir") else None,
        review_file=Path(raw["reviews"]["review_file"]) if raw.get("reviews", {}).get("review_file") else None,
        event_study=EventStudyConfig(
            window_before=int(event_cfg.get("window_before", 10)),
            window_after=int(event_cfg.get("window_after", 10)),
            volume_lookback=int(event_cfg.get("volume_lookback", 20)),
            label="espp",
        ),
        strategy=StrategyConfig(
            entry_tau=int(strategy_cfg.get("entry_tau", 1)),
            exit_tau=int(strategy_cfg.get("exit_tau", 5)),
            volume_spike_threshold=float(strategy_cfg.get("volume_spike_threshold", 1.25)),
            min_confidence=float(strategy_cfg.get("min_confidence", 0.7)),
        ),
        cross_section=CrossSectionConfig(
            market_cap_bins=tuple(cross_cfg.get("market_cap_bins", [2e10, 2e11])),
            volatility_bins=tuple(cross_cfg.get("volatility_bins", [0.015, 0.03])),
            employee_heavy_threshold=int(cross_cfg.get("employee_heavy_threshold", 100_000)),
        ),
    )


def _empty_review_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "event_review_id",
            "original_assigned_event_date",
            "reviewed_event_date",
            "review_status",
            "review_note",
        ]
    )


def _load_event_date_reviews(review_file: Path | None) -> pd.DataFrame:
    if review_file is None or not review_file.exists():
        return _empty_review_frame()

    reviews = pd.read_csv(review_file, dtype=str).fillna("")
    if "event_review_id" not in reviews.columns:
        reviews["event_review_id"] = ""

    required = {"ticker", "original_assigned_event_date", "reviewed_event_date", "review_status", "review_note", "event_review_id"}
    missing = required.difference(reviews.columns)
    if missing:
        raise ValueError(f"Review file missing required columns: {sorted(missing)}")

    allowed_statuses = {"accepted", "corrected", "rejected"}
    reviews["review_status"] = reviews["review_status"].str.strip().str.lower()
    reviews["event_review_id"] = reviews["event_review_id"].str.strip()
    invalid_statuses = sorted(set(reviews["review_status"]).difference(allowed_statuses))
    if invalid_statuses:
        raise ValueError(f"Review file has invalid review_status values: {invalid_statuses}")

    reviews["ticker"] = reviews["ticker"].str.strip()
    reviews["original_assigned_event_date"] = reviews["original_assigned_event_date"].str.strip()
    missing_tickers = reviews[reviews["ticker"] == ""]
    if not missing_tickers.empty:
        raise ValueError("Review rows require ticker")

    reviews["original_assigned_event_date"] = reviews["original_assigned_event_date"].map(
        lambda value: _parse_date(value, "original_assigned_event_date").isoformat() if value else ""
    )
    reviews["reviewed_event_date"] = reviews["reviewed_event_date"].map(lambda value: _parse_date(value, "reviewed_event_date").isoformat() if value else "")
    corrected_without_date = reviews[(reviews["review_status"] == "corrected") & (reviews["reviewed_event_date"] == "")]
    if not corrected_without_date.empty:
        raise ValueError("Corrected review rows require reviewed_event_date")

    missing_keys = reviews[(reviews["event_review_id"] == "") & (reviews["original_assigned_event_date"] == "")]
    if not missing_keys.empty:
        raise ValueError("Review rows require event_review_id or original_assigned_event_date")

    duplicated_ids = reviews[(reviews["event_review_id"] != "")].duplicated(subset=["event_review_id"], keep=False)
    if duplicated_ids.any():
        duplicates = reviews.loc[(reviews["event_review_id"] != "") & duplicated_ids, ["event_review_id"]].drop_duplicates().to_dict("records")
        raise ValueError(f"Duplicate review rows found for event_review_id keys: {duplicates}")

    fallback_rows = reviews["event_review_id"] == ""
    duplicated_fallback = reviews.loc[fallback_rows].duplicated(subset=["ticker", "original_assigned_event_date"], keep=False)
    if duplicated_fallback.any():
        duplicates = reviews.loc[fallback_rows & duplicated_fallback, ["ticker", "original_assigned_event_date"]].drop_duplicates().to_dict("records")
        raise ValueError(f"Duplicate review rows found for fallback event keys: {duplicates}")

    return reviews.loc[:, ["ticker", "event_review_id", "original_assigned_event_date", "reviewed_event_date", "review_status", "review_note"]].copy()


def _apply_event_date_reviews(
    events: list[ESPPEvent],
    audit_frame: pd.DataFrame,
    reviews: pd.DataFrame,
) -> tuple[list[ESPPEvent], pd.DataFrame]:
    audited = audit_frame.copy()
    if audited.empty:
        audited = pd.DataFrame(
            columns=[
                "ticker",
                "filing_type",
                "filing_date",
                "source_fixture_path",
                "source_id",
                "source_snippet",
                "candidate_month_day",
                "assigned_event_date",
                "derivation_rule",
                "confidence",
                "fallback_anchor_used",
                "event_review_id",
            ]
        )

    audited["review_status"] = "unreviewed"
    audited["reviewed_event_date"] = None
    audited["review_note"] = None
    audited["effective_event_date"] = audited.get("assigned_event_date")
    audited["included_in_event_study"] = True

    if not reviews.empty and not audited.empty:
        reviewed = audited.copy()
        id_reviews = reviews[reviews["event_review_id"] != ""].copy()
        if not id_reviews.empty:
            reviewed = reviewed.merge(
                id_reviews,
                how="left",
                on="event_review_id",
                suffixes=("", "_review"),
            )
        else:
            reviewed["original_assigned_event_date"] = None
            reviewed["reviewed_event_date_review"] = None
            reviewed["review_status_review"] = None
            reviewed["review_note_review"] = None

        unmatched = reviewed["review_status_review"].isna()
        fallback_reviews = reviews[reviews["event_review_id"] == ""].copy()
        if unmatched.any() and not fallback_reviews.empty:
            fallback_matched = reviewed.loc[unmatched].merge(
                fallback_reviews,
                how="left",
                left_on=["ticker", "assigned_event_date"],
                right_on=["ticker", "original_assigned_event_date"],
                suffixes=("", "_fallback"),
            )
            fallback_column_map = {
                "original_assigned_event_date": "original_assigned_event_date",
                "reviewed_event_date_review": "reviewed_event_date_fallback",
                "review_status_review": "review_status_fallback",
                "review_note_review": "review_note_fallback",
            }
            for target_column, source_column in fallback_column_map.items():
                if source_column in fallback_matched.columns:
                    reviewed.loc[unmatched, target_column] = fallback_matched[source_column].values

        matched = reviewed["review_status_review"].notna()
        reviewed.loc[matched, "review_status"] = reviewed.loc[matched, "review_status_review"]
        reviewed.loc[matched, "reviewed_event_date"] = reviewed.loc[matched, "reviewed_event_date_review"].replace("", None)
        reviewed.loc[matched, "review_note"] = reviewed.loc[matched, "review_note_review"].replace("", None)
        corrected = reviewed["review_status"] == "corrected"
        rejected = reviewed["review_status"] == "rejected"
        reviewed.loc[corrected, "effective_event_date"] = reviewed.loc[corrected, "reviewed_event_date"]
        reviewed.loc[rejected, "effective_event_date"] = None
        reviewed.loc[rejected, "included_in_event_study"] = False
        audited = reviewed.drop(columns=["original_assigned_event_date", "reviewed_event_date_review", "review_status_review", "review_note_review"])

    event_lookup: dict[tuple[str, str], ESPPEvent] = {}
    for event in events:
        event_date_key = event.event_date.isoformat()
        fallback_key = f"{event.ticker}|{event_date_key}"
        event_lookup[(fallback_key, event_date_key)] = event
        if event.event_review_id:
            event_lookup[(event.event_review_id, event_date_key)] = event
    reviewed_events: list[ESPPEvent] = []
    for row in audited.itertuples(index=False):
        if not bool(row.included_in_event_study):
            continue
        event_date_key = row.assigned_event_date
        lookup_candidates = [
            (f"{row.ticker}|{event_date_key}", event_date_key),
        ]
        if getattr(row, "event_review_id", None):
            lookup_candidates.insert(0, (row.event_review_id, event_date_key))

        original_event = None
        for original_key in lookup_candidates:
            original_event = event_lookup.get(original_key)
            if original_event is not None:
                break
        if original_event is None:
            continue
        effective_event_date = row.effective_event_date or row.assigned_event_date
        reviewed_events.append(replace(original_event, event_date=_parse_date(effective_event_date, "effective_event_date")))

    audited["reviewed_event_date"] = audited["reviewed_event_date"].where(pd.notna(audited["reviewed_event_date"]), None)
    audited["review_note"] = audited["review_note"].where(pd.notna(audited["review_note"]), None)
    audited["effective_event_date"] = audited["effective_event_date"].where(pd.notna(audited["effective_event_date"]), None)
    audited = audited.sort_values(["ticker", "assigned_event_date", "candidate_month_day", "source_id"], ignore_index=True)
    return reviewed_events, audited


def _ticker_meta_frame(config: ExperimentConfig, panel: pd.DataFrame) -> pd.DataFrame:
    vol = (
        panel.groupby("ticker", as_index=False)["raw_ret"]
        .std(ddof=1)
        .rename(columns={"raw_ret": "daily_volatility"})
        .fillna({"daily_volatility": 0.0})
    )
    meta = pd.DataFrame([{"ticker": t.ticker, "market_cap": t.market_cap, "employees": t.employees} for t in config.tickers])
    merged = meta.merge(vol, on="ticker", how="left").fillna({"daily_volatility": 0.0})
    return assign_cross_sectional_groups(merged, config.cross_section)


def _persist_strategy_outputs(output_dir: Path, artifacts: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts.event_level.to_csv(output_dir / "strategy_event_level.csv", index=False)
    artifacts.group_summary.to_csv(output_dir / "strategy_group_summary.csv", index=False)
    artifacts.overall_summary.to_csv(output_dir / "strategy_overall_summary.csv", index=False)


def _horizon_returns(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for (ticker, event_id), event_slice in panel.groupby(["ticker", "event_id"]):
        horizon_window = event_slice[event_slice["tau"].between(1, horizon)]["raw_ret"].astype(float)
        if len(horizon_window) < horizon:
            continue
        rows.append(
            {
                "ticker": str(ticker),
                "event_id": float(event_id),
                "horizon": float(horizon),
                "return": float((1.0 + horizon_window).prod() - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _distribution_summary(distribution: pd.DataFrame) -> pd.DataFrame:
    if distribution.empty:
        return pd.DataFrame()

    grouped = distribution.groupby("horizon", as_index=False)
    return grouped["return"].agg(
        n_events="count",
        mean="mean",
        median="median",
        std=lambda x: x.std(ddof=1),
        hit_rate_positive=lambda x: (x > 0.0).mean(),
    )


def _histogram_table(values: pd.Series, bins: int = 10) -> pd.DataFrame:
    clean = values.astype(float).dropna()
    if clean.empty:
        return pd.DataFrame()
    counts, edges = np.histogram(clean, bins=bins)
    rows = []
    for idx, count in enumerate(counts):
        rows.append(
            {
                "bin": f"[{edges[idx]:+.2%}, {edges[idx + 1]:+.2%})",
                "count": int(count),
            }
        )
    return pd.DataFrame(rows)


def _format_summary_for_display(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return summary
    formatted = summary.copy()
    formatted["horizon"] = formatted["horizon"].astype(int).map(lambda h: f"t+{h}")
    formatted["mean"] = formatted["mean"].map(lambda x: f"{x:+.2%}")
    formatted["median"] = formatted["median"].map(lambda x: f"{x:+.2%}")
    formatted["std"] = formatted["std"].fillna(0.0).map(lambda x: f"{x:.2%}")
    formatted["hit_rate_positive"] = formatted["hit_rate_positive"].map(lambda x: f"{x:.1%}")
    return formatted


def _diagnostic_conclusion(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "no detectable pattern"

    means = summary["mean"].astype(float)
    hit_rates = summary["hit_rate_positive"].astype(float)
    strong_sell_pressure = bool((means < -0.003).all() and (hit_rates < 0.45).all())
    no_pattern = bool((means.abs() < 0.001).all() and hit_rates.between(0.45, 0.55).all())

    if strong_sell_pressure:
        return "evidence of sell pressure"
    if no_pattern:
        return "no detectable pattern"
    return "mixed results"


def _run_diagnostic_report(panel: pd.DataFrame, output_dir: Path) -> None:
    horizons = [1, 3, 5]
    all_dist = pd.concat([_horizon_returns(panel, h) for h in horizons], ignore_index=True)
    all_summary = _distribution_summary(all_dist)

    output_dir.mkdir(parents=True, exist_ok=True)
    all_dist.to_csv(output_dir / "diagnostic_returns_distribution.csv", index=False)
    all_summary.to_csv(output_dir / "diagnostic_summary_overall.csv", index=False)
    ticker_summary = (
        all_dist.groupby(["ticker", "horizon"], as_index=False)["return"]
        .agg(
            n_events="count",
            mean="mean",
            median="median",
            std=lambda x: x.std(ddof=1),
            hit_rate_positive=lambda x: (x > 0.0).mean(),
        )
        .sort_values(["ticker", "horizon"], ignore_index=True)
    )
    ticker_summary.to_csv(output_dir / "diagnostic_summary_by_ticker.csv", index=False)

    print("\n=== Event Study Diagnostics ===")
    if all_summary.empty:
        print("No event returns available for diagnostic summary.")
        return

    horizon_indexed = all_summary.set_index("horizon")
    avg_t1 = float(horizon_indexed.loc[1.0, "mean"]) if 1.0 in horizon_indexed.index else float("nan")
    avg_t3 = float(horizon_indexed.loc[3.0, "mean"]) if 3.0 in horizon_indexed.index else float("nan")
    avg_t5 = float(horizon_indexed.loc[5.0, "mean"]) if 5.0 in horizon_indexed.index else float("nan")

    hit_t1 = float(horizon_indexed.loc[1.0, "hit_rate_positive"]) if 1.0 in horizon_indexed.index else float("nan")
    hit_t3 = float(horizon_indexed.loc[3.0, "hit_rate_positive"]) if 3.0 in horizon_indexed.index else float("nan")
    hit_t5 = float(horizon_indexed.loc[5.0, "hit_rate_positive"]) if 5.0 in horizon_indexed.index else float("nan")

    event_count = int(all_dist.loc[all_dist["horizon"] == 1.0, "event_id"].nunique())

    print("Average returns:")
    print(f"  t+1: {avg_t1:+.2%}")
    print(f"  t+3: {avg_t3:+.2%}")
    print(f"  t+5: {avg_t5:+.2%}")

    print("\nHit rate (% positive returns):")
    print(f"  t+1: {hit_t1:.1%}")
    print(f"  t+3: {hit_t3:.1%}")
    print(f"  t+5: {hit_t5:.1%}")

    print(f"\nEvents used: {event_count}")

    by_ticker = (
        all_dist.groupby(["ticker", "horizon"], as_index=False)["return"]
        .agg(
            n_events="count",
            mean="mean",
            median="median",
            std=lambda x: x.std(ddof=1),
            hit_rate_positive=lambda x: (x > 0.0).mean(),
        )
        .sort_values(["ticker", "horizon"], ignore_index=True)
    )
    t1_by_ticker = by_ticker[by_ticker["horizon"] == 1.0][["ticker", "mean"]].copy()
    t1_by_ticker["mean"] = t1_by_ticker["mean"].map(lambda x: f"{x:+.2%}")
    t1_by_ticker = t1_by_ticker.rename(columns={"mean": "avg_t+1_return"})

    print("\nPer-ticker average return at t+1:")
    if t1_by_ticker.empty:
        print("  no data")
    else:
        print(t1_by_ticker.to_string(index=False))

    conclusion = _diagnostic_conclusion(all_summary)
    print(f"\nConclusion: {conclusion}")


def run_first_pass_event_study(config_path: Path) -> None:
    _configure_logging()
    config = _load_config(config_path)
    reviews = _load_event_date_reviews(config.review_file)
    LOGGER.info(
        "Running ESPP strategy experiment for %s from %s to %s",
        ", ".join(t.ticker for t in config.tickers),
        config.start_date.isoformat(),
        config.end_date.isoformat(),
    )

    loader = _build_price_data_provider(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_prices = loader.load_daily_ohlcv(config.benchmark, config.start_date, config.end_date)
    persist_prices(benchmark_prices, config.output_dir / "benchmark_prices.csv")

    all_event_rows: list[pd.DataFrame] = []
    audit_frames: list[pd.DataFrame] = []
    for ticker_cfg in config.tickers:
        ticker = ticker_cfg.ticker
        LOGGER.info("[%s] loading prices", ticker)
        try:
            prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
        except ValueError as exc:
            LOGGER.warning("[%s] skipping, unable to load prices: %s", ticker, exc)
            continue
        persist_prices(prices, config.output_dir / f"{ticker}_prices.csv")

        docs = _load_filings_for_ticker(config, ticker)
        hints = parse_many_espp_hints(docs)
        events, audit_frame = estimate_event_dates_with_audit(ticker, hints, config.start_date.year, config.end_date.year)
        events, audit_frame = _apply_event_date_reviews(events, audit_frame, reviews[reviews["ticker"] == ticker].copy())
        audit_frames.append(audit_frame)

        result = run_event_study(
            price_frame=prices,
            benchmark_frame=benchmark_prices,
            events=events,
            config=EventStudyConfig(
                window_before=config.event_study.window_before,
                window_after=config.event_study.window_after,
                volume_lookback=config.event_study.volume_lookback,
                label=ticker,
            ),
        )
        if result.panel.empty:
            continue
        ticker_panel = result.panel.copy()
        ticker_panel["ticker"] = ticker
        all_event_rows.append(ticker_panel)

    _persist_date_audit(config.output_dir, audit_frames)

    all_events = pd.concat(all_event_rows, ignore_index=True) if all_event_rows else pd.DataFrame()
    audit_for_summary = pd.concat(audit_frames, ignore_index=True) if audit_frames else pd.DataFrame()
    report_path = write_research_summary_report(config.output_dir, audit_for_summary, all_events)
    LOGGER.info("Wrote descriptive research summary to %s", report_path)

    if not all_event_rows:
        LOGGER.warning("No event windows generated across universe.")
        return

    all_events.to_csv(config.output_dir / "all_event_windows.csv", index=False)
    _run_diagnostic_report(all_events, config.output_dir)

    filtered_events = filter_event_panel(all_events, config.strategy)
    filtered_events.to_csv(config.output_dir / "filtered_event_windows.csv", index=False)

    ticker_groups = _ticker_meta_frame(config, all_events)
    ticker_groups.to_csv(config.output_dir / "ticker_cross_section.csv", index=False)

    strategy_artifacts = simulate_strategy(filtered_events, ticker_groups, config.strategy)
    _persist_strategy_outputs(config.output_dir, strategy_artifacts)

    if strategy_artifacts.overall_summary.empty:
        print("No tradable events after filters.")
        return

    print("\n=== Strategy Hypothesis Testing Summary ===")
    print(strategy_artifacts.overall_summary.to_string(index=False))
    print("\n=== Cross-Section Group Summary ===")
    print(strategy_artifacts.group_summary.to_string(index=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ESPP strategy hypothesis testing experiment")
    parser.add_argument("--config", type=Path, default=Path("config/example.yaml"), help="Path to YAML experiment config")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_first_pass_event_study(config_path=args.config)
