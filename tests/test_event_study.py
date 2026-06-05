from datetime import date
import sys
import types

import pandas as pd

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

from src.analysis.event_study import EventStudyConfig, run_event_study
from src.events.espp_event_extractor import ESPPEvent


def test_run_event_study_builds_expected_tau_range() -> None:
    idx = pd.bdate_range("2024-01-01", periods=40)
    price = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": [100 + i * 0.1 for i in range(len(idx))],
            "volume": [1_000_000 + i * 100 for i in range(len(idx))],
        },
        index=idx,
    )
    benchmark = price.copy()

    event_dt = idx[20].date()
    result = run_event_study(
        price,
        benchmark,
        [
            ESPPEvent(
                ticker="TEST",
                event_date=event_dt,
                source_filing_date=date(2024, 2, 1),
                source_filing_type="10-K",
                confidence=0.8,
                approximation_method="unit-test",
            )
        ],
        EventStudyConfig(window_before=10, window_after=10),
    )

    assert not result.panel.empty
    assert result.panel["tau"].min() == -10
    assert result.panel["tau"].max() == 10
    assert len(result.aar_summary) == 21
