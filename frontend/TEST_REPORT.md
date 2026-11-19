# WorkClarity Frontend — Test & Verification Report

**Branch:** `feature/react-frontend`  
**Base Main Commit:** `24c8e9c`  
**Backend Under Test:** FastAPI `0.162.5` + Uvicorn `0.54.0` (`http://127.0.0.1:8000`, unmodified)  
**Frontend Stack:** React `19.3.1`, Vite `8.3.6`, TypeScript `6.0.3`, Tailwind CSS `4.3.5`, Vitest `5.1.0`  
**Test Execution Date:** 2026-11-17

---

## 1. Build, Lint & Automated Test Summary

| Check | Command | Outcome | Details |
|---|---|---|---|
| ESLint | `npm run lint` (`eslint .`) | **PASS** | 0 errors, 0 warnings |
| TypeScript & Production Build | `npm run build` (`tsc -b && vite build`) | **PASS** | Type-checked `tsconfig.app.json`, `tsconfig.node.json`, `tsconfig.test.json`; built `dist/` in `684ms` |
| Frontend Unit & Integration Tests | `npm test` (`vitest run`) | **PASS (32 / 32)** | `src/test/milestone1.test.tsx` (9/9) + `src/test/e2e_backend.test.tsx` (23/23 against live FastAPI backend) |
| Live Browser Verification | Chromium (`http://localhost:5173`) | **PASS** | Zero console errors; HTTP 200 on `/health` and `/api/v1/shifts/calculate`; zero horizontal overflow at `375px`, `390px`, `768px`, and `1280px` |

---

## 2. End-to-End Acceptance Test Results (Against Live FastAPI Backend)

All dataset scenarios were verified directly against `data_validation/test_data/` fixtures (`truth_shifts.csv`, `expected_weekly_earnings.csv`, `expected_conflicts.csv`, and `schedule_inputs/*.csv`) via the real `POST /api/v1/shifts/calculate` endpoint.

