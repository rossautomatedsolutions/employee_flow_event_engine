import builtins
import sys
import types
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

matplotlib = types.ModuleType("matplotlib")
pyplot = types.ModuleType("pyplot")


class _DummyAxes:
    def plot(self, *args, **kwargs) -> None:
        return None

    def axhline(self, *args, **kwargs) -> None:
        return None

    def set_title(self, *args, **kwargs) -> None:
        return None

    def set_xlabel(self, *args, **kwargs) -> None:
        return None

    def set_ylabel(self, *args, **kwargs) -> None:
        return None

    def legend(self, *args, **kwargs) -> None:
        return None


class _DummyFigure:
    def tight_layout(self) -> None:
        return None


def _dummy_subplots(*args, **kwargs):
    return _DummyFigure(), _DummyAxes()


pyplot.Figure = object
pyplot.subplots = _dummy_subplots
matplotlib.pyplot = pyplot
sys.modules.setdefault("matplotlib", matplotlib)
sys.modules.setdefault("matplotlib.pyplot", pyplot)

from src.pipeline.run_event_study import (
    ExperimentConfig,
    TickerConfig,
    _apply_event_date_reviews,
    _build_price_data_provider,
    _diagnostic_conclusion,
    _distribution_summary,
    _horizon_returns,
    _load_event_date_reviews,
    _load_filings_for_ticker,
    _load_config,
    _persist_date_audit,
    run_first_pass_event_study,
)
from src.analysis.event_study import EventStudyConfig, run_event_study
from src.analysis.strategy import CrossSectionConfig, StrategyConfig
from src.data.price_loader import CSVPriceLoader
from src.data.sec_parser import parse_many_espp_hints
from src.events.espp_event_extractor import ESPPEvent
from src.events.espp_event_extractor import estimate_event_dates_with_audit


def _sample_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAA", "event_id": 1, "tau": 1, "raw_ret": -0.01},
            {"ticker": "AAA", "event_id": 1, "tau": 2, "raw_ret": -0.01},
            {"ticker": "AAA", "event_id": 1, "tau": 3, "raw_ret": 0.0},
            {"ticker": "AAA", "event_id": 1, "tau": 4, "raw_ret": 0.0},
            {"ticker": "AAA", "event_id": 1, "tau": 5, "raw_ret": 0.0},
            {"ticker": "BBB", "event_id": 2, "tau": 1, "raw_ret": 0.01},
            {"ticker": "BBB", "event_id": 2, "tau": 2, "raw_ret": 0.0},
            {"ticker": "BBB", "event_id": 2, "tau": 3, "raw_ret": 0.0},
            {"ticker": "BBB", "event_id": 2, "tau": 4, "raw_ret": 0.0},
            {"ticker": "BBB", "event_id": 2, "tau": 5, "raw_ret": 0.0},
        ]
    )


def test_horizon_returns_uses_compounded_returns() -> None:
    panel = _sample_panel()

    h3 = _horizon_returns(panel, horizon=3)

    aaa = h3.loc[h3["ticker"] == "AAA", "return"].iloc[0]
    bbb = h3.loc[h3["ticker"] == "BBB", "return"].iloc[0]
    assert aaa == (1 - 0.01) * (1 - 0.01) * (1 + 0.0) - 1
    assert bbb == (1 + 0.01) * (1 + 0.0) * (1 + 0.0) - 1


def test_diagnostic_conclusion_sell_pressure() -> None:
    distribution = pd.DataFrame(
        {
            "horizon": [1.0, 3.0, 5.0],
            "return": [-0.02, -0.01, -0.03],
        }
    )
    summary = _distribution_summary(distribution)

    assert _diagnostic_conclusion(summary) == "evidence of sell pressure"


def test_persist_date_audit_writes_expected_shape(tmp_path) -> None:
    audit_frame = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "test_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-02-15|test_fixture|06-30|2024-06-30|filing_text_month_day",
            }
        ]
    )

    _persist_date_audit(tmp_path, [audit_frame])

    written = pd.read_csv(tmp_path / "espp_date_audit.csv")
    assert written.columns.tolist() == [
        "ticker",
        "filing_type",
        "filing_date",
        "source_fixture_path",
        "source_id",
        "source_snippet",
        "candidate_month_day",
        "assigned_event_date",
        "derivation_rule",
        "confidence",
        "fallback_anchor_used",
        "event_review_id",
        "review_status",
        "reviewed_event_date",
        "review_note",
        "effective_event_date",
        "included_in_event_study",
    ]
    assert written.loc[0, "ticker"] == "TEST"


def test_persist_date_audit_records_rejected_reviews_for_auditability(tmp_path: Path) -> None:
    event_review_id = "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    reviews = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_review_id": event_review_id,
                "original_assigned_event_date": "2024-06-30",
                "reviewed_event_date": "",
                "review_status": "rejected",
                "review_note": "Manual review rejected this candidate event",
            }
        ]
    )
    events = [
        ESPPEvent(
            "TEST",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            event_review_id,
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "fixture_a",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": event_review_id,
            }
        ]
    )

    _, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)
    _persist_date_audit(tmp_path, [reviewed_audit])

    written = pd.read_csv(tmp_path / "espp_date_audit.csv")

    assert written.loc[0, "event_review_id"] == event_review_id
    assert written.loc[0, "review_status"] == "rejected"
    assert bool(written.loc[0, "included_in_event_study"]) is False
    assert pd.isna(written.loc[0, "effective_event_date"])
    assert written.loc[0, "review_note"] == "Manual review rejected this candidate event"


