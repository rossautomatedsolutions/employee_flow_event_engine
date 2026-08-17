from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.data.sec_parser import ESPPContextMatch, ESPPFilingHint, FilingDocument
from src.events.espp_event_extractor import ESPPEvent
from src.pipeline.batch_config import Phase3CandidateConfig

PRIMARY_QUEUE_DISPOSITION = "primary_review_queue"
EXCLUDED_QUEUE_DISPOSITION = "excluded_from_primary_queue"
PRIMARY_PRIORITY_TIERS = ("Tier1", "Tier2", "Tier3")
EXCLUDED_PRIORITY_TIER = EXCLUDED_QUEUE_DISPOSITION
PHASE3_ALLOWED_REVIEW_STATUSES = {
    "accepted",
    "corrected",
    "rejected",
    "unreviewed",
    "unresolved",
    "future_scheduled",
}

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
STRONG_SPECIFIC_PURCHASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "exercise_of_purchase_rights": re.compile(r"\bafter the exercise of purchase rights on that date\b", flags=re.IGNORECASE),
}
STRONG_RECURRING_PURCHASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "purchase_dates_occur_on": re.compile(r"\bpurchase dates? occur on\b", flags=re.IGNORECASE),
    "purchase_date_on_or_before": re.compile(r"\bpurchase date on the first trading day on or before\b", flags=re.IGNORECASE),
    "ends_with_purchase_date": re.compile(r"\bends with a purchase date on the first trading day on or before\b", flags=re.IGNORECASE),
    "purchase_date_definition_on_or_before": re.compile(
        r"\bpurchase date\b[^.]{0,160}\bfirst trading day on or before\b",
        flags=re.IGNORECASE,
    ),
    "named_purchase_period_dates": re.compile(
        r"\bpurchase period\s*\((?:december|june|january|february|march|april|may|july|august|september|october|november)",
        flags=re.IGNORECASE,
    ),
}
PERIOD_BOUNDARY_OR_CAPACITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "current_purchase_period_runs_until": re.compile(r"\bcurrent purchase period which runs until\b", flags=re.IGNORECASE),
}
ADMINISTRATIVE_CUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "reduce_percentage_election": re.compile(r"\breduce (?:their|the) percentage election\b", flags=re.IGNORECASE),
    "increase_percentage_election": re.compile(r"\bincrease (?:their|the) election\b", flags=re.IGNORECASE),
    "change_election": re.compile(r"\b(change|modify|reduce|increase).{0,80}\belection\b", flags=re.IGNORECASE),
}
PROSPECTIVE_CUE_PATTERNS: dict[str, re.Pattern[str]] = {
    **STRONG_RECURRING_PURCHASE_PATTERNS,
    **PERIOD_BOUNDARY_OR_CAPACITY_PATTERNS,
    "may_be_purchased": re.compile(r"\bmay be purchased under the espp\b", flags=re.IGNORECASE),
    "purchase_date_definition": re.compile(r"\b[p\"“]?purchase date[p\"”]?\s+means\b", flags=re.IGNORECASE),
}
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
SUBSCRIPTION_CONTEXT_PATTERN = re.compile(r"\b(subscription date|subscription agreement)\b", flags=re.IGNORECASE)
OFFERING_MECHANICS_PATTERN = re.compile(
    r"\b(offering periods? begin|implemented by consecutive, overlapping offering periods|commencement date of each offering period|offering date)\b",
    flags=re.IGNORECASE,
)
SNAPSHOT_CONTEXT_PATTERN = re.compile(
    r"\b(as of|reserved for future issuance|remain(?:ed)? available for future issuance|shares subject to purchase during the purchase periods in effect|"
    r"number of shares to be issued .* not determinable|eligible to participate|closing price|shares outstanding|aggregate unearned stock-based compensation expense|"
    r"available under the espp|shares remaining available)\b",
    flags=re.IGNORECASE,
)
STRONG_SNAPSHOT_CONTEXT_PATTERN = re.compile(
    r"\b(shares subject to purchase during the purchase periods in effect as of|"
    r"number of shares to be issued upon exercise of outstanding rights .* not determinable)\b",
    flags=re.IGNORECASE,
)
UNRELATED_CONTEXT_PATTERN = re.compile(
    r"\b(donations?|workforce|severance|job eliminations|stock-based compensation expense|expire or are canceled without delivery of shares)\b",
    flags=re.IGNORECASE,
)
PLAN_HISTORY_PATTERN = re.compile(
    r"\b(initially adopted by the board|approved by our stockholders|amended and restated|proposal is approved by our stockholders)\b",
    flags=re.IGNORECASE,
)
SHARE_RESERVE_MECHANICS_PATTERN = re.compile(
    r"\b(automatic annual increase|immediately preceding january 31|shares available under the espp|shares remaining available)\b",
    flags=re.IGNORECASE,
)
SENTENCE_BOUNDARY_PATTERN = re.compile(r"[.!?]")
CLAUSE_BOUNDARY_PATTERN = re.compile(r"[,:;()\[\]]")

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
    "source_sentence",
    "source_sentence_window",
    "match_start_offset",
    "match_end_offset",
    "context_start_offset",
    "context_end_offset",
    "context_window_chars",
    "phrase_start_offset",
    "phrase_end_offset",
    "distance_to_purchase_phrase",
    "same_sentence_as_purchase_phrase",
    "same_clause_as_purchase_phrase",
    "attachment_score",
    "nearest_purchase_phrase",
    "truncated_snippet_boundary_indicator",
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
    "execution_cues",
    "prospective_cues",
    "administrative_cues",
    "evidence_class",
    "quality_category",
    "queue_disposition",
    "review_priority_tier",
    "quality_decision_rule",
    "exclusion_reason",
    "shadowed_by_event_review_id",
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
    "source_sentence",
    "source_sentence_window",
    "distance_to_purchase_phrase",
    "same_sentence_as_purchase_phrase",
    "same_clause_as_purchase_phrase",
    "attachment_score",
    "nearest_purchase_phrase",
    "truncated_snippet_boundary_indicator",
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
    "execution_cues",
    "prospective_cues",
    "administrative_cues",
    "evidence_class",
    "quality_category",
    "queue_disposition",
    "review_priority_tier",
    "quality_decision_rule",
    "exclusion_reason",
    "shadowed_by_event_review_id",
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
    pre_refinement_review_queue: pd.DataFrame
    review_queue: pd.DataFrame
    excluded_queue: pd.DataFrame
    validated_audit: pd.DataFrame
    validated_events: list[ESPPEvent]
    provisional_audit: pd.DataFrame
    provisional_events: list[ESPPEvent]


