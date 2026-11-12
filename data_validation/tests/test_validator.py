"""Regression tests for the validation and earnings module.

They run the module on the synthetic test data and compare its output with the answer keys.
Run from the data_validation folder:  python3 -m pytest tests -v
The module under test is backend/app/services/shift_calculations.py at the top of the repository.
"""

import csv
import os
import sys

import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "test_data")

# The service lives in the backend at backend/app/services/shift_calculations.py
SERVICE = os.path.join(os.path.dirname(ROOT), "backend", "app", "services", "shift_calculations.py")
_spec = importlib.util.spec_from_file_location("shift_calculations", SERVICE)
service = importlib.util.module_from_spec(_spec)
sys.modules["shift_calculations"] = service
_spec.loader.exec_module(service)

load_flag_messages = service.load_flag_messages
load_known_locations = service.load_known_locations
load_rules = service.load_rules
process_shifts = service.process_shifts
calculate_shifts = service.calculate_shifts


def read(name):
    with open(os.path.join(DATA, name), newline="") as f:
        return list(csv.DictReader(f))


RULES = load_rules(os.path.join(DATA, "pay_rules.csv"))
MESSAGES = load_flag_messages(os.path.join(DATA, "flag_types.csv"))
KNOWN = load_known_locations(os.path.join(DATA, "locations.csv"))

LOCATIONS = {r["location_id"]: r["location_name"] for r in read("locations.csv")}
EMPLOYERS = {r["employer_id"]: r["employer_name"] for r in read("employers.csv")}


def truth_input(rows=None):
    """Correct shifts shaped like worker-confirmed input."""
    out = []
    for r in rows or read("truth_shifts.csv"):
        out.append(dict(
            shift_id=r["shift_id"], worker_id=r["worker_id"], shift_date=r["shift_date"],
            start_time=r["start_time"], end_time=r["end_time"], break_minutes=r["break_minutes"],
            employer_name=EMPLOYERS[r["employer_id"]], location=LOCATIONS[r["location_id"]],
            hourly_rate=r["hourly_rate"], currency=r["currency"], shift_status=r["shift_status"],
            confirmation_status="confirmed"))
    return out


# S029 line 2 is the confirmed shift whose rate is missing, so the answer key expects it to be incomplete
NO_RATE = {"S029-02"}


def run_truth(rows=None, remove_rates=True):
    shifts = truth_input(rows)
    if remove_rates:
        for s in shifts:
            if s["shift_id"] in NO_RATE:
                s["hourly_rate"] = None
    return process_shifts(shifts, RULES, MESSAGES, KNOWN)


def weekly_lookup(result):
    return {(w["worker_id"], w["pay_week_start"], w["currency"]): w for w in result["weekly_summary"]}


# ------------------------------------------------------------------ earnings
def test_weekly_totals_match_every_answer_key_row():
    result = run_truth()
    weekly = weekly_lookup(result)
    schedules = {s["schedule_id"]: s for s in read("schedules.csv")}
    expected = read("expected_weekly_earnings.csv")
    assert len(expected) == 32
    for e in expected:
        key = (e["worker_id"], e["pay_week_start"], e["currency"])
        got = weekly[key]
        assert got["shifts"] == int(e["shifts"]), e["weekly_id"]
        assert got["cancelled_shifts"] == int(e["cancelled_shifts"]), e["weekly_id"]
        assert got["incomplete_shifts"] == int(e["incomplete_shifts"]), e["weekly_id"]
        assert abs(got["paid_hours"] - float(e["paid_hours"])) < 0.005, e["weekly_id"]
        assert abs(got["regular_hours"] - float(e["regular_hours"])) < 0.005, e["weekly_id"]
        assert abs(got["overtime_hours"] - float(e["overtime_hours"])) < 0.005, e["weekly_id"]
        assert abs(got["gross_earnings"] - float(e["expected_gross_mvp"])) < 0.005, e["weekly_id"]
        assert abs(got["gross_with_overtime"] - float(e["expected_gross_with_overtime"])) < 0.015, e["weekly_id"]
        assert e["schedule_id"] in schedules


def test_reference_schedule_s001_is_384():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S001"]
    result = run_truth(rows)
    assert result["weekly_summary"][0]["gross_earnings"] == 384.00


