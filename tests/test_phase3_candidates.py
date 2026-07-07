from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data.sec_parser import FilingDocument, extract_espp_hints
from src.pipeline.batch_config import Phase3CandidateConfig
from src.pipeline.phase3_candidates import build_phase3_candidate_artifacts, load_phase3_candidate_reviews
from src.pipeline.run_batch import run_phase2_batch


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


def test_phase3_extracts_bounded_screened_candidates_and_preserves_source_snippets() -> None:
    unrelated_prefix = ("filler " * 300).strip()
    text = (
        "March 15, 2024 board meeting. "
        f"{unrelated_prefix} "
        "Employee Stock Purchase Plan purchase dates occur on June 30 and December 31 during each semiannual cycle."
    )
    document = _document(text=text, source_id="0001")
    hint = extract_espp_hints(document)

    artifacts = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True, context_window_chars=120),
    )

    assert len(artifacts.raw_candidates) == 2
    assert artifacts.raw_candidates["candidate_event_date"].tolist() == ["2024-06-30", "2024-12-31"]
    assert artifacts.raw_candidates["specific_date_indicator"].tolist() == [True, True]
    assert artifacts.raw_candidates["recurring_language_indicator"].tolist() == [True, True]
    assert all("Employee Stock Purchase Plan" in snippet for snippet in artifacts.raw_candidates["source_snippet"])
    assert all("March 15, 2024 board meeting" not in snippet for snippet in artifacts.raw_candidates["source_snippet"])


def test_phase3_diagnostic_override_extracts_from_unscreened_filings_only_when_enabled() -> None:
    document = _document(
        text="The annual meeting will occur on March 15, 2024 and no stock plan language is present.",
        source_id="0002",
    )
    hint = extract_espp_hints(document)

    without_override = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True, diagnostic_extract_from_unscreened_filings=False),
    )
    with_override = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True, diagnostic_extract_from_unscreened_filings=True),
    )

    assert without_override.raw_candidates.empty
    assert len(with_override.raw_candidates) == 1
    assert bool(with_override.raw_candidates.loc[0, "diagnostic_only"]) is True
    assert bool(with_override.raw_candidates.loc[0, "screening_passed"]) is False
    assert with_override.raw_candidates.loc[0, "candidate_event_date"] == "2024-03-15"


def test_phase3_deduplicates_candidates_and_flags_non_purchase_language() -> None:
    purchase_doc_a = _document(
        text="Employee Stock Purchase Plan purchase date is June 30.",
        source_id="0003",
    )
    purchase_doc_b = _document(
        text="Employee Stock Purchase Plan purchase date is June 30.",
        source_id="0004",
        filing_date=date(2024, 4, 1),
        filing_type="DEF 14A",
    )
    approval_doc = _document(
        text="Shareholders approved the Employee Stock Purchase Plan on April 10, 2024.",
        source_id="0005",
        filing_date=date(2024, 5, 1),
        filing_type="DEF 14A",
    )
    documents = [purchase_doc_a, purchase_doc_b, approval_doc]
    hints = [extract_espp_hints(document) for document in documents]

    artifacts = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=documents,
        hints=hints,
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True),
    )

    assert len(artifacts.raw_candidates) == 3
    assert len(artifacts.review_queue) == 1
    assert len(artifacts.excluded_queue) == 1
    june_row = artifacts.review_queue[artifacts.review_queue["candidate_event_date"] == "2024-06-30"].iloc[0]
    assert int(june_row["duplicate_count"]) == 2
    assert june_row["deduplication_reason"] == "same_event_across_filings"
    approval_row = artifacts.excluded_queue[artifacts.excluded_queue["candidate_event_date"] == "2024-04-10"].iloc[0]
    assert bool(approval_row["likely_plan_adoption_amendment_expiration_approval_indicator"]) is True
    assert "shareholder_approval" in str(approval_row["non_purchase_language_flags"])


