from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from src.analysis.event_study import EventStudyConfig, run_event_study
from src.data.price_loader import YFinancePriceLoader, persist_prices
from src.data.sec_parser import FilingDocument, parse_many_espp_hints
from src.events.espp_event_extractor import estimate_event_dates


@dataclass(slots=True)
class PipelineConfig:
    tickers: list[str]
    benchmark: str
    start_date: date
    end_date: date
    output_dir: Path


def _load_config(path: Path) -> PipelineConfig:
    payload = yaml.safe_load(path.read_text())
    return PipelineConfig(
        tickers=payload["tickers"],
        benchmark=payload.get("benchmark", "SPY"),
        start_date=date.fromisoformat(payload["start_date"]),
        end_date=date.fromisoformat(payload["end_date"]),
        output_dir=Path(payload.get("output_dir", "artifacts")),
    )


def _mock_filings(ticker: str, start_year: int, end_year: int) -> list[FilingDocument]:
    filings = []
    for year in range(start_year, end_year + 1):
        text = (
            f"The employee stock purchase plan (ESPP) includes purchase dates around June 30 and "
            f"December 31 for calendar year {year}."
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


def _save_summary_plot(summary: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(summary["tau"], summary["aar"], marker="o", label="AAR")
    axes[0].axhline(0.0, color="black", linestyle="--", linewidth=0.8)
    axes[0].set_ylabel("Average Abnormal Return")
    axes[0].legend()

    axes[1].plot(summary["tau"], summary["caar"], marker="o", color="tab:orange", label="CAAR")
    axes[1].set_ylabel("Cumulative AAR")
    axes[1].set_xlabel("Event Time (tau)")
    axes[1].legend()

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def run_pipeline(config_path: Path) -> None:
    config = _load_config(config_path)
    loader = YFinancePriceLoader()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_prices = loader.load_daily_ohlcv(config.benchmark, config.start_date, config.end_date)
    benchmark_prices.to_csv(config.output_dir / "benchmark_prices.csv", index_label="date")

    all_summaries = []
    for ticker in config.tickers:
        prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
        persist_prices(prices, config.output_dir / f"{ticker}_prices.csv")

        docs = _mock_filings(ticker, config.start_date.year, config.end_date.year)
        hints = parse_many_espp_hints(docs)
        events = estimate_event_dates(ticker, hints, config.start_date.year, config.end_date.year)

        result = run_event_study(
            price_frame=prices,
            benchmark_frame=benchmark_prices,
            events=events,
            config=EventStudyConfig(window_before=10, window_after=10),
        )

        ticker_dir = config.output_dir / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        result.panel.to_csv(ticker_dir / "event_panel.csv", index=False)
        result.aar_summary.to_csv(ticker_dir / "aar_summary.csv", index=False)

        if not result.aar_summary.empty:
            _save_summary_plot(result.aar_summary, ticker_dir / "aar_plot.png")
            summary = result.aar_summary.copy()
            summary["ticker"] = ticker
            all_summaries.append(summary)

    if all_summaries:
        combined = pd.concat(all_summaries, ignore_index=True)
        combined.to_csv(config.output_dir / "combined_aar_summary.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ESPP event study pipeline")
    parser.add_argument("--config", default="config/example.yaml", type=Path)
    args = parser.parse_args()
    run_pipeline(args.config)
