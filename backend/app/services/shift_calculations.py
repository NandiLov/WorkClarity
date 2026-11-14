"""WorkClarity shift validation and gross earnings (backend service).

Entry point for the backend: calculate_shifts(payload). The lower level process_shifts(shifts)
is what the tests use. Placed at backend/app/services/shift_calculations.py as agreed with Nandila.

One function does the work: process_shifts(shifts). It takes a list of shifts and
returns the checked shifts, the schedule conflicts and the weekly totals. It uses only
the Python standard library, so it can be called from the FastAPI backend as it is.

The input and output shape below is a proposal. It is written to match the csv contract
(docs/csv_input_contract.md) and Castro's specification, and it can change when Nandila
confirms the shape she wants.

Input, one dict per shift (extra keys are ignored, empty text counts as missing):
    shift_id or raw_id   optional identifier, the list position is used if both are missing
    worker_id            who the shift belongs to, needed for conflicts and weekly totals
    shift_date           YYYY-MM-DD
    start_time           HH:MM, 24 hour
    end_time             HH:MM, 24 hour. Earlier than the start means the shift ends the next day
    break_minutes        unpaid break, whole number
    employer_name        text
    location or location_text   text
    hourly_rate          number, entered or confirmed by the worker
    currency             for example USD
    shift_status         scheduled, changed or cancelled (blank means scheduled)
    confirmation_status  confirmed, unconfirmed, needs_review or rejected (blank means unconfirmed)
    extraction_confidence  optional, 0 to 1

Output:
    {
      "shifts": [ {id, worker_id, shift_date, week_start, paid_hours, hourly_rate, currency,
                   gross_earnings, status, issues: [ {code, flag_type_id, flag_name,
                   severity, reason, message} ]} ],
      "conflicts": [ {shift_a_id, shift_b_id, conflict_type, gap_minutes, flag_type_id,
                      flag_name, message} ],
      "commute_not_assessed": [ {shift_a_id, shift_b_id, gap_minutes, message} ],
      "weekly_summary": [ {worker_id, pay_week_start, currency, shifts, cancelled_shifts,
                           incomplete_shifts, pending_shifts, paid_hours (eligible hours only),
                           incomplete_hours, pending_hours, regular_hours, overtime_hours,
                           gross_earnings, gross_with_overtime} ]
    }

Shift status:
    counted       confirmed, valid, has a rate, included in gross earnings
    incomplete    confirmed and valid but the rate, the break or the currency is missing, stays visible,
                  left out of gross earnings until the worker fills it in (a break of 0 means no break)
    excluded      confirmed but has an error, left out until the worker fixes it
    unconfirmed   the worker has not confirmed it, left out of totals
    needs_review  shown in the review queue, left out of earnings until corrected and confirmed.
                  A possible duplicate is held here too, so it never counts twice
    rejected      kept for traceability, left out of the active schedule, conflicts and earnings
    cancelled     kept as a record, 0.00 earnings

A missing employer or a missing location is a warning only. It does not stop a shift counting
as long as the essential details (date, times, break, rate) are valid. A missing date is a
blocking error. A missing or unknown location means the commute check could not be done.

Money rules (see test_data/pay_rules.csv): gross pay, unpaid breaks, overtime off,
paid hours rounded to 2 decimals, then gross rounded to 2 decimals per shift, then summed.
"""

import csv
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

LOW_CONFIDENCE_BELOW = 0.75

DEFAULT_RULES = {
    "pay_week_start": "monday",
    "overtime_enabled": "false",
    "overtime_threshold_hours": "40",
    "overtime_multiplier": "1.5",
    "max_shift_hours": "16",
    "min_commute_gap_minutes": "30",
}

# code -> (flag_type_id, severity)
ISSUE_FLAGS = {
    "MISSING_DATE": ("FL03", "error"),
    "INVALID_TIME": ("FL03", "error"),
    "INVALID_END_DATE": ("FL03", "error"),
    "INVALID_DURATION": ("FL03", "error"),
    "INVALID_BREAK": ("FL03", "error"),
    "MISSING_BREAK": ("FL03", "warning"),
    "MISSING_RATE": ("FL03", "warning"),
    "MISSING_CURRENCY": ("FL03", "warning"),
    "MISSING_EMPLOYER": ("FL03", "warning"),
    "MISSING_LOCATION": ("FL03", "warning"),
    "UNKNOWN_LOCATION": ("FL03", "warning"),
    "POSSIBLE_DUPLICATE": ("FL04", "warning"),
    "CANCELLED": ("FL05", "info"),
    "UNCONFIRMED": ("FL06", "warning"),
    "NEEDS_REVIEW": ("FL06", "warning"),
    "LOW_CONFIDENCE": ("FL06", "warning"),
    "OVERLAP": ("FL01", "error"),
    "COMMUTE_GAP": ("FL02", "warning"),
}

