# employee_flow_event_engine

`employee_flow_event_engine` is a modular Python research project for analyzing whether Employee Stock Purchase Plan (ESPP) purchase dates are associated with statistically significant price behavior.

The repository now has two explicit tracks:

- Phase 1: a tested offline fixture workflow for deterministic ESPP event extraction, review, audit, and event-study replay.
- Phase 2 / 3: a scalable batch-processing scaffold for auditable research-dataset construction over a dated current S&P 500 universe snapshot, including bounded live SEC acquisition and a review-gated candidate queue.

## What it does

- Loads historical OHLCV data from either local CSV fixtures or the legacy `yfinance` provider.
- Loads local filing fixtures (YAML) for reproducible ESPP text inputs.
- Can acquire bounded live SEC / EDGAR submissions and filing documents keyed by issuer CIK.
- Parses filing text (10-K / DEF 14A style documents) for ESPP clues.
- Screens filings for ESPP mentions, extracts bounded candidate-date evidence, and generates a manual review queue.
- Generates approximate ESPP event dates with audit metadata once candidates are reviewed or explicitly run in diagnostic mode.
- Runs event studies over configurable windows (default `t-10` to `t+10`).
- Filters for tradable candidates (volume spike threshold + minimum ESPP confidence).
- Simulates an event strategy (default: enter `t+1` close, exit `t+5` close) and compares to a baseline.
- Produces abnormal-return summaries, cross-sectional slices, strategy metrics, CSV outputs, and simple plots.

## Project layout

