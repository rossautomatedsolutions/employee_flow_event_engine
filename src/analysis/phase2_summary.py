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
    rows = [
        {"metric": "total_universe_companies", "value": summary["total_universe_companies"]},
        {"metric": "unique_issuers", "value": summary["unique_issuers"]},
        {"metric": "companies_processed", "value": summary["companies_processed"]},
        {"metric": "companies_with_espp_mentions", "value": summary["companies_with_espp_mentions"]},
        {"metric": "companies_with_candidate_dates", "value": summary["companies_with_candidate_dates"]},
        {"metric": "accepted_events", "value": summary["accepted_events"]},
        {"metric": "corrected_events", "value": summary["corrected_events"]},
        {"metric": "rejected_events", "value": summary["rejected_events"]},
        {"metric": "unresolved_events", "value": summary["unresolved_events"]},
        {"metric": "future_scheduled_events", "value": summary["future_scheduled_events"]},
        {"metric": "companies_with_usable_event_windows", "value": summary["companies_with_usable_event_windows"]},
        {"metric": "event_windows_generated", "value": summary["event_windows_generated"]},
        {"metric": "failures", "value": summary["failures"]},
        {"metric": "warnings", "value": summary["warnings"]},
    ]
    for optional_metric in (
        "filings_discovered",
        "filings_matching_forms",
        "filings_in_date_window",
        "filings_selected",
        "raw_candidate_dates",
        "deduplicated_candidates",
        "candidates_awaiting_review",
        "provisional_diagnostic_windows",
    ):
        if optional_metric in summary:
            rows.append({"metric": optional_metric, "value": summary[optional_metric]})
    return pd.DataFrame(rows)


def _pipe_value_counts(values: pd.Series) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values.fillna("").astype(str):
        for part in [candidate.strip() for candidate in value.split("|")]:
            if not part:
                continue
            counts[part] = counts.get(part, 0) + 1
    return dict(sorted(counts.items()))


