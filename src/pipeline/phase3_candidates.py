from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.data.sec_parser import ESPPContextMatch, ESPPFilingHint, FilingDocument
from src.events.espp_event_extractor import ESPPEvent
from src.pipeline.batch_config import Phase3CandidateConfig

MONTH_NAME_TO_NUMBER = {
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

DATE_PHRASE_PATTERN = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|november|december"
    r")\s+([0-3]?\d)(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\b",
    flags=re.IGNORECASE,
)
PURCHASE_KEYWORD_PATTERN = re.compile(
    r"\b(purchase date|purchase dates|purchase period|purchase periods|shares are purchased|stock purchase)\b",
    flags=re.IGNORECASE,
)
RECURRING_LANGUAGE_PATTERNS: dict[str, re.Pattern[str]] = {
    "semiannual_cycle": re.compile(r"\b(semi[-\s]?annual|six[-\s]month|twice per year|twice each year)\b", flags=re.IGNORECASE),
    "quarterly_cycle": re.compile(r"\bquarterly\b", flags=re.IGNORECASE),
    "monthly_cycle": re.compile(r"\bmonthly\b", flags=re.IGNORECASE),
    "last_business_day": re.compile(r"\blast business day\b", flags=re.IGNORECASE),
    "last_day_of_period": re.compile(r"\blast day of (?:the )?period\b", flags=re.IGNORECASE),
}
NON_PURCHASE_LANGUAGE_PATTERNS: dict[str, re.Pattern[str]] = {
    "plan_adoption": re.compile(r"\badopt(?:ed|ion)?\b", flags=re.IGNORECASE),
    "board_approval": re.compile(r"\bboard approval\b", flags=re.IGNORECASE),
    "shareholder_approval": re.compile(r"\bshareholder approval\b|\bshareholders approved\b", flags=re.IGNORECASE),
    "amendment": re.compile(r"\bamend(?:ed|ment)?\b", flags=re.IGNORECASE),
    "expiration": re.compile(r"\bexpir(?:ation|e|es|ed)\b", flags=re.IGNORECASE),
    "termination": re.compile(r"\bterminat(?:e|ed|ion)\b", flags=re.IGNORECASE),
    "enrollment_period": re.compile(r"\benrollment period\b", flags=re.IGNORECASE),
    "offering_commencement": re.compile(r"\boffering commencement\b|\bcommencement date\b", flags=re.IGNORECASE),
}
SCHEDULE_PATTERN = re.compile(
    r"\b(last business day|last day of (?:the )?period|semi[-\s]?annual purchase cycle|quarterly purchase cycle)\b",
    flags=re.IGNORECASE,
)

RAW_CANDIDATE_COLUMNS = [
    "raw_candidate_id",
    "ticker",
    "issuer_name",
    "issuer_id",
    "cik",
    "source_kind",
    "source_id",
    "source_url",
    "source_cache_path",
    "accession_number",
    "filing_type",
    "filing_date",
    "report_date",
    "screening_passed",
    "diagnostic_only",
    "matched_espp_term",
    "matched_espp_terms",
    "source_match_text",
    "source_phrase",
    "source_snippet",
    "match_start_offset",
    "match_end_offset",
    "context_start_offset",
    "context_end_offset",
    "context_window_chars",
    "phrase_start_offset",
    "phrase_end_offset",
    "candidate_month_day",
    "candidate_event_date",
    "candidate_signature",
    "extraction_rule",
    "extraction_confidence",
    "confidence",
    "ambiguity_flags",
    "explicit_year_indicator",
    "inferred_year_indicator",
    "recurring_language_indicator",
    "specific_date_indicator",
    "likely_purchase_date_indicator",
    "likely_plan_adoption_amendment_expiration_approval_indicator",
    "non_purchase_language_flags",
    "duplicate_group_id",
    "event_review_id",
    "review_status",
    "corrected_event_date",
    "reviewer_note",
    "reviewed_at",
    "reviewer_id",
    "eligibility_status_for_validated_research",
]

REVIEW_QUEUE_COLUMNS = [
    "event_review_id",
    "duplicate_group_id",
    "ticker",
    "issuer_name",
    "issuer_id",
    "cik",
    "candidate_event_date",
    "original_assigned_event_date",
    "candidate_month_day",
    "source_kind",
    "canonical_source_id",
    "canonical_accession_number",
    "canonical_filing_type",
    "canonical_filing_date",
    "canonical_report_date",
    "source_phrase",
    "source_snippet",
    "matched_espp_terms",
    "matched_espp_term",
    "extraction_rule",
    "derivation_rule",
    "extraction_confidence",
    "confidence",
    "ambiguity_flags",
    "explicit_year_indicator",
    "inferred_year_indicator",
    "recurring_language_indicator",
    "specific_date_indicator",
    "likely_purchase_date_indicator",
    "likely_plan_adoption_amendment_expiration_approval_indicator",
    "non_purchase_language_flags",
    "duplicate_count",
    "contributing_accession_numbers",
    "contributing_filing_dates",
    "deduplication_reason",
    "review_status",
    "corrected_event_date",
    "reviewer_note",
    "reviewed_at",
    "reviewer_id",
    "eligibility_status_for_validated_research",
    "effective_event_date",
    "included_in_event_study",
]

