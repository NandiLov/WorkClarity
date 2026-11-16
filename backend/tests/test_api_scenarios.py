"""API tests for the cases that matter most, sent through the real endpoint.

They protect the earnings behaviour agreed on PR 3 while the backend changes.
Run from the repository root:  python -m pytest backend/tests -q
The rules are never sent in these requests: the server's own defaults apply.
"""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)
URL = "/api/v1/shifts/calculate"


def shift(**changes):
    base = dict(
        shift_id="S1", employer_name="Acme", shift_date="2026-11-09", start_time="09:00",
        end_time="17:00", break_minutes=30, hourly_rate="16.50", currency="USD",
        location="Store A", confirmation_status="confirmed", shift_status="scheduled",
    )
    base.update(changes)
    return base


def post(shifts):
    response = client.post(URL, json={"worker_id": "W1", "shifts": shifts})
    assert response.status_code == 200
    return response.json()


def codes(item):
    return {flag["code"] for flag in item["flags"]}


def test_spec_acceptance_example_gives_14_5_hours_and_232():
    # Castro's acceptance example: Mon 8h with 30 min break, Tue 8h with 60 min break,
    # Wed with an unknown break, all at 16.00 per hour.
    out = post([
        shift(shift_id="M", shift_date="2026-11-09", break_minutes=30, hourly_rate="16"),
        shift(shift_id="T", shift_date="2026-11-10", start_time="10:00", end_time="18:00",
              break_minutes=60, hourly_rate="16"),
        shift(shift_id="W", shift_date="2026-11-11", break_minutes=None, hourly_rate="16"),
    ])
    week = out["weekly_summary"][0]
    assert week["paid_hours"] == 14.5 and week["gross_earnings"] == 232.0
    assert week["earnings_incomplete"] is True and week["incomplete_shifts"] == 1
    wednesday = next(s for s in out["shifts"] if s["shift_id"] == "W")
    assert wednesday["earnings_status"] == "incomplete" and wednesday["gross_earnings"] is None
    assert "MISSING_BREAK" in codes(wednesday)


def test_a_missing_break_is_not_treated_as_zero_minutes():
    out = post([shift(break_minutes=None)])
    item = out["shifts"][0]
    assert item["eligible_for_earnings"] is False and item["gross_earnings"] is None
    assert "MISSING_BREAK" in codes(item)


def test_a_confirmed_zero_break_counts_in_full():
    item = post([shift(break_minutes=0)])["shifts"][0]
    assert item["paid_hours"] == 8.0 and item["gross_earnings"] == 132.0


def test_a_possible_duplicate_is_held_and_not_counted_twice():
    out = post([shift(shift_id="A"), shift(shift_id="B")])
    first, second = out["shifts"]
    assert first["earnings_status"] == "counted"
    assert second["earnings_status"] == "needs_review" and second["gross_earnings"] is None
    assert "POSSIBLE_DUPLICATE" in codes(second)
    assert out["weekly_summary"][0]["gross_earnings"] == 123.75


def test_rejecting_a_duplicate_releases_the_retained_shift():
    out = post([shift(shift_id="A"), shift(shift_id="B", confirmation_status="rejected")])
    kept = next(s for s in out["shifts"] if s["shift_id"] == "A")
    assert kept["earnings_status"] == "counted" and kept["gross_earnings"] == 123.75
    assert "POSSIBLE_DUPLICATE" not in codes(kept)


def test_a_missing_currency_makes_earnings_incomplete_with_no_total():
    out = post([shift(currency=None)])
    item, week = out["shifts"][0], out["weekly_summary"][0]
    assert item["earnings_status"] == "incomplete" and item["gross_earnings"] is None
    assert "MISSING_CURRENCY" in codes(item)
    assert week["gross_earnings"] is None and week["earnings_incomplete"] is True


def test_a_missing_rate_is_a_warning_and_the_shift_is_not_counted():
    out = post([shift(hourly_rate=None)])
    item, week = out["shifts"][0], out["weekly_summary"][0]
    assert item["validation_status"] == "warning"
    assert item["earnings_status"] == "incomplete" and item["gross_earnings"] is None
    assert week["earnings_incomplete"] is True and week["gross_earnings"] is None


def test_earnings_use_exact_minutes_and_round_only_the_money():
    # 12:10 to 17:00 with no break is 4h50m. At 13.00 per hour that is 62.83 (not 62.79).
    item = post([shift(start_time="12:10", end_time="17:00", break_minutes=0, hourly_rate="13.00")])["shifts"][0]
    assert item["paid_hours"] == 4.83 and item["gross_earnings"] == 62.83


def test_a_week_with_only_unconfirmed_shifts_is_not_counted_yet_not_zero():
    week = post([shift(confirmation_status="unconfirmed")])["weekly_summary"][0]
    assert week["gross_earnings"] is None and week["earnings_incomplete"] is True


def test_a_week_where_every_shift_is_cancelled_is_a_real_zero():
    week = post([shift(shift_status="cancelled")])["weekly_summary"][0]
    assert week["gross_earnings"] == 0.0 and week["earnings_incomplete"] is False


def test_an_overnight_shift_with_an_end_date_is_counted_in_the_week_it_starts():
    item = post([shift(start_time="22:00", end_time="06:00", end_date="2026-11-10", break_minutes=0)])["shifts"][0]
    assert item["paid_hours"] == 8.0 and item["week_start"] == "2026-11-09"


def test_weekly_hours_separate_eligible_from_incomplete_and_waiting_hours():
    # Castro's review of PR 5: paid_hours is the hours behind gross_earnings, nothing else.
    out = post([
        shift(shift_id="A", shift_date="2026-11-09", hourly_rate="16"),
        shift(shift_id="B", shift_date="2026-11-10", hourly_rate=None),
        shift(shift_id="C", shift_date="2026-11-11", hourly_rate="16", confirmation_status="unconfirmed"),
    ])
    week = out["weekly_summary"][0]
    assert week["paid_hours"] == 7.5 and week["gross_earnings"] == 120.0
    assert week["incomplete_hours"] == 7.5 and week["pending_hours"] == 7.5
