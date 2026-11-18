"""Numbers that are not usable amounts must be flagged, never crash the service.

Found while reviewing the front end (PR 9): a rate or break written as NaN or Infinity made the endpoint
return a 500 error, so the worker saw "service unavailable" instead of a flag to fix.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import shift_calculations as service

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


@pytest.mark.parametrize("rate", ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "-5", "abc"])
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


# ---- a rate above the accepted limit has its own flag and message (review points on PR 10) ----
@pytest.mark.parametrize("rate", ["1000000.01", "1e30", "1e400", "99999999"])
def test_a_rate_above_the_limit_gets_its_own_flag_and_message_not_missing(rate):
    shifts, _ = calculate(hourly_rate=rate)
    codes = [f["code"] for f in shifts["BAD"]["flags"]]
    assert "RATE_TOO_HIGH" in codes and "MISSING_RATE" not in codes
    assert shifts["BAD"]["gross_earnings"] is None and shifts["BAD"]["earnings_status"] == "incomplete"
    reason = next(f["reason"] for f in shifts["BAD"]["flags"] if f["code"] == "RATE_TOO_HIGH")
    assert "above the accepted limit of 1,000,000.00 USD" in reason and "Please check the rate" in reason
    assert "above the accepted limit" in shifts["BAD"]["earnings_reason"]


def test_a_rate_exactly_at_the_limit_still_counts():
    shifts, _ = calculate(hourly_rate="1000000")
    assert shifts["BAD"]["earnings_status"] == "counted"


def test_one_shift_over_the_limit_does_not_stop_the_others_counting():
    shifts, body = calculate(hourly_rate="5000000")
    assert shifts["GOOD"]["earnings_status"] == "counted" and shifts["GOOD"]["gross_earnings"] == 112.5
    assert body["weekly_summary"][0]["earnings_incomplete"] is True


def _run(rules, currency, rate):
    shift = {**GOOD, "shift_id": "X", "worker_id": "W1", "currency": currency, "hourly_rate": rate}
    return service.process_shifts([shift], rules=rules)["shifts"][0]


def test_the_limit_comes_from_the_rules_and_can_differ_per_currency():
    rules = {"max_hourly_rate": "1000000", "max_hourly_rate_NGN": "5000"}
    over = _run(rules, "NGN", "6000")
    assert over["status"] == "incomplete" and [i["code"] for i in over["issues"]] == ["RATE_TOO_HIGH"]
    assert "limit of 5,000.00 NGN" in over["issues"][0]["reason"]
    assert _run(rules, "NGN", "4000")["status"] == "counted"
    assert _run(rules, "USD", "6000")["status"] == "counted"     # USD keeps the default limit


def test_a_limit_that_is_not_a_usable_number_falls_back_to_the_default():
    for bad in ("abc", "NaN", "-5", "0", ""):
        assert _run({"max_hourly_rate": bad}, "USD", "1000000.01")["issues"][0]["code"] == "RATE_TOO_HIGH"
        assert _run({"max_hourly_rate": bad}, "USD", "50")["status"] == "counted"


def test_the_shipped_rules_files_hold_the_same_default_limit():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    backend_rules = service.load_rules(os.path.join(root, "backend", "app", "config", "pay_rules.csv"))
    test_rules = service.load_rules(os.path.join(root, "data_validation", "test_data", "pay_rules.csv"))
    assert backend_rules["max_hourly_rate"] == test_rules["max_hourly_rate"] == "1000000"