def test_rejected_review_is_excluded_from_event_study_output_but_preserved_in_audit(tmp_path: Path) -> None:
    event_review_id = "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    reviews = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_review_id": event_review_id,
                "original_assigned_event_date": "2024-06-30",
                "reviewed_event_date": "",
                "review_status": "rejected",
                "review_note": "Manual review rejected this candidate event",
            }
        ]
    )
    events = [
        ESPPEvent(
            "TEST",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            event_review_id,
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "fixture_a",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": event_review_id,
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)
    _persist_date_audit(tmp_path, [reviewed_audit])

    price_index = pd.bdate_range("2024-06-28", periods=3)
    price = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1_000_000, 1_100_000, 1_200_000],
        },
        index=price_index,
    )
    benchmark = price.copy()
    result = run_event_study(price, benchmark, reviewed_events, EventStudyConfig(window_before=0, window_after=0))
    written_audit = pd.read_csv(tmp_path / "espp_date_audit.csv")

    assert reviewed_events == []
    assert reviewed_audit.loc[0, "review_status"] == "rejected"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is False
    assert result.panel.empty
    assert written_audit.loc[0, "event_review_id"] == event_review_id
    assert written_audit.loc[0, "review_status"] == "rejected"
    assert bool(written_audit.loc[0, "included_in_event_study"]) is False


def _test_config_with_fixture_dir(fixture_dir: Path | None) -> ExperimentConfig:
    return ExperimentConfig(
        tickers=[TickerConfig(ticker="TEST", market_cap=1.0, employees=1)],
        benchmark="SPY",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        output_dir=Path("artifacts/test"),
        price_source="yfinance",
        price_data_path=None,
        filing_fixture_dir=fixture_dir,
        review_file=None,
        event_study=EventStudyConfig(),
        strategy=StrategyConfig(),
        cross_section=CrossSectionConfig(),
    )


def test_load_filings_for_ticker_prefers_fixture_and_falls_back_to_mock(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    fixture_path = fixture_dir / "test_fixture.yaml"
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

    config = _test_config_with_fixture_dir(fixture_dir)

    fixture_docs = _load_filings_for_ticker(config, "TEST")
    assert len(fixture_docs) == 1
    assert fixture_docs[0].source_kind == "fixture"
    assert fixture_docs[0].source_id == "test_fixture_2024"
    assert fixture_docs[0].source_fixture_path == str(fixture_path)

    mock_docs = _load_filings_for_ticker(config, "MISSING")
    assert len(mock_docs) == 1
    assert mock_docs[0].ticker == "MISSING"
    assert mock_docs[0].source_kind == "mock"
    assert mock_docs[0].source_id == "mock_missing_2024_10k"
    assert mock_docs[0].source_fixture_path is None


def test_apply_event_date_reviews_leaves_events_unchanged_without_review_file() -> None:
    events = [
        ESPPEvent(
            ticker="TEST",
            event_date=date(2024, 1, 15),
            source_filing_date=date(2024, 1, 1),
            source_filing_type="10-K",
            confidence=0.8,
            approximation_method="filing_text_month_day",
            source="fixture",
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "test_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "01-15",
                "assigned_event_date": "2024-01-15",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|test_fixture|01-15|2024-01-15|filing_text_month_day",
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, _load_event_date_reviews(None))

    assert [event.event_date for event in reviewed_events] == [date(2024, 1, 15)]
    assert reviewed_audit.loc[0, "review_status"] == "unreviewed"
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-01-15"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is True


def test_apply_event_date_reviews_handles_accepted_corrected_and_rejected_rows(tmp_path: Path) -> None:
    review_file = tmp_path / "espp_date_reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-01-01|test_fixture|01-15|2024-01-15|filing_text_month_day,TEST,2024-01-15,,accepted,Reviewed and kept as-is",
                "TEST|10-K|2024-01-01|test_fixture|02-15|2024-02-15|filing_text_month_day,TEST,2024-02-15,2024-02-16,corrected,Shift to reviewed business day",
                "TEST|10-K|2024-01-01|test_fixture|03-15|2024-03-15|filing_text_month_day,TEST,2024-03-15,,rejected,Not a real ESPP purchase date",
            ]
        ),
        encoding="utf-8",
    )
    reviews = _load_event_date_reviews(review_file)
    events = [
        ESPPEvent("TEST", date(2024, 1, 15), date(2024, 1, 1), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-01-01|test_fixture|01-15|2024-01-15|filing_text_month_day"),
        ESPPEvent("TEST", date(2024, 2, 15), date(2024, 1, 1), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-01-01|test_fixture|02-15|2024-02-15|filing_text_month_day"),
        ESPPEvent("TEST", date(2024, 3, 15), date(2024, 1, 1), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-01-01|test_fixture|03-15|2024-03-15|filing_text_month_day"),
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "test_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "01-15",
                "assigned_event_date": "2024-01-15",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|test_fixture|01-15|2024-01-15|filing_text_month_day",
            },
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "test_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "02-15",
                "assigned_event_date": "2024-02-15",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|test_fixture|02-15|2024-02-15|filing_text_month_day",
            },
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "test_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "03-15",
                "assigned_event_date": "2024-03-15",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|test_fixture|03-15|2024-03-15|filing_text_month_day",
            },
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert [event.event_date for event in reviewed_events] == [date(2024, 1, 15), date(2024, 2, 16)]
    assert reviewed_audit["review_status"].tolist() == ["accepted", "corrected", "rejected"]
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-01-15"
    assert reviewed_audit.loc[1, "effective_event_date"] == "2024-02-16"
    assert pd.isna(reviewed_audit.loc[2, "effective_event_date"])
    assert reviewed_audit["included_in_event_study"].tolist() == [True, True, False]

    idx = pd.bdate_range("2024-01-01", periods=80)
    price = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": [100 + i * 0.1 for i in range(len(idx))],
            "volume": [1_000_000 + i * 10 for i in range(len(idx))],
        },
        index=idx,
    )
    benchmark = price.copy()
    result = run_event_study(price, benchmark, reviewed_events, EventStudyConfig(window_before=0, window_after=0))

    assert sorted(result.panel["event_date"].astype(str).unique().tolist()) == ["2024-01-15", "2024-02-16"]
    assert "2024-03-15" not in result.panel["event_date"].astype(str).tolist()


