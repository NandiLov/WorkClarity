import csv
import os
import random
from datetime import datetime, timedelta

random.seed(11)
OUT = os.path.join(os.getcwd(), "workclarity_synthetic_100_csv")
os.makedirs(OUT, exist_ok=True)
DATASET = "workclarity_dev"
MIN_GAP = 30
TRAVEL_DIFF_LOCATION = 30
OT_THRESHOLD = 40
OT_MULT = 1.5

# ------------------------------------------------------------------ lookups
employers = [
    ("E01", "BrightMart", "retail", 14.50),
    ("E02", "SwiftLogistics", "logistics", 15.50),
    ("E03", "Central Cafe Group", "food service", 16.00),
    ("E04", "Diner Y Co", "food service", 15.00),
    ("E05", "CityCare Hospital", "healthcare", 15.00),
    ("E06", "Wellness Clinic", "healthcare", 15.50),
    ("E07", "Harbor Grill", "food service", 20.00),
    ("E08", "Kiosk Co", "retail", 13.50),
    ("E09", "Grand Hotel", "hospitality", 18.00),
    ("E10", "FitLife", "fitness", 15.00),
    ("E11", "PackRight", "manufacturing", 15.00),
]
locations = [
    ("L01", "E01", "Store A", "Central"),
    ("L02", "E02", "Warehouse B", "East"),
    ("L03", "E03", "Cafe Central", "Central"),
    ("L04", "E02", "Night Warehouse", "East"),
    ("L05", "E01", "Retail X", "North"),
    ("L06", "E04", "Diner Y", "North"),
    ("L07", "E05", "Hospital Annex", "West"),
    ("L08", "E03", "Cafe Downtown", "West"),
    ("L09", "E02", "Warehouse", "East"),
    ("L10", "E06", "Clinic Front Desk", "South"),
    ("L11", "E07", "Restaurant Bar", "South"),
    ("L12", "E02", "Depot", "East"),
    ("L13", "E08", "Mall Kiosk", "Central"),
    ("L14", "E09", "Hotel Front", "Central"),
    ("L15", "E10", "Gym Reception", "North"),
    ("L16", "E11", "Packing Plant", "East"),
]
loc_by_name = {l[2]: l for l in locations}
dept_by_loc = {
    "Store A": "sales floor", "Warehouse B": "dispatch", "Cafe Central": "counter",
    "Night Warehouse": "dispatch", "Retail X": "sales floor", "Diner Y": "kitchen",
    "Hospital Annex": "patient support", "Cafe Downtown": "counter", "Warehouse": "inventory",
    "Clinic Front Desk": "front desk", "Restaurant Bar": "bar", "Depot": "loading",
    "Mall Kiosk": "sales floor", "Hotel Front": "front desk", "Gym Reception": "front desk",
    "Packing Plant": "packing",
}
emp_name = {}
worker_names = [
    "Ada Okoye", "Ben Carter", "Chloe Nguyen", "Dev Patel", "Elena Rossi", "Femi Adeyemi", "Grace Kim",
    "Hassan Ali", "Isla Moreno", "Jonah Brooks", "Kemi Balogun", "Liam Walsh", "Maya Singh", "Noah Pereira",
    "Olu Johnson", "Priya Shah", "Quinn Foster", "Rosa Diaz", "Sam Okafor", "Tara Lewis",
]

case_types = [
    ("CT01", "reference_overnight", "Reference example with one overnight shift, expected gross 384"),
    ("CT02", "clean_week", "Clean week with no extraction errors"),
    ("CT03", "overnight", "Overnight shifts that end the next day"),
    ("CT04", "overlap", "Two jobs with overlapping shifts"),
    ("CT05", "commute_conflict", "Shifts at different locations with too little travel time"),
    ("CT06", "incomplete", "Extraction misses values"),
    ("CT07", "schedule_change", "Shift times changed after the first version"),
    ("CT08", "ambiguous_time", "AM and PM misread"),
    ("CT09", "duplicate", "Shifts extracted twice"),
    ("CT10", "hallucinated_shift", "Extraction invents a shift"),
    ("CT11", "week_boundary", "Overnight shift crossing the pay week boundary"),
    ("CT12", "multi_rate", "Weekday and weekend rates"),
    ("CT13", "overtime", "More than 40 hours in the pay week"),
    ("CT14", "cancelled_shift", "Cancelled shifts are kept as records but not counted in projected earnings"),
    ("CT15", "missing_info", "Employer or location missing from the extracted shift"),
    ("CT16", "invalid_duration", "Extracted shift length is zero or longer than 16 hours"),
    ("CT17", "invalid_break", "Extracted break is negative or longer than the shift"),
    ("CT18", "mixed_currency", "One week with shifts in two currencies, totals kept separate"),
    ("CT19", "incomplete_earnings", "Confirmed shift without a rate, earnings shown as incomplete"),
    ("CT20", "unknown_location", "Extracted location matches no known location, commute cannot be assessed"),
    ("CT21", "review_and_rejected", "One shift sent to the review queue and one extracted shift the worker rejected, both left out of earnings"),
]
ct_id = {c[1]: c[0] for c in case_types}

error_types = [
    ("ET01", "unparseable_time", "error", "Time value cannot be parsed as HH:MM"),
    ("ET02", "missing_rate", "error", "Hourly rate missing"),
    ("ET03", "missing_end_time", "error", "End time missing"),
    ("ET04", "missing_date", "error", "Shift date missing"),
    ("ET05", "missing_break", "warning", "Break minutes missing"),
    ("ET06", "stale_schedule_change", "error", "Extraction reads the old time after a schedule change"),
    ("ET07", "am_pm_error", "error", "AM and PM misread"),
    ("ET08", "wrong_date", "error", "Date shifted to the wrong day"),
    ("ET09", "duplicate_row", "warning", "Same shift extracted twice"),
    ("ET10", "hallucinated_shift", "error", "Shift that is not on the schedule"),
    ("ET11", "missing_location", "warning", "Location missing, a warning that does not stop the shift counting"),
    ("ET12", "missing_employer", "warning", "Employer missing, a warning that does not stop the shift counting"),
    ("ET13", "invalid_duration", "error", "Shift length is zero or longer than 16 hours"),
    ("ET14", "invalid_break", "error", "Break is negative or longer than the shift"),
    ("ET15", "confirmed_missing_rate", "error", "Worker confirmed the shift but the hourly rate is missing, so earnings are incomplete"),
    ("ET16", "unknown_location", "warning", "Location text matches no known location, so travel time cannot be assessed"),
]
et_id = {e[1]: e[0] for e in error_types}

flag_types = [
    ("FL01", "overlap", "error", "These shifts happen at the same time. Please check which one is right."),
    ("FL02", "insufficient_commute", "warning", "You may not have enough time to get from one job to the next."),
    ("FL03", "missing_or_invalid", "depends on the error", "Some details of this shift are missing or look wrong. Please check them."),
    ("FL04", "duplicate", "warning", "This shift may be a duplicate. It is not counted until you check it and confirm which one is correct."),
    ("FL05", "cancelled", "info", "This shift was cancelled, so it is not counted in your estimated earnings."),
    ("FL06", "unconfirmed", "warning", "This shift has not been confirmed yet. Please review it and confirm it so it counts toward your earnings."),
]
et_flag = {
    "unparseable_time": "FL03", "missing_rate": "FL03", "missing_end_time": "FL03", "missing_date": "FL03",
    "missing_break": "FL03", "missing_location": "FL03", "missing_employer": "FL03",
    "stale_schedule_change": "FL06", "am_pm_error": "FL06", "wrong_date": "FL06", "hallucinated_shift": "FL06",
    "duplicate_row": "FL04",
    "invalid_duration": "FL03", "invalid_break": "FL03", "confirmed_missing_rate": "FL03", "unknown_location": "FL03",
}

