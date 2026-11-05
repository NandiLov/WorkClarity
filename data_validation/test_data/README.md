# WorkClarity synthetic dataset (122 shifts, csv)

## What this is

This is fake data that behaves like the real WorkClarity pipeline will. It has 122 correct shifts for 20 workers across 31 schedules and three pay weeks, plus 128 rows that pretend to be what our AI extracted from those schedules. 33 of the extracted rows contain deliberate mistakes. We use it to build and test validation, earnings calculations and accuracy reports before real data exists. No real person or company is in it.

Schedule S001 is the reference example: three shifts that must add up to 384.00. Every schedule is in csv format, following the kickoff decision to test the MVP with csv first. The files in schedule_inputs are the csv files a worker would upload, and csv_input_contract.md describes the structure we still need to agree. Image and pdf versions are kept in the earlier dataset for later testing.

## The story in five steps

1. A worker uploads a csv schedule.
2. The AI reads it and structures the shifts. Here that is raw_shifts.
3. The worker reviews and confirms what the AI read. Here that is the confirmation_status column.
4. The application validates the shifts, checks for conflicts and calculates earnings from the confirmed data.
5. The app shows the worker a weekly summary and calendar, with flags in plain language.

For testing we also know the right answers, so we can check every step. Those answer tables will not exist in real life.

## The tables, in plain words

For the meaning of every column, see data_dictionary.csv.

### Tables that will exist in the real product

| Table | Rows | What one row is | Who uses it |
| --- | ---: | --- | --- |
| workers | 20 | One row per worker: name, home area, how they travel. | Everyone, as a lookup. Names are fake. |
| employers | 11 | One row per company that employs workers. | Everyone, as a lookup. |
| locations | 16 | One row per place of work. Each belongs to one employer. | Ololade, to check commute conflicts. |
| schedules | 31 | One row per uploaded schedule file: whose it is, which pay week, which file format. | Nandila (what gets uploaded), Lavanya (which schedule is which test), Ololade. |
| raw_shifts | 128 | What the AI extracted, one row per shift line, with deliberate mistakes. This is the table the validation layer reads. | Nandila (shape of the AI output), Ololade (input to validation). |
| pay_rules | 22 | The pay and conflict rules we are assuming, such as pay week start and minimum travel gap. | Castro owns the values. Ololade uses them in calculations. |
| flag_types | 6 | The six kinds of flag a worker can see, each with a plain-language message. | Castro (wording), Nandila (app display), Ololade (checks). |

### Tables that exist only for testing

| Table | Rows | What one row is | Who uses it |
| --- | ---: | --- | --- |
| case_types | 21 | Names of the test scenarios, such as overnight, overlap, incomplete. | Lavanya, to label and add test cases. |
| error_types | 16 | The kinds of extraction mistake we planted, with a severity and the flag the worker sees. | Nandila and Lavanya, to see what the AI gets wrong. |
| truth_shifts | 122 | The correct shifts exactly as the schedules say, with correct hours and pay. This is the answer key. | Lavanya (format of correct answers), Ololade (accuracy checks). |
| raw_truth_map | 128 | Links each extracted row to the correct shift it should match. An empty shift_id means the AI invented the row. | Ololade, to measure accuracy. |
| planted_errors | 33 | Which extracted rows carry which mistake. | Ololade and Lavanya, to confirm our checks catch what we planted. |
| expected_weekly_earnings | 32 | The correct weekly hours and gross pay for each schedule. | Ololade, to confirm earnings are calculated correctly. |
| expected_conflicts | 5 | The overlaps and tight commutes that should be found. | Ololade and Castro, to agree what counts as a conflict. |

### The one big table for reading

| Table | Rows | What one row is | Who uses it |
| --- | ---: | --- | --- |
| shift_details | 122 | The big table: one row per correct shift with names, locations, rates, hours and pay all in one place. | Everyone, for reading and demos. |

