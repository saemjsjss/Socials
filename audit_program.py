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
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from src.scraper.client import admin_client

# The 7 fields treated as "sections" on each student.
SECTIONS = ["name", "passport_no", "dob", "expiry", "father_name", "mother_name", "address"]
SECTION_LABEL = {
    "name": "Name", "passport_no": "Passport No", "dob": "DOB", "expiry": "Passport Expiry",
    "father_name": "Father", "mother_name": "Mother", "address": "Address",
}
# A field whose status is one of these has a portal value that DISAGREES with the passport.
WRONG_STATUSES = {"MISMATCH", "TYPO", "DATE_MISMATCH", "DISCREPANCY", "PARTIAL_MATCH"}


async def fetch_program_student_ids(program: str):
    """Return de-duplicated (student_id, list_name, doc_filename) for the program view.

    Only the student IDs are essential — every field used in the cross-check is
    re-fetched live per student inside audit_student_passport(). The list name is just
    for display, and the passport filename is auto-discovered later if missing here.
    """
    if not admin_client.is_authenticated:
        await admin_client.login()

    # The list shows 50 students per page ("Page 1 of 5"); read every page, not just the
    # first, or larger programs are silently cut short.
    by_id = {}
    page, pages = 1, 1
    while page <= pages:
        url = f"{admin_client.base_url}/students.php?prog={quote_plus(program)}&pg={page}"
        resp = await admin_client.client.get(url)
        if "login.php" in str(resp.url):  # session expired -> re-auth and retry
            admin_client.is_authenticated = False
            await admin_client.login()
            resp = await admin_client.client.get(url)
        m = re.search(r"Page \d+ of (\d+)", resp.text)
        pages = int(m.group(1)) if m else page
        _collect_rows(BeautifulSoup(resp.text, "html.parser"), by_id)
        page += 1
    return list(by_id.values())


def _collect_rows(soup, by_id):
    """Add every student row on one list page to by_id (keyed by student id)."""
    for tr in soup.find_all("tr"):
        edit_a = tr.find("a", href=re.compile(r"student_edit\.php\?id=\d+"))
        if not edit_a:
            continue
        stu_id = re.search(r"id=(\d+)", edit_a.get("href")).group(1)
        text = tr.get_text(" ", strip=True)
        name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|Passport|$)", text)
        pass_a = tr.find("a", href=re.compile(r"view_doc\.php\?f=passport_"))
        doc_filename = re.search(r"f=([^&]+)", pass_a.get("href")).group(1) if pass_a else None
        by_id[stu_id] = {
            "id": stu_id,
            "name": name_m.group(1).strip() if name_m else "",
            "doc_filename": doc_filename,
        }


def classify(audit: dict):
    """Sort one audit result into buckets.

    Returns a dict:
      scan        -> 'ok' | 'none' (no scan on file) | 'unreadable' (scan present, MRZ unreadable)
      wrong       -> ["Passport No: portal='..' vs passport='..'", ...]
      blank       -> ["Father", ...]        (portal field is empty)
      not_on_scan -> ["Father", ...]        (portal has a value, scan doesn't show it)
      best_name   -> a name to display, taken from the audit if the list gave none
    """
    status = str(audit.get("status", "")).upper()
    fields = audit.get("fields", {}) or {}
    if status == "MISSING_DOCUMENT":
        return {"scan": "none", "wrong": [], "blank": [], "not_on_scan": [], "best_name": ""}
    if status == "INVALID_DOCUMENT" or not fields:
        return {"scan": "unreadable", "wrong": [], "blank": [], "not_on_scan": [], "best_name": ""}

    wrong, blank, not_on_scan = [], [], []
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
        # else st == MATCH (or similar) -> field is fine
    best_name = str((fields.get("name") or {}).get("portal", "")).strip()
    return {"scan": "ok", "wrong": wrong, "blank": blank,
            "not_on_scan": not_on_scan, "best_name": best_name}


async def main():
    program = sys.argv[1] if len(sys.argv) > 1 else "Bachelor's Degree"
    print(f"\nLogging in and fetching students for program: {program!r} ...")
    students = await fetch_program_student_ids(program)
    print(f"Found {len(students)} students.")
    if not students:
        print("Nothing to check. Confirm the program name matches the portal exactly, "
              "and that MOCK_MODE=false with a valid read-only login in .env.")
        await admin_client.close()
        return 1  # non-zero exit, so bootstrap does not count an empty run as success

    print("Cross-checking each passport LIVE (OCR can take a few minutes)...\n")
    rows = []
    n_clean = n_none = n_unreadable = 0
    n_with_wrong = n_with_blank = 0
    tot_wrong = tot_blank = tot_not_on_scan = 0

    for i, s in enumerate(students, 1):
        form_data = {"name": s["name"]}
        try:
            audit = await admin_client.audit_student_passport(s["id"], form_data, s["doc_filename"])
        except Exception as e:
            audit = {"status": "ERROR", "fields": {}, "verdict": f"audit error: {e}"}

        c = classify(audit)
        name = s["name"] or c["best_name"] or f"(ID {s['id']})"
        wrong, blank, nos = c["wrong"], c["blank"], c["not_on_scan"]

        if c["scan"] == "none":
            n_none += 1
            flag, scan_txt = "NO-SCAN", "No"
        elif c["scan"] == "unreadable":
            n_unreadable += 1
            flag, scan_txt = "UNREADBL", "Yes (unreadable)"
        else:
            scan_txt = "Yes"
            if wrong:
                n_with_wrong += 1
            if blank:
                n_with_blank += 1
            if not wrong and not blank:
                n_clean += 1
            flag = "OK" if (not wrong and not blank) else "ISSUE"

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
            "Not-on-Scan (info)": "; ".join(nos),
            "Verdict": audit.get("verdict", ""),
        })
        print(f"  {i:>2}/{len(students)}  [{flag:>8}] {name}: "
              f"wrong={len(wrong)} blank={len(blank)} not-on-scan={len(nos)}")

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
    print(f"No passport scan on file:        {n_none}")
    print(f"Scan on file but MRZ unreadable: {n_unreadable}")
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
