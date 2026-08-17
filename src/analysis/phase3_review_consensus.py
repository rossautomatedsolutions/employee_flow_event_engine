from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.analysis.phase3_review_packet import REVIEW_DECISION_COLUMNS
from src.pipeline.phase3_candidates import load_phase3_candidate_reviews

REVIEWER_A_FILE_NAME = "review_decisions_reviewer_a.csv"
REVIEWER_B_FILE_NAME = "review_decisions_reviewer_b.csv"
CONSENSUS_AUDIT_FILE_NAME = "review_consensus_audit.csv"
CONSENSUS_DECISIONS_FILE_NAME = "review_consensus_decisions.csv"
CONSENSUS_MARKDOWN_FILE_NAME = "review_consensus_summary.md"

CONSENSUS_AUDIT_COLUMNS = [
    "event_review_id",
    "ticker",
    "issuer_name",
    "candidate_event_date",
    "review_priority_tier",
    "quality_category",
    "reviewer_a_status",
    "reviewer_a_corrected_event_date",
    "reviewer_a_note",
    "reviewer_a_reviewed_at",
    "reviewer_a_id",
    "reviewer_b_status",
    "reviewer_b_corrected_event_date",
    "reviewer_b_note",
    "reviewer_b_reviewed_at",
    "reviewer_b_id",
    "consensus_review_status",
    "consensus_corrected_event_date",
    "auto_resolution_eligible",
    "manual_resolution_required",
    "resolution_status",
    "resolution_reason",
]


@dataclass(slots=True)
class Phase3ReviewConsensusArtifacts:
    reviewer_a_template: pd.DataFrame
    reviewer_b_template: pd.DataFrame
    consensus_audit: pd.DataFrame
    consensus_decisions: pd.DataFrame
    summary_markdown: str


