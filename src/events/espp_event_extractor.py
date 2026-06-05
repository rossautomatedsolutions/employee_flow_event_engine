from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd

from src.data.sec_parser import ESPPFilingHint, FilingDocument

LOGGER = logging.getLogger(__name__)

DEFAULT_ANCHORS: tuple[tuple[int, int], ...] = ((6, 30), (12, 31))
MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

ESPP_KEYWORDS = (
    "employee stock purchase plan",
    "offering period",
    "purchase date",
)


@dataclass(slots=True)
class ESPPEvent:
    ticker: str
    event_date: date
    source_filing_date: date
    source_filing_type: str
    confidence: float
    approximation_method: str
    source: str | None = None
    event_review_id: str | None = None


@dataclass(slots=True)
class ESPPDateAuditRecord:
    ticker: str
    filing_type: str | None
    filing_date: date | None
    source_fixture_path: str | None
    source_id: str | None
    source_snippet: str | None
    candidate_month_day: str
    assigned_event_date: date
    derivation_rule: str
    confidence: float
    fallback_anchor_used: bool
    event_review_id: str


def _hint_derivation_rule(hint: ESPPFilingHint) -> str:
    if hint.source_kind == "mock":
        return "mock_filing_text_month_day"
    return "filing_text_month_day"


def _normalize_source_component(value: str | None) -> str:
    if not value:
        return "na"
    return value.replace("\\", "/")


def _build_event_review_id(
    ticker: str,
    filing_type: str | None,
    filing_date: date | None,
    source_id: str | None,
    source_fixture_path: str | None,
    candidate_month_day: str,
    assigned_event_date: date,
    derivation_rule: str,
) -> str:
    source_ref = source_id or _normalize_source_component(source_fixture_path)
    filing_type_part = filing_type or "na"
    filing_date_part = filing_date.isoformat() if filing_date else "na"
    return (
        f"{ticker}|{filing_type_part}|{filing_date_part}|{source_ref}|"
        f"{candidate_month_day}|{assigned_event_date.isoformat()}|{derivation_rule}"
    )


class EventExtractor(Protocol):
    """Protocol to keep extractor implementations extensible (e.g., RSU, insider windows)."""

    def extract(self, ticker: str, filings: list[FilingDocument], start_year: int, end_year: int) -> pd.DataFrame:
        ...


class ESPPEventExtractor:
    """Concrete extractor for ESPP event schedules."""

    def extract(self, ticker: str, filings: list[FilingDocument], start_year: int, end_year: int) -> pd.DataFrame:
        return extract_espp_event_dataframe(ticker=ticker, filings=filings, start_year=start_year, end_year=end_year)


class RSUVestingExtractor:
    """Placeholder extension point for future RSU vesting extraction."""

    def extract(self, ticker: str, filings: list[FilingDocument], start_year: int, end_year: int) -> pd.DataFrame:
        raise NotImplementedError("RSU vesting extraction is not implemented yet.")


class InsiderSellingWindowExtractor:
    """Placeholder extension point for future insider selling window extraction."""

    def extract(self, ticker: str, filings: list[FilingDocument], start_year: int, end_year: int) -> pd.DataFrame:
        raise NotImplementedError("Insider selling window extraction is not implemented yet.")


def _parse_month_day_phrase(text: str) -> set[tuple[int, int]]:
    pattern = re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+([0-3]?\d)(?:st|nd|rd|th)?\b",
        flags=re.IGNORECASE,
    )
    matches: set[tuple[int, int]] = set()
    for month, day in pattern.findall(text):
        d = int(day)
        if 1 <= d <= 31:
            matches.add((MONTH_NAMES[month.lower()], d))
    return matches


def _contains_all_keywords(text: str) -> bool:
    lowered = text.lower()
    return all(keyword in lowered for keyword in ESPP_KEYWORDS)


def _format_month_day(month: int, day: int) -> str:
    return f"{month:02d}-{day:02d}"


def _assign_candidate_to_event_date(filing_date: date, month: int, day: int) -> date:
    event_year = filing_date.year
    if (month, day) < (filing_date.month, filing_date.day):
        event_year += 1
    return date(event_year, month, day)


