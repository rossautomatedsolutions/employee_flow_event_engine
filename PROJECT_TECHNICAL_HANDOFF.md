# Project Technical Handoff

Validated on Sunday, August 23, 2026 against repository code, tracked configs, sampled local artifacts, and the current automated test suite (`108` tests passed).

This document is intended to let a future ChatGPT/Codex session understand what this repository actually implements, what is proven, what should be reused, and how future alpha-research modules should interface with it without duplicating work.

## 1. Executive Summary

### What the project does

`employee_flow_event_engine` is a Python research repository for identifying Employee Stock Purchase Plan (ESPP) event candidates from SEC filings and studying their associated price behavior.

The repository has two real operating modes:

- Legacy offline replay (`src/pipeline/run_event_study.py`): deterministic fixture-based ESPP date extraction, audit generation, event-study output, and a simple hypothesis-testing strategy summary.
- Batch / discovery workflow (`src/pipeline/run_batch.py`): current-membership S&P 500 universe selection, bounded filing ingestion, SEC cache management, filing screening, Phase 3 candidate extraction, manual-review workflow, reviewed reruns, and closeout reproducibility.

### Current maturity / status

The project is mature as a closed research stack for one specific question:

- Can a conservative SEC-only methodology recover enough historically validated ESPP purchase events to justify a broader event study?

As of August 17, 2026, and validated again from code and artifacts on Tuesday, August 18, 2026:

- The answer for the bounded 33-issuer discovery sample is no.
- The SEC-only executed-event methodology is considered empirically closed out, not unfinished.

### What is actually working today

- Offline deterministic replay from local filing fixtures and local CSV prices.
- Current-membership S&P 500 universe loading and validation, including duplicate-CIK/share-class handling.
- Bounded SEC filing acquisition with caching, throttling, retries, cache-only replay, and filing-inventory artifacts.
- Filing-level ESPP screening.
- Phase 3 bounded candidate extraction from filing context.
- Candidate deduplication, classification, tiering, exclusion, and manual-review queue generation.
- Single-review and dual-review consensus workflows.
- Review-gated validated event generation.
- Optional event-study execution over validated events.
- Portable cache-bundle restore and exact reproduction of the final 33-issuer closeout.

### What is experimental, partial, deprecated, or placeholder

- The old Phase 1 strategy path is still supported, but it is a research smoke workflow, not the main architecture for future event discovery.
- `YFinancePriceLoader` is exploratory convenience infrastructure, not a robust institutional data layer.
- `diagnostic_extract_from_unscreened_filings` is diagnostic-only and intentionally separated from validated outputs.
- `RSUVestingExtractor` and `InsiderSellingWindowExtractor` are placeholders and raise `NotImplementedError`.
- Plot creation exists in memory inside `src/analysis/event_study.py`, but the pipelines do not save plot files to `artifacts/`.

### Intended role in a broader trading / alpha stack

This repository is best treated as:

- a reusable research-data construction and audit layer
- a bounded event-identification and adjudication workflow
- a lightweight event-study and research-report scaffold

It is not:

- a broker integration layer
- a live trading engine
- a portfolio-management system
- a generalized alpha platform

The most reusable value is the scaffolding around auditable data ingestion, stable review keys, candidate triage, and reproducibility.

## 2. Repository / System Architecture

### Architecture by component

| Area | Exists today? | Primary modules | Notes |
| --- | --- | --- | --- |
| Data ingestion | Yes | `src/data/price_loader.py`, `src/data/sec_parser.py`, `src/sec/edgar.py` | CSV price replay, Trading Foundation EOD loading, `yfinance`, local YAML fixtures, SEC EDGAR acquisition/cache |
| Preprocessing / ETL | Yes | `src/universe/sp500_universe.py`, `src/pipeline/company_status.py`, `src/pipeline/batch_config.py` | Universe normalization, config parsing, status persistence |
| Universe construction | Yes | `src/universe/sp500_universe.py` | Current-membership S&P 500 snapshot only |
| Feature generation | Yes, narrow | `src/analysis/metrics.py`, `src/pipeline/phase3_candidates.py`, `src/analysis/strategy.py` | Returns, abnormal returns, volume spike ratios, attachment scores, confidence labels, review tiers |
| Screeners | Yes | `src/data/sec_parser.py`, `src/sec/edgar.py` | Filing-level ESPP mention screening |
| Signal generation | Yes, narrow | `src/events/espp_event_extractor.py`, `src/pipeline/phase3_candidates.py` | ESPP date heuristics and reviewed event construction |
| Ranking / scoring | Yes, heuristic | `src/pipeline/phase3_candidates.py`, `src/analysis/strategy.py` | Candidate confidence, attachment, quality category, review priority tiers |
| Backtesting / research | Yes | `src/analysis/event_study.py`, `src/analysis/strategy.py`, `src/analysis/research_summary.py`, `src/analysis/phase2_summary.py` | Event studies, descriptive reporting, simple strategy summaries |
| Portfolio / risk management | Minimal only | `src/analysis/strategy.py` | Summary metrics only; no true book/risk engine |
| Execution / order management | No | None | Not implemented |
| Reporting / artifacts | Yes | `src/analysis/research_summary.py`, `src/analysis/phase2_summary.py`, `src/analysis/phase3_review_packet.py`, `src/analysis/phase3_review_consensus.py`, `src/analysis/phase3_candidate_quality.py` | CSV and Markdown outputs |
| Notebooks | No committed notebooks | None | `rg --files -g "*.ipynb"` returned no notebook files |
| CLI / scripts | Yes | `pipeline/run_event_study.py`, `pipeline/run_batch.py`, `scripts/*.py` | Thin wrappers around `src` entry points |
| APIs / external services | Yes | SEC EDGAR, `yfinance`, local Trading Foundation `historical_data` root | No broker or database integrations |

