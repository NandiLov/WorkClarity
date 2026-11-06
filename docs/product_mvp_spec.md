# WorkClarity — MVP Product Specification

**Project:** WorkClarity   
**Version:** 1.0 — Draft for Team Review  
**Target delivery:** 28 November 2026

## 1. Product Overview

WorkClarity is a schedule-to-earnings assistant for hourly workers.

Workers can upload their work schedules, review AI-extracted shifts, correct mistakes, identify scheduling conflicts, and see estimated gross earnings for the week.

The product should be simple, transparent, and usable without technical knowledge.

**Core workflow:**

Upload schedule → Extract shifts → Review and correct → Validate → Confirm → View weekly schedule and estimated gross earnings.

## 2. MVP Scope

### Included

- CSV schedule upload.
- PDF schedule upload.
- AI-assisted extraction and normalization.
- Worker review and correction of extracted shifts.
- Shift confirmation and rejection.
- Detection of overlaps, possible duplicates, missing information, and insufficient commute gaps.
- Weekly calendar or schedule view.
- Estimated gross earnings per shift and per week.
- Separate earnings totals for different currencies.
- Saved corrections and confirmation statuses.

### Excluded from MVP

- Image schedule uploads.
- Monthly earnings reports.
- Tax and deduction calculations.
- Overtime calculations.
- Actual travel-time routing.
- Payroll processing.
- A separate correction-history screen.

## 3. Worker Experience

### Screen 1 — Upload Schedule

The worker uploads a CSV or PDF schedule.

The system should:

- Accept supported files.
- Show a clear error for unsupported or unreadable files.
- Extract shifts into structured records.
- Mark extracted shifts as unconfirmed.
- Preserve original extracted information for comparison.

**Acceptance criterion:** The worker can upload a supported schedule and proceed to review extracted shifts.

### Screen 2 — Review and Edit Shifts

The worker can see and edit:

- Shift date.
- Employer.
- Start and end times.
- Unpaid break duration.
- Work location.
- Hourly rate and currency.
- Shift status.

The worker can confirm, reject, or leave a shift requiring review.

The original extracted values should remain available alongside worker corrections.

**Acceptance criterion:** Calculations use validated, worker-confirmed corrected values, not unreviewed AI extraction.

### Screen 3 — Resolve Warnings

The system should identify:

- Overlapping shifts.
- Possible duplicate shifts.
- Insufficient gaps between shifts at different locations.
- Missing or invalid information.
- Cancelled or unworked shifts.
- Shifts requiring worker confirmation.

A commute gap of less than 30 minutes between different locations triggers a warning. This is a product heuristic, not a real travel-time estimate.

If location information is missing, commute feasibility is **not assessed**, rather than marked as passed.

Missing or unknown break duration must be confirmed before earnings are finalized.

Possible duplicates must be resolved before they can contribute twice to earnings.

**Acceptance criterion:** The worker understands what needs attention and which shifts are excluded or incomplete.

### Screen 4 — Weekly Schedule

Display shifts grouped by day, with the week starting on Monday.

Each shift should show:

- Date and time.
- Employer and location.
- Confirmation status.
- Warnings or errors.
- Estimated earnings where available.

Overnight shifts belong to the reporting week in which they begin.

The Monday reporting week is a WorkClarity product default, not a universal payroll rule.

**Acceptance criterion:** Workers can identify their shifts and unresolved issues for the selected week.

### Screen 5 — Weekly Earnings

Show:

- Total eligible paid hours.
- Estimated gross earnings.
- Per-shift earnings.
- Weekly totals by currency.
- Incomplete earnings indicators.
- Reasons why shifts were excluded or earnings could not be calculated.

The formula is:

**Paid hours = Shift duration − Unpaid break duration**

**Estimated gross earnings = Paid hours × Confirmed hourly rate**

Round monetary amounts to two decimal places.

Do not calculate overtime, taxes, or deductions in the MVP.

**Acceptance criterion:** Only eligible, validated, confirmed shifts contribute to estimated gross earnings.

## 4. Confirmation and Earnings Rules

| Status | Expected behavior |
|---|---|
| Unconfirmed | Excluded from earnings |
| Needs review | Excluded until resolved and confirmed |
| Confirmed | Eligible if valid and complete |
| Rejected | Excluded from active schedule and earnings, retained for traceability |
| Cancelled/unworked | Excluded from earnings |
| Missing rate or currency | Earnings marked incomplete |
| Invalid date, duration or break | Blocking error |
| Missing employer or location | Warning, not automatically blocking |
| Unresolved possible duplicate | Held for review to prevent double counting |
| Missing break | Worker confirms zero break or provides duration before earnings are finalized |

## 5. Backend and Frontend Data Requirements

The frontend needs access to:

- Worker and reporting-week identifiers.
- Shift identifiers and dates.
- Employer, location, start/end times and breaks.
- Original extracted values.
- Worker-corrected values.
- Confirmation and shift statuses.
- Validation flags and errors.
- Earnings eligibility.
- Paid hours, hourly rate, currency and estimated gross earnings.
- Weekly totals and incomplete earnings indicators.
- Exclusion or incomplete reasons.
- Commute feasibility assessment status.

The backend remains the source of truth for calculations and validation.

Firestore collection names, nesting, and canonical field names are subject to Nandila's architecture and integration decisions.

## 6. Product Acceptance Test

Example worker schedule:

| Day | Shift | Unpaid break | Rate |
|---|---|---|---|
| Monday | 09:00–17:00 | 30 minutes | $16/hour |
| Tuesday | 10:00–18:00 | 60 minutes | $16/hour |
| Wednesday | 09:00–17:00 | Unknown | $16/hour |

Expected result:

- Monday: 7.5 paid hours = $120.00.
- Tuesday: 7 paid hours = $112.00.
- Wednesday: Held for break confirmation.
- **Weekly eligible paid hours: 14.5.**
- **Weekly estimated gross: $232.00.**

After the worker confirms Wednesday's break duration, the system recalculates earnings if the shift is otherwise valid and confirmed.

## 7. Definition of Done

The MVP is ready when:

- A worker can upload CSV and PDF schedules.
- Extracted shifts can be reviewed, edited, confirmed or rejected.
- Invalid and incomplete shifts are handled clearly.
- Scheduling conflicts and warnings are visible.
- Eligible paid hours and gross earnings are calculated correctly.
- Weekly schedule and earnings views are usable.
- Worker corrections and statuses persist.
- The frontend and backend use agreed data contracts.
- End-to-end tests pass.
- The team can demonstrate the complete workflow.

## 8. Team Responsibilities

**Castro Mzizi — Product & Project / AI Cloud Lead:** Product requirements, worker experience, acceptance criteria, product review and demo alignment.

**Nandila Mulilalila — Team Lead / Architecture:** Backend, cloud architecture, integration and technical decisions.

**Ololade Gbodogbe — Data Validation and Earnings:** Synthetic data, validation rules, earnings calculations and regression tests.

**Lavanya Sai Bandla — Testing:** Test coverage, regression verification and quality assurance.

## 9. Open Decisions

Before finalizing implementation:

1. Confirm canonical backend field names and frontend data contract.
2. Resolve missing-break and duplicate-earnings handling.
3. Confirm incomplete earnings behavior for missing currency.
4. Ensure review queues include confirmed shifts with unresolved blocking errors or incomplete earnings.
5. Agree on the simplest Firestore structure and frontend integration approach.

These decisions should be resolved collaboratively through the existing pull-request review process.
