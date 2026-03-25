from datetime import date

from src.data.sec_parser import FilingDocument, extract_espp_hints
from src.events.espp_event_extractor import extract_espp_event_dataframe, estimate_event_dates


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
