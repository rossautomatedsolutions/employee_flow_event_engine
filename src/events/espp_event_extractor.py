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


def estimate_event_dates(
    ticker: str,
    filing_hints: list[ESPPFilingHint],
    start_year: int,
    end_year: int,
) -> list[ESPPEvent]:
    """Backward-compatible conversion to ESPPEvent records for the event-study pipeline."""

    events: list[ESPPEvent] = []
    ticker_hints = [hint for hint in filing_hints if hint.ticker == ticker]

    for year in range(start_year, end_year + 1):
        candidates: set[tuple[int, int]] = set()
        supporting_hints = [hint for hint in ticker_hints if hint.filing_date.year in {year - 1, year}]

        for hint in supporting_hints:
            candidates.update(hint.month_day_candidates)

        if not candidates:
            candidates.update(DEFAULT_ANCHORS)
            method = "fallback_default_anchors"
            confidence = 0.2
            source_hint = None
        else:
            method = "filing_text_month_day"
            confidence = max((hint.confidence for hint in supporting_hints), default=0.5)
            source_hint = max(supporting_hints, key=lambda hint: hint.confidence, default=None)

        for month, day in sorted(candidates):
            try:
                event_date = date(year, month, day)
            except ValueError:
                continue

            events.append(
                ESPPEvent(
                    ticker=ticker,
                    event_date=event_date,
                    source_filing_date=source_hint.filing_date if source_hint else date(year, 1, 1),
                    source_filing_type=source_hint.filing_type if source_hint else "N/A",
                    confidence=round(confidence, 3),
                    approximation_method=method,
                )
            )

    return sorted(events, key=lambda event: event.event_date)
