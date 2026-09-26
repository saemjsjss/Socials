"""
Google Drive/Sheets progress-sheet builder for the Hangeul bot.

For each program+intake it drops a progress sheet into the right Drive folder, filled
with LIVE PORTAL data.

Layout: the flat "Book1" format — ONE header row, the columns in COLUMNS below
(Student ID … Bank Certificate), one row per student.  A program's "drop_columns" are
left out (KLP, EAP and Bachelor's have no Previous University/Subject/Degree/CGPA).

How it works:
  1. PULL every student from the live portal (the read-only students.php?export=csv
     export, all pages in one request).  Direct students only (B2B partner students
     are left out); one sheet per program + intake found on the portal.
  2. If the sheet already exists, UPDATE IT IN PLACE: only the main (portal) tab is
     rewritten, so tabs people add (university sub-sheets) survive every re-run.
  3. Otherwise CREATE a fresh Google Sheet in the intake folder; write header + rows.
  4. FORMAT: Times New Roman 14, bold frozen header, no underlines, dates as
     YYYY-MM-DD, phones as 8801XXXXXXXXX, missing values left blank (never "N/A").

Runtime: a Google OAuth login as rahmansaem@gmail.com (credentials.json -> token.json in
the bot root), plus the portal login the bot already has.  Runs on the PC only (the
portal is unreachable from the cloud).

CLI (run from E:\\BOT):
  python -m src.sheets.progress_builder --auth            # one-time Google login
  python -m src.sheets.progress_builder --dump-profile HNG-2026-920   # inspect portal fields
  python -m src.sheets.progress_builder --program KLP     # build one program's sheet
  python -m src.sheets.progress_builder --all             # build all four
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bot root (E:\BOT) — where credentials.json / token.json live.
BOT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_PATH = BOT_ROOT / "credentials.json"
TOKEN_PATH = BOT_ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

# The parent "ALL STUDENTS" folder (partner.account@example.com) — for reference only; the
# builder writes straight into each program's INTAKE folder below.
PARENT_FOLDER_ID = "14rJxMXNJzS5Z2ABuTI_Iijc-CmAhqer-"

# --- Sheet layout (Book1.xlsx) ---------------------------------------------------
# (sheet header, portal CSV column).  A portal column of None means the value is
# computed (IELTS/TOPIK) or has no field on the portal (Passport Issue -> blank).
COLUMNS: List[tuple] = [
    ("Student ID", "Student ID"),
    ("Full Name", "Full Name"),
    ("Surname", "Surname"),
    ("Given Name", "Given Name"),
    ("Email", "Email"),
    ("Mobile", "Mobile"),
    ("Guardian WhatsApp", "Guardian WhatsApp"),
    ("DOB", "DOB"),
    ("Gender", "Gender"),
    ("District", "District"),
    ("Address", "Address"),
    ("Father", "Father"),
    ("Mother", "Mother"),
    ("Study Status", "Study Status"),
    ("SSC Year", "SSC Year"),
    ("SSC GPA", "SSC GPA"),
    ("SSC Group", "SSC Group"),
    ("SSC School", "SSC School"),
    ("HSC Year", "HSC Year"),
    ("HSC GPA", "HSC GPA"),
    ("HSC Group", "HSC Group"),
    ("HSC College", "HSC College"),
    ("Previous University", "Previous University"),
    ("Subject", "Subject"),
    ("Degree", "Degree"),
    ("CGPA", "CGPA"),
    ("Program", "Program"),
    ("IELTS/TOPIK", None),
    ("Passport Status", "Passport Status"),
    ("Passport No", "Passport No"),
    ("Passport Issue", "_ISSUE_DATE"),
    ("Passport Expiry", "Passport Expiry"),
    ("Visa Rejection History", "Visa Rejection History"),
    ("Sponsor", "Sponsor"),
    ("Sponsor Occupation", "Sponsor Occupation"),
    ("Bank Certificate", "Bank Certificate"),
]
DATE_COLUMNS = {"DOB", "Passport Expiry"}
UNIVERSITY_COLUMNS = ["Previous University", "Subject", "Degree", "CGPA"]
PHONE_COLUMNS = {"Mobile", "Guardian WhatsApp"}

# --- Per-program registry --------------------------------------------------------
# folder_id = the program's folder under ALL STUDENTS.  Each intake gets its own
# sub-folder there (named like "MARCH 2027", created when first needed) holding the
# sheet "<program name> <INTAKE>".  Intakes come from the students' Intake field on
# the portal, so a new intake gets its sheet as soon as a student is on it.
PROGRAMS: Dict[str, Dict[str, Any]] = {
    "KLP": {
        "name": "KOREAN LANGUAGE PROGRAM (KLP)",
        "folder_id": "1t7_Nsk8QOfygaGEWYIwx3nD21Ep_Zpx_",
        "match_tokens": ["korean language program", "klp"],
        "drop_columns": UNIVERSITY_COLUMNS,
    },
    "EAP": {
        "name": "EAP (ENGLISH FOR ACADEMIC PURPOSE)",
        "folder_id": "1QWXwpUkMLbVmbedRqguDrCacctU6n0Nu",
        "match_tokens": ["eap", "english for academic"],
        "drop_columns": UNIVERSITY_COLUMNS,
    },
    "BACHELOR": {
        "name": "BACHELOR'S DEGREE",
        "folder_id": "18eCQDuBUpnTduxoIsILpEBGkuwUqCysI",
        "match_tokens": ["bachelor"],
        "drop_columns": UNIVERSITY_COLUMNS,
    },
    "MASTER": {
        "name": "MASTER'S DEGREE",
        "folder_id": "1aLaTubJU4AnaZx5WM0sXY4Giq6qli1VR",
        "match_tokens": ["master"],
    },
}

_BLANKS = {"", "na", "n/a", "none", "null", "-", "--", "—", "n.a", "n.a.", "not provided", "not applicable"}


# --- small pure helpers ----------------------------------------------------------
def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def clean_value(v: Any) -> str:
    """Trim, and turn every 'no value' marker into a true blank (never 'N/A')."""
    s = "" if v is None else str(v).strip()
    if _norm_key(s) in {_norm_key(b) for b in _BLANKS}:
        return ""
    return s


def normalize_date(v: Any) -> str:
    """Return the date as YYYY-MM-DD when we can recognise it; else the cleaned original."""
    s = clean_value(v)
    if not s:
        return ""
    s2 = s.replace(".", "-").replace("/", "-").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s2)          # YYYY-M-D
    if m:
        y, mo, d = m.groups()
    else:
        m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s2)      # D-M-Y
        if m:
            d, mo, y = m.groups()
        else:
            return s  # unrecognised — leave as-is
    try:
        y, mo, d = int(y), int(mo), int(d)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return s
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except ValueError:
        return s


def normalize_phone(v: Any) -> str:
    """Bangladeshi numbers as 8801XXXXXXXXX (13 digits, no '+', spaces or dashes):
    '+8801700000071' / '01700000072' / '1700000072' -> '8801…'.  Anything that is not
    a recognisable BD mobile keeps just its digits."""
    s = clean_value(v)
    if not s:
        return ""
    d = re.sub(r"\D", "", s)
    if len(d) == 11 and d.startswith("01"):
        return "88" + d
    if len(d) == 10 and d.startswith("1"):
        return "880" + d
    if len(d) == 14 and d.startswith("8800"):      # "+880 01…" typed with the trunk 0
        return "880" + d[4:]
    return d


def ielts_topik(student: Dict[str, Any]) -> str:
    """Combine the portal's separate 'IELTS/TOEFL' and 'Korean Level' fields.
    Only real scores are shown: 'NO', 'NO KNOWLEDGE', 'BASIC …' count as blank."""
    parts = []
    ielts = clean_value(student.get("IELTS/TOEFL", ""))
    if ielts and ielts.upper() not in {"NO", "NONE"}:
        parts.append(f"IELTS {ielts}" if re.match(r"^\d", ielts) else ielts)
    korean = clean_value(student.get("Korean Level", "")).upper()
    if "TOPIK" in korean:
        parts.append(korean)
    return " / ".join(parts)


def program_matches(prog_value: str, match_tokens: List[str]) -> bool:
    p = _norm_key(prog_value)
    return any(_norm_key(tok) in p for tok in match_tokens)


def sheet_title(cfg: Dict[str, Any]) -> str:
    """Sheet file name = '<program name> <INTAKE>' (no 'PROGRESS SHEET' suffix)."""
    return f"{cfg['name']} {cfg['intake']}"


# --- portal roster (async, reuses the bot's scraper) -----------------------------
def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _fetch_all_students_async() -> List[Dict[str, str]]:
    """Every student from the portal's own CSV export of students.php (read-only GET).
    One request covers all pages, and only 'All Students' — never signed_students.php."""
    from src.scraper.client import admin_client
    try:
        if not admin_client.is_authenticated:
            await admin_client.login()
        url = f"{admin_client.base_url}/students.php?export=csv"
        resp = await admin_client.client.get(url, timeout=60.0)
        if "login.php" in str(resp.url):
            admin_client.is_authenticated = False
            await admin_client.login()
            resp = await admin_client.client.get(url, timeout=60.0)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")
        if "text/csv" not in resp.headers.get("content-type", "") and "Full Name" not in text[:2000]:
            raise RuntimeError("portal did not return the students CSV export")
        return [dict(r) for r in csv.DictReader(io.StringIO(text))]
    finally:
        await admin_client.close()


_ALL_STUDENTS_CACHE: Optional[List[Dict[str, str]]] = None


def fetch_all_students() -> List[Dict[str, str]]:
    """Fetched once per run, so --all makes a single portal request."""
    global _ALL_STUDENTS_CACHE
    if _ALL_STUDENTS_CACHE is None:
        _ALL_STUDENTS_CACHE = _run_async(_fetch_all_students_async())
    return _ALL_STUDENTS_CACHE


# Only the agency's own students go on the progress sheets; B2B partner students
# (Source = "B2B") are left out, like the portal's source=direct filter.
INCLUDE_SOURCES = {"direct"}


def normalize_intake(v: Any) -> str:
    """'March 2027' / 'MARCH  2027' -> 'MARCH 2027'; blank markers -> ''."""
    return " ".join(clean_value(v).upper().split())


def program_key_of(student: Dict[str, str]) -> Optional[str]:
    for key, cfg in PROGRAMS.items():
        if program_matches(student.get("Program", ""), cfg["match_tokens"]):
            return key
    return None


def direct_students() -> List[Dict[str, str]]:
    return [s for s in fetch_all_students() if _norm_key(s.get("Source", "")) in INCLUDE_SOURCES]


def target(program_key: str, intake: str) -> Dict[str, Any]:
    """One sheet = one program + one intake."""
    return {**PROGRAMS[program_key], "key": program_key, "intake": normalize_intake(intake)}


def all_targets() -> List[Dict[str, Any]]:
    """Every program + intake that has at least one Direct student on the portal."""
    seen = set()
    for s in direct_students():
        key, intake = program_key_of(s), normalize_intake(s.get("Intake", ""))
        if key and intake:
            seen.add((key, intake))
    order = list(PROGRAMS)
    return [target(k, i) for k, i in sorted(seen, key=lambda t: (order.index(t[0]), t[1]))]


def students_without_intake() -> List[Dict[str, str]]:
    """Direct students whose Intake is blank on the portal (they can't go on a sheet)."""
    return [s for s in direct_students() if program_key_of(s) and not normalize_intake(s.get("Intake", ""))]


def fetch_roster(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    """Direct students in this program AND this intake, in the portal's order."""
    want_intake = normalize_intake(cfg["intake"])
    return [
        s for s in direct_students()
        if program_matches(s.get("Program", ""), cfg["match_tokens"])
        and normalize_intake(s.get("Intake", "")) == want_intake
    ]


def columns_for(cfg: Dict[str, Any]) -> List[tuple]:
    """This program's columns: COLUMNS minus its drop_columns (KLP/EAP/Bachelor's have
    no university columns; Master's keeps them)."""
    drop = set(cfg.get("drop_columns", []))
    return [c for c in COLUMNS if c[0] not in drop]


_ISSUE_CACHE: Optional[Dict[str, str]] = None


def issue_date_for(student: Dict[str, Any]) -> str:
    """Passport issue date: the portal has it on the student edit page only, so it comes
    from the cache filled by src/sheets/passport_issue.py."""
    global _ISSUE_CACHE
    if _ISSUE_CACHE is None:
        from src.sheets import passport_issue
        _ISSUE_CACHE = passport_issue.load()
    return _ISSUE_CACHE.get((student.get("Passport No") or "").strip().upper(), "")


def build_row(student: Dict[str, Any], columns: Optional[List[tuple]] = None) -> List[str]:
    out: List[str] = []
    for header, source in (columns or COLUMNS):
        if header == "IELTS/TOPIK":
            val = ielts_topik(student)
        elif source == "_ISSUE_DATE":
            val = normalize_date(issue_date_for(student))
        elif source is None:
            val = ""
        else:
            val = clean_value(student.get(source, ""))
            if header in DATE_COLUMNS:
                val = normalize_date(val)
            elif header in PHONE_COLUMNS:
                val = normalize_phone(val)
            elif header == "Gender":
                val = val.upper()   # portal mixes "MALE" and "Male"
        out.append(val)
    return out


# --- Google API plumbing ---------------------------------------------------------
def _load_credentials(interactive: bool = False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:
            logger.warning("token refresh failed (%s) — need a fresh login", e)
    if not interactive:
        raise RuntimeError(
            "Google login required. Run:  python -m src.sheets.progress_builder --auth"
        )
    from google_auth_oauthlib.flow import InstalledAppFlow
    cred_path = CREDENTIALS_PATH
    if not cred_path.exists():
        # Windows hides extensions, so "credentials.json" often gets saved as ".json.json".
        doubled = BOT_ROOT / "credentials.json.json"
        if doubled.exists():
            cred_path = doubled
        else:
            raise RuntimeError(f"credentials.json not found at {CREDENTIALS_PATH}. Put it in E:\\BOT.")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _services(interactive: bool = False):
    from googleapiclient.discovery import build
    creds = _load_credentials(interactive=interactive)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def _col_letter(n: int) -> str:
    """1-indexed column number -> A1 letter(s)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _intake_folder(drive, cfg: Dict[str, Any]) -> str:
    """The intake's folder inside the program folder (created if missing)."""
    name = cfg["intake"].replace("\\", "\\\\").replace("'", "\\'")
    found = drive.files().list(
        q=(f"name = '{name}' and '{cfg['folder_id']}' in parents and trashed = false "
           "and mimeType = 'application/vnd.google-apps.folder'"),
        fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if found:
        return found[0]["id"]
    return drive.files().create(
        body={"name": cfg["intake"], "parents": [cfg["folder_id"]],
              "mimeType": "application/vnd.google-apps.folder"},
        fields="id", supportsAllDrives=True).execute()["id"]


def find_sheet(drive, cfg: Dict[str, Any]) -> Optional[str]:
    """The existing sheet for this program + intake, if any."""
    folder = _intake_folder(drive, cfg)
    title = sheet_title(cfg).replace("\\", "\\\\").replace("'", "\\'")
    found = drive.files().list(
        q=(f"name = '{title}' and '{folder}' in parents "
           "and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"),
        orderBy="modifiedTime desc", fields="files(id)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    return found[0]["id"] if found else None


def sheet_drift(cfg: Dict[str, Any]) -> int:
    """How many cells on this sheet's main tab differ from what the portal says it
    should hold (e.g. cells someone cleared or typed over by hand). -1 = no sheet yet."""
    drive, sheets = _services()
    ssid = find_sheet(drive, cfg)
    if not ssid:
        return -1
    tab = sheets.spreadsheets().get(spreadsheetId=ssid, fields="sheets.properties.title"
                                    ).execute()["sheets"][0]["properties"]["title"]
    have = sheets.spreadsheets().values().get(spreadsheetId=ssid, range=f"'{tab}'"
                                              ).execute().get("values", [])
    cols = columns_for(cfg)
    want = [[h for h, _ in cols]] + [build_row(s, cols) for s in fetch_roster(cfg)]
    width = len(cols)
    diff = 0
    for i in range(max(len(have), len(want))):
        a = [str(x) for x in (have[i] if i < len(have) else [])]
        b = want[i] if i < len(want) else []
        a, b = a + [""] * (width - len(a)), b + [""] * (width - len(b))
        diff += sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    return diff


def build_program(program_key: str, dry_run: bool = False) -> List[str]:
    """Build every intake sheet of one program. Returns the sheet URLs."""
    return [build_target(t, dry_run) for t in all_targets() if t["key"] == program_key]


def build_target(cfg: Dict[str, Any], dry_run: bool = False) -> str:
    """Build (or rebuild) one program + intake sheet. Returns the sheet URL."""
    title = sheet_title(cfg)
    logger.info("Building %s", title)

    roster = fetch_roster(cfg)
    logger.info("  portal roster: %d student(s)", len(roster))
    cols = columns_for(cfg)
    header = [h for h, _ in cols]
    rows = [build_row(s, cols) for s in roster]

    if dry_run:
        logger.info("  DRY RUN — not writing to Drive (%d columns x %d rows).", len(header), len(rows))
        return "(dry-run)"

    drive, sheets = _services()

    tab_title = title[:100]
    ncols = len(header)
    nrows = len(rows) + 1

    # 1) re-runnable: if this intake's sheet already exists, update it IN PLACE — only
    #    the main (portal) tab is rewritten; any other tabs people added (university
    #    sub-sheets etc.) are left untouched.  Otherwise create a fresh sheet.
    ssid = find_sheet(drive, cfg)
    if ssid:
        tabs = sheets.spreadsheets().get(spreadsheetId=ssid).execute()["sheets"]
        # the portal tab is the one named after the sheet; fall back to the first tab
        tab = next((t["properties"] for t in tabs if t["properties"]["title"] == tab_title),
                   tabs[0]["properties"])
        sheets.spreadsheets().values().clear(
            spreadsheetId=ssid, range=f"'{tab['title']}'").execute()
        logger.info("  updating existing sheet %s (other tabs kept)", ssid)
    else:
        created = drive.files().create(
            body={"name": title, "parents": [_intake_folder(drive, cfg)],
                  "mimeType": "application/vnd.google-apps.spreadsheet"},
            supportsAllDrives=True, fields="id",
        ).execute()
        ssid = created["id"]
        tab = sheets.spreadsheets().get(spreadsheetId=ssid).execute()["sheets"][0]["properties"]
    tab_id = tab["sheetId"]

    # 2) size + name the tab, then write header and rows
    sheets.spreadsheets().batchUpdate(spreadsheetId=ssid, body={"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": tab_id, "title": tab_title,
                           "gridProperties": {"rowCount": max(nrows, 2), "columnCount": ncols,
                                              "frozenRowCount": 1}},
            "fields": "title,gridProperties.rowCount,gridProperties.columnCount,"
                      "gridProperties.frozenRowCount"}},
    ]}).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=ssid,
        range=f"'{tab_title}'!A1:{_col_letter(ncols)}{nrows}",
        valueInputOption="RAW",
        body={"values": [header] + rows},
    ).execute()

    # 3) Times New Roman 14, no underline; bold header; columns fitted to content
    sheets.spreadsheets().batchUpdate(spreadsheetId=ssid, body={"requests": [
        {"repeatCell": {
            "range": {"sheetId": tab_id},
            "cell": {"userEnteredFormat": {"textFormat": {
                "fontFamily": "Times New Roman", "fontSize": 14, "underline": False}}},
            "fields": "userEnteredFormat.textFormat.fontFamily,"
                      "userEnteredFormat.textFormat.fontSize,"
                      "userEnteredFormat.textFormat.underline"}},
        {"repeatCell": {
            "range": {"sheetId": tab_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": tab_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": ncols}}},
    ]}).execute()

    url = f"https://docs.google.com/spreadsheets/d/{ssid}/edit"
    logger.info("  done: %s", url)
    return url


