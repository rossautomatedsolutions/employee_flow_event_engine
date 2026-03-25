from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analysis.metrics import abnormal_returns, daily_returns, mean_and_tstat, volume_spike_ratio
from src.events.espp_event_extractor import ESPPEvent


@dataclass(slots=True)
class EventStudyConfig:
    window_before: int = 10
    window_after: int = 10


@dataclass(slots=True)
class EventStudyResult:
    panel: pd.DataFrame
    aar_summary: pd.DataFrame


def _event_window_index(anchor: int, before: int, after: int, limit: int) -> list[int]:
    start = max(0, anchor - before)
    stop = min(limit, anchor + after + 1)
    return list(range(start, stop))


def run_event_study(
    price_frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame,
    events: list[ESPPEvent],
    config: EventStudyConfig,
) -> EventStudyResult:
    prices = price_frame.sort_index().copy()
    benchmark = benchmark_frame.sort_index().copy()

    prices["ret"] = daily_returns(prices["close"])
    benchmark["ret"] = daily_returns(benchmark["close"])
    prices["abret"] = abnormal_returns(prices["ret"], benchmark["ret"])
    prices["vol_spike"] = volume_spike_ratio(prices["volume"])

    rows: list[dict] = []
    index = prices.index
    for event in events:
        ts = pd.Timestamp(event.event_date)
        if ts not in index:
            continue

        anchor = index.get_loc(ts)
        window_rows = _event_window_index(anchor, config.window_before, config.window_after, len(index))
        for pos in window_rows:
            dt = index[pos]
            rows.append(
                {
                    "ticker": event.ticker,
                    "event_date": event.event_date,
                    "date": dt.date(),
                    "tau": pos - anchor,
                    "ret": float(prices.iloc[pos]["ret"]),
                    "abret": float(prices.iloc[pos]["abret"]),
                    "vol_spike": float(prices.iloc[pos]["vol_spike"]),
                    "confidence": event.confidence,
                    "approximation_method": event.approximation_method,
                }
            )

    panel = pd.DataFrame(rows)
    if panel.empty:
        return EventStudyResult(panel=panel, aar_summary=pd.DataFrame())

    grouped = panel.groupby("tau", as_index=False)
    aar = grouped["abret"].mean().rename(columns={"abret": "aar"})
    caar = aar["aar"].cumsum()

    tstats = grouped["abret"].apply(lambda x: mean_and_tstat(x)[1]).rename("t_stat")
    vol = grouped["vol_spike"].mean().rename("avg_volume_spike")

    aar_summary = aar.join(tstats, on="tau").join(vol, on="tau")
    aar_summary["caar"] = caar
    return EventStudyResult(panel=panel, aar_summary=aar_summary)