def test_overtime_is_not_applied_s013():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S013"]
    week = run_truth(rows)["weekly_summary"][0]
    assert week["gross_earnings"] == 810.00
    assert week["overtime_hours"] == 14.0
    assert week["gross_with_overtime"] == 915.00


def test_cancelled_shifts_give_zero_s015():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S015"]
    result = run_truth(rows)
    assert result["weekly_summary"][0]["gross_earnings"] == 371.25
    assert result["weekly_summary"][0]["cancelled_shifts"] == 2
    cancelled = [s for s in result["shifts"] if s["status"] == "cancelled"]
    assert len(cancelled) == 2
    assert all(s["gross_earnings"] == 0.0 for s in cancelled)
    assert all(any(i["flag_name"] == "cancelled" for i in s["issues"]) for s in cancelled)


def test_spec_examples_with_a_30_minute_break_at_16_50_give_132_00_and_123_75():
    result = process_shifts([dict(
        shift_id="X1", worker_id="W1", shift_date="2026-11-09", start_time="09:00", end_time="17:30",
        break_minutes=30, employer_name="A", location="Store A", hourly_rate="16.50", currency="USD",
        confirmation_status="confirmed")], RULES, MESSAGES, KNOWN)
    assert result["shifts"][0]["paid_hours"] == 8.0
    assert result["shifts"][0]["gross_earnings"] == 132.0
    result = process_shifts([dict(
        shift_id="X2", worker_id="W1", shift_date="2026-11-09", start_time="09:00", end_time="17:00",
        break_minutes=30, employer_name="A", location="Store A", hourly_rate="16.50", currency="USD",
        confirmation_status="confirmed")], RULES, MESSAGES, KNOWN)
    assert result["shifts"][0]["paid_hours"] == 7.5
    assert result["shifts"][0]["gross_earnings"] == 123.75


def test_overnight_shift_counts_in_start_date_week():
    result = process_shifts([dict(
        shift_id="N1", worker_id="W1", shift_date="2026-11-08", start_time="22:00", end_time="06:00",
        break_minutes=0, employer_name="A", location="Hotel Front", hourly_rate="18", currency="USD",
        confirmation_status="confirmed")], RULES, MESSAGES, KNOWN)
    shift = result["shifts"][0]
    assert shift["paid_hours"] == 8.0
    assert shift["week_start"] == "2026-11-02"
    assert shift["gross_earnings"] == 144.0


def test_two_currencies_are_never_added_together_s028():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S028"]
    weeks = run_truth(rows)["weekly_summary"]
    by_cur = {w["currency"]: w["gross_earnings"] for w in weeks}
    assert by_cur == {"USD": 202.50, "EUR": 180.00}


def test_confirmed_shift_without_a_rate_is_incomplete_s029():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S029"]
    shifts = truth_input(rows)
    shifts[1]["hourly_rate"] = None
    result = process_shifts(shifts, RULES, MESSAGES, KNOWN)
    week = result["weekly_summary"][0]
    assert week["gross_earnings"] == 337.50
    assert week["incomplete_shifts"] == 1
    assert week["paid_hours"] == 30.0
    assert result["shifts"][1]["status"] == "incomplete"
    assert any(i["code"] == "MISSING_RATE" for i in result["shifts"][1]["issues"])


def test_unconfirmed_shifts_are_left_out_of_totals():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S002"]
    shifts = truth_input(rows)
    shifts[0]["confirmation_status"] = "unconfirmed"
    week = process_shifts(shifts, RULES, MESSAGES, KNOWN)["weekly_summary"][0]
    assert week["gross_earnings"] == round(4 * 123.75, 2)


# ------------------------------------------------------------------ conflicts
def test_conflicts_match_the_five_known_conflicts():
    result = run_truth()
    got = {(c["shift_a_id"], c["shift_b_id"], c["conflict_type"], c["gap_minutes"]) for c in result["conflicts"]}
    expected = {
        (c["shift_a_id"], c["shift_b_id"], c["conflict_type"],
         None if c["gap_minutes"] == "" else int(c["gap_minutes"]))
        for c in read("expected_conflicts.csv")}
    assert len(expected) == 5
    assert got == expected
    flags = {c["conflict_type"]: c["flag_name"] for c in result["conflicts"]}
    assert flags == {"overlap": "overlap", "commute_conflict": "insufficient_commute"}