def build_phase3_review_consensus_artifacts(
    review_queue: pd.DataFrame | None,
    reviewer_a_reviews: pd.DataFrame | None,
    reviewer_b_reviews: pd.DataFrame | None,
) -> Phase3ReviewConsensusArtifacts:
    queue = review_queue.copy() if review_queue is not None else pd.DataFrame()
    template = _build_decisions_template(queue)
    reviewer_a_template = _tag_template(template, reviewer_id="reviewer_a")
    reviewer_b_template = _tag_template(template, reviewer_id="reviewer_b")

    if queue.empty:
        empty_audit = pd.DataFrame(columns=CONSENSUS_AUDIT_COLUMNS)
        return Phase3ReviewConsensusArtifacts(
            reviewer_a_template=reviewer_a_template,
            reviewer_b_template=reviewer_b_template,
            consensus_audit=empty_audit,
            consensus_decisions=pd.DataFrame(columns=REVIEW_DECISION_COLUMNS),
            summary_markdown=render_phase3_review_consensus_summary(empty_audit),
        )

    reviewer_a_lookup = _review_lookup(reviewer_a_reviews)
    reviewer_b_lookup = _review_lookup(reviewer_b_reviews)
    audit_rows: list[dict[str, object]] = []
    decision_rows: list[dict[str, str]] = []
    consensus_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    ordered_queue = queue.sort_values(
        ["ticker", "_priority_rank", "candidate_event_date", "event_review_id"],
        ignore_index=True,
    ) if "_priority_rank" in queue.columns else queue.sort_values(
        ["ticker", "candidate_event_date", "event_review_id"],
        ignore_index=True,
    )

    for row in ordered_queue.itertuples(index=False):
        event_review_id = str(getattr(row, "event_review_id", "") or "")
        candidate_event_date = _string_or_empty(getattr(row, "candidate_event_date", ""))
        reviewer_a = reviewer_a_lookup.get(event_review_id, _empty_review_record("reviewer_a"))
        reviewer_b = reviewer_b_lookup.get(event_review_id, _empty_review_record("reviewer_b"))
        resolution = _resolve_consensus(
            reviewer_a_status=reviewer_a["review_status"],
            reviewer_a_corrected_event_date=reviewer_a["corrected_event_date"],
            reviewer_b_status=reviewer_b["review_status"],
            reviewer_b_corrected_event_date=reviewer_b["corrected_event_date"],
        )

        audit_rows.append(
            {
                "event_review_id": event_review_id,
                "ticker": _string_or_empty(getattr(row, "ticker", "")),
                "issuer_name": _string_or_empty(getattr(row, "issuer_name", "")),
                "candidate_event_date": candidate_event_date,
                "review_priority_tier": _string_or_empty(getattr(row, "review_priority_tier", "")),
                "quality_category": _string_or_empty(getattr(row, "quality_category", "")),
                "reviewer_a_status": reviewer_a["review_status"],
                "reviewer_a_corrected_event_date": reviewer_a["corrected_event_date"],
                "reviewer_a_note": reviewer_a["reviewer_note"],
                "reviewer_a_reviewed_at": reviewer_a["reviewed_at"],
                "reviewer_a_id": reviewer_a["reviewer_id"],
                "reviewer_b_status": reviewer_b["review_status"],
                "reviewer_b_corrected_event_date": reviewer_b["corrected_event_date"],
                "reviewer_b_note": reviewer_b["reviewer_note"],
                "reviewer_b_reviewed_at": reviewer_b["reviewed_at"],
                "reviewer_b_id": reviewer_b["reviewer_id"],
                "consensus_review_status": resolution["review_status"],
                "consensus_corrected_event_date": resolution["corrected_event_date"],
                "auto_resolution_eligible": resolution["auto_resolution_eligible"],
                "manual_resolution_required": resolution["manual_resolution_required"],
                "resolution_status": resolution["resolution_status"],
                "resolution_reason": resolution["resolution_reason"],
            }
        )

        reviewer_note = _consensus_note(
            resolution_status=resolution["resolution_status"],
            resolution_reason=resolution["resolution_reason"],
            reviewer_a_status=reviewer_a["review_status"],
            reviewer_b_status=reviewer_b["review_status"],
            corrected_event_date=resolution["corrected_event_date"],
        )
        decision_rows.append(
            {
                "event_review_id": event_review_id,
                "ticker": _string_or_empty(getattr(row, "ticker", "")),
                "issuer_name": _string_or_empty(getattr(row, "issuer_name", "")),
                "candidate_event_date": candidate_event_date,
                "original_assigned_event_date": candidate_event_date,
                "review_status": resolution["review_status"],
                "corrected_event_date": resolution["corrected_event_date"],
                "reviewer_note": reviewer_note,
                "reviewed_at": consensus_timestamp if resolution["auto_resolution_eligible"] else "",
                "reviewer_id": "dual_review_consensus" if resolution["auto_resolution_eligible"] else "",
            }
        )

    consensus_audit = pd.DataFrame(audit_rows).reindex(columns=CONSENSUS_AUDIT_COLUMNS)
    consensus_decisions = pd.DataFrame(decision_rows).reindex(columns=REVIEW_DECISION_COLUMNS)
    return Phase3ReviewConsensusArtifacts(
        reviewer_a_template=reviewer_a_template,
        reviewer_b_template=reviewer_b_template,
        consensus_audit=consensus_audit,
        consensus_decisions=consensus_decisions,
        summary_markdown=render_phase3_review_consensus_summary(consensus_audit),
    )


