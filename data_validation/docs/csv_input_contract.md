# CSV input contract (draft for the MVP test)

Status: proposed by Ololade. Nandila and Castro to confirm or change.

One csv file is one worker's schedule for one pay week. The first row is the header, the file is UTF-8 and the separator is a comma. See csv_upload_template.csv for a working example and the schedule_inputs folder for 30 more.

## Columns

| Column | Required | Format | Example | Notes |
| --- | --- | --- | --- | --- |
| shift_date | Yes | YYYY-MM-DD | 2026-11-05 | The date the shift starts |
| start_time | Yes | HH:MM, 24 hour | 22:00 | |
| end_time | Yes | HH:MM, 24 hour | 06:00 | Earlier than start_time means the shift ends the next day |
| break_minutes | No | Whole number | 30 | Unpaid break. Blank is flagged because the break is unknown |
| employer_name | Yes | Text | Warehouse B Co | Used to tell shifts from different companies apart |
| location | Yes | Text | Warehouse B | Used for commute checks |
| department | No | Text | dispatch | |
| hourly_rate | Yes for earnings | Number | 18.00 | Entered or confirmed by the worker. If a real upload has no rate, the app asks the worker |
| currency | Yes | Currency code | USD | |
| shift_status | No | scheduled, changed or cancelled | cancelled | Blank means scheduled |
| stated_hours | No | Number | 8 | Shift length before breaks, used only as a cross-check |

## Rules

- Cancelled shifts are kept as records and left out of projected earnings.
- Gross earnings are paid hours multiplied by the hourly rate, where paid hours are the shift length minus the unpaid break.
- Overtime is not applied in the MVP.
- Anything missing, unreadable or unconfirmed is flagged for the worker in plain language. See flag_types.csv for the six flags.

## Questions to confirm

- Are these the column names and formats the AI step will receive and return?
- Is one worker per file right, or should the file have a worker_id column?
- Which second format do we add after csv?