```text
src/
  analysis/
    event_study.py
    metrics.py
    phase2_summary.py
    phase3_review_packet.py
    research_summary.py
    strategy.py
  data/
    price_loader.py
    sec_parser.py
  sec/
    edgar.py
  events/
    espp_event_extractor.py
  pipeline/
    batch_config.py
    company_status.py
    phase3_candidates.py
    run_batch.py
    run_event_study.py
  universe/
    sp500_universe.py
config/
  example.yaml
  phase2_example.yaml
  phase3_live_sec_pilot_cache_only.yaml
  phase3_live_sec_pilot_cache_only_reviewed.yaml
  phase3_live_sec_pilot_cache_only_diagnostic.yaml
  phase3_reviewed_fixture.yaml
  sp500_universe_2026-07-04.csv
fixtures/
  prices/
  sec_filings/
tests/
README.md
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Phase 1 offline replay

```bash
python -m src.pipeline.run_event_study --config config/example.yaml
```

The example run is fully local/reproducible today:

- filing text comes from local YAML fixtures
- ESPP date review decisions come from a local CSV review file
- price and benchmark data come from a local CSV fixture

That means the current example config is suitable for fully offline Research v0.1 replay. The legacy live path still exists if you explicitly switch `price_source` back to `yfinance`.

### Phase 2 bounded batch example

```bash
python -m src.pipeline.run_batch --config config/phase2_example.yaml --force
```

That example intentionally stays bounded and deterministic:

- it uses the dated current-universe snapshot in [`config/sp500_universe_2026-07-04.csv`](config/sp500_universe_2026-07-04.csv)
- it filters to a 5-company development subset
- it uses local filing fixtures and a local CSV price fixture
- it writes universe validation, per-company status, consolidated audit, and Phase 2 summary artifacts
- it supports resumable execution through `resume_mode` and `--force`

### Phase 2B live SEC / EDGAR pilot

```bash
python -m src.pipeline.run_batch --config config/phase2_live_sec_pilot.yaml --force
```

Before running that live-acquisition command, provide a valid SEC user agent either by setting
`filings.sec_user_agent` in a local config override or by exporting
`SEC_EDGAR_USER_AGENT`.

The Phase 2B pilot also stays intentionally bounded:

- it keeps the same five-company subset used by the offline Phase 2A sample
- it uses live SEC submissions and filing documents keyed by CIK
- it uses a configurable SEC-compliant user agent and sequential throttled requests
- it writes durable raw metadata and filing-document cache files under the configured `cache_dir`
- it writes filing inventory, filing-level ESPP screening, and SEC acquisition metrics artifacts
- it supports cache-only reruns through [`config/phase2_live_sec_pilot_cache_only.yaml`](config/phase2_live_sec_pilot_cache_only.yaml)

### Phase 3A cache-only review-queue pilot

```bash
python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only.yaml --force
```

The Phase 3A cache-only pilot keeps the same bounded five-company scope and adds:

- explicit filing-date selection before the filing-count safety cap
- separate stages for filing discovery, ESPP screening, candidate extraction, review, and event-window generation
- bounded context extraction around ESPP-relevant text rather than whole-filing month/day scans in the primary path
- raw candidate preservation plus a deduplicated manual review queue
- default exclusion of unreviewed live candidates from validated research windows
- a reviewer-facing CSV packet, Markdown packet, editable decisions template, and workflow instructions
- dual-review templates (`review_decisions_reviewer_a.csv` and `review_decisions_reviewer_b.csv`), a derived `review_consensus_decisions.csv`, and a consensus summary that isolates only genuine reviewer disagreements or incomplete work for manual resolution
- an optional diagnostic-only provisional-window rerun through [`config/phase3_live_sec_pilot_cache_only_diagnostic.yaml`](config/phase3_live_sec_pilot_cache_only_diagnostic.yaml)

### Phase 3A.2 reviewed manual-review pilot

1. Generate the five-company cache-only packet:

```bash
python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only.yaml --force
```

2. Open [`artifacts/phase3_live_sec_pilot_cache_only/reports/candidate_review_packet.md`](artifacts/phase3_live_sec_pilot_cache_only/reports/candidate_review_packet.md) and inspect each retained candidate.
3. Prefer the dual-review path:
   fill [`artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_a.csv`](artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_a.csv) and [`artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_b.csv`](artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_b.csv) without changing `event_review_id`.
4. Refresh the consensus artifacts:

```bash
python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only.yaml
```

5. Inspect [`artifacts/phase3_live_sec_pilot_cache_only/reports/review_consensus_summary.md`](artifacts/phase3_live_sec_pilot_cache_only/reports/review_consensus_summary.md) and use [`artifacts/phase3_live_sec_pilot_cache_only/review_consensus_decisions.csv`](artifacts/phase3_live_sec_pilot_cache_only/review_consensus_decisions.csv) as the reviewed input.
   The current formal adjudication policy for live SEC-derived Phase 3 candidates is documented in [`PHASE3_EVENT_POLICY.md`](PHASE3_EVENT_POLICY.md).
6. Rerun the consensus-reviewed cache-only pilot:

```bash
python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only_consensus_reviewed.yaml --force
```

7. Legacy single-review fallback:
   record reviewer decisions in [`artifacts/phase3_live_sec_pilot_cache_only/review_decisions.csv`](artifacts/phase3_live_sec_pilot_cache_only/review_decisions.csv) without changing `event_review_id`, then rerun the original reviewed config:

```bash
python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only_reviewed.yaml --force
```

That reviewed path:

- loads decisions by stable `event_review_id`
- keeps missing decisions as `unreviewed`
- generates validated event windows only for `accepted` and `corrected`
- uses `corrected_event_date` for corrected candidates
- excludes `rejected`, `unresolved`, `future_scheduled`, and `unreviewed` from validated windows
- keeps all decisions visible in `espp_date_audit.csv`
- persists the applied reviewed input in `applied_review_decisions.csv` so reviewed output folders remain self-contained
- omits reviewer-facing packet and consensus workflow artifacts inside reviewed output folders, because those remain authoritative only in the upstream review-queue output directory
- does not enable provisional diagnostic windows

For a fully deterministic offline replay of the reviewed workflow, run:

```bash
python -m src.pipeline.run_batch --config config/phase3_reviewed_fixture.yaml --force
```

### Phase 3B discovery sample-building run

```bash
python -m src.pipeline.run_batch --config config/phase3_sec_discovery_sector33_20260817.yaml --force
```

That discovery config is intentionally different from the reviewed five-company pilot:

- it uses a dated current-membership S&P 500 parent universe but an explicitly bounded, sector-balanced 33-issuer discovery sample documented in [`config/phase3_sec_discovery_sector33_20260817.source.md`](config/phase3_sec_discovery_sector33_20260817.source.md)
- it keeps the conservative Phase 3 event policy and enables policy-driven auto review only for clear evidence classes
- it captures richer nearby sentence context and evidence-cue metadata for adjudication and aggregate reporting
- it disables event-study window generation (`event_study.enabled: false`) so the run can answer the validated-event viability gate before requiring broader ticker price coverage
- it should be labeled as a current-membership discovery sample, not as a historical point-in-time S&P 500 study

Terminal closeout result on 2026-08-17:

- 33 issuers and 197 selected filings produced 791 raw candidates and 11 retained review candidates
- the final reviewed discovery result produced 0 accepted historical events, 7 rejected, 3 unresolved, and 1 `future_scheduled`
- therefore this conservative SEC-only executed-event methodology did not yield a sufficiently large validated historical sample to justify broader price/event-study coverage

That is a methodology conclusion, not a claim that employee-flow effects do not exist or that ESPP-related market effects cannot matter.

Tracked closeout reproduction inputs:

```bash
python -m src.pipeline.run_batch --config config/phase3_sec_discovery_sector33_20260817.yaml --force
python -m src.pipeline.run_batch --config config/phase3_sec_discovery_sector33_20260817_bkr_recovery.yaml --force
python -m src.pipeline.run_batch --config config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml --force
```

The second command is only needed if the initial live discovery run leaves the March 31, 2025 `BKR` proxy filing unretrieved. The final cache-only reviewed config consumes the tracked review decisions in [`config/phase3_sec_discovery_sector33_20260817_review_decisions.csv`](config/phase3_sec_discovery_sector33_20260817_review_decisions.csv).

That final cache-only rerun reproduces the terminal reviewed result from the local SEC cache created by the live discovery workflow; the cache and generated artifact directories remain workspace-local under `artifacts/`.

Research v0.1 includes two offline replay configs:

- [`config/example.yaml`](config/example.yaml) is the minimal offline replay and intentionally keeps a tiny synthetic price fixture, including weekend/holiday rows, so the end-to-end path stays small and deterministic.
- [`config/offline_business_day_example.yaml`](config/offline_business_day_example.yaml) is the slightly more market-calendar-realistic offline replay and uses business-day-only price rows plus manual review corrections that move non-business assigned dates onto business-day `effective_event_date` values. It also uses explicit manual review rejections to exclude irrelevant fallback anchors so the smoke-run audit stays focused on the tiny fixture window.

Both configs remain research fixtures for offline replay and decision support. They are not production ESPP date validation.

Example config includes:

- `price_source: csv`
- `price_data_path` pointing at a local research price fixture under [`fixtures/prices`](fixtures/prices)
- ticker metadata (market cap + employees) for cross-sectional grouping
- a local `filings.fixture_dir` pointing at repo fixtures under [`fixtures/sec_filings`](fixtures/sec_filings)
- an optional `reviews.review_file` pointing at a local ESPP date review CSV

## Price fixture format

For offline replay, the pipeline can read a local CSV with one row per `ticker` and `date`.

Required columns:

- `ticker`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`

