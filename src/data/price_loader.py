from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import pandas as pd


class PriceDataProvider(Protocol):
    """Interface for pluggable market data providers."""

    def load_daily_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Return business-day indexed OHLCV data between [start, end]."""


@dataclass(slots=True)
class CSVPriceLoader:
    """Deterministic CSV-backed implementation for offline research replays."""

    csv_path: Path
    _dataset: pd.DataFrame | None = field(default=None, init=False, repr=False)

    def _load_dataset(self) -> pd.DataFrame:
        if self._dataset is not None:
            return self._dataset
        if not self.csv_path.exists():
            raise ValueError(f"CSV price data file not found: {self.csv_path}")

        try:
            frame = pd.read_csv(self.csv_path)
        except Exception as exc:
            raise ValueError(f"Unable to read CSV price data from {self.csv_path}: {exc}") from exc

        frame = frame.rename(columns=lambda value: str(value).strip().lower().replace(" ", "_"))
        required = {"ticker", "date", "open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"CSV price data missing required columns {missing} in {self.csv_path}")

        frame["ticker"] = frame["ticker"].astype(str).str.strip()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.tz_localize(None)
        invalid_dates = frame["date"].isna()
        if invalid_dates.any():
            bad_rows = sorted(set(frame.index[invalid_dates].tolist()))
            raise ValueError(f"CSV price data has invalid date values at rows {bad_rows[:5]} in {self.csv_path}")

        ordered = frame.sort_values(["ticker", "date"], ignore_index=True).copy()
        self._dataset = ordered
        return ordered

    def load_daily_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        dataset = self._load_dataset()
        ticker_rows = dataset[dataset["ticker"] == ticker].copy()
        if ticker_rows.empty:
            raise ValueError(f"CSV price data missing ticker {ticker!r} in {self.csv_path}")

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        in_range = ticker_rows["date"].between(start_ts, end_ts)
        frame = ticker_rows.loc[in_range, ["date", "open", "high", "low", "close", "volume"]].copy()
        if frame.empty:
            available_start = ticker_rows["date"].min().date()
            available_end = ticker_rows["date"].max().date()
            raise ValueError(
                f"CSV price data missing rows for ticker {ticker!r} in {start}..{end}; "
                f"available range is {available_start}..{available_end} from {self.csv_path}"
            )

        frame = frame.set_index("date").sort_index()
        return frame


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


def build_price_loader(price_source: str = "yfinance", price_data_path: Path | None = None) -> PriceDataProvider:
    normalized = price_source.strip().lower()
    if normalized == "csv":
        if price_data_path is None:
            raise ValueError("price_data_path is required when price_source is 'csv'")
        return CSVPriceLoader(price_data_path)
    if normalized in {"yfinance", "yf"}:
        return YFinancePriceLoader()
    raise ValueError(f"Unsupported price_source: {price_source!r}")


def persist_prices(frame: pd.DataFrame, out_path: Path) -> None:
    """Persist prices as deterministic CSV (sorted index + fixed float format)."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = frame.sort_index().copy()
    ordered.to_csv(out_path, float_format="%.8f", index_label="date")