def test_adjacent_shifts_at_the_same_location_are_not_overlaps():
    base = dict(worker_id="W1", shift_date="2026-11-09", break_minutes=0, employer_name="A",
                location="Store A", hourly_rate="15", currency="USD", confirmation_status="confirmed")
    shifts = [dict(base, shift_id="A", start_time="08:00", end_time="12:00"),
              dict(base, shift_id="B", start_time="12:00", end_time="16:00")]
    result = process_shifts(shifts, RULES, MESSAGES, KNOWN)
    assert result["conflicts"] == []


# ------------------------------------------------------------------ extracted rows with planted errors
def run_raw():
    raw = read("raw_shifts.csv")
    return raw, process_shifts(raw, RULES, MESSAGES, KNOWN, include_unconfirmed=True)


def by_id(result):
    return {s["id"]: s for s in result["shifts"]}


def test_every_planted_error_is_caught_with_the_right_flag():
    raw, result = run_raw()
    shifts = by_id(result)
    planted = read("planted_errors.csv")
    expected_flag = {e["error_type_id"]: e["flag_type_id"] for e in read("error_types.csv")}
    names = {e["error_type_id"]: e["error_type"] for e in read("error_types.csv")}
    assert len(planted) == 33
    missed = []
    for p in planted:
        flags = {i["flag_type_id"] for i in shifts[p["raw_id"]]["issues"]}
        if expected_flag[p["error_type_id"]] not in flags:
            missed.append((p["raw_id"], names[p["error_type_id"]]))
    assert missed == []


def test_specific_codes_for_the_new_edge_cases():
    raw, result = run_raw()
    shifts = by_id(result)
    codes = lambda rid: {i["code"] for i in shifts[rid]["issues"]}
    rid = {(r["schedule_id"], r["line_no"]): r["raw_id"] for r in raw}
    assert "INVALID_DURATION" in codes(rid[("S026", "2")])
    assert "INVALID_DURATION" in codes(rid[("S026", "3")])
    assert "INVALID_BREAK" in codes(rid[("S027", "2")])
    assert "INVALID_BREAK" in codes(rid[("S027", "3")])
    assert "MISSING_RATE" in codes(rid[("S029", "2")])
    assert shifts[rid[("S029", "2")]]["status"] == "incomplete"
    assert "UNKNOWN_LOCATION" in codes(rid[("S030", "2")])
    assert "MISSING_LOCATION" in codes(rid[("S014", "2")])
    assert "MISSING_EMPLOYER" in codes(rid[("S014", "4")])


def test_unknown_location_says_commute_cannot_be_assessed_s030():
    raw, result = run_raw()
    rid = {(r["schedule_id"], r["line_no"]): r["raw_id"] for r in raw}
    pairs = {(p["shift_a_id"], p["shift_b_id"]) for p in result["commute_not_assessed"]}
    assert (rid[("S030", "1")], rid[("S030", "2")]) in pairs
    commute = [c for c in result["conflicts"] if c["conflict_type"] == "commute_conflict"
               and rid[("S030", "2")] in (c["shift_a_id"], c["shift_b_id"])]
    assert commute == []


def test_clean_rows_get_no_false_missing_invalid_or_duplicate_flags():
    raw, result = run_raw()
    shifts = by_id(result)
    planted_ids = {p["raw_id"] for p in read("planted_errors.csv")}
    false_positives = []
    for r in raw:
        if r["raw_id"] in planted_ids:
            continue
        bad = [i["code"] for i in shifts[r["raw_id"]]["issues"] if i["flag_type_id"] in ("FL03", "FL04")]
        if bad:
            false_positives.append((r["raw_id"], bad))
    assert false_positives == []


def test_worker_messages_come_from_flag_types_csv():
    raw, result = run_raw()
    wanted = {f["flag_type_id"]: f["worker_message"] for f in read("flag_types.csv")}
    for s in result["shifts"]:
        for i in s["issues"]:
            assert i["message"] == wanted[i["flag_type_id"]]


# ------------------------------------------------------------------ Castro's product decisions
def one_shift(**changes):
    base = dict(shift_id="T1", worker_id="W1", shift_date="2026-11-09", start_time="09:00", end_time="17:00",
                break_minutes=30, employer_name="Acme", location="Store A", hourly_rate="16.50",
                currency="USD", shift_status="scheduled", confirmation_status="confirmed")
    base.update(changes)
    return base


def run(shifts, **kw):
    return process_shifts(shifts, RULES, MESSAGES, KNOWN, **kw)


