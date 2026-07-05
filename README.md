# employee_flow_event_engine

`employee_flow_event_engine` is a modular Python research project for analyzing whether Employee Stock Purchase Plan (ESPP) purchase dates are associated with statistically significant price behavior.

The repository now has two explicit tracks:

- Phase 1: a tested offline fixture workflow for deterministic ESPP event extraction, review, audit, and event-study replay.
- Phase 2: an initial batch-processing scaffold for scalable, auditable research-dataset construction over a dated current S&P 500 universe snapshot.

## What it does

- Loads historical OHLCV data from either local CSV fixtures or the legacy `yfinance` provider.
- Loads local filing fixtures (YAML) for reproducible ESPP text inputs.
- Can acquire bounded live SEC / EDGAR submissions and filing documents keyed by issuer CIK.
- Parses filing text (10-K / DEF 14A style documents) for ESPP clues.
- Generates approximate ESPP event dates with audit metadata.
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
    run_batch.py
    run_event_study.py
  universe/
    sp500_universe.py
config/
  example.yaml
  phase2_example.yaml
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

Before running that command, provide a valid SEC user agent either by setting
`filings.sec_user_agent` in a local config override or by exporting
`SEC_EDGAR_USER_AGENT`.

The Phase 2B pilot also stays intentionally bounded:

- it keeps the same five-company subset used by the offline Phase 2A sample
- it uses live SEC submissions and filing documents keyed by CIK
- it uses a configurable SEC-compliant user agent and sequential throttled requests
- it writes durable raw metadata and filing-document cache files under the configured `cache_dir`
- it writes filing inventory, filing-level ESPP screening, and SEC acquisition metrics artifacts
- it supports cache-only reruns through [`config/phase2_live_sec_pilot_cache_only.yaml`](config/phase2_live_sec_pilot_cache_only.yaml)

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
- `filings.max_filings_per_issuer`
- `filings.cache_only`
- `filings.request_delay_seconds`
- `filings.max_retries`
- `filings.timeout_seconds`

The committed live pilot configs intentionally omit a concrete
`filings.sec_user_agent` value so personal contact details are not stored in
the repository.

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

Review statuses:

- `accepted`: keep the original assigned event date
- `corrected`: replace the event date used downstream with `reviewed_event_date`
- `rejected`: exclude the event from downstream event-study windows

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

## TODOs (ESPP date accuracy)

1. Replace keyword/date heuristics with parser logic that captures plan-specific date fields from full filing sections.
2. Expand the SEC EDGAR adapter with richer filing metadata (`accepted_datetime`, exhibit inventory, submission text fallback).
3. Cross-reference extracted candidate dates with company fiscal calendars to reduce false positives.
4. Introduce confidence calibration and event-quality filters before running event studies.
5. Expand the local human-review override workflow beyond the current CSV-based review file when research needs more nuanced curation.

## Extensibility points

- Swap market data source by implementing `PriceDataProvider` in `src/data/price_loader.py`.
- Extend text parsers in `src/data/sec_parser.py`.
- Add additional metrics in `src/analysis/metrics.py` and consume them in `event_study.py`.
