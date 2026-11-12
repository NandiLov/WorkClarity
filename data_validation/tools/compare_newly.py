"""Compare Newly's own earnings rules with our validation module and our answer keys.

Usage (from the data_validation folder):
    python3 -I tools/compare_newly.py <path to Newly logic.ts> [output folder]

Part A runs the 31 clean csv files in test_data/schedule_inputs and checks the weekly gross against
expected_weekly_earnings.csv. Part B runs the 128 extracted rows (with the 33 planted errors) and
checks how many errors each side catches. Needs tsx (npm install -g tsx) to run Newly's TypeScript.
"""
import csv, io, json, os, shutil, subprocess, sys, importlib.util, tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "test_data")
SERVICE = os.path.join(os.path.dirname(ROOT), "backend", "app", "services", "shift_calculations.py")
spec = importlib.util.spec_from_file_location("shift_calculations", SERVICE)
svc = importlib.util.module_from_spec(spec); sys.modules["shift_calculations"] = svc; spec.loader.exec_module(svc)

def read(name):
    with open(os.path.join(DATA, name), newline="") as f:
        return list(csv.DictReader(f))

RULES = svc.load_rules(os.path.join(DATA, "pay_rules.csv"))
MESSAGES = svc.load_flag_messages(os.path.join(DATA, "flag_types.csv"))
KNOWN = svc.load_known_locations(os.path.join(DATA, "locations.csv"))

def run_newly(logic_ts, inputs, workdir):
    inp, outp = os.path.join(workdir, "in.json"), os.path.join(workdir, "out.json")
    with open(inp, "w") as f: json.dump(inputs, f)
    runner = os.path.join(ROOT, "tools", "newly_runner.mts")
    tsx = shutil.which("tsx")
    if not tsx:
        sys.exit("tsx was not found. Install it with: npm install -g tsx  (then open a new terminal)")
    r = subprocess.run([tsx, runner, logic_ts, inp, outp], capture_output=True, text=True, cwd=workdir)
    if r.returncode != 0:
        sys.exit("Newly runner failed:\n" + r.stderr)
    with open(outp) as f: return json.load(f)

def money(x): return None if x is None else round(float(x), 2)

# ------------------------------------------------------------------ Part A: clean csv files
def part_a(logic_ts, work):
    schedules = {r["schedule_id"]: r for r in read("schedules.csv")}
    inputs, ours = {}, {}
    for sid, s in schedules.items():
        path = os.path.join(DATA, "schedule_inputs", s["file_name"])
        text = open(path, newline="").read()
        inputs[sid] = {"csv": text}
        rows = list(csv.DictReader(io.StringIO(text)))
        shifts = [dict(r, shift_id=f"{sid}-{i+1:02d}", confirmation_status="confirmed") for i, r in enumerate(rows)]
        res = svc.calculate_shifts({"worker_id": s["worker_id"], "shifts": shifts, "rules": RULES}, MESSAGES, KNOWN)
        ours[sid] = res
    newly = run_newly(logic_ts, inputs, work)
    expected = defaultdict(dict)
    for r in read("expected_weekly_earnings.csv"):
        expected[r["schedule_id"]][(r["pay_week_start"], r["currency"])] = r
    diffs = []
    for sid in schedules:
        n = newly[sid]
        newly_w = {}
        for w in n.get("weekly", []):
            for cur, g in w["gross"].items():
                newly_w[(w["week_start"], cur)] = (g, w["counted"][cur], w["incomplete"])
            if not w["gross"]:
                newly_w[(w["week_start"], "-")] = (0.0, 0, w["incomplete"])
        ours_w = {(w["week_start"], w["currency"]): w for w in ours[sid]["weekly_summary"]}
        for key, e in expected[sid].items():
            want = money(e["expected_gross_mvp"])
            got_n = newly_w.get(key)
            got_o = ours_w.get(key)
            n_gross = got_n[0] if got_n else None
            o_gross = money(got_o["gross_earnings"]) if got_o else None
            if n_gross != want or o_gross != want:
                diffs.append(dict(schedule=sid, week=key[0], currency=key[1], expected=want, newly=n_gross, ours=o_gross,
                                  newly_incomplete=got_n[2] if got_n else None, expected_incomplete=int(e["incomplete_shifts"]),
                                  cancelled=int(e["cancelled_shifts"])))
        # a week or currency Newly shows that the answer key does not have
        for key in newly_w:
            if key not in expected[sid] and newly_w[key][0]:
                diffs.append(dict(schedule=sid, week=key[0], currency=key[1], expected=None, newly=newly_w[key][0], ours=None,
                                  newly_incomplete=newly_w[key][2], expected_incomplete=None, cancelled=None))
    return schedules, newly, ours, diffs, sum(len(v) for v in expected.values())

