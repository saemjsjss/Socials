# 03c — File map: `src\sheets\`, `src\verify\`, `tools\` and every root-level file

**What's in this file:** a file-by-file map of the Google-Sheets/report modules, the document/OCR verifier, the one tool script, and every tracked file in the root of `C:\Hangeul\BOT` (scripts, launchers, staging copies, config, docs). For each: purpose, signatures, constants/regexes, what it reads and writes, who calls it, how it fails, and its git history. Since 30 Sep 2026 it also covers the **sheet jobs' Supabase hand-over**: the last step each of the four subprocess jobs makes (`src\cloud\sheet_hooks.py`, §1.8), the new `requirements.txt` pins and the new `.env` keys (§4.2, §4.4).
**How the pieces work together** (the sheet design, the reports, the verdict semantics) is in [07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md). Tests are in [10_TESTS_AND_VERIFICATION.md](10_TESTS_AND_VERIFICATION.md), and the Telegram commands and schedule are in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md). The other file maps are [03a (`src\bot\`)](03a_FILES_src_bot.md), [03b (scraper, LLM, API, config)](03b_FILES_src_scraper_llm_api_config.md) and [03d (`src\cloud\`, the Supabase publish layer)](03d_FILES_src_cloud.md); what is published and why is in [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md); launchers and supervision in operation are in [02 §5](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md); the system view in [01_ARCHITECTURE.md](01_ARCHITECTURE.md); the pack index in [00_INDEX.md](00_INDEX.md).

**Pack written:** 29 Sep 2026 from `c17d887`. **Refreshed:** 30 Sep 2026 (Asia/Dhaka) to repo `C:\Hangeul\BOT`, branch `main`, HEAD `8317741` (48 commits, 113 tracked files, working tree clean). Line numbers are `path:line` at `8317741`. Secrets are never shown: a secret is written as "value in `secrets/bot.env` (KEY_NAME)". The pack's `secrets\` folder holds exact copies of `.env` (as `bot.env`), `credentials.json` and `token.json`. Student data is written as `<student name>`, `<passport no>` and so on.

---

## 0. Scope and inventory

| Path | Lines | Last commit | Role (one line) |
|---|---|---|---|
| `src\sheets\__init__.py` | 0 | 366dec0 | Empty package marker |
| `src\sheets\progress_builder.py` | 595 | 9dcd9ad | Portal CSV → one Google Sheet per program+intake; Google auth; shared helpers |
| `src\sheets\auto_sync.py` | 493 | 41055de | The 15-minute job: sheets → document download → Telegram summary → document check → Supabase hand-over |
| `src\sheets\verified_docs.py` | 437 | 9ead47d | Downloads document-verified students' ZIPs (to this PC or Drive); shrinks files over 2 MB |
| `src\sheets\missing_report.py` | 358 | 41055de | 09:05 missing-information report (Telegram + Excel); `/missing` program lists; Supabase hand-over |
| `src\sheets\stage_report.py` | 270 | 41055de | `/stage` report: stage from the student list, status/% from each progress page; Supabase hand-over |
| `src\sheets\passport_issue.py` | 145 | 41055de | 08:30 cache of passport issue dates read from `student_edit.php`; Supabase hand-over |
| `src\cloud\sheet_hooks.py` | 470 | 3caa393 | What the four sheet jobs hand to the Supabase publisher as their last step (summarised in §1.8; full map in [03d](03d_FILES_src_cloud.md)) |
| `src\sheets\attendance.py` | 111 | 4154aa5 | Office attendance from a Google Sheet. **Not wired into any job** |
| `src\verify\__init__.py` | 0 | 366dec0 | Empty package marker |
| `src\verify\rules.py` | 134 | 366dec0 | The document guidelines as data: thresholds, file patterns, required documents, word lists |
| `src\verify\doc_verifier.py` | 1241 | d659983 | Reads each file (text layer / EasyOCR), runs per-document rules and cross-document checks |
| `src\verify\page_checks.py` | 452 | 4154aa5* | Image-level checks: colour, QR/barcode, Bangla, seals, e-Apostille page order |
| `src\verify\field_check.py` | 302 | 4154aa5 | Portal field values vs what the documents say (MATCH / DIFFERS / UNREADABLE / NO DOCUMENT / BLANK) |
| `src\verify\auto_verify.py` | 609 | 9dcd9ad | Orchestrates both checks, OCR text cache, locking, `results.json`, both Excel reports |
| `tools\export_windows_ca.ps1` | 41 | 366dec0 | Exports Windows root certificates to `data\windows-ca.pem` |
| Root (33 tracked files): 9 Python scripts, 3 byte-identical staging copies, 12 Windows launchers/installers, 4 config/packaging files, 4 docs (+ `.agents\rules\hangeul_operational_guardrails.md`), 1 image | see §4 | | |

(*) also f74e45d: mixed levels → FLAG (and the baseline 366dec0).

The 24 test files in `tests\` (plus `tests\conftest.py`) are listed with their subjects and counts in [§7](#7-the-tests-folder-index) below and described in full in [10_TESTS_AND_VERIFICATION.md](10_TESTS_AND_VERIFICATION.md). The task list also named a root `test_crosscheck.py`. It **no longer exists**: 40da0e6 removed it (it printed a hard-coded registry as if it were live cross-check results). The tracked file is `tests\test_crosscheck.py`.

**What changed in this scope between `c17d887` and `8317741`** (`git diff --stat c17d887..8317741`): the four sheet jobs gained their Supabase hand-over (41055de, from branch `cloud/jobs`); `verified_docs._parse_rows` decodes Cloudflare's hidden e-mails (9ead47d); `requirements.txt`, `.env.example`, `config.py` / `src\config.py` gained the Supabase and embedding keys (36ae72e); the root `telegram_bot.py` staging copy follows `src\bot\telegram_bot.py` (performance commands and command publish hooks). `src\verify\`, `tools\`, every root script, launcher and document are **unchanged**.

### How everything in this scope is started

```
pythonw run.py  (the bot process: Telegram polling + APScheduler + uvicorn :8000)
 ├─ every 15 min  _run_module("src.sheets.auto_sync")            → subprocess, log → hangeul_sync.log, 3600 s cap
 │                   └─ progress_builder → verified_docs.run_local → notify() → auto_verify.run(budget=6)
 │                      → sheet_hooks.after_sync(cloud)             (last step; publishing on only)
 ├─ 08:30         _run_module("src.sheets.passport_issue --refresh")  → … → sheet_hooks.after_issue_refresh
 ├─ 09:05         _run_module("src.sheets.missing_report")            → … → sheet_hooks.after_missing_daily | after_missing_failed
 ├─ hourly        _run_module("src.cloud.full_picture")               (Supabase only, see 03d / 13; skipped while publishing is off)
 ├─ /missing btn  _run_report_module("src.sheets.missing_report", "--program", KEY)     → stdout captured, 180 s cap
 │                                                                     → … → sheet_hooks.after_missing_program
 └─ /stage btns   _run_report_module("src.sheets.stage_report", "--program", KEY[, "--intake", I])
                                                                       → (with --intake) sheet_hooks.after_stage

 each sheet_hooks.after_* ─► handoff.submit(job, batches, failed_reads)
      writes data\cloud\pending\<YYYYmmdd-HHMMSS-ffffff>-<job>.json (.part + os.replace)
      and starts, WITHOUT waiting:  python.exe -m src.cloud.publish --from <file> --timeout 3600
      (stdin closed, stdout+stderr appended to hangeul_sync.log, CUDA_VISIBLE_DEVICES=-1, HF_HUB_OFFLINE=1, no window)
```

`_run_module` is at `src\bot\scheduler.py:392` and `_run_report_module` at `src\bot\telegram_bot.py:2215`. Both swap `pythonw.exe` for `python.exe`, set `PYTHONIOENCODING=utf-8`, pass `creationflags=0x08000000` (CREATE_NO_WINDOW) and use `cwd` = the bot folder. **Why a subprocess per job:** a crash, hang or GPU-memory leak inside a heavy job cannot take the bot down, and every run starts with fresh GPU memory. See HANDOFF §2, and MIGRATION §8 on OCR slowing down in long processes. **Why the publisher is yet another process:** the job must never wait for Supabase or load the embedding model (auto_sync still holds torch on the GPU after the document check; a button report's reply *is* its stdout, which the bot reads until the pipe closes), so the job only writes a small file and spawns `src.cloud.publish`, which embeds on the CPU and uploads on its own time (§1.8).

---

## 1. `src\sheets\`

### 1.1 `src\sheets\progress_builder.py` (595 lines)

**Purpose.** Builds and updates one Google Sheet per **program + intake** in Drive from the portal's CSV export. It is also the shared helper library for every other sheets and verify module: portal CSV fetch, value normalisers, program matching, Google credentials.

**Constants**

| Name | Value / meaning |
|---|---|
| `BOT_ROOT` | `Path(__file__).resolve().parent.parent.parent` → `C:\Hangeul\BOT` |
| `CREDENTIALS_PATH` / `TOKEN_PATH` | `BOT_ROOT\credentials.json` (OAuth Desktop client) / `BOT_ROOT\token.json` (user token). Copies: `secrets\credentials.json`, `secrets\token.json` |
| `SCOPES` | `["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]` |
| `PARENT_FOLDER_ID` | `"<Drive folder id: ALL STUDENTS, see progress_builder.py:56>"`, the Drive folder "ALL STUDENTS" (owned by the agency's Google account). Used by `verified_docs` Drive mode only |
| `COLUMNS` | 36 `(sheet header, CSV column)` pairs, listed in [07 §3.3](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md). `None` = computed (`IELTS/TOPIK`); `"_ISSUE_DATE"` = the passport issue date (`issue_date_for`) |
| `DATE_COLUMNS` | `{"DOB", "Passport Expiry"}` → `normalize_date` |
| `UNIVERSITY_COLUMNS` | `["Previous University", "Subject", "Degree", "CGPA"]` |
| `PHONE_COLUMNS` | `{"Mobile", "Guardian WhatsApp"}` → `normalize_phone` |
| `PROGRAMS` | `{"KLP", "EAP", "BACHELOR", "MASTER"}` → `{"name", "folder_id", "match_tokens", "drop_columns"?}`, listed in [07 §3.1](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md) |
| `_BLANKS` | `{"", "na", "n/a", "none", "null", "-", "--", "—", "n.a", "n.a.", "not provided", "not applicable"}`: "no value" markers become a true blank |
| `INCLUDE_SOURCES` | `{"direct"}`. Only the CSV's `Source` = Direct goes on the sheets; B2B partner students are left out |
| `_ALL_STUDENTS_CACHE`, `_ISSUE_CACHE` | Per-process caches: one CSV request per run, one issue-date cache load per run |

**Functions** (source order)

| Signature | Contract |
|---|---|
| `_norm_key(s: str) -> str` | Lower-case, keep `[a-z0-9]` only. The comparison key used everywhere |
| `clean_value(v: Any) -> str` | Trim. Any `_BLANKS` marker (compared by `_norm_key`) → `""`. Never returns "N/A" |
| `normalize_date(v: Any) -> str` | Replaces `.` and `/` with `-`. `^(\d{4})-(\d{1,2})-(\d{1,2})$` (Y-M-D) or `^(\d{1,2})-(\d{1,2})-(\d{4})$` (**D-M-Y**, day first) → `YYYY-MM-DD`. Returns the cleaned original if it cannot recognise the value or the month/day is out of range |
| `normalize_phone(v: Any) -> str` | Keeps digits. 11 digits starting `01` → `"88"+d`; 10 starting `1` → `"880"+d`; 14 starting `8800` → `"880"+d[4:]`; anything else stays as its digits |
| `ielts_topik(student) -> str` | Joins the CSV's `IELTS/TOEFL` (a number becomes `"IELTS 6.5"`; `NO`/`NONE` are dropped) and `Korean Level` (only when it contains `TOPIK`) with `" / "` |
| `program_matches(prog_value: str, match_tokens: List[str]) -> bool` | Any `_norm_key(token)` is a substring of `_norm_key(prog_value)` |
| `sheet_title(cfg) -> str` | `f"{cfg['name']} {cfg['intake']}"`, e.g. `"MASTER'S DEGREE MARCH 2027"`. Also the main tab's title (cut to 100 characters) |
| `_run_async(coro)` | Runs `coro` on a fresh event loop and closes the loop |
| `async _fetch_all_students_async() -> List[Dict[str,str]]` | `GET {base}/students.php?export=csv` (60 s). If the response URL contains `login.php`, logs in again and repeats once. Decodes `utf-8-sig`. Raises `RuntimeError("portal did not return the students CSV export")` unless the content-type contains `text/csv` or the first 2000 characters contain `Full Name`. Always closes `admin_client` |
| `fetch_all_students() -> List[Dict[str,str]]` | The cached CSV rows (all students, all sources) |
| `normalize_intake(v) -> str` | `" ".join(clean_value(v).upper().split())`: `"March  2027"` → `"MARCH 2027"` |
| `program_key_of(student) -> Optional[str]` | The first `PROGRAMS` key whose `match_tokens` match the `Program` field |
| `direct_students() -> List[Dict]` | CSV rows with `_norm_key(Source) == "direct"` |
| `target(program_key: str, intake: str) -> Dict` | `{**PROGRAMS[key], "key": key, "intake": normalize_intake(intake)}` |
| `all_targets() -> List[Dict]` | Every (program, intake) with at least one Direct student, in `PROGRAMS` order, then by intake string |
| `students_without_intake() -> List[Dict]` | Direct students with a program but a blank `Intake` (they are on no sheet) |
| `fetch_roster(cfg) -> List[Dict]` | Direct students of that program and intake, in portal CSV order |
| `columns_for(cfg) -> List[tuple]` | `COLUMNS` minus the program's `drop_columns` |
| `issue_date_for(student) -> str` | If the CSV row has a `"Passport Issue Date"` key (it does since Sep 2026), returns that value (it may be blank). Otherwise the `passport_issue` cache value under `passport_key(Passport No)` |
| `build_row(student, columns=None) -> List[str]` | One sheet row: `IELTS/TOPIK` via `ielts_topik`; `_ISSUE_DATE` via `normalize_date(issue_date_for())`; date/phone columns normalised; `Gender` upper-cased; everything else `clean_value` |
| `_load_credentials(interactive: bool = False)` | Loads `token.json` with `SCOPES`. Returns it if valid; if expired with a refresh token, refreshes it and **writes `token.json` back**. If not interactive, raises `RuntimeError("Google login required. Run:  python -m src.sheets.progress_builder --auth")`. If interactive, runs `InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0)` and accepts `credentials.json.json` (Windows hides extensions) |
| `_services(interactive=False) -> (drive, sheets)` | `googleapiclient.discovery.build("drive","v3")` and `build("sheets","v4")` with `cache_discovery=False` |
| `_col_letter(n: int) -> str` | 1-based column number → A1 letters |
| `_intake_folder(drive, cfg) -> str` | Finds or creates the folder named after the intake (e.g. `MARCH 2027`) inside `cfg["folder_id"]` (`supportsAllDrives`, `trashed = false`) |
| `find_sheet(drive, cfg) -> Optional[str]` | The newest-modified spreadsheet named `sheet_title(cfg)` in the intake folder |
| `sheet_drift(cfg) -> int` | Cells on the **first** tab that differ from what the portal says it should hold (header + rows, padded to width). `-1` means no sheet exists |
| `build_program(program_key, dry_run=False) -> List[str]` | `build_target` for each of that program's targets. Returns the URLs |
| `build_target(cfg, dry_run=False) -> str` | See [07 §3.5](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md). An existing sheet: clears and rewrites only the tab titled `title[:100]` (if none has that title, **the first tab**). Otherwise creates the spreadsheet in the intake folder. Then resizes the tab (rows = n+1, columns = width, 1 frozen row), writes with `valueInputOption="RAW"`, applies Times New Roman 14 with no underline, a bold header, and auto-resized columns. Returns `https://docs.google.com/spreadsheets/d/{id}/edit` (or `"(dry-run)"`) |
| `dump_profile(student_id: str) -> None` | Prints one student's raw CSV fields (first 60 characters of each) |
| `main()` | CLI: `--auth`, `--program KLP\|EAP\|BACHELOR\|MASTER`, `--all` (per sheet `title: url` or `title: FAILED — e`, then lists students with no intake), `--dump-profile ID`, `--dry-run` |

- **Reads:** the portal `students.php?export=csv` (GET; login POST if needed), the `passport_issue` cache, `token.json`, `credentials.json`. **Writes:** Google Drive (folders, spreadsheets) and Sheets (values, formatting); `token.json` on refresh or login.
- **Imports:** `src.scraper.client.admin_client` (lazily), `src.sheets.passport_issue` (lazily), the Google libraries (lazily).
- **Callers:** `auto_sync`, `missing_report`, `stage_report`, `passport_issue`, `verified_docs`, `attendance`, `verify.doc_verifier` (`fetch_all_students`, `program_key_of`), `verify.field_check` (`target`, `columns_for`, `build_row`, `normalize_date`), `bootstrap.py` phase 1, `build_sheets.bat`, `gauth.bat`, and the root copy `progress_builder.py`. Since 30 Sep also `src\cloud`: `records.student_exports` (`normalize_phone`, for the export's row key), `sheet_hooks.missing_program` (`program_key_of`), and `auto_sync.run_once`, which hands the module cache `_ALL_STUDENTS_CACHE` (the CSV rows this run read) to the hand-over, so the export is never read twice.
- **Errors:** raises `RuntimeError` (no CSV, no Google login, no `credentials.json`) and Google `HttpError`. `--all` catches per sheet and prints `FAILED`.
- **History:** 366dec0 baseline. 4154aa5: `BOT_ROOT` became location-independent (it was `E:\BOT`). 9dcd9ad: `issue_date_for` takes the CSV's own `Passport Issue Date` column first (the old cache keyed on the placeholder `PENDING` had given 12 students another student's date). Unchanged since (the staging copy's blob is still `8bc8e0d`).
- **Gotchas:** (1) `sheet_drift` and `missing_report.read_sheets` read `sheets[0]` (the first tab), while `build_target` writes the tab named after the sheet. If a manager moves a university tab to first place, drift compares the wrong tab and forces a rebuild every 15 minutes. (2) If the main tab is deleted, `build_target` overwrites the first remaining tab, usually a university tab (MIGRATION §8: never delete or clear main tabs). (3) **`clean_value` blanks a Bangla-only cell** (found by the dry-run fix 752cd53, not fixed): `_norm_key` keeps only `[a-z0-9]`, so a text in Bangla script normalises to `""`, which is in `_BLANKS`, and the sheet shows an empty cell. The Supabase copy does **not** use `clean_value` for this reason (`records.is_filler` keeps any non-ASCII text); fixing it here means editing both `src\sheets\progress_builder.py` and its root staging copy.

### 1.2 `src\sheets\auto_sync.py` (493 lines)

**Purpose.** The 15-minute job, run as `python -m src.sheets.auto_sync`. In order: (1) rebuild every program+intake sheet whose data changed and restore hand-edited main tabs; (2) download newly verified students' documents; (3) send one Telegram summary if anything changed; (4) run the document and field check on up to 6 students and send its own summary; (5) **only while Supabase publishing is on**, hand everything it read and sent to the publisher (`sheet_hooks.after_sync`, §1.8). Step 5 never changes steps 1-4: with publishing off the `cloud` dict is `None`, nothing is kept and the run behaves exactly as at `c17d887`.

**Constants.** `DATA_DIR = BOT_ROOT\data`; `STATE_PATH = data\sheet_state.json`; `LOCK_PATH = data\auto_sync.lock`; `DOCS_ROOT = settings.docs_root()`; `LOCK_STALE_SECONDS = 2*3600`; `MAX_NAMES = 8` (names listed per section); `RETRIES = 3`; `RETRY_WAIT = 20` s; `REPORT_AFTER_FAILURES = 3` (consecutive failed runs, about 45 min, before telling anyone).

**Functions**

| Signature | Contract |
|---|---|
| `_pid_alive(pid: int) -> bool` | Windows: `OpenProcess(0x1000 QUERY_LIMITED_INFORMATION)` then `GetExitCodeProcess == 259` (STILL_ACTIVE). POSIX: `os.kill(pid, 0)` |
| `_lock_held(path) -> bool` | Held only if the file is under 2 h old **and** its PID is alive. A dead PID's lock is deleted. An unreadable but fresh lock counts as held |
| `_fresh_portal_client() -> None` | `client.admin_client = HangeulAdminClient()`. Every step closes its client, so the next step needs a new one |
| `_passport_no(rec) -> str` | `Passport No` without spaces, upper-cased, only if ≥6 characters and it contains a digit (`PENDING` is no identity) |
| `_name_mobile(rec) -> str` | `_norm_key(Full Name) + _norm_key(Mobile)` when both are present |
| `_row_key(rec) -> str` | `"Student ID:{ID}"`, else `"Passport No:{P}"`, else `"NAME:{normname}{normmobile}"` |
| `_snapshot(cfg) -> {key: rec}` | `build_row` records keyed by `_row_key`. A duplicate key gets `#2`, `#3`, … so two rows never overwrite each other |
| `_digest(rec) -> str` | `sha1(json.dumps(rec, sort_keys=True))` |
| `_same_student(old, new) -> int` | 3 = same Student ID; 2 = same real passport number; 1 = same name+mobile; 0 = not the same |
| `_COMMON_NAME_WORDS` | About 50 name words (md, mst, mohammad, rahman, islam, hossain, akter, khatun, ahmed, …). One of these alone does not make two names alike |
| `_mobile(rec) -> str` | The last 10 digits (if there are ≥10) |
| `_likely_same(old, new) -> float` | For a key change that arrives with a name or mobile correction. 0 if either name is blank. **0 if both DOBs are set and differ** (siblings sharing one mobile). `1 + SequenceMatcher ratio` if the mobile is the same **and** (telling-word ratio ≥ 0.7, or a shared telling word of ≥3 letters, or one word set contains the other). 1.0 if the DOB and the normalised name are the same |
| `_changed_columns(old, new) -> str` | The first 4 changed column names, with `…` when there are more |
| `sheet_changes(prev, cur) -> (new, removed, edited)` | Pairs added and removed keys in two passes (`_same_student`, then `_likely_same`). Candidates sort by (−score, added index, removed index), and each row is paired once. A paired row with a different hash is an edit. A same-key row with a different hash is an edit. Returns names, and `"<name> (Col1, Col2…)"` for edits, in current row order |
| `sync_sheets(state) -> List[str]` | Walks `pb.all_targets()`, plus any previously tracked intake that is now empty (it is rebuilt empty once). No previous snapshot: build, then `📄 {title}: sheet ready (N students) — change tracking started`. Unchanged: if `pb.sheet_drift(cfg) > 0`, rebuild and report `🛠 … N cell(s) had been changed by hand … restored from the portal …`. Changed: build, then `📄 {title}: sheet updated — now N students` and `   • N new/removed/edited: …; +K more`. Saves `state["sheets"]` without the intakes that emptied |
| `sync_docs(cloud: Optional[Dict] = None) -> List[str]` (`:275`) | `vd.run_local(DOCS_ROOT)` on a new loop (`skip_drive_done=True` by default), then `doc_lines`. With a `cloud` dict it also keeps `cloud["documents"] = result["students"]` (the whole verified list the run read) and `cloud["documents_at"]` (the time the step started) |
| `doc_lines(result) -> List[str]` | `📁 N newly verified student(s) — documents saved:` and `   • {name} — {prog}, {n} file(s)[, k compressed to under 2 MB]`. Re-downloads are listed only if they brought new files (`📁 N student(s) changed their documents on the portal — new files saved:`). `⚠️ Could not download documents for {name}: {err[:120]} (will retry next run)`. Shows at most `MAX_NAMES*2` names per list |
| `verify_docs(cloud: Optional[Dict] = None) -> List[str]` (`:315`) | `av.summary_lines(av.run(budget=av.DEFAULT_BUDGET))`. With a `cloud` dict: **before** the run `cloud["store_ok"] = sheet_hooks.store_readable(av.STORE_PATH)` (a missing `results.json` is a fresh start and counts as readable; an unreadable one makes `auto_verify` start from an empty store, which must not be published as "the whole truth"), and after it `cloud["verify"] = result` |
| `SYNC_TITLE`, `CHECK_TITLE` (`:331-332`) | `"🔄 Portal sync — changes found"`, `"🔍 Document check"` (named so the hand-over records the title each notice was sent with) |
| `notify(lines, title=SYNC_TITLE) -> bool` (`:335`) | Plain text (no `parse_mode`) with `disable_web_page_preview`, split by `replies.split_text` (3900-character pieces between lines), posted to `https://api.telegram.org/bot{token}/sendMessage` for every `settings.brief_recipient_ids()`. Refusals and exceptions are logged, never raised. **Returns** `True` only when Telegram accepted every piece for at least one recipient (`False` when the token or recipients are missing); since 41055de, so a notice is published as a `notification` record only once it was really sent |
| `_with_retries(step, label)` | Up to 3 attempts, 20 s apart, each on a fresh portal client. Re-raises the last error |
| `_failure_line(state, key, label, err)` | Increments `state["failures"][key]`. Below 3: prints only, sends nothing. At 3 or more: `⚠️ {label} has failed {n} times in a row: {err}` |
| `_failure_cleared(state, key, label)` | Pops the counter. If it had reached 3: `✅ {label} is working again (it had failed {n} times in a row).` |
| `run_once(send=True, verify=True) -> List[str]` (`:412`) | Lock (skip if held) → **`cloud = {"run_at": time.time(), "title": SYNC_TITLE, "sent": []}` if `sheet_hooks.on()`, else `None`** (an import failure of the publish layer is one warning `Supabase publish failed (portal_sync): the publish layer could not load (<Type>)` and `cloud` stays `None`) → load state → sheets step (state saved in `finally`; an error is also kept as `cloud["sheets_error"]`) → docs step (state saved; `cloud["docs_error"]`) → print `[YYYY-MM-DD HH:MM] …` or `no changes`; `cloud["lines"] = lines` → `notify(lines)` if there is anything, and only if it returned `True`, `cloud["sent"].append((SYNC_TITLE, lines, time))` → verification (its exceptions are logged and never fail the sync; `cloud["verify_error"]`), sent with title `CHECK_TITLE` and recorded in `cloud["sent"]` the same way → **last of all** `cloud["export"] = pb._ALL_STUDENTS_CACHE` and `sheet_hooks.after_sync(cloud)` (`:475-477`) → unlink the lock (`finally`) |
| `main()` | `--no-notify`, `--no-verify` |

- **Reads:** the portal (CSV, the verified-documents list, `download_docs.php` ZIPs), Google Drive and Sheets, `data\sheet_state.json`. **Writes:** Sheets, `DOCS_ROOT\…`, `sheet_state.json`, the lock file, Telegram (`sendMessage`), everything `auto_verify` writes, and (publishing on) one handoff file in `data\cloud\pending\` plus a publisher process.
- **Callers:** `scheduler.run_portal_sync` (every 15 min), `bootstrap`/MIGRATION's quiet first sync (`--no-notify`). `src\cloud` also imports `_row_key` (`records.student_exports`: the Supabase `student_export` key is the sheet sync's own row key) and `_pid_alive` (`backfill`: the sync-lock check).
- **History:** 4154aa5 made `DOCS_ROOT` configurable. 9dcd9ad: row-key pairing (a Student ID given at payment verification is one edit, not new plus removed; `PENDING` is no identity; duplicate keys get `#n`); `notify` got its `title` and line-safe splitting; first downloads were separated from re-downloads. e164679: `_likely_same` (an ID given in the same sync as a name or mobile correction). c17d887: siblings on one mobile with other DOBs are no longer merged; a completed or re-spelled name still is. 41055de: the `cloud` dict, `notify -> bool`, the titles as constants and the hand-over at the end.
- **Evidence it works:** on 28 Sep 2026 at 21:36 `hangeul_sync.log` shows `Progress-sheet update attempt 1/3 failed (<HttpError 503 …>) — retrying in 20s`, and the run then succeeded with nothing sent. The log has 142 `no changes` runs up to 29 Sep 04:51. With publishing on (from 30 Sep 22:27), each run's publisher writes one line into the same log, e.g. `2026-09-30 22:43:15,500 [INFO] hangeul.cloud: Supabase publish (portal_sync): ok, 0 upserted, 0 deleted, 976 unchanged, 0 row(s) sent, 0 failed, 0 read(s) failed; 0 record(s) embedded in 0.0 s; 0.4 s in all, …`; at 23:13 and 23:28 it sent 2 and 3 changed rows (7.5 s and 5.9 s in all).

### 1.3 `src\sheets\verified_docs.py` (437 lines)

**Purpose.** Copies every document-verified Direct student's files from the portal's "download all" ZIP, to this PC (`run_local`, used by the sync and phase 4) or to Google Drive (`run`, the older mode, CLI only).

**Constants.** `LIST_PATH = "students.php?source=direct&filter_docs=verified"`; `TARGET_FOLDER_NAME = "VERIFIED STUDENT DOCUMENTS"`; `FOLDER_MIME = "application/vnd.google-apps.folder"`; `LOCAL_DONE_MARKER = ".download_complete"`; `MAX_FILE_BYTES = 2*1024*1024`; `_TARGET_BYTES = int(1.95*1024*1024)`; `BACKUP_ROOT = settings.docs_originals_root()` (`C:\Hangeul\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB`); `_A4 = (595, 842)` points.

| Signature | Contract |
|---|---|
| `_parse_rows(html) -> List[{"uid","name","passport","program","docs"}]` (`:44`) | The soup is built as `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (`:46-47`, 9ead47d): the portal is served through Cloudflare, which rewrites every e-mail address in the HTML as `[email protected]` with the real address XOR-encoded in `data-cfemail`; `src.scraper.parsers.decode_cf_emails` puts the address back before any text is read (see [03b](03b_FILES_src_scraper_llm_api_config.md) and [04](04_PORTAL_INTEGRATION.md)). Then, for each `<a href=~ download_docs\.php\?uid=\d+>`: the uid, then the parent `<tr>` text split by `" \| "`, taking the value after the labels `Full Name`, `Passport No` and `Program`. `docs` = the sorted unique file names from `view_doc\.php\?f=([^"&'\s]+)` in that row, joined with `\|`. The names carry the upload time (`passport_<uid>_<unix time>.jpeg`), so this is a fingerprint of what the student has uploaded |
| `async fetch_verified_students(client) -> List[Dict]` | `client.read_student_pages({"source":"direct","filter_docs":"verified"})` (every page), de-duplicated by uid. Raises `PortalUnavailable` (including a refused login) instead of returning a partial list |
| `program_folder(s) -> str` | The `PROGRAMS[*]["name"]` whose tokens match, else `"OTHER PROGRAMS"` |
| `folder_name(s) -> str` | `"{NAME} ({PASSPORT})"`, or the name alone, or `"UID {uid}"` |
| `_q`, `_find_folder`, `_find_or_create_folder`, `_existing_names`, `_upload` | Drive helpers (query escaping, `appProperties`, paged listing, resumable `MediaIoBaseUpload`) |
| `async run(limit=0, list_only=False)` | **Drive mode.** Folder chain `ALL STUDENTS/VERIFIED STUDENT DOCUMENTS/<PROGRAM>/<NAME (PASSPORT)>/`. Skips a folder whose `appProperties.hangeul_docs_complete == "1"`. Moves an older loose folder into its program folder. Uploads only names not already there, then sets the property. Prints `[n/N] name: k file(s) uploaded` or `FAILED` |
| `async _download_zip(client, uid) -> bytes` | `GET download_docs.php?uid=N&zip=1` (300 s). Raises `RuntimeError` unless the content-type contains `zip` |
| `_safe_path_part(s) -> str` | Replaces `\ / : * ? " < > \|` with `-`, strips trailing dots and spaces, `"UNNAMED"` if empty |
| `_drive_complete_names() -> set` | Names of every Drive folder with `appProperties has {key='hangeul_docs_complete' and value='1'}` |
| `_shrink_pdf(src) -> Optional[bytes]` | Re-renders each page as JPEG on an A4-sized page, down a ladder of (long side px, quality) = (1754,70) (1600,65) (1400,60) (1240,55) (1100,50) (950,45). Returns the first result ≤1.95 MB, else None |
| `_shrink_image(src) -> Optional[bytes]` | RGB thumbnail with long side 2400/2000/1600/1300 × quality 80/70/60/50; the first ≤1.95 MB |
| `shrink_large_files(folder, root) -> List[str]` | For each file over 2 MB (not the marker): shrink it; copy the original to `BACKUP_ROOT\<same relative path>` (only if no backup exists yet); write through `.part` then replace; a PNG becomes `.jpg`. Returns one report line per file handled |
| `async run_local(root, limit=0, skip_drive_done=True) -> {"saved","redownloaded","failed","students"}` (`:330`) | `"students"` (41055de) is **every** verified student the list showed (`listed = list(students)` at `:341`, taken before `limit` cuts the list): the sync hands it to Supabase as `student_documents`, so it must be the whole list whatever `limit` is. Logs in, lists the verified students; if `skip_drive_done`, skips names already complete in Drive. Folder `root\<PROGRAM>\<NAME (PASSPORT)>`. **Skip rule:** a marker whose content equals the current `docs` fingerprint is skipped; a legacy marker (`""`/`"ok"`) is rewritten with the fingerprint and skipped; a different fingerprint means a re-download (`again = True`). Only files not already on disk are extracted (written through `.part`). Then shrinks and writes the marker with the fingerprint. `saved`/`redownloaded` = `(program, name, n_new_files, shrink_report)`; `failed` = `(name, str(e))` |
| `main()` | `--list`, `--limit N`, `--local FOLDER`, `--include-drive-done` |

- **Reads:** the portal (the verified list pages, the ZIPs), Drive (when `skip_drive_done` is on). **Writes:** `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\…`, `…ORIGINALS OVER 2MB\…`, and Drive in `run()` mode.
- **Callers:** `auto_sync.sync_docs`, `bootstrap.py` phase 4, MIGRATION phase 4 (`--local … --include-drive-done`).
- **History:** 4154aa5: `BACKUP_ROOT` and the `--local` help text configurable. 9dcd9ad: the list goes through the client's one session path (a refused login raises instead of looping), and first downloads are separated from re-downloads. 41055de: the `"students"` key. 9ead47d: Cloudflare e-mails decoded in `_parse_rows` (the `students.php` verified-documents list feeds `student_documents`).
- **Gotcha, seen live:** the sync calls `run_local` with `skip_drive_done=True`, so students whose folders were finished in Drive by the old PC are skipped every run, even though phase 4 downloaded them (30 Sep 2026: `160 verified student(s) on the portal.`, `6 already complete in Google Drive - not downloaded again.`, `Finished: 0 saved, 156 already on this PC, 4 already in Drive, 0 failed.`). A document they replace on the portal is not fetched again by the sync.

### 1.4 `src\sheets\missing_report.py` (358 lines)

**Purpose.** The 09:05 "missing information" report (a Telegram summary and an Excel file), and the full per-program list behind the `/missing` buttons.

**Constants.** `REQUIRED` (30 fields: Student ID, Full Name, Surname, Given Name, Email, Mobile, Guardian WhatsApp, DOB, Gender, District, Address, Father, Mother, Study Status, SSC Year/GPA/Group/School, HSC Year/GPA/Group/College, Program, Passport Status, Passport No, Passport Expiry, Visa Rejection History, Sponsor, Sponsor Occupation, Bank Certificate). `UNIVERSITY_FIELDS` (4). `REPORT_DIR = BOT_ROOT\data\missing_reports`. `UNIVERSITY_NOTE`. Not counted: `IELTS/TOPIK` (optional) and `Passport Issue`.

| Signature | Contract |
|---|---|
| `_university_fields(rec, program_key) -> List[str]` | All 4 if the program is MASTER, or if `Study Status` contains both COMPLETED and GRADUATE. `["Previous University","Subject"]` if it contains `CURRENTLY IN UNDERGRADUATE`. Otherwise `[]` |
| `_sheet_has_university(program_key) -> bool` | True only for MASTER (the others drop those columns) |
| `portal_index(students=None) -> Dict` | The Direct CSV rows keyed `"ID:{sid}"` or `"NM:{normname}{normphone}"`. A key shared by two records is dropped (it tells nothing) |
| `portal_record(rec, index) -> Optional[Dict]` | Looks up the sheet row's own CSV record |
| `missing_fields(rec, program_key, index=None) -> List[str]` | Blank `REQUIRED` fields, plus the needed university fields, checked on the sheet (MASTER) or the portal record (others). If the record is not found they are not counted here |
| `unchecked_fields(rec, program_key, index=None) -> List[str]` | The university fields that could not be checked (no sheet column and no portal record) |
| `read_sheets() -> {"KLP\|MARCH 2027": [row dicts]}` | For each target: `find_sheet`, then the **first** tab's values, rows as dicts (padded), blank rows dropped. A missing sheet is logged and skipped |
| `_unchecked_line(unchecked, indent)` | `⚠️ University fields not checked for N student(s) (not found in the portal export): …` (the first 10) |
| `build_report(data, index=None) -> (lines, rows)` | Head: `🗓 Missing-information report — DD Mon YYYY` + `X of Y students have missing information.` (+ `UNIVERSITY_NOTE`). Per sheet: `📋 {name} {intake} — k of n incomplete`, the top 10 as `   • {sid} {name} — m missing: first 6 +more`, `   … and K more (see the Excel file)`. Then the no-intake list (15). `rows` = `(program name, intake, sid, name, mobile, n_missing, "a, b, …")` |
| `program_report(program_key, data=None, index=None) -> str` | The full list for one program: header, `(live from the progress sheets, DD Mon YYYY HH:MM)`, the totals line inserted at index 2, per intake `🗂 {intake} — k of n incomplete`, every incomplete student, `✅ Everyone complete`, and the no-intake section |
| `write_excel(rows) -> Path` | `data\missing_reports\missing_information_YYYY-MM-DD.xlsx`, one sheet `"Missing information"`, header `[Program, Intake, Student ID, Full Name, Mobile, Missing count, Missing fields]` in bold, frozen at `A2`, widths 34/15/15/32/16/14/120. Only rows with count > 0, sorted by (program, −count) |
| `send(lines, xlsx) -> bool` (`:241`) | `sendMessage` chunks (plain text) plus `sendDocument` (caption `"Every incomplete student with the fields they are missing"`) to every `brief_recipient_ids()`. `xlsx=None` sends the text only. **Returns** `True` only when Telegram accepted every text piece for at least one recipient (`False` when the token or recipients are missing); the Excel file's outcome does not count (41055de) |
| `_supabase(call) -> None` (`:280`) | The very last step: `call(sheet_hooks)` inside `try`; any exception is one `logger.warning("Supabase publish failed (missing_report): %s", type(e).__name__)`. Never raises and **never prints**, because the `/missing` button's reply is this process's stdout |
| `main()` (`:291`) | `--program KEY`: reads `data = read_sheets()` and `index = portal_index()` itself (the same reads, in the same order, as `program_report(key)` makes alone), prints `program_report(key, data, index)`, then `_supabase(lambda h: h.after_missing_program(key, text, data, index))` (`:314`). On error it prints `❌ Couldn't read the progress sheets or the portal: {reason}. …` and returns (exit 0, so `/missing` shows the reason) **without** a hand-over. `--student ID` prints one line (no hand-over). With no flag: the daily report. If it cannot be built: the notice `❌ Couldn't build today's missing-information report: {reason}. It will run again tomorrow at 09:05 (or send /missing).` is printed, sent (unless `--no-notify`), `sent_at = time.time() if send([notice], None) else None`, then `_supabase(… after_missing_failed(notice, sent_at, e))` (`:347`) and `SystemExit(1)`. Built: prints the lines and `Excel: <path>`, `sent_at = time.time() if send(lines, xlsx) else None` (None with `--no-notify`), then `_supabase(… after_missing_daily(lines, rows, sent_at))` (`:354`) |

- **Reads:** Google Sheets (first tab of each progress sheet), the portal CSV. **Writes:** `data\missing_reports\*.xlsx`, Telegram, and (publishing on) one handoff file plus a publisher process.
- **Callers:** `scheduler.run_missing_report` (09:05), `telegram_bot.missing_button` (`--program`), and `voice.py` (command `missing_report` → `missing_command`). `sheet_hooks.missing_program` calls `build_report` again (on that program's sheets only) to get the per-student rows for Supabase.
- **History:** 4154aa5 baseline paths. 9dcd9ad: university fields of KLP, EAP and Bachelor's students come from the portal record, and a student without one is "not checked", never "complete". e164679: a daily report that cannot be built says so in one plain Telegram message and exits non-zero. 41055de: `send -> bool`, `_supabase` and the three hand-overs.
- **Test note:** the send time and the heading come from this module's own `time` (`time.time()`, `time.strftime`), so a test that fixes `records.now` must also fix `missing_report.time`: `tests\test_cloud_jobs.py:456` `pin_job_clock` does (the test passed only on 29 Sep until e4d1cea).

### 1.5 `src\sheets\stage_report.py` (270 lines)

**Purpose.** The `/stage` menu's data: the intakes of a program (JSON) and the stage report of one program+intake (text).

**Constants.** `STAGE_ORDER` = Application Received, Payment Verified, Documents Under Review, Documents Verified, University Applied, Admission & Tuition, VIN Application, Embassy Submission, Visa Result, Admitted / Completed, Accepted (the portal's own stage filter). `NO_INTAKE = "NONE"`. `NOT_FOUND = "⚠️ Stage not found on the student list"`. `PROGRESS_READERS = 4`.

| Signature | Contract |
|---|---|
| `read_listed_students() -> List[Dict]` | Every `students.php` page through its **own** `HangeulAdminClient().read_students()`. Raises `PortalUnavailable` |
| `_norm(text)`, `_digits(text)` | Normaliser; the last 10 digits |
| `read_progress(uids) -> {uid: {"pct","stage","status"} \| {"error": why}}` | `GET progress.php?uid=N` with its own client. The first uid runs alone (so the login happens once), the rest go 4 at a time (`asyncio.Semaphore`). `parsers.parse_progress_page` runs in a thread (`.pg-ring` for the %, `.pg-now .pg-stage`, `.pg-now .pg-status`). Once a `PortalUnavailable` is unreachable or a login failure, the remaining pages get the same error without being requested |
| `match_listed(rows, listed) -> List[Optional[Dict]]` | Matches each CSV row to its list record by Student ID. Without an ID: by normalised name among records whose ID no other row claims, told apart by mobile if the name is shared. `None` if not found (never guessed) |
| `_stage_of(s)`, `attach_stages(rows, listed)` | The list's `status` (its stage), or `"(no stage)"`, or None |
| `program_students(key)`, `intakes_for(key) -> [{"intake","count"}]` | Direct students of the program. Intakes sorted by (year, month), then a `NONE` entry for blanks |
| `_intake_sort_key(intake)` | `(year, month index)`, unknown → `(9999, 99)` |
| `_progress_words(page, stage) -> str` | `"Verified — 22%"`. If the progress page's own stage differs: `"progress page: {stage} · {status} — {pct}%"`. `"progress page not read"` on an error |
| `stage_report(program_key, intake, listed=None, progress=None, reads=None) -> str` (`:178`) | `reads` (41055de), when a dict is given, is filled at `:204-205` with what the report was built from: `matched` (each CSV row's list record or None), `pages` (the progress pages by uid) and `by_stage` (`{stage: [(CSV row, list record)]}`), for the Supabase copy. Header `📊 Stages — {name} {intake}` + `(live from the portal, …) — N students`; counts per stage in `STAGE_ORDER` (then unknown stages, then `NOT_FOUND`); per stage `🔹 {stage} (n)` and `   {sid} {name} — {progress words}`; a closing warning `⚠️ k of the n progress pages could not be read ({most common reason})…`; footer `Status and % from each student's own progress page (progress.php), read just now.` Raises `PortalUnavailable` if the list cannot be read |
| `main()` (`:232`) | `--program` (required) and `--intake`. No intake: prints `json.dumps(intakes_for(key))` or `{"error": reason}` (no hand-over). With an intake: prints the report built with `reads={}`, then, as the very last step, `sheet_hooks.after_stage(key, intake if intake == "NONE" else pb.normalize_intake(intake), text, reads)` (`:257-258`) inside `try` (an exception is one `logging` warning `Supabase publish failed (stage_report): <Type>`, never printed). If the report fails it prints `❌ Couldn't read the portal: {reason}. …` and returns with no hand-over |

- **Reads:** the portal CSV, every `students.php` page, `progress.php?uid=N` for each listed student. **Writes:** stdout only, plus (publishing on) one handoff file and a publisher process.
- **Callers:** `telegram_bot.stage_program_button` / `stage_intake_button`, and free-text and voice routes to `/stage`. `src\cloud\backfill.collect_progress` reuses `read_progress` for the one-time backfill (every student's progress page, 4 at a time).
- **Why it avoids the CSV's `Current Stage`, `Current Status` and `Progress %`:** they were stale. In Sep 2026, 64 of 329 statuses and 89 of 329 percentages disagreed with the progress pages, and both pending-payment applicants showed "Payment Verified" (module docstring). The Supabase `student_export` records carry `stale_columns: ["Current Stage", "Current Status", "Progress %"]` for the same reason.
- **History:** 9dcd9ad: the stage comes from the list's "Stage · Applied" column. e164679: status and % from each `progress.php`. (The memory note "status and % still come from the CSV" is stale: HEAD reads the progress pages.) 41055de: `reads=` and the hand-over.

### 1.6 `src\sheets\passport_issue.py` (145 lines)

**Purpose.** The portal keeps the passport issue date only on the edit page (`student_edit.php`, input `passport_issue_date`). It is cached daily at 08:30. Since 41055de the same refresh is also the source of every student's **profile** in Supabase (`student_profile`): it already reads every edit page, so while publishing is on it keeps each page in memory and hands them over after the cache file is written.

| Item | Detail |
|---|---|
| `CACHE_PATH` | `data\passport_issue.json`, shape `{"by_passport": {"<PASSPORT>": "<date as typed>"}}` (276 entries on 29 Sep, 282 on 30 Sep) |
| `load() -> Dict[str,str]` | Returns `by_passport` (`{}` if missing or unreadable, with a warning) |
| `passport_key(value) -> str` | No spaces, upper-cased, ≥6 characters and containing a digit, else `""` |
| `_ISSUE_RE` | `r'name="passport_issue_date"[^>]*value="([^"]*)"'` |
| `MAX_UNREAD = 10` | Edit pages that may time out before the refresh gives up (and keeps the cache) |
| `async _fetch_async(limit=0, pages=None) -> Dict` (`:58`) | `pages`, when a dict is given, keeps every edit page read as `pages[str(uid)] = (html, time.time())` (`:84-85`), for the Supabase profiles. `c.read_students()` (every page) → `{passport_key(details["Passport No"]): [uids]}`. For each passport, `GET student_edit.php?id=uid` (60 s) for each uid. A `PortalUnavailable` that is not "unreachable", or the 11th unreachable page, is **re-raised** (so the old cache is kept). An unreachable page keeps the previous date. Several uids with **different** dates → left out (logged). Prints progress every 50 |
| `refresh(limit=0, pages=None) -> Dict` (`:106`) | Runs `_fetch_async(limit, pages)` and **then** writes the JSON (indent 1). An exception before the write leaves the old file untouched |
| `_supabase_on() -> bool` (`:113`) | `sheet_hooks.on()`, `False` on any exception |
| `main()` (`:121`) | `--refresh`, `--limit N`. `pages = {} if args.refresh and _supabase_on() else None` (pages are kept only while publishing is on; their profiles are parsed **after** the cache file is written, so the refresh itself is not slowed). Prints the count and the first 10 entries. After a `--refresh`, as the very last step: `sheet_hooks.after_issue_refresh(data, pages, not args.limit)` (`:139`; complete only without `--limit`), an exception being one warning `Supabase publish failed (issue_refresh): <Type>` |

- **Callers:** `scheduler.run_issue_date_refresh` (08:30), `bootstrap.py` phase 2, `progress_builder.issue_date_for` (fallback), `auto_verify.field_fingerprint`, `field_check` (the cache age and the value). `passport_key` is also imported by `src\cloud\records`, `sheet_hooks` and `student_index` (one passport normaliser everywhere).
- **History:** 9dcd9ad: keyed by each student's own Passport No read from the list (the old key `PENDING` shared one date across 12 students); a failed read keeps the last cache. 41055de: `pages=` and the hand-over.
- **Note:** a refresh with up to `MAX_UNREAD` (10) timed-out edit pages still writes the file and is published complete; the safety reviewer of 29 Sep considered this and found no delete that differs from what the file itself says (an unreadable page keeps its previous date in the file).

### 1.7 `src\sheets\attendance.py` (111 lines)

**Purpose.** Reads the office attendance Google Sheet ("Attendance — Live (auto-updated from office PC)"). **No job or command calls it** (HANDOFF §5.2: the office start time and grace period were never confirmed).

`SHEET_ID = "<Sheet id: attendance, see attendance.py:21>"`, `TODAY_TAB = "Today"`, `OFFICE_START = time(9,0)`, `GRACE_MINUTES = 0`. `_parse_time(v)` uses `\s*(\d{1,2})[:.](\d{2})`. `read_today() -> (label, [{"name","in","out","punches","late_by"}])`: a row starting "Daily attendance" gives the label; the row whose first cell is "Name" is the header; each later row is `[name, in, out, punches]`. `report_lines()`: `🕘 Attendance — {label}`, `N in, k late (office starts 09:00)`, the late, on-time and no-check-in lists, and device IDs without a name (`ID\s*\d+`). CLI prints the lines. It uses `pb._services()` and so the same OAuth token. Not published to Supabase either.

### 1.8 The sheet jobs' Supabase hand-over: `src\cloud\sheet_hooks.py` (470 lines)

**Purpose.** Since 30 Sep 2026 22:27 (`CLOUD_PUBLISH_ENABLED=true`) what the bot reads from the portal and the reports it builds are also copied (which job writes which kind, and what is read but not published, is the table in [13 §13](13_SUPABASE_PUBLISHING.md)), as rows + text + gte-small embeddings, into the Supabase project `dcbcbpwpmdtaanboetiz` for Jeannie (the owner's spec `hangeul-bot-prompt.md`, decisions D1-D13; see [13](13_SUPABASE_PUBLISHING.md)). This module is the sheet jobs' side of that copy: one function each job calls as its **very last step**, after Drive, Sheets, the `.xlsx` files and Telegram. It builds the records from what the job **already read** (nothing is read from the portal again; only the edit pages' forms are parsed, by the client's own `HangeulAdminClient._profile_fields`) and gives them to `src.cloud.handoff.submit`. The file map of `src\cloud\` (records, publish, handoff, embed, …) is [03d](03d_FILES_src_cloud.md).

| Job (process) | Hook (line) | `hg_runs.job` | Batches handed over (kind: scope, complete?) |
|---|---|---|---|
| `auto_sync` (15 min) | `after_sync(cloud)` (`:441`) → `sync_batches` (`:160`) | `portal_sync` | `student_export`: `all`, complete only if `records.export_complete` (header has `Student ID` and `Full Name` **and** at least `EXPORT_SHARE = 0.9` × the students the last whole `students.php` read counted, taken from the hash state by `listed_students()` = `len(publish.known_keys("student","all"))`), else partial with the reason in `failed_reads`. `student_documents`: `all`, complete (never sent when the list is empty). `report` `sync_summary\|<run time>` (never complete) + its `report_section`s (complete; one per unindented line with its indented lines, `line_sections` `:115`). After the document check (`verify_batches` `:266`): `doc_verdict`, `field_check`, `doc_page_text` per passport just checked **plus up to `CATCH_UP_PASSPORTS = 6` passports Supabase never accepted** (each passport its own complete scope); then, from the whole `results.json`: `doc_check` (`all`, complete), `field_correction` (`all`, append-only, never complete), the `DOCUMENT CHECK` and `FIELD CHECK` reports + sections. One `notification` per notice Telegram accepted (`cloud["sent"]`) |
| `missing_report` (09:05) | `after_missing_daily(lines, rows, sent_at)` (`:446`) | `missing_report` | `report` `missing_report\|<day>` + one `report_section` per incomplete student; a `notification` only when `sent_at` is set |
| `missing_report` (09:05, failed) | `after_missing_failed(notice, sent_at, error)` (`:451`) | `missing_report` | the failure notice as a `notification` (if sent) and `"progress sheets or the portal: <reason>"` in `failed_reads` |
| `missing_report --program` (`/missing`) | `after_missing_program(key, text, data, index)` (`:456`) | `missing_report` | `report` `missing_program:<KEY>\|<day>` whose data holds every student's missing fields (`build_report` on that program's sheets), with a section per intake |
| `stage_report --intake` (`/stage`) | `after_stage(key, intake, text, reads)` (`:462`) | `stage_report` | `student_progress` of the pages read (`all`, **never complete**: one program and intake is not every student) and `report` `stage_report:<KEY>:<INTAKE>\|<day>` + a section per stage |
| `passport_issue --refresh` (08:30) | `after_issue_refresh(by_passport, pages, complete)` (`:467`) | `issue_refresh` | `passport_issue` (`all`, complete only without `--limit`) and one `student_profile` per edit page read (each uid its own complete scope) |

**Rules, and why:**
- `on()` (`:56`) = `handoff.enabled()` = `SUPABASE_URL` **and** `SUPABASE_SECRET_KEY` non-empty **and** `CLOUD_PUBLISH_ENABLED` true (`src\cloud\publish.py:103`); `False` on any exception. While it is off the jobs keep nothing and `hand_over` builds nothing (no file, no process, no request).
- `hand_over(job, build)` (`:65`) never raises and never prints (a button report's stdout is its reply). It drops batches without rows (a complete batch is never sent empty: an empty list from a page whose layout changed must not empty a scope, R2/R5) and calls `handoff.submit`. A failure is one line on the `hangeul.cloud` logger, `Supabase publish failed (<job>): the records could not be built (<ExceptionType>)`, with no student data in it.
- A read that failed sends **no batch** and adds a plain reason to `failed_reads` (the `hg_runs` row then says `partial`). `reason(what, e)` (`:83`) uses the portal's own words for a portal failure (`portal_error_reason`), otherwise only the exception's type (an exception text can quote a student's value), and replaces any URL with `<url>`, capped at 200 characters.
- `store_readable(path)` (`:149`): a missing `results.json` counts as readable (a fresh start is the truth); an unreadable one means `auto_verify` started from an empty store, so the store-wide kinds (`doc_check`, `field_correction`, the two reports) are **not** sent that run.
- `student_ids(documents, export)` (`:226`) → `{passport: (portal uid, HNG id)}` from this run's verified list and CSV, merged into `data\cloud\student_index.json` (`src.cloud.student_index.remember`), so the passport-keyed records carry the student's uid even on a run whose list could not be read.
- `handoff.submit` (`src\cloud\handoff.py:118`) writes `data\cloud\pending\<YYYYmmdd-HHMMSS-ffffff>-<job>.json` = `{"version": 1, "job", "created_at", "failed_reads", "batches"}` through a `.part` file and `os.replace`, then starts `python.exe -m src.cloud.publish --from <file> --timeout 3600` (the console `python.exe`, never `pythonw`) with `cwd` = the bot folder, `stdin=DEVNULL`, stdout and stderr **appended to `hangeul_sync.log`** (never the caller's pipe: `_run_report_module` reads the button report's stdout to its end), `close_fds=True`, `CREATE_NO_WINDOW`, and the env `PYTHONIOENCODING=utf-8`, `CUDA_VISIBLE_DEVICES=-1`, `HF_HUB_OFFLINE=1`. It does not wait. The publisher deletes the file when it is done (sent or failed); files older than `STALE_HOURS = 6` (a publisher that was killed) are pruned on the next write.

**Gotcha, seen live.** The publisher's log line and the finishing sync's own stdout go into the same `hangeul_sync.log`; the sync's stdout goes to a file and is block-buffered, so its last lines can reach the log after the publisher has started writing. On 30 Sep at 22:58 the sync's `[YYYY-MM-DD HH:MM] …` stamp line was cut in two: `[2026-09-` then `2026-09-30 22:58:09,138 [INFO] hangeul.cloud: Supabase publish (portal_sync): ok, …`. Harmless; read the log with that in mind.

**History:** 41055de (branch `cloud/jobs`: the hooks, `store_readable`, the catch-up passports and `tests\test_cloud_jobs.py`), 3caa393 (review fixes: the export is complete only under the 90 % rule, no longer on its header alone; `student_ids` through the new `student_index`). The handoff's `CUDA_VISIBLE_DEVICES=-1` (it was `""`, which does not survive into a Windows child) is from 752cd53. Tests: [10 §3](10_TESTS_AND_VERIFICATION.md) (`test_cloud_jobs.py`, 26 tests).

---

## 2. `src\verify\`

### 2.1 `src\verify\rules.py` (134 lines): the guidelines as data

| Name | Value |
|---|---|
| `PROGRAMS` | `["KLP","EAP","BACHELOR","MASTER"]` |
| `MIN_BANK_TAKA` | KLP 1,800,000 · EAP 1,800,000 · BACHELOR 2,500,000 · MASTER 2,500,000 (Document 08) |
| `MIN_TAX_PAID_TAKA` / `MIN_NET_WEALTH_TAKA` | 10,000 / 5,000,000 (Master's, Document 9.1) |
| `PASSPORT_MIN_MONTHS` | 12 |
| `FAMILY_CERT_MAX_MONTHS` | 3 |
| `BANK_MIN_ACCOUNT_MONTHS` | 6 (`BANK_MIN_STATEMENT_MONTHS` 6 and `BANK_RELAXED_STATEMENT_MONTHS` 2 are defined but unused) |
| `PHOTO_RATIO` / `PHOTO_FORMATS` | 35/45 / `(".jpg", ".jpeg")` |
| `MIN_OPENING_BALANCE`, `PREFERRED_OPENING_MAX` | Defined, **not used by any check at HEAD** (the "opening balance" false-FAIL rule of HANDOFF §5.1 is dormant) |
| `MIN_COLOUR_PERCENT` | 0.08 (% of clearly coloured pixels; 0.5 had called 36 genuine colour scans greyscale) |
| `IDENTITY_DOCS` | passport, student_nid, birth_cert, father_nid, mother_nid, family_cert, academic |
| `QR_DOCS` | `["birth_cert"]` (the only document required in its online QR form) |
| `TRANSLATION_WORDS`, `BANGLA_RANGE` | `["translated","translation","true copy","english translation"]`, U+0980–U+09FF |
| `FILE_PATTERNS` | Document key → file-name keywords (listed in [07 §10.2](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)) |
| `REQUIRED` | Every program: passport, photo, birth_cert, father_nid, mother_nid, family_cert, academic, bank, trade_license; MASTER adds income_tax |
| `OPTIONAL` | student_nid, death_cert, affidavit, personal_statement, recommendation, eca, language_cert |
| Word lists | `NOTARY_WORDS`, `LAWYER_PAD_WORDS`, `APOSTILLE_WORDS`, `PROVISIONAL_WORDS`, `ONLINE_BIRTH_WORDS`, `OPENING_BALANCE_WORDS`, `SOLVENCY_WORDS`, `SEAL_WORDS`, `USD_WORDS`, `UNION_ISSUER_WORDS`, `REF_NO_WORDS`, `TRADE_RUNNING_WORDS` |
| `BOILERPLATE_NUMBERS` | `{"1301109623"}` (printed on 49 students' NIDs: a form or notary number, not a person's) |
| `TYPED_DOCS` | `{"personal_statement","recommendation","eca"}` (the colour-scan rule does not apply) |
| `TITLES` | Key → report title: `"01 Passport"`, `"02 Photo"`, `"03 Student NID"`, `"04 Birth Certificate"`, `"05 Father NID"`, `"05 Mother NID"`, `"05 Death Certificate"`, `"06 Family Relationship Certificate"`, `"07 Academic Certificate & Transcript"`, `"08 Bank Solvency & Statement"`, `"09 Financial (Trade Licence / TIN / Employment)"`, `"09.1 Income Tax"`, `"10 Affidavit"`, and 4 more |

No functions; imported as `R` by `doc_verifier`, `page_checks` and `field_check`. Unchanged since the baseline.

### 2.2 `src\verify\doc_verifier.py` (1241 lines)

**Purpose.** Checks one student's **downloaded** documents against `rules.py` and the portal record. It reads every file (the PDF text layer first, EasyOCR only for scans), runs the per-document rules, adds the image rules from `page_checks`, then the cross-document checks. It also has a standalone Excel report.

**Module state.** `DOCS_ROOTS = [settings.docs_root(), settings.konyang_root()]` (an absent root is skipped; Konyang is absent on this PC); `REPORT_DIR = settings.verification_dir()`; `TODAY = date.today()` at import (fine, because every run is a new process); `PASS, FLAG, FAIL, MISSING, NOTE`; `_reader` (the lazy EasyOCR singleton).

**Reading text**

| Signature | Contract |
|---|---|
| `_ocr_reader()` | `easyocr.Reader(["en"], gpu=torch.cuda.is_available(), verbose=False)`. `verbose=False` since d659983: the first-run download's "█" progress bar crashed a cp1252 console, and every scan read as unreadable |
| `_MIN_PAGE_CHARS = 300` | Below this, `_ocr_image` retries turned 90° CCW, 90° CW and 180° and keeps the longest text (landscape board certificates read 196 characters untouched and 729 turned) |
| `_ocr_image(arr, turned=None) -> str` | `" ".join(readtext(arr, detail=0))` with the rotation retry. Appends `True` to `turned` when a turn helped |
| `read_pages(path, max_pages=20, sideways=None) -> List[str]` | Text per page, in order. Images: OCR. PDF pages with a text layer under 40 characters: rendered at **200 dpi** and OCR'd; the 1-based numbers of turned pages go into `sideways`. An unopenable PDF → `[]` |
| `read_document(path, max_pages=20) -> (text, sizes)` | The whole-file text plus each page's size. Images: `PIL` size + OCR. PDF: a text layer over 80 characters is used as is, otherwise **150 dpi** OCR. An unopenable PDF → `("[unreadable: e]", [])` |

**Text helpers.** `norm(s)` (collapse whitespace, lower-case); `notarised(text, path)` (`NOTARY_WORDS` or `page_checks.seal_present`); `has_any(text, words)` (substring, then fuzzy: tokens of ≥4 letters vs words of ≥5, length within ±2, `SequenceMatcher ≥ 0.8`, first word of a phrase; so "advocale" matches "advocate"); `_MONTHS`; `_DIGIT_LOOKALIKE` (`I l→1, S s→5, O o→0, B→8, Z→2, G→6, q→9`, used only for the ordinal day); `months_between(a, b)`.

`find_dates(text) -> List[date]` recognises: `D[./-]M[./-]YYYY` (day and month swapped when month > 12); `YYYY[./-]M[./-]D`; `D(st|nd|rd|th)? Mon[a-z]* YYYY`; `YYYY.M.D`; `D.M.YYYY`; `Mon D(th)?, YYYY`; two-digit years `D-M-YY` (2000+ when ≤ this year's two digits + 15); OCR ordinals such as `ISth September 2026`; and boxed digits `1 5  1 0  2 0 0 4` → 15/10/2004 (year 1900 to this year + 15).

`money_value(raw)` handles lakh grouping and a decimal comma (`'33,74,119,69'` → 3374119.69). `find_money_taka(text)` matches `\b(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{6,9}(?:\.\d{1,2})?)\b` and keeps amounts from 100,000 to 100,000,000, unique, in descending order.

**Per-document checkers.** Each returns `[(verdict, detail)]`. The full rule table is in [07 §10.4](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md).

| Signature | Notes |
|---|---|
| `check_passport(text, student, sizes, path=None)` | Expiry from the portal (`YYYY-MM-DD`), else the latest date on the scan dated this year or later. The seal-placement check is commented out (it flagged every scan) |
| `check_photo(text, student, sizes, path=None)` | Ratio, resolution, background (top band and top corners only; the shoulders are not backdrop), contrast, format, a NOTE for female applicants (ears visible) |
| `check_birth_cert(text, student, sizes, path=None, others=None)` | The DOB is compared with the **passport** text (`others["passport"]`), not the portal |
| `nid_numbers(text) -> List[str]` | Digit runs `\d[\d\s.\-]{7,32}\d`, joined, kept at 17/13/10 digits; drops `BOILERPLATE_NUMBERS`, `01…` of ≤13 digits (mobiles) and 13-digit `880…` |
| `check_nid(text, student, sizes, whose, path=None, others=None)` | `whose` ∈ father/mother/student. Numbers compared **per page and only at the same length** (a 10-digit Smart NID and a 13-digit legacy number are two formats of one identity) |
| `issue_date(text) -> Optional[date]` | From the first `(date\|ref\|memo\|serial)[^\n]{0,90}` line in the first 1200 characters (within 3 years, never a birth date), or a DDMMYYYY found in its digit run; else the latest date within the last 3 years |
| `check_family_cert(text, student, sizes, path=None)` | 3-month validity, Union Parishad/City Corporation issuer, notarised, the student's name in the first 1200 characters, ≥2 ID numbers |
| `check_academic(text, student, sizes, path=None, others=None)` | `page_checks.academic_check(path, read_pages(path, sideways=…))`, a NOTE for sideways pages, provisional, notarised, the three names, SSC/HSC GPA |
| `looks_like_solvency(text)`, `looks_like_statement(text)` | Word tests (the statement test needs ≥2 of statement/debit/credit/…) |
| `document_date(text)` | `issue_date` or the latest date |
| `opening_balance(text)` | **Unused.** A labelled figure, else the last figure on the first transaction row |
| `STATEMENT_DATE_LABELS`, `statement_date(pages)` | A date beside "Generation Date", "Print Date", "Statement Date", "Date of Issue", "as on", …; else the end of a "period … to …" range |
| `check_bank(text, student, sizes, program, path=None, others=None)` | Minimum, USD on solvency, seal, account age, **solvency (page 1) vs statement (pages 2+) date: FLAG, not FAIL** (f74e45d), and the account holder (sponsor FATHER/MOTHER, else the student). It records `others["_account_holder"]` |
| `current_fiscal_year()` | `"Y-Y+1"`, July to June |
| `taxpayer_name(text)`, `proprietor_name(text)`, `is_tin(text)` | Regexes: `certify\s+that\s+(…)\s+is\s+a\s+registered\s+taxpayer`, `name\s+of\s+proprietor…`, and so on |
| `check_financial(text, student, sizes, path=None, others=None)` | Sponsor must be a parent; the document is in the account holder's name; kind; trade licence fiscal year = current; business ≥2 years; notarised; TIN name vs proprietor name (each once per student via `_financial_name_done` and `_tin_vs_trade_done`) |
| `check_income_tax(text, student, sizes, program, path=None)` | MASTER net wealth ≥ 50 lakh; a tax-paid figure (< 1,000,000); notarised |

`CHECKS` maps each key to `lambda t, s, z, p, prog, path: …`, where `p` is the dict of texts already read for this student (so the birth certificate can see the passport and the trade licence can see the bank account holder).

**Cross-document checks.** `name_tokens(name)` drops md/mst/most/mohammad/mohammed/sk/mr/mrs/late and tokens of ≤2 characters. `readable(text)`: ≥25 words of ≥3 letters, >60% of them with a vowel. `name_in(text, name) -> Optional[bool]`: hits ≥ max(1, tokens − 1). `cross_checks(texts, student) -> rows` builds `CROSS-CHECK name` (per person; FLAG when not matched on ≥2 readable documents), `CROSS-CHECK date of birth` (FLAG when the portal DOB is missing on ≥2 readable documents), `CROSS-CHECK passport number` (FLAG when on no document), and `CROSS-CHECK affidavit` (only after a name mismatch: no affidavit → FLAG; not in the applicant's name → **FAIL**).

**Running a student**

| Signature | Contract |
|---|---|
| `classify(filename) -> Optional[str]` | The **longest** matching `FILE_PATTERNS` keyword wins ("PASSPORT SIZE PHOTO" → photo; "FATHER NID" → father_nid) |
| `verify_student(folder, student, program) -> List[row]` | Groups non-dot files by key (unknown → `"other"`, never checked). For each key in `REQUIRED[program] + OPTIONAL`: a required key that is absent → `{"verdict": "MISSING", "detail": "required by the guideline but not uploaded"}`. For each file: `read_document` (on an exception → FLAG "could not read the file"), the checker, and for non-photos `PC.colour_check(PC.inspect(path), key)`, `PC.qr_check(info, required=key in QR_DOCS, text)` and `PC.bangla_check(text)`. The row verdict is the worst of FAIL > FLAG > PASS (**NOTE never counts**), and the detail is `" \| ".join("VERDICT: text")`. Ends with `cross_checks` |
| `student_verdict(rows) -> str` | Any MISSING → `INCOMPLETE`; else any FAIL → `FAIL`; else any FLAG → `REVIEW`; else `PASS` |
| `student_folders() -> {PASSPORT: (folder, name)}` | Every `<root>\<program>\<NAME (PASSPORT)>` (also a flat `<root>\<NAME (PASSPORT)>`), regex `(.*?)\s*\(([^)]+)\)$`. The first root wins (`setdefault`) |
| `portal_students() -> {PASSPORT: csv row}` | **All** CSV rows (not only Direct) keyed by the upper-cased `Passport No`. The last row wins, which is how the head of branch's duplicated number hides a student (HANDOFF §5.2) |
| `program_of(student) -> str` | `pb.program_key_of` or `"KLP"` |
| `write_report(all_rows, path)`, `run(passports, report_name="")` | Standalone report `document_check_YYYY-MM-DD_HHMM.xlsx` (sheets "Documents" and "Summary"), rewritten after every student |
| `main()` | `--student NAMEPART`, `--passport P`, `--all`, `--program KEY`, `--limit N`, `--report NAME` |

- **Reads:** local files under `DOCS_ROOTS`, the portal CSV (through `progress_builder`). **Writes:** only the standalone report in the CLI; the bot uses it through `auto_verify`.
- **History:** f74e45d: the solvency vs statement date rule went FAIL → FLAG. 4154aa5: `DOCS_ROOTS` and `REPORT_DIR` from settings (they were `E:\…`). d659983: `verbose=False`. HANDOFF §6.1: a shell heredoc once turned `\b` into backspace bytes, and NID numbers were never read. Write patches with an editor tool.

### 2.3 `src\verify\page_checks.py` (452 lines)

**Purpose.** Checks that look at the scan itself: colour vs black-and-white, QR/barcodes (pyzbar first, OpenCV as fallback), Bangla needing translation, visible notary seals, and e-Apostille page structure.

| Signature | Contract |
|---|---|
| `_pages(path, dpi=250, max_pages=4)` | Each page as an OpenCV BGR image (PyMuPDF for PDFs, `cv2.imread` for images) |
| `is_digital(path) -> bool` | A PDF where at least half of the first ≤4 pages hold ≥25 real text words (`get_text("words")`). Images are never digital |
| `_clean_code(raw: bytes) -> str` | Decodes barcode bytes (utf-8, utf-16-le/be, latin-1), strips control characters |
| `inspect(path) -> {"saturation","qr","qr_seen","pages","digital"}` | Saturation = max over pages of % pixels with HSV S>70 and V>60. QR from `cv2.QRCodeDetector().detectAndDecodeMulti` plus `pyzbar.decode`; `qr_seen` is also set by `detectMulti` (a QR is there but unreadable) |
| `colour_check(info, doc_key="")` | `TYPED_DOCS` → PASS; digital → PASS; None → FLAG; ≥0.08% → PASS; ≥0.02% → NOTE (a pale stamp); else **FAIL** "looks like a black-and-white scan" |
| `qr_check(info, required=False, text="")` | A TIN (taxpayer/tin certificate/etin) → `[]`. Codes → PASS (the first 48 characters of 2 codes). A QR seen but unreadable → FLAG. Required (birth certificate) with neither a QR nor online wording → FLAG. Else PASS (the rule is about legibility; not every document carries a QR) |
| `bangla_check(text)` | >40 Bangla characters and fewer Latin than Bangla: translation words → FLAG, else **FAIL** |
| `passport_seal_check(path)` | Red seal (S>90, V>70, H<10 or >170) overlapping the largest ink block → FAIL if >10% of the seal is inside. **Disabled** in `check_passport` (it flagged all 12 test passports) |
| `annotate(path, out_png)` | Debug drawing. **Dead code** (HANDOFF §5.2) |
| `seal_present(path) -> bool` | 150 dpi, ≤4 pages. Violet mask (H 115–165, S>60, V>60) with a component > 0.08% of the page, or red mask with a component > 0.15%, after a 9×9 morphological close |
| `APOSTILLE_SUBJECTS` | `verification_dir()\apostille.json` `{application id: "HSC"}`. **Absent on this PC** (lost with the old PC), so the subject-mismatch FAIL is dormant |
| `apostille_subject(url)` | Looks up the id `/([0-9]{6,})\s*$` in that JSON |
| `APOSTILLE_HOSTS` | `("apostille.mygov.bd", "mofa-servicedirect", "apostille")` |
| `LEVELS` | Regexes, HSC tested before SSC: `HSC` `higher\s+secondary\|\bh\.?\s?s\.?\s?c\b\|\balim\b\|intermediate\s+certificate`; `SSC` `secondary\s+school\s+certificate\|\bs\.?\s?s\.?\s?c\b\|\bdakhil\b`; `DIPLOMA`; `MASTER`; `BACHELOR` |
| `page_codes(path, max_pages=20) -> List[List[str]]` | Codes per page at 250 dpi (pyzbar first, OpenCV if none) |
| `level_of(text)` | The first matching level |
| `academic_check(path, pages_text)` | No apostille QR: FAIL (wording present, "QR could not be read"; or none at all). Else PASS "n e-Apostille QR code(s) read". **Page 1 not an apostille → FAIL** (kept FAIL by the owner's decision 18). For each apostille block (up to the next): empty → FLAG; unnamed → NOTE; **mixed levels → FLAG** (f74e45d, was FAIL); a known subject ≠ level → FAIL (dormant); else PASS |

- **Callers:** `doc_verifier`. **History:** f74e45d (mixed levels → FLAG); 4154aa5 (`APOSTILLE_SUBJECTS` path). HANDOFF §6.1: the heredoc `\b` corruption once stopped `H.S.C.`, `B.Sc`, `MBA` and `Master` from being recognised (about 70 false flags).

### 2.4 `src\verify\field_check.py` (302 lines)

**Purpose.** Does each portal field agree with the student's documents?

`MATCH, DIFFERS, UNREADABLE, NO_DOC = "MATCH", "DIFFERS", "UNREADABLE", "NO DOCUMENT"`, plus `"BLANK"` for an empty portal value. `SOURCES` maps each checkable field to report-title prefixes (for example `"DOB": ["01 Passport","03 Student NID","04 Birth","06 Family","07 Academic"]`; `"District"`/`"Address"` include `"05 "`, meaning any 05-document; `"Sponsor Occupation": ["09 Financial"]`). `DATE_FIELDS = {DOB, Passport Expiry, Passport Issue}`, `NUMBER_FIELDS = {Passport No, Guardian WhatsApp, SSC Year, HSC Year}`, `GPA_FIELDS = {SSC GPA, HSC GPA, CGPA}`. `_OCR_SWAPS`: a/A→4, o/O→0, i/I/l/L→1, s/S→5, b/B→8. `ISSUE_CACHE_MAX_HOURS = 26`.

| Signature | Contract |
|---|---|
| `_ocr_variant(s)` | `\W` removed, lower-cased, then `_OCR_SWAPS` |
| `_docs_for(field, texts)` | Texts whose title starts with or contains a `SOURCES` prefix |
| `_validity_consistent(issue, expiry) -> str` | A non-empty explanation when expiry = issue + 5 or 10 years (±3 days; 29 Feb → 28) |
| `check_field(field, value, texts, student=None) -> (result, detail)` | No source document → NO DOCUMENT. Dates: `find_dates` or the MRZ `YYMMDD` (if `P<[A-Z<]{3,}` or `<<<` is present). Numbers: substring, then `_ocr_variant`. GPA: exact or `\b{g}\d*\b`. Text: tokens >2 characters, hits ≥ n−1. Not found and nothing readable → UNREADABLE. Issue/expiry consistent with each other → MATCH. A date field with other readable dates → DIFFERS ("shows … instead"). Sponsor Occupation "business" + a trade licence → MATCH. Passport No: a plausible other number `\b(?:[A-Z]\d{8}\|B[MWXY]\d{7})\b` → DIFFERS. Else UNREADABLE |
| `issue_cache_age_hours() -> Optional[float]` | The age of `passport_issue.json` by mtime |
| `check_student(pas, folder, student) -> List[{"field","portal","result","detail"}]` | Builds the student's sheet row (`pb.build_row`), reads every file (`read_document`, titles via `classify`/`R.TITLES`), and checks each column that is in `SOURCES`. Blank → BLANK. **Passport Issue DIFFERS with a cache missing or over 26 h old → UNREADABLE** with the refresh command (never accuse staff from stale data: HANDOFF §6.3) |
| `write_report(rows, path)`, `main()` | Standalone `field_check_*.xlsx` ("Field check" and "Summary"). Flags `--passport`, `--program`, `--report`, `--skip` |

- **Imports:** `progress_builder`, `rules`, and from `doc_verifier`: `REPORT_DIR, classify, find_dates, find_money_taka, norm, portal_students, program_of, read_document, readable, student_folders`. Because it imports `read_document` by name, `auto_verify` must patch `fc.read_document` as well.
- **History:** 4154aa5 only (paths). HANDOFF §4.5 reported 3,394 comparisons with 1 difference on the old PC. On this PC: 2,842 MATCH, 364 UNREADABLE, 11 BLANK, 1 DIFFERS.

### 2.5 `src\verify\auto_verify.py` (609 lines)

**Purpose.** The pass the sync runs: pick the students whose documents or portal record changed, run the document check and then the field check, keep every OCR text so nothing is read twice, store the results, and rebuild both Excel reports from the store.

**Constants.** `REPORT_DIR = settings.verification_dir()` (`C:\Hangeul\BOT\data\verification`); `STORE_PATH = …\results.json`; `TEXT_DIR = …\text`; `LOCK_PATH = …\auto_verify.lock`; `LOCK_STALE_SECONDS = 4*3600`; `DOC_REPORT = …\DOCUMENT CHECK.xlsx`; `FIELD_REPORT = …\FIELD CHECK.xlsx`; `SKIP_PASSPORTS = {<head of branch's passport number>}` (the head of branch is not an applicant); `PROGRAM_ORDER = ["KLP","EAP","BACHELOR","MASTER"]`; `DEFAULT_BUDGET = 6`.

| Signature | Contract |
|---|---|
| `_pid_alive`, `_lock_held` | As in `auto_sync` (4 h stale) |
| `_hash(parts)`, `_file_parts(folder)` | sha1 of `"\|".join(["name:size:int(mtime)" for non-dot files])` |
| `doc_fingerprint(folder)` | Changes only when a document is added, replaced or resized |
| `field_fingerprint(folder, student)` | The files, plus `k=v` for every CSV field (sorted), plus `_issue=<cached issue date>` |
| `load_store() / save_store(store)` | `{"documents": {}, "fields": {}, "corrections": []}`. Saved atomically through `results.tmp` + replace. An unreadable store starts fresh (with a warning) |
| `pending(store, folders, portal) -> List[passport]` | Passports that have a folder and a portal record, are not skipped, and whose document **or** field fingerprint changed; oldest folder mtime first |
| `_text_cache_path(pas)` | `text\<PASSPORT>.json` |
| `install_text_cache(pas) -> handle` | Monkeypatches `dv.read_document`, `fc.read_document` and `dv.read_pages` with caching wrappers. Keys `"{name}:{size}:{int(mtime)}:{max_pages}"` → `{"text","sizes"}` and `"PAGES:{name}:{size}:{mtime}:{max_pages}"` → `{"pages","sideways"}` |
| `save_text_cache(handle)` | Writes the JSON and restores the originals |
| `_record_corrections(store, pas, program, name, previous, current) -> int` | For every field whose portal value changed since the last check, appends `{"noticed","student","passport","program","field","was","now","was_result","now_result","detail"}` |
| `check_one(pas, folder, student, store) -> (verdict, field_note, corrected)` | The document check only if the doc fingerprint changed (stores `{"fingerprint","checked","student","program","verdict","rows"}`); the field check only if the field fingerprint changed (stores `{"fingerprint","checked","student","program","rows"}`, note `"{m} matched, {d} differ"`) |
| `_cell(v)` | Strips control characters and caps at 32,000 (Excel refuses both) |
| `_style_header(ws)`, `_programs_in(section)` | A bold header frozen at A2; programs in `PROGRAM_ORDER` |
| `write_document_report(store, path=DOC_REPORT)` | See [07 §10.7](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md) |
| `write_field_report(store, path=FIELD_REPORT)` | Summary, per-program sheets and the `Corrections` sheet (newest first) |
| `write_reports(store) -> [Path, Path]` | Both |
| `run(budget=6, only=None, recheck=False) -> {"checked","waiting","skipped","store"}` | Lock (if held: prints the PID and returns an empty result). `recheck` blanks every fingerprint inside the lock, keeping findings and corrections. Queue = `only` or `pending`, capped at `budget`. Per student: `check_one`. **`NameError`, `AttributeError`, `ImportError` or `TypeError` → `RuntimeError` that stops the run** (a code fault must not produce a clean-looking report: a `NameError` in `check_bank` once skipped every bank check). Other exceptions skip the student. The store is saved after every student. The reports are rewritten when anything was checked or a report file is missing. **Returned shape** (`auto_verify.py:522-523`): `{"checked": [ {"student": <Full Name>, "passport": <passport no>, "program": dv.program_of(student), "verdict": "PASS"\|"REVIEW"\|"FAIL"\|"INCOMPLETE", "differs": <int, field rows with result DIFFERS>, "corrected": <int, portal fields changed since the last check>} ... ], "waiting": max(0, queued − checked) (int), "skipped": ["<name> (<passport>): <error>", ...], "store": <the results.json dict>}`. **Early return when the lock is held** (`:467`): `{"checked": [], "waiting": 0, "store": load_store()}`, with **no `skipped` key**, so consumers must use `.get("skipped", [])`. Consumers: `summary_lines(result)` (`:542`; reads `checked`, `waiting` and `store` via `_first_problem`) and `auto_sync.verify_docs()` (`auto_sync.py:324`), which since 41055de also hands the whole result (with `store`) to the Supabase copy, and `src\cloud\sheet_hooks.verify_batches` (`:266`), which reads only `checked` and `store`, both with `.get` (so the lock-held early return is safe there too) |
| `_first_problem(result, d)` | The first FAIL rule text (after `FAIL:`), or the first MISSING document, capped at 160 characters |
| `summary_lines(result)` | `🔍 Documents checked: N`, `   • {student} ({program}) — {VERDICT (why)}[, k field(s) differ from the portal][, k portal field(s) corrected since last check]`, `   N more waiting — they run on the next passes.`, `   Reports: DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx in {REPORT_DIR}` (the last line only when something failed) |
| `main()` | `--budget N` (0 = no limit), `--passport a,b`, `--pending`, `--rebuild`, `--recheck`, `--recheck-all` (deletes `results.json`). Reconfigures stdout to UTF-8 |

- **Callers:** `auto_sync.verify_docs`, `bootstrap.py` phase 5 (`--recheck --budget 0`), MIGRATION's batch loop (`--budget 5` until no "more waiting"), and `brief.read_document_check` (reads `results.json` for the 18:05 brief). Since 30 Sep also the Supabase copy, read-only: `src\cloud\sheet_hooks.verify_batches` (this run's result, `av.STORE_PATH`, `av.TEXT_DIR`) and `src\cloud\backfill.collect_results` / `collect_page_texts` (the whole `results.json` and every `text\<PASSPORT>.json`, matched to the file version now on disk by name, size and mtime). Neither writes to `data\verification\`. `auto_verify.py` itself is unchanged since 9dcd9ad.
- **History:** 4154aa5: paths from settings. 9dcd9ad: `_first_problem`, so FAIL/INCOMPLETE lines name the rule.
- **Operational rule:** close both .xlsx files before a run (Excel locks them and the write fails at the end: HANDOFF §7).

---

## 3. `tools\export_windows_ca.ps1` (41 lines)

Exports every certificate in `Cert:\LocalMachine\Root`, `CurrentUser\Root`, `LocalMachine\CA` and `CurrentUser\CA` (de-duplicated by thumbprint) as PEM to `data\windows-ca.pem`, and prints the count and size. Use it when Python fails with `CERTIFICATE_VERIFY_FAILED` but a browser works (antivirus or ISP TLS interception). `src\__init__.py` then sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `HTTPX_SSL_CERT_FILE` and `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to that file (`setdefault`) when it exists. The script's header comment has a one-liner that appends it to certifi's bundle. **On this PC `data\windows-ca.pem` does not exist**: HTTPS works without it (MIGRATION §5). Baseline only.

---

## 4. Root-level tracked files

### 4.1 Python entry point and scripts

None of the nine root scripts changed between `c17d887` and `8317741` (line counts and last commits below are still right). None of them publishes to Supabase: only the jobs and handlers under `src\` do, and `run.py` reaches the publish layer only through the scheduler and the command handlers it starts.

#### `run.py` (110 lines): the bot's single process
- If `sys.stdout` or `sys.stderr` is None (pythonw), redirects them to `hangeul_stdout.log` / `hangeul_stderr.log` (append, line-buffered, UTF-8); otherwise reconfigures them to UTF-8.
- Logging: `hangeul_bot.log` (FileHandler) plus stdout, level INFO, format `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. The httpx token-redaction filter comes from importing `src` (`src\__init__.py`).
- `async check_ollama_status()` prints one of three `rich` lines from `ollama_client.check_health()`.
- `async start_all()`: a banner Panel (mode LIVE/MOCK, API URL, whether the Telegram token is set, the model); `apply_telegram_dns_fix()` (`src\net_fix.py`); the Ollama check; `uvicorn.Config("src.api.main:app", host=settings.API_HOST, port=settings.API_PORT)`; `build_telegram_application()`. If there is an application: `async with app: start(); post_init(app); updater.start_polling(); await server.serve()`, then stop in `finally`. Otherwise only the API.
- `__main__`: `asyncio.run(start_all())`. KeyboardInterrupt or SystemExit → exit 0.
- Imports `uvicorn`, `rich` (**required**: its absence crashed start-up, found in the migration audit), `src.config`, `src.net_fix`, `src.bot.telegram_bot`, `src.llm.ollama_client`. Started by `start.bat` (console) or `start_background.vbs` (pythonw). History: 4154aa5 (`LOG_DIR` beside the file).

#### `bootstrap.py` (151 lines): cold start in phases
`run(label, args, why) -> bool` runs `[sys.executable, *args]` in the bot folder and prints `-> done` or `FAILED (exit n)` with the time. The `PHASES` keys and their functions (the function names are shifted by one against the labels; the printed labels are right):

| Key | Function | Command |
|---|---|---|
| 1 | `phase_1` | `-m src.sheets.progress_builder --all` |
| 2 | `phase_1b` | `-m src.sheets.passport_issue --refresh` |
| 3 | `phase_2` | `audit_program.py "<program>"` for "Korean Language Program (KLP)", "EAP (English for Academic Purpose)", "Bachelor's Degree", "Master's Degree" |
| 4 | `phase_3` | `-m src.sheets.verified_docs --local <DOCS_ROOT>` (without `--include-drive-done`: MIGRATION adds it by hand) |
| 5 | `phase_4` | `-m src.verify.auto_verify --recheck --budget 0` (MIGRATION replaces this with the batch loop) |
| 6 | `phase_5` | Prints the hand-over steps (start_background.vbs, install_autostart, install_watchdog) |

CLI: `--from N`, `--only N`, `--plan`. It stops at the first failed phase with `python bootstrap.py --from n`. `import src` first sets the CA bundle. **MIGRATION §8: do not run it unattended** (it only notices crashes, not phases that quietly did nothing), and run phase 2 before phase 1. History: 4154aa5 (DOCS from settings), 03ccf15 (the portal's own program names; "KLP"/"EAP" had matched nobody, so 214 + 29 students were skipped).

#### `audit_program.py` (232 lines): passport cross-check for one program (bootstrap phase 3)
- `SECTIONS = ["name","passport_no","dob","expiry","father_name","mother_name","address"]`. `WRONG_STATUSES = {MISMATCH, TYPO, DATE_MISMATCH, DISCREPANCY, PARTIAL_MATCH}`. `CHECK_STATUSES = {OCR_UNCERTAIN, NOT_READ}` ("check by eye", never counted as clean). `UNCHECKED_STATUSES = {PORTAL_UNREADABLE, OCR_UNAVAILABLE, ERROR}`.
- `async fetch_program_student_ids(program) -> [{"id","name","doc_filename"}]`: `admin_client.read_students({"prog": program})` (every page), then `scheduler.passport_scan(s)`.
- `classify(audit) -> {"scan": ok|none|unreadable|unchecked, "wrong","blank","not_on_scan","check","best_name"}`: `MISSING_DOCUMENT` → none; unchecked statuses → unchecked; `MRZ_UNREADABLE`/`SCAN_UNREADABLE`/`INVALID_DOCUMENT` or no fields → unreadable.
- `async main()`: for each student, `admin_client.audit_student_passport(id, {"name": …}, doc_filename)` (live EasyOCR + ICAO MRZ); prints `[ISSUE|CHECK|OK|NO-SCAN|UNCHECKD|UNREADBL]` lines and a TOTAL REPORT; writes `program_audit_<program>_<YYYYmmdd_HHMM>.csv` (utf-8-sig) in the current folder and opens it (`os.startfile`). **Exit 1** if the portal cannot be read or 0 students match (so bootstrap does not count an empty run as success).
- History: 03ccf15 (follows "Page X of N"), 344a247 (the shared reader; the new OCR statuses sorted honestly). The four CSVs from 27 Sep sit untracked in the bot folder and hold student data.

#### `download_passports.py` (51 lines)
Downloads every passport scan not yet saved into `passports\<uid>_<file>` (the folder is created at import). The list comes from `inspect_passports.passport_students(await admin_client.read_students())`; each scan is fetched with `admin_client.portal_get("view_doc.php?f=…", timeout=60)`. An HTML response (`<` first or `<html` in the first 1000 bytes) is never saved; ≤100 bytes is a failure. History: 344a247 (every page; a web page is never saved).

#### `inspect_passports.py` (55 lines)
`passport_students(records)` → `[{"id","name","surname","given_name","dob","passport_no","expiry","doc_url": "view_doc.php?f=<newest passport_ scan>"}]` for students with a scan. `list_students()` prints them all (read-only). It says "Couldn't read the portal: …" instead of an empty list. It is imported by `download_passports.py` and `tests\test_integration.py`. History: 344a247.

#### `get_consultations.py` (142 lines): **legacy, broken against today's portal**
It uses `login()` plus an unfiltered `GET consult_requests.php`, the **old fixed column positions** (`len(cols) >= 8`, received = `cols[6]`, status = `cols[7]`) and a substring date match. The portal moved to 7 named columns (cd0277a), so it now finds no rows. It prints a "CONSULTATION REQUESTS BRIEF" (totals, per-counsellor workload, by program, pending/no-answer lists). Kept from the baseline; the bot uses `parsers.consultation_view` and `client.read_consultation_day` instead. Do not copy it.

#### `compress_docs.py` (174 lines): **legacy one-off**
Walks a hard-coded `TARGET_DIR = r"E:\drive-download-20260917T042358Z-1-001"` and compresses PDFs (profiles (dpi, quality) 135/75 … 75/50, fewer profiles for >15 and >25 pages) and images (quality 85→30) to ≤1.95 MB **in place, with no backup**. Superseded by `verified_docs.shrink_large_files` (A4 ladder, original kept). Baseline only.

#### `test_system.py` (145 lines): legacy smoke script (not pytest)
Five `rich` "suites": settings; `parsers.extract_csrf_token` / `parse_tables` / `parse_dashboard_metrics` on sample HTML; `admin_client.login/get_dashboard/get_applications/get_inquiries/crawl_page("payments.php")` (meaningful only with `MOCK_MODE=true`: in live mode it logs in to the real portal); `ollama_client.check_health`, `_answer_query_fallback`, `answer_agent_query`; the FastAPI routes `/`, `/healthz`, `/api/dashboard/stats`, `/api/applications`, `/api/applications/inquiries`, `/api/auth/status` through `httpx.ASGITransport`. History: f8fefa4, 7f42ad0 (kept in step with removed functions).

#### `test_verified.py` (36 lines)
Prints today's payment-verified students with `admin_client.get_verified_students(target_date=local_today())` (every page). Uses `yearless_day_problem`. Exit 1 on a portal failure. History: 344a247 (it had read page 1 only, with substring dates and a `20,000.00 BDT` stand-in amount).

### 4.2 Byte-identical staging copies (`telegram_bot.py`, `config.py`, `progress_builder.py`)

Git blobs at `8317741`: `telegram_bot.py` = `src\bot\telegram_bot.py` (`cfc9358…`, was `c2d3dd9…` at `c17d887`), `config.py` = `src\config.py` (`8ca063f…`, was `2a2998a…`), `progress_builder.py` = `src\sheets\progress_builder.py` (`8bc8e0d…`, unchanged). **Why they exist:** the original workflow sent the owner fresh files to drop into the bot folder; `apply_bot_update.bat` copies `telegram_bot.py` → `src\bot\` and `config.py` → `src\`, and `install_sheets.bat` copies `progress_builder.py` → `src\sheets\`. **Rule kept through every commit (R24):** edit `src\…`, then copy to the root, and check with `cmp` (c5c1a7c, 4154aa5 and 344a247 say so explicitly). If they drift, the next `apply_bot_update.bat` would overwrite `src\` with an old copy. Since 36ae72e two tests enforce it: `tests\test_cloud.py:1126` and `tests\test_performance.py:1008` (`test_the_root_staging_copies_are_byte_identical`), and every build, merge and preflight of 29-30 Sep re-checked it with `cmp`. `apply_bot_update.bat` still checks only for `crosscheck_range` and `def authorized_ids` (§4.3); it knows nothing of `src\cloud\` or `src\bot\performance.py`, so it cannot deploy this release: deploy with git (`git merge --ff-only`) as was done on 30 Sep.

**`config.py` / `src\config.py` (147 lines).** `BOT_ROOT = Path(__file__).resolve().parent.parent`, `ENV_PATH = BOT_ROOT\.env`, `_folder(value, default)` (empty → default; a relative path counts from `BOT_ROOT`). `class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8", extra="ignore")`. A Windows environment variable of the same name overrides `.env`.

| Key | Default in code | Value on this PC (`.env`) |
|---|---|---|
| `MOCK_MODE` | `True` (a missing line means demo data) | `false` |
| `HANGEUL_BASE_URL` | `https://hangeul.com.bd/admin` | same |
| `HANGEUL_USERNAME` / `HANGEUL_PASSWORD` | dummy placeholders | value in `secrets/bot.env` (HANGEUL_USERNAME / HANGEUL_PASSWORD) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` (not localhost: IPv6 first cost 2 s per connection) | same |
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | same |
| `OLLAMA_NUM_CTX` | `3072` (one value for every call; a change reloads the model) | same |
| `TELEGRAM_BOT_TOKEN` | `""` | value in `secrets/bot.env` (TELEGRAM_BOT_TOKEN) |
| `TELEGRAM_ADMIN_CHAT_ID` | `""` (empty → the bot refuses everyone) | value in `secrets/bot.env` (TELEGRAM_ADMIN_CHAT_ID) (the owner's user id) |
| `TELEGRAM_AUTHORIZED_CHAT_IDS` | `""` | not set (only the admin is authorised) |
| `TELEGRAM_BRIEF_CHAT_IDS` | `""` (empty → `authorized_ids()`) | not set (so the sync and missing reports go to the admin) |
| `DAILY_REPORT_TIME` / `REPORT_TIMEZONE` | `18:05` / `Asia/Dhaka` | same |
| `ENABLE_SCHEDULED_REPORTS` | `True` (false turns off **every** job) | `true` |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | `""` | value in `secrets/bot.env` (GMAIL_ADDRESS / GMAIL_APP_PASSWORD) |
| `JENNIE_VOICE_ENABLED` / `JENNIE_VOICE_URL` / `JENNIE_SPOKEN_BRIEF` | `False` / `http://127.0.0.1:8765` / `True` | false / same / false (voice off since 28 Sep 17:08) |
| `BRAIN_ALWAYS_LOADED` / `BRAIN_IDLE_UNLOAD` | `False` / `"5m"` | defaults |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | same (whole network, no password: known and left as is) |
| `SUPABASE_URL` (36ae72e) | `""` | `https://dcbcbpwpmdtaanboetiz.supabase.co` (the Jeannie project; its `hg_*` tables are owned by the Jeannie repo `C:\Hangeul\JARVIS\Jeenie-saem-bot`, migrations in `supabase\migrations\`) |
| `SUPABASE_SECRET_KEY` (36ae72e) | `""` | value in `secrets/bot.env` (SUPABASE_SECRET_KEY): the project's **secret** key (`sb_secret_…`), never the publishable key. Never printed or logged: the `src\__init__.py` log filter (36ae72e) masks `sb_secret_…`, `sb_publishable_…`, `sbp_…`, JWT-shaped keys, and the values after `apikey:` / `Bearer` on the `httpx`, `httpcore.*` and `hangeul.cloud` loggers |
| `CLOUD_PUBLISH_ENABLED` (36ae72e) | `False` | `true` since 30 Sep 2026 22:27 (`.env` line 43). Publishing runs only when this **and** both keys above are set (`src\cloud\publish.py:103` `enabled()`). Write `true` or `false`: an **empty** value (`CLOUD_PUBLISH_ENABLED=`) makes pydantic raise a `ValidationError` when `Settings()` loads, and the bot does not start (found by the release preflight) |
| `CLOUD_EMBED_MODEL` / `CLOUD_EMBED_REVISION` (36ae72e) | `thenlper/gte-small` / `17e1f347d17fe144873b1201da91788898c639cd` | defaults (not in `.env`). Every vector in Supabase must come from this exact model and revision, the one Jeannie queries with. Once `data\cloud_state.json` records an `embed_model`, a process with another model publishes **nothing** (one log line) until the chunks are re-embedded (clear `hg_records` on the Jeannie side, then delete `data\cloud_state.json`): `src\cloud\publish.py:744-752`, 3caa393 |
| `SUPABASE_ACCESS_TOKEN` | not a setting | present in `.env` for the **Supabase CLI only** (value in `secrets/bot.env` (SUPABASE_ACCESS_TOKEN), an `sbp_…` personal token). `Settings` has `extra="ignore"`, so the bot never parses or echoes it |
| `DOCS_ROOT`, `DOCS_ORIGINALS_ROOT`, `KONYANG_ROOT`, `VERIFICATION_DIR` | `""` → `<parent of BOT>\VERIFIED STUDENT DOCUMENTS`, `…\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB`, `…\KONYANG DOCUMENTS`, `<BOT>\data\verification` | defaults |

Methods: `docs_root()`, `docs_originals_root()`, `konyang_root()`, `verification_dir()`, `authorized_ids() -> set` (the admin plus the extra IDs, split on `,`, `;` and spaces), `brief_recipient_ids() -> set` (`TELEGRAM_BRIEF_CHAT_IDS`, else `authorized_ids()`). The module-level `settings = Settings()`. History: 4154aa5 (paths), d7a5817 (Jennie keys), d9bbecc (model, `num_ctx`, 127.0.0.1), c17d887 (brain on demand), 36ae72e (the five Supabase/embedding keys; 12 lines). On this PC the voice is **off** (`JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false`) and the brain is loaded on demand (`BRAIN_ALWAYS_LOADED` default `False`).

**`telegram_bot.py` (2437 lines)** is mapped function by function with the bot's other modules in [03a](03a_FILES_src_bot.md); the commands are in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md). Index of its top-level names by line at `8317741`, grouped by feature:

| Feature | Names (line) |
|---|---|
| Access, start | `is_authorized` 22 (refuses everyone when no ID is configured: c5c1a7c), `start_command` 39 |
| Dates, report, brief, stats | `_DATE_FILLER_RE` 80, `normalize_date_input` 88, `parse_user_report_intent` 108, `report_command` 122, `brief_command` 163, `_fig` 187, `format_stats_report` 192, `stats_command` 233, `students_command` 247, `get_commands_cheatsheet_text` 279, `pin_command` 320 |
| Admitted | `admitted_command` 346, `ADMITTED_ROSTER_MAX` 375, `format_admitted_report` 378 |
| Inquiries | `INQUIRIES_LOG_MAX` 439, `_DONE_STATUSES` 440, `_bold_safe` 443, `_inquiry_who` 449, `format_inquiries_report` 464 (its day line is now headed `Consultations on <day>`, no longer `Performance on <day>`: 314afdb), `build_inquiries_report` 534, `_send_inquiries_report` 572, `DATE_PROMPT_KEY` 592, `_ask_date_again` 595, `inquiries_today_command` 607, `inquiries_date_command` 614, `consultations_command` 780, `inquiries_command` 784 |
| Verified | `verified_today_command` 650, `verified_date_command` 657, `format_verified_students_report` 798, `verified_command` 858 |
| Performance (bbd8f98, replaced by ce23535/314afdb) | `_send_performance_report` 718 (reads the portal's Consultant Performance page through `src\bot\performance.py`, then `cloud.publish(reads)` after the reply, not awaited), `performance_today_command` 742, `performance_month_command` 752, `performance_command` 762 (`/performance [today\|month]`); aliases `/perf_today`, `/perf_month`. Mapped in [03a](03a_FILES_src_bot.md) |
| Alerts, passports, calendar | `alerts_command` 788, `PASSPORTS_OCR_MAX` 915, `format_passports_report` 918, `passports_command` 969, `CALENDAR_UPCOMING_MAX` 1011, `format_calendar_report` 1014, `calendar_command` 1095 |
| E-mail (`/sendmail`) | `_send_gmail` 1148, `_find_student_for_email` 1174, `_find_student_in_export` 1187, `_find_student_on_list_page` 1229, `_pick_student_email` 1289, `_ai_write_email` 1312, `_handle_email_flow` 1354, `sendmail_command` 1472 |
| Cross-check | `_chunk_message` 1492, `CROSSCHECK_NAME_MAX` 1506, `_CROSSCHECK_WORDS_RE` 1510, `_crosscheck_query` 1517, `_stamp_guard` 1555, `_verified_between` 1571, `_stamp_minutes` 1588, `_crosscheck_card` 1597, `_audit_cards` 1621, `_NOT_OCR_CHECKED` 1653, `_ocr_checked` 1656, `_ocr_note` 1661, `_format_crosscheck_results` 1675, `_send_blocks` 1720, `build_crosscheck_report` 1745, `_crosscheck_run` 1803, `_parse_date_range` 1820, `crosscheck_range_command` 1854, `crosscheck_command` 1924, `crosscheck_today_command` 682, `crosscheck_date_command` 690 |
| Free text | `handle_natural_language_message` 1973 |
| Supabase hooks (2b6798f, e4d1cea) | Handlers keep what they read in a local `reads = {}` through `src.cloud.command_hooks.seen(reads, …)` and call `cloud.publish(reads)` after the reply (not awaited): `stats_command` 239-245, `students_command` 255-277 (page 1: partial), `admitted_command` 360-372, `build_inquiries_report` 535-568 / `_send_inquiries_report` 577-587, `_send_performance_report` 728-739, `verified_command` 901-912, `passports_command` 984-1008, `calendar_command` 1130-1135 (with words only), `_audit_cards` 1626-1648 (`cloud.audited`), `build_crosscheck_report` 1746-1755. Mapped in [03a](03a_FILES_src_bot.md) and [03d](03d_FILES_src_cloud.md) |
| Sheets menus (this scope) | `MISSING_PROGRAMS` 2172 (`[("KLP","🇰🇷 KLP"),("EAP","📘 EAP"),("BACHELOR","🎓 Bachelor's"),("MASTER","🎓 Master's")]`), `missing_command` 2180 (buttons `missing:{KEY}`), `missing_button` 2192, `_run_report_module` 2215, `_reply_long` 2243, `stage_command` 2249 (buttons `stage:{KEY}`), `stage_program_button` 2260 (JSON intakes → buttons `stagei:{KEY}\|{INTAKE}`, labelled `"{INTAKE} ({n})"` or `"⚠️ No intake set ({n})"`), `stage_intake_button` 2294 |
| Start-up | `post_init` 2314 (sets **13** menu commands: the 11 of `c17d887` plus `performance_today` and `performance_month`), `build_telegram_application` 2367 |

### 4.3 Windows launchers and installers (all CRLF, pinned by `.gitattributes`)

All of them locate their own folder (`%~dp0`, `WScript.ScriptFullName`, `$PSScriptRoot`) and use only `.venv\Scripts\python(w).exe`. If that interpreter is missing they fail visibly and **never fall back to another Python** (053efc5). The venv's `python.exe` is a redirector that starts the real `Python312` interpreter as a child with the same arguments; every process matcher counts both.

| File | Lines | What it does exactly |
|---|---|---|
| `start.bat` | 20 | `cd /d "%~dp0"`, title, then `"%~dp0.venv\Scripts\python.exe" run.py` in a console; `pause`. `:nopython` prints an error and exits 1 |
| `start_background.vbs` | 13 | `pythonw = botDir & "\.venv\Scripts\pythonw.exe"`. If it is missing, shows a `MsgBox` and quits with 1. Otherwise `WshShell.Run """" & pythonw & """ run.py", 0, False` (hidden, no wait). The target of the Startup shortcut and of the watchdog |
| `stop.bat` | 11 | One PowerShell pipeline over `Get-CimInstance Win32_Process`: venv python(w) with `\brun\.py\b` in the command line, plus their Python312 children, plus venv `-m src.*` jobs whose parent is `run.py` or gone, plus their children → `Stop-Process -Force`, printing `Stopped PID: n <cmdline>`. Never touches other Python processes. `stop.bat nopause` skips the pause. From PowerShell call it as `cmd /c "C:\Hangeul\BOT\stop.bat" nopause`. Since 30 Sep the same rules also catch any running Supabase publisher (`-m src.cloud.publish`, a child of `run.py` or of a job, or orphaned) and the hourly `-m src.cloud.full_picture`; a publisher stopped mid-run leaves its handoff file (pruned after 6 h, never re-sent) and the hash state advances only for the calls Supabase had already acknowledged, so the next read of that data sends whatever was not accepted |
| `check_status.bat` | 17 | The same matching, shown as a table (`ProcessId, ParentProcessId, Name, CommandLine`), then the last 25 lines of `hangeul_bot.log` |
| `watchdog.ps1` | 31 | Finds `run.py` under the venv (python.exe **or** pythonw.exe) plus children. Running → appends `yyyy-MM-dd HH:mm  running (pid a b)` to `hangeul_watchdog.log`, exit 0. Missing pythonw → a log line, exit 1. Otherwise logs `not running - starting it` and `Start-Process wscript.exe "<dir>\start_background.vbs" -WindowStyle Hidden`. **Seen on 30 Sep 2026 20:35** (a reboot): the Startup shortcut and the watchdog both started the bot, the second copy shut itself down (two start-up messages in Telegram), and Ollama was not up yet, so the start-up check said "Ollama not reachable". A grace period after boot (and a wait of up to 60 s for Ollama at start-up) was offered to the owner and is unanswered |
| `install_watchdog.bat` | 33 | `schtasks /Create /TN "HangeulBotWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"<dir>watchdog.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F`. The folder goes in through delayed expansion so no character in it can break the quoting; `/TR` must stay ≤261 characters. **Installed** on 27 Sep 2026: the task is `Ready`, a time trigger repeating every `PT5M` from 2026-09-27T11:46, user `User`, Interactive, `Limited`; last result 0 |
| `install_autostart.bat` | 22 | Creates `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HangeulBot.lnk` → `wscript.exe "<dir>\start_background.vbs"`, working folder `<dir>`, WindowStyle 7 (minimised). **Installed.** (The Startup folder also holds `Ollama.lnk` → `ollama app.exe`.) Both only run once someone signs in; BIOS "power on after AC loss" plus Windows auto sign-in covers power cuts |
| `apply_bot_update.bat` | 82 | 1) Takes `telegram_bot.py` and `config.py` from this folder, else the newest `telegram_bot*.py` / `config*.py` in `%USERPROFILE%\Downloads`; 2) `call stop.bat nopause`; 3) copies them into `src\bot\` and `src\`; 4) deletes `__pycache__` under the root and `src` only (not `.venv`); 5) checks with `findstr` that `crosscheck_range` is in the bot file and `def authorized_ids` is in the config, otherwise "UPDATE INCOMPLETE" and exit 1; 6) `start "" start.bat`. 053efc5 fixed an unescaped `)` that stopped it from ever reaching the start step, and unescaped `&` |
| `install_sheets.bat` | 47 | Creates `src\sheets\__init__.py`, copies `progress_builder.py` (from here or Downloads) into `src\sheets\`, and pip-installs `google-api-python-client google-auth-httplib2 google-auth-oauthlib` into the venv. From the first sheets roll-out; `requirements.txt` now pins these |
| `gauth.bat` | 27 | pip-installs the Google libraries, prints the sign-in instructions (the owner's Google account; "Advanced → Go to Hangeul Bot (unsafe)"; allow both screens), then runs `-m src.sheets.progress_builder --auth` |
| `build_sheets.bat` | 22 | `-m src.sheets.progress_builder --all` |
| `run_passport_audit.bat` | 28 | `audit_program.py "Bachelor's Degree"` (edit the name for another program); the CSV opens in Excel |

### 4.4 Packaging and configuration

- **`requirements.txt` (49 lines, last commit 36ae72e).** Pinned to what was proven in the Python 3.12 venv on 27 Sep 2026: `torch==2.11.0+cu128`, `torchvision==0.26.0+cu128` (**install first**, from `https://download.pytorch.org/whl/cu128`, or easyocr pulls PyPI's CPU-only torch); `easyocr==1.7.2`, `pymupdf==1.28.2`, `opencv-python-headless==5.0.0.93`, `pyzbar==0.1.9` (needs the MSVC++ x64 redistributable), `pillow==12.3.0`, `pypdf==6.19.0`, `openpyxl==3.1.5`; `httpx==0.28.1`, `beautifulsoup4==4.15.0`, `python-telegram-bot==22.8`, `apscheduler==3.11.3`, `tzdata==2026.4`, `fastapi==0.141.1`, `uvicorn==0.54.0`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`, `python-dotenv==1.2.3`, `rich==15.0.0`; **since 36ae72e, lines 38-44, the Supabase embeddings:** `sentence-transformers==6.1.0` and `transformers==5.17.0` (the two whose versions decide how the model loads: **transformers 5 loads gte-small as float16 unless `src\cloud\embed.py` asks for float32**, which it does; float16 on the CPU was about 7× slower); `google-api-python-client==2.200.0`, `google-auth-oauthlib==1.4.1`, `google-auth-httplib2==0.4.2`.
  - **How they were installed** (29 Sep 2026 09:19): `.venv\Scripts\python.exe -m pip install -c <freeze of the venv before> "sentence-transformers==6.1.0"`, i.e. with the old `pip freeze` as a **constraints file**, so nothing already installed (torch 2.11.0+cu128, numpy, …) could move; a before/after freeze diff showed only additions. It brought `transformers 5.17.0`, `huggingface_hub 1.33.0`, `tokenizers 0.23.2`, `safetensors 0.8.0`, `scikit-learn 1.9.1`, `hf-xet 1.6.0`, `joblib 1.6.0`, `regex 2026.9.29`, `threadpoolctl 3.7.0`, `tqdm 4.70.1`, `typer 0.27.2`, `cloudpickle 3.1.2`, `narwhals 2.26.0`, `shellingham 1.5.4`. Copy that method for any addition to this venv.
  - **The model** `thenlper/gte-small` at revision `17e1f347d17fe144873b1201da91788898c639cd` (MIT, about 68 MB, 384 dimensions, mean pooling, normalised) sits in the Hugging Face cache `~\.cache\huggingface` (`hub\models--thenlper--gte-small\snapshots\<revision>`). It is downloaded once; every process that embeds runs with `HF_HUB_OFFLINE=1` and `CUDA_VISIBLE_DEVICES=-1` (CPU only, so the GPU stays with OCR and Ollama).
  - **Not listed but installed:** `pytest 9.1.1` (for `tests\`).
- **`.env.example` (144 lines, last commit 36ae72e).** A documented template of every key `src\config.py` reads (defaults as in the table above). It also notes that `TELEGRAM_DNS_FIX` and `TELEGRAM_API_IP` (`src\net_fix.py`) and the CA-bundle variables are read **only from the Windows environment**, and that paths must be written without quotes. Since 36ae72e it has a Supabase block (lines 106-118): `SUPABASE_URL=`, `SUPABASE_SECRET_KEY=`, `CLOUD_PUBLISH_ENABLED=false` and the commented `#CLOUD_EMBED_MODEL=` / `#CLOUD_EMBED_REVISION=`, with the notes that publishing runs only when all three are set, that a Supabase failure is one log line and never delays Drive, Sheets or Telegram, that the key is the secret key (`sb_secret_…`) and never the publishable one, and that the CLI's personal access token is not read by the bot. It has no real secrets. History: 4154aa5, d7a5817, d9bbecc, 36ae72e.
- **`.gitignore` (60 lines, unchanged since 366dec0).** Secrets (`.env`, `.env.*` except the example, `token.json`, `credentials.json`, `credentials.json.json`, `*.key`, `*.pem`); student data (`data/`, `passports/`, `passports_001/`, `*.csv`, `*.xlsx`, `*.xls`, `*.zip`, `VERIFIED STUDENT DOCUMENTS/`, `KONYANG DOCUMENTS/`, `**/verification/`, `**/text/`); logs (`*.log`); Python (`__pycache__/`, `.venv/`, …); editors; reports that quote students (`bachelor_portal_audit.md`, `run_one_student.py`, `*_audit_*.md`). `data/` already covers every Supabase file the bot writes (`data\cloud_state.json`, `data\cloud\…`, dry-run payloads), so no new line was needed.
- **`.gitattributes` (6 lines, 053efc5).** `*.bat`, `*.cmd`, `*.vbs` and `*.ps1` → `text eol=crlf`. With LF only, cmd.exe misreads `goto` labels.

### 4.5 Documentation (history carriers; all pre-date parts of HEAD)

None of these files changed between `c17d887` and `8317741`: none mentions Supabase, `src\cloud\`, the performance commands or the 13-entry menu. This pack is the only written description of them.

| File | Status | Contents, and what is now stale |
|---|---|---|
| `README.md` (118) | Baseline, **stale** | The original "Website-to-API + qwen2.5:7b + Telegram" description, the tree, quick start. Stale: `e:\BOT`, Python311, qwen2.5:7b, and "if the admin chat ID is empty the first user who sends /start is authorised" (now false) |
| `HANDOFF.md` (310) | Baseline (25 Sep 2026, old PC) | The architecture, the 15-minute cycle, how a document is checked, known problems (§5.1: four false-FAIL rules), lessons (§6), how to run it (§7). It quotes real student names: never copy it verbatim into another product. Stale: E: paths, Python 3.11, "watchdog not installed", its counts |
| `MIGRATION.md` (249) | Rewritten in b0245df (27 Sep 2026) | The move that actually happened: paths, venv and torch first, Ollama, the HTTPS check, Google sign-in (the OAuth app is In production), the three `.env` checks, cold start phases 2-1-3-4-5 with real timings, the batch loop, autostart and watchdog, retiring the old PC, the schedule, and a table of what was fixed or knowingly left |
| `PC_BUILD.md` (201) | Baseline (26 Sep 2026) | A hardware purchase proposal (i7-14700 / RTX 5080 builds with Star Tech prices, an AMD alternative). **Not what was bought:** the target PC is a Ryzen 5 8600G + RTX 5060 8 GB with a single C: drive, and its "split topology" was rejected |
| `.agents\rules\hangeul_operational_guardrails.md` (43) | Baseline | Rules 1–7: read-only portal; never add pending payments and window applications together; verified-student audit fields; the 45-day calendar; live audits only; `students.php` only, never `signed_students.php`; no AI features and no buttons on the portal |

### 4.6 `test_passport.jpg`
A tracked 1248×1800 JPEG (382,243 bytes, baseline). **Nothing in the code or tests references it.** It is a passport-style image: treat it as personal data and do not open or reuse it.

---

## 5. Generated, untracked files in the bot folder (what exists at run time)

| Path | Written by | Contents |
|---|---|---|
| `.env`, `credentials.json`, `token.json` | the owner; `--auth` | Secrets. Copies in `secrets\` (`bot.env`, `credentials.json`, `token.json`) |
| `data\sheet_state.json` | `auto_sync` | `{"sheets": {"PROG\|INTAKE": {rowkey: {"name","hash","rec"}}}, "failures": {}}`, about 375 KB, 7 sheets (30 Sep) |
| `data\auto_sync.lock`, `data\verification\auto_verify.lock` | the jobs | The PID of the running job. The Supabase backfill and the hourly full picture also read `data\auto_sync.lock` (`src\cloud\backfill.py` `quiet_reason`, with `auto_sync._pid_alive`) and do not start while a live sync holds it |
| `data\passport_issue.json` | `passport_issue` | `{"by_passport": {…}}` (282 entries on 30 Sep) |
| `data\missing_reports\missing_information_YYYY-MM-DD.xlsx` | `missing_report` | The daily Excel file (the newest one is what the backfill publishes as `report missing_report\|<day>`) |
| `data\verification\results.json` | `auto_verify` | 1.8 MB: 158 `documents`, 158 `fields`, 0 `corrections` (30 Sep) |
| `data\verification\text\<PASSPORT>.json` | `auto_verify` | 158 OCR text caches (the source of the `doc_page_text` records) |
| `data\verification\DOCUMENT CHECK.xlsx`, `FIELD CHECK.xlsx` | `auto_verify` | The two reports |
| `data\alerted_passport_issues.json` | the passport watcher | `{"version": 2, "scans": {…}}` (311 scans on 30 Sep) |
| `data\cloud_state.json` | `src.cloud.publish` | The Supabase hash state (D9: only changed rows are ever sent): `{"version": 1, "embed_model": "thenlper/gte-small@17e1f347…", "records": {"<kind>\|<key>": {"h","s","t"}}, "scopes": {…}, "reads": {…}}`; about 2.2 MB with 13,543 records at 23:28 on 30 Sep. Created by the real backfill (30 Sep 21:48-22:05). Deleting it makes the next publish send everything again. Details in [03d](03d_FILES_src_cloud.md) / [13](13_SUPABASE_PUBLISHING.md) |
| `data\cloud\pending\` | `src.cloud.handoff` | Handoff files `<YYYYmmdd-HHMMSS-ffffff>-<job>.json` waiting for their publisher; normally empty (each publisher deletes its file; files over 6 h old are pruned) |
| `data\cloud\publish.lock`, `data\cloud\student_index.json`, `data\cloud\backfill_20260930.log` | `src.cloud` | One publisher at a time (empty lock file); `{passport: (uid, HNG id)}` for the passport-keyed kinds (15 KB); the one-time backfill's console log (counts only, 3.3 KB, ends `Done in 1025 s; 0 read(s) failed.`) |
| `data\jennie_fillers\` | `voice.py` | 7 filler clips (voice is off) |
| `passports\` | the watcher, `download_passports.py` | 378 scans on 30 Sep. Never open them |
| `program_audit_*.csv` (4) | `audit_program.py` | Phase 3 results (student data) |
| `hangeul_bot.log`, `hangeul_stdout.log`, `hangeul_stderr.log`, `hangeul_sync.log`, `hangeul_watchdog.log` | `run.py`, `_run_module`, `watchdog.ps1`, the Supabase publishers | Logs. Bot tokens are redacted by the `src\__init__.py` filter since 0fce479 and e205327, and Supabase keys, `sbp_` tokens, JWTs and `apikey:`/`Bearer` values since 36ae72e. Every publisher appends its one summary line (`Supabase publish (<job>): ok, …`) to `hangeul_sync.log` |
| `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\<PROGRAM>\<NAME (PASSPORT)>\` | `verified_docs` | 160 folders on 30 Sep (KLP 106, Bachelor's 37, EAP 9, Master's 8), each with a `.download_complete` marker |
| `C:\Hangeul\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\` | `shrink_large_files` | Originals of the shrunk files |

---

## 6. Call graph of this scope

```
scheduler._run_module ──► auto_sync.run_once
                            ├─ sync_sheets ─► progress_builder.{all_targets, target, columns_for, fetch_roster, build_row,
                            │                                   sheet_drift, build_target, sheet_title}
                            │                 └─ fetch_all_students ─► scraper.client.admin_client (GET students.php?export=csv)
                            ├─ sync_docs ───► verified_docs.run_local ─► client.read_student_pages / GET download_docs.php
                            │                                           └─ shrink_large_files
                            ├─ notify ──────► Telegram sendMessage (httpx), replies.split_text
                            ├─ verify_docs ─► auto_verify.run ─► doc_verifier.{student_folders, portal_students, verify_student,
                            │                                                   student_verdict} ─► page_checks, rules
                            │                                 └─ field_check.check_student ─► passport_issue.load
                            └─ (publishing on) sheet_hooks.after_sync ─► records.* ─► handoff.submit ─► [python -m src.cloud.publish]
scheduler._run_module ──► passport_issue.refresh ─► client.read_students, GET student_edit.php
                            └─ (publishing on) sheet_hooks.after_issue_refresh ─► HangeulAdminClient._profile_fields, records.* ─► handoff.submit
scheduler._run_module ──► missing_report.main ─► read_sheets (Sheets API) + portal_index (CSV) ─► write_excel, send
                            └─ (publishing on) sheet_hooks.after_missing_daily | after_missing_failed ─► handoff.submit
telegram_bot._run_report_module ─► missing_report --program | stage_report --program [--intake]
                            └─ (publishing on) sheet_hooks.after_missing_program | after_stage ─► handoff.submit
brief.read_document_check ─► data\verification\results.json
src.cloud.backfill ─► verified_docs.fetch_verified_students, stage_report.read_progress, auto_sync._pid_alive
                       (backfill.quiet_reason: quiet windows + a live data\auto_sync.lock; full_picture.skip_reason calls it)
src.cloud.records  ─► auto_sync._row_key, progress_builder.normalize_phone, passport_issue.passport_key  (reuse only; see 03d)
```

---

## 7. The `tests\` folder (index)

So that every tracked path appears in a file map, the 24 pytest files and `conftest.py` are indexed here. What each one pins, the fakes they share and how to run them are in [10 §1-§3](10_TESTS_AND_VERIFICATION.md); counts are the collected tests at `8317741` (**1152 in all**; `1152 passed in 54.70s` in a clean `git archive` copy on 30 Sep 2026; in the live checkout, which has a `.env`, 2 of them skip by design: [10 §1](10_TESTS_AND_VERIFICATION.md)).

| File | Lines | Tests | Added in | Subject | Details |
|---|---|---|---|---|---|
| `tests\conftest.py` | 29 | 0 | 36ae72e | Puts the bot folder on `sys.path`, registers the `slow` marker, and an autouse fixture that switches Supabase publishing **off** for every test whatever `.env` says | [10 §1, §2.4](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_performance.py` | 1064 | 225 | bbd8f98 (rewritten ce23535, 314afdb) | `/performance_today`, `/performance_month` and their aliases and free-text routes: the portal's Consultant Performance page only (`consult_performance.php?period=today\|month`) | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_foundation.py` | 787 | 102 | e0d47ab | Strict dates, long replies, the one portal session, the all-pages students reader, `/verified*`, `/admitted`, `/students`; defines the shared fakes (`portal`, `pin_today`, `row()`, `page()`, `Chat`, `Message`, `run`) | [10 §2.1-2.2, §2.5, §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_freetext.py` | 686 | 107 | 7f42ad0 | Free-text routing (`ask.py`), live answers, `/calendar` words, the LLM's fact pick, Jennie's spoken checks | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_voice_fast.py` | 872 | 105 | d9bbecc | Fast Jennie: filler clip, one-call routing, memory, one-sentence reply, number checks, Ollama options, warm-up | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_brief.py` | 1053 | 90 | f8fefa4 | The factual 18:05 brief, its readers and `claims_problem` | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_crosscheck.py` | 654 | 72 | 40da0e6 | `/crosscheck*`, `/passports`, the MRZ/OCR validator with a stub OCR engine | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_jobs.py` | 849 | 42 | 9dcd9ad | Passport watcher, portal sync, `/stage`, `/missing`, passport issue dates, verified-docs download | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_inquiries.py` | 343 | 36 | 46cdf03 | `/inquiries_today`, `/inquiries_date`, `/consultations`, `/inquiries` and their free-text routes | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_voice.py` | 698 | 29 | d7a5817 | Jennie's voice path against a fake voice service (fakes reused by 3 other files) | [10 §2.3, §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_repair_voice.py` | 120 | 22 | e164679 | Jennie: impossible spoken dates, failed reads worded in code | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_repair.py` | 498 | 19 | e164679 | The verifiers' repair list: date re-ask, `/admitted` university cell, paid vs verified income, OCR claims, calendar ranges, sync edits, missing-report failure | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_watcher_nonblocking.py` | 483 | 10 | 7241465 | The 30-minute watcher's OCR runs off the event loop | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_integration.py` | 153 | 9 | 344a247 | What the merge of the fix branches put right: `/alerts`, `/stats`, the `/sendmail` lookup, prompts, root scripts (imports the fakes from `test_foundation`) | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_consultations.py` | 138 | 8 | cd0277a | `consult_requests.php` read by column name | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_final_fixes.py` | 96 | 8 | c17d887 | The last cases re-verification found partly wrong, and the brain on demand | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud.py` | 1129 | 61 | 36ae72e | The Supabase publish layer: records, content hash, only-changed rows, deletes by key list, 200-row calls, failures, `hg_runs`, dry run, handoff, backfill, embedder, secrets; defines `FakeSupabase` and the `cloud` fixture | [10 §2.4, §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_commands.py` | 538 | 38 | 2b6798f | What the command handlers and free-text answers publish, after the reply | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_bot_jobs.py` | 689 | 33 | 5048a07 | The watcher's, the 18:05 brief's and the hourly full picture's publishing | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_fixes.py` | 544 | 32 | 3caa393 | One block per finding of the three code reviewers of 29 Sep | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_cf_email.py` | 375 | 28 | 9ead47d | Cloudflare's hidden e-mails decoded on every page parse; one log line for a missing model | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_performance.py` | 349 | 27 | e4d1cea | The `consultant_performance` kind: records, scope `<period>\|<first ISO day>`, completeness, the commands' and full picture's publishing | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_jobs.py` | 726 | 26 | 41055de | **This scope's hooks**: the four sheet jobs' hand-over (§1.8) | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_dry_run.py` | 390 | 17 | 752cd53 | The first dry run's findings: portal filler words, one log line, `CUDA_VISIBLE_DEVICES=-1`, the 1 MB body cap | [10 §3](10_TESTS_AND_VERIFICATION.md) |
| `tests\test_cloud_all.py` | 157 | 6 | cb16394 | Where the hook branches meet: one tile record, audits that survive the watcher, job names, the hourly job registered once | [10 §3](10_TESTS_AND_VERIFICATION.md) |

None of these files reaches the portal, Telegram, Google, SMTP, Ollama, the voice service or a real Supabase (Supabase is `FakeSupabase` on `httpx.MockTransport`); `pytest` itself is not in `requirements.txt` (install it separately, [02 §3.2](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)). The root `test_system.py` and `test_verified.py` are not pytest files (§4.1).