PHASE3_AUDIT_COLUMNS = [
    *REVIEW_QUEUE_COLUMNS,
    "assigned_event_date",
    "reviewed_event_date",
    "review_note",
    "included_in_provisional_diagnostic",
]


@dataclass(slots=True)
class Phase3CandidateArtifacts:
    raw_candidates: pd.DataFrame
    review_queue: pd.DataFrame
    validated_audit: pd.DataFrame
    validated_events: list[ESPPEvent]
    provisional_audit: pd.DataFrame
    provisional_events: list[ESPPEvent]


def _empty_review_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_review_id",
            "ticker",
            "original_assigned_event_date",
            "corrected_event_date",
            "review_status",
            "reviewer_note",
            "reviewed_at",
            "reviewer_id",
        ]
    )


def load_phase3_candidate_reviews(review_file: Path | None) -> pd.DataFrame:
    if review_file is None or not review_file.exists():
        return _empty_review_frame()

    reviews = pd.read_csv(review_file, dtype=str).fillna("")
    if "corrected_event_date" not in reviews.columns and "reviewed_event_date" in reviews.columns:
        reviews["corrected_event_date"] = reviews["reviewed_event_date"]
    if "reviewer_note" not in reviews.columns and "review_note" in reviews.columns:
        reviews["reviewer_note"] = reviews["review_note"]
    if "event_review_id" not in reviews.columns:
        reviews["event_review_id"] = ""
    if "original_assigned_event_date" not in reviews.columns:
        reviews["original_assigned_event_date"] = reviews.get("candidate_event_date", "")
    if "reviewed_at" not in reviews.columns:
        reviews["reviewed_at"] = ""
    if "reviewer_id" not in reviews.columns:
        reviews["reviewer_id"] = ""

    required = {
        "event_review_id",
        "ticker",
        "original_assigned_event_date",
        "corrected_event_date",
        "review_status",
        "reviewer_note",
        "reviewed_at",
        "reviewer_id",
    }
    missing = required.difference(reviews.columns)
    if missing:
        raise ValueError(f"Review file missing required columns: {sorted(missing)}")

    reviews["ticker"] = reviews["ticker"].str.strip()
    reviews["event_review_id"] = reviews["event_review_id"].str.strip()
    reviews["original_assigned_event_date"] = reviews["original_assigned_event_date"].str.strip()
    reviews["corrected_event_date"] = reviews["corrected_event_date"].str.strip()
    reviews["review_status"] = reviews["review_status"].str.strip().str.lower()
    reviews.loc[reviews["review_status"] == "", "review_status"] = "unreviewed"

    allowed_statuses = {"accepted", "corrected", "rejected", "unreviewed"}
    invalid_statuses = sorted(set(reviews["review_status"]).difference(allowed_statuses))
    if invalid_statuses:
        raise ValueError(f"Review file has invalid review_status values: {invalid_statuses}")

    if not reviews.empty:
        missing_keys = reviews[(reviews["event_review_id"] == "") & (reviews["original_assigned_event_date"] == "")]
        if not missing_keys.empty:
            raise ValueError("Review rows require event_review_id or original_assigned_event_date")
        corrected_without_date = reviews[(reviews["review_status"] == "corrected") & (reviews["corrected_event_date"] == "")]
        if not corrected_without_date.empty:
            raise ValueError("Corrected review rows require corrected_event_date")
        duplicated_ids = reviews[(reviews["event_review_id"] != "")].duplicated(subset=["event_review_id"], keep=False)
        if duplicated_ids.any():
            duplicates = reviews.loc[(reviews["event_review_id"] != "") & duplicated_ids, ["event_review_id"]].drop_duplicates().to_dict("records")
            raise ValueError(f"Duplicate review rows found for event_review_id keys: {duplicates}")

    return reviews.loc[:, list(_empty_review_frame().columns)].copy()


