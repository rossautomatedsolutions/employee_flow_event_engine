from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from src.analysis.event_study import EventStudyConfig


@dataclass(slots=True)
class BatchRunConfig:
    benchmark: str
    universe_file: Path
    ticker_subset: list[str] | None
    sector_subset: list[str] | None
    start_date: date
    end_date: date
    output_dir: Path
    cache_dir: Path
    resume_mode: bool
    offline_mode: bool
    max_companies: int | None
    price_source: str
    price_data_path: Path | None
    filing_fixture_dir: Path | None
    review_file: Path | None
    event_study: EventStudyConfig


def _parse_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value!r}. Expected YYYY-MM-DD") from exc


def _as_string_list(raw: object, field: str) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list of strings when provided")
    values = [str(item).strip() for item in raw if str(item).strip()]
    return values or None


def load_batch_config(config_path: Path) -> BatchRunConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    event_cfg = raw.get("event_study", {})
    config = BatchRunConfig(
        benchmark=str(raw["benchmark"]).strip(),
        universe_file=Path(raw["universe_file"]),
        ticker_subset=_as_string_list(raw.get("ticker_subset"), "ticker_subset"),
        sector_subset=_as_string_list(raw.get("sector_subset"), "sector_subset"),
        start_date=_parse_date(raw["start_date"], "start_date"),
        end_date=_parse_date(raw["end_date"], "end_date"),
        output_dir=Path(raw.get("output_dir", "artifacts/phase2_batch")),
        cache_dir=Path(raw.get("cache_dir", "artifacts/cache")),
        resume_mode=bool(raw.get("resume_mode", False)),
        offline_mode=bool(raw.get("offline_mode", False)),
        max_companies=int(raw["max_companies"]) if raw.get("max_companies") is not None else None,
        price_source=str(raw.get("price_source", "yfinance")).strip(),
        price_data_path=Path(raw["price_data_path"]) if raw.get("price_data_path") else None,
        filing_fixture_dir=Path(raw["filings"]["fixture_dir"]) if raw.get("filings", {}).get("fixture_dir") else None,
        review_file=Path(raw["reviews"]["review_file"]) if raw.get("reviews", {}).get("review_file") else None,
        event_study=EventStudyConfig(
            window_before=int(event_cfg.get("window_before", 10)),
            window_after=int(event_cfg.get("window_after", 10)),
            volume_lookback=int(event_cfg.get("volume_lookback", 20)),
            label="phase2_batch",
        ),
    )
    if config.end_date < config.start_date:
        raise ValueError("end_date must be on or after start_date")
    if config.max_companies is not None and config.max_companies <= 0:
        raise ValueError("max_companies must be positive when provided")
    if config.offline_mode and config.price_source.strip().lower() != "csv":
        raise ValueError("offline_mode requires price_source: csv for deterministic runs")
    return config