Example:

```csv
ticker,date,open,high,low,close,volume
AAPL,2024-06-30,102,103,101,102,800000
SPY,2024-06-30,302,303,301,302,1500000
```

If `price_source: csv` is selected, the offline path does not import or call `yfinance`.

## Filing input modes

Phase 2 batch runs support two bounded filing-input modes:

- `filings.source: fixture` for deterministic local YAML replay
- `filings.source: sec` for bounded live SEC / EDGAR acquisition with durable caching

### Filing fixture format

The fixture mode reads local YAML inputs so date-identification runs are reproducible and auditable at the filing-text layer.

Each fixture contains:

```yaml
ticker: AAPL
filing_type: 10-K
filing_date: "2024-02-15"
source_id: aapl_2024_10k_fixture
text: |
  The employee stock purchase plan (ESPP) has six-month offering periods.
  The purchase date for each period occurs on June 30 and December 31.
```

If `filings.fixture_dir` is configured and a ticker fixture is present, the pipeline uses that local text.
If no local fixture is found for a ticker, the Phase 1 pipeline falls back to `_mock_filings(...)`. Those rows are intentionally labeled as mock-derived in `source_id`, `derivation_rule`, and event metadata so they do not masquerade as fixture or SEC evidence. This fallback is for research continuity only and is not a production filing source.

### Live SEC pilot configuration

The live pilot configuration adds:

