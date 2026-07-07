from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PACKET_FILE_NAME = "candidate_review_packet.csv"
PACKET_MARKDOWN_FILE_NAME = "candidate_review_packet.md"
DECISIONS_FILE_NAME = "review_decisions.csv"
INSTRUCTIONS_FILE_NAME = "review_workflow_instructions.md"

REVIEW_PACKET_COLUMNS = [
    "stable_candidate_id",
    "ticker",
    "issuer_name",
    "cik",
    "candidate_event_date",
    "priority_tier",
    "classification",
    "confidence",
    "filing_form",
    "filing_date",
    "accession_number",
    "source_phrase",
    "bounded_source_snippet",
    "matched_espp_terms",
    "purchase_language_attachment_score",
    "same_sentence_indicator",
    "same_clause_indicator",
    "explicit_year_indicator",
    "inferred_year_indicator",
    "recurring_language_indicator",
    "specific_date_indicator",
    "ambiguity_flags",
    "duplicate_count",
    "contributing_accession_numbers",
    "canonical_selection_reason",
    "plain_language_review_question",
]

REVIEW_DECISION_COLUMNS = [
    "event_review_id",
    "ticker",
    "issuer_name",
    "candidate_event_date",
    "original_assigned_event_date",
    "review_status",
    "corrected_event_date",
    "reviewer_note",
    "reviewed_at",
    "reviewer_id",
]


@dataclass(slots=True)
class Phase3ReviewPacketArtifacts:
    packet_frame: pd.DataFrame
    decisions_template: pd.DataFrame
    packet_markdown: str
    instructions_markdown: str


def build_phase3_review_packet_artifacts(review_queue: pd.DataFrame | None) -> Phase3ReviewPacketArtifacts:
    queue = _normalized_frame(review_queue)
    packet_frame = _packet_frame(queue)
    decisions_template = _decisions_template(queue)
    packet_markdown = render_phase3_review_packet_markdown(packet_frame)
    instructions_markdown = render_phase3_review_workflow_instructions()
    return Phase3ReviewPacketArtifacts(
        packet_frame=packet_frame,
        decisions_template=decisions_template,
        packet_markdown=packet_markdown,
        instructions_markdown=instructions_markdown,
    )


def write_phase3_review_packet_artifacts(output_dir: Path, review_queue: pd.DataFrame | None) -> dict[str, Path]:
    artifacts = build_phase3_review_packet_artifacts(review_queue)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    packet_csv_path = output_dir / PACKET_FILE_NAME
    packet_md_path = reports_dir / PACKET_MARKDOWN_FILE_NAME
    decisions_path = output_dir / DECISIONS_FILE_NAME
    instructions_path = reports_dir / INSTRUCTIONS_FILE_NAME

    _write_protected_csv(packet_csv_path, artifacts.packet_frame, packet_name="review packet CSV")
    _write_protected_text(packet_md_path, artifacts.packet_markdown, packet_name="review packet Markdown")
    _write_or_preserve_decisions_template(decisions_path, artifacts.decisions_template)
    _write_protected_text(instructions_path, artifacts.instructions_markdown, packet_name="review workflow instructions")

    return {
        "packet_csv": packet_csv_path,
        "packet_markdown": packet_md_path,
        "review_decisions": decisions_path,
        "instructions_markdown": instructions_path,
    }


def render_phase3_review_packet_markdown(packet_frame: pd.DataFrame) -> str:
    lines = [
        "# Phase 3 Candidate Review Packet",
        "",
        "This packet contains the retained manual-review candidates only. It does not provide a model recommendation.",
        "",
        f"- Candidate rows: {len(packet_frame)}",
        "",
    ]

    if packet_frame.empty:
        lines.extend(["No retained candidates were generated.", ""])
        return "\n".join(lines)

    for row in packet_frame.itertuples(index=False):
        lines.extend(
            [
                f"## {row.stable_candidate_id}",
                "",
                f"- Ticker: {row.ticker}",
                f"- Issuer: {row.issuer_name}",
                f"- CIK: {row.cik}",
                f"- Candidate event date: {row.candidate_event_date}",
                f"- Priority tier: {row.priority_tier}",
                f"- Classification: {row.classification}",
                f"- Confidence: {row.confidence}",
                f"- Filing form: {row.filing_form}",
                f"- Filing date: {row.filing_date}",
                f"- Accession number: {row.accession_number}",
                f"- Matched ESPP terms: {row.matched_espp_terms or 'none'}",
                f"- Attachment score: {row.purchase_language_attachment_score}",
                f"- Same sentence: {row.same_sentence_indicator}",
                f"- Same clause: {row.same_clause_indicator}",
                f"- Explicit year: {row.explicit_year_indicator}",
                f"- Inferred year: {row.inferred_year_indicator}",
                f"- Recurring language: {row.recurring_language_indicator}",
                f"- Specific date: {row.specific_date_indicator}",
                f"- Ambiguity flags: {row.ambiguity_flags or 'none'}",
                f"- Duplicate count: {row.duplicate_count}",
                f"- Contributing accession numbers: {row.contributing_accession_numbers or 'none'}",
                f"- Canonical selection reason: {row.canonical_selection_reason}",
                f"- Review question: {row.plain_language_review_question}",
                "",
                f"Source phrase: `{row.source_phrase}`",
                "",
                "```text",
                str(row.bounded_source_snippet),
                "```",
                "",
            ]
        )

    return "\n".join(lines)