def test_phase3_excludes_snapshot_and_plan_history_candidates_but_preserves_raw_rows() -> None:
    purchase_doc = _document(
        text=(
            "Includes 73 shares remaining available for issuance as of June 30, 2024 under the "
            "Employee Stock Purchase Plan, after the exercise of purchase rights on that date."
        ),
        source_id="0100",
        filing_type="DEF 14A",
    )
    snapshot_doc = _document(
        text=(
            "Under our Employee Stock Purchase Plan, the number of shares to be issued upon exercise "
            "of outstanding rights as of January 28, 2024 is not determinable."
        ),
        source_id="0101",
        filing_type="DEF 14A",
    )
    amendment_doc = _document(
        text="Apple Inc. Employee Stock Purchase Plan, as amended and restated as of March 10, 2015.",
        source_id="0102",
    )
    documents = [purchase_doc, snapshot_doc, amendment_doc]
    hints = [extract_espp_hints(document) for document in documents]

    artifacts = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=documents,
        hints=hints,
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True),
    )

    assert len(artifacts.raw_candidates) == 3
    assert "attachment_score" in artifacts.raw_candidates.columns
    assert set(artifacts.raw_candidates["queue_disposition"]) == {"primary_review_queue", "excluded_from_primary_queue"}
    assert len(artifacts.review_queue) == 1
    assert artifacts.review_queue.loc[0, "quality_category"] == "plausible_specific_purchase_date"
    assert len(artifacts.excluded_queue) == 2
    assert set(artifacts.excluded_queue["quality_category"]) == {
        "plan_history_or_amendment_restatement",
        "reporting_snapshot_or_share_reserve_context",
    }


def test_phase3_explicit_recurring_purchase_language_receives_priority_tiers() -> None:
    document = _document(
        text=(
            "Employee Stock Purchase Plan purchase dates occur on June 30, 2024 and December 31, 2024 "
            "during each semiannual cycle."
        ),
        source_id="0103",
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

    assert len(artifacts.review_queue) == 2
    assert artifacts.review_queue["quality_category"].eq("plausible_recurring_purchase_schedule").all()
    assert set(artifacts.review_queue["review_priority_tier"]) <= {"Tier2", "Tier3"}
    assert artifacts.excluded_queue.empty


def test_phase3_review_loader_and_corrected_date_propagation(tmp_path: Path) -> None:
    document = _document(
        text="Employee Stock Purchase Plan purchase date is June 30.",
        source_id="0006",
    )
    hint = extract_espp_hints(document)
    preliminary = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=pd.DataFrame(),
        config=Phase3CandidateConfig(enabled=True),
    )
    review_file = tmp_path / "phase3_reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,corrected_event_date,review_status,reviewer_note,reviewed_at,reviewer_id",
                f"{preliminary.review_queue.loc[0, 'event_review_id']},AAPL,2024-06-30,2024-07-01,corrected,Shifted to first business day,2026-07-05T12:00:00Z,qa",
            ]
        ),
        encoding="utf-8",
    )

    reviews = load_phase3_candidate_reviews(review_file)
    artifacts = build_phase3_candidate_artifacts(
        ticker="AAPL",
        issuer_name="Apple Inc.",
        issuer_id="apple-inc",
        cik="0000320193",
        documents=[document],
        hints=[hint],
        reviews=reviews,
        config=Phase3CandidateConfig(enabled=True),
    )

    assert artifacts.validated_audit.loc[0, "review_status"] == "corrected"
    assert artifacts.validated_audit.loc[0, "effective_event_date"] == "2024-07-01"
    assert artifacts.validated_audit.loc[0, "eligibility_status_for_validated_research"] == "eligible"
    assert len(artifacts.validated_events) == 1
    assert artifacts.validated_events[0].event_date.isoformat() == "2024-07-01"


def _write_phase3_fixture_dir(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "aapl.yaml").write_text(
        "\n".join(
            [
                "ticker: AAPL",
                "filing_type: 10-K",
                'filing_date: "2024-02-15"',
                "source_id: aapl_fixture",
                "accession_number: aapl_fixture",
                "report_date: \"2023-12-31\"",
                "text: |",
                "  Employee Stock Purchase Plan purchase dates occur on June 30 and December 31 during each semiannual cycle.",
            ]
        ),
        encoding="utf-8",
    )
    return fixture_dir