def test_load_event_date_reviews_rejects_duplicate_legacy_fallback_keys(tmp_path: Path) -> None:
    review_file = tmp_path / "duplicate_fallback_reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ",TEST,2024-06-30,2024-07-01,corrected,First ambiguous fallback row",
                ",TEST,2024-06-30,,rejected,Second ambiguous fallback row",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate review rows found for fallback event keys"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_duplicate_legacy_fallback_keys_after_whitespace_normalization(tmp_path: Path) -> None:
    review_file = tmp_path / "duplicate_fallback_reviews_whitespace.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ",TEST,2024-06-30,,accepted,First normalized fallback row",
                ", TEST , 2024-06-30 ,,rejected,Whitespace-variant fallback row",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate review rows found for fallback event keys"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_legacy_rows_without_any_review_key(tmp_path: Path) -> None:
    review_file = tmp_path / "missing_legacy_review_key.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ",TEST,,2024-07-01,corrected,Malformed legacy review row without any matching key",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Review rows require event_review_id or original_assigned_event_date"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_blank_ticker_values(tmp_path: Path) -> None:
    review_file = tmp_path / "blank_ticker_review.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ",,2024-06-30,2024-07-01,corrected,Blank legacy fallback ticker should fail fast",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ticker"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_invalid_review_status_values(tmp_path: Path) -> None:
    review_file = tmp_path / "invalid_review_status.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,,approve,Unsupported review status should fail fast",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid review_status"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_blank_review_status_values(tmp_path: Path) -> None:
    review_file = tmp_path / "blank_review_status.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,,,Blank review status should fail fast",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid review_status"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_malformed_reviewed_event_date_values(tmp_path: Path) -> None:
    review_file = tmp_path / "invalid_reviewed_event_date.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,07/01/2024,corrected,Malformed corrected reviewed date should fail fast",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid reviewed_event_date"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_malformed_original_assigned_event_date_values(tmp_path: Path) -> None:
    review_file = tmp_path / "invalid_original_assigned_event_date.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ",TEST,06/30/2024,2024-07-01,corrected,Malformed legacy fallback key date should fail fast",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid original_assigned_event_date"):
        _load_event_date_reviews(review_file)


def test_load_event_date_reviews_rejects_duplicate_event_review_ids_with_conflicting_key_in_message(tmp_path: Path) -> None:
    duplicate_key = "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    review_file = tmp_path / "duplicate_event_review_ids.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                f"{duplicate_key},TEST,2024-06-30,2024-07-01,corrected,First duplicate preferred-key row",
                f"{duplicate_key},TEST,2024-06-30,,rejected,Second duplicate preferred-key row",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate review rows found for event_review_id keys") as exc_info:
        _load_event_date_reviews(review_file)

    assert duplicate_key in str(exc_info.value)


def test_load_event_date_reviews_rejects_duplicate_event_review_ids_after_whitespace_normalization(tmp_path: Path) -> None:
    duplicate_key = "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    review_file = tmp_path / "duplicate_event_review_ids_whitespace.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                f"{duplicate_key},TEST,2024-06-30,,accepted,First preferred-key row",
                f" {duplicate_key} ,TEST,2024-06-30,,rejected,Whitespace-variant preferred-key row",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate review rows found for event_review_id keys") as exc_info:
        _load_event_date_reviews(review_file)

    assert duplicate_key in str(exc_info.value)


