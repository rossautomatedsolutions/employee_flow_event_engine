from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PHASE2_WARNING_BANNER = (
    "Preliminary research infrastructure output. Descriptive only. "
    "Not a trading signal."
)
PHASE2_LIMITATION = (
    "Current Phase 2 universe uses current S&P 500 membership rather than historical point-in-time membership, "
    "so survivorship and index-selection bias are present."
)


@dataclass(slots=True)
class Phase2SummaryArtifacts:
    summary: dict[str, Any]
    markdown: str
    headline_metrics: pd.DataFrame
    sector_counts: pd.DataFrame


def _normalized_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame.copy() if frame is not None else pd.DataFrame()


def _event_window_count(panel: pd.DataFrame) -> int:
    if panel.empty:
        return 0
    if {"ticker", "event_id"}.issubset(panel.columns):
        return int(panel.loc[:, ["ticker", "event_id"]].drop_duplicates().shape[0])
    if {"ticker", "event_date"}.issubset(panel.columns):
        return int(panel.loc[:, ["ticker", "event_date"]].drop_duplicates().shape[0])
    if "event_id" in panel.columns:
        return int(panel["event_id"].nunique())
    return 0


def _headline_metrics(summary: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "total_universe_companies", "value": summary["total_universe_companies"]},
            {"metric": "unique_issuers", "value": summary["unique_issuers"]},
            {"metric": "companies_processed", "value": summary["companies_processed"]},
            {"metric": "companies_with_espp_mentions", "value": summary["companies_with_espp_mentions"]},
            {"metric": "companies_with_candidate_dates", "value": summary["companies_with_candidate_dates"]},
            {"metric": "accepted_events", "value": summary["accepted_events"]},
            {"metric": "corrected_events", "value": summary["corrected_events"]},
            {"metric": "rejected_events", "value": summary["rejected_events"]},
            {"metric": "companies_with_usable_event_windows", "value": summary["companies_with_usable_event_windows"]},
            {"metric": "event_windows_generated", "value": summary["event_windows_generated"]},
            {"metric": "failures", "value": summary["failures"]},
            {"metric": "warnings", "value": summary["warnings"]},
        ]
    )


def build_phase2_summary(
    universe: pd.DataFrame | None,
    statuses: pd.DataFrame | None,
    audit: pd.DataFrame | None,
    panel: pd.DataFrame | None,
) -> Phase2SummaryArtifacts:
    universe_frame = _normalized_frame(universe)
    status_frame = _normalized_frame(statuses)
    audit_frame = _normalized_frame(audit)
    panel_frame = _normalized_frame(panel)

    processed_statuses = {"completed", "completed_no_espp", "completed_no_usable_events", "warning", "failed"}
    companies_processed = (
        int(status_frame["processing_status"].isin(processed_statuses).sum()) if "processing_status" in status_frame.columns else 0
    )
    sector_counts = (
        status_frame.groupby("sector", as_index=False)
        .agg(
            companies=("ticker", "count"),
            processed=("processing_status", lambda values: int(pd.Series(values).isin(processed_statuses).sum())),
            usable_event_windows=("usable_event_windows", lambda values: int((pd.Series(values) > 0).sum())),
            failures=("processing_status", lambda values: int((pd.Series(values) == "failed").sum())),
        )
        .sort_values("sector", ignore_index=True)
        if not status_frame.empty
        else pd.DataFrame(columns=["sector", "companies", "processed", "usable_event_windows", "failures"])
    )

    counts_by_derivation_rule = (
        audit_frame["derivation_rule"].fillna("unknown").value_counts().sort_index().to_dict()
        if "derivation_rule" in audit_frame.columns and not audit_frame.empty
        else {}
    )
    counts_by_review_status = (
        audit_frame["review_status"].fillna("unreviewed").replace("", "unreviewed").value_counts().sort_index().to_dict()
        if "review_status" in audit_frame.columns and not audit_frame.empty
        else {}
    )

    summary = {
        "warning_banner": PHASE2_WARNING_BANNER,
        "limitation": PHASE2_LIMITATION,
        "total_universe_companies": int(len(universe_frame)),
        "unique_issuers": int(universe_frame["issuer_id"].nunique()) if "issuer_id" in universe_frame.columns and not universe_frame.empty else 0,
        "companies_processed": companies_processed,
        "companies_with_espp_mentions": int((status_frame.get("espp_mentions_found", pd.Series(dtype=int)) > 0).sum()),
        "companies_with_candidate_dates": int((status_frame.get("candidate_events_found", pd.Series(dtype=int)) > 0).sum()),
        "accepted_events": int(status_frame.get("accepted_events", pd.Series(dtype=int)).sum()),
        "corrected_events": int(status_frame.get("corrected_events", pd.Series(dtype=int)).sum()),
        "rejected_events": int(status_frame.get("rejected_events", pd.Series(dtype=int)).sum()),
        "companies_with_usable_event_windows": int((status_frame.get("usable_event_windows", pd.Series(dtype=int)) > 0).sum()),
        "failures": int((status_frame.get("processing_status", pd.Series(dtype=str)) == "failed").sum()),
        "warnings": int(status_frame.get("warning_count", pd.Series(dtype=int)).sum()),
        "counts_by_sector": sector_counts.to_dict("records"),
        "counts_by_derivation_rule": {str(key): int(value) for key, value in counts_by_derivation_rule.items()},
        "counts_by_review_status": {str(key): int(value) for key, value in counts_by_review_status.items()},
        "event_windows_generated": _event_window_count(panel_frame),
    }
    headline_metrics = _headline_metrics(summary)
    return Phase2SummaryArtifacts(
        summary=summary,
        markdown=render_phase2_summary_markdown(summary),
        headline_metrics=headline_metrics,
        sector_counts=sector_counts,
    )


