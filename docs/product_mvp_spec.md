# WorkClarity — MVP Product Specification

**Project:** WorkClarity  
**Version:** 1.1 — Updated After Team Review  
**Target Delivery:** 28 November 2026  
**Document Owner:** Castro Mzizi — Product & Project

## 1. Product Overview

WorkClarity is a schedule-to-earnings assistant designed for hourly workers managing shifts across multiple employers.

Workers can upload schedules, review extracted shifts, correct mistakes, identify scheduling conflicts, and view estimated weekly gross earnings.

The product should be simple, transparent, accessible, and usable without technical knowledge.

**Core workflow:**

Upload Schedule → Extract Shifts → Review and Correct → Validate → Confirm → View Weekly Schedule and Estimated Gross Earnings

### Product Principles

- Workers retain control over their shift information.
- AI-extracted information must be reviewed before contributing to earnings.
- Earnings calculations must be deterministic, consistent, and explainable.
- Incomplete information must never be presented as a confirmed financial result.
- The frontend and backend must follow one agreed set of business rules.
- Reliability of the complete worker journey takes priority over additional features.

## 2. MVP Scope

### 2.1 Core MVP — Required

- CSV schedule upload.
- Structured shift extraction and normalisation.
- Worker review and correction of extracted shifts.
- Shift confirmation and rejection.
- Detection of overlapping shifts, possible duplicates, missing information, and insufficient commute gaps.
- Weekly schedule view.
- Estimated gross earnings per shift and per week.
- Separate earnings totals for different currencies.
- Persistent worker corrections and confirmation statuses.
- Clear validation warnings, errors, and incomplete earnings indicators.
- Integration between the frontend and the agreed backend validation and earnings service.

### 2.2 Conditional MVP Features

The following features are included in the intended product experience but are dependent on extraction reliability, integration readiness, and available development time:

- PDF schedule upload and extraction.
- Image schedule upload and extraction.
- NVIDIA-assisted extraction of unstructured schedule information.

**Priority decision:** CSV must work reliably from upload through earnings calculation before PDF and image support is considered complete.

PDF and image formats must not be represented as fully supported unless they have been successfully tested.

### 2.3 Excluded from MVP

- Monthly earnings reports.
- Tax and deduction calculations.
- Overtime calculations.
- Actual travel-time routing.
- Payroll processing.
- A separate correction-history screen.
- Advanced analytics and forecasting.

## 3. Worker Experience

### Screen 1 — Upload Schedule

The worker uploads a CSV schedule, or a supported PDF or image schedule where extraction functionality is available.

The system should:

- Accept supported file formats.
- Display clear errors for unsupported, corrupted, or unreadable files.
- Extract or normalise shifts into structured records.
- Mark newly extracted shifts as unconfirmed.
- Preserve original extracted information for comparison with worker corrections.
- Direct the worker to the review interface.

**Acceptance criterion:** A worker can upload a CSV schedule and proceed to review the extracted shifts without manually rebuilding the schedule.

PDF and image acceptance criteria apply only when those integrations are implemented.

### Screen 2 — Review and Edit Shifts

The worker must be able to review and correct:

- Shift date.
- End date for overnight shifts.
- Employer.
- Start and end times.
- Unpaid break duration.
- Work location.
- Hourly rate.
- Currency.
- Shift and confirmation status.

The worker can confirm, reject, or leave a shift requiring review.

The system must preserve both the original extracted values and the worker-corrected values.

A confirmed shift containing unresolved errors or incomplete earnings information must remain visible in the review queue.

**Acceptance criterion:** Earnings calculations use validated, worker-confirmed values rather than unreviewed extracted information.

### Screen 3 — Resolve Warnings

The system should identify:

- Overlapping shifts.
- Possible duplicate shifts.
- Insufficient gaps between shifts at different locations.
- Missing or invalid information.
- Cancelled or unworked shifts.
- Shifts requiring worker confirmation.

#### Commute Gap Rule

A gap of less than 30 minutes between shifts at different locations triggers a warning.

This is a scheduling heuristic, not a verified travel-time estimate.

If location information is missing, commute feasibility is marked **Not assessed**, rather than passed.

#### Duplicate Handling

Possible duplicate shifts must be held for review to prevent double counting.

If a worker rejects one duplicate, the retained shift should become eligible for calculation, provided it satisfies all other confirmation and validation requirements.

#### Missing Breaks

An unknown break duration must not automatically be treated as zero.

The worker must confirm a zero-minute break or provide the actual break duration before earnings can be calculated.

**Acceptance criterion:** Workers can identify which shifts require attention and understand why earnings are excluded or incomplete.

### Screen 4 — Weekly Schedule

Display shifts grouped by day, with the reporting week starting on Monday.

Each shift should show:

- Date and time.
- Employer and location.
- Confirmation status.
- Warnings or errors.
- Estimated earnings where available.

Overnight shifts must support an explicit end date.

For reporting purposes, overnight shifts belong to the week in which they begin.

The Monday reporting week is a WorkClarity product default, not a universal payroll rule.

**Acceptance criterion:** Workers can identify their scheduled shifts, confirmed work, and outstanding issues for the selected week.

