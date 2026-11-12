# Newly calculator against our answer keys

Prepared by Ololade, updated 2026-11-12 after Castro's PR 3 decisions (exact minutes). Newly's earnings rules (logic.ts) were run the way the app uses them: parse the csv, import the rows that are not errors, let the worker confirm every shift the app allows, then total each Monday week. The same data was run through our module. Re-run it with `python3 -I tools/compare_newly.py <path to logic.ts> <output folder>` from the data_validation folder. It needs tsx (`npm install -g tsx`).

## Part A: the 31 clean csv files against expected_weekly_earnings.csv

32 weekly rows in the answer key. Newly matches 30 and differs on 2.

| Schedule | Week | Answer key | Newly | Cause | Fix belongs to |
| --- | --- | --- | --- | --- | --- |
| S015 | 2026-11-09 | 371.25 | 618.75 | The csv marks 2 of 5 shifts as cancelled. Newly does not read the shift_status column, so it counts them. A worker could mark them cancelled by hand | Newly or the FastAPI service |
| S029 | 2026-11-16 | 337.50 | 450.00 | Not a Newly fault. The clean csv file has the rate on every row. The missing rate is only in the extracted rows (Part B). Our module gives 450.00 on this file too | Not comparable in Part A |

S005 (250.33) and S018 (384.92) used to differ by a few cents. Castro decided on 2026-11-12 to use exact minutes and round only the final money amount, which is what Newly already did. Our answer key and module were changed to match, so these two now agree.

All other weekly rows match the answer key: S001 384.00, S013 810.00, S028 202.50 USD and 180.00 EUR, S031 337.50 after confirmation, and the rest.

## Part B: the 128 extracted rows with the 33 planted errors

Newly raises some warning or conflict on 21 of the 33 planted errors (an upper bound, because any warning on the row counts). Our module catches all 33.

| Planted error | Not caught by Newly |
| --- | --- |
| am_pm_error | 5 |
| wrong_date | 2 |
| hallucinated_shift | 2 |
| invalid_duration | 1 |
| stale_schedule_change | 1 |
| unparseable_time | 1 |

Newly has no check for impossible shift lengths, repeated shifts or times that look wrong. Impossible shifts are counted in the weekly total (for example an 18 hour shift in S008 and S020). The weekly totals of the extracted rows differ in 13 weeks between Newly and our module, mostly because of these rows. Where our module has nothing counted yet it now returns no total ("Not counted yet", for example S008). Those totals are not an answer key, so each needs a look case by case.

## What this means

- Rules Newly lacks: reading shift_status (cancelled) from the csv, a hold for possible duplicates, a check for impossible shift lengths, and flags that carry a reason and a message. A missing date blocks a shift in both.
- Rounding is no longer a difference: both use exact minutes.
- The Newly rules were tested as they stand. Nothing was changed in Newly.
