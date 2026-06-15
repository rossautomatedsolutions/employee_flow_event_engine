import pandas as pd

from src.analysis.research_summary import WARNING_BANNER, build_research_summary


def test_build_research_summary_counts_review_status_and_window_coverage() -> None:
    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "derivation_rule": "filing_text_month_day",
                "review_status": "accepted",
                "effective_event_date": "2024-07-01",
                "included_in_event_study": True,
            },
            {
                "ticker": "AAPL",
                "derivation_rule": "filing_text_month_day",
                "review_status": "corrected",
                "effective_event_date": "2024-12-31",
                "included_in_event_study": True,
            },
            {
                "ticker": "CRM",
                "derivation_rule": "fallback_default_anchors",
                "review_status": "rejected",
                "effective_event_date": None,
                "included_in_event_study": False,
            },
            {
                "ticker": "CRM",
                "derivation_rule": "filing_text_month_day",
                "review_status": "corrected",
                "effective_event_date": "2025-01-02",
                "included_in_event_study": True,
            },
        ]
    )
    panel = pd.DataFrame(
        [
            {"ticker": "AAPL", "event_id": 1, "event_date": "2024-07-01", "tau": 0, "raw_ret": 0.02, "abnormal_ret": 0.01},
            {"ticker": "AAPL", "event_id": 1, "event_date": "2024-07-01", "tau": 1, "raw_ret": 0.01, "abnormal_ret": 0.005},
            {"ticker": "AAPL", "event_id": 2, "event_date": "2024-12-31", "tau": 0, "raw_ret": -0.01, "abnormal_ret": -0.004},
            {"ticker": "AAPL", "event_id": 2, "event_date": "2024-12-31", "tau": 1, "raw_ret": 0.03, "abnormal_ret": 0.012},
        ]
    )

    report = build_research_summary(audit, panel)
    summary = report.summary

    assert summary["total_candidate_events"] == 4
    assert summary["accepted_events"] == 1
    assert summary["corrected_events"] == 2
    assert summary["rejected_events"] == 1
    assert summary["included_in_event_study_count"] == 3
    assert summary["event_windows_generated"] == 2
    assert summary["missing_or_empty_price_window_count"] == 1
    assert summary["number_of_tickers"] == 2
    assert summary["event_date_start"] == "2024-07-01"
    assert summary["event_date_end"] == "2025-01-02"
    assert summary["counts_by_review_status"] == {"accepted": 1, "corrected": 2, "rejected": 1}
    assert summary["counts_by_derivation_rule"] == {
        "fallback_default_anchors": 1,
        "filing_text_month_day": 3,
    }
    assert summary["event_day_returns"]["mean_raw_return"] == 0.005
    assert summary["t_plus_1_returns"]["median_abnormal_return"] == 0.0085


def test_research_summary_markdown_includes_descriptive_only_warning() -> None:
    report = build_research_summary(pd.DataFrame(), pd.DataFrame())

    assert WARNING_BANNER in report.markdown
    assert "descriptive only" in report.markdown.lower()
    assert "not statistically meaningful" in report.markdown.lower()
    assert "not a trading signal" in report.markdown.lower()
    assert "insufficient for inference" in report.markdown.lower()
