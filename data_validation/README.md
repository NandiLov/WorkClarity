# Data validation and earnings (Ololade)

This folder holds the synthetic test data, the documents that describe it, and (soon) the Python module that validates shifts and calculates gross earnings.

All data is fake. No real person or company is in it.

## Folders

| Folder | What is in it |
| --- | --- |
| docs | The csv input contract, the field mapping against Castro's specification, the change log with reviewers and open items, and the data dictionary |
| test_data | 31 example csv schedules (schedule_inputs), the reference tables, the extracted rows, the planted errors and the answer keys. test_data/README.md explains each table |
| generator | The script that rebuilds the test data. Run it from an empty working folder: `python3 generate_workclarity_dataset_csv.py` |
| backend (one level up) | The Python service lives at backend/app/services/shift_calculations.py, as agreed with Nandila. calculate_shifts takes one worker's shifts and rules, and returns the checked shifts, conflicts and weekly totals. docs/module_interface.md shows the input and output |
| tests | 43 regression tests that run the service on the test data and check it against the answer keys. Run them from this folder with `python3 -m pytest tests -v` |

## Where to start

- Reviewers: read docs/CHANGES.md first. It lists who checks what and the open decisions.
- Castro: pay rules, flags and the field mapping.
- Nandila: the csv contract and the shape of the module's input and output.
- Lavanya: the edge case schedules S026 to S031 and the answer keys.

## Known answers

S001 = 384.00 USD, S013 = 810.00 USD (overtime off), S015 = 371.25 USD.

Open items are listed in docs/CHANGES.md. Please answer them in the pull request comments.
