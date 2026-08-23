# Historical Options Data Status

Validated in the sandbox on Sunday, August 23, 2026 against:

- this repository's current code, tests, configs, and docs
- the sandbox-side Trading Foundation repo at `C:\GitHub\Trading_Foundation`
- the sandbox-side Trading Foundation schema reference at `C:\GitHub\Trading_Foundation\historical_data\SPY\schema_summary.json`

The canonical main-machine upstream root is expected to be:

```text
C:\Users\RAS\OneDrive\RAS\Trading\Live\Trading_Foundation\historical_data
```

That exact main-machine path was not present in the sandbox, so schema was verified here but coverage still requires main-machine validation.

## Repository purpose

`employee_flow_event_engine` is currently a daily-resolution ESPP event-study and research-reporting repo. Its implemented workflows:

- identify candidate ESPP purchase dates from SEC filings
- review or correct those dates
- load daily underlying prices for the ticker and benchmark
- run daily event windows and descriptive strategy summaries

It does not currently implement:

- historical option-chain reconstruction
- contract selection from historical bid/ask snapshots
- option PnL or lifecycle modeling
- intraday event-time alignment
- IV-surface or Greeks-based research inside this repo

## Actual dataset needs

Current implemented workflows require:

- [x] EOD underlying
- [ ] Intraday underlying
- [ ] Historical option snapshot
- [ ] Historical option OHLC
- [ ] IV surface
- [ ] IV metrics
- [ ] IV rank / percentile
- [ ] Volatility / skew artifacts
- [ ] Other

Future ideas mentioned in handoff material may eventually need option snapshots, option OHLC, or IV artifacts, but no committed workflow in this repo currently consumes them.

## Exact fields required

Current implemented market-data fields:

- `t`
- `open`
- `high`
- `low`
- `close`
- `volume`

Internal adapter mapping:

- Trading Foundation `t` -> normalized daily index used by `PriceDataProvider.load_daily_ohlcv(...)`
- Trading Foundation `open`, `high`, `low`, `close`, `volume` -> same internal names

Currently not required by committed repo logic:

- `option_symbol`
- `expiration`
- `strike`
- `option_type`
- `bid` / `ask`
- `bid_size` / `ask_size`
- `delta`, `gamma`, `vega`, `theta`, `rho`
- `implied_volatility`
- `underlying_price`

## Temporal granularity

Current repo requirement:

- `daily`

Current repo does not require:

- once-per-day point-in-time chain snapshot
- one-minute underlying
- one-minute option OHLC
- multiple intraday chain snapshots
- event-time quote alignment
- full contract lifecycle

## Historical depth

Minimum functional integration:

- enough daily price coverage for each ticker and the benchmark to span the configured event-study window around each reviewed event date

Research sample size needed for stronger conclusions:

- enough validated ESPP events to support a broader study

Important distinction:

- the current dominant limitation is event sample size, not missing options history
- the final SEC-only discovery closeout produced `0` accepted historical events on August 17, 2026, so broader empirical conclusions remain sample-limited even with better price access

## Requirement mapping

| Requirement | Needed by repo? | Trading Foundation source | Status | Notes |
| --- | ---: | --- | --- | --- |
| Daily underlying OHLCV for ticker and benchmark event windows | Yes | `historical_data/<TICKER>/eod/<TICKER>_1D.csv` | PASS WITH LIMITATIONS | Adapter built in `src/data/price_loader.py` as `TradingFoundationPriceLoader`; sandbox confirmed schema, but main-machine ticker/date coverage still needs audit. |
| Historical option opportunity-set / bid-ask chain reconstruction | No | `historical_data/<TICKER>/option_snapshot/<TICKER>_options_snapshot_<DATE>.csv` | PASS | Upstream layer appears structurally suitable for future option-selection research, but no committed repo path currently needs it. |
| Historical realized option-price path / exit approximation | No | `historical_data/<TICKER>/option_ohlc/option_ohlc_<DATE>.csv` | PASS | No current repo module models option contract returns or lifecycle exits. |
| Derived IV / skew state | No | `historical_data/<TICKER>/volatility/*` | PASS | Current repo uses daily equity-price volatility only; it does not consume upstream IV metrics yet. |
| Underlying intraday event-time alignment | No | `historical_data/<TICKER>/intraday/*.csv` | PASS | Existing event-study logic is daily only. |

