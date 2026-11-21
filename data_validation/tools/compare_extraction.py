"""Compare what an extractor read from the PDF and image schedules with the answer key.

Usage (from the data_validation folder):
    python3 -I tools/compare_extraction.py <extracted csv> [answer key csv] [report csv]

The extracted csv has one row per shift the extractor read, with the columns:
    file_name, shift_date, start_time, end_time, break_minutes, employer_name, location,
    department, hourly_rate, currency, shift_status
The answer key defaults to test_data/unstructured/answer_key.csv. Dates may be written as 2026-11-03,
times as 08:00 or 8:00 AM, rates as 15 or 15.00. Everything is normalised before it is compared.

Shifts are matched inside each file by date and start time. A shift in the key that has no match is
"missed". A shift that was read but is not in the key is "invented" (for example a shift of another employee).
In the answer key an empty cell means the document does not state that detail. If the extractor fills it with a
value, that is an "invented detail". If the extractor leaves empty something that is written down, that is a
"dropped detail". A dash, n/a, null, unknown or TBC counts as empty.
"money fields" are the ones that change earnings: date, start, end, break, rate and currency.
"""
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_KEY = os.path.join(ROOT, "test_data", "unstructured", "answer_key.csv")
FILES_CSV = os.path.join(ROOT, "test_data", "unstructured", "files.csv")

FIELDS = ["shift_date", "start_time", "end_time", "break_minutes", "employer_name", "location",
          "department", "hourly_rate", "currency", "shift_status"]
MONEY_FIELDS = ["shift_date", "start_time", "end_time", "break_minutes", "hourly_rate", "currency"]
EARNINGS_CRITICAL_FIELDS = [*MONEY_FIELDS, "shift_status"]


# ----------------------------------------------------------------------------- normalising
EMPTY_WORDS = {"", "-", "\u2013", "\u2014", "n/a", "na", "null", "unknown", "tbc", "?", "missing"}


def is_empty(value):
    return (value or "").strip().lower() in EMPTY_WORDS


def norm_date(value):
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%a %d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def norm_time(value):
    text = (value or "").strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return text


def norm_int(value):
    text = (value or "").strip().lower()
    if text in ("", "none", "no break"):
        return "" if text == "" else "0"
    m = re.search(r"-?\d+", text)
    return str(int(m.group())) if m else text


