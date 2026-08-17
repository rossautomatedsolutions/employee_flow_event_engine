# Phase 3 Final SEC Replay Bundle

This directory contains the tracked portability bundle for the final reviewed 33-issuer SEC-only discovery closeout dated 2026-08-17.

Authoritative tracked inputs:

- `phase3_sec_discovery_sector33_20260817_sec_cache.tar.gz`
- `phase3_sec_discovery_sector33_20260817_sec_cache_manifest.json`
- `config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml`
- `config/phase3_sec_discovery_sector33_20260817_review_decisions.csv`
- `config/sp500_universe_2026-07-04.csv`
- `fixtures/prices/phase2_research_sample_prices.csv`

Bundle scope:

- 33 base SEC submissions JSON files
- 40 historical submissions JSON files referenced by those issuer submissions payloads
- 197 filing `index.json` files
- 197 filing `metadata.json` provenance files
- 197 primary filing documents

The `metadata.json` files are preserved for provenance and auditability. The cache-only replay itself requires the submissions JSON, filing `index.json`, and filing primary documents.

Fresh-clone replay:

```bash
python scripts/restore_phase3_final_cache.py
python scripts/verify_phase3_final_reproduction.py
```

If `artifacts/phase3_sec_discovery_sector33_20260817_cache` already exists from a failed or partial replay, the restore script automatically moves that directory to a sibling `*_pre_restore_backup` path before extracting the tracked bundle.

Equivalent direct reproduction after restore:

```bash
python -m src.pipeline.run_batch --config config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml --force
```

Expected reviewed result:

- 33 issuers attempted
- 197 selected filings complete
- 11 retained candidates
- 0 accepted
- 7 rejected
- 3 unresolved
- 1 future_scheduled

The bundle and manifest intentionally contain no SEC user-agent string, credentials, or local contact details.
