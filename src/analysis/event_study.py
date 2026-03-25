from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analysis.metrics import abnormal_returns, daily_returns, mean_and_tstat, volume_spike_ratio


@dataclass(slots=True)
class EventStudyConfig:
    window_before: int = 10
    window_after: int = 10
    volume_lookback: int = 20
    label: str = "event"


@dataclass(slots=True)
class EventStudyResult:
    panel: pd.DataFrame
    event_study_table: pd.DataFrame
    summary_stats: pd.DataFrame
    metrics: pd.DataFrame
    plots: dict[str, plt.Figure]

    @property
    def aar_summary(self) -> pd.DataFrame:
        """Backward-compatible alias used by existing pipeline code."""
        return self.event_study_table


def _extract_event_meta(event: Any) -> tuple[pd.Timestamp | None, dict[str, Any]]:
    if isinstance(event, pd.Timestamp):
        return event.normalize(), {}
    if isinstance(event, str):
        return pd.Timestamp(event).normalize(), {}

    # Generic object contract: event_date/date + optional metadata attributes.
    event_date = getattr(event, "event_date", getattr(event, "date", None))
    if event_date is None:
        return None, {}

    meta: dict[str, Any] = {}
    for attr in ("ticker", "event_type", "confidence", "approximation_method", "source"):
        if hasattr(event, attr):
            meta[attr] = getattr(event, attr)
    return pd.Timestamp(event_date).normalize(), meta


def _coerce_event_dates(events: Iterable[Any]) -> list[tuple[pd.Timestamp, dict[str, Any]]]:
    parsed: list[tuple[pd.Timestamp, dict[str, Any]]] = []
    for item in events:
        ts, meta = _extract_event_meta(item)
        if ts is not None:
            parsed.append((ts, meta))
    return parsed


def _event_window_index(anchor: int, before: int, after: int, limit: int) -> np.ndarray:
    start = max(0, anchor - before)
    stop = min(limit, anchor + after + 1)
    return np.arange(start, stop)


def _build_plots(table: pd.DataFrame, label: str) -> dict[str, plt.Figure]:
    if table.empty:
        return {}

    figs: dict[str, plt.Figure] = {}

    ret_fig, ret_ax = plt.subplots(figsize=(9, 4))
    ret_ax.plot(table["tau"], table["mean_abret"], marker="o", label="Mean abnormal return")
    ret_ax.plot(table["tau"], table["cum_mean_abret"], marker="o", label="Cumulative mean abnormal return")
    ret_ax.axhline(0.0, color="black", linestyle="--", linewidth=0.8)
    ret_ax.set_title(f"{label.title()} study returns")
    ret_ax.set_xlabel("Event time (tau)")
    ret_ax.set_ylabel("Return")
    ret_ax.legend()
    ret_fig.tight_layout()
    figs["returns"] = ret_fig

    vol_fig, vol_ax = plt.subplots(figsize=(9, 4))
    vol_ax.plot(table["tau"], table["mean_vol_ratio"], marker="o", color="tab:green", label="Volume / trailing average")
    vol_ax.axhline(1.0, color="black", linestyle="--", linewidth=0.8)
    vol_ax.set_title(f"{label.title()} volume reaction")
    vol_ax.set_xlabel("Event time (tau)")
    vol_ax.set_ylabel("Volume ratio")
    vol_ax.legend()
    vol_fig.tight_layout()
    figs["volume"] = vol_fig

    return figs