def test_rules_file_holds_castros_decisions():
    assert RULES["pay_week_start"] == "monday"
    assert RULES["min_commute_gap_minutes"] == "30"
    assert RULES["second_mvp_format"] == "pdf_and_image"
    assert RULES["valid_break"] == "nonnegative_and_shorter_than_shift"
    assert RULES["missing_employer_or_location"] == "warning_not_blocking"
    assert RULES["missing_date"] == "blocking_error"
    assert RULES["earnings_source"] == "validated_worker_confirmed"


def test_missing_employer_is_a_warning_and_the_shift_still_counts():
    shift = run([one_shift(employer_name="")])["shifts"][0]
    issue = next(i for i in shift["issues"] if i["code"] == "MISSING_EMPLOYER")
    assert issue["severity"] == "warning" and issue["flag_name"] == "missing_or_invalid"
    assert shift["status"] == "counted"
    assert shift["gross_earnings"] == 123.75


def test_missing_location_is_a_warning_and_the_commute_check_is_unavailable():
    base = dict(worker_id="W1", shift_date="2026-11-09", break_minutes=0, employer_name="A",
                hourly_rate="15", currency="USD", confirmation_status="confirmed")
    shifts = [dict(base, shift_id="A", start_time="08:00", end_time="12:00", location="Store A"),
              dict(base, shift_id="B", start_time="12:15", end_time="16:00", location="")]
    result = run(shifts)
    second = result["shifts"][1]
    assert second["status"] == "counted"
    assert any(i["code"] == "MISSING_LOCATION" and i["severity"] == "warning" for i in second["issues"])
    assert result["conflicts"] == []
    assert len(result["commute_not_assessed"]) == 1


def test_missing_date_blocks_the_shift_with_a_specific_reason():
    shift = run([one_shift(shift_date="")])["shifts"][0]
    issue = next(i for i in shift["issues"] if i["code"] == "MISSING_DATE")
    assert issue["flag_type_id"] == "FL03" and issue["severity"] == "error"
    assert "date" in issue["reason"].lower()
    assert shift["status"] == "excluded"
    assert shift["gross_earnings"] is None


def test_needs_review_is_visible_but_left_out_of_earnings():
    result = run([one_shift(shift_id="A"), one_shift(shift_id="B", shift_date="2026-11-10",
                                                    confirmation_status="needs_review")])
    shifts = {s["id"]: s for s in result["shifts"]}
    assert shifts["B"]["status"] == "needs_review"
    assert any(i["code"] == "NEEDS_REVIEW" and i["flag_type_id"] == "FL06" for i in shifts["B"]["issues"])
    week = result["weekly_summary"][0]
    assert week["shifts"] == 2 and week["gross_earnings"] == 123.75


def test_rejected_is_kept_but_not_in_the_schedule_conflicts_or_earnings():
    base = one_shift(shift_id="A")
    overlapping_rejected = one_shift(shift_id="B", start_time="10:00", end_time="14:00",
                                     confirmation_status="rejected")
    result = run([base, overlapping_rejected], include_unconfirmed=True)
    shifts = {s["id"]: s for s in result["shifts"]}
    assert shifts["B"]["status"] == "rejected"
    assert result["conflicts"] == []
    week = result["weekly_summary"][0]
    assert week["shifts"] == 1 and week["gross_earnings"] == 123.75


def test_confirmed_shift_with_a_missing_rate_stays_visible_and_incomplete():
    shift = run([one_shift(hourly_rate="")])["shifts"][0]
    assert shift["status"] == "incomplete"
    assert shift["paid_hours"] == 7.5 and shift["gross_earnings"] is None


def test_unconfirmed_is_flagged_even_when_the_extraction_is_confident():
    shift = run([one_shift(confirmation_status="unconfirmed", extraction_confidence="0.99")])["shifts"][0]
    codes = [i["code"] for i in shift["issues"]]
    assert "UNCONFIRMED" in codes and "LOW_CONFIDENCE" not in codes
    assert shift["status"] == "unconfirmed"


def test_break_rule_nonnegative_and_shorter_than_the_shift():
    def codes(brk):
        shift = run([one_shift(break_minutes=brk)])["shifts"][0]
        return {i["code"] for i in shift["issues"]}
    assert "INVALID_BREAK" not in codes(0)
    assert "INVALID_BREAK" not in codes(479)
    assert "INVALID_BREAK" in codes(480)
    assert "INVALID_BREAK" in codes(600)
    assert "INVALID_BREAK" in codes(-15)


