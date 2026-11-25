# WorkClarity V1 — Technical Architecture

**Source baseline:** `feature/workclarity-v1-mvp`, commit `a48d241`, inspected 25 November 2026. This is an architecture description for a hackathon MVP, not a security certification or production deployment audit. For user-facing project information, see the [root README](../README.md).

## Components and responsibilities

| Component | Source | Responsibility |
| --- | --- | --- |
| React frontend | `frontend/src/` | CSV import, upload of unstructured schedules, worker corrections and status, weekly schedule, warnings, and earnings presentation. |
| Frontend state | `frontend/src/context/ScheduleContext.tsx` | Worker-specific demo state; browser `localStorage`; recalculation requests; stale-response safeguards; status transitions. |
| API client | `frontend/src/api/shiftsApi.ts` | `GET /health`; `POST /api/v1/shifts/extract` (multipart); `POST /api/v1/shifts/calculate` (JSON). |
| FastAPI app | `backend/app/main.py` | App setup, `/health`, CORS origin allowlist, route registration. |
| Shift routes | `backend/app/api/shifts.py` | Extract and calculate endpoints and server configuration. |
| AI orchestration | `ai_extraction/orchestrator.py` | Provider selection, retries, conditional failover, partial results and telemetry. |
| AI normalization | `ai_extraction/schema.py`, `ai_extraction/prompt.py` | Structured shift normalization, uncertainty and worker attribution, individual-review requirement. |
| Backend calculations | `backend/app/services/shift_calculations.py` | Validation, overlap/commute flags, duplicate handling, minute-accurate paid hours, separate-currency gross totals. |
| Deployment configuration | `Dockerfile`, `firebase.json` | Cloud Run-compatible container and Firebase-hosted SPA configuration. Neither file proves the production resource's current state. |

## Actual API interface

### Health

`GET /health` returns health, service name and version; it does not prove AI-provider availability.

### Document extraction

`POST /api/v1/shifts/extract` expects a multipart request with `file` and optional `target_worker`. The server validates nonempty file bytes, extension and signature and enforces a **20 MiB** upload limit; supported extensions are `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`. The response includes extraction status, whether it succeeded/was partial/failed, provider information, reviewable shift records and whether manual entry is required.

The prompt requests all visible shifts, while postprocessing discards unambiguously unrelated workers and holds ambiguous attribution for verification. Every AI-extracted shift is `needs_review`, requires **individual confirmation**, and is not bulk-confirmable. Model-derived values are not directly accepted as earnings.

Providers are Gemini primary and NVIDIA fallback **by default**, contingent on credentials, configuration, vendor availability, consent and approval. Failure, incomplete extraction and empty-schedule states are not all equivalent and must be handled separately. See [AI extraction README](../ai_extraction/README.md) for environment variables and fallback policy.

### Validation and earnings

`POST /api/v1/shifts/calculate` expects JSON with `worker_id`, `shifts` and optional `include_unconfirmed`. The backend returns checked shifts, flags, conflicts, `commute_not_assessed`, and weekly summaries.

- Pay week begins Monday; overnight shift is assigned to its start date/week.
- Shift paid time is computed from exact minutes minus an explicitly recorded unpaid break.
- Monetary values use Decimal and exact internal shift earnings; the weekly total is rounded after summing exact eligible earnings, not by summing the separately displayed rounded shift amounts.
- Only eligible confirmed shifts count. Rejected/cancelled shifts never create payable earnings, and duplicates are held until reviewed.
- Missing break, rate or currency are incomplete; `null` must not be silently converted into `0`.
- Weekly totals are kept per currency without conversion. A pending/incomplete-only week is "Not counted yet"; a genuinely cancelled-only week may show a zero total.
- A gap below 30 minutes between distinct, known locations is a scheduling warning, **not a route-time calculation**.
- Overtime-pay, taxes, deductions, statutory payroll and real transfer times are not calculated.