| # | Scenario | Reference Dataset / Fixture | Expected Result | Actual Result | Status |
|---|---|---|---|---|---|
| 0 | Repository Answer-Key Parity | `truth_shifts.csv`, `expected_weekly_earnings.csv`, `expected_conflicts.csv` | All 32 weekly summary rows and 5 conflicts match backend output | All 32 weekly summary rows (`paid_hours`, `gross_earnings`, `incomplete_shifts`, `cancelled_shifts`) and all 5 conflicts matched | **PASS** |
| 1 | CSV File Upload | `schedule_inputs/S001_schedule.csv` | 3 shifts extracted as `unconfirmed`, serialized with `null` blanks, calculated via FastAPI | 3 shifts loaded as `unconfirmed`; confirming ready shifts yields `$384.00 (USD)` and `24 hrs` | **PASS** |
| 2 | Duplicate Detection & Rejection | `S009` duplicate shift (`WK-S009`) | Extra duplicate copy flagged `POSSIBLE_DUPLICATE` (`FL04`) and held; rejecting duplicate leaves `$315.00` | Duplicate held out of earnings; `"Reject Duplicate"` leaves retained shifts counted at `$315.00 (USD)` | **PASS** |
| 3 | Overlapping Shifts | `schedule_inputs/S004_schedule.csv` (`C001`, `WK-S004`) | Backend returns `overlap` (`FL01`) conflict; UI renders conflict without recalculating earnings locally | `"Overlapping Shifts (1)"` rendered with `$230.00 (USD)` and `16 hrs` preserved | **PASS** |
| 4 | Insufficient Commute Gaps | `schedule_inputs/S005_schedule.csv` (`C002`) | `commute_conflict` (`10 min gap`, `FL02`) shown with 30-min heuristic disclaimer | `"Short Travel Gaps Between Locations (1)"`, `"10 min gap"`, and heuristic disclaimer displayed | **PASS** |
| 5 | Missing & Unknown Locations | `S014` + `S030` (`Riverside Annex`, `WK-S030`) | `UNKNOWN_LOCATION` & `MISSING_LOCATION` warnings; commute marked `"Not assessed"`; `$258.75` counted | `"Commute Feasibility Not Assessed (1)"` shown; `$258.75 (USD)` and `17.25 hrs` counted | **PASS** |
| 6 | Overnight Shifts | `S001_schedule.csv`, `S011_schedule.csv` (`WK-S011`) | `22:00–06:00` marked Overnight; Sunday night `2026-11-08` assigned to Monday week `2026-11-02` (`$279.00`) | Overnight badge rendered; `S011` grouped in `Nov 2 – Nov 8, 2026` totaling `$279.00 (USD)` (`15.5 hrs`) | **PASS** |
| 7 | Cancelled Shifts | `schedule_inputs/S015_schedule.csv` (`WK-S015`) + all-cancelled week | 2 cancelled shifts at `$0.00`, `$371.25` total; all-cancelled week shows `$0.00` genuine zero | `$371.25 (USD)` (`22.5 hrs`); all-cancelled week renders `$0.00 (USD)` genuine zero notice | **PASS** |
| 8 | Missing Hourly Rates & Currencies | `S029` (`WK-S029`) + missing currency CSV | Missing rate yields `$337.50` + 1 incomplete (`7.5 hrs`); missing currency yields `"Not counted yet"` | `$337.50 (USD)` + `1 incomplete shift(s) (7.5 hrs)`; missing currency displays `"CURRENCY MISSING"` & `"Not counted yet"` | **PASS** |
| 9 | Multiple Currencies | `schedule_inputs/S028_schedule.csv` (`WK-S028-USD`, `WK-S028-EUR`) | Currencies remain strictly separated (`$202.50 USD` and `€180.00 EUR`) | Separate `USD` and `EUR` cards showing `$202.50 (USD)` and `€180.00 (EUR)` | **PASS** |
| 10 | Exact-Minute & Weekly Rounding | `S005_schedule.csv` (`WK-S005`) + two 1-min shifts at `$100/hr` | `4.83 hrs` → `$62.83` (`$250.33` week); two `$1.67` shifts → `$3.33` weekly total | `$62.83`, `17.33 hrs`, `$250.33 (USD)`; `$1.67` per shift and `$3.33 (USD)` weekly total | **PASS** |
| 11 | Explicit Zero-Minute Breaks | Spec §6.1 Wednesday blank break | Blank break excluded; `"Confirm 0 min break"` + confirm counts full 8h (`$360.00`) | Blank break held; `"Confirm 0 min break"` + confirm updates total to `$360.00 (USD)` (`22.5 hrs`) | **PASS** |
| 12 | Unconfirmed Shifts Excluded | `S001_schedule.csv` on initial upload | Newly uploaded `unconfirmed` shifts show `"Not counted yet"` | Overview and Earnings render `"Not counted yet"` until confirmed | **PASS** |
| 13 | Persistence After Browser Refresh | `W008` `S028_schedule.csv` across unmount/remount | Worker shifts and edits persist in `localStorage` and re-sync with backend | `$202.50 (USD)` and `€180.00 (EUR)` restored after unmount/remount | **PASS** |
| 14 | Worker Workspace Isolation | `W001` (`S001`) vs `W008` (`S028`) | Separate `localStorage` keys per worker without cross-leakage | `workclarity_dev_state_v1_W001` (`$384.00`) isolated from `W008` (`S028`) | **PASS** |
| 15 | Backend Disconnection & Recovery | Simulated network failure + `"Retry recalculation"` | Stale totals hidden during failure; restored cleanly upon retry | `"Calculation service unavailable"` shown, `$232.00` hidden, restored to `$232.00 (USD)` on retry | **PASS** |
| 16 | Stale API Response Protection | Delayed `$100.00` response after `$360.00` edit | Delayed earlier API response discarded via monotonic request ID & `AbortController` | `$360.00 (USD)` retained; stale `$100.00` never rendered | **PASS** |
| 17 | Original Value Preservation & Reset | Spec §6.1 (`30` min edit → `"Reset to original"`) | Edit moves total to `$352.00` (`22 hrs`) with diff; reset restores `(empty)` break, `unconfirmed`, `$232.00` | `$352.00 (USD)` (`22 hrs`), diff pill shown; `"Reset to original"` restores `$232.00 (USD)` (`14.5 hrs`) | **PASS** |
| 18 | Mobile & Desktop Responsiveness | `375×812`, `390×844`, `768×1024`, `1280×800` | Mobile bottom nav (`lg:hidden`), desktop sidebar (`hidden lg:flex`), collapsed technical IDs, zero horizontal overflow | Confirmed in Vitest and live browser (`scrollWidth <= innerWidth` on all viewports; `"Technical details"` collapsed) | **PASS** |
| 19 | Invalid Duration & Break Edge Cases | `S026` (`>16h`, `0h`) & `S027` (`-15`, `600` min) | `INVALID_DURATION` and `INVALID_BREAK` mark shifts `excluded` (`gross_earnings: null`) | All 4 invalid shifts returned `excluded` with exact backend codes | **PASS** |
| 20 | Multi-Employer Append & Cross-Employer Conflicts | `employer_a.csv` (`BrightMart`, `CityCare Hospital`) + `employer_b.csv` (`Diner Y Co`, `Central Cafe Group`) | Both schedules preserved with unique IDs; FastAPI detects cross-employer overlap and 15m commute gap; combined gross `$239.75` (`16.75 hrs`) | All 4 shifts preserved across 2 unique `schedule_id`s and 4 unique `shift_id`s; overlap + 15m commute conflict detected; `$239.75 (USD)` calculated | **PASS** |
| 21 | Duplicate Schedule Re-Import Protection | `S001_schedule.csv` imported twice in Append mode | 6 unique `shift_id`s; duplicates flagged `POSSIBLE_DUPLICATE`, blocked from bulk confirm, and held out of earnings (`$384.00`, not `$768.00`) | 6 unique `shift_id`s preserved; `Confirm All Valid Shifts (0)` disabled; earnings remained `$384.00 (USD)` even after single-shift confirm attempts | **PASS** |
| 22 | Explicit Replace Confirmation Warning | `S001_schedule.csv` replaced with `S004_schedule.csv` | Warning shown and upload disabled until confirmation checkbox is checked | Warning rendered, upload disabled until checked, then cleanly replaced `S001` with 3 `S004` shifts | **PASS** |
| 23 | Confirmation Integrity on Edit | Confirmed `$128.00` shift edited via `Save Changes`, then `Save & Confirm` | Editing details resets `confirmation_status` to `unconfirmed` (`Not counted yet`); `Save & Confirm` re-confirms (`$112.00`) while retaining `extracted` (`0`), `previous_current` (`30`), and `current` (`60`) | Modal warned & reset status to `unconfirmed`; earnings changed to `"Not counted yet"`; `Save & Confirm` restored `$112.00 (USD)` with all 3 break values preserved | **PASS** |
| 24 | Bulk Confirmation Safety | `S001_schedule.csv` with delayed validation & offline fault | `Confirm All Valid Shifts` disabled while validation pending, stale, or offline; enabled with exact count (`3`) once validated | Button remained disabled while pending and offline; enabled at `(3)` on valid backend response and showed `"Confirmed 3 validated shift(s) and updated earnings."` | **PASS** |
| 25 | CSV Quote, Header & Column-Count Robustness | Unclosed quotes, mid-field quotes, trailing chars, `hourly_rate` duplicate, `date`/`shift_date` alias collision, unquoted comma shift, repeated filenames | All malformed CSVs rejected (`ok: false`) without silent column corruption; repeated filenames get distinct IDs | All 6 malformed CSV cases returned explicit errors; repeated uploads generated distinct `schedule_id` and `shift_id` values | **PASS** |
| 26 | Overview vs. Sidebar Attention Count Parity & Stale Guard | `schedule_inputs/S005_schedule.csv` (1 commute gap + 3 unconfirmed shifts) | Overview distinguishes `1` scheduling & commute alert, `3` shifts requiring attention, and `4` total attention items matching sidebar/mobile badges; post-confirm shows `1` total (`1` alert + `0` flagged shifts); stale/offline states never show stale counts | Overview rendered `4 total attention items` (`1 scheduling & commute alert`, `3 shifts requiring attention`) matching nav badge `4`; post-confirm updated both to `1`; in-flight stale showed `—` and offline hid stale badge/cards | **PASS** |

