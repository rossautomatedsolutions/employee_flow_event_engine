from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from src.analysis.event_study import run_event_study
from src.analysis.phase3_candidate_quality import write_phase3_candidate_quality_reports
from src.analysis.phase2_summary import write_phase2_summary_reports
from src.data.price_loader import PriceDataProvider, build_price_loader
from src.events.espp_event_extractor import ESPPEvent, estimate_event_dates_with_audit
from src.pipeline.batch_config import BatchRunConfig, load_batch_config
from src.pipeline.company_status import (
    CompanyProcessingStatus,
    empty_status_frame,
    read_status_frame,
    status_frame_from_records,
    utc_timestamp,
    write_status_frame,
)
from src.pipeline.phase3_candidates import build_phase3_candidate_artifacts, load_phase3_candidate_reviews
from src.pipeline.run_event_study import _apply_event_date_reviews, _configure_logging, _load_event_date_reviews, _persist_date_audit
from src.sec.edgar import Phase2FilingAcquisitionResult, load_batch_filing_inputs
from src.universe.sp500_universe import (
    LoadedSP500Universe,
    load_sp500_universe,
    render_universe_validation_report_markdown,
    select_universe_companies,
)

LOGGER = logging.getLogger("pipeline.phase2_batch")
STATUS_FILE_NAME = "company_processing_status.csv"
WINDOWS_FILE_NAME = "all_event_windows.csv"
FILING_INVENTORY_FILE_NAME = "filing_inventory.csv"
FILING_SCREENING_FILE_NAME = "filing_screening_results.csv"
ACQUISITION_METRICS_FILE_NAME = "sec_acquisition_metrics.csv"
RAW_CANDIDATE_FILE_NAME = "raw_candidate_extractions.csv"
REVIEW_QUEUE_FILE_NAME = "candidate_review_queue.csv"
EXCLUDED_QUEUE_FILE_NAME = "excluded_candidate_audit.csv"
PROVISIONAL_AUDIT_FILE_NAME = "provisional_diagnostic_candidate_audit.csv"
PROVISIONAL_WINDOWS_FILE_NAME = "provisional_diagnostic_event_windows.csv"
SUCCESSFUL_RESUME_STATUSES = {
    "completed",
    "completed_no_espp",
    "completed_no_usable_events",
    "completed_pending_review",
    "warning",
}


@dataclass(slots=True)
class CompanyRunArtifacts:
    status: CompanyProcessingStatus
    audit_frame: pd.DataFrame
    panel_frame: pd.DataFrame
    inventory_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    screening_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    acquisition_metrics_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_candidate_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    pre_refinement_review_queue_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    review_queue_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    excluded_queue_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    provisional_audit_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    provisional_panel_frame: pd.DataFrame = field(default_factory=pd.DataFrame)


def _build_price_provider(config: BatchRunConfig) -> PriceDataProvider:
    return build_price_loader(price_source=config.price_source, price_data_path=config.price_data_path)


def _acquire_filings(config: BatchRunConfig, ticker: str, cik: str, company_name: str) -> Phase2FilingAcquisitionResult:
    return load_batch_filing_inputs(
        filing_config=config.filings,
        cache_dir=config.cache_dir,
        ticker=ticker,
        cik=cik,
        company_name=company_name,
    )


def _base_status_row(company: pd.Series, processing_status: str, error_message: str = "") -> CompanyProcessingStatus:
    return CompanyProcessingStatus(
        ticker=str(company["ticker"]),
        company_name=str(company["company_name"]),
        cik=str(company["cik"]),
        sector=str(company["gics_sector"]),
        sub_industry=str(company["gics_sub_industry"]),
        issuer_id=str(company["issuer_id"]),
        primary_ticker=str(company["primary_ticker"]),
        is_primary_share_class=bool(company["is_primary_share_class"]),
        processing_status=processing_status,
        error_message=error_message,
        processing_timestamp=utc_timestamp(),
    )