def render_phase3_review_consensus_summary(consensus_audit: pd.DataFrame | None) -> str:
    audit = consensus_audit.copy() if consensus_audit is not None else pd.DataFrame(columns=CONSENSUS_AUDIT_COLUMNS)
    if audit.empty:
        return "\n".join(
            [
                "# Review Consensus Summary",
                "",
                "- Candidate rows: 0",
                "- Auto-resolved rows: 0",
                "- Manual resolution required rows: 0",
                "",
                "No retained review candidates are present.",
                "",
            ]
        )

    resolution_counts = audit["resolution_status"].fillna("unknown").value_counts().to_dict()
    auto_resolved = audit[audit["auto_resolution_eligible"]].copy()
    manual_required = audit[audit["manual_resolution_required"]].copy()
    lines = [
        "# Review Consensus Summary",
        "",
        f"- Candidate rows: {len(audit)}",
        f"- Auto-resolved rows: {int(audit['auto_resolution_eligible'].sum())}",
        f"- Auto-resolved accepted: {int((audit['resolution_status'] == 'agreed_accepted').sum())}",
        f"- Auto-resolved corrected: {int((audit['resolution_status'] == 'agreed_corrected').sum())}",
        f"- Auto-resolved rejected: {int((audit['resolution_status'] == 'agreed_rejected').sum())}",
        f"- Auto-resolved unresolved: {int((audit['resolution_status'] == 'agreed_unresolved').sum())}",
        f"- Auto-resolved future_scheduled: {int((audit['resolution_status'] == 'agreed_future_scheduled').sum())}",
        f"- Manual resolution required rows: {int(audit['manual_resolution_required'].sum())}",
        f"- Pipeline-ready review file: `{CONSENSUS_DECISIONS_FILE_NAME}`",
        "",
        "## Resolution Counts",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(resolution_counts.items()))

    lines.extend(["", "## Auto-Resolved", ""])
    if auto_resolved.empty:
        lines.append("- none")
    else:
        for row in auto_resolved.itertuples(index=False):
            corrected_suffix = (
                f" -> {row.consensus_corrected_event_date}" if _string_or_empty(row.consensus_corrected_event_date) else ""
            )
            lines.append(f"- {row.event_review_id}: {row.consensus_review_status}{corrected_suffix}")

    lines.extend(["", "## Manual Resolution Required", ""])
    if manual_required.empty:
        lines.append("- none")
    else:
        for row in manual_required.itertuples(index=False):
            lines.append(f"- {row.event_review_id}: {row.resolution_reason}")

    lines.append("")
    return "\n".join(lines)


def write_phase3_review_consensus_artifacts(output_dir: Path, review_queue: pd.DataFrame | None) -> dict[str, Path]:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    reviewer_a_path = output_dir / REVIEWER_A_FILE_NAME
    reviewer_b_path = output_dir / REVIEWER_B_FILE_NAME
    existing_reviewer_a = load_phase3_candidate_reviews(reviewer_a_path)
    existing_reviewer_b = load_phase3_candidate_reviews(reviewer_b_path)
    artifacts = build_phase3_review_consensus_artifacts(review_queue, existing_reviewer_a, existing_reviewer_b)

    _write_or_preserve_template(reviewer_a_path, artifacts.reviewer_a_template)
    _write_or_preserve_template(reviewer_b_path, artifacts.reviewer_b_template)

    refreshed_reviewer_a = load_phase3_candidate_reviews(reviewer_a_path)
    refreshed_reviewer_b = load_phase3_candidate_reviews(reviewer_b_path)
    final_artifacts = build_phase3_review_consensus_artifacts(review_queue, refreshed_reviewer_a, refreshed_reviewer_b)

    consensus_audit_path = output_dir / CONSENSUS_AUDIT_FILE_NAME
    consensus_decisions_path = output_dir / CONSENSUS_DECISIONS_FILE_NAME
    summary_path = reports_dir / CONSENSUS_MARKDOWN_FILE_NAME

    final_artifacts.consensus_audit.to_csv(consensus_audit_path, index=False)
    final_artifacts.consensus_decisions.to_csv(consensus_decisions_path, index=False)
    summary_path.write_text(final_artifacts.summary_markdown, encoding="utf-8")

    return {
        "reviewer_a": reviewer_a_path,
        "reviewer_b": reviewer_b_path,
        "consensus_audit": consensus_audit_path,
        "consensus_decisions": consensus_decisions_path,
        "summary_markdown": summary_path,
    }


def _tag_template(template: pd.DataFrame, *, reviewer_id: str) -> pd.DataFrame:
    tagged = template.copy()
    if tagged.empty:
        return tagged
    tagged["reviewer_id"] = reviewer_id
    return tagged.reindex(columns=REVIEW_DECISION_COLUMNS)