def test_apply_event_date_reviews_can_review_duplicate_ticker_date_rows_independently(tmp_path: Path) -> None:
    review_file = tmp_path / "espp_date_reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-01-01|fixture_a|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,,accepted,Keep first duplicate row",
                "TEST|10-K|2024-01-01|fixture_b|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,,rejected,Reject second duplicate row",
            ]
        ),
        encoding="utf-8",
    )
    reviews = _load_event_date_reviews(review_file)
    events = [
        ESPPEvent("TEST", date(2024, 6, 30), date(2024, 1, 1), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-01-01|fixture_a|06-30|2024-06-30|filing_text_month_day"),
        ESPPEvent("TEST", date(2024, 6, 30), date(2024, 1, 1), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-01-01|fixture_b|06-30|2024-06-30|filing_text_month_day"),
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/a.yaml",
                "source_id": "fixture_a",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|fixture_a|06-30|2024-06-30|filing_text_month_day",
            },
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-01-01",
                "source_fixture_path": "fixtures/sec_filings/b.yaml",
                "source_id": "fixture_b",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-01-01|fixture_b|06-30|2024-06-30|filing_text_month_day",
            },
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert len(reviewed_events) == 1
    assert reviewed_events[0].event_review_id == "TEST|10-K|2024-01-01|fixture_a|06-30|2024-06-30|filing_text_month_day"
    assert reviewed_audit["review_status"].tolist() == ["accepted", "rejected"]


def test_apply_event_date_reviews_supports_legacy_ticker_date_fallback_matching() -> None:
    reviews = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_review_id": "",
                "original_assigned_event_date": "2024-06-30",
                "reviewed_event_date": "2024-07-01",
                "review_status": "corrected",
                "review_note": "Legacy fallback review without deterministic id",
            }
        ]
    )
    events = [
        ESPPEvent(
            "TEST",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day",
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/test.yaml",
                "source_id": "fixture_a",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day",
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert [event.event_date for event in reviewed_events] == [date(2024, 7, 1)]
    assert reviewed_audit.loc[0, "review_status"] == "corrected"
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-07-01"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is True


def test_apply_event_date_reviews_supports_whitespace_normalized_legacy_ticker_date_fallback_matching(tmp_path: Path) -> None:
    review_file = tmp_path / "whitespace_legacy_fallback_review.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                ", AAPL , 2024-06-30 ,2024-07-01,corrected,Legacy fallback row should still match after normalization",
            ]
        ),
        encoding="utf-8",
    )
    reviews = _load_event_date_reviews(review_file)

    events = [
        ESPPEvent(
            "AAPL",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            "AAPL|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day",
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/aapl.yaml",
                "source_id": "fixture_a",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "AAPL|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day",
                "included_in_event_study": True,
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert reviews.loc[0, "event_review_id"] == ""
    assert [event.event_date for event in reviewed_events] == [date(2024, 7, 1)]
    assert reviewed_audit.loc[0, "review_status"] == "corrected"
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-07-01"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is True


def test_apply_event_date_reviews_supports_whitespace_normalized_preferred_event_review_id_matching(tmp_path: Path) -> None:
    event_review_id = "AAPL|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    review_file = tmp_path / "whitespace_preferred_review.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                f" {event_review_id} ,AAPL,2024-06-30,2024-07-01,corrected,Preferred review id should still match after normalization",
            ]
        ),
        encoding="utf-8",
    )
    reviews = _load_event_date_reviews(review_file)

    events = [
        ESPPEvent(
            "AAPL",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            event_review_id,
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/aapl.yaml",
                "source_id": "fixture_a",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": event_review_id,
                "included_in_event_study": True,
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert reviews.loc[0, "event_review_id"] == event_review_id
    assert [event.event_date for event in reviewed_events] == [date(2024, 7, 1)]
    assert reviewed_audit.loc[0, "review_status"] == "corrected"
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-07-01"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is True


def test_apply_event_date_reviews_supports_whitespace_normalized_preferred_event_review_id_rejection(tmp_path: Path) -> None:
    event_review_id = "AAPL|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"
    review_file = tmp_path / "whitespace_preferred_rejected_review.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                f" {event_review_id} ,AAPL,2024-06-30,,rejected,Preferred review id should exclude this event after normalization",
            ]
        ),
        encoding="utf-8",
    )
    reviews = _load_event_date_reviews(review_file)

    events = [
        ESPPEvent(
            "AAPL",
            date(2024, 6, 30),
            date(2024, 2, 15),
            "10-K",
            0.8,
            "filing_text_month_day",
            "fixture",
            event_review_id,
        )
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/aapl.yaml",
                "source_id": "fixture_a",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": event_review_id,
                "included_in_event_study": True,
            }
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert reviews.loc[0, "event_review_id"] == event_review_id
    assert reviewed_events == []
    assert reviewed_audit.loc[0, "review_status"] == "rejected"
    assert bool(reviewed_audit.loc[0, "included_in_event_study"]) is False
    assert pd.isna(reviewed_audit.loc[0, "effective_event_date"])


def test_apply_event_date_reviews_prefers_event_review_id_over_legacy_ticker_date_key() -> None:
    reviews = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "event_review_id": "TEST|10-K|2024-02-15|fixture_b|06-30|2024-06-30|filing_text_month_day",
                "original_assigned_event_date": "2024-06-30",
                "reviewed_event_date": "",
                "review_status": "rejected",
                "review_note": "Specific duplicate row should be rejected by id",
            },
            {
                "ticker": "TEST",
                "event_review_id": "",
                "original_assigned_event_date": "2024-06-30",
                "reviewed_event_date": "2024-07-01",
                "review_status": "corrected",
                "review_note": "Legacy fallback applies only to unmatched rows",
            },
        ]
    )
    events = [
        ESPPEvent("TEST", date(2024, 6, 30), date(2024, 2, 15), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"),
        ESPPEvent("TEST", date(2024, 6, 30), date(2024, 2, 15), "10-K", 0.8, "filing_text_month_day", "fixture", "TEST|10-K|2024-02-15|fixture_b|06-30|2024-06-30|filing_text_month_day"),
    ]
    audit = pd.DataFrame(
        [
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/a.yaml",
                "source_id": "fixture_a",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day",
            },
            {
                "ticker": "TEST",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/b.yaml",
                "source_id": "fixture_b",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 0.8,
                "fallback_anchor_used": False,
                "event_review_id": "TEST|10-K|2024-02-15|fixture_b|06-30|2024-06-30|filing_text_month_day",
            },
        ]
    )

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, reviews)

    assert [event.event_review_id for event in reviewed_events] == ["TEST|10-K|2024-02-15|fixture_a|06-30|2024-06-30|filing_text_month_day"]
    assert [event.event_date for event in reviewed_events] == [date(2024, 7, 1)]
    assert reviewed_audit["review_status"].tolist() == ["corrected", "rejected"]
    assert reviewed_audit.loc[0, "effective_event_date"] == "2024-07-01"
    assert pd.isna(reviewed_audit.loc[1, "effective_event_date"])


def test_csv_price_loader_reads_local_prices_without_yfinance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "TEST,2024-06-30,100,101,99,100.5,1000000",
                "TEST,2024-07-01,101,102,100,101.5,1100000",
            ]
        ),
        encoding="utf-8",
    )

    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yfinance":
            raise AssertionError("yfinance should not be imported for CSV-backed price loading")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    loader = CSVPriceLoader(csv_path)
    frame = loader.load_daily_ohlcv("TEST", date(2024, 6, 30), date(2024, 7, 1))

    assert frame.index.strftime("%Y-%m-%d").tolist() == ["2024-06-30", "2024-07-01"]
    assert frame["close"].tolist() == [100.5, 101.5]