- `filings.sec_user_agent`
- `filings.forms`
- `filings.filing_start_date`
- `filings.filing_end_date`
- `filings.max_filings_per_issuer`
- `filings.cache_only`
- `filings.request_delay_seconds`
- `filings.max_retries`
- `filings.timeout_seconds`
- `event_study.enabled` to disable window generation during sample-building runs
- `phase3.auto_policy_review` to auto-resolve clear evidence classes without relaxing the event policy
- `phase3.review_as_of_date` to make `future_scheduled` versus historical policy decisions reproducible

The committed live pilot configs intentionally omit a concrete
`filings.sec_user_agent` value so personal contact details are not stored in
the repository.
Cache-only reruns can replay from an existing local SEC cache without setting a
user agent, but any live SEC network acquisition still requires one.

Filing selection is deterministic and staged:

1. discover all deduplicated filing metadata for the issuer
2. apply allowed form filters
3. apply the configured filing-date window
4. apply the maximum-filings-per-issuer safety cap

The resulting artifacts keep those stage counts separate so the review queue is auditable.

The SEC cache layout is:

- `<cache_dir>/submissions/CIK##########.json`
- `<cache_dir>/submissions/CIK##########-submissions-###.json` when historical submissions files are needed
- `<cache_dir>/filings/<cik>/<accession_without_dashes>/index.json`
- `<cache_dir>/filings/<cik>/<accession_without_dashes>/metadata.json`
- `<cache_dir>/filings/<cik>/<accession_without_dashes>/<primary_document>`

## Review File Format

The pipeline can also apply an optional manual review layer from a local CSV file such as [`config/espp_date_reviews.csv`](config/espp_date_reviews.csv).

Required columns:

- `event_review_id`
- `ticker`
- `original_assigned_event_date`
- `reviewed_event_date`
- `review_status`
- `review_note`

`event_review_id` is a deterministic composite key written into `espp_date_audit.csv`. It is intended to be stable for the same source inputs across repeated runs and is the preferred review-matching key. The pipeline still supports `ticker + original_assigned_event_date` as a fallback for older review rows.

Legacy review statuses:

- `accepted`: keep the original assigned event date
- `corrected`: replace the event date used downstream with `reviewed_event_date`
- `rejected`: exclude the event from downstream event-study windows
- `unreviewed`: keep the candidate in the audit trail but exclude it from validated event-study windows

Phase 3 review queues also include reviewer-facing editable columns:

- `review_status`
- `corrected_event_date`
- `reviewer_note`
- `reviewed_at`
- `reviewer_id`

Phase 3 review statuses:

- `accepted`: the text supports an observed historical ESPP purchase event on the candidate date
- `corrected`: the text supports an observed historical ESPP purchase event on a different explicit date
- `rejected`: the text is an administrative, plan-history, or otherwise non-purchase-event reference
- `unresolved`: the text points to a purchase schedule or boundary but does not affirm that the purchase actually occurred on the candidate date
- `future_scheduled`: the text establishes a future schedule as of review time, but the event is still ineligible for historical event-study use
- `unreviewed`: review work is still incomplete

If a Phase 3 review queue is supplied back to the pipeline with blank review fields, those rows remain `unreviewed` and therefore ineligible for validated research outputs.
`accepted`, `rejected`, `unresolved`, `future_scheduled`, and `unreviewed` rows must leave `corrected_event_date` blank. `corrected` rows must supply a valid `YYYY-MM-DD` replacement date.

Example:

```csv
event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note
AAPL|10-K|2024-02-15|aapl_2024_10k_fixture|06-30|2024-06-30|filing_text_month_day,AAPL,2024-06-30,,accepted,Reviewed against fixture text
CRM|10-K|2024-03-01|crm_2024_10k_fixture|01-01|2025-01-01|filing_text_month_day,CRM,2025-01-01,2025-01-02,corrected,Shifted to reviewed purchase date
NVDA|na|na|default_anchor_nvda_2025_1231|12-31|2025-12-31|fallback_default_anchors,NVDA,2025-12-31,,rejected,Heuristic date not supported by manual review
```

## Phase 2 outputs

Under the configured Phase 2 output directory:

