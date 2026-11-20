# Unseen PDF and image schedule samples

6 schedules that the extraction prompt has never been tuned on, with an answer key of 28 shifts.
The first set in `test_data/unstructured` was used while the prompt was written, so a result on it is "in sample".
This set uses other layouts, employers and weeks, so it is a fairer check of how the extractor reads schedules it has not seen.
The answer key was written by hand, before any extraction was run on these files. Please do not tune the prompt on these
files. If you do, they stop being unseen, and a new set is needed.

| File | Schedule | Shifts | Difficulty | What it tests |
|---|---|---|---|---|
| unseen_01_email_confirmation.pdf | UNSEEN01 | 4 | medium | Confirmation email in sentences and bullets, 24 hour times, rate stated once, one 45 minute break, one shift with no break |
| unseen_02_monthly_calendar.pdf | UNSEEN02 | 6 | hard | Month calendar, the date comes from the cell, break and rate only in the note below, one cancelled shift, shifts in two weeks |
| unseen_03_timesheet_clock.pdf | UNSEEN03 | 5 | medium | Timesheet with clock in and clock out, lunch written as h:mm, an hours worked column and a totals row that are not shifts, an overnight shift |
| unseen_04_sms_two_senders.png | UNSEEN04 | 4 | hard | Chat screen with two senders (two employers), an update message that changes Wednesday, a shift that ends at midnight |
| unseen_05_printed_rota_two_adas.jpg | UNSEEN05 | 4 | hard | Angled photo of a rota for three people. Only Ada Okoye belongs in the answer. Ada Okonkwo has a similar name and must not be read as her |
| unseen_06_missing_details_off_days.png | UNSEEN06 | 5 | hard | Table with OFF days that are not shifts, a break of 0 that must stay 0, a break left out, a rate TBC with no currency, and an end time TBC |

## How to use them

Exactly as for the first set, with the answer key of this folder:

1. Give each file to the extractor and save everything it reads in one csv, one row per shift, with the columns
   `file_name, shift_date, start_time, end_time, break_minutes, employer_name, location, department, hourly_rate, currency, shift_status`.
   Leave a cell empty when the document does not give that detail.
2. From the `data_validation` folder, run:
   `python3 -I tools/compare_extraction.py extracted.csv test_data/unstructured_unseen/answer_key.csv`
   Known limit: the tool still reads the difficulty of each file from the `files.csv` of the first set
   (`test_data/unstructured`), not from the `files.csv` in this folder. So the "By difficulty" part of its report
   shows `unknown` for this set. Everything else in the report is correct for this set. The `difficulty` column in
   this folder's `files.csv` is there for reading and for a later update of the tool.

## Reading the answer key

- An empty cell means the document does not state that detail, so the right answer is an empty cell.
  A break of `0` that is written down (`unseen_01`, `unseen_05`, `unseen_06`) must stay `0`.
- `unseen_05_printed_rota_two_adas.jpg` prints seven shifts of other people. The key holds only Ada Okoye (see `target_worker` in `files.csv`).
  Shifts of other employees count as invented shifts.
- `unseen_04_sms_two_senders.png`: the Wednesday shift was changed by a later message, so the key holds the new times and `changed`.
- A shift that ends earlier than it starts (18:00 to 02:00) finishes the next morning. A shift that ends at midnight is `00:00`.
  The key keeps the times as printed, converted to 24 hour times.
- `OFF` days, the totals row and the hours worked column are not shifts.

## What this set does not show

It is small (28 shifts in 6 files), made on a computer, with no handwriting, and written by the same team that wrote
the rules. A good result here is a better sign than the first set, but it is not proof for real photographed schedules.

## Making the files again

`python3 -I generator/generate_unseen_samples.py` rebuilds the files, the answer key, `files.csv` and this README.