def test_csv_price_loader_errors_are_clear(tmp_path: Path) -> None:
    missing_columns = tmp_path / "missing_columns.csv"
    missing_columns.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close",
                "TEST,2024-06-30,100,101,99,100.5",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required columns"):
        CSVPriceLoader(missing_columns).load_daily_ohlcv("TEST", date(2024, 6, 30), date(2024, 6, 30))

    good_csv = tmp_path / "good.csv"
    good_csv.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "TEST,2024-06-30,100,101,99,100.5,1000000",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing ticker"):
        CSVPriceLoader(good_csv).load_daily_ohlcv("OTHER", date(2024, 6, 30), date(2024, 6, 30))

    with pytest.raises(ValueError, match="available range is 2024-06-30..2024-06-30"):
        CSVPriceLoader(good_csv).load_daily_ohlcv("TEST", date(2024, 7, 1), date(2024, 7, 2))


def test_load_config_and_offline_pipeline_use_csv_price_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture_dir = tmp_path / "filings"
    fixture_dir.mkdir()
    (fixture_dir / "aapl.yaml").write_text(
        "\n".join(
            [
                'ticker: "AAPL"',
                'filing_type: "10-K"',
                'filing_date: "2024-02-15"',
                'source_id: "aapl_fixture"',
                'text: |',
                '  The employee stock purchase plan (ESPP) has six-month offering periods.',
                '  The purchase date for each period occurs on June 30 and December 31.',
            ]
        ),
        encoding="utf-8",
    )
    (fixture_dir / "crm.yaml").write_text(
        "\n".join(
            [
                'ticker: "CRM"',
                'filing_type: "10-K"',
                'filing_date: "2024-03-01"',
                'source_id: "crm_fixture"',
                'text: |',
                '  The employee stock purchase plan has recurring purchase dates on January 1 and July 1.',
                '  Each offering period resets after the scheduled purchase date.',
            ]
        ),
        encoding="utf-8",
    )

    review_file = tmp_path / "reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "AAPL|10-K|2024-02-15|aapl_fixture|06-30|2024-06-30|filing_text_month_day,AAPL,2024-06-30,2024-07-01,corrected,Shift to local trading calendar row",
                "AAPL|10-K|2024-02-15|aapl_fixture|12-31|2024-12-31|filing_text_month_day,AAPL,2024-12-31,,accepted,Keep explicit year-end date",
                "CRM|10-K|2024-03-01|crm_fixture|01-01|2025-01-01|filing_text_month_day,CRM,2025-01-01,2025-01-02,corrected,Shift to local trading calendar row",
                "CRM|10-K|2024-03-01|crm_fixture|07-01|2024-07-01|filing_text_month_day,CRM,2024-07-01,,rejected,Reject duplicate summer signal for this smoke replay",
            ]
        ),
        encoding="utf-8",
    )

    price_file = tmp_path / "prices.csv"
    price_file.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "AAPL,2024-06-28,100,101,99,100,1000000",
                "AAPL,2024-06-29,101,102,100,101,900000",
                "AAPL,2024-06-30,102,103,101,102,800000",
                "AAPL,2024-07-01,103,104,102,103,2500000",
                "AAPL,2024-07-02,104,105,103,104,1100000",
                "AAPL,2024-12-30,110,111,109,110,1000000",
                "AAPL,2024-12-31,111,112,110,111,2300000",
                "AAPL,2025-01-01,112,113,111,112,900000",
                "AAPL,2025-01-02,113,114,112,113,1000000",
                "AAPL,2025-01-03,114,115,113,114,1000000",
                "CRM,2024-06-28,200,201,199,200,900000",
                "CRM,2024-06-29,201,202,200,201,850000",
                "CRM,2024-06-30,202,203,201,202,800000",
                "CRM,2024-07-01,203,204,202,203,2200000",
                "CRM,2024-07-02,204,205,203,204,1000000",
                "CRM,2024-12-30,210,211,209,210,1000000",
                "CRM,2024-12-31,211,212,210,211,900000",
                "CRM,2025-01-01,212,213,211,212,850000",
                "CRM,2025-01-02,213,214,212,213,2400000",
                "CRM,2025-01-03,214,215,213,214,1100000",
                "SPY,2024-06-28,300,301,299,300,1500000",
                "SPY,2024-06-29,301,302,300,301,1500000",
                "SPY,2024-06-30,302,303,301,302,1500000",
                "SPY,2024-07-01,303,304,302,303,1500000",
                "SPY,2024-07-02,304,305,303,304,1500000",
                "SPY,2024-12-30,310,311,309,310,1500000",
                "SPY,2024-12-31,311,312,310,311,1500000",
                "SPY,2025-01-01,312,313,311,312,1500000",
                "SPY,2025-01-02,313,314,312,313,1500000",
                "SPY,2025-01-03,314,315,313,314,1500000",
            ]
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "artifacts"
    config_path = tmp_path / "offline.yaml"
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                'price_source: "csv"',
                f'price_data_path: "{price_file.as_posix()}"',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-03"',
                f'output_dir: "{output_dir.as_posix()}"',
                "filings:",
                f'  fixture_dir: "{fixture_dir.as_posix()}"',
                "reviews:",
                f'  review_file: "{review_file.as_posix()}"',
                "tickers:",
                '  - ticker: "AAPL"',
                "    market_cap: 3000000000000",
                "    employees: 161000",
                '  - ticker: "CRM"',
                "    market_cap: 280000000000",
                "    employees: 73600",
                "event_study:",
                "  window_before: 1",
                "  window_after: 1",
                "  volume_lookback: 5",
                "strategy:",
                "  entry_tau: 1",
                "  exit_tau: 1",
                "  volume_spike_threshold: 1.0",
                "  min_confidence: 0.4",
                "cross_section:",
                "  market_cap_bins: [500000000000, 2000000000000]",
                "  volatility_bins: [0.018, 0.032]",
                "  employee_heavy_threshold: 100000",
            ]
        ),
        encoding="utf-8",
    )

    config = _load_config(config_path)
    loader = _build_price_data_provider(config)
    assert isinstance(loader, CSVPriceLoader)

    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yfinance":
            raise AssertionError("yfinance should not be imported for offline CSV pipeline runs")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    run_first_pass_event_study(config_path)

    audit = pd.read_csv(output_dir / "espp_date_audit.csv")
    status_counts = audit["review_status"].value_counts().to_dict()
    assert status_counts["accepted"] == 1
    assert status_counts["corrected"] == 2
    assert status_counts["rejected"] == 1
    assert status_counts["unreviewed"] == 2

    all_events = pd.read_csv(output_dir / "all_event_windows.csv")
    assert sorted(set(all_events["event_date"].astype(str))) == ["2024-07-01", "2024-12-31", "2025-01-02"]
    assert "2024-07-01" in all_events["event_date"].astype(str).tolist()
    assert "2025-01-02" in all_events["event_date"].astype(str).tolist()
    assert "2025-01-01" not in all_events["event_date"].astype(str).tolist()
    assert not ((all_events["ticker"] == "CRM") & (all_events["event_date"].astype(str) == "2024-07-01")).any()