## Smallest correct integration implemented

Implemented in this task:

- added `TradingFoundationPriceLoader` behind `PriceDataProvider`
- added `price_source: trading_foundation` support
- allowed `offline_mode` batch configs to use local deterministic Trading Foundation data
- added tracked validation config at `config/trading_foundation_business_day_example.yaml`

Not implemented in this task because the current repo does not need it:

- option snapshot loader
- option OHLC loader
- IV metrics loader
- intraday underlying loader

## Point-in-time and research safety

Current adapter safeguards:

- requires Trading Foundation daily EOD files to exist at the expected canonical path pattern
- requires `t`, `open`, `high`, `low`, `close`, and `volume`
- rejects invalid timestamps
- rejects duplicate daily rows for the same symbol/date
- raises explicit range errors when requested dates are outside available coverage

No silent fallback was added from empirical Trading Foundation data to synthetic option proxies.

## Sandbox validation

Automated validation completed in the sandbox:

```text
python -m pytest -q tests/test_pipeline_diagnostics.py tests/test_phase2_batch.py
```

Result:

- `54 passed` on Sunday, August 23, 2026

What was actually validated:

- Trading Foundation EOD schema mapping
- date-range filtering
- end-to-end first-pass event-study execution with a Trading Foundation-style local directory
- batch-config acceptance of `price_source: trading_foundation` in `offline_mode`

What was not validated in the sandbox:

- real main-machine ticker coverage under `C:\Users\RAS\OneDrive\RAS\Trading\Live\Trading_Foundation\historical_data`
- real AAPL / CRM / SPY files at that root
- any upstream option snapshot / option OHLC / IV metrics coverage

## Main-machine validation package

Exact repo command:

```text
python -m src.pipeline.run_event_study --config config/trading_foundation_business_day_example.yaml
```

Exact Trading Foundation path in config:

```text
C:\Users\RAS\OneDrive\RAS\Trading\Live\Trading_Foundation\historical_data
```

Expected output files:

- `artifacts/trading_foundation_business_day_example/benchmark_prices.csv`
- `artifacts/trading_foundation_business_day_example/AAPL_prices.csv`
- `artifacts/trading_foundation_business_day_example/CRM_prices.csv`
- `artifacts/trading_foundation_business_day_example/espp_date_audit.csv`
- `artifacts/trading_foundation_business_day_example/all_event_windows.csv`
- `artifacts/trading_foundation_business_day_example/reports/espp_research_summary.md`

Expected sanity checks:

- `benchmark_prices.csv`, `AAPL_prices.csv`, and `CRM_prices.csv` are non-empty
- price dates fall inside `2024-06-28` through `2025-01-03`
- `espp_date_audit.csv` contains business-day `effective_event_date` values such as `2024-07-01`, `2024-12-31`, and `2025-01-02`
- `all_event_windows.csv` is non-empty
- the run does not import or depend on `yfinance`

Failure signals to watch for:

- missing Trading Foundation EOD file for `AAPL`, `CRM`, or `SPY`
- missing required columns
- invalid timestamp values
- requested date range outside available coverage
- empty `all_event_windows.csv` caused by missing underlying coverage on reviewed event dates

Please paste back for follow-up review:

- the terminal output from the command
- the first 5 rows of `artifacts/trading_foundation_business_day_example/espp_date_audit.csv`
- the first 5 rows of `artifacts/trading_foundation_business_day_example/all_event_windows.csv`
- a directory listing of `artifacts/trading_foundation_business_day_example`

## Readiness classification

`ADAPTER_BUILT_BUT_COVERAGE_REQUIRES_MAIN_MACHINE_AUDIT`

Why:

- the repo's current implemented research does not require historical options data
- the real need is daily underlying EOD, and that integration is now implemented
- sandbox validation proved the adapter and workflow wiring
- actual main-machine file coverage still must be checked before the integration can be called fully validated
