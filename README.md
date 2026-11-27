# WorkClarity

**From fragmented work schedules to clearer shifts and earnings.**

WorkClarity is a hackathon-stage web application for hourly workers who juggle schedules from one or more employers. It imports schedules, lets workers verify and correct shifts, identifies scheduling conflicts and missing details, and produces **estimated gross earnings** using deterministic backend rules.

> **Status — 25 November 2026:** V1 MVP deployment candidate. The team has reported a working Firebase-hosted frontend at [workclarity.web.app](https://workclarity.web.app), connected to a Google Cloud-hosted API, including a successful synthetic PDF-to-earnings demonstration. The repository's `feature/workclarity-v1-mvp` branch contains the integrated implementation. This is **not** a production-ready payroll or employee-data service. Do not upload real worker records without approved privacy, authentication, persistence, and cloud-cost controls.
>
> **Cost notice:** The team has asked contributors **not to run additional AI uploads on the deployed application** without approval. Use synthetic local tests and existing demo evidence instead.

## What works in the V1 code

| Feature | Implementation |
| --- | --- |
| CSV schedule import | Client-side CSV parser; imports are initially unconfirmed and can be appended or used to replace a schedule with confirmation. |
| PDF / image schedule extraction | `POST /api/v1/shifts/extract` accepts PDF, PNG, JPEG, and WebP files (up to 20 MB). Gemini is the default primary provider; NVIDIA can be the fallback when configured. |
| Worker review and correction | Workers can edit, confirm, reject, restore, and compare current shifts with extracted values. AI-extracted shifts always start as `needs_review` and require **individual confirmation**. |
| Worker attribution safeguards | Clearly unrelated roster rows are excluded; uncertain or unnamed worker assignments remain flagged for review and must be explicitly assigned to a worker before shift confirmation. Worker-assignment confirmation is managed through frontend state/localStorage and is not independently persisted or enforced through a dedicated backend confirmation endpoint. Assigning a worker does not confirm the shift itself; AI-extracted shifts remain in `needs_review` until individually confirmed by the user.  |
| Validation and conflict detection | FastAPI calculation service detects overlapping shifts, possible duplicates, missing/invalid data, and short inter-job gaps. |
| Schedule and earnings views | Monday-start weekly schedule, overnight shifts, per-currency estimated gross earnings, and separate pending/incomplete hours. |
| Five frontend routes | `/upload`, `/review`, `/warnings`, `/schedule`, `/earnings`. |

**Scope distinction:** The source code implements the features above; the cloud deployment and its successful synthetic end-to-end test are **team-reported**, not independently certified production readiness. The newer UI redesign on `design/v1-ui-polish` is a separate local workstream and is not part of the V1 implementation described here until reviewed and merged.

**Additional deployed-app QA (team-reported, 25 November):** Ololade checked seven synthetic demonstration scenarios against the deployed app: the specification example, overnight shifts, short commute gaps, overlaps, duplicate/cancelled shifts, multiple currencies, and missing information. She reported results matching her local tests. This is useful smoke-test evidence, **not** an independent security or production certification.

## User journey

1. **Upload:** Import a CSV file or send a PDF/image schedule for AI extraction. Multiple files can be appended one at a time.
2. **Review:** Check dates, times, employer, location, breaks, rates, currencies, and any AI confidence/worker-attribution indicators.
3. **Correct and confirm:** Compare original extraction with edits. Resolve uncertain worker assignment before confirming an AI shift. AI shifts cannot be bulk-confirmed.
4. **Resolve warnings:** Address overlaps, duplicates, incomplete data, and short gaps between locations.
5. **See the results:** View the week and estimated gross earnings for **eligible, validated, worker-confirmed** shifts, separated by currency.

AI extraction is not a payroll calculator. The Python service, rather than the AI model or React frontend, calculates paid time and estimated earnings.

## Architecture

| Layer | Technology | What it does |
| --- | --- | --- |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router | Upload, review, corrections, warnings, weekly schedule, and earnings display. |
| Frontend state | React context + browser `localStorage` | Holds a separate **local demo workspace** for each selectable worker. This is not server-side persistence or an authentication boundary. |
| API | Python FastAPI + Pydantic | Health check, AI extraction endpoint, and deterministic calculation endpoint. |
| Extraction | `ai_extraction/` + `pypdfium2` / Pillow | PDF/image preparation, Gemini and NVIDIA provider adapters, retries/fallback, schema validation, and incomplete/failed extraction reporting. |
| Calculation | `backend/app/services/shift_calculations.py` | Authoritative validation, conflict detection, paid hours, and gross earnings, using server-side pay rules and known locations. |
| Deployment configuration | `Dockerfile` + `firebase.json` | Python API container (Cloud Run compatible) and Firebase Hosting single-page-app configuration. |

**Data path:** CSV is parsed in the browser; PDF/images are sent to the extraction API. Workers review/edit the resulting shift records. The frontend then posts their current records to the calculation API and displays its response. The browser stores its workspace locally.

### API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health status; responds with service name and API version. |
| `POST` | `/api/v1/shifts/extract` | Multipart form upload: `file` plus optional `target_worker` for identification context; returns extraction status, reviewable shifts, provider metadata, and errors/partial-result details. |
| `POST` | `/api/v1/shifts/calculate` | JSON payload with `worker_id`, `shifts`, and optional `include_unconfirmed`; returns validated shifts, flags, conflicts, commute-not-assessed entries, and weekly summaries. |

The extraction endpoint validates file extensions, file signatures, and the **20 MB** upload limit. A successful HTTP response alone does not mean extraction succeeded: inspect `extraction_status`, `succeeded`, `manual_entry_required`, and `shifts`.

### AI extraction behaviour

- **Primary provider:** Gemini (`GEMINI_API_KEY`); **optional fallback:** NVIDIA (`NVIDIA_API_KEY`). Provider and model settings are configurable in `ExtractionServiceConfig.from_env()`.
- The current prompt asks the model to identify **all visible shifts**. Parsed output is then checked for worker attribution: confidently unrelated workers are filtered, while ambiguous attribution is held for human review.
- Unknown financial details remain missing (`null`), not invented; an **explicit** zero-minute break is kept as `0`.
- The API preserves review requirements on every AI shift (`needs_review`, `requires_individual_review=true`, `eligible_for_bulk_confirmation=false`).
- A failed or partial extraction must be handled as such; the worker may need to enter missing shifts manually.
- `high`, `medium`, and `low` AI confidence are qualitative review indicators. The frontend does **not** map these to made-up numeric confidence values. The backend's legacy numeric FL06 threshold remains separate.

Read [AI extraction documentation](ai_extraction/README.md) for provider defaults, retries, configuration, benchmarks, and failure classification.

## Earnings and validation rules

- **Pay week:** Monday through Sunday. An overnight shift belongs to the date and week on which it starts.
- **Eligible earnings:** A shift must be confirmed, valid, non-duplicate, not cancelled/rejected, and have the necessary break, rate, and currency information.
- **Minutes and money:** Paid time is based on exact shift minutes minus unpaid break minutes. Intermediate calculations retain precision; displayed hours and monetary amounts are rounded to two decimals, with the weekly gross total aggregated and then rounded.
- **Incomplete is not zero:** Missing break, rate, or currency prevents earnings from being counted until resolved. An explicitly recorded zero break is valid; a blank break is not assumed to be zero.
- **No counted shifts:** Display **“Not counted yet”** when shifts are pending/incomplete, rather than presenting an artificial zero. A genuinely all-cancelled week can be `$0.00`.
- **Currencies:** Weekly totals remain separate by currency; no FX conversion or mixing of currencies.
- **Overlaps and duplicates:** Overlapping distinct shifts are flagged. A duplicate copy is held for review and never double-counted; rejected duplicates do not continue blocking the retained copy.
- **Commute check:** A gap of less than **30 minutes** between different known locations triggers a heuristic warning, **not** a calculated route duration. Missing/unknown locations are reported as not assessed.
- **Defaults:** Maximum shift duration is 16 hours. Overtime calculations are **disabled** for this MVP; the app does not calculate taxes, deductions, statutory entitlements, or actual payroll.

Rules are loaded from [`backend/app/config/pay_rules.csv`](backend/app/config/pay_rules.csv); the [product specification](docs/product_mvp_spec.md) and [validation module](data_validation/) provide the detailed contract and fixtures.

### Known-answer example

Three shifts at $16/hour include Monday (09:00–17:00, 30-minute unpaid break), Tuesday (10:00–18:00, 60-minute unpaid break), and Wednesday (09:00–17:00, missing break). If Monday and Tuesday are valid and confirmed, the eligible total is **14.5 hours and $232.00**, while Wednesday remains **incomplete** until the break is supplied or explicitly confirmed as zero.

This example is distinct from the team's reported synthetic cloud demonstration of **three extracted shifts, 24 eligible hours, and $384 estimated gross earnings**.

## Local development

### Prerequisites

- Python 3.12 is used by the project's Dockerfile; install a compatible Python environment locally.
- Node.js and npm compatible with the pinned frontend lockfile (`frontend/package-lock.json`).
- Provider API keys are **only** required for real AI extraction, not for ordinary calculation tests or CSV import.

From the repository root:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
~~~

In a **second terminal**:

~~~bash
cd frontend
npm ci
npm run dev
~~~

Open `http://localhost:5173`. The Vite development server proxies `/health` and `/api` to `http://127.0.0.1:8000`. Verify the backend at `http://127.0.0.1:8000/health`.

If using Windows PowerShell, activate the virtual environment with `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

### Configuration (do not commit secrets)

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Authenticates live Gemini extraction. |
| `NVIDIA_API_KEY` | Authenticates live NVIDIA fallback/extraction. |
| `AI_EXTRACTION_PRIMARY_PROVIDER` | `gemini` (default) or `nvidia`. |
| `AI_EXTRACTION_FALLBACK_ENABLED` | `true` (default) or `false`; disable for Gemini-only local testing. |
| `AI_EXTRACTION_FALLBACK_PROVIDER` | Selects fallback provider (`nvidia` by default). |
| `AI_EXTRACTION_PRIMARY_MODEL`, `AI_EXTRACTION_FALLBACK_MODEL` | Optional model overrides. |
| `AI_EXTRACTION_TIMEOUT_SECONDS`, `AI_EXTRACTION_TOTAL_DEADLINE_SECONDS` | Per-attempt and total extraction deadlines. |
| `WORKCLARITY_CORS_ORIGINS` | Comma-separated explicit browser origins allowed by the API; configure for hosted frontend origin. Wildcard `*` is rejected. |
| `VITE_API_BASE_URL` | **Build-time** frontend base URL for FastAPI. Leave unset for local Vite proxy; set appropriately when building for separate hosting. |

For advanced retry, processing, and empty-schedule settings, see [`ai_extraction/README.md`](ai_extraction/README.md). Never paste API keys into Slack, GitHub, screenshots, or demo recordings.

### Running tests

Start the FastAPI service on port **8000** in one terminal when running frontend live-backend tests.

~~~bash
# At repository root with virtual environment active:
python -m pytest backend/tests ai_extraction/tests data_validation/tests -q

# Frontend (separate terminal):
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
~~~

**Last team-reported verification for V1 fixes (`a48d241`):** 211 Python tests passed, 40 frontend tests passed, plus clean frontend lint and production build. These are local/test-environment results, not proof that authentication, persistence, or real-world production privacy requirements are complete.

## Validation quality: synthetic regression evidence

The [validation quality report](data_validation/docs/validation_quality_report.md) evaluates the rules on a **synthetic** dataset of 128 shift records: 33 with planted errors and 95 clean records.

- **33/33 planted errors were flagged and held out of earnings as initially delivered**, including the safeguard that unconfirmed shifts are not counted. **Only 25/33** were detected by shift-specific validation rules; the other eight were held by the general review/confirmation safeguards.
- **0/95 clean records received a missing, invalid, or duplicate flag** under the report's false-alarm definition.
- **Important limitation:** If a worker incorrectly confirms every planted error, **8 flawed shifts can enter earnings** because the rules cannot independently detect wrong dates, stale schedule updates, a plausible AM/PM mistake, or nonexistent shifts. Three further warning-only errors can count without affecting the stated pay calculation. Individual worker review remains essential.

These results measure the synthetic validation fixtures and business rules, **not** real-world detection rates or AI extraction accuracy.

## Extraction benchmarks: interpret carefully

The frozen **PR #14** six-document synthetic unseen set contains **28 expected target-worker shifts**. Independent provider runs using the **earlier frozen extraction prompt** reported:

| Metric | Gemini | NVIDIA |
| --- | ---: | ---: |
| Expected shifts detected | 28/28 | 28/28 |
| Earnings-critical field accuracy | 100% | 96.4% |
| All-field accuracy | 93.6% | 81.1% |

Both reported zero invented shifts in that historical evaluation. These are **synthetic benchmark figures**, not general real-world accuracy guarantees and **not** a remeasurement of the revised V1 worker-identification prompt. Two image headers in samples 5 and 6 are **ambiguous by design** (department versus location); the frozen answer key was not changed after seeing the results. Header interpretation and worker attribution remain areas to evaluate. The optional comparator's attribution-aware mode was added in the V1 fix branch; historical benchmark files were left unchanged. **Rerun/approve the revised-prompt benchmark before using new accuracy claims in the demo.**

## Deployment and production-readiness limits

- The repository includes a Firebase Hosting SPA configuration and a Python Cloud Run-compatible Dockerfile. Hosting the frontend does **not** itself mean the API is reachable; the frontend build must point at the correct API origin, and CORS must allow the deployed frontend.
- **No application login/authenticated worker ownership is implemented in the inspected V1 frontend/API flow.** The selectable workers are demo profiles, not authenticated user accounts.
- The inspected frontend persists schedules, edits, and confirmation decisions in **browser `localStorage`**. Do **not** claim Firestore persistence, Cloud Storage retention, or cross-device synchronisation as implemented V1 features merely because they were architectural goals. A Firestore database appearing as provisioned on the team deployment board does **not** establish that V1 is using it; Nandila should confirm the deployed backend wiring before making any persistence claim.
- AI uploads may send schedule content to configured third-party model providers and incur usage charges. Provider approval, privacy disclosures, secure credentials, access controls, and data-retention decisions must be completed before handling real worker data.
- No tax, deduction, overtime-pay, currency conversion, payroll disbursement, or verified travel-time calculations are implemented.
- The separate `design/v1-ui-polish` redesign requires review and merging before it can be described as the deployed UI.

## Repository guide

| Path | Purpose |
| --- | --- |
| [`frontend/`](frontend/) | React application, five screens, local state, API client, frontend tests. |
| [`backend/app/main.py`](backend/app/main.py) | FastAPI application, CORS and health route registration. |
| [`backend/app/api/shifts.py`](backend/app/api/shifts.py) | Extraction and calculation HTTP endpoints. |
| [`backend/app/services/shift_calculations.py`](backend/app/services/shift_calculations.py) | Authoritative deterministic validation and earnings engine. |
| [`backend/app/services/extraction_service.py`](backend/app/services/extraction_service.py) | Extraction API service, upload validation, orchestrator wiring. |
| [`ai_extraction/`](ai_extraction/) | Model adapters, prompts, PDF/image processing, safeguards, benchmark tools. |
| [`data_validation/`](data_validation/) | Synthetic test data, expected results, and comparison tooling. |
| [`data_validation/docs/validation_quality_report.md`](data_validation/docs/validation_quality_report.md) | Synthetic planted-error detection, false-alarm results, and confirmation limitations. |
| [`docs/technical_architecture.md`](docs/technical_architecture.md) | V1 component responsibilities, data flow, API contracts and deployment boundaries. |
| [`docs/product_mvp_spec.md`](docs/product_mvp_spec.md) | Product requirements and acceptance rules. |
| [`Dockerfile`](Dockerfile) / [`firebase.json`](firebase.json) | Container and frontend hosting configuration. |

## Team

| Contributor | Focus |
| --- | --- |
| **Nandila Mulilalila** | Team lead, architecture, cloud deployment, and integration. |
| **Ololade Gbodogbe** | Validation, earnings rules, synthetic fixtures, and evaluation. |
| **Castro Mzizi** | Product/worker experience, frontend and AI-extraction integration, safeguards. |
| **Lavanya Sai Bandla** | Quality assurance, test verification, and cross-platform review. |

Created for the **Mentor Me Collective × Google Cloud Launchpad** hackathon. Target submission: **28 November 2026**.

> This README documents the V1 implementation in the `feature/workclarity-v1-mvp` branch, including its current functionality, verification evidence, and known limitations. It is not a certification of production readiness.
