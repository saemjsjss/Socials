"""
Daily "missing information" report from the progress sheets (sent at 09:05 by the bot).

For every student on each program's progress sheet (main tab), counts which required
fields are blank, then sends a Telegram summary plus an Excel file listing every
student with what they are missing.

What counts as missing:
  * REQUIRED — always expected.
  * UNIVERSITY_FIELDS — all four for Master's students and graduates; only university +
    subject for students currently in undergraduate (no final degree/CGPA yet).  The KLP, EAP
    and Bachelor's sheets have no university columns, so for their students these fields are
    read from the student's own portal record (the students.php CSV export the report reads
    anyway); a student that record cannot be found for is listed as "not checked", never as
    complete.
  * Not counted: IELTS/TOPIK (optional) and Passport Issue (no such field on the portal).

CLI (run from the BOT folder):
  python -m src.sheets.missing_report               # build + send the report
  python -m src.sheets.missing_report --no-notify   # build only (prints the summary)
  python -m src.sheets.missing_report --student HNG-2026-925   # one student
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Dict, List, Optional

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


UNIVERSITY_NOTE = ("University fields of KLP, EAP and Bachelor's students are read from the portal "
                   "(those sheets have no university columns).")


def _university_fields(rec: Dict[str, str], program_key: str) -> List[str]:
    """Master's students and graduates need all four; students still in undergraduate
    have no final degree/CGPA yet, so only university + subject are expected."""
    status = rec.get("Study Status", "").upper()
    if program_key == "MASTER" or "COMPLETED" in status and ("GRADUATE" in status):
        return UNIVERSITY_FIELDS
    if "CURRENTLY IN UNDERGRADUATE" in status:
        return ["Previous University", "Subject"]
    return []


def _sheet_has_university(program_key: str) -> bool:
    return not set(UNIVERSITY_FIELDS) & set(pb.PROGRAMS[program_key].get("drop_columns", []))


def portal_index(students: Optional[List[Dict[str, str]]] = None) -> Dict[str, Dict[str, str]]:
    """The portal's own records (the CSV export, pb.direct_students()) by Student ID, and by name +
    mobile for students without an ID, to read the fields a sheet has no column for."""
    index: Dict[str, Dict[str, str]] = {}
    for s in pb.direct_students() if students is None else students:
        sid = pb.clean_value(s.get("Student ID", "")).upper()
        key = f"ID:{sid}" if sid else f"NM:{pb._norm_key(s.get('Full Name', ''))}{pb.normalize_phone(s.get('Mobile', ''))}"
        index[key] = None if key in index else s        # a key two records share tells nothing
    return {k: v for k, v in index.items() if v is not None}


def portal_record(rec: Dict[str, str], index: Optional[Dict[str, Dict[str, str]]]) -> Optional[Dict[str, str]]:
    """The sheet row's own portal record from portal_index, or None when it cannot be told."""
    if not index:
        return None
    sid = pb.clean_value(rec.get("Student ID", "")).upper()
    if sid:
        return index.get(f"ID:{sid}")
    return index.get(f"NM:{pb._norm_key(rec.get('Full Name', ''))}{pb.normalize_phone(rec.get('Mobile', ''))}")


