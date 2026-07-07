from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(slots=True)
class Phase3CandidateQualityArtifacts:
    comparison: pd.DataFrame
    counts: pd.DataFrame
    markdown: str


CATEGORY_REFINEMENTS = {
    "plausible_specific_purchase_date": "Keep in the primary queue when the filing ties the date directly to exercised purchase rights or an explicitly bounded current purchase period.",
    "plausible_recurring_purchase_schedule": "Keep recurring purchase dates in the primary queue when purchase-language attachment is strong, but tier them below issuer-specific exercised-purchase disclosures.",
    "offering_period_start_end_or_commencement": "Exclude offering-period mechanics unless the snippet also states a purchase date in the same clause or sentence.",
    "subscription_or_enrollment_date": "Exclude subscription and enrollment dates from the primary queue while retaining them in the audit trail.",
    "plan_history_or_amendment_restatement": "Exclude amendment, restatement, approval, and historical plan-adoption dates from the primary queue.",
    "reporting_snapshot_or_share_reserve_context": "Exclude as-of snapshots, share-reserve footnotes, eligibility counts, and market-price snapshots unless a stronger same-date purchase anchor overrides them.",
    "unrelated_adjacent_corporate_or_financial_date": "Exclude unrelated operational or financial dates that sit near ESPP text but are not attached to a purchase action.",
    "multiple_dates_or_inferred_year_ambiguous": "Exclude low-attachment multi-date or inferred-year rows, especially when the snippet is truncated at the extraction boundary.",
    "duplicate_of_stronger_same_date_candidate": "Exclude lower-priority same-date duplicates when a stronger candidate for the same issuer/date remains in the primary queue.",
    "insufficient_context": "Exclude rows whose date text does not stay close enough to purchase language to justify review priority.",
}


def build_phase3_candidate_quality_artifacts(
    pre_refinement_queue: pd.DataFrame | None,
    review_queue: pd.DataFrame | None,
    excluded_queue: pd.DataFrame | None,
) -> Phase3CandidateQualityArtifacts:
    before_frame = _normalized_frame(pre_refinement_queue)
    primary_frame = _normalized_frame(review_queue)
    excluded_frame = _normalized_frame(excluded_queue)
    combined = pd.concat([primary_frame, excluded_frame], ignore_index=True) if not (primary_frame.empty and excluded_frame.empty) else pd.DataFrame()

    comparison = pd.DataFrame(
        [
            {"metric": "canonical_candidates_before_refinement", "before_refinement": int(len(before_frame)), "after_refinement": int(len(before_frame))},
            {"metric": "primary_review_queue_candidates", "before_refinement": int(len(before_frame)), "after_refinement": int(len(primary_frame))},
            {"metric": "excluded_candidates", "before_refinement": 0, "after_refinement": int(len(excluded_frame))},
            {"metric": "tier1_candidates", "before_refinement": 0, "after_refinement": int((combined.get("review_priority_tier", pd.Series(dtype=str)) == "Tier1").sum())},
            {"metric": "tier2_candidates", "before_refinement": 0, "after_refinement": int((combined.get("review_priority_tier", pd.Series(dtype=str)) == "Tier2").sum())},
            {"metric": "tier3_candidates", "before_refinement": 0, "after_refinement": int((combined.get("review_priority_tier", pd.Series(dtype=str)) == "Tier3").sum())},
            {"metric": "excluded_from_primary_queue", "before_refinement": 0, "after_refinement": int((combined.get("queue_disposition", pd.Series(dtype=str)) == "excluded_from_primary_queue").sum())},
        ]
    )

    counts = pd.concat(
        [
            _dimension_counts(combined, dimension="issuer", column="ticker"),
            _dimension_counts(combined, dimension="extraction_rule", column="extraction_rule"),
            _dimension_counts(combined, dimension="confidence", column="confidence"),
            _dimension_counts(combined, dimension="ambiguity_flag", column="ambiguity_flags", split_pipe=True),
            _dimension_counts(combined, dimension="review_priority_tier", column="review_priority_tier"),
            _dimension_counts(combined, dimension="quality_category", column="quality_category"),
            _dimension_counts(combined, dimension="queue_disposition", column="queue_disposition"),
        ],
        ignore_index=True,
    ) if not combined.empty else pd.DataFrame(columns=["dimension", "value", "queue_disposition", "count"])

    return Phase3CandidateQualityArtifacts(
        comparison=comparison,
        counts=counts,
        markdown=render_phase3_candidate_quality_markdown(before_frame, primary_frame, excluded_frame, combined),
    )