# ------------------------------------------------------------------ Part B: extracted rows with planted errors
def part_b(logic_ts, work):
    raw = read("raw_shifts.csv")
    by_sched = defaultdict(list)
    for r in raw: by_sched[r["schedule_id"]].append(r)
    inputs, order = {}, {}
    for sid, rows in by_sched.items():
        rows.sort(key=lambda r: int(r["line_no"]))
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["shift_date", "start_time", "end_time", "break_minutes", "employer_name", "location", "hourly_rate", "currency"])
        for r in rows:
            w.writerow([r["shift_date"], r["start_time"], r["end_time"], r["break_minutes"], r["employer_name"], r["location_text"], r["hourly_rate"], r["currency"]])
        acts = {str(i + 1): "rejected" for i, r in enumerate(rows) if r["confirmation_status"] == "rejected"}
        inputs[sid] = {"csv": buf.getvalue(), "actions": acts}
        order[sid] = rows
    newly = run_newly(logic_ts, inputs, work)
    # ours: the same rows, everything confirmed except rejected
    shaped = [dict(r, confirmation_status="rejected" if r["confirmation_status"] == "rejected" else "confirmed") for r in raw]
    ours = svc.process_shifts(shaped, RULES, MESSAGES, KNOWN, include_unconfirmed=True)
    ours_by_id = {s["id"]: s for s in ours["shifts"]}
    flags_ex = {e["error_type_id"]: e["flag_type_id"] for e in read("error_types.csv")}
    names = {e["error_type_id"]: e["error_type"] for e in read("error_types.csv")}
    rid_pos = {}
    for sid, rows in order.items():
        for i, r in enumerate(rows): rid_pos[r["raw_id"]] = (sid, i + 1)
    caught = []
    for p in read("planted_errors.csv"):
        sid, pos = rid_pos[p["raw_id"]]
        n = newly[sid]
        shift = next((s for s in n["shifts"] if s["line"] == pos + 1), None)
        skipped = any(s["line"] == pos + 1 for s in n["skipped"])
        n_flag = skipped or (shift and (shift["import_issues"] or shift["conflict_ids"] or shift["id"] in n["refused"]))
        o_flag = flags_ex[p["error_type_id"]] in {i["flag_type_id"] for i in ours_by_id[p["raw_id"]]["issues"]}
        caught.append(dict(raw_id=p["raw_id"], schedule=sid, error=names[p["error_type_id"]], newly=bool(n_flag), ours=bool(o_flag)))
    # weekly totals of the extracted rows after the worker confirms them, Newly against ours
    worker = {sid: rows[0]["worker_id"] for sid, rows in order.items()}
    ours_w = {(w["worker_id"], w["pay_week_start"], w["currency"]): w for w in ours["weekly_summary"]}
    weekly = []
    for sid, n in newly.items():
        for w in n["weekly"]:
            keys = set(w["gross"]) | {c for (wk, wd, c) in ours_w if wk == worker[sid] and wd == w["week_start"]}
            for cur in sorted(k for k in keys if k):
                o = ours_w.get((worker[sid], w["week_start"], cur))
                n_g = w["gross"].get(cur)
                o_g = money(o["gross_earnings"]) if o else None
                o_inc = o["incomplete_shifts"] if o else 0
                if n_g != o_g or w["incomplete"] != o_inc:
                    weekly.append(dict(schedule=sid, week=w["week_start"], currency=cur, newly=n_g, ours=o_g,
                                       newly_incomplete=w["incomplete"], ours_incomplete=o_inc))
    return newly, ours, caught, weekly

def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    logic_ts = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        schedules, newly_a, ours_a, diffs, total = part_a(logic_ts, work)
        newly_b, ours_b, caught, weekly_b = part_b(logic_ts, work)
    json.dump(dict(part_a_differences=diffs, part_b_planted=caught, part_b_weekly_differences=weekly_b), open(os.path.join(out_dir, "newly_comparison.json"), "w"), indent=1)
    ca = [c for c in caught if c["newly"]]; co = [c for c in caught if c["ours"]]
    print(f"Part A: {total} weekly rows in the answer key, {len(diffs)} differ for Newly or for our module")
    for d in diffs: print("  ", d)
    print(f"Part B: planted errors caught: Newly {len(ca)} of {len(caught)}, ours {len(co)} of {len(caught)}")
    print(f"Part B weekly totals of the extracted rows: {len(weekly_b)} differ")
    for d in weekly_b: print("  ", d)
    missed = defaultdict(int)
    for c in caught:
        if not c["newly"]: missed[c["error"]] += 1
    for k, v in sorted(missed.items()): print(f"   Newly misses {v} x {k}")
if __name__ == "__main__":
    main()