def _write_phase3_price_file(tmp_path: Path) -> Path:
    price_path = tmp_path / "prices.csv"
    price_path.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "AAPL,2024-06-28,100,101,99,100,1000000",
                "AAPL,2024-06-30,102,103,101,102,800000",
                "AAPL,2024-07-01,103,104,102,103,2500000",
                "AAPL,2024-12-31,111,112,110,111,2300000",
                "AAPL,2025-01-01,112,113,111,112,900000",
                "SPY,2024-06-28,300,301,299,300,1500000",
                "SPY,2024-06-30,302,303,301,302,1500000",
                "SPY,2024-07-01,303,304,302,303,1500000",
                "SPY,2024-12-31,311,312,310,311,1500000",
                "SPY,2025-01-01,312,313,311,312,1500000",
            ]
        ),
        encoding="utf-8",
    )
    return price_path


def _write_phase3_universe_file(tmp_path: Path) -> Path:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "AAPL,Apple Inc.,Apple Inc.,apple-inc,320193,Information Technology,Technology Hardware Storage & Peripherals,AAPL,true",
            ]
        ),
        encoding="utf-8",
    )
    return universe_path


def _write_phase3_config(tmp_path: Path, universe_path: Path, price_path: Path, fixture_dir: Path, output_dir: Path) -> Path:
    config_path = tmp_path / "phase3.yaml"
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                f'universe_file: "{universe_path.as_posix()}"',
                'ticker_subset: ["AAPL"]',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-01"',
                f'output_dir: "{output_dir.as_posix()}"',
                f'cache_dir: "{(tmp_path / "cache").as_posix()}"',
                "resume_mode: false",
                "offline_mode: true",
                "max_companies: 1",
                'price_source: "csv"',
                f'price_data_path: "{price_path.as_posix()}"',
                "filings:",
                f'  fixture_dir: "{fixture_dir.as_posix()}"',
                '  filing_start_date: "2024-01-01"',
                '  filing_end_date: "2024-12-31"',
                "reviews:",
                "  review_file: null",
                "phase3:",
                "  enabled: true",
                "  screened_only: true",
                "  diagnostic_extract_from_unscreened_filings: false",
                "  context_window_chars: 120",
                "  require_review_for_validated_windows: true",
                "  generate_provisional_unreviewed_windows: true",
                "event_study:",
                "  window_before: 0",
                "  window_after: 1",
                "  volume_lookback: 5",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def test_run_phase3_batch_writes_review_queue_and_separate_provisional_outputs(tmp_path: Path) -> None:
    fixture_dir = _write_phase3_fixture_dir(tmp_path)
    price_path = _write_phase3_price_file(tmp_path)
    universe_path = _write_phase3_universe_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_phase3_config(tmp_path, universe_path, price_path, fixture_dir, output_dir)

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / "company_processing_status.csv")
    audit = pd.read_csv(output_dir / "espp_date_audit.csv")
    raw_candidates = pd.read_csv(output_dir / "raw_candidate_extractions.csv")
    review_queue = pd.read_csv(output_dir / "candidate_review_queue.csv")
    provisional_windows = pd.read_csv(output_dir / "provisional_diagnostic_event_windows.csv")

    assert status.loc[0, "processing_status"] == "completed_pending_review"
    assert status.loc[0, "usable_event_windows"] == 0
    assert status.loc[0, "provisional_event_windows"] == 2
    assert len(raw_candidates) == 2
    assert len(review_queue) == 2
    assert review_queue["review_priority_tier"].isin(["Tier1", "Tier2", "Tier3"]).all()
    assert set(audit["review_status"]) == {"unreviewed"}
    assert audit["included_in_event_study"].tolist() == [False, False]
    assert sorted(provisional_windows["event_date"].astype(str).unique().tolist()) == ["2024-06-30", "2024-12-31"]
    assert not (output_dir / "all_event_windows.csv").exists()
    assert not (output_dir / "excluded_candidate_audit.csv").exists()
    assert (output_dir / "candidate_quality_before_after.csv").exists()
    assert (output_dir / "candidate_quality_counts.csv").exists()
    assert (output_dir / "reports" / "candidate_quality_audit.md").exists()