def render_phase2_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Phase 2 Research Infrastructure Summary",
        "",
        f"**{summary['warning_banner']}**",
        "",
        summary["limitation"],
        "",
        "## Coverage",
        "",
        f"- Total universe companies: {summary['total_universe_companies']}",
        f"- Unique issuers: {summary['unique_issuers']}",
        f"- Companies processed: {summary['companies_processed']}",
        f"- Companies with ESPP mentions: {summary['companies_with_espp_mentions']}",
        f"- Companies with candidate dates: {summary['companies_with_candidate_dates']}",
        f"- Accepted events: {summary['accepted_events']}",
        f"- Corrected events: {summary['corrected_events']}",
        f"- Rejected events: {summary['rejected_events']}",
        f"- Companies with usable event windows: {summary['companies_with_usable_event_windows']}",
        f"- Event windows generated: {summary['event_windows_generated']}",
        f"- Failures: {summary['failures']}",
        f"- Warnings: {summary['warnings']}",
        "",
        "## Counts By Review Status",
        "",
    ]
    counts_by_review_status = summary.get("counts_by_review_status", {})
    if counts_by_review_status:
        lines.extend(f"- {key}: {value}" for key, value in counts_by_review_status.items())
    else:
        lines.append("- none")

    lines.extend(["", "## Counts By Derivation Rule", ""])
    counts_by_derivation_rule = summary.get("counts_by_derivation_rule", {})
    if counts_by_derivation_rule:
        lines.extend(f"- {key}: {value}" for key, value in counts_by_derivation_rule.items())
    else:
        lines.append("- none")

    lines.extend(["", "## Counts By Sector", ""])
    counts_by_sector = summary.get("counts_by_sector", [])
    if counts_by_sector:
        lines.extend(
            f"- {row['sector']}: companies={row['companies']}, processed={row['processed']}, "
            f"usable_event_windows={row['usable_event_windows']}, failures={row['failures']}"
            for row in counts_by_sector
        )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This output is meant to validate scalable dataset construction, auditability, and resumable execution. "
            "It is not a trading signal or a predictive model result.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_phase2_summary_reports(
    output_dir: Path,
    universe: pd.DataFrame | None,
    statuses: pd.DataFrame | None,
    audit: pd.DataFrame | None,
    panel: pd.DataFrame | None,
) -> Path:
    artifacts = build_phase2_summary(universe, statuses, audit, panel)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir = output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    report_path = report_dir / "phase2_research_summary.md"
    report_path.write_text(artifacts.markdown, encoding="utf-8")
    artifacts.headline_metrics.to_csv(output_dir / "phase2_summary_metrics.csv", index=False)
    artifacts.sector_counts.to_csv(output_dir / "phase2_sector_counts.csv", index=False)
    return report_path