### End-to-end data flow

#### Legacy offline replay

1. Load YAML filing fixtures from `fixtures/sec_filings`.
2. Parse ESPP hints and month/day candidates.
3. Estimate event dates, generate `event_review_id`, and persist `espp_date_audit.csv`.
4. Optionally apply manual review overrides from a CSV.
5. Load ticker and benchmark prices from CSV, Trading Foundation EOD folders, or `yfinance`.
6. Run event study and descriptive strategy summaries.
7. Persist CSV outputs plus `reports/espp_research_summary.md`.

#### Batch / discovery workflow

1. Load and validate the universe file.
2. Select tickers by explicit subset, sector subset, and/or max-company cap.
3. Acquire filings from fixtures or SEC cache/live SEC.
4. Write filing inventory and screening artifacts.
5. For Phase 2 legacy mode: estimate event dates directly from hints.
6. For Phase 3 mode: extract bounded candidates, deduplicate, classify, and build review queues.
7. Apply reviews or policy auto-review.
8. Convert eligible reviewed candidates into validated events.
9. Optionally run event-study windows.
10. Persist issuer status, audits, review artifacts, and summary reports.

## 3. Data Contracts

### Tracked input contracts

| Contract | Location | Important fields | Granularity / frequency | Point-in-time assumptions | Downstream consumers |
| --- | --- | --- | --- | --- | --- |
| Universe snapshot | `config/sp500_universe_2026-07-04.csv` | `ticker`, `company_name`, `issuer_name`, `issuer_id`, `cik`, `gics_sector`, `gics_sub_industry`, `primary_ticker`, `is_primary_share_class` | One row per listed share class in the dated snapshot | Snapshot date is July 4, 2026; current membership, not historical point-in-time | `src/universe/sp500_universe.py`, all batch runs |
| Universe source note | `config/sp500_universe_2026-07-04.source.md` | Snapshot date and manual primary-share-class mapping | Documentation | Not machine-read; human provenance only | Humans, handoff |
| Offline filing fixtures | `fixtures/sec_filings/*.yaml` | `ticker`, `filing_type`, `filing_date`, `text`; optional `source_id`, `source_url`, `source_cache_path`, `accession_number`, `report_date`, `issuer_name`, `issuer_id`, `cik` | One document or list of documents per YAML file | Research fixtures, not authoritative SEC records | `src/data/sec_parser.py`, offline runs, tests |
| Offline price fixtures | `fixtures/prices/*.csv` | `ticker`, `date`, `open`, `high`, `low`, `close`, `volume` | Daily OHLCV rows | Only as complete as each fixture file; no automatic market-calendar validation beyond what tests/configs assert | `CSVPriceLoader`, all offline runs |
| Trading Foundation validation config | `config/trading_foundation_business_day_example.yaml` | Canonical Trading Foundation `price_source`, main-machine `price_data_path`, reviewed business-day fixture inputs | One config | Absolute path is intentionally main-machine specific | Main-machine empirical validation of `TradingFoundationPriceLoader` |
| Legacy review CSV | `config/espp_date_reviews.csv`, `config/espp_business_day_reviews.csv` | `event_review_id`, `ticker`, `original_assigned_event_date`, `reviewed_event_date`, `review_status`, `review_note` | One row per reviewed legacy candidate | Review matching prefers `event_review_id`; fallback is `ticker + original_assigned_event_date` | `src/pipeline/run_event_study.py`, Phase 2 legacy mode |
| Phase 3 review CSV | `config/phase3_sec_discovery_sector33_20260817_review_decisions.csv` and generated review packets | `event_review_id`, `ticker`, `original_assigned_event_date`, `corrected_event_date`, `review_status`, `reviewer_note`, `reviewed_at`, `reviewer_id` | One row per deduplicated Phase 3 candidate | `review_as_of_date` matters for `future_scheduled` interpretation | `src/pipeline/phase3_candidates.py`, reviewed Phase 3 reruns |
| Batch config YAML | `config/*.yaml` | Universe path, ticker subset, date range, price source, filing source, output/cache dirs, event-study toggle, Phase 3 toggles | One config per run | Some configs are deterministic; live SEC configs depend on caches or network state | `src/pipeline/batch_config.py`, `src/pipeline/run_batch.py` |

### External / cached input contracts

