from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.analysis.event_study import run_event_study
from src.analysis.phase2_summary import write_phase2_summary_reports
from src.data.price_loader import PriceDataProvider, build_price_loader
from src.data.sec_parser import FilingDocument, load_filing_documents_from_fixtures, parse_many_espp_hints
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
from src.pipeline.run_event_study import _apply_event_date_reviews, _configure_logging, _load_event_date_reviews, _persist_date_audit
from src.universe.sp500_universe import (
    LoadedSP500Universe,
    load_sp500_universe,
    render_universe_validation_report_markdown,
    select_universe_companies,
)

LOGGER = logging.getLogger("pipeline.phase2_batch")
STATUS_FILE_NAME = "company_processing_status.csv"
WINDOWS_FILE_NAME = "all_event_windows.csv"
SUCCESSFUL_RESUME_STATUSES = {"completed", "completed_no_espp", "completed_no_usable_events", "warning"}


@dataclass(slots=True)
class CompanyRunArtifacts:
    status: CompanyProcessingStatus
    audit_frame: pd.DataFrame
    panel_frame: pd.DataFrame


def _build_price_provider(config: BatchRunConfig) -> PriceDataProvider:
    return build_price_loader(price_source=config.price_source, price_data_path=config.price_data_path)


def _load_filings(config: BatchRunConfig, ticker: str) -> list[FilingDocument]:
    if config.filing_fixture_dir is None:
        if config.offline_mode:
            return []
        raise NotImplementedError("Live filing acquisition is not implemented yet for Phase 2 batch runs.")
    return load_filing_documents_from_fixtures(config.filing_fixture_dir, ticker=ticker)


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
        if getattr(hint, "confidence", 0.0) > 0 or bool(getattr(hint, "month_day_candidates", [])):
            mention_rows += 1
    return mention_rows