def test_every_issue_has_a_reason_and_the_messages_ask_for_a_check():
    raw, result = run_raw()
    for s in result["shifts"]:
        for i in s["issues"]:
            assert i["reason"]
    assert "check" in MESSAGES["FL04"].lower() and "remove" not in MESSAGES["FL04"].lower()
    assert "not been confirmed" in MESSAGES["FL06"].lower()


def test_earnings_use_confirmed_validated_shifts_only():
    shifts = [one_shift(shift_id="OK"),
              one_shift(shift_id="NEW", shift_date="2026-11-10", confirmation_status="unconfirmed"),
              one_shift(shift_id="REV", shift_date="2026-11-11", confirmation_status="needs_review"),
              one_shift(shift_id="REJ", shift_date="2026-11-12", confirmation_status="rejected"),
              one_shift(shift_id="BAD", shift_date="2026-11-13", start_time="09:00", end_time="09:00")]
    week = run(shifts)["weekly_summary"][0]
    assert week["gross_earnings"] == 123.75


# ------------------------------------------------------------------ the backend interface agreed with Nandila
def backend_shift(**changes):
    base = dict(shift_id="S1", employer="Acme", date="2026-11-09", start_time="09:00", end_time="17:00",
                end_date=None, break_minutes=30, hourly_rate="16.50", currency="USD",
                location_text="Store A", confirmation_status="confirmed", shift_status="scheduled",
                source_line="2026-11-09,09:00,17:00,30,Acme,Store A,,16.50,USD,scheduled,8.0")
    base.update(changes)
    return base


def calc(shifts, rules=None, worker_id="W1"):
    payload = {"worker_id": worker_id, "shifts": shifts}
    if rules is not None:
        payload["rules"] = rules
    return calculate_shifts(payload)


def test_backend_shape_in_and_out():
    out = calc([backend_shift()], {"pay_week_start": "monday", "min_commute_gap_minutes": 30})
    shift = out["shifts"][0]
    assert out["worker_id"] == "W1"
    assert shift["shift_id"] == "S1" and shift["date"] == "2026-11-09"
    assert shift["paid_hours"] == 7.5 and shift["gross_earnings"] == 123.75
    assert shift["validation_status"] == "valid" and shift["eligible_for_earnings"] is True
    assert shift["earnings_status"] == "counted" and shift["flags"] == []
    assert shift["source_line"].startswith("2026-11-09,09:00")
    week = out["weekly_summary"][0]
    assert week == {"week_start": "2026-11-09", "currency": "USD", "shifts": 1, "paid_hours": 7.5,
                    "gross_earnings": 123.75, "incomplete_shifts": 0, "earnings_incomplete": False,
                    "cancelled_shifts": 0}


def test_both_csv_names_and_backend_names_are_accepted():
    csv_style = dict(shift_id="S1", employer_name="Acme", shift_date="2026-11-09", start_time="09:00",
                     end_time="17:00", break_minutes=30, hourly_rate="16.50", currency="USD",
                     location="Store A", confirmation_status="confirmed")
    out = calc([csv_style])
    assert out["shifts"][0]["gross_earnings"] == 123.75
    assert out["shifts"][0]["validation_status"] == "valid"


def test_reporting_week_start_comes_from_the_rules():
    sunday_shift = backend_shift(date="2026-11-08")
    monday_week = calc([sunday_shift], {"pay_week_start": "monday"})["weekly_summary"][0]["week_start"]
    sunday_week = calc([sunday_shift], {"week_start": "sunday"})["weekly_summary"][0]["week_start"]
    assert monday_week == "2026-11-02" and sunday_week == "2026-11-08"


def test_commute_gap_threshold_comes_from_the_rules():
    first = backend_shift(shift_id="A", start_time="08:00", end_time="12:00", break_minutes=0)
    second = backend_shift(shift_id="B", start_time="12:40", end_time="16:00", break_minutes=0,
                           location_text="Store B")
    assert calc([first, second], {"min_commute_gap_minutes": 30})["conflicts"] == []
    out = calc([first, second], {"commute_gap_minutes": 45})
    assert [c["conflict_type"] for c in out["conflicts"]] == ["commute_conflict"]


