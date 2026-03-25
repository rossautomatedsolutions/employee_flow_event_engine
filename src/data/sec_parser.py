from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

ESPP_KEYWORDS = [
    "employee stock purchase plan",
    "espp",
    "section 423",
    "purchase period",
    "offering period",
]

MONTH_DAY_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+"
    r"([0-3]?\d)(?:st|nd|rd|th)?\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class FilingDocument:
    ticker: str
    filing_type: str
    filing_date: date
    text: str


@dataclass(slots=True)
class ESPPFilingHint:
    ticker: str
    filing_type: str
    filing_date: date
    confidence: float
    snippets: list[str]
    month_day_candidates: list[tuple[int, int]]


def _to_month_number(name: str) -> int:
    month_names = {
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
    return month_names[name.lower()]


def extract_espp_hints(document: FilingDocument) -> ESPPFilingHint:
    """Heuristic parser for ESPP references in filing text."""

    lowered = document.text.lower()
    hit_count = sum(lowered.count(term) for term in ESPP_KEYWORDS)
    confidence = min(1.0, 0.2 * hit_count)

    snippets: list[str] = []
    for term in ESPP_KEYWORDS:
        match = re.search(rf"(.{{0,80}}{re.escape(term)}.{{0,80}})", lowered, flags=re.IGNORECASE)
        if match:
            snippets.append(match.group(1).strip())

    month_day_candidates: list[tuple[int, int]] = []
    for month, day in MONTH_DAY_PATTERN.findall(document.text):
        m = _to_month_number(month)
        d = int(day)
        if 1 <= d <= 31:
            month_day_candidates.append((m, d))

    deduped = sorted(set(month_day_candidates))
    return ESPPFilingHint(
        ticker=document.ticker,
        filing_type=document.filing_type,
        filing_date=document.filing_date,
        confidence=confidence,
        snippets=snippets,
        month_day_candidates=deduped,
    )


def parse_many_espp_hints(documents: Iterable[FilingDocument]) -> list[ESPPFilingHint]:
    return [extract_espp_hints(document) for document in documents]
