"""Builds a second set of PDF and image schedules that the extraction prompt has never been tuned on.

The first set (test_data/unstructured) was used while the extraction prompt was written, so a result on it is
"in sample". This set uses other layouts, other employers and other weeks, and its answer key is written by hand
below, so it is a fairer check of how the extractor does on schedules it has not seen.

Usage (from the data_validation folder):
    python3 -I generator/generate_unseen_samples.py

It needs reportlab, Pillow and numpy (the same as generate_unstructured_samples.py). The output is repeatable.
It writes test_data/unstructured_unseen/: pdf and images folders, answer_key.csv, files.csv and README.md.
Check it the same way as the first set:
    python3 -I tools/compare_extraction.py extracted.csv test_data/unstructured_unseen/answer_key.csv
"""
import csv
import os
import numpy as np
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_unstructured_samples as g  # noqa: E402  (the drawing helpers are shared)

from PIL import Image, ImageDraw  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

OUT = os.path.join(g.ROOT, "test_data", "unstructured_unseen")
KEY_FIELDS = g.KEY_FIELDS
S = g._shift


def hmm(minutes):
    return f"{int(minutes) // 60}:{int(minutes) % 60:02d}"


def worked_hours(r):
    start = datetime.strptime(r["start_time"], "%H:%M")
    end = datetime.strptime(r["end_time"], "%H:%M")
    minutes = (end - start).seconds // 60
    return (minutes - int(r["break_minutes"] or 0)) / 60


# ----------------------------------------------------------------------------- the answer key
def u01():
    a = ("Northside Books", "Retail X", "shop floor")
    return [S("2026-11-09", "06:30", "14:30", "30", *a, "17.25", "USD"),
            S("2026-11-11", "06:30", "14:30", "30", *a, "17.25", "USD"),
            S("2026-11-12", "13:00", "21:15", "45", *a, "17.25", "USD"),
            S("2026-11-14", "08:00", "12:30", "0", *a, "17.25", "USD")]


def u02():
    a = ("Parkway Pharmacy", "Mall Kiosk", "counter")
    return [S("2026-11-09", "09:00", "17:00", "30", *a, "15.80", "USD"),
            S("2026-11-10", "09:00", "17:00", "30", *a, "15.80", "USD"),
            S("2026-11-12", "12:00", "20:00", "30", *a, "15.80", "USD"),
            S("2026-11-16", "10:00", "18:00", "30", *a, "15.80", "USD"),
            S("2026-11-17", "10:00", "18:00", "30", *a, "15.80", "USD", "cancelled"),
            S("2026-11-19", "14:00", "22:00", "30", *a, "15.80", "USD")]


def u03():
    a = ("Sunrise Care Home", "Hospital Annex", "carer")
    return [S("2026-11-16", "07:00", "15:00", "45", *a, "14.50", "USD"),
            S("2026-11-17", "07:00", "15:00", "45", *a, "14.50", "USD"),
            S("2026-11-18", "14:00", "22:00", "30", *a, "14.50", "USD"),
            S("2026-11-20", "07:00", "11:00", "0", *a, "14.50", "USD"),
            S("2026-11-21", "22:00", "06:00", "45", *a, "14.50", "USD")]


def u04():
    q = ("Quickserve Foods", "Diner Y", "kitchen")
    f = ("Anchor Freight", "Depot", "loading")
    return [S("2026-11-16", "16:00", "23:00", "30", *q, "13.50", "USD"),
            S("2026-11-18", "17:00", "00:00", "30", *q, "13.50", "USD", "changed"),
            S("2026-11-20", "16:00", "23:00", "30", *q, "13.50", "USD"),
            S("2026-11-21", "06:00", "14:00", "30", *f, "16.00", "USD")]


