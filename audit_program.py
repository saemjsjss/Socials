#!/usr/bin/env python3
"""
Batch passport cross-check for ONE program (e.g. all Bachelor's Degree students).

For every student in `students.php?prog=<program>` it cross-checks the portal-typed
information against the uploaded passport scan (live EasyOCR + ICAO Doc 9303 MRZ +
visual page), and writes a total report. For each student it separates issues into
three honest buckets:

  * WRONG        -> portal value is present but DISAGREES with the passport
                    (e.g. Passport No: portal='AB123' vs passport='AB129'). Red flags.
  * BLANK        -> the portal record itself has no value in that field (data-entry gap).
  * NOT ON SCAN  -> the field isn't visible on the uploaded scan. Normal for
                    Father/Mother/Address when only the single bio-page was uploaded
                    (the back / emergency page carries those). Informational, not an error.

Sections checked (7): Name, Passport No, DOB, Passport Expiry, Father's Name,
Mother's Name, Permanent Address.

READ-ONLY: only GET requests to the portal (never edits anything).

Run it ON THE PC where the bot lives (the portal is only reachable from there):

    cd E:\\BOT
    python audit_program.py "Bachelor's Degree"

    # any program works, e.g.:
    #   python audit_program.py "Master's Degree"
    #   python audit_program.py "KLP (Korean Language Program)"

Or just double-click `run_passport_audit.bat` (does the Bachelor's Degree run for you).

Output: prints a live progress + summary and writes
`program_audit_<program>_<timestamp>.csv` in the current folder (opens in Excel).
"""
import asyncio
import csv
import os
import re
import sys
from datetime import datetime

from src.scraper.client import admin_client