| Contract | Location | Important fields | Granularity / frequency | Point-in-time assumptions | Downstream consumers |
| --- | --- | --- | --- | --- | --- |
| SEC submissions JSON | `<cache_dir>/submissions/CIK##########.json` and optional `*-submissions-###.json` | SEC submissions payload fields used to discover filings | One file per issuer plus optional history files | Deterministic only after cached; live runs depend on SEC responses at acquisition time | `src/sec/edgar.py` |
| SEC filing directory metadata | `<cache_dir>/filings/<cik>/<accession>/index.json` | Filing directory file listing | One per selected filing | Cached snapshot of SEC archive directory | `src/sec/edgar.py` |
| SEC primary filing document | `<cache_dir>/filings/<cik>/<accession>/<primary_document>` | Raw filing HTML/TXT | One per selected filing | Text normalized locally after fetch | `src/sec/edgar.py`, `src/data/sec_parser.py` |
| Filing provenance metadata | `<cache_dir>/filings/<cik>/<accession>/metadata.json` | `ticker`, `cik`, `accession_number`, `form`, `filing_date`, `report_date`, `primary_document`, URLs | One per selected filing | Generated by repo during download | Reproducibility bundle tooling |
| Trading Foundation historical data root | Configurable local filesystem path such as `C:\Users\RAS\OneDrive\RAS\Trading\Live\Trading_Foundation\historical_data` | Current repo consumes `eod/<TICKER>_1D.csv` with `t`, `open`, `high`, `low`, `close`, `volume`; upstream tree also contains `intraday`, `option_snapshot`, `option_ohlc`, and `volatility` | Daily EOD per symbol for current repo; other layers exist upstream but are not consumed here yet | Schema was verified from sandbox-side Trading Foundation references; ticker/date coverage still requires machine-local audit | `TradingFoundationPriceLoader`, first-pass and future batch runs that select `price_source: trading_foundation` |

### Generated output contracts

| Artifact | Location | Key fields / schema | Granularity | Canonical? | Downstream use |
| --- | --- | --- | --- | --- | --- |
| Selected universe | `<output_dir>/selected_universe.csv` | Same normalized universe fields as input snapshot | One row per selected share class | Yes, per run | Batch reporting and future reproducibility |
| Company status | `<output_dir>/company_processing_status.csv` | `processing_status`, filing counts, candidate counts, review counts, warnings, timestamps, universe identity fields | One row per selected share class | Yes, per run | Summary metrics, rerun diagnostics |
| Filing inventory | `<output_dir>/filing_inventory.csv` | Filing metadata plus form/date-window flags, source, cache paths, warning text | One row per discovered filing | Yes, per run | Audit, filing provenance, future sampling |
| Filing screening results | `<output_dir>/filing_screening_results.csv` | `espp_mention_flag`, matched terms, snippets, month/day candidates | One row per processed filing | Yes, per run | Filing-level screening audit |
| SEC acquisition metrics | `<output_dir>/sec_acquisition_metrics.csv` | Cache hit/miss counts, retry count, stage counts, warning count | One row per issuer | Yes, per run | SEC pipeline diagnostics |
| Legacy event audit | `<output_dir>/espp_date_audit.csv` in Phase 1/2 legacy mode | `event_review_id`, filing/source fields, assigned/effective dates, review fields, inclusion flag | One row per event-date candidate | Yes, per run | Event study input audit |
| Raw Phase 3 candidates | `<output_dir>/raw_candidate_extractions.csv` | Full `RAW_CANDIDATE_COLUMNS` schema from `src/pipeline/phase3_candidates.py` | One row per raw candidate mention | Yes, per run | Deep audit; raw evidence preservation |
| Deduplicated review queue | `<output_dir>/candidate_review_queue.csv` | Full `REVIEW_QUEUE_COLUMNS` schema | One row per canonical candidate group | Yes, per run | Manual review, reviewed reruns, future evidence consumption |
| Excluded candidate audit | `<output_dir>/excluded_candidate_audit.csv` | Same as review queue schema | One row per excluded canonical candidate | Yes, per run | False-positive analysis; method refinement |
| Review packet | `<output_dir>/candidate_review_packet.csv`, `reports/candidate_review_packet.md` | Reviewer-facing subset of candidate fields | One row / one Markdown section per retained candidate | Yes for manual review, not for research results | Human adjudication |
| Dual-review consensus outputs | `<output_dir>/review_decisions_reviewer_a.csv`, `review_decisions_reviewer_b.csv`, `review_consensus_audit.csv`, `review_consensus_decisions.csv`, `reports/review_consensus_summary.md` | Stable `event_review_id` keyed review records | One row per retained candidate | Yes when dual review is used | Final reviewed Phase 3 reruns |
| Validated event windows | `<output_dir>/all_event_windows.csv` | `event_id`, `event_date`, `tau`, `close_price`, `raw_ret`, `benchmark_ret`, `abnormal_ret`, `cum_ret`, `cum_abret`, `vol_ratio`, plus event metadata | One row per event-day observation | Yes if event study is enabled | Research summaries, strategy layer |
| Provisional diagnostics | `<output_dir>/provisional_diagnostic_candidate_audit.csv`, `<output_dir>/provisional_diagnostic_event_windows.csv` | Same concept as validated outputs, but diagnostic-only | Candidate/event-window rows | No, explicitly non-canonical | Diagnostic exploration only |
| Summary metrics | `<output_dir>/phase2_summary_metrics.csv`, `<output_dir>/phase2_sector_counts.csv`, `reports/phase2_research_summary.md` | Summary counts and Markdown narrative | Run-level | Yes, per run | Rapid orientation |
| Offline research summary | `<output_dir>/reports/espp_research_summary.md` | Descriptive coverage and return snapshots | Run-level | Yes for offline replay only | Offline smoke validation |
| Legacy strategy artifacts | `strategy_event_level.csv`, `strategy_group_summary.csv`, `strategy_overall_summary.csv`, `ticker_cross_section.csv` | Event-level and grouped descriptive strategy metrics | Event- and group-level | Secondary only | Legacy hypothesis testing |

