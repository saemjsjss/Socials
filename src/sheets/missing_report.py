"""
Daily "missing information" report from the progress sheets (sent at 09:05 by the bot).

For every student on each program's progress sheet (main tab), counts which required
fields are blank, then sends a Telegram summary plus an Excel file listing every
student with what they are missing.

What counts as missing:
  * REQUIRED — always expected.
  * UNIVERSITY_FIELDS — all four for Master's students and graduates; only university +
    subject for students currently in undergraduate (no final degree/CGPA yet).
  * Not counted: IELTS/TOPIK (optional) and Passport Issue (no such field on the portal).

CLI (run from E:\\BOT):
  python -m src.sheets.missing_report               # build + send the report
  python -m src.sheets.missing_report --no-notify   # build only (prints the summary)
  python -m src.sheets.missing_report --student HNG-2026-925   # one student
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Dict, List

from src.sheets import progress_builder as pb

logger = logging.getLogger(__name__)

REQUIRED = [
    "Student ID", "Full Name", "Surname", "Given Name", "Email", "Mobile", "Guardian WhatsApp",
    "DOB", "Gender", "District", "Address", "Father", "Mother", "Study Status",
    "SSC Year", "SSC GPA", "SSC Group", "SSC School",
    "HSC Year", "HSC GPA", "HSC Group", "HSC College",
    "Program", "Passport Status", "Passport No", "Passport Expiry",
    "Visa Rejection History", "Sponsor", "Sponsor Occupation", "Bank Certificate",
]
UNIVERSITY_FIELDS = ["Previous University", "Subject", "Degree", "CGPA"]
REPORT_DIR = pb.BOT_ROOT / "data" / "missing_reports"


def _university_fields(rec: Dict[str, str], program_key: str) -> List[str]:
    """Master's students and graduates need all four; students still in undergraduate
    have no final degree/CGPA yet, so only university + subject are expected."""
    if pb.PROGRAMS[program_key].get("drop_columns"):
        return []  # this program's sheet has no university columns
    status = rec.get("Study Status", "").upper()
    if program_key == "MASTER" or "COMPLETED" in status and ("GRADUATE" in status):
        return UNIVERSITY_FIELDS
    if "CURRENTLY IN UNDERGRADUATE" in status:
        return ["Previous University", "Subject"]
    return []


def missing_fields(rec: Dict[str, str], program_key: str) -> List[str]:
    fields = REQUIRED + _university_fields(rec, program_key)
    return [f for f in fields if not pb.clean_value(rec.get(f, ""))]


def read_sheets() -> Dict[str, List[Dict[str, str]]]:
    """Main-tab rows of every program + intake progress sheet, keyed "KLP|MARCH 2027"."""
    drive, sheets = pb._services()
    out: Dict[str, List[Dict[str, str]]] = {}
    for cfg in pb.all_targets():
        title = pb.sheet_title(cfg)
        ssid = pb.find_sheet(drive, cfg)
        if not ssid:
            logger.warning("no progress sheet for %s", title)
            continue
        tab = sheets.spreadsheets().get(spreadsheetId=ssid, fields="sheets.properties.title"
                                        ).execute()["sheets"][0]["properties"]["title"]
        grid = sheets.spreadsheets().values().get(spreadsheetId=ssid, range=f"'{tab}'"
                                                  ).execute().get("values", [])
        if not grid:
            continue
        hdr = grid[0]
        out[f"{cfg['key']}|{cfg['intake']}"] = [
            dict(zip(hdr, r + [""] * (len(hdr) - len(r)))) for r in grid[1:] if any(r)]
    return out


def build_report(data: Dict[str, List[Dict[str, str]]]):
    """Returns (summary_lines, rows) where rows feed the Excel file."""
    lines: List[str] = []
    rows = []
    total_students = total_incomplete = 0
    for sk, recs in data.items():
        key, intake = sk.split("|", 1)
        cfg = pb.target(key, intake)
        items = []
        for rec in recs:
            miss = missing_fields(rec, key)
            rows.append((cfg["name"], cfg["intake"], rec.get("Student ID", ""), rec.get("Full Name", ""),
                         rec.get("Mobile", ""), len(miss), ", ".join(miss)))
            if miss:
                items.append((len(miss), rec.get("Student ID", "") or "(no ID)", rec.get("Full Name", ""), miss))
        total_students += len(recs)
        total_incomplete += len(items)
        items.sort(key=lambda t: -t[0])
        lines.append(f"\n📋 {cfg['name']} {cfg['intake']} — {len(items)} of {len(recs)} incomplete")
        for n, sid, name, miss in items[:10]:
            shown = ", ".join(miss[:6]) + (f" +{len(miss) - 6} more" if len(miss) > 6 else "")
            lines.append(f"   • {sid} {name} — {n} missing: {shown}")
        if len(items) > 10:
            lines.append(f"   … and {len(items) - 10} more (see the Excel file)")
    no_intake = pb.students_without_intake()
    if no_intake:
        lines.append(f"\n⚠️ {len(no_intake)} student(s) have NO INTAKE on the portal, so they are on no sheet:")
        for s in no_intake[:15]:
            lines.append(f"   • {s.get('Student ID') or '(no ID)'} {s.get('Full Name', '')} — {s.get('Program', '')}")
            rows.append((s.get("Program", ""), "(no intake)", s.get("Student ID", ""), s.get("Full Name", ""),
                         pb.normalize_phone(s.get("Mobile", "")), 1, "Intake"))
    head = (f"🗓 Missing-information report — {time.strftime('%d %b %Y')}\n"
            f"{total_incomplete} of {total_students} students have missing information.")
    return [head] + lines, rows


def program_report(program_key: str) -> str:
    """Full missing-information list for ONE program (all its intakes) — used by the
    Telegram menu commands /missing_klp, /missing_eap, /missing_bachelor, /missing_master."""
    cfg = pb.PROGRAMS[program_key]
    data = {sk: recs for sk, recs in read_sheets().items() if sk.split("|", 1)[0] == program_key}
    out = [f"📋 Missing information — {cfg['name']}", f"(live from the progress sheets, {time.strftime('%d %b %Y %H:%M')})"]
    total = incomplete = 0
    for sk, recs in data.items():
        intake = sk.split("|", 1)[1]
        items = [(missing_fields(r, program_key), r) for r in recs]
        items = sorted([t for t in items if t[0]], key=lambda t: -len(t[0]))
        total += len(recs)
        incomplete += len(items)
        out.append(f"\n🗂 {intake} — {len(items)} of {len(recs)} incomplete")
        for miss, r in items:
            out.append(f"• {r.get('Student ID') or '(no ID)'} {r.get('Full Name', '')} — "
                       f"{len(miss)} missing: {', '.join(miss)}")
        if not items:
            out.append("✅ Everyone complete")
    no_intake = [s for s in pb.students_without_intake() if pb.program_key_of(s) == program_key]
    if no_intake:
        out.append(f"\n⚠️ No intake on the portal ({len(no_intake)}) — not on any sheet, set their intake:")
        for s in no_intake:
            out.append(f"• {s.get('Student ID') or '(no ID)'} {s.get('Full Name', '')}")
    out.insert(2, f"{incomplete} of {total} students have missing information.")
    return "\n".join(out)


def write_excel(rows) -> "pb.Path":
    from openpyxl import Workbook
    from openpyxl.styles import Font
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"missing_information_{time.strftime('%Y-%m-%d')}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Missing information"
    ws.append(["Program", "Intake", "Student ID", "Full Name", "Mobile", "Missing count", "Missing fields"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in sorted(rows, key=lambda r: (r[0], -r[5])):
        if r[5]:
            ws.append(list(r))
    ws.freeze_panes = "A2"
    for col, width in zip("ABCDEFG", (34, 15, 15, 32, 16, 14, 120)):
        ws.column_dimensions[col].width = width
    wb.save(path)
    return path


def send(lines: List[str], xlsx) -> None:
    import httpx
    from src.config import settings
    token, ids = settings.TELEGRAM_BOT_TOKEN, settings.brief_recipient_ids()
    if not token or not ids:
        logger.warning("Telegram not configured — report not sent")
        return
    text = "\n".join(lines)
    chunks, cur = [], ""
    for line in text.split("\n"):  # split on line boundaries, under Telegram's limit
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    with httpx.Client(timeout=60) as http:
        for chat in ids:
            try:
                for c in chunks:
                    http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": c, "disable_web_page_preview": True})
                with open(xlsx, "rb") as f:
                    http.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": chat, "caption": "Every incomplete student with the fields they are missing"},
                              files={"document": (xlsx.name, f)})
            except Exception as e:
                logger.warning("Telegram send to %s failed: %s", chat, e)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Report missing student information from the progress sheets.")
    ap.add_argument("--no-notify", action="store_true", help="don't send to Telegram")
    ap.add_argument("--student", metavar="ID", help="show one student only")
    ap.add_argument("--program", metavar="KEY", help="full list for one program: KLP | EAP | BACHELOR | MASTER")
    args = ap.parse_args()
    if args.program:
        key = args.program.strip().upper()
        if key not in pb.PROGRAMS:
            raise SystemExit(f"Unknown program {key!r}. Choose one of: {', '.join(pb.PROGRAMS)}")
        print(program_report(key))
        return
    data = read_sheets()
    if args.student:
        want = args.student.strip().upper()
        for sk, recs in data.items():
            key, intake = sk.split("|", 1)
            for rec in recs:
                if rec.get("Student ID", "").upper() == want:
                    miss = missing_fields(rec, key)
                    print(f"{want} {rec.get('Full Name', '')} — {pb.PROGRAMS[key]['name']} {intake}: "
                          f"{len(miss)} missing: {', '.join(miss) or 'nothing'}")
                    return
        print(f"{want} not found in the progress sheets.")
        return
    lines, rows = build_report(data)
    xlsx = write_excel(rows)
    print("\n".join(lines))
    print(f"\nExcel: {xlsx}")
    if not args.no_notify:
        send(lines, xlsx)


if __name__ == "__main__":
    main()