---

## 3. Manual Browser Verification (Reported & Confirmed Live)

- **Spec §6.1 Acceptance Walkthrough:**
  - Initial state: `$232.00 (USD)` and `14.5 hrs` eligible paid hours.
  - Worker edit (Wednesday break changed to `30` minutes and confirmed): `$352.00 (USD)` and `22 hrs`.
  - `"Reset to original"`: restored blank break, `needs_review`/`unconfirmed` state, and `$232.00 (USD)` / `14.5 hrs`.
- **Responsive Viewport Checks (Live Chromium on `http://localhost:5173`):**
  - Desktop (`1280×800`): Deep navy sidebar with `Calculation Service: Connected`, overview cards, worker-friendly badges, and collapsed `"Technical details"` disclosure.
  - Tablet (`768×1024`), Mobile (`390×844`), Small Mobile (`375×812`): `scrollWidth <= innerWidth` confirmed across `/review` and `/earnings` with mobile bottom navigation.

---

## 4. Dependency Security Audit (`npm audit`)

Ran `npm audit` without applying breaking upgrades or `npm audit fix --force`:

- **Production runtime dependencies (`react`, `react-dom`, `react-router-dom`, `lucide-react`):** **0 vulnerabilities**
- **Development dependencies:** **7 moderate severity vulnerabilities** from a single transitive chain:
  - `minimatch` (`7.0.0 - 11.0.0`) — potential ReDoS via globparts amplification (`GHSA-g3hv-75wg-m249`), pulled in by `typescript-eslint` (`<=8.72.2`) and `@typescript-eslint/*` dev packages.
  - **0 high** and **0 critical** vulnerabilities.
  - `npm audit fix --force` was intentionally **not** executed because it would downgrade `typescript-eslint` to `8.36.0` (breaking change).