def _build_decisions_template(review_queue: pd.DataFrame) -> pd.DataFrame:
    if review_queue.empty:
        return pd.DataFrame(columns=REVIEW_DECISION_COLUMNS)
    template = review_queue.copy()
    sort_columns = [column for column in ("ticker", "candidate_event_date", "event_review_id") if column in template.columns]
    if sort_columns:
        template = template.sort_values(sort_columns, ignore_index=True)
    return pd.DataFrame(
        {
            "event_review_id": template.get("event_review_id", pd.Series(dtype=str)).fillna("").astype(str),
            "ticker": template.get("ticker", pd.Series(dtype=str)).fillna("").astype(str),
            "issuer_name": template.get("issuer_name", pd.Series(dtype=str)).fillna("").astype(str),
            "candidate_event_date": template.get("candidate_event_date", pd.Series(dtype=str)).fillna("").astype(str),
            "original_assigned_event_date": template.get("candidate_event_date", pd.Series(dtype=str)).fillna("").astype(str),
            "review_status": "",
            "corrected_event_date": "",
            "reviewer_note": "",
            "reviewed_at": "",
            "reviewer_id": "",
        }
    ).reindex(columns=REVIEW_DECISION_COLUMNS)


def _review_lookup(reviews: pd.DataFrame | None) -> dict[str, dict[str, str]]:
    if reviews is None or reviews.empty:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    for row in reviews.fillna("").itertuples(index=False):
        event_review_id = str(getattr(row, "event_review_id", "") or "").strip()
        if not event_review_id:
            continue
        lookup[event_review_id] = {
            "review_status": str(getattr(row, "review_status", "") or "").strip().lower() or "unreviewed",
            "corrected_event_date": _string_or_empty(getattr(row, "corrected_event_date", "")),
            "reviewer_note": _string_or_empty(getattr(row, "reviewer_note", "")),
            "reviewed_at": _string_or_empty(getattr(row, "reviewed_at", "")),
            "reviewer_id": _string_or_empty(getattr(row, "reviewer_id", "")),
        }
    return lookup


def _empty_review_record(default_reviewer_id: str) -> dict[str, str]:
    return {
        "review_status": "unreviewed",
        "corrected_event_date": "",
        "reviewer_note": "",
        "reviewed_at": "",
        "reviewer_id": default_reviewer_id,
    }


def _resolve_consensus(
    *,
    reviewer_a_status: str,
    reviewer_a_corrected_event_date: str,
    reviewer_b_status: str,
    reviewer_b_corrected_event_date: str,
) -> dict[str, object]:
    if reviewer_a_status == reviewer_b_status == "accepted":
        return _resolution("accepted", "", True, False, "agreed_accepted", "Both reviewers accepted the candidate date.")
    if reviewer_a_status == reviewer_b_status == "rejected":
        return _resolution("rejected", "", True, False, "agreed_rejected", "Both reviewers rejected the candidate.")
    if reviewer_a_status == reviewer_b_status == "unresolved":
        return _resolution(
            "unresolved",
            "",
            True,
            False,
            "agreed_unresolved",
            "Both reviewers agreed that the text remains insufficient to validate an observed purchase event.",
        )
    if reviewer_a_status == reviewer_b_status == "future_scheduled":
        return _resolution(
            "future_scheduled",
            "",
            True,
            False,
            "agreed_future_scheduled",
            "Both reviewers agreed that the text establishes a future schedule that is still ineligible for historical event-study use.",
        )
    if reviewer_a_status == reviewer_b_status == "corrected":
        if reviewer_a_corrected_event_date and reviewer_a_corrected_event_date == reviewer_b_corrected_event_date:
            return _resolution(
                "corrected",
                reviewer_a_corrected_event_date,
                True,
                False,
                "agreed_corrected",
                f"Both reviewers corrected the candidate to {reviewer_a_corrected_event_date}.",
            )
        return _resolution(
            "unreviewed",
            "",
            False,
            True,
            "corrected_date_disagreement",
            "Both reviewers chose corrected but did not agree on the replacement date.",
        )
    if reviewer_a_status == reviewer_b_status == "unreviewed":
        return _resolution(
            "unreviewed",
            "",
            False,
            True,
            "agreed_unreviewed",
            "Both reviewers left the candidate operationally unreviewed.",
        )
    if "unreviewed" in {reviewer_a_status, reviewer_b_status}:
        return _resolution(
            "unreviewed",
            "",
            False,
            True,
            "one_reviewer_unreviewed",
            "One reviewer made a decision while the other left the candidate operationally unreviewed.",
        )
    return _resolution(
        "unreviewed",
        "",
        False,
        True,
        "status_disagreement",
        f"Reviewer statuses disagreed ({reviewer_a_status} vs {reviewer_b_status}).",
    )


