# Field mapping: Castro's specification (v1.0) and the synthetic csv set

Status: draft by Ololade, 2026-11-05. Written from a summary of Castro's Product Requirements and Acceptance Specification, so Castro should check every row against the document. Rows marked "confirm" need a decision.

## 1. Input csv columns

| Castro's spec | This dataset | Match | Action |
| --- | --- | --- | --- |
| shift_date | shift_date | Same | None |
| start_time | start_time | Same | None |
| end_time | end_time | Same | None |
| break_minutes | break_minutes | Same | None |
| hourly_rate | hourly_rate | Same | None |
| currency | currency | Same | None |
| employer_name | employer_name | Same | Spec treats it as optional, this dataset treats it as required. Confirm |
| location_text | location | Name differs | Rename one side. Confirm |
| department | department | Same | None |
| end_date (optional) | not present | Missing here | Add it, or keep the rule that an end time earlier than the start time means the next day. Confirm |
| not in spec | shift_status | Extra here | Keep or drop. Confirm |
| not in spec | stated_hours | Extra here | Keep or drop. Confirm |

## 2. Validation flags

| Spec code | Dataset error type | Dataset flag | Note |
| --- | --- | --- | --- |
| INVALID_TIME | unparseable_time, missing_end_time | missing_or_invalid | missing_end_time maps here only if a missing time counts as invalid. Confirm |
| MISSING_RATE | missing_rate | missing_or_invalid | |
| MISSING_EMPLOYER | missing_employer | missing_or_invalid | Blocking or warning is still open in the spec |
| MISSING_LOCATION | missing_location | missing_or_invalid | |
| INVALID_BREAK | missing_break, invalid_break (S027) | missing_or_invalid | invalid_break covers a negative break and a break longer than the shift. The rule (PR16) is an assumption |
| INVALID_DURATION | invalid_duration (S026) | missing_or_invalid | One shift over 16 hours and one with equal start and end |
| POSSIBLE_DUPLICATE | duplicate_row | duplicate | |
| LOW_CONFIDENCE | stale_schedule_change, am_pm_error, wrong_date, hallucinated_shift | unconfirmed | Planted extraction mistakes that the worker has to review |
| OVERLAP | overlap conflict (expected_conflicts.csv) | overlap | |
| COMMUTE_GAP | insufficient_commute conflict (expected_conflicts.csv) | insufficient_commute | 30 minute assumption in both |
| none | missing_date | missing_or_invalid | No matching spec code. Confirm which code applies |
| MISSING_RATE on a confirmed shift | confirmed_missing_rate (S029) | missing_or_invalid | The shift is left out of gross pay and counted in incomplete_shifts |
| Unknown location, unable to assess commute | unknown_location (S030) | missing_or_invalid | The commute check should say it cannot assess, not that the commute is fine |

## 3. States

| Spec state | Dataset field and value |
| --- | --- |
| extracted or draft | confirmation_status = unconfirmed |
| needs_review | not modelled yet |
| confirmed | confirmation_status = confirmed |
| rejected | not modelled yet |
| cancelled | shift_status = cancelled, counts_toward_earnings = false, gross_earnings = 0.00 |

## 4. Output

| Spec output | Dataset |
| --- | --- |
| Paid hours per shift | truth_shifts.paid_hours |
| Gross earnings per shift, rounded to 2 decimals | truth_shifts.gross_earnings |
| Weekly total from the rounded per shift amounts | expected_weekly_earnings.expected_gross_mvp. Checked: all 25 weeks match |
| Totals per currency, no mixed currency | expected_weekly_earnings has a currency column. S028 has one USD row and one EUR row |
| Earnings incomplete count | expected_weekly_earnings.incomplete_shifts. S029 has 1 |
| Label "Estimated gross earnings (before tax or deductions)" | Display text for the app, not stored in the data |

## 5. What this dataset does not test yet

- Rejected and needs_review states
- A missing employer or location treated as blocking (the spec has not decided between blocking and warning)
- A csv with an end_date column

These need the open decisions on missing employer, end_date and the rejected and needs_review states before the answer keys are written.
