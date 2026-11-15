"""Builds PDF and image schedules from the clean csv schedules, plus the answer key.

These files are for checking how well the NVIDIA extraction (or any extractor) reads schedules that are
not csv. Every file shows the shifts of one schedule in test_data/schedule_inputs, so the correct values
are already known. The answer key lists what an extractor should read from each file.

Usage (from the data_validation folder):
    python3 -I generator/generate_unstructured_samples.py

Writes to test_data/unstructured: pdf and images folders, answer_key.csv and files.csv.
Needs reportlab, Pillow and numpy. The output is repeatable (fixed random seed).
"""
import csv
import os
import random
from datetime import date, datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INPUTS = os.path.join(ROOT, "test_data", "schedule_inputs")
OUT = os.path.join(ROOT, "test_data", "unstructured")
FONT_DIR = "/usr/share/fonts/truetype/dejavu"

KEY_FIELDS = ["shift_date", "start_time", "end_time", "break_minutes", "employer_name", "location",
              "department", "hourly_rate", "currency", "shift_status"]

# file name, schedule, kind, layout or look, difficulty, what it tests
FILES = [
    ("pdf_01_table_clean.pdf", "S001", "pdf", "table", "easy", "Clean table with an overnight shift"),
    ("pdf_02_table_week.pdf", "S002", "pdf", "table", "easy", "Clean table, five days, 30 minute breaks"),
    ("pdf_03_sentences_12h.pdf", "S003", "pdf", "sentences", "medium", "One sentence per shift, 12 hour times, overnight shifts"),
    ("pdf_04_weekly_grid.pdf", "S012", "pdf", "grid", "hard", "Weekly grid, days as columns, weekend rate"),
    ("pdf_05_list_exact_minutes.pdf", "S005", "pdf", "sentences", "medium", "Shifts that do not end on the hour (12:10), 12 hour times"),
    ("img_01_screenshot_clean.png", "S013", "image", "clean", "easy", "Clean screenshot of a table, six long shifts"),
    ("img_02_photo_tilted.jpg", "S015", "image", "tilted", "medium", "Tilted photo with shadow and noise, two cancelled shifts"),
    ("img_03_blurry_lowlight.jpg", "S016", "image", "blurry", "hard", "Blurry low light photo, five overnight shifts"),
    ("img_04_phone_dark_mode.png", "S024", "image", "dark", "medium", "Phone dark mode cards, weekend rate"),
    ("img_05_cropped_perspective.jpg", "S025", "image", "perspective", "hard", "Angled and cropped photo, overnight shift on the pay week boundary"),
    ("img_06_chat_message.png", "S023", "image", "chat", "medium", "Manager chat message in free text, no table, rate stated once, two changed shifts"),
]


# ----------------------------------------------------------------------------- data helpers
def read_schedule(schedule_id):
    with open(os.path.join(INPUTS, f"{schedule_id}_schedule.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pay_week_start(rows):
    first = min(date.fromisoformat(r["shift_date"]) for r in rows)
    return first.fromordinal(first.toordinal() - first.weekday())


def day_label(iso, year=False):
    d = date.fromisoformat(iso)
    text = f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"
    return f"{text} {d.year}" if year else text


def t12(hhmm):
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def money(rate, currency):
    return f"{float(rate):.2f} {currency}"


def break_text(minutes):
    return "no break" if int(minutes) == 0 else f"{int(minutes)} minute break"


def status_text(status):
    return "CANCELLED" if status == "cancelled" else "Scheduled"


def week_header(rows):
    start = pay_week_start(rows)
    return f"Week of {start.day} {start.strftime('%B %Y')}"


# ----------------------------------------------------------------------------- pdf
def register_fonts():
    pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))


def table_rows(rows, show_year=True):
    head = ["Date", "Start", "End", "Break (min)", "Employer", "Location", "Department", "Rate", "Status"]
    body = [[day_label(r["shift_date"], show_year), r["start_time"], r["end_time"], r["break_minutes"],
             r["employer_name"], r["location"], r["department"], money(r["hourly_rate"], r["currency"]),
             status_text(r["shift_status"])] for r in rows]
    return head, body