FLAG_NAMES = {
    "FL01": "overlap", "FL02": "insufficient_commute", "FL03": "missing_or_invalid",
    "FL04": "duplicate", "FL05": "cancelled", "FL06": "unconfirmed",
}

DEFAULT_MESSAGES = {
    "FL01": "These shifts happen at the same time. Please check which one is right.",
    "FL02": "You may not have enough time to get from one job to the next.",
    "FL03": "Some details of this shift are missing or look wrong. Please check them.",
    "FL04": "This shift may be a duplicate. It is not counted until you check it and confirm which one is correct.",
    "FL05": "This shift was cancelled, so it is not counted in your estimated earnings.",
    "FL06": "This shift has not been confirmed yet. Please review it and confirm it so it counts toward your earnings.",
}

REASONS = {
    "MISSING_DATE": "The shift date is missing or is not a valid date written as YYYY-MM-DD.",
    "INVALID_TIME": "The start time or end time is missing or is not a valid 24 hour time written as HH:MM.",
    "INVALID_END_DATE": "The end date is not a valid date written as YYYY-MM-DD.",
    "INVALID_DURATION": "The shift length is zero, negative or longer than the maximum allowed.",
    "INVALID_BREAK": "The break is negative or as long as, or longer than, the shift.",
    "MISSING_BREAK": "The break length is missing. Please confirm whether you had no break or enter the break, so earnings are not overstated.",
    "MISSING_RATE": "The hourly rate is missing, so earnings for this shift are incomplete.",
    "MISSING_CURRENCY": "The currency is missing, so earnings for this shift are incomplete and cannot be added to a total.",
    "MISSING_EMPLOYER": "The employer is missing.",
    "MISSING_LOCATION": "The location is missing, so the commute check is unavailable.",
    "UNKNOWN_LOCATION": "The location does not match a known location, so the commute check is unavailable.",
    "POSSIBLE_DUPLICATE": "Another shift has the same worker, date, times and location, so this one is held for review and not counted twice.",
    "CANCELLED": "The shift was cancelled and is not counted in earnings.",
    "UNCONFIRMED": "The worker has not confirmed this shift yet.",
    "NEEDS_REVIEW": "This shift is waiting in the review queue.",
    "LOW_CONFIDENCE": "The extraction was not confident about this shift.",
    "OVERLAP": "This shift overlaps another shift.",
    "COMMUTE_GAP": "The gap to the next shift at a different location is shorter than the minimum.",
}

INCOMPLETE_CODES = ("MISSING_RATE", "MISSING_BREAK", "MISSING_CURRENCY")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
CENT = Decimal("0.01")


# ------------------------------------------------------------------ loading reference files
def load_rules(path=None):
    """Read pay_rules.csv into a dict of rule_name to value. Missing file gives the defaults."""
    rules = dict(DEFAULT_RULES)
    if path and os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rules[row["rule_name"]] = row["value"]
    return rules


def load_flag_messages(path=None):
    """Read flag_types.csv into a dict of flag_type_id to worker message."""
    messages = dict(DEFAULT_MESSAGES)
    if path and os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                messages[row["flag_type_id"]] = row["worker_message"]
    return messages


def load_known_locations(path=None):
    """Read locations.csv into a set of normalised location names."""
    names = set()
    if path and os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                names.add(_norm(row["location_name"]))
    return names


# ------------------------------------------------------------------ small helpers
def _blank(v):
    return v is None or str(v).strip() == ""


def _norm(v):
    return "" if v is None else str(v).strip().casefold()


def _get(shift, *names):
    for n in names:
        if n in shift and not _blank(shift[n]):
            return shift[n]
    return None


