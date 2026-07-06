from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

STATUS_COLUMNS = [
    "ticker",
    "company_name",
    "cik",
    "sector",
    "sub_industry",
    "issuer_id",
    "primary_ticker",
    "is_primary_share_class",
    "processing_status",
    "filings_discovered",
    "filings_matching_forms",
    "filings_in_date_window",
    "filings_selected",
    "filings_processed",
    "configured_filing_start_date",
    "configured_filing_end_date",
    "effective_filing_start_date",
    "effective_filing_end_date",
    "espp_mentions_found",
    "raw_candidate_count",
    "deduplicated_candidate_count",
    "candidates_awaiting_review",
    "candidate_events_found",
    "accepted_events",
    "corrected_events",
    "rejected_events",
    "provisional_event_windows",
    "usable_event_windows",
    "warning_count",
    "error_message",
    "processing_timestamp",
]


@dataclass(slots=True)
class CompanyProcessingStatus:
    ticker: str
    company_name: str
    cik: str
    sector: str
    sub_industry: str
    issuer_id: str
    primary_ticker: str
    is_primary_share_class: bool
    processing_status: str
    filings_discovered: int = 0
    filings_matching_forms: int = 0
    filings_in_date_window: int = 0
    filings_selected: int = 0
    filings_processed: int = 0
    configured_filing_start_date: str | None = None
    configured_filing_end_date: str | None = None
    effective_filing_start_date: str | None = None
    effective_filing_end_date: str | None = None
    espp_mentions_found: int = 0
    raw_candidate_count: int = 0
    deduplicated_candidate_count: int = 0
    candidates_awaiting_review: int = 0
    candidate_events_found: int = 0
    accepted_events: int = 0
    corrected_events: int = 0
    rejected_events: int = 0
    provisional_event_windows: int = 0
    usable_event_windows: int = 0
    warning_count: int = 0
    error_message: str = ""
    processing_timestamp: str = ""

    def to_row(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "cik": self.cik,
            "sector": self.sector,
            "sub_industry": self.sub_industry,
            "issuer_id": self.issuer_id,
            "primary_ticker": self.primary_ticker,
            "is_primary_share_class": self.is_primary_share_class,
            "processing_status": self.processing_status,
            "filings_discovered": int(self.filings_discovered),
            "filings_matching_forms": int(self.filings_matching_forms),
            "filings_in_date_window": int(self.filings_in_date_window),
            "filings_selected": int(self.filings_selected),
            "filings_processed": int(self.filings_processed),
            "configured_filing_start_date": self.configured_filing_start_date,
            "configured_filing_end_date": self.configured_filing_end_date,
            "effective_filing_start_date": self.effective_filing_start_date,
            "effective_filing_end_date": self.effective_filing_end_date,
            "espp_mentions_found": int(self.espp_mentions_found),
            "raw_candidate_count": int(self.raw_candidate_count),
            "deduplicated_candidate_count": int(self.deduplicated_candidate_count),
            "candidates_awaiting_review": int(self.candidates_awaiting_review),
            "candidate_events_found": int(self.candidate_events_found),
            "accepted_events": int(self.accepted_events),
            "corrected_events": int(self.corrected_events),
            "rejected_events": int(self.rejected_events),
            "provisional_event_windows": int(self.provisional_event_windows),
            "usable_event_windows": int(self.usable_event_windows),
            "warning_count": int(self.warning_count),
            "error_message": self.error_message,
            "processing_timestamp": self.processing_timestamp or utc_timestamp(),
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_status_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STATUS_COLUMNS)


def status_frame_from_records(records: Iterable[CompanyProcessingStatus]) -> pd.DataFrame:
    rows = [record.to_row() for record in records]
    if not rows:
        return empty_status_frame()
    frame = pd.DataFrame(rows).reindex(columns=STATUS_COLUMNS)
    return frame.sort_values(["primary_ticker", "ticker"], ignore_index=True)


def read_status_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return empty_status_frame()
    frame = pd.read_csv(path).reindex(columns=STATUS_COLUMNS)
    if "is_primary_share_class" in frame.columns:
        frame["is_primary_share_class"] = (
            frame["is_primary_share_class"]
            .fillna(False)
            .map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        )
    numeric_columns = [
        "filings_discovered",
        "filings_matching_forms",
        "filings_in_date_window",
        "filings_selected",
        "filings_processed",
        "espp_mentions_found",
        "raw_candidate_count",
        "deduplicated_candidate_count",
        "candidates_awaiting_review",
        "candidate_events_found",
        "accepted_events",
        "corrected_events",
        "rejected_events",
        "provisional_event_windows",
        "usable_event_windows",
        "warning_count",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = frame[column].fillna(0).astype(int)
    if "processing_status" in frame.columns:
        frame["processing_status"] = frame["processing_status"].fillna("pending").astype(str)
    for column in (
        "configured_filing_start_date",
        "configured_filing_end_date",
        "effective_filing_start_date",
        "effective_filing_end_date",
    ):
        if column in frame.columns:
            frame[column] = frame[column].fillna("").astype(str)
    if "error_message" in frame.columns:
        frame["error_message"] = frame["error_message"].fillna("").astype(str)
    return frame.reindex(columns=STATUS_COLUMNS)


def write_status_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.reindex(columns=STATUS_COLUMNS).to_csv(path, index=False)
