# Proposed Firestore structure for the validation output

Status: proposal by Ololade, 2026-11-05, updated 2026-11-06 after Castro's review. Nandila owns the data structure and Castro confirms what the frontend needs to retrieve. Everything here is a suggestion to change.

The structure follows the output of `calculate_shifts` in `module_interface.md`. Firestore has no joins, so each screen should be answered by reading one collection, and the service output is stored as it comes back so the frontend never recalculates anything.

## Collections

| Collection | One document is | Document id | Written by |
| --- | --- | --- | --- |
| `workers` | One worker profile | worker_id | The app, outside this proposal |
| `schedules` | One uploaded csv file | schedule_id | FastAPI on upload |
| `shifts` | One shift, with what was extracted, what the worker corrected and the calculated result | shift_id | FastAPI, then the worker's review |
| `weekly_summaries` | One pay week in one currency for one worker | worker_id, week_start and currency joined, for example W001_2026-11-09_USD | The service output |
| `conflicts` | One overlap or commute conflict, or one pair where the commute could not be assessed | generated id | The service output |
| `config` | The pay rules, in one document called pay_rules | pay_rules | Castro's values, read by the service |

## Fields of the shift document

| Field | Type | Source and meaning |
| --- | --- | --- |
| worker_id, schedule_id | string | Links to the worker and the uploaded file |
| source_line | string | The original csv row, kept for traceability and never edited |
| extracted | map | What the AI read: date, start_time, end_time, break_minutes, employer, location_text, hourly_rate, currency, shift_status. Never edited |
| current | map | The same fields after the worker's corrections. The service calculates from this map |
| confirmation_status | string | confirmed, unconfirmed, needs_review or rejected |
| week_start | string | From the output, the Monday of the pay week by default |
| paid_hours, gross_earnings | number | From the output, already rounded to 2 decimals |
| validation_status | string | valid, warning or invalid |
| earnings_status | string | counted, incomplete, excluded, unconfirmed, needs_review, rejected or cancelled |
| eligible_for_earnings | boolean | True only for valid, worker-confirmed shifts |
| flags | array of maps | Each has code, flag_type_id, flag_name, severity, reason and message, exactly as the service returns them |
| updated_at | timestamp | When the shift was last recalculated |

The `extracted` map is kept separate from `current` so the original upload stays available for comparison, as Castro asked. Every correction by the worker changes `current`, then the service is run again for that worker and the results below are overwritten.

## Weekly summary document

Fields come straight from the output: week_start, currency, shifts, paid_hours, gross_earnings, incomplete_shifts, earnings_incomplete and cancelled_shifts, plus worker_id. Totals are always read from this document and never added up in the frontend, which also keeps currencies from being mixed.

## Conflict document

Fields: worker_id, conflict_type (overlap, commute_conflict or commute_not_assessed), shift_a_id, shift_b_id, gap_minutes and week_start. A rejected shift never appears here.

## What each screen reads

| Screen | Query |
| --- | --- |
| Weekly summary | The `weekly_summaries` documents for the worker and week, one per currency |
| Calendar for a week | `shifts` where worker_id and week_start match, excluding rejected |
| Review queue | `shifts` where worker_id matches and earnings_status is needs_review, unconfirmed, incomplete or excluded. This includes confirmed shifts with a missing rate, break or currency, or an unresolved error |
| Why earnings are incomplete or excluded | The `reason` in each item of the shift's `flags` array, no extra read |
| Original and corrected values | The `extracted` and `current` maps of the shift document |
| Shift earnings and weekly gross | `gross_earnings` on the shift, and the `weekly_summaries` document |
| Commute cannot be assessed | `conflicts` where conflict_type is commute_not_assessed |
| Warnings on a shift | The `flags` array of that shift document, no extra read |
| Conflicts for a week | `conflicts` where worker_id and week_start match |

Suggested indexes: shifts on worker_id with week_start, and shifts on worker_id with earnings_status.

## Open questions

- Nandila: collection names, and whether shifts should be a subcollection under schedules or a top level collection as shown here. Top level makes the calendar and review queue queries simpler
- Castro: reviewed on 2026-11-06. The screens match the MVP, and a monthly summary and a correction history screen are not needed for now
- Nandila: whether the service is run again for the whole worker after each correction (simplest, and what this proposal assumes) or only for the changed week