Note: schedules carries a case_type_id label, which is a test label. A real schedule would not have it.

## Why the data is split into several tables

- **Each fact is stored once.** BrightMart's name lives in one row of employers. Every shift points to it with an employer_id. If a name changes, we fix one row, not thousands, and no two copies can disagree.
- **Each table has one owner.** The AI writes only raw_shifts. Castro decides pay_rules. The data layer writes the checked results. Nobody overwrites anybody else's work.
- **The AI output stays untouched.** We keep exactly what the AI returned so we can measure how accurate it was. If cleaned values replaced it, that measurement would be lost.
- **The answer key stays separate.** Validation must never be able to see the right answers, or the test would be meaningless.
- **Sensitive details are easy to protect.** Names and pay rates sit in their own tables, so the app or a dashboard can be given access to only what it needs.

## How the tables connect

Every table has a primary key, a column whose value is unique in that table, such as worker_id in workers. A foreign key is a column in another table that holds those same values and points back to the original row. This is how tables join. Examples: truth_shifts.worker_id points to workers.worker_id, and truth_shifts.location_id points to locations.location_id.

| Table | Primary key | Foreign keys |
| --- | --- | --- |
| workers | worker_id | none |
| employers | employer_id | none |
| locations | location_id | employer_id to employers.employer_id |
| case_types | case_type_id | none |
| flag_types | flag_type_id | none |
| error_types | error_type_id | flag_type_id to flag_types.flag_type_id |
| pay_rules | rule_id | none |
| schedules | schedule_id | worker_id to workers.worker_id, case_type_id to case_types.case_type_id |
| truth_shifts | shift_id | schedule_id to schedules.schedule_id, worker_id to workers.worker_id, employer_id to employers.employer_id, location_id to locations.location_id |
| raw_shifts | raw_id | schedule_id to schedules.schedule_id, worker_id to workers.worker_id |
| raw_truth_map | raw_id | raw_id to raw_shifts.raw_id, shift_id to truth_shifts.shift_id |
| planted_errors | error_id | raw_id to raw_shifts.raw_id, error_type_id to error_types.error_type_id |
| expected_weekly_earnings | weekly_id | worker_id to workers.worker_id, schedule_id to schedules.schedule_id |
| expected_conflicts | conflict_id | worker_id to workers.worker_id, shift_a_id to truth_shifts.shift_id, shift_b_id to truth_shifts.shift_id |
| shift_details | shift_id | shift_id to truth_shifts.shift_id, schedule_id to schedules.schedule_id, worker_id to workers.worker_id, employer_id to employers.employer_id, location_id to locations.location_id, case_type_id to case_types.case_type_id |

To compare the AI with the right answer: raw_shifts joins raw_truth_map on raw_id, then truth_shifts on shift_id.

## Why we also kept one big table

Small tables are best for storing data, but they are tiring to read, because one question needs five joins. shift_details solves this: one row per correct shift with the worker name, employer, location, department, hours and pay already included. It keeps every key (shift_id, schedule_id, worker_id, employer_id, location_id, case_type_id), so it can still be joined to any other table.

Think of the small tables as the filing cabinet and shift_details as the summary sheet on your desk. Rebuild the sheet from the cabinet whenever the cabinet changes. Never edit the sheet by hand.

In the real product the app will read finished tables like this one, so it needs simple queries and no joins, while the pipeline keeps writing to the small tables.

## What this means for each person

**Nandila (AI extraction and implementation).** csv_input_contract.md is the csv structure I propose for the MVP test, and schedule_inputs holds 31 example csv files in that structure. raw_shifts shows the output shape I assumed for the AI step, including confirmation_status for the worker review. Please compare both with what you are building and tell me what differs. error_types lists the kinds of mistake I planted so you can see which ones your extraction should avoid.