@dataclass(slots=True)
class AttachmentMetrics:
    distance_to_purchase_phrase: int | None
    same_sentence_as_purchase_phrase: bool
    same_clause_as_purchase_phrase: bool
    attachment_score: float
    nearest_purchase_phrase: str | None
    truncated_snippet_boundary_indicator: bool


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


def _is_valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


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

    invalid_statuses = sorted(set(reviews["review_status"]).difference(PHASE3_ALLOWED_REVIEW_STATUSES))
    if invalid_statuses:
        raise ValueError(f"Review file has invalid review_status values: {invalid_statuses}")

    if not reviews.empty:
        missing_keys = reviews[(reviews["event_review_id"] == "") & (reviews["original_assigned_event_date"] == "")]
        if not missing_keys.empty:
            raise ValueError("Review rows require event_review_id or original_assigned_event_date")
        corrected_without_date = reviews[(reviews["review_status"] == "corrected") & (reviews["corrected_event_date"] == "")]
        if not corrected_without_date.empty:
            raise ValueError("Corrected review rows require corrected_event_date")
        corrected_with_invalid_date = reviews[
            (reviews["review_status"] == "corrected")
            & (~reviews["corrected_event_date"].map(_is_valid_iso_date))
        ]
        if not corrected_with_invalid_date.empty:
            raise ValueError("Corrected review rows require corrected_event_date in YYYY-MM-DD format")
        accepted_with_corrected_date = reviews[
            (reviews["review_status"] == "accepted")
            & (reviews["corrected_event_date"] != "")
        ]
        if not accepted_with_corrected_date.empty:
            raise ValueError("Accepted review rows must leave corrected_event_date blank and use the candidate date")
        noncorrected_with_corrected_date = reviews[
            (reviews["review_status"].isin(["rejected", "unreviewed", "unresolved", "future_scheduled"]))
            & (reviews["corrected_event_date"] != "")
        ]
        if not noncorrected_with_corrected_date.empty:
            raise ValueError("Rejected, unreviewed, unresolved, and future_scheduled review rows must leave corrected_event_date blank")
        duplicated_ids = reviews[(reviews["event_review_id"] != "")].duplicated(subset=["event_review_id"], keep=False)
        if duplicated_ids.any():
            duplicates = reviews.loc[(reviews["event_review_id"] != "") & duplicated_ids, ["event_review_id"]].drop_duplicates().to_dict("records")
            raise ValueError(f"Duplicate review rows found for event_review_id keys: {duplicates}")
        fallback_rows = reviews[reviews["event_review_id"] == ""].copy()
        duplicated_fallbacks = fallback_rows.duplicated(subset=["ticker", "original_assigned_event_date"], keep=False)
        if duplicated_fallbacks.any():
            duplicates = fallback_rows.loc[
                duplicated_fallbacks,
                ["ticker", "original_assigned_event_date"],
            ].drop_duplicates().to_dict("records")
            raise ValueError(f"Duplicate review rows found for ticker + original_assigned_event_date keys: {duplicates}")

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
            pre_refinement_review_queue=pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS),
            review_queue=pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS),
            excluded_queue=pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS),
            validated_audit=audited_review_queue.copy(),
            validated_events=[],
            provisional_audit=pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS),
            provisional_events=[],
        )

    raw_candidates = _assign_duplicate_groups(raw_candidates)
    pre_refinement_review_queue = _build_review_queue(raw_candidates)
    review_queue, excluded_queue = _refine_review_queue(pre_refinement_review_queue)
    audited_review_queue = _apply_reviews(
        review_queue,
        reviews,
        require_review_for_validated_windows=config.require_review_for_validated_windows,
        auto_policy_review=config.auto_policy_review,
        review_as_of_date=config.review_as_of_date or date.today(),
    )
    finalized_excluded_queue = _finalize_excluded_queue(excluded_queue)
    canonical_annotations = pd.concat(
        [
            audited_review_queue[
                [
                    "duplicate_group_id",
                    "event_review_id",
                    "quality_category",
                    "queue_disposition",
                    "review_priority_tier",
                    "quality_decision_rule",
                    "exclusion_reason",
                    "shadowed_by_event_review_id",
                    "review_status",
                    "corrected_event_date",
                    "reviewer_note",
                    "reviewed_at",
                    "reviewer_id",
                    "eligibility_status_for_validated_research",
                    "execution_cues",
                    "prospective_cues",
                    "administrative_cues",
                    "evidence_class",
                ]
            ],
            finalized_excluded_queue[
                [
                    "duplicate_group_id",
                    "event_review_id",
                    "quality_category",
                    "queue_disposition",
                    "review_priority_tier",
                    "quality_decision_rule",
                    "exclusion_reason",
                    "shadowed_by_event_review_id",
                    "review_status",
                    "corrected_event_date",
                    "reviewer_note",
                    "reviewed_at",
                    "reviewer_id",
                    "eligibility_status_for_validated_research",
                    "execution_cues",
                    "prospective_cues",
                    "administrative_cues",
                    "evidence_class",
                ]
            ],
        ],
        ignore_index=True,
    )
    enriched_raw = raw_candidates.drop(
        columns=[
            "event_review_id",
            "quality_category",
            "queue_disposition",
            "review_priority_tier",
            "quality_decision_rule",
            "exclusion_reason",
            "shadowed_by_event_review_id",
            "review_status",
            "corrected_event_date",
            "reviewer_note",
            "reviewed_at",
            "reviewer_id",
            "eligibility_status_for_validated_research",
            "execution_cues",
            "prospective_cues",
            "administrative_cues",
            "evidence_class",
        ],
        errors="ignore",
    ).merge(
        canonical_annotations,
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
        pre_refinement_review_queue=pre_refinement_review_queue.sort_values(
            ["ticker", "candidate_event_date", "duplicate_group_id"],
            ignore_index=True,
        ),
        review_queue=audited_review_queue.reindex(columns=REVIEW_QUEUE_COLUMNS).sort_values(
            ["ticker", "candidate_event_date", "duplicate_group_id"],
            ignore_index=True,
        ),
        excluded_queue=finalized_excluded_queue.reindex(columns=REVIEW_QUEUE_COLUMNS).sort_values(
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
    local_phrase_start = max(0, phrase_start - context_start)
    local_phrase_end = max(local_phrase_start, phrase_end - context_start)
    attachment = _attachment_metrics(source_snippet, local_phrase_start, local_phrase_end)
    source_sentence, source_sentence_window = _sentence_context(document.text, phrase_start, phrase_end)
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
        "source_sentence": source_sentence,
        "source_sentence_window": source_sentence_window,
        "match_start_offset": match_start,
        "match_end_offset": match_end,
        "context_start_offset": context_start,
        "context_end_offset": context_end,
        "context_window_chars": context_window_chars,
        "phrase_start_offset": phrase_start,
        "phrase_end_offset": phrase_end,
        "distance_to_purchase_phrase": attachment.distance_to_purchase_phrase,
        "same_sentence_as_purchase_phrase": attachment.same_sentence_as_purchase_phrase,
        "same_clause_as_purchase_phrase": attachment.same_clause_as_purchase_phrase,
        "attachment_score": attachment.attachment_score,
        "nearest_purchase_phrase": attachment.nearest_purchase_phrase,
        "truncated_snippet_boundary_indicator": attachment.truncated_snippet_boundary_indicator,
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
        "execution_cues": " | ".join(_matched_cue_names(source_sentence_window or source_snippet, STRONG_SPECIFIC_PURCHASE_PATTERNS)),
        "prospective_cues": " | ".join(_matched_cue_names(source_sentence_window or source_snippet, PROSPECTIVE_CUE_PATTERNS)),
        "administrative_cues": " | ".join(_matched_cue_names(source_sentence_window or source_snippet, ADMINISTRATIVE_CUE_PATTERNS)),
        "evidence_class": None,
        "quality_category": None,
        "queue_disposition": None,
        "review_priority_tier": None,
        "quality_decision_rule": None,
        "exclusion_reason": None,
        "shadowed_by_event_review_id": None,
        "duplicate_group_id": None,
        "event_review_id": None,
        "review_status": "unreviewed",
        "corrected_event_date": None,
        "reviewer_note": None,
        "reviewed_at": None,
        "reviewer_id": None,
        "eligibility_status_for_validated_research": "ineligible_unreviewed",
    }


def _matched_cue_names(text: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    normalized = _normalized_text(text)
    return [name for name, pattern in patterns.items() if pattern.search(normalized)]


def _previous_sentence_boundary(text: str, anchor: int) -> int:
    last_positions = [text.rfind(marker, 0, anchor) for marker in ".!?\n"]
    position = max(last_positions)
    return 0 if position < 0 else position + 1


def _next_sentence_boundary(text: str, anchor: int) -> int:
    positions = [text.find(marker, anchor) for marker in ".!?\n"]
    valid = [position for position in positions if position >= 0]
    return len(text) if not valid else min(valid) + 1


def _sentence_context(text: str, phrase_start: int, phrase_end: int) -> tuple[str, str]:
    if not text:
        return "", ""

    sentence_start = _previous_sentence_boundary(text, phrase_start)
    sentence_end = _next_sentence_boundary(text, phrase_end)
    matched_sentence = text[sentence_start:sentence_end].strip()

    window_start = _previous_sentence_boundary(text, max(sentence_start - 1, 0)) if sentence_start > 0 else 0
    window_end = _next_sentence_boundary(text, min(sentence_end + 1, len(text))) if sentence_end < len(text) else len(text)
    sentence_window = text[window_start:window_end].strip()
    return matched_sentence, sentence_window


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
        ordered["_attachment_rank"] = ordered["attachment_score"].fillna(0.0).astype(float)
        ordered["_explicit_year_rank"] = ordered["explicit_year_indicator"].astype(int)
        ordered = ordered.sort_values(
            [
                "_specific_rank",
                "_purchase_rank",
                "_non_purchase_rank",
                "_attachment_rank",
                "confidence",
                "_explicit_year_rank",
                "filing_date",
                "accession_number",
                "raw_candidate_id",
            ],
            ascending=[False, False, True, False, False, False, False, True, True],
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
                "source_sentence": _string_or_none(canonical.get("source_sentence")),
                "source_sentence_window": _string_or_none(canonical.get("source_sentence_window")),
                "distance_to_purchase_phrase": canonical.get("distance_to_purchase_phrase"),
                "same_sentence_as_purchase_phrase": bool(canonical.get("same_sentence_as_purchase_phrase")),
                "same_clause_as_purchase_phrase": bool(canonical.get("same_clause_as_purchase_phrase")),
                "attachment_score": float(canonical.get("attachment_score", 0.0) or 0.0),
                "nearest_purchase_phrase": _string_or_none(canonical.get("nearest_purchase_phrase")),
                "truncated_snippet_boundary_indicator": bool(canonical.get("truncated_snippet_boundary_indicator")),
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
                "execution_cues": _string_or_none(canonical.get("execution_cues")),
                "prospective_cues": _string_or_none(canonical.get("prospective_cues")),
                "administrative_cues": _string_or_none(canonical.get("administrative_cues")),
                "evidence_class": None,
                "quality_category": None,
                "queue_disposition": None,
                "review_priority_tier": None,
                "quality_decision_rule": None,
                "exclusion_reason": None,
                "shadowed_by_event_review_id": None,
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


def _refine_review_queue(review_queue: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if review_queue.empty:
        empty = pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS)
        return empty.copy(), empty.copy()

    annotated = review_queue.copy()
    decisions = annotated.apply(_quality_decision, axis=1, result_type="expand")
    for column in decisions.columns:
        annotated[column] = decisions[column].values
    evidence = annotated.apply(_evidence_annotation, axis=1, result_type="expand")
    for column in evidence.columns:
        annotated[column] = evidence[column].values
    annotated = _apply_same_date_shadowing(annotated)

    primary_queue = annotated[annotated["queue_disposition"] == PRIMARY_QUEUE_DISPOSITION].copy()
    excluded_queue = annotated[annotated["queue_disposition"] == EXCLUDED_QUEUE_DISPOSITION].copy()
    return (
        primary_queue.reindex(columns=REVIEW_QUEUE_COLUMNS).reset_index(drop=True),
        excluded_queue.reindex(columns=REVIEW_QUEUE_COLUMNS).reset_index(drop=True),
    )


def _finalize_excluded_queue(excluded_queue: pd.DataFrame) -> pd.DataFrame:
    if excluded_queue.empty:
        return pd.DataFrame(columns=REVIEW_QUEUE_COLUMNS)

    finalized = excluded_queue.copy()
    finalized["review_status"] = "unreviewed"
    finalized["corrected_event_date"] = None
    finalized["reviewer_note"] = None
    finalized["reviewed_at"] = None
    finalized["reviewer_id"] = None
    finalized["eligibility_status_for_validated_research"] = "ineligible_excluded_from_primary_queue"
    finalized["effective_event_date"] = finalized["candidate_event_date"]
    finalized["included_in_event_study"] = False
    return finalized.reindex(columns=REVIEW_QUEUE_COLUMNS).reset_index(drop=True)


def _quality_decision(row: pd.Series) -> dict[str, object]:
    snippet = _normalized_text(_string_or_none(row.get("source_snippet")) or "")
    ambiguity_flags = set(_pipe_split_values(row.get("ambiguity_flags")))
    non_purchase_flags = set(_pipe_split_values(row.get("non_purchase_language_flags")))
    attachment_score = float(row.get("attachment_score", 0.0) or 0.0)
    recurring = bool(row.get("recurring_language_indicator"))
    likely_purchase = bool(row.get("likely_purchase_date_indicator"))
    inferred_year = bool(row.get("inferred_year_indicator"))
    same_sentence = bool(row.get("same_sentence_as_purchase_phrase"))
    same_clause = bool(row.get("same_clause_as_purchase_phrase"))
    truncated = bool(row.get("truncated_snippet_boundary_indicator"))
    strong_specific = any(pattern.search(snippet) for pattern in STRONG_SPECIFIC_PURCHASE_PATTERNS.values())
    strong_recurring = any(pattern.search(snippet) for pattern in STRONG_RECURRING_PURCHASE_PATTERNS.values())
    period_boundary_or_capacity = any(pattern.search(snippet) for pattern in PERIOD_BOUNDARY_OR_CAPACITY_PATTERNS.values())
    plan_history = (
        bool(non_purchase_flags.intersection({"plan_adoption", "board_approval", "shareholder_approval", "amendment", "termination"}))
        or PLAN_HISTORY_PATTERN.search(snippet) is not None
    )

    if strong_specific and attachment_score >= 0.55:
        return _decision(
            category="plausible_specific_purchase_date",
            tier="Tier1",
            disposition=PRIMARY_QUEUE_DISPOSITION,
            rule="strong_specific_purchase_language",
        )

    if strong_recurring and attachment_score >= 0.45:
        tier = (
            "Tier2"
            if (
                STRONG_RECURRING_PURCHASE_PATTERNS["purchase_date_on_or_before"].search(snippet) is not None
                or STRONG_RECURRING_PURCHASE_PATTERNS["purchase_date_definition_on_or_before"].search(snippet) is not None
                or same_clause
            )
            else "Tier3"
        )
        return _decision(
            category="plausible_recurring_purchase_schedule",
            tier=tier,
            disposition=PRIMARY_QUEUE_DISPOSITION,
            rule="explicit_recurring_purchase_schedule",
        )

    if period_boundary_or_capacity and attachment_score >= 0.65:
        return _decision(
            category="purchase_period_end_or_capacity_estimate",
            tier="Tier2",
            disposition=PRIMARY_QUEUE_DISPOSITION,
            rule="period_boundary_or_capacity_estimate_language",
        )

    if SUBSCRIPTION_CONTEXT_PATTERN.search(snippet):
        return _decision(
            category="subscription_or_enrollment_date",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="negative_context_subscription_date",
            exclusion_reason="subscription_or_enrollment_date",
        )

    if plan_history:
        return _decision(
            category="plan_history_or_amendment_restatement",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="negative_context_plan_history",
            exclusion_reason="plan_history_or_amendment_restatement",
        )

    if inferred_year and truncated:
        return _decision(
            category="multiple_dates_or_inferred_year_ambiguous",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="truncated_inferred_year_context",
            exclusion_reason="multiple_dates_or_inferred_year_ambiguous",
        )

    if STRONG_SNAPSHOT_CONTEXT_PATTERN.search(snippet):
        return _decision(
            category="reporting_snapshot_or_share_reserve_context",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="strong_snapshot_context",
            exclusion_reason="reporting_snapshot_or_share_reserve_context",
        )

    if OFFERING_MECHANICS_PATTERN.search(snippet) and not strong_specific and not strong_recurring:
        return _decision(
            category="offering_period_start_end_or_commencement",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="negative_context_offering_mechanics",
            exclusion_reason="offering_period_start_end_or_commencement",
        )

    if UNRELATED_CONTEXT_PATTERN.search(snippet):
        return _decision(
            category="unrelated_adjacent_corporate_or_financial_date",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="negative_context_unrelated_adjacent_date",
            exclusion_reason="unrelated_adjacent_corporate_or_financial_date",
        )

    if SNAPSHOT_CONTEXT_PATTERN.search(snippet) or SHARE_RESERVE_MECHANICS_PATTERN.search(snippet):
        if attachment_score < 0.8:
            return _decision(
                category="reporting_snapshot_or_share_reserve_context",
                tier=EXCLUDED_PRIORITY_TIER,
                disposition=EXCLUDED_QUEUE_DISPOSITION,
                rule="negative_context_reporting_snapshot",
                exclusion_reason="reporting_snapshot_or_share_reserve_context",
            )

    if "multiple_dates_in_context" in ambiguity_flags and attachment_score < 0.5 and not likely_purchase:
        return _decision(
            category="multiple_dates_or_inferred_year_ambiguous",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="multiple_dates_low_attachment",
            exclusion_reason="multiple_dates_or_inferred_year_ambiguous",
        )

    if inferred_year and attachment_score < 0.65:
        return _decision(
            category="multiple_dates_or_inferred_year_ambiguous",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="inferred_year_low_attachment",
            exclusion_reason="multiple_dates_or_inferred_year_ambiguous",
        )

    if recurring and likely_purchase and attachment_score >= 0.55 and same_sentence:
        return _decision(
            category="plausible_recurring_purchase_schedule",
            tier="Tier3",
            disposition=PRIMARY_QUEUE_DISPOSITION,
            rule="recurring_purchase_language_with_attachment",
        )

    if likely_purchase and attachment_score >= 0.65 and (same_sentence or same_clause):
        return _decision(
            category="plausible_specific_purchase_date",
            tier="Tier3",
            disposition=PRIMARY_QUEUE_DISPOSITION,
            rule="purchase_language_with_attachment",
        )

    if "multiple_dates_in_context" in ambiguity_flags and attachment_score < 0.65:
        return _decision(
            category="multiple_dates_or_inferred_year_ambiguous",
            tier=EXCLUDED_PRIORITY_TIER,
            disposition=EXCLUDED_QUEUE_DISPOSITION,
            rule="multiple_dates_unclear_attachment",
            exclusion_reason="multiple_dates_or_inferred_year_ambiguous",
        )

    return _decision(
        category="insufficient_context",
        tier=EXCLUDED_PRIORITY_TIER,
        disposition=EXCLUDED_QUEUE_DISPOSITION,
        rule="insufficient_purchase_attachment",
        exclusion_reason="insufficient_context",
    )


def _evidence_annotation(row: pd.Series) -> dict[str, object]:
    sentence_window = _normalized_text(
        _string_or_none(row.get("source_sentence_window"))
        or _string_or_none(row.get("source_sentence"))
        or _string_or_none(row.get("source_snippet"))
        or ""
    )
    execution_cues = _matched_cue_names(sentence_window, STRONG_SPECIFIC_PURCHASE_PATTERNS)
    prospective_cues = _matched_cue_names(sentence_window, PROSPECTIVE_CUE_PATTERNS)
    administrative_cues = _matched_cue_names(sentence_window, ADMINISTRATIVE_CUE_PATTERNS)
    quality_category = str(row.get("quality_category") or "").strip()

    if execution_cues:
        evidence_class = "executed_purchase_event"
    elif administrative_cues:
        evidence_class = "administrative_election_change"
    elif quality_category == "purchase_period_end_or_capacity_estimate":
        evidence_class = "purchase_period_end_or_capacity_estimate"
    elif prospective_cues or quality_category == "plausible_recurring_purchase_schedule":
        evidence_class = "recurring_purchase_schedule_or_definition"
    elif quality_category == "plausible_specific_purchase_date":
        evidence_class = "specific_purchase_reference_without_execution"
    else:
        evidence_class = "insufficient_or_excluded_context"

    return {
        "execution_cues": " | ".join(execution_cues),
        "prospective_cues": " | ".join(prospective_cues),
        "administrative_cues": " | ".join(administrative_cues),
        "evidence_class": evidence_class,
    }


def _decision(
    *,
    category: str,
    tier: str,
    disposition: str,
    rule: str,
    exclusion_reason: str | None = None,
    shadowed_by_event_review_id: str | None = None,
) -> dict[str, object]:
    return {
        "quality_category": category,
        "queue_disposition": disposition,
        "review_priority_tier": tier,
        "quality_decision_rule": rule,
        "exclusion_reason": exclusion_reason,
        "shadowed_by_event_review_id": shadowed_by_event_review_id,
    }


def _apply_same_date_shadowing(review_queue: pd.DataFrame) -> pd.DataFrame:
    if review_queue.empty:
        return review_queue

    shadowed = review_queue.copy()
    for _, group in shadowed.groupby(["ticker", "candidate_event_date"], dropna=False, sort=False):
        candidate_event_date = _string_or_none(group.iloc[0].get("candidate_event_date"))
        if not candidate_event_date:
            continue
        primary = group[group["queue_disposition"] == PRIMARY_QUEUE_DISPOSITION].copy()
        if len(primary) <= 1:
            continue
        primary["_tier_rank"] = primary["review_priority_tier"].map(_priority_rank)
        primary = primary.sort_values(
            ["_tier_rank", "attachment_score", "confidence", "duplicate_count", "canonical_filing_date", "event_review_id"],
            ascending=[True, False, False, False, False, True],
            ignore_index=True,
        )
        keeper = str(primary.loc[0, "event_review_id"])
        for event_review_id in primary.loc[1:, "event_review_id"].astype(str):
            row_mask = shadowed["event_review_id"].astype(str) == event_review_id
            shadowed.loc[row_mask, "quality_category"] = "duplicate_of_stronger_same_date_candidate"
            shadowed.loc[row_mask, "queue_disposition"] = EXCLUDED_QUEUE_DISPOSITION
            shadowed.loc[row_mask, "review_priority_tier"] = EXCLUDED_PRIORITY_TIER
            shadowed.loc[row_mask, "quality_decision_rule"] = "shadowed_by_same_date_primary_candidate"
            shadowed.loc[row_mask, "exclusion_reason"] = "shadowed_by_higher_priority_same_date_candidate"
            shadowed.loc[row_mask, "shadowed_by_event_review_id"] = keeper
    return shadowed


def _priority_rank(tier: object) -> int:
    value = str(tier or "").strip()
    if value == "Tier1":
        return 1
    if value == "Tier2":
        return 2
    if value == "Tier3":
        return 3
    return 99


def _apply_reviews(
    review_queue: pd.DataFrame,
    reviews: pd.DataFrame,
    *,
    require_review_for_validated_windows: bool,
    auto_policy_review: bool,
    review_as_of_date: date,
) -> pd.DataFrame:
    if review_queue.empty:
        return pd.DataFrame(columns=PHASE3_AUDIT_COLUMNS)

    audited = review_queue.copy()
    audited["review_status"] = "unreviewed"
    audited["corrected_event_date"] = None
    audited["reviewer_note"] = None
    audited["reviewed_at"] = None
    audited["reviewer_id"] = None

    if auto_policy_review:
        auto_reviews = audited.apply(
            lambda row: _auto_policy_review_row(row, review_as_of_date=review_as_of_date),
            axis=1,
            result_type="expand",
        )
        auto_matched = auto_reviews["review_status"].fillna("") != ""
        audited.loc[auto_matched, "review_status"] = auto_reviews.loc[auto_matched, "review_status"]
        audited.loc[auto_matched, "corrected_event_date"] = auto_reviews.loc[auto_matched, "corrected_event_date"].replace("", None)
        audited.loc[auto_matched, "reviewer_note"] = auto_reviews.loc[auto_matched, "reviewer_note"].replace("", None)
        audited.loc[auto_matched, "reviewed_at"] = auto_reviews.loc[auto_matched, "reviewed_at"].replace("", None)
        audited.loc[auto_matched, "reviewer_id"] = auto_reviews.loc[auto_matched, "reviewer_id"].replace("", None)

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


def _auto_policy_review_row(row: pd.Series, *, review_as_of_date: date) -> dict[str, object]:
    candidate_event_date = _string_or_none(row.get("candidate_event_date"))
    evidence_class = str(row.get("evidence_class") or "").strip()
    if not candidate_event_date:
        return _auto_review_result("", "")

    candidate_date = date.fromisoformat(candidate_event_date)
    if evidence_class == "executed_purchase_event":
        return _auto_review_result(
            "accepted",
            "Policy auto-review accepted explicit executed-event language.",
        )
    if evidence_class == "administrative_election_change":
        return _auto_review_result(
            "rejected",
            "Policy auto-review rejected administrative election-change language as non-purchase evidence.",
        )
    if evidence_class in {
        "purchase_period_end_or_capacity_estimate",
        "recurring_purchase_schedule_or_definition",
        "specific_purchase_reference_without_execution",
    }:
        review_status = "future_scheduled" if candidate_date > review_as_of_date else "unresolved"
        return _auto_review_result(
            review_status,
            f"Policy auto-review classified {evidence_class} without affirmative execution proof.",
        )
    return _auto_review_result("", "")


def _auto_review_result(review_status: str, reviewer_note: str) -> dict[str, object]:
    return {
        "review_status": review_status,
        "corrected_event_date": "",
        "reviewer_note": reviewer_note,
        "reviewed_at": "",
        "reviewer_id": "policy_auto_review" if review_status else "",
    }


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
    if review_status == "unresolved":
        return "ineligible_unresolved"
    if review_status == "future_scheduled":
        return "ineligible_future_scheduled"
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


def _attachment_metrics(snippet: str, phrase_start: int, phrase_end: int) -> AttachmentMetrics:
    truncated = phrase_start <= 0 or phrase_end >= len(snippet)
    purchase_matches = list(PURCHASE_KEYWORD_PATTERN.finditer(snippet))
    if not purchase_matches:
        return AttachmentMetrics(
            distance_to_purchase_phrase=None,
            same_sentence_as_purchase_phrase=False,
            same_clause_as_purchase_phrase=False,
            attachment_score=0.0,
            nearest_purchase_phrase=None,
            truncated_snippet_boundary_indicator=truncated,
        )

    best_match = min(
        purchase_matches,
        key=lambda match: _span_distance(phrase_start, phrase_end, match.start(), match.end()),
    )
    distance = _span_distance(phrase_start, phrase_end, best_match.start(), best_match.end())
    same_sentence = _same_segment(snippet, phrase_start, phrase_end, best_match.start(), best_match.end(), SENTENCE_BOUNDARY_PATTERN)
    same_clause = _same_segment(snippet, phrase_start, phrase_end, best_match.start(), best_match.end(), CLAUSE_BOUNDARY_PATTERN)

    score = 0.0
    if same_sentence:
        score += 0.35
    if same_clause:
        score += 0.25
    if distance == 0:
        score += 0.30
    elif distance <= 20:
        score += 0.25
    elif distance <= 40:
        score += 0.20
    elif distance <= 80:
        score += 0.10
    if any(pattern.search(snippet) for pattern in STRONG_SPECIFIC_PURCHASE_PATTERNS.values()):
        score += 0.15
    elif any(pattern.search(snippet) for pattern in STRONG_RECURRING_PURCHASE_PATTERNS.values()):
        score += 0.10
    if truncated and distance > 20:
        score -= 0.15

    return AttachmentMetrics(
        distance_to_purchase_phrase=distance,
        same_sentence_as_purchase_phrase=same_sentence,
        same_clause_as_purchase_phrase=same_clause,
        attachment_score=round(max(0.0, min(1.0, score)), 3),
        nearest_purchase_phrase=best_match.group(0),
        truncated_snippet_boundary_indicator=truncated,
    )


def _span_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def _same_segment(
    text: str,
    a_start: int,
    a_end: int,
    b_start: int,
    b_end: int,
    boundary_pattern: re.Pattern[str],
) -> bool:
    segment_start, segment_end = _segment_bounds(text, int((a_start + a_end) / 2), boundary_pattern)
    return b_start >= segment_start and b_end <= segment_end


def _segment_bounds(text: str, anchor: int, boundary_pattern: re.Pattern[str]) -> tuple[int, int]:
    prior_end = 0
    for match in boundary_pattern.finditer(text[:anchor]):
        prior_end = match.end()
    next_start = len(text)
    upcoming = boundary_pattern.search(text, anchor)
    if upcoming is not None:
        next_start = upcoming.start()
    return prior_end, next_start


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


def _pipe_split_values(value: object) -> list[str]:
    if value is None:
        return []
    items: list[str] = []
    for part in str(value).split("|"):
        stripped = part.strip()
        if stripped and stripped.lower() != "nan":
            items.append(stripped)
    return items


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    string_value = str(value).strip()
    if string_value == "" or string_value.lower() == "nan":
        return None
    return string_value