### Screen 5 — Weekly Earnings

Display:

- Total eligible paid hours.
- Estimated gross earnings.
- Per-shift earnings.
- Weekly totals by currency.
- Incomplete earnings indicators.
- Reasons why shifts were excluded or could not be calculated.

#### Calculation Rules

**Paid minutes = Shift duration in minutes − Unpaid break minutes**

**Estimated gross earnings = (Paid minutes ÷ 60) × Confirmed hourly rate**

Use exact minutes for calculations.

Do not round intermediate paid hours before calculating earnings.

Round final monetary amounts to two decimal places.

Displayed per-shift monetary amounts must not introduce cumulative rounding errors into weekly totals.

No overtime, taxes, or deductions are calculated in the MVP.

#### Weeks With No Counted Shifts

When shifts exist but none can be counted because confirmation or required information is outstanding, display:

**Not counted yet**

Do not present 0.00 as a final earnings result in this situation.

A genuine zero-earnings week must remain distinguishable from an incomplete week.

**Acceptance criterion:** Only eligible, validated, confirmed shifts contribute to estimated gross earnings, and incomplete totals are clearly identified.

## 4. Confirmation and Earnings Rules

| Status or Condition | Expected Behaviour |
|---|---|
| Unconfirmed | Excluded from earnings |
| Needs review | Excluded until resolved and confirmed |
| Confirmed | Eligible if valid and complete |
| Rejected | Excluded from active schedule and earnings; retained for traceability |
| Cancelled/unworked | Excluded from earnings |
| Missing hourly rate | Warning with incomplete earnings; shift remains visible |
| Missing currency | Earnings incomplete; no unsupported monetary total |
| Missing break | Earnings incomplete until break duration is confirmed |
| Invalid date | Blocking error |
| Invalid duration | Blocking error |
| Invalid break duration | Blocking error |
| Missing employer | Warning, not automatically blocking |
| Missing location | Warning; commute feasibility not assessed |
| Possible duplicate | Held for review to prevent double counting |
| Rejected duplicate | Retained valid copy may become eligible |
| Shift exceeding 16 hours | Invalid for MVP |
| Commute gap under 30 minutes | Scheduling warning, not verified travel time |

The 16-hour maximum shift duration may become configurable in a future release.

Validation status and earnings completeness must remain distinguishable. A shift may be structurally valid while its earnings are incomplete.

## 5. Backend and Frontend Data Requirements

The frontend requires access to:

- Worker identifier.
- Reporting-week identifier.
- Unique shift identifier.
- Shift start date.
- Shift end date for overnight shifts.
- Employer and location.
- Start and end times.
- Unpaid break duration.
- Original extracted values.
- Worker-corrected values.
- Confirmation status.
- Shift status.
- Validation flags and error messages.
- Earnings eligibility.
- Paid minutes or paid hours.
- Hourly rate and currency.
- Estimated gross earnings.
- Weekly totals.
- Earnings completeness indicators.
- Exclusion or incomplete reasons.
- Commute feasibility assessment status.

### 5.1 Single Source of Truth

The backend must remain the authoritative source for validation and earnings calculations.

The existing Newly prototype may be retained as the frontend.

However, Newly's independent earnings calculations must not remain a competing source of business logic after integration.

The agreed target architecture is:

- **Frontend:** Existing Newly prototype, adapted as required.
- **Backend:** FastAPI service on Google Cloud.
- **Validation and earnings:** Existing Python calculation module.
- **Persistence:** Firestore.
- **File storage:** Google Cloud Storage, where required.
- **AI extraction:** NVIDIA-assisted extraction component for supported unstructured formats.

These are target integration requirements, not a claim that all components have already been deployed.

### 5.2 Persistence Requirements

The system must preserve:

- Original extracted shift information.
- Worker corrections.
- Confirmation and rejection decisions.
- Current validation status.
- Relevant earnings information.
- Identifiers needed to retrieve and update shifts.

Canonical field names, API responses, Firestore collections, and nesting must be finalised with Nandila.

## 6. Product Acceptance Test

### 6.1 Earnings Example

Example worker schedule:

| Day | Shift | Unpaid Break | Rate | Confirmation |
|---|---|---|---|---|
| Monday | 09:00–17:00 | 30 minutes | $16/hour | Confirmed |
| Tuesday | 10:00–18:00 | 60 minutes | $16/hour | Confirmed |
| Wednesday | 09:00–17:00 | Unknown | $16/hour | Held for review |

Expected result:

- Monday: 7.5 paid hours = $120.00.
- Tuesday: 7 paid hours = $112.00.
- Wednesday: Excluded pending break confirmation.
- **Weekly eligible paid hours: 14.5.**
- **Weekly estimated gross: $232.00.**
- Weekly earnings must indicate that the Wednesday shift remains incomplete.

Once the worker confirms Wednesday's break duration and the shift satisfies all other requirements, the system recalculates the weekly earnings.

### 6.2 Additional Acceptance Scenarios

**Scenario A — Duplicate shifts**

Two identical shifts are detected. The worker rejects one and confirms the other.

Expected: The retained valid shift contributes once to earnings.