def run_event_study(
    price_frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame,
    events: Iterable[Any],
    config: EventStudyConfig | None = None,
) -> EventStudyResult:
    cfg = config or EventStudyConfig()

    prices = price_frame.copy()
    benchmark = benchmark_frame.copy()
    prices.index = pd.to_datetime(prices.index).normalize()
    benchmark.index = pd.to_datetime(benchmark.index).normalize()
    prices = prices.sort_index()
    benchmark = benchmark.sort_index()

    required_cols = {"close", "volume"}
    missing = required_cols.difference(prices.columns)
    if missing:
        raise ValueError(f"price_frame missing required columns: {sorted(missing)}")
    if "close" not in benchmark.columns:
        raise ValueError("benchmark_frame missing required column: ['close']")

    prices["ret"] = daily_returns(prices["close"])
    benchmark["ret"] = daily_returns(benchmark["close"])
    prices["abret"] = abnormal_returns(prices["ret"], benchmark["ret"]).reindex(prices.index)
    prices["cum_ret"] = prices["ret"].cumsum()
    prices["cum_abret"] = prices["abret"].fillna(0.0).cumsum()
    prices["vol_ratio"] = volume_spike_ratio(prices["volume"], lookback=cfg.volume_lookback)

    parsed_events = _coerce_event_dates(events)

    rows: list[dict[str, Any]] = []
    index = prices.index
    for event_id, (event_ts, meta) in enumerate(parsed_events, start=1):
        if event_ts not in index:
            continue
        anchor = int(index.get_loc(event_ts))
        positions = _event_window_index(anchor, cfg.window_before, cfg.window_after, len(index))
        window = prices.iloc[positions].copy()
        window["tau"] = positions - anchor
        window["event_id"] = event_id
        window["event_date"] = event_ts.date()
        for key, value in meta.items():
            window[key] = value
        rows.extend(
            window[["event_id", "event_date", "tau", "ret", "abret", "cum_ret", "cum_abret", "vol_ratio"] + [c for c in meta.keys() if c in window.columns]]
            .rename(columns={"ret": "raw_ret", "abret": "abnormal_ret"})
            .to_dict("records")
        )

    panel = pd.DataFrame(rows)
    if panel.empty:
        empty = pd.DataFrame()
        return EventStudyResult(panel=panel, event_study_table=empty, summary_stats=empty, metrics=empty, plots={})

    grouped = panel.groupby("tau")
    event_study_table = pd.DataFrame(
        {
            "tau": grouped.size().index,
            "n_obs": grouped.size().values,
            "mean_raw_ret": grouped["raw_ret"].mean().values,
            "median_raw_ret": grouped["raw_ret"].median().values,
            "std_raw_ret": grouped["raw_ret"].std(ddof=1).fillna(0.0).values,
            "mean_abret": grouped["abnormal_ret"].mean().values,
            "median_abret": grouped["abnormal_ret"].median().values,
            "std_abret": grouped["abnormal_ret"].std(ddof=1).fillna(0.0).values,
            "mean_vol_ratio": grouped["vol_ratio"].mean().values,
            "median_vol_ratio": grouped["vol_ratio"].median().values,
            "std_vol_ratio": grouped["vol_ratio"].std(ddof=1).fillna(0.0).values,
            "t_stat_abret": grouped["abnormal_ret"].apply(lambda x: mean_and_tstat(x)[1]).values,
        }
    ).sort_values("tau", ignore_index=True)
    event_study_table["cum_mean_raw_ret"] = event_study_table["mean_raw_ret"].cumsum()
    event_study_table["cum_mean_abret"] = event_study_table["mean_abret"].cumsum()
    # Backward-compatible column aliases expected by older callers.
    event_study_table["aar"] = event_study_table["mean_abret"]
    event_study_table["caar"] = event_study_table["cum_mean_abret"]
    event_study_table["t_stat"] = event_study_table["t_stat_abret"]
    event_study_table["avg_volume_spike"] = event_study_table["mean_vol_ratio"]

    summary_stats = pd.DataFrame(
        {
            "metric": [
                "events_used",
                "window_before",
                "window_after",
                "avg_event_raw_ret",
                "avg_event_abnormal_ret",
                "avg_event_volume_ratio",
            ],
            "value": [
                float(panel["event_id"].nunique()),
                float(cfg.window_before),
                float(cfg.window_after),
                float(panel["raw_ret"].mean()),
                float(panel["abnormal_ret"].mean()),
                float(panel["vol_ratio"].mean()),
            ],
        }
    )

    metrics_rows: list[dict[str, float]] = []
    for horizon in (1, 3, 5):
        horizon_slice = panel[panel["tau"].between(1, horizon)].groupby("event_id", as_index=False).agg(
            horizon_return=("raw_ret", "sum"),
            horizon_abret=("abnormal_ret", "sum"),
        )
        if horizon_slice.empty:
            continue
        t_stat = mean_and_tstat(horizon_slice["horizon_return"])[1]
        metrics_rows.append(
            {
                "horizon": float(horizon),
                "mean_return": float(horizon_slice["horizon_return"].mean()),
                "mean_abnormal_return": float(horizon_slice["horizon_abret"].mean()),
                "hit_rate_positive": float((horizon_slice["horizon_return"] > 0).mean()),
                "hit_rate_negative": float((horizon_slice["horizon_return"] < 0).mean()),
                "t_stat_mean_return": float(t_stat),
            }
        )
    metrics = pd.DataFrame(metrics_rows)

    plots = _build_plots(event_study_table, cfg.label)
    return EventStudyResult(
        panel=panel,
        event_study_table=event_study_table,
        summary_stats=summary_stats,
        metrics=metrics,
        plots=plots,
    )
