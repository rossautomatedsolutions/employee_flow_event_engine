from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.analysis.event_study import EventStudyConfig, run_event_study
from src.data.price_loader import YFinancePriceLoader, persist_prices
from src.data.sec_parser import FilingDocument, parse_many_espp_hints
from src.events.espp_event_extractor import estimate_event_dates

LOGGER = logging.getLogger("pipeline.event_study")
DEFAULT_UNIVERSE = ["AAPL", "MSFT", "AMZN", "CRM", "NVDA"]


@dataclass(slots=True)
class ExperimentConfig:
    tickers: list[str]
    benchmark: str
    start_date: date
    end_date: date
    output_dir: Path


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


def _build_config(years: int, output_dir: Path, benchmark: str) -> ExperimentConfig:
    bounded_years = max(2, min(5, years))
    end_date = date.today()
    start_date = end_date - timedelta(days=bounded_years * 365)
    return ExperimentConfig(
        tickers=DEFAULT_UNIVERSE,
        benchmark=benchmark,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
    )


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


def _summarize_metrics(all_events: pd.DataFrame) -> pd.DataFrame:
    horizons = [1, 3, 5]
    rows: list[dict[str, float]] = []

    for horizon in horizons:
        per_event = (
            all_events[all_events["tau"].between(1, horizon)]
            .groupby(["ticker", "event_id"], as_index=False)
            .agg(
                horizon_return=("raw_ret", "sum"),
                horizon_abnormal_return=("abnormal_ret", "sum"),
                avg_volume_ratio=("vol_ratio", "mean"),
            )
        )
        if per_event.empty:
            continue

        rows.append(
            {
                "horizon": float(horizon),
                "avg_return": float(per_event["horizon_return"].mean()),
                "avg_abnormal_return": float(per_event["horizon_abnormal_return"].mean()),
                "volume_spike_indicator": float((per_event["avg_volume_ratio"] > 1.25).mean()),
                "n_events": float(len(per_event)),
            }
        )

    return pd.DataFrame(rows)


def _interpret_signal(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "Insufficient event coverage: no detectable signal yet."

    horizon_values = {int(row["horizon"]): row for _, row in summary.iterrows()}
    h1 = horizon_values.get(1)
    h3 = horizon_values.get(3)
    h5 = horizon_values.get(5)
    if h1 is None or h3 is None or h5 is None:
        return "Incomplete horizon coverage: first-pass signal is inconclusive."

    sell_pressure = h1["avg_return"] < 0 and h3["avg_return"] <= 0
    rebound = h1["avg_return"] < 0 and h5["avg_return"] > h1["avg_return"]

    return (
        f"Sell pressure evidence: {'YES' if sell_pressure else 'NO'} | "
        f"Rebound evidence: {'YES' if rebound else 'NO'} | "
        "Interpret with caution (heuristic event dates, first-pass sample)."
    )


def run_first_pass_event_study(years: int, output_dir: Path, benchmark: str) -> None:
    _configure_logging()
    config = _build_config(years=years, output_dir=output_dir, benchmark=benchmark)
    LOGGER.info(
        "Running ESPP first-pass study for %s from %s to %s",
        ", ".join(config.tickers),
        config.start_date.isoformat(),
        config.end_date.isoformat(),
    )

    loader = YFinancePriceLoader()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        benchmark_prices = loader.load_daily_ohlcv(config.benchmark, config.start_date, config.end_date)
    except ValueError as exc:
        LOGGER.error("Unable to load benchmark %s: %s", config.benchmark, exc)
        return
    persist_prices(benchmark_prices, config.output_dir / "benchmark_prices.csv")

    all_event_rows: list[pd.DataFrame] = []

    for ticker in config.tickers:
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
            config=EventStudyConfig(window_before=10, window_after=10, label=ticker),
        )

        if result.panel.empty:
            LOGGER.warning("[%s] no usable event windows", ticker)
            continue

        ticker_panel = result.panel.copy()
        ticker_panel["ticker"] = ticker
        all_event_rows.append(ticker_panel)
        LOGGER.info("[%s] events used: %s", ticker, int(ticker_panel["event_id"].nunique()))

    if not all_event_rows:
        LOGGER.warning("No event windows generated across universe.")
        return

    all_events = pd.concat(all_event_rows, ignore_index=True)
    all_events.to_csv(config.output_dir / "all_event_windows.csv", index=False)

    summary = _summarize_metrics(all_events)
    summary.to_csv(config.output_dir / "summary_report.csv", index=False)

    interpretation = _interpret_signal(summary)
    print("\n=== ESPP First-Pass Summary ===")
    print(summary.to_string(index=False))
    print("\nInterpretation:")
    print(interpretation)
    print("\nFirst-pass answer: Is there any detectable signal?")
    print("- " + interpretation)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run first-pass ESPP event study experiment")
    parser.add_argument("--years", type=int, default=5, help="Price history length in years (bounded to 2..5)")
    parser.add_argument("--benchmark", type=str, default="SPY", help="Benchmark ticker for abnormal returns")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/first_pass"), help="Output directory")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_first_pass_event_study(years=args.years, output_dir=args.output_dir, benchmark=args.benchmark)
