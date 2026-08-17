# Phase 3 Discovery Sample Source Note

This file documents the bounded discovery-scale sample used by
[`config/phase3_sec_discovery_sector33_20260817.yaml`](config/phase3_sec_discovery_sector33_20260817.yaml).

- Parent universe: [`config/sp500_universe_2026-07-04.csv`](config/sp500_universe_2026-07-04.csv)
- Parent universe methodology: dated current S&P 500 membership snapshot, not a historical point-in-time constituent file
- Sample date anchor: 2026-07-04
- Sample purpose: feasibility / sample-building run for retrospectively disclosed ESPP purchase events
- Historical-label warning: this is not an unbiased historical S&P 500 sample and not a point-in-time investable universe

## Selection Rule

The sample is deterministic and sector-balanced:

1. Restrict the parent universe to `is_primary_share_class = true`.
2. Sort by `gics_sector`, then `ticker`.
3. Take the first 3 tickers alphabetically within each GICS sector.

That produces 33 issuers total: 3 issuers across each of the 11 sectors in the
dated 2026-07-04 snapshot.

## Label

Use this exact label in research writeups:

`Current-membership S&P 500 sector-balanced discovery sample (snapshot date 2026-07-04) for retrospectively disclosed ESPP purchase events.`

## Why Event Study Is Disabled

This discovery config disables event-study window generation on purpose.
The immediate goal is to measure validated-event availability under the
conservative Phase 3 policy before requesting broader live market-data coverage
for tickers outside the five-company pilot fixture.
