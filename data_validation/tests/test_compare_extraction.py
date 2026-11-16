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
    assert len(files) == 14
    keyed = {}
    for r in key_rows():
        keyed[r["file_name"]] = keyed.get(r["file_name"], 0) + 1
    for f in files:
        assert os.path.exists(os.path.join(UNSTRUCTURED, f["folder"], f["file_name"]))
        assert keyed[f["file_name"]] == int(f["shifts"])


def test_answer_key_matches_the_clean_csv_schedules():
    files = {r["file_name"]: r["schedule_id"] for r in tool.read_csv(os.path.join(UNSTRUCTURED, "files.csv"))}
    for name, schedule_id in files.items():
        if not schedule_id.startswith("S"):   # TEAM01, MISS01 and MISS02 are written by hand, not from a csv schedule
            continue
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


def _one_shift_key():
    return [r for r in key_rows() if r["file_name"] == "img_06_chat_message.png"][:1]


def test_a_blank_hourly_rate_is_reported_as_a_mismatch():
    # QA recommendation on PR 6: the key has a valid rate, so an empty rate must never count as a match.
    key = _one_shift_key()
    assert key[0]["hourly_rate"] == "15.50"
    got = [dict(r) for r in key]
    got[0]["hourly_rate"] = ""
    file_result = tool.compare(key, got)["img_06_chat_message.png"]
    assert file_result["field_ok"]["hourly_rate"] == 0 and file_result["money_ok"] == 0
    assert file_result["wrong"][0][2] == ["hourly_rate"]
    assert "expected '15.50' got ''" in tool.report(tool.compare(key, got))


def test_a_missing_hourly_rate_column_is_reported_as_a_mismatch():
    key = _one_shift_key()
    got = [{k: v for k, v in r.items() if k != "hourly_rate"} for r in key]
    file_result = tool.compare(key, got)["img_06_chat_message.png"]
    assert file_result["field_ok"]["hourly_rate"] == 0 and file_result["all_ok"] == 0
    assert tool.summarise(tool.compare(key, got))["money_ok"] == 0


def _rows(file_name):
    return [dict(r) for r in key_rows() if r["file_name"] == file_name]


def test_hand_written_samples_have_blank_details_in_the_key():
    missing = _rows("pdf_07_missing_details.pdf")
    assert len(missing) == 6
    assert [r["break_minutes"] for r in missing] == ["30", "", "30", "30", "30", "30"]
    assert missing[2]["hourly_rate"] == "" and missing[2]["currency"] == ""      # rate not shown
    assert missing[3]["hourly_rate"] == "18.00" and missing[3]["currency"] == ""  # currency not shown
    assert missing[4]["end_time"] == "" and missing[5]["location"] == ""
    photo = _rows("img_07_photo_missing_details.jpg")
    assert [r["break_minutes"] for r in photo] == ["45", "", "45", "0"]          # the written 0 is a real 0


def test_a_team_roster_key_holds_only_the_target_workers_shifts():
    files = {r["file_name"]: r for r in tool.read_csv(os.path.join(UNSTRUCTURED, "files.csv"))}
    roster = files["pdf_06_team_roster_multi_employee.pdf"]
    assert roster["target_worker"] == "Maria Santos" and roster["shifts"] == "4"
    assert len(_rows("pdf_06_team_roster_multi_employee.pdf")) == 4


def test_filling_a_blank_detail_is_reported_as_an_invented_detail():
    key = _rows("pdf_07_missing_details.pdf")
    got = [dict(r) for r in key]
    got[1]["break_minutes"] = "0"          # the break is not in the document, 0 is made up
    got[2]["hourly_rate"] = "18.00"        # the rate is not in the document either
    got[2]["currency"] = "USD"
    result = tool.compare(key, got)["pdf_07_missing_details.pdf"]
    assert sum(len(f) for _, _, f in result["made_up"]) == 3
    assert result["dropped"] == []
    summary = tool.summarise(tool.compare(key, got))
    assert summary["made_up_details"] == 3
    text = tool.report(tool.compare(key, got))
    assert "INVENTED DETAIL" in text and "Details invented (the document does not state them): 3" in text


def test_dash_na_and_tbc_count_as_blank_and_match_a_blank_key():
    key = _rows("pdf_07_missing_details.pdf")
    got = [dict(r) for r in key]
    got[1]["break_minutes"] = "-"
    got[2]["hourly_rate"] = "n/a"
    got[2]["currency"] = "null"
    got[4]["end_time"] = "TBC"
    got[5]["location"] = "Unknown"
    summary = tool.summarise(tool.compare(key, got))
    assert summary["all_ok"] == 6 and summary["made_up_details"] == 0 and summary["dropped_details"] == 0


def test_a_written_zero_break_must_not_be_dropped_or_confused_with_a_blank():
    key = _rows("img_07_photo_missing_details.jpg")
    kept = [dict(r) for r in key]
    assert tool.summarise(tool.compare(key, kept))["all_ok"] == 4
    dropped = [dict(r) for r in key]
    dropped[3]["break_minutes"] = ""       # the 0 is written down, so leaving it empty is a mistake
    assert tool.summarise(tool.compare(key, dropped))["dropped_details"] == 1
    zero_for_blank = [dict(r) for r in key]
    zero_for_blank[1]["break_minutes"] = "0"  # a made up 0 where the document has a dash
    assert tool.summarise(tool.compare(key, zero_for_blank))["made_up_details"] == 1


def test_shifts_of_other_employees_count_as_invented_shifts():
    key = _rows("pdf_06_team_roster_multi_employee.pdf")
    got = [dict(r) for r in key]
    got.append({**key[0], "shift_date": "2026-11-17", "start_time": "09:00", "end_time": "17:00"})  # James Okoro's shift
    result = tool.compare(key, got)["pdf_06_team_roster_multi_employee.pdf"]
    assert len(result["invented"]) == 1 and result["matched"] == 4 and len(result["missed"]) == 0
    assert tool.summarise(tool.compare(key, got))["invented"] == 1


def test_the_csv_report_labels_invented_and_dropped_details(tmp_path):
    key = _rows("img_07_photo_missing_details.jpg")
    got = [dict(r) for r in key]
    got[1]["break_minutes"] = "0"
    got[3]["break_minutes"] = ""
    out = tmp_path / "differences.csv"
    tool.write_report_csv(tool.compare(key, got), str(out))
    kinds = [r["problem"] for r in tool.read_csv(str(out))]
    assert "invented_detail" in kinds and "dropped_detail" in kinds
