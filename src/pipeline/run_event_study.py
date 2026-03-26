from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.analysis.event_study import EventStudyConfig, run_event_study
from src.analysis.strategy import (
    CrossSectionConfig,
    StrategyConfig,
    assign_cross_sectional_groups,
    filter_event_panel,
    simulate_strategy,
)
from src.data.price_loader import YFinancePriceLoader, persist_prices
from src.data.sec_parser import FilingDocument, parse_many_espp_hints
from src.events.espp_event_extractor import estimate_event_dates

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
            )
        )
    return filings


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value!r}. Expected YYYY-MM-DD") from exc


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


def run_first_pass_event_study(config_path: Path) -> None:
    _configure_logging()
    config = _load_config(config_path)
    LOGGER.info(
        "Running ESPP strategy experiment for %s from %s to %s",
        ", ".join(t.ticker for t in config.tickers),
        config.start_date.isoformat(),
        config.end_date.isoformat(),
    )

    loader = YFinancePriceLoader()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_prices = loader.load_daily_ohlcv(config.benchmark, config.start_date, config.end_date)
    persist_prices(benchmark_prices, config.output_dir / "benchmark_prices.csv")

    all_event_rows: list[pd.DataFrame] = []
    for ticker_cfg in config.tickers:
        ticker = ticker_cfg.ticker
        LOGGER.info("[%s] loading prices", ticker)
        try:
            prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
        except ValueError as exc:
            LOGGER.warning("[%s] skipping, unable to load prices: %s", ticker, exc)
            continue
        persist_prices(prices, config.output_dir / f"{ticker}_prices.csv")

        docs = _mock_filings(ticker, config.start_date.year, config.end_date.year)
        hints = parse_many_espp_hints(docs)
        events = estimate_event_dates(ticker, hints, config.start_date.year, config.end_date.year)

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

    if not all_event_rows:
        LOGGER.warning("No event windows generated across universe.")
        return

    all_events = pd.concat(all_event_rows, ignore_index=True)
    all_events.to_csv(config.output_dir / "all_event_windows.csv", index=False)

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
