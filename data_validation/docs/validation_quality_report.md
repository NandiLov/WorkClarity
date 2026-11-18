# Validation quality report

How well do the validation rules catch the errors planted in the test data? The rules were run on `test_data/raw_shifts.csv`: 128 shifts as an AI extraction might deliver them, 33 with a planted error and 95 clean. Created by `tools/quality_report.py`, so it can be made again after any change to the rules.

## The numbers

- **All 33 planted errors were flagged and held out of the earnings total as delivered, but only 25 were identified by specific validation rules.** 33 of 33 raised the flag expected for their error type (100%).
- **25 of 33** were found by a specific rule that looks at the shift itself: a time that cannot be read, a missing date or rate, an impossible length or break, a duplicate, an unknown location.
- **8 of 33** are held by the general safeguards only, not by a rule that understands the error. They look like normal shifts (a wrong date, an old time after a change, an AM and PM mix up, a shift that is not on the schedule). No rule can see that they are wrong. They are held back only because the worker has not confirmed them and the extraction was low confidence.
- **0 of 95** clean shifts got a missing, invalid or duplicate flag.

## What the worker's confirmation changes

The shifts above were not confirmed by the worker, which is why all 33 stay out of earnings. To see what the rules do without that protection, the same data was run again with the worker confirming every planted error without noticing it.

- **22 of 33** are still stopped by the rules (excluded, incomplete or held for review).
- **3** still count because they are warnings that do not change the pay: a missing location, a missing employer, an unknown location.
- **8** count in the earnings. These are the ones no rule can see. The worker's review is the only thing that stops them, so the review screen has to show the extracted details clearly.

## By type of error

| Error type | Planted | Expected flag raised | Found by a specific rule | Rules that fired | If the worker confirms it |
|---|---|---|---|---|---|
| unparseable time | 2 | 2 of 2 | 2 of 2 | INVALID_TIME | 2 excluded |
| missing rate | 3 | 3 of 3 | 3 of 3 | MISSING_RATE | 3 incomplete |
| wrong date | 2 | 2 of 2 | 0 of 2 | none, held as unconfirmed and low confidence | 2 counted |
| missing end time | 2 | 2 of 2 | 2 of 2 | INVALID_TIME | 2 excluded |
| missing date | 2 | 2 of 2 | 2 of 2 | MISSING_DATE | 2 excluded |
| stale schedule change | 3 | 3 of 3 | 0 of 3 | none, held as unconfirmed and low confidence | 3 counted |
| am pm error | 5 | 5 of 5 | 4 of 5 | INVALID_DURATION | 4 excluded, 1 counted |
| duplicate row | 3 | 3 of 3 | 3 of 3 | POSSIBLE_DUPLICATE | 3 needs_review |
| missing break | 1 | 1 of 1 | 1 of 1 | MISSING_BREAK | 1 incomplete |
| missing location | 1 | 1 of 1 | 1 of 1 | MISSING_LOCATION | 1 counted |
| missing employer | 1 | 1 of 1 | 1 of 1 | MISSING_EMPLOYER | 1 counted |
| hallucinated shift | 2 | 2 of 2 | 0 of 2 | none, held as unconfirmed and low confidence | 2 counted |
| invalid duration | 2 | 2 of 2 | 2 of 2 | INVALID_DURATION | 2 excluded |
| invalid break | 2 | 2 of 2 | 2 of 2 | INVALID_BREAK | 2 excluded |
| confirmed missing rate | 1 | 1 of 1 | 1 of 1 | MISSING_RATE | 1 incomplete |
| unknown location | 1 | 1 of 1 | 1 of 1 | UNKNOWN_LOCATION | 1 counted |

## Every planted error

