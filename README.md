# employee_flow_event_engine

`employee_flow_event_engine` is a modular Python Research v0.1 project for analyzing whether Employee Stock Purchase Plan (ESPP) purchase dates are associated with statistically significant price behavior.

## What it does

- Loads historical OHLCV data from either local CSV fixtures or the legacy `yfinance` provider.
- Loads local filing fixtures (YAML) for reproducible ESPP text inputs.
- Parses filing text (10-K / DEF 14A style documents) for ESPP clues.
- Generates approximate ESPP event dates with audit metadata.
- Runs event studies over configurable windows (default `t-10` to `t+10`).
- Filters for tradable candidates (volume spike threshold + minimum ESPP confidence).
- Simulates an event strategy (default: enter `t+1` close, exit `t+5` close) and compares to a baseline.
- Produces abnormal-return summaries, cross-sectional slices, strategy metrics, CSV outputs, and simple plots.

## Project layout

```text
src/
  data/
    price_loader.py
    sec_parser.py
  events/
    espp_event_extractor.py
  analysis/
    event_study.py
    metrics.py
  pipeline/
    run_event_study.py
config/
  example.yaml
fixtures/
  sec_filings/
tests/
README.md
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m src.pipeline.run_event_study --config config/example.yaml
```

The example run is fully local/reproducible today:

- filing text comes from local YAML fixtures
- ESPP date review decisions come from a local CSV review file
- price and benchmark data come from a local CSV fixture

That means the current example config is suitable for fully offline Research v0.1 replay. The legacy live path still exists if you explicitly switch `price_source` back to `yfinance`.

Research v0.1 includes two offline replay configs:

- [`config/example.yaml`](C:/GitHub/employee_flow_event_engine/config/example.yaml) is the minimal offline replay and intentionally keeps a tiny synthetic price fixture, including weekend/holiday rows, so the end-to-end path stays small and deterministic.
- [`config/offline_business_day_example.yaml`](C:/GitHub/employee_flow_event_engine/config/offline_business_day_example.yaml) is the slightly more market-calendar-realistic offline replay and uses business-day-only price rows plus manual review corrections that move non-business assigned dates onto business-day `effective_event_date` values. It also uses explicit manual review rejections to exclude irrelevant fallback anchors so the smoke-run audit stays focused on the tiny fixture window.

Both configs remain research fixtures for offline replay and decision support. They are not production ESPP date validation.

Example config includes:

- `price_source: csv`
- `price_data_path` pointing at a local research price fixture under [`fixtures/prices`](C:/GitHub_Review_Folder/employee_flow_event_engine/fixtures/prices)
- ticker metadata (market cap + employees) for cross-sectional grouping
- a local `filings.fixture_dir` pointing at repo fixtures under [`fixtures/sec_filings`](C:/GitHub_Review_Folder/employee_flow_event_engine/fixtures/sec_filings)
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

## Filing fixture format

The pipeline does not fetch live SEC / EDGAR filings yet. Instead it reads local YAML fixtures so date-identification runs are reproducible and auditable at the filing-text layer.

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
If no local fixture is found for a ticker, the pipeline falls back to `_mock_filings(...)`. Those rows are intentionally labeled as mock-derived in `source_id`, `derivation_rule`, and event metadata so they do not masquerade as fixture or SEC evidence. This fallback is for research continuity only and is not a production filing source.

## Review File Format

The pipeline can also apply an optional manual review layer from a local CSV file such as [`config/espp_date_reviews.csv`](C:/GitHub_Review_Folder/employee_flow_event_engine/config/espp_date_reviews.csv).

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

## Outputs

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

## Determinism and reproducibility notes

- CSV outputs are generated with stable ordering and fixed float formatting where applicable.
- Pipeline behavior is controlled by explicit config values.
- Price inputs can come from a deterministic local CSV when `price_source: csv` is configured.
- Filing inputs come from local YAML fixtures when configured.
- Event date construction follows deterministic precedence rules and writes an audit CSV for review.
- Manual review decisions are applied deterministically from a local CSV when configured.
- Review matching prefers deterministic `event_review_id` keys and falls back to `ticker + original_assigned_event_date` for older review rows.

## Current date-identification limitations

- This repository should be treated as Research v0.1, not a production-grade ESPP date mastering workflow.
- The extractor is still heuristic-heavy and looks for keywords plus month/day patterns in free text.
- Year assignment uses a simple next-occurrence rollover rule from the filing date; it does not reconstruct plan calendars from full filing context.
- If a year has no explicit month/day candidates, the pipeline falls back to default semiannual anchors (`06-30`, `12-31`).
- The audit artifact improves traceability, but it does not validate whether an inferred date is the true ESPP purchase date.
- Manual review can override or reject heuristic dates, but the process is still local research curation rather than production-grade event mastering.
- Local fixtures are research inputs, not canonical SEC records, and no live EDGAR retrieval or accession-level provenance is included yet.
- The offline CSV price fixture is only a small research replay sample; it is not a complete market-history source.
- The legacy `yfinance` path remains available for exploratory use, but it is not part of the fully offline replay path.

## TODOs (ESPP date accuracy)

1. Replace keyword/date heuristics with parser logic that captures plan-specific date fields from full filing sections.
2. Add SEC EDGAR retrieval adapter with filing metadata tracking (`accession`, `filing_url`, `accepted_datetime`).
3. Cross-reference extracted candidate dates with company fiscal calendars to reduce false positives.
4. Introduce confidence calibration and event-quality filters before running event studies.
5. Expand the local human-review override workflow beyond the current CSV-based review file when research needs more nuanced curation.

## Extensibility points

- Swap market data source by implementing `PriceDataProvider` in `src/data/price_loader.py`.
- Extend text parsers in `src/data/sec_parser.py`.
- Add additional metrics in `src/analysis/metrics.py` and consume them in `event_study.py`.
