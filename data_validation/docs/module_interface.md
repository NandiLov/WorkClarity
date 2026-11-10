# Validation and earnings service: interface

The service is one Python file at `backend/app/services/shift_calculations.py`, agreed with Nandila. The backend calls `calculate_shifts(payload)` and gets back the results. It uses only the Python standard library and does no input or output of its own. The tests are in `data_validation/tests`.

## Input

One dictionary per worker:

```
{
  "worker_id": "W001",
  "shifts": [
    {
      "shift_id": "S1", "employer": "Acme", "date": "2026-11-09",
      "start_time": "09:00", "end_time": "17:00", "end_date": null,
      "break_minutes": 30, "hourly_rate": "16.50", "currency": "USD",
      "location_text": "Store A", "confirmation_status": "confirmed",
      "shift_status": "scheduled", "source_line": "the original csv row"
    }
  ],
  "rules": { "pay_week_start": "monday", "min_commute_gap_minutes": 30 },
  "known_locations": ["Store A", "Store B"]
}
```

`rules` and `known_locations` are optional. Without rules the defaults are a Monday week start and a 30 minute commute gap. Without `known_locations`, an unrecognised location is not flagged.

## Output

```
{
  "worker_id": "W001",
  "shifts": [
    {
      "shift_id": "S1", "date": "2026-11-09", "week_start": "2026-11-09",
      "paid_hours": 7.5, "hourly_rate": 16.5, "currency": "USD", "gross_earnings": 123.75,
      "validation_status": "valid",          valid, warning or invalid
      "earnings_status": "counted",          counted, incomplete, excluded, unconfirmed, needs_review, rejected or cancelled
      "eligible_for_earnings": true,
      "flags": [ { "code", "flag_type_id", "flag_name", "severity", "reason", "message" } ],
      "source_line": "the original csv row"
    }
  ],
  "weekly_summary": [
    { "week_start": "2026-11-09", "currency": "USD", "shifts": 1, "paid_hours": 7.5,
      "gross_earnings": 123.75, "incomplete_shifts": 0, "earnings_incomplete": false,
      "cancelled_shifts": 0 }
  ],
  "conflicts": [ overlaps and commute conflicts ],
  "commute_not_assessed": [ pairs where a location is missing or unknown ]
}
```

## Business rules built in

- Only valid, worker-confirmed shifts count towards final earnings (`eligible_for_earnings`).
- A missing employer or location is a warning and the shift still counts. A missing date is a blocking error.
- needs_review, rejected, unconfirmed and cancelled shifts are left out of final earnings. Rejected shifts are also left out of the schedule and conflicts.
- A confirmed shift with no rate, no break or no currency stays visible and is counted in `incomplete_shifts`. A missing break is never treated as zero: the worker confirms no break (0) or enters one first. With no currency, no total is produced.
- A possible duplicate is held for review and not counted, so the same shift never counts twice.
- For the review queue, use `earnings_status` of needs_review, unconfirmed, incomplete or excluded. That includes confirmed shifts that still have a missing rate or an error. Each flag carries a `reason` that explains why earnings are incomplete or excluded.
- Overtime is not applied. Weekly totals are kept per currency and never added together.
- An `end_date` later than the date makes an overnight shift exact. Without it, an end time earlier than the start time means the next day.

## Field names: interface and csv contract

The service accepts both sets of names, so nothing blocks integration. Nandila and Ololade still need to choose which one is the standard.

| Backend interface | csv contract column | Note |
| --- | --- | --- |
| shift_id | none | Added by the backend |
| employer | employer_name | Same meaning |
| date | shift_date | Same meaning |
| start_time, end_time | start_time, end_time | Same |
| end_date | none | Optional, not in the csv contract yet |
| break_minutes | break_minutes | Same |
| hourly_rate | hourly_rate | Same |
| currency | currency | Same |
| location_text | location | Same meaning. Castro asked to match the integration contract |
| confirmation_status | none | Set by the worker review step |
| shift_status | shift_status | Same |
| source_line | none | The original csv row, kept for traceability |
