from __future__ import annotations

import csv
import json
from pathlib import Path

import src.reproducibility.phase3_final_bundle as phase3_bundle
from src.reproducibility.phase3_final_bundle import EXPECTED_RESULT_COUNTS, summarize_reproduction_output


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_restore_portable_bundle_round_trip(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    cache_dir = repo_root / "artifacts" / "phase3_sec_discovery_sector33_20260817_cache"
    bundle_dir = repo_root / "reproducibility" / "phase3_sec_discovery_sector33_20260817"
    bundle_path = bundle_dir / "bundle.tar.gz"
    manifest_path = bundle_dir / "manifest.json"

    _write_text(
        repo_root / "config" / "phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml",
        "\n".join(
            [
                "ticker_subset:",
                "  - TEST",
                'universe_file: "config/sp500_universe_2026-07-04.csv"',
                'price_data_path: "fixtures/prices/phase2_research_sample_prices.csv"',
                'output_dir: "artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed"',
                'cache_dir: "artifacts/phase3_sec_discovery_sector33_20260817_cache"',
            ]
        )
        + "\n",
    )
    _write_text(repo_root / "config" / "phase3_sec_discovery_sector33_20260817_review_decisions.csv", "ticker\nTEST\n")
    _write_text(cache_dir / "submissions" / "CIK0000000001.json", '{"filings":{"recent":{}}}')
    _write_text(cache_dir / "filings" / "0000000001" / "000000000100000001" / "index.json", '{"directory":{"item":[]}}')
    _write_text(
        cache_dir / "filings" / "0000000001" / "000000000100000001" / "metadata.json",
        json.dumps(
            {
                "ticker": "TEST",
                "cik": "0000000001",
                "accession_number": "0000000001-00-000001",
                "form": "10-K",
                "filing_date": "2024-01-01",
                "primary_document": "test.htm",
                "submission_source_file": "CIK0000000001.json",
                "document_url": "https://example.test/doc",
                "index_url": "https://example.test/index",
            }
        ),
    )
    _write_text(cache_dir / "filings" / "0000000001" / "000000000100000001" / "test.htm", "<html>TEST</html>")

    monkeypatch.setattr(
        phase3_bundle,
        "EXPECTED_RESULT_COUNTS",
        {**phase3_bundle.EXPECTED_RESULT_COUNTS, "filings_selected": 1},
    )

    manifest = phase3_bundle.build_portable_bundle(
        repo_root=repo_root,
        cache_dir=cache_dir,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        config_path=repo_root / "config" / "phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml",
        review_file=repo_root / "config" / "phase3_sec_discovery_sector33_20260817_review_decisions.csv",
    )

    assert manifest["cache_summary"]["file_count"] == 4

    for path in list(cache_dir.rglob("*")):
        if path.is_file():
            path.unlink()
    for path in sorted(cache_dir.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
    cache_dir.rmdir()

    result = phase3_bundle.restore_portable_bundle(
        repo_root=repo_root,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        overwrite=False,
    )

    assert Path(result["restored_cache_dir"]).exists()
    assert (cache_dir / "filings" / "0000000001" / "000000000100000001" / "test.htm").read_text(encoding="utf-8") == "<html>TEST</html>"
    assert result["preexisting_cache_backup_dir"] is None


def test_restore_portable_bundle_backs_up_existing_target(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    cache_dir = repo_root / "artifacts" / "phase3_sec_discovery_sector33_20260817_cache"
    bundle_dir = repo_root / "reproducibility" / "phase3_sec_discovery_sector33_20260817"
    bundle_path = bundle_dir / "bundle.tar.gz"
    manifest_path = bundle_dir / "manifest.json"

    _write_text(
        repo_root / "config" / "phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml",
        "\n".join(
            [
                "ticker_subset:",
                "  - TEST",
                'universe_file: "config/sp500_universe_2026-07-04.csv"',
                'price_data_path: "fixtures/prices/phase2_research_sample_prices.csv"',
                'output_dir: "artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed"',
                'cache_dir: "artifacts/phase3_sec_discovery_sector33_20260817_cache"',
            ]
        )
        + "\n",
    )
    _write_text(repo_root / "config" / "phase3_sec_discovery_sector33_20260817_review_decisions.csv", "ticker\nTEST\n")
    _write_text(cache_dir / "submissions" / "CIK0000000001.json", '{"filings":{"recent":{}}}')
    _write_text(cache_dir / "filings" / "0000000001" / "000000000100000001" / "index.json", '{"directory":{"item":[]}}')
    _write_text(
        cache_dir / "filings" / "0000000001" / "000000000100000001" / "metadata.json",
        json.dumps(
            {
                "ticker": "TEST",
                "cik": "0000000001",
                "accession_number": "0000000001-00-000001",
                "form": "10-K",
                "filing_date": "2024-01-01",
                "primary_document": "test.htm",
                "submission_source_file": "CIK0000000001.json",
                "document_url": "https://example.test/doc",
                "index_url": "https://example.test/index",
            }
        ),
    )
    _write_text(cache_dir / "filings" / "0000000001" / "000000000100000001" / "test.htm", "<html>TEST</html>")

    monkeypatch.setattr(
        phase3_bundle,
        "EXPECTED_RESULT_COUNTS",
        {**phase3_bundle.EXPECTED_RESULT_COUNTS, "filings_selected": 1},
    )

    phase3_bundle.build_portable_bundle(
        repo_root=repo_root,
        cache_dir=cache_dir,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        config_path=repo_root / "config" / "phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml",
        review_file=repo_root / "config" / "phase3_sec_discovery_sector33_20260817_review_decisions.csv",
    )

    _write_text(cache_dir / "partial.txt", "incomplete")

    result = phase3_bundle.restore_portable_bundle(
        repo_root=repo_root,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        overwrite=False,
    )

    backup_dir = Path(result["preexisting_cache_backup_dir"])
    assert backup_dir.exists()
    assert (backup_dir / "partial.txt").read_text(encoding="utf-8") == "incomplete"
    assert (cache_dir / "filings" / "0000000001" / "000000000100000001" / "test.htm").read_text(encoding="utf-8") == "<html>TEST</html>"


def test_summarize_reproduction_output_validates_expected_counts(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts" / "phase3_sec_discovery_sector33_20260817_agent_reviewed"
    status_rows = [
        {
            "ticker": f"T{i:02d}",
            "processing_status": "completed_no_usable_events",
            "filings_selected": 6 if i < 32 else 5,
            "filings_processed": 6 if i < 32 else 5,
            "raw_candidate_count": 0,
            "accepted_events": 0,
            "rejected_events": 0,
            "unresolved_events": 0,
            "future_scheduled_events": 0,
            "warning_count": 0,
        }
        for i in range(EXPECTED_RESULT_COUNTS["issuers_attempted"])
    ]
    status_rows[0]["raw_candidate_count"] = 791
    status_rows[0]["rejected_events"] = 7
    status_rows[0]["unresolved_events"] = 3
    status_rows[0]["future_scheduled_events"] = 1
    _write_csv(output_dir / "company_processing_status.csv", status_rows)
    _write_csv(
        output_dir / "candidate_review_queue.csv",
        [{"ticker": "T00", "event_review_id": f"id-{i}"} for i in range(EXPECTED_RESULT_COUNTS["retained_candidates"])],
    )
    _write_csv(
        output_dir / "sec_acquisition_metrics.csv",
        [{"ticker": f"T{i:02d}", "cache_misses_total": 0} for i in range(EXPECTED_RESULT_COUNTS["issuers_attempted"])],
    )

    summary = summarize_reproduction_output(output_dir)

    assert summary["issuers_attempted"] == EXPECTED_RESULT_COUNTS["issuers_attempted"]
    assert summary["filings_selected"] == EXPECTED_RESULT_COUNTS["filings_selected"]
    assert summary["retained_candidates"] == EXPECTED_RESULT_COUNTS["retained_candidates"]
    assert summary["rejected"] == EXPECTED_RESULT_COUNTS["rejected"]
    assert summary["unresolved"] == EXPECTED_RESULT_COUNTS["unresolved"]
    assert summary["future_scheduled"] == EXPECTED_RESULT_COUNTS["future_scheduled"]