def test_end_date_for_an_overnight_shift():
    out = calc([backend_shift(start_time="22:00", end_time="06:00", end_date="2026-11-10", break_minutes=0)])
    assert out["shifts"][0]["paid_hours"] == 8.0
    assert out["shifts"][0]["validation_status"] == "valid"


def test_end_date_before_the_start_or_not_a_date_is_invalid():
    before = calc([backend_shift(end_date="2026-11-08")])["shifts"][0]
    assert before["validation_status"] == "invalid"
    assert any(f["code"] == "INVALID_DURATION" for f in before["flags"])
    bad = calc([backend_shift(end_date="next day")])["shifts"][0]
    assert any(f["code"] == "INVALID_END_DATE" for f in bad["flags"])
    assert bad["eligible_for_earnings"] is False


def test_only_valid_confirmed_shifts_are_eligible():
    shifts = [backend_shift(shift_id="OK"),
              backend_shift(shift_id="UNC", date="2026-11-10", confirmation_status="unconfirmed"),
              backend_shift(shift_id="REV", date="2026-11-11", confirmation_status="needs_review"),
              backend_shift(shift_id="REJ", date="2026-11-12", confirmation_status="rejected"),
              backend_shift(shift_id="CAN", date="2026-11-13", shift_status="cancelled"),
              backend_shift(shift_id="BAD", date="2026-11-14", start_time="25:00")]
    out = calc(shifts)
    eligible = {s["shift_id"]: s["eligible_for_earnings"] for s in out["shifts"]}
    assert eligible == {"OK": True, "UNC": False, "REV": False, "REJ": False, "CAN": False, "BAD": False}
    assert out["weekly_summary"][0]["gross_earnings"] == 123.75


def test_missing_employer_or_location_warns_but_still_counts_and_missing_date_blocks():
    out = calc([backend_shift(shift_id="A", employer=""),
                backend_shift(shift_id="B", date="2026-11-10", location_text=""),
                backend_shift(shift_id="C", date="")])
    by_id = {s["shift_id"]: s for s in out["shifts"]}
    for name in ("A", "B"):
        assert by_id[name]["validation_status"] == "warning" and by_id[name]["eligible_for_earnings"] is True
    assert by_id["C"]["validation_status"] == "invalid" and by_id["C"]["eligible_for_earnings"] is False


def test_incomplete_earnings_are_indicated_in_the_weekly_summary():
    out = calc([backend_shift(shift_id="A"), backend_shift(shift_id="B", date="2026-11-10", hourly_rate=None)])
    week = out["weekly_summary"][0]
    assert week["incomplete_shifts"] == 1 and week["earnings_incomplete"] is True
    assert week["gross_earnings"] == 123.75 and week["paid_hours"] == 15.0


def test_weekly_summary_is_grouped_by_currency():
    out = calc([backend_shift(shift_id="A"),
                backend_shift(shift_id="B", date="2026-11-10", currency="EUR", hourly_rate="10")])
    totals = {w["currency"]: w["gross_earnings"] for w in out["weekly_summary"]}
    assert totals == {"USD": 123.75, "EUR": 75.0}


def test_known_locations_can_be_passed_by_the_backend():
    payload = {"worker_id": "W1", "shifts": [backend_shift(location_text="Riverside Annex")],
               "known_locations": ["Store A", "Store B"]}
    flags = calculate_shifts(payload)["shifts"][0]["flags"]
    assert any(f["code"] == "UNKNOWN_LOCATION" for f in flags)


# ------------------------------------------------------------------ S031: review queue and rejected rows in the csv data
def s031_rows():
    raw, result = run_raw()
    rows = {r["line_no"]: r for r in raw if r["schedule_id"] == "S031"}
    return rows, by_id(result), result


def test_s031_needs_review_and_rejected_rows_exist_in_the_data():
    rows, _, _ = s031_rows()
    assert sorted(rows) == ["1", "2", "3", "4"]
    assert rows["1"]["confirmation_status"] == "confirmed"
    assert rows["2"]["confirmation_status"] == "needs_review"
    assert rows["3"]["confirmation_status"] == "confirmed"
    assert rows["4"]["confirmation_status"] == "rejected"
    statuses = {r["confirmation_status"] for r in read("raw_shifts.csv")}
    assert statuses == {"confirmed", "unconfirmed", "needs_review", "rejected"}