pay_rules = [
    ("PR01", "pay_week_start", "monday", "Default reporting week starts on Monday. This is a product default, not a universal payroll rule. An overnight shift counts in the week of its start date"),
    ("PR02", "earnings_basis", "gross", "Gross pay before tax and deductions, from worker-confirmed hours and rates"),
    ("PR03", "breaks", "unpaid", "break_minutes is deducted from paid hours"),
    ("PR04", "overtime_enabled", "false", "Overtime not applied in the MVP: every hour is paid at the standard rate. Weekly output also shows an overtime figure for comparison"),
    ("PR05", "overtime_threshold_hours", str(OT_THRESHOLD), "Weekly hours above this are overtime when enabled"),
    ("PR06", "overtime_multiplier", str(OT_MULT), "Rate multiplier for overtime hours when enabled"),
    ("PR07", "max_shift_hours", "16", "Longer shifts are flagged as invalid duration"),
    ("PR08", "min_commute_gap_minutes", str(MIN_GAP), "Initial commute gap warning between shifts at different locations. This is a product default, not a universal travel time rule"),
    ("PR09", "weekend_pay_type", "weekend", "Saturday and Sunday shifts are labelled weekend"),
    ("PR10", "rounding", "2", "Round money to 2 decimal places"),
    ("PR11", "rate_source", "worker_entered", "Hourly rate is entered or confirmed by the worker"),
    ("PR12", "cancelled_shifts", "excluded_from_projected_earnings", "Cancelled shifts that were not worked are kept as records but not counted"),
    ("PR13", "cancellation_compensation", "out_of_scope", "Any pay for cancelled shifts needs separate rules and is outside the initial scope"),
    ("PR14", "test_input_format", "csv", "The MVP is tested with csv input first"),
    ("PR15", "second_mvp_format", "pdf", "PDF is the planned second input format after csv. Images are deferred"),
    ("PR16", "valid_break", "nonnegative_and_shorter_than_shift", "break_minutes must be zero or more and shorter than the shift duration, otherwise the shift is flagged as invalid"),
    ("PR17", "currency_totals", "separate_per_currency", "Weekly totals are kept per currency and never added across currencies"),
    ("PR18", "missing_rate_confirmed", "earnings_incomplete", "A confirmed shift without a rate stays visible but is left out of gross pay and counted as incomplete"),
    ("PR19", "missing_employer_or_location", "warning_not_blocking", "A missing employer or location is a warning and does not stop the shift counting, as long as the essential shift details are valid. A missing or unknown location means the commute check is unavailable, not passed"),
    ("PR20", "missing_date", "blocking_error", "A missing date is a blocking validation error under the missing or invalid flag, with a specific missing date reason"),
    ("PR21", "needs_review_and_rejected", "excluded_from_earnings", "needs_review shifts show in the review queue and are left out of final earnings until corrected and confirmed. Rejected shifts are kept for traceability but left out of the active schedule and earnings"),
    ("PR22", "earnings_source", "validated_worker_confirmed", "Earnings are calculated from validated, worker-confirmed shift data, including the worker's corrections. The original csv stays available for traceability and comparison"),
    ("PR23", "missing_break", "incomplete_until_confirmed", "A missing break is never treated as zero minutes. The shift stays visible and its earnings are incomplete until the worker confirms no break (0) or enters the break, so estimated earnings are not overstated"),
    ("PR24", "possible_duplicate", "held_for_review", "A possible duplicate is warned, and the extra copy is held for review and not counted. Final earnings never count the same shift twice before the worker resolves it"),
    ("PR25", "missing_currency", "incomplete", "A missing currency makes that shift's earnings incomplete. No total is produced without a currency, and totals are never mixed across currencies"),
]

# ------------------------------------------------------------------ schedules
# sid, worker, format, case, description, version
sched_defs = [
    ("S001", "W001", "table_image", "reference_overnight", "Reference example, expected gross 384", 1),
    ("S002", "W002", "csv_text", "clean_week", "Monday to Friday with 30 minute breaks", 1),
    ("S003", "W003", "pdf", "overnight", "Three overnight shifts with breaks", 1),
    ("S004", "W004", "table_image", "overlap", "Overlapping shifts at two jobs", 1),
    ("S005", "W005", "pdf", "commute_conflict", "10 minute gap between locations", 1),
    ("S006", "W006", "table_image", "incomplete", "Missing end time and date", 1),
    ("S007", "W007", "csv_text", "schedule_change", "First shift time changed", 2),
    ("S008", "W008", "table_image", "ambiguous_time", "AM and PM misread", 1),
    ("S009", "W009", "pdf", "duplicate", "One shift extracted twice", 1),
    ("S010", "W010", "table_image", "hallucinated_shift", "Invented shift", 1),
    ("S011", "W011", "pdf", "week_boundary", "Sunday night shift ends Monday", 1),
    ("S012", "W012", "csv_text", "multi_rate", "Weekday and weekend rates", 1),
    ("S013", "W013", "table_image", "overtime", "54 hours in the week", 1),
    ("S014", "W001", "table_image", "missing_info", "Employer and location missing on two shifts", 1),
    ("S015", "W014", "csv_text", "cancelled_shift", "Two cancelled shifts, kept but not counted", 1),
    ("S016", "W015", "pdf", "overnight", "Five overnight shifts", 1),
    ("S017", "W016", "table_image", "overlap", "Overlap on Monday", 1),
    ("S018", "W017", "pdf", "commute_conflict", "Two tight commutes", 1),
    ("S019", "W018", "table_image", "incomplete", "Several missing values", 1),
    ("S020", "W019", "csv_text", "ambiguous_time", "Three AM and PM errors", 1),
    ("S021", "W020", "pdf", "duplicate", "Two repeated shifts", 1),
    ("S022", "W002", "csv_text", "hallucinated_shift", "Invented Saturday shift", 1),
    ("S023", "W003", "table_image", "schedule_change", "Two shifts moved by one hour", 2),
    ("S024", "W004", "csv_text", "multi_rate", "Weekend rate on Saturday and Sunday", 1),
    ("S025", "W005", "pdf", "week_boundary", "Sunday night shift crossing into Monday", 1),
    ("S026", "W006", "csv_text", "invalid_duration", "One shift over 16 hours and one with equal start and end", 1),
    ("S027", "W007", "csv_text", "invalid_break", "One negative break and one break longer than the shift", 1),
    ("S028", "W008", "csv_text", "mixed_currency", "Two USD shifts and two EUR shifts in one week", 1),
    ("S029", "W009", "csv_text", "incomplete_earnings", "Confirmed shift without a rate", 1),
    ("S030", "W010", "csv_text", "unknown_location", "Second shift location matches no known location", 1),
    ("S031", "W011", "csv_text", "review_and_rejected", "One shift in the review queue and one rejected extracted shift", 1),
]
sched_defs = [(a, b, "csv_text", d, e, f) for (a, b, c, d, e, f) in sched_defs]
sched = {s[0]: s for s in sched_defs}
ext = {"table_image": "png", "csv_text": "csv", "pdf": "pdf"}

truth = []


def add(sid, date, start, end, brk, rate, loc, status="scheduled", currency="USD"):
    n = sum(1 for t in truth if t["schedule_id"] == sid) + 1
    s = sched[sid]
    l = loc_by_name[loc]
    d = datetime.strptime(date, "%Y-%m-%d")
    truth.append(dict(
        shift_id=f"{sid}-{n:02d}", schedule_id=sid, line_no=n, worker_id=s[1],
        employer_id=l[1], location_id=l[0], shift_date=date, start_time=start, end_time=end,
        break_minutes=brk, break_paid="false", hourly_rate=rate, currency=currency,
        pay_type="weekend" if d.weekday() >= 5 else "regular", shift_status=status,
        department=dept_by_loc[loc], _loc=loc))


def days(sid, dates, start, end, brk, rate, loc, status="scheduled"):
    for d in dates:
        add(sid, d, start, end, brk, rate, loc, status)


D = lambda n: f"2026-11-{n:02d}"

# week of Nov 2 (original 13 schedules, 40 shifts)
add("S001", D(3), "08:00", "16:00", 0, 15.00, "Store A")
add("S001", D(4), "09:00", "17:00", 0, 15.00, "Store A")
add("S001", D(5), "22:00", "06:00", 0, 18.00, "Warehouse B")
days("S002", [D(d) for d in range(2, 7)], "09:00", "17:00", 30, 16.50, "Cafe Central")
add("S003", D(2), "22:00", "07:00", 60, 17.00, "Night Warehouse")
add("S003", D(4), "21:30", "05:30", 30, 17.00, "Night Warehouse")
add("S003", D(6), "23:00", "07:00", 0, 17.00, "Night Warehouse")
add("S004", D(3), "08:00", "14:00", 0, 14.00, "Retail X")
add("S004", D(3), "12:00", "18:00", 0, 15.00, "Diner Y")
add("S004", D(5), "09:00", "13:00", 0, 14.00, "Retail X")
add("S005", D(4), "07:00", "12:00", 0, 15.00, "Hospital Annex")
add("S005", D(4), "12:10", "17:00", 0, 13.00, "Cafe Downtown")
add("S005", D(6), "08:00", "16:00", 30, 15.00, "Hospital Annex")
days("S006", [D(2), D(3), D(4)], "10:00", "18:00", 30, 12.00, "Warehouse")
days("S007", [D(3), D(4)], "09:00", "17:00", 30, 15.50, "Clinic Front Desk")
truth[-2]["shift_status"] = "changed"
add("S008", D(2), "17:00", "23:00", 0, 20.00, "Restaurant Bar")
add("S008", D(4), "13:00", "21:00", 30, 20.00, "Restaurant Bar")
days("S009", [D(2), D(3), D(5)], "08:00", "16:00", 30, 14.00, "Depot")
days("S010", [D(3), D(4)], "10:00", "15:00", 0, 13.50, "Mall Kiosk")
add("S011", D(2), "08:00", "16:00", 30, 18.00, "Hotel Front")
add("S011", D(8), "22:00", "06:00", 0, 18.00, "Hotel Front")
days("S012", [D(3), D(4)], "10:00", "18:00", 30, 15.00, "Gym Reception")
add("S012", D(7), "10:00", "18:00", 30, 20.00, "Gym Reception")
days("S013", [D(d) for d in range(2, 8)], "08:00", "17:00", 0, 15.00, "Packing Plant")