def _parse_date(v):
    if _blank(v):
        return None
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _parse_time(v):
    if _blank(v):
        return None
    m = TIME_RE.match(str(v).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _to_decimal(v):
    if _blank(v):
        return None
    try:
        return Decimal(str(v).strip())
    except Exception:
        return None


def _currency(v):
    if _blank(v):
        return None
    s = str(v).strip()
    return "USD" if s == "$" else s.upper()


def _money(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _week_start(day, week_start_name="monday"):
    name = str(week_start_name).strip().lower()
    first = WEEKDAYS.index(name) if name in WEEKDAYS else 0
    return (day - timedelta(days=(day.weekday() - first) % 7)).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ per shift checks
def _check_shift(shift, index, rules, known_locations):
    """Return a dict describing one shift with its issues. Duplicates are added later."""
    sid = _get(shift, "shift_id", "raw_id") or f"row{index + 1}"
    issues = []

    def issue(code):
        issues.append(code)

    day = _parse_date(_get(shift, "shift_date", "date"))
    if day is None:
        issue("MISSING_DATE")

    start_raw, end_raw = _get(shift, "start_time"), _get(shift, "end_time")
    start, end = _parse_time(start_raw), _parse_time(end_raw)
    if start is None or end is None:
        issue("INVALID_TIME")

    end_date_raw = _get(shift, "end_date")
    end_day = _parse_date(end_date_raw) if end_date_raw is not None else None
    if end_date_raw is not None and end_day is None:
        issue("INVALID_END_DATE")

    start_dt = end_dt = None
    minutes = None
    if day is not None and start is not None and end is not None:
        start_dt = day.replace(hour=start[0], minute=start[1])
        if end_day is not None:
            end_dt = end_day.replace(hour=end[0], minute=end[1])
            ordered = end_dt > start_dt
        else:
            end_dt = day.replace(hour=end[0], minute=end[1])
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            ordered = True
        minutes = int((end_dt - start_dt).total_seconds() // 60)
        if not ordered or end_dt == start_dt or minutes > int(rules["max_shift_hours"]) * 60:
            issue("INVALID_DURATION")
            minutes_ok = False
        else:
            minutes_ok = True
    else:
        minutes_ok = False

    brk_raw = _get(shift, "break_minutes")
    brk = _to_int(brk_raw)
    if brk_raw is None:
        issue("MISSING_BREAK")  # earnings stay incomplete until the worker confirms no break (0) or enters it
        brk = None
    elif brk is None or brk < 0 or (minutes is not None and minutes_ok and brk >= minutes):
        issue("INVALID_BREAK")
        brk = None

    rate = _to_decimal(_get(shift, "hourly_rate"))
    if rate is None or rate < 0:
        issue("MISSING_RATE")
        rate = None

    if _currency(_get(shift, "currency")) is None:
        issue("MISSING_CURRENCY")

    if _get(shift, "employer_name", "employer") is None:
        issue("MISSING_EMPLOYER")

    location = _get(shift, "location", "location_text")
    if location is None:
        issue("MISSING_LOCATION")
    elif known_locations and _norm(location) not in known_locations:
        issue("UNKNOWN_LOCATION")

    status_raw = _norm(_get(shift, "shift_status")) or "scheduled"
    cancelled = status_raw == "cancelled"
    confirmation = _norm(_get(shift, "confirmation_status"))
    confirmed = confirmation == "confirmed"
    rejected = confirmation == "rejected"
    needs_review = confirmation == "needs_review"
    if cancelled:
        issue("CANCELLED")
    if needs_review:
        issue("NEEDS_REVIEW")
    elif not confirmed and not rejected:
        issue("UNCONFIRMED")
    conf = _get(shift, "extraction_confidence")
    try:
        if conf is not None and float(conf) < LOW_CONFIDENCE_BELOW:
            issue("LOW_CONFIDENCE")
    except ValueError:
        pass

    paid_hours = None      # shown to the worker, rounded to 2 decimals
    paid_exact = None      # exact hours from whole minutes, used for earnings
    if minutes is not None and minutes_ok and brk is not None:
        paid_exact = Decimal(minutes - brk) / Decimal(60)
        paid_hours = paid_exact.quantize(CENT, rounding=ROUND_HALF_UP)

    return dict(
        id=sid, worker_id=_get(shift, "worker_id"), day=day, start_dt=start_dt, end_dt=end_dt,
        location=location, cancelled=cancelled, confirmed=confirmed, rejected=rejected,
        needs_review=needs_review, rate=rate,
        currency=_currency(_get(shift, "currency")), paid_hours=paid_hours, paid_exact=paid_exact,
        codes=issues, key=(_get(shift, "worker_id"), str(_get(shift, "shift_date", "date")),
                           str(start_raw), str(end_raw), _norm(location)),
        valid_times=minutes_ok,
    )


def _earnings_reason(status, codes):
    """Plain reason why a shift is not fully counted, or None when it is counted."""
    if status == "counted":
        return None
    if status == "cancelled":
        return REASONS["CANCELLED"]
    if status == "rejected":
        return "The worker rejected this shift, so it is not counted."
    if status == "needs_review":
        return REASONS["POSSIBLE_DUPLICATE"] if "POSSIBLE_DUPLICATE" in codes else REASONS["NEEDS_REVIEW"]
    if status == "unconfirmed":
        return REASONS["UNCONFIRMED"]
    if status == "incomplete":
        return " ".join(REASONS[c] for c in INCOMPLETE_CODES if c in codes)
    return " ".join(REASONS[c] for c in codes if ISSUE_FLAGS[c][1] == "error")


def _status_and_gross(s):
    errors = [c for c in s["codes"] if ISSUE_FLAGS[c][1] == "error"]
    if s["rejected"]:
        return "rejected", None
    if s["cancelled"]:
        return "cancelled", Decimal("0.00")
    if s["needs_review"]:
        return "needs_review", None
    if not s["confirmed"]:
        return "unconfirmed", None
    if "POSSIBLE_DUPLICATE" in s["codes"]:
        return "needs_review", None  # held for review so it does not count twice
    blocking = [c for c in errors if c != "MISSING_RATE"]
    if blocking:
        return "excluded", None
    if any(c in s["codes"] for c in INCOMPLETE_CODES):
        return "incomplete", None
    return "counted", _money(s["paid_exact"] * s["rate"])


# ------------------------------------------------------------------ conflicts
def _find_conflicts(checked, rules, messages, include_unconfirmed):
    min_gap = int(rules["min_commute_gap_minutes"])
    conflicts, not_assessed = [], []
    by_worker = {}
    for s in checked:
        if s["cancelled"] or s["rejected"] or s["start_dt"] is None or not s["valid_times"]:
            continue
        if not include_unconfirmed and not s["confirmed"]:
            continue
        by_worker.setdefault(s["worker_id"], []).append(s)
    for worker, items in by_worker.items():
        items.sort(key=lambda x: x["start_dt"])
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a["start_dt"] < b["end_dt"] and b["start_dt"] < a["end_dt"]:
                    conflicts.append(dict(
                        shift_a_id=a["id"], shift_b_id=b["id"], conflict_type="overlap", gap_minutes=None,
                        flag_type_id="FL01", flag_name="overlap", message=messages["FL01"]))
                    continue
                gap = int((b["start_dt"] - a["end_dt"]).total_seconds() // 60)
                if 0 <= gap < min_gap:
                    la, lb = a["location"], b["location"]
                    unknown = a["_loc_unknown"] or b["_loc_unknown"]
                    if unknown:
                        not_assessed.append(dict(
                            shift_a_id=a["id"], shift_b_id=b["id"], gap_minutes=gap,
                            message="Unable to assess the travel time because a location is missing or not recognised."))
                    elif _norm(la) != _norm(lb):
                        conflicts.append(dict(
                            shift_a_id=a["id"], shift_b_id=b["id"], conflict_type="commute_conflict",
                            gap_minutes=gap, flag_type_id="FL02", flag_name="insufficient_commute",
                            message=messages["FL02"]))
    return conflicts, not_assessed


# ------------------------------------------------------------------ weekly totals
def _weekly(results, rules):
    groups = {}
    for r in results:
        if r["week_start"] is None or r["status"] == "rejected":
            continue
        groups.setdefault((r["worker_id"], r["week_start"], r["currency"]), []).append(r)
    threshold = Decimal(rules["overtime_threshold_hours"])
    mult = Decimal(rules["overtime_multiplier"])
    overtime_on = str(rules["overtime_enabled"]).lower() == "true"
    rows = []
    for (worker, week, cur), items in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], str(kv[0][2]))):
        counted = [i for i in items if i["status"] == "counted"]
        incomplete = [i for i in items if i["status"] == "incomplete"]
        pending = [i for i in items if i["status"] in ("unconfirmed", "needs_review")]
        def _hours_of(group):
            return sum((i["_exact_hours"] for i in group if i["_exact_hours"] is not None), Decimal("0"))
        # paid_hours = eligible hours only: the hours that make up gross_earnings.
        # Hours of incomplete and waiting shifts are reported apart so they are never mixed in.
        hours = _hours_of(counted)
        incomplete_hours = _hours_of(incomplete)
        pending_hours = _hours_of(pending)
        gross = sum((Decimal(str(i["gross_earnings"])) for i in counted), Decimal("0"))
        # "Not counted yet": nothing counted but shifts are still waiting, so the total is null, not 0.00.
        # A genuine zero (for example every shift cancelled) stays 0.00.
        no_total = cur is None or (not counted and bool(incomplete or pending))
        ot = max(hours - threshold, Decimal("0"))
        with_ot = gross if ot == 0 or hours == 0 else gross + ot * (gross / hours) * (mult - 1)
        rows.append(dict(
            worker_id=worker, pay_week_start=week, currency=cur, shifts=len(items),
            cancelled_shifts=sum(1 for i in items if i["status"] == "cancelled"),
            incomplete_shifts=len(incomplete), pending_shifts=len(pending),
            paid_hours=float(_money(hours)),
            incomplete_hours=float(_money(incomplete_hours)), pending_hours=float(_money(pending_hours)),
            regular_hours=float(_money(min(hours, threshold))), overtime_hours=float(_money(ot)),
            gross_earnings=None if no_total else float(_money(with_ot if overtime_on else gross)),
            gross_with_overtime=None if no_total else float(_money(with_ot))))
    return rows


# ------------------------------------------------------------------ rules from the caller
RULE_ALIASES = {
    "week_start": "pay_week_start",
    "reporting_week_start": "pay_week_start",
    "commute_gap_minutes": "min_commute_gap_minutes",
    "commute_gap_threshold_minutes": "min_commute_gap_minutes",
    "min_commute_gap": "min_commute_gap_minutes",
    "max_shift_length_hours": "max_shift_hours",
}


def merge_rules(rules=None):
    """Start from the defaults and apply the rules the caller passes in (names are flexible)."""
    merged = dict(DEFAULT_RULES)
    for key, value in (rules or {}).items():
        merged[RULE_ALIASES.get(key, key)] = value if isinstance(value, str) else str(value)
    return merged


# ------------------------------------------------------------------ main function
def process_shifts(shifts, rules=None, flag_messages=None, known_locations=None, include_unconfirmed=False):
    """Check shifts, find conflicts and total the weekly gross earnings.

    rules             dict from load_rules(), defaults are used when None
    flag_messages     dict from load_flag_messages(), the plain-language worker messages
    known_locations   set from load_known_locations(). When given, an unrecognised location is flagged
    include_unconfirmed  when True, unconfirmed shifts also take part in conflict checks
    """
    rules = merge_rules(rules)
    messages = flag_messages or DEFAULT_MESSAGES
    checked = [_check_shift(s, i, rules, known_locations) for i, s in enumerate(shifts)]

    # a later shift with the same worker, date, times and location is a possible duplicate
    seen = set()
    for s in checked:
        if s["worker_id"] is None or s["day"] is None:
            seen_key = None
        else:
            seen_key = s["key"]
        if s["rejected"]:
            seen_key = None  # a rejected shift is ignored, so it never holds back its twin
        if seen_key is not None:
            if seen_key in seen:
                s["codes"].append("POSSIBLE_DUPLICATE")
            seen.add(seen_key)
        s["_loc_unknown"] = ("MISSING_LOCATION" in s["codes"]) or ("UNKNOWN_LOCATION" in s["codes"])

    results = []
    for s in checked:
        status, gross = _status_and_gross(s)
        issues = []
        for code in s["codes"]:
            flag_id, severity = ISSUE_FLAGS[code]
            issues.append(dict(code=code, flag_type_id=flag_id, flag_name=FLAG_NAMES[flag_id],
                               severity=severity, reason=REASONS[code], message=messages[flag_id]))
        paid = None if s["paid_hours"] is None else float(s["paid_hours"])
        exact = s["paid_exact"]
        reason = _earnings_reason(status, s["codes"])
        if status == "cancelled":
            paid = 0.0
        results.append(dict(
            id=s["id"], worker_id=s["worker_id"], shift_date=s["day"].strftime("%Y-%m-%d") if s["day"] else None,
            week_start=_week_start(s["day"], rules.get("pay_week_start", "monday")) if s["day"] else None, paid_hours=paid,
            _exact_hours=exact, hourly_rate=float(s["rate"]) if s["rate"] is not None else None, currency=s["currency"],
            gross_earnings=float(gross) if gross is not None else None, status=status, issues=issues,
            earnings_reason=reason))

    conflicts, not_assessed = _find_conflicts(checked, rules, messages, include_unconfirmed)
    return dict(shifts=results, conflicts=conflicts, commute_not_assessed=not_assessed,
                weekly_summary=_weekly(results, rules))


# ------------------------------------------------------------------ service entry point for the backend
def calculate_shifts(payload, flag_messages=None, known_locations=None, include_unconfirmed=False):
    """Entry point for the FastAPI backend. Takes one worker's shifts and the rules, returns the results.

    payload = {
        "worker_id": "W001",
        "shifts": [ {shift_id, employer, date, start_time, end_time, end_date, break_minutes,
                     hourly_rate, currency, location_text, confirmation_status, shift_status,
                     source_line}, ... ],
        "rules": {"pay_week_start": "monday", "min_commute_gap_minutes": 30},   # optional
        "known_locations": ["Store A", ...]                                      # optional
    }

    Returns {
        "worker_id": ...,
        "shifts": [ {shift_id, date, week_start, paid_hours, hourly_rate, currency, gross_earnings,
                     validation_status (valid, warning or invalid), earnings_status,
                     eligible_for_earnings, earnings_reason, flags: [...], source_line} ],
        "weekly_summary": [ {week_start, currency, shifts, paid_hours (eligible hours only),
                             incomplete_hours, pending_hours, gross_earnings,
                             incomplete_shifts, earnings_incomplete, cancelled_shifts} ],
        "conflicts": [...], "commute_not_assessed": [...]
    }
    Both the backend field names (employer, date, location_text) and the csv column names
    (employer_name, shift_date, location) are accepted.
    """
    worker_id = payload.get("worker_id")
    incoming = list(payload.get("shifts") or [])
    prepared = []
    for shift in incoming:
        item = dict(shift)
        if _blank(item.get("worker_id")):
            item["worker_id"] = worker_id
        prepared.append(item)

    known = known_locations
    if payload.get("known_locations"):
        known = {_norm(n) for n in payload["known_locations"]}

    result = process_shifts(prepared, payload.get("rules"), flag_messages, known, include_unconfirmed)

    shifts = []
    for original, item in zip(incoming, result["shifts"]):
        severities = {i["severity"] for i in item["issues"]}
        if "error" in severities:
            validation_status = "invalid"
        elif severities:
            validation_status = "warning"
        else:
            validation_status = "valid"
        shifts.append(dict(
            shift_id=item["id"], date=item["shift_date"], week_start=item["week_start"],
            paid_hours=item["paid_hours"], hourly_rate=item["hourly_rate"], currency=item["currency"],
            gross_earnings=item["gross_earnings"], validation_status=validation_status,
            earnings_status=item["status"], eligible_for_earnings=item["status"] == "counted",
            earnings_reason=item["earnings_reason"], flags=item["issues"],
            source_line=original.get("source_line")))

    weekly = [dict(week_start=w["pay_week_start"], currency=w["currency"], shifts=w["shifts"],
                   paid_hours=w["paid_hours"], incomplete_hours=w["incomplete_hours"],
                   pending_hours=w["pending_hours"], gross_earnings=w["gross_earnings"],
                   incomplete_shifts=w["incomplete_shifts"], earnings_incomplete=(w["incomplete_shifts"] + w["pending_shifts"]) > 0,
                   cancelled_shifts=w["cancelled_shifts"])
              for w in result["weekly_summary"]]

    return dict(worker_id=worker_id, shifts=shifts, weekly_summary=weekly,
                conflicts=result["conflicts"], commute_not_assessed=result["commute_not_assessed"])