### Canonical artifacts future projects should consume

Consume these first:

- `src/universe/sp500_universe.py` plus `config/sp500_universe_2026-07-04.csv` for current repo universe logic
- `selected_universe.csv` and `company_processing_status.csv` from a fresh run when you need exact run scope
- `filing_inventory.csv`, `filing_screening_results.csv`, `raw_candidate_extractions.csv`, and `candidate_review_queue.csv` when extending filing/event methodology
- `espp_date_audit.csv` only when you specifically need reviewed event dates from a completed run
- `reproducibility/phase3_sec_discovery_sector33_20260817/*` for the final closeout evidence bundle and manifest

Do not treat old `artifacts/` folders as canonical just because they exist locally. They are gitignored and some predate current schema/report logic.

## 4. Signals, Screens, and Trading Logic

| Component | Location | Logic / formula | Inputs | Outputs | Status |
| --- | --- | --- | --- | --- | --- |
| Filing keyword screener | `src/data/sec_parser.py` | Search for `"employee stock purchase plan"`, `"espp"`, `"section 423"`, `"purchase period"`, `"offering period"` | Filing text | `ESPPFilingHint` with `matched_terms`, snippets, date candidates, confidence | Implemented and tested |
| Legacy explicit-date extractor | `src/events/espp_event_extractor.py` | Parse month/day phrases; use keyword-pattern heuristics; infer year by next occurrence after filing date | `ESPPFilingHint` list | `ESPPEvent` list and audit rows | Implemented and tested |
| Legacy fallback anchors | `src/events/espp_event_extractor.py` | If no explicit date candidates for a year, add `06-30` and `12-31` | Filing date range | Audit/events with `fallback_default_anchors` | Implemented; heuristic only |
| Batch filing screen | `src/sec/edgar.py` | Filing inventory plus `extract_espp_hints` screening per selected filing | SEC/fixture documents | `filing_screening_results.csv` | Implemented and tested |
| Phase 3 bounded candidate extraction | `src/pipeline/phase3_candidates.py` | Extract specific dates from bounded context around ESPP matches; optional recurring-schedule fallback | `FilingDocument`, `ESPPContextMatch` | Raw candidate rows | Implemented and tested |
| Candidate year assignment | `src/pipeline/phase3_candidates.py` | If year omitted, assign next occurrence relative to filing date | Filing date + month/day | `candidate_event_date` | Implemented and tested |
| Candidate confidence label | `src/pipeline/phase3_candidates.py` | Explicit year + purchase language + non-purchase flags map to `high`/`medium`/`low` and numeric score | Candidate metadata | `extraction_confidence`, `confidence` | Implemented |
| Purchase-language attachment score | `src/pipeline/phase3_candidates.py` | Score from same sentence/clause, distance to purchase phrase, strong cue patterns, truncation penalty | Snippet and phrase offsets | `attachment_score` and related fields | Implemented and tested |
| Duplicate grouping | `src/pipeline/phase3_candidates.py` | Group by `ticker|kind|signature` where kind depends on purchase/non-purchase/recurring classification | Raw candidates | `duplicate_group_id` | Implemented |
| Canonical candidate selection | `src/pipeline/phase3_candidates.py` | Sort duplicate group by specificity, purchase likelihood, non-purchase likelihood, attachment, confidence, explicit year, filing recency | Raw candidate group | One canonical review row | Implemented |
| Queue refinement / exclusion | `src/pipeline/phase3_candidates.py` | Deterministic rules classify candidates into categories such as `plausible_specific_purchase_date`, `plausible_recurring_purchase_schedule`, `plan_history_or_amendment_restatement`, `reporting_snapshot_or_share_reserve_context`, `insufficient_context` | Deduplicated review rows | Primary queue vs excluded audit | Implemented and tested |
| Same-date shadowing | `src/pipeline/phase3_candidates.py` | If multiple primary candidates share ticker/date, keep highest-priority one and exclude the rest | Review queue | Shadowed excluded rows | Implemented |
| Evidence classification | `src/pipeline/phase3_candidates.py` | Map rows into `executed_purchase_event`, `administrative_election_change`, `recurring_purchase_schedule_or_definition`, `specific_purchase_reference_without_execution`, etc. | Candidate text windows | `evidence_class` | Implemented and tested |
| Policy auto-review | `src/pipeline/phase3_candidates.py` | Accept executed-event language; reject administrative-election language; mark schedule/boundary language as `unresolved` or `future_scheduled` based on `review_as_of_date` | Evidence class + candidate date | Review fields | Implemented and tested |
| Review eligibility gate | `src/pipeline/phase3_candidates.py` | Only `accepted` and `corrected` are eligible when `require_review_for_validated_windows=true` | Review status + dates | `included_in_event_study` | Implemented |
| Event study | `src/analysis/event_study.py` | Daily returns, abnormal returns vs benchmark, mean AAR/CAAR, t-stats, volume spike ratios over configurable window | Price frame, benchmark frame, events | Event panel and summary tables | Implemented and tested |
| Volume-spike filter | `src/analysis/strategy.py` | Keep events where `tau == 0` has `vol_ratio > threshold` and `confidence >= min_confidence` | Event panel | Filtered event panel | Implemented |
| Simple strategy summary | `src/analysis/strategy.py` | Compound raw and benchmark returns from post-entry window; summarize average excess return, win rate, Sharpe, max drawdown | Filtered panel + cross-sectional groups | Strategy CSVs | Implemented, but descriptive only |

