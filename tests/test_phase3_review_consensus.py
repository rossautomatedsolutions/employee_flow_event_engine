from __future__ import annotations

import pandas as pd

from src.analysis.phase3_review_consensus import (
    CONSENSUS_AUDIT_FILE_NAME,
    CONSENSUS_DECISIONS_FILE_NAME,
    CONSENSUS_MARKDOWN_FILE_NAME,
    REVIEWER_A_FILE_NAME,
    REVIEWER_B_FILE_NAME,
    build_phase3_review_consensus_artifacts,
    write_phase3_review_consensus_artifacts,
)


def _review_queue() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_review_id": "MSFT|specific_purchase|2025-06-30",
                "ticker": "MSFT",
                "issuer_name": "Microsoft",
                "candidate_event_date": "2025-06-30",
                "review_priority_tier": "Tier1",
                "quality_category": "plausible_specific_purchase_date",
                "_priority_rank": 1,
            },
            {
                "event_review_id": "NVDA|specific_purchase|2026-08-31",
                "ticker": "NVDA",
                "issuer_name": "Nvidia",
                "candidate_event_date": "2026-08-31",
                "review_priority_tier": "Tier1",
                "quality_category": "plausible_specific_purchase_date",
                "_priority_rank": 1,
            },
            {
                "event_review_id": "CRM|specific_purchase|2026-06-15",
                "ticker": "CRM",
                "issuer_name": "Salesforce",
                "candidate_event_date": "2026-06-15",
                "review_priority_tier": "Tier3",
                "quality_category": "plausible_recurring_purchase_schedule",
                "_priority_rank": 3,
            },
            {
                "event_review_id": "AMZN|specific_purchase|2026-12-31",
                "ticker": "AMZN",
                "issuer_name": "Amazon",
                "candidate_event_date": "2026-12-31",
                "review_priority_tier": "Tier2",
                "quality_category": "purchase_period_end_or_capacity_estimate",
                "_priority_rank": 2,
            },
        ]
    )


def test_phase3_review_consensus_auto_resolves_only_matching_reviewer_decisions() -> None:
    reviewer_a = pd.DataFrame(
        [
            {
                "event_review_id": "MSFT|specific_purchase|2025-06-30",
                "ticker": "MSFT",
                "original_assigned_event_date": "2025-06-30",
                "corrected_event_date": "",
                "review_status": "accepted",
                "reviewer_note": "Historical exercise wording is strong.",
                "reviewed_at": "2026-08-17T12:00:00Z",
                "reviewer_id": "reviewer_a",
            },
            {
                "event_review_id": "NVDA|specific_purchase|2026-08-31",
                "ticker": "NVDA",
                "original_assigned_event_date": "2026-08-31",
                "corrected_event_date": "",
                "review_status": "future_scheduled",
                "reviewer_note": "Current purchase period runs until a future date that remains ineligible for historical study use.",
                "reviewed_at": "2026-08-17T12:01:00Z",
                "reviewer_id": "reviewer_a",
            },
            {
                "event_review_id": "CRM|specific_purchase|2026-06-15",
                "ticker": "CRM",
                "original_assigned_event_date": "2026-06-15",
                "corrected_event_date": "",
                "review_status": "unresolved",
                "reviewer_note": "Recurring schedule language does not confirm that the purchase actually occurred on the candidate date.",
                "reviewed_at": "2026-08-17T12:02:00Z",
                "reviewer_id": "reviewer_a",
            },
            {
                "event_review_id": "AMZN|specific_purchase|2026-12-31",
                "ticker": "AMZN",
                "original_assigned_event_date": "2026-12-31",
                "corrected_event_date": "",
                "review_status": "rejected",
                "reviewer_note": "Reviewer A treats this as excluded plan-boundary language.",
                "reviewed_at": "2026-08-17T12:03:00Z",
                "reviewer_id": "reviewer_a",
            },
        ]
    )
    reviewer_b = pd.DataFrame(
        [
            {
                "event_review_id": "MSFT|specific_purchase|2025-06-30",
                "ticker": "MSFT",
                "original_assigned_event_date": "2025-06-30",
                "corrected_event_date": "",
                "review_status": "accepted",
                "reviewer_note": "Matches explicit historical purchase-rights execution language.",
                "reviewed_at": "2026-08-17T12:05:00Z",
                "reviewer_id": "reviewer_b",
            },
            {
                "event_review_id": "NVDA|specific_purchase|2026-08-31",
                "ticker": "NVDA",
                "original_assigned_event_date": "2026-08-31",
                "corrected_event_date": "",
                "review_status": "future_scheduled",
                "reviewer_note": "Reviewer B agrees that this is a future-scheduled row, not a historical event-study input.",
                "reviewed_at": "2026-08-17T12:06:00Z",
                "reviewer_id": "reviewer_b",
            },
            {
                "event_review_id": "CRM|specific_purchase|2026-06-15",
                "ticker": "CRM",
                "original_assigned_event_date": "2026-06-15",
                "corrected_event_date": "",
                "review_status": "unresolved",
                "reviewer_note": "Reviewer B agrees the text remains insufficient to validate an observed event.",
                "reviewed_at": "2026-08-17T12:07:00Z",
                "reviewer_id": "reviewer_b",
            },
            {
                "event_review_id": "AMZN|specific_purchase|2026-12-31",
                "ticker": "AMZN",
                "original_assigned_event_date": "2026-12-31",
                "corrected_event_date": "",
                "review_status": "accepted",
                "reviewer_note": "Reviewer B would still accept this row.",
                "reviewed_at": "2026-08-17T12:08:00Z",
                "reviewer_id": "reviewer_b",
            },
        ]
    )

    artifacts = build_phase3_review_consensus_artifacts(_review_queue(), reviewer_a, reviewer_b)

    decisions = artifacts.consensus_decisions.set_index("event_review_id")
    audit = artifacts.consensus_audit.set_index("event_review_id")

    assert decisions.loc["MSFT|specific_purchase|2025-06-30", "review_status"] == "accepted"
    assert decisions.loc["NVDA|specific_purchase|2026-08-31", "review_status"] == "future_scheduled"
    assert decisions.loc["CRM|specific_purchase|2026-06-15", "review_status"] == "unresolved"
    assert decisions.loc["AMZN|specific_purchase|2026-12-31", "review_status"] == "unreviewed"
    assert bool(audit.loc["MSFT|specific_purchase|2025-06-30", "auto_resolution_eligible"]) is True
    assert bool(audit.loc["NVDA|specific_purchase|2026-08-31", "auto_resolution_eligible"]) is True
    assert bool(audit.loc["CRM|specific_purchase|2026-06-15", "auto_resolution_eligible"]) is True
    assert bool(audit.loc["AMZN|specific_purchase|2026-12-31", "manual_resolution_required"]) is True
    assert audit.loc["AMZN|specific_purchase|2026-12-31", "resolution_status"] == "status_disagreement"
    assert "review_consensus_decisions.csv" in artifacts.summary_markdown


