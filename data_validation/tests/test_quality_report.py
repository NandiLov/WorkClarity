"""Tests for the validation quality report (tools/quality_report.py).

They check the headline numbers and that the report in docs is the one the rules produce now.
Run from the data_validation folder:  python3 -m pytest tests -v
"""

import csv
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location("quality_report", os.path.join(ROOT, "tools", "quality_report.py"))
qr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qr)

DATA = qr.analyse()
SUMMARY = qr.summary(DATA)


def test_every_planted_error_raises_the_expected_flag_and_stays_out_of_earnings():
    assert SUMMARY["planted"] == 33
    assert SUMMARY["caught"] == 33
    assert SUMMARY["held_out"] == 33


def test_no_clean_shift_gets_a_missing_invalid_or_duplicate_flag():
    assert SUMMARY["clean"] == 95 and SUMMARY["false_alarms"] == 0


def test_25_errors_are_found_by_a_specific_rule_and_8_only_by_the_confirmation_step():
    assert SUMMARY["by_rule"] == 25 and SUMMARY["general_only"] == 8
    hidden = {x["error_type"] for x in DATA["errors"] if not x["by_rule"]}
    assert hidden == {"wrong_date", "stale_schedule_change", "am_pm_error", "hallucinated_shift"}


def test_if_the_worker_confirms_every_error_22_are_blocked_3_count_by_design_and_8_reach_earnings():
    assert SUMMARY["blocked_if_confirmed"] == 22
    assert SUMMARY["by_design"] == 3
    assert SUMMARY["reach_earnings"] == 8
    assert SUMMARY["blocked_if_confirmed"] + SUMMARY["by_design"] + SUMMARY["reach_earnings"] == SUMMARY["planted"]


def test_the_committed_report_and_csv_match_what_the_rules_produce_now(tmp_path):
    md, table = tmp_path / "report.md", tmp_path / "report.csv"
    qr.write_report(DATA, str(md))
    qr.write_csv(DATA, str(table))
    docs = os.path.join(ROOT, "docs")
    assert md.read_text(encoding="utf-8") == open(os.path.join(docs, "validation_quality_report.md"), encoding="utf-8").read()
    assert table.read_text(encoding="utf-8").replace("\r\n", "\n") == \
        open(os.path.join(docs, "validation_quality_report.csv"), encoding="utf-8").read().replace("\r\n", "\n")
    with open(str(table), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 33 and all(r["caught"] == "yes" for r in rows)
