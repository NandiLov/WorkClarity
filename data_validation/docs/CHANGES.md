# What changed after the team's feedback (csv set, version 2)

Date: 2026-11-04, edge cases added 2026-11-05. These changes follow the replies from Lavanya, Castro and Nandila. The earlier mixed-format set is unchanged and kept for later image and pdf testing.

## Who reviews what

| Reviewer | Please check | Files to open |
| --- | --- | --- |
| Castro | Pay rules, the six flags and their wording, how cancelled shifts are handled, and the two assumptions still open (pay week start, travel gap) | pay_rules.csv, flag_types.csv, error_types.csv, expected_weekly_earnings.csv |
| Nandila | The csv structure, the shape of the extracted rows including confirmation_status, and who owns the Python module | csv_input_contract.md, csv_upload_template.csv, schedule_inputs folder, raw_shifts.csv |
| Lavanya | The new test scenarios, the csv-only set, and the correct answers for schedules S014 and S015 | case_types.csv, truth_shifts.csv, planted_errors.csv, schedules.csv |

## Changes

| No. | Change | Asked by | Where to see it | Reviewer |
| --- | --- | --- | --- | --- |
| 1 | The first 25 schedules and 105 extracted rows are now csv. The image and pdf data stays in the earlier set | Castro, Nandila, Lavanya | schedules.csv, raw_shifts.csv | Lavanya |
| 2 | A draft csv structure, one example csv file per schedule, and a short template | Nandila | csv_input_contract.md, csv_upload_template.csv, schedule_inputs folder | Nandila |
| 3 | Earnings column renamed to gross_earnings. Earnings are gross, from confirmed hours and worker-entered rates, after unpaid breaks | Lavanya, Castro | truth_shifts.csv, shift_details.csv, pay_rules.csv (PR02, PR11) | Castro |
| 4 | Overtime is not applied. Every hour is paid at the standard rate. S013 gives 810.00, and 915.00 only if overtime were applied | Lavanya, Castro | pay_rules.csv (PR04), expected_weekly_earnings.csv | Castro |
| 5 | Cancelled shifts: two added in schedule S015. They stay as records, are marked as not counting toward earnings, and give 0.00. Cancellation pay is out of scope | Lavanya, Castro | truth_shifts.csv, raw_shifts.csv, pay_rules.csv (PR12, PR13) | Castro |
| 6 | Missing employer and missing location test cases: two extracted rows in schedule S014, with two new error types | Lavanya | raw_shifts.csv, planted_errors.csv, error_types.csv | Lavanya |
| 7 | Six flags in plain language: overlap, insufficient commute, missing or invalid, duplicate, cancelled, unconfirmed. Every planted error maps to a flag | Castro | flag_types.csv, error_types.csv | Castro |
| 8 | confirmation_status added to extracted rows, to match the worker review step. 33 of 105 rows are unconfirmed | Castro | raw_shifts.csv | Nandila |
| 9 | Two new test scenario types, cancelled shift and missing info | Lavanya | case_types.csv | Lavanya |
| 10 | The source line of each extracted row is now the original csv row, so extraction can be checked against it | Nandila | raw_shifts.csv | Nandila |
| 11 | Pay rules updated: worker-entered rates, cancelled shifts excluded, cancellation pay out of scope, csv for testing, second format still to be agreed | Castro | pay_rules.csv (PR11 to PR15) | Castro |
| 12 | BigQuery marked optional in the README, because the app logic is Python with Firestore | Nandila | README.md | Nandila |
| 13 | Data dictionary has a new change column (new, changed, renamed, unchanged) and 11 rows describing the csv upload file | Castro | data_dictionary.csv | Castro |
| 14 | New field_mapping.md compares Castro's specification with this dataset: columns, validation codes, states, output, and the cases not tested yet | Castro, Nandila | field_mapping.md | Castro |
| 15 | Five edge case schedules added, S026 to S030, with 19 shifts and 19 extracted rows: zero or over 16 hour shifts (S026), negative or too long breaks (S027), two currencies in one week (S028), a confirmed shift without a rate (S029), and an unknown location (S030). Earlier schedules, shifts and answers are unchanged | Castro's specification | schedules.csv, truth_shifts.csv, raw_shifts.csv, planted_errors.csv, schedule_inputs folder | Lavanya |
| 16 | New error types ET13 to ET16, new case types CT16 to CT20, and new rules PR16 (valid break), PR17 (totals per currency) and PR18 (confirmed shift without a rate is incomplete). PR16 is an assumption | Castro's specification | error_types.csv, case_types.csv, pay_rules.csv | Castro |
| 17 | expected_weekly_earnings has two new columns, currency and incomplete_shifts. S028 has one row per currency, and S029 leaves the shift without a rate out of gross pay | Castro's specification | expected_weekly_earnings.csv | Castro |

## Still open

| Open item | Needs a decision from |
| --- | --- |
| Pay week starts Monday (assumption) | Castro |
| Minimum travel gap of 30 minutes between jobs at different locations (assumption) | Castro |
| Which second format to add after csv | Nandila and Castro |
| Wording of the six flag messages | Castro |
| Whether the csv columns match what the AI step expects | Nandila |
| Who owns the Python validation and earnings module, and the shape of its function | Nandila |
| Whether Cloud Storage is needed for uploaded files | Nandila |
| Break rule PR16: zero or more and shorter than the shift (assumption) | Castro |
| Whether a missing employer or location blocks the shift or only warns | Castro |
| Rejected and needs_review states, and whether end_date is needed | Castro and Nandila |

## Not checked yet

schema.sql has not been run in BigQuery. If it gives an error on the first run, tell Ololade.