def test_rejected_review_stays_excluded_across_run_first_pass_boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture_dir = tmp_path / "filings"
    fixture_dir.mkdir()
    (fixture_dir / "test.yaml").write_text(
        "\n".join(
            [
                'ticker: "TEST"',
                'filing_type: "10-K"',
                'filing_date: "2024-02-15"',
                'source_id: "test_fixture"',
                'text: |',
                '  The employee stock purchase plan (ESPP) has six-month offering periods.',
                '  The purchase date for each period occurs on June 30 and December 31.',
            ]
        ),
        encoding="utf-8",
    )

    review_file = tmp_path / "reviews.csv"
    review_file.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "TEST|10-K|2024-02-15|test_fixture|06-30|2024-06-30|filing_text_month_day,TEST,2024-06-30,,accepted,Keep the summer event in the study",
                "TEST|10-K|2024-02-15|test_fixture|12-31|2024-12-31|filing_text_month_day,TEST,2024-12-31,,rejected,Reject the year-end event from the study",
            ]
        ),
        encoding="utf-8",
    )

    price_file = tmp_path / "prices.csv"
    price_file.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "TEST,2024-06-28,100,101,99,100,1000000",
                "TEST,2024-06-29,101,102,100,101,900000",
                "TEST,2024-06-30,102,103,101,102,800000",
                "TEST,2024-07-01,103,104,102,103,1100000",
                "TEST,2024-12-30,110,111,109,110,1000000",
                "TEST,2024-12-31,111,112,110,111,1200000",
                "TEST,2025-01-01,112,113,111,112,1000000",
                "SPY,2024-06-28,300,301,299,300,1500000",
                "SPY,2024-06-29,301,302,300,301,1500000",
                "SPY,2024-06-30,302,303,301,302,1500000",
                "SPY,2024-07-01,303,304,302,303,1500000",
                "SPY,2024-12-30,310,311,309,310,1500000",
                "SPY,2024-12-31,311,312,310,311,1500000",
                "SPY,2025-01-01,312,313,311,312,1500000",
            ]
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "artifacts"
    config_path = tmp_path / "offline_rejected_boundary.yaml"
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                'price_source: "csv"',
                f'price_data_path: "{price_file.as_posix()}"',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-01"',
                f'output_dir: "{output_dir.as_posix()}"',
                "filings:",
                f'  fixture_dir: "{fixture_dir.as_posix()}"',
                "reviews:",
                f'  review_file: "{review_file.as_posix()}"',
                "tickers:",
                '  - ticker: "TEST"',
                "    market_cap: 1000000000",
                "    employees: 1000",
                "event_study:",
                "  window_before: 0",
                "  window_after: 1",
                "  volume_lookback: 5",
                "strategy:",
                "  entry_tau: 1",
                "  exit_tau: 1",
                "  volume_spike_threshold: 1.0",
                "  min_confidence: 0.0",
                "cross_section:",
                "  market_cap_bins: [500000000, 2000000000]",
                "  volatility_bins: [0.01, 0.02]",
                "  employee_heavy_threshold: 10000",
            ]
        ),
        encoding="utf-8",
    )

    _guard_yfinance_import(monkeypatch)
    run_first_pass_event_study(config_path)

    audit = pd.read_csv(output_dir / "espp_date_audit.csv")
    rejected_row = audit[audit["event_review_id"] == "TEST|10-K|2024-02-15|test_fixture|12-31|2024-12-31|filing_text_month_day"]
    included_row = audit[audit["event_review_id"] == "TEST|10-K|2024-02-15|test_fixture|06-30|2024-06-30|filing_text_month_day"]
    all_events = pd.read_csv(output_dir / "all_event_windows.csv")

    assert rejected_row["review_status"].tolist() == ["rejected"]
    assert rejected_row["included_in_event_study"].tolist() == [False]
    assert included_row["review_status"].tolist() == ["accepted"]
    assert included_row["included_in_event_study"].tolist() == [True]
    assert sorted(set(all_events["event_date"].astype(str))) == ["2024-06-30"]
    assert "2024-12-31" not in all_events["event_date"].astype(str).tolist()
    assert sorted(set(all_events["ticker"])) == ["TEST"]


def _guard_yfinance_import(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yfinance":
            raise AssertionError("yfinance should not be imported for offline CSV pipeline runs")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)


def _write_temp_config_from_repo_fixture(template_path: Path, output_dir: Path, tmp_path: Path) -> Path:
    config_text = template_path.read_text(encoding="utf-8")
    updated = config_text.replace(
        'output_dir: "artifacts/offline_business_day_example"',
        f'output_dir: "{output_dir.as_posix()}"',
    )
    temp_config = tmp_path / template_path.name
    temp_config.write_text(updated, encoding="utf-8")
    return temp_config