---

## 5. Backend Observations (Untouched)

Backend business logic and repository files outside `frontend/` were **not modified**. The following observations were noted for backend follow-up:

1. **Duplicate shifts also emit an `OVERLAP` (`FL01`) conflict** ([`backend/app/services/shift_calculations.py`](../backend/app/services/shift_calculations.py)): `_find_conflicts` excludes `cancelled` and `rejected` shifts, so a held duplicate (`needs_review` with `POSSIBLE_DUPLICATE`) still pairs with its original copy and emits an `overlap` conflict until one copy is rejected.
2. **No `CORSMiddleware` configured** ([`backend/app/main.py`](../backend/app/main.py)): direct browser requests from another origin fail CORS unless routed through the Vite dev proxy or a same-origin reverse proxy.
3. **Calculated shift payload omits display metadata** (`start_time`, `end_time`, `end_date`, `break_minutes`, `employer`, `location_text`), requiring the client to retain and merge calculated results by `shift_id`.
4. **Module docstring vs. implementation rounding wording** ([`backend/app/services/shift_calculations.py`](../backend/app/services/shift_calculations.py)): the docstring describes summing shift-rounded amounts, while the code (correctly, per `test_weekly_earnings_round_only_after_combining_exact_shift_earnings`) sums unrounded `_exact_gross_earnings` before rounding at the weekly total.
5. **`truth_shifts.csv` `S005-02` gross value on `main`:** `S005-02` in `data_validation/test_data/truth_shifts.csv` lists `62.79`, whereas the backend accurately calculates `$62.83` (`290 / 60 * 13`) and `$250.33` for `WK-S005`.
6. **Non-finite numeric string guard in `_to_decimal`:** strings like `"NaN"` or `"Infinity"` construct non-finite `Decimal` instances that pass `< 0` comparisons and can raise `InvalidOperation` during quantization.
