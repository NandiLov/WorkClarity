# PDF and image schedule samples

14 schedules that are not csv, for checking how accurately an extractor (for example the NVIDIA step) reads them.
Eleven of them show the shifts of one clean csv schedule from `test_data/schedule_inputs`, so the correct values are known.
Three are written by hand: a team roster with several employees, and two schedules where some details are left out on purpose.
`answer_key.csv` lists what should be read from every file (62 shifts in total). `files.csv` describes each file.

| File | Schedule | Shifts | Difficulty | What it tests |
|---|---|---|---|---|
| pdf_01_table_clean.pdf | S001 | 3 | easy | Clean table with an overnight shift |
| pdf_02_table_week.pdf | S002 | 5 | easy | Clean table, five days, 30 minute breaks |
| pdf_03_sentences_12h.pdf | S003 | 3 | medium | One sentence per shift, 12 hour times, overnight shifts |
| pdf_04_weekly_grid.pdf | S012 | 3 | hard | Weekly grid, days as columns, weekend rate |
| pdf_05_list_exact_minutes.pdf | S005 | 3 | medium | Shifts that do not end on the hour (12:10), 12 hour times |
| img_01_screenshot_clean.png | S013 | 6 | easy | Clean screenshot of a table, six long shifts |
| img_02_photo_tilted.jpg | S015 | 5 | medium | Tilted photo with shadow and noise, two cancelled shifts |
| img_03_blurry_lowlight.jpg | S016 | 5 | hard | Blurry low light photo, five overnight shifts |
| img_04_phone_dark_mode.png | S024 | 5 | medium | Phone dark mode cards, weekend rate |
| img_05_cropped_perspective.jpg | S025 | 5 | hard | Angled and cropped photo, overnight shift on the pay week boundary |
| img_06_chat_message.png | S023 | 5 | medium | Manager chat message in free text, no table, rate stated once, two changed shifts |
| pdf_06_team_roster_multi_employee.pdf | TEAM01 | 4 | hard | Team roster with four employees. Only the shifts of Maria Santos belong in the answer, the others must not be read as hers |
| pdf_07_missing_details.pdf | MISS01 | 6 | hard | Table with details left out on purpose: a break, a rate, a currency, an end time and a location. The answer for each is blank |
| img_07_photo_missing_details.jpg | MISS02 | 4 | hard | Tilted photo with a break and a rate left out, and a break of 0 that is written down and must stay 0 |

## How to use them

1. Give each file to the extractor and save everything it reads in one csv, one row per shift, with these columns:
   `file_name, shift_date, start_time, end_time, break_minutes, employer_name, location, department, hourly_rate, currency, shift_status`
   (`file_name` is the name of the sample file, for example `img_03_blurry_lowlight.jpg`).
   Leave a cell empty when the document does not give that detail.
2. From the `data_validation` folder, run:
   `python3 -I tools/compare_extraction.py extracted.csv`
   Add a third value to also save the list of differences, for example `... extracted.csv test_data/unstructured/answer_key.csv differences.csv`.
3. The report shows shifts found, missed and invented, details invented and details dropped, accuracy for each field,
   results by difficulty and by file, and every difference. "Money fields" are date, start, end, break, rate and currency,
   the ones that change earnings.

Dates, times and rates can be written in common formats (`2026-11-03` or `3 Nov 2026`, `22:00` or `10:00 PM`, `17` or `17.00`).
They are converted before comparing. A dash, `n/a`, `null`, `unknown` or `TBC` counts as empty. Shifts are matched inside each
file by date and start time.

## Does the extractor invent details?

Two of the files leave details out on purpose (`pdf_07_missing_details.pdf`, `img_07_photo_missing_details.jpg`).
In the answer key an empty cell means the document does not say, so the right answer is an empty cell.
If the extractor fills it with a value, for example a break of `0` or a guessed rate, the report counts it as an
invented detail. If it leaves out something that is written down, it counts as a dropped detail. In
`img_07_photo_missing_details.jpg` the Friday break is written as `0`, and that must stay `0`, not become empty.

`pdf_06_team_roster_multi_employee.pdf` lists four employees. The answer key holds only the shifts of Maria Santos
(see `target_worker` in `files.csv`). Shifts of the other employees count as invented shifts.

## What the files show

- Every file has a "Week of ..." heading with the year. Day labels like "Tue 3 Nov" have no year, so the extractor
  has to take the year from the heading.
- A shift that ends earlier than it starts (22:00 to 06:00) finishes the next morning. The key keeps the times as printed.
- Cancelled shifts are printed as CANCELLED and the key has `shift_status` cancelled.
- The images are made on a computer: tilt, shadow, noise, blur, low light, perspective and cropping. They are not real
  photos, and there is no handwriting. Real photographed rosters may be harder.

## Checking what the extractor reads against what validation does

Reading a file correctly is not the same as getting the earnings right. After extraction the shifts go through the
validation rules like csv shifts. Anything missing or doubtful is flagged, not guessed.

## Making the files again

`python3 -I generator/generate_unstructured_samples.py` rebuilds the files, the answer key, `files.csv` and this README.
It needs reportlab, Pillow and numpy, and the output is repeatable.