- `selected_universe.csv`
- `company_processing_status.csv`
- `filing_inventory.csv`
- `filing_screening_results.csv`
- `sec_acquisition_metrics.csv`
- `espp_date_audit.csv`
- `all_event_windows.csv` when usable windows exist
- `phase2_summary_metrics.csv`
- `phase2_sector_counts.csv`
- `reports/universe_validation_report.md`
- `reports/phase2_research_summary.md`

Phase 3A runs add:

- `raw_candidate_extractions.csv`
- `candidate_review_queue.csv`
- `provisional_diagnostic_candidate_audit.csv` when diagnostic provisional mode is enabled
- `provisional_diagnostic_event_windows.csv` when diagnostic provisional mode is enabled

`company_processing_status.csv` includes per-company batch state such as:

- `ticker`
- `company_name`
- `cik`
- `sector`
- `processing_status`
- `filings_discovered`
- `filings_processed`
- `espp_mentions_found`
- `candidate_events_found`
- `accepted_events`
- `corrected_events`
- `rejected_events`
- `usable_event_windows`
- `warning_count`
- `error_message`
- `processing_timestamp`

Phase 3A status rows also carry:

- filing discovery and selection-stage counts
- configured and effective filing-date windows
- raw-candidate counts
- deduplicated review-queue counts
- candidates awaiting review
- provisional diagnostic-window counts

Secondary share classes in legitimate duplicate-CIK groups are marked as `skipped` so filing research is not duplicated across multiple listed share classes.

## Phase 1 outputs

Under `artifacts/` (or configured output dir):

- `<ticker>_prices.csv`
- `espp_date_audit.csv`
- `all_event_windows.csv`
- `benchmark_prices.csv`
- `diagnostic_returns_distribution.csv`
- `diagnostic_summary_overall.csv`
- `diagnostic_summary_by_ticker.csv`
- `filtered_event_windows.csv`
- `ticker_cross_section.csv`
- `strategy_event_level.csv`
- `strategy_group_summary.csv`
- `strategy_overall_summary.csv`
- `reports/espp_research_summary.md`

`espp_date_audit.csv` captures the date-identification layer used by the study and includes:

- `ticker`
- `filing_type`
- `filing_date`
- `source_fixture_path`
- `source_id`
- `source_snippet`
- `candidate_month_day`
- `assigned_event_date`
- `derivation_rule`
- `confidence`
- `fallback_anchor_used`
- `event_review_id`
- `review_status`
- `reviewed_event_date`
- `review_note`
- `effective_event_date`
- `included_in_event_study`

## Offline descriptive research summary

The offline pipeline now also writes `reports/espp_research_summary.md` under the configured output directory.

That report is intentionally narrow:

- it is an offline Research v0.1 fixture smoke summary
- it is descriptive only and meant for research triage
- it summarizes review-status counts, derivation-rule counts, included event coverage, event-window generation coverage, and simple return snapshots already present in the offline outputs
- it explicitly labels tiny fixture samples as insufficient for inference

The summary does not make production ESPP accuracy claims, alpha claims, or trading claims. It is only there to help decide whether the reviewed offline ESPP dataset has enough usable evidence to justify a deeper next research pass.

## Phase 2 universe handling

Phase 2 introduces a versioned S&P 500 universe loader and validator.

The universe file includes:

- `ticker`
- `company_name`
- `issuer_name`
- `issuer_id`
- `cik`
- `gics_sector`
- `gics_sub_industry`
- `primary_ticker`
- `is_primary_share_class`

Validation checks:

- required columns
- ticker normalization
- CIK normalization
- duplicate ticker detection
- duplicate CIK detection
- legitimate multi-share-class group handling
- primary-share-class consistency

The loader writes a Markdown validation report so duplicate-company cases remain explicit and auditable.

Source notes for the current dated snapshot live in [`config/sp500_universe_2026-07-04.source.md`](config/sp500_universe_2026-07-04.source.md).

## Determinism and reproducibility notes

- CSV outputs are generated with stable ordering and fixed float formatting where applicable.
- Pipeline behavior is controlled by explicit config values.
- Price inputs can come from a deterministic local CSV when `price_source: csv` is configured.
- Filing inputs come from local YAML fixtures when configured.
- Live SEC filing inputs can be replayed from the raw cache when `filings.cache_only: true` is configured.
- Event date construction follows deterministic precedence rules and writes an audit CSV for review.
- Manual review decisions are applied deterministically from a local CSV when configured.
- Review matching prefers deterministic `event_review_id` keys and falls back to `ticker + original_assigned_event_date` for older review rows.
- Phase 2 batch selection, status outputs, and summary outputs are also config-driven and deterministic in offline mode.

