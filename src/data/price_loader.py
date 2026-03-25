from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import pandas as pd


class PriceDataProvider(Protocol):
    """Interface for pluggable market data providers."""

    def load_daily_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Return business-day indexed OHLCV data between [start, end]."""


@dataclass(slots=True)
class YFinancePriceLoader:
    """Yahoo Finance based implementation used as initial provider."""

    auto_adjust: bool = True

    def load_daily_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf

        history = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=self.auto_adjust,
            progress=False,
            interval="1d",
            actions=False,
            threads=False,
        )
        if history.empty:
            raise ValueError(f"No price data returned for {ticker} in {start}..{end}")

        frame = history.rename(columns=str.lower)
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        expected = ["open", "high", "low", "close", "volume"]
        missing = [column for column in expected if column not in frame.columns]
        if missing:
            raise ValueError(f"Price provider missing required columns: {missing}")
        return frame[expected].sort_index()


def persist_prices(frame: pd.DataFrame, out_path: Path) -> None:
    """Persist prices as deterministic CSV (sorted index + fixed float format)."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = frame.sort_index().copy()
    ordered.to_csv(out_path, float_format="%.8f", index_label="date")