def _resolution(
    review_status: str,
    corrected_event_date: str,
    auto_resolution_eligible: bool,
    manual_resolution_required: bool,
    resolution_status: str,
    resolution_reason: str,
) -> dict[str, object]:
    return {
        "review_status": review_status,
        "corrected_event_date": corrected_event_date,
        "auto_resolution_eligible": auto_resolution_eligible,
        "manual_resolution_required": manual_resolution_required,
        "resolution_status": resolution_status,
        "resolution_reason": resolution_reason,
    }


def _consensus_note(
    *,
    resolution_status: str,
    resolution_reason: str,
    reviewer_a_status: str,
    reviewer_b_status: str,
    corrected_event_date: str,
) -> str:
    if resolution_status == "agreed_corrected" and corrected_event_date:
        return f"Auto-resolved from dual reviewer agreement. Both reviewers corrected the candidate to {corrected_event_date}."
    if resolution_status in {"agreed_accepted", "agreed_rejected", "agreed_unresolved", "agreed_future_scheduled"}:
        return f"Auto-resolved from dual reviewer agreement. Both reviewers marked the candidate as {reviewer_a_status}."
    if resolution_status == "agreed_unreviewed":
        return "Manual resolution required: both reviewers left the candidate operationally unreviewed. See review_consensus_audit.csv."
    return (
        "Manual resolution required: "
        f"{resolution_reason} Reviewer A={reviewer_a_status}; Reviewer B={reviewer_b_status}. "
        "See review_consensus_audit.csv."
    )


def _write_or_preserve_template(path: Path, template: pd.DataFrame) -> None:
    if path.exists():
        existing = pd.read_csv(path, dtype=str).fillna("")
        canonical = _align_existing_template(existing, template, path=path)
        if not _normalized_review_frame(existing).equals(_normalized_review_frame(canonical)):
            canonical.to_csv(path, index=False)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(path, index=False)


def _align_existing_template(existing: pd.DataFrame, template: pd.DataFrame, *, path: Path) -> pd.DataFrame:
    if "event_review_id" not in existing.columns:
        raise ValueError(f"Existing reviewer decision template is missing event_review_id: {path}")

    existing_ids = existing["event_review_id"].astype(str).str.strip()
    expected_ids = template.get("event_review_id", pd.Series(dtype=str)).astype(str).str.strip()
    if existing_ids.duplicated().any():
        raise ValueError(f"Existing reviewer decision template contains duplicate event_review_id values: {path}")
    if sorted(existing_ids.tolist()) != sorted(expected_ids.tolist()):
        raise ValueError(
            "Existing reviewer decision template does not match the current stable candidate IDs; "
            f"refusing to overwrite {path}"
        )

    existing_by_id = existing.assign(event_review_id=existing_ids).set_index("event_review_id")
    aligned = template.copy()
    for column in REVIEW_DECISION_COLUMNS:
        if column == "event_review_id" or column not in existing_by_id.columns:
            continue
        existing_values = existing_by_id[column].reindex(expected_ids.tolist()).fillna("").astype(str).tolist()
        default_values = aligned[column].fillna("").astype(str).tolist()
        aligned[column] = [
            existing_value if existing_value != "" else default_value
            for existing_value, default_value in zip(existing_values, default_values)
        ]
    return aligned.reindex(columns=REVIEW_DECISION_COLUMNS)


def _normalized_review_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy().reindex(columns=REVIEW_DECISION_COLUMNS).fillna("")
    for column in normalized.columns:
        normalized[column] = normalized[column].astype(str)
    normalized["event_review_id"] = normalized["event_review_id"].str.strip()
    return normalized.reset_index(drop=True)


def _string_or_empty(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text
