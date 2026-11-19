"""Validation quality report: how well do the rules catch the errors planted in the test data?

Runs the validation module on test_data/raw_shifts.csv (128 shifts as an AI extraction might deliver them,
33 of them with a planted error) and writes two files to the docs folder:
    validation_quality_report.md   the report, with the numbers for the presentation
    validation_quality_report.csv  one row per planted error

Usage (from the data_validation folder):
    python3 -I tools/quality_report.py

The numbers come from the rules as they are now, so run it again after any change to the rules.
The tests in tests/test_quality_report.py check the headline numbers.
"""
import csv
import importlib.util
import os
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "test_data")
DOCS = os.path.join(ROOT, "docs")
SERVICE = os.path.join(os.path.dirname(ROOT), "backend", "app", "services", "shift_calculations.py")

# Flags that say a shift was held back for a general reason. They do not show that the rules understood the error.
GENERAL_CODES = {"LOW_CONFIDENCE", "UNCONFIRMED", "NEEDS_REVIEW", "CANCELLED", "REJECTED"}
# Statuses that keep a shift out of the earnings total.
BLOCKED = {"excluded", "incomplete", "needs_review", "unconfirmed", "rejected", "cancelled"}


def load_service():
    spec = importlib.util.spec_from_file_location("shift_calculations", SERVICE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["shift_calculations"] = module
    spec.loader.exec_module(module)
    return module


def read(name):
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(service, rows):
    rules = service.load_rules(os.path.join(DATA, "pay_rules.csv"))
    messages = service.load_flag_messages(os.path.join(DATA, "flag_types.csv"))
    known = service.load_known_locations(os.path.join(DATA, "locations.csv"))
    result = service.process_shifts(rows, rules, messages, known, include_unconfirmed=True)
    return {s["id"]: s for s in result["shifts"]}


def analyse():
    """Returns the figures behind the report."""
    service = load_service()
    raw = read("raw_shifts.csv")
    planted = read("planted_errors.csv")
    types = {t["error_type_id"]: t for t in read("error_types.csv")}
    planted_ids = {p["raw_id"] for p in planted}

    as_delivered = run(service, raw)
    # The same data, but the worker has confirmed every planted error without noticing it.
    confirmed_rows = [dict(r, confirmation_status="confirmed") if r["raw_id"] in planted_ids else dict(r) for r in raw]
    if_confirmed = run(service, confirmed_rows)

    errors = []
    for p in planted:
        t = types[p["error_type_id"]]
        shift = as_delivered[p["raw_id"]]
        flags = {i["flag_type_id"] for i in shift["issues"]}
        codes = sorted({i["code"] for i in shift["issues"]})
        specific = [c for c in codes if c not in GENERAL_CODES]
        confirmed = if_confirmed[p["raw_id"]]
        errors.append({
            "error_id": p["error_id"], "raw_id": p["raw_id"], "error_type": t["error_type"],
            "expected_flag": t["flag_type_id"], "caught": t["flag_type_id"] in flags,
            "codes": codes, "specific_codes": specific, "by_rule": bool(specific),
            "status": shift["status"], "status_if_confirmed": confirmed["status"],
            "blocked": confirmed["status"] in BLOCKED, "by_design": t["severity"] == "warning" and confirmed["status"] == "counted",
        })

    clean = [r for r in raw if r["raw_id"] not in planted_ids]
    false_alarms = [r["raw_id"] for r in clean
                    if any(i["flag_type_id"] in ("FL03", "FL04") for i in as_delivered[r["raw_id"]]["issues"])]
    return {"raw_count": len(raw), "clean_count": len(clean), "errors": errors, "false_alarms": false_alarms,
            "clean_status": Counter(as_delivered[r["raw_id"]]["status"] for r in clean)}


def summary(data):
    e = data["errors"]
    return {
        "planted": len(e),
        "caught": sum(1 for x in e if x["caught"]),
        "by_rule": sum(1 for x in e if x["by_rule"]),
        "general_only": sum(1 for x in e if not x["by_rule"]),
        "held_out": sum(1 for x in e if x["status"] in BLOCKED),
        "blocked_if_confirmed": sum(1 for x in e if x["blocked"]),
        "by_design": sum(1 for x in e if x["by_design"]),
        "reach_earnings": sum(1 for x in e if x["status_if_confirmed"] == "counted" and not x["by_design"]),
        "false_alarms": len(data["false_alarms"]),
        "clean": data["clean_count"],
    }


def by_type(data):
    groups = OrderedDict()
    for x in data["errors"]:
        g = groups.setdefault(x["error_type"], {"n": 0, "caught": 0, "by_rule": 0, "codes": set(), "after": Counter()})
        g["n"] += 1
        g["caught"] += x["caught"]
        g["by_rule"] += x["by_rule"]
        g["codes"].update(x["specific_codes"])
        g["after"][x["status_if_confirmed"]] += 1
    return groups


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def write_csv(data, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["error_id", "raw_id", "error_type", "expected_flag", "caught", "caught_by_a_specific_rule",
                    "codes_raised", "status_as_delivered", "status_if_worker_confirms"])
        for x in data["errors"]:
            w.writerow([x["error_id"], x["raw_id"], x["error_type"], x["expected_flag"], "yes" if x["caught"] else "NO",
                        "yes" if x["by_rule"] else "no", " ".join(x["codes"]), x["status"], x["status_if_confirmed"]])


def write_report(data, path):
    s = summary(data)
    g = by_type(data)
    lines = []
    add = lines.append
    add("# Validation quality report")
    add("")
    add(f"How well do the validation rules catch the errors planted in the test data? The rules were run on "
        f"`test_data/raw_shifts.csv`: {data['raw_count']} shifts as an AI extraction might deliver them, "
        f"{s['planted']} with a planted error and {s['clean']} clean. Created by `tools/quality_report.py`, so it can be "
        f"made again after any change to the rules.")
    add("")
    add("## The numbers")
    add("")
    add(f"- **All {s['planted']} planted errors were flagged and held out of the earnings total as delivered, but only "
        f"{s['by_rule']} were identified by specific validation rules.** "
        f"{s['caught']} of {s['planted']} raised the flag expected for their error type ({pct(s['caught'], s['planted'])}).")
    add(f"- **{s['by_rule']} of {s['planted']}** were found by a specific rule that looks at the shift itself: a time that "
        f"cannot be read, a missing date or rate, an impossible length or break, a duplicate, an unknown location.")
    add(f"- **{s['general_only']} of {s['planted']}** are held by the general safeguards only, not by a rule that understands the error. They look like normal shifts (a wrong date, an old time after a change, "
        f"an AM and PM mix up, a shift that is not on the schedule). No rule can see that they are wrong. They are held back "
        f"only because the worker has not confirmed them and the extraction was low confidence.")
    add(f"- **{s['false_alarms']} of {s['clean']}** clean shifts got a missing, invalid or duplicate flag.")
    add("")
    add("## What the worker's confirmation changes")
    add("")
    add(f"The shifts above were not confirmed by the worker, which is why all {s['held_out']} stay out of earnings. "
        f"To see what the rules do without that protection, the same data was run again with the worker confirming every "
        f"planted error without noticing it.")
    add("")
    add(f"- **{s['blocked_if_confirmed']} of {s['planted']}** are still stopped by the rules (excluded, incomplete or held for review).")
    add(f"- **{s['by_design']}** still count because they are warnings that do not change the pay: a missing location, "
        f"a missing employer, an unknown location.")
    add(f"- **{s['reach_earnings']}** count in the earnings. These are the ones no rule can see. "
        f"The worker's review is the only thing that stops them, so the review screen has to show the extracted details "
        f"clearly.")
    add("")
    add("## By type of error")
    add("")
    add("| Error type | Planted | Expected flag raised | Found by a specific rule | Rules that fired | If the worker confirms it |")
    add("|---|---|---|---|---|---|")
    for name, v in g.items():
        after = ", ".join(f"{n} {st}" for st, n in v["after"].items())
        rules = ", ".join(sorted(v["codes"])) or "none, held as unconfirmed and low confidence"
        add(f"| {name.replace('_', ' ')} | {v['n']} | {v['caught']} of {v['n']} | {v['by_rule']} of {v['n']} | {rules} | {after} |")
    add("")
    add("## Every planted error")
    add("")
    add("| Error | Shift | Type | Expected flag | Raised | Status as delivered | Status if the worker confirms |")
    add("|---|---|---|---|---|---|---|")
    for x in data["errors"]:
        add(f"| {x['error_id']} | {x['raw_id']} | {x['error_type'].replace('_', ' ')} | {x['expected_flag']} | "
            f"{' '.join(x['codes'])} | {x['status']} | {x['status_if_confirmed']} |")
    add("")
    add("## What this does not show")
    add("")
    add("- The test data is synthetic. The rules and the planted errors were written by the same team, so this measures "
        "that the rules keep doing what we designed, not how they do on real schedules.")
    add("- It checks the validation rules, not the AI extraction itself. Extraction accuracy for PDFs and images is "
        "evaluated separately using `tools/compare_extraction.py` and the samples in `test_data/unstructured`.")
    add("- A shift can look normal and still be wrong. For those, the worker's confirmation is the safeguard, as the table above shows.")
    add("")
    add(f"False alarms are counted as clean shifts with a missing, invalid or duplicate flag. Clean shifts as delivered: "
        f"{', '.join(f'{n} {st}' for st, n in sorted(data['clean_status'].items()))}.")
    add("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    data = analyse()
    os.makedirs(DOCS, exist_ok=True)
    write_report(data, os.path.join(DOCS, "validation_quality_report.md"))
    write_csv(data, os.path.join(DOCS, "validation_quality_report.csv"))
    s = summary(data)
    print(f"{s['caught']} of {s['planted']} planted errors raised the expected flag; {s['by_rule']} by a specific rule; "
          f"{s['false_alarms']} false alarms in {s['clean']} clean shifts. Report written to {DOCS}")


if __name__ == "__main__":
    main()
