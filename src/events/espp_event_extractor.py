from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.data.sec_parser import ESPPFilingHint


@dataclass(slots=True)
class ESPPEvent:
    ticker: str
    event_date: date
    source_filing_date: date
    source_filing_type: str
    confidence: float
    approximation_method: str


DEFAULT_ANCHORS: tuple[tuple[int, int], ...] = ((6, 30), (12, 31))


def estimate_event_dates(
    ticker: str,
    filing_hints: list[ESPPFilingHint],
    start_year: int,
    end_year: int,
) -> list[ESPPEvent]:
    """
    Build an annual/semi-annual ESPP event schedule.

    Priority:
    1. Month/day hints from filings.
    2. Generic fallback anchors (Jun 30 / Dec 31).

    TODO: Replace this with structured extraction from actual ESPP sections
    and plan effective dates to improve event timing precision.
    """

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