| Error | Shift | Type | Expected flag | Raised | Status as delivered | Status if the worker confirms |
|---|---|---|---|---|---|---|
| ER001 | R007 | unparseable time | FL03 | INVALID_TIME LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER002 | R008 | missing rate | FL03 | LOW_CONFIDENCE MISSING_RATE UNCONFIRMED | unconfirmed | incomplete |
| ER003 | R011 | wrong date | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER004 | R019 | missing end time | FL03 | INVALID_TIME LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER005 | R020 | missing date | FL03 | LOW_CONFIDENCE MISSING_DATE UNCONFIRMED | unconfirmed | excluded |
| ER006 | R021 | stale schedule change | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER007 | R023 | am pm error | FL06 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER008 | R024 | am pm error | FL06 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER009 | R027 | duplicate row | FL04 | LOW_CONFIDENCE POSSIBLE_DUPLICATE UNCONFIRMED | unconfirmed | needs_review |
| ER010 | R035 | missing break | FL03 | LOW_CONFIDENCE MISSING_BREAK UNCONFIRMED | unconfirmed | incomplete |
| ER011 | R043 | missing location | FL03 | LOW_CONFIDENCE MISSING_LOCATION UNCONFIRMED | unconfirmed | counted |
| ER012 | R045 | missing employer | FL03 | LOW_CONFIDENCE MISSING_EMPLOYER UNCONFIRMED | unconfirmed | counted |
| ER013 | R054 | wrong date | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER014 | R060 | unparseable time | FL03 | INVALID_TIME LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER015 | R068 | missing end time | FL03 | INVALID_TIME LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER016 | R070 | missing date | FL03 | LOW_CONFIDENCE MISSING_DATE UNCONFIRMED | unconfirmed | excluded |
| ER017 | R071 | missing rate | FL03 | LOW_CONFIDENCE MISSING_RATE UNCONFIRMED | unconfirmed | incomplete |
| ER018 | R072 | am pm error | FL06 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER019 | R074 | am pm error | FL06 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER020 | R076 | am pm error | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER021 | R079 | duplicate row | FL04 | LOW_CONFIDENCE POSSIBLE_DUPLICATE UNCONFIRMED | unconfirmed | needs_review |
| ER022 | R082 | duplicate row | FL04 | LOW_CONFIDENCE POSSIBLE_DUPLICATE UNCONFIRMED | unconfirmed | needs_review |
| ER023 | R089 | stale schedule change | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER024 | R090 | stale schedule change | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER025 | R098 | missing rate | FL03 | LOW_CONFIDENCE MISSING_RATE UNCONFIRMED | unconfirmed | incomplete |
| ER026 | R104 | hallucinated shift | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER027 | R105 | hallucinated shift | FL06 | LOW_CONFIDENCE UNCONFIRMED | unconfirmed | counted |
| ER028 | R107 | invalid duration | FL03 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER029 | R108 | invalid duration | FL03 | INVALID_DURATION LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER030 | R111 | invalid break | FL03 | INVALID_BREAK LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER031 | R112 | invalid break | FL03 | INVALID_BREAK LOW_CONFIDENCE UNCONFIRMED | unconfirmed | excluded |
| ER032 | R119 | confirmed missing rate | FL03 | LOW_CONFIDENCE MISSING_RATE | incomplete | incomplete |
| ER033 | R123 | unknown location | FL03 | LOW_CONFIDENCE UNCONFIRMED UNKNOWN_LOCATION | unconfirmed | counted |

## What this does not show

- The test data is synthetic. The rules and the planted errors were written by the same team, so this measures that the rules keep doing what we designed, not how they do on real schedules.
- It checks the validation rules, not the AI extraction itself. Extraction accuracy for PDFs and images is evaluated separately using `tools/compare_extraction.py` and the samples in `test_data/unstructured`.
- A shift can look normal and still be wrong. For those, the worker's confirmation is the safeguard, as the table above shows.

False alarms are counted as clean shifts with a missing, invalid or duplicate flag. Clean shifts as delivered: 2 cancelled, 83 counted, 1 needs_review, 1 rejected, 8 unconfirmed.
