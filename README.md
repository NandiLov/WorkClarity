# WorkClarity

**From work schedules to clearer shifts and earnings.**

WorkClarity is a schedule-to-earnings assistant for hourly workers who manage shifts across one or more employers. It aims to turn uploaded schedules into a reviewable weekly view, highlight scheduling problems, and estimate gross earnings without hiding uncertainty.

> **Project status:** Hackathon MVP in development. The Python validation and earnings service and synthetic regression dataset are in the repository. The complete upload-to-earnings frontend/backend journey is an integration goal, not yet documented here as production-ready.

## The problem

Hourly workers may receive schedules in different formats, work for multiple employers, and need to reconcile overlapping shifts, breaks, hourly rates, and weekly earnings. Manual tracking can be time-consuming and error-prone.

## How WorkClarity is designed to work

1. **Upload** a schedule. CSV is the priority format for the first complete workflow.
2. **Review** extracted or normalised shifts and correct any mistakes.
3. **Confirm or reject** shifts. Unreviewed extraction does not count toward earnings.
4. **Resolve warnings** for overlaps, possible duplicates, missing details, and short gaps between jobs.
5. **See the week** with confirmed shifts and estimated gross earnings, separated by currency.

**Core journey:** CSV upload → shift review → correction → confirmation → backend validation → weekly earnings.

PDF and image extraction, including NVIDIA-assisted processing, are conditional MVP goals and should not be assumed available until integrated and tested.

## MVP rules at a glance

- **Worker confirmation:** Only eligible, validated, confirmed shifts contribute to earnings.
- **Pay week:** Starts Monday; overnight shifts are assigned to the week in which they begin.
- **Paid time:** Shift duration minus unpaid breaks. Calculations use exact minutes; final monetary amounts are rounded to two decimal places.
- **Incomplete earnings:** Missing rate, currency, or unconfirmed break details must be surfaced, not silently treated as zero.
- **No counted shifts:** Show **Not counted yet** when shifts are awaiting confirmation or required information; distinguish this from a genuine zero-earnings week.
- **Duplicates:** Avoid double counting. Rejecting one duplicate should release the retained valid copy for consideration.
- **Commute warning:** A gap under 30 minutes between different locations is a scheduling heuristic, **not** a verified travel-time estimate.
- **Maximum shift length:** 16 hours for the MVP.
- **Out of scope:** Tax, deductions, overtime calculations, payroll processing, and actual route-time estimation.

The authoritative product decisions and acceptance tests are in [the MVP product specification](docs/product_mvp_spec.md).

## Technical direction

| Layer | Approach | Notes |
| --- | --- | --- |
| Frontend | Existing Newly prototype | Candidate interface to connect to the backend; integration to be verified |
| API | Python / FastAPI | Target backend service |
| Validation and earnings | Python calculation service | Deterministic rules, not parallel frontend calculations |
| Persistence | Google Cloud Firestore | Intended storage for shifts, corrections, and statuses |
| File storage | Google Cloud Storage | As required by upload/extraction flow |
| AI extraction | NVIDIA-assisted extraction | Conditional support for unstructured PDF/image schedules |

The backend is intended to be the **single source of truth** for validation and earnings. These are architectural targets; this README does not imply that every cloud component is deployed.

## Repository guide

| Path | Purpose |
| --- | --- |
| [`docs/product_mvp_spec.md`](docs/product_mvp_spec.md) | Worker journey, business rules, product decisions, and acceptance criteria |
| [`backend/app/services/shift_calculations.py`](backend/app/services/shift_calculations.py) | Python validation and gross-earnings service |
| [`data_validation/`](data_validation/) | Synthetic schedules, reference data, documentation, and regression tests |
| [`data_validation/docs/module_interface.md`](data_validation/docs/module_interface.md) | Validation service input/output contract |
| [`data_validation/docs/CHANGES.md`](data_validation/docs/CHANGES.md) | Data-validation changes and outstanding decisions |

## Run the validation tests

From the repository root, with Python 3 and `pytest` installed:

```bash
cd data_validation
python3 -m pytest tests -v
```

The data-validation README documents **49 regression tests** and known-answer fixtures. Passing these tests does **not** establish that the complete frontend, API, persistence, and extraction workflow has passed end-to-end tests.

For the dataset format and fixtures, see [`data_validation/README.md`](data_validation/README.md) and the documents in `data_validation/docs/`.

> Full application installation, environment variables, API startup, and deployment instructions should be added once the team confirms the integrated implementation. Do not commit API keys, credentials, or real worker information.

## Acceptance example

For confirmed shifts at **$16/hour**:

| Day | Shift | Unpaid break | Eligible earnings |
| --- | --- | --- | ---: |
| Monday | 09:00–17:00 | 30 min | $120.00 |
| Tuesday | 10:00–18:00 | 60 min | $112.00 |
| Wednesday | 09:00–17:00 | Unknown | Not counted yet |

**Current eligible total:** 14.5 paid hours and **$232.00**, with Wednesday flagged as incomplete. When the break is supplied and the shift is otherwise valid and confirmed, the total is recalculated.

## Current priorities

1. Complete the CSV-first worker journey end to end.
2. Align the Newly interface with the FastAPI data contract and authoritative Python earnings service.
3. Persist original extracted values, worker corrections, and confirmation decisions.
4. Implement and verify the agreed edge cases: duplicate rejection, missing rates, exact-minute rounding, overnight shifts, and incomplete weeks.
5. Run integration and end-to-end tests; add PDF/image extraction only when reliable.

## Team

| Contributor | Focus |
| --- | --- |
| **Nandila Mulilalila** | Team lead, architecture, cloud and integration |
| **Ololade Gbodogbe** | Data validation, earnings calculations, synthetic fixtures and regression tests |
| **Castro Mzizi** | Product and project planning, worker experience and acceptance criteria |
| **Lavanya Sai Bandla** | Testing and quality assurance |

Built for the **Mentor Me Collective × Google Cloud Launchpad** hackathon.

**Target delivery:** 28 November 2026.

## Contributing

Use pull requests for changes. For business-rule changes, update the relevant tests and check alignment with the [product specification](docs/product_mvp_spec.md). Coordinate API fields and persistence decisions with the team before introducing parallel implementations.

## License

No repository-wide license has been verified. Please confirm licensing with the repository owner before adding a license declaration.