# week of Nov 9 (12 new schedules, 60 shifts)
days("S014", [D(d) for d in range(9, 14)], "09:00", "17:00", 30, 15.00, "Store A")
days("S015", [D(d) for d in range(9, 14)], "07:00", "15:00", 30, 16.50, "Cafe Central")
days("S016", [D(d) for d in range(9, 14)], "22:00", "06:00", 30, 17.50, "Night Warehouse")
add("S017", D(9), "08:00", "14:00", 0, 14.00, "Retail X")
add("S017", D(9), "13:00", "19:00", 0, 15.00, "Diner Y")
add("S017", D(10), "09:00", "15:00", 0, 14.00, "Retail X")
add("S017", D(11), "09:00", "15:00", 0, 14.00, "Retail X")
add("S017", D(12), "18:00", "23:00", 0, 15.00, "Diner Y")
add("S018", D(9), "07:00", "12:00", 0, 15.00, "Hospital Annex")
add("S018", D(9), "12:15", "17:00", 0, 13.00, "Cafe Downtown")
add("S018", D(11), "07:00", "12:00", 0, 15.00, "Hospital Annex")
add("S018", D(11), "12:20", "17:00", 0, 13.00, "Cafe Downtown")
add("S018", D(13), "08:00", "16:00", 30, 15.00, "Hospital Annex")
days("S019", [D(d) for d in range(9, 14)], "10:00", "18:00", 30, 12.00, "Warehouse")
days("S020", [D(d) for d in range(9, 14)], "17:00", "23:00", 0, 20.00, "Restaurant Bar")
days("S021", [D(d) for d in range(9, 14)], "08:00", "16:00", 30, 14.00, "Depot")
days("S022", [D(d) for d in range(9, 14)], "09:00", "17:00", 30, 16.50, "Cafe Central")
days("S023", [D(9), D(10)], "10:00", "18:00", 30, 15.50, "Clinic Front Desk", "changed")
days("S023", [D(11), D(12), D(13)], "09:00", "17:00", 30, 15.50, "Clinic Front Desk")
days("S024", [D(9), D(10), D(11)], "10:00", "18:00", 30, 15.00, "Gym Reception")
days("S024", [D(14), D(15)], "10:00", "18:00", 30, 20.00, "Gym Reception")
days("S025", [D(9), D(10), D(11), D(12)], "08:00", "16:00", 30, 18.00, "Hotel Front")
add("S025", D(15), "22:00", "06:00", 0, 18.00, "Hotel Front")

# week of Nov 16 (5 edge case schedules, 19 shifts)
NEW_SIDS = {"S026", "S027", "S028", "S029", "S030", "S031"}
days("S026", [D(d) for d in range(16, 20)], "09:00", "17:00", 30, 15.00, "Store A")
days("S027", [D(d) for d in range(16, 20)], "09:00", "17:00", 30, 15.00, "Store A")
add("S028", D(16), "10:00", "18:00", 30, 13.50, "Mall Kiosk")
add("S028", D(17), "10:00", "18:00", 30, 13.50, "Mall Kiosk")
add("S028", D(18), "10:00", "18:00", 30, 12.00, "Mall Kiosk", currency="EUR")
add("S028", D(19), "10:00", "18:00", 30, 12.00, "Mall Kiosk", currency="EUR")
days("S029", [D(d) for d in range(16, 20)], "08:00", "16:00", 30, 15.00, "Packing Plant")
add("S030", D(16), "07:00", "12:00", 0, 15.00, "Hospital Annex")
add("S030", D(16), "12:15", "17:00", 0, 15.00, "Hospital Annex")
add("S030", D(17), "07:00", "15:00", 30, 15.00, "Hospital Annex")
days("S031", [D(d) for d in range(16, 19)], "08:00", "16:00", 30, 15.00, "Cafe Downtown")
INCOMPLETE = {"S029-02"}


for _t in truth:
    if _t["schedule_id"] == "S015" and _t["line_no"] in (3, 5):
        _t["shift_status"] = "cancelled"


def span(date, start, end):
    s = datetime.strptime(f"{date} {start}", "%Y-%m-%d %H:%M")
    e = datetime.strptime(f"{date} {end}", "%Y-%m-%d %H:%M")
    if e <= s:
        e += timedelta(days=1)
    return s, e


