from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

WARNING_BANNER = (
    "Research v0.1 fixture smoke summary. Descriptive only. "
    "Not statistically meaningful. Not a trading signal."
)


@dataclass(slots=True)
class ResearchSummary:
    summary: dict[str, Any]
    markdown: str


def _normalized_audit_frame(audit: pd.DataFrame | None) -> pd.DataFrame:
    frame = audit.copy() if audit is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "derivation_rule",
                "review_status",
                "effective_event_date",
                "included_in_event_study",
            ]
        )

    if "review_status" not in frame.columns:
        frame["review_status"] = "unreviewed"
    else:
        frame["review_status"] = frame["review_status"].fillna("unreviewed").replace("", "unreviewed")

    if "included_in_event_study" not in frame.columns:
        frame["included_in_event_study"] = False
    frame["included_in_event_study"] = frame["included_in_event_study"].map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes"}
        if not isinstance(value, bool)
        else value
    )
    return frame


def _normalized_panel_frame(panel: pd.DataFrame | None) -> pd.DataFrame:
    return panel.copy() if panel is not None else pd.DataFrame()


def _event_pairs_from_audit(audit: pd.DataFrame) -> set[tuple[str, str]]:
    if audit.empty:
        return set()
    included = audit[audit["included_in_event_study"]].copy()
    included["effective_event_date"] = pd.to_datetime(included["effective_event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    included = included.dropna(subset=["ticker", "effective_event_date"])
    return set(zip(included["ticker"].astype(str), included["effective_event_date"].astype(str)))


def _event_pairs_from_panel(panel: pd.DataFrame) -> set[tuple[str, str]]:
    if panel.empty or not {"ticker", "event_date"}.issubset(panel.columns):
        return set()
    events = panel.loc[:, ["ticker", "event_date"]].drop_duplicates().copy()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    events = events.dropna(subset=["ticker", "event_date"])
    return set(zip(events["ticker"].astype(str), events["event_date"].astype(str)))


def _return_snapshot(panel: pd.DataFrame, tau: int) -> dict[str, float | None]:
    if panel.empty or "tau" not in panel.columns:
        return {
            "mean_raw_return": None,
            "median_raw_return": None,
            "mean_abnormal_return": None,
            "median_abnormal_return": None,
        }
    window = panel[panel["tau"] == tau]
    if window.empty:
        return {
            "mean_raw_return": None,
            "median_raw_return": None,
            "mean_abnormal_return": None,
            "median_abnormal_return": None,
        }
    return {
        "mean_raw_return": float(window["raw_ret"].mean()) if "raw_ret" in window.columns else None,
        "median_raw_return": float(window["raw_ret"].median()) if "raw_ret" in window.columns else None,
        "mean_abnormal_return": float(window["abnormal_ret"].mean()) if "abnormal_ret" in window.columns else None,
        "median_abnormal_return": float(window["abnormal_ret"].median()) if "abnormal_ret" in window.columns else None,
    }


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2%}"


def build_research_summary(audit: pd.DataFrame | None, panel: pd.DataFrame | None) -> ResearchSummary:
    audit_frame = _normalized_audit_frame(audit)
    panel_frame = _normalized_panel_frame(panel)

    review_counts = audit_frame["review_status"].value_counts().sort_index().to_dict() if not audit_frame.empty else {}
    derivation_counts = audit_frame["derivation_rule"].fillna("unknown").value_counts().sort_index().to_dict() if "derivation_rule" in audit_frame.columns and not audit_frame.empty else {}

    included_dates = pd.to_datetime(
        audit_frame.loc[audit_frame["included_in_event_study"], "effective_event_date"],
        errors="coerce",
    ).dropna()
    event_pairs_from_audit = _event_pairs_from_audit(audit_frame)
    event_pairs_from_panel = _event_pairs_from_panel(panel_frame)
    missing_or_empty = len(event_pairs_from_audit.difference(event_pairs_from_panel))
    generated_window_count = len(event_pairs_from_panel)

    tau_zero = _return_snapshot(panel_frame, tau=0)
    tau_plus_one = _return_snapshot(panel_frame, tau=1)
    insufficient_for_inference = generated_window_count < 10

    summary: dict[str, Any] = {
        "warning_banner": WARNING_BANNER,
        "total_candidate_events": int(len(audit_frame)),
        "accepted_events": int(review_counts.get("accepted", 0)),
        "corrected_events": int(review_counts.get("corrected", 0)),
        "rejected_events": int(review_counts.get("rejected", 0)),
        "included_in_event_study_count": int(audit_frame["included_in_event_study"].sum()) if not audit_frame.empty else 0,
        "number_of_tickers": int(audit_frame["ticker"].dropna().astype(str).nunique()) if "ticker" in audit_frame.columns and not audit_frame.empty else 0,
        "event_date_start": included_dates.min().date().isoformat() if not included_dates.empty else None,
        "event_date_end": included_dates.max().date().isoformat() if not included_dates.empty else None,
        "event_windows_generated": generated_window_count,
        "missing_or_empty_price_window_count": int(missing_or_empty),
        "counts_by_derivation_rule": {str(key): int(value) for key, value in derivation_counts.items()},
        "counts_by_review_status": {str(key): int(value) for key, value in review_counts.items()},
        "event_day_returns": tau_zero,
        "t_plus_1_returns": tau_plus_one,
        "insufficient_for_inference": insufficient_for_inference,
    }
    markdown = render_research_summary_markdown(summary)
    return ResearchSummary(summary=summary, markdown=markdown)


def render_research_summary_markdown(summary: dict[str, Any]) -> str:
    counts_by_status = summary.get("counts_by_review_status", {})
    counts_by_rule = summary.get("counts_by_derivation_rule", {})
    lines = [
        "# ESPP Research Summary",
        "",
        f"**{summary['warning_banner']}**",
        "",
        "This report is a Research v0.1 fixture smoke summary for offline ESPP event-study outputs.",
        "It is descriptive only, is not statistically meaningful on small fixture samples, and is not a trading signal.",
        "",
        "## Coverage",
        "",
        f"- Total candidate events: {summary['total_candidate_events']}",
        f"- Accepted events: {summary['accepted_events']}",
        f"- Corrected events: {summary['corrected_events']}",
        f"- Rejected events: {summary['rejected_events']}",
        f"- Included in event study: {summary['included_in_event_study_count']}",
        f"- Number of tickers: {summary['number_of_tickers']}",
        f"- Event date range: {summary['event_date_start'] or 'n/a'} to {summary['event_date_end'] or 'n/a'}",
        f"- Event windows generated: {summary['event_windows_generated']}",
        f"- Missing or empty price windows: {summary['missing_or_empty_price_window_count']}",
        "",
        "## Return Snapshots",
        "",
        f"- Event day mean raw return: {_format_percent(summary['event_day_returns']['mean_raw_return'])}",
        f"- Event day median raw return: {_format_percent(summary['event_day_returns']['median_raw_return'])}",
        f"- Event day mean abnormal return: {_format_percent(summary['event_day_returns']['mean_abnormal_return'])}",
        f"- Event day median abnormal return: {_format_percent(summary['event_day_returns']['median_abnormal_return'])}",
        f"- t+1 mean raw return: {_format_percent(summary['t_plus_1_returns']['mean_raw_return'])}",
        f"- t+1 median raw return: {_format_percent(summary['t_plus_1_returns']['median_raw_return'])}",
        f"- t+1 mean abnormal return: {_format_percent(summary['t_plus_1_returns']['mean_abnormal_return'])}",
        f"- t+1 median abnormal return: {_format_percent(summary['t_plus_1_returns']['median_abnormal_return'])}",
        "",
        "## Review Status Counts",
        "",
    ]
    if counts_by_status:
        lines.extend([f"- {key}: {value}" for key, value in counts_by_status.items()])
    else:
        lines.append("- none")

    lines.extend(["", "## Derivation Rule Counts", ""])
    if counts_by_rule:
        lines.extend([f"- {key}: {value}" for key, value in counts_by_rule.items()])
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The current fixture sample is insufficient for inference and should only be used to decide whether deeper research setup work is justified."
            if summary.get("insufficient_for_inference", False)
            else "The sample is still descriptive only and should not be treated as a trading signal or production conclusion.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_research_summary_report(output_dir: Path, audit: pd.DataFrame | None, panel: pd.DataFrame | None) -> Path:
    report = build_research_summary(audit, panel)
    report_dir = output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "espp_research_summary.md"
    report_path.write_text(report.markdown, encoding="utf-8")
    return report_path