def _choose_preferred_audit_row(records: list[ESPPDateAuditRecord]) -> ESPPDateAuditRecord:
    ordered = sorted(
        records,
        key=lambda record: (
            -record.confidence,
            record.filing_date or date.max,
            record.filing_type or "",
            record.source_id or "",
            record.source_fixture_path or "",
            record.candidate_month_day,
        ),
    )
    return ordered[0]


def _audit_frame(records: list[ESPPDateAuditRecord]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "ticker": record.ticker,
                "filing_type": record.filing_type,
                "filing_date": record.filing_date.isoformat() if record.filing_date else None,
                "source_fixture_path": record.source_fixture_path,
                "source_id": record.source_id,
                "source_snippet": record.source_snippet,
                "candidate_month_day": record.candidate_month_day,
                "assigned_event_date": record.assigned_event_date.isoformat(),
                "derivation_rule": record.derivation_rule,
                "confidence": record.confidence,
                "fallback_anchor_used": record.fallback_anchor_used,
                "event_review_id": record.event_review_id,
            }
            for record in sorted(
                records,
                key=lambda item: (item.assigned_event_date, item.ticker, item.candidate_month_day, item.source_id or "", item.event_review_id),
            )
        ]
    )
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "filing_type",
                "filing_date",
                "source_fixture_path",
                "source_id",
                "source_snippet",
                "candidate_month_day",
                "assigned_event_date",
                "derivation_rule",
                "confidence",
                "fallback_anchor_used",
                "event_review_id",
            ]
        )
    return frame


def _candidate_month_days_from_filing(text: str) -> tuple[set[tuple[int, int]], str, str]:
    lowered = text.lower()
    candidates = _parse_month_day_phrase(text)

    if candidates and _contains_all_keywords(text):
        return candidates, "high", "keyword_pattern_and_explicit_dates"

    # Pattern examples: "January 1 and July 1"
    jan_jul_pattern = re.search(r"january\s+1\s+and\s+july\s+1", lowered)
    if jan_jul_pattern:
        return {(1, 1), (7, 1)}, "medium", "offering_cycle_start_dates"

    # Pattern examples: "six-month offering periods" / "purchase date is last day of period"
    six_month_pattern = re.search(r"six[-\s]month\s+offering\s+period", lowered)
    last_day_pattern = re.search(r"purchase\s+date\s+is\s+(the\s+)?last\s+day\s+of\s+(the\s+)?period", lowered)
    if six_month_pattern or last_day_pattern:
        return set(DEFAULT_ANCHORS), "medium", "six_month_period_last_day_assumption"

    if candidates:
        return candidates, "medium", "explicit_dates_without_all_keywords"

    return set(), "low", "no_espp_signal"


def extract_espp_event_dataframe(
    ticker: str,
    filings: list[FilingDocument],
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """Extract ESPP events into a normalized DataFrame.

    Returns columns: ticker, event_date, confidence_score, source.
    """

    years = range(start_year, end_year + 1)
    rows: list[dict[str, str | date]] = []
    ticker_filings = [filing for filing in filings if filing.ticker == ticker]

    for year in years:
        year_filings = [f for f in ticker_filings if f.filing_date.year in {year - 1, year}]
        candidate_dates: set[tuple[int, int]] = set()
        best_confidence = "low"

        for filing in year_filings:
            extracted, confidence_score, derivation = _candidate_month_days_from_filing(filing.text)
            if extracted:
                candidate_dates.update(extracted)
                if confidence_score == "high" or (confidence_score == "medium" and best_confidence == "low"):
                    best_confidence = confidence_score
                LOGGER.info(
                    "ESPP event derivation for %s (%s filed %s): %s -> %s",
                    ticker,
                    filing.filing_type,
                    filing.filing_date.isoformat(),
                    derivation,
                    sorted(extracted),
                )

        if not candidate_dates:
            candidate_dates = set(DEFAULT_ANCHORS)
            best_confidence = "low"
            LOGGER.info(
                "ESPP fallback heuristic for %s %s: using semi-annual anchors %s",
                ticker,
                year,
                sorted(candidate_dates),
            )
            source = "heuristic"
        else:
            source = "SEC"

        for month, day in sorted(candidate_dates):
            try:
                event_date = date(year, month, day)
            except ValueError:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "event_date": event_date,
                    "confidence_score": best_confidence,
                    "source": source,
                }
            )

    return pd.DataFrame(rows).sort_values("event_date").reset_index(drop=True)