def u05():
    """Ada Okoye's shifts (the answer) and everyone else's (printed, but not hers)."""
    r = ("Ridgeway Events", "Hotel Front", "banquets")
    ada = [S("2026-11-23", "18:00", "02:00", "30", *r, "15.00", "USD", worker_name="Ada Okoye"),
           S("2026-11-25", "18:00", "02:00", "30", *r, "15.00", "USD", worker_name="Ada Okoye"),
           S("2026-11-27", "16:00", "00:00", "30", *r, "15.00", "USD", worker_name="Ada Okoye"),
           S("2026-11-28", "12:00", "20:00", "0", *r, "15.00", "USD", worker_name="Ada Okoye")]
    others = [S("2026-11-23", "07:00", "15:00", "30", *r, "14.00", "USD", worker_name="Ada Okonkwo"),
              S("2026-11-23", "18:00", "02:00", "30", *r, "15.00", "USD", worker_name="Ben Fraser"),
              S("2026-11-24", "12:00", "20:00", "30", *r, "15.00", "USD", worker_name="Ben Fraser"),
              S("2026-11-24", "07:00", "15:00", "30", *r, "14.00", "USD", worker_name="Ada Okonkwo"),
              S("2026-11-25", "12:00", "20:00", "30", *r, "14.00", "USD", worker_name="Ada Okonkwo"),
              S("2026-11-27", "16:00", "00:00", "30", *r, "15.00", "USD", worker_name="Ben Fraser"),
              S("2026-11-28", "12:00", "20:00", "0", *r, "14.00", "USD", worker_name="Ada Okonkwo")]
    drawn = sorted(ada + others, key=lambda x: (x["shift_date"], x["worker_name"]))
    return ada, drawn


def u06():
    a = ("Anchor Freight", "Depot", "loading")
    return [S("2026-11-23", "06:00", "14:00", "30", *a, "16.00", "USD"),
            S("2026-11-24", "06:00", "14:00", "0", *a, "16.00", "USD"),
            S("2026-11-26", "06:00", "14:00", "", *a, "16.00", "USD"),
            S("2026-11-27", "06:00", "14:00", "30", *a, "", ""),
            S("2026-11-29", "10:00", "", "30", *a, "16.00", "USD")]


ADA, ROSTER = u05()
FILES = [
    ("unseen_01_email_confirmation.pdf", "pdf", "UNSEEN01", "pdf", "email", "medium", u01(), "",
     "Confirmation email in sentences and bullets, 24 hour times, rate stated once, one 45 minute break, one shift with no break"),
    ("unseen_02_monthly_calendar.pdf", "pdf", "UNSEEN02", "pdf", "calendar", "hard", u02(), "",
     "Month calendar, the date comes from the cell, break and rate only in the note below, one cancelled shift, shifts in two weeks"),
    ("unseen_03_timesheet_clock.pdf", "pdf", "UNSEEN03", "pdf", "timesheet", "medium", u03(), "",
     "Timesheet with clock in and clock out, lunch written as h:mm, an hours worked column and a totals row that are not shifts, an overnight shift"),
    ("unseen_04_sms_two_senders.png", "images", "UNSEEN04", "image", "chat", "hard", u04(), "",
     "Chat screen with two senders (two employers), an update message that changes Wednesday, a shift that ends at midnight"),
    ("unseen_05_printed_rota_two_adas.jpg", "images", "UNSEEN05", "image", "perspective", "hard", ADA, "Ada Okoye",
     "Angled photo of a rota for three people. Only Ada Okoye belongs in the answer. Ada Okonkwo has a similar name and must not be read as her"),
    ("unseen_06_missing_details_off_days.png", "images", "UNSEEN06", "image", "clean", "hard", u06(), "",
     "Table with OFF days that are not shifts, a break of 0 that must stay 0, a break left out, a rate TBC with no currency, and an end time TBC"),
]


# ----------------------------------------------------------------------------- pdf helpers
def pdf_styles():
    g.register_fonts()
    styles = getSampleStyleSheet()
    for s in ("Title", "Normal", "Heading2", "Heading3"):
        styles[s].fontName = "DejaVu-Bold" if s != "Normal" else "DejaVu"
    styles["Normal"].fontSize = 10.5
    styles["Normal"].leading = 15
    return styles


def grid_style(size=9):
    return TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
                       ("FONTSIZE", (0, 0), (-1, -1), size), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                       ("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])


def pdf_email(path, rows):
    st = pdf_styles()
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm,
                            bottomMargin=20 * mm, title="Your confirmed shifts")
    first = rows[0]
    story = [Paragraph("From: Northside Books scheduling &lt;rota@northsidebooks.example&gt;", st["Normal"]),
             Paragraph("To: Daniel", st["Normal"]),
             Paragraph("Date: Fri 6 Nov 2026", st["Normal"]),
             Paragraph("Subject: Your confirmed shifts, week of 9 November 2026", st["Heading3"]),
             Spacer(1, 6 * mm),
             Paragraph("Hi Daniel,", st["Normal"]), Spacer(1, 3 * mm),
             Paragraph(f"Here are your confirmed shifts at {first['employer_name']}, {first['location']} "
                       f"({first['department']}). Your rate is {first['hourly_rate']} {first['currency']} per hour.",
                       st["Normal"]), Spacer(1, 3 * mm)]
    for r in rows:
        lunch = "no lunch break" if int(r["break_minutes"]) == 0 else f"{r['break_minutes']} min unpaid lunch"
        story.append(Paragraph(f"&bull; {g.day_label(r['shift_date'])}: {r['start_time']} to {r['end_time']}, {lunch}",
                               st["Normal"]))
    story += [Spacer(1, 3 * mm),
              Paragraph("You are not scheduled on Tuesday 10 Nov, Friday 13 Nov or Sunday 15 Nov.", st["Normal"]),
              Spacer(1, 3 * mm),
              Paragraph("Please reply to confirm you have seen this. Thanks, Marcus", st["Normal"])]
    doc.build(story)


