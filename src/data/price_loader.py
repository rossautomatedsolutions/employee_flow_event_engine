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
class TradingFoundationPriceLoader:
    """Loader for canonical Trading Foundation daily EOD files."""

    historical_data_root: Path
    _dataset_cache: dict[str, pd.DataFrame] = field(default_factory=dict, init=False, repr=False)

    def _resolved_root(self) -> Path:
        if self.historical_data_root.name.lower() == "historical_data":
            return self.historical_data_root
        nested = self.historical_data_root / "historical_data"
        return nested if nested.exists() else self.historical_data_root

    def _symbol_path(self, ticker: str) -> Path:
        symbol = ticker.strip().upper()
        return self._resolved_root() / symbol / "eod" / f"{symbol}_1D.csv"

    def _parse_timestamps(self, timestamps: pd.Series, csv_path: Path) -> pd.Series:
        parsed = pd.to_datetime(
            timestamps,
            errors="coerce",
            utc=True,
            format="ISO8601",
        )
        invalid_timestamps = parsed.isna()
        if invalid_timestamps.any():
            bad_rows = sorted(set(parsed.index[invalid_timestamps].tolist()))
            raise ValueError(
                "Trading Foundation EOD data has invalid timestamp values at rows "
                f"{bad_rows[:5]} in {csv_path}"
            )
        return parsed

    def _load_symbol_dataset(self, ticker: str) -> pd.DataFrame:
        symbol = ticker.strip().upper()
        cached = self._dataset_cache.get(symbol)
        if cached is not None:
            return cached

        csv_path = self._symbol_path(symbol)
        if not csv_path.exists():
            raise ValueError(
                "Trading Foundation EOD file not found for "
                f"{symbol!r}: expected {csv_path}"
            )

        try:
            frame = pd.read_csv(csv_path)
        except Exception as exc:
            raise ValueError(f"Unable to read Trading Foundation EOD data from {csv_path}: {exc}") from exc

        frame = frame.rename(columns=lambda value: str(value).strip().lower().replace(" ", "_"))
        required = {"t", "open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(
                f"Trading Foundation EOD data missing required columns {missing} in {csv_path}"
            )

        frame["t"] = self._parse_timestamps(frame["t"], csv_path)
        frame["date"] = frame["t"].dt.tz_localize(None).dt.normalize()
        duplicate_dates = frame["date"].duplicated(keep=False)
        if duplicate_dates.any():
            duplicate_values = (
                frame.loc[duplicate_dates, "date"]
                .dt.strftime("%Y-%m-%d")
                .drop_duplicates()
                .tolist()
            )
            raise ValueError(
                "Trading Foundation EOD data has duplicate daily rows for "
                f"{symbol!r} on {duplicate_values[:5]} in {csv_path}"
            )

        ordered = frame.sort_values("date", ignore_index=True).copy()
        self._dataset_cache[symbol] = ordered
        return ordered

    def load_daily_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        dataset = self._load_symbol_dataset(ticker)
        symbol = ticker.strip().upper()

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        in_range = dataset["date"].between(start_ts, end_ts)
        frame = dataset.loc[in_range, ["date", "open", "high", "low", "close", "volume"]].copy()
        if frame.empty:
            available_start = dataset["date"].min().date()
            available_end = dataset["date"].max().date()
            raise ValueError(
                f"Trading Foundation EOD data missing rows for ticker {symbol!r} in {start}..{end}; "
                f"available range is {available_start}..{available_end} from {self._symbol_path(symbol)}"
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
    if normalized in {"trading_foundation", "trading-foundation", "tf"}:
        if price_data_path is None:
            raise ValueError(
                "price_data_path is required when price_source is 'trading_foundation' "
                "(point it at the Trading_Foundation historical_data root or repo root)"
            )
        return TradingFoundationPriceLoader(price_data_path)
    if normalized in {"yfinance", "yf"}:
        return YFinancePriceLoader()
    raise ValueError(f"Unsupported price_source: {price_source!r}")


def persist_prices(frame: pd.DataFrame, out_path: Path) -> None:
    """Persist prices as deterministic CSV (sorted index + fixed float format)."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = frame.sort_index().copy()
    ordered.to_csv(out_path, float_format="%.8f", index_label="date")