def missing_fields(rec: Dict[str, str], program_key: str,
                   index: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    """The required fields this sheet row leaves blank. University fields are checked on the sheet
    when it has the columns, else on the student's portal record (portal_index); when that record
    cannot be found they are not counted here but listed by unchecked_fields."""
    miss = [f for f in REQUIRED if not pb.clean_value(rec.get(f, ""))]
    uni = _university_fields(rec, program_key)
    source = rec if _sheet_has_university(program_key) else portal_record(rec, index)
    if uni and source is not None:
        miss += [f for f in uni if not pb.clean_value(source.get(f, ""))]
    return miss


def unchecked_fields(rec: Dict[str, str], program_key: str,
                     index: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    """The university fields this student needs but that could not be checked: the sheet has no
    such columns and the student's portal record was not found."""
    uni = _university_fields(rec, program_key)
    if not uni or _sheet_has_university(program_key) or portal_record(rec, index) is not None:
        return []
    return uni


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


def _unchecked_line(unchecked: List[Dict[str, str]], indent: str) -> List[str]:
    if not unchecked:
        return []
    names = "; ".join(f"{r.get('Student ID') or '(no ID)'} {r.get('Full Name', '')}" for r in unchecked[:10])
    more = f"; +{len(unchecked) - 10} more" if len(unchecked) > 10 else ""
    return [f"{indent}⚠️ University fields not checked for {len(unchecked)} student(s) "
            f"(not found in the portal export): {names}{more}"]


def build_report(data: Dict[str, List[Dict[str, str]]], index: Optional[Dict[str, Dict[str, str]]] = None):
    """Returns (summary_lines, rows) where rows feed the Excel file. `index` is portal_index()
    (read from the portal when not given)."""
    index = portal_index() if index is None else index
    lines: List[str] = []
    rows = []
    total_students = total_incomplete = 0
    uses_portal = False
    for sk, recs in data.items():
        key, intake = sk.split("|", 1)
        cfg = pb.target(key, intake)
        uses_portal = uses_portal or not _sheet_has_university(key)
        items, unchecked = [], []
        for rec in recs:
            miss = missing_fields(rec, key, index)
            if unchecked_fields(rec, key, index):
                unchecked.append(rec)
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
        lines += _unchecked_line(unchecked, "   ")
    no_intake = pb.students_without_intake()
    if no_intake:
        lines.append(f"\n⚠️ {len(no_intake)} student(s) have NO INTAKE on the portal, so they are on no sheet:")
        for s in no_intake[:15]:
            lines.append(f"   • {s.get('Student ID') or '(no ID)'} {s.get('Full Name', '')} — {s.get('Program', '')}")
            rows.append((s.get("Program", ""), "(no intake)", s.get("Student ID", ""), s.get("Full Name", ""),
                         pb.normalize_phone(s.get("Mobile", "")), 1, "Intake"))
    head = (f"🗓 Missing-information report — {time.strftime('%d %b %Y')}\n"
            f"{total_incomplete} of {total_students} students have missing information."
            + (f"\n{UNIVERSITY_NOTE}" if uses_portal else ""))
    return [head] + lines, rows


def program_report(program_key: str, data: Optional[Dict[str, List[Dict[str, str]]]] = None,
                   index: Optional[Dict[str, Dict[str, str]]] = None) -> str:
    """Full missing-information list for ONE program (all its intakes) — used by the
    Telegram menu commands /missing_klp, /missing_eap, /missing_bachelor, /missing_master.
    `data` (read_sheets()) and `index` (portal_index()) are read live when not given."""
    cfg = pb.PROGRAMS[program_key]
    data = {sk: recs for sk, recs in (read_sheets() if data is None else data).items()
            if sk.split("|", 1)[0] == program_key}
    index = portal_index() if index is None else index
    out = [f"📋 Missing information — {cfg['name']}", f"(live from the progress sheets, {time.strftime('%d %b %Y %H:%M')})"]
    if not _sheet_has_university(program_key):
        out.append(UNIVERSITY_NOTE)
    total = incomplete = 0
    for sk, recs in data.items():
        intake = sk.split("|", 1)[1]
        items = [(missing_fields(r, program_key, index), r) for r in recs]
        unchecked = [r for r in recs if unchecked_fields(r, program_key, index)]
        items = sorted([t for t in items if t[0]], key=lambda t: -len(t[0]))
        total += len(recs)
        incomplete += len(items)
        out.append(f"\n🗂 {intake} — {len(items)} of {len(recs)} incomplete")
        for miss, r in items:
            out.append(f"• {r.get('Student ID') or '(no ID)'} {r.get('Full Name', '')} — "
                       f"{len(miss)} missing: {', '.join(miss)}")
        out += _unchecked_line(unchecked, "")
        if not items and not unchecked:
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
    """The report's lines (plain text, split under Telegram's limit) and, when `xlsx` is given, its
    Excel file, to every brief recipient."""
    import httpx
    from src.config import settings
    token, ids = settings.TELEGRAM_BOT_TOKEN, settings.brief_recipient_ids()
    if not token or not ids:
        logger.warning("Telegram not configured — report not sent")
        return
    from src.bot.replies import split_text
    chunks = split_text("\n".join(lines))   # between lines, under Telegram's limit
    with httpx.Client(timeout=60) as http:
        for chat in ids:
            try:
                for c in chunks:
                    resp = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data={"chat_id": chat, "text": c, "disable_web_page_preview": True})
                    if resp.status_code >= 400:
                        logger.warning("Telegram refused the report for %s: HTTP %s %s", chat,
                                       resp.status_code, resp.text[:200])
                if xlsx is None:
                    continue
                with open(xlsx, "rb") as f:
                    resp = http.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                     data={"chat_id": chat, "caption": "Every incomplete student with the fields they are missing"},
                                     files={"document": (xlsx.name, f)})
                    if resp.status_code >= 400:
                        logger.warning("Telegram refused the Excel file for %s: HTTP %s", chat, resp.status_code)
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
        try:
            print(program_report(key))
        except Exception as e:
            from src.scraper.client import portal_error_reason
            logger.error("missing-information report for %s failed: %s", key, e)
            print(f"❌ Couldn't read the progress sheets or the portal: {portal_error_reason(e)}.\n"
                  f"Missing information — {pb.PROGRAMS[key]['name']}: not available right now. "
                  "Please try again in a minute.")
        return
    if args.student:
        data = read_sheets()
        want = args.student.strip().upper()
        index = portal_index()
        for sk, recs in data.items():
            key, intake = sk.split("|", 1)
            for rec in recs:
                if rec.get("Student ID", "").upper() == want:
                    miss = missing_fields(rec, key, index)
                    unchecked = unchecked_fields(rec, key, index)
                    print(f"{want} {rec.get('Full Name', '')} — {pb.PROGRAMS[key]['name']} {intake}: "
                          f"{len(miss)} missing: {', '.join(miss) or 'nothing'}"
                          + (f" (not checked: {', '.join(unchecked)})" if unchecked else ""))
                    return
        print(f"{want} not found in the progress sheets.")
        return
    # The daily report (09:05): progress sheets or a portal that cannot be read are said to the
    # admin in one plain message, never left to a silent "exit 1" in the log.
    try:
        data = read_sheets()
        lines, rows = build_report(data)
        xlsx = write_excel(rows)
    except Exception as e:
        from src.scraper.client import portal_error_reason
        logger.error("missing-information report failed: %s", e)
        notice = (f"❌ Couldn't build today's missing-information report: {portal_error_reason(e)}. "
                  "It will run again tomorrow at 09:05 (or send /missing).")
        print(notice)
        if not args.no_notify:
            send([notice], None)
        raise SystemExit(1)
    print("\n".join(lines))
    print(f"\nExcel: {xlsx}")
    if not args.no_notify:
        send(lines, xlsx)


if __name__ == "__main__":
    main()