def dump_profile(student_id: str) -> None:
    """Print one student's portal fields (from the CSV export) to calibrate mappings."""
    want = student_id.strip().upper()
    match = [s for s in fetch_all_students() if clean_value(s.get("Student ID", "")).upper() == want]
    if not match:
        print(f"\nNo student with Student ID {student_id} in students.php.")
        return
    prof = match[0]
    print(f"\nPortal fields for {student_id} ({len(prof)} columns):")
    for k, v in prof.items():
        print(f"  {k!r}: {str(v)[:60]!r}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    ap = argparse.ArgumentParser(description="Build Hangeul progress sheets in Drive.")
    ap.add_argument("--auth", action="store_true", help="do the one-time Google login")
    ap.add_argument("--program", help="build one program's intake sheets: KLP | EAP | BACHELOR | MASTER")
    ap.add_argument("--all", action="store_true", help="build every program + intake sheet")
    ap.add_argument("--dump-profile", metavar="ID", help="print a student's raw portal fields")
    ap.add_argument("--dry-run", action="store_true", help="fetch + map but do NOT write to Drive")
    args = ap.parse_args()

    if args.auth:
        _load_credentials(interactive=True)
        print("Google login OK — token.json saved. You can now build sheets.")
        return
    if args.dump_profile:
        dump_profile(args.dump_profile)
        return
    if args.all:
        for t in all_targets():
            try:
                print(f"{sheet_title(t)}: {build_target(t, dry_run=args.dry_run)}")
            except Exception as e:
                print(f"{sheet_title(t)}: FAILED — {e}")
        missing = students_without_intake()
        if missing:
            print(f"\n{len(missing)} student(s) have no intake on the portal and are on no sheet:")
            for st in missing:
                print(f"  {st.get('Student ID') or '(no ID)'} {st.get('Full Name', '')} — {st.get('Program', '')}")
        return
    if args.program:
        key = args.program.strip().upper()
        if key not in PROGRAMS:
            raise SystemExit(f"Unknown program {key!r}. Choose one of: {', '.join(PROGRAMS)}")
        print(f"{key}: {build_program(key, dry_run=args.dry_run)}")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