## Phase 2 limitations

- The current Phase 2 universe uses current S&P 500 membership rather than historical point-in-time membership.
- That introduces survivorship bias and index-selection bias into downstream research outputs.
- The current Phase 2 batch scaffold is for research infrastructure and dataset construction, not predictive modeling or a trading signal.
- The live SEC path is a bounded five-company pilot only. It is not a full S&P 500 run.
- SEC requests are intentionally sequential and throttled; the repo does not issue parallel EDGAR requests.
- Filing-level ESPP screening is heuristic and auditable, but it does not automatically accept an inferred event as ground truth.
- Phase 3A candidate extraction is deterministic and bounded, but it still requires human review before live candidates become validated research events.
- Recurring plan language, approval language, amendment language, and schedule-like text are preserved and flagged rather than auto-accepted as purchase events.

## Phase 3A review flow

Phase 3A makes the stage boundaries explicit:

1. filing discovery and acquisition
2. ESPP mention screening
3. bounded candidate-date extraction
4. manual review decisions
5. validated event-window generation

The primary Phase 3 path only extracts from filings that pass ESPP screening. A diagnostic override can also extract from non-screened filings, but those results remain diagnostic-only and are written separately from validated research outputs.

Candidate-quality metadata includes:

- source accession and filing metadata
- source phrase and bounded snippet
- matched ESPP term(s)
- extraction rule and deterministic confidence
- ambiguity flags
- explicit-year versus inferred-year indicators
- recurring-language indicators
- likely purchase-date versus likely non-purchase-language flags
- duplicate-group identifiers and review eligibility

Deduplication preserves every raw row while also producing one canonical review-queue row per candidate group, including contributing accessions, contributing filing dates, duplicate counts, and a deterministic deduplication reason.

Validated versus provisional outputs are intentionally separated:

- `espp_date_audit.csv` and `all_event_windows.csv` are the validated research path
- `provisional_diagnostic_candidate_audit.csv` and `provisional_diagnostic_event_windows.csv` are diagnostic-only when enabled
- unreviewed candidates do not enter the validated event-study dataset
- provisional diagnostic windows are not merged into the validated research summary

## Current date-identification limitations

- This repository should be treated as Research v0.1, not a production-grade ESPP date mastering workflow.
- The extractor is still heuristic-heavy and looks for keywords plus month/day patterns in free text.
- Year assignment uses a simple next-occurrence rollover rule from the filing date; it does not reconstruct plan calendars from full filing context.
- If a year has no explicit month/day candidates, the pipeline falls back to default semiannual anchors (`06-30`, `12-31`).
- The audit artifact improves traceability, but it does not validate whether an inferred date is the true ESPP purchase date.
- Manual review can override or reject heuristic dates, but the process is still local research curation rather than production-grade event mastering.
- Local fixtures are research inputs, not canonical SEC records.
- The offline CSV price fixture is only a small research replay sample; it is not a complete market-history source.
- The legacy `yfinance` path remains available for exploratory use, but it is not part of the fully offline replay path.

## Optional Future Research

These are not blockers to the current SEC-only closeout:

1. Replace keyword/date heuristics with parser logic that captures plan-specific date fields from full filing sections.
2. Expand the SEC EDGAR adapter with richer filing metadata (`accepted_datetime`, exhibit inventory, submission text fallback).
3. Cross-reference extracted candidate dates with company fiscal calendars to reduce false positives.
4. Introduce confidence calibration and event-quality filters before running event studies.
5. Expand the local human-review override workflow beyond the current CSV-based review file when research needs more nuanced curation.
6. Target forms, issuers, or alternative data sources more likely to contain explicit executed-event wording.
7. Revisit broader universe design, including point-in-time index membership, only as a future methodology extension.

## Extensibility points

- Swap market data source by implementing `PriceDataProvider` in `src/data/price_loader.py`.
- Extend text parsers in `src/data/sec_parser.py`.
- Add additional metrics in `src/analysis/metrics.py` and consume them in `event_study.py`.
