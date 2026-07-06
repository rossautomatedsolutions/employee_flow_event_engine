from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import yaml

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
DEFAULT_SCREENING_CONTEXT_CHARS = 240


@dataclass(slots=True)
class FilingDocument:
    ticker: str
    filing_type: str
    filing_date: date
    text: str
    source_fixture_path: str | None = None
    source_id: str | None = None
    source_kind: str = "fixture"
    source_url: str | None = None
    source_cache_path: str | None = None
    accession_number: str | None = None
    report_date: date | None = None
    issuer_name: str | None = None
    issuer_id: str | None = None
    cik: str | None = None


@dataclass(slots=True)
class ESPPContextMatch:
    term: str
    matched_text: str
    start_offset: int
    end_offset: int
    context_start_offset: int
    context_end_offset: int
    context_window_chars: int
    snippet: str


@dataclass(slots=True)
class ESPPFilingHint:
    ticker: str
    filing_type: str
    filing_date: date
    confidence: float
    snippets: list[str]
    month_day_candidates: list[tuple[int, int]]
    source_fixture_path: str | None = None
    source_id: str | None = None
    source_kind: str = "fixture"
    matched_terms: list[str] = field(default_factory=list)
    matches: list[ESPPContextMatch] = field(default_factory=list)


def _coerce_date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field}: {value!r}. Expected YYYY-MM-DD") from exc


def _coerce_fixture_records(raw: object, fixture_path: Path) -> list[dict[str, object]]:
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [record for record in raw if isinstance(record, dict)]
    raise ValueError(f"Unsupported fixture structure in {fixture_path}")


def load_filing_documents_from_fixtures(root: Path, ticker: str | None = None) -> list[FilingDocument]:
    """Load local filing fixtures from YAML files for deterministic research runs."""

    if not root.exists():
        return []

    documents: list[FilingDocument] = []
    for fixture_path in sorted(root.rglob("*.y*ml")):
        raw = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        if raw is None:
            continue
        for record in _coerce_fixture_records(raw, fixture_path):
            doc_ticker = str(record["ticker"])
            if ticker is not None and doc_ticker != ticker:
                continue
            documents.append(
                FilingDocument(
                    ticker=doc_ticker,
                    filing_type=str(record["filing_type"]),
                    filing_date=_coerce_date(record["filing_date"], "filing_date"),
                    text=str(record["text"]),
                    source_fixture_path=str(fixture_path),
                    source_id=str(record.get("source_id") or fixture_path.stem),
                    source_kind="fixture",
                    source_url=str(record.get("source_url")) if record.get("source_url") else None,
                    source_cache_path=str(record.get("source_cache_path")) if record.get("source_cache_path") else None,
                    accession_number=str(record.get("accession_number")) if record.get("accession_number") else None,
                    report_date=(
                        _coerce_date(record["report_date"], "report_date")
                        if record.get("report_date")
                        else None
                    ),
                    issuer_name=str(record.get("issuer_name")) if record.get("issuer_name") else None,
                    issuer_id=str(record.get("issuer_id")) if record.get("issuer_id") else None,
                    cik=str(record.get("cik")) if record.get("cik") else None,
                )
            )

    return sorted(
        documents,
        key=lambda doc: (
            doc.ticker,
            doc.filing_date,
            doc.filing_type,
            doc.source_id or "",
            doc.source_fixture_path or "",
        ),
    )


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
    matched_terms: list[str] = []
    matches: list[ESPPContextMatch] = []
    for term in ESPP_KEYWORDS:
        term_found = False
        for match in re.finditer(re.escape(term), document.text, flags=re.IGNORECASE):
            start_offset = int(match.start())
            end_offset = int(match.end())
            context_start = max(0, start_offset - DEFAULT_SCREENING_CONTEXT_CHARS)
            context_end = min(len(document.text), end_offset + DEFAULT_SCREENING_CONTEXT_CHARS)
            snippet = document.text[context_start:context_end].strip()
            matches.append(
                ESPPContextMatch(
                    term=term,
                    matched_text=match.group(0),
                    start_offset=start_offset,
                    end_offset=end_offset,
                    context_start_offset=context_start,
                    context_end_offset=context_end,
                    context_window_chars=DEFAULT_SCREENING_CONTEXT_CHARS,
                    snippet=snippet,
                )
            )
            if not term_found:
                matched_terms.append(term)
                snippets.append(snippet)
                term_found = True

    month_day_candidates: list[tuple[int, int]] = []
    for month, day in MONTH_DAY_PATTERN.findall(document.text):
        m = _to_month_number(month)
        d = int(day)
        if 1 <= d <= 31:
            month_day_candidates.append((m, d))

    deduped = sorted(set(month_day_candidates)) if matched_terms else []
    return ESPPFilingHint(
        ticker=document.ticker,
        filing_type=document.filing_type,
        filing_date=document.filing_date,
        confidence=confidence,
        snippets=snippets,
        month_day_candidates=deduped,
        source_fixture_path=document.source_fixture_path,
        source_id=document.source_id,
        source_kind=document.source_kind,
        matched_terms=matched_terms,
        matches=matches,
    )


def parse_many_espp_hints(documents: Iterable[FilingDocument]) -> list[ESPPFilingHint]:
    return [extract_espp_hints(document) for document in documents]