def test_s031_review_queue_shift_is_visible_flagged_and_left_out_of_earnings():
    rows, shifts, result = s031_rows()
    review = shifts[rows["2"]["raw_id"]]
    assert review["status"] == "needs_review"
    assert "NEEDS_REVIEW" in {i["code"] for i in review["issues"]}
    assert review["paid_hours"] == 7.5
    week = [w for w in result["weekly_summary"] if w["worker_id"] == "W011" and w["pay_week_start"] == "2026-11-16"][0]
    assert week["gross_earnings"] == 225.00
    assert week["paid_hours"] == 15.0


def test_s031_rejected_shift_is_kept_but_not_in_the_schedule_conflicts_or_earnings():
    rows, shifts, result = s031_rows()
    rejected = shifts[rows["4"]["raw_id"]]
    assert rejected["status"] == "rejected"
    # it overlaps line 3 (10:00 to 14:00 on the same day) but must not create a conflict
    ids = {rows["3"]["raw_id"], rows["4"]["raw_id"]}
    assert [c for c in result["conflicts"] if {c["shift_a_id"], c["shift_b_id"]} & ids] == []
    week = [w for w in result["weekly_summary"] if w["worker_id"] == "W011" and w["pay_week_start"] == "2026-11-16"][0]
    assert week["shifts"] == 3  # lines 1 to 3, the rejected line is not in the schedule


def test_s031_has_no_truth_row_for_the_rejected_line_and_no_planted_error():
    rows, _, _ = s031_rows()
    mapping = {m["raw_id"]: m["shift_id"] for m in read("raw_truth_map.csv")}
    assert mapping[rows["4"]["raw_id"]] == ""
    assert mapping[rows["2"]["raw_id"]] == "S031-02"
    planted_raw = {p["raw_id"] for p in read("planted_errors.csv")}
    assert not planted_raw & {r["raw_id"] for r in rows.values()}


def test_s031_gives_the_answer_key_once_the_worker_has_confirmed_every_shift():
    rows = [r for r in read("truth_shifts.csv") if r["schedule_id"] == "S031"]
    week = process_shifts(truth_input(rows), RULES, MESSAGES, KNOWN)["weekly_summary"][0]
    assert week["gross_earnings"] == 337.50
    expected = [e for e in read("expected_weekly_earnings.csv") if e["schedule_id"] == "S031"][0]
    assert float(expected["expected_gross_mvp"]) == 337.50


# ------------------------------------------------------------------ Castro's second review: breaks, duplicates, currency, review queue
def test_rules_file_holds_the_second_review_decisions():
    assert RULES["missing_break"] == "incomplete_until_confirmed"
    assert RULES["possible_duplicate"] == "held_for_review"
    assert RULES["missing_currency"] == "incomplete"


def test_a_missing_break_is_never_treated_as_zero_minutes():
    shift = calc([backend_shift(break_minutes=None)])["shifts"][0]
    assert shift["earnings_status"] == "incomplete" and shift["eligible_for_earnings"] is False
    assert shift["paid_hours"] is None and shift["gross_earnings"] is None
    flag = next(f for f in shift["flags"] if f["code"] == "MISSING_BREAK")
    assert "no break" in flag["reason"] and "overstated" in flag["reason"]
    week = calc([backend_shift(break_minutes=None)])["weekly_summary"][0]
    assert week["gross_earnings"] is None and week["earnings_incomplete"] is True and week["incomplete_shifts"] == 1


def test_a_confirmed_zero_break_counts_in_full():
    shift = calc([backend_shift(break_minutes=0)])["shifts"][0]
    assert shift["earnings_status"] == "counted" and shift["paid_hours"] == 8.0 and shift["gross_earnings"] == 132.0


def test_a_possible_duplicate_is_held_for_review_and_not_counted_twice():
    out = calc([backend_shift(shift_id="A"), backend_shift(shift_id="B")])
    first, second = out["shifts"]
    assert first["earnings_status"] == "counted"
    assert second["earnings_status"] == "needs_review" and second["eligible_for_earnings"] is False
    assert second["gross_earnings"] is None
    assert "POSSIBLE_DUPLICATE" in {f["code"] for f in second["flags"]}
    assert out["weekly_summary"][0]["gross_earnings"] == 123.75