def build_pdf(path, rows, layout, title):
    register_fonts()
    styles = getSampleStyleSheet()
    for s in ("Title", "Normal", "Heading2"):
        styles[s].fontName = "DejaVu-Bold" if s != "Normal" else "DejaVu"
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=title)
    story = [Paragraph("Work schedule", styles["Title"]), Paragraph(week_header(rows), styles["Heading2"]),
             Spacer(1, 6 * mm)]
    if layout == "table":
        head, body = table_rows(rows)
        t = Table([head] + body, repeatRows=1)
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
                               ("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(t)
    elif layout == "sentences":
        for r in rows:
            line = (f"{day_label(r['shift_date'])}: {r['employer_name']} at {r['location']} ({r['department']}), "
                    f"{t12(r['start_time'])} to {t12(r['end_time'])}, {break_text(r['break_minutes'])}, "
                    f"{money(r['hourly_rate'], r['currency'])} per hour.")
            if r["shift_status"] == "cancelled":
                line += " This shift has been cancelled."
            story.append(Paragraph(line, styles["Normal"]))
            story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Times marked AM or PM. A shift that ends earlier than it starts finishes the next morning.",
                               styles["Normal"]))
    elif layout == "grid":
        start = pay_week_start(rows)
        days = [date.fromordinal(start.toordinal() + i) for i in range(7)]
        by_date = {r["shift_date"]: r for r in rows}
        head = [""] + [f"{d.strftime('%a')} {d.day} {d.strftime('%b')}" for d in days]
        employer = rows[0]["employer_name"]
        cells = [f"{employer}, {rows[0]['location']}"]
        for d in days:
            r = by_date.get(d.isoformat())
            cells.append("" if r is None else f"{r['start_time']} - {r['end_time']}\nbreak {r['break_minutes']} min\n"
                         f"{money(r['hourly_rate'], r['currency'])}/h")
        t = Table([head, cells], colWidths=[45 * mm] + [30 * mm] * 7, rowHeights=[10 * mm, 28 * mm])
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(t)
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Department: {rows[0]['department']}. Blank day = not working.", styles["Normal"]))
    doc.build(story)


# ----------------------------------------------------------------------------- images
def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.load_default()


def draw_table_image(rows, bg=(255, 255, 255), ink=(20, 20, 20), head_bg=(225, 225, 225), line=(150, 150, 150),
                     show_year=False):
    head, body = table_rows(rows, show_year=show_year)
    widths = [150, 70, 70, 150, 220, 190, 170, 130, 130]
    row_h, pad = 44, 14
    width = sum(widths) + 2 * pad
    height = 130 + row_h * (len(body) + 1) + pad
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    d.text((pad, 18), "Work schedule", fill=ink, font=font(30, True))
    d.text((pad, 64), week_header(rows), fill=ink, font=font(22))
    y = 110
    for ri, row in enumerate([head] + body):
        x = pad
        if ri == 0:
            d.rectangle([pad, y, width - pad, y + row_h], fill=head_bg)
        for ci, cell in enumerate(row):
            d.rectangle([x, y, x + widths[ci], y + row_h], outline=line)
            d.text((x + 8, y + 11), str(cell), fill=ink, font=font(18, ri == 0))
            x += widths[ci]
        y += row_h
    return img


def draw_dark_cards(rows):
    bg, card, ink, sub = (18, 18, 24), (38, 40, 52), (240, 240, 245), (160, 165, 180)
    width, card_h, pad = 700, 150, 24
    height = 140 + (card_h + 16) * len(rows) + pad
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    d.text((pad, 24), "My shifts", fill=ink, font=font(32, True))
    d.text((pad, 76), week_header(rows), fill=sub, font=font(20))
    y = 120
    for r in rows:
        d.rounded_rectangle([pad, y, width - pad, y + card_h], radius=18, fill=card)
        d.text((pad + 20, y + 14), day_label(r["shift_date"]), fill=sub, font=font(20))
        d.text((pad + 20, y + 44), f"{r['start_time']} to {r['end_time']}", fill=ink, font=font(32, True))
        d.text((pad + 20, y + 92), f"{r['employer_name']}, {r['location']}", fill=ink, font=font(20))
        d.text((pad + 20, y + 118), f"{r['department']}  |  break {r['break_minutes']} min", fill=sub, font=font(17))
        d.text((width - pad - 190, y + 20), money(r["hourly_rate"], r["currency"]) + "/h", fill=ink, font=font(22, True))
        y += card_h + 16
    return img


def t_chat(hhmm):
    d = datetime.strptime(hhmm, "%H:%M")
    return d.strftime("%I").lstrip("0") + (d.strftime(":%M") if d.minute else "") + d.strftime("%p").lower()


def draw_chat(rows):
    """A phone chat screen with one long message from a manager. No table, times written as 10am to 6pm."""
    first = rows[0]
    lines = [f"Hi team, rota for {week_header(rows).lower().replace('week of', 'the week of')}.",
             f"{first['employer_name']}, {first['location']} ({first['department']}).",
             f"Rate this week: {first['hourly_rate']} {first['currency']} per hour.", ""]
    for r in rows:
        tail = f", {break_text(r['break_minutes'])}"
        if r["shift_status"] == "changed":
            tail += " (changed)"
        elif r["shift_status"] == "cancelled":
            tail += " (CANCELLED)"
        lines.append(f"{day_label(r['shift_date'])}: {t_chat(r['start_time'])} to {t_chat(r['end_time'])}{tail}")
    lines += ["", "Please reply to confirm. Thanks!"]
    f_body, f_small = font(20), font(15)
    width, pad = 720, 22
    line_h = 30
    bubble_h = line_h * len(lines) + 54
    height = 170 + bubble_h + 140
    img = Image.new("RGB", (width, height), (229, 221, 213))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 90], fill=(7, 94, 84))
    d.ellipse([pad, 22, pad + 46, 68], fill=(190, 200, 205))
    d.text((pad + 62, 24), "Manager", fill=(255, 255, 255), font=font(24, True))
    d.text((pad + 62, 58), "online", fill=(200, 230, 225), font=f_small)
    d.rounded_rectangle([pad, 110, width - pad - 30, 110 + bubble_h], radius=14, fill=(255, 255, 255))
    y = 128
    for line in lines:
        d.text((pad + 18, y), line, fill=(30, 30, 30), font=f_body)
        y += line_h
    d.text((width - pad - 110, 110 + bubble_h - 26), "09:12", fill=(130, 130, 130), font=f_small)
    d.rounded_rectangle([pad + 120, 110 + bubble_h + 20, width - pad, 110 + bubble_h + 78], radius=14, fill=(220, 248, 198))
    d.text((pad + 140, 110 + bubble_h + 36), "Ok, thank you", fill=(30, 30, 30), font=f_body)
    return img


