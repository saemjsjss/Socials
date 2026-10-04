# 07 — Google Sheets, reports and the document/OCR check

**What's in this file:** how Hangeul BOT keeps one Google Sheet per program+intake in step with the portal, and what it tells Telegram when something changes. It also covers the 09:05 missing-information report, the `/stage` report, the verified-documents download, the 08:30 passport issue-date refresh, and the document/OCR verifier (`results.json`, `DOCUMENT CHECK.xlsx`, `FIELD CHECK.xlsx`, what PASS / REVIEW / FAIL / INCOMPLETE mean, and the rule decisions taken in the migration), and, since 30 Sep 2026, what each of these jobs hands to Supabase as its very last step (§13).
The function-level map of these modules is in [03c_FILES_sheets_verify_root_scripts.md](03c_FILES_sheets_verify_root_scripts.md); the schedule and the Telegram commands are in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md); tests and audits are in [10_TESTS_AND_VERIFICATION.md](10_TESTS_AND_VERIFICATION.md). The sync inside the whole system (subprocess model, data stores) is in [01_ARCHITECTURE.md](01_ARCHITECTURE.md) §2.5, the Google credential files in [secrets/README.md](secrets/README.md), the rules R11, R12, R20, R21 in [09](09_BLUEPRINT_RULES_AND_LESSONS.md), the Supabase publish layer the jobs hand their reads to in [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md) (its code map: [03d](03d_FILES_src_cloud.md); its local files and settings: [02 §2.1, §3.11](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)), and the pack index in [00_INDEX.md](00_INDEX.md).