def test_phase3_review_consensus_writer_creates_templates_and_derived_outputs(tmp_path) -> None:
    output_dir = tmp_path / "artifacts"
    paths = write_phase3_review_consensus_artifacts(output_dir, _review_queue())

    assert paths["reviewer_a"].name == REVIEWER_A_FILE_NAME
    assert paths["reviewer_b"].name == REVIEWER_B_FILE_NAME
    assert paths["consensus_audit"].name == CONSENSUS_AUDIT_FILE_NAME
    assert paths["consensus_decisions"].name == CONSENSUS_DECISIONS_FILE_NAME
    assert paths["summary_markdown"].name == CONSENSUS_MARKDOWN_FILE_NAME

    reviewer_a = pd.read_csv(output_dir / REVIEWER_A_FILE_NAME, dtype=str).fillna("")
    reviewer_b = pd.read_csv(output_dir / REVIEWER_B_FILE_NAME, dtype=str).fillna("")
    consensus = pd.read_csv(output_dir / CONSENSUS_DECISIONS_FILE_NAME, dtype=str).fillna("")
    summary_text = (output_dir / "reports" / CONSENSUS_MARKDOWN_FILE_NAME).read_text(encoding="utf-8")

    assert reviewer_a["reviewer_id"].tolist() == ["reviewer_a", "reviewer_a", "reviewer_a", "reviewer_a"]
    assert reviewer_b["reviewer_id"].tolist() == ["reviewer_b", "reviewer_b", "reviewer_b", "reviewer_b"]
    assert consensus["review_status"].tolist() == ["unreviewed", "unreviewed", "unreviewed", "unreviewed"]
    assert "Manual resolution required rows: 4" in summary_text


def test_phase3_review_consensus_writer_reorders_existing_templates_without_losing_reviews(tmp_path) -> None:
    output_dir = tmp_path / "artifacts"
    paths = write_phase3_review_consensus_artifacts(output_dir, _review_queue())

    reviewer_a_path = paths["reviewer_a"]
    reviewer_a = pd.read_csv(reviewer_a_path, dtype=str).fillna("")
    reordered = reviewer_a.iloc[::-1].reset_index(drop=True)
    preserved_id = reordered.loc[0, "event_review_id"]
    reordered.loc[0, "review_status"] = "accepted"
    reordered.loc[0, "reviewer_note"] = "Preserve this consensus review."
    reordered.to_csv(reviewer_a_path, index=False)

    write_phase3_review_consensus_artifacts(output_dir, _review_queue())

    repaired = pd.read_csv(reviewer_a_path, dtype=str).fillna("")
    expected_ids = build_phase3_review_consensus_artifacts(
        _review_queue(),
        pd.DataFrame(columns=repaired.columns),
        pd.DataFrame(columns=repaired.columns),
    ).reviewer_a_template["event_review_id"].tolist()
    assert repaired["event_review_id"].tolist() == expected_ids
    repaired_by_id = repaired.set_index("event_review_id")
    assert repaired_by_id.loc[preserved_id, "review_status"] == "accepted"
    assert repaired_by_id.loc[preserved_id, "reviewer_note"] == "Preserve this consensus review."
