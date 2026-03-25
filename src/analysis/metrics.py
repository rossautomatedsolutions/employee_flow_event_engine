from __future__ import annotations

import math

import numpy as np
import pandas as pd


def daily_returns(close_series: pd.Series) -> pd.Series:
    return close_series.astype(float).pct_change().fillna(0.0)


def abnormal_returns(asset_returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
    aligned_asset, aligned_benchmark = asset_returns.align(benchmark_returns, join="inner")
    return aligned_asset - aligned_benchmark


def mean_and_tstat(series: pd.Series) -> tuple[float, float]:
    cleaned = series.dropna().astype(float)
    if cleaned.empty:
        return 0.0, 0.0

    mean = float(cleaned.mean())
    std = float(cleaned.std(ddof=1))
    if math.isclose(std, 0.0) or len(cleaned) < 2:
        return mean, 0.0

    t_stat = mean / (std / math.sqrt(len(cleaned)))
    return mean, float(t_stat)


def volume_spike_ratio(volume_series: pd.Series, lookback: int = 20) -> pd.Series:
    baseline = volume_series.astype(float).rolling(window=lookback, min_periods=max(5, lookback // 2)).mean()
    ratio = volume_series / baseline
    return ratio.replace([np.inf, -np.inf], np.nan).fillna(1.0)
