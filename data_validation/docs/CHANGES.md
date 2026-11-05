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
| 18 | The Python module validation/shift_validator.py and 38 regression tests are added. The tests check S001 = 384.00, S013 = 810.00, S015 = 371.25, all 31 weekly answers, the 5 known conflicts, and all 33 planted errors with the right flag. The input and output shape is a proposal for Nandila to confirm | Castro's specification | validation folder, tests folder | Nandila |
| 19 | Data fix found by the tests: the planted wrong date on S016 line 3 (R054) was 2026-11-12, the same date as line 4, which made line 4 look like a duplicate. It is now 2026-11-14. Only that one cell in raw_shifts.csv changed | Found during testing | raw_shifts.csv | Lavanya |
| 20 | Castro's review applied: PR01 and PR08 confirmed as product defaults, not universal payroll or travel time rules. PR15 now says PDF is the planned second format. PR16 now reads nonnegative_and_shorter_than_shift. New rules PR19 to PR22 record the decisions below | Castro | pay_rules.csv | Castro |
| 21 | A missing employer or location is a warning, not a blocker, as long as the essential details are valid. A missing or unknown location means the commute check is unavailable, not passed. error_types ET11 and ET12 changed from error to warning | Castro | pay_rules.csv (PR19), error_types.csv, validation module | Castro |
| 22 | A missing date is a blocking error under the missing or invalid flag, and every issue now carries a specific reason text | Castro | pay_rules.csv (PR20), validation module | Castro |
| 23 | needs_review shifts show in the review queue and are left out of earnings until confirmed. Rejected shifts are kept for traceability and left out of the schedule, conflicts and earnings. Both are in the module and covered by tests. They are now also in the csv test data as schedule S031 (change 29) | Castro | pay_rules.csv (PR21), validation module, tests | Castro |
| 24 | Flags: FL03 severity now depends on the underlying error, FL04 asks the worker to check a possible duplicate and not remove one, FL06 covers any unconfirmed shift | Castro | flag_types.csv | Castro |
| 25 | Earnings come from validated, worker-confirmed shifts, including corrections. Unconfirmed, rejected and invalid shifts do not count. The original csv is kept for traceability | Castro, Lavanya | pay_rules.csv (PR22) | Lavanya |
| 26 | Nandila confirmed the module is a separate service at backend/app/services/shift_calculations.py and gave her input and output shape. The file moved there from data_validation/validation and a new entry point, calculate_shifts, takes her payload and returns shifts with validation_status, eligible_for_earnings, paid hours, gross earnings, flags, a weekly summary per currency and an incomplete earnings indicator | Nandila | backend/app/services/shift_calculations.py, docs/module_interface.md | Nandila |
| 27 | The service accepts her field names (employer, date, location_text, end_date, source_line) and the csv names (employer_name, shift_date, location). end_date and the reporting week start from the rules are now supported | Nandila | shift_calculations.py, docs/module_interface.md | Nandila |
| 29 | Schedule S031 added so the csv data has a needs_review shift and a rejected shift. Line 2 is a true shift sent to the review queue. Line 4 is an extracted shift the worker rejected, with no true shift behind it. Until the worker confirms line 2 the module gives 225.00, and 337.50 once it is confirmed, which is the answer key. Added: schedules.csv, truth_shifts.csv (3 rows), raw_shifts.csv (4 rows R125 to R128), raw_truth_map.csv, expected_weekly_earnings.csv (1 row), shift_details.csv, case_types.csv (CT21) and schedule_inputs. 5 new tests bring the total to 43 | Castro (PR21) | test_data, tests | Lavanya |
| 28 | Cloud Storage is not needed for now. csv uploads are processed directly in FastAPI, and the original source line is kept on every shift | Nandila | docs/module_interface.md | Nandila |

## Cleaning and fixes that may affect Lavanya's work

Nothing earlier was removed or renumbered. Every earlier row, id and answer is unchanged, except the one cell in the first line below.

| What we did | Effect on test work |
| --- | --- |
| Fixed the planted wrong date in R054 (S016 line 3), from 2026-11-12 to 2026-11-14, because it made R055 look like a duplicate | If you compared R054 before, update it. It is still a planted wrong_date error |
| Added S031 with four extracted rows R125 to R128 at the end of the data | Totals are now 31 schedules, 122 true shifts, 128 extracted rows and 32 weekly rows (were 30, 119, 124 and 31). Planted errors stay at 33 and known conflicts stay at 5 |
| confirmation_status now has four values: confirmed, unconfirmed, needs_review and rejected | Check any filter that assumed only confirmed and unconfirmed |
| The rejected row R128 has no true shift (empty shift_id in raw_truth_map), like the invented shifts in S010 and S022, but it is not a planted error | Extracted rows without a true shift are now 3, while planted hallucinated_shift errors stay at 2. Do not use empty shift_id to count invented shifts |
| The needs_review row R126 is a true shift (S031-02) | Expected totals depend on state. The answer key says 337.50 for S031, and the module says 225.00 until the worker confirms line 2 |
| expected_weekly_earnings has a currency column and one row per currency, and S029 has an incomplete_shifts count | Join on worker, pay week and currency, not worker and pay week. S028 has two rows |
| Missing employer and missing location (S014) are now warnings, and a missing date (S006, S019) is a blocking error | Pass or fail expectations for these planted errors follow the severity in error_types.csv |
| Casing, spacing and symbol differences in location text, employer names and currency are cleaning cases, not planted errors | Standardize them before comparing the extracted rows with the true shifts. About 1 in 8 locations, 1 in 10 employers and 1 in 12 currency values are affected |
| Earnings column renamed to gross_earnings and cancelled shifts give 0.00 (S015 lines 3 and 5) | Update any query that used the old name |
| travel_minutes_to_next_shift is empty on the last shift of each worker and between the older schedules and S026 to S031, which are separate test weeks | Do not expect a value there |

## Still open

| Open item | Needs a decision from |
| --- | --- |
| Which field names are the standard: employer, date and location_text, or the csv names. Nandila said to align with the csv contract. The service accepts both, so nothing breaks either way. Final confirmation needed | Nandila |
| Whether shift_status and stated_hours stay in the csv contract | Nandila |

## Resolved by Nandila on 2026-11-05

The service is separate and lives at backend/app/services/shift_calculations.py. Nandila connects it to FastAPI and tests the full flow. csv uploads are processed directly in FastAPI without Cloud Storage for now. She is arranging access to the shared Google Cloud project.

## Resolved by Castro on 2026-11-05

Monday pay week (PR01), 30 minute travel gap (PR08), break rule (PR16), PDF as the second format (PR15), missing employer or location as a warning, missing date as a blocking error, needs_review and rejected handling, and the flag wording and severity.

## Resolved in this update

- end_date added as an optional column in csv_input_contract.md and data_dictionary.csv (csv_upload_file.end_date). The service already supports it.
- needs_review and rejected shifts are now in the csv data as schedule S031 (change 29), with tests.
- Confidence score: not part of Nandila's interface, so the service does not receive it and the low confidence check is skipped when it is absent. Closed.

## Not checked yet

schema.sql has not been run in BigQuery. If it gives an error on the first run, tell Ololade.
