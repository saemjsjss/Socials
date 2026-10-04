# 01 — Architecture

**What's in this file:** the whole Hangeul BOT system as one picture: every process (including the Supabase publisher children and the hourly full picture), external system (including Supabase) and data store (including the hash state and the pending handoff files); how a typed command, a free-text question, a scheduled job, a subprocess job, a voice note, a REST call, a performance command, a publish and the hourly full picture flow through the code, each with its publish step; the module dependency graph with `src\cloud\`; the cross-cutting mechanisms every feature relies on; and the concurrency model (one asyncio loop, worker threads, locks, APScheduler settings, subprocesses).
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), from `C:\Hangeul\BOT` at `main` = `8317741` (48 commits, 113 tracked files; first written 29 Sep 2026 at `c17d887`). Line numbers are `path:line` at `8317741`; "(at c17d887)" marks an older line.
**Siblings:** start at [00_INDEX.md](00_INDEX.md). Details per area: [environment and operations](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md), file maps [src\bot](03a_FILES_src_bot.md) / [scraper, llm, api, config](03b_FILES_src_scraper_llm_api_config.md) / [sheets, verify, root scripts](03c_FILES_sheets_verify_root_scripts.md) / [src\cloud](03d_FILES_src_cloud.md), [portal](04_PORTAL_INTEGRATION.md), [commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md), [LLM and Jennie](06_LLM_AND_JENNIE_VOICE.md), [sheets and document check](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), [history](08_HISTORY_STAGE_BY_STAGE.md), [blueprint rules](09_BLUEPRINT_RULES_AND_LESSONS.md), [tests](10_TESTS_AND_VERIFICATION.md), [open items](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md), [adaptation map](12_ADAPTATION_MAP.md), [Supabase publishing](13_SUPABASE_PUBLISHING.md).

