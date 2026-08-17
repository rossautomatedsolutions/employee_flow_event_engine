from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.analysis.phase3_review_packet import (
    REVIEW_DECISION_COLUMNS,
    REVIEW_PACKET_COLUMNS,
    build_phase3_review_packet_artifacts,
    write_phase3_review_packet_artifacts,
)
from src.data.sec_parser import FilingDocument, extract_espp_hints
from src.pipeline.batch_config import Phase3CandidateConfig
from src.pipeline.phase3_candidates import build_phase3_candidate_artifacts


def _document(
    *,
    text: str,
    source_id: str,
    filing_date: date = date(2024, 2, 15),
    filing_type: str = "10-K",
) -> FilingDocument:
    return FilingDocument(
        ticker="AAPL",
        filing_type=filing_type,
        filing_date=filing_date,
        text=text,
        source_id=source_id,
        source_kind="sec",
        accession_number=source_id,
        report_date=date(2023, 12, 31),
        source_cache_path=f"cache/{source_id}.htm",
    )


def _review_queue() -> pd.DataFrame:
    document = _document(
        text=(
            "Employee Stock Purchase Plan purchase dates occur on June 30, 2024 and "
            "December 31, 2024 during each semiannual cycle."
        ),
        source_id="phase3_packet_fixture",
        filing_type="DEF 14A",
        filing_date=date(2024, 4, 1),
    )
    hint = extract_espp_hints(document)
    artifacts = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True),
    )
    return artifacts.review_queue


def test_phase3_review_packet_generation_uses_stable_candidate_ids() -> None:
    review_queue = _review_queue()

    artifacts = build_phase3_review_packet_artifacts(review_queue)

    assert list(artifacts.packet_frame.columns) == REVIEW_PACKET_COLUMNS
    assert list(artifacts.decisions_template.columns) == REVIEW_DECISION_COLUMNS
    assert artifacts.packet_frame["stable_candidate_id"].tolist() == review_queue["event_review_id"].tolist()
    assert artifacts.decisions_template["event_review_id"].tolist() == review_queue["event_review_id"].tolist()
    assert artifacts.decisions_template["review_status"].eq("").all()
    assert "does not provide a model recommendation" in artifacts.packet_markdown.lower()
    assert "specific historical ESPP purchase date" in artifacts.packet_markdown
    assert "stable candidate ID is the join key" in artifacts.instructions_markdown
    assert "future_scheduled" in artifacts.instructions_markdown
    assert "unresolved" in artifacts.instructions_markdown


def test_phase3_review_packet_writer_preserves_decisions_and_refuses_packet_overwrite(tmp_path: Path) -> None:
    review_queue = _review_queue()

    paths = write_phase3_review_packet_artifacts(tmp_path, review_queue)
    decisions_path = paths["review_decisions"]
    packet_csv_path = paths["packet_csv"]

    decisions = pd.read_csv(decisions_path, dtype=str).fillna("")
    decisions.loc[0, "review_status"] = "accepted"
    decisions.to_csv(decisions_path, index=False)

    write_phase3_review_packet_artifacts(tmp_path, review_queue)
    preserved = pd.read_csv(decisions_path, dtype=str).fillna("")
    assert preserved.loc[0, "review_status"] == "accepted"

    packet_csv_path.write_text("tampered packet", encoding="utf-8")
    with pytest.raises(ValueError, match="review packet CSV"):
        write_phase3_review_packet_artifacts(tmp_path, review_queue)


def test_phase3_review_packet_writer_reorders_existing_decisions_without_losing_reviews(tmp_path: Path) -> None:
    review_queue = _review_queue()
    paths = write_phase3_review_packet_artifacts(tmp_path, review_queue)
    decisions_path = paths["review_decisions"]

    decisions = pd.read_csv(decisions_path, dtype=str).fillna("")
    assert len(decisions) >= 2

    reversed_rows = decisions.iloc[::-1].reset_index(drop=True)
    preserved_id = reversed_rows.loc[0, "event_review_id"]
    reversed_rows.loc[0, "review_status"] = "accepted"
    reversed_rows.loc[0, "reviewer_note"] = "Preserve this review."
    reversed_rows.to_csv(decisions_path, index=False)

    write_phase3_review_packet_artifacts(tmp_path, review_queue)

    repaired = pd.read_csv(decisions_path, dtype=str).fillna("")
    expected_ids = build_phase3_review_packet_artifacts(review_queue).decisions_template["event_review_id"].tolist()
    assert repaired["event_review_id"].tolist() == expected_ids
    repaired_by_id = repaired.set_index("event_review_id")
    assert repaired_by_id.loc[preserved_id, "review_status"] == "accepted"
    assert repaired_by_id.loc[preserved_id, "reviewer_note"] == "Preserve this review."
