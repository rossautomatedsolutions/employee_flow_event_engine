# Project Status

Last updated: 2026-08-17

## Current State

- The five-company live SEC pilot validated the workflow for bounded SEC retrieval, durable caching, candidate extraction, conservative event adjudication, reviewed reruns, and event-study gating.
- The 33-issuer sector-balanced discovery sample served as the terminal empirical viability test for the current SEC-only executed-event methodology.
- That discovery closeout is now complete and reproducible from tracked configs plus the local SEC cache/artifact bundle in this workspace.
- No mandatory work remains for the current SEC-only research phase.

## Final Research Result

The current SEC-only executed-event methodology is too sparse for the intended historical event study in the bounded discovery sample.

Bounded discovery closeout on 2026-08-17:

- Sample: 33 issuers from the current-membership S&P 500 sector-balanced discovery set
- Selected filings after safety cap: 197
- Raw candidates: 791
- Retained review candidates: 11
- Accepted historical events: 0
- Rejected: 7
- Unresolved: 3
- Future scheduled: 1
- Issuers with at least one accepted historical event: 0

Interpretation:

- This does not show that employee-flow effects do not exist.
- This does not show that ESPP-related events have no market effect.
- It shows that this specific conservative SEC-derived executed-event identification approach did not yield a sufficiently large validated historical event sample in the bounded 33-issuer discovery test.

## Completed Scope

The current repository/version can be considered complete for this SEC-only research phase in the following areas:

- COMPLETE: pipeline implementation for offline replay, batch processing, and Phase 3 review-gated discovery
- COMPLETE: bounded SEC retrieval, caching, throttling, retry/backoff, and cache-only replay
- COMPLETE: candidate extraction, candidate-quality refinement, and audit preservation
- COMPLETE: formal Phase 3 event policy and review-state handling
- COMPLETE: dual-review / consensus-reviewed live pilot workflow
- COMPLETE: agent-reviewed discovery closeout workflow
- COMPLETE: reproducible cache-only rerun of the final reviewed discovery result
- COMPLETE: bounded empirical viability testing of the SEC-only executed-event methodology
- COMPLETE: research conclusion for the methodology actually tested

## Reproducibility / Validation

Tracked closeout inputs:

- `config/phase3_sec_discovery_sector33_20260817.yaml`
- `config/phase3_sec_discovery_sector33_20260817.source.md`
- `config/phase3_sec_discovery_sector33_20260817_bkr_recovery.yaml`
- `config/phase3_sec_discovery_sector33_20260817_review_decisions.csv`
- `config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml`

Authoritative local closeout artifacts in this workspace:

- `artifacts/phase3_sec_discovery_sector33_20260817/`
- `artifacts/phase3_sec_discovery_sector33_20260817_bkr_refetch/`
- `artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed/`

Those artifact directories remain gitignored by design; the tracked repository
preserves the closeout methodology, rerun configs, and review decisions, while
the current workspace preserves the local SEC cache and reproduced outputs.

Closeout-specific findings:

- The initial live discovery run completed all 33 issuers but left one selected filing timed out: `BKR DEF 14A 0001193125-25-067674`.
- A narrow `BKR` recovery rerun on 2026-08-17 completed the missing selected filing and did not add candidate evidence.
- The final cache-only reviewed rerun completed with 33 processed issuers, 0 failures, and 0 warnings.

## Research Validity / Caveats

- The universe remains a dated current-membership S&P 500 snapshot rather than a historical point-in-time constituent set.
- The repo remains Research v0.1 infrastructure rather than a production-grade ESPP event-mastering system.
- The negative viability result is about sample sufficiency for this methodology, not about the nonexistence of employee-related price effects.

## Optional Future Research

These are optional follow-ons, not blockers to current closeout:

- improve heuristics around plan-effective, purchase-period-start, and purchase-period-end language
- target filing forms or issuer populations more likely to contain explicit executed-event wording
- broaden or redesign the bounded universe sample
- obtain point-in-time index membership to reduce survivorship bias
- investigate alternate employee-flow observables
- investigate non-SEC data sources for event identification
- revisit unresolved rows only if stronger execution evidence becomes available

## Definition Of Done

For the SEC-only research phase currently in scope, done means:

- the live pilot workflow is policy-governed and reproducible
- the bounded discovery sample has been executed and reviewed
- the final empirical viability result is explicit
- code, docs, configs, and final artifacts agree on that result
- optional future ideas are separated from blockers

Those conditions are now met.