def build_phase3_candidate_artifacts(
    *,
    ticker: str,
    issuer_name: str,
    issuer_id: str,
    cik: str,
    documents: list[FilingDocument],
    hints: list[ESPPFilingHint],
    reviews: pd.DataFrame,
    config: Phase3CandidateConfig,
) -> Phase3CandidateArtifacts:
    raw_rows: list[dict[str, object]] = []
    screened_source_ids = {
        hint.source_id
        for hint in hints
        if bool(hint.matched_terms or hint.confidence > 0)
    }
    document_lookup = {document.source_id: document for document in documents}

    for hint in hints:
        document = document_lookup.get(hint.source_id)
        if document is None:
            continue
        screening_passed = hint.source_id in screened_source_ids
        if screening_passed:
            for match in hint.matches:
                raw_rows.extend(
                    _extract_candidates_from_match(
                        document=document,
                        hint=hint,
                        match=match,
                        ticker=ticker,
                        issuer_name=issuer_name,
                        issuer_id=issuer_id,
                        cik=cik,
                        context_window_chars=config.context_window_chars,
                    )
                )
        elif config.diagnostic_extract_from_unscreened_filings:
            raw_rows.extend(
                _extract_candidates_from_unscreened_document(
                    document=document,
                    ticker=ticker,
                    issuer_name=issuer_name,
                    issuer_id=issuer_id,
                    cik=cik,
                    context_window_chars=config.context_window_chars,
                )
            )

    raw_candidates = pd.DataFrame(raw_rows).reindex(columns=RAW_CANDIDATE_COLUMNS)
    if raw_candidates.empty:
        audited_review_queue = pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS)
        return Phase3CandidateArtifacts(
            raw_candidates=raw_candidates,
            review_queue=pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS),
            validated_audit=audited_review_queue.copy(),
            validated_events=[],
            provisional_audit=pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS),
            provisional_events=[],
        )

    raw_candidates = _assign_duplicate_groups(raw_candidates)
    review_queue = _build_review_queue(raw_candidates)
    audited_review_queue = _apply_reviews(review_queue, reviews, require_review_for_validated_windows=config.require_review_for_validated_windows)
    enriched_raw = raw_candidates.drop(
        columns=[
            "event_review_id",
            "review_status",
            "corrected_event_date",
            "reviewer_note",
            "reviewed_at",
            "reviewer_id",
            "eligibility_status_for_validated_research",
        ],
        errors="ignore",
    ).merge(
        audited_review_queue[
            [
                "duplicate_group_id",
                "event_review_id",
                "review_status",
                "corrected_event_date",
                "reviewer_note",
                "reviewed_at",
                "reviewer_id",
                "eligibility_status_for_validated_research",
            ]
        ],
        how="left",
        on="duplicate_group_id",
    ).reindex(columns=RAW_CANDIDATE_COLUMNS)

    validated_audit = audited_review_queue.reindex(columns=PHASE3_AUDIT_COLUMNS).sort_values(
        ["ticker", "candidate_event_date", "duplicate_group_id"],
        ignore_index=True,
    )
    validated_events = events_from_candidate_audit(validated_audit, inclusion_column="included_in_event_study")

    provisional_audit = pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS)
    provisional_events: list[ESPPEvent] = []
    if config.generate_provisional_unreviewed_windows:
        provisional_audit = validated_audit[
            (validated_audit["review_status"] == "unreviewed")
            & (validated_audit["candidate_event_date"].fillna("") != "")
        ].copy()
        if not provisional_audit.empty:
            provisional_audit["included_in_provisional_diagnostic"] = True
            provisional_events = events_from_candidate_audit(
                provisional_audit,
                inclusion_column="included_in_provisional_diagnostic",
            )

    return Phase3CandidateArtifacts(
        raw_candidates=enriched_raw.sort_values(
            ["ticker", "candidate_event_date", "duplicate_group_id", "source_id", "phrase_start_offset"],
            ignore_index=True,
        ),
        review_queue=audited_review_queue.reindex(columns=REVIEW_QUEUE_COLUMNS).sort_values(
            ["ticker", "candidate_event_date", "duplicate_group_id"],
            ignore_index=True,
        ),
        validated_audit=validated_audit,
        validated_events=validated_events,
        provisional_audit=provisional_audit.reindex(columns=PHASE3_AUDIT_COLUMNS),
        provisional_events=provisional_events,
    )


def events_from_candidate_audit(audit_frame: pd.DataFrame, inclusion_column: str) -> list[ESPPEvent]:
    if audit_frame.empty:
        return []

    events: list[ESPPEvent] = []
    for row in audit_frame.itertuples(index=False):
        if not bool(getattr(row, inclusion_column, False)):
            continue
        effective_event_date = getattr(row, "effective_event_date", "") or getattr(row, "candidate_event_date", "")
        if not effective_event_date:
            continue
        source_filing_date = getattr(row, "canonical_filing_date", "") or effective_event_date
        events.append(
            ESPPEvent(
                ticker=str(row.ticker),
                event_date=date.fromisoformat(str(effective_event_date)),
                source_filing_date=date.fromisoformat(str(source_filing_date)),
                source_filing_type=str(getattr(row, "canonical_filing_type", "")),
                confidence=float(getattr(row, "confidence", 0.0)),
                approximation_method=str(getattr(row, "extraction_rule", "")),
                source=str(getattr(row, "canonical_source_id", "")),
                event_review_id=str(getattr(row, "event_review_id", "")) or None,
            )
        )
    return events