def _acquisition_status_kwargs(acquired: Phase2FilingAcquisitionResult) -> dict[str, object]:
    metrics = acquired.metrics
    return {
        "filings_discovered": int(metrics.filings_discovered),
        "filings_matching_forms": int(metrics.filings_matching_forms),
        "filings_in_date_window": int(metrics.filings_in_date_window),
        "filings_selected": int(metrics.filings_selected),
        "filings_processed": int(metrics.filings_processed),
        "configured_filing_start_date": (
            metrics.configured_filing_start_date.isoformat() if metrics.configured_filing_start_date else None
        ),
        "configured_filing_end_date": (
            metrics.configured_filing_end_date.isoformat() if metrics.configured_filing_end_date else None
        ),
        "effective_filing_start_date": (
            metrics.effective_filing_start_date.isoformat() if metrics.effective_filing_start_date else None
        ),
        "effective_filing_end_date": (
            metrics.effective_filing_end_date.isoformat() if metrics.effective_filing_end_date else None
        ),
    }


def _date_in_range(value: object, start_date: date, end_date: date) -> bool:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return False
    return start_date <= parsed <= end_date


def _filter_artifacts_to_date_range(
    events: list[ESPPEvent],
    audit_frame: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> tuple[list[ESPPEvent], pd.DataFrame]:
    filtered_events = [event for event in events if start_date <= event.event_date <= end_date]
    if audit_frame.empty:
        return filtered_events, audit_frame

    event_dates = audit_frame["effective_event_date"].where(audit_frame["effective_event_date"].notna(), audit_frame["assigned_event_date"])
    in_range = event_dates.map(lambda value: _date_in_range(value, start_date, end_date))
    return filtered_events, audit_frame.loc[in_range].reset_index(drop=True)


def _filter_events_to_date_range(events: list[ESPPEvent], start_date: date, end_date: date) -> list[ESPPEvent]:
    return [event for event in events if start_date <= event.event_date <= end_date]


def _status_counts(reviewed_audit: pd.DataFrame) -> tuple[int, int, int]:
    if reviewed_audit.empty or "review_status" not in reviewed_audit.columns:
        return 0, 0, 0
    counts = reviewed_audit["review_status"].fillna("unreviewed").replace("", "unreviewed").value_counts()
    return int(counts.get("accepted", 0)), int(counts.get("corrected", 0)), int(counts.get("rejected", 0))


def _warning_count(reviewed_audit: pd.DataFrame) -> int:
    if reviewed_audit.empty:
        return 0
    warning_total = 0
    if "fallback_anchor_used" in reviewed_audit.columns:
        warning_total += int(reviewed_audit["fallback_anchor_used"].fillna(False).astype(bool).sum())
    return warning_total


def _espp_mentions_found(documents_count: int, hints: list[object]) -> int:
    if documents_count == 0:
        return 0
    mention_rows = 0
    for hint in hints:
        if bool(getattr(hint, "matched_terms", [])) or getattr(hint, "confidence", 0.0) > 0:
            mention_rows += 1
    return mention_rows


def _screened_filing_count(screening_frame: pd.DataFrame) -> int:
    if screening_frame.empty or "espp_mention_flag" not in screening_frame.columns:
        return 0
    return int(screening_frame["espp_mention_flag"].fillna(False).astype(bool).sum())


def _event_window_count(panel_frame: pd.DataFrame) -> int:
    if panel_frame.empty:
        return 0
    if {"ticker", "event_id"}.issubset(panel_frame.columns):
        return int(panel_frame.loc[:, ["ticker", "event_id"]].drop_duplicates().shape[0])
    if "event_id" in panel_frame.columns:
        return int(panel_frame["event_id"].nunique())
    return 0


def _build_company_status(
    company: pd.Series,
    processing_status: str,
    *,
    acquisition_kwargs: dict[str, object],
    espp_mentions_found: int = 0,
    raw_candidate_count: int = 0,
    deduplicated_candidate_count: int = 0,
    candidates_awaiting_review: int = 0,
    candidate_events_found: int = 0,
    accepted_events: int = 0,
    corrected_events: int = 0,
    rejected_events: int = 0,
    provisional_event_windows: int = 0,
    usable_event_windows: int = 0,
    warning_count: int = 0,
    error_message: str = "",
) -> CompanyProcessingStatus:
    return CompanyProcessingStatus(
        ticker=str(company["ticker"]),
        company_name=str(company["company_name"]),
        cik=str(company["cik"]),
        sector=str(company["gics_sector"]),
        sub_industry=str(company["gics_sub_industry"]),
        issuer_id=str(company["issuer_id"]),
        primary_ticker=str(company["primary_ticker"]),
        is_primary_share_class=bool(company["is_primary_share_class"]),
        processing_status=processing_status,
        espp_mentions_found=espp_mentions_found,
        raw_candidate_count=raw_candidate_count,
        deduplicated_candidate_count=deduplicated_candidate_count,
        candidates_awaiting_review=candidates_awaiting_review,
        candidate_events_found=candidate_events_found,
        accepted_events=accepted_events,
        corrected_events=corrected_events,
        rejected_events=rejected_events,
        provisional_event_windows=provisional_event_windows,
        usable_event_windows=usable_event_windows,
        warning_count=warning_count,
        error_message=error_message,
        processing_timestamp=utc_timestamp(),
        **acquisition_kwargs,
    )


def _process_primary_company(
    company: pd.Series,
    config: BatchRunConfig,
    loader: PriceDataProvider,
    benchmark_prices: pd.DataFrame,
    reviews: pd.DataFrame,
) -> CompanyRunArtifacts:
    ticker = str(company["ticker"])
    cik = str(company["cik"])
    company_name = str(company["company_name"])
    acquired: Phase2FilingAcquisitionResult | None = None
    try:
        acquired = _acquire_filings(config, ticker=ticker, cik=cik, company_name=company_name)
        filings = acquired.documents
        hints = acquired.hints
        acquisition_metrics_frame = pd.DataFrame([acquired.metrics.to_row()])
        acquisition_warnings = acquired.metrics.warning_count
        acquisition_kwargs = _acquisition_status_kwargs(acquired)

        if config.filings.source == "sec" and acquired.metrics.filings_selected > 0 and acquired.metrics.filings_processed == 0:
            raise RuntimeError(f"No SEC filing documents could be processed for {ticker}")

        if config.offline_mode and config.filings.source == "fixture" and acquired.metrics.filings_discovered == 0:
            return CompanyRunArtifacts(
                status=_base_status_row(
                    company,
                    "skipped",
                    error_message=f"No local filing fixtures available for {ticker} in offline_mode.",
                ),
                audit_frame=pd.DataFrame(),
                panel_frame=pd.DataFrame(),
                inventory_frame=acquired.inventory_frame,
                screening_frame=acquired.screening_frame,
                acquisition_metrics_frame=acquisition_metrics_frame,
            )

        if acquired.metrics.filings_selected == 0:
            return CompanyRunArtifacts(
                status=_build_company_status(
                    company,
                    "completed_no_usable_events",
                    acquisition_kwargs=acquisition_kwargs,
                    warning_count=acquisition_warnings,
                ),
                audit_frame=pd.DataFrame(),
                panel_frame=pd.DataFrame(),
                inventory_frame=acquired.inventory_frame,
                screening_frame=acquired.screening_frame,
                acquisition_metrics_frame=acquisition_metrics_frame,
            )

        mentions_found = _espp_mentions_found(len(filings), hints)
        if config.filings.source == "sec" and mentions_found == 0:
            return CompanyRunArtifacts(
                status=_build_company_status(
                    company,
                    "completed_no_espp",
                    acquisition_kwargs=acquisition_kwargs,
                    warning_count=acquisition_warnings,
                ),
                audit_frame=pd.DataFrame(),
                panel_frame=pd.DataFrame(),
                inventory_frame=acquired.inventory_frame,
                screening_frame=acquired.screening_frame,
                acquisition_metrics_frame=acquisition_metrics_frame,
            )

        prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
        events, audit_frame = estimate_event_dates_with_audit(
            ticker,
            hints,
            config.start_date.year,
            config.end_date.year,
        )
        events, audit_frame = _apply_event_date_reviews(
            events,
            audit_frame,
            reviews[reviews["ticker"] == ticker].copy(),
        )
        events, audit_frame = _filter_artifacts_to_date_range(events, audit_frame, config.start_date, config.end_date)

        event_study = run_event_study(
            price_frame=prices,
            benchmark_frame=benchmark_prices,
            events=events,
            config=config.event_study,
        )
        accepted_events, corrected_events, rejected_events = _status_counts(audit_frame)
        warnings = _warning_count(audit_frame) + acquisition_warnings
        usable_event_windows = _event_window_count(event_study.panel)

        if mentions_found == 0:
            processing_status = "completed_no_espp"
        elif usable_event_windows == 0:
            processing_status = "completed_no_usable_events"
        elif warnings > 0:
            processing_status = "warning"
        else:
            processing_status = "completed"

        panel_frame = event_study.panel.copy()
        if not panel_frame.empty:
            panel_frame["ticker"] = ticker
        return CompanyRunArtifacts(
            status=_build_company_status(
                company,
                processing_status,
                acquisition_kwargs=acquisition_kwargs,
                espp_mentions_found=mentions_found,
                candidate_events_found=int(len(audit_frame)),
                accepted_events=accepted_events,
                corrected_events=corrected_events,
                rejected_events=rejected_events,
                usable_event_windows=usable_event_windows,
                warning_count=warnings,
            ),
            audit_frame=audit_frame,
            panel_frame=panel_frame,
            inventory_frame=acquired.inventory_frame,
            screening_frame=acquired.screening_frame,
            acquisition_metrics_frame=acquisition_metrics_frame,
        )
    except Exception as exc:
        LOGGER.exception("[%s] failed during Phase 2 batch processing", ticker)
        return CompanyRunArtifacts(
            status=_base_status_row(company, "failed", error_message=str(exc)),
            audit_frame=pd.DataFrame(),
            panel_frame=pd.DataFrame(),
            inventory_frame=acquired.inventory_frame if acquired is not None else pd.DataFrame(),
            screening_frame=acquired.screening_frame if acquired is not None else pd.DataFrame(),
            acquisition_metrics_frame=(
                pd.DataFrame([acquired.metrics.to_row()]) if acquired is not None else pd.DataFrame()
            ),
        )


def _process_phase3_company(
    company: pd.Series,
    config: BatchRunConfig,
    loader: PriceDataProvider,
    benchmark_prices: pd.DataFrame,
    reviews: pd.DataFrame,
) -> CompanyRunArtifacts:
    ticker = str(company["ticker"])
    cik = str(company["cik"])
    company_name = str(company["company_name"])
    issuer_name = str(company["issuer_name"])
    issuer_id = str(company["issuer_id"])
    acquired: Phase2FilingAcquisitionResult | None = None
    try:
        acquired = _acquire_filings(config, ticker=ticker, cik=cik, company_name=company_name)
        acquisition_metrics_frame = pd.DataFrame([acquired.metrics.to_row()])
        acquisition_warnings = acquired.metrics.warning_count
        acquisition_kwargs = _acquisition_status_kwargs(acquired)

        if config.filings.source == "sec" and acquired.metrics.filings_selected > 0 and acquired.metrics.filings_processed == 0:
            raise RuntimeError(f"No SEC filing documents could be processed for {ticker}")

        if config.offline_mode and config.filings.source == "fixture" and acquired.metrics.filings_discovered == 0:
            return CompanyRunArtifacts(
                status=_base_status_row(
                    company,
                    "skipped",
                    error_message=f"No local filing fixtures available for {ticker} in offline_mode.",
                ),
                audit_frame=pd.DataFrame(),
                panel_frame=pd.DataFrame(),
                inventory_frame=acquired.inventory_frame,
                screening_frame=acquired.screening_frame,
                acquisition_metrics_frame=acquisition_metrics_frame,
            )

        phase3_artifacts = build_phase3_candidate_artifacts(
            ticker=ticker,
            issuer_name=issuer_name,
            issuer_id=issuer_id,
            cik=cik,
            documents=acquired.documents,
            hints=acquired.hints,
            reviews=reviews[reviews["ticker"] == ticker].copy() if not reviews.empty else reviews.copy(),
            config=config.phase3,
        )
        mentions_found = _screened_filing_count(acquired.screening_frame)
        raw_candidate_count = int(len(phase3_artifacts.raw_candidates))
        deduplicated_candidate_count = int(len(phase3_artifacts.review_queue))
        candidates_awaiting_review = int(
            phase3_artifacts.review_queue["review_status"].fillna("unreviewed").replace("", "unreviewed").eq("unreviewed").sum()
        ) if not phase3_artifacts.review_queue.empty else 0
        accepted_events, corrected_events, rejected_events = _status_counts(phase3_artifacts.validated_audit)

        validated_events = _filter_events_to_date_range(phase3_artifacts.validated_events, config.start_date, config.end_date)
        provisional_events = _filter_events_to_date_range(phase3_artifacts.provisional_events, config.start_date, config.end_date)
        validated_panel = pd.DataFrame()
        provisional_panel = pd.DataFrame()
        if validated_events or provisional_events:
            prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
            if validated_events:
                validated_study = run_event_study(
                    price_frame=prices,
                    benchmark_frame=benchmark_prices,
                    events=validated_events,
                    config=config.event_study,
                )
                validated_panel = validated_study.panel.copy()
                if not validated_panel.empty:
                    validated_panel["ticker"] = ticker
            if provisional_events:
                provisional_study = run_event_study(
                    price_frame=prices,
                    benchmark_frame=benchmark_prices,
                    events=provisional_events,
                    config=config.event_study,
                )
                provisional_panel = provisional_study.panel.copy()
                if not provisional_panel.empty:
                    provisional_panel["ticker"] = ticker

        usable_event_windows = _event_window_count(validated_panel)
        provisional_event_windows = _event_window_count(provisional_panel)
        warnings = acquisition_warnings

        if mentions_found == 0 and raw_candidate_count == 0:
            processing_status = "completed_no_espp"
        elif raw_candidate_count == 0:
            processing_status = "completed_no_usable_events"
        elif candidates_awaiting_review > 0:
            processing_status = "completed_pending_review"
        elif usable_event_windows == 0:
            processing_status = "completed_no_usable_events"
        elif warnings > 0:
            processing_status = "warning"
        else:
            processing_status = "completed"

        return CompanyRunArtifacts(
            status=_build_company_status(
                company,
                processing_status,
                acquisition_kwargs=acquisition_kwargs,
                espp_mentions_found=mentions_found,
                raw_candidate_count=raw_candidate_count,
                deduplicated_candidate_count=deduplicated_candidate_count,
                candidates_awaiting_review=candidates_awaiting_review,
                candidate_events_found=deduplicated_candidate_count,
                accepted_events=accepted_events,
                corrected_events=corrected_events,
                rejected_events=rejected_events,
                provisional_event_windows=provisional_event_windows,
                usable_event_windows=usable_event_windows,
                warning_count=warnings,
            ),
            audit_frame=phase3_artifacts.validated_audit,
            panel_frame=validated_panel,
            inventory_frame=acquired.inventory_frame,
            screening_frame=acquired.screening_frame,
            acquisition_metrics_frame=acquisition_metrics_frame,
            raw_candidate_frame=phase3_artifacts.raw_candidates,
            pre_refinement_review_queue_frame=phase3_artifacts.pre_refinement_review_queue,
            review_queue_frame=phase3_artifacts.review_queue,
            excluded_queue_frame=phase3_artifacts.excluded_queue,
            provisional_audit_frame=phase3_artifacts.provisional_audit,
            provisional_panel_frame=provisional_panel,
        )
    except Exception as exc:
        LOGGER.exception("[%s] failed during Phase 3 batch processing", ticker)
        return CompanyRunArtifacts(
            status=_base_status_row(company, "failed", error_message=str(exc)),
            audit_frame=pd.DataFrame(),
            panel_frame=pd.DataFrame(),
            inventory_frame=acquired.inventory_frame if acquired is not None else pd.DataFrame(),
            screening_frame=acquired.screening_frame if acquired is not None else pd.DataFrame(),
            acquisition_metrics_frame=(
                pd.DataFrame([acquired.metrics.to_row()]) if acquired is not None else pd.DataFrame()
            ),
        )


def _read_existing_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _upsert_company_frame(existing: pd.DataFrame, incoming: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if existing.empty:
        return incoming.copy()
    kept = existing[existing["ticker"] != ticker].copy() if "ticker" in existing.columns else existing.copy()
    if incoming.empty:
        return kept.reset_index(drop=True)
    combined = pd.concat([kept, incoming], ignore_index=True)
    sort_columns = [
        column
        for column in (
            "ticker",
            "filing_date",
            "accession_number",
            "candidate_event_date",
            "event_date",
            "assigned_event_date",
            "candidate_month_day",
            "source_id",
            "event_review_id",
        )
        if column in combined.columns
    ]
    if sort_columns:
        combined = combined.sort_values(sort_columns, ignore_index=True)
    return combined.reset_index(drop=True)


def _write_optional_frame(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _persist_universe_artifacts(output_dir: Path, loaded_universe: LoadedSP500Universe, selected_universe: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    selected_universe.to_csv(output_dir / "selected_universe.csv", index=False)
    (output_dir / "reports" / "universe_validation_report.md").write_text(
        render_universe_validation_report_markdown(loaded_universe.report),
        encoding="utf-8",
    )


def _restore_existing_status(existing_row: dict[str, object], ticker: str) -> CompanyProcessingStatus:
    def _int_value(key: str) -> int:
        return int(existing_row.get(key, 0) or 0)

    def _str_value(key: str) -> str:
        value = existing_row.get(key, "")
        return "" if value is None else str(value)

    return CompanyProcessingStatus(
        ticker=ticker,
        company_name=_str_value("company_name"),
        cik=_str_value("cik"),
        sector=_str_value("sector"),
        sub_industry=_str_value("sub_industry"),
        issuer_id=_str_value("issuer_id"),
        primary_ticker=_str_value("primary_ticker"),
        is_primary_share_class=bool(existing_row.get("is_primary_share_class", False)),
        processing_status=_str_value("processing_status"),
        filings_discovered=_int_value("filings_discovered"),
        filings_matching_forms=_int_value("filings_matching_forms"),
        filings_in_date_window=_int_value("filings_in_date_window"),
        filings_selected=_int_value("filings_selected"),
        filings_processed=_int_value("filings_processed"),
        configured_filing_start_date=_str_value("configured_filing_start_date"),
        configured_filing_end_date=_str_value("configured_filing_end_date"),
        effective_filing_start_date=_str_value("effective_filing_start_date"),
        effective_filing_end_date=_str_value("effective_filing_end_date"),
        espp_mentions_found=_int_value("espp_mentions_found"),
        raw_candidate_count=_int_value("raw_candidate_count"),
        deduplicated_candidate_count=_int_value("deduplicated_candidate_count"),
        candidates_awaiting_review=_int_value("candidates_awaiting_review"),
        candidate_events_found=_int_value("candidate_events_found"),
        accepted_events=_int_value("accepted_events"),
        corrected_events=_int_value("corrected_events"),
        rejected_events=_int_value("rejected_events"),
        provisional_event_windows=_int_value("provisional_event_windows"),
        usable_event_windows=_int_value("usable_event_windows"),
        warning_count=_int_value("warning_count"),
        error_message=_str_value("error_message"),
        processing_timestamp=_str_value("processing_timestamp"),
    )


def _filter_existing_frame_to_selected_tickers(frame: pd.DataFrame, selected_tickers: set[str]) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return frame
    return frame[frame["ticker"].isin(selected_tickers)].reset_index(drop=True)


def run_phase2_batch(config_path: Path, force: bool = False) -> None:
    _configure_logging()
    config = load_batch_config(config_path)
    loaded_universe = load_sp500_universe(config.universe_file)
    selected_universe = select_universe_companies(
        loaded_universe.companies,
        ticker_subset=config.ticker_subset,
        sector_subset=config.sector_subset,
        max_companies=config.max_companies,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    _persist_universe_artifacts(config.output_dir, loaded_universe, selected_universe)

    loader = _build_price_provider(config)
    benchmark_prices = loader.load_daily_ohlcv(config.benchmark, config.start_date, config.end_date)
    legacy_reviews = _load_event_date_reviews(config.review_file) if not config.phase3.enabled else pd.DataFrame()
    phase3_reviews = load_phase3_candidate_reviews(config.review_file) if config.phase3.enabled else pd.DataFrame()

    status_path = config.output_dir / STATUS_FILE_NAME
    audit_path = config.output_dir / "espp_date_audit.csv"
    windows_path = config.output_dir / WINDOWS_FILE_NAME
    inventory_path = config.output_dir / FILING_INVENTORY_FILE_NAME
    screening_path = config.output_dir / FILING_SCREENING_FILE_NAME
    acquisition_metrics_path = config.output_dir / ACQUISITION_METRICS_FILE_NAME
    raw_candidates_path = config.output_dir / RAW_CANDIDATE_FILE_NAME
    review_queue_path = config.output_dir / REVIEW_QUEUE_FILE_NAME
    excluded_queue_path = config.output_dir / EXCLUDED_QUEUE_FILE_NAME
    provisional_audit_path = config.output_dir / PROVISIONAL_AUDIT_FILE_NAME
    provisional_windows_path = config.output_dir / PROVISIONAL_WINDOWS_FILE_NAME

    existing_status = read_status_frame(status_path) if config.resume_mode and not force else empty_status_frame()
    existing_audit = _read_existing_frame(audit_path) if config.resume_mode and not force else pd.DataFrame()
    existing_windows = _read_existing_frame(windows_path) if config.resume_mode and not force else pd.DataFrame()
    existing_inventory = _read_existing_frame(inventory_path) if config.resume_mode and not force else pd.DataFrame()
    existing_screening = _read_existing_frame(screening_path) if config.resume_mode and not force else pd.DataFrame()
    existing_acquisition_metrics = _read_existing_frame(acquisition_metrics_path) if config.resume_mode and not force else pd.DataFrame()
    existing_raw_candidates = _read_existing_frame(raw_candidates_path) if config.phase3.enabled and config.resume_mode and not force else pd.DataFrame()
    existing_review_queue = _read_existing_frame(review_queue_path) if config.phase3.enabled and config.resume_mode and not force else pd.DataFrame()
    existing_excluded_queue = _read_existing_frame(excluded_queue_path) if config.phase3.enabled and config.resume_mode and not force else pd.DataFrame()
    existing_provisional_audit = _read_existing_frame(provisional_audit_path) if config.phase3.enabled and config.resume_mode and not force else pd.DataFrame()
    existing_provisional_windows = _read_existing_frame(provisional_windows_path) if config.phase3.enabled and config.resume_mode and not force else pd.DataFrame()
    existing_status_lookup = (
        existing_status.set_index("ticker").to_dict("index")
        if not existing_status.empty and "ticker" in existing_status.columns
        else {}
    )

    status_records: list[CompanyProcessingStatus] = []
    combined_audit = existing_audit.copy()
    combined_windows = existing_windows.copy()
    combined_inventory = existing_inventory.copy()
    combined_screening = existing_screening.copy()
    combined_acquisition_metrics = existing_acquisition_metrics.copy()
    combined_raw_candidates = existing_raw_candidates.copy()
    combined_review_queue = existing_review_queue.copy()
    combined_excluded_queue = existing_excluded_queue.copy()
    combined_provisional_audit = existing_provisional_audit.copy()
    combined_provisional_windows = existing_provisional_windows.copy()
    selected_tickers = set(selected_universe["ticker"].tolist())
    combined_audit = _filter_existing_frame_to_selected_tickers(combined_audit, selected_tickers)
    combined_windows = _filter_existing_frame_to_selected_tickers(combined_windows, selected_tickers)
    combined_inventory = _filter_existing_frame_to_selected_tickers(combined_inventory, selected_tickers)
    combined_screening = _filter_existing_frame_to_selected_tickers(combined_screening, selected_tickers)
    combined_acquisition_metrics = _filter_existing_frame_to_selected_tickers(combined_acquisition_metrics, selected_tickers)
    combined_raw_candidates = _filter_existing_frame_to_selected_tickers(combined_raw_candidates, selected_tickers)
    combined_review_queue = _filter_existing_frame_to_selected_tickers(combined_review_queue, selected_tickers)
    combined_excluded_queue = _filter_existing_frame_to_selected_tickers(combined_excluded_queue, selected_tickers)
    combined_provisional_audit = _filter_existing_frame_to_selected_tickers(combined_provisional_audit, selected_tickers)
    combined_provisional_windows = _filter_existing_frame_to_selected_tickers(combined_provisional_windows, selected_tickers)

    for _, company in selected_universe.iterrows():
        ticker = str(company["ticker"])
        if not bool(company["is_primary_share_class"]):
            status_records.append(
                _base_status_row(
                    company,
                    "skipped",
                    error_message=f"Skipped duplicate share class; issuer will be processed via primary ticker {company['primary_ticker']}.",
                )
            )
            combined_audit = _upsert_company_frame(combined_audit, pd.DataFrame(), ticker)
            combined_windows = _upsert_company_frame(combined_windows, pd.DataFrame(), ticker)
            combined_inventory = _upsert_company_frame(combined_inventory, pd.DataFrame(), ticker)
            combined_screening = _upsert_company_frame(combined_screening, pd.DataFrame(), ticker)
            combined_acquisition_metrics = _upsert_company_frame(combined_acquisition_metrics, pd.DataFrame(), ticker)
            combined_raw_candidates = _upsert_company_frame(combined_raw_candidates, pd.DataFrame(), ticker)
            combined_review_queue = _upsert_company_frame(combined_review_queue, pd.DataFrame(), ticker)
            combined_excluded_queue = _upsert_company_frame(combined_excluded_queue, pd.DataFrame(), ticker)
            combined_provisional_audit = _upsert_company_frame(combined_provisional_audit, pd.DataFrame(), ticker)
            combined_provisional_windows = _upsert_company_frame(combined_provisional_windows, pd.DataFrame(), ticker)
            continue

        existing_row = existing_status_lookup.get(ticker)
        if config.resume_mode and not force and existing_row and existing_row.get("processing_status") in SUCCESSFUL_RESUME_STATUSES:
            status_records.append(_restore_existing_status(existing_row, ticker))
            LOGGER.info("[%s] resume_mode kept prior successful result", ticker)
            continue

        artifacts = (
            _process_phase3_company(company, config, loader, benchmark_prices, phase3_reviews)
            if config.phase3.enabled
            else _process_primary_company(company, config, loader, benchmark_prices, legacy_reviews)
        )
        status_records.append(artifacts.status)
        combined_audit = _upsert_company_frame(combined_audit, artifacts.audit_frame, ticker)
        combined_windows = _upsert_company_frame(combined_windows, artifacts.panel_frame, ticker)
        combined_inventory = _upsert_company_frame(combined_inventory, artifacts.inventory_frame, ticker)
        combined_screening = _upsert_company_frame(combined_screening, artifacts.screening_frame, ticker)
        combined_acquisition_metrics = _upsert_company_frame(
            combined_acquisition_metrics,
            artifacts.acquisition_metrics_frame,
            ticker,
        )
        combined_raw_candidates = _upsert_company_frame(combined_raw_candidates, artifacts.raw_candidate_frame, ticker)
        combined_review_queue = _upsert_company_frame(combined_review_queue, artifacts.review_queue_frame, ticker)
        combined_excluded_queue = _upsert_company_frame(combined_excluded_queue, artifacts.excluded_queue_frame, ticker)
        combined_provisional_audit = _upsert_company_frame(
            combined_provisional_audit,
            artifacts.provisional_audit_frame,
            ticker,
        )
        combined_provisional_windows = _upsert_company_frame(
            combined_provisional_windows,
            artifacts.provisional_panel_frame,
            ticker,
        )

    status_frame = status_frame_from_records(status_records)
    write_status_frame(status_path, status_frame)
    if config.phase3.enabled:
        _write_optional_frame(audit_path, combined_audit)
    else:
        _persist_date_audit(config.output_dir, [combined_audit] if not combined_audit.empty else [])
    _write_optional_frame(windows_path, combined_windows)
    _write_optional_frame(inventory_path, combined_inventory)
    _write_optional_frame(screening_path, combined_screening)
    _write_optional_frame(acquisition_metrics_path, combined_acquisition_metrics)
    _write_optional_frame(raw_candidates_path, combined_raw_candidates)
    _write_optional_frame(review_queue_path, combined_review_queue)
    _write_optional_frame(excluded_queue_path, combined_excluded_queue)
    _write_optional_frame(provisional_audit_path, combined_provisional_audit)
    _write_optional_frame(provisional_windows_path, combined_provisional_windows)
    if config.phase3.enabled:
        write_phase3_candidate_quality_reports(
            config.output_dir,
            pd.concat([combined_review_queue, combined_excluded_queue], ignore_index=True),
            combined_review_queue,
            combined_excluded_queue,
        )
    report_path = write_phase2_summary_reports(
        config.output_dir,
        selected_universe,
        status_frame,
        combined_audit,
        combined_windows,
        raw_candidates=combined_raw_candidates,
        review_queue=combined_review_queue,
        provisional_panel=combined_provisional_windows,
    )
    LOGGER.info("Wrote Phase 2 summary report to %s", report_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 2 ESPP research batch pipeline")
    parser.add_argument("--config", type=Path, default=Path("config/phase2_example.yaml"), help="Path to YAML Phase 2 batch config")
    parser.add_argument("--force", action="store_true", help="Reprocess even previously completed companies")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_phase2_batch(config_path=args.config, force=bool(args.force))
