"""A shift entered twice is one duplicate issue, not also an overlap conflict.

Agreed on PR 9 (Castro and Nandila): keep the duplicate warning and hold the extra copy for review, and keep overlap
conflicts for genuinely different shifts that overlap.
"""
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

BASE = {
    "worker_id": "W1", "employer_name": "BrightMart", "location": "Store A",
    "shift_date": "2026-11-03", "start_time": "08:00", "end_time": "16:00", "break_minutes": 30,
    "hourly_rate": "15", "currency": "USD", "shift_status": "scheduled", "confirmation_status": "confirmed",
}


def shift(shift_id, **overrides):
    return {**BASE, "shift_id": shift_id, **overrides}


def calculate(*shifts):
    response = client.post("/api/v1/shifts/calculate", json={"worker_id": "W1", "shifts": list(shifts)})
    assert response.status_code == 200, response.text
    body = response.json()
    return {s["shift_id"]: s for s in body["shifts"]}, body["conflicts"]


def codes(s):
    return [f["code"] for f in s["flags"]]


def test_an_exact_duplicate_is_one_duplicate_issue_and_no_overlap():
    shifts, conflicts = calculate(shift("A"), shift("B"))
    assert conflicts == []
    assert shifts["A"]["earnings_status"] == "counted" and codes(shifts["A"]) == []
    assert shifts["B"]["earnings_status"] == "needs_review" and "POSSIBLE_DUPLICATE" in codes(shifts["B"])


def test_three_copies_give_no_overlap_and_only_the_first_counts():
    shifts, conflicts = calculate(shift("A"), shift("B"), shift("C"))
    assert conflicts == []
    assert [shifts[i]["earnings_status"] for i in "ABC"] == ["counted", "needs_review", "needs_review"]


def test_the_duplicate_copy_still_adds_nothing_to_the_week():
    response = client.post("/api/v1/shifts/calculate", json={"worker_id": "W1", "shifts": [shift("A"), shift("B")]})
    week = response.json()["weekly_summary"][0]
    assert week["gross_earnings"] == 112.5 and week["paid_hours"] == 7.5


def test_different_shifts_that_overlap_are_still_an_overlap():
    shifts, conflicts = calculate(shift("A"), shift("B", location="Store B", start_time="12:00", end_time="20:00"))
    assert [(c["shift_a_id"], c["shift_b_id"], c["conflict_type"]) for c in conflicts] == [("A", "B", "overlap")]


def test_same_times_at_another_location_is_not_a_duplicate_so_it_overlaps():
    _, conflicts = calculate(shift("A"), shift("B", location="Store B"))
    assert [c["conflict_type"] for c in conflicts] == ["overlap"]


def test_a_duplicate_that_also_overlaps_a_different_shift_keeps_that_overlap():
    other = shift("D", location="Store B", start_time="12:00", end_time="20:00")
    _, conflicts = calculate(shift("A"), shift("B"), other)
    pairs = sorted((c["shift_a_id"], c["shift_b_id"]) for c in conflicts)
    assert pairs == [("A", "D"), ("B", "D")]          # nothing between A and B


def test_rejecting_the_original_releases_the_copy_with_no_overlap():
    shifts, conflicts = calculate(shift("A", confirmation_status="rejected"), shift("B"))
    assert conflicts == []
    assert shifts["B"]["earnings_status"] == "counted"