def test_business_day_price_fixture_contains_only_business_day_rows() -> None:
    fixture_path = Path("fixtures/prices/research_business_day_prices.csv")
    prices = pd.read_csv(fixture_path, parse_dates=["date"])

    assert not prices.empty
    assert prices["date"].dt.dayofweek.lt(5).all()
    assert set(prices["date"].dt.strftime("%Y-%m-%d")) == {
        "2024-06-28",
        "2024-07-01",
        "2024-07-02",
        "2024-12-30",
        "2024-12-31",
        "2025-01-02",
        "2025-01-03",
    }


def test_offline_business_day_config_runs_without_live_market_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    template_path = Path("config/offline_business_day_example.yaml")
    output_dir = tmp_path / "artifacts"
    config_path = _write_temp_config_from_repo_fixture(template_path, output_dir, tmp_path)

    config = _load_config(config_path)
    loader = _build_price_data_provider(config)
    assert isinstance(loader, CSVPriceLoader)

    _guard_yfinance_import(monkeypatch)
    run_first_pass_event_study(config_path)

    audit = pd.read_csv(output_dir / "espp_date_audit.csv")
    status_counts = audit["review_status"].value_counts().to_dict()
    assert status_counts["corrected"] == 2
    assert status_counts["accepted"] == 1
    assert status_counts["rejected"] == 3
    assert "unreviewed" not in status_counts

    all_events = pd.read_csv(output_dir / "all_event_windows.csv")
    assert sorted(set(all_events["event_date"].astype(str))) == ["2024-07-01", "2024-12-31", "2025-01-02"]
    assert sorted(audit.loc[audit["included_in_event_study"], "effective_event_date"].dropna().tolist()) == [
        "2024-07-01",
        "2024-12-31",
        "2025-01-02",
    ]
    rejected_fallbacks = audit[
        (audit["ticker"] == "AAPL")
        & (audit["derivation_rule"] == "fallback_default_anchors")
        & (audit["assigned_event_date"].isin(["2025-06-30", "2025-12-31"]))
    ].sort_values("assigned_event_date", ignore_index=True)
    assert rejected_fallbacks["review_status"].tolist() == ["rejected", "rejected"]
    assert rejected_fallbacks["included_in_event_study"].tolist() == [False, False]
    assert rejected_fallbacks["review_note"].str.contains("Manual research exclusion", regex=False).all()
    assert "2024-06-30" not in all_events["event_date"].astype(str).tolist()
    assert "2025-01-01" not in all_events["event_date"].astype(str).tolist()
    assert not ((all_events["ticker"] == "CRM") & (all_events["event_date"].astype(str) == "2024-07-01")).any()
    assert "2025-06-30" not in all_events["event_date"].astype(str).tolist()
    assert "2025-12-31" not in all_events["event_date"].astype(str).tolist()

    summary_path = output_dir / "reports" / "espp_research_summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "Research v0.1 fixture smoke summary" in summary_text
    assert "Descriptive only" in summary_text
    assert "Not a trading signal" in summary_text


def test_business_day_fallback_review_ids_still_match_manual_rejections() -> None:
    review_ids = _load_event_date_reviews(Path("config/espp_business_day_reviews.csv"))
    rejected_fallback_reviews = review_ids[
        (review_ids["ticker"] == "AAPL")
        & (review_ids["review_status"] == "rejected")
        & (review_ids["original_assigned_event_date"].isin(["2025-06-30", "2025-12-31"]))
    ].sort_values("original_assigned_event_date", ignore_index=True)

    assert rejected_fallback_reviews["event_review_id"].tolist() == [
        "AAPL|na|na|default_anchor_aapl_2025_0630|06-30|2025-06-30|fallback_default_anchors",
        "AAPL|na|na|default_anchor_aapl_2025_1231|12-31|2025-12-31|fallback_default_anchors",
    ]

    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": None,
                "filing_date": None,
                "source_fixture_path": None,
                "source_id": "default_anchor_aapl_2025_0630",
                "source_snippet": None,
                "candidate_month_day": "06-30",
                "assigned_event_date": "2025-06-30",
                "derivation_rule": "fallback_default_anchors",
                "confidence": 0.2,
                "fallback_anchor_used": True,
                "event_review_id": "AAPL|na|na|default_anchor_aapl_2025_0630|06-30|2025-06-30|fallback_default_anchors",
            },
            {
                "ticker": "AAPL",
                "filing_type": None,
                "filing_date": None,
                "source_fixture_path": None,
                "source_id": "default_anchor_aapl_2025_1231",
                "source_snippet": None,
                "candidate_month_day": "12-31",
                "assigned_event_date": "2025-12-31",
                "derivation_rule": "fallback_default_anchors",
                "confidence": 0.2,
                "fallback_anchor_used": True,
                "event_review_id": "AAPL|na|na|default_anchor_aapl_2025_1231|12-31|2025-12-31|fallback_default_anchors",
            },
        ]
    )
    events = [
        ESPPEvent("AAPL", date(2025, 6, 30), date(2025, 1, 1), "N/A", 0.2, "fallback_default_anchors", "heuristic", "AAPL|na|na|default_anchor_aapl_2025_0630|06-30|2025-06-30|fallback_default_anchors"),
        ESPPEvent("AAPL", date(2025, 12, 31), date(2025, 1, 1), "N/A", 0.2, "fallback_default_anchors", "heuristic", "AAPL|na|na|default_anchor_aapl_2025_1231|12-31|2025-12-31|fallback_default_anchors"),
    ]

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, rejected_fallback_reviews)

    assert reviewed_events == []
    assert reviewed_audit["review_status"].tolist() == ["rejected", "rejected"]
    assert reviewed_audit["included_in_event_study"].tolist() == [False, False]