def pdf_calendar(path, rows):
    st = pdf_styles()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="November 2026 shifts")
    by_date = {r["shift_date"]: r for r in rows}
    first = rows[0]
    head = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    body = []
    day = date(2026, 10, 26)
    for _ in range(6):
        week = []
        for _ in range(7):
            text = str(day.day)
            r = by_date.get(day.isoformat())
            if r:
                text += f"\n{r['start_time']}-{r['end_time']}"
                if r["shift_status"] == "cancelled":
                    text += "\nCANCELLED"
            week.append(text)
            day = date.fromordinal(day.toordinal() + 1)
        body.append(week)
    t = Table([head] + body, colWidths=[37 * mm] * 7, rowHeights=[8 * mm] + [19 * mm] * 6)
    style = grid_style(9)
    style.add("VALIGN", (0, 1), (-1, -1), "TOP")
    t.setStyle(style)
    story = [Paragraph("November 2026", st["Title"]),
             Paragraph(f"{first['employer_name']}, {first['location']} ({first['department']})", st["Heading2"]),
             Spacer(1, 3 * mm), t, Spacer(1, 3 * mm),
             Paragraph(f"Every shift has a {first['break_minutes']} minute unpaid break. "
                       f"Pay rate: {first['hourly_rate']} {first['currency']} per hour.", st["Normal"])]
    doc.build(story)


def pdf_timesheet(path, rows):
    st = pdf_styles()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=15 * mm, title="Timesheet")
    first = rows[0]
    head = ["Day", "Clock in", "Clock out", "Unpaid lunch (h:mm)", "Hours worked", "Rate"]
    body = [[g.day_label(r["shift_date"]), r["start_time"], r["end_time"], hmm(r["break_minutes"]),
             f"{worked_hours(r):.2f}", f"{first['hourly_rate']} {first['currency']}"] for r in rows]
    total = sum(worked_hours(r) for r in rows)
    body.append(["Total", "", "", "", f"{total:.2f}", ""])
    t = Table([head] + body, colWidths=[40 * mm, 30 * mm, 30 * mm, 50 * mm, 35 * mm, 35 * mm])
    style = grid_style(10)
    style.add("FONTNAME", (0, len(body)), (-1, len(body)), "DejaVu-Bold")
    t.setStyle(style)
    story = [Paragraph(f"Timesheet: {first['employer_name']}, {first['location']} ({first['department']})", st["Title"]),
             Paragraph("Week of 16 November 2026", st["Heading2"]), Spacer(1, 5 * mm), t, Spacer(1, 5 * mm),
             Paragraph("Signed by supervisor: ______________", st["Normal"])]
    doc.build(story)


# ----------------------------------------------------------------------------- image helpers
def bubble(d, x, y, width, lines, sender, fill, f_body, f_small):
    line_h = 28
    h = 40 + line_h * len(lines) + 16
    d.rounded_rectangle([x, y, x + width, y + h], radius=14, fill=fill)
    d.text((x + 16, y + 10), sender, fill=(7, 94, 84), font=f_small)
    ty = y + 40
    for line in lines:
        d.text((x + 16, ty), line, fill=(30, 30, 30), font=f_body)
        ty += line_h
    return y + h + 18, h