def add_noise(img, sigma, rng):
    arr = np.asarray(img).astype(np.float32)
    arr += rng.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def add_shadow(img, strength):
    w, h = img.size
    grad = np.linspace(1.0, 1.0 - strength, w, dtype=np.float32)[None, :, None]
    arr = np.asarray(img).astype(np.float32) * grad
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def paste_on_desk(img, color=(120, 100, 80), margin=70):
    desk = Image.new("RGB", (img.width + 2 * margin, img.height + 2 * margin), color)
    desk.paste(img, (margin, margin))
    return desk


def perspective(img, shift):
    w, h = img.size
    coeffs = find_coeffs([(0, 0), (w, 0), (w, h), (0, h)],
                         [(shift, shift * 0.6), (w - shift * 0.3, 0), (w, h - shift * 0.5), (0, h)])
    return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(90, 80, 70))


def find_coeffs(target, source):
    matrix = []
    for (x, y), (u, v) in zip(target, source):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(matrix, dtype=np.float64)
    b = np.array([c for p in source for c in p], dtype=np.float64)
    return np.linalg.solve(a, b).tolist()


def build_image(path, rows, look, rng):
    if look == "clean":
        draw_table_image(rows).save(path)
    elif look == "dark":
        draw_dark_cards(rows).save(path)
    elif look == "chat":
        draw_chat(rows).save(path)
    elif look == "tilted":
        img = paste_on_desk(draw_table_image(rows))
        img = img.rotate(3.5, expand=True, fillcolor=(120, 100, 80), resample=Image.BICUBIC)
        img = add_noise(add_shadow(img, 0.35), 6, rng)
        img.save(path, quality=80)
    elif look == "blurry":
        img = paste_on_desk(draw_table_image(rows, bg=(215, 210, 195), ink=(70, 70, 75), line=(170, 165, 150)), (70, 62, 55))
        img = img.rotate(-2, expand=True, fillcolor=(70, 62, 55), resample=Image.BICUBIC)
        img = add_noise(add_shadow(img.filter(ImageFilter.GaussianBlur(1.4)), 0.5), 9, rng)
        img.save(path, quality=60)
    elif look == "perspective":
        img = draw_table_image(rows, bg=(250, 248, 240))
        img = perspective(paste_on_desk(img, (100, 90, 80), 90), 90)
        w, h = img.size
        img = img.crop((0, int(h * 0.03), int(w * 0.97), int(h * 0.98)))
        img = add_noise(add_shadow(img, 0.25), 5, rng)
        img.save(path, quality=55)
    else:
        raise ValueError(look)


# ----------------------------------------------------------------------------- main
def main():
    os.makedirs(os.path.join(OUT, "pdf"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "images"), exist_ok=True)
    rng = np.random.default_rng(2026)
    random.seed(2026)
    key_rows, file_rows = [], []
    for name, schedule_id, kind, look, difficulty, note in FILES:
        rows = read_schedule(schedule_id)
        folder = "pdf" if kind == "pdf" else "images"
        path = os.path.join(OUT, folder, name)
        if kind == "pdf":
            build_pdf(path, rows, look, f"Schedule {schedule_id}")
        else:
            build_image(path, rows, look, rng)
        file_rows.append({"file_name": name, "folder": folder, "schedule_id": schedule_id, "kind": kind,
                          "layout_or_look": look, "difficulty": difficulty, "shifts": len(rows), "what_it_tests": note})
        for i, r in enumerate(rows, 1):
            key_rows.append({"file_name": name, "shift_no": i, **{k: r[k] for k in KEY_FIELDS}})
    with open(os.path.join(OUT, "answer_key.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file_name", "shift_no"] + KEY_FIELDS)
        w.writeheader()
        w.writerows(key_rows)
    with open(os.path.join(OUT, "files.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(file_rows[0].keys()))
        w.writeheader()
        w.writerows(file_rows)
    print(f"Wrote {len(file_rows)} files and {len(key_rows)} answer key rows to {OUT}")


if __name__ == "__main__":
    main()
