# 12 — Adaptation map: what to change for another agency

**What's in this file:** every constant, string and rule in Hangeul BOT that is specific to this agency, its admin portal, Bangladesh or this PC, with its `path:line` at `8317741`, the Hangeul value, and what a new agency must supply instead: the portal (including the Consultant Performance page and the Cloudflare decoding), the pipeline words, branding, Google, identity heuristics, document rules, operations, and the Supabase publish layer (the project ref, the schema owner, the kinds, the filler words, the embedding model). Then the parts that are generic and can be copied as they are.
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), at `main` = `8317741` (first written 29 Sep 2026 at `c17d887`); every line number below was re-checked against the code at `8317741`.
**Read with:** [00 Index](00_INDEX.md) (§4.1 reading order), [09 Blueprint rules](09_BLUEPRINT_RULES_AND_LESSONS.md) (Part C rebuild order, Part D points here), [04 Portal](04_PORTAL_INTEGRATION.md) (§8 portal survey checklist), [02 Environment](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md) (§3.5 Google from zero, §3.11 Supabase set-up), [07 Sheets and document check](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), [13 Supabase publishing](13_SUPABASE_PUBLISHING.md), the file maps [03a](03a_FILES_src_bot.md), [03b](03b_FILES_src_scraper_llm_api_config.md), [03c](03c_FILES_sheets_verify_root_scripts.md), [03d](03d_FILES_src_cloud.md).

Secrets are never shown ("value in secrets/bot.env (KEY_NAME)"); Google ids are masked (they are identifiers, not secrets, but they point at student data). The Supabase project ref and URL are not secrets and are shown. **Recommendation throughout:** a new bot should read every agency-specific value from `.env` or one `agency.py`/`agency.yaml` file, never from literals scattered over 20 modules as here.

---

## 1. The portal (what the scraper assumes)