Secrets are never shown: a secret is "value in secrets/bot.env (KEY_NAME)" (`secrets\bot.env` is the pack's exact copy of `C:\Hangeul\BOT\.env`). Student data appears only as placeholders (`<student name>`, `<uid>`, `HNG-YYYY-NNN`).

---

## 0. The system in one paragraph

One Python process (`run.py`) runs three things in **one asyncio event loop**: a python-telegram-bot 22.8 `Application` that long-polls Telegram for @the_Jennie_bot, an APScheduler `AsyncIOScheduler` with **seven** jobs, and a uvicorn/FastAPI REST API on `0.0.0.0:8000`. Every figure the bot states comes from a **live, read-only** read of the agency portal `https://hangeul.com.bd/admin` (httpx GETs plus the one login POST, parsed with BeautifulSoup by header names and CSS classes, after Cloudflare's hidden e-mail addresses are decoded in every soup). Heavy or outward-facing work that touches Google (the 15-minute portal-to-Sheets sync with the GPU document check, the 08:30 issue-date refresh, the 09:05 missing report, the `/missing` and `/stage` reports) runs in **separate `python -m src.…` subprocesses** so a crash, hang or GPU leak there cannot take the bot down. Since 30 Sep 2026 22:27 **everything the bot reads or builds is also published to Supabase** (project `dcbcbpwpmdtaanboetiz`) for the owner's phone assistant **Jeannie**: after its own work each job or command writes one handoff file and starts a **CPU-only publisher process** that embeds the changed records with gte-small and sends them through the RPC `hg_sync`; an hourly **full picture** process re-reads the portal's lists so the copy is complete even on a quiet day. Supabase never delays or blocks Telegram, Sheets or Drive: a failure there is one log line. A local LLM (`qwen3:4b-instruct` in Ollama on `127.0.0.1:11434`, loaded on demand) never produces a figure: it only picks numbered facts, drafts `/sendmail` bodies for approval, and writes one summary sentence that a deterministic claim checker verifies. `/performance_today` and `/performance_month` show only the portal's own Consultant Performance page. The optional voice assistant "Jennie" (a separate FastAPI service on `127.0.0.1:8765` with faster-whisper and CosyVoice2) is fully built and **switched off** since 28 Sep 2026 17:08 to free the 8 GB GPU. A Windows scheduled task restarts the bot within 5 minutes if it dies, and everything starts at sign-in.

---

## 1. Component diagram

```
                                  ┌──────────────────────────── EXTERNAL ────────────────────────────┐
   Telegram users (admin only)    │  api.telegram.org  (Bot API, HTTPS; getUpdates long poll)          │
        ▲        │                │        ▲  sendMessage/editMessageText/deleteMessage/               │
        │        ▼                │        │  pinChatMessage/setMyCommands(13)/sendVoice/getFile       │
        └── Telegram app ─────────┼────────┘                                                           │
                                  │  hangeul.com.bd/admin  (PHP portal behind Cloudflare; GET + POST   │
                                  │                         login.php only)                            │
                                  │  Google Drive v3 + Sheets v4 (OAuth user token)                    │
                                  │  smtp.gmail.com:465 (SMTP_SSL, /sendmail after SEND only)          │
                                  │  dcbcbpwpmdtaanboetiz.supabase.co (PostgREST: POST/PATCH hg_runs,  │
                                  │    POST rpc/hg_sync; secret key)  ──► read by Jeannie (not the bot)│
                                  └──────▲──────────────▲──────────────▲─────────────▲──────────▲──────┘
                                         │ long poll    │ GET/login    │ Sheets/Drive│ SMTP     │ HTTPS (children only)
┌────────────────────────── C:\Hangeul\BOT  (bot process: .venv pythonw.exe run.py) ────────────────────────┐ │
│  ONE asyncio loop                                                                                          │ │
│  ┌──────────────────────────────┐  ┌────────────────────────────┐  ┌──────────────────────────────────┐   │ │
│  │ PTB Application (22.8)       │  │ AsyncIOScheduler (3.11.3)  │  │ uvicorn + FastAPI src.api.main   │   │ │
│  │  46 handlers (+1 voice, off) │  │  daily_executive_briefing  │  │  0.0.0.0:8000, CORS *, no auth   │   │ │
│  │  src\bot\telegram_bot.py     │  │  passport_upload_watcher   │  │  /api/auth|dashboard|            │   │ │
│  │  src\bot\ask.py  (free text) │  │  portal_sync ─────────────┐│  │  applications|crawler            │   │ │
│  │  src\bot\performance.py      │  │  missing_info_report ─────┤│  └──────────────┬───────────────────┘   │ │
│  │  src\bot\brief.py (brief)    │  │  passport_issue_refresh ──┤│                 │                       │ │
│  │  src\bot\voice.py (off)      │  │  brain_keep_warm          ││                 │                       │ │
│  │  src\bot\replies.py (send)   │  │  cloud_full_picture ──────┤│                 │                       │ │
│  └──────────────┬───────────────┘  └────────────┬──────────────┼┘                 │                       │ │
│                 └────────────────┬──────────────┘              │   shared singleton│                       │ │
│                                  ▼                             │                   │                       │ │
│  src\scraper\client.py  admin_client = HangeulAdminClient() ◄──┼───────────────────┘                       │ │
│    portal_get / fetch_html / read_* ── httpx.AsyncClient (cookie jar = the portal session)                 │ │
│    parsers.py (decode_cf_emails at every soup; worker threads) · ocr_validator.py (EasyOCR CPU, RLock)     │ │
│  src\llm\ollama_client.py  ollama_client ─────────────────────────────────────────► Ollama :11434         │ │
│  src\bot\voice.py (only if JENNIE_VOICE_ENABLED) ─────────────────────────────────► voice service :8765   │ │
│  src\cloud\command_hooks / bot_jobs: seen() → after the reply/job → handoff.submit (thread) ──┐           │ │
└─────────────────────────────────────────────┬────────────────────────────────────────────────┼───────────┘ │
                                              │ asyncio.create_subprocess_exec(.venv\Scripts\python.exe -m …)│
                                              ▼   (stdout+stderr appended to hangeul_sync.log, killed after 3600 s)
┌──────────────────── job subprocesses (each: own HangeulAdminClient session, own Google client) ──────┼───────┐ │
│  -m src.sheets.auto_sync           every 15 min: sheets ▸ document ZIPs ▸ Telegram ▸ GPU doc check ▸ after_sync│
│  -m src.sheets.passport_issue --refresh     08:30: student_edit.php per passport ▸ passport_issue.json ▸ hook │ │
│  -m src.sheets.missing_report               09:05: Sheets main tabs + CSV ▸ Telegram text + .xlsx ▸ hook    │ │
│  -m src.sheets.missing_report --program K   /missing button (stdout captured, 180 s) ▸ hook (never prints)  │ │
│  -m src.sheets.stage_report --program K [--intake I]   /stage buttons (stdout captured, 180 s) ▸ hook        │ │
│  -m src.cloud.full_picture          hourly (CPU only): every list page ▸ publish_batches (own lock, 45 min) ─┼─┤
└────────────────────────────────────────────────────────────────────────────────────────────────┬──────┘ │
                                                  sheet_hooks.hand_over → handoff.submit ─────────┤         │
                                                                                                  ▼         │
┌─────── publisher children (CPU only: CUDA_VISIBLE_DEVICES=-1, HF_HUB_OFFLINE=1; never waited for) ────────┐│
│  -m src.cloud.publish --from data\cloud\pending\<time>-<job>.json --timeout 3600                           ││
│    prepare_process ▸ read file ▸ publisher_lock (data\cloud\publish.lock) ▸ hash state ▸ gte-small ▸       ├┘
│    POST hg_runs ▸ POST rpc/hg_sync (≤200 rows, ≤1,000,000 bytes) ▸ PATCH hg_runs ▸ delete the file          │
│  -m src.cloud.backfill  (by hand, once: 30 Sep 21:48-22:05)                                                 │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

┌── Ollama 0.34.4 (per-user) ────────────────┐   ┌── Jennie voice service (DISABLED) ───────────────────────┐
│ Startup\Ollama.lnk → ollama app.exe →      │   │ C:\Hangeul\JARVIS\jennie_voice\.venv pythonw service.py  │
│ ollama.exe serve 127.0.0.1:11434 →         │   │ 127.0.0.1:8765  GET /health  POST /stt  POST /tts        │
│ llama-server.exe runner (qwen3:4b-instruct,│   │ faster-whisper large-v3-turbo (GPU per request) / medium │
│ num_ctx 3072, FA + q8_0 KV, 2.62 GiB)      │   │ (CPU) · CosyVoice2-0.5B (CPU resident, GPU borrowed)     │
└────────────────────────────────────────────┘   └──────────────────────────────────────────────────────────┘

┌── Supervision ─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Startup\HangeulBot.lnk → wscript start_background.vbs → .venv\Scripts\pythonw.exe run.py (at sign-in)      │
│ Task \HangeulBotWatchdog (every 5 min, Ready, no grace after boot) → powershell watchdog.ps1 → start if missing│
│ Task \JennieVoiceWatchdog (Disabled) · JennieVoice.lnk parked in C:\Hangeul\JARVIS\disabled\               │
│ BIOS "power on after AC loss" + Windows auto sign-in (account User) cover power cuts                       │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

DATA ON DISK (C:\Hangeul\BOT unless noted; all git-ignored): data\alerted_passport_issues.json · data\sheet_state.json ·
data\passport_issue.json · data\verification\{results.json, text\*.json, DOCUMENT CHECK.xlsx, FIELD CHECK.xlsx} ·
data\missing_reports\*.xlsx · data\jennie_fillers\ · data\cloud_state.json · data\cloud\{pending\, publish.lock,
student_index.json, backfill_20260930.log} · passports\ · C:\Hangeul\VERIFIED STUDENT DOCUMENTS\… ·
…\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\… · hangeul_{bot,stdout,stderr,sync,watchdog}.log · .env · token.json ·
%USERPROFILE%\.cache\huggingface (gte-small @17e1f347, 67.7 MB)
DATA IN GOOGLE: 7 progress spreadsheets (one per program + intake) under Drive folder "ALL STUDENTS"
DATA IN SUPABASE: hg_runs · hg_records (13,540 after the backfill) · hg_chunks (15,629, vector(384)) · hg_changes (trigger)
```

### 1.1 Processes

| Process | Command line (as on this PC) | Started by | Listens | Lifetime | Logs |
|---|---|---|---|---|---|
| **Bot** | `C:\Hangeul\BOT\.venv\Scripts\pythonw.exe run.py` → child `C:\Users\User\AppData\Local\Programs\Python\Python312\pythonw.exe run.py` (the venv exe is a redirector: always **two PIDs**, e.g. `12204` → `12676` since the 30 Sep 22:27 restart; the child owns port 8000) | `Startup\HangeulBot.lnk` at sign-in; `watchdog.ps1` every 5 min if missing; `start.bat` (console) by hand | `0.0.0.0:8000` (uvicorn) | until stopped; restarted after deploys | `hangeul_bot.log` (all loggers, INFO), `hangeul_stdout.log` (same lines + `rich` banner), `hangeul_stderr.log` (uvicorn, tracebacks) |
| **Sync job** | `.venv\Scripts\python.exe -m src.sheets.auto_sync` (`pythonw` swapped for console-less `python.exe`, `CREATE_NO_WINDOW`, `PYTHONIOENCODING=utf-8`, `cwd=C:\Hangeul\BOT`) | `scheduler.run_portal_sync` (`scheduler.py:344`) every 15 min | — | ~30 s when nothing changed; capped at 3600 s | appended to `hangeul_sync.log` |
| **Issue-date refresh** | `… -m src.sheets.passport_issue --refresh` | `scheduler.run_issue_date_refresh` 08:30 | — | ~300 sequential GETs | `hangeul_sync.log` |
| **Missing report** | `… -m src.sheets.missing_report` | `scheduler.run_missing_report` 09:05 | — | — | `hangeul_sync.log` |
| **Report subprocesses** | `… -m src.sheets.missing_report --program KEY`, `… -m src.sheets.stage_report --program KEY [--intake I]` | `telegram_bot._run_report_module` (`telegram_bot.py:2215`) on a button tap | — | ≤ 180 s; stdout is the reply (the Supabase hook never prints) | stderr tail logged on failure |
| **Full picture** (new) | `… -m src.cloud.full_picture` (CPU only: `CUDA_VISIBLE_DEVICES=-1` set in its `__main__`) | `scheduler.run_full_picture` (`scheduler.py:369-389`) through `_run_module`, hourly, first 7.5 min after the start; only while publishing is on and outside the quiet windows | — | reads ~18 s + publish ~2-7 s when little changed; stops itself after `DEADLINE = 45 * 60` s (`full_picture.py:58`) | `hangeul_sync.log` |
| **Publisher** (new) | `.venv\Scripts\python.exe -m src.cloud.publish --from data\cloud\pending\<YYYYMMDD-HHMMSS-ffffff>-<job>.json --timeout 3600` (console `python.exe`, never `pythonw.exe`) | `handoff.submit` → `spawn` → `start` (`handoff.py:118`, `:109`, `:101`: `subprocess.Popen(..., stdin=DEVNULL, stdout=log, stderr=log, env=child_env(), close_fds=True, creationflags=CREATE_NO_WINDOW)`) from whichever process read the data: the bot (watcher, brief, commands) or a job process (sync, reports, refresh); nobody waits for it | — | 0.4 s to a few minutes (≈5 s model load when rows changed); stops itself after `CHILD_TIMEOUT = 3600` s | `hangeul_sync.log` (see the log-interleaving caveat, [13 §18](13_SUPABASE_PUBLISHING.md)) |
| **Backfill** (by hand) | `.venv\Scripts\python.exe -m src.cloud.backfill [--dry-run]` from `C:\Hangeul\BOT` | the owner or an agent, once (30 Sep 21:48 with `CLOUD_PUBLISH_ENABLED=true` in that process's environment only) | — | 1,025 s on 30 Sep; refuses in a quiet window or during a sync | its own redirect, `data\cloud\backfill_20260930.log` |
| **Ollama** | `ollama app.exe` (tray) → `ollama.exe serve` → one `llama-server.exe` runner per loaded model | `Startup\Ollama.lnk` | `127.0.0.1:11434` | always; the model loads on demand and unloads after 5 idle min (voice off) | Ollama's own |
| **Voice service** (off) | `C:\Hangeul\JARVIS\jennie_voice\.venv\Scripts\pythonw.exe service.py` | `JennieVoice.lnk` (parked in `C:\Hangeul\JARVIS\disabled\`) + task `JennieVoiceWatchdog` (Disabled) | `127.0.0.1:8765` (`SO_EXCLUSIVEADDRUSE`) | last ran 28 Sep until ~17:06 | `jennie_voice.log` (rotating 3 × 2 MB) |
| **Watchdog** | `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\Hangeul\BOT\watchdog.ps1"` | task `\HangeulBotWatchdog`, `PT5M`, `InteractiveToken`, `/RL LIMITED` | — | seconds | `hangeul_watchdog.log` (`yyyy-MM-dd HH:mm  running (pid a b)`) |
| **Supabase CLI** (by hand, migrations only) | `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe` v2.118.0, run from the Jeannie clone `C:\Hangeul\JARVIS\Jeenie-saem-bot` with value in secrets/bot.env (SUPABASE_ACCESS_TOKEN) in its own process environment | the agent on the owner's delegation, 29 Sep ~10:30 (`link`, `db push --dry-run`, `db push --yes`, `migration list`) | — | seconds | none kept |

Details, XML and scripts: [02 §5](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md); the Supabase children in [13 §9, §11, §12](13_SUPABASE_PUBLISHING.md).

### 1.2 External systems

| System | How it is reached | What the bot does there | Who calls it | Never |
|---|---|---|---|---|
| **Portal** `https://hangeul.com.bd/admin` (served through Cloudflare) | `httpx.AsyncClient(follow_redirects=True, timeout=15.0, verify=False)` (`client.py:113-118`), Chrome 122 User-Agent, cookie jar = PHP session | GET `index.php`, `students.php` (+ `pg`, `status=pending`, `source=direct&filter_docs=verified`, `prog`, `export=csv`), `student_edit.php?id=N`, `view_doc.php?f=…`, `download_docs.php?uid=N&zip=1`, `consult_requests.php` (`status`, `from`, `to`), `calendar.php`, `window_applications.php?status=under_review`, `progress.php?uid=N`, **`consult_performance.php?period=today\|month`**; **one POST: `login.php`** (`_csrf`, `username`, `password`; `client.py:184`) | `src\scraper\client.py` (all in-process reads), `progress_builder._fetch_all_students_async`, `verified_docs._download_zip`, `stage_report`, `passport_issue`, `telegram_bot._find_student_in_export`, and the Supabase readers `src\cloud\backfill.collect_*` (the backfill and the hourly full picture, each with a session of its own) | any other POST/PUT/DELETE, `signed_students.php`, portal AI pages (`ask_ai.php`, `ai_training.php`, `team_assistant.php`), any form or button, the performance page's Custom range form ([04 §2](04_PORTAL_INTEGRATION.md)) |
| **Telegram Bot API** | PTB long polling (`getUpdates`), token value in secrets/bot.env (TELEGRAM_BOT_TOKEN); `src\net_fix.py` may pin `api.telegram.org` to a reachable IP inside the process | replies, edits of "⏳" messages, deletes, `setMyCommands` (**13** entries), `pinChatMessage`, `sendVoice`, `getFile` (voice) | the bot process via PTB; subprocess jobs via raw `httpx` `POST https://api.telegram.org/bot<token>/sendMessage` and `/sendDocument` (plain text, `disable_web_page_preview=True`) | webhooks; a second poller on the same token (HTTP 409); anything from the Supabase processes |
| **Google** Drive v3 + Sheets v4 | `google-api-python-client`, OAuth **user** token (`token.json`, scopes `drive` + `spreadsheets`), Desktop client `credentials.json` (project `hangeul-bo`, In production) | build/refresh one spreadsheet per program + intake, read main tabs, look up Drive folders flagged complete | subprocesses only (`progress_builder`, `auto_sync`, `missing_report`, `verified_docs`) | from the bot process itself; no service account exists |
| **Gmail SMTP** `smtp.gmail.com:465` | `smtplib.SMTP_SSL(..., timeout=30)`, sender value in secrets/bot.env (GMAIL_ADDRESS), app password value in secrets/bot.env (GMAIL_APP_PASSWORD) | send one e-mail after an authorised user typed SEND | `telegram_bot._send_gmail` (`telegram_bot.py:1148`), synchronous inside the loop | from a voice note (refused) |
| **Ollama** `127.0.0.1:11434` | `httpx.AsyncClient(timeout=60.0)`; `/api/tags`, `/api/chat`, `/api/generate`, `/api/ps` | fact picking, brief summary, e-mail drafts, (voice) routing and replies | `src\llm\ollama_client.py` | receive raw inquiry rows, contacts or remarks |
| **Voice service** `127.0.0.1:8765` (off) | `httpx.AsyncClient(trust_env=False)`, host must be 127.0.0.1/localhost/::1 | `/stt`, `/tts` | `src\bot\voice.py` | any non-local host |
| **Supabase** `https://dcbcbpwpmdtaanboetiz.supabase.co` (project `dcbcbpwpmdtaanboetiz`, ap-northeast-1; PostgREST v14.5, Postgres 17.6) | `httpx.Client(base_url=SUPABASE_URL, timeout=30.0, follow_redirects=False)` (`publish._client`, `publish.py:342`) with `apikey` and `Authorization: Bearer` = value in secrets/bot.env (SUPABASE_SECRET_KEY) | `POST /rest/v1/hg_runs` (one row per run), `POST /rest/v1/rpc/hg_sync` (upsert by content hash, delete by `p_all_keys`), `PATCH /rest/v1/hg_runs?id=eq.<run>` ([13 §3](13_SUPABASE_PUBLISHING.md)) | **only** the CPU-only children: the publisher, the full picture and the backfill (never the bot process or a sheet job directly) | DDL (the schema belongs to the Jeannie repo, D12); reads to answer anything (`hg_match`, `hg_changes_since` are Jeannie's); the publishable key; logging a server message (it can quote a key holding a passport number) |
| **Hugging Face** | not contacted at run time: every embedding process runs with `HF_HUB_OFFLINE=1`; the pinned revision was fetched once by hand into `%USERPROFILE%\.cache\huggingface` (29 Sep, the owner's OK) | — | — | a download from a running job |

### 1.3 Data stores

| Store | Format / key shape | Written by (how) | Read by | Notes |
|---|---|---|---|---|
| `data\alerted_passport_issues.json` | `{"version": 2, "scans": {"<uid>\|passport_<uid>_<unix>.<ext>": {"uid","student_id","status","checked","alert","sent","sent_at"}}}` | watcher, after **every** audit, `.part` + `os.replace` | watcher; `passport_alert` records (watcher, backfill) | 311 entries on 30 Sep; an older uid-only list is distrusted |
| `data\sheet_state.json` | `{"sheets": {"KLP\|MARCH 2027": {"<row key>": {"name","hash","rec"}}}, "failures": {"sheets": n, "docs": n}}` | `auto_sync` after each step | `auto_sync` | row key = `Student ID:` / `Passport No:` / `NAME:` ([07 §3.6](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)); the `student_export` record key reuses it |
| `data\passport_issue.json` | `{"by_passport": {"<PASSPORT>": "<date>"}}` | `passport_issue.refresh` (only after a complete read) | `progress_builder.issue_date_for`, `field_check`, `auto_verify.field_fingerprint`, `passport_issue` records | 282 entries on 30 Sep |
| `data\verification\results.json` | `{"documents": {PASSPORT: {...}}, "fields": {...}, "corrections": [...]}` | `auto_verify` after every student, `results.tmp` + replace | `auto_verify` (reports), `brief.read_document_check` (section 5, labelled "not live"), `sheet_hooks.verify_batches`, the backfill | **only copy** of the Corrections history; 158 students, 1.8 MB on 30 Sep |
| `data\verification\text\<PASSPORT>.json` | OCR text keyed `"{file}:{size}:{mtime}:{max_pages}"` (or `PAGES:…`) | `auto_verify.install_text_cache` wrappers | same; `doc_page_text` records | OCR is never repeated for an unchanged file |
| `DOCUMENT CHECK.xlsx`, `FIELD CHECK.xlsx` | openpyxl reports | rebuilt in full from `results.json` | staff | close them in Excel before a run; published to Supabase from `results.json`, never as files (D2) |
| `data\missing_reports\missing_information_YYYY-MM-DD.xlsx` | one sheet | `missing_report.write_excel` | Telegram `sendDocument`; the backfill reads the newest (openpyxl, read-only) | student personal data |
| `data\auto_sync.lock`, `data\verification\auto_verify.lock` | the PID | the jobs | the jobs; **read** by the full picture and the backfill (quiet check) | stale after 2 h / 4 h or a dead PID |
| `passports\<uid>_passport_<uid>_<unix>.<ext>` | binary scans (+ `_extracted.jpg` for PDFs) | `audit_student_passport` (`.part` + replace), `download_passports.py` | OCR | never open: student images; never published (D2) |
| `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\<PROGRAM>\<NAME (PASSPORT)>\` | files + `.download_complete` (fingerprint of the portal file names) | `verified_docs.run_local` | `doc_verifier`, `field_check`; the Supabase layer lists and stats them only (to match OCR cache versions) | originals of shrunk files in `…\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\` |
| `data\jennie_fillers\` | `ko_1..3.ogg`, `en_1..3.ogg`, `fillers.json` | `voice.prepare_fillers` | `voice._pick_filler` | voice off |
| **`data\cloud_state.json`** (new) | `{"version": 1, "embed_model": "thenlper/gte-small@17e1f347…", "records": {"<kind>\|<key>": {"h": content_hash, "s": scope, "t": read_at}}, "scopes": {"<kind>\|<scope>": key digest of its last complete publish}, "reads": {"<kind>\|<scope>": its read time}}` | every publisher, the full picture and the backfill (`publish.save_state`, `.part` + `os.replace`), only for rows Supabase accepted | the same; `sheet_hooks.listed_students()` (the export's 90 % rule) | 13,543 records, 600 scope digests, 2.2 MB on 30 Sep 23:28; missing = everything is resent (harmless, slow) ([13 §7.2](13_SUPABASE_PUBLISHING.md)) |
| **`data\cloud\pending\<YYYYMMDD-HHMMSS-ffffff>-<job>.json`** (new) | `{"version": 1, "job", "created_at", "failed_reads": [...], "batches": [{"kind", "scope" (or null + "scope_range"), "complete", "rows", "all_keys"?, "read_at"}]}` | `handoff.write` (`handoff.py:70`, `.part` + `os.replace`) in the process that read the data | its one publisher, which deletes it sent or failed (D6: no queue) | a file left by a killed publisher is pruned after `STALE_HOURS = 6` and not re-sent; normally empty |
| **`data\cloud\publish.lock`** (new) | 1 locked byte (`msvcrt.locking`) | `publish.publisher_lock` (`publish.py:251`) | every publisher | one publisher at a time; the OS frees it when the process dies; never delete by hand |
| **`data\cloud\student_index.json`** (new) | `{"version": 1, "by_passport": {"<PASSPORT>": {"uid": "<uid>", "hng": "HNG-2026-<n>"}}}` | `student_index.remember` after every list read | records of the passport-keyed kinds | a passport two students share gets `""` (no guessing); 14.7 KB |
| `data\cloud\dry_run\<stamp>-<job>-<run8>\NNNN-<label>.json` | request bodies exactly as they would be sent | a dry run (`backfill --dry-run`) | the verifier | absent in the live tree; the 29/30 Sep ones (full student data, ~100 MB each) are under `C:\Hangeul\JARVIS\cloud\{all,release}\data\cloud\dry_run\` ([11 §F](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)) |
| Google Sheets | one spreadsheet per program + intake; the main tab mirrors the portal | `progress_builder.build_target` | staff, `missing_report.read_sheets`, `sheet_drift` | never delete a main tab |
| **Supabase** `hg_runs`, `hg_records` (PK `(kind, key)`), `hg_chunks` (PK `(kind, key, ord)`, `vector(384)`, cascade), `hg_changes` (trigger-filled change log) | the Jeannie migration `20260929030000_hangeul_context.sql` ([13 §3](13_SUPABASE_PUBLISHING.md)) | only through `hg_sync` and the `hg_runs` POST/PATCH | Jeannie (server and PWA); verifiers (GET only) | 13,540 records and 15,629 chunks after the 30 Sep backfill; RLS on with no policies: only the secret key gets through |
| In memory (lost on restart) | PTB `context.user_data` (`override_text`, `override_date`, `override_query`, `crosscheck_date_only`, `awaiting_date_for`, `date_prompt_answer`, `email_flow`); `admin_client` cookie jar and `_profile_cache` (also read by `command_hooks.profile_of`); voice `_history` (6 turns per chat) and `_filler_clips`; `command_hooks._tasks` and `handoff._children` (strong references to background handoffs and publisher children) | handlers | handlers | nothing conversational persists |
| `.env`, `token.json`, `credentials.json` | secrets | owner; `token.json` rewritten on every refresh | `src\config.py`; `progress_builder._load_credentials` | copies in `secrets\` |
| `%USERPROFILE%\.cache\huggingface` | the gte-small snapshot at `17e1f347d17fe144873b1201da91788898c639cd` | fetched once by hand | the embedding processes (offline) | a new PC must fetch it once |
| Logs | text, no rotation (bot) | see §1.1 | operators | every secret shape is redacted by `src\__init__.py` (§4.8); read `hg_runs`, not `hangeul_sync.log`, for publish results ([13 §18](13_SUPABASE_PUBLISHING.md) item 2) |

---

## 2. Request flows

### 2.1 A typed command: `/verified_date 12 Sep 2026`

```
Telegram ─getUpdates─► PTB Application (updates handled one at a time, in order)
  └─ CommandHandler("verified_date") → verified_date_command(update, context)        telegram_bot.py:657
       raw = user_data.pop("override_text") or " ".join(context.args)   ("12 Sep 2026"; none → date prompt, §2.2)
       user_data["override_date"] = raw → verified_command(update, context)            telegram_bot.py:858
         is_authorized(update)?  no → "⛔ Unauthorized access. Your Chat ID is: `<id>`"   telegram_bot.py:22
         normalize_date_input(raw, strict=True) → src.dates.parse_user_date(prefer_past=True)   telegram_bot.py:88
             None → _ask_date_again(...) + replies.date_error_reply(raw, "/verified_date")   (never today)
         src.dates.yearless_day_problem(day, local_today()) → "ℹ️ … not available (<why>)"
         reads = {}                                              (the Supabase copy's scratch dict)
         status = reply_text("⏳ _Gathering verified student records for 12 September 2026..._")
         admin_client.get_verified_students(target_date=day)                          client.py:547
           read_verified_students(day, all_pages=True)                                 client.py:522
             read_students() → read_student_pages(): portal_get("students.php"), ("students.php", {"pg": 2}) … N
                 each page: "<table" present? pager page == asked? ; decode_cf_emails + parse_students_page
                 in asyncio.to_thread; end: unique uids ≥ pager total, else PortalUnavailable
             stamp guard (rows but no "Payment verified by" line → PortalUnavailable)
             parsers.verification(student, day)   (the row's own .pf-by stamp, whole tokens, applied-date rule)
         cloud.seen(reads, verified=(day, list))   only when publishing is on and not mock (command_hooks.py:93)
         text = format_verified_students_report(list, "12 September 2026")
         PortalUnavailable/other → replies.portal_error_reply("Verified students for 12 September 2026", e)
         replies.reply_long(update.message, text, edit=status)
           split_text(text, 3900 UTF-16 units, between lines) → piece 1 edits the ⏳ message, the rest reply
           a piece refused as Markdown ("Can't parse entities") → resent as markdown_to_plain(piece)
         cloud.publish(reads)   AFTER the reply, not awaited (command_hooks.py:139): a background task runs
           build(reads) → verification_day batch (complete when the day passes yearless_day_problem)
           → handoff.submit("command", batches) in a worker thread → publisher child (§2.9)
```

Every command follows this shape: input precedence `override_text` → `context.args` → message text; strict date parsing; "⏳" message; live read through `admin_client`; `cloud.seen(...)` right after each successful read; formatter that shows only what the rows show; `portal_error_reply` / `date_error_reply` on failure; `reply_long(edit=status)`; then `cloud.publish(reads)`. The reply is byte-identical with publishing on or off (a test pins it). The per-command table is in [05 §2](05_TELEGRAM_COMMANDS_AND_JOBS.md); what each handler keeps and publishes is in [05 §9](05_TELEGRAM_COMMANDS_AND_JOBS.md) and [03d §12.2](03d_FILES_src_cloud.md).

### 2.2 The "which date?" conversation (two updates)

1. `/verified_date` with no argument → `user_data["awaiting_date_for"] = "verified"` → prompt `📅 *Total Verified Students* … (e.g. \`12 Sep 2026\`, \`yesterday\` or \`2026-09-12\`)`.
2. The next non-command text reaches `handle_natural_language_message` (`telegram_bot.py:1973`): after the `email_flow` check it **pops** `awaiting_date_for`, sets `override_text = <text>` and `DATE_PROMPT_KEY = "verified"`, calls `verified_date_command`, and pops `DATE_PROMPT_KEY` in `finally`.
3. An unreadable answer calls `_ask_date_again` (`telegram_bot.py:595`): the question stays open only if the answer looks like a date try (`has_date_hint`) or is ≤ 2 words ("tomorow"); a new 3+-word question is not swallowed.

### 2.3 A free-text question

```
MessageHandler(filters.TEXT & ~filters.COMMAND) → handle_natural_language_message(update, context, query=None)   telegram_bot.py:1973
  0 not authorised → return silently
  1 user_data["email_flow"] → _handle_email_flow (the /sendmail state machine; SEND/EDIT/DENY)
  2 user_data.pop("awaiting_date_for") → the pending date command (§2.2)
  3 route = ask.classify(query, local_today())          ask.py:529 — whole-word rules in a fixed order, first match
                                                        wins, no I/O (hello, /report, pin, PERFORMANCE, crosscheck, …;
                                                        the list is 05 §6.2)
       hello → ask.HELLO · pin → pin_command
       performance → topic "month" → performance_month_command · "today" → performance_today_command
                     · any other day/span/period → ask.performance_other_reply(route) (reads nothing)   (§2.8)
       report → report_command(override_text) · stats → stats_command
       inquiries / verified / passports / crosscheck → the command handlers with override_text (dates re-read strictly)
       a span asked of a one-day answer → awaiting_date_for + ask.one_day_reply (passports over a past span → range cross-check)
       admitted → override_query → admitted_command · missing / stage → the button menus · calendar → calendar_command
       pending | window_review | dashboard | intake | applied | unknown → ask.reply(message, route, query)   ask.py:1065
  ask.reply: reads = {} ; "🤔 _Reading the live portal..._" → answer_*(…, reads=reads) → reply_long(edit=…)
       answer_pending      every page of students.php?status=pending, rows whose own Payment is Pending, vs the badge
       answer_window_review window_applications.php?status=under_review + the "Under review" tile
       answer_dashboard    index.php tiles + cards → Fact list (ask.dashboard_facts, decoded soup) → _dashboard_answer(topic)
       answer_intake / answer_applied   every page of students.php, counted in code
       answer_unknown      index.php facts → ollama_client._answer_query_fallback (whole-label match, no LLM)
                           → else ollama_client.answer_agent_query (POST /api/chat, format=AGENT_SCHEMA,
                             num_predict 60, returns fact INDICES) → facts shown word for word → else cant_answer()
       any exception → portal_error_reply("The answer", e)
       then cloud.publish(reads)   (ask.py:1092: the answers' seen() keys — facts, pending, students, calendar)
```

The LLM can only choose indices of facts already read and formatted by code; the reply prints the facts, not the model's words ([06 §2.1](06_LLM_AND_JENNIE_VOICE.md)).

### 2.4 A scheduled in-process job: the 18:05 brief

```
AsyncIOScheduler CronTrigger(hour=18, minute=5, timezone=Asia/Dhaka), misfire_grace_time=600, max_instances=1, coalesce=True
  → scheduler.send_daily_briefing(app)                                               scheduler.py:248
      no TELEGRAM_ADMIN_CHAT_ID → warning, return
      composed = await brief.compose_brief()                                          brief.py:600
        reads = _PortalReads()   one after another; each ≤ READ_TIMEOUT 75 s; all ≤ PORTAL_BUDGET 150 s;
                                 first unreachable answer → the rest "not read: the portal did not answer";
                                 each failed read's exception kept in reads.errors (for the Supabase run)
          1 read_consultation_day(today)   consult_requests.php?status=all&from=D&to=D (filter echoed, rows == caption == tabs)
          2 read_verified_students(today)  every students.php page (skipped when yearless_day_problem)
          3 read_consultation_totals()     consult_requests.php?status=file_opened (status tabs = all-time counts)
          4 read_pending_payments()        students.php?status=pending (badge)
          5 read_window_apps_under_review() window_applications.php?status=under_review
          6 get_dashboard()                index.php tiles
          7 get_calendar_events()          calendar.php (today only)
          8 asyncio.to_thread(read_document_check)   data\verification\results.json ("not live")   brief.py:628
        sections 1-5 → Brief(text, facts, reads)   (a figure not read = "not available (<why>)", never 0;
                                                    the third field only feeds the Supabase copy, brief.py:76-81)
        llm_summary(facts) → ollama_client.chat(num_predict 120, timeout 30) → check_summary → claims_problem
          → kept only if every number/word/clause matches a fact; else dropped ("Brief summary dropped: <why>")
      _send_brief(bot, chat_id, text) → send_pieces(..., "Markdown")  (split + plain-text fallback)
      if JENNIE_VOICE_ENABLED and JENNIE_SPOKEN_BRIEF: voice.send_spoken_brief(bot, chat_id, facts)  (own try; both false now)
      await bot_jobs.hand_over("daily_brief", bot_jobs.brief_batches, composed)      scheduler.py:278
        (after everything was sent; to_thread + wait_for 30 s; never raises: report "brief|<day>", its sections,
         brief_fact, and each read that succeeded — the day's consultations and verifications, totals, tiles)
      any exception → "Failed to dispatch scheduled briefing: …" (never raises into APScheduler)
```

The 30-minute passport watcher (`check_new_passport_uploads`, `scheduler.py:158`) has the same in-loop shape with its own memory and budget: read every page (`listed_at = bot_jobs.now()` right after, `:174`) → for each new `uid|file` key, newest upload first, `audit_student_passport` (OCR in a worker thread) until 20 minutes, noting each audit's profile read (`bot_jobs.profile_now` / `keep_profile`, `:204`, `:212`) → save after every audit → send unsent alerts packed under 3900 characters, marking each sent only after Telegram accepted it (`bot_jobs.note_sent`) → **last**, `await bot_jobs.hand_over("passport_watcher", bot_jobs.watcher_batches, …)` (`:243`): `student` complete, `passport_audit` complete over every listed scan, `passport_alert` complete over each student's newest scan, `student_profile` per audited uid, one `notification` per accepted alert message ([05 §7.2](05_TELEGRAM_COMMANDS_AND_JOBS.md), [13 §5.11](13_SUPABASE_PUBLISHING.md)).

### 2.5 A subprocess job: the 15-minute portal sync

```
IntervalTrigger(minutes=15) → scheduler.run_portal_sync() → _run_module("src.sheets.auto_sync", "Portal sync")   scheduler.py:344, :392
  asyncio.create_subprocess_exec(<venv>\python.exe, "-m", "src.sheets.auto_sync", cwd=BOT_ROOT,
      stdout/stderr → hangeul_sync.log (append), env PYTHONIOENCODING=utf-8, creationflags=0x08000000)
  await proc.wait() within 3600 s → else proc.kill(); logs "Portal sync finished (exit N)."
  ── inside the child (auto_sync.run_once(send=True, verify=True), auto_sync.py:412) ──
  data\auto_sync.lock held (PID alive, < 2 h)? → "Another sync is still running — skipped."
  cloud = {"run_at", "title", "sent": []} only when sheet_hooks.on() (publishing on); else None and nothing is kept
  1 sheets: progress_builder.fetch_all_students() = ONE GET students.php?export=csv (utf-8-sig, "Full Name" check)
            per (program, intake) target: _snapshot → compare with sheet_state.json → build_target (Sheets API) or
            sheet_drift restore; row keys paired across key changes (_same_student, _likely_same)
  2 docs:   verified_docs.run_local(DOCS_ROOT): every page of students.php?source=direct&filter_docs=verified
            (decoded soup), GET download_docs.php?uid=N&zip=1 for new/changed fingerprints, shrink files > 2 MB
            each step: 3 attempts 20 s apart, fresh HangeulAdminClient; a failure is announced only on the 3rd run in a row
            cloud["documents"] = result["students"] (the whole list)
  3 notify(lines) -> bool: raw Bot API sendMessage (plain text, split_text) to settings.brief_recipient_ids();
            an accepted notice goes into cloud["sent"]
  4 auto_verify.run(budget=6): up to 6 students whose document/field fingerprint changed → EasyOCR on the GPU
            → results.json → DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx → notify(title="🔍 Document check")
            (cloud["store_ok"] = sheet_hooks.store_readable(results.json) before; cloud["verify"] = result after;
             a NameError/AttributeError/ImportError/TypeError stops the run: a code fault must not look like a clean report)
  5 LAST: cloud["export"] = pb._ALL_STUDENTS_CACHE; sheet_hooks.after_sync(cloud)      auto_sync.py:475-477
            → sync_batches: student_export (complete if header ok and rows ≥ 90 % of the students last listed),
              student_documents, report sync_summary (when it had lines), per-passport doc_verdict / field_check /
              doc_page_text for the checked passports + up to 6 never accepted, then doc_check, field_correction and
              the two check reports, and one notification per accepted notice
            → handoff.submit("portal_sync", …): one file + a publisher child; the sync exits without waiting
```

`missing_report`, `passport_issue --refresh` and the `/missing` / `/stage` button reports follow the same "own process, own session, own Google client, Supabase hook last" pattern; the button reports capture stdout (180 s) and send it as plain text, so their hook (`sheet_hooks.hand_over`) **never prints** and the publisher child never inherits that pipe ([07 §13](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), [03c §1.8](03c_FILES_sheets_verify_root_scripts.md)).

### 2.6 A voice note (built; registered only when `JENNIE_VOICE_ENABLED=true`)

```
MessageHandler(filters.VOICE | filters.AUDIO, voice.handle_voice_message, block=False)    (runs beside typed updates)
  1 is_authorized? no → log only          2 > 60 s or > 20 MiB → short note
  3 filler clip at once (background task; pre-rendered OGG, cached Telegram file_id)
  4 download (getFile)                    5 POST /stt inside _voice_turn() (one asyncio.Lock per loop, wait ≤ 240 s)
  6 language: ko if Whisper says ko or ≥ 30 % Hangul
  7 "🎧 heard: <text>" (background)       8 email_flow waiting? → EMAIL_FLOW_NOTE, stop (checked again before dispatch)
  9 voice.route(heard, last 3 turns) → ONE ollama chat call, format=_ROUTER_SCHEMA → {command, date, english_query}
      dates recomputed in code (relative words, weekday names; impossible dates → the command's date error)
 10 voice._dispatch → the SAME command handler on a _CapturingUpdate (reply_text/edit_text/delete recorded);
      nothing placed → handle_natural_language_message(proxy, context, query=english_query or heard)
      (a spoken performance question reaches the page this way, through the "stats" route and ask.classify)
 11 spoken_reply: facts = answer_facts(captured text) (≤ 8 one-figure lines)
      English: brain sentence checked by _fact_problem → brief.claims_problem, else a fixed line built in code
      Korean: always built in code from the headline fact (_korean_line), e.g. "짜잔! 어제 상담 요청은 21건이에용!"
 12 _remember (deque(maxlen=6), memory only)  13 POST /tts in _voice_turn() → sendVoice("jennie.ogg")
 14 one metadata-only timing line (never the words)
```

`voice.py` is unchanged since `e164679`. Full detail, prompts and latencies: [06 §5](06_LLM_AND_JENNIE_VOICE.md).

### 2.7 A REST call (nothing uses it today)

`GET http://<pc>:8000/api/dashboard/stats` → FastAPI route `dashboard.get_dashboard_stats` → `admin_client.get_dashboard()` (the **same** singleton and session as the bot, same event loop) → JSON. `/api/applications` lets `PortalUnavailable` escape (HTTP 500); `/api/applications/inquiries|consultations` still read the unfiltered 500-row consultation page (and, since the Cloudflare decoding, return real e-mail addresses); `/api/crawler/parse-page` GETs any path. It binds `0.0.0.0` with CORS `*` and no authentication, by the owner's choice (decision 9). It publishes nothing to Supabase. A rebuild should bind `127.0.0.1`, add authentication and an allow-list of pages ([03b §10](03b_FILES_src_scraper_llm_api_config.md), [11 §B3](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).

### 2.8 The performance commands: the portal's own page, nothing computed

```
/performance_today | /perf_today | "performence today"-style words (§2.3)       → the today branch
/performance_month | /perf_month | "this months performance"-style words      → the month branch
"performance yesterday" | "consultant performance yesterday" | another span or period
  → ask.performance_other_reply(route) (ask.py:508-526): nothing read, nothing published            (third branch)
today / month branches:
  → performance_today_command (telegram_bot.py:742) · performance_month_command (:752) · /performance [words] (:762,
    ask.performance_route decides today / month / other)
  → _send_performance_report(update, kind)                                             telegram_bot.py:718
      status = reply_text(performance.waiting_text(kind))
      performance.build_performance_report(kind, reads=reads)                          performance.py:281
        admin_client.read_consult_performance(kind)                                     client.py:425
          kind not in PERFORMANCE_PERIODS {"today","month"} → ValueError; mock mode → PortalUnavailable
          ONE GET consult_performance.php?period=<kind> (fetch_html) → asyncio.to_thread(parse_consult_performance)
            (decode_cf_emails; tiles div.pf-stats > div.pf-stat, top card section.pf-top, leaderboard table.tbl.pf,
             count badge, tr.pf-empty-row > .pf-empty as the only empty state; PerformanceLayoutError → PortalUnavailable)
          the page's open tab and "Showing …" label must be the period asked for (the portal falls back to This Month)
        cloud.seen(reads, performance=(kind, page))
        format_consult_performance(kind, page, today): the 4 tiles, the top performer, the leaderboard, ⚠️ self-checks
          where the page disagrees with itself (said, never corrected)
        failure → portal_error_reply("The portal's Consultant Performance page (<Today|This Month>)", e)  (never zeros)
      for piece in performance.message_pieces(report):   (whole records only: a consultant never straddles two messages)
          reply_long(update.message, piece, edit=status if first)
      cloud.publish(reads) → kind consultant_performance, scope "<period>|<first ISO day>" (stable while the range grows)
```

The first version (29-30 Sep, `bbd8f98`, `a721066`) computed team figures itself from consultations and verifications; the owner corrected the meaning on 30 Sep 13:11 and `ce23535` / `314afdb` removed every self-computed reader. Details: [05 §5.15](05_TELEGRAM_COMMANDS_AND_JOBS.md), [03a §6a](03a_FILES_src_bot.md), [04 §3.10](04_PORTAL_INTEGRATION.md), [08 §13-§14](08_HISTORY_STAGE_BY_STAGE.md).

### 2.9 A publish: from what a job read to Supabase

```
bot process (a command, the brief, the watcher)                      a sheet job process (sync, reports, refresh)
  command_hooks.publish(reads) → background task (to_thread)           sheet_hooks.hand_over(job, build)  (last step,
  bot_jobs.hand_over(job, build, *args) → to_thread, wait_for 30 s       synchronous, never prints)
        │  build: src.cloud.records — one pure function per kind: reader output → records
        │  {kind, key, scope, student_uid, student_hng_id, student_name, passport_no, day, data, content,
        │   content_hash = sha256(canonical {kind,key,scope,data,content}), source, read_at}
        │  grouped as batch(kind, scope, rows, complete[, all_keys, read_at]) / batches(kind, rows, complete[, scope_range])
        │  a read that failed → no batch at all, only a line in failed_reads (never rows=[] with complete=True)
        ▼
  handoff.submit(job, batches, failed_reads)                                          handoff.py:118
    nothing unless publishing is on (SUPABASE_URL + SUPABASE_SECRET_KEY + CLOUD_PUBLISH_ENABLED=true) and there is a
    batch (the bot-process hooks also refuse mock mode: command_hooks.active, bot_jobs.hand_over)
    write data\cloud\pending\<time>-<job>.json (.part + os.replace) → spawn → start: Popen(venv python.exe -m
    src.cloud.publish --from <file> --timeout 3600, DEVNULL/log/log, env = child_env(): +PYTHONIOENCODING=utf-8,
    CUDA_VISIBLE_DEVICES=-1, HF_HUB_OFFLINE=1) — returns at once
        ▼
  ── publisher child: publish.main (publish.py:911) → process_file (:871) ──
    embed.prepare_process() (CUDA hidden before torch; offline; libraries quiet) · deadline timer 3600 s (os._exit(3))
    publish_batches(job, batches, failed_reads) (:836) under publisher_lock (≤ 20 min wait) inside ONE run(job):
      POST /rest/v1/hg_runs {id, job, started_at, counts: {}}  (fails → p_run null in every call)
      per batch → publish(kind, scope, rows, complete, all_keys, read_at) (:639) / publish_scopes (scope_range):
        _normalise (left-out rows make the batch partial) → load hash state → older complete read? → partial
        changed rows = (h, s) differ, not older than the version sent → gone keys (complete only, kept if a newer
        read sent them) → nothing to do? skipped "no changes" → embed_model guard → chunk (≤350 words, ≤510 tokens,
        heading repeated) → gte-small float32 CPU, groups of ≤200 rows / ≤250 chunks → split by exact bytes ≤ 1,000,000
        → drop the scope digest → POST /rest/v1/rpc/hg_sync per call (p_all_keys only on the last call of a complete
        read) → on each 2xx record {h, s, t} and save the state; after the last, forget the gone keys, set digest + read time
        → a refusal or timeout: one log line; state not advanced; Supabase given up on for the rest of the run
      PATCH /rest/v1/hg_runs?id=eq.<id> {finished_at, status ok|partial|failed, counts, note}  (always)
    delete the handoff file (sent or failed); one INFO summary line to hangeul_sync.log
```

The contract (the SQL), every kind's complete rule and the engine's steps in full: [13 §3-§10](13_SUPABASE_PUBLISHING.md); the functions: [03d §2-§5](03d_FILES_src_cloud.md).

### 2.10 The hourly full picture

```
IntervalTrigger(minutes=60, start_date=now + 7.5 min), id cloud_full_picture, max_instances=1, coalesce=True   scheduler.py:501-509
  → scheduler.run_full_picture()                                                       scheduler.py:369
      publishing off → return (nothing started) · full_picture.skip_reason() → "Full picture publish skipped: <reason>."
        (a quiet window 18:00-18:10, 08:25-08:40, 09:00-09:10, or within LEAD_MINUTES = 5 before one, or a live
         data\auto_sync.lock: backfill.quiet_reason, backfill.py:57, :66)
      else _run_module("src.cloud.full_picture", "Full picture publish") → child (CPU only)
  ── child: full_picture.main (full_picture.py:177) → run (:132) ──
    publishing off or MOCK_MODE → skip · skip_reason() again · publisher_lock(120 s) or skip the hour · skip_reason() again
    collect (:95) with PortalSession (:77: after the first unreachable answer every later page fails at once),
    skip_reason() asked before EVERY page:
      1 every page of students.php            → student (complete), verification (per stamp day, complete in the window)
      2 every page of students.php?status=pending → pending_payment
      3 consult_requests.php yesterday and today (date filter) → consultation (per day), consultation_day (partial)
      4 consult_requests.php?status=file_opened → consultation_totals
      5 window_applications.php?status=under_review → window_application
      6 index.php → dashboard_fact (complete only when all 7 groups show)
      7 calendar.php → calendar_item (never complete)
      8 consult_performance.php?period=today and ?period=month → consultant_performance
    publish.publish_batches("full_picture", batches, failed) in one run; stops itself after 45 min
    "Full picture: <n> batch(es) read in <t> s, <r> read(s) failed; <p> publish(es), <f> failed."
```

First runs on 30 Sep: 22:35 (12 batches read in 18.3 s; 3 upserted, 779 unchanged; 6.9 s in all) and 23:35 (782 unchanged, 1.6 s). About 16 portal GETs an hour. It sends nothing to Telegram ([13 §11](13_SUPABASE_PUBLISHING.md), [05 §7.7](05_TELEGRAM_COMMANDS_AND_JOBS.md)).

---

## 3. Module dependency graph

Arrows mean "imports". `(lazy)` = imported inside a function, which is how every cycle is broken and how optional parts (voice, Google libraries, OCR, the embedding model) stay out of processes that do not need them.

```
LAYER 0  side effects and settings
  src\__init__.py        CA-bundle env vars (if data\windows-ca.pem exists) + the secret-redaction filter
                         (7 patterns: bot token, Bearer, apikey, sb_secret_, sb_publishable_, sbp_, JWT) on 8 loggers
                         (httpx, httpcore + 5 children, hangeul.cloud); imported first by everything
  src\config.py          Settings(BaseSettings) → settings, BOT_ROOT, _folder()                ← pydantic-settings
                         (+ SUPABASE_URL, SUPABASE_SECRET_KEY, CLOUD_PUBLISH_ENABLED, CLOUD_EMBED_MODEL/REVISION)
  src\net_fix.py         apply_telegram_dns_fix() (socket.getaddrinfo patch for api.telegram.org)

LAYER 1  pure helpers
  src\dates.py           → config (lazy, for REPORT_TIMEZONE)
  src\llm\prompts.py     SYSTEM_AGENT_CHAT, AGENT_SCHEMA
  src\scraper\mock_data.py
  src\verify\rules.py    thresholds, file patterns, word lists (data only)

LAYER 2  parsing, OCR, LLM transport
  src\scraper\parsers.py      decode_cf_emails (every soup) ; → dates (lazy)                    ← bs4 (html.parser)
  src\scraper\ocr_validator.py                                     ← cv2, numpy, easyocr (lazy), pypdf
  src\llm\ollama_client.py    → config, prompts                    ← httpx

LAYER 3  the portal client
  src\scraper\client.py  → config, dates, parsers, ocr_validator, mock_data    ← httpx, bs4
                          exports admin_client (singleton), HangeulAdminClient, PortalUnavailable, portal_error_reason,
                          PERFORMANCE_PAGE, PERFORMANCE_PERIODS

LAYER 4  sending and shared sheet helpers
  src\bot\replies.py     ← telegram.error.BadRequest, telegram.helpers ; → dates (lazy), client.portal_error_reason (lazy)
  src\sheets\progress_builder.py → client (lazy), passport_issue (lazy)    ← googleapiclient, google-auth (lazy)

LAYER 4C the Supabase publish layer (src\cloud\, 11 files; everything that touches features is lazy)
  src\cloud\__init__.py        JOBS (the hg_runs.job names)
  src\cloud\records.py         module level: hashlib, json, math, re, datetime only ;
                               (lazy) config, dates, parsers (verification, payment_text, _label_key),
                               sheets.passport_issue.passport_key, sheets.progress_builder, sheets.auto_sync._row_key,
                               client.PERFORMANCE_PERIODS, bot.performance._range_dates
  src\cloud\publish.py         → config ← httpx ; records, embed, handoff (lazy)
  src\cloud\handoff.py         → publish (CHILD_TIMEOUT, CLOUD_DIR, enabled), config ; embed.NO_GPU, records (lazy)
  src\cloud\embed.py           → config ; sentence-transformers 6.1.0, transformers 5.17.0, torch (lazy, CPU-only processes)
  src\cloud\student_index.py   → config
  src\cloud\bot_jobs.py        → handoff, records ; client, dates, command_hooks.profile_of (lazy)
  src\cloud\command_hooks.py   (lazy) handoff, records, client.admin_client, dates
  src\cloud\sheet_hooks.py     (lazy) handoff, publish, records, student_index, client, progress_builder,
                               missing_report, passport_issue, verify.auto_verify, verify.doc_verifier
  src\cloud\backfill.py        → records, config ; publish, embed, student_index, bot_jobs.watched_scans, client,
                               parsers, ask (dashboard_facts, calendar_items), auto_sync, stage_report, verified_docs (lazy)
  src\cloud\full_picture.py    → backfill, publish, records, config, client (HangeulAdminClient, PortalUnavailable)

LAYER 5  features
  src\bot\brief.py       → replies, config, dates, ollama_client, client ; voice (lazy: _numbers_in, _plain…), parsers (lazy)
  src\bot\ask.py         → dates ; brief.esc, replies, client, parsers, ollama_client, cloud.command_hooks (all lazy)
  src\bot\performance.py → brief.esc, client (PERFORMANCE_PAGE, PERFORMANCE_PERIODS), parsers._label_key ;
                           replies, cloud.command_hooks, dates, client.admin_client (lazy)
  src\sheets\passport_issue.py   → progress_builder ; client, cloud.sheet_hooks (lazy)
  src\sheets\verified_docs.py    → config, progress_builder, parsers.decode_cf_emails ; client (lazy)
  src\sheets\auto_sync.py        → config, progress_builder, verified_docs ; client, verify.auto_verify,
                                   bot.replies.split_text, cloud.sheet_hooks (lazy)
  src\sheets\missing_report.py   → progress_builder ; config, bot.replies.split_text, client, cloud.sheet_hooks (lazy)
  src\sheets\stage_report.py     → progress_builder ; client, parsers, cloud.sheet_hooks (lazy)
  src\sheets\attendance.py       → progress_builder            (not wired)
  src\verify\page_checks.py      → config, rules               ← cv2, fitz (PyMuPDF), pyzbar
  src\verify\doc_verifier.py     → config, page_checks, rules ; progress_builder (lazy)   ← easyocr (GPU), fitz, PIL
  src\verify\field_check.py      → progress_builder, rules, doc_verifier ; passport_issue (lazy)
  src\verify\auto_verify.py      → config ; doc_verifier, field_check, passport_issue (lazy)  ← openpyxl

LAYER 6  schedule and voice
  src\bot\scheduler.py   → config, client, ollama_client, brief, replies, cloud.bot_jobs (top level, scheduler.py:17) ;
                           voice, ollama_client.brain_pinned, cloud.full_picture.skip_reason (lazy)
  src\bot\voice.py       → config, ollama_client ; telegram_bot (lazy, "as bot"), ask, brief.claims_problem,
                           replies.date_error_reply, dates (lazy)

LAYER 7  the Telegram surface
  src\bot\telegram_bot.py → config, client.admin_client, ollama_client, scheduler.setup_scheduler (top level) ;
                            replies, brief, ask, performance, voice, dates, parsers, client.PortalUnavailable,
                            cloud.command_hooks ("as cloud") (lazy)

LAYER 8  entry points
  run.py                 → config, net_fix, bot.telegram_bot (build_telegram_application, post_init), ollama_client ; uvicorn "src.api.main:app"
  src\api\main.py        → config, client.admin_client, api.routes.{auth,dashboard,applications,crawler} → client, api.schemas
  python -m src.cloud.publish | src.cloud.full_picture | src.cloud.backfill
                         each sets CUDA_VISIBLE_DEVICES=-1 in its __main__ before anything can import torch
  root scripts           bootstrap.py → subprocesses ; audit_program.py → client + scheduler.passport_scan ;
                         download_passports.py → client + inspect_passports ; test_verified.py → client, dates
  root staging copies    telegram_bot.py, config.py, progress_builder.py (byte-identical, imported by nothing;
                         apply_bot_update.bat / install_sheets.bat copy them over src\; a test asserts the identity)
```

Why the lazy imports: `telegram_bot` imports `scheduler` at the top and `scheduler` imports `brief`; `voice` needs `telegram_bot`'s handlers and `telegram_bot` optionally needs `voice`; `brief.claims_problem` reuses `voice._numbers_in`; `records` needs readers from four packages that themselves import `sheet_hooks` or `command_hooks`. Importing inside functions breaks every cycle, keeps `voice` (and its httpx client) out of the process unless a voice path runs, and keeps `sentence_transformers` / `transformers` out of every process except the three CPU-only entry points. The bot process does import `src.cloud.bot_jobs` → `handoff` → `publish` (httpx and settings only) through `scheduler.py:17`, but never `embed`'s model. The subprocess jobs import only `src.sheets.*` / `src.verify.*` / `src.scraper.client` / `src.cloud.sheet_hooks` and never `src.bot.telegram_bot` (only `replies.split_text`, which needs just `telegram.error` and `telegram.helpers`).

Tests (`tests\`, 24 files + `conftest.py`, 1,152 cases at `8317741`; 2 skip by design in a checkout that has a real `.env`) sit beside this graph and fake it at the transport: `httpx.MockTransport` for the portal, Ollama, the voice service and Supabase (`FakeSupabase` enforces the SQL's rules), recording fake PTB objects for Telegram, `StubEmbedder` for the model, and an autouse fixture that turns publishing off in every test ([10 §2](10_TESTS_AND_VERIFICATION.md)).

---

## 4. Cross-cutting mechanisms

### 4.1 One portal session, and `PortalUnavailable` instead of empty results

- **Where:** `src\scraper\client.py`: `class PortalUnavailable(RuntimeError)` (`:66`, `__init__(self, reason: str, *, unreachable: bool = False)`), `portal_error_reason(e)` (`:80`), `_ended_on_login(resp)` (`:93`), `_ensure_session()` (`:294`), `_get_once()` (`:303`), `portal_get(path, params=None, timeout=60.0) -> httpx.Response` (`:314`), `fetch_html(path, timeout=60.0, params=None) -> str` (`:339`).
- **Contract:** one `httpx.AsyncClient` per process holds the PHP session cookie. `portal_get` logs in when there is no session and **checks that the login worked**; a GET whose final URL ends on `login.php` means the session expired → one fresh login and one retry → still `login.php` raises; HTTP ≥ 400 raises; `httpx.TimeoutException` / `TransportError` raise with `unreachable=True`; connect timeout is `min(timeout, 10)` s so a dead host fails fast while a 2 MB page keeps its read timeout. It never returns a login page or an error page as data.
- **The reply:** every caller turns the exception into `replies.portal_error_reply(what, e)` = `❌ Couldn't read the portal: <reason>.\n<what>: not available right now. Please try again in a minute.` (`replies.py:159-165`); the brief turns it into `not available (<why>)` per section and uses `.unreachable` to skip the rest of its reads; the full picture's `PortalSession` does the same per page (`full_picture.py:77-92`); a Supabase batch from a failed read is never sent (only a failed-read line).
- **Login:** `login()` (`:150`) GETs `login.php`, extracts `_csrf` (`parsers.extract_csrf_token`), POSTs `{"_csrf", "username", "password"}` (`:184`); a response still on `login.php` is a refused login. It is the only POST to the portal in the codebase (the Supabase POST/PATCH calls go only to `SUPABASE_URL`).
- **Singleton scope:** in the bot process `admin_client` is shared by every handler, the scheduler jobs and the REST API. Each subprocess builds its own (`auto_sync._fresh_portal_client()` even replaces it between steps, since each step runs its own event loop and closes the client); the backfill and the full picture build their own too. There is **no lock around `login()`**: two coroutines that find the session expired at once can both log in, which is harmless (each POST just renews the cookie); the brief reads sequentially on purpose ("one portal session, no parallel logins").
- **Legacy methods** (`get_consultation_requests`, `get_inquiries`, `get_calendar_events`, `get_student_full_profile`, `crawl_page`) still use `self.client.get` with a hand-rolled re-login and return `[]` / `{}` / `{"error": …}`; a rebuild should route them through `portal_get` ([03b §3.9](03b_FILES_src_scraper_llm_api_config.md), [04 §1.2](04_PORTAL_INTEGRATION.md)).
- **Why:** before `e0d47ab`/`f8fefa4` every failure returned `[]`, `login()` failures were ignored, and the bot said "No student payments were verified" when the portal simply had not been read ([09 R5](09_BLUEPRINT_RULES_AND_LESSONS.md)).

### 4.2 The all-pages students reader

- **Where:** `read_student_pages(params=None, *, all_pages=True) -> List[str]` (`client.py:454`) and `read_students(params=None, *, all_pages=True) -> List[Dict]` (`client.py:501`); `parsers.student_pager(html)` (`_PAGER_RE = Page\s+(\d+)\s+of\s+(\d+)(?:\s*·\s*([\d,]+)\s+students?)?`, `parsers.py:325`), `parsers.student_uids(html)` (`_UID_RE = student_edit\.php\?id=(\d+)`), `parsers.parse_students_page(html)`.
- **Algorithm:** page 1 with the caller's params (empty values and `pg` dropped), page N with `{**params, "pg": N}`; no `<table` → raise; page 1 with ≥ `STUDENTS_PER_PAGE = 50` rows but no pager → raise; the pager must name the page asked for ("the list changed while it was read"); `pages = max(pages, pager.pages)` follows a list that grows mid-read; more than `MAX_STUDENT_PAGES = 40` → raise; at the end fewer unique uids than the pager's total → raise. `read_students` parses each page **in a worker thread** (`client.py:512`), maps `StudentListLayoutError` to `PortalUnavailable`, and de-duplicates by `uid` (fallback key `("row", student_id, student_name, applied_date)`) keeping list order.
- **Used by:** `/verified*`, `/crosscheck*`, `/passports`, `/admitted`, pending/intake/applied answers, the passport watcher, `/stage`, the issue-date refresh, the verified-documents list, the `/sendmail` fallback, root scripts, and the Supabase `student` / `verification` / `pending_payment` readers (backfill, full picture). `/students` alone reads page 1 on purpose (the 50 newest), and its `student` batch is therefore **partial**.
- **Why:** on 28 Sep the list had 330 students on 7 pages; page-1 reads hid 274 of 322 verifications, the watcher saw 42 of 301 scans ([09 R2](09_BLUEPRINT_RULES_AND_LESSONS.md)). The Google sheets avoid paging altogether with the one-request `students.php?export=csv`. On 30 Sep the list had 340 students.

### 4.3 Strict dates

- **Where:** `src\dates.py` (unchanged since `e164679`: `parse_user_date(text, today=None, *, prefer_past=False) -> Optional[date]`, `user_date_problem(...)`, `has_date_hint(text)`, `parse_stamp(text) -> Optional[Stamp]`, `parse_portal_date(text)`, `stamp_on_day(stamp, day, applied=None)`, `yearless_day_problem(day, today)`, `local_today()`); `telegram_bot.normalize_date_input(text, strict=False)` (`:88`) with `_DATE_FILLER_RE` (`:80`); `replies.date_error_reply(raw, command="", reason=None)`; `ask.date_window(...)` (`ask.py:266`) for spans; `performance._range_dates` (`performance.py:93`) for the performance page's range line (also used by `records.performance_window`); `voice._words_date` for spoken dates.
- **Rules:** month names only as whole words next to a day number (`_MONTH` longest-first alternation, `\b`, numeric guards `(?<![\w/.:-])` / `(?![\w/.:-])`); day-first numbers; no year → this year, or last year with `prefer_past` when the day is still to come; an impossible date, two different dates, or no date → `None` plus a reason, **never today or another stand-in**. Words routed from free text are lenient (no date = today); a date given to a command is strict. "Today" is always `local_today()` in `REPORT_TIMEZONE = Asia/Dhaka`, never the PC clock. A performance range that cannot be read as two days in order publishes nothing (no stand-in day).
- **Portal stamps:** "Payment verified by NAME · 27 Sep, 17:19" has **no year**: stamps are read only from the row's own `.pf-by` element, matched on whole tokens, never before the student's "Applied On" day, and a day whose day-and-month has come round again since is `not available` (`yearless_day_problem`). A future day is `not available (a date in the future)`. The Supabase `verification` records use the same rule (`records.verification_day`; window `records.verification_window`, `records.py:564`).
- **Why:** "27 sep" matched inside the transfer-intake option "2027 SEPTEMBER", "8 Sep" inside "18 Sep", names read as months, and "31 Sep" silently became today ([09 R3, R4](09_BLUEPRINT_RULES_AND_LESSONS.md)). Tests pin "today" in every module that holds its own name for it (`tests\test_foundation.py:136` `pin_today`), since `ask.py` imports `local_today` by name ([10 §2.5](10_TESTS_AND_VERIFICATION.md)).

### 4.4 `reply_long`: Telegram's size and Markdown limits

- **Where:** `src\bot\replies.py`: `TELEGRAM_LIMIT = 4096`, `CHUNK_CHARS = 3900`, `telegram_len(text)` (UTF-16 code units: `len(text.encode("utf-16-le")) // 2`), `split_text(text, limit=3900)` (between lines; an overlong line is cut at its last fitting space), `markdown_to_plain(text)`, `is_markdown_error(e)`, `send_pieces(send, text, parse_mode="Markdown", *, first=None, limit=3900)`, `reply_long(message, text, parse_mode="Markdown", *, edit=None)` (`:122`), `send_long(bot, chat_id, text, parse_mode)`.
- **Contract:** every reply that grows with portal data goes through it; piece 1 edits the "⏳" message (a "not modified" edit counts as sent; another edit error falls back to a new message); a piece refused for its legacy Markdown ("Can't parse entities") is resent as plain text; other errors propagate. Every formatter keeps Markdown entities on one line, so a split between lines never cuts an entity. Cross-check and passport reports use `telegram_bot._send_blocks` (`:1720`) to pack whole per-student cards; the performance report uses `performance.message_pieces` (`performance.py:247`) to pack whole consultant records; the watcher packs whole alert blocks (`scheduler._alert_messages`, `:104`); subprocess jobs use `split_text` with plain text.
- **Escaping:** portal text inside Markdown goes through `brief.esc` (`telegram.helpers.escape_markdown(str(v), version=1)`); inside `*bold*` a literal `*` becomes `∗` (`_bold_safe`); code spans are never nested inside `_italics_`.

### 4.5 The claim checker and "the LLM never writes a figure"

- **Where:** `src\bot\brief.py`: `claims_problem(text, facts, extra_words=()) -> Optional[str]` (`:456`), `check_summary(summary, facts, *, is_today=True)` (`:519`), `llm_summary(facts, *, is_today=True)` (`:541`); `src\llm\ollama_client.py`: `answer_agent_query(query, facts)`, `_answer_query_fallback(query, facts)`, `prompt_fits(what, *texts)`; `src\llm\prompts.py`: `SYSTEM_AGENT_CHAT`, `AGENT_SCHEMA`.
- **The four LLM uses and their gates:** (1) free-text "unknown" questions: the model returns fact **indices** under a JSON schema; the bot prints those facts verbatim; (2) the brief's summary: kept only if `claims_problem` returns `None`; (3) `/sendmail` drafts: always shown in full and sent only after the user types SEND; the "Ollama is down" fallback text is detected and replaced by a template; (4) Jennie: routing is a command enum; English sentences pass `claims_problem`; Korean sentences are built in code. The performance commands and everything published to Supabase are built by code only; the embedding model only turns text into vectors, it writes nothing.
- **`claims_problem` order:** empty → non-ASCII script → off-topic words (visa, passport, conversion, intake, rate, percent, "prepared by", YTD, `%`) → vague or comparing count words (both, several, most, more, than, increased, ordinals…) → negations → every number (digits or words) must occur in the facts → every word must be a fact word, a connector or an allowed extra word (after plural folding and synonyms) → per clause, the numbers must be the figure of the fact whose keywords the clause shares most (keywords weighted `1/df` with exact `Fraction`s). Anything that fails is dropped, never "fixed".
- **Prompt size:** Ollama silently truncates a prompt longer than `num_ctx` (keeps about its last half; measured: every over-long prompt came back as 1,538 tokens at 3072), so `prompt_fits` estimates `chars / 2.4` and requires `num_ctx - 512` free; `answer_agent_query` refuses to call when it does not fit.
- **Why:** the LLM-written executive brief of 28 Sep invented passport numbers, dates of birth, a visa count and a conversion rate ([06 §4](06_LLM_AND_JENNIE_VOICE.md), [09 R7](09_BLUEPRINT_RULES_AND_LESSONS.md)).

### 4.6 Live data only

- Every command and the brief read the portal **when asked**; no answer comes from a stored copy. Removed on the way: the hard-coded `AUDIT_REGISTRY` "pre-audited" ledger of 10 Sep and the static `/passports` text (`40da0e6`), the dashboard placeholders (`f8fefa4`), the stand-in amounts and intakes (`e0d47ab`), and the self-computed performance figures (`ce23535`).
- The only local data a live answer uses is labelled: the brief's section 5 is "from the last automated check, not live" (`results.json`).
- **The Supabase copy is written, never read, by the bot.** It is a snapshot for Jeannie: every record carries `read_at` (the time of the read that last **changed** it), and freshness comes from `hg_runs.finished_at` / `status`. Jeannie must date what she says ([13 §3.7](13_SUPABASE_PUBLISHING.md)).
- Caches are keyed by the **identity of the thing read**, never used as truth about the portal: the watcher remembers `uid|passport_<uid>_<unix upload time>.<ext>` (a re-upload is a new key); a saved scan is reused only if it is that exact upload, ≥ 1000 bytes and not HTML; OCR text is cached by `file:size:mtime`; document downloads are fingerprinted by the portal's own file names; the issue-date cache is a fallback and a difference based on a cache older than 26 h is downgraded to UNREADABLE; the Supabase hash state only decides what to **send**, never what to say.
- Guardrail file `.agents\rules\hangeul_operational_guardrails.md` rule 5 ("live auditing, zero stale data") is the owner's standing rule ([04 §2.2](04_PORTAL_INTEGRATION.md)).

### 4.7 Pending payments and window applications are never added together

- Two different portal objects: **pending payments** = students whose payment is not yet verified (`students.php?status=pending`; the sidebar badge `Pending Payments <span class="badge">N</span>`; the dashboard tile "Pending payment" in the "Direct / legacy pipeline" group); **window applications under review** = applications to university admission windows (`window_applications.php?status=under_review`, each row's own `.status-pill`; the tile "Under review" in the "Admissions flow" group).
- Everywhere they appear they are two lines with two sources: `brief.section_portal` (`• Pending payments: N (students.php?status=pending)` / `• Window applications under review: N (window\_applications.php)` / `_(two separate figures, never added together)_` and two separate facts), `ask.answer_pending` and `ask.answer_window_review` (each ends by naming the other as a separate figure), `/stats` (`_Pending payment and Under review are separate figures._`). The brief-summary prompt forbids combining them and the claim checker's per-clause rule cannot attach one's number to the other. In Supabase they are two kinds (`pending_payment`, `window_application`) and two separate figures in the brief report's `data`.
- **Why:** guardrail rule 2 ("metric decoupling"), written by the owner before this work.

### 4.8 Other mechanisms every feature relies on

| Mechanism | Where | Contract | Why |
|---|---|---|---|
| Explicit allow-list authorisation | `telegram_bot.is_authorized` (`:22`), `Settings.authorized_ids()` | chat id must be `TELEGRAM_ADMIN_CHAT_ID` or in `TELEGRAM_AUTHORIZED_CHAT_IDS`; **empty list → refuse everyone** (log the sender's id; `/start` shows it) | the baseline bound the first sender as admin, again after every restart (`c5c1a7c`) |
| Secret redaction | `src\__init__.py:25-79`: `_TOKEN_RE` (`:36`), `_SECRET_PATTERNS` (`:41`), `redact(text)` (`:52`), `_RedactBotToken` (`:59`), attached at `:77-79` | 7 patterns: `bot\d{6,}(?::\|%3[Aa])[A-Za-z0-9_-]{30,}` → `bot<token>`; `Bearer <8+>` and `apikey: <8+>` values → `<redacted>`; `sb_secret_…`, `sb_publishable_…`, `sbp_<16+>`; JWT shapes → `<jwt>`; on `httpx`, `httpcore`, `httpcore.connection/.http11/.http2/.proxy/.socks` and `hangeul.cloud` (a filter on a logger does not see its children's records) | 2,831 tokens had been logged in plain text (`0fce479`, `e205327`); the Supabase keys travel in headers (`36ae72e`) |
| Subprocess isolation | `scheduler._run_module` (`:392`), `telegram_bot._run_report_module` (`:2215`), `handoff.start` (`handoff.py:101`) | venv `python.exe -m <module>`, `cwd=BOT_ROOT`, UTF-8, no window, timeout 3600 s / 180 s / the child's own deadline, never raises; the publisher's stdin is `DEVNULL` and its output goes to the log, never a caller's pipe | a crash, hang or GPU leak in Google/OCR/embedding work cannot take the bot down; each run starts with clean memory |
| Atomic writes | watcher memory, scans, `results.json`, sheets state, fillers, `cloud_state.json`, handoff files, `student_index.json` | write `*.part` / `*.tmp`, then `os.replace` | a crash never leaves half a file; a reader sees none or all |
| Job locks | `data\auto_sync.lock`, `data\verification\auto_verify.lock`, `data\cloud\publish.lock` | PID inside (the first two; ignored if the PID is dead or the file is older than 2 h / 4 h); an OS byte lock that the OS frees when its holder dies (the third) | one sync at a time even if one is started by hand; one writer of the hash state |
| Staging copies | root `telegram_bot.py`, `config.py`, `progress_builder.py` | byte-identical to `src\bot\telegram_bot.py`, `src\config.py`, `src\sheets\progress_builder.py`; `tests\test_cloud.py:1126` and `tests\test_performance.py:1008` assert it | `apply_bot_update.bat` and `install_sheets.bat` copy them over `src\` |
| Settings | `src\config.py` `Settings(BaseSettings)` (`extra="ignore"`, `:144`) | Windows env > `.env` > code default; `MOCK_MODE` defaults to **True** (demo data); `CLOUD_PUBLISH_ENABLED` defaults to False and must be written `true` or `false`, **never empty** (`CLOUD_PUBLISH_ENABLED=` raises a `ValidationError` and the bot does not start) | one place for every key ([02 §4](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |
| Telegram reachability | `src\net_fix.py` `apply_telegram_dns_fix() -> str \| None` | resolve `api.telegram.org`; if no resolved IP accepts TCP 443 within `PROBE_TIMEOUT = 3.0` s, try `CANDIDATE_IPS` and patch `socket.getaddrinfo` for that host only; `TELEGRAM_API_IP` forces an IP, `TELEGRAM_DNS_FIX=false` disables (Windows environment only) | the network the bot was built on returned an unreachable Telegram address; no admin rights needed |
| Read-only by construction | `client.py` (one POST, `:184`), test fixture `portal` raises on any non-GET, audit and dry-run network guards | findings are reported with a `student_edit.php?id=<uid>` link for staff; Supabase is written only through `hg_sync` and `hg_runs`, never with DDL | guardrail rules 1 and 7; D12 |

### 4.9 The Supabase copy: after the work, in another process, one line when it fails

- **Where:** the hooks `src\cloud\command_hooks.py` (commands, free text, performance), `src\cloud\bot_jobs.py` (brief, watcher), `src\cloud\sheet_hooks.py` (sync, missing report, stage report, issue refresh); the builders `src\cloud\records.py`; the file and child `src\cloud\handoff.py`; the engine `src\cloud\publish.py`; the model `src\cloud\embed.py`; the readers `src\cloud\backfill.py` and `src\cloud\full_picture.py`. Every call site outside `src\cloud\` is listed in [03d §12](03d_FILES_src_cloud.md).
- **On or off:** only when `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `CLOUD_PUBLISH_ENABLED=true` are all set (`publish.enabled`, `publish.py:103`); while off, nothing is kept, built, written or started anywhere; the bot-process hooks (`command_hooks.active`, `bot_jobs.hand_over`) and the full picture also refuse mock mode (demo data is not the portal's). On since 30 Sep 22:27.
- **Contract for every hook:** keep what a read returned (`seen`) only after it succeeded; build and hand over **after** the job's own work (the reply, the Telegram brief, the sheets, the alerts); never await the publisher; never raise into the job; never print into a button report's stdout; a build that fails or takes over 30 s (bot jobs) is one log line.
- **What goes:** 26 kinds ([13 §5](13_SUPABASE_PUBLISHING.md)), one record per entity, only changed rows (content hash, D9), deletes only from a **complete** read, per (kind, scope), through `p_all_keys` on the last call (D10). A failed read sends no batch at all.
- **Failure isolation (D6):** Supabase down, slow, refusing the key, or the model missing → one WARNING line for the whole run, the run's `hg_runs` row PATCHed `failed`, the hash state not advanced (so the rows go again next time); no retries within a run, no Telegram alert, no outbox beyond the hash state.
- **Why a separate process:** the bot process has torch with CUDA for the passport OCR and must keep its event loop free; the button reports' stdout is their reply; and one lock-holding writer keeps the hash state consistent ([13 §9](13_SUPABASE_PUBLISHING.md)).

### 4.10 Portal-content hygiene: Cloudflare's stand-ins and the portal's filler words

- **Cloudflare:** the portal is served through Cloudflare, whose e-mail obfuscation rewrites every address in the HTML to `[email protected]` inside `a.__cf_email__[data-cfemail=HEX]` (or a `span`), and every `mailto:` to `/cdn-cgi/l/email-protection#HEX`. `parsers.decode_cf_emails(node)` (`parsers.py:64-97`; byte decoder `_cf_address`, `:24-39`: first byte = key, each next byte XOR key = one UTF-8 byte; the result must contain "@", be printable, have no space) restores them in place, **at every soup, before any `get_text`**: 13 in `parsers.py`, 2 in `client.py` (`:614`, `:721`), 1 in `ask.py` (`:690`), 1 in `verified_docs.py` (`:47`); `tests\test_cloud_cf_email.py:287` fails on any unwrapped `BeautifulSoup(` in `src\`. An undecodable stand-in is removed from longer text (`_EMAIL_HIDDEN_GAP_RE`, `parsers.py:328`) and blanked as a filler in records. The CSV export and input `value` attributes are not rewritten ([04 §1.4](04_PORTAL_INTEGRATION.md)).
- **Filler words:** a whole cell of "N/A", "None", "null", "nil", "Pending", "TBD", "Not available/applicable/provided", marks only ("—", "--"), or the Cloudflare stand-in is **no value**: `records.is_filler(value, field)` (`records.py:230`, words `FILLER_WORDS` `:206`) blanks it in `data`, leaves it out of the text, and names the field in `data.blank_on_portal` (`_mark_blank`, `:266`). "Pending" in a status field (`is_status_field`, `:223`: status/stage/result/step, or Payment, Bank Certificate/Solvency, VIN App/Required) is a real state and stays. The reader's own stand-ins ("Unassigned", "Event", "Dashboard") are blanked too. Applied to the Supabase records only; the Telegram replies show the portal as it is ([13 §6](13_SUPABASE_PUBLISHING.md)).
- **Why:** dry run 1 (29 Sep 14:39) found 45 "N/A", "None", "--" and 7 "PENDING" cells kept as values; dry run 2 (15:37) found the stand-in in all 333 student e-mails and 1,005 of 1,014 consultation contacts, and in the bot's own replies ([09 R28, R29](09_BLUEPRINT_RULES_AND_LESSONS.md)).

---

## 5. Concurrency model

### 5.1 One event loop

`run.py` ends in `asyncio.run(start_all())`. Inside that one loop:

| Tenant | What it is | Blocking rules |
|---|---|---|
| PTB `Application` | built with `Application.builder().token(token).post_init(post_init).build()` (`telegram_bot.py:2374`), i.e. PTB defaults: **updates are processed one at a time, in order** (no `concurrent_updates`), handlers `block=True` | a long handler (a 62-scan cross-check ≈ 10 min) delays every later typed update ([11 §B14](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)); only the voice handler is `block=False` (`telegram_bot.py:2432`) |
| PTB updater | `app.updater.start_polling()` (long polling) | — |
| uvicorn | `await server.serve()` (it is what keeps `start_all` running; when it returns, the finally stops the updater and the app) | a failed bind on port 8000 (`[Errno 10048]`) ends the process after polling has briefly started (seen again on 30 Sep 20:36, §6) |
| APScheduler | `AsyncIOScheduler()` (`scheduler.py:24`, default local timezone; cron jobs pass `ZoneInfo("Asia/Dhaka")` explicitly) started inside `build_telegram_application()` → `setup_scheduler(app)` (`scheduler.py:419`); jobs are coroutines run on the same loop | jobs exist only when a valid Telegram token exists (no token → no application → no scheduler) and `ENABLE_SCHEDULED_REPORTS=true` |
| Background tasks | `application.create_task(warm_brain(), name="brain-warm-up")` or `create_task(ollama_client.unload(), name="brain-release")` in `post_init`; `voice._background(coro)` (strong refs in `_tasks`); `command_hooks._background` → `loop.create_task(asyncio.to_thread(build_and_submit), name="cloud-handoff")` (strong refs in `command_hooks._tasks`, `:71`, `:151-160`) | startup never waits for the brain; a handler never waits for its Supabase handoff |

Everything on the loop must `await` I/O and must not burn CPU. Known synchronous spots: `_send_gmail` (SMTP, up to its 30 s timeout) and small parsers of small pages (e.g. `get_dashboard` parses `index.php` on the loop).

**Copy this model or not?** Not as it is. What it costs today: one update at a time means a date-range cross-check (no cap on OCR runs, ~10 s a scan; a 62-scan check took ~10 min) blocks every other typed command ([11 §B14](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)); there is **no global error handler** (`add_error_handler` is never called, [03a §8.9](03a_FILES_src_bot.md)), so an unexpected exception in a handler is only logged by PTB and the user gets no reply; and `_send_gmail` (`telegram_bot.py:1148`) blocks the loop while SMTP talks. **Rebuild rule** (also [09 Part C](09_BLUEPRINT_RULES_AND_LESSONS.md)):
1. Either build with `.concurrent_updates(True)` and put a per-chat `asyncio.Lock` around every handler that reads or writes `context.user_data` (`awaiting_date_for`, `email_flow`), or keep sequential updates and register only the OCR-heavy handlers (`/crosscheck*`, `/audit`, `/passports`) with `block=False`, as the voice handler already is.
2. Cap OCR runs per request (e.g. 20 scans) or ask the user to confirm a bigger run, and say how many are left.
3. Register `app.add_error_handler(...)` that logs the traceback and replies one short plain line ("Something went wrong on my side; it is logged").
4. Run the SMTP send with `await asyncio.to_thread(_send_gmail, ...)`.
5. Keep any second destination (here Supabase) off the loop and out of the process, as §4.9 does.

### 5.2 Worker threads (`asyncio.to_thread`)

| Call site | Work moved off the loop | Why |
|---|---|---|
| `client.py:512` `parse_students_page` (in `read_students`) | ~1 MB per page × 7 pages | parsing would stall Telegram for seconds |
| `client.py:349`, `:360` `consultation_table`, `consultation_view` | `consult_requests.php` (~2 MB unfiltered, ~110 KB per day) | same |
| `client.py:559` `parse_pending_payments`, `:567` `parse_window_applications`, `:444` `parse_consult_performance` | brief / answers / performance | same |
| `client.py:711` `validate_passport_data` (in `audit_student_passport`) | EasyOCR + MRZ on the CPU (~10 s per scan) | **the incident:** the watcher ran OCR on the loop and the bot "went deaf" for ~3.5 min every half hour (`7241465`) |
| `ask.py:773` `dashboard_facts`, `:893` `parse_pending_payments`, `:897` `parse_students_page`, `:1404` `calendar_items` | free-text answers | same |
| `brief.py:628` `read_document_check` | reads the 1.8 MB `results.json` | file I/O |
| `bot_jobs.py:83` `hand_over` (`asyncio.wait_for(asyncio.to_thread(work), timeout=30)`), `command_hooks.py:157`, `handoff.py:144` `submit_async` | building the records and writing the ~1 MB handoff file | the watcher's full student list must not stall Telegram |
| `stage_report.py:90` `parse_progress_page` | subprocess, 4 pages at a time (`asyncio.Semaphore(PROGRESS_READERS=4)`) | — (the backfill reuses `read_progress` in a worker thread) |

### 5.3 Locks

| Lock | Where | Protects | Rule |
|---|---|---|---|
| `_ocr_lock = threading.RLock()` | `ocr_validator.py:67` | the shared CPU `easyocr.Reader(['en'], gpu=False)` and the PDF's `<name>_extracted.jpg` | `validate_passport_data` holds it for the whole audit; `_ocr_items` takes it again around `readtext`; `get_ocr_reader()` builds the reader with double-checked locking. So the watcher and a `/crosscheck` never OCR at the same time, and the loop stays free |
| Scan save without yielding | `client.audit_student_passport` (`:630-713`) | `passports\<uid>_<file>` | the "already saved?" check, the `.part` write and the `os.replace` happen with no `await` between them, so two coroutines never write one scan twice |
| `_voice_turn()` (`asyncio.Lock`, one per event loop, created lazily) | `voice.py:99-120` (`_turn = None` at `:99`, `async def _voice_turn()` at `:103`, `asyncio.timeout(VOICE_TURN_WAIT)` at `:113`, `VoiceServiceBusy` at `:116`, release in `finally` at `:119-120`) | the voice service (it runs one request at a time) | every STT, TTS, filler render and spoken brief takes a turn; waiting more than `VOICE_TURN_WAIT = 240 s` → "busy" |
| `auto_sync.lock`, `auto_verify.lock` | files | overlapping job processes | PID + age check; the full picture and the backfill only **read** `auto_sync.lock` to stay out of a running sync |
| `publisher_lock` | `publish.py:208-271`, file `data\cloud\publish.lock` (`msvcrt.locking(fd, LK_NBLCK, 1)` on Windows, `fcntl.flock` elsewhere, retried every 0.25 s; re-entrant in one process via `_mutex` RLock) | the hash state and "one model in memory" | publishers and the backfill wait `LOCK_WAIT = 20 * 60` s, then drop the handoff with one line; the full picture waits 120 s, then skips its hour; the OS frees it if the holder dies |
| APScheduler `max_instances=1` | every job | one run of a job at a time | a watcher run with an empty memory can audit for 20 min |
| The voice service's own lock | `service.py` | its models | a request waiting > 120 s (`JENNIE_LOCK_WAIT_S`) gets 503 |

### 5.4 APScheduler settings

| Job id | Trigger | `misfire_grace_time` | Other options | Runs |
|---|---|---|---|---|
| `daily_executive_briefing` | `CronTrigger(hour=18, minute=5, timezone=Asia/Dhaka)` from `DAILY_REPORT_TIME` (unparsable → 18:05) (`scheduler.py:435-444`) | **600 s** (the default would be 1 s: a stalled moment at 18:05 must not drop the brief) | `replace_existing=True, max_instances=1, coalesce=True` | in the loop; hand-over last |
| `passport_upload_watcher` | `IntervalTrigger(minutes=30)` (`:448-456`) | default (1 s) | same | in the loop, OCR in threads, stops starting audits after `WATCHER_BUDGET_SECONDS = 1200` (`scheduler.py:35`); hand-over last |
| `portal_sync` | `IntervalTrigger(minutes=15)` (`:459-466`) | default | same | subprocess |
| `missing_info_report` | `CronTrigger(hour=9, minute=5, timezone=Asia/Dhaka)` (`:469-477`) | 3600 s | same | subprocess |
| `passport_issue_refresh` | `CronTrigger(hour=8, minute=30, timezone=Asia/Dhaka)` (`:480-488`) | 3600 s | same | subprocess |
| `brain_keep_warm` | `IntervalTrigger(minutes=10)` (`:491-498`) | default | same | in the loop; returns at once unless `brain_pinned()` |
| `cloud_full_picture` (new) | `IntervalTrigger(minutes=FULL_PICTURE_MINUTES=60, start_date=now + FULL_PICTURE_FIRST_MINUTES=7.5 min)` (`:365-366`, `:501-509`) | default | same | subprocess `-m src.cloud.full_picture` (CPU only); a no-op while publishing is off; skipped near a quiet window or during a sync |

The start line (`scheduler.py:512-513`): `Scheduler active: daily briefing set for 18:05 (Asia/Dhaka), passport watcher running every 30m, portal sync every 15m, missing-info report 09:05, Supabase full picture every 60m.` (the last clause only while publishing is on).

**Why these times, and what is configurable.** The times (18:05, 09:05, 08:30) and intervals (30, 15 and 10 minutes) are **inherited from the baseline** (`HANDOFF.md:120-123` lists them; no reason is recorded anywhere). The hourly full picture's 7.5-minute offset puts it midway between the sync's 15-minute and the watcher's 30-minute beats. Only the brief's time is a setting (`DAILY_REPORT_TIME`); the rest are literals in `setup_scheduler` (`scheduler.py:450` watcher 30 min, `:461` sync 15 min, `:471` missing report 09:05, `:482` issue-date refresh 08:30, `:493` brain keep-warm 10 min, `:503` full picture 60 min) and the quiet windows are a literal in `backfill.py:57` (`QUIET_WINDOWS = ((18, 0, 18, 10), (8, 25, 8, 40), (9, 0, 9, 10))`). The constraints that do matter: the 08:30 issue-date refresh (~290 page reads) must finish before the 09:05 report that uses it; an idle sync takes ~30 s and an idle watcher run ~9 s, so both fit their intervals easily; the watcher's own budget (20 min) must stay below its 30-minute interval, and `max_instances=1` skips a run rather than overlapping; the full picture must never read the portal into a quiet window, so it checks before every page. **Rebuild rule:** make every time, interval and quiet window a setting (e.g. `WATCHER_INTERVAL_MIN`, `SYNC_INTERVAL_MIN`, `MISSING_REPORT_TIME`, `ISSUE_REFRESH_TIME`, `FULL_PICTURE_INTERVAL_MIN`, derive the quiet windows from the job times) and check these constraints at start-up.

Interval jobs first fire one interval after the bot starts (the full picture 7.5 min after), so a restart shifts their phase (after the 30 Sep 22:27:37 restart: full picture at 22:35, 23:35; sync at 22:43, 22:58, …; watcher at 22:57, 23:27, …, in the same second as a sync start). Do not restart between 18:00-18:10, 08:25-08:40, 09:00-09:10, or while `check_status.bat` shows a `-m src.sheets.auto_sync` or `-m src.cloud.*` child ([02 §9.2](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).

### 5.5 GPU and CPU placement

| Work | Device | Why |
|---|---|---|
| Passport OCR (`ocr_validator`, watcher and cross-checks) | **CPU** (`gpu=False`) | keeps the 8 GB RTX 5060 for Ollama and the document verifier; ~10 s per scan is fine every 30 min |
| Document OCR (`doc_verifier`, in the sync subprocess) | GPU (`gpu=torch.cuda.is_available()`), 6 students per run, fresh process | one long process grew GPU memory until Windows spilled it to RAM (90 → 570 s per student) |
| LLM (`qwen3:4b-instruct`, `num_ctx` 3072, flash attention + q8_0 KV) | GPU, 2.62 GiB; loaded on demand, `keep_alive "5m"` (pinned `-1` only with voice on) | idle GPU ~1.0-1.2 GB with voice off |
| Embeddings (gte-small, in the publisher, full-picture and backfill children) | **CPU only**, `CUDA_VISIBLE_DEVICES=-1` set before torch (`embed.prepare_process`, `embed.py:60`), float32 (`embed.py:222`) | 0 VRAM measured (369 `nvidia-smi` samples in dry run 3); ~14 ms a short record; 0.86-1.57 GB RAM; the GPU stays with Ollama and OCR (R12) |
| Voice STT / TTS (off) | Whisper large-v3-turbo on the GPU per request if ≥ 3.0 GB free (CPU medium otherwise); CosyVoice2 CPU-resident, borrowed onto the GPU if 3.8 GB free | the card cannot hold brain + ears + voice + desktop at once ([02 §8](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)) |

---

## 6. Start-up and shutdown sequence

1. `run.py` top: if `sys.stdout` / `sys.stderr` are `None` (pythonw), reopen them as `hangeul_stdout.log` / `hangeul_stderr.log` (append, UTF-8, line-buffered); else reconfigure them to UTF-8.
2. `import src…`: `src\__init__.py` sets the CA-bundle variables if `data\windows-ca.pem` exists (it does not on this PC) and installs the secret-redaction filter on its 8 loggers.
3. `logging.basicConfig(level=INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")` with `FileHandler(hangeul_bot.log)` + `StreamHandler(stdout)`.
4. `start_all()`: `rich` banner; `apply_telegram_dns_fix()`; `ollama_client.check_health()` (`GET /api/tags`; it does not wait: after a reboot Ollama may answer seconds later, logged as "Ollama not reachable at http://127.0.0.1:11434"); `uvicorn.Config("src.api.main:app", host=API_HOST, port=API_PORT, log_level="info")`.
5. `build_telegram_application()` (`telegram_bot.py:2367`): no valid token (empty or `your_telegram_bot_token_here`) → `None` (API only, **no scheduler**); else **46** `add_handler` calls in the order of [03a §8.2](03a_FILES_src_bot.md) (42 `CommandHandler` names, 3 `CallbackQueryHandler`s for `^missing:`, `^stage:`, `^stagei:`, 1 free-text `MessageHandler(filters.TEXT & ~filters.COMMAND)`), the 47th (voice) only when `JENNIE_VOICE_ENABLED`, then `setup_scheduler(app)` → 7 jobs → `scheduler.start()` and the start line. Importing the scheduler also imports `src.cloud.bot_jobs` (no model, no network).
6. `async with telegram_app:` (initialize) → `await telegram_app.start()` → `await post_init(telegram_app)` (`telegram_bot.py:2314`, called by `run.py` itself: PTB 22 runs the builder's `post_init` hook only inside `run_polling`/`run_webhook`): `set_my_commands` (13 entries; log `Successfully set 13 bot menu commands (set_my_commands).`, counted with `len(commands)` since `bbd8f98`), send and pin the cheat-sheet to the admin chat (on every start), then the brain warm-up (voice on) or release (voice off, this PC) task.
7. `await telegram_app.updater.start_polling()` → `await server.serve()` (runs until shutdown).
8. Shutdown (`KeyboardInterrupt`/`SystemExit`, `stop.bat` kill, or `serve()` returning): `finally: updater.stop(); app.stop()`; exit 0. `stop.bat` uses `Stop-Process -Force` on the redirector pair and any `-m src.*` children, including **publishers** and the **full picture** (a publisher started by the bot has the bot as parent; one started by a sync is an orphan): a running sync is killed mid-write, and a killed publisher leaves its handoff file in `data\cloud\pending\` (pruned after 6 h, not re-sent; its rows go again on the next read of their scope) and an `hg_runs` row without `finished_at`. Stop only at quiet moments.

**After a reboot** (observed 30 Sep 20:35, [02 §9.6](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)): the Startup shortcut and the watchdog's first tick both started a copy within seconds; the second copy polled briefly, pinned a second cheat-sheet, then failed to bind port 8000 (`[Errno 10048]`) and stopped itself 3 s after starting. Nothing else happened, but a rebuild should take its single-instance lock **before** polling and give the watchdog a grace period after boot ([09 R15, W14](09_BLUEPRINT_RULES_AND_LESSONS.md), [11 B24](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).

---

## 7. Design choices and the reason for each

| Choice | Reason |
|---|---|
| Scrape the owner's portal read-only instead of asking for an API | the portal has no API; the owner forbids any write (guardrails 1, 7) |
| One process for bot + scheduler + API | one session, one loop, one supervisor; the API reuses the bot's reader |
| Heavy/Google jobs as subprocesses | isolation from crashes and GPU leaks; each gets a fresh session and fresh GPU memory |
| Long polling, not a webhook | no public endpoint, no TLS certificate, works behind the ISP |
| Parse by header names and CSS classes, after decoding the CDN's rewrites | the portal changed its layout three times in September 2026, and Cloudflare rewrites every e-mail address |
| The portal's own counters (status tabs, badges, tiles, date filter) over counting capped lists | `consult_requests.php` lists only the newest 500 requests |
| CSV export for the sheets, list pages for the bot | the CSV is one request with every field but some of its columns are stale (`Current Stage`, `Current Status`, `Progress %`); the list pages carry the live stage and the stamps |
| Code computes, the LLM only chooses or words under a checker | the small local model invents facts when given slots to fill |
| "Performance" = the portal's own Consultant Performance page, shown as it is | the owner's correction of 30 Sep 13:11; the first version computed its own team figures |
| One small model for everything, one option set | fits beside the voice in 8 GB; a changed `num_ctx` reloads the model |
| Local OCR, local LLM, local voice, local embeddings | answers contain student names: the bot's processing stays on the PC; the only outside copies are the portal's own, Telegram, Google, Gmail and, by the owner's decision D1, Supabase |
| A second, complete copy in Supabase as structured rows + text + 384-number vectors | the owner's spec (D1-D13): Jeannie answers from rows (R7 holds there too) and uses the vectors only to find them |
| Hand the copy to a CPU-only child through a file, after the work | the bot keeps its loop and its GPU; a button report's stdout stays its reply; Supabase can never delay or break Telegram, Sheets or Drive (D6) |
| Only changed rows (local hash state + server upsert by hash), deletes only from complete reads | upload what changed (D9) and hard-delete what is gone (D10) without ever deleting on a partial read (R2, R5) |
| The schema lives in the reader's repo; the bot only writes rows | D12: one owner of the contract; the bot never runs DDL |
| Git with one commit per change, root staging copies kept identical | every step revertible; the legacy updater must not roll back fixes |
| Logon-based autostart + a 5-minute watchdog, not a Windows service | no admin rights needed; BIOS power-on + auto sign-in cover power cuts |

The rules a new bot must follow, with the incident behind each, are in [09_BLUEPRINT_RULES_AND_LESSONS.md](09_BLUEPRINT_RULES_AND_LESSONS.md); the Supabase layer as a spec is [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md).
