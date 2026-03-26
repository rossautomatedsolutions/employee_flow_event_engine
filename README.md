# employee_flow_event_engine

`employee_flow_event_engine` is a modular Python research project for analyzing whether Employee Stock Purchase Plan (ESPP) purchase dates are associated with statistically significant price behavior.

## What it does

- Loads historical OHLCV data (currently via `yfinance`, through a swappable provider interface).
- Parses filing text (10-K / DEF 14A style documents) for ESPP clues.
- Generates approximate ESPP event dates.
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

Example config includes ticker metadata (market cap + employees) for cross-sectional grouping.

## Outputs

Under `artifacts/` (or configured output dir):

- `<ticker>_prices.csv`
- `<ticker>/event_panel.csv`
- `<ticker>/aar_summary.csv`
- `<ticker>/aar_plot.png`
- `filtered_event_windows.csv`
- `ticker_cross_section.csv`
- `strategy_event_level.csv`
- `strategy_group_summary.csv`
- `strategy_overall_summary.csv`

## Determinism and reproducibility notes

- CSV outputs are generated with stable ordering and fixed float formatting where applicable.
- Pipeline behavior is controlled by explicit config values.
- Event date construction follows deterministic precedence rules.

## TODOs (ESPP date accuracy)

1. Replace keyword/date heuristics with parser logic that captures plan-specific date fields from full filing sections.
2. Add SEC EDGAR retrieval adapter with filing metadata tracking (`accession`, `filing_url`, `accepted_datetime`).
3. Cross-reference extracted candidate dates with company fiscal calendars to reduce false positives.
4. Introduce confidence calibration and event-quality filters before running event studies.
5. Add optional human-review override file (`config/espp_overrides.yaml`) for research curation.

## Extensibility points

- Swap market data source by implementing `PriceDataProvider` in `src/data/price_loader.py`.
- Extend text parsers in `src/data/sec_parser.py`.
- Add additional metrics in `src/analysis/metrics.py` and consume them in `event_study.py`.
