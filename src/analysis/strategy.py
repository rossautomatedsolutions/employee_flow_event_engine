from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class StrategyConfig:
    entry_tau: int = 1
    exit_tau: int = 5
    volume_spike_threshold: float = 1.25
    min_confidence: float = 0.7


@dataclass(slots=True)
class CrossSectionConfig:
    market_cap_bins: tuple[float, float] = (2e10, 2e11)
    volatility_bins: tuple[float, float] = (0.015, 0.03)
    employee_heavy_threshold: int = 100_000


@dataclass(slots=True)
class StrategyArtifacts:
    event_level: pd.DataFrame
    group_summary: pd.DataFrame
    overall_summary: pd.DataFrame


def assign_cross_sectional_groups(
    ticker_frame: pd.DataFrame,
    cross_cfg: CrossSectionConfig,
) -> pd.DataFrame:
    frame = ticker_frame.copy()

    cap_labels = ["small_cap", "mid_cap", "large_cap"]
    frame["market_cap_group"] = pd.cut(
        frame["market_cap"],
        bins=[-np.inf, cross_cfg.market_cap_bins[0], cross_cfg.market_cap_bins[1], np.inf],
        labels=cap_labels,
    ).astype(str)

    vol_labels = ["low_vol", "mid_vol", "high_vol"]
    frame["volatility_group"] = pd.cut(
        frame["daily_volatility"],
        bins=[-np.inf, cross_cfg.volatility_bins[0], cross_cfg.volatility_bins[1], np.inf],
        labels=vol_labels,
    ).astype(str)

    frame["employee_group"] = np.where(
        frame["employees"] >= cross_cfg.employee_heavy_threshold,
        "employee_heavy",
        "employee_light",
    )

    return frame


def filter_event_panel(panel: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    frame = panel.copy()
    required_cols = {"event_id", "tau", "vol_ratio", "confidence"}
    missing = required_cols.difference(frame.columns)
    if missing:
        raise ValueError(f"Panel missing required columns for filtering: {sorted(missing)}")

    tau_zero = frame[frame["tau"] == 0]
    qualified_events = tau_zero[
        (tau_zero["vol_ratio"] > cfg.volume_spike_threshold) & (tau_zero["confidence"] >= cfg.min_confidence)
    ]["event_id"].unique()

    return frame[frame["event_id"].isin(qualified_events)].copy()


def _window_compounded_return(frame: pd.DataFrame, start_tau: int, end_tau: int, return_col: str) -> float:
    window = frame[frame["tau"].between(start_tau, end_tau)][return_col].astype(float)
    if window.empty:
        return float("nan")
    return float((1.0 + window).prod() - 1.0)


def simulate_strategy(
    filtered_panel: pd.DataFrame,
    ticker_groups: pd.DataFrame,
    cfg: StrategyConfig,
) -> StrategyArtifacts:
    if filtered_panel.empty:
        empty = pd.DataFrame()
        return StrategyArtifacts(event_level=empty, group_summary=empty, overall_summary=empty)

    rows: list[dict[str, float | str]] = []
    for (ticker, event_id), event_slice in filtered_panel.groupby(["ticker", "event_id"]):
        strategy_ret = _window_compounded_return(event_slice, cfg.entry_tau + 1, cfg.exit_tau, "raw_ret")
        baseline_ret = _window_compounded_return(event_slice, cfg.entry_tau + 1, cfg.exit_tau, "benchmark_ret")
        if math.isnan(strategy_ret) or math.isnan(baseline_ret):
            continue
        rows.append(
            {
                "ticker": str(ticker),
                "event_id": float(event_id),
                "strategy_return": strategy_ret,
                "baseline_return": baseline_ret,
                "excess_return": strategy_ret - baseline_ret,
            }
        )

    event_level = pd.DataFrame(rows)
    if event_level.empty:
        empty = pd.DataFrame()
        return StrategyArtifacts(event_level=empty, group_summary=empty, overall_summary=empty)

    event_level = event_level.merge(ticker_groups, on="ticker", how="left")
    group_summary = _summarize_by_group(event_level)
    overall_summary = _summarize_performance(event_level.assign(group="all")).drop(columns=["group"])
    return StrategyArtifacts(event_level=event_level, group_summary=group_summary, overall_summary=overall_summary)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0).astype(float)).cumprod()
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def _summarize_performance(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby("group", as_index=False)
    rows: list[dict[str, float | str]] = []
    for group, g in grouped:
        excess = g["excess_return"].astype(float)
        std = float(excess.std(ddof=1))
        sharpe = 0.0 if math.isclose(std, 0.0) else float(excess.mean() / std * math.sqrt(252 / max(1, len(excess))))
        rows.append(
            {
                "group": str(group),
                "n_events": float(len(g)),
                "avg_strategy_return": float(g["strategy_return"].mean()),
                "avg_baseline_return": float(g["baseline_return"].mean()),
                "avg_excess_return": float(excess.mean()),
                "win_rate": float((g["strategy_return"] > g["baseline_return"]).mean()),
                "sharpe_ratio": sharpe,
                "max_drawdown": _max_drawdown(excess),
            }
        )
    return pd.DataFrame(rows)


def _summarize_by_group(event_level: pd.DataFrame) -> pd.DataFrame:
    summaries: list[pd.DataFrame] = []
    for dim in ("market_cap_group", "volatility_group", "employee_group"):
        temp = event_level.copy()
        temp["group"] = temp[dim].astype(str)
        summary = _summarize_performance(temp)
        summary.insert(0, "dimension", dim)
        summaries.append(summary)
    return pd.concat(summaries, ignore_index=True)