Derive the new portal's equivalents with the survey checklist in [04 §8](04_PORTAL_INTEGRATION.md) before touching these (including items 11-12: a CDN that rewrites content, and a page that shows a default view for a parameter it does not take).

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| Portal root | `src\config.py:24` (`HANGEUL_BASE_URL`), `.env` | `https://hangeul.com.bd/admin` | its admin URL (key name can stay generic, e.g. `PORTAL_BASE_URL`) |
| Login | `src\scraper\client.py:150` `login()` (the one POST, `:184`; [03b §3.5](03b_FILES_src_scraper_llm_api_config.md)) | GET `login.php`, hidden `_csrf`, POST `username`/`password`/`_csrf`; success = final URL not `login.php` | its form fields, CSRF field name, and how an expired session shows |
| Page size | `client.py:44` `STUDENTS_PER_PAGE` | `50` | its list page size (a full first page with no pager is treated as a layout error) |
| Page cap | `client.py:45` `MAX_STUDENT_PAGES` | `40` | a cap above its real page count |
| Consultation list cap | `client.py:52` `CONSULT_LIST_LIMIT` | `500` (the newest 500 requests) | its list cap, if any; use the portal's own counters for totals |
| Totals view | `client.py:53` `CONSULT_TOTALS_VIEW` | `{"status": "file_opened"}` (the lightest tab whose status tabs count every request) | its cheapest view that still shows all counters |
| Page paths | `client.py` readers, [04 §3](04_PORTAL_INTEGRATION.md) | `login.php`, `index.php`, `students.php` (+ `?pg=N`, `?status=pending`, `?export=csv`, `?source=direct&filter_docs=verified`), `student_edit.php?id=N`, `view_doc.php?f=`, `consult_requests.php`, `calendar.php`, `window_applications.php?status=under_review`, `progress.php?uid=N`, `download_docs.php?uid=N&zip=1`, `consult_performance.php?period=` | its pages, one reader each |
| Performance page | `client.py:57-58` `PERFORMANCE_PAGE = "consult_performance.php"`, `PERFORMANCE_PERIODS = {"today": "Today", "month": "This Month"}`; `client.py:425-452` `read_consult_performance` (refuses a page whose open tab or "Showing" label is another period) | Leads › Performance ("Consultant Performance"), periods `today` and `month` only (the page also has This Week, All Time and a Custom range form, never used) | its own staff-performance page, if any, and its period parameter; if it has none, drop the feature rather than compute one (09 R40) |
| Performance layout | `src\scraper\parsers.py:955` `PerformanceLayoutError`, `:963` `_PERF_COLUMNS` (rank, name by `consultant`/`counsellor`/`staff`/`name`, score, conversion, files opened, consultancies, points, docs ready), `:976` `_PERF_SHAPES`, `:988` `_PERF_TOP_METRICS`, `:1088` `parse_consult_performance` (`nav.pf-tabs a.on`, `p.pf-showing`, `div.pf-stats > div.pf-stat`, `section.pf-top`, `table.tbl.pf`, `tr.pf-empty-row > .pf-empty`) | the portal's own class names and header words | its selectors and column words ([04 §3.10](04_PORTAL_INTEGRATION.md)) |
| Performance reply | `src\bot\performance.py:47` `_TILE_EMOJI`, `:49` `_TILE_COLUMN`, `:50` `_TOP_FIGURES`, `:51` `_RANGE_START_RE`; `:218` `format_consult_performance` | tiles "Consultancies done", "Files opened", "Conversion (file open)", "Docs ready"; the range line "01 Sep – 30 Sep 2026" | its tile words and range format |
| Performance words (free text) | `src\bot\ask.py:103` `_PERFORMANCE_WORDS` | `perform[ae]nces?\|perfom[ae]nces?\|performaces?\|perfromances?\|preformances?\|productivity\|leader[\s-]?boards?\|performers?` (English, with the owner's own misspellings) | its owner's words and spellings |
| CDN rewriting | `parsers.py:19-20` `_CF_CLASS = "__cf_email__"`, `_CF_LINK = "/cdn-cgi/l/email-protection#"`; `:24` `_cf_address`; `:64` `decode_cf_emails`; `:327-328` `_EMAIL_HIDDEN_RE`, `_EMAIL_HIDDEN_GAP_RE` | the portal is served through Cloudflare with e-mail obfuscation on | keep the decoder and its wrapped-soup test if its portal is behind Cloudflare (it is harmless otherwise); add a decoder for any other rewrite its CDN makes (09 R28) |
| Dashboard tiles | `parsers.py:217` `_DASHBOARD_TILES` | summary key → (tile label, link part), e.g. `"pending_payment": ("Pending payment", "students.php")`, `"window_apps_under_review": ("Under review", "window_applications")` | its tile labels and links |
| Dashboard cards | `src\bot\ask.py:671` `_CARDS` | `"At a glance", "Needs attention", "Application pipeline", "Applications by program", "Top universities"` | its card titles (also in §8's `DASHBOARD_GROUPS`) |
| Student list columns | `parsers.py:321-324` `_STUDENT_COLUMNS`, `_REQUIRED_STUDENT_COLUMNS` | found by header words `sl`, `student`, `universit`, `program`, `doc`, `payment`, `stage`; required: `sl`, `student`, `program`, `stage` | its header words and which are required |
| Pager | `parsers.py:325` `_PAGER_RE` | `Page X of N · T students` | its pager text |
| Agency student id | `parsers.py:330` `_HNG_RE` | `HNG-\d{4}-\d+` (blank until payment is verified) | its id format |
| "Admitted" stage | `parsers.py:317` `ADMITTED_STAGE` | `"Admitted / Completed"` | the stage its dashboard counts as admitted |
| Payment stamp and amounts | `parsers.py:331-334` `_STAMP_TEXT`, `_VERIFIED_BY_RE`, `_PAID_RE`, `_INCOME_RE` | `Payment verified by <name> · 27 Sep, 17:19` (no year), `Paid: <n> BDT <method>`, `Verified income: <n> BDT` | its stamp wording and currency (see §7) |
| Consultation statuses | `parsers.py:642` `CONSULT_STATUSES` | `"New", "No Answer", "Wrong Number", "Consulted", "File Opened"` | its lead/inquiry statuses |
| Calendar | `parsers.py:1211-1217` `_CAL_RANGE_RE`, `_CAL_TIME_RE`, `_CAL_TIME_END_RE`, `_CAL_PROGRESS_RE`, `_CAL_EMPTY_RE`, `_CAL_PROGRAM_RE` | `27 Sep[ 2026][ – 30 Sep]`, `N% / days left`, empty words, program words `klp\|eap\|bachelor\|master\|degree\|language\|phd\|diploma` | its calendar layout and words |
| Upload file names | `client.audit_student_passport` (`client.py:630`), the watcher (`scheduler.py:36` `_UPLOAD_TIME_RE`, `:74` `passport_scan`; the same rule in `src\cloud\bot_jobs.py:249`) | `passport_<uid>_<unixtime>.<ext>` (the epoch dates the upload) | its naming, or another way to date an upload |
| CSV export columns | `students.php?export=csv`, [04 §3.3](04_PORTAL_INTEGRATION.md) | 63 columns (`Source` … `Applied On`) | its export's columns; the sheets, reports and the `student_export` kind map them by header name |
| Read-only guardrails | `.agents\rules\hangeul_operational_guardrails.md` | 7 rules (GET only, never add pending payments to window applications, …) | its own owner-written rules |

## 2. The pipeline vocabulary (programs, stages, statuses)

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| Program words (free text) | `src\bot\ask.py:164-168` `_PROGRAM_KEYS`, `:169` `_PROGRAM_NAMES` | `klp` (`korean language`, `language program`), `eap` (`english for academic`), `bachelor` (`undergrad`), `master` (`postgrad`), `phd` (`doctorate`) | its programs and the words staff use for them |
| Stage names (free text) | `ask.py:171-173` `_STAGES`, `:176-177` `_STAGE_ONLY` | `Application Received`, `Payment Verified`, `Documents Under Review`, `Documents Verified`, `University Applied`, `Admission & Tuition`, `VIN Application`, `Embassy Submission`, `Visa Result`, `Admitted / Completed` | its stage pipeline |
| Stage order (`/stage`) | `src\sheets\stage_report.py:33-37` `STAGE_ORDER` | the ten above plus `Accepted` | the same list, in its order |
| Consultation statuses (brief) | `src\bot\brief.py:61-62` `DONE`, `KNOWN_STATUSES` | done = `Consulted`, `File Opened`; known = those + `New`, `No Answer`, `Wrong Number` | its statuses, and which count as "done" |
| Brief fact wording | `brief.py:126-360` (the section builders `section_consultations` `:141` … `section_documents` `:345`; [03a §4.3](03a_FILES_src_bot.md)) | e.g. `Consultation requests received today: N`, `Students whose payment was verified today: N` | the same pattern with its own subjects; the claim checker only accepts these words |
| Brief summary rules | `brief.py:364-375` `_SUMMARY_SYSTEM`, `:376` `_OFF_TOPIC_RE` | never mention `visas`, `passports`, `intakes`, `conversion`; pending payments and window applications never combined | its own "never report" subjects and "never add together" pairs |
| `/missing` buttons | `src\bot\telegram_bot.py:2172-2177` `MISSING_PROGRAMS` | `("KLP", "🇰🇷 KLP")`, `("EAP", "📘 EAP")`, `("BACHELOR", "🎓 Bachelor's")`, `("MASTER", "🎓 Master's")` | its programs |
| Program list (documents) | `src\verify\rules.py:16` `PROGRAMS`, `src\verify\auto_verify.py:58` `PROGRAM_ORDER` | `KLP`, `EAP`, `BACHELOR`, `MASTER` | its programs |
| Cold-start program names | `bootstrap.py` `phase_2` | `"Korean Language Program (KLP)"`, `"EAP (English for Academic Purpose)"`, `"Bachelor's Degree"`, `"Master's Degree"` (the portal's own spelling; "KLP" alone matched no student) | the portal's exact program names |

## 3. Branding and identity strings

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| LLM system prompt (typed questions) | `src\llm\prompts.py:7` `SYSTEM_AGENT_CHAT` | "You help the office of Hangeul Korean Language & Visa (a study-in-Korea agency in Dhaka) …" | agency name, what it does, city |
| Welcome text | `telegram_bot.py:39-76` `start_command` (heading at `:52`) | `👋 *Welcome to Hangeul Admin Operational AI Bot!*` + the command list | its bot name and commands |
| Pinned cheat-sheet | `telegram_bot.py:279-318` `get_commands_cheatsheet_text` | the Hangeul command list | its commands |
| Menu | `telegram_bot.py:2316-2330` (13 `BotCommand`s in `post_init`) | 11 command descriptions plus the two performance entries ("Today: the portal's Consultant Performance page: tiles, top performer, leaderboard") | its commands and wording ([05 §3.1](05_TELEGRAM_COMMANDS_AND_JOBS.md)) |
| Reply headings | e.g. `telegram_bot.py:196` `📊 *Hangeul Admin Quick Stats*`, `:407` `🎓 *Hangeul Portal — Admitted Students*`, `:1027`/`:1063` `📅 *Hangeul Admin Calendar & Deadlines*`; brief header `📋 *HANGEUL DAILY BRIEF*` (`brief.py:632`) | "Hangeul" | its name (one constant) |
| E-mail identity | `telegram_bot.py:1318-1320` (system prompt: "on behalf of `<manager name>`, Manager at Hangeul Korean Language and Visa (HKLV) in Dhaka", sign-off `<manager name>` / `Manager, HKLV`), `:1324` ("a student at HKLV"), `:1350` (fallback template sign-off) | the manager's real name, hard-coded | **new `.env` keys**, e.g. `EMAIL_SIGNOFF_NAME`, `EMAIL_SIGNOFF_TITLE`, `AGENCY_SHORT_NAME`; build both strings from them ([06 §2.3](06_LLM_AND_JENNIE_VOICE.md)) |
| Gmail sender | `.env` `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (value in secrets/bot.env) | the agency Gmail | its own account and app password ([02 §3.6](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |
| Voice persona | `src\bot\voice.py:385` `_ROUTER_SYSTEM` ("the voice assistant of the Telegram bot of Hangeul Korean Language & Visa, a study-in-Korea agency in Dhaka … Korean or English"), `:773-830` `_CUTE_EN`, `_FACT_RULES`, `_REPLY_SYSTEM_EN`, `_REPLY_SYSTEM_KO`, `_BRIEF_SYSTEM_EN` (`voice.py` unchanged since `e164679`) | "Jennie", cute (애교) style, English + Korean | persona name, languages, style; the reference voice must be synthetic or consented ([06 §5](06_LLM_AND_JENNIE_VOICE.md)) |
| Watcher alert footer | `src\bot\scheduler.py:40` `_ALERT_FOOTER` | `_(Strict Read-Only Alert: Please update in admin portal manually if required)_` | its wording |
| Bot account | BotFather | `@the_Jennie_bot`, token value in secrets/bot.env (TELEGRAM_BOT_TOKEN) | **its own bot and token** (one bot per token, [02 §5.5](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |
| Admin chat | `.env` `TELEGRAM_ADMIN_CHAT_ID` | value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID) (the owner's own Telegram user id) | its admin's Telegram user id |

## 4. Google (Sheets and Drive)

Set up from zero with [02 §3.5 "Google from zero"](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md). `progress_builder.py` is unchanged since `c17d887`.

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| OAuth client | `credentials.json` (`progress_builder.py:46`) | Desktop client of Cloud project `hangeul-bo` (a copy is in `secrets\credentials.json`) | its own project and client |
| User token | `token.json` (`progress_builder.py:47`) | the owner's Google account | its own sign-in (`--auth`) |
| Parent folder | `src\sheets\progress_builder.py:56` `PARENT_FOLDER_ID` | `<Drive folder id: ALL STUDENTS>` (masked) | its parent folder id (**move to `.env`**) |
| Programs | `progress_builder.py:108-131` `PROGRAMS` | per key `KLP`/`EAP`/`BACHELOR`/`MASTER`: `name` (sheet-name prefix, e.g. `KOREAN LANGUAGE PROGRAM (KLP)`), `folder_id` (`<Drive folder id: …>`), `match_tokens` (substrings of the normalised `Program`, e.g. `korean language program`, `klp`), `drop_columns` (`UNIVERSITY_COLUMNS` for all but MASTER) | its programs, their Drive folders and matching words |
| Sheet columns | `progress_builder.py:61` `COLUMNS` (36 columns, "Book1" layout), `:100` `UNIVERSITY_COLUMNS` | `(sheet header, CSV column)` pairs such as `("SSC Year", "SSC Year")`, `("HSC GPA", …)`, IELTS/TOPIK computed, `Passport Issue` from the edit page | its sheet layout and CSV names |
| Phone format | `progress_builder.py:174-188` `normalize_phone` | Bangladesh: `01XXXXXXXXX` → `8801XXXXXXXXX`; 10 digits starting `1` → `880…`; `8800…` → `880…` | its country code and trunk rules |
| Blank-cell rule (sheets) | `progress_builder.clean_value` | ASCII-letter comparison of filler words (blanks Bangla-only cells: open, [11 B25](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)) | use the script-aware `records.is_filler` rule of §8 instead |
| Which students | `progress_builder.py:258` `INCLUDE_SOURCES` | `{"direct"}` (B2B partner students left out) | its own rule |
| Intake format | `progress_builder.normalize_intake` (`:261`) | `MARCH 2027` (upper case, single spaces) | its intake naming |
| Attendance sheet (not wired) | `src\sheets\attendance.py:21` `SHEET_ID` | `<Sheet id: attendance>` (masked) | its sheet, if used |
| Missing-info fields | `src\sheets\missing_report.py:34-41` `REQUIRED`, `:42` `UNIVERSITY_FIELDS`, `:50` `_university_fields` (by program and `Study Status`) | 30 required fields incl. `SSC Year/GPA/Group/School`, `HSC …`, `Passport No`, `Sponsor`, `Bank Certificate`; university fields: all four for Master's or a `Study Status` containing both `COMPLETED` and `GRADUATE`; only `Previous University` and `Subject` for `CURRENTLY IN UNDERGRADUATE`; none otherwise | its required fields and their conditions |

## 5. Identity heuristics (names, passports)

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| Common name words | `src\sheets\auto_sync.py:150-156` `_COMMON_NAME_WORDS` | `md`, `mst`, `mohammad`, `sheikh`, `syed`, `kazi`, … and the commonest Bangladeshi surnames (`rahman`, `islam`, `hossain`, `uddin`, `akter`, `khatun`, `ahmed`, `chowdhury`, `khan`, …) | the name words its students commonly share (so one shared word does not pair two records) |
| Honorifics in MRZ names | `src\scraper\ocr_validator.py:552` `_HONORIFICS` | `MD`, `MST`, `MR`, `MRS`, `MISS`, `MOHAMMAD`, `MOHAMMED`, `MOSTAFA`, `LATE` | its honorifics |
| Passport number repair | `ocr_validator.py:248-256` `_repair_doc_number` | a Bangladeshi number's leading `A` read as `4`, `8` or `0` is tried as `A` | its passport-number shape and common OCR confusions |
| Passport number patterns | `src\verify\field_check.py:154` | `[A-Z]\d{8}` (e-passport) and `B[MWXY]\d{7}` (machine-readable) | its country's formats |
| Placeholder passports | `src\sheets\passport_issue.passport_key` (used by `src\cloud\records.py` and `student_index.py`) | `""` for blank, `—` or `PENDING` | its own placeholder words |
| Issuing state | `ocr_validator.py:223`, `:301` (MRZ examples) | `BGD` | its students' nationality (MRZ state code) |
| Staff to skip | `src\verify\auto_verify.py:56` `SKIP_PASSPORTS` | one staff member's passport number (the head of branch, not an applicant; masked here) | its own staff who appear as students, or none |

## 6. Document rules (the verifier)

All of `src\verify\rules.py` (134 lines) is the agency's written guideline turned into data ([03c §2.1](03c_FILES_sheets_verify_root_scripts.md), [07 §10](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)); replace it as a whole. None of `src\verify\` changed since `c17d887`.

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| Bank minimums | `rules.py:19` `MIN_BANK_TAKA`, `:34-36` `MIN_OPENING_BALANCE`, `PREFERRED_OPENING_MAX` | KLP/EAP 1,800,000 taka; Bachelor/Master 2,500,000 (opening max 2,600,000) | its amounts and currency |
| Tax and wealth | `rules.py:22-23` `MIN_TAX_PAID_TAKA`, `MIN_NET_WEALTH_TAKA` | 10,000 and 5,000,000 taka | its thresholds |
| Time limits | `rules.py:25-29` | passport ≥ 12 months valid; family certificate ≤ 3 months old; bank account ≥ 6 months, 6 months of statements (2 for "excellent accredited" universities) | its limits |
| Photo | `rules.py:30-31` | 3.5 × 4.5 cm ratio, JPG/JPEG | its photo rule |
| File names and required documents | `rules.py:56` `FILE_PATTERNS`, `:78` `REQUIRED`, `:88` `OPTIONAL`, `:45` `IDENTITY_DOCS`, `:49` `QR_DOCS` | the portal's document slots per program (passport, NIDs, birth certificate, SSC/HSC, bank, tax, …) | its document slots |
| Word lists | `rules.py:51-112` (`TRANSLATION_WORDS`, `NOTARY_WORDS`, `LAWYER_PAD_WORDS`, `APOSTILLE_WORDS` incl. `ministry of foreign affairs`/`mofa`, `ONLINE_BIRTH_WORDS` incl. `bdris`, `UNION_ISSUER_WORDS` incl. `union parishad`/`pourashava`, `USD_WORDS`, …) | Bangladeshi institutions and wording | its institutions and wording |
| Script to translate | `rules.py:52` `BANGLA_RANGE`, `src\verify\page_checks.py:175-183` `bangla_check` (`[ঀ-৿]`) | Bangla text without an English translation → FAIL | its local script |
| Boilerplate numbers | `rules.py:117` `BOILERPLATE_NUMBERS` | one 10-digit form/notary number printed on many NIDs | its own, found from data |
| Fiscal year | `src\verify\doc_verifier.py:766-769` `current_fiscal_year` | July–June (`2026-2027` from July 2026) | its tax year |
| National id numbers | `doc_verifier.py:414` `nid_numbers` | 10-digit Smart NID, 13 or 17-digit legacy NID, 17-digit birth registration | its id formats |
| Apostille hosts | `page_checks.py:314` `APOSTILLE_HOSTS` | `apostille.mygov.bd`, `mofa-servicedirect`, `apostille` (Bangladesh foreign ministry) | its e-apostille or verification hosts |
| Education levels | `page_checks.py:318-322` `LEVELS` | `HSC` (incl. `alim`, `intermediate`), `SSC` (incl. `dakhil`), `DIPLOMA`, `MASTER`, … | its school-level names |
| pyzbar runtime | `page_checks.py:100-103`, `:331-334` | needs the VC++ 2013 runtime; a failed import silently disables QR reading | treat a failed import as a hard error (R25, [02 §3.1](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |

## 7. Operations (names, ports, times, the PC)

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| `.env` key names | `src\config.py` | `HANGEUL_BASE_URL`, `HANGEUL_USERNAME`, `HANGEUL_PASSWORD` (values in secrets/bot.env) | neutral names (`PORTAL_*`) |
| Time zone | `config.py:58` `REPORT_TIMEZONE` | `Asia/Dhaka` (also the `+06:00` of every Supabase `read_at`) | its zone |
| Currency | `brief.py:224` (`f"{sum(amounts):,.2f} BDT"`), `brief.py:409` `_SYNONYMS` (`taka`, `tk` → `bdt`), `parsers.py:333-334` | `BDT` / taka | its currency and synonyms |
| Month names | `src\dates.py:27-34` `MONTHS`, `MONTH_NAMES` | English | its language(s) |
| Schedule | `.env` `DAILY_REPORT_TIME` (18:05); literals `scheduler.py:450` (watcher 30 min), `:461` (sync 15 min), `:471` (missing report 09:05), `:482` (issue-date refresh 08:30), `:493` (brain keep-warm 10 min), `:365-366` + `:503` (full picture every 60 min, first after 7.5 min) | inherited from the baseline, no recorded reason (the 7.5 min offset falls between the 15- and 30-minute beats) | its times; make all of them settings ([01 §5.4](01_ARCHITECTURE.md)) |
| Quiet windows | `src\cloud\backfill.py:57` `QUIET_WINDOWS`, `src\cloud\full_picture.py:60` `LEAD_MINUTES = 5` | 18:00-18:10, 08:25-08:40, 09:00-09:10 (around the scheduled jobs) | derive them from its own job times |
| Scheduled task, shortcuts | `install_watchdog.bat:14`, `install_autostart.bat`, `C:\Hangeul\JARVIS\jennie_voice\install_jennie_voice.bat` | tasks `HangeulBotWatchdog`, `JennieVoiceWatchdog`; Startup `HangeulBot.lnk`, `JennieVoice.lnk` (and `Ollama.lnk` from Ollama) | its names; the watchdog matches processes by folder, so two bots on one PC need distinct folders |
| Logs | `run.py:9`, `:17`, `:37`; `watchdog.ps1:6`; `scheduler._run_module` (`SYNC_LOG_FILE`, `scheduler.py:340`); `src\cloud\handoff.py:47` `LOG_PATH` | `hangeul_bot.log`, `hangeul_stdout.log`, `hangeul_stderr.log`, `hangeul_watchdog.log`, `hangeul_sync.log` (shared by the jobs and the publishers) | its names; one log per writer process is better ([09 R45](09_BLUEPRINT_RULES_AND_LESSONS.md)) |
| Ports | `config.py` `API_PORT`; `service.py:49-50` | REST API `8000` on `0.0.0.0` (bind `127.0.0.1` in a rebuild); voice service `127.0.0.1:8765`; Ollama `127.0.0.1:11434` | free ports on its PC |
| Folders | `config.py` `docs_root()`, `docs_originals_root()`, `konyang_root()`, `verification_dir()`; `src\cloud\publish.py:83-87` (`data\cloud_state.json`, `data\cloud\`), `handoff.py:46` (`data\cloud\pending`) | `C:\Hangeul\BOT`, `C:\Hangeul\VERIFIED STUDENT DOCUMENTS`, `…\ - ORIGINALS OVER 2MB`, `C:\Hangeul\KONYANG DOCUMENTS` (absent), `data\verification`, `data\cloud` | its paths (the first four are already settings: `DOCS_ROOT`, `DOCS_ORIGINALS_ROOT`, `KONYANG_ROOT`, `VERIFICATION_DIR`) |
| Hardware budget | [02 §8](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md), `ollama_client` `num_ctx` 3072, voice `TTS_GPU_NEED_GB = 3.8` | one RTX 5060 8 GB shared by the brain, document OCR and voice; embeddings on the Ryzen 5 8600G CPU (~14 ms a short record, up to 1.57 GB RAM) | re-measure on its GPU and CPU before choosing models |
| Telegram DNS workaround | `src\net_fix.py:25-36` `CANDIDATE_IPS` | the old PC's network returned an unreachable Telegram address | keep it (generic), or disable with the Windows variable `TELEGRAM_DNS_FIX=false` ([03b §13](03b_FILES_src_scraper_llm_api_config.md)) |
| Tools outside the venv | `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe` (v2.118.0, checksum-verified), `%USERPROFILE%\.cache\huggingface` (the model) | this PC's paths | its own ([02 §3.11](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |

## 8. Supabase publishing (the copy for a phone assistant)

Only if the new agency wants a second, complete copy of what its bot reads for another reader (here Jeannie). The layer is `src\cloud\` (11 files, [03d](03d_FILES_src_cloud.md)); the contract and every kind are in [13](13_SUPABASE_PUBLISHING.md). The code is mostly generic (§9); these are the parts that name this agency, this project or this model.

| Item | path:line | Hangeul value | What the new agency supplies |
|---|---|---|---|
| The switch | `src\config.py:88` `CLOUD_PUBLISH_ENABLED: bool = False`; `.env` line 43 | `true` since 30 Sep 2026 22:27 | `false` until its own backfill and postcheck passed (09 R41); never an empty value (R43) |
| Project URL | `src\config.py:86` `SUPABASE_URL`; `.env` line 39 | `https://dcbcbpwpmdtaanboetiz.supabase.co` (project ref `dcbcbpwpmdtaanboetiz`, region ap-northeast-1, PostgREST v14.5, Postgres 17.6) | **its own project**; never share one project between two bots (R15) |
| Write key | `src\config.py:87` `SUPABASE_SECRET_KEY`; `.env` line 40 | value in secrets/bot.env (SUPABASE_SECRET_KEY) (an `sb_secret_…` key) | its project's secret (service_role) key; never the publishable key (R37) |
| CLI token | not a setting (`Settings` has `extra="ignore"`, `config.py:144`); `.env` line 42 | value in secrets/bot.env (SUPABASE_ACCESS_TOKEN) (an account-wide `sbp_…` token, used only for `supabase link` / `db push`) | its own, only on the machine that applies migrations; better kept out of the bot's `.env` altogether |
| Schema owner | `C:\Hangeul\JARVIS\Jeenie-saem-bot\supabase\migrations\` (repo `munim430-ai/Jeenie-saem-bot`, clone at `31202e9`) | 4 migrations; the bot's is `20260929030000_hangeul_context.sql` (337 lines); the table comment must start `hangeul_context v1` (`hangeul_context.sql:18-25`) | the reader's repo and its migration (D12: the bot never runs DDL) |
| Table and RPC names | the migration; `publish.py` (`/rest/v1/hg_runs`, `/rest/v1/rpc/hg_sync`) | prefix `hg_` ("Hangeul"): `hg_runs`, `hg_records`, `hg_chunks`, `hg_changes`, `hg_sync`, `hg_match`, `hg_changes_since` | its prefix (change it in the migration and in `publish.py` together) |
| Job names | `src\cloud\__init__.py:23-24` `JOBS` | `portal_sync`, `passport_watcher`, `daily_brief`, `missing_report`, `issue_refresh`, `stage_report`, `command`, `backfill`, `full_picture` (`hg_runs.job` is unchecked; a test pins every hook to this tuple) | its own jobs |
| Kinds | `src\cloud\records.py:41-47` `CLOUD_KINDS` (26) | the spec's 24 plus `doc_check` and `consultant_performance`; Hangeul-specific ones: `student_export` (the 63-column CSV), `verification` (from yearless stamps), `passport_audit` / `passport_alert` / `passport_issue` (the passport OCR), `doc_verdict` / `doc_check` / `field_check` / `field_correction` / `doc_page_text` (the verifier's `results.json` and OCR caches), `consultant_performance`, `window_application` | one kind per thing its readers return; drop the kinds whose feature it does not have, and tell the reader's side about any added kind (Jeannie still has to learn `doc_check` and `consultant_performance`, [11 B26](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)) |
| Keys and scopes | `records.py` per kind ([13 §5](13_SUPABASE_PUBLISHING.md)); `performance_scope` `:823-830` | e.g. `student` by portal uid in scope `all`; `verification` by uid in its stamp day; `consultation` by the portal's hidden row id in its received day; `consultant_performance` `<period>\|<first ISO day>\|<name>` in scope `<period>\|<first ISO day>` | its source's stable ids (R11) and scopes that stay put while a window grows (R30) |
| Complete rules | `records.py:527` `pending_complete`, `:665` `export_complete` (`EXPORT_SHARE = 0.9`, `:57`), `:923` `performance_complete`, `:979` `window_complete`, `:1016-1024` `DASHBOARD_GROUPS` / `dashboard_complete`; `sheet_hooks.py:48` `CATCH_UP_PASSPORTS = 6` | the portal's own badges, counters and groups | its own proofs of a whole read (R31); partial when in doubt |
| Volatile fields | `records.py:52` `STUDENT_VOLATILE = ("sl", "details_text", "id")`, `:54` `STALE_EXPORT_COLUMNS` | the list's row number, the joined details text, a duplicate id; the export's stale stage columns | the fields of its pages that change without the entity changing (or every record is resent every run) |
| Filler words and status fields | `records.py:206` `FILLER_WORDS`, `:214-215` `STATUS_FIELDS`, `_STATUS_NAME_RE`, `:216` `BLANK_ON_PORTAL`, `:280-282` the reader's stand-ins (`Unassigned`, `Event`, `Dashboard`) | `na, none, null, nil, pending, tbd, notavailable, notapplicable, notprovided, emailprotected`; "Pending" kept in fields named status/stage/result/step and in Payment, Bank Certificate, Bank Solvency, VIN App, VIN Required | its portal's own "no value" words (found by a dry run, not guessed) and its status fields (R29) |
| Text templates | `records.py` (e.g. `_STUDENT_TEXT_LABELS` `:411`; each kind's content builder, [13 §5](13_SUPABASE_PUBLISHING.md)) | English sentences with the portal's page names ("Student <name> (<HNG id>, portal uid <uid>). Program …") | its own language and field labels (the text is only for finding rows; figures come from `data`) |
| Date windows | `records.py:564` `verification_window` (today − 367 days, moved forward until `yearless_day_problem` clears); `backfill.py:55` `CONSULT_FLOOR = date(2015, 1, 1)` (start of the bisection for the oldest request) | the yearless stamps' one-year horizon; the agency's founding era | its own horizons |
| Embedding model | `src\config.py:91-92` `CLOUD_EMBED_MODEL = "thenlper/gte-small"`, `CLOUD_EMBED_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"`; `src\cloud\embed.py:34-38` (`DIMENSIONS = 384`, `MAX_WORDS = 350`, `MAX_TOKENS = 510`, `HEADING_WORDS = 40`, `ENCODE_BATCH = 32`); `requirements.txt:38-44` (`sentence-transformers==6.1.0`, `transformers==5.17.0`) | gte-small, 384 dimensions, float32, CPU; the reader embeds its questions with `Supabase/gte-small` (the ONNX export of the same model) | the **reader's** model, pinned to a revision on both sides; the vector size in the migration (`vector(384)`) and `MAX_TOKENS` follow the model (R35, R36) |
| Size limits | `src\cloud\publish.py:89-91` `MAX_ROWS = 200` (the SQL's limit), `MAX_CHUNKS = 250`, `MAX_BODY = 1_000_000` | this project's gateway (limit never measured) | its server's row limit and a body budget below its gateway's (R33) |
| Full-picture pages | `src\cloud\full_picture.py:95-119` `collect` (8 reads), `:58` `DEADLINE = 45 * 60`, `:59` `LOCK_WAIT = 120.0` | students (all pages), pending, yesterday's and today's consultations, the totals, window applications, `index.php`, `calendar.php`, the performance page | the lists that change on a quiet day in its portal |

What the new agency supplies, in order: its own project (URL and secret key) and the reader's migration applied with the CLI ([02 §3.11](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md) steps 3-5); the kinds, keys, scopes and complete rules for its own readers; its filler words, found by a guarded dry run against its live portal; the reader's embedding model at a pinned revision, fetched once with the owner's OK; then the release sequence of [09 R41](09_BLUEPRINT_RULES_AND_LESSONS.md).

## 9. Generic: copy as it is

These parts carry no agency knowledge. They are the reusable core of the blueprint.

| Part | Where | Why it is generic |
|---|---|---|
| Long replies and the Markdown fallback | `src\bot\replies.py` (`telegram_len`, `split_text` at 3900, `send_pieces`, `reply_long`, `markdown_to_plain`, `date_error_reply`, `portal_error_reply`) | Telegram's limits are the same for every bot ([03a §3](03a_FILES_src_bot.md)) |
| Whole-record splitting | `performance.message_pieces` (`src\bot\performance.py:247`), `telegram_bot._send_blocks` (`:1720`) | any report whose records must not straddle two messages |
| Strict dates | `src\dates.py` (`parse_user_date`, `user_date_problem`, `has_date_hint`, `parse_stamp`, `stamp_on_day`, `yearless_day_problem`, `local_today`) | only the month names (§7) are language-specific ([03b §2](03b_FILES_src_scraper_llm_api_config.md)) |
| The claim checker | `brief.claims_problem` + `voice._numbers_in`, `_WORD_VALUES`, `_WORD_SCALES` | works on any fact list; only `_OFF_TOPIC_RE` and `_SYNONYMS` hold agency words (§2, §7); move the number reader out of `voice.py` ([06 §3.1](06_LLM_AND_JENNIE_VOICE.md)) |
| The failure type and the one session path | `PortalUnavailable(reason, unreachable)`, `portal_error_reason`, `_ensure_session`, `portal_get`, `fetch_html`, `_ended_on_login` (`client.py`) | any logged-in, read-only scraper ([04 §1.1](04_PORTAL_INTEGRATION.md)) |
| The CDN decoder | `parsers.decode_cf_emails`, `_cf_address` (`parsers.py:24-97`) and the wrapped-soup test (`tests\test_cloud_cf_email.py:287`) | any site behind Cloudflare's e-mail obfuscation |
| The all-pages reader pattern | `read_student_pages` / `read_students`: follow the pager, keep the query, de-duplicate by id, cap pages, check the stated total | any paged list ([01 §4.2](01_ARCHITECTURE.md)) |
| The sequential portal reads with budgets | `brief._PortalReads` (per-read timeout, total budget, stop after the portal stops answering); `full_picture.PortalSession` (the same, per page) | any report built from several reads |
| The watcher outbox | `data\alerted_passport_issues.json` keyed by upload; mark sent only after Telegram accepted it; a time budget per run (R10) | any "alert once" job ([03a §5.3](03a_FILES_src_bot.md)) |
| Subprocess jobs | `scheduler._run_module` (venv python, `-m`, UTF-8, no window, 3600 s cap, log to a file) and the raw Bot API calls of `auto_sync.notify` / `missing_report.send` ([07 §9](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)) | isolates crashes and GPU memory from the bot |
| Locks | `_ocr_lock` (`threading.RLock` around a shared OCR reader), `_voice_turn()` (`asyncio.Lock`), PID-file locks with an age check (`auto_sync.lock`, `auto_verify.lock`), the OS byte lock `publisher_lock`, APScheduler `max_instances=1` | concurrency patterns, not business rules ([01 §5.3](01_ARCHITECTURE.md)) |
| Secret redaction and the CA hook | `src\__init__.py` (`redact()` with 7 patterns on 8 loggers; `data\windows-ca.pem` → the CA variables) | every Telegram bot on Windows that also talks to a hosted database |
| Telegram DNS workaround | `src\net_fix.py` | process-local, generic ([03b §13](03b_FILES_src_scraper_llm_api_config.md)) |
| Authorisation | `is_authorized` (refuse everyone when the allow-list is empty; tell a stranger their chat id), `authorized_ids()`, `brief_recipient_ids()` | R16 |
| Single instance and supervision | `start_background.vbs`, `stop.bat`, `check_status.bat`, `watchdog.ps1` matched by folder, the scheduled task every 5 min | rename only ([02 §5](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |
| The LLM client | `ollama_client` (one option set, fixed `num_ctx`, `keep_alive` policy, `prompt_fits`, `chat` never raising) and the fact-picking JSON schema `AGENT_SCHEMA` | only the system prompt text is agency-specific (§3) |
| The publish engine | `src\cloud\publish.py` (hash state with scope and read time, read ordering, gone keys after the accepted delete, digest drop, exact-byte batching, runs, the model guard, the lock, the dry run, short reasons) | any "copy what changed, delete only from complete reads" sink with an upsert-by-hash RPC ([13 §7](13_SUPABASE_PUBLISHING.md)) |
| The handoff and the embedder | `src\cloud\handoff.py` (atomic file + a never-awaited CPU-only child with a deadline), `src\cloud\embed.py` (`prepare_process`, `-1` GPU hiding, float32, offline, chunking with a repeated heading, `StubEmbedder`) | any second destination that must never slow the first (R42, R34-R36) |
| The record helpers | `records.make`, `content_hash`, `as_read_at`, `iso_day`, `clean_text`, `jsonable`, `unique_keys`, `is_filler` / `_mark_blank` (with the agency's words from §8) | any record store with hashed upserts |
| The voice service | `C:\Hangeul\JARVIS\jennie_voice\service.py` (API, guards, GPU borrowing, render control) | only the persona, languages and reference voice change ([06 §5.2](06_LLM_AND_JENNIE_VOICE.md)) |
| Test fakes and audit tools | `tests\test_foundation.py` `portal` fixture, `Chat`/`Message`, `pin_today`; `tests\test_cloud.py` `FakeSupabase` and the `cloud` fixture; `tests\conftest.py` (publishing off by default); the network guards, `mask()` and `parse_legacy_markdown` ([10 §2, §4.6](10_TESTS_AND_VERIFICATION.md)) | the builders `row()`/`page()` must be rewritten for the new portal's markup, the pattern stays |
