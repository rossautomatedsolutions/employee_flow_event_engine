import pandas as pd

from src.analysis.strategy import (
    CrossSectionConfig,
    StrategyConfig,
    assign_cross_sectional_groups,
    filter_event_panel,
    simulate_strategy,
)


def test_assign_cross_sectional_groups() -> None:
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "market_cap": 1e11, "employees": 50000, "daily_volatility": 0.01},
            {"ticker": "BBB", "market_cap": 3e12, "employees": 200000, "daily_volatility": 0.04},
        ]
    )
    grouped = assign_cross_sectional_groups(meta, CrossSectionConfig())
    assert grouped.loc[grouped["ticker"] == "AAA", "market_cap_group"].iloc[0] == "mid_cap"
    assert grouped.loc[grouped["ticker"] == "BBB", "employee_group"].iloc[0] == "employee_heavy"


def test_filter_and_simulate_strategy() -> None:
    panel = pd.DataFrame(
        [
            {"ticker": "AAA", "event_id": 1, "tau": 0, "vol_ratio": 1.5, "confidence": 0.9, "raw_ret": 0.0, "benchmark_ret": 0.0},
            {"ticker": "AAA", "event_id": 1, "tau": 2, "vol_ratio": 1.1, "confidence": 0.9, "raw_ret": 0.01, "benchmark_ret": 0.002},
            {"ticker": "AAA", "event_id": 1, "tau": 3, "vol_ratio": 1.1, "confidence": 0.9, "raw_ret": 0.01, "benchmark_ret": 0.002},
            {"ticker": "AAA", "event_id": 1, "tau": 4, "vol_ratio": 1.1, "confidence": 0.9, "raw_ret": 0.01, "benchmark_ret": 0.002},
            {"ticker": "AAA", "event_id": 1, "tau": 5, "vol_ratio": 1.1, "confidence": 0.9, "raw_ret": 0.01, "benchmark_ret": 0.002},
            {"ticker": "BBB", "event_id": 2, "tau": 0, "vol_ratio": 1.0, "confidence": 0.9, "raw_ret": 0.0, "benchmark_ret": 0.0},
            {"ticker": "BBB", "event_id": 2, "tau": 2, "vol_ratio": 1.1, "confidence": 0.9, "raw_ret": -0.01, "benchmark_ret": 0.002},
        ]
    )

    filtered = filter_event_panel(panel, StrategyConfig(volume_spike_threshold=1.25, min_confidence=0.7))
    assert set(filtered["event_id"].unique()) == {1}

    groups = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "market_cap_group": "large_cap",
                "volatility_group": "mid_vol",
                "employee_group": "employee_light",
            }
        ]
    )
    artifacts = simulate_strategy(filtered, groups, StrategyConfig(entry_tau=1, exit_tau=5))
    assert not artifacts.overall_summary.empty
    assert artifacts.overall_summary["win_rate"].iloc[0] == 1.0