### Important interpretation notes

- The Phase 3 pipeline produces reviewed research events, not live trade signals.
- The queue tiers (`Tier1`, `Tier2`, `Tier3`) are reviewer-priority tiers, not predicted alpha-strength tiers.
- `event_review_id` is the stable join key for all review workflows and should be preserved.
- The final closeout config uses `phase3.review_as_of_date: "2026-08-17"`, so `future_scheduled` classifications are anchored to August 17, 2026. If `review_as_of_date` is omitted in a future auto-review run, results can become time-dependent because the code falls back to `date.today()`.

## 5. Risk Controls

### Controls actually enforced today

- Universe validation rejects malformed tickers, malformed CIKs, duplicate tickers, and malformed duplicate-CIK groups.
- Secondary share classes are skipped so filings are processed once per issuer.
- Batch configs validate date ranges, `offline_mode`, filing-source mode, SEC user-agent requirements, retry/timeouts, and Phase 3 toggle consistency.
- Live SEC requests are sequential, throttled, and retried only on retryable errors.
- `max_filings_per_issuer` is a hard safety cap.
- Filing selection order is deterministic: discover -> form filter -> filing-date window -> safety cap.
- Review gating prevents `rejected`, `unresolved`, `future_scheduled`, and usually `unreviewed` candidates from entering validated event windows.
- Cache-only replay fails fast if required SEC cache files are missing.
- Final reproduction patches the SEC client so any network call raises an assertion.
- Batch processing isolates issuer failures so one bad issuer does not abort the full run.
- `resume_mode` can preserve already-successful issuer outputs.

### Controls that are not implemented

- No broker/account kill switch.
- No position limits, gross/net exposure controls, or concentration limits.
- No realized or unrealized loss limits.
- No live drawdown stop.
- No order validation layer.
- No market-hours gating, exchange connectivity monitoring, or alert routing.
- No portfolio optimizer or position-sizing engine.

### Practical conclusion

This repository contains research-process controls and reproducibility controls, not live-trading risk controls.

## 6. Backtesting and Validation

### Available backtest / research workflows

- Offline event-study replay via `src/pipeline/run_event_study.py`
- Batch event-study execution inside `src/pipeline/run_batch.py` when `event_study.enabled: true`
- Descriptive strategy summaries via `src/analysis/strategy.py`

### Core assumptions

- Price data is daily OHLCV only.
- Daily returns are close-to-close percentage returns.
- Abnormal return is asset return minus benchmark return.
- Volume spike ratio is current volume divided by trailing rolling mean volume.
- Event windows are centered only on event dates that exist in the price index.
- No intraday execution modeling exists.

### Transaction costs / slippage

- None are modeled.
- No commissions, borrow fees, slippage, spread costs, market impact, or capacity constraints are included.

### Lookahead protections and methodological guards

- Phase 3 reviewed outputs require review acceptance/correction before validated event windows.
- Final closeout replay is cache-only and network-blocked.
- The discovery sample explicitly disables event-study window generation until event viability is proven.

### What is not present

- No train/test split.
- No walk-forward.
- No cross-validation.
- No benchmark beyond benchmark-return subtraction and a simple strategy baseline.
- No explicit survivorship-bias mitigation beyond documenting that the universe is current-membership only.

### Existing experiments and validated results

- Offline replay fixtures: working and covered by tests.
- Five-company live SEC pilot and cache-only review workflow: working.
- Five-company consensus-reviewed pilot (`artifacts/phase3_live_sec_pilot_cache_only_consensus_reviewed`) shows:
  - `accepted_events = 3`
  - `rejected_events = 4`
  - `unresolved_events = 3`
  - `future_scheduled_events = 2`
  - `event_windows_generated = 1`
- Final 33-issuer closeout (`artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed`) shows:
  - `filings_selected = 197`
  - `raw_candidate_dates = 791`
  - `deduplicated_candidates = 11`
  - `accepted_events = 0`
  - `rejected_events = 7`
  - `unresolved_events = 3`
  - `future_scheduled_events = 1`
  - `event_windows_generated = 0`

### Test validation

The repository test suite passed on Tuesday, August 18, 2026:

- `105 passed in 27.03s`

Coverage is strongest around:

- universe normalization and duplicate-CIK handling
- CSV price loading
- SEC acquisition caching and date-windowing
- legacy event-review matching and propagation
- Phase 3 candidate extraction/refinement/review application
- review-packet and consensus workflows
- batch resume behavior and issuer-failure isolation
- final portability-bundle restore and replay assertions

### Known methodological weaknesses

- Current-membership universe creates survivorship and selection bias.
- ESPP event identification remains heuristic-heavy.
- The SEC-only methodology did not yield a large enough validated sample.
- Price fixtures are intentionally tiny and not a production-grade market-history source.
- Trading Foundation EOD is now the preferred empirical daily market-data path when the canonical upstream root is available locally.
- `yfinance` is convenient, not institutional.

