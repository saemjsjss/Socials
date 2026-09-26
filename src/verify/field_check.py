"""
Field check — does the portal's record agree with the student's documents?

The progress sheet holds ~32 fields per student, but only the ones below can be proved
from documents (the rest are workflow fields: Student ID, Email, Mobile, Program,
Passport Status, Bank Certificate, Sponsor, Visa Rejection History, Study Status).

For each checkable field the value is looked for in the documents that could carry it:

  MATCH      the value appears in the right document
  DIFFERS    that document clearly holds a different value (worth a human's eye)
  UNREADABLE the document is there but OCR could not read that part

CLI (run from the BOT folder):
  python -m src.verify.field_check --passport A00990016
  python -m src.verify.field_check --program BACHELOR
  python -m src.verify.field_check --program MASTER --report master_fields.xlsx
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.sheets import progress_builder as pb
from src.verify import rules as R
from src.verify.doc_verifier import (REPORT_DIR, classify, find_dates, find_money_taka, norm,
                                     portal_students, program_of, read_document, readable,
                                     student_folders)

logger = logging.getLogger(__name__)

MATCH, DIFFERS, UNREADABLE, NO_DOC = "MATCH", "DIFFERS", "UNREADABLE", "NO DOCUMENT"

# field -> the documents that could carry it (matched against the report's document titles)
SOURCES: Dict[str, List[str]] = {
    "Full Name": ["01 Passport", "03 Student NID", "04 Birth", "06 Family", "07 Academic", "10 Affidavit"],
    "Surname": ["01 Passport", "07 Academic", "04 Birth"],
    "Given Name": ["01 Passport", "07 Academic", "04 Birth"],
    "DOB": ["01 Passport", "03 Student NID", "04 Birth", "06 Family", "07 Academic"],
    "Gender": ["01 Passport", "03 Student NID", "04 Birth"],
    "District": ["01 Passport", "03 Student NID", "04 Birth", "05 ", "06 Family"],
    "Address": ["01 Passport", "03 Student NID", "04 Birth", "05 ", "06 Family"],
    "Father": ["01 Passport", "03 Student NID", "04 Birth", "05 Father", "06 Family", "07 Academic"],
    "Mother": ["01 Passport", "03 Student NID", "04 Birth", "05 Mother", "06 Family", "07 Academic"],
    "SSC Year": ["07 Academic"], "SSC GPA": ["07 Academic"], "SSC Group": ["07 Academic"],
    "SSC School": ["07 Academic"], "HSC Year": ["07 Academic"], "HSC GPA": ["07 Academic"],
    "HSC Group": ["07 Academic"], "HSC College": ["07 Academic"], "CGPA": ["07 Academic"],
    "Previous University": ["07 Academic"],
    "Passport No": ["01 Passport"], "Passport Expiry": ["01 Passport"], "Passport Issue": ["01 Passport"],
    "Guardian WhatsApp": ["01 Passport", "09 Financial"],
    "Sponsor Occupation": ["09 Financial"],
}
DATE_FIELDS = {"DOB", "Passport Expiry", "Passport Issue"}
NUMBER_FIELDS = {"Passport No", "Guardian WhatsApp", "SSC Year", "HSC Year"}
GPA_FIELDS = {"SSC GPA", "HSC GPA", "CGPA"}


_OCR_SWAPS = str.maketrans({"a": "4", "o": "0", "i": "1", "l": "1", "s": "5", "b": "8",
                            "A": "4", "O": "0", "I": "1", "L": "1", "S": "5", "B": "8"})


def _ocr_variant(s: str) -> str:
    """Normalise the letters OCR most often turns into digits, so A00990007 and the
    scanned '400990007' compare equal."""
    return re.sub(r"\W", "", str(s).lower()).translate(_OCR_SWAPS)


def _docs_for(field: str, texts: Dict[str, str]) -> Dict[str, str]:
    pats = SOURCES.get(field, [])
    return {k: v for k, v in texts.items() if any(k.startswith(p) or p in k for p in pats)}


def _validity_consistent(issue: str, expiry: str) -> str:
    """A Bangladeshi passport is issued for exactly 5 or 10 years, so the issue date is
    provable from the expiry date alone: expiry = issue + 5 or 10 years (less a day)."""
    try:
        i = dt.date.fromisoformat(pb.normalize_date(issue))
        e = dt.date.fromisoformat(pb.normalize_date(expiry))
    except ValueError:
        return ""
    for years in (5, 10):
        try:
            due = i.replace(year=i.year + years)
        except ValueError:                     # 29 February
            due = i.replace(year=i.year + years, day=28)
        if abs((e - due).days) <= 3:
            return f"{years}-year passport: issue {i} + {years} years = expiry {e}"
    return ""


def check_field(field: str, value: str, texts: Dict[str, str],
                student: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    docs = _docs_for(field, texts)
    if not docs:
        return NO_DOC, "none of the documents that carry this field were uploaded"
    v = str(value).strip()
    for name, text in docs.items():
        if field in DATE_FIELDS:
            try:
                d = dt.date.fromisoformat(pb.normalize_date(v))
            except ValueError:
                continue
            if d in find_dates(text):
                return MATCH, f"found on {name}"
            # passports carry the date again as YYMMDD in the machine-readable lines
            if re.search(r"P<[A-Z<]{3,}", text.upper()) or "<<<" in text:
                if d.strftime("%y%m%d") in re.sub(r"[^0-9]", "", text):
                    return MATCH, f"found in the machine-readable line of {name}"
        elif field in NUMBER_FIELDS:
            flat = re.sub(r"\W", "", norm(text))
            if re.sub(r"\W", "", v).lower() in flat:
                return MATCH, f"found on {name}"
            # OCR confuses letters and digits on passport scans: A<->4, O<->0, I<->1, S<->5, B<->8
            if _ocr_variant(v) in _ocr_variant(flat):
                return MATCH, f"found on {name} (OCR read a digit for a letter)"
        elif field in GPA_FIELDS:
            g = v.rstrip("0").rstrip(".")
            if v in text or (g and re.search(rf"\b{re.escape(g)}\d*\b", text)):
                return MATCH, f"found on {name}"
        else:
            toks = [t for t in norm(v).split() if len(t) > 2]
            if toks and sum(1 for t in toks if t in norm(text)) >= max(1, len(toks) - 1):
                return MATCH, f"found on {name}"

    # not found: is the document readable (so the value really differs), or just unreadable?
    readable_docs = [n for n, t in docs.items() if readable(t)]
    if not readable_docs:
        return UNREADABLE, f"could not read {', '.join(docs)} well enough to compare"
    if student and field in ("Passport Issue", "Passport Expiry"):
        issue, expiry = ((v, student.get("Passport Expiry", "")) if field == "Passport Issue"
                         else (student.get("Passport Issue", "") or
                               __import__("src.sheets.passport_issue", fromlist=["load"]).load()
                               .get((student.get("Passport No") or "").upper(), ""), v))
        ok = _validity_consistent(issue, expiry)
        if ok:
            other = "expiry" if field == "Passport Issue" else "issue"
            return MATCH, f"consistent with the passport's {other} date ({ok})"
    if field in DATE_FIELDS:
        others = sorted({d.isoformat() for n in readable_docs for d in find_dates(docs[n])})
        if others:
            return DIFFERS, f"{', '.join(readable_docs)} shows {', '.join(others[:4])} instead"
        return UNREADABLE, f"no date could be read from {', '.join(readable_docs)}"
    if field == "Sponsor Occupation" and re.search(r"business", str(v), re.I):
        if any(re.search(r"trade\s*licen", docs[n], re.I) for n in readable_docs):
            return MATCH, ("a trade licence in the sponsor's name is on file — it names the trade "
                           "rather than the word 'business'")
    if field == "Passport No":
        # only a plausible Bangladeshi passport number counts as a real difference
        found = sorted({m.group(0) for n in readable_docs
                        for m in re.finditer(r"\b(?:[A-Z]\d{8}|B[MWXY]\d{7})\b", docs[n].upper())})
        found = [f for f in found if _ocr_variant(f) != _ocr_variant(v)]
        if found:
            return DIFFERS, f"the passport shows {', '.join(found[:3])} instead"
    return UNREADABLE, f"not found on {', '.join(readable_docs)} (OCR may have missed it)"


ISSUE_CACHE_MAX_HOURS = 26      # the scheduler refreshes it daily at 08:30


def issue_cache_age_hours() -> Optional[float]:
    """How old the passport-issue cache is, in hours.

    That cache is the one portal value not carried by the students export, so it is read
    separately and can fall behind.  Reporting a difference from a stale copy accuses
    someone of a mistake they have already corrected, which is worse than staying quiet.
    """
    try:
        from src.sheets import passport_issue
        path = passport_issue.CACHE_PATH
        if not path.exists():
            return None
        return (dt.datetime.now() - dt.datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
    except Exception as e:
        logger.warning("could not judge the age of the issue-date cache: %s", e)
        return None


def check_student(pas: str, folder: Path, student: Dict[str, str]) -> List[Dict[str, object]]:
    program = program_of(student)
    cfg = pb.target(program, pb.normalize_intake(student.get("Intake", "")))
    cols = pb.columns_for(cfg)
    row = dict(zip([h for h, _ in cols], pb.build_row(student, cols)))
    texts: Dict[str, str] = {}
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        key = classify(f.name)
        title = R.TITLES.get(key, key or f.stem)
        try:
            t, _ = read_document(f)
        except Exception as e:
            t = ""
            logger.warning("%s unreadable: %s", f.name, e)
        texts[title] = texts.get(title, "") + "\n" + t
    out = []
    for field in [h for h, _ in cols]:
        if field not in SOURCES:
            continue
        value = row.get(field, "")
        if not value:
            out.append({"field": field, "portal": "", "result": "BLANK",
                        "detail": "nothing on the portal to check"})
            continue
        result, detail = check_field(field, value, texts, student)
        if field == "Passport Issue" and result == DIFFERS:
            age = issue_cache_age_hours()
            if age is None or age > ISSUE_CACHE_MAX_HOURS:
                result = UNREADABLE
                detail = (f"the portal's issue date is held in a cache that is "
                          f"{'missing' if age is None else f'{age:.0f} hours old'} — refresh it "
                          "before treating this as an error "
                          "(python -m src.sheets.passport_issue --refresh)")
        out.append({"field": field, "portal": value, "result": result, "detail": detail})
    return out


def write_report(rows: List[Dict[str, object]], path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    colour = {MATCH: "C6EFCE", DIFFERS: "FFC7CE", UNREADABLE: "FFEB9C", NO_DOC: "F2F2F2", "BLANK": "FFFFFF"}
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Field check"
    ws.append(["Student", "Passport", "Program", "Field", "Portal value", "Result", "Detail"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r["student"], r["passport"], r["program"], r["field"], r["portal"], r["result"], r["detail"]])
        ws.cell(row=ws.max_row, column=6).fill = PatternFill("solid", fgColor=colour.get(str(r["result"]), "FFFFFF"))
    ws.freeze_panes = "A2"
    for col, w in zip("ABCDEFG", (28, 13, 11, 22, 30, 12, 70)):
        ws.column_dimensions[col].width = w

    ws2 = wb.create_sheet("Summary")
    ws2.append(["Student", "Passport", "Program", "Checked", "Match", "Differs", "Unreadable", "No document", "Blank"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    per: Dict[str, Dict[str, object]] = {}
    for r in rows:
        s = per.setdefault(str(r["passport"]), {"student": r["student"], "program": r["program"],
                                                MATCH: 0, DIFFERS: 0, UNREADABLE: 0, NO_DOC: 0, "BLANK": 0})
        s[str(r["result"])] = int(s.get(str(r["result"]), 0)) + 1
    for pas, s in per.items():
        checked = int(s[MATCH]) + int(s[DIFFERS]) + int(s[UNREADABLE])
        ws2.append([s["student"], pas, s["program"], checked, s[MATCH], s[DIFFERS], s[UNREADABLE],
                    s[NO_DOC], s["BLANK"]])
        if int(s[DIFFERS]):
            ws2.cell(row=ws2.max_row, column=6).fill = PatternFill("solid", fgColor="FFC7CE")
    ws2.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHI", (28, 13, 11, 9, 8, 9, 12, 13, 8)):
        ws2.column_dimensions[col].width = w
    wb.save(path)
    return path


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Check portal fields against the student's documents.")
    ap.add_argument("--passport", help="one student")
    ap.add_argument("--program", help="KLP | EAP | BACHELOR | MASTER")
    ap.add_argument("--report", default="", help="report file name")
    ap.add_argument("--skip", default="", help="comma-separated passports to skip")
    args = ap.parse_args()

    folders, portal = student_folders(), portal_students()
    skip = {s.strip().upper() for s in args.skip.split(",") if s.strip()}
    if args.passport:
        picks = [args.passport.strip().upper()]
    elif args.program:
        key = args.program.strip().upper()
        picks = sorted(p for p in folders if p in portal and p not in skip
                       and program_of(portal[p]) == key)
    else:
        ap.print_help()
        return

    out = REPORT_DIR / (args.report or f"field_check_{dt.datetime.now():%Y-%m-%d_%H%M}.xlsx")
    rows: List[Dict[str, object]] = []
    for i, pas in enumerate(picks, 1):
        if pas not in folders or pas not in portal:
            continue
        student = portal[pas]
        res = check_student(pas, folders[pas][0], student)
        counts: Dict[str, int] = {}
        for r in res:
            counts[str(r["result"])] = counts.get(str(r["result"]), 0) + 1
            rows.append({**r, "student": student.get("Full Name", ""), "passport": pas,
                         "program": program_of(student)})
        print(f"[{i}/{len(picks)}] {student.get('Full Name', '')[:28]:30} "
              f"match {counts.get(MATCH, 0):>2} | differs {counts.get(DIFFERS, 0)} | "
              f"unreadable {counts.get(UNREADABLE, 0)}", flush=True)
        write_report(rows, out)
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