## Persistence and security boundaries

The inspected frontend uses per-demo-worker **browser `localStorage`** keys (`workclarity_dev_state_v1_<workerId>`) and a local worker selector. It does **not** implement authenticated users or server-enforced tenant separation. Do not document Cloud Firestore or Cloud Storage as live application persistence merely because they appear in design discussions. A Firestore instance listed on the deployment board may be provisioned but is **not evidence of application persistence**; confirm actual deployed storage reads/writes with Nandila before claiming integration.

PDF/images sent to the API can be transmitted to configured third-party providers. Before use with real worker data, establish authorization, privacy disclosures, provider agreements, retention rules, access boundaries, secure key handling, abuse/rate limiting and cloud budget controls. Avoid live paid uploads without team lead approval.

## Runtime, deployment and settings

- Python runtime dependencies in `requirements.txt` include FastAPI, Uvicorn, `python-multipart`, `pypdfium2` and Pillow.
- Frontend runs on Vite locally at port 5173; Vite proxies `/api` and `/health` to FastAPI at port 8000.
- Cloud Run-compatible Dockerfile runs Uvicorn on `${PORT:-8080}`; Firebase config hosts `frontend/dist` with SPA fallback rewrite.
- `VITE_API_BASE_URL` is set **at frontend build time** for a separately hosted API.
- `WORKCLARITY_CORS_ORIGINS` configures an explicit backend CORS allowlist; wildcard origins are removed.
- `GEMINI_API_KEY` and `NVIDIA_API_KEY` are backend secrets; no secret should be included in the repository, output screenshots or recordings.
- The team reports a successful deployed synthetic flow at [workclarity.web.app](https://workclarity.web.app), but that result must not be conflated with full production-readiness verification.

## Test and benchmark evidence

- **Team-reported V1 verification:** 211 Python tests, 40 frontend tests passing on commit `a48d241`. No new tests were executed as part of this documentation update.
- **Team-reported deployed QA (25 November):** Ololade reported that seven synthetic demo scenarios (specification example, overnight, commute gap, overlap, duplicates/cancellations, multi-currency, missing details) matched the corresponding local results. This is smoke-test evidence, not a security audit.
- **Historical independent synthetic unseen benchmark (previous extraction prompt):** 28 of 28 target shifts detected by each provider; Gemini 100% earnings-critical and 93.6% all-field accuracy; NVIDIA 96.4% earnings-critical and 81.1% all-field accuracy. Two image headers in the synthetic unseen set were ambiguous by design; the frozen answer key was preserved.
- **Important boundary:** the revised all-shifts extraction prompt has not been independently rebenchmarked against these samples in the evidence inspected. Do not present historical results as the deployed-prompt accuracy.
- **Confidence indicator:** qualitative AI confidence is review UI metadata; the backend's numeric FL06 logic is separate and is not fed an arbitrary text-to-number mapping.
- **Previous frontend report:** `frontend/TEST_REPORT.md` records the 19 November baseline; its earlier "missing CORS", "duplicate/overlap double reporting" and non-finite value concerns are no longer current in the V1 source. Retain the historical observations as a dated audit record.

### Synthetic validation quality and human review

The [validation quality report](../data_validation/docs/validation_quality_report.md) records 33/33 planted errors held initially, with 25/33 recognised by specific validation rules and 0/95 false alarms on clean records under the report's definition. **Eight plausible errors would enter earnings if a worker confirmed them without noticing** (with three additional warning-only cases also able to count). This demonstrates why worker confirmation is a safeguard and why it does **not** guarantee that confirmed data is correct. These are synthetic fixtures, not estimates of field performance.

## Out of scope / open work

Authentication, authorization and tenant isolation, reliable cloud persistence and cross-device state, worker-data protection and retention, deployment integration hardening, audited cost controls, provider approvals, a fresh revised-prompt benchmark, and production operational monitoring are not established as completed V1 features by the inspected source.