## 7. Live / Paper Trading Integration

There is no live or paper trading integration in this repository.

Specifically absent:

- Alpaca or other broker adapters
- order objects or order state machines
- scheduling/orchestration for market sessions
- alerting/notification integrations
- account/risk synchronization
- persistent trade logs beyond research artifacts

Any future live trading layer should be built outside this repo or added as a clearly separate subsystem.

## 8. Existing Artifacts and Proven Outputs

### Tracked and authoritative in git

- `README.md`
- `PROJECT_STATUS.md`
- `PHASE3_EVENT_POLICY.md`
- `docs/HISTORICAL_OPTIONS_DATA_STATUS.md`
- `config/*.yaml`
- `config/phase3_sec_discovery_sector33_20260817_review_decisions.csv`
- `config/sp500_universe_2026-07-04.csv`
- `fixtures/*`
- `reproducibility/phase3_sec_discovery_sector33_20260817/README.md`
- `reproducibility/phase3_sec_discovery_sector33_20260817/phase3_sec_discovery_sector33_20260817_sec_cache.tar.gz`
- `reproducibility/phase3_sec_discovery_sector33_20260817/phase3_sec_discovery_sector33_20260817_sec_cache_manifest.json`

### Generated and reproducible

- `artifacts/phase3_live_sec_pilot_cache_only/*`
- `artifacts/phase3_live_sec_pilot_cache_only_consensus_reviewed/*`
- `artifacts/phase3_sec_discovery_sector33_20260817/*`
- `artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed/*`

These are useful when they correspond to a recent rerun from a tracked config. They are not git-tracked and should be treated as per-machine state.

### Generated but not authoritative by themselves

- `artifacts/first_pass/*`
- `artifacts/offline_business_day_example/*`
- `artifacts/trading_foundation_business_day_example/*`
- `artifacts/phase2_example/*`
- `artifacts/phase3_reviewed_fixture/*`

These are valuable examples and smoke artifacts, but future sessions should prefer the tracked configs plus fresh reruns over assuming every existing local CSV is current.

### Canonical artifact guidance

Treat these as canonical for future orientation:

- Final closeout bundle and manifest under `reproducibility/phase3_sec_discovery_sector33_20260817/`
- The final closeout config `config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml`
- The final review decisions file `config/phase3_sec_discovery_sector33_20260817_review_decisions.csv`
- Freshly rerun `selected_universe.csv`, `company_processing_status.csv`, `filing_inventory.csv`, `raw_candidate_extractions.csv`, `candidate_review_queue.csv`, and `espp_date_audit.csv`

### Stale or contradictory local outputs found during validation

- `artifacts/phase3_reviewed_fixture/reports/phase2_research_summary.md` reports `Companies processed: 0`, but the paired `company_processing_status.csv` contains `processing_status=completed_pending_review` for `TST`, and current code counts `completed_pending_review` as processed.
- Some older local artifact CSVs predate current status-column additions such as `unresolved_events` and `future_scheduled_events`.
- `README.md` mentions that the project produces simple plots, but no current pipeline persists plot files to `artifacts/`; plot objects only exist in memory inside `src/analysis/event_study.py`.
- The README project-layout block is incomplete relative to the current codebase: it omits newer modules such as `src/analysis/phase3_candidate_quality.py`, `src/analysis/phase3_review_consensus.py`, and `src/reproducibility/phase3_final_bundle.py`.

## 9. Reusable Components

### DO NOT REBUILD

| Reusable component | Exact location | Why reuse it |
| --- | --- | --- |
| Universe normalization and validation | `src/universe/sp500_universe.py` | Handles ticker/CIK normalization and legitimate duplicate-CIK share-class groups |
| Batch config parsing | `src/pipeline/batch_config.py` | Encodes the current run contract, SEC safeguards, and Phase 3 feature toggles |
| Price provider abstraction | `src/data/price_loader.py` | Clean interface for replacing fixture / Yahoo data with a better provider; now includes a canonical Trading Foundation daily EOD adapter |
| Filing fixture loader | `src/data/sec_parser.py::load_filing_documents_from_fixtures` | Deterministic local replay path |
| Filing screening parser | `src/data/sec_parser.py::extract_espp_hints` | Existing filing-level ESPP hint extraction |
| SEC acquisition and cache logic | `src/sec/edgar.py` | Already solves user-agent handling, throttling, cache layout, and stage-count artifacts |
| Legacy event audit keying | `src/events/espp_event_extractor.py::_build_event_review_id` and `estimate_event_dates_with_audit` | Stable review keys and auditable legacy event-date generation |
| Phase 3 raw-candidate extraction | `src/pipeline/phase3_candidates.py::build_phase3_candidate_artifacts` | Central candidate extraction, dedupe, tiering, and review application logic |
| Phase 3 review loader | `src/pipeline/phase3_candidates.py::load_phase3_candidate_reviews` | Validates corrected dates, duplicate keys, and status semantics |
| Review packet generation | `src/analysis/phase3_review_packet.py` | Stable reviewer-facing packet and preserved decision templates |
| Dual-review consensus | `src/analysis/phase3_review_consensus.py` | Reusable adjudication pattern for any human-reviewed signal pipeline |
| Candidate quality audit | `src/analysis/phase3_candidate_quality.py` | Useful for any future false-positive / queue-quality analysis |
| Company status schema | `src/pipeline/company_status.py` | Reusable issuer-level processing ledger |
| Batch resume / failure isolation | `src/pipeline/run_batch.py` | Already handles per-issuer persistence and resumability |
| Event-study engine | `src/analysis/event_study.py` | Reusable for any externally supplied event table |
| Strategy summary helpers | `src/analysis/strategy.py` | Reusable only as descriptive research helpers, not a production strategy engine |
| Phase summaries | `src/analysis/research_summary.py`, `src/analysis/phase2_summary.py` | Standardized Markdown/CSV research handoff outputs |
| Final replay bundle tooling | `src/reproducibility/phase3_final_bundle.py` and `scripts/*.py` | Solves portable evidence packaging, restore, and no-network reproduction |

