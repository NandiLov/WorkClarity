# Field mapping: Castro's specification (v1.0) and the synthetic csv set

Status: draft by Ololade, 2026-11-05, updated after Castro's review on 2026-11-05 and again on 2026-11-06. Written from Castro's Product Requirements and Acceptance Specification. Rows marked "confirm" still need a decision, mostly from Nandila.

## 1. Input csv columns

| Castro's spec | This dataset | Match | Action |
| --- | --- | --- | --- |
| shift_date | shift_date | Same | None |
| start_time | start_time | Same | None |
| end_time | end_time | Same | None |
| break_minutes | break_minutes | Same | None |
| hourly_rate | hourly_rate | Same | None |
| currency | currency | Same | None |
| employer_name | employer_name | Same | Castro decided: a missing employer is a warning and the shift still counts. Listed as Recommended in the csv contract |
| location_text | location | Name differs | The service accepts both. Nandila's interface uses location_text. Confirm which is the standard |
| department | department | Same | None |
| end_date (optional) | end_date (optional) | Added | Now an optional column in the csv contract and the data dictionary, and supported by the service. Without it, an end time earlier than the start time means the next day |
| not in spec | shift_status | Extra here | Keep or drop. Confirm |
| not in spec | stated_hours | Extra here | Keep or drop. Confirm |

## 2. Validation flags

| Spec code | Dataset error type | Dataset flag | Note |
| --- | --- | --- | --- |
| INVALID_TIME | unparseable_time, missing_end_time | missing_or_invalid | A missing time counts as invalid |
| MISSING_RATE | missing_rate | missing_or_invalid | Warning. The shift is not counted and the week is marked incomplete |
| MISSING_EMPLOYER | missing_employer | missing_or_invalid | Decided by Castro: a warning, the shift still counts |
| MISSING_LOCATION | missing_location | missing_or_invalid | Decided by Castro: a warning, and the commute check is unavailable |
| INVALID_BREAK | missing_break, invalid_break (S027) | missing_or_invalid | A missing break is never treated as zero: earnings stay incomplete until the worker confirms no break or enters one (PR23). invalid_break covers a negative break and a break as long as or longer than the shift. Rule PR16, confirmed by Castro |
| INVALID_DURATION | invalid_duration (S026) | missing_or_invalid | One shift over 16 hours and one with equal start and end |
| POSSIBLE_DUPLICATE | duplicate_row | duplicate | The extra copy is held for review and not counted, so a shift is never counted twice (PR24) |
| LOW_CONFIDENCE | stale_schedule_change, am_pm_error, wrong_date, hallucinated_shift | unconfirmed | Planted extraction mistakes that the worker has to review |
| OVERLAP | overlap conflict (expected_conflicts.csv) | overlap | |
| COMMUTE_GAP | insufficient_commute conflict (expected_conflicts.csv) | insufficient_commute | 30 minute assumption in both |
| none | missing_date | missing_or_invalid | Castro decided: a blocking error under the missing or invalid flag, with a specific reason |
| none | missing currency (unit test, no schedule file) | missing_or_invalid | Earnings are incomplete and no total is produced without a currency (PR25). Added after Castro's second review |
| MISSING_RATE on a confirmed shift | confirmed_missing_rate (S029) | missing_or_invalid | The shift is left out of gross pay and counted in incomplete_shifts |
| Unknown location, unable to assess commute | unknown_location (S030) | missing_or_invalid | The commute check should say it cannot assess, not that the commute is fine |

## 3. States

| Spec state | Dataset field and value |
| --- | --- |
| extracted or draft | confirmation_status = unconfirmed |
| needs_review | confirmation_status = needs_review (S031 line 2). In the module, the tests and the csv data |
| confirmed | confirmation_status = confirmed |
| rejected | confirmation_status = rejected (S031 line 4). In the module, the tests and the csv data |
| cancelled | shift_status = cancelled, counts_toward_earnings = false, gross_earnings = 0.00 |

## 4. Output

| Spec output | Dataset |
| --- | --- |
| Paid hours per shift | truth_shifts.paid_hours |
| Gross earnings per shift, from exact minutes, rounded to 2 decimals | truth_shifts.gross_earnings |
| Weekly total from the per shift amounts | expected_weekly_earnings.expected_gross_mvp. Checked: all 32 weekly rows match |
| Totals per currency, no mixed currency | expected_weekly_earnings has a currency column. S028 has one USD row and one EUR row |
| Earnings incomplete count | expected_weekly_earnings.incomplete_shifts. S029 has 1 |
| Label "Estimated gross earnings (before tax or deductions)" | Display text for the app, not stored in the data |

## 5. What this dataset does not test yet

- A csv with an end_date column. The contract now lists it as optional and the module is tested with it, but no schedule file uses it yet
- The location column name, waiting on Nandila's contract