**Scenario B — Missing hourly rate**

A worker confirms a shift without an hourly rate.

Expected: The shift remains visible with an incomplete earnings warning. No unsupported earnings amount is calculated.

**Scenario C — Overnight shift**

A worker has a shift starting before midnight and ending the following day.

Expected: The system uses the correct start and end dates, calculates the duration accurately, and assigns the shift to the week in which it begins.

**Scenario D — No eligible shifts**

A worker uploads a schedule but has not confirmed any shifts.

Expected: Weekly earnings display **Not counted yet**, rather than a misleading final total of 0.00.

**Scenario E — Earnings precision**

A shift includes paid minutes that produce fractional hours.

Expected: Earnings are calculated from exact minutes, with monetary rounding applied at the final calculation stage.

**Scenario F — Commute warning**

Two shifts at different locations have less than 30 minutes between them.

Expected: The system displays a scheduling warning without claiming to have calculated actual travel time.

**Scenario G — Corrected extraction**

The worker changes an incorrectly extracted shift time and confirms the correction.

Expected: The corrected value is used in calculations, the original value is preserved, and the updated information persists.

## 7. Definition of Done

The core MVP is ready when:

- CSV upload works end to end.
- Extracted shifts can be reviewed, edited, confirmed, and rejected.
- Original extracted information and worker corrections are preserved.
- Invalid and incomplete shifts are handled clearly.
- Scheduling conflicts and warnings are visible.
- Eligible paid hours and gross earnings are calculated correctly.
- Weekly schedule and earnings views are usable.
- Worker corrections and statuses persist.
- Frontend and backend use the agreed data contract.
- Earnings calculations use one authoritative backend implementation.
- Overnight shifts are handled correctly.
- Duplicate resolution prevents double counting.
- Incomplete earnings are not displayed as confirmed zero totals.
- The existing validator regression tests continue passing.
- Frontend/backend end-to-end tests pass.
- The team can demonstrate the complete worker journey.

PDF and image extraction must be separately verified against known-answer test files if implemented.

The existing validator tests do not replace full end-to-end testing.

## 8. Team Responsibilities

**Castro Mzizi — Product & Project**

Product requirements, worker experience, acceptance criteria, frontend review, product decisions, and demo alignment.

**Nandila Mulilalila — Team Lead / Architecture**

Backend, cloud architecture, API contracts, persistence, integration, and technical decisions.

**Ololade Gbodogbe — Data Validation and Earnings**

Synthetic data, validation rules, earnings calculations, regression tests, and implementation of agreed calculation changes.

**Lavanya Sai Bandla — Testing and Quality Assurance**

Regression verification, acceptance test coverage, integration testing, and end-to-end quality assurance.

## 9. Product Decisions and Remaining Implementation Items

### 9.1 Confirmed Product Decisions

The following decisions were established through PR #3 review:

1. **Upload priority:** CSV first; PDF and image extraction depend on reliability and development capacity.
2. **Missing hourly rate:** Warning with incomplete earnings, not a blocking scheduling error.
3. **Earnings rounding:** Calculate using exact minutes and round monetary amounts at the final stage.
4. **No eligible shifts:** Display **Not counted yet** when shifts await confirmation or required information.
5. **Duplicate handling:** Rejecting one duplicate must allow the retained valid shift to become eligible.
6. **Maximum shift duration:** Retain the 16-hour validation limit for the MVP.
7. **Backend and persistence:** Standardise data contracts, preserve original and corrected values, and support overnight end dates.
8. **Commute warnings:** The 30-minute rule is a scheduling heuristic, not a verified travel-time estimate.

### 9.2 Remaining Implementation Items

**Nandila**

- Finalise canonical backend fields and API responses.
- Confirm the minimum Firestore structure.
- Confirm Google Cloud deployment status.
- Confirm the NVIDIA integration approach.
- Establish how the Newly frontend connects to the FastAPI service.

**Ololade**

- Apply the agreed missing-rate behaviour.
- Fix rejected-duplicate handling.
- Implement exact-minute earnings calculations.
- Implement the no-counted-shifts earnings behaviour.
- Extend regression tests for these decisions.

**Castro**

- Review the Newly screens against this specification.
- Identify missing or inconsistent worker interactions.
- Confirm that the final interface follows the agreed product rules.
- Support integration review and demonstration planning.

**Lavanya**

- Verify that the agreed product rules have test coverage.
- Continue validator regression testing.
- Test the connected frontend and backend.
- Record and verify end-to-end issues.

### 9.3 Integration Priority

The immediate priority is a reliable end-to-end worker journey:

**CSV Upload → Shift Review → Worker Correction → Confirmation → Backend Validation → Weekly Earnings**

The team should avoid maintaining separate calculation implementations.

Additional extraction formats should not delay delivery of this core workflow.

## 10. Final Product Acceptance

This document defines the agreed product behaviour and acceptance criteria for WorkClarity's MVP.

It does not imply that all integration, deployment, or testing tasks have already been completed.

The MVP will be considered ready for demonstration when the complete worker journey works reliably, calculations match the agreed rules, and outstanding limitations are documented.

**Target submission: 28 November 2026.**