def test_a_missing_currency_makes_earnings_incomplete_and_gives_no_total():
    out = calc([backend_shift(currency=None)])
    shift, week = out["shifts"][0], out["weekly_summary"][0]
    assert shift["earnings_status"] == "incomplete" and shift["gross_earnings"] is None
    assert "MISSING_CURRENCY" in {f["code"] for f in shift["flags"]}
    assert week["currency"] is None and week["gross_earnings"] is None
    assert week["earnings_incomplete"] is True and week["incomplete_shifts"] == 1


def test_confirmed_shifts_with_unresolved_problems_are_available_for_the_review_queue():
    out = calc([backend_shift(shift_id="A", hourly_rate=None),
                backend_shift(shift_id="B", date="2026-11-10", start_time="xx"),
                backend_shift(shift_id="C", date="2026-11-11")])
    status = {s["shift_id"]: s["earnings_status"] for s in out["shifts"]}
    assert status == {"A": "incomplete", "B": "excluded", "C": "counted"}
    need_attention = {"needs_review", "unconfirmed", "incomplete", "excluded"}
    assert [s["shift_id"] for s in out["shifts"] if s["earnings_status"] in need_attention] == ["A", "B"]
    reasons = {s["shift_id"]: [f["reason"] for f in s["flags"]] for s in out["shifts"] if s["flags"]}
    assert all(reasons[k] for k in ("A", "B"))


# ---- Castro's decisions on PR 3 -------------------------------------------------
def test_earnings_use_exact_minutes_and_round_only_the_money():
    # 12:10 to 17:00 with no break is 4h50m = 4.8333 hours; at 13.00 that is 62.83, not 62.79
    shift = calc([backend_shift(start_time="12:10", end_time="17:00", break_minutes=0, hourly_rate="13.00")])["shifts"][0]
    assert shift["paid_hours"] == 4.83 and shift["gross_earnings"] == 62.83


def test_a_missing_hourly_rate_is_a_warning_and_the_shift_is_not_counted():
    out = calc([backend_shift(hourly_rate=None)])
    shift, week = out["shifts"][0], out["weekly_summary"][0]
    assert shift["validation_status"] == "warning"
    assert shift["earnings_status"] == "incomplete" and shift["gross_earnings"] is None
    assert next(f for f in shift["flags"] if f["code"] == "MISSING_RATE")["severity"] == "warning"
    assert week["earnings_incomplete"] is True and week["gross_earnings"] is None


def test_a_week_with_nothing_counted_yet_shows_null_not_zero():
    out = calc([backend_shift(confirmation_status="unconfirmed")])
    week = out["weekly_summary"][0]
    assert week["gross_earnings"] is None and week["earnings_incomplete"] is True


def test_a_week_where_every_shift_is_cancelled_is_a_real_zero():
    out = calc([backend_shift(shift_status="cancelled")])
    week = out["weekly_summary"][0]
    assert week["gross_earnings"] == 0.0 and week["earnings_incomplete"] is False and week["cancelled_shifts"] == 1


def test_a_rejected_shift_does_not_block_its_twin():
    for order in (("rejected", "confirmed"), ("confirmed", "rejected")):
        out = calc([backend_shift(shift_id="A", confirmation_status=order[0]),
                    backend_shift(shift_id="B", confirmation_status=order[1])])
        by_id = {s["shift_id"]: s for s in out["shifts"]}
        kept = by_id["A"] if order[0] == "confirmed" else by_id["B"]
        assert kept["earnings_status"] == "counted" and kept["gross_earnings"] == 123.75
        assert "POSSIBLE_DUPLICATE" not in {f["code"] for f in kept["flags"]}
        assert out["weekly_summary"][0]["gross_earnings"] == 123.75


def test_spec_acceptance_example_232():
    out = calc([backend_shift(shift_id="M", date="2026-11-09", start_time="09:00", end_time="17:00",
                              break_minutes=30, hourly_rate="16", currency="USD"),
                backend_shift(shift_id="T", date="2026-11-10", start_time="10:00", end_time="18:00",
                              break_minutes=60, hourly_rate="16", currency="USD"),
                backend_shift(shift_id="W", date="2026-11-11", start_time="09:00", end_time="17:00",
                              break_minutes=None, hourly_rate="16", currency="USD")])
    week = out["weekly_summary"][0]
    assert week["paid_hours"] == 14.5 and week["gross_earnings"] == 232.0
    assert week["earnings_incomplete"] is True and week["incomplete_shifts"] == 1
