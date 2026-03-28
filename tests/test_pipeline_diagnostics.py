import pandas as pd

from src.pipeline.run_event_study import _diagnostic_conclusion, _distribution_summary, _horizon_returns


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