## 10. Known Gaps / Technical Debt

### Genuine blockers

- The final SEC-only methodology did not produce a usable validated historical sample for a broader ESPP event study.
- Daily market-data integration is now available through Trading Foundation EOD, but this repo still has no native consumers for upstream intraday, option snapshot, option OHLC, or IV-metrics layers because the current ESPP workflows do not require them.
- There is no point-in-time universe history.
- There is no live execution, broker, or portfolio/risk subsystem.

### Worthwhile improvements

- Formalize schema versioning for generated CSV artifacts.
- Persist run metadata more explicitly, including config fingerprints and generation timestamps in summary artifacts.
- Add native consumers for Trading Foundation intraday/options/IV layers only when a future research module actually requires them.
- Add typed contracts or dataframe validators for the major output artifacts.
- Save plots explicitly if visual artifacts are wanted as first-class outputs.
- Separate general event-study utilities from ESPP-specific logic more cleanly if the repo broadens.

### Optional enhancements

- Alternative employee-flow observables beyond conservative SEC executed-event extraction.
- Better candidate calibration and richer evidence scoring.
- Additional filing forms or non-SEC sources more likely to contain executed-event wording.
- Generalized signal notebook templates that consume the universe and price-provider layers.

### Deliberately out of scope for the current repo state

- Merging unrelated SEC/fundamental ML systems into this repo
- Live broker execution
- Full portfolio construction and optimization
- A generalized feature store

## 11. Integration Contract for Future Alpha Research

### Recommended future flow

`universe -> market data -> features -> signal -> ranked candidates -> backtest/research evidence -> validated strategy -> separate risk/execution layer`

### What future modules should consume

At minimum:

- universe definition from `src/universe/sp500_universe.py`
- market data through a `PriceDataProvider`-compatible source
- for event-driven work, reviewed event tables from `espp_date_audit.csv` or a future standardized event table
- for filing-based work, `filing_inventory.csv`, `filing_screening_results.csv`, `raw_candidate_extractions.csv`, and `candidate_review_queue.csv`

### What future modules should output

Future modules should emit, at minimum:

- a candidate table
- a backtest or research-evidence summary
- a Markdown handoff/report
- a config file that fully determines the run

### Recommended minimum signal schema

This schema is not implemented centrally yet, but it is the recommended contract for new modules:

| Field | Meaning |
| --- | --- |
| `as_of_date` | Date the signal snapshot is valid |
| `ticker` | Normalized ticker |
| `issuer_id` | Stable issuer identity when available |
| `signal_family` | e.g. `mean_reversion`, `pead`, `vol_term_structure`, `options_ev`, `returns_ml` |
| `signal_name` | Concrete model/rule name |
| `signal_direction` | `long`, `short`, `flat`, or score-only |
| `horizon_days` | Intended holding horizon |
| `raw_score` | Native model/rule score |
| `normalized_score` | Comparable ranking score within the module |
| `evidence_type` | `price_only`, `event_reviewed`, `filing_candidate`, `vol_surface`, etc. |
| `evidence_ref` | Path or stable ID of supporting artifact |
| `data_cut_timestamp` | Timestamp for reproducibility |
| `config_id` | Hash or human-readable run/config identifier |
| `validated_flag` | Whether the module considers this candidate research-ready |

### Recommended minimum research-evidence outputs

- `candidate_signals.csv`
- `backtest_summary.csv`
- `research_report.md`
- optional `event_windows.csv` when event-driven

### Promotion rules into the existing system

#### If the new work is event-driven

- Reuse the Phase 3 pattern: raw evidence -> canonical candidate rows -> stable review key -> reviewed event table -> optional event study.
- Keep human-review states separate from validated research states.
- Preserve stable IDs.

#### If the new work is price / returns / volatility driven

- Bypass the SEC-specific extraction code.
- Reuse the universe loader, price-provider interface, event-study engine where useful, and summary/report patterns.
- Put new data-source logic under `src/data/`.
- Put new signal/backtest logic under `src/analysis/` or a clearly named `src/pipeline/` module.

### Directory / artifact convention for future modules

Recommended pattern:

- code: `src/analysis/<module>.py` and/or `src/pipeline/<module>.py`
- config: `config/<module>.yaml`
- outputs: `artifacts/<module_run_name>/`
- report: `artifacts/<module_run_name>/reports/<module>_summary.md`