for t in truth:
    s, e = span(t["shift_date"], t["start_time"], t["end_time"])
    mins = int((e - s).total_seconds() // 60)
    t["ends_next_day"] = "true" if e.date() > s.date() else "false"
    cancelled = t["shift_status"] == "cancelled"
    t["counts_toward_earnings"] = "false" if cancelled else "true"
    t["paid_hours"] = 0.0 if cancelled else round((mins - t["break_minutes"]) / 60, 2)
    t["gross_earnings"] = round(t["paid_hours"] * t["hourly_rate"], 2)
    t["verified_by"] = "generator"
    t["verified_at"] = "2026-11-04"
    t["_s"], t["_e"] = s, e

# travel minutes to next shift of the same worker
for w in {t["worker_id"] for t in truth}:
    ws = sorted([t for t in truth if t["worker_id"] == w and t["shift_status"] != "cancelled"], key=lambda x: x["_s"])
    for i, a in enumerate(ws):
        if i + 1 < len(ws):
            a["travel_minutes_to_next_shift"] = 0 if ws[i + 1]["location_id"] == a["location_id"] else TRAVEL_DIFF_LOCATION
            if ws[i + 1]["schedule_id"] in NEW_SIDS and a["schedule_id"] not in NEW_SIDS:
                a["travel_minutes_to_next_shift"] = None  # edge case weeks are separate tests
        else:
            a["travel_minutes_to_next_shift"] = None

# ------------------------------------------------------------------ schedules table
def week_start(d):
    dd = datetime.strptime(d, "%Y-%m-%d")
    return (dd - timedelta(days=dd.weekday())).strftime("%Y-%m-%d")


schedules = []
for i, s in enumerate(sched_defs):
    first = min(t["shift_date"] for t in truth if t["schedule_id"] == s[0])
    schedules.append(dict(
        schedule_id=s[0], worker_id=s[1], case_type_id=ct_id[s[3]], source_format=s[2],
        file_name=f"{s[0]}_schedule.{ext[s[2]]}", pay_week_start=week_start(first),
        schedule_version=s[5], description=s[4],
        uploaded_at=f"2026-11-01T{8 + i % 10:02d}:{(i * 7) % 60:02d}:00"))

workers = []
areas = ["North", "South", "East", "West", "Central"]
modes = ["bus", "train", "car", "walk", "bike"]
for n in range(1, 21):
    workers.append(dict(worker_id=f"W{n:03d}", worker_name=worker_names[n - 1],
                        home_area=random.choice(areas), transport_mode=random.choice(modes)))
emp_name = {e[0]: e[1] for e in employers}

# ------------------------------------------------------------------ raw extraction with planted errors
overrides = {
    ("S002", 4): (dict(end_time="17h"), "unparseable_time"),
    ("S002", 5): (dict(hourly_rate=None), "missing_rate"),
    ("S003", 3): (dict(shift_date=D(7)), "wrong_date"),
    ("S006", 2): (dict(end_time=None), "missing_end_time"),
    ("S006", 3): (dict(shift_date=None), "missing_date"),
    ("S007", 1): (dict(start_time="08:00", end_time="16:00"), "stale_schedule_change"),
    ("S008", 1): (dict(start_time="05:00"), "am_pm_error"),
    ("S008", 2): (dict(start_time="01:00"), "am_pm_error"),
    ("S012", 3): (dict(break_minutes=None), "missing_break"),
    ("S016", 3): (dict(shift_date=D(14)), "wrong_date"),
    ("S017", 4): (dict(start_time="9am"), "unparseable_time"),
    ("S019", 2): (dict(end_time=None), "missing_end_time"),
    ("S019", 4): (dict(shift_date=None), "missing_date"),
    ("S019", 5): (dict(hourly_rate=None), "missing_rate"),
    ("S020", 1): (dict(start_time="05:00"), "am_pm_error"),
    ("S020", 3): (dict(end_time="11:00"), "am_pm_error"),
    ("S020", 5): (dict(start_time="07:00"), "am_pm_error"),
    ("S023", 1): (dict(start_time="09:00", end_time="17:00"), "stale_schedule_change"),
    ("S023", 2): (dict(start_time="09:00", end_time="17:00"), "stale_schedule_change"),
    ("S024", 5): (dict(hourly_rate=None), "missing_rate"),
    ("S014", 2): (dict(location_text=""), "missing_location"),
    ("S014", 4): (dict(employer_name=""), "missing_employer"),
    ("S026", 2): (dict(end_time="02:00"), "invalid_duration"),
    ("S026", 3): (dict(end_time="09:00"), "invalid_duration"),
    ("S027", 2): (dict(break_minutes=-15), "invalid_break"),
    ("S027", 3): (dict(break_minutes=600), "invalid_break"),
    ("S029", 2): (dict(hourly_rate=None), "confirmed_missing_rate"),
    ("S030", 2): (dict(location_text="Riverside Annex"), "unknown_location"),
}
dup_keys = {("S009", 2), ("S021", 2), ("S021", 4)}
stale_old = {("S007", 1), ("S023", 1), ("S023", 2)}


def csv_line(t):
    hrs = round((t["_e"] - t["_s"]).total_seconds() / 3600, 2)
    return ",".join(str(x) for x in (t["shift_date"], t["start_time"], t["end_time"], t["break_minutes"],
                                     emp_name[t["employer_id"]], t["_loc"], t["department"],
                                     f'{t["hourly_rate"]:.2f}', t["currency"], t["shift_status"], hrs))


raw, map_rows, planted = [], [], []
rid = 0
eid = 0


def new_raw(t, over, etype, line_text, dup=False):
    global rid, eid
    rid += 1
    r = dict(raw_id=f"R{rid:03d}", schedule_id=t["schedule_id"], line_no=t["line_no"],
             worker_id=t["worker_id"], shift_date=t["shift_date"], start_time=t["start_time"],
             end_time=t["end_time"], break_minutes=t["break_minutes"], hourly_rate=t["hourly_rate"],
             location_text=t["_loc"], source_format=sched[t["schedule_id"]][2],
             file_name=f"{t['schedule_id']}_schedule.{ext[sched[t['schedule_id']][2]]}",
             source_line=line_text)
    r.update(over)
    # added fields: employer name text, department, currency, and hours printed on the document
    r["employer_name"] = emp_name[t["employer_id"]]
    r["department"] = t["department"]
    r["currency"] = t["currency"]
    r["shift_status"] = "scheduled" if etype == "stale_schedule_change" else t["shift_status"]
    r["stated_hours"] = round((t["_e"] - t["_s"]).total_seconds() / 3600, 2)
    if random.random() < 0.10:
        r["employer_name"] = random.choice([r["employer_name"].upper(), r["employer_name"] + " "])
    if random.random() < 0.08 and t["currency"] == "USD":
        r["currency"] = "$"
    # cleaning noise (not an error): casing and spacing differences in location text
    if random.random() < 0.12:
        r["location_text"] = random.choice([r["location_text"].upper(), r["location_text"].lower(), r["location_text"] + " "])
    if etype in ("missing_location", "missing_employer"):
        r.update(over)
    bad = bool(etype)
    r["extraction_confidence"] = round(random.uniform(0.40, 0.70), 2) if bad else round(random.uniform(0.90, 0.99), 2)
    r["confirmation_status"] = "unconfirmed" if (bad or random.random() < 0.07) else "confirmed"
    if etype == "confirmed_missing_rate":
        r["confirmation_status"] = "confirmed"
    r["extraction_method"] = "ai"
    r["extraction_version"] = "v0"
    sch = schedules[[s["schedule_id"] for s in schedules].index(t["schedule_id"])]
    r["extracted_at"] = sch["uploaded_at"].replace(":00", ":30", 1) if False else sch["uploaded_at"][:-2] + "30"
    raw.append(r)
    map_rows.append(dict(raw_id=r["raw_id"], shift_id=t["shift_id"]))
    if etype:
        eid += 1
        planted.append(dict(error_id=f"ER{eid:03d}", raw_id=r["raw_id"], error_type_id=et_id[etype]))
    return r


for t in truth:
    if t["schedule_id"] in NEW_SIDS:
        continue
    key = (t["schedule_id"], t["line_no"])
    over, etype = overrides.get(key, ({}, None))
    line_text = csv_line(t)
    new_raw(t, over, etype, line_text)
    if key in dup_keys:
        r2 = new_raw(t, {}, "duplicate_row", line_text)

# hallucinated shifts: no truth row
for sid, date in (("S010", D(5)), ("S022", D(14))):
    eid += 1
    rid += 1
    tt = [t for t in truth if t["schedule_id"] == sid]
    base = tt[-1]
    n = len(tt) + 1
    sch = [s for s in schedules if s["schedule_id"] == sid][0]
    r = dict(raw_id=f"R{rid:03d}", schedule_id=sid, line_no=n, worker_id=base["worker_id"], shift_date=date,
             start_time=base["start_time"], end_time=base["end_time"], break_minutes=base["break_minutes"],
             hourly_rate=base["hourly_rate"], location_text=base["_loc"], source_format=sched[sid][2],
             file_name=sch["file_name"], source_line=None, employer_name=emp_name[base["employer_id"]],
             department=base["department"], currency="USD", stated_hours=None, shift_status="scheduled",
             extraction_method="ai", extraction_version="v0",
             extraction_confidence=round(random.uniform(0.40, 0.70), 2), confirmation_status="unconfirmed", extracted_at=sch["uploaded_at"][:-2] + "30")
    raw.append(r)
    map_rows.append(dict(raw_id=r["raw_id"], shift_id=None))
    planted.append(dict(error_id=f"ER{eid:03d}", raw_id=r["raw_id"], error_type_id=et_id["hallucinated_shift"]))

# edge case schedules are extracted last so earlier raw ids stay the same
for t in truth:
    if t["schedule_id"] not in NEW_SIDS:
        continue
    key = (t["schedule_id"], t["line_no"])
    over, etype = overrides.get(key, ({}, None))
    new_raw(t, over, etype, csv_line(t))

# S031: line 2 is sent to the review queue (the true shift, not yet confirmed by the worker) and a fourth extracted
# line overlapping line 3 is rejected by the worker (no true shift behind it). They are worker states, not planted errors.
_s031 = {t["line_no"]: t for t in truth if t["schedule_id"] == "S031"}
for _r in raw:
    if _r["schedule_id"] == "S031":
        _r["confirmation_status"] = "needs_review" if _r["line_no"] == 2 else "confirmed"
        if _r["line_no"] == 2:
            _r["extraction_confidence"] = 0.62
_sch31 = [x for x in schedules if x["schedule_id"] == "S031"][0]
rid += 1
_loc = loc_by_name["Cafe Downtown"]
raw.append(dict(raw_id=f"R{rid:03d}", schedule_id="S031", line_no=4, worker_id="W011", shift_date=D(18),
                start_time="10:00", end_time="14:00", break_minutes=0, hourly_rate=15.0, location_text="Cafe Downtown",
                source_format="csv_text", file_name=_sch31["file_name"], source_line=None,
                employer_name=emp_name[_loc[1]], department=dept_by_loc["Cafe Downtown"], currency="USD",
                stated_hours=None, shift_status="scheduled", extraction_method="ai", extraction_version="v0",
                extraction_confidence=0.55, confirmation_status="rejected", extracted_at=_sch31["uploaded_at"][:-2] + "30"))
map_rows.append(dict(raw_id=f"R{rid:03d}", shift_id=None))

# ------------------------------------------------------------------ expected weekly earnings and conflicts
weekly = {}
for t in truth:
    weekly.setdefault((t["worker_id"], t["schedule_id"], week_start(t["shift_date"]), t["currency"]), []).append(t)
weekly_rows = []
_cur_count = {}
for (_w, _sid, _ws, _cur) in weekly:
    _cur_count[_sid] = _cur_count.get(_sid, 0) + 1
for (w, sid, ws, cur), items in sorted(weekly.items(), key=lambda kv: (kv[0][1], kv[0][3])):
    hours = round(sum(i["paid_hours"] for i in items), 2)
    incomplete = [i for i in items if i["shift_id"] in INCOMPLETE]
    gross = round(sum(i["gross_earnings"] for i in items if i["shift_id"] not in INCOMPLETE), 2)
    ot = round(max(hours - OT_THRESHOLD, 0), 2)
    with_ot = gross if ot == 0 else round(gross + ot * (gross / hours) * (OT_MULT - 1), 2)
    weekly_rows.append(dict(weekly_id=f"WK-{sid}" if _cur_count[sid] == 1 else f"WK-{sid}-{cur}", worker_id=w, schedule_id=sid, pay_week_start=ws, currency=cur, incomplete_shifts=len(incomplete),
                            shifts=len(items), cancelled_shifts=sum(1 for i in items if i["shift_status"] == "cancelled"), paid_hours=hours, regular_hours=min(hours, OT_THRESHOLD),
                            overtime_hours=ot, expected_gross_mvp=gross, expected_gross_with_overtime=with_ot))

conflicts = []
cid = 0
for w in sorted({t["worker_id"] for t in truth}):
    ws = sorted([t for t in truth if t["worker_id"] == w and t["shift_status"] != "cancelled"], key=lambda x: x["_s"])
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            a, b = ws[i], ws[j]
            if a["_s"] < b["_e"] and b["_s"] < a["_e"]:
                cid += 1
                conflicts.append(dict(conflict_id=f"C{cid:03d}", worker_id=w, shift_a_id=a["shift_id"],
                                      shift_b_id=b["shift_id"], conflict_type="overlap", gap_minutes=None))
            else:
                gap = int((b["_s"] - a["_e"]).total_seconds() // 60)
                if 0 <= gap < MIN_GAP and a["location_id"] != b["location_id"]:
                    cid += 1
                    conflicts.append(dict(conflict_id=f"C{cid:03d}", worker_id=w, shift_a_id=a["shift_id"],
                                          shift_b_id=b["shift_id"], conflict_type="commute_conflict", gap_minutes=gap))

# ------------------------------------------------------------------ schema definition: columns, types, keys
S, I, F, B, DT = "STRING", "INT64", "FLOAT64", "BOOL", "DATE"
TS = "TIMESTAMP"
schema = [
    ("workers", [("worker_id", S), ("worker_name", S), ("home_area", S), ("transport_mode", S)], "worker_id", []),
    ("employers", [("employer_id", S), ("employer_name", S), ("industry", S), ("default_rate", F)], "employer_id", []),
    ("locations", [("location_id", S), ("employer_id", S), ("location_name", S), ("area", S)], "location_id",
     [("employer_id", "employers", "employer_id")]),
    ("case_types", [("case_type_id", S), ("case_type", S), ("description", S)], "case_type_id", []),
    ("flag_types", [("flag_type_id", S), ("flag_name", S), ("severity", S), ("worker_message", S)], "flag_type_id", []),
    ("error_types", [("error_type_id", S), ("error_type", S), ("severity", S), ("description", S), ("flag_type_id", S)],
     "error_type_id", [("flag_type_id", "flag_types", "flag_type_id")]),
    ("pay_rules", [("rule_id", S), ("rule_name", S), ("value", S), ("description", S)], "rule_id", []),
    ("schedules", [("schedule_id", S), ("worker_id", S), ("case_type_id", S), ("source_format", S), ("file_name", S),
                   ("pay_week_start", DT), ("schedule_version", I), ("description", S), ("uploaded_at", TS)],
     "schedule_id", [("worker_id", "workers", "worker_id"), ("case_type_id", "case_types", "case_type_id")]),
    ("truth_shifts", [("shift_id", S), ("schedule_id", S), ("line_no", I), ("worker_id", S), ("employer_id", S),
                      ("location_id", S), ("department", S), ("shift_date", DT), ("start_time", S), ("end_time", S), ("ends_next_day", B),
                      ("break_minutes", I), ("break_paid", B), ("hourly_rate", F), ("currency", S), ("pay_type", S),
                      ("shift_status", S), ("counts_toward_earnings", B), ("travel_minutes_to_next_shift", I), ("paid_hours", F), ("gross_earnings", F),
                      ("verified_by", S), ("verified_at", DT)], "shift_id",
     [("schedule_id", "schedules", "schedule_id"), ("worker_id", "workers", "worker_id"),
      ("employer_id", "employers", "employer_id"), ("location_id", "locations", "location_id")]),
    ("raw_shifts", [("raw_id", S), ("schedule_id", S), ("line_no", I), ("worker_id", S), ("shift_date", S),
                    ("start_time", S), ("end_time", S), ("break_minutes", I), ("hourly_rate", F), ("location_text", S),
                    ("employer_name", S), ("department", S), ("currency", S), ("stated_hours", F), ("shift_status", S),
                    ("source_format", S), ("file_name", S), ("source_line", S), ("extraction_method", S),
                    ("extraction_version", S), ("extraction_confidence", F), ("confirmation_status", S), ("extracted_at", TS)], "raw_id",
     [("schedule_id", "schedules", "schedule_id"), ("worker_id", "workers", "worker_id")]),
    ("raw_truth_map", [("raw_id", S), ("shift_id", S)], "raw_id",
     [("raw_id", "raw_shifts", "raw_id"), ("shift_id", "truth_shifts", "shift_id")]),
    ("planted_errors", [("error_id", S), ("raw_id", S), ("error_type_id", S)], "error_id",
     [("raw_id", "raw_shifts", "raw_id"), ("error_type_id", "error_types", "error_type_id")]),
    ("expected_weekly_earnings", [("weekly_id", S), ("worker_id", S), ("schedule_id", S), ("pay_week_start", DT),
                                  ("currency", S), ("shifts", I), ("incomplete_shifts", I), ("cancelled_shifts", I), ("paid_hours", F), ("regular_hours", F), ("overtime_hours", F),
                                  ("expected_gross_mvp", F), ("expected_gross_with_overtime", F)], "weekly_id",
     [("worker_id", "workers", "worker_id"), ("schedule_id", "schedules", "schedule_id")]),
    ("expected_conflicts", [("conflict_id", S), ("worker_id", S), ("shift_a_id", S), ("shift_b_id", S),
                            ("conflict_type", S), ("gap_minutes", I)], "conflict_id",
     [("worker_id", "workers", "worker_id"), ("shift_a_id", "truth_shifts", "shift_id"),
      ("shift_b_id", "truth_shifts", "shift_id")]),
    ("shift_details", [("shift_id", S), ("schedule_id", S), ("worker_id", S), ("employer_id", S), ("location_id", S),
                       ("case_type_id", S), ("worker_name", S), ("employer_name", S), ("location_name", S),
                       ("department", S), ("shift_date", DT), ("start_time", S), ("end_time", S),
                       ("ends_next_day", B), ("break_minutes", I), ("hourly_rate", F), ("currency", S),
                       ("pay_type", S), ("shift_status", S), ("counts_toward_earnings", B), ("paid_hours", F), ("gross_earnings", F), ("case_type", S)],
     "shift_id",
     [("shift_id", "truth_shifts", "shift_id"), ("schedule_id", "schedules", "schedule_id"),
      ("worker_id", "workers", "worker_id"), ("employer_id", "employers", "employer_id"),
      ("location_id", "locations", "location_id"), ("case_type_id", "case_types", "case_type_id")]),
]

# wide reporting table built from the normalized tables, keys kept so it still joins to every table
_wn = {w["worker_id"]: w["worker_name"] for w in workers}
_ln = {l[0]: l[2] for l in locations}
_en = {e[0]: e[1] for e in employers}
_sc = {s["schedule_id"]: s for s in schedules}
_ctn = {c[0]: c[1] for c in case_types}
shift_details = []
for t in truth:
    cid = _sc[t["schedule_id"]]["case_type_id"]
    shift_details.append(dict(
        shift_id=t["shift_id"], schedule_id=t["schedule_id"], worker_id=t["worker_id"], employer_id=t["employer_id"],
        location_id=t["location_id"], case_type_id=cid, worker_name=_wn[t["worker_id"]],
        employer_name=_en[t["employer_id"]], location_name=_ln[t["location_id"]], department=t["department"],
        shift_date=t["shift_date"], start_time=t["start_time"], end_time=t["end_time"],
        ends_next_day=t["ends_next_day"], break_minutes=t["break_minutes"], hourly_rate=t["hourly_rate"],
        currency=t["currency"], pay_type=t["pay_type"], shift_status=t["shift_status"], counts_toward_earnings=t["counts_toward_earnings"],
        paid_hours=t["paid_hours"], gross_earnings=t["gross_earnings"], case_type=_ctn[cid]))

data = {
    "workers": workers,
    "employers": [dict(employer_id=a, employer_name=b, industry=c, default_rate=d) for a, b, c, d in employers],
    "locations": [dict(location_id=a, employer_id=b, location_name=c, area=d) for a, b, c, d in locations],
    "case_types": [dict(case_type_id=a, case_type=b, description=c) for a, b, c in case_types],
    "flag_types": [dict(flag_type_id=a, flag_name=b, severity=c, worker_message=d) for a, b, c, d in flag_types],
    "error_types": [dict(error_type_id=a, error_type=b, severity=c, description=d, flag_type_id=et_flag[b]) for a, b, c, d in error_types],
    "pay_rules": [dict(rule_id=a, rule_name=b, value=c, description=d) for a, b, c, d in pay_rules],
    "schedules": schedules,
    "truth_shifts": truth,
    "raw_shifts": raw,
    "raw_truth_map": map_rows,
    "planted_errors": planted,
    "expected_weekly_earnings": weekly_rows,
    "expected_conflicts": conflicts,
    "shift_details": shift_details,
}

# ------------------------------------------------------------------ write csv
for name, cols, pk, fks in schema:
    names = [c[0] for c in cols]
    with open(os.path.join(OUT, f"{name}.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=names)
        wr.writeheader()
        for r in data[name]:
            wr.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in names})

# ------------------------------------------------------------------ BigQuery DDL
ddl = [f"-- WorkClarity synthetic dataset schema for BigQuery. Keys are informational (NOT ENFORCED) but help joins and the query planner.",
       f"-- Create the dataset first: bq mk --dataset {DATASET}", ""]
for name, cols, pk, fks in schema:
    lines = [f"  {c} {t}" + (" NOT NULL" if c == pk else "") for c, t in cols]
    lines.append(f"  PRIMARY KEY ({pk}) NOT ENFORCED")
    for col, rt, rc in fks:
        lines.append(f"  CONSTRAINT fk_{name}_{col} FOREIGN KEY ({col}) REFERENCES {DATASET}.{rt}({rc}) NOT ENFORCED")
    ddl.append(f"CREATE OR REPLACE TABLE {DATASET}.{name} (\n" + ",\n".join(lines) + "\n);\n")
open(os.path.join(OUT, "schema.sql"), "w").write("\n".join(ddl))

# ------------------------------------------------------------------ integrity checks
problems = []
for name, cols, pk, fks in schema:
    ids = [r[pk] for r in data[name]]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate primary key in {name}")
    for col, rt, rc in fks:
        parents = {r[rc] for r in data[rt]}
        for r in data[name]:
            v = r.get(col)
            if v is not None and v not in parents:
                problems.append(f"{name}.{col}={v} not found in {rt}.{rc}")
        # hallucinated shifts have null shift_id by design, so only unexpected nulls matter
for r in data["truth_shifts"]:
    for col in ("schedule_id", "worker_id", "employer_id", "location_id"):
        if r[col] is None:
            problems.append("null FK in truth_shifts")

print("rows:", {n: len(data[n]) for n in data})
print("integrity problems:", problems if problems else "none")
tot = {r["schedule_id"]: r["expected_gross_mvp"] for r in weekly_rows}
print("S001 gross", tot["S001"], "S013 mvp", tot["S013"], [r["expected_gross_with_overtime"] for r in weekly_rows if r["schedule_id"] == "S013"])
print("raw rows", len(raw), "planted", len(planted), "conflicts", [(c["shift_a_id"], c["shift_b_id"], c["conflict_type"], c["gap_minutes"]) for c in conflicts])
print("worker weeks:", sum(1 for _ in weekly_rows), "shifts per pay_type:", {p: sum(1 for t in truth if t["pay_type"] == p) for p in ("regular", "weekend")})

# ------------------------------------------------------------------ README
n = {k: len(v) for k, v in data.items()}
desc = {
    "workers": ("One row per worker: name, home area, how they travel.", "Everyone, as a lookup. Names are fake."),
    "employers": ("One row per company that employs workers.", "Everyone, as a lookup."),
    "locations": ("One row per place of work. Each belongs to one employer.", "Ololade, to check commute conflicts."),
    "schedules": ("One row per uploaded schedule file: whose it is, which pay week, which file format.", "Nandila (what gets uploaded), Lavanya (which schedule is which test), Ololade."),
    "pay_rules": ("The pay and conflict rules we are assuming, such as pay week start and minimum travel gap.", "Castro owns the values. Ololade uses them in calculations."),
    "raw_shifts": ("What the AI extracted, one row per shift line, with deliberate mistakes. This is the table the validation layer reads.", "Nandila (shape of the AI output), Ololade (input to validation)."),
    "case_types": ("Names of the test scenarios, such as overnight, overlap, incomplete.", "Lavanya, to label and add test cases."),
    "error_types": ("The kinds of extraction mistake we planted, with a severity and the flag the worker sees.", "Nandila and Lavanya, to see what the AI gets wrong."),
    "truth_shifts": ("The correct shifts exactly as the schedules say, with correct hours and pay. This is the answer key.", "Lavanya (format of correct answers), Ololade (accuracy checks)."),
    "raw_truth_map": ("Links each extracted row to the correct shift it should match. An empty shift_id means the AI invented the row.", "Ololade, to measure accuracy."),
    "planted_errors": ("Which extracted rows carry which mistake.", "Ololade and Lavanya, to confirm our checks catch what we planted."),
    "expected_weekly_earnings": ("The correct weekly hours and gross pay for each schedule.", "Ololade, to confirm earnings are calculated correctly."),
    "expected_conflicts": ("The overlaps and tight commutes that should be found.", "Ololade and Castro, to agree what counts as a conflict."),
    "flag_types": ("The six kinds of flag a worker can see, each with a plain-language message.", "Castro (wording), Nandila (app display), Ololade (checks)."),
    "shift_details": ("The big table: one row per correct shift with names, locations, rates, hours and pay all in one place.", "Everyone, for reading and demos."),
}
rd = []
rd.append(f"# WorkClarity synthetic dataset ({n['truth_shifts']} shifts, csv)\n")
rd.append("## What this is\n")
rd.append(f"This is fake data that behaves like the real WorkClarity pipeline will. It has {n['truth_shifts']} correct shifts for {n['workers']} workers across {n['schedules']} schedules and three pay weeks, plus {n['raw_shifts']} rows that pretend to be what our AI extracted from those schedules. {n['planted_errors']} of the extracted rows contain deliberate mistakes. We use it to build and test validation, earnings calculations and accuracy reports before real data exists. No real person or company is in it.\n")
rd.append("Schedule S001 is the reference example: three shifts that must add up to 384.00. Every schedule is in csv format, following the kickoff decision to test the MVP with csv first. The files in schedule_inputs are the csv files a worker would upload, and csv_input_contract.md describes the structure we still need to agree. Image and pdf versions are kept in the earlier dataset for later testing.\n")
rd.append("## The story in five steps\n")
rd.append("1. A worker uploads a csv schedule.")
rd.append("2. The AI reads it and structures the shifts. Here that is raw_shifts.")
rd.append("3. The worker reviews and confirms what the AI read. Here that is the confirmation_status column.")
rd.append("4. The application validates the shifts, checks for conflicts and calculates earnings from the confirmed data.")
rd.append("5. The app shows the worker a weekly summary and calendar, with flags in plain language.\n")
rd.append("For testing we also know the right answers, so we can check every step. Those answer tables will not exist in real life.\n")
rd.append("## The tables, in plain words\n")
rd.append("For the meaning of every column, see data_dictionary.csv.\n")
groups = [
    ("Tables that will exist in the real product", ["workers", "employers", "locations", "schedules", "raw_shifts", "pay_rules", "flag_types"]),
    ("Tables that exist only for testing", ["case_types", "error_types", "truth_shifts", "raw_truth_map", "planted_errors", "expected_weekly_earnings", "expected_conflicts"]),
    ("The one big table for reading", ["shift_details"]),
]
for title, names in groups:
    rd.append(f"### {title}\n")
    rd.append("| Table | Rows | What one row is | Who uses it |")
    rd.append("| --- | ---: | --- | --- |")
    for nm in names:
        rd.append(f"| {nm} | {n[nm]} | {desc[nm][0]} | {desc[nm][1]} |")
    rd.append("")
rd.append("Note: schedules carries a case_type_id label, which is a test label. A real schedule would not have it.\n")
rd.append("## Why the data is split into several tables\n")
rd.append("- **Each fact is stored once.** BrightMart's name lives in one row of employers. Every shift points to it with an employer_id. If a name changes, we fix one row, not thousands, and no two copies can disagree.")
rd.append("- **Each table has one owner.** The AI writes only raw_shifts. Castro decides pay_rules. The data layer writes the checked results. Nobody overwrites anybody else's work.")
rd.append("- **The AI output stays untouched.** We keep exactly what the AI returned so we can measure how accurate it was. If cleaned values replaced it, that measurement would be lost.")
rd.append("- **The answer key stays separate.** Validation must never be able to see the right answers, or the test would be meaningless.")
rd.append("- **Sensitive details are easy to protect.** Names and pay rates sit in their own tables, so the app or a dashboard can be given access to only what it needs.\n")
rd.append("## How the tables connect\n")
rd.append("Every table has a primary key, a column whose value is unique in that table, such as worker_id in workers. A foreign key is a column in another table that holds those same values and points back to the original row. This is how tables join. Examples: truth_shifts.worker_id points to workers.worker_id, and truth_shifts.location_id points to locations.location_id.\n")
rd.append("| Table | Primary key | Foreign keys |")
rd.append("| --- | --- | --- |")
for name, cols, pk, fks in schema:
    fk_text = ", ".join(f"{c} to {rt}.{rc}" for c, rt, rc in fks) or "none"
    rd.append(f"| {name} | {pk} | {fk_text} |")
rd.append("")
rd.append("To compare the AI with the right answer: raw_shifts joins raw_truth_map on raw_id, then truth_shifts on shift_id.\n")
rd.append("## Why we also kept one big table\n")
rd.append("Small tables are best for storing data, but they are tiring to read, because one question needs five joins. shift_details solves this: one row per correct shift with the worker name, employer, location, department, hours and pay already included. It keeps every key (shift_id, schedule_id, worker_id, employer_id, location_id, case_type_id), so it can still be joined to any other table.\n")
rd.append("Think of the small tables as the filing cabinet and shift_details as the summary sheet on your desk. Rebuild the sheet from the cabinet whenever the cabinet changes. Never edit the sheet by hand.\n")
rd.append("In the real product the app will read finished tables like this one, so it needs simple queries and no joins, while the pipeline keeps writing to the small tables.\n")
rd.append("## What this means for each person\n")
rd.append("**Nandila (AI extraction and implementation).** csv_input_contract.md is the csv structure I propose for the MVP test, and schedule_inputs holds 31 example csv files in that structure. raw_shifts shows the output shape I assumed for the AI step, including confirmation_status for the worker review. Please compare both with what you are building and tell me what differs. error_types lists the kinds of mistake I planted so you can see which ones your extraction should avoid.\n")
rd.append("**Castro (product and user experience).** pay_rules now reflects your recommendations: gross pay from confirmed hours and worker-entered rates after unpaid breaks, overtime not applied, cancelled shifts kept as records but not counted, and cancellation pay out of scope. The pay week start and the 30 minute travel gap are still my assumptions, so please confirm them. flag_types holds the six flags you listed, each with a plain-language message for the worker. Please edit the wording. expected_conflicts shows the overlaps and tight commutes the app should flag.\n")
rd.append("**Lavanya (testing).** truth_shifts is the format of the correct answers, and case_types lists the scenarios we cover: overnight, overlap, commute, incomplete, schedule change, ambiguous time, duplicate, invented shift, week boundary, multiple rates, overtime, cancelled shifts and missing employer or location. Add your own test schedules as csv files like the ones in schedule_inputs, with the correct answers in the truth_shifts format and a case type for each. planted_errors shows which extracted rows are wrong and how.\n")
rd.append("**Ololade (data validation and earnings).** The small tables load into BigQuery, validation reads raw_shifts, and the expected tables let me confirm that every check and calculation is right. The accuracy report compares raw_shifts with truth_shifts.\n")
rd.append("**The whole team.** We all work from the same fake data, the same keys and the same assumptions, so we can find disagreements about field names or pay rules now and not during the build. Every assumption is written down, and anything we change is one edit and a rerun of the generator script.\n")
rd.append("## Things worth knowing\n")
rd.append("- raw_shifts keeps dates and times as text so malformed values still load, such as an end time written as 17h.")
rd.append("- raw_shifts has no shift_id on purpose. The AI would not know the answer. The link exists only in raw_truth_map.")
rd.append("- stated_hours is an optional csv column with the shift length before breaks. Validation can compare it with the length calculated from the start and end times.")
rd.append("- About 1 in 8 location texts, 1 in 10 employer names and 1 in 12 currency values have different casing, spacing or symbols. These are cleaning cases, not planted errors, so standardize them in the staging step.")
rd.append("- worker_name lives only in workers. Shift tables use worker_id so personal details stay in one place.")
rd.append("- Pay rules marked as assumptions (pay week start and the travel gap) still need the team's confirmation. Overtime is not applied in the MVP.")
rd.append("- Cancelled shifts stay in the data as records. They have counts_toward_earnings set to false and a gross_earnings of 0.00, so projected earnings leave them out.")
rd.append("- confirmation_status in raw_shifts shows whether the worker has confirmed what the AI read: confirmed, unconfirmed, needs_review or rejected. Only confirmed rows count toward earnings. S031 has one needs_review row and one rejected row. The truth answer key for S031 has the three real shifts (337.50), and the module should give 225.00 until the worker corrects and confirms the needs_review shift. The rejected row has no true shift behind it and is not a planted error.")
rd.append("- Hourly rates are worker-entered or worker-confirmed. They are in the test files so earnings can be tested.")
rd.append("- Schedules S026 to S031 are edge cases: a shift over 16 hours or with equal start and end (S026), a negative break and a break longer than the shift (S027), two currencies in one week (S028), a confirmed shift without a rate (S029), a location that matches nothing known (S030) and a shift in the review queue plus a rejected shift (S031). The rules behind them, PR16 to PR18, are assumptions for Castro to confirm.")
rd.append("- expected_weekly_earnings has one row per schedule and currency. Totals are never added across currencies. incomplete_shifts counts confirmed shifts left out of gross pay because the rate is missing.")
rd.append("- schema.sql creates every table with unenforced keys. It has not been run against BigQuery yet, so run it once and fix any message.\n")
rd.append("## Load into BigQuery (optional)\n")
rd.append("The app itself will use Python and Firestore, so this step is only for accuracy reports and dashboards. The Python validation module can read the csv files directly.\n")
rd.append("1. Create the dataset: `bq mk --dataset workclarity_dev`")
rd.append("2. Run schema.sql in BigQuery Studio. This creates the empty tables with their keys.")
rd.append("3. Load each CSV into its table, parents first: workers, employers, locations, case_types, flag_types, error_types, pay_rules, schedules, then truth_shifts, raw_shifts, raw_truth_map, planted_errors, expected_weekly_earnings, expected_conflicts and shift_details.")
rd.append("   Example: `bq load --source_format=CSV --skip_leading_rows=1 workclarity_dev.truth_shifts truth_shifts.csv`")
rd.append("4. Check the counts match the table above.")
open(os.path.join(OUT, "README.md"), "w").write("\n".join(rd) + "\n")


# ------------------------------------------------------------------ data dictionary (plain meaning of every column)
col_desc = {
    "worker_id": "Unique ID of the worker, for example W001",
    "worker_name": "Worker name (fake)",
    "home_area": "Area of the city where the worker lives",
    "transport_mode": "How the worker usually travels: bus, train, car, walk or bike",
    "employer_id": "Unique ID of the employer, for example E01",
    "employer_name": "Name of the employer company",
    "industry": "Type of business, for example retail or healthcare",
    "default_rate": "Typical hourly rate at this employer",
    "location_id": "Unique ID of the place of work, for example L01",
    "location_name": "Name of the place of work",
    "area": "Area of the city where the location is",
    "case_type_id": "ID of the test scenario, for example CT04",
    "case_type": "Name of the test scenario, for example overlap",
    "error_type_id": "ID of the kind of extraction mistake",
    "error_type": "Name of the kind of extraction mistake",
    "severity": "How serious the mistake is: error or warning",
    "rule_id": "Unique ID of the pay or conflict rule",
    "rule_name": "Name of the rule",
    "value": "Value of the rule, for example monday or 30",
    "schedule_id": "Unique ID of the uploaded schedule, for example S001",
    "source_format": "Format of the uploaded schedule. Every schedule in this set is csv_text",
    "file_name": "Name of the uploaded schedule file",
    "pay_week_start": "Date the pay week begins (a Monday)",
    "schedule_version": "Version number of the schedule, 2 or more means it was changed",
    "uploaded_at": "When the schedule was uploaded",
    "shift_id": "Unique ID of the correct shift, for example S001-01",
    "line_no": "Position of the shift line inside its schedule",
    "department": "Team or area the worker is in, for example kitchen or front desk",
    "shift_date": "Date the shift starts",
    "start_time": "Shift start time, 24 hour HH:MM",
    "end_time": "Shift end time, 24 hour HH:MM. Earlier than start means the shift ends the next day",
    "ends_next_day": "true if the shift ends on the day after it starts",
    "break_minutes": "Unpaid break in minutes",
    "break_paid": "true if the break is paid",
    "hourly_rate": "Pay per hour",
    "currency": "Currency of the rate, for example USD",
    "pay_type": "regular or weekend",
    "shift_status": "scheduled, changed or cancelled",
    "travel_minutes_to_next_shift": "Minutes needed to travel to the worker's next shift (0 if same location, empty for the last shift)",
    "paid_hours": "Hours paid: shift length minus the unpaid break",
    "gross_earnings": "Gross pay for the shift before tax and deductions: paid hours times hourly rate. 0.00 for cancelled shifts",
    "verified_by": "Who confirmed the correct answer (generator for synthetic data)",
    "verified_at": "Date the answer was confirmed",
    "raw_id": "Unique ID of one extracted row",
    "location_text": "Location as the AI wrote it, may differ in casing or spacing",
    "stated_hours": "Optional shift length from the csv, before breaks, used as a cross-check",
    "source_line": "The original schedule line the row came from",
    "extraction_method": "How the row was produced, ai for all synthetic rows",
    "extraction_version": "Version of the extraction method",
    "extraction_confidence": "How sure the AI was, from 0 to 1",
    "extracted_at": "When the row was extracted",
    "error_id": "Unique ID of one planted mistake",
    "weekly_id": "Unique ID of the weekly result",
    "shifts": "Number of shifts in the week",
    "regular_hours": "Hours up to the overtime threshold",
    "overtime_hours": "Hours above the overtime threshold",
    "expected_gross_mvp": "Correct gross pay for the week with overtime switched off",
    "expected_gross_with_overtime": "Correct gross pay for the week if overtime applied",
    "conflict_id": "Unique ID of the conflict",
    "shift_a_id": "First shift in the conflict",
    "shift_b_id": "Second shift in the conflict",
    "conflict_type": "overlap or commute_conflict",
    "counts_toward_earnings": "false for cancelled shifts, which are kept as records but not counted in projected earnings",
    "cancelled_shifts": "Number of cancelled shifts in the week, not counted in pay",
    "confirmation_status": "confirmed, unconfirmed, needs_review (in the review queue) or rejected (kept for traceability, not in the schedule or earnings)",
    "flag_type_id": "ID of the flag shown to the worker",
    "flag_name": "Name of the flag: overlap, insufficient_commute, missing_or_invalid, duplicate, cancelled or unconfirmed",
    "worker_message": "Plain-language message shown to the worker",
    "gap_minutes": "Minutes between the two shifts, for commute conflicts",
    "incomplete_shifts": "Number of confirmed shifts left out of gross pay because the rate is missing",
}
table_override = {
    ("case_types", "description"): "What the test scenario covers",
    ("error_types", "description"): "What the mistake means",
    ("pay_rules", "description"): "Plain explanation of the rule",
    ("schedules", "description"): "Short note on what the schedule is for",
    ("raw_shifts", "shift_date"): "Date as the AI wrote it, text. Empty if missed",
    ("raw_shifts", "start_time"): "Start time as the AI wrote it, text. May be wrong or malformed",
    ("raw_shifts", "end_time"): "End time as the AI wrote it, text. May be wrong, malformed or empty",
    ("raw_shifts", "break_minutes"): "Break as the AI wrote it. Empty if missed",
    ("raw_shifts", "hourly_rate"): "Rate as the AI wrote it. Empty if missed",
    ("raw_shifts", "currency"): "Currency as the AI wrote it, USD or the $ symbol",
    ("raw_shifts", "employer_name"): "Employer as the AI wrote it, casing may differ",
    ("raw_shifts", "worker_id"): "Worker the schedule belongs to",
    ("raw_truth_map", "shift_id"): "Correct shift this row should match. Empty if the AI invented the row",
    ("raw_truth_map", "raw_id"): "Extracted row",
    ("planted_errors", "raw_id"): "Extracted row that carries the mistake",
    ("expected_weekly_earnings", "paid_hours"): "Correct paid hours for the week",
    ("expected_weekly_earnings", "worker_id"): "Worker the week belongs to",
    ("expected_conflicts", "worker_id"): "Worker who has the conflict",
    ("flag_types", "severity"): "error, warning or info",
    ("expected_weekly_earnings", "currency"): "Currency of this row. Totals are kept per currency and never mixed",
    ("expected_weekly_earnings", "expected_gross_mvp"): "Correct gross pay for the week with overtime switched off, from shifts that have a rate. Shifts counted in incomplete_shifts are left out",
    ("raw_shifts", "shift_status"): "Status as the AI read it: scheduled, changed or cancelled",
    ("raw_shifts", "location_text"): "Location as the AI wrote it, casing may differ, empty if missed",
}
dd_rows = []
for name, cols, pk, fks in schema:
    fkmap = {c: f"{rt}.{rc}" for c, rt, rc in fks}
    first = data[name][0] if data[name] else {}
    for c, t in cols:
        key = "primary key" if c == pk else (f"foreign key to {fkmap[c]}" if c in fkmap else "")
        if c == pk and c in fkmap:
            key = f"primary key, foreign key to {fkmap[c]}"
        ex = first.get(c)
        dd_rows.append(dict(table=name, column=c, type=t, key=key,
                            meaning=table_override.get((name, c), col_desc.get(c, "")),
                            example="" if ex is None else ex))
with open(os.path.join(OUT, "data_dictionary.csv"), "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=["table", "column", "type", "key", "meaning", "example"])
    wr.writeheader()
    wr.writerows(dd_rows)
missing = [r["table"] + "." + r["column"] for r in dd_rows if not r["meaning"]]
print("dictionary rows", len(dd_rows), "missing meanings", missing)


# ------------------------------------------------------------------ csv input files and contract
inp_dir = os.path.join(OUT, "schedule_inputs")
os.makedirs(inp_dir, exist_ok=True)
CSV_HEADER = "shift_date,start_time,end_time,break_minutes,employer_name,location,department,hourly_rate,currency,shift_status,stated_hours"
for s_ in schedules:
    lines = [csv_line(t) for t in truth if t["schedule_id"] == s_["schedule_id"]]
    with open(os.path.join(inp_dir, s_["file_name"]), "w", newline="") as f:
        f.write(CSV_HEADER + "\n" + "\n".join(lines) + "\n")
with open(os.path.join(OUT, "csv_upload_template.csv"), "w", newline="") as f:
    lines = [csv_line(t) for t in truth if t["schedule_id"] == "S001"]
    f.write(CSV_HEADER + "\n" + "\n".join(lines) + "\n")

CONTRACT = """# CSV input contract (draft for the MVP test)

Status: proposed by Ololade. Nandila and Castro to confirm or change.

One csv file is one worker's schedule for one pay week. The first row is the header, the file is UTF-8 and the separator is a comma. See csv_upload_template.csv for a working example and the schedule_inputs folder for 31 more.

## Columns

| Column | Required | Format | Example | Notes |
| --- | --- | --- | --- | --- |
| shift_date | Yes | YYYY-MM-DD | 2026-11-05 | The date the shift starts |
| start_time | Yes | HH:MM, 24 hour | 22:00 | |
| end_time | Yes | HH:MM, 24 hour | 06:00 | Earlier than start_time means the shift ends the next day |
| break_minutes | No | Whole number | 30 | Unpaid break. Blank is flagged because the break is unknown |
| employer_name | Yes | Text | Warehouse B Co | Used to tell shifts from different companies apart |
| location | Yes | Text | Warehouse B | Used for commute checks |
| department | No | Text | dispatch | |
| hourly_rate | Yes for earnings | Number | 18.00 | Entered or confirmed by the worker. If a real upload has no rate, the app asks the worker |
| currency | Yes | Currency code | USD | |
| shift_status | No | scheduled, changed or cancelled | cancelled | Blank means scheduled |
| stated_hours | No | Number | 8 | Shift length before breaks, used only as a cross-check |

## Rules

- Cancelled shifts are kept as records and left out of projected earnings.
- Gross earnings are paid hours multiplied by the hourly rate, where paid hours are the shift length minus the unpaid break.
- Overtime is not applied in the MVP.
- Anything missing, unreadable or unconfirmed is flagged for the worker in plain language. See flag_types.csv for the six flags.

## Questions to confirm

- Are these the column names and formats the AI step will receive and return?
- Is one worker per file right, or should the file have a worker_id column?
- Which second format do we add after csv?
"""
open(os.path.join(OUT, "csv_input_contract.md"), "w").write(CONTRACT)
print("input files:", len(os.listdir(inp_dir)))