**Castro (product and user experience).** pay_rules now reflects your recommendations: gross pay from confirmed hours and worker-entered rates after unpaid breaks, overtime not applied, cancelled shifts kept as records but not counted, and cancellation pay out of scope. The pay week start and the 30 minute travel gap are still my assumptions, so please confirm them. flag_types holds the six flags you listed, each with a plain-language message for the worker. Please edit the wording. expected_conflicts shows the overlaps and tight commutes the app should flag.

**Lavanya (testing).** truth_shifts is the format of the correct answers, and case_types lists the scenarios we cover: overnight, overlap, commute, incomplete, schedule change, ambiguous time, duplicate, invented shift, week boundary, multiple rates, overtime, cancelled shifts and missing employer or location. Add your own test schedules as csv files like the ones in schedule_inputs, with the correct answers in the truth_shifts format and a case type for each. planted_errors shows which extracted rows are wrong and how.

**Ololade (data validation and earnings).** The small tables load into BigQuery, validation reads raw_shifts, and the expected tables let me confirm that every check and calculation is right. The accuracy report compares raw_shifts with truth_shifts.

**The whole team.** We all work from the same fake data, the same keys and the same assumptions, so we can find disagreements about field names or pay rules now and not during the build. Every assumption is written down, and anything we change is one edit and a rerun of the generator script.

## Things worth knowing

- raw_shifts keeps dates and times as text so malformed values still load, such as an end time written as 17h.
- raw_shifts has no shift_id on purpose. The AI would not know the answer. The link exists only in raw_truth_map.
- stated_hours is an optional csv column with the shift length before breaks. Validation can compare it with the length calculated from the start and end times.
- About 1 in 8 location texts, 1 in 10 employer names and 1 in 12 currency values have different casing, spacing or symbols. These are cleaning cases, not planted errors, so standardize them in the staging step.
- worker_name lives only in workers. Shift tables use worker_id so personal details stay in one place.
- Pay rules marked as assumptions (pay week start and the travel gap) still need the team's confirmation. Overtime is not applied in the MVP.
- Cancelled shifts stay in the data as records. They have counts_toward_earnings set to false and a gross_earnings of 0.00, so projected earnings leave them out.
- confirmation_status in raw_shifts shows whether the worker has confirmed what the AI read: confirmed, unconfirmed, needs_review or rejected. Only confirmed rows count toward earnings. S031 has one needs_review row and one rejected row. The truth answer key for S031 has the three real shifts (337.50), and the module should give 225.00 until the worker corrects and confirms the needs_review shift. The rejected row has no true shift behind it and is not a planted error.
- Hourly rates are worker-entered or worker-confirmed. They are in the test files so earnings can be tested.
- Schedules S026 to S031 are edge cases: a shift over 16 hours or with equal start and end (S026), a negative break and a break longer than the shift (S027), two currencies in one week (S028), a confirmed shift without a rate (S029), a location that matches nothing known (S030) and a shift in the review queue plus a rejected shift (S031). The rules behind them, PR16 to PR18, are assumptions for Castro to confirm.
- expected_weekly_earnings has one row per schedule and currency. Totals are never added across currencies. incomplete_shifts counts confirmed shifts left out of gross pay because the rate is missing.
- schema.sql creates every table with unenforced keys. It has not been run against BigQuery yet, so run it once and fix any message.

## Load into BigQuery (optional)

The app itself will use Python and Firestore, so this step is only for accuracy reports and dashboards. The Python validation module can read the csv files directly.

1. Create the dataset: `bq mk --dataset workclarity_dev`
2. Run schema.sql in BigQuery Studio. This creates the empty tables with their keys.
3. Load each CSV into its table, parents first: workers, employers, locations, case_types, flag_types, error_types, pay_rules, schedules, then truth_shifts, raw_shifts, raw_truth_map, planted_errors, expected_weekly_earnings, expected_conflicts and shift_details.
   Example: `bq load --source_format=CSV --skip_leading_rows=1 workclarity_dev.truth_shifts truth_shifts.csv`
4. Check the counts match the table above.
