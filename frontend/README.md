# WorkClarity Frontend

Schedule-to-earnings web application for hourly workers managing shifts across multiple employers. Built with React, TypeScript, Vite, Tailwind CSS, React Router, and Lucide icons.

## Architecture Principles

- **Backend as Single Source of Truth:** All shift validation, conflict/commute detection, exact-minute paid hour calculations, and weekly gross earnings totals are calculated exclusively by the WorkClarity FastAPI backend (`POST /api/v1/shifts/calculate`). The frontend never calculates payable earnings independently.
- **Worker Control & Traceability:** Newly uploaded CSV shifts start as `unconfirmed`. Original extracted values (`extracted`) and raw CSV rows (`source_line`) are preserved separately from worker-corrected values (`current`), with one-click reset to original values.
- **No Guessed Financial Data:** Blank breaks, hourly rates, and currencies are sent as `null` (never coerced to `0` or `"USD"`). Weeks with no eligible counted shifts display **"Not counted yet"** rather than `$0.00`, while all-cancelled weeks display genuine `$0.00`. Separate currencies are never combined.
- **Stale Response & Offline Safety:** Out-of-order API responses are ignored using `AbortController` and monotonic request IDs. When the backend is unreachable, stale totals are hidden behind an explicit error banner until recalculation succeeds.
- **Temporary Local Persistence:** Worker workspace state is stored temporarily in browser `localStorage` isolated per worker (`workclarity_dev_state_v1_<workerId>`) until cloud Firestore persistence is connected.

## Tech Stack

- React 19 + TypeScript
- Vite 8 + `@tailwindcss/vite` (Tailwind CSS v4)
- React Router v7
- Lucide React
- Vitest + React Testing Library (`jsdom`)
- ESLint + TypeScript Project References

## Five Core Screens

1. **Upload Schedule (`/upload`):** Drag-and-drop or browse UTF-8 `.csv` schedules, validate CSV structure, download a CSV template, or load synthetic demonstration schedules. (PDF and image extraction remain conditional MVP features until backend extraction endpoints are available.)
2. **Review & Correct (`/review`):** Inspect extracted shifts, confirm `0`-minute breaks or supply missing break/rate/currency details, confirm or reject shifts, restore rejected shifts, view worker edits vs. original extracted values, and reset shifts to original values.
3. **Warnings & Conflicts (`/warnings`):** Resolve overlapping shifts, possible duplicates, short commute gaps (`< 30 min` scheduling heuristic), unassessed commute pairs (missing/unrecognized locations), and blocking validation errors.
4. **Weekly Schedule (`/schedule`):** Monday-to-Sunday weekly calendar view with overnight shifts assigned to the start date/week and optional traceability toggle for rejected shifts.
5. **Weekly Earnings (`/earnings`):** Authoritative per-currency weekly gross earnings cards, eligible vs. incomplete vs. pending hour breakdowns, rounding transparency, and per-shift earnings explanations.

## Local Setup & Running

### Prerequisites

- Node.js 20+ (verified on Node `v26.13.1`, npm `11.20.0`)
- Python 3.11+ (verified on Python `3.15.1`) with FastAPI backend dependencies installed

### 1. Start the FastAPI Backend

From the repository root (`WorkClarity/`):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### 2. Install & Start the Frontend

From `WorkClarity/frontend/`:

```bash
npm install
npm run dev
```

The frontend dev server runs at `http://localhost:5173`. By default, [vite.config.ts](./vite.config.ts) proxies `/health` and `/api` requests to `http://127.0.0.1:8000`.

### Environment Configuration

- `VITE_API_BASE_URL` (optional): Base URL for the FastAPI service when deploying or testing outside the Vite dev proxy (e.g., `VITE_API_BASE_URL=http://127.0.0.1:8000`). Leave unset in local dev to use the built-in Vite proxy. Do **not** commit `.env` files or credentials.

## Available Scripts

Run inside `WorkClarity/frontend/`:

- `npm run dev` — Start Vite development server on port `5173`
- `npm run build` — Type-check (`tsc -b`) and build production bundle into `dist/`
- `npm run lint` — Run ESLint across the codebase
- `npm test` — Run Vitest unit and live-backend E2E test suites (requires FastAPI backend running on `http://127.0.0.1:8000` for `src/test/e2e_backend.test.tsx`)
- `npm run test:watch` — Run Vitest in watch mode
- `npm run preview` — Preview the production build locally

## Testing & Verification

See [TEST_REPORT.md](./TEST_REPORT.md) for the complete Milestone 2 & 3 acceptance test report, dataset verification results, security audit findings, and backend observations.
