from datetime import date
from pathlib import Path

import pandas as pd

from src.data.sec_parser import FilingDocument, extract_espp_hints, load_filing_documents_from_fixtures
from src.events.espp_event_extractor import extract_espp_event_dataframe, estimate_event_dates, estimate_event_dates_with_audit


def test_extract_espp_hints_captures_keywords_and_dates() -> None:
    doc = FilingDocument(
        ticker="TEST",
        filing_type="10-K",
        filing_date=date(2024, 2, 15),
        text="Employee Stock Purchase Plan has purchase period ending June 30 and December 31.",
    )

    hint = extract_espp_hints(doc)
    assert hint.confidence > 0
    assert (6, 30) in hint.month_day_candidates
    assert (12, 31) in hint.month_day_candidates


def test_estimate_event_dates_uses_fallback_without_hints() -> None:
    events = estimate_event_dates("TEST", [], 2024, 2024)
    assert len(events) == 2
    assert events[0].event_date == date(2024, 6, 30)
    assert events[1].event_date == date(2024, 12, 31)


def test_extract_espp_event_dataframe_from_sec_text() -> None:
    filings = [
        FilingDocument(
            ticker="TEST",
            filing_type="10-K",
            filing_date=date(2024, 2, 15),
            text=(
                "Our Employee Stock Purchase Plan uses an offering period, and the purchase date "
                "occurs on January 1 and July 1."
            ),
        )
    ]

    frame = extract_espp_event_dataframe("TEST", filings, 2024, 2024)
    assert frame["event_date"].tolist() == [date(2024, 1, 1), date(2024, 7, 1)]
    assert set(frame["confidence_score"].tolist()) == {"high"}
    assert set(frame["source"].tolist()) == {"SEC"}


def test_extract_espp_event_dataframe_uses_heuristic_fallback() -> None:
    frame = extract_espp_event_dataframe("TEST", [], 2024, 2024)
    assert frame["event_date"].tolist() == [date(2024, 6, 30), date(2024, 12, 31)]
    assert set(frame["confidence_score"].tolist()) == {"low"}
    assert set(frame["source"].tolist()) == {"heuristic"}


def test_load_filing_documents_from_local_fixtures(tmp_path: Path) -> None:
    fixture_path = tmp_path / "sample.yaml"
    fixture_path.write_text(
        "\n".join(
            [
                'ticker: "TEST"',
                'filing_type: "10-K"',
                'filing_date: "2024-02-15"',
                'source_id: "test_fixture_2024"',
                'text: |',
                '  Employee Stock Purchase Plan purchase date occurs on June 30.',
            ]
        ),
        encoding="utf-8",
    )

    docs = load_filing_documents_from_fixtures(tmp_path, ticker="TEST")

    assert len(docs) == 1
    assert docs[0].source_id == "test_fixture_2024"
    assert docs[0].source_fixture_path == str(fixture_path)


def test_estimate_event_dates_with_audit_extracts_explicit_month_day() -> None:
    doc = FilingDocument(
        ticker="TEST",
        filing_type="10-K",
        filing_date=date(2024, 2, 15),
        text="Employee Stock Purchase Plan purchase date occurs on June 30 and December 31.",
        source_fixture_path="fixtures/sec_filings/test.yaml",
        source_id="test_fixture",
    )

    events, audit = estimate_event_dates_with_audit("TEST", [extract_espp_hints(doc)], 2024, 2024)

    assert [event.event_date for event in events] == [date(2024, 6, 30), date(2024, 12, 31)]
    assert audit["candidate_month_day"].tolist() == ["06-30", "12-31"]
    assert audit["derivation_rule"].tolist() == ["filing_text_month_day", "filing_text_month_day"]
    assert audit["source_id"].tolist() == ["test_fixture", "test_fixture"]
    assert audit["event_review_id"].tolist() == [
        "TEST|10-K|2024-02-15|test_fixture|06-30|2024-06-30|filing_text_month_day",
        "TEST|10-K|2024-02-15|test_fixture|12-31|2024-12-31|filing_text_month_day",
    ]


def test_estimate_event_dates_with_audit_event_review_id_is_deterministic() -> None:
    doc = FilingDocument(
        ticker="TEST",
        filing_type="10-K",
        filing_date=date(2024, 2, 15),
        text="Employee Stock Purchase Plan purchase date occurs on June 30 and December 31.",
        source_fixture_path="fixtures/sec_filings/test.yaml",
        source_id="test_fixture",
    )

    _, first_audit = estimate_event_dates_with_audit("TEST", [extract_espp_hints(doc)], 2024, 2024)
    _, second_audit = estimate_event_dates_with_audit("TEST", [extract_espp_hints(doc)], 2024, 2024)

    assert first_audit["event_review_id"].tolist() == second_audit["event_review_id"].tolist()


def test_estimate_event_dates_with_audit_uses_fallback_anchors() -> None:
    events, audit = estimate_event_dates_with_audit("TEST", [], 2024, 2024)

    assert [event.event_date for event in events] == [date(2024, 6, 30), date(2024, 12, 31)]
    assert audit["fallback_anchor_used"].tolist() == [True, True]
    assert set(audit["derivation_rule"].tolist()) == {"fallback_default_anchors"}


def test_estimate_event_dates_with_audit_fallback_event_review_ids_match_business_day_review_csv() -> None:
    doc = FilingDocument(
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 2, 15),
        text="Employee Stock Purchase Plan purchase date occurs on June 30 and December 31.",
        source_id="aapl_2024_10k_fixture",
    )

    _, audit = estimate_event_dates_with_audit("AAPL", [extract_espp_hints(doc)], 2024, 2025)
    fallback_ids = audit.loc[audit["fallback_anchor_used"], "event_review_id"].tolist()

    assert fallback_ids == [
        "AAPL|na|na|default_anchor_aapl_2025_0630|06-30|2025-06-30|fallback_default_anchors",
        "AAPL|na|na|default_anchor_aapl_2025_1231|12-31|2025-12-31|fallback_default_anchors",
    ]


def test_estimate_event_dates_with_audit_rolls_forward_past_filing_date() -> None:
    doc = FilingDocument(
        ticker="TEST",
        filing_type="10-K",
        filing_date=date(2024, 3, 1),
        text="Employee Stock Purchase Plan purchase dates occur on January 1 and July 1.",
    )

    events, audit = estimate_event_dates_with_audit("TEST", [extract_espp_hints(doc)], 2024, 2025)

    assert [event.event_date for event in events] == [date(2024, 7, 1), date(2025, 1, 1)]
    assert pd.to_datetime(audit["assigned_event_date"]).dt.date.tolist() == [date(2024, 7, 1), date(2025, 1, 1)]


def test_estimate_event_dates_with_audit_labels_mock_sources_as_mock() -> None:
    doc = FilingDocument(
        ticker="TEST",
        filing_type="10-K",
        filing_date=date(2024, 2, 15),
        text="Employee Stock Purchase Plan purchase date occurs on June 30 and December 31.",
        source_id="mock_test_2024_10k",
        source_kind="mock",
    )

    events, audit = estimate_event_dates_with_audit("TEST", [extract_espp_hints(doc)], 2024, 2024)

    assert [event.source for event in events] == ["mock", "mock"]
    assert set(audit["derivation_rule"].tolist()) == {"mock_filing_text_month_day"}
    assert all(event.event_review_id for event in events)