def draw_two_sender_chat(rows):
    q = [r for r in rows if r["employer_name"] == "Quickserve Foods"]
    f = [r for r in rows if r["employer_name"] == "Anchor Freight"][0]
    f_body, f_small = g.font(20), g.font(15)
    width, pad = 740, 22
    msgs = [
        ("sep", "Thu 12 Nov 2026"),
        ("msg", "Quickserve Foods", [f"Hi! Rota for the week of 16 Nov, {q[0]['location']} ({q[0]['department']}).",
                                      "Mon 4pm to 11pm", "Wed 4pm to 11pm", "Fri 4pm to 11pm",
                                      f"30 min break each shift. {q[0]['hourly_rate']} USD per hour."]),
        ("sep", "Sun 15 Nov 2026"),
        ("msg", "Quickserve Foods", ["Update: Wednesday is now 5pm to midnight.", "Break is still 30 min."]),
        ("sep", "Mon 16 Nov 2026"),
        ("msg", "Anchor Freight", [f"Hello, we need you at the {f['location']} on Sat 21 Nov,",
                                   f"6am to 2pm ({f['department']}), 30 min break,", f"{f['hourly_rate']} USD per hour."]),
    ]
    height = 120
    for m in msgs:
        height += 46 if m[0] == "sep" else 40 + 28 * len(m[2]) + 34
    img = Image.new("RGB", (width, height + 40), (229, 221, 213))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 80], fill=(7, 94, 84))
    d.text((pad, 24), "Messages", fill=(255, 255, 255), font=g.font(28, True))
    y = 100
    for m in msgs:
        if m[0] == "sep":
            d.rounded_rectangle([width // 2 - 110, y, width // 2 + 110, y + 30], radius=10, fill=(215, 225, 230))
            d.text((width // 2 - 92, y + 5), m[1], fill=(70, 80, 90), font=f_small)
            y += 46
        else:
            y, _ = bubble(d, pad, y, width - 2 * pad - 40, m[2], m[1], (255, 255, 255), f_body, f_small)
    return img


def draw_rota_image(rows):
    head = ["Name", "Day", "Time", "Break", "Rate"]
    widths = [210, 150, 210, 110, 150]
    row_h, pad = 44, 16
    body = [[r["worker_name"], g.day_label(r["shift_date"]), f"{r['start_time']} - {r['end_time']}",
             f"{r['break_minutes']} min", f"{r['hourly_rate']} {r['currency']}"] for r in rows]
    width = sum(widths) + 2 * pad
    height = 150 + row_h * (len(body) + 1) + pad
    img = Image.new("RGB", (width, height), (250, 248, 240))
    d = ImageDraw.Draw(img)
    d.text((pad, 16), "Ridgeway Events: staff rota", fill=(20, 20, 20), font=g.font(30, True))
    d.text((pad, 60), "Hotel Front (banquets)", fill=(20, 20, 20), font=g.font(22))
    d.text((pad, 92), "Week of 23 November 2026", fill=(20, 20, 20), font=g.font(22))
    y = 134
    for ri, row in enumerate([head] + body):
        x = pad
        if ri == 0:
            d.rectangle([pad, y, width - pad, y + row_h], fill=(225, 225, 225))
        for ci, cell in enumerate(row):
            d.rectangle([x, y, x + widths[ci], y + row_h], outline=(150, 150, 150))
            d.text((x + 8, y + 11), str(cell), fill=(20, 20, 20), font=g.font(18, ri == 0))
            x += widths[ci]
        y += row_h
    return img


def draw_missing_image(rows):
    """A clean table. A day without a shift is printed as OFF, a detail that is not known as - or TBC."""
    by_date = {r["shift_date"]: r for r in rows}
    head = ["Day", "Start", "End", "Break", "Rate"]
    widths = [170, 130, 130, 120, 190]
    row_h, pad = 44, 16
    body = []
    for i in range(7):
        iso = date.fromordinal(date(2026, 11, 23).toordinal() + i).isoformat()
        r = by_date.get(iso)
        if r is None:
            body.append([g.day_label(iso), "OFF", "", "", ""])
            continue
        end = r["end_time"] or "TBC"
        brk = "-" if r["break_minutes"] == "" else r["break_minutes"]
        rate = f"{r['hourly_rate']} {r['currency']}" if r["hourly_rate"] else "TBC"
        body.append([g.day_label(iso), r["start_time"], end, brk, rate])
    width = sum(widths) + 2 * pad
    height = 140 + row_h * (len(body) + 1) + pad
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((pad, 16), "Anchor Freight - Depot (loading)", fill=(20, 20, 20), font=g.font(30, True))
    d.text((pad, 66), "Week of 23 November 2026", fill=(20, 20, 20), font=g.font(22))
    y = 110
    for ri, row in enumerate([head] + body):
        x = pad
        if ri == 0:
            d.rectangle([pad, y, width - pad, y + row_h], fill=(225, 225, 225))
        for ci, cell in enumerate(row):
            d.rectangle([x, y, x + widths[ci], y + row_h], outline=(150, 150, 150))
            d.text((x + 8, y + 11), str(cell), fill=(20, 20, 20), font=g.font(18, ri == 0))
            x += widths[ci]
        y += row_h
    return img


# ----------------------------------------------------------------------------- writing everything
def main():
    rng = np.random.default_rng(20261120)
    for sub in ("pdf", "images"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    p = lambda sub, name: os.path.join(OUT, sub, name)  # noqa: E731
    by = {f[0]: f for f in FILES}

    pdf_email(p("pdf", FILES[0][0]), FILES[0][6])
    pdf_calendar(p("pdf", FILES[1][0]), FILES[1][6])
    pdf_timesheet(p("pdf", FILES[2][0]), FILES[2][6])
    draw_two_sender_chat(FILES[3][6]).save(p("images", FILES[3][0]))
    img = g.paste_on_desk(draw_rota_image(ROSTER), (100, 90, 80), 90)
    img = g.perspective(img, 60)
    w, h = img.size
    img = img.crop((0, int(h * 0.02), int(w * 0.98), int(h * 0.99)))
    img = g.add_noise(g.add_shadow(img, 0.25), 5, rng)
    img.save(p("images", FILES[4][0]), quality=70)
    draw_missing_image(FILES[5][6]).save(p("images", FILES[5][0]))

    with open(os.path.join(OUT, "answer_key.csv"), "w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["file_name", "shift_no"] + KEY_FIELDS)
        for name, _, _, _, _, _, rows, _, _ in FILES:
            for n, r in enumerate(rows, 1):
                w_.writerow([name, n] + [r[k] for k in KEY_FIELDS])
    with open(os.path.join(OUT, "files.csv"), "w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["file_name", "folder", "schedule_id", "kind", "layout_or_look", "difficulty", "shifts",
                     "target_worker", "what_it_tests"])
        for name, folder, sid, kind, look, diff, rows, target, tests in FILES:
            w_.writerow([name, folder, sid, kind, look, diff, len(rows), target, tests])
    total = sum(len(f[6]) for f in FILES)
    table = "\n".join(f"| {f[0]} | {f[2]} | {len(f[6])} | {f[5]} | {f[8]} |" for f in FILES)
    readme = f"""# Unseen PDF and image schedule samples

{len(FILES)} schedules that the extraction prompt has never been tuned on, with an answer key of {total} shifts.
The first set in `test_data/unstructured` was used while the prompt was written, so a result on it is "in sample".
This set uses other layouts, employers and weeks, so it is a fairer check of how the extractor reads schedules it has not seen.
The answer key was written by hand, before any extraction was run on these files. Please do not tune the prompt on these
files. If you do, they stop being unseen, and a new set is needed.

| File | Schedule | Shifts | Difficulty | What it tests |
|---|---|---|---|---|
{table}

## How to use them

Exactly as for the first set, with the answer key of this folder:

1. Give each file to the extractor and save everything it reads in one csv, one row per shift, with the columns
   `file_name, shift_date, start_time, end_time, break_minutes, employer_name, location, department, hourly_rate, currency, shift_status`.
   Leave a cell empty when the document does not give that detail.
2. From the `data_validation` folder, run:
   `python3 -I tools/compare_extraction.py extracted.csv test_data/unstructured_unseen/answer_key.csv`
   Known limit: the tool still reads the difficulty of each file from the `files.csv` of the first set
   (`test_data/unstructured`), not from the `files.csv` in this folder. So the "By difficulty" part of its report
   shows `unknown` for this set. Everything else in the report is correct for this set. The `difficulty` column in
   this folder's `files.csv` is there for reading and for a later update of the tool.

## Reading the answer key

- An empty cell means the document does not state that detail, so the right answer is an empty cell.
  A break of `0` that is written down (`unseen_01`, `unseen_05`, `unseen_06`) must stay `0`.
- `unseen_05_printed_rota_two_adas.jpg` prints seven shifts of other people. The key holds only Ada Okoye (see `target_worker` in `files.csv`).
  Shifts of other employees count as invented shifts.
- `unseen_04_sms_two_senders.png`: the Wednesday shift was changed by a later message, so the key holds the new times and `changed`.
- A shift that ends earlier than it starts (18:00 to 02:00) finishes the next morning. A shift that ends at midnight is `00:00`.
  The key keeps the times as printed, converted to 24 hour times.
- `OFF` days, the totals row and the hours worked column are not shifts.

## What this set does not show

It is small ({total} shifts in {len(FILES)} files), made on a computer, with no handwriting, and written by the same team that wrote
the rules. A good result here is a better sign than the first set, but it is not proof for real photographed schedules.

## Making the files again

`python3 -I generator/generate_unseen_samples.py` rebuilds the files, the answer key, `files.csv` and this README.
"""
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    print(f"wrote {len(FILES)} files and {total} key rows to {OUT}")


if __name__ == "__main__":
    main()
