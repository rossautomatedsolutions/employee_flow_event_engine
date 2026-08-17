# Project Status

Last updated: 2026-08-17

## Current State

- The repository now has a formal Phase 3 SEC-derived ESPP event policy implemented in code, tests, and live artifacts.
- The 12 retained live SEC candidates in `artifacts/phase3_live_sec_pilot_cache_only/` now auto-resolve with zero owner-review rows.
- Final live consensus counts are 3 `accepted`, 4 `rejected`, 3 `unresolved`, and 2 `future_scheduled`.
- The latest reviewed live output is `artifacts/phase3_live_sec_pilot_cache_only_consensus_reviewed/`.
- That reviewed live output produces 1 validated historical event window: `MSFT` on `2024-06-30`.
- Owner row-by-row adjudication is no longer required for the Phase 3 live pilot.

## Completed In This Batch

- Defined and documented the explicit event-adjudication policy in `PHASE3_EVENT_POLICY.md`.
- Added Phase 3 review states `unresolved` and `future_scheduled` across loading, validation, eligibility handling, summaries, and company status counts.
- Tightened SEC snippet classification so recurring purchase-date definitions and purchase-period-boundary language are not misclassified as observed historical purchases.
- Updated dual-review consensus logic so matching `unresolved` and `future_scheduled` decisions auto-resolve instead of surfacing as manual owner work.
- Fixed `resume_mode` restoration so persisted `unresolved_events` and `future_scheduled_events` counts survive resumable reruns.
- Removed reviewer-facing packet and consensus workflow artifacts from reviewed output directories that already consume an applied review file.
- Allowed cache-only SEC reruns to replay from local artifacts without requiring a user-agent override, while still requiring a real SEC user agent for live network acquisition.
- Regenerated live review artifacts and reran both:
  - `config/phase3_live_sec_pilot_cache_only.yaml`
  - `config/phase3_live_sec_pilot_cache_only_consensus_reviewed.yaml`
- Hardened reruns so review files with the correct stable candidate IDs no longer fail only because rows were sorted differently.
- Added regression tests for the review-file canonicalization behavior.

## Live Review Status

Authoritative live-review inputs and outputs:

- `artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_a.csv`
- `artifacts/phase3_live_sec_pilot_cache_only/review_decisions_reviewer_b.csv`
- `artifacts/phase3_live_sec_pilot_cache_only/review_consensus_audit.csv`
- `artifacts/phase3_live_sec_pilot_cache_only/review_consensus_decisions.csv`
- `artifacts/phase3_live_sec_pilot_cache_only/reports/review_consensus_summary.md`
- `artifacts/phase3_live_sec_pilot_cache_only_consensus_reviewed/`

Final 12-row dispositions:

- `CRM|specific_purchase|2024-06-15` -> `rejected`
- `CRM|specific_purchase|2024-12-15` -> `rejected`
- `CRM|specific_purchase|2025-06-15` -> `rejected`
- `CRM|specific_purchase|2025-12-15` -> `rejected`
- `CRM|specific_purchase|2026-06-15` -> `unresolved`
- `CRM|specific_purchase|2026-12-15` -> `future_scheduled`
- `MSFT|specific_purchase|2023-06-30` -> `accepted`
- `MSFT|specific_purchase|2024-06-30` -> `accepted`
- `MSFT|specific_purchase|2025-06-30` -> `accepted`
- `NVDA|specific_purchase|2024-08-30` -> `unresolved`
- `NVDA|specific_purchase|2025-08-29` -> `unresolved`
- `NVDA|specific_purchase|2026-08-31` -> `future_scheduled`

Historical event-study input after review:

- `MSFT|specific_purchase|2024-06-30`

Accepted but outside the configured event-study date window `2024-06-28` through `2025-01-03`:

- `MSFT|specific_purchase|2023-06-30`
- `MSFT|specific_purchase|2025-06-30`

## Current Test Status

- `python -m pytest -q`
  Result on 2026-08-17: `98 passed in 19.79s`
- Reproduced cache-only live pilot outputs on 2026-08-17 by rerunning:
  - `python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only.yaml --force`
  - `python -m src.pipeline.run_batch --config config/phase3_live_sec_pilot_cache_only_consensus_reviewed.yaml --force`

## Research Validity / Caveats

- Historical event-study inclusion now requires affirmative evidence that the ESPP purchase or exercise actually occurred on the candidate date.
- Recurring plan rules, purchase-period end dates, projected capacity language, and future schedule references remain visible in audit artifacts but do not generate validated windows.
- `MSFT` remains the strongest live evidence because the filings explicitly state purchase rights were exercised on the named dates.
- The bounded five-company SEC pilot is still a workflow-validation slice, not a full-universe production dataset.
- The universe snapshot remains current-membership based, so survivorship and index-selection bias still apply.

## Definition Of Done

Closeout-ready state for this repository now means:

- the live Phase 3 candidate set is governed by explicit policy rather than owner row-by-row interpretation
- reviewed reruns complete reproducibly
- tests cover the live review states and rerun behavior
- docs, summaries, and artifacts agree on the final reviewed event set

Those conditions are now met for the current bounded pilot.

## Next Action

No mandatory autonomous closeout work remains in the bounded pilot.

Owner/final validation can focus on:

- confirming the formal policy in `PHASE3_EVENT_POLICY.md`
- inspecting the reviewed live artifacts in `artifacts/phase3_live_sec_pilot_cache_only_consensus_reviewed/`

Optional future research after owner validation:

- expand beyond the five-company pilot
- revisit broader filing coverage or point-in-time universe construction
- test whether additional evidence classes can safely upgrade some `unresolved` rows without relaxing the conservative policy
