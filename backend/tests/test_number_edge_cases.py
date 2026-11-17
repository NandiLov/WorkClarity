"""Numbers that are not usable amounts must be flagged, never crash the service.

Found while reviewing the front end (PR 9): a rate or break written as NaN or Infinity made the endpoint
return a 500 error, so the worker saw "service unavailable" instead of a flag to fix.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

GOOD = {
    "shift_id": "GOOD", "employer_name": "BrightMart", "location": "Store A",
    "shift_date": "2026-11-03", "start_time": "08:00", "end_time": "16:00", "break_minutes": 30,
    "hourly_rate": "15", "currency": "USD", "shift_status": "scheduled", "confirmation_status": "confirmed",
}


def calculate(**overrides):
    bad = {**GOOD, "shift_id": "BAD", "shift_date": "2026-11-04", **overrides}
    response = client.post("/api/v1/shifts/calculate", json={"worker_id": "W1", "shifts": [GOOD, bad]})
    assert response.status_code == 200, response.text
    return {s["shift_id"]: s for s in response.json()["shifts"]}, response.json()


@pytest.mark.parametrize("rate", ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "1e400", "1e30", "-5", "abc"])
def test_a_rate_that_is_not_a_usable_amount_is_flagged_as_missing(rate):
    shifts, _ = calculate(hourly_rate=rate)
    assert [f["code"] for f in shifts["BAD"]["flags"] if f["code"] == "MISSING_RATE"] == ["MISSING_RATE"]
    assert shifts["BAD"]["gross_earnings"] is None and shifts["BAD"]["earnings_status"] == "incomplete"


@pytest.mark.parametrize("brk", ["NaN", "Infinity", "-Infinity", "1e999", "-30", "abc"])
def test_a_break_that_is_not_a_usable_number_is_flagged_as_invalid(brk):
    shifts, _ = calculate(break_minutes=brk)
    assert "INVALID_BREAK" in [f["code"] for f in shifts["BAD"]["flags"]]
    assert shifts["BAD"]["gross_earnings"] is None and shifts["BAD"]["earnings_status"] == "excluded"


def test_one_bad_number_does_not_stop_the_other_shifts_from_counting():
    shifts, body = calculate(hourly_rate="Infinity", break_minutes="NaN")
    assert shifts["GOOD"]["earnings_status"] == "counted" and shifts["GOOD"]["gross_earnings"] == 112.5
    week = body["weekly_summary"][0]
    assert week["gross_earnings"] == 112.5 and week["earnings_incomplete"] is True


def test_a_normal_high_rate_still_counts():
    shifts, _ = calculate(hourly_rate="250000")
    assert shifts["BAD"]["earnings_status"] == "counted"
