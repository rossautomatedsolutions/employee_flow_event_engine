from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path

import yaml

from src.analysis.event_study import EventStudyConfig
from src.sec.edgar import DEFAULT_SEC_FORMS, SECFilingSourceConfig

LOCAL_DETERMINISTIC_PRICE_SOURCES = {"csv", "trading_foundation", "trading-foundation", "tf"}


@dataclass(slots=True)
class Phase3CandidateConfig:
    enabled: bool = False
    screened_only: bool = True
    diagnostic_extract_from_unscreened_filings: bool = False
    context_window_chars: int = 240
    require_review_for_validated_windows: bool = True
    generate_provisional_unreviewed_windows: bool = False
    auto_policy_review: bool = False
    review_as_of_date: date | None = None


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
    filings: SECFilingSourceConfig
    filing_fixture_dir: Path | None
    review_file: Path | None
    event_study_enabled: bool
    event_study: EventStudyConfig
    phase3: Phase3CandidateConfig


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


def _as_string_tuple(raw: object, field: str, default: tuple[str, ...]) -> tuple[str, ...]:
    values = _as_string_list(raw, field)
    if values is None:
        return default
    return tuple(values)


def load_batch_config(config_path: Path) -> BatchRunConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    event_cfg = raw.get("event_study", {})
    filings_cfg = raw.get("filings", {})
    phase3_cfg = raw.get("phase3", {})
    sec_user_agent = str(filings_cfg.get("sec_user_agent") or os.environ.get("SEC_EDGAR_USER_AGENT", "")).strip() or None
    filing_source = str(filings_cfg.get("source", "fixture")).strip().lower()
    filings = SECFilingSourceConfig(
        source=filing_source,
        fixture_dir=Path(filings_cfg["fixture_dir"]) if filings_cfg.get("fixture_dir") else None,
        sec_user_agent=sec_user_agent,
        forms=_as_string_tuple(filings_cfg.get("forms"), "filings.forms", DEFAULT_SEC_FORMS),
        filing_start_date=_parse_date(filings_cfg["filing_start_date"], "filings.filing_start_date") if filings_cfg.get("filing_start_date") else None,
        filing_end_date=_parse_date(filings_cfg["filing_end_date"], "filings.filing_end_date") if filings_cfg.get("filing_end_date") else None,
        max_filings_per_issuer=int(filings_cfg.get("max_filings_per_issuer", 6)),
        cache_only=bool(filings_cfg.get("cache_only", False)),
        request_delay_seconds=float(filings_cfg.get("request_delay_seconds", 0.2)),
        max_retries=int(filings_cfg.get("max_retries", 3)),
        timeout_seconds=float(filings_cfg.get("timeout_seconds", 30.0)),
    )
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
        filings=filings,
        filing_fixture_dir=filings.fixture_dir,
        review_file=Path(raw["reviews"]["review_file"]) if raw.get("reviews", {}).get("review_file") else None,
        event_study_enabled=bool(event_cfg.get("enabled", True)),
        event_study=EventStudyConfig(
            window_before=int(event_cfg.get("window_before", 10)),
            window_after=int(event_cfg.get("window_after", 10)),
            volume_lookback=int(event_cfg.get("volume_lookback", 20)),
            label="phase2_batch",
        ),
        phase3=Phase3CandidateConfig(
            enabled=bool(phase3_cfg.get("enabled", False)),
            screened_only=bool(phase3_cfg.get("screened_only", True)),
            diagnostic_extract_from_unscreened_filings=bool(phase3_cfg.get("diagnostic_extract_from_unscreened_filings", False)),
            context_window_chars=int(phase3_cfg.get("context_window_chars", 240)),
            require_review_for_validated_windows=bool(phase3_cfg.get("require_review_for_validated_windows", True)),
            generate_provisional_unreviewed_windows=bool(phase3_cfg.get("generate_provisional_unreviewed_windows", False)),
            auto_policy_review=bool(phase3_cfg.get("auto_policy_review", False)),
            review_as_of_date=(
                _parse_date(phase3_cfg["review_as_of_date"], "phase3.review_as_of_date")
                if phase3_cfg.get("review_as_of_date")
                else None
            ),
        ),
    )
    if config.end_date < config.start_date:
        raise ValueError("end_date must be on or after start_date")
    if config.max_companies is not None and config.max_companies <= 0:
        raise ValueError("max_companies must be positive when provided")
    if config.offline_mode and config.price_source.strip().lower() not in LOCAL_DETERMINISTIC_PRICE_SOURCES:
        raise ValueError(
            "offline_mode requires a local deterministic price_source such as "
            "'csv' or 'trading_foundation'"
        )
    if config.filings.source not in {"fixture", "sec"}:
        raise ValueError("filings.source must be either 'fixture' or 'sec'")
    if config.filings.source == "fixture" and config.filing_fixture_dir is None:
        raise ValueError("filings.fixture_dir is required when filings.source is 'fixture'")
    if config.filings.filing_start_date and config.filings.filing_end_date:
        if config.filings.filing_end_date < config.filings.filing_start_date:
            raise ValueError("filings.filing_end_date must be on or after filings.filing_start_date")
    if config.filings.max_filings_per_issuer <= 0:
        raise ValueError("filings.max_filings_per_issuer must be positive")
    if config.filings.max_retries < 0:
        raise ValueError("filings.max_retries must be zero or positive")
    if config.filings.timeout_seconds <= 0:
        raise ValueError("filings.timeout_seconds must be positive")
    if config.filings.source == "sec":
        if not config.filings.cache_only and not config.filings.sec_user_agent:
            raise ValueError("filings.sec_user_agent or SEC_EDGAR_USER_AGENT is required when filings.source is 'sec'")
        if not config.filings.cache_only and config.filings.request_delay_seconds < 0.1:
            raise ValueError("filings.request_delay_seconds must be at least 0.1 seconds for live SEC requests")
    if config.phase3.context_window_chars <= 0:
        raise ValueError("phase3.context_window_chars must be positive")
    if not config.phase3.screened_only:
        raise ValueError("phase3.screened_only must remain true in this bounded research increment")
    if config.phase3.diagnostic_extract_from_unscreened_filings and not config.phase3.enabled:
        raise ValueError("phase3.enabled must be true when diagnostic extraction override is enabled")
    if config.phase3.generate_provisional_unreviewed_windows and not config.phase3.enabled:
        raise ValueError("phase3.enabled must be true when provisional diagnostic windows are enabled")
    if config.phase3.generate_provisional_unreviewed_windows and not config.event_study_enabled:
        raise ValueError("event_study.enabled must be true when provisional diagnostic windows are enabled")
    if config.phase3.auto_policy_review and not config.phase3.enabled:
        raise ValueError("phase3.enabled must be true when policy auto review is enabled")
    return config