def render_phase3_review_workflow_instructions() -> str:
    return "\n".join(
        [
            "# Review Workflow Instructions",
            "",
            "1. Open `reports/candidate_review_packet.md` and inspect each retained candidate row in order.",
            "2. Use the bounded snippet, matched terms, filing form, filing date, and accession number to verify the source context.",
            "3. Enter decisions in `review_decisions.csv` without changing `event_review_id`; that stable candidate ID is the join key.",
            "4. Allowed `review_status` values are `accepted`, `corrected`, `rejected`, and `unreviewed`.",
            "5. Use `accepted` only when the candidate event date already reflects the supported ESPP purchase date. Leave `corrected_event_date` blank.",
            "6. Use `corrected` only when the filing clearly supports a different date, and enter that replacement date in `YYYY-MM-DD` format.",
            "7. Use `rejected` when the text is not an ESPP purchase event. Leave `corrected_event_date` blank.",
            "8. Leave uncertain rows as `unreviewed`. Unreviewed candidates remain visible in audit outputs but do not generate validated event windows.",
            "9. Save `review_decisions.csv` in place, then rerun the dedicated reviewed pilot configuration.",
            "",
        ]
    )


def _packet_frame(review_queue: pd.DataFrame) -> pd.DataFrame:
    if review_queue.empty:
        return pd.DataFrame(columns=REVIEW_PACKET_COLUMNS)

    frame = review_queue.copy()
    frame = frame.sort_values(
        ["ticker", "_priority_rank", "candidate_event_date", "canonical_filing_date", "event_review_id"],
        ignore_index=True,
    )
    rows: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        rows.append(
            {
                "stable_candidate_id": str(row.event_review_id),
                "ticker": str(row.ticker),
                "issuer_name": str(row.issuer_name),
                "cik": str(row.cik),
                "candidate_event_date": _string_or_empty(getattr(row, "candidate_event_date", "")),
                "priority_tier": _string_or_empty(getattr(row, "review_priority_tier", "")),
                "classification": _string_or_empty(getattr(row, "quality_category", "")),
                "confidence": float(getattr(row, "confidence", 0.0) or 0.0),
                "filing_form": _string_or_empty(getattr(row, "canonical_filing_type", "")),
                "filing_date": _string_or_empty(getattr(row, "canonical_filing_date", "")),
                "accession_number": _string_or_empty(getattr(row, "canonical_accession_number", "")),
                "source_phrase": _string_or_empty(getattr(row, "source_phrase", "")),
                "bounded_source_snippet": _string_or_empty(getattr(row, "source_snippet", "")),
                "matched_espp_terms": _string_or_empty(getattr(row, "matched_espp_terms", "")),
                "purchase_language_attachment_score": float(getattr(row, "attachment_score", 0.0) or 0.0),
                "same_sentence_indicator": bool(getattr(row, "same_sentence_as_purchase_phrase", False)),
                "same_clause_indicator": bool(getattr(row, "same_clause_as_purchase_phrase", False)),
                "explicit_year_indicator": bool(getattr(row, "explicit_year_indicator", False)),
                "inferred_year_indicator": bool(getattr(row, "inferred_year_indicator", False)),
                "recurring_language_indicator": bool(getattr(row, "recurring_language_indicator", False)),
                "specific_date_indicator": bool(getattr(row, "specific_date_indicator", False)),
                "ambiguity_flags": _string_or_empty(getattr(row, "ambiguity_flags", "")),
                "duplicate_count": int(getattr(row, "duplicate_count", 0) or 0),
                "contributing_accession_numbers": _string_or_empty(getattr(row, "contributing_accession_numbers", "")),
                "canonical_selection_reason": _canonical_selection_reason(row),
                "plain_language_review_question": _plain_language_review_question(row),
            }
        )
    return pd.DataFrame(rows).reindex(columns=REVIEW_PACKET_COLUMNS)


