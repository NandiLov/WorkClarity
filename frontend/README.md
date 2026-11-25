# WorkClarity Frontend

React/TypeScript worker-facing UI for importing schedules, checking the source data, resolving conflicts, and viewing estimated gross earnings. This file documents the **V1 code on `feature/workclarity-v1-mvp` at `a48d241` (25 November 2026)**, not the independent, unmerged UI redesign.

## Technology

- React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router 7, Lucide icons
- React context for shift state; browser `localStorage` for **temporary per-demo-worker** workspace data
- FastAPI for all authoritative validation, scheduling conflict checks, and gross earnings calculations
- Vitest, React Testing Library, and browser-like `jsdom` for frontend testing

The demo worker switcher **is not login or authorization**. Neither browser storage nor a successful hosted demo establishes Firestore persistence, cross-device synchronization, or production worker-data security.

## Working routes

| Route | Purpose |
| --- | --- |
| `/upload` | Accept one CSV, PDF, PNG, JPEG, or WebP schedule at a time; append to a workspace or confirm replacement; demo presets and CSV template. PDF/images require the extraction API and configured live AI provider(s). |
| `/review` | Review, edit, individually confirm or reject AI shifts, restore rejected shifts, compare extracted and corrected values; explicitly verify ambiguous worker attribution before confirming. |
| `/warnings` | Surface overlap, duplicate, missing/invalid information, short travel-gap and not-assessed commute conditions. |
| `/schedule` | Display Monday-to-Sunday shifts by week, including overnight shifts and their statuses. |
| `/earnings` | Display FastAPI-returned **estimated gross earnings**, separated by currency and by eligible/incomplete/pending status. |

### Safety and business rules

- CSV imports begin `unconfirmed`; AI extracted records begin `needs_review` and **always require individual worker confirmation** (not bulk confirmation).
- Missing breaks, rates and currencies are sent as `null`, not inferred as zero. Explicit zero-minute breaks are preserved.
- Editing an already confirmed shift invalidates its previous confirmation where appropriate and triggers recalculation.
- A worker must explicitly verify an uncertain or unnamed employee assignment before confirmation is allowed.
- The AI model does **not** calculate earnings; the frontend posts worker-reviewed shifts to `POST /api/v1/shifts/calculate` and renders authoritative results.
- Responses are guarded against stale requests. Offline/error states do not present stale totals as current.
- Qualitative AI confidence (`high`, `medium`, `low`) informs review UI and is not mapped to arbitrary numeric values for backend FL06.
- The commute warning is a **30-minute scheduling heuristic**, not map-based travel-time routing.

## Local development

From the repository root, first start FastAPI in one terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`; the API health endpoint is <http://127.0.0.1:8000/health>.

For PowerShell, replace venv activation with `.venv\Scripts\Activate.ps1`. Real AI extraction requires valid provider credentials in the backend environment; do not commit credentials or test against the deployed paid service without team approval.

### Frontend configuration

| Variable | Meaning |
| --- | --- |
| `VITE_API_BASE_URL` | Optional frontend **build-time** API base URL. Leave empty for the local Vite proxy. For separate frontend/API hosting, set to the API origin. |

The FastAPI service must allow the frontend's deployed origin through `WORKCLARITY_CORS_ORIGINS`; the backend disallows wildcard `*` origins.

### Scripts

Run from `frontend/`:

```bash
npm run lint
npm run build
npm test
```

`npm test` includes live-backend integration tests that need FastAPI on `127.0.0.1:8000`; UI-only tests can run without paid AI calls.

## Verification and known limits

- Latest team-reported verification for the V1 fixes: **211 Python tests passed, 40 frontend tests passed**, with frontend lint and build passing. These figures are **reported**, not a fresh independent run for this README change.
- [`TEST_REPORT.md`](TEST_REPORT.md) captures **historical frontend testing from 19 November**, including 33 tests and observations from an earlier branch. Its old remarks about missing CORS, duplicate-overlap detection and non-finite numbers have since been superseded by merged fixes and the inspected V1 code.
- The five-screen redesign on `design/v1-ui-polish` has been exercised separately but **must be reviewed and merged** before it is represented as deployed.
- State remains in browser `localStorage` for the inspected UI; real authentication, cloud persistence, data retention, tenant isolation and privacy approval are outside the V1 implementation.
- For the complete architecture and benchmark caveats, see [`../README.md`](../README.md) and [`../docs/technical_architecture.md`](../docs/technical_architecture.md).