def norm_rate(value):
    text = re.sub(r"[^0-9.\-]", "", (value or "").strip())
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def norm_text(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


NORMALISERS = {"shift_date": norm_date, "start_time": norm_time, "end_time": norm_time, "break_minutes": norm_int,
               "hourly_rate": norm_rate, "currency": lambda v: (v or "").strip().upper(),
               "shift_status": norm_text, "employer_name": norm_text, "location": norm_text, "department": norm_text}


def normalise(row):
    return {f: "" if is_empty(row.get(f)) else NORMALISERS[f](row.get(f)) for f in FIELDS}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ----------------------------------------------------------------------------- comparing
def match_file(key_rows, got_rows):
    """Returns (pairs, missed, invented) for one file. Matches on date and start time, then on date alone."""
    unused = list(range(len(got_rows)))
    pairs, missed = [], []
    pending = []
    for k in key_rows:
        hit = next((i for i in unused if got_rows[i]["shift_date"] == k["shift_date"]
                    and got_rows[i]["start_time"] == k["start_time"]), None)
        if hit is None:
            pending.append(k)
        else:
            unused.remove(hit)
            pairs.append((k, got_rows[hit]))
    for k in pending:
        hit = next((i for i in unused if got_rows[i]["shift_date"] == k["shift_date"]), None)
        if hit is None:
            missed.append(k)
        else:
            unused.remove(hit)
            pairs.append((k, got_rows[hit]))
    return pairs, missed, [got_rows[i] for i in unused]


def compare(key_all, got_all):
    """key_all and got_all are lists of dicts with file_name. Returns a result dict."""
    key_by_file, got_by_file = defaultdict(list), defaultdict(list)
    for r in key_all:
        key_by_file[r["file_name"]].append({**normalise(r), "file_name": r["file_name"]})
    for r in got_all:
        got_by_file[r["file_name"]].append({**normalise(r), "file_name": r["file_name"]})
    per_file = {}
    for name in sorted(set(key_by_file) | set(got_by_file)):
        pairs, missed, invented = match_file(key_by_file.get(name, []), got_by_file.get(name, []))
        field_ok = {f: sum(1 for k, g in pairs if k[f] == g[f]) for f in FIELDS}
        all_ok = sum(1 for k, g in pairs if all(k[f] == g[f] for f in FIELDS))
        money_ok = sum(1 for k, g in pairs if all(k[f] == g[f] for f in MONEY_FIELDS))
        earnings_critical_ok = sum(1 for k, g in pairs if all(k[f] == g[f] for f in EARNINGS_CRITICAL_FIELDS))
        wrong = [(k, g, [f for f in FIELDS if k[f] != g[f]]) for k, g in pairs if any(k[f] != g[f] for f in FIELDS)]
        # a detail the document does not state, filled in by the extractor
        made_up = [(k, g, [f for f in FIELDS if k[f] == "" and g[f] != ""]) for k, g in pairs
                   if any(k[f] == "" and g[f] != "" for f in FIELDS)]
        # a detail that is written in the document, left empty by the extractor
        dropped = [(k, g, [f for f in FIELDS if k[f] != "" and g[f] == ""]) for k, g in pairs
                   if any(k[f] != "" and g[f] == "" for f in FIELDS)]
        per_file[name] = {"expected": len(key_by_file.get(name, [])), "matched": len(pairs), "missed": missed,
                          "invented": invented, "field_ok": field_ok, "all_ok": all_ok, "money_ok": money_ok,
                          "earnings_critical_ok": earnings_critical_ok,
                          "wrong": wrong, "made_up": made_up, "dropped": dropped}
    return per_file


def summarise(per_file):
    exp = sum(v["expected"] for v in per_file.values())
    matched = sum(v["matched"] for v in per_file.values())
    missed = sum(len(v["missed"]) for v in per_file.values())
    invented = sum(len(v["invented"]) for v in per_file.values())
    tp, fp, fn = matched, invented, missed
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"expected": exp, "matched": matched, "missed": missed,
            "invented": invented,
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6),
            "made_up_details": sum(len(f) for v in per_file.values() for _, _, f in v["made_up"]),
            "dropped_details": sum(len(f) for v in per_file.values() for _, _, f in v["dropped"]),
            "all_ok": sum(v["all_ok"] for v in per_file.values()),
            "money_ok": sum(v["money_ok"] for v in per_file.values()),
            "earnings_critical_ok": sum(v.get("earnings_critical_ok", 0) for v in per_file.values()),
            "field_ok": {f: sum(v["field_ok"][f] for v in per_file.values()) for f in FIELDS}}


def pct(a, b):
    return "n/a" if not b else f"{100.0 * a / b:.1f}%"


def load_difficulty():
    if not os.path.exists(FILES_CSV):
        return {}
    return {r["file_name"]: r["difficulty"] for r in read_csv(FILES_CSV)}