def test_business_day_corrected_review_ids_still_match_and_flow_downstream() -> None:
    reviews = _load_event_date_reviews(Path("config/espp_business_day_reviews.csv"))
    corrected_reviews = reviews[
        reviews["event_review_id"].isin(
            [
                "AAPL|10-K|2024-02-15|aapl_2024_10k_fixture|06-30|2024-06-30|filing_text_month_day",
                "CRM|10-K|2024-03-01|crm_2024_10k_fixture|01-01|2025-01-01|filing_text_month_day",
            ]
        )
    ].sort_values("ticker", ignore_index=True)

    assert corrected_reviews["event_review_id"].tolist() == [
        "AAPL|10-K|2024-02-15|aapl_2024_10k_fixture|06-30|2024-06-30|filing_text_month_day",
        "CRM|10-K|2024-03-01|crm_2024_10k_fixture|01-01|2025-01-01|filing_text_month_day",
    ]
    assert corrected_reviews["review_status"].tolist() == ["corrected", "corrected"]
    assert corrected_reviews["reviewed_event_date"].tolist() == ["2024-07-01", "2025-01-02"]

    audit = pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/sec_filings/aapl_2024_10k.yaml",
                "source_id": "aapl_2024_10k_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 1.0,
                "fallback_anchor_used": False,
                "event_review_id": "AAPL|10-K|2024-02-15|aapl_2024_10k_fixture|06-30|2024-06-30|filing_text_month_day",
            },
            {
                "ticker": "CRM",
                "filing_type": "10-K",
                "filing_date": "2024-03-01",
                "source_fixture_path": "fixtures/sec_filings/crm_2024_10k.yaml",
                "source_id": "crm_2024_10k_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "01-01",
                "assigned_event_date": "2025-01-01",
                "derivation_rule": "filing_text_month_day",
                "confidence": 1.0,
                "fallback_anchor_used": False,
                "event_review_id": "CRM|10-K|2024-03-01|crm_2024_10k_fixture|01-01|2025-01-01|filing_text_month_day",
            },
        ]
    )
    events = [
        ESPPEvent("AAPL", date(2024, 6, 30), date(2024, 2, 15), "10-K", 1.0, "filing_text_month_day", "fixture", "AAPL|10-K|2024-02-15|aapl_2024_10k_fixture|06-30|2024-06-30|filing_text_month_day"),
        ESPPEvent("CRM", date(2025, 1, 1), date(2024, 3, 1), "10-K", 1.0, "filing_text_month_day", "fixture", "CRM|10-K|2024-03-01|crm_2024_10k_fixture|01-01|2025-01-01|filing_text_month_day"),
    ]

    reviewed_events, reviewed_audit = _apply_event_date_reviews(events, audit, corrected_reviews)

    assert [event.event_date for event in reviewed_events] == [date(2024, 7, 1), date(2025, 1, 2)]
    assert reviewed_audit["review_status"].tolist() == ["corrected", "corrected"]
    assert reviewed_audit["effective_event_date"].tolist() == ["2024-07-01", "2025-01-02"]
    assert reviewed_audit["included_in_event_study"].tolist() == [True, True]

    idx = pd.to_datetime(["2024-06-28", "2024-07-01", "2024-07-02", "2024-12-31", "2025-01-02", "2025-01-03"])
    price = pd.DataFrame(
        {
            "open": [100, 103, 104, 210, 213, 214],
            "high": [101, 104, 105, 211, 214, 215],
            "low": [99, 102, 103, 209, 212, 213],
            "close": [100, 103, 104, 211, 213, 214],
            "volume": [1_000_000, 2_500_000, 1_100_000, 900_000, 2_400_000, 1_100_000],
        },
        index=idx,
    )
    benchmark = pd.DataFrame(
        {
            "open": [300, 303, 304, 311, 313, 314],
            "high": [301, 304, 305, 312, 314, 315],
            "low": [299, 302, 303, 310, 312, 313],
            "close": [300, 303, 304, 311, 313, 314],
            "volume": [1_500_000] * 6,
        },
        index=idx,
    )
    result = run_event_study(price, benchmark, reviewed_events, EventStudyConfig(window_before=0, window_after=0))

    assert sorted(result.panel["event_date"].astype(str).unique().tolist()) == ["2024-07-01", "2025-01-02"]
    assert "2024-06-30" not in result.panel["event_date"].astype(str).tolist()
    assert "2025-01-01" not in result.panel["event_date"].astype(str).tolist()


def test_business_day_review_csv_fully_covers_generated_reviewed_ids() -> None:
    config = _load_config(Path("config/offline_business_day_example.yaml"))
    reviews = _load_event_date_reviews(Path("config/espp_business_day_reviews.csv"))

    audit_frames: list[pd.DataFrame] = []
    reviewed_statuses: dict[str, str] = {}
    for ticker_cfg in config.tickers:
        docs = _load_filings_for_ticker(config, ticker_cfg.ticker)
        hints = parse_many_espp_hints(docs)
        events, audit = estimate_event_dates_with_audit(
            ticker_cfg.ticker,
            hints,
            config.start_date.year,
            config.end_date.year,
        )
        _, reviewed_audit = _apply_event_date_reviews(events, audit, reviews[reviews["ticker"] == ticker_cfg.ticker].copy())
        audit_frames.append(reviewed_audit)
        ticker_reviewed = reviewed_audit[reviewed_audit["review_status"] != "unreviewed"]
        reviewed_statuses.update(dict(zip(ticker_reviewed["event_review_id"], ticker_reviewed["review_status"])))

    full_audit = pd.concat(audit_frames, ignore_index=True)
    expected_reviews = reviews[reviews["event_review_id"] != ""].copy()

    generated_ids = set(full_audit["event_review_id"].tolist())
    expected_ids = set(expected_reviews["event_review_id"].tolist())
    assert expected_ids.issubset(generated_ids)

    expected_statuses = dict(zip(expected_reviews["event_review_id"], expected_reviews["review_status"]))
    assert reviewed_statuses == expected_statuses