**Pack written:** 29 Sep 2026 at `c17d887`. **Refreshed:** 30 Sep 2026 (Asia/Dhaka) at `8317741`. Numbers marked "29 Sep" are from the first edition; the refresh adds the 30 Sep figures from the data files in `C:\Hangeul\BOT\data` (counts only). `path:line` is at `8317741`: of the modules below only `src\sheets\auto_sync.py`, `missing_report.py`, `passport_issue.py`, `stage_report.py` and `verified_docs.py` changed (the Supabase hooks and one Cloudflare decode); `progress_builder.py`, `attendance.py` and all of `src\verify\` are as they were, so their line numbers still hold. Student data is shown only as `<placeholders>`.

---

## 1. The big picture

```
                    hangeul.com.bd/admin  (read-only: GET + the login POST, nothing else)
   students.php?export=csv │ students.php?source=direct&filter_docs=verified │ download_docs.php?uid=N&zip=1
          │                                   │                                        │
          ▼                                   ▼                                        ▼
  progress_builder ──► Google Sheets   verified_docs.run_local ──► C:\Hangeul\VERIFIED STUDENT DOCUMENTS\<PROG>\<NAME (PASSPORT)>\
  (one sheet per program+intake)              │                         (files > 2 MB shrunk, originals kept)
          │                                   ▼
          └──────────────► auto_sync.run_once (every 15 min, own process) ──► Telegram "🔄 Portal sync — changes found"
                                              │
                                              ▼
                       auto_verify.run(budget=6) ──► doc_verifier + page_checks + field_check (EasyOCR on the GPU)
                                              │            │
                                              │            └─► data\verification\results.json ─► DOCUMENT CHECK.xlsx
                                              │                                              └─► FIELD CHECK.xlsx
                                              └─► Telegram "🔍 Document check"

  08:30  passport_issue --refresh  (student_edit.php per student) ─► data\passport_issue.json
  09:05  missing_report            (the sheets' main tabs + the CSV) ─► Telegram text + missing_information_<date>.xlsx
  /stage stage_report              (students.php every page + progress.php per student) ─► Telegram text

  every job above, LAST, after Drive / Sheets / .xlsx / Telegram (only while publishing is on):
     src.cloud.sheet_hooks.after_*  ─► data\cloud\pending\<time>-<job>.json ─► python -m src.cloud.publish (own
     CPU-only process, never waited for) ─► Supabase hg_sync (rows + text + gte-small embeddings)      (§13)
```

**Design rules that shape every part** (and why):

1. **The portal is read-only.** Findings are reported; staff correct the portal by hand (guardrails rules 1 and 7; HANDOFF §1). Every job reads `students.php` ("All Students") and never `signed_students.php` (rule 6).
2. **A sheet's main tab mirrors the portal.** Staff notes go in their own tabs, which the bot never touches. Hand edits to the main tab are undone (and reported) on the next quiet run.
3. **Never report from stale or partial data.** A list that cannot be read whole raises `PortalUnavailable`, and the job says "Couldn't read the portal" rather than showing 0 or "none". A passport-issue difference from a cache over 26 h old is downgraded to UNREADABLE.
4. **Every heavy job is its own subprocess** (`scheduler._run_module`), so an OCR crash or a Google outage cannot take the bot down, and GPU memory starts clean each run.
5. **Notify only on change, and only about outages that persist** (3 consecutive failed runs), so a passing Google 503 never pings anyone.
6. **Supabase is a copy made last, never a step the job waits for.** Each job keeps what it already read, and only when it has finished its own work (sheets, files, Telegram) hands it over in one small file to a publisher process of its own. A Supabase outage is one log line and changes nothing a job sends or writes (§13).

---

## 2. Google authentication (OAuth user token, **not** a service account)

The task brief called this "service-account auth", but **no service account exists** (HANDOFF §2). The bot signs in as the owner's own Google account through the OAuth "installed application" flow:

| Item | Value |
|---|---|
| Client secrets | `C:\Hangeul\BOT\credentials.json`: a **Desktop** OAuth client from Google Cloud project `hangeul-bo` (Google Auth Platform → Clients). Copy: `secrets\credentials.json` |
| User token | `C:\Hangeul\BOT\token.json` (access and refresh token). Copy: `secrets\token.json` |
| Scopes | `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/spreadsheets` (`progress_builder.SCOPES`) |
| First sign-in | `.venv\Scripts\python.exe -m src.sheets.progress_builder --auth` (or `gauth.bat`). This runs `InstalledAppFlow.run_local_server(port=0)`: a browser opens, you sign in as the owner's account, click "Advanced → Go to Hangeul Bot (unsafe)", and allow both Drive and Sheets. It writes `token.json` |
| Refresh | `_load_credentials()`: an expired token with a refresh token is refreshed and `token.json` is **rewritten**. A non-interactive call without a valid token raises `RuntimeError("Google login required. Run: python -m src.sheets.progress_builder --auth")` |
| Publishing status | The OAuth app has been **In production** since 27 Sep 2026, so refresh tokens no longer expire after 7 days. A sign-in made while the app is in "Testing" still expires (MIGRATION §6) |
| APIs used | Drive v3 (`files.list/create/update`, `appProperties`, `supportsAllDrives=True`, `includeItemsFromAllDrives=True`); Sheets v4 (`spreadsheets.get`, `values.get/clear/update`, `batchUpdate`). Clients built with `cache_discovery=False` |
| Who uses it | `progress_builder` (the sheets), `missing_report.read_sheets`, `verified_docs` (Drive mode and the `_drive_complete_names` check inside every sync), `attendance` (not wired) |

A replica needs the equivalent: an OAuth Desktop client whose consent screen is published "In production", a one-time interactive sign-in, and write access to `token.json` so refreshes persist. A service account would also work if the Drive folders were shared with it, but this system does not use one. The step-by-step setup for a **new** Google account (Cloud project, the two APIs, consent screen, client, Drive folders, first sign-in) is [02 §3.5 "Google from zero"](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md).

---

## 3. The progress sheets

### 3.1 Drive layout and programs

```
ALL STUDENTS                         (PARENT_FOLDER_ID <Drive folder id: ALL STUDENTS, see progress_builder.py:56>, owned by the agency account)
├── KOREAN LANGUAGE PROGRAM (KLP)/   folder_id <Drive folder id: KLP, see progress_builder.py:111>
│   ├── DECEMBER 2026/  └ spreadsheet "KOREAN LANGUAGE PROGRAM (KLP) DECEMBER 2026"
│   ├── MARCH 2027/     └ …
│   └── SEPTEMBER 2027/ └ …
├── EAP (ENGLISH FOR ACADEMIC PURPOSE)/  folder_id <Drive folder id: EAP, see progress_builder.py:117>
├── BACHELOR'S DEGREE/               folder_id <Drive folder id: BACHELOR, see progress_builder.py:123>
├── MASTER'S DEGREE/                 folder_id <Drive folder id: MASTER, see progress_builder.py:129>
├── VERIFIED STUDENT DOCUMENTS/      (Drive mode of verified_docs, used by the old PC; folders flagged complete are skipped by the sync, see §4)
└── KONYANG DOCUMENTS/               (41 older student folders, left in Drive; not used)
```

The Drive folder ids and the attendance sheet id are **identifiers, not secrets** (reaching them still needs the OAuth token), but they point straight at the student sheets, so the pack masks them as `<Drive folder id: …>`. The real values are hard-coded in `src\sheets\progress_builder.py:56` (`PARENT_FOLDER_ID`), `:111`, `:117`, `:123`, `:129` (`PROGRAMS[*]["folder_id"]`) and `src\sheets\attendance.py:21` (`SHEET_ID`). A new agency creates its own folders and puts their ids there (better: in `.env`); see [02 §3.5 "Google from zero"](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md) and [12 Adaptation map](12_ADAPTATION_MAP.md).

| Key | Sheet name part (`name`) | `match_tokens` (substring of the normalised `Program`) | `drop_columns` |
|---|---|---|---|
| `KLP` | `KOREAN LANGUAGE PROGRAM (KLP)` | `korean language program`, `klp` | the 4 university columns |
| `EAP` | `EAP (ENGLISH FOR ACADEMIC PURPOSE)` | `eap`, `english for academic` | the 4 university columns |
| `BACHELOR` | `BACHELOR'S DEGREE` | `bachelor` | the 4 university columns |
| `MASTER` | `MASTER'S DEGREE` | `master` | none (keeps Previous University, Subject, Degree, CGPA) |

- **One spreadsheet = one program + one intake.** The intake folder (e.g. `MARCH 2027`) is created inside the program folder the first time a student is on that intake. The file name and the main tab title are both `"<program name> <INTAKE>"` (the tab title is cut to 100 characters).
- **Targets** come from the data: every (program, intake) with at least one **Direct** student (`Source` = direct; B2B partner students are excluded, like the portal's `source=direct` filter). Intakes are normalised to upper case with single spaces (`"March  2027"` → `"MARCH 2027"`). A student with a program but no intake is on no sheet; `--all` and the missing report list them.
- **Sheets that exist** (rows from `data\sheet_state.json`, all keyed by Student ID), 29 Sep → 30 Sep 2026 23:43: KLP DECEMBER 2026 (124 → 124), KLP MARCH 2027 (89 → 94), KLP SEPTEMBER 2027 (3 → 3), EAP DECEMBER 2026 (25 → 25), EAP MARCH 2027 (5 → 6), BACHELOR'S DEGREE MARCH 2027 (56 → 58), MASTER'S DEGREE MARCH 2027 (28 → 30). The Bachelor's spreadsheet also has 2 university tabs a manager added by hand; they survived the cold-start rebuild.

### 3.2 Source of the data
The rows come from `GET students.php?export=csv` in **one request** (all students, 63 columns; the list is in [04 §3.3](04_PORTAL_INTEGRATION.md); HANDOFF.md:95 says 62; the export saved by the 28 Sep re-verification has 63, `Passport Issue Date` among them). Page-by-page scraping was abandoned early because it silently capped at 50 students (HANDOFF §3). The CSV is decoded `utf-8-sig` and read with `csv.DictReader`. A response that is neither `text/csv` nor contains `Full Name` in its first 2000 characters is an error (usually a login page). It is fetched once per process (`_ALL_STUDENTS_CACHE`), so the sync, `--all` and the verifier share one snapshot.

### 3.3 Columns ("Book1" flat layout, one header row, one row per student)

| # | Header | From the CSV column | Transform |
|---|---|---|---|
| 1 | Student ID | `Student ID` | `clean_value` (the HNG id, `HNG-<year>-<n>`; blank until payment is verified) |
| 2 | Full Name | `Full Name` | clean |
| 3 | Surname | `Surname` | clean |
| 4 | Given Name | `Given Name` | clean |
| 5 | Email | `Email` | clean |
| 6 | Mobile | `Mobile` | `normalize_phone` → `8801XXXXXXXXX` |
| 7 | Guardian WhatsApp | `Guardian WhatsApp` | `normalize_phone` |
| 8 | DOB | `DOB` | `normalize_date` → `YYYY-MM-DD` |
| 9 | Gender | `Gender` | upper case (the portal mixes `MALE`/`Male`) |
| 10–13 | District, Address, Father, Mother | same names | clean |
| 14 | Study Status | `Study Status` | clean |
| 15–18 | SSC Year, SSC GPA, SSC Group, SSC School | same | clean |
| 19–22 | HSC Year, HSC GPA, HSC Group, HSC College | same | clean |
| 23–26 | Previous University, Subject, Degree, CGPA | same | clean (**Master's only**) |
| 27 | Program | `Program` | clean |
| 28 | IELTS/TOPIK | computed | `IELTS/TOEFL` (a number → `IELTS 6.5`; NO/NONE dropped) + `Korean Level` when it contains TOPIK, joined with ` / ` |
| 29 | Passport Status | `Passport Status` | clean |
| 30 | Passport No | `Passport No` | clean |
| 31 | Passport Issue | `Passport Issue Date` if the CSV has that column (it does since Sep 2026), else the `passport_issue.json` cache by passport number | `normalize_date` |
| 32 | Passport Expiry | `Passport Expiry` | `normalize_date` |
| 33–36 | Visa Rejection History, Sponsor, Sponsor Occupation, Bank Certificate | same | clean |

KLP, EAP and Bachelor's sheets have 32 columns; Master's has 36. "No value" markers (`n/a`, `none`, `null`, `-`, `—`, `not provided`, …) are written as **true blanks**, never "N/A". Known side finding (29 Sep 2026, not fixed, outside the Supabase work): `progress_builder.clean_value` compares ASCII letters only, so a cell written only in Bangla script is blanked on the sheet too; the Supabase copy keeps such a cell as a value (§13.6). Values are written with `valueInputOption="RAW"`, so dates and phone numbers stay text (no reformatting, no scientific notation).

### 3.4 Formatting
Times New Roman 14, no underline on the whole tab; bold header row; 1 frozen row; grid sized exactly to rows+1 by the column count (at least 2 rows); columns auto-resized (`autoResizeDimensions`).

### 3.5 How a sheet is built or updated (`build_target`)
1. `find_sheet`: the newest-modified spreadsheet with that exact name in the intake folder (created if missing).
2. **It exists:** find the tab titled `title[:100]` (fallback: **the first tab**), clear its values, and rewrite it. Every other tab is left as it is.
3. **It does not exist:** `drive.files().create(mimeType=spreadsheet, parents=[intake folder])` and use its first tab.
4. `updateSheetProperties` (title, rowCount, columnCount, frozenRowCount=1) → `values.update` A1:{last column}{n+1} → a formatting `batchUpdate`.

**Never delete or clear a main tab by hand.** With it gone, step 2 falls back to the first remaining tab, usually a manager's university tab (MIGRATION §8, decision 8).

### 3.6 The 15-minute sync of the sheets (`auto_sync.sync_sheets`)

**State file** `data\sheet_state.json`:
```json
{"sheets": {"KLP|MARCH 2027": {"Student ID:HNG-2026-<n>": {"name": "<student name>", "hash": "<sha1>", "rec": {"Student ID": "…", "Full Name": "…", "…": "…"}}}},
 "failures": {"sheets": 0, "docs": 0}}
```

**Row key** (`_row_key`), in order of preference:
1. `"Student ID:{ID}"`
2. `"Passport No:{P}"`, only for a real number: ≥6 characters with a digit. `PENDING`, which many students without a passport share, is no identity.
3. `"NAME:{normalised name}{normalised mobile}"`

Two rows with one key get `#2`, `#3`, … so they never overwrite each other. `hash = sha1(json.dumps(rec, sort_keys=True))` over the row exactly as it would be written.

**Per target, each run:**

| Situation | Action | Telegram line |
|---|---|---|
| No previous snapshot | Build the sheet, start tracking | `📄 {title}: sheet ready (N students) — change tracking started` |
| Nothing changed on the portal | `sheet_drift` (cells on the first tab that differ from what the portal says). If > 0: rebuild | `🛠 {title}: {n} cell(s) had been changed by hand on the sheet — restored from the portal (the main tab always mirrors the portal; type notes in your own tabs instead)` |
| Rows added, removed or edited | Rebuild | `📄 {title}: sheet updated — now N students`, then `   • k new: a; b; … +m more`, `   • k removed: …`, `   • k edited: <name> (Col1, Col2, Col3, Col4…)` (at most 8 names per list) |
| Intake tracked before, now empty | Rebuilt empty once, then forgotten | as "updated" |

**Telling an edit from "one left, one joined"** (`sheet_changes`). A student's key changes when a Student ID is given at payment verification, or a passport number is filled in or corrected. Unmatched old and new keys are paired in two passes, the surest match first and each row paired once:
- Pass 1, `_same_student`: 3 = the same Student ID, 2 = the same real passport number, 1 = the same name + mobile.
- Pass 2, `_likely_same`, for an ID given in the same sync as a name or mobile correction: the same last-10-digit mobile **and** a like name (ratio ≥ 0.7 over the words that tell people apart, a shared uncommon word of ≥3 letters, or one name's words contained in the other's: `"<SURNAME> MD"` → `"<SURNAME> MD <GIVEN>"`), or the same DOB and normalised name. **Two different DOBs are never one person**: siblings on one family mobile who share only a surname stay two students (c17d887). About 50 common Bangladeshi name words (`md`, `mst`, `mohammad`, `rahman`, `islam`, `hossain`, `akter`, `khatun`, `ahmed`, …) never count as a telling word.
- A paired row whose hash differs is reported as edited with the changed columns; one with no change is not reported.

**Example message** (plain text, no Markdown):
```
🔄 Portal sync — changes found

📄 BACHELOR'S DEGREE MARCH 2027: sheet updated — now 56 students
   • 1 new: <student name>
   • 1 edited: <student name> (Student ID)
📁 1 newly verified student(s) — documents saved:
   • <STUDENT NAME> (<passport no>) — BACHELOR'S DEGREE, 11 file(s), 2 compressed to under 2 MB
```

**Delivery** (`notify`, `src\sheets\auto_sync.py:335-363`; since the publish layer it **returns** whether Telegram accepted every piece for at least one recipient, so only a message that really went out is published as a `notification`): `sendMessage` via httpx to `https://api.telegram.org/bot<token>/sendMessage` (token: value in `secrets/bot.env` (TELEGRAM_BOT_TOKEN)), `disable_web_page_preview=True`, split between lines into pieces of ≤3900 Telegram characters (UTF-16 units) by `src.bot.replies.split_text`. Recipients are `settings.brief_recipient_ids()`: `TELEGRAM_BRIEF_CHAT_IDS`, or else everyone in `authorized_ids()`. On this PC that is only the admin chat. Nothing is sent when there are no lines.

**Failures.** Each step (sheets, docs) gets 3 attempts 20 s apart, each on a fresh portal session. A step that still fails increments `state["failures"][step]`; only the **3rd consecutive** failed run (about 45 min) produces `⚠️ {label} has failed {n} times in a row: {error}`, and recovery after that produces `✅ {label} is working again (it had failed {n} times in a row).` The state is saved after each step even on failure. The run is guarded by `data\auto_sync.lock` (the PID; ignored if older than 2 h or if the PID is dead).

**Order inside one run** (`run_once`, `auto_sync.py:412-480`): sheets → documents → **the sync summary is sent** → the document check (slow OCR runs after the summary, so it never delays sheet news; a verification error never fails the sync) → the document-check notice → **the Supabase handoff, last of all** (`sheet_hooks.after_sync(cloud)`, `:476-477`; §13.2).

**The quiet first sync.** After a cold start run `python -m src.sheets.auto_sync --no-notify` once. It records the starting state without messaging anyone; without it the first scheduled run announces every sheet as new (MIGRATION §8).

---

## 4. Verified documents (`verified_docs.run_local`)

| Step | Detail |
|---|---|
| Who | `students.php?source=direct&filter_docs=verified`, every page (`client.read_student_pages`). For each row: the uid (from the `download_docs.php?uid=N` link), `Full Name`, `Passport No`, `Program` (the text after each label in the row), and the **docs fingerprint**: the sorted `view_doc.php?f=<file>` names joined with `\|`. The portal puts the upload time in each file name (`<doc>_<uid>_<unix time>.<ext>`), so replacing a document changes the fingerprint. The page is parsed as `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (`verified_docs.py:44-47`, since `9ead47d`): the portal sits behind Cloudflare, which rewrites every e-mail address in the HTML as `[email protected]` with the real address hidden in a `data-cfemail="HEX"` attribute (class `__cf_email__`, or a link to `/cdn-cgi/l/email-protection#HEX`; the first byte of HEX is a key and every following byte XOR the key is one byte of the UTF-8 address, `parsers._cf_address`, `:24-39`); `parsers.decode_cf_emails` (`src\scraper\parsers.py:64`) turns each back into the plain address, as a browser shows it, before any text is read ([04](04_PORTAL_INTEGRATION.md)) |
| Where | `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\<PROGRAM NAME>\<FULL NAME> (<PASSPORT NO>)\` (Windows-illegal characters → `-`). A program that matches none → `OTHER PROGRAMS` |
| Fetch | `GET download_docs.php?uid=N&zip=1` (300 s; the content-type must contain `zip`), unzipped in memory. Only files not already in the folder are written, each through a `.part` file then renamed |
| Done marker | `.download_complete` holds the fingerprint. The same fingerprint → skip. A different one → re-download (only new files are added; nothing is deleted). A legacy marker (`ok`/empty) is upgraded in place and skipped |
| Shrink | Every file over 2 MB: the original is copied first to `C:\Hangeul\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\<same sub-path>`. A PDF is re-rendered page by page as JPEG on an A4-sized page down the ladder 1754 px/q70 → 1600/65 → 1400/60 → 1240/55 → 1100/50 → 950/45, until it is ≤1.95 MB (A4 sizing also fixes scans saved with giant page sizes). A JPEG/PNG is thumbnailed to 2400/2000/1600/1300 px × quality 80/70/60/50, and a PNG becomes `.jpg`. If it cannot get under 2 MB it is left as is and reported |
| Drive check | With `skip_drive_done=True` (the default, and what the sync uses), students whose name matches a Drive folder carrying `appProperties.hangeul_docs_complete = "1"` (from the old PC's Drive-mode uploads) are skipped. On this PC that is 4 students, so the sync never re-checks their uploads. The cold start used `--include-drive-done`, so their files are on disk |
| Result | `{"saved": [(program, name, n_new, shrink_lines)], "redownloaded": [...], "failed": [(name, error)], "students": <every verified student the list showed>}` (`run_local`, `verified_docs.py:330-350`) → `doc_lines` (see §3.6). A re-download that brought no new file is not reported. `"students"` (new) is the whole list whatever `limit` is; the sync keeps it for the Supabase copy (kind `student_documents`, §13.2) |

Status: 29 Sep, 148 student folders (KLP 105, Bachelor's 36, Master's 4, EAP 3); 30 Sep, **160** (KLP 106, Bachelor's 37, EAP 9, Master's 8), the same 160 the portal's verified list shows. A typical sync logs `Finished: 0 saved, 143 already on this PC, 4 already in Drive, 0 failed.` (29 Sep figures).

Drive mode (`python -m src.sheets.verified_docs` without `--local`) uploads to `ALL STUDENTS/VERIFIED STUDENT DOCUMENTS/<PROGRAM>/<NAME (PASSPORT)>/` and marks finished folders with the `appProperties` flag. It is only used by hand.

---

## 5. Missing-information report (09:05 daily, and `/missing`)

**Schedule.** APScheduler `CronTrigger(hour=9, minute=5, timezone=Asia/Dhaka)`, `id="missing_info_report"`, `misfire_grace_time=3600`, `coalesce`, `max_instances=1`. It runs `python -m src.sheets.missing_report` as a subprocess (output → `hangeul_sync.log`, killed after 3600 s).

**Input.** The **main tab of every progress sheet** (read back from Google, `read_sheets`, key `"KLP|MARCH 2027"`), plus the portal CSV (`portal_index`) for the fields a sheet has no column for.

**What counts as missing**
- `REQUIRED` (30 fields): every sheet column except IELTS/TOPIK (optional), Passport Issue (not on the export originally) and the 4 university columns.
- University fields: all 4 (Previous University, Subject, Degree, CGPA) for **Master's** students and for anyone whose `Study Status` says COMPLETED … GRADUATE; only Previous University + Subject for `CURRENTLY IN UNDERGRADUATE`; none otherwise. The Master's sheet has these columns. For KLP, EAP and Bachelor's they are read from the student's **own CSV record**, matched by `ID:<Student ID>`, else `NM:<normalised name><normalised phone>`; a key two records share is dropped. When that record cannot be found the student is listed as **"not checked"**, never as complete (9dcd9ad).
- Students with **no intake** on the portal (on no sheet) are listed separately and get the missing field "Intake".

**Telegram text** (plain, split under the limit), to `brief_recipient_ids()`:
```
🗓 Missing-information report — 29 Sep 2026
<X> of <Y> students have missing information.
University fields of KLP, EAP and Bachelor's students are read from the portal (those sheets have no university columns).

📋 KOREAN LANGUAGE PROGRAM (KLP) MARCH 2027 — <k> of <n> incomplete
   • <HNG id> <student name> — <m> missing: Email, Guardian WhatsApp, … +<r> more      (top 10, most missing first; 6 fields shown)
   … and <K> more (see the Excel file)
   ⚠️ University fields not checked for <n> student(s) (not found in the portal export): …

⚠️ <n> student(s) have NO INTAKE on the portal, so they are on no sheet:
   • <HNG id or (no ID)> <student name> — <program>                                       (up to 15)
```

**The Excel file** `C:\Hangeul\BOT\data\missing_reports\missing_information_YYYY-MM-DD.xlsx` (openpyxl): one sheet `Missing information`; header `Program | Intake | Student ID | Full Name | Mobile | Missing count | Missing fields` in bold, frozen at A2; column widths 34/15/15/32/16/14/120; **only incomplete students**, sorted by program, then most missing first. Sent with `sendDocument`, caption "Every incomplete student with the fields they are missing". It contains student personal data and goes only to the brief recipients.

**Failure.** If the sheets or the portal cannot be read, one plain message goes out: `❌ Couldn't build today's missing-information report: <reason>. It will run again tomorrow at 09:05 (or send /missing).`, and the process exits 1 (e164679). Just before that exit it hands the notice (when Telegram accepted it) and the failure reason to Supabase (`after_missing_failed`, `missing_report.py:347`; §13.3). `send()` (`:241-277`) now returns whether Telegram accepted every text piece for at least one recipient; that decides whether a `notification` record is made.

**`/missing`.** An inline keyboard of 4 buttons (`missing:KLP|EAP|BACHELOR|MASTER`) → `python -m src.sheets.missing_report --program KEY` (180 s) → `program_report`: every intake of that program with **every** incomplete student and their fields, `✅ Everyone complete`, the "not checked" line, and the no-intake list. A failure prints `❌ Couldn't read the progress sheets or the portal: <reason>. …`, which is shown as is. The `--program` path now reads the sheets and the portal index itself (`data = read_sheets()`, `index = portal_index()`, then `program_report(key, data, index)`, `missing_report.py:303-306`), so the same reads that built the reply can be published after it is printed (`:314`); a failed read publishes nothing.

Because it reads the **sheets** (not the CSV) for the required fields, the report reflects what staff see on the sheets; the sync keeps those equal to the portal.

---

## 6. Stage report (`/stage`)

Flow: `/stage` → program buttons `stage:KEY` → `python -m src.sheets.stage_report --program KEY` prints JSON `[{"intake":"MARCH 2027","count":46}, …, {"intake":"NONE","count":n}]` (or `{"error": reason}`) → intake buttons `stagei:KEY|INTAKE`, labelled `MARCH 2027 (46)` or `⚠️ No intake set (n)` → `--program KEY --intake INTAKE` → the text report.

| Piece | Source | Why |
|---|---|---|
| Who is in the program+intake | the CSV export, Direct only (the same students as the sheets) | one request |
| Each student's **stage** | the "Stage · Applied" column of **every** `students.php` page (`read_students`, its own session), matched by Student ID, else by normalised name (with the mobile to tell two students of one name apart) | the CSV's `Current Stage` was stale (both pending-payment applicants showed "Payment Verified") |
| **Status and %** | each student's `progress.php?uid=N`: `.pg-ring` "NN%", `.pg-now .pg-stage`, `.pg-now .pg-status`. The first page is read alone (the login), then 4 at a time; once the portal stops answering, the rest are not requested | the CSV's `Current Status`/`Progress %` disagreed with 64 and 89 of 329 progress pages |

Output:
```
📊 Stages — KOREAN LANGUAGE PROGRAM (KLP) MARCH 2027
(live from the portal, 29 Sep 2026 10:15) — <n> students

• Payment Verified: <n>
• Documents Under Review: <n>
• ⚠️ Stage not found on the student list: <n>

🔹 Payment Verified (<n>)
   <HNG id> <student name> — Verified — 22%
   <HNG id> <student name> — progress page: Documents Under Review · Submitted — 33%     (the progress page's own stage differs)
   <HNG id> <student name> — progress page not read

⚠️ <k> of the <n> progress pages could not be read (<most common reason>): those lines show no status or %.
Status and % from each student's own progress page (progress.php), read just now.
```
After the report is printed (the button's reply is this process's stdout), `stage_report.main` hands the report and what it was built from to Supabase: `stage_report(key, intake, reads=reads)` fills `reads` with `matched` (each CSV row's list record or None), `pages` (the progress pages by uid) and `by_stage` (`stage_report.py:205`), then `sheet_hooks.after_stage(...)` (`:257-258`; never raises, never prints; §13.4). A report that could not be read publishes nothing.

Stages are ordered by the portal's pipeline: Application Received → Payment Verified → Documents Under Review → Documents Verified → University Applied → Admission & Tuition → VIN Application → Embassy Submission → Visa Result → Admitted / Completed → Accepted; then unknown stages, then "not found". If the student list cannot be read: `❌ Couldn't read the portal: <reason>. Stages for <program> <intake>: not available right now. Please try again in a minute.`

---

## 7. Passport issue-date refresh (08:30 daily)

**Why it exists.** The CSV export originally had no passport issue date; the portal keeps it on the edit page as `<input name="passport_issue_date" value="…">`. About 300 edit-page GETs are too slow for the 15-minute sync, so the dates are cached once a day before the 09:05 report. Since Sep 2026 the CSV has a `Passport Issue Date` column, which the sheets use first; the cache remains the fallback and feeds the field check and its fingerprint.

| Item | Detail |
|---|---|
| Schedule | `CronTrigger(hour=8, minute=30, Asia/Dhaka)`, `id="passport_issue_refresh"`, grace 3600 s, running `python -m src.sheets.passport_issue --refresh` |
| Keys | each student's own `Passport No` from the `students.php` details row, no spaces, upper case; ignored unless ≥6 characters with a digit (`PENDING` had given 12 students another student's date) |
| Read | for each passport, `GET student_edit.php?id=<uid>` for each uid holding it; regex `name="passport_issue_date"[^>]*value="([^"]*)"` |
| Conflicts | one passport number on several records (one person registered twice) is kept only if the non-blank dates agree; otherwise it is left out, with a log line |
| Partial failure | an edit page that does not answer keeps its previous date; after 10 such pages (`MAX_UNREAD`), or on any refused login or unreadable list, the refresh raises and **the old file stays** (it is written only after a complete read) |
| Output | `C:\Hangeul\BOT\data\passport_issue.json` = `{"by_passport": {"<passport>": "<date>"}}`: 276 dates on 29 Sep, **282** after the 30 Sep 08:30 refresh (274 of 302 at the cold start; the rest are blank on the portal) |
| Supabase (new) | while publishing is on, `main` keeps every edit page it read in memory (`pages = {uid: (html, time read)}`, `passport_issue.py:85`, `:129`; only then, so the refresh itself is not slowed) and, after the file is written, calls `sheet_hooks.after_issue_refresh(data, pages, not args.limit)` (`:133-140`): the `passport_issue` records and one `student_profile` per edit page (§13.5). The first refresh with publishing on is 1 Oct 2026 08:30; the 282 dates of 30 Sep reached Supabase through the backfill |
| Consumers | `progress_builder.issue_date_for` (fallback), `auto_verify.field_fingerprint` (a changed date re-runs the field check), `field_check` (the value, and **the 26-hour staleness rule**: a Passport Issue DIFFERS from a cache over 26 h old, or a missing cache, becomes UNREADABLE: "refresh it before treating this as an error") |

---

## 8. Attendance (built, not wired)
`src\sheets\attendance.py` reads the tab `Today` of the sheet `<Sheet id: attendance, see attendance.py:21>` (kept up to date by the office PC) and formats who was in, who was late after 09:00 (`GRACE_MINUTES = 0`), and who had not checked in. It was meant for the 09:05 report, but the office start time and grace were never confirmed, so no job calls it.

---

## 9. What gets sent where (summary)

| Message | Sender | Recipients | Format |
|---|---|---|---|
| `🔄 Portal sync — changes found` | `auto_sync.notify` | `brief_recipient_ids()` | plain text, split |
| `🔍 Document check` | `auto_sync.notify(title=…)` | same | plain text |
| `⚠️ … has failed N times in a row` / `✅ … working again` | `auto_sync` | same | plain text |
| `🗓 Missing-information report` + `.xlsx` | `missing_report.send` | same | plain text + `sendDocument` |
| `/missing …`, `/stage …` replies | the bot (`_reply_long`, `parse_mode=None`) | the requesting authorised chat | plain text, split |
| 18:05 brief section "5) DOCUMENT CHECK (from the last automated check, not live)" | `brief.read_document_check` over `results.json` | admin | Markdown, e.g. `146 students: FAIL 61, REVIEW 67, INCOMPLETE 15, PASS 3` + last check time |
| Everything each job above read and sent, as records | `src.cloud.sheet_hooks.after_*` → the publisher process | Supabase project `dcbcbpwpmdtaanboetiz` (`hg_records` + `hg_chunks` through `hg_sync`, one `hg_runs` row per run) | rows + text + 384-number embeddings; §13 |

**The raw Bot API calls of the subprocess jobs.** `auto_sync` and `missing_report` run as separate Python processes (no `python-telegram-bot` application, no event loop), so they call the Bot API directly with a synchronous `httpx.Client`. They get no DNS override from `src\net_fix.py` (only `run.py` calls it) and no `parse_mode` (plain text, so no Markdown can be refused).

| Call | Code | Endpoint | Form fields (`data=`, form-encoded) | Timeout | On failure |
|---|---|---|---|---|---|
| Sync / document-check / outage summary | `auto_sync.notify(lines, title=SYNC_TITLE)` (`SYNC_TITLE = "🔄 Portal sync — changes found"`, `CHECK_TITLE = "🔍 Document check"`, `src\sheets\auto_sync.py:331-363`; returns True when every piece reached at least one recipient) | `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage` | `chat_id`, `text` (one chunk of `split_text(f"{title}\n\n" + "\n".join(lines))`), `disable_web_page_preview=True` | `httpx.Client(timeout=30)` | HTTP ≥ 400 → WARNING `Telegram refused the summary for <chat>: HTTP <code> <first 200 chars>`; an exception → WARNING `Telegram send to <chat> failed: <e>`, per chunk; never raises |
| Missing-info text | `missing_report.send(lines, xlsx)` (`src\sheets\missing_report.py:241-277`; returns True when every text piece reached at least one recipient) | same `sendMessage` | `chat_id`, `text` (chunks of `split_text("\n".join(lines))`), `disable_web_page_preview=True` | `httpx.Client(timeout=60)` | `Telegram refused the report for <chat>: HTTP …`; an exception skips the rest for that chat |
| Missing-info Excel | same, when `xlsx` is not `None` | `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendDocument` | `data={"chat_id", "caption": "Every incomplete student with the fields they are missing"}`, `files={"document": (xlsx.name, <open file>)}` (multipart) | same client (60 s) | `Telegram refused the Excel file for <chat>: HTTP <code>` |

Recipients are `settings.brief_recipient_ids()` (`TELEGRAM_BRIEF_CHAT_IDS`, or every authorised id when it is empty). With no token or no recipient both functions log `Telegram not configured — … not sent` and return. The token appears in the URL, which is why `src\__init__.py`'s log filter redacts `bot<digits>:<secret>` from httpx's request lines ([03a §1](03a_FILES_src_bot.md)).

---

## 10. The document/OCR check

### 10.1 When it runs and how much
- Inside every sync process, after the summary: `auto_verify.run(budget=6)`. Six students per 15-minute run, each run a fresh process, so GPU memory never builds up.
- **Queue** (`pending`): students with a local folder **and** a CSV record (by passport number) whose **document fingerprint** (sha1 of `name:size:mtime` of every non-dot file) or **field fingerprint** (the files, plus every CSV field `k=v`, plus the cached issue date) changed since the last check; oldest folder first. The head of branch's passport number is in `SKIP_PASSPORTS` (not an applicant).
- A document fingerprint change → the full document check (OCR). A field-only change (staff corrected the portal) → only the fast field check. Correcting the portal never re-reads the scans.
- Lock: `data\verification\auto_verify.lock` (4 h stale, PID-checked).
- **Bulk re-checks must run in batches.** One long `--budget 0` process grew GPU memory student by student (7 GB of VRAM + 6 GB spilled to system RAM) and slowed from about 90 s to about 570 s per student. A fresh process per 5 students holds about 93 s per student (MIGRATION §8, decision 17):
  ```powershell
  do { $out = .venv\Scripts\python.exe -m src.verify.auto_verify --budget 5 2>&1
       $out | Select-String "Documents checked|more waiting|could not"
  } while ($LASTEXITCODE -eq 0 -and ($out -match "more waiting"))
  ```
- The cold start's phase 5 (144 students) took 2 h 26 min this way. Keep games closed: with a game on the same 8 GB RTX 5060, OCR per A4 page went from 1.8 s to about 17 s, and an out-of-memory during OCR can cache truncated text as final.

### 10.2 Reading and classifying files
- **Classification by file name** (`classify`): the longest keyword wins. `FILE_PATTERNS`: passport `passport`; photo `passport size photo`, `picture`, `photo`; student_nid `student nid`, `student_nid`, `nid card`, `id card cv`, `id_card`; birth_cert `birth certificate`, `birth_cert`; father_nid / mother_nid `father nid`/`father_nid`, `mother nid`/`mother_nid`; death_cert; family_cert `family relationship`, `family certificate`, `family_cert`; academic `academic certificate`, `academic_cert`, `transcript`; bank `bank statement`, `bank_statement`, `solvency`, `sanchay`, `savings`; trade_license `trade license`, `trade_license`, `tin`, `employment certificate`; income_tax `income tax`, `tax certificate`, `tax challan`, `acknowledgement`/`acknowledgment`; affidavit; personal_statement `personal statement`, `study plan`; recommendation; eca `extra curricular`, `eca`; language_cert `ielts`, `topik`, `toefl`. The portal names files consistently (`passport_<uid>_<time>.pdf`, `family_cert_…`), so name matching is reliable. An unmatched file is `other` and is never checked.
- **Reading** (`read_document`, `read_pages`): a PDF text layer when it has one (>80 characters per page for the whole-file text, ≥40 per page for page text); otherwise PyMuPDF renders the page (150 dpi whole-file, 200 dpi per page) and EasyOCR (English, GPU) reads it. Pages under 300 characters are retried turned 90° each way and 180° (sideways board certificates). Images are OCR'd directly.
- **OCR text cache** `data\verification\text\<PASSPORT>.json`: whole-file text by `"{file}:{size}:{mtime}:{max_pages}"` and per-page text by `"PAGES:{file}:{size}:{mtime}:{max_pages}"` (with the sideways page list). A cold student takes about 50–90 s; a cached re-check about 6 s. 146 cache files on 29 Sep, 158 on 30 Sep. Every readable page of the current file version is also published as a `doc_page_text` record (§13.2).

### 10.3 Required documents

| Program | Required (absence = MISSING, student INCOMPLETE) | Optional (checked if present) |
|---|---|---|
| KLP, EAP, BACHELOR | 01 Passport, 02 Photo, 04 Birth Certificate, 05 Father NID, 05 Mother NID, 06 Family Relationship Certificate, 07 Academic Certificate & Transcript, 08 Bank Solvency & Statement, 09 Financial (Trade Licence / TIN / Employment) | 03 Student NID, 05 Death Certificate, 10 Affidavit, Personal Statement / Study Plan, Recommendation Letter, Extra Curricular (ECA), IELTS / TOPIK Certificate |
| MASTER | the same + 09.1 Income Tax | the same |

The program comes from the CSV `Program` (`pb.program_key_of`, defaulting to KLP).

### 10.4 Per-document rules (verdict per finding)

| Document | PASS when | FLAG (a human looks) | FAIL (a rule broken) | NOTE (never affects the verdict) |
|---|---|---|---|---|
| 01 Passport | ≥12 months left (expiry from the portal's `YYYY-MM-DD`, else the latest date on the scan dated this year or later); the portal passport number appears in the scan text | no expiry readable; number not found | expired; <12 months left | — (the seal-placement check is disabled) |
| 02 Photo (image checks only) | ratio within ±0.06 of 35/45; top-band + top-corner background average with every channel >190 | ratio off; min side <300 px; greyscale stddev <30; image cannot be opened | background not white; file not .jpg/.jpeg | female applicant: check both ears are visible |
| 04 Birth Certificate | online-registration wording (`bdris`, `birth registration`, `online`, `qr`); notarised (wording **or** a violet/red seal); a date (or at least the year) the same as on the **passport** | not confirmably online; little English; no passport to compare; a date unreadable on either | not notarised; no date matches any passport date | — |
| 03/05 NIDs (student, father, mother) | notarised; on a lawyer/advocate or approved-translation pad; the person's first name on both the NID and the passport; the same ID number on ≥2 pages at the **same length** (10, 13 or 17 digits) | pad not confirmed; name mismatch or no passport; two different numbers of one length (OCR, not forgery); no number read | not notarised | numbers read but not on two pages in one format |
| 06 Family Relationship | issued within 3 months (the date beside Date/Ref/Memo/Serial); Union Parishad/Pourashava/City Corporation issuer; notarised; the student's name in the first 1200 characters; ≥2 ID numbers | issue date unreadable; issuer unknown; name not at the top; few ID numbers | older than 3 months; not notarised | — |
| 07 Academic | an e-Apostille QR (`apostille.mygov.bd`, `mofa-servicedirect`, `apostille`) read by pyzbar/OpenCV; **page 1 is an apostille**; the pages after each apostille are one qualification (HSC/SSC/DIPLOMA/MASTER/BACHELOR by regex, HSC tested before SSC); notarised; the student's, father's and mother's names; the portal SSC/HSC GPA in the text | an apostille not followed by its certificate; **pages after an apostille not all one qualification** (was FAIL until f74e45d); no notarisation; a name or GPA not found | no scannable apostille QR (or its QR unreadable); **page 1 is not an apostille** (kept FAIL: decision 18); "provisional" certificate; apostille subject ≠ page level (dormant: `apostille.json` absent) | pages turned upright to be read; pages that name no qualification |
| 08 Bank | the highest taka amount ≥ the minimum (KLP/EAP 1,800,000; BACHELOR/MASTER 2,500,000); USD stated on a solvency certificate; a seal or signature; account ≥6 months old; the solvency (page 1) and statement (pages 2+) dates equal; the account holder (FATHER/MOTHER per the portal Sponsor, else the student) named | no amount; no USD; no seal at all; account <6 months; **solvency date ≠ statement generation date** (was FAIL until f74e45d); a single-page file; holder not found | below the minimum | one or both dates unreadable |
| 09 Financial (trade licence / TIN / employment) | sponsor is a parent; in the account holder's name; the kind recognised; the trade licence fiscal year = the current one (July–June, e.g. 2026-2027); business ≥2 years; trade licence notarised; the TIN and trade-licence names agree | sponsor not a parent; not in the holder's name; kind unknown; no fiscal year; business <2 years; TIN vs licence names differ | fiscal year not current; trade licence not notarised | — |
| 09.1 Income Tax (Master's) | net wealth ≥ 5,000,000 BDT; a tax-paid figure; notarised | any of those not found | — | — |
| **Every document except the photo** | colour scan (≥0.08% clearly coloured pixels), or a typed or computer-generated document; QR readable, or none on the page; English or translated | colour unjudgeable; a QR present but unreadable; birth certificate with no QR and no online wording; Bangla with translation wording (check the pad) | black-and-white scan (<0.02%); Bangla with no translation | faint colour (0.02–0.08%: a pale stamp?) |

The **document verdict** is the worst finding (FAIL > FLAG > PASS; NOTE ignored). Its detail is every finding as `VERDICT: text` joined with ` | `. Fuzzy wording (`has_any`) accepts OCR errors such as "advocale" and "nolary" (SequenceMatcher ≥0.8).

### 10.5 Cross-document checks (the reviewer's first rule)

| Row | Rule |
|---|---|
| `CROSS-CHECK name` (applicant, father, mother) | The name's meaningful tokens (titles MD/MST/… dropped) must appear (all but one) on each readable identity document (passport, student NID, birth certificate, the right parent's NID, family certificate, academic). Missing on ≥2 → FLAG ("check whether the spelling really differs"); on 1 → PASS (one document alone is usually OCR). Unreadable documents (fewer than 25 real words, or ≤60% of them with a vowel) are skipped and named |
| `CROSS-CHECK date of birth` | The portal DOB must be found on passport, student NID, birth certificate and family certificate; not found on ≥2 readable ones → FLAG |
| `CROSS-CHECK passport number` | The portal number (spaces removed) on any document → PASS, else FLAG |
| `CROSS-CHECK affidavit` | Only when a name mismatch was flagged: no affidavit → FLAG; an affidavit not in the **applicant's** name → **FAIL** (a parent's affidavit is not accepted) |

### 10.6 Student verdicts

| Student verdict | Meaning | Rule (`student_verdict`) |
|---|---|---|
| **INCOMPLETE** | a required document is not uploaded | any row MISSING (it outranks FAIL) |
| **FAIL** | at least one rule is clearly broken | any row FAIL |
| **REVIEW** | nothing broken, but at least one thing needs a human | any row FLAG |
| **PASS** | everything present and every rule satisfied | otherwise |

Checks are deliberately conservative: a rule fails only on clear evidence, and anything doubtful is a FLAG (`rules.py` docstring). **Every false positive so far was found by the manager looking at a document, not by the code** (HANDOFF §6.5), so treat the first report of any new rule as a list of questions.

### 10.7 Storage and reports

**`C:\Hangeul\BOT\data\verification\results.json`** (1.6 MB on 29 Sep, 1.8 MB on 30 Sep; saved atomically through `results.tmp` after every student):
```json
{
  "documents": {"<PASSPORT>": {"fingerprint": "<sha1>", "checked": "2026-09-27T15:19:01", "student": "<name>",
                                "program": "KLP", "verdict": "REVIEW",
                                "rows": [{"doc": "01 Passport", "file": "<file name>", "verdict": "PASS",
                                          "detail": "PASS: valid until … | PASS: passport number … found on the scan | PASS: colour scan (…)"}]}},
  "fields":    {"<PASSPORT>": {"fingerprint": "<sha1>", "checked": "…", "student": "<name>", "program": "KLP",
                                "rows": [{"field": "DOB", "portal": "<value>", "result": "MATCH", "detail": "found on 01 Passport"}]}},
  "corrections": [{"noticed": "…", "student": "…", "passport": "…", "program": "…", "field": "…", "was": "…", "now": "…",
                   "was_result": "DIFFERS", "now_result": "MATCH", "detail": "…"}]
}
```
Both reports are **rebuilt in full from this file** on every pass that checked someone (or when a report file is missing), so a pass that checks 2 students still yields a complete report. `python -m src.verify.auto_verify --rebuild` rewrites them without checking anyone. The old PC's `results.json` (the only Corrections history) was lost with that PC, so `corrections` is empty on this PC.

**`DOCUMENT CHECK.xlsx`**
- Sheet `Summary`: `Student | Passport | Program | Verdict | Missing | Fail | Flag | Pass | Checked`, sorted by program then student; the Verdict cell coloured PASS `C6EFCE`, FLAG/REVIEW `FFEB9C`, FAIL `FFC7CE`, MISSING/INCOMPLETE `F2F2F2`, NOTE `DDEBF7`.
- One sheet per program (KLP, EAP, BACHELOR, MASTER): `Student | Passport | Student verdict | Document | File | Verdict | Details`, one row per document or cross-check, with the Verdict and Student-verdict cells coloured. Widths 28/13/14/38/34/10/120. The header is bold and frozen at A2.

**`FIELD CHECK.xlsx`**
- `Summary`: `Student | Passport | Program | Checked | Match | Differs | Unreadable | No document | Blank | Last checked` (Checked = Match + Differs + Unreadable; the Differs cell is red when > 0).
- One sheet per program: `Student | Passport | Field | Portal value | Result | Detail` (Result coloured MATCH green, DIFFERS red, UNREADABLE yellow, NO DOCUMENT grey).
- `Corrections`, newest first: `Noticed | Student | Passport | Program | Field | Was on portal | Now on portal | Was | Now | Detail`. This is every portal field that changed after a check, and whether the change fixed it. It cannot tell a staff edit from an issue-cache refresh (HANDOFF §5.2: 85 of 246 entries on the old PC were the refresh).

Close both files in Excel before a run, or the write fails at the end.

**Field-check results** per field: MATCH (found in the right document; the MRZ `YYMMDD`; OCR letter/digit swaps; a 5- or 10-year passport validity proving issue from expiry; a trade licence proving "business"), DIFFERS (a readable document clearly shows another date or another plausible passport number `[A-Z]\d{8}` / `B[MWXY]\d{7}`), UNREADABLE, NO DOCUMENT, BLANK. The fields checked are Full Name, Surname, Given Name, DOB, Gender, District, Address, Father, Mother, SSC/HSC Year/GPA/Group/School/College, Previous University and CGPA (Master's), Passport No, Passport Issue, Passport Expiry, Guardian WhatsApp and Sponsor Occupation.

**Telegram summary** (title `🔍 Document check`):
```
🔍 Documents checked: 2
   • <student name> (BACHELOR) — FAIL (07 Academic Certificate & Transcript: page 1 is not an e-Apostille — …)
   • <student name> (KLP) — REVIEW, 1 field(s) differ from the portal
   3 more waiting — they run on the next passes.
   Reports: DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx in C:\Hangeul\BOT\data\verification
```
FAIL names the first failing rule; INCOMPLETE names the first missing document (160 characters max).

**Code faults stop the run.** A `NameError`, `AttributeError`, `ImportError` or `TypeError` inside the rules raises `RuntimeError("the rules failed on … This is a code fault, not a document problem — the run has stopped so the report is not silently wrong.")`. A swallowed `name 'holder' is not defined` once skipped every bank check while the report looked clean (HANDOFF §6.2). Any other exception skips only that student ("could not be read").

### 10.8 Numbers on this PC (29 and 30 Sep 2026)

- Cold start (27 Sep, phase 5): 144 students → FAIL 61 / REVIEW 65 / INCOMPLETE 15 / PASS 3; field check 2,801 MATCH, 1 DIFFERS.
- 29 Sep (`results.json`): 146 students → REVIEW 67, FAIL 61, INCOMPLETE 15, PASS 3 (KLP 105, BACHELOR 35, MASTER 3, EAP 3). Document rows: PASS 2,014, FLAG 370, FAIL 89, MISSING 15. Field rows: MATCH 2,842, UNREADABLE 364, BLANK 11, DIFFERS 1. Corrections: 0. The last document check was then 27 Sep 2026 15:19.
- **30 Sep 23:43 (`results.json`): 158 students → REVIEW 73, FAIL 63, INCOMPLETE 19, PASS 3** (KLP 106, BACHELOR 36, EAP 9, MASTER 7). Document rows: PASS 2,187, FLAG 418, FAIL 93, MISSING 19. Field rows: MATCH 3,052, UNREADABLE 424, BLANK 13, DIFFERS 1. Corrections: 0. The newest check: 30 Sep 2026 11:34 (the sync's own passes checked the 12 newly verified students). The same store went to Supabase in the backfill as 158 `doc_check`, 2,717 `doc_verdict`, 3,490 `field_check` and 3,469 `doc_page_text` records (§13).
- FAIL findings by rule (anonymised, 29 Sep): page 1 not an e-Apostille **47**; birth-certificate date matches no passport date 16; trade-licence fiscal year not current 4; apostille QR unreadable 4; family certificate older than 3 months 3; black-and-white scan 12 (across bank, IELTS, NIDs, birth certificate, affidavit); NID not notarised 5; birth certificate not notarised 1; bank below minimum 1; photo background not white 1.

---

## 11. Rules decided in the migration (27 Sep 2026) and their status

| # | Decision | Where in code | Status |
|---|---|---|---|
| 7 | The **two remaining known-false FAIL rules go to FLAG** before the cold start, because every student was about to get a fresh verdict that staff act on: (a) solvency certificate date ≠ statement generation date; (b) pages after an e-Apostille not all one qualification. They go back to FAIL only once proven against real documents (HANDOFF §8.1). Message text unchanged | `doc_verifier.py:737-742`, `page_checks.py:432-439`, commit **f74e45d** | Done |
| — | HANDOFF §5.1's other two false-FAIL rules: "ID number differs between pages" is already a FLAG (compared only at the same length: a 10-digit Smart NID and a 13/17-digit legacy number are one identity); "opening balance below minimum" (`opening_balance()`, `MIN_OPENING_BALANCE`) is **not called** by any check at HEAD | `check_nid`, `rules.py:34-36` | Dormant |
| 7 | The apostille **subject-mismatch** FAIL needs `apostille.json` (`{application id: level}`), which was lost with the old PC | `page_checks.py:442-445` | Dormant |
| 18 | "Page 1 is not an e-Apostille" stays **FAIL** even though it causes 47 of 61 FAILs (the files are ordered certificate → apostille). Apostille-first is the real guideline, and staff must re-assemble those files. **Do not propose downgrading it again** | `page_checks.py:401-407` | Kept by the owner |
| 9 | **Only the Telegram auto-claim hole was closed**: with no admin chat ID configured, `is_authorized()` used to bind the first sender as admin (a stranger got student data and `/sendmail` from the agency Gmail, and again after every restart). It now refuses everyone and logs the sender's chat ID; the "Unauthorized" reply shows that ID so the owner can copy it into `.env` | `telegram_bot.py:22-37`, commit **c5c1a7c** | Done |
| 9 | Declined by the owner, not to be re-proposed: `API_HOST` stays `0.0.0.0` (a REST API on the whole LAN, with no password); the passport watcher's old "mark every alert sent but send 3" (since fixed anyway in 9dcd9ad); the uncapped portal re-login loop in `verified_docs` (since fixed in 9dcd9ad: a refused login raises) | — | Left as is (two were later fixed by the command work) |
| 14 | A GPU guard (postpone OCR when VRAM is low) was offered for games on the same RTX 5060; no decision | — | Open risk |
| 16 | The Konyang copy in Drive (41 folders) stays in Drive; `KONYANG_ROOT` is absent, so the verifier skips it | `doc_verifier.DOCS_ROOTS` | As decided |
| 17 | Bulk OCR re-checks run in batches of 5 (a fresh process each) | MIGRATION §8 | As decided |

HANDOFF §5.2 items still open: the TIN taxpayer name is unreadable on some students (so TIN vs licence cannot run); the passport seal-placement check is disabled; `annotate()` is dead code; `attendance.py` is unwired; one student's portal record carries the head of branch's passport number, so `portal_students()` (keyed by passport) cannot check that student until staff fix the record.

---

## 12. Subtleties worth copying (or avoiding) in another bot

1. **Read the CSV once; key rows by a stable identity with fallbacks; treat placeholders as no identity.** Most false "new + removed" reports came from keys changing under a student.
2. **Mirror, don't merge.** The main tab is overwritten from the portal every time it differs; people keep their notes in other tabs. Report restored hand edits so people learn.
3. **Fingerprint what you download by the source's own file names** (they carry the upload time); fingerprint what you check by `name:size:mtime`, and separately by the source record, so a record edit triggers only the cheap check.
4. **Cache OCR by file identity forever**; OCR is the only expensive step.
5. **Code faults must stop a batch**; data faults skip one item. A clean-looking report from swallowed exceptions is the worst outcome.
6. **Count consecutive failures before alerting**, and announce recovery once.
7. **Cap each run's heavy work** (6 students) and run it in a fresh process.
8. **Copy to a second store last, from what the job already read, in a process the job does not wait for.** Keep the reads in a plain dict while the job runs (`cloud`, `reads`, `pages`), build nothing while the copy is off, mark a batch complete only for a whole read, and let a button report's stdout stay its reply (the hook never prints). A copy that re-read the portal would double the load and could disagree with what Telegram was told (§13).
9. Known traps here: `sheet_drift` and `read_sheets` read the *first* tab while `build_target` writes the *named* tab; `run_local(skip_drive_done=True)` inside the sync silently skips folders marked complete in Drive; `portal_students()` uses all sources and lets a duplicated passport number hide a student; `doc_verifier.TODAY` is fixed at import (fine only because every run is a new process).

---

## 13. What the sheet jobs publish to Supabase (since 30 Sep 2026 22:27)

The four subprocess jobs of this file publish what they read to the owner's Supabase project
(`dcbcbpwpmdtaanboetiz`) for Jeannie. The layer, its record shape, the `hg_sync` contract and every kind are in
[13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md); the settings, local files and switch in
[02 §2.1, §3.11](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md). This section is only what **these jobs** hand over.
Code: `src\cloud\sheet_hooks.py` (470 lines), called from the jobs; tests: `tests\test_cloud_jobs.py` (26 tests),
plus `test_cloud_all.py` and `test_cloud_fixes.py`.

### 13.1 The common rules

| Rule | How |
|---|---|
| Off means nothing | every job checks `sheet_hooks.on()` (= `handoff.enabled()`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `CLOUD_PUBLISH_ENABLED` all set) **before keeping anything**; while it is off no read is kept, nothing is built, no file written, no process started |
| Last step | the hook runs after Drive, Sheets, the `.xlsx` and Telegram, so the job's own work and messages are exactly what they are without Supabase |
| No re-reading | the records are built from what the job already read (`src.cloud.records`); nothing is fetched from the portal again, nothing re-parsed except the edit pages' forms (`HangeulAdminClient._profile_fields`) |
| One call | `hand_over(job, build)` (`sheet_hooks.py:65-80`): `build()` → `(batches, failed_reads)`, batches without rows dropped, then `handoff.submit(job, batches, failed)` writes `data\cloud\pending\<time>-<job>.json` and starts `python -m src.cloud.publish --from <file>` without waiting (the publisher embeds on the CPU and calls `hg_sync`) |
| Never raises, never prints | a hook failure is one log line `Supabase publish failed (<job>): the records could not be built (<ExceptionType>)`; a `/missing` or `/stage` button's reply is the process's stdout, which the hook never writes to, and the publisher never holds that pipe |
| Whole reads only delete | a batch is `complete=True` only for a whole read; the publisher then sends the full key list (`p_all_keys`) and Supabase deletes that scope's other records. A failed read sends **no** batch and adds a plain reason (the portal's own words, or only the exception type; never a URL or a value) to the run's failed reads, making its `hg_runs` row `partial`. A complete batch is never sent empty (an empty list from a changed page layout must not empty a scope) |
| Only what went out | a Telegram message becomes a `notification` record only when `notify()` / `send()` returned True (every piece accepted for at least one recipient) |
| `hg_runs.job` | `portal_sync`, `missing_report`, `stage_report`, `issue_refresh` (`JOB_*`, `sheet_hooks.py:41-44`) |

### 13.2 The 15-minute portal sync (`auto_sync.run_once` → `after_sync(cloud)`, job `portal_sync`)

While publishing is on, `run_once` keeps a dict `cloud` (created at `auto_sync.py:418-427`, filled as the run goes):
`run_at` (epoch of the start), `title` (`SYNC_TITLE`), `sent` (`[(title, lines, epoch)]` of each accepted
notice), `sheets_error` / `docs_error` (the exception of a failed step), `documents` + `documents_at` (the
verified list `run_local` returned, `sync_docs`, `:275-286`), `lines` (the summary as built), `store_ok`
(whether `results.json` could be read before the check, `store_readable`), `verify` / `verify_error`
(`auto_verify.run`'s result, `verify_docs`, `:315-327`) and, last, `export` = `progress_builder._ALL_STUDENTS_CACHE`
(the one CSV snapshot the run used). `sheet_hooks.sync_batches(cloud)` (`sheet_hooks.py:160-213`) turns it into:

| Kind | Key / scope | Complete | From | Notes |
|---|---|---|---|---|
| `student_export` | key = the sheet sync's own row key (`Student ID:<id>` / `Passport No:<p>` / `NAME:<name><mobile>`, `#2` for a repeat); scope `all` | only when `records.export_complete`: the header has `Student ID` and `Full Name` **and** the rows are ≥ 90 % (`EXPORT_SHARE`) of the students the last whole read of `students.php` counted (the hash state's `student`/`all` keys, `listed_students()`); else not complete, with the failed read `students.php?export=csv: N rows, fewer than 90% of the M students the list shows` | the CSV export already fetched for the sheets | every column kept; `Current Stage`, `Current Status`, `Progress %` marked `stale_columns` and left out of the text ([04 §3.3](04_PORTAL_INTEGRATION.md)). Why the 90 % rule: the export has no pager or total, and a stream cut short after its header still parses |
| `student_documents` | key uid; scope `all` | yes | the verified-documents list (`run_local`'s `"students"`) | uid, name, passport, program and the `\|`-joined file names (the fingerprint): file **names** only, never the files. No list → failed read `students.php?source=direct&filter_docs=verified: …` |
| `report` `sync_summary\|<run_at ISO>` + `report_section` per summary block | report scope `sync_summary` (never complete: other runs' summaries stay); sections scope `sync_summary\|<run_at>` (complete) | — | the summary lines as built, sent or not | sections = each line at the margin with its indented `   • …` lines (`line_sections`) |
| `doc_verdict` (key `passport\|document`, `#2` for a repeat), `field_check` (key `passport\|field`), `doc_page_text` (key `passport\|file\|p<page>`, or `passport\|file\|all` for a file read only whole) | scope = the passport, each its own complete scope | yes | the passports this pass just checked, **plus up to 6 (`CATCH_UP_PASSPORTS`) whose records Supabase never accepted** (checked before publishing began, or a failed publish) | `doc_page_text` = the OCR text cache `data\verification\text\<P>.json`, the version whose size and mtime match the file now in the student's folder, unreadable pages left out. Student uid / HNG id come from `data\cloud\student_index.json` |
| `doc_check` (added beyond the owner's spec: the student-level verdict no document row carries) | key passport; scope `all` | yes | the whole `results.json` (the store is the whole truth of the check) | verdict, program, when checked, the rows' verdict counts and the field check's result counts |
| `field_correction` | key sha1 of the entry; scope `all` | **no** (append-only, never deleted) | `results.json` `corrections[]` | empty on this PC (0) |
| `report` `document_check\|<day of the newest check>` / `field_check\|<day>` + a `report_section` per student (+ a Corrections section when there are any) | report scopes `document_check` / `field_check`; sections `<report>\|<day>` | sections yes | the same store `DOCUMENT CHECK.xlsx` / `FIELD CHECK.xlsx` are built from | the `.xlsx` files themselves are never uploaded |
| `notification` | key sha1(text \| sent time); scope the ISO day | no | each notice Telegram accepted: `🔄 Portal sync — changes found` and `🔍 Document check` (title + lines, as sent) | source `auto_sync` |

When `results.json` was unreadable before the check (`store_ok` False, so `auto_verify` started from an empty
store), only the per-passport kinds of the passports just checked are sent, the store-wide kinds
(`doc_check`, `field_correction`, the two reports) are not, and the failed read says `results.json: unreadable
before the document check (it started from an empty store)`: an empty store must never delete 158 students'
records. A document check that could not run adds `document check: could not run (<Type>)`.

What it looks like in `hangeul_sync.log` on 30 Sep: `Supabase publish (portal_sync): ok, 0 upserted, 0 deleted,
976 unchanged, …, 0.4 s in all, peak memory 0.06 GB.` (22:43, nothing changed: nothing embedded), and at 23:13
`ok, 2 upserted, 0 deleted, 1036 unchanged, 2 row(s) sent, …; 2 record(s) embedded in 0.1 s; 7.5 s in all, peak
memory 0.86 GB.` A run that has only unchanged rows costs well under a second because the hash state
(`data\cloud_state.json`) already has them: only changed records are embedded and sent.

### 13.3 The missing-information report (job `missing_report`)

| Run | Hook (`missing_report.py`) | Batches (`sheet_hooks.py`) |
|---|---|---|
| 09:05 daily, built | `_supabase(lambda h: h.after_missing_daily(lines, rows, sent_at))` (`:354`), after the text and the Excel file went out; `sent_at` is the send time only when `send()` returned True | `report` key `missing_report\|<ISO day>`, scope `missing_report` (not complete), text = the report as sent, `data.facts.rows` = every row `build_report` made (every student on the sheets, `missing_count` 0 for the complete ones, plus the no-intake students, intake `(no intake)`) as `{program, intake, student_id, full_name, mobile, missing_count, missing_fields}`; a `report_section` per **incomplete** student (scope `missing_report\|<day>`, complete); a `notification` when sent (`missing_daily`, `:341-352`) |
| 09:05 daily, could not be built | `after_missing_failed(notice, sent_at, e)` (`:347`), then exit 1 | the notice as a `notification` (when Telegram accepted it) and the failed read `progress sheets or the portal: <reason>` (`missing_failed`, `:355-358`) |
| `/missing` button (`--program KEY`) | `after_missing_program(key, text, data, index)` (`:314`), after the list was printed; a failed read returns before it | `report` key `missing_program:<KEY>\|<day>`, scope `missing_program:<KEY>`, `data.facts = {program, rows}` (every student on that program's sheets with the count and names of the fields missing, 0 for the complete ones, as `build_report` counts them, plus that program's no-intake students), a section per text block (`records.split_sections`: each intake) (`missing_program`, `:361-376`) |

The backfill also published the newest `data\missing_reports\missing_information_*.xlsx` (30 Sep: 1 report,
118 incomplete-student sections).

### 13.4 The stage report (`/stage` → `--program KEY --intake INTAKE`, job `stage_report`)

`stage_batches(program_key, intake, text, reads)` (`sheet_hooks.py:381-413`):

* `student_progress` (key uid, scope `all`, **never complete**: one program and intake is not every student)
  for each progress page read (`{pct, stage, status}`; a page that failed is left out), with the list record's
  HNG id and name;
* `report` key `stage_report:<KEY>:<INTAKE>|<day>` (scope `stage_report:<KEY>:<INTAKE>`), text = the report as
  printed, `data.facts = {program, intake, counts: {stage: n}, students: [{student_id, full_name, stage, uid,
  progress_pct, progress_stage, progress_status | progress_error}]}`, plus a section per text block.

The full, complete `student_progress` set (all 340 on 30 Sep) came from the backfill, which reads every
student's `progress.php` 4 at a time as `/stage` does.

### 13.5 The 08:30 passport issue-date refresh (job `issue_refresh`)

`issue_batches(by_passport, pages, complete)` (`sheet_hooks.py:418-436`):

* `passport_issue` (key = the passport number, scope `all`): one record per passport with a date, **complete
  only when the refresh read every student** (no `--limit`); 282 records in the backfill;
* `student_profile` (key = scope = uid, each its own complete scope): `student_edit.php`'s form as
  `HangeulAdminClient._profile_fields(html)` reads it, for every edit page the refresh read. The portal's filler
  words are blanked (below).

### 13.6 What every record of these jobs shares

* **Filler words are no value.** A cell holding only `N/A`, `None`, `null`, `nil`, `--`, `—`, `TBD`, `not
  provided`, `not applicable`, `not available`, marks only, `PENDING` outside a status field, or Cloudflare's `[email protected]`
  stand-in (`records.FILLER_WORDS`, `is_filler`, `src\cloud\records.py:206-240`) is written as `""` in `data`,
  left out of the text, and named in `data["blank_on_portal"]` (sorted; `details.<label>` for a `students.php`
  details field), so Jeannie can say "not given on the portal" without inventing or losing anything. A status
  field's `Pending` (Payment Status, Passport Status, VIN Status, Visa Result, a stage…) is data. Unlike
  `progress_builder.clean_value`, a Bangla-only cell is a value here (`clean_value` compares ASCII letters only
  and blanks such cells in the Google Sheets: a known, unfixed side finding).
* **E-mail addresses are real.** Every portal page is decoded with `parsers.decode_cf_emails` before it is read
  (§4), so Supabase holds the addresses, never `[email protected]`; the independent postcheck of 30 Sep found 0
  stand-ins and 0 fillers in 13,540 records.
* **Student columns.** `student_uid`, `student_hng_id`, `student_name`, `passport_no` and `day` are derived
  from the hashed fields only (the passport-keyed kinds get uid and HNG id from `student_index.json`), so a
  record's hash does not flip when a list could not be read.

### 13.7 Not published by these jobs

The Google Sheets themselves (their data is the CSV export: `student_export`), the `.xlsx` files (their
content is the reports above), document files and scans (only file names and OCR text), `sheet_state.json`,
and the attendance sheet. The passport watcher, the 18:05 brief, the command answers and the hourly full
picture publish through their own hooks (`src\cloud\bot_jobs.py`, `command_hooks.py`, `full_picture.py`):
[13](13_SUPABASE_PUBLISHING.md), [05](05_TELEGRAM_COMMANDS_AND_JOBS.md).