def _process_primary_company(
    company: pd.Series,
    config: BatchRunConfig,
    loader: PriceDataProvider,
    benchmark_prices: pd.DataFrame,
    reviews: pd.DataFrame,
) -> CompanyRunArtifacts:
    ticker = str(company["ticker"])
    try:
        filings = _load_filings(config, ticker)
        if config.offline_mode and not filings:
            return CompanyRunArtifacts(
                status=_base_status_row(
                    company,
                    "skipped",
                    error_message=f"No local filing fixtures available for {ticker} in offline_mode.",
                ),
                audit_frame=pd.DataFrame(),
                panel_frame=pd.DataFrame(),
            )

        prices = loader.load_daily_ohlcv(ticker, config.start_date, config.end_date)
        hints = parse_many_espp_hints(filings)
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
        warnings = _warning_count(audit_frame)
        mentions_found = _espp_mentions_found(len(filings), hints)
        usable_event_windows = int(event_study.panel["event_id"].nunique()) if not event_study.panel.empty else 0

        if mentions_found == 0:
            processing_status = "completed_no_espp"
        elif usable_event_windows == 0:
            processing_status = "completed_no_usable_events"
        elif warnings > 0:
            processing_status = "warning"
        else:
            processing_status = "completed"

        status = CompanyProcessingStatus(
            ticker=ticker,
            company_name=str(company["company_name"]),
            cik=str(company["cik"]),
            sector=str(company["gics_sector"]),
            sub_industry=str(company["gics_sub_industry"]),
            issuer_id=str(company["issuer_id"]),
            primary_ticker=str(company["primary_ticker"]),
            is_primary_share_class=bool(company["is_primary_share_class"]),
            processing_status=processing_status,
            filings_discovered=len(filings),
            filings_processed=len(filings),
            espp_mentions_found=mentions_found,
            candidate_events_found=int(len(audit_frame)),
            accepted_events=accepted_events,
            corrected_events=corrected_events,
            rejected_events=rejected_events,
            usable_event_windows=usable_event_windows,
            warning_count=warnings,
            processing_timestamp=utc_timestamp(),
        )
        panel_frame = event_study.panel.copy()
        if not panel_frame.empty:
            panel_frame["ticker"] = ticker
        return CompanyRunArtifacts(status=status, audit_frame=audit_frame, panel_frame=panel_frame)
    except Exception as exc:
        LOGGER.exception("[%s] failed during Phase 2 batch processing", ticker)
        return CompanyRunArtifacts(
            status=_base_status_row(company, "failed", error_message=str(exc)),
            audit_frame=pd.DataFrame(),
            panel_frame=pd.DataFrame(),
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
    sort_columns = [column for column in ("ticker", "event_date", "assigned_event_date", "candidate_month_day") if column in combined.columns]
    if sort_columns:
        combined = combined.sort_values(sort_columns, ignore_index=True)
    return combined.reset_index(drop=True)


def _persist_universe_artifacts(output_dir: Path, loaded_universe: LoadedSP500Universe, selected_universe: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    selected_universe.to_csv(output_dir / "selected_universe.csv", index=False)
    (output_dir / "reports" / "universe_validation_report.md").write_text(
        render_universe_validation_report_markdown(loaded_universe.report),
        encoding="utf-8",
    )


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
    reviews = _load_event_date_reviews(config.review_file)

    status_path = config.output_dir / STATUS_FILE_NAME
    audit_path = config.output_dir / "espp_date_audit.csv"
    windows_path = config.output_dir / WINDOWS_FILE_NAME

    existing_status = read_status_frame(status_path) if config.resume_mode and not force else empty_status_frame()
    existing_audit = _read_existing_frame(audit_path) if config.resume_mode and not force else pd.DataFrame()
    existing_windows = _read_existing_frame(windows_path) if config.resume_mode and not force else pd.DataFrame()
    existing_status_lookup = (
        existing_status.set_index("ticker").to_dict("index")
        if not existing_status.empty and "ticker" in existing_status.columns
        else {}
    )

    status_records: list[CompanyProcessingStatus] = []
    combined_audit = existing_audit.copy()
    combined_windows = existing_windows.copy()
    selected_tickers = set(selected_universe["ticker"].tolist())
    if not combined_audit.empty and "ticker" in combined_audit.columns:
        combined_audit = combined_audit[combined_audit["ticker"].isin(selected_tickers)].reset_index(drop=True)
    if not combined_windows.empty and "ticker" in combined_windows.columns:
        combined_windows = combined_windows[combined_windows["ticker"].isin(selected_tickers)].reset_index(drop=True)

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
            continue

        existing_row = existing_status_lookup.get(ticker)
        if config.resume_mode and not force and existing_row and existing_row.get("processing_status") in SUCCESSFUL_RESUME_STATUSES:
            status_records.append(
                CompanyProcessingStatus(
                    ticker=ticker,
                    company_name=str(existing_row["company_name"]),
                    cik=str(existing_row["cik"]),
                    sector=str(existing_row["sector"]),
                    sub_industry=str(existing_row["sub_industry"]),
                    issuer_id=str(existing_row["issuer_id"]),
                    primary_ticker=str(existing_row["primary_ticker"]),
                    is_primary_share_class=bool(existing_row["is_primary_share_class"]),
                    processing_status=str(existing_row["processing_status"]),
                    filings_discovered=int(existing_row["filings_discovered"]),
                    filings_processed=int(existing_row["filings_processed"]),
                    espp_mentions_found=int(existing_row["espp_mentions_found"]),
                    candidate_events_found=int(existing_row["candidate_events_found"]),
                    accepted_events=int(existing_row["accepted_events"]),
                    corrected_events=int(existing_row["corrected_events"]),
                    rejected_events=int(existing_row["rejected_events"]),
                    usable_event_windows=int(existing_row["usable_event_windows"]),
                    warning_count=int(existing_row["warning_count"]),
                    error_message=str(existing_row.get("error_message", "")),
                    processing_timestamp=str(existing_row["processing_timestamp"]),
                )
            )
            LOGGER.info("[%s] resume_mode kept prior successful result", ticker)
            continue

        artifacts = _process_primary_company(company, config, loader, benchmark_prices, reviews)
        status_records.append(artifacts.status)
        combined_audit = _upsert_company_frame(combined_audit, artifacts.audit_frame, ticker)
        combined_windows = _upsert_company_frame(combined_windows, artifacts.panel_frame, ticker)

    status_frame = status_frame_from_records(status_records)
    write_status_frame(status_path, status_frame)
    _persist_date_audit(config.output_dir, [combined_audit] if not combined_audit.empty else [])
    if combined_windows.empty:
        if windows_path.exists():
            windows_path.unlink()
    else:
        combined_windows.to_csv(windows_path, index=False)
    report_path = write_phase2_summary_reports(config.output_dir, selected_universe, status_frame, combined_audit, combined_windows)
    LOGGER.info("Wrote Phase 2 summary report to %s", report_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 2 ESPP research batch pipeline")
    parser.add_argument("--config", type=Path, default=Path("config/phase2_example.yaml"), help="Path to YAML Phase 2 batch config")
    parser.add_argument("--force", action="store_true", help="Reprocess even previously completed companies")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_phase2_batch(config_path=args.config, force=bool(args.force))
