# Employee Flow Event Engine — Recording Script

## Recording preparation

- Install the repository’s declared runtime dependencies with `python -m pip install -e .`; the notebook was validated with the existing Jupyter runtime and no dependency file was changed.
- From the repository root, open `notebooks/employee_flow_event_engine_demo.ipynb`.
- Run all cells once before recording so the compact tables and chart are already visible.
- Collapse the setup and pipeline-run code cells after execution if the notebook interface supports it; leave their one-line confirmations visible.
- Record from the title cell through the closing frame. The `TST` / TestCo data is a deterministic illustrative fixture, not a real issuer or performance example.

## 0:00–0:12 — Opening hook

**On screen:** Title and value proposition.

“Employee-related corporate events can be useful research evidence, but filing text is rarely ready to trade. This engine turns Employee Stock Purchase Plan references into structured, review-gated research records—not automatic trade instructions.”

## 0:12–0:30 — Problem and workflow

**On screen:** The research-problem section.

“An ESPP reference can describe a recurring schedule, an administrative change, or an actual completed purchase. Treating every date as equivalent would create false confidence. The workflow screens filings, extracts bounded evidence, classifies and deduplicates candidates, applies review decisions, and only then builds validated event-study windows.”

## 0:30–0:47 — Representative input

**On screen:** Input table.

“This short TestCo fixture is deliberately small and deterministic. Each filing record retains its filing type, filing date, source identifier, and the exact nearby evidence. The same document contract supports local fixtures today and SEC acquisition or cache replay in the broader pipeline.”

## 0:47–1:05 — Real pipeline

**On screen:** Pipeline confirmation.

“This cell invokes the repository’s real Phase 3 batch workflow. It preserves the tracked fixture inputs and redirects only generated artifacts into a demo-specific directory. There are no credentials, paid services, network calls, or notebook reimplementation of the pipeline logic.”

## 1:05–1:32 — Evidence packet

**On screen:** Structured evidence table.

“Here is the core output. Every candidate has a stable event key, canonical filing provenance, source type, extraction confidence, and an attachment score measuring how closely the date is tied to purchase language. Crucially, the review decision remains separate: evidence quality does not silently become research eligibility.”

## 1:32–1:58 — Validation gate

**On screen:** Review-status chart and two-row validated-event table.

“The fixture demonstrates four outcomes: accepted, corrected, rejected, and unreviewed. Only accepted and corrected records pass into validated event windows. The corrected row also shows why the review layer matters: it can adjust an effective date without losing the original evidence trail. These displayed returns are fixture observations for workflow validation, not performance claims.”

## 1:58–2:18 — Ecosystem role

**On screen:** Integration table.

“The outputs are clean contracts for a downstream research-opportunity or finance-decision system: candidate provenance for triage, reviewed event dates for joins, and event windows for research reporting. This repository contributes one evidence family. It has no broker, portfolio construction, position-sizing, or live-trading capability.”

## 2:18–2:35 — Close

**On screen:** Closing takeaways.

“Three takeaways: evidence stays traceable, review gates validated research, and the resulting artifacts are reusable in a broader research stack. Employee Flow Event Engine turns ambiguous filing text into disciplined, reproducible research evidence.”