def render_phase3_candidate_quality_markdown(
    before_frame: pd.DataFrame,
    primary_frame: pd.DataFrame,
    excluded_frame: pd.DataFrame,
    combined: pd.DataFrame,
) -> str:
    lines = [
        "# Phase 3 Candidate Quality Audit",
        "",
        "## Queue Summary",
        "",
        f"- Canonical candidates before refinement: {len(before_frame)}",
        f"- Primary review queue after refinement: {len(primary_frame)}",
        f"- Excluded candidates after refinement: {len(excluded_frame)}",
        f"- Tier1 candidates: {int((combined.get('review_priority_tier', pd.Series(dtype=str)) == 'Tier1').sum())}",
        f"- Tier2 candidates: {int((combined.get('review_priority_tier', pd.Series(dtype=str)) == 'Tier2').sum())}",
        f"- Tier3 candidates: {int((combined.get('review_priority_tier', pd.Series(dtype=str)) == 'Tier3').sum())}",
        "",
        "## Category Audit",
        "",
    ]

    if combined.empty or "quality_category" not in combined.columns:
        lines.append("- none")
        return "\n".join(lines) + "\n"

    categories = combined["quality_category"].fillna("uncategorized").value_counts().to_dict()
    for category, count in categories.items():
        subset = combined[combined["quality_category"].fillna("uncategorized") == category].copy()
        issuers = ", ".join(sorted(subset["ticker"].dropna().astype(str).unique().tolist())) or "none"
        rules = ", ".join(
            f"{rule} ({value})"
            for rule, value in subset["extraction_rule"].fillna("unknown").value_counts().to_dict().items()
        ) or "none"
        queue_mix = ", ".join(
            f"{label}={value}"
            for label, value in subset["queue_disposition"].fillna("unknown").value_counts().to_dict().items()
        ) or "none"
        ambiguity = ", ".join(
            f"{label} ({value})"
            for label, value in _pipe_value_counts(subset.get("ambiguity_flags", pd.Series(dtype=str))).items()
        ) or "none"
        non_purchase = ", ".join(
            f"{label} ({value})"
            for label, value in _pipe_value_counts(subset.get("non_purchase_language_flags", pd.Series(dtype=str))).items()
        ) or "none"
        phrases = "; ".join(_sample_strings(subset.get("source_phrase", pd.Series(dtype=str)))) or "none"
        lines.extend(
            [
                f"### {_humanize(category)}",
                "",
                f"- Candidate count: {count}",
                f"- Issuers: {issuers}",
                f"- Queue outcome: {queue_mix}",
                f"- Extraction rules: {rules}",
                f"- Current ambiguity flags: {ambiguity}",
                f"- Current non-purchase flags: {non_purchase}",
                f"- Common phrases or structures: {phrases}",
                f"- Deterministic refinement: {CATEGORY_REFINEMENTS.get(category, 'Retain deterministic classification and audit visibility for this category.')}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def write_phase3_candidate_quality_reports(
    output_dir: Path,
    pre_refinement_queue: pd.DataFrame | None,
    review_queue: pd.DataFrame | None,
    excluded_queue: pd.DataFrame | None,
) -> dict[str, Path]:
    artifacts = build_phase3_candidate_quality_artifacts(pre_refinement_queue, review_queue, excluded_queue)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    comparison_path = output_dir / "candidate_quality_before_after.csv"
    counts_path = output_dir / "candidate_quality_counts.csv"
    markdown_path = reports_dir / "candidate_quality_audit.md"

    artifacts.comparison.to_csv(comparison_path, index=False)
    artifacts.counts.to_csv(counts_path, index=False)
    markdown_path.write_text(artifacts.markdown, encoding="utf-8")

    return {
        "comparison": comparison_path,
        "counts": counts_path,
        "markdown": markdown_path,
    }


def _normalized_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame.copy() if frame is not None else pd.DataFrame()


def _dimension_counts(
    frame: pd.DataFrame,
    *,
    dimension: str,
    column: str,
    split_pipe: bool = False,
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=["dimension", "value", "queue_disposition", "count"])

    rows: list[dict[str, object]] = []
    for disposition, group in frame.groupby(frame.get("queue_disposition", pd.Series(dtype=str)).fillna("unknown"), dropna=False):
        if split_pipe:
            counts = _pipe_value_counts(group[column])
            for value, count in counts.items():
                rows.append({"dimension": dimension, "value": value, "queue_disposition": disposition, "count": int(count)})
            continue
        counts = group[column].fillna("unknown").astype(str).value_counts().to_dict()
        for value, count in counts.items():
            rows.append({"dimension": dimension, "value": value, "queue_disposition": disposition, "count": int(count)})
    return pd.DataFrame(rows)


def _pipe_value_counts(values: pd.Series) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values.fillna("").astype(str):
        for part in [candidate.strip() for candidate in value.split("|")]:
            if not part or part.lower() == "nan":
                continue
            counts[part] = counts.get(part, 0) + 1
    return dict(sorted(counts.items()))


def _sample_strings(values: pd.Series, limit: int = 3) -> list[str]:
    samples: list[str] = []
    for value in values.fillna("").astype(str):
        cleaned = " ".join(value.split())
        if not cleaned or cleaned.lower() == "nan":
            continue
        if cleaned not in samples:
            samples.append(cleaned[:120] + ("..." if len(cleaned) > 120 else ""))
        if len(samples) >= limit:
            break
    return samples


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()
