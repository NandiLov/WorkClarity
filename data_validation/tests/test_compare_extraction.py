"""Tests for the extraction comparison tool and the PDF and image sample set.

Run from the data_validation folder:  python3 -m pytest tests -v
"""

import csv
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNSTRUCTURED = os.path.join(ROOT, "test_data", "unstructured")

_spec = importlib.util.spec_from_file_location("compare_extraction", os.path.join(ROOT, "tools", "compare_extraction.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def key_rows():
    return tool.read_csv(os.path.join(UNSTRUCTURED, "answer_key.csv"))


def test_every_sample_file_exists_and_has_answer_key_rows():
    files = tool.read_csv(os.path.join(UNSTRUCTURED, "files.csv"))
    assert len(files) == 11
    keyed = {}
    for r in key_rows():
        keyed[r["file_name"]] = keyed.get(r["file_name"], 0) + 1
    for f in files:
        assert os.path.exists(os.path.join(UNSTRUCTURED, f["folder"], f["file_name"]))
        assert keyed[f["file_name"]] == int(f["shifts"])


def test_answer_key_matches_the_clean_csv_schedules():
    files = {r["file_name"]: r["schedule_id"] for r in tool.read_csv(os.path.join(UNSTRUCTURED, "files.csv"))}
    for name, schedule_id in files.items():
        source = tool.read_csv(os.path.join(ROOT, "test_data", "schedule_inputs", f"{schedule_id}_schedule.csv"))
        key = [r for r in key_rows() if r["file_name"] == name]
        assert [(r["shift_date"], r["start_time"], r["end_time"], r["hourly_rate"]) for r in key] == \
               [(r["shift_date"], r["start_time"], r["end_time"], r["hourly_rate"]) for r in source]


def test_a_perfect_extraction_scores_everything_right():
    result = tool.summarise(tool.compare(key_rows(), key_rows()))
    total = len(key_rows())
    assert result["expected"] == total and result["matched"] == total
    assert result["all_ok"] == total and result["missed"] == 0 and result["invented"] == 0


def test_formats_are_normalised_before_comparing():
    key = [{"file_name": "a.pdf", "shift_date": "2026-11-03", "start_time": "22:00", "end_time": "07:00",
            "break_minutes": "60", "employer_name": "Swift Logistics", "location": "Night Warehouse",
            "department": "dispatch", "hourly_rate": "17.00", "currency": "USD", "shift_status": "scheduled"}]
    got = [{"file_name": "a.pdf", "shift_date": "3 Nov 2026", "start_time": "10:00 PM", "end_time": "7:00 AM",
            "break_minutes": "60 minutes", "employer_name": "swift  logistics", "location": "Night Warehouse",
            "department": "Dispatch", "hourly_rate": "17", "currency": "usd", "shift_status": "Scheduled"}]
    assert tool.summarise(tool.compare(key, got))["all_ok"] == 1


def test_wrong_missed_and_invented_shifts_are_counted():
    key = key_rows()
    got = [dict(r) for r in key if r["file_name"] == "pdf_02_table_week.pdf"]
    expected_in_file = len(got)
    got[0]["end_time"] = "18:00"                       # one wrong field
    missing = got.pop()                                  # one shift not read
    got.append({**got[0], "shift_date": "2026-11-20", "start_time": "09:00"})  # one invented shift
    per_file = tool.compare([r for r in key if r["file_name"] == "pdf_02_table_week.pdf"], got)
    file_result = per_file["pdf_02_table_week.pdf"]
    assert file_result["expected"] == expected_in_file
    assert len(file_result["missed"]) == 1 and file_result["missed"][0]["shift_date"] == missing["shift_date"]
    assert len(file_result["invented"]) == 1
    assert file_result["all_ok"] == expected_in_file - 2     # the wrong one and the missed one
    assert file_result["field_ok"]["end_time"] == expected_in_file - 2


def test_report_text_lists_the_differences():
    key = [r for r in key_rows() if r["file_name"] == "img_01_screenshot_clean.png"]
    got = [dict(r) for r in key]
    got[0]["hourly_rate"] = "16.00"
    text = tool.report(tool.compare(key, got))
    assert "expected '15.00' got '16.00'" in text and "Differences to look at" in text