def estimate_event_dates_with_audit(
    ticker: str,
    filing_hints: list[ESPPFilingHint],
    start_year: int,
    end_year: int,
) -> tuple[list[ESPPEvent], pd.DataFrame]:
    """Estimate event dates and emit an auditable row per assigned event date."""

    year_range = range(start_year, end_year + 1)
    explicit_by_date: dict[date, list[ESPPDateAuditRecord]] = {}
    ticker_hints = [hint for hint in filing_hints if hint.ticker == ticker]

    for hint in ticker_hints:
        snippet = hint.snippets[0] if hint.snippets else None
        for month, day in hint.month_day_candidates:
            try:
                assigned_event_date = _assign_candidate_to_event_date(hint.filing_date, month, day)
            except ValueError:
                continue
            if assigned_event_date.year not in year_range:
                continue

            record = ESPPDateAuditRecord(
                ticker=ticker,
                filing_type=hint.filing_type,
                filing_date=hint.filing_date,
                source_fixture_path=hint.source_fixture_path,
                source_id=hint.source_id,
                source_snippet=snippet,
                candidate_month_day=_format_month_day(month, day),
                assigned_event_date=assigned_event_date,
                derivation_rule=_hint_derivation_rule(hint),
                confidence=round(hint.confidence, 3),
                fallback_anchor_used=False,
                event_review_id=_build_event_review_id(
                    ticker=ticker,
                    filing_type=hint.filing_type,
                    filing_date=hint.filing_date,
                    source_id=hint.source_id,
                    source_fixture_path=hint.source_fixture_path,
                    candidate_month_day=_format_month_day(month, day),
                    assigned_event_date=assigned_event_date,
                    derivation_rule=_hint_derivation_rule(hint),
                ),
            )
            explicit_by_date.setdefault(assigned_event_date, []).append(record)

    explicit_records = [_choose_preferred_audit_row(records) for records in explicit_by_date.values()]
    explicit_years = {record.assigned_event_date.year for record in explicit_records}

    fallback_records: list[ESPPDateAuditRecord] = []
    for year in year_range:
        if year in explicit_years:
            continue
        for month, day in DEFAULT_ANCHORS:
            fallback_records.append(
                ESPPDateAuditRecord(
                    ticker=ticker,
                    filing_type=None,
                    filing_date=None,
                    source_fixture_path=None,
                    source_id=f"default_anchor_{ticker.lower()}_{year}_{month:02d}{day:02d}",
                    source_snippet=None,
                    candidate_month_day=_format_month_day(month, day),
                    assigned_event_date=date(year, month, day),
                    derivation_rule="fallback_default_anchors",
                    confidence=0.2,
                    fallback_anchor_used=True,
                    event_review_id=_build_event_review_id(
                        ticker=ticker,
                        filing_type=None,
                        filing_date=None,
                        source_id=f"default_anchor_{ticker.lower()}_{year}_{month:02d}{day:02d}",
                        source_fixture_path=None,
                        candidate_month_day=_format_month_day(month, day),
                        assigned_event_date=date(year, month, day),
                        derivation_rule="fallback_default_anchors",
                    ),
                )
            )

    audit_records = sorted(
        [*explicit_records, *fallback_records],
        key=lambda record: (record.assigned_event_date, record.candidate_month_day, record.source_id or ""),
    )
    events = [
        ESPPEvent(
            ticker=record.ticker,
            event_date=record.assigned_event_date,
            source_filing_date=record.filing_date or date(record.assigned_event_date.year, 1, 1),
            source_filing_type=record.filing_type or "N/A",
            confidence=record.confidence,
            approximation_method=record.derivation_rule,
            source=(
                "heuristic"
                if record.fallback_anchor_used
                else ("mock" if record.derivation_rule == "mock_filing_text_month_day" else "fixture")
            ),
            event_review_id=record.event_review_id,
        )
        for record in audit_records
    ]
    return events, _audit_frame(audit_records)


def estimate_event_dates(
    ticker: str,
    filing_hints: list[ESPPFilingHint],
    start_year: int,
    end_year: int,
) -> list[ESPPEvent]:
    """Backward-compatible conversion to ESPPEvent records for the event-study pipeline."""
    events, _ = estimate_event_dates_with_audit(
        ticker=ticker,
        filing_hints=filing_hints,
        start_year=start_year,
        end_year=end_year,
    )
    return events