def report(per_file):
    lines = []
    total = summarise(per_file)
    lines.append("EXTRACTION CHECK")
    lines.append(f"Shifts in the answer key: {total['expected']}")
    lines.append(f"Shifts found: {total['matched']} ({pct(total['matched'], total['expected'])})")
    lines.append(f"Shifts missed: {total['missed']}")
    lines.append(f"Shifts invented (read but not in the key): {total['invented']}")
    lines.append(
        f"Shift detection (TP/FP/FN): TP={total['true_positives']}, FP={total['false_positives']}, "
        f"FN={total['false_negatives']}, Precision={100.0 * total['precision']:.1f}%, "
        f"Recall={100.0 * total['recall']:.1f}%, F1={100.0 * total['f1']:.1f}%"
    )
    lines.append(f"Details invented (the document does not state them): {total['made_up_details']}")
    lines.append(f"Details dropped (written in the document, left empty): {total['dropped_details']}")
    lines.append(f"Shifts with every field right: {total['all_ok']} ({pct(total['all_ok'], total['expected'])})")
    lines.append(f"Shifts with every money field right: {total['money_ok']} ({pct(total['money_ok'], total['expected'])})")
    lines.append(
        f"Shifts with every earnings-critical field right (including status): "
        f"{total['earnings_critical_ok']} ({pct(total['earnings_critical_ok'], total['expected'])})"
    )
    lines.append("")
    lines.append("Accuracy by field (of the shifts found):")
    for f in FIELDS:
        lines.append(f"  {f:15s} {pct(total['field_ok'][f], total['matched'])}")
    difficulty = load_difficulty()
    by_level = defaultdict(lambda: [0, 0, 0, 0])
    for name, v in per_file.items():
        lvl = difficulty.get(name, "unknown")
        by_level[lvl][0] += v["expected"]
        by_level[lvl][1] += v["matched"]
        by_level[lvl][2] += v["money_ok"]
        by_level[lvl][3] += v.get("earnings_critical_ok", 0)
    lines.append("")
    lines.append("By difficulty (shifts, found, money fields right, earnings-critical right):")
    for lvl in ("easy", "medium", "hard", "unknown"):
        if lvl in by_level:
            e, m, ok, ec = by_level[lvl]
            lines.append(
                f"  {lvl:8s} {e:3d} shifts, found {pct(m, e)}, "
                f"money fields right {pct(ok, e)}, earnings-critical right {pct(ec, e)}"
            )
    lines.append("")
    lines.append("By file:")
    for name, v in per_file.items():
        lines.append(
            f"  {name}: expected {v['expected']}, found {v['matched']}, missed {len(v['missed'])}, "
            f"invented {len(v['invented'])}, money fields right {v['money_ok']}, "
            f"earnings-critical right {v.get('earnings_critical_ok', 0)}"
        )
    problems = []
    for name, v in per_file.items():
        for k in v["missed"]:
            problems.append(f"  {name}: MISSED {k['shift_date']} {k['start_time']}-{k['end_time']}")
        for g in v["invented"]:
            problems.append(f"  {name}: INVENTED {g['shift_date']} {g['start_time']}-{g['end_time']}")
        for k, g, fields in v["wrong"]:
            def label(f):
                tag = " INVENTED DETAIL" if k[f] == "" else (" DROPPED DETAIL" if g[f] == "" else "")
                return f"{f}: expected {k[f]!r} got {g[f]!r}{tag}"
            detail = ", ".join(label(f) for f in fields)
            problems.append(f"  {name}: {k['shift_date']} {k['start_time']} wrong -> {detail}")
    lines.append("")
    lines.append("Differences to look at:" if problems else "No differences found.")
    lines.extend(problems)
    return "\n".join(lines)


def write_report_csv(per_file, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file_name", "problem", "shift_date", "start_time", "end_time", "detail"])
        for name, v in per_file.items():
            for k in v["missed"]:
                w.writerow([name, "missed", k["shift_date"], k["start_time"], k["end_time"], ""])
            for g in v["invented"]:
                w.writerow([name, "invented", g["shift_date"], g["start_time"], g["end_time"], ""])
            for k, g, fields in v["wrong"]:
                w.writerow([name, "wrong_field", k["shift_date"], k["start_time"], k["end_time"],
                            "; ".join(f"{x}: expected {k[x]} got {g[x]}" for x in fields)])
            for k, g, fields in v["made_up"]:
                w.writerow([name, "invented_detail", k["shift_date"], k["start_time"], k["end_time"],
                            "; ".join(f"{x}: document has none, got {g[x]}" for x in fields)])
            for k, g, fields in v["dropped"]:
                w.writerow([name, "dropped_detail", k["shift_date"], k["start_time"], k["end_time"],
                            "; ".join(f"{x}: expected {k[x]}" for x in fields)])


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    got = read_csv(argv[1])
    key = read_csv(argv[2] if len(argv) > 2 else DEFAULT_KEY)
    per_file = compare(key, got)
    print(report(per_file))
    if len(argv) > 3:
        write_report_csv(per_file, argv[3])
        print(f"\nDetails written to {argv[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