def build_phase2_summary(
    universe: pd.DataFrame | None,
    statuses: pd.DataFrame | None,
    audit: pd.DataFrame | None,
    panel: pd.DataFrame | None,
    raw_candidates: pd.DataFrame | None = None,
    review_queue: pd.DataFrame | None = None,
    provisional_panel: pd.DataFrame | None = None,
) -> Phase2SummaryArtifacts:
    universe_frame = _normalized_frame(universe)
    status_frame = _normalized_frame(statuses)
    audit_frame = _normalized_frame(audit)
    panel_frame = _normalized_frame(panel)
    raw_candidate_frame = _normalized_frame(raw_candidates)
    review_queue_frame = _normalized_frame(review_queue)
    provisional_panel_frame = _normalized_frame(provisional_panel)

    processed_statuses = {
        "completed",
        "completed_no_espp",
        "completed_no_usable_events",
        "completed_pending_review",
        "warning",
        "failed",
    }
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
    counts_by_extraction_confidence = (
        raw_candidate_frame["extraction_confidence"].fillna("unknown").value_counts().sort_index().to_dict()
        if "extraction_confidence" in raw_candidate_frame.columns and not raw_candidate_frame.empty
        else {}
    )
    counts_by_ambiguity_flag = (
        _pipe_value_counts(raw_candidate_frame["ambiguity_flags"])
        if "ambiguity_flags" in raw_candidate_frame.columns and not raw_candidate_frame.empty
        else {}
    )
    filing_window_configured = sorted(
        {
            (str(start), str(end))
            for start, end in zip(
                status_frame.get("configured_filing_start_date", pd.Series(dtype=str)).fillna(""),
                status_frame.get("configured_filing_end_date", pd.Series(dtype=str)).fillna(""),
            )
            if start or end
        }
    )
    effective_filing_window = sorted(
        {
            (str(start), str(end))
            for start, end in zip(
                status_frame.get("effective_filing_start_date", pd.Series(dtype=str)).fillna(""),
                status_frame.get("effective_filing_end_date", pd.Series(dtype=str)).fillna(""),
            )
            if start or end
        }
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
        "unresolved_events": int(status_frame.get("unresolved_events", pd.Series(dtype=int)).sum()),
        "future_scheduled_events": int(status_frame.get("future_scheduled_events", pd.Series(dtype=int)).sum()),
        "companies_with_usable_event_windows": int((status_frame.get("usable_event_windows", pd.Series(dtype=int)) > 0).sum()),
        "failures": int((status_frame.get("processing_status", pd.Series(dtype=str)) == "failed").sum()),
        "warnings": int(status_frame.get("warning_count", pd.Series(dtype=int)).sum()),
        "filings_discovered": int(status_frame.get("filings_discovered", pd.Series(dtype=int)).sum()),
        "filings_matching_forms": int(status_frame.get("filings_matching_forms", pd.Series(dtype=int)).sum()),
        "filings_in_date_window": int(status_frame.get("filings_in_date_window", pd.Series(dtype=int)).sum()),
        "filings_selected": int(status_frame.get("filings_selected", pd.Series(dtype=int)).sum()),
        "raw_candidate_dates": int(len(raw_candidate_frame)) if not raw_candidate_frame.empty else int(status_frame.get("raw_candidate_count", pd.Series(dtype=int)).sum()),
        "deduplicated_candidates": int(len(review_queue_frame)) if not review_queue_frame.empty else int(status_frame.get("deduplicated_candidate_count", pd.Series(dtype=int)).sum()),
        "candidates_awaiting_review": int(status_frame.get("candidates_awaiting_review", pd.Series(dtype=int)).sum()),
        "provisional_diagnostic_windows": _event_window_count(provisional_panel_frame),
        "counts_by_sector": sector_counts.to_dict("records"),
        "counts_by_derivation_rule": {str(key): int(value) for key, value in counts_by_derivation_rule.items()},
        "counts_by_review_status": {str(key): int(value) for key, value in counts_by_review_status.items()},
        "counts_by_extraction_confidence": {str(key): int(value) for key, value in counts_by_extraction_confidence.items()},
        "counts_by_ambiguity_flag": {str(key): int(value) for key, value in counts_by_ambiguity_flag.items()},
        "configured_filing_windows": [{"start": start, "end": end} for start, end in filing_window_configured],
        "effective_filing_windows": [{"start": start, "end": end} for start, end in effective_filing_window],
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
        f"- Unresolved events: {summary['unresolved_events']}",
        f"- Future scheduled events: {summary['future_scheduled_events']}",
        f"- Raw candidate dates: {summary.get('raw_candidate_dates', 0)}",
        f"- Deduplicated candidates: {summary.get('deduplicated_candidates', 0)}",
        f"- Candidates awaiting review: {summary.get('candidates_awaiting_review', 0)}",
        f"- Companies with usable event windows: {summary['companies_with_usable_event_windows']}",
        f"- Event windows generated: {summary['event_windows_generated']}",
        f"- Provisional diagnostic windows: {summary.get('provisional_diagnostic_windows', 0)}",
        f"- Failures: {summary['failures']}",
        f"- Warnings: {summary['warnings']}",
        "",
        "## Filing Selection",
        "",
        f"- Filings discovered: {summary.get('filings_discovered', 0)}",
        f"- Filings matching form filters: {summary.get('filings_matching_forms', 0)}",
        f"- Filings inside filing-date window: {summary.get('filings_in_date_window', 0)}",
        f"- Filings selected after safety cap: {summary.get('filings_selected', 0)}",
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

    lines.extend(["", "## Counts By Extraction Confidence", ""])
    counts_by_extraction_confidence = summary.get("counts_by_extraction_confidence", {})
    if counts_by_extraction_confidence:
        lines.extend(f"- {key}: {value}" for key, value in counts_by_extraction_confidence.items())
    else:
        lines.append("- none")

    lines.extend(["", "## Counts By Ambiguity Flag", ""])
    counts_by_ambiguity_flag = summary.get("counts_by_ambiguity_flag", {})
    if counts_by_ambiguity_flag:
        lines.extend(f"- {key}: {value}" for key, value in counts_by_ambiguity_flag.items())
    else:
        lines.append("- none")

    lines.extend(["", "## Filing Date Windows", ""])
    configured_filing_windows = summary.get("configured_filing_windows", [])
    effective_filing_windows = summary.get("effective_filing_windows", [])
    if configured_filing_windows:
        lines.extend(
            f"- configured: {row['start'] or 'open'} to {row['end'] or 'open'}"
            for row in configured_filing_windows
        )
    else:
        lines.append("- configured: none")
    if effective_filing_windows:
        lines.extend(
            f"- effective: {row['start'] or 'open'} to {row['end'] or 'open'}"
            for row in effective_filing_windows
        )
    else:
        lines.append("- effective: none")

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
    raw_candidates: pd.DataFrame | None = None,
    review_queue: pd.DataFrame | None = None,
    provisional_panel: pd.DataFrame | None = None,
) -> Path:
    artifacts = build_phase2_summary(
        universe,
        statuses,
        audit,
        panel,
        raw_candidates=raw_candidates,
        review_queue=review_queue,
        provisional_panel=provisional_panel,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir = output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    report_path = report_dir / "phase2_research_summary.md"
    report_path.write_text(artifacts.markdown, encoding="utf-8")
    artifacts.headline_metrics.to_csv(output_dir / "phase2_summary_metrics.csv", index=False)
    artifacts.sector_counts.to_csv(output_dir / "phase2_sector_counts.csv", index=False)
    return report_path