def _decisions_template(review_queue: pd.DataFrame) -> pd.DataFrame:
    if review_queue.empty:
        return pd.DataFrame(columns=REVIEW_DECISION_COLUMNS)

    template = review_queue.copy().sort_values(
        ["ticker", "_priority_rank", "candidate_event_date", "event_review_id"],
        ignore_index=True,
    )
    template_frame = pd.DataFrame(
        {
            "event_review_id": template["event_review_id"].fillna("").astype(str),
            "ticker": template["ticker"].fillna("").astype(str),
            "issuer_name": template["issuer_name"].fillna("").astype(str),
            "candidate_event_date": template["candidate_event_date"].fillna("").astype(str),
            "original_assigned_event_date": template["candidate_event_date"].fillna("").astype(str),
            "review_status": "",
            "corrected_event_date": "",
            "reviewer_note": "",
            "reviewed_at": "",
            "reviewer_id": "",
        }
    )
    return template_frame.reindex(columns=REVIEW_DECISION_COLUMNS)


def _canonical_selection_reason(row: object) -> str:
    duplicate_count = int(getattr(row, "duplicate_count", 0) or 0)
    attachment_score = float(getattr(row, "attachment_score", 0.0) or 0.0)
    confidence = float(getattr(row, "confidence", 0.0) or 0.0)
    deduplication_reason = _string_or_empty(getattr(row, "deduplication_reason", ""))
    if duplicate_count <= 1:
        duplicate_note = "Unique retained candidate after refinement."
    elif deduplication_reason == "same_event_across_filings":
        duplicate_note = f"Chosen as the strongest same-date candidate across {duplicate_count} duplicate filing contexts."
    elif deduplication_reason == "overlapping_snippets_same_filing":
        duplicate_note = f"Chosen as the strongest snippet among {duplicate_count} overlapping candidates from the same filing."
    else:
        duplicate_note = f"Chosen as the canonical representative among {duplicate_count} duplicate candidate contexts."
    year_note = "explicit-year support" if bool(getattr(row, "explicit_year_indicator", False)) else "inferred-year handling"
    return (
        f"{duplicate_note} Canonical row retained with attachment score {attachment_score:.2f}, "
        f"confidence {confidence:.2f}, and {year_note}."
    )


def _plain_language_review_question(row: object) -> str:
    candidate_event_date = _string_or_empty(getattr(row, "candidate_event_date", "")) or "the referenced date"
    return (
        f"Does this text establish {candidate_event_date} as a specific historical ESPP purchase date, "
        "a recurring purchase schedule, another event that is not an ESPP purchase date, or insufficient evidence?"
    )


def _priority_rank(value: object) -> int:
    tier = str(value or "").strip()
    if tier == "Tier1":
        return 1
    if tier == "Tier2":
        return 2
    if tier == "Tier3":
        return 3
    return 99


def _normalized_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    normalized = frame.copy() if frame is not None else pd.DataFrame()
    if normalized.empty:
        return normalized
    normalized["_priority_rank"] = normalized.get("review_priority_tier", pd.Series(dtype=str)).map(_priority_rank)
    return normalized


def _write_protected_csv(path: Path, frame: pd.DataFrame, *, packet_name: str) -> None:
    _write_protected_text(path, frame.to_csv(index=False, lineterminator="\n"), packet_name=packet_name)


def _write_protected_text(path: Path, content: str, *, packet_name: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing.replace("\r\n", "\n") != content.replace("\r\n", "\n"):
            raise ValueError(f"Refusing to overwrite existing {packet_name}: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_or_preserve_decisions_template(path: Path, template: pd.DataFrame) -> None:
    if path.exists():
        existing = pd.read_csv(path, dtype=str).fillna("")
        if "event_review_id" not in existing.columns:
            raise ValueError(f"Existing review decisions file is missing event_review_id: {path}")
        existing_ids = existing["event_review_id"].astype(str).str.strip().tolist()
        expected_ids = template["event_review_id"].astype(str).str.strip().tolist()
        if existing_ids != expected_ids:
            raise ValueError(
                "Existing review decisions file does not match the current stable candidate IDs; "
                f"refusing to overwrite {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(path, index=False)


def _string_or_empty(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text
