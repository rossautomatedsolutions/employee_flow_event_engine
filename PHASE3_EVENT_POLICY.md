# Phase 3 Event Policy

Last updated: 2026-08-17

## Purpose

This policy governs Phase 3 SEC-derived ESPP candidate adjudication for historical event-study use.

The objective is conservative, reproducible historical measurement. The policy does not optimize for accepting more events.

## Core Rule

An event enters the historical event study only when the source text affirmatively supports that the ESPP purchase or exercise actually occurred on the candidate date.

Evidence that a plan contemplated, scheduled, defined, bounded, or estimated a purchase date is not sufficient by itself for historical event-study inclusion.

## Review Status Meanings

- `accepted`: the filing affirmatively supports an observed completed ESPP purchase or exercise on the candidate date
- `corrected`: the filing affirmatively supports an observed completed ESPP purchase or exercise, but on a different explicit date
- `rejected`: the text is administrative, definitional, plan-history, election-change, or otherwise not evidence of an observed purchase event
- `unresolved`: the text points to a purchase schedule, purchase-date rule, or period boundary, but does not affirm that the purchase actually occurred on the candidate date
- `future_scheduled`: as of 2026-08-17, the filing establishes a future schedule or future period end that remains ineligible for historical event-study use
- `unreviewed`: review work is operationally incomplete; this is not a methodological judgment

## Evidence Taxonomy

- Completed or executed purchase event: potentially eligible
- Explicitly scheduled future purchase event: not eligible before occurrence
- Recurring plan rule from which a date can be inferred: not sufficient on its own
- Purchase-period end date: not sufficient on its own
- Enrollment, election, or contribution-change date: not eligible
- Ambiguous date reference: not eligible without stronger execution evidence

## Practical Adjudication Rules

1. Accept only affirmative executed-event language.
2. Do not accept recurring purchase schedules without execution evidence.
3. Do not accept purchase-period-end language without execution evidence.
4. Do not accept projected share-capacity language as proof of execution.
5. Treat future-dated schedule references as `future_scheduled`, not as historical events.
6. Use `unresolved` when the text plausibly references a purchase boundary or rule but still fails the executed-event standard.
7. Keep `rejected`, `unresolved`, `future_scheduled`, and `unreviewed` rows out of validated event windows.

## 12-Candidate Adjudication

| Event review id | Final status | Evidence category | Reason |
| --- | --- | --- | --- |
| `CRM\|specific_purchase\|2024-06-15` | `rejected` | enrollment/election/change date | Filing ties the date to reducing an election during a purchase period, not to an observed purchase execution. |
| `CRM\|specific_purchase\|2024-12-15` | `rejected` | enrollment/election/change date | Same administrative election-change language as the June 2024 row. |
| `CRM\|specific_purchase\|2025-06-15` | `rejected` | enrollment/election/change date | Same administrative election-change language as the prior CRM 10-K rows. |
| `CRM\|specific_purchase\|2025-12-15` | `rejected` | enrollment/election/change date | Same administrative election-change language as the prior CRM 10-K rows. |
| `CRM\|specific_purchase\|2026-06-15` | `unresolved` | recurring plan rule | The filing defines when a purchase date falls within a recurring offering structure, but it does not affirm that a June 15, 2026 purchase actually occurred. |
| `CRM\|specific_purchase\|2026-12-15` | `future_scheduled` | explicitly scheduled future purchase event | The filing defines a future purchase-date rule, but December 15, 2026 is still future as of 2026-08-17 and remains ineligible for historical use. |
| `MSFT\|specific_purchase\|2023-06-30` | `accepted` | completed/executed purchase event | Filing states shares remained available after the exercise of purchase rights on that date. |
| `MSFT\|specific_purchase\|2024-06-30` | `accepted` | completed/executed purchase event | Filing states shares remained available after the exercise of purchase rights on that date. |
| `MSFT\|specific_purchase\|2025-06-30` | `accepted` | completed/executed purchase event | Filing states shares remained available after the exercise of purchase rights on that date. |
| `NVDA\|specific_purchase\|2024-08-30` | `unresolved` | purchase-period end date | Filing says the current purchase period runs until the date and gives projected purchasable share volume, but does not affirm execution on that date. |
| `NVDA\|specific_purchase\|2025-08-29` | `unresolved` | purchase-period end date | Same period-boundary and projected-capacity language as the 2024 NVDA row. |
| `NVDA\|specific_purchase\|2026-08-31` | `future_scheduled` | explicitly scheduled future purchase event | The current purchase period runs until a date that is still in the future as of 2026-08-17 and still lacks execution evidence. |

## Historical Event-Study Input

Accepted reviewed events:

- `MSFT|specific_purchase|2023-06-30`
- `MSFT|specific_purchase|2024-06-30`
- `MSFT|specific_purchase|2025-06-30`

Configured historical event-study date window in the live pilot:

- `2024-06-28` through `2025-01-03`

Therefore the only event that currently enters the historical event study is:

- `MSFT|specific_purchase|2024-06-30`

## Owner Review

Owner row-by-row adjudication is not required for the current bounded Phase 3 live SEC pilot.

Insufficient evidence is handled by exclusion through `rejected`, `unresolved`, or `future_scheduled`; it is not converted into certainty by owner interpretation.