# The 7 fields treated as "sections" on each student.
SECTIONS = ["name", "passport_no", "dob", "expiry", "father_name", "mother_name", "address"]
SECTION_LABEL = {
    "name": "Name", "passport_no": "Passport No", "dob": "DOB", "expiry": "Passport Expiry",
    "father_name": "Father", "mother_name": "Mother", "address": "Address",
}
# A field whose status is one of these has a portal value that DISAGREES with the passport.
WRONG_STATUSES = {"MISMATCH", "TYPO", "DATE_MISMATCH", "DISCREPANCY", "PARTIAL_MATCH"}
# A field whose status is one of these could not be told for sure (a possible OCR misread, a
# check digit that failed): a person checks it by eye. Never counted as a match.
CHECK_STATUSES = {"OCR_UNCERTAIN", "NOT_READ"}
# Audit results that checked nothing: the portal did not serve the profile or the scan, the OCR
# engine did not run, or the audit itself failed. Never counted as an unreadable scan.
UNCHECKED_STATUSES = {"PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "ERROR"}


async def fetch_program_student_ids(program: str):
    """Return de-duplicated (student_id, list_name, doc_filename) for the program view.

    Only the student IDs are essential — every field used in the cross-check is
    re-fetched live per student inside audit_student_passport(). The list name is just
    for display, and the passport filename is auto-discovered later if missing here.

    Every page of students.php?prog=<program> is read through the shared reader
    (admin_client.read_students: it follows "Page 1 of N", de-duplicates by uid, and raises
    PortalUnavailable when the list cannot be read whole, so a failed read is never "0 students").
    """
    from src.bot.scheduler import passport_scan
    records = await admin_client.read_students({"prog": program})
    return [{"id": s["uid"],
             "name": (s.get("details") or {}).get("Full Name") or s.get("student_name") or "",
             "doc_filename": passport_scan(s)}
            for s in records if s.get("uid")]


def classify(audit: dict):
    """Sort one audit result into buckets.

    Returns a dict:
      scan        -> 'ok' | 'none' (no scan on file) | 'unreadable' (scan present, MRZ unreadable)
                     | 'unchecked' (the portal or the OCR engine failed: nothing was checked)
      wrong       -> ["Passport No: portal='..' vs passport='..'", ...]
      blank       -> ["Father", ...]        (portal field is empty)
      not_on_scan -> ["Father", ...]        (portal has a value, scan doesn't show it)
      check       -> ["Name", ...]          (could not be told for sure: check by eye)
      best_name   -> a name to display, taken from the audit if the list gave none
    """
    status = str(audit.get("status", "")).upper()
    fields = audit.get("fields", {}) or {}
    empty = {"wrong": [], "blank": [], "not_on_scan": [], "check": [], "best_name": ""}
    if status == "MISSING_DOCUMENT":
        return {"scan": "none", **empty}
    if status in UNCHECKED_STATUSES:
        return {"scan": "unchecked", **empty}
    if status in ("MRZ_UNREADABLE", "SCAN_UNREADABLE", "INVALID_DOCUMENT") or not fields:
        return {"scan": "unreadable", **empty}

    wrong, blank, not_on_scan, check = [], [], [], []
    for key in SECTIONS:
        f = fields.get(key)
        if not f:
            continue
        st = str(f.get("status", "")).upper()
        portal = str(f.get("portal", "")).strip()
        doc = str(f.get("doc", "")).strip()
        label = SECTION_LABEL[key]
        if st in WRONG_STATUSES:
            wrong.append(f"{label}: portal='{portal}' vs passport='{doc}'")
        elif not portal:
            blank.append(label)                 # portal record itself is empty
        elif st == "NOT_IN_SCAN":
            not_on_scan.append(label)           # value exists on portal, not on this scan
        elif st in CHECK_STATUSES:
            check.append(label)                 # possible OCR misread: a person looks
        # else st == MATCH (or similar) -> field is fine
    best_name = str((fields.get("name") or {}).get("portal", "")).strip()
    return {"scan": "ok", "wrong": wrong, "blank": blank,
            "not_on_scan": not_on_scan, "check": check, "best_name": best_name}


async def main():
    program = sys.argv[1] if len(sys.argv) > 1 else "Bachelor's Degree"
    print(f"\nLogging in and fetching students for program: {program!r} ...")
    try:
        students = await fetch_program_student_ids(program)
    except Exception as e:
        from src.scraper.client import portal_error_reason
        print(f"Couldn't read the portal: {portal_error_reason(e)}. Nothing was checked.")
        await admin_client.close()
        return 1
    print(f"Found {len(students)} students (every page of the list read).")
    if not students:
        print("Nothing to check. Confirm the program name matches the portal exactly, "
              "and that MOCK_MODE=false with a valid read-only login in .env.")
        await admin_client.close()
        return 1  # non-zero exit, so bootstrap does not count an empty run as success

    print("Cross-checking each passport LIVE (OCR can take a few minutes)...\n")
    rows = []
    n_clean = n_none = n_unreadable = n_unchecked = 0
    n_with_wrong = n_with_blank = n_with_check = 0
    tot_wrong = tot_blank = tot_not_on_scan = 0

    for i, s in enumerate(students, 1):
        form_data = {"name": s["name"]}
        try:
            audit = await admin_client.audit_student_passport(s["id"], form_data, s["doc_filename"])
        except Exception as e:
            audit = {"status": "ERROR", "fields": {}, "verdict": f"audit error: {e}"}

        c = classify(audit)
        name = s["name"] or c["best_name"] or f"(ID {s['id']})"
        wrong, blank, nos, check = c["wrong"], c["blank"], c["not_on_scan"], c["check"]

        if c["scan"] == "none":
            n_none += 1
            flag, scan_txt = "NO-SCAN", "No"
        elif c["scan"] == "unchecked":
            n_unchecked += 1
            flag, scan_txt = "UNCHECKD", "Not checked (portal or OCR failed)"
        elif c["scan"] == "unreadable":
            n_unreadable += 1
            flag, scan_txt = "UNREADBL", "Yes (unreadable)"
        else:
            scan_txt = "Yes"
            if wrong:
                n_with_wrong += 1
            if blank:
                n_with_blank += 1
            if check:
                n_with_check += 1
            if not wrong and not blank and not check:
                n_clean += 1
            flag = "ISSUE" if (wrong or blank) else ("CHECK" if check else "OK")

        tot_wrong += len(wrong)
        tot_blank += len(blank)
        tot_not_on_scan += len(nos)

        rows.append({
            "ID": s["id"],
            "Name": name,
            "Passport Scan": scan_txt,
            "Wrong Count": len(wrong),
            "Wrong Fields (portal vs passport)": " | ".join(wrong),
            "Blank-in-Portal Count": len(blank),
            "Blank-in-Portal Fields": "; ".join(blank),
            "Check-by-eye Fields": "; ".join(check),
            "Not-on-Scan (info)": "; ".join(nos),
            "Verdict": audit.get("verdict", ""),
        })
        print(f"  {i:>2}/{len(students)}  [{flag:>8}] {name}: "
              f"wrong={len(wrong)} blank={len(blank)} check-by-eye={len(check)} not-on-scan={len(nos)}")

    safe = re.sub(r"[^A-Za-z0-9]+", "_", program).strip("_") or "program"
    out = os.path.abspath(f"program_audit_{safe}_{datetime.now():%Y%m%d_%H%M}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n================ TOTAL REPORT ================")
    print(f"Program:                         {program}")
    print(f"Students checked:                {len(students)}")
    print(f"Fully clean (all match):         {n_clean}")
    print(f"Have WRONG info (mismatches):    {n_with_wrong}   (total wrong fields: {tot_wrong})")
    print(f"Have BLANK portal fields:        {n_with_blank}   (total blank fields: {tot_blank})")
    print(f"Have fields to check by eye:     {n_with_check}   (possible OCR misreads, not errors)")
    print(f"No passport scan on file:        {n_none}")
    print(f"Scan on file but MRZ unreadable: {n_unreadable}")
    print(f"Not checked (portal/OCR failed): {n_unchecked}")
    print(f"'Not on scan' occurrences (info):{tot_not_on_scan}   "
          f"(usually Father/Mother/Address on single-page scans)")
    print(f"\nPer-student detail written to:\n  {out}")
    print("=============================================\n")

    # Auto-open the CSV in Excel on Windows (best-effort; harmless if it fails).
    try:
        if os.name == "nt":
            os.startfile(out)  # noqa: E1101 (Windows-only)
    except Exception:
        pass

    await admin_client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