def _extract_candidates_from_match(
    *,
    document: FilingDocument,
    hint: ESPPFilingHint,
    match: ESPPContextMatch,
    ticker: str,
    issuer_name: str,
    issuer_id: str,
    cik: str,
    context_window_chars: int,
) -> list[dict[str, object]]:
    context_start = max(0, match.start_offset - context_window_chars)
    context_end = min(len(document.text), match.end_offset + context_window_chars)
    snippet = document.text[context_start:context_end].strip()
    return _extract_candidate_rows(
        document=document,
        snippet=snippet,
        context_start=context_start,
        context_end=context_end,
        match_start=match.start_offset,
        match_end=match.end_offset,
        matched_term=match.term,
        matched_terms=hint.matched_terms,
        source_match_text=match.matched_text,
        screening_passed=True,
        diagnostic_only=False,
        ticker=ticker,
        issuer_name=issuer_name,
        issuer_id=issuer_id,
        cik=cik,
        context_window_chars=context_window_chars,
        rule_prefix="bounded",
    )


def _extract_candidates_from_unscreened_document(
    *,
    document: FilingDocument,
    ticker: str,
    issuer_name: str,
    issuer_id: str,
    cik: str,
    context_window_chars: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate_index, match in enumerate(DATE_PHRASE_PATTERN.finditer(document.text), start=1):
        context_start = max(0, match.start() - context_window_chars)
        context_end = min(len(document.text), match.end() + context_window_chars)
        snippet = document.text[context_start:context_end].strip()
        recurring_flags = _matching_flag_names(snippet, RECURRING_LANGUAGE_PATTERNS)
        non_purchase_flags = _matching_flag_names(snippet, NON_PURCHASE_LANGUAGE_PATTERNS)
        likely_purchase = bool(PURCHASE_KEYWORD_PATTERN.search(snippet))
        month = MONTH_NAME_TO_NUMBER[str(match.group(1)).lower()]
        day = int(match.group(2))
        year_text = match.group(3)
        explicit_year = bool(year_text)
        inferred_year = not explicit_year
        try:
            candidate_event_date = (
                date(int(year_text), month, day)
                if explicit_year
                else _assign_next_occurrence(document.filing_date, month, day)
            )
        except ValueError:
            continue
        confidence_label, confidence_score = _confidence_for_candidate(
            explicit_year=explicit_year,
            recurring_language=bool(recurring_flags),
            likely_purchase=likely_purchase,
            likely_non_purchase=bool(non_purchase_flags),
        )
        rows.append(
            _candidate_row(
                document=document,
                ticker=ticker,
                issuer_name=issuer_name,
                issuer_id=issuer_id,
                cik=cik,
                screening_passed=False,
                diagnostic_only=True,
                matched_term="",
                matched_terms=[],
                source_match_text="",
                source_phrase=match.group(0),
                source_snippet=snippet,
                match_start=match.start(),
                match_end=match.end(),
                context_start=context_start,
                context_end=context_end,
                context_window_chars=context_window_chars,
                phrase_start=match.start(),
                phrase_end=match.end(),
                candidate_month_day=f"{month:02d}-{day:02d}",
                candidate_event_date=candidate_event_date.isoformat(),
                candidate_signature=candidate_event_date.isoformat(),
                extraction_rule=f"diagnostic_unscreened_explicit_date_{'explicit_year' if explicit_year else 'inferred_year'}",
                extraction_confidence=confidence_label,
                confidence_score=confidence_score,
                ambiguity_flags=[*recurring_flags, *non_purchase_flags, *([] if explicit_year else ["inferred_year"])],
                explicit_year=explicit_year,
                inferred_year=inferred_year,
                recurring_language=bool(recurring_flags),
                specific_date=True,
                likely_purchase=likely_purchase,
                likely_non_purchase=bool(non_purchase_flags),
                non_purchase_flags=non_purchase_flags,
                raw_suffix=f"diagnostic_date_{candidate_index}",
            )
        )
    return rows


def _extract_candidate_rows(
    *,
    document: FilingDocument,
    snippet: str,
    context_start: int,
    context_end: int,
    match_start: int,
    match_end: int,
    matched_term: str,
    matched_terms: list[str],
    source_match_text: str,
    screening_passed: bool,
    diagnostic_only: bool,
    ticker: str,
    issuer_name: str,
    issuer_id: str,
    cik: str,
    context_window_chars: int,
    rule_prefix: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    recurring_flags = _matching_flag_names(snippet, RECURRING_LANGUAGE_PATTERNS)
    non_purchase_flags = _matching_flag_names(snippet, NON_PURCHASE_LANGUAGE_PATTERNS)
    likely_purchase = bool(PURCHASE_KEYWORD_PATTERN.search(snippet))
    specific_date_matches = list(DATE_PHRASE_PATTERN.finditer(snippet))

    for candidate_index, phrase_match in enumerate(specific_date_matches, start=1):
        month = MONTH_NAME_TO_NUMBER[str(phrase_match.group(1)).lower()]
        day = int(phrase_match.group(2))
        year_text = phrase_match.group(3)
        explicit_year = bool(year_text)
        inferred_year = not explicit_year
        try:
            candidate_event_date = (
                date(int(year_text), month, day)
                if explicit_year
                else _assign_next_occurrence(document.filing_date, month, day)
            )
        except ValueError:
            continue
        ambiguity_flags = list(recurring_flags)
        ambiguity_flags.extend(non_purchase_flags)
        if inferred_year:
            ambiguity_flags.append("inferred_year")
        if len(specific_date_matches) > 1:
            ambiguity_flags.append("multiple_dates_in_context")
        confidence_label, confidence_score = _confidence_for_candidate(
            explicit_year=explicit_year,
            recurring_language=bool(recurring_flags),
            likely_purchase=likely_purchase,
            likely_non_purchase=bool(non_purchase_flags),
        )
        rows.append(
            _candidate_row(
                document=document,
                ticker=ticker,
                issuer_name=issuer_name,
                issuer_id=issuer_id,
                cik=cik,
                screening_passed=screening_passed,
                diagnostic_only=diagnostic_only,
                matched_term=matched_term,
                matched_terms=matched_terms,
                source_match_text=source_match_text,
                source_phrase=phrase_match.group(0),
                source_snippet=snippet,
                match_start=match_start,
                match_end=match_end,
                context_start=context_start,
                context_end=context_end,
                context_window_chars=context_window_chars,
                phrase_start=context_start + phrase_match.start(),
                phrase_end=context_start + phrase_match.end(),
                candidate_month_day=f"{month:02d}-{day:02d}",
                candidate_event_date=candidate_event_date.isoformat(),
                candidate_signature=candidate_event_date.isoformat(),
                extraction_rule=f"{rule_prefix}_explicit_date_{'explicit_year' if explicit_year else 'inferred_year'}",
                extraction_confidence=confidence_label,
                confidence_score=confidence_score,
                ambiguity_flags=ambiguity_flags,
                explicit_year=explicit_year,
                inferred_year=inferred_year,
                recurring_language=bool(recurring_flags),
                specific_date=True,
                likely_purchase=likely_purchase,
                likely_non_purchase=bool(non_purchase_flags),
                non_purchase_flags=non_purchase_flags,
                raw_suffix=f"date_{candidate_index}",
            )
        )

    if rows:
        return rows

    schedule_match = SCHEDULE_PATTERN.search(snippet)
    if schedule_match and recurring_flags:
        rows.append(
            _candidate_row(
                document=document,
                ticker=ticker,
                issuer_name=issuer_name,
                issuer_id=issuer_id,
                cik=cik,
                screening_passed=screening_passed,
                diagnostic_only=diagnostic_only,
                matched_term=matched_term,
                matched_terms=matched_terms,
                source_match_text=source_match_text,
                source_phrase=schedule_match.group(0),
                source_snippet=snippet,
                match_start=match_start,
                match_end=match_end,
                context_start=context_start,
                context_end=context_end,
                context_window_chars=context_window_chars,
                phrase_start=context_start + schedule_match.start(),
                phrase_end=context_start + schedule_match.end(),
                candidate_month_day=None,
                candidate_event_date=None,
                candidate_signature=_normalized_text(schedule_match.group(0)),
                extraction_rule=f"{rule_prefix}_recurring_schedule",
                extraction_confidence="low",
                confidence_score=0.35,
                ambiguity_flags=[*recurring_flags, *non_purchase_flags, "non_specific_schedule"],
                explicit_year=False,
                inferred_year=False,
                recurring_language=True,
                specific_date=False,
                likely_purchase=likely_purchase,
                likely_non_purchase=bool(non_purchase_flags),
                non_purchase_flags=non_purchase_flags,
                raw_suffix="schedule",
            )
        )
    return rows


def _candidate_row(
    *,
    document: FilingDocument,
    ticker: str,
    issuer_name: str,
    issuer_id: str,
    cik: str,
    screening_passed: bool,
    diagnostic_only: bool,
    matched_term: str,
    matched_terms: list[str],
    source_match_text: str,
    source_phrase: str,
    source_snippet: str,
    match_start: int,
    match_end: int,
    context_start: int,
    context_end: int,
    context_window_chars: int,
    phrase_start: int,
    phrase_end: int,
    candidate_month_day: str | None,
    candidate_event_date: str | None,
    candidate_signature: str,
    extraction_rule: str,
    extraction_confidence: str,
    confidence_score: float,
    ambiguity_flags: list[str],
    explicit_year: bool,
    inferred_year: bool,
    recurring_language: bool,
    specific_date: bool,
    likely_purchase: bool,
    likely_non_purchase: bool,
    non_purchase_flags: list[str],
    raw_suffix: str,
) -> dict[str, object]:
    source_id = document.source_id or ""
    accession_number = document.accession_number or document.source_id or ""
    raw_candidate_id = f"{ticker}|{accession_number}|{raw_suffix}|{phrase_start}"
    return {
        "raw_candidate_id": raw_candidate_id,
        "ticker": ticker,
        "issuer_name": issuer_name,
        "issuer_id": issuer_id,
        "cik": cik,
        "source_kind": document.source_kind,
        "source_id": source_id,
        "source_url": document.source_url,
        "source_cache_path": document.source_cache_path,
        "accession_number": accession_number,
        "filing_type": document.filing_type,
        "filing_date": document.filing_date.isoformat(),
        "report_date": document.report_date.isoformat() if document.report_date else None,
        "screening_passed": screening_passed,
        "diagnostic_only": diagnostic_only,
        "matched_espp_term": matched_term,
        "matched_espp_terms": " | ".join(matched_terms),
        "source_match_text": source_match_text,
        "source_phrase": source_phrase,
        "source_snippet": source_snippet,
        "match_start_offset": match_start,
        "match_end_offset": match_end,
        "context_start_offset": context_start,
        "context_end_offset": context_end,
        "context_window_chars": context_window_chars,
        "phrase_start_offset": phrase_start,
        "phrase_end_offset": phrase_end,
        "candidate_month_day": candidate_month_day,
        "candidate_event_date": candidate_event_date,
        "candidate_signature": candidate_signature,
        "extraction_rule": extraction_rule,
        "extraction_confidence": extraction_confidence,
        "confidence": round(confidence_score, 3),
        "ambiguity_flags": " | ".join(_dedupe_preserve_order(ambiguity_flags)),
        "explicit_year_indicator": explicit_year,
        "inferred_year_indicator": inferred_year,
        "recurring_language_indicator": recurring_language,
        "specific_date_indicator": specific_date,
        "likely_purchase_date_indicator": likely_purchase,
        "likely_plan_adoption_amendment_expiration_approval_indicator": likely_non_purchase,
        "non_purchase_language_flags": " | ".join(non_purchase_flags),
        "duplicate_group_id": None,
        "event_review_id": None,
        "review_status": "unreviewed",
        "corrected_event_date": None,
        "reviewer_note": None,
        "reviewed_at": None,
        "reviewer_id": None,
        "eligibility_status_for_validated_research": "ineligible_unreviewed",
    }


def _assign_duplicate_groups(raw_candidates: pd.DataFrame) -> pd.DataFrame:
    assigned = raw_candidates.copy()
    assigned["duplicate_group_id"] = assigned.apply(_duplicate_group_id, axis=1)
    return assigned


def _build_review_queue(raw_candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for duplicate_group_id, group in raw_candidates.groupby("duplicate_group_id", dropna=False, sort=True):
        ordered = group.copy()
        ordered["_specific_rank"] = ordered["specific_date_indicator"].astype(int)
        ordered["_purchase_rank"] = ordered["likely_purchase_date_indicator"].astype(int)
        ordered["_non_purchase_rank"] = ordered["likely_plan_adoption_amendment_expiration_approval_indicator"].astype(int)
        ordered["_explicit_year_rank"] = ordered["explicit_year_indicator"].astype(int)
        ordered = ordered.sort_values(
            [
                "_specific_rank",
                "_purchase_rank",
                "_non_purchase_rank",
                "confidence",
                "_explicit_year_rank",
                "filing_date",
                "accession_number",
                "raw_candidate_id",
            ],
            ascending=[False, False, True, False, False, False, True, True],
            ignore_index=True,
        )
        canonical = ordered.iloc[0]
        candidate_event_date = _string_or_none(canonical.get("candidate_event_date"))
        matched_term_values = _collect_unique_strings(group["matched_espp_term"])
        matched_terms_values = _collect_unique_pipe_values(group["matched_espp_terms"])
        contributing_accessions = _collect_unique_strings(group["accession_number"])
        contributing_filing_dates = _collect_unique_strings(group["filing_date"])
        rows.append(
            {
                "event_review_id": str(duplicate_group_id),
                "duplicate_group_id": duplicate_group_id,
                "ticker": str(canonical["ticker"]),
                "issuer_name": str(canonical["issuer_name"]),
                "issuer_id": str(canonical["issuer_id"]),
                "cik": str(canonical["cik"]),
                "candidate_event_date": candidate_event_date,
                "original_assigned_event_date": candidate_event_date,
                "candidate_month_day": _string_or_none(canonical.get("candidate_month_day")),
                "source_kind": str(canonical["source_kind"]),
                "canonical_source_id": _string_or_none(canonical.get("source_id")),
                "canonical_accession_number": _string_or_none(canonical.get("accession_number")),
                "canonical_filing_type": _string_or_none(canonical.get("filing_type")),
                "canonical_filing_date": _string_or_none(canonical.get("filing_date")),
                "canonical_report_date": _string_or_none(canonical.get("report_date")),
                "source_phrase": _string_or_none(canonical.get("source_phrase")),
                "source_snippet": _string_or_none(canonical.get("source_snippet")),
                "matched_espp_terms": " | ".join(matched_terms_values),
                "matched_espp_term": " | ".join(matched_term_values),
                "extraction_rule": str(canonical["extraction_rule"]),
                "derivation_rule": str(canonical["extraction_rule"]),
                "extraction_confidence": str(canonical["extraction_confidence"]),
                "confidence": float(canonical["confidence"]),
                "ambiguity_flags": _string_or_none(canonical.get("ambiguity_flags")),
                "explicit_year_indicator": bool(canonical["explicit_year_indicator"]),
                "inferred_year_indicator": bool(canonical["inferred_year_indicator"]),
                "recurring_language_indicator": bool(canonical["recurring_language_indicator"]),
                "specific_date_indicator": bool(canonical["specific_date_indicator"]),
                "likely_purchase_date_indicator": bool(canonical["likely_purchase_date_indicator"]),
                "likely_plan_adoption_amendment_expiration_approval_indicator": bool(
                    canonical["likely_plan_adoption_amendment_expiration_approval_indicator"]
                ),
                "non_purchase_language_flags": _string_or_none(canonical.get("non_purchase_language_flags")),
                "duplicate_count": int(len(group)),
                "contributing_accession_numbers": " | ".join(contributing_accessions),
                "contributing_filing_dates": " | ".join(contributing_filing_dates),
                "deduplication_reason": _deduplication_reason(group),
                "review_status": "unreviewed",
                "corrected_event_date": None,
                "reviewer_note": None,
                "reviewed_at": None,
                "reviewer_id": None,
                "eligibility_status_for_validated_research": _eligibility_status(
                    review_status="unreviewed",
                    candidate_event_date=candidate_event_date,
                    corrected_event_date=None,
                    require_review_for_validated_windows=True,
                ),
                "effective_event_date": candidate_event_date,
                "included_in_event_study": False,
            }
        )
    return pd.DataFrame(rows).reindex(columns=REVIEW_QUEUE_COLUMNS)


def _apply_reviews(
    review_queue: pd.DataFrame,
    reviews: pd.DataFrame,
    *,
    require_review_for_validated_windows: bool,
) -> pd.DataFrame:
    if review_queue.empty:
        return pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS)

    audited = review_queue.copy()
    audited["review_status"] = "unreviewed"
    audited["corrected_event_date"] = None
    audited["reviewer_note"] = None
    audited["reviewed_at"] = None
    audited["reviewer_id"] = None

    if not reviews.empty:
        direct_reviews = reviews[reviews["event_review_id"] != ""].copy()
        if not direct_reviews.empty:
            audited = audited.merge(
                direct_reviews,
                how="left",
                on="event_review_id",
                suffixes=("", "_review"),
            )
        else:
            audited["ticker_review"] = ""
            audited["original_assigned_event_date_review"] = ""
            audited["corrected_event_date_review"] = ""
            audited["review_status_review"] = ""
            audited["reviewer_note_review"] = ""
            audited["reviewed_at_review"] = ""
            audited["reviewer_id_review"] = ""

        unmatched = audited["review_status_review"].fillna("") == ""
        fallback_reviews = reviews[reviews["event_review_id"] == ""].copy()
        if unmatched.any() and not fallback_reviews.empty:
            fallback_matched = audited.loc[unmatched].merge(
                fallback_reviews,
                how="left",
                left_on=["ticker", "original_assigned_event_date"],
                right_on=["ticker", "original_assigned_event_date"],
                suffixes=("", "_fallback"),
            )
            for target, source in {
                "corrected_event_date_review": "corrected_event_date_fallback",
                "review_status_review": "review_status_fallback",
                "reviewer_note_review": "reviewer_note_fallback",
                "reviewed_at_review": "reviewed_at_fallback",
                "reviewer_id_review": "reviewer_id_fallback",
            }.items():
                if source in fallback_matched.columns:
                    audited.loc[unmatched, target] = fallback_matched[source].values

        matched = audited["review_status_review"].fillna("") != ""
        audited.loc[matched, "review_status"] = audited.loc[matched, "review_status_review"].replace("", "unreviewed")
        audited.loc[matched, "corrected_event_date"] = audited.loc[matched, "corrected_event_date_review"].replace("", None)
        audited.loc[matched, "reviewer_note"] = audited.loc[matched, "reviewer_note_review"].replace("", None)
        audited.loc[matched, "reviewed_at"] = audited.loc[matched, "reviewed_at_review"].replace("", None)
        audited.loc[matched, "reviewer_id"] = audited.loc[matched, "reviewer_id_review"].replace("", None)
        audited = audited.drop(
            columns=[
                column
                for column in audited.columns
                if column.endswith("_review") or column.endswith("_fallback") or column == "ticker_review"
            ],
            errors="ignore",
        )

    audited["effective_event_date"] = audited["candidate_event_date"]
    corrected_rows = audited["review_status"] == "corrected"
    audited.loc[corrected_rows, "effective_event_date"] = audited.loc[corrected_rows, "corrected_event_date"]
    audited["eligibility_status_for_validated_research"] = audited.apply(
        lambda row: _eligibility_status(
            review_status=str(row["review_status"]),
            candidate_event_date=_string_or_none(row.get("candidate_event_date")),
            corrected_event_date=_string_or_none(row.get("corrected_event_date")),
            require_review_for_validated_windows=require_review_for_validated_windows,
        ),
        axis=1,
    )
    audited["included_in_event_study"] = audited["eligibility_status_for_validated_research"] == "eligible"
    audited["assigned_event_date"] = audited["candidate_event_date"]
    audited["reviewed_event_date"] = audited["corrected_event_date"]
    audited["review_note"] = audited["reviewer_note"]
    audited["included_in_provisional_diagnostic"] = False
    return audited.reindex(columns=PHASE3_AUDIT_COLUMNS)


def _eligibility_status(
    *,
    review_status: str,
    candidate_event_date: str | None,
    corrected_event_date: str | None,
    require_review_for_validated_windows: bool,
) -> str:
    if not candidate_event_date:
        return "ineligible_no_candidate_date"
    if review_status == "accepted":
        return "eligible"
    if review_status == "corrected":
        return "eligible" if corrected_event_date else "ineligible_missing_corrected_date"
    if review_status == "rejected":
        return "ineligible_rejected"
    if require_review_for_validated_windows:
        return "ineligible_unreviewed"
    return "eligible"


def _duplicate_group_id(row: pd.Series) -> str:
    ticker = str(row["ticker"])
    candidate_event_date = _string_or_none(row.get("candidate_event_date"))
    non_purchase = bool(row.get("likely_plan_adoption_amendment_expiration_approval_indicator", False))
    likely_purchase = bool(row.get("likely_purchase_date_indicator", False))
    recurring = bool(row.get("recurring_language_indicator", False))
    if candidate_event_date:
        if non_purchase:
            kind = "specific_non_purchase"
        elif likely_purchase:
            kind = "specific_purchase"
        else:
            kind = "specific_ambiguous"
        signature = candidate_event_date
    else:
        kind = "recurring_schedule" if recurring else "context_without_date"
        signature = _normalized_text(_string_or_none(row.get("candidate_signature")) or _string_or_none(row.get("source_phrase")) or "na")
    return f"{ticker}|{kind}|{signature}"


def _deduplication_reason(group: pd.DataFrame) -> str:
    if len(group) <= 1:
        return "unique_candidate"
    accessions = _collect_unique_strings(group["accession_number"])
    if len(accessions) == 1:
        return "overlapping_snippets_same_filing"
    if bool(group["recurring_language_indicator"].fillna(False).any()):
        return "repeated_recurring_language_across_filings"
    if group["candidate_event_date"].fillna("").nunique() == 1:
        return "same_event_across_filings"
    return "duplicate_candidate_contexts"


def _confidence_for_candidate(
    *,
    explicit_year: bool,
    recurring_language: bool,
    likely_purchase: bool,
    likely_non_purchase: bool,
) -> tuple[str, float]:
    if explicit_year and likely_purchase and not likely_non_purchase:
        return "high", 0.95
    if likely_purchase and not likely_non_purchase:
        return ("medium", 0.75) if not recurring_language else ("medium", 0.65)
    if explicit_year and not likely_non_purchase:
        return "medium", 0.6
    return "low", 0.35 if recurring_language or likely_non_purchase else 0.45


def _assign_next_occurrence(filing_date: date, month: int, day: int) -> date:
    event_year = filing_date.year
    if (month, day) < (filing_date.month, filing_date.day):
        event_year += 1
    return date(event_year, month, day)


def _matching_flag_names(text: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    return [name for name, pattern in patterns.items() if pattern.search(text)]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _collect_unique_strings(values: pd.Series) -> list[str]:
    items: list[str] = []
    for value in values.fillna("").astype(str):
        stripped = value.strip()
        if stripped and stripped not in items:
            items.append(stripped)
    return items


def _collect_unique_pipe_values(values: pd.Series) -> list[str]:
    items: list[str] = []
    for value in values.fillna("").astype(str):
        for part in [candidate.strip() for candidate in value.split("|")]:
            if part and part not in items:
                items.append(part)
    return items


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    string_value = str(value).strip()
    if string_value == "" or string_value.lower() == "nan":
        return None
    return string_value