## 12. Relationship to Other Projects

- This repo does not directly depend on a separate SEC/fundamental/filing-ML research stack.
- That separate system should stay separate unless this repo later adopts an explicit API or artifact contract for it.
- Preferred integration path is a clean signal/feature/result interface, not code-copying or repo-merging.
- Price/returns-based machine learning is in scope for future work here.
- SEC/fundamental ML should not be conflated with price/returns ML or event-study scaffolding.

## 13. Recommended Next Uses

Prioritize small research modules that reuse current infrastructure instead of building another general platform.

### Highest-leverage next steps

1. Build a generalized event-study input path that accepts externally curated event tables, because the event-study and audit/report layers already exist and the current blocker is event sourcing, not event-window code.
2. Build price/returns-based mean-reversion or volatility notebooks on top of `load_sp500_universe`, `PriceDataProvider`, and the reporting scaffold.
3. Reuse the existing Trading Foundation daily loader for equity/event work, and add broader `PriceDataProvider`-compatible consumers only before attempting intraday, options-ranking, or volatility-term-structure research.
4. Reuse the Phase 3 review workflow for any future human-adjudicated event signal, not just ESPP.

### Likely duplication to avoid

- Mean reversion research should not rebuild universe loading, daily OHLCV loading, summary reporting, or simple event-study math.
- PEAD / event-driven work should not rebuild stable review IDs, review packets, or dual-review consensus machinery.
- Volatility/options research should not rebuild run-config patterns, artifact conventions, or replay/report scaffolding.
- Returns-based ML should not rebuild the entire repo just to get price access or reporting; it mainly needs a module-specific signal contract plus any additional market-data layers not already covered by the current daily loader.
- Screener development should not recreate filing inventory, screening-stage artifacts, or per-issuer status tracking.

### Recommended immediate next step

Do not spend more time expanding the SEC-only ESPP executed-event methodology unless a new evidence source or materially stronger extraction logic is available.

The fastest productive reuse is:

- build a non-SEC event table or price-based signal module
- plug it into the current universe/data/report scaffold
- keep execution and portfolio logic out of this repo for now

## 14. Machine-Readable Quick Reference

```yaml
project_name: employee_flow_event_engine
validated_on: 2026-08-18
current_state: closed_out_sec_only_research_stack
primary_question: >
  Can a conservative SEC-only methodology recover enough historically validated
  ESPP purchase events to justify broader event-study work?
answer_as_of_2026_08_17: no

canonical_entry_points:
  - src.pipeline.run_batch.run_phase2_batch
  - src.pipeline.run_event_study.run_first_pass_event_study
  - scripts.restore_phase3_final_cache
  - scripts.verify_phase3_final_reproduction

canonical_input_artifacts:
  - config/sp500_universe_2026-07-04.csv
  - config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml
  - config/phase3_sec_discovery_sector33_20260817_review_decisions.csv
  - fixtures/prices/phase2_research_sample_prices.csv
  - reproducibility/phase3_sec_discovery_sector33_20260817/phase3_sec_discovery_sector33_20260817_sec_cache.tar.gz
  - reproducibility/phase3_sec_discovery_sector33_20260817/phase3_sec_discovery_sector33_20260817_sec_cache_manifest.json

canonical_output_artifacts:
  - selected_universe.csv
  - company_processing_status.csv
  - filing_inventory.csv
  - filing_screening_results.csv
  - raw_candidate_extractions.csv
  - candidate_review_queue.csv
  - espp_date_audit.csv
  - reports/phase2_research_summary.md

key_modules:
  universe: src/universe/sp500_universe.py
  price_data: src/data/price_loader.py
  filing_parser: src/data/sec_parser.py
  sec_ingestion: src/sec/edgar.py
  legacy_event_extraction: src/events/espp_event_extractor.py
  phase3_candidates: src/pipeline/phase3_candidates.py
  batch_orchestration: src/pipeline/run_batch.py
  event_study: src/analysis/event_study.py
  review_packet: src/analysis/phase3_review_packet.py
  review_consensus: src/analysis/phase3_review_consensus.py
  reproducibility: src/reproducibility/phase3_final_bundle.py

reusable_utilities_do_not_rebuild:
  - universe validation and selection
  - CSV price loader abstraction
  - SEC cache acquisition and replay
  - stable review-id workflows
  - candidate review packet generation
  - dual-review consensus generation
  - company status persistence and resume behavior
  - event-study engine and summary reports

risk_layer:
  implemented: research_process_controls_only
  missing:
    - live broker controls
    - order management
    - portfolio limits
    - kill switches
    - production risk management

integration_contract:
  consume:
    - universe snapshot or selected_universe.csv
    - PriceDataProvider-compatible market data
    - reviewed event tables for event-driven work
  output_minimum:
    - candidate_signals.csv
    - backtest_summary.csv
    - research_report.md
  keep_separate_from:
    - unrelated SEC/fundamental ML stacks

current_blockers:
  - no validated historical sample from the final SEC-only methodology
  - no robust production-grade market-data layer
  - no point-in-time universe history
  - no live execution stack

recommended_immediate_next_step: >
  Reuse the universe/data/report scaffold for a non-SEC event table or a
  price/returns-based alpha module instead of extending the current SEC-only
  ESPP methodology.
```
