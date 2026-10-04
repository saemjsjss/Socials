# 02 — Environment, setup and operations

What's in this file: the PC the Hangeul BOT runs on, where every file lives, a from-scratch install
(Python venv, Ollama, Google sign-in, Gmail, Telegram, and the optional Supabase publishing: its packages,
the embedding-model cache, the Supabase CLI, the Jeannie repo and its migrations), every `.env` key with its
default, how the bot process is started, supervised and kept to one instance, the logs, the local files of
the Supabase publish layer, the GPU memory budget with the lessons learned the hard way, and day-2
operations (deploy, restart, roll back, what a reboot does, re-enable the voice).

Sibling files: the LLM and the voice assistant are in [06_LLM_AND_JENNIE_VOICE.md](06_LLM_AND_JENNIE_VOICE.md);
the Telegram commands and scheduled jobs in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md);
the Supabase publish layer itself (records, kinds, `hg_sync`, the Jeannie schema, the backfill) in
[13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md) and its file map in [03d_FILES_src_cloud.md](03d_FILES_src_cloud.md);
the credential files and the key list in [secrets/README.md](secrets/README.md) (delete that folder before sharing).
Also: [portal integration](04_PORTAL_INTEGRATION.md), per-file references ([src\bot](03a_FILES_src_bot.md),
[scraper / llm / api / config](03b_FILES_src_scraper_llm_api_config.md),
[sheets / verify / root scripts](03c_FILES_sheets_verify_root_scripts.md)),
[sheets and document check](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md),
[history stage by stage](08_HISTORY_STAGE_BY_STAGE.md), [open items](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md),
[architecture](01_ARCHITECTURE.md), [blueprint rules](09_BLUEPRINT_RULES_AND_LESSONS.md), [tests](10_TESTS_AND_VERIFICATION.md),
and the pack index [00_INDEX.md](00_INDEX.md).

**Pack written:** 29 Sep 2026 at `c17d887`. **Refreshed:** 30 Sep 2026 (Asia/Dhaka) at `8317741`
(branch `main`, 48 commits, 113 tracked files, working tree clean, no remote). Facts were read from the code
at that head, from Windows itself (`Get-ScheduledTask`, `nvidia-smi`, `ollama ps`, the Startup folder), from
the logs and data files (counts only), from the session notes and from the workflow results of 29-30 Sep.
`path:line` means a line in `C:\Hangeul\BOT` at `8317741`. Secret values are never shown: they are "value in
secrets/bot.env (KEY_NAME)".

---

## 1. The PC

| Item | Value (measured on 29 Sep 2026 unless stated) |
|---|---|
| Machine name / account | `SAEMPC`, local account `User` ("Password required: No"; Windows signs in automatically) |
| OS | Windows 10 Pro, build 10.0.19045 |
| CPU | AMD Ryzen 5 8600G (6 cores / 12 threads) with **Radeon 760M integrated graphics** |
| GPU | **NVIDIA GeForce RTX 5060, 8 GB** (8151 MiB reported by `nvidia-smi`), driver 616.92, Blackwell (sm_120) → needs PyTorch **cu128** wheels |
| RAM | ~16 GB (14.9 GB usable) — tight when the voice service runs (section 8.2, lesson 10). Each Supabase publisher process adds 0.06-0.9 GB for a few seconds (its log line gives the peak; 1.57 GB in the first dry-run backfill, which embedded everything) |
| Disk | **One drive only: C:** (1 TB NVMe; 364 GB used, 589 GB free). There is **no E:** any more |
| Python | 3.12.10 from python.org, with the `py` launcher (`C:\Users\User\AppData\Local\Programs\Python\Launcher\py.exe`); the real interpreter is `C:\Users\User\AppData\Local\Programs\Python\Python312\` |
| Ollama | 0.34.4, installed per-user in `C:\Users\User\AppData\Local\Programs\Ollama\` (`ollama app.exe` tray app starts `ollama.exe serve`) |
| Git | used locally only: repo `C:\Hangeul\BOT`, branch `main` at `8317741`, **no remote** (nothing has been pushed; push only if the owner asks and gives the URL). Six build worktrees are still registered (`git worktree list`): `C:\Hangeul\JARVIS\cloud\{core,jobs,inproc,commands,all,release}` on the branches `cloud/*` (`cloud/release` = `8317741`, the others older); see §2 |
| Power-cut recovery | BIOS "power on when AC power returns" + Windows auto sign-in (both set by the owner); no UPS was detected. Everything starts at sign-in (Startup shortcut + watchdog task), not as a Windows service. What a reboot does in practice (30 Sep 2026 20:35): §9.6 |
| Supabase (optional, live since 30 Sep 2026 22:27) | project ref `dcbcbpwpmdtaanboetiz` (`https://dcbcbpwpmdtaanboetiz.supabase.co`, region ap-northeast-1, Postgres 17), owned by the owner's Supabase account; the `hg_*` tables belong to the Jeannie repo (§3.11). The bot writes to it from separate CPU-only publisher processes; nothing else on this PC depends on it |

**History.** The bot used to run on an older PC (Intel i3-14100 + RTX 5060, everything on `E:\BOT`). That PC
is gone and nothing could be copied from it: the secrets were re-created from their sources and the data was
rebuilt from the portal (the "cold start", 27 Sep 2026). `C:\Hangeul\BOT\PC_BUILD.md` describes the old PC's
bottlenecks and two *proposed* new builds (i7-14700 + RTX 5080 16 GB, or Ryzen 9 9950X3D); **neither was
bought** — the owner chose to move everything onto this Ryzen 5 8600G / RTX 5060 PC (memory note
`hangeul-migration-target.md`: "It is not either build in PC_BUILD.md"). PC_BUILD's plan to keep the old PC
for the bot was rejected in favour of a full move. By 30 Sep 2026 the owner had also **deleted the old PC's bot
and the old Telegram bot**, so @the_Jennie_bot on this PC is the only copy (§5.5).

---

## 2. Folder layout

```
C:\Hangeul\
├── BOT\                                   the bot: git repo (113 tracked files) + live data (git-ignored)
│   ├── .env                               live config + secrets (git-ignored, 43 lines, 21 keys) -> secrets\bot.env
│   ├── .env.example                       template with every key documented (Supabase block at :106-118)
│   ├── credentials.json / token.json      Google OAuth client + user token (git-ignored)
│   ├── .venv\                             Python 3.12 venv (5.2 GB: torch 2.11.0+cu128, easyocr, sentence-transformers, ...)
│   ├── run.py                             the entry point: Telegram polling + REST API in one process
│   ├── start.bat / start_background.vbs   start (console / hidden)
│   ├── stop.bat / check_status.bat        stop / show this folder's bot processes + last 25 log lines
│   ├── watchdog.ps1                       restart-if-dead, run every 5 min by task HangeulBotWatchdog
│   ├── install_autostart.bat              creates Startup\HangeulBot.lnk
│   ├── install_watchdog.bat               creates scheduled task HangeulBotWatchdog
│   ├── apply_bot_update.bat               legacy one-click updater (copies root telegram_bot.py/config.py into src\)
│   ├── gauth.bat / install_sheets.bat / build_sheets.bat / run_passport_audit.bat   Google + sheet helpers
│   ├── bootstrap.py                       cold-start phases 1-5 (+ printed phase 6 hand-over); MIGRATION runs 4 and 5 by hand
│   ├── audit_program.py, download_passports.py, inspect_passports.py, get_consultations.py, compress_docs.py
│   ├── telegram_bot.py, config.py, progress_builder.py   ROOT COPIES: byte-identical to src\bot\telegram_bot.py,
│   │                                      src\config.py, src\sheets\progress_builder.py (keep them identical)
│   ├── test_system.py, test_verified.py, test_passport.jpg   old root test scripts (NOT the pytest suite)
│   ├── tests\                             the pytest suite (24 test files + conftest.py, 604 test functions, 1152 collected cases)
│   ├── tools\export_windows_ca.ps1        exports Windows root CAs to data\windows-ca.pem (only if HTTPS breaks)
│   ├── src\                               the package (see the other pack files)
│   │   ├── __init__.py                    CA-bundle env vars + Telegram-token log redaction filter
│   │   ├── config.py                      Settings (pydantic-settings) -- every .env key
│   │   ├── net_fix.py                     Telegram DNS workaround
│   │   ├── dates.py                       strict date parsing (yearless portal stamps)
│   │   ├── api\                           FastAPI app (main.py, routes\auth|dashboard|applications|crawler.py)
│   │   ├── bot\                           telegram_bot.py, scheduler.py, brief.py, ask.py, replies.py, voice.py, performance.py
│   │   ├── cloud\                         the Supabase publish layer (11 files: __init__, publish, records, embed, handoff,
│   │   │                                  backfill, full_picture, bot_jobs, command_hooks, sheet_hooks, student_index; 03d)
│   │   ├── llm\                           ollama_client.py, prompts.py
│   │   ├── scraper\                       client.py (httpx session), parsers.py (BeautifulSoup), ocr_validator.py, mock_data.py
│   │   ├── sheets\                        progress_builder.py, auto_sync.py, missing_report.py, passport_issue.py, verified_docs.py, ...
│   │   └── verify\                        auto_verify.py, doc_verifier.py, page_checks.py, field_check.py, rules.py
│   ├── data\                              git-ignored run-time state (student data: never share)
│   │   ├── cloud_state.json               the Supabase hash state (2.2 MB on 30 Sep; §2.1)
│   │   ├── cloud\                         the publish layer's working folder: pending\, publish.lock,
│   │   │                                  student_index.json, backfill_20260930.log (§2.1)
│   │   ├── sheet_state.json               auto_sync's memory of every sheet/student
│   │   ├── alerted_passport_issues.json   passport watcher memory {"version": 2, "scans": {"uid|file": ...}}
│   │   ├── passport_issue.json            cached passport issue dates
│   │   ├── auto_sync.lock                 present only while a sync runs (PID inside)
│   │   ├── missing_reports\               the 09:05 Excel reports
│   │   ├── jennie_fillers\                Jennie's 6 pre-rendered filler clips + fillers.json
│   │   └── verification\                  results.json (ONLY copy of the Corrections history), text\ (OCR cache),
│   │                                      DOCUMENT CHECK.xlsx, FIELD CHECK.xlsx, auto_verify.lock while running
│   ├── passports\                         passport scans the watcher downloaded (student images: never open)
│   ├── program_audit_*.csv                phase-3 passport audit outputs (27 Sep 2026)
│   └── hangeul_bot.log, hangeul_stdout.log, hangeul_stderr.log, hangeul_sync.log, hangeul_watchdog.log
├── VERIFIED STUDENT DOCUMENTS\            downloaded documents <PROGRAM>\<NAME (PASSPORT)>\ (default DOCS_ROOT)
├── VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB\   originals of shrunk files (default DOCS_ORIGINALS_ROOT)
├── (KONYANG DOCUMENTS\)                   absent on this PC; KONYANG_ROOT is skipped when missing
├── JARVIS\                                everything for the voice assistant "Jennie" + audit/fix artefacts
│   ├── jennie_voice\                      the voice service (service.py, FastAPI on 127.0.0.1:8765) + its own .venv (6.7 GB)
│   │   ├── models\hf\                     faster-whisper large-v3-turbo (+ small) weights (2.0 GB)
│   │   ├── start_jennie_voice.vbs, stop_jennie_voice.bat, watchdog_jennie_voice.ps1, install_jennie_voice.bat
│   │   ├── bench_stt.py, smoke_test.py, offline_test.py (+ their .json results), stubs\pyworld.py
│   │   └── jennie_voice.log, jennie_watchdog.log, jennie_voice_stdout.log, jennie_voice_stderr.log
│   ├── voice-trials\                      TTS/STT trial venvs; cosyvoice\repo (CosyVoice code + CosyVoice2-0.5B
│   │                                      weights, 3.8 GB) and cosyvoice\ref (Jennie's reference voice) and
│   │                                      whisper\hf_home (medium/large-v3, 4.4 GB) ARE USED AT RUN TIME: do not delete
│   ├── voice-samples\                     the rendered candidate voices the owner chose from by ear
│   ├── brain-trial\                       LLM choice trial, latency harness, brief cross-check scripts
│   ├── disabled\JennieVoice.lnk           the voice service's Startup shortcut, parked while the voice is off (still there 30 Sep)
│   ├── command-audit\                     independent per-command audit scripts (28 Sep 2026)
│   ├── fix\                               fix-workflow artefacts: audit\audit_results.json, brief_workflow_results.json, scratch\
│   ├── tools\supabase\                    Supabase CLI v2.118.0: bin\supabase.exe (+ supabase-go.exe), the release zip and its
│   │                                      checksums.txt (§3.11). Not on PATH: call it by its full path
│   ├── tools\node\                        Node.js v22.23.3 for the Jeannie build (node-v22.23.3-win-x64\ + its zip, checksum
│   │                                      checked; no system install). Not on PATH: prepend node-v22.23.3-win-x64\ in that shell
│   ├── Jeenie-saem-bot\                   clone of the Jeannie repo (github.com/munim430-ai/Jeenie-saem-bot, main = 31202e9,
│   │                                      behind origin/main f7bbdca); supabase\migrations\ = the 4 applied migrations;
│   │                                      supabase\.temp\ = the CLI's link state
│   ├── jeannie-hg\                        git worktree of that clone, branch saem/hangeul-context-reader from origin/main
│   │                                      f7bbdca: Jeannie's reader of the hg_* data, being built (workflow wf_1a222cb1-960,
│   │                                      approved 30 Sep 23:48), unmerged and not pushed (see 11 B26)
│   ├── cloud\                             Supabase build worktrees of C:\Hangeul\BOT (core, jobs, inproc, commands, all, release:
│   │                                      git worktrees on the cloud/* branches) + scratch\. all\data\cloud\dry_run\ holds the three
│   │                                      dry-run payload folders of 29 Sep (FULL student data: never share; remove with
│   │                                      `git worktree remove` once no longer needed)
│   └── perf\, perf2\                      scratch of the two performance builds (their worktrees were removed)
└── REFERENCE\                             this pack (secrets\ holds copies of the live credentials)
```

Outside `C:\Hangeul`:

| Path | What |
|---|---|
| `C:\Users\User\.ollama\models` | Ollama model store (6.7 GB: `qwen3:4b-instruct` 2.5 GB, `qwen2.5:7b` 4.7 GB). `OLLAMA_MODELS` is not set, so this default is used |
| `C:\Users\User\.EasyOCR` | EasyOCR detection/recognition models (94 MB), downloaded on first use |
| `C:\Users\User\.cache\huggingface\hub` | the Hugging Face cache (65 MB): `models--thenlper--gte-small\snapshots\17e1f347d17fe144873b1201da91788898c639cd\` (`model.safetensors`, `config.json`, `modules.json`, `sentence_bert_config.json`, `1_Pooling\`, tokenizer files) with the weights stored content-addressed under `hub\blobs\` (hf-xet). `HF_HOME` is **not** set, so this default is used; the publisher runs with `HF_HUB_OFFLINE=1` and never downloads (§3.11) |
| `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` | `HangeulBot.lnk`, `Ollama.lnk` (and the owner's unrelated `Send to OneNote.lnk`) |
| Task Scheduler root | `\HangeulBotWatchdog` (Ready), `\JennieVoiceWatchdog` (Disabled) |
| `C:\Users\User\.claude\projects\C--Users-User-Downloads-hangeul-bot-main-hangeul-bot-main\memory\` | decision notes (`hangeul-migration-target.md`, `hangeul-migration-decisions.md`, `hangeul-jarvis-plan.md`) |
| same folder, `*.jsonl` | the two build-session transcripts (contain pasted secrets, including the Supabase personal access token: never share) |
| `C:\Users\User\Downloads\hangeul-bot-main\hangeul-bot-main` | the untouched GitHub zip the move started from (no secrets, no data) |
| `C:\Users\User\Downloads\hangeul-bot-prompt.md` | the owner's spec of the Supabase publish layer (decisions D1-D13, the `hg_sync` contract, the kinds table); summarised in [13](13_SUPABASE_PUBLISHING.md) |

### 2.1 The Supabase publish layer's local files

All under `C:\Hangeul\BOT\data\` (git-ignored; they hold student data or keys derived from it: never share).
Paths are constants in `src\cloud\publish.py:83-87`, `src\cloud\handoff.py:46-48` and `src\cloud\student_index.py:31`.

| Path | Written by | What it is | Rule |
|---|---|---|---|
| `data\cloud_state.json` | every publisher (`publish.save_state`, `.part` + `os.replace`) | the hash state: `{"version": 1, "embed_model": "thenlper/gte-small@17e1f347…", "records": {"<kind>\|<key>": {"h": content_hash, "s": scope, "t": read_at}}, "scopes": {"<kind>\|<scope>": digest of the keys of its last complete publish}, "reads": {"<kind>\|<scope>": read time of its last complete publish}}`. 2.2 MB on 30 Sep (13,540+ records) | Only rows Supabase accepted (HTTP 2xx) advance it. Missing or unreadable = everything is sent again (harmless: `hg_sync` answers "unchanged"). **Do not delete it casually**: the next run then re-embeds and re-sends every record (the backfill took 17 min) |
| `data\cloud\pending\<YYYYmmdd-HHMMSS-ffffff>-<job>.json` | `handoff.write` (`.part` + `os.replace`) in the job that read the data | one handoff file: `{"version": 1, "job", "created_at", "failed_reads": [...], "batches": [...]}` | The publisher deletes it when done (sent or failed: decision D6, no retry queue). A file left by a killed publisher (stop.bat, a power cut) is removed after `STALE_HOURS = 6` by the next `write`; it is **not** re-sent, but the rows it held are resent by the next read of the same scope because their hashes never advanced. Normally empty (it was empty at 23:43 on 30 Sep) |
| `data\cloud\publish.lock` | `publish.publisher_lock` (`publish.py:251`; an OS byte lock through `msvcrt.locking`, released by Windows if the process dies) | one publisher at a time, so the hash state is never written by two | a publisher waits up to `LOCK_WAIT = 20 min` (`publish.py:93`); the hourly full picture waits `LOCK_WAIT = 120 s` (`full_picture.py`) and then skips its hour. The 0-byte file stays on disk between runs; that is normal, never delete it by hand |
| `data\cloud\student_index.json` | `student_index.remember` | `{"version": 1, "by_passport": {"<PASSPORT>": {"uid": "<portal uid>", "hng": "HNG-<year>-<n>"}}}`: which student a passport-keyed record (document check, OCR pages) belongs to | a passport two students share in one list is given to neither |
| `data\cloud\backfill_20260930.log` | the owner's shell (`… -m src.cloud.backfill > data\cloud\backfill_20260930.log 2>&1`) | the one-time backfill's progress: per kind "N record(s), N sent: N upserted, N unchanged, N deleted", ending `Done in 1025 s; 0 read(s) failed.` and `exit 0` (3,323 bytes, counts only) | name any later backfill log `backfill_YYYYMMDD.log` beside it |
| `data\cloud\dry_run\<YYYYmmdd-HHMMSS>-<job>-<id>\` | a dry run (`--dry-run`) | every request body exactly as it would be sent (`POST-hg_runs`, each `hg_sync` call) | absent in the live tree; the three dry runs of 29 Sep are in `C:\Hangeul\JARVIS\cloud\all\data\cloud\dry_run\` (99 MB for the third; full student data) |

The publishers log to `C:\Hangeul\BOT\hangeul_sync.log` (§6), one line per run.

---

## 3. From-scratch install

The order matters (torch before easyocr; Ollama env vars before Ollama starts; Google sign-in before the
cold start). Every command is run in PowerShell from `C:\Hangeul\BOT` unless stated, and **always with
`.venv\Scripts\python.exe`, never a bare `python`** (the launchers use only the venv; a package installed into
another Python is invisible to them).

### 3.1 Prerequisites

1. **NVIDIA driver** for the RTX 5060 (this PC: 616.92).
2. **Python 3.12** from python.org (tick the `py` launcher). Python 3.11 is no longer required.
3. **Visual C++ Redistributable Packages for Visual Studio 2013 (x64)** specifically (it provides
   `msvcr120.dll`, which pyzbar's bundled `libzbar-64.dll` and `libiconv.dll` need; this PC has it in
   `C:\Windows\System32\msvcr120.dll`). A newer "Visual C++ 2015-2022" redistributable does **not** replace it.
   Without it `pyzbar` cannot load its DLL, and the failure is **silent**: `page_checks.py:100-103` and
   `:331-334` both do `except Exception: _zbar = None` and fall back to OpenCV's `QRCodeDetector` alone, which
   "often cannot" read real scans (the code's own comment). The result is mass false "no scannable apostille QR"
   FAILs ([07 §10.4](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)) instead of a visible error. Run the pyzbar
   pre-flight in §3.9 after installing. **Rebuild rule:** treat a failed pyzbar import as a hard error at
   start-up, never as "no QR on the page".
4. **Git for Windows** (local history; one commit per change).

### 3.2 The bot's venv

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

The last line must print `True NVIDIA GeForce RTX 5060`. **Torch goes in first, from the cu128 index**: if
`easyocr` is installed first it pulls PyPI's CPU-only torch and the CUDA command then silently does nothing
(OCR runs on the CPU). `requirements.txt` pins what was proven on this PC on 27 Sep 2026:

| Group | Pins |
|---|---|
| GPU | `torch==2.11.0+cu128`, `torchvision==0.26.0+cu128` |
| OCR / documents | `easyocr==1.7.2`, `pymupdf==1.28.2`, `opencv-python-headless==5.0.0.93`, `pyzbar==0.1.9`, `pillow==12.3.0`, `pypdf==6.19.0`, `openpyxl==3.1.5` |
| Portal, bot, API | `httpx==0.28.1`, `beautifulsoup4==4.15.0`, `python-telegram-bot==22.8`, `apscheduler==3.11.3`, `tzdata==2026.4`, `fastapi==0.141.1`, `uvicorn==0.54.0`, `pydantic==2.13.5`, `pydantic-settings==2.15.0`, `python-dotenv==1.2.3`, `rich==15.0.0` (run.py crashes without it) |
| Google | `google-api-python-client==2.200.0`, `google-auth-oauthlib==1.4.1`, `google-auth-httplib2==0.4.2` |
| Supabase publishing (`requirements.txt:38-44`, added with the publish layer) | `sentence-transformers==6.1.0`, `transformers==5.17.0`. They pull, and this PC has: `huggingface_hub==1.33.0`, `tokenizers==0.23.2`, `safetensors==0.8.0`, `scikit-learn==1.9.1`, `hf-xet==1.6.0`, `joblib==1.6.0`, `threadpoolctl==3.7.0`, `regex==2026.9.29`, `tqdm==4.70.1`, `typer==0.27.2`, `shellingham==1.5.4`, `narwhals==2.26.0`, `cloudpickle==3.1.2`. They use the **existing CUDA torch** (the embedder runs it on the CPU) |

**How the Supabase packages were added to the live venv without changing anything already there**
(29 Sep 2026 09:19): freeze the venv first (84 pins), use that freeze as a **pip constraints file**, dry-run,
install, freeze again and compare:

```powershell
.venv\Scripts\python.exe -m pip freeze > venv_freeze_before.txt
.venv\Scripts\python.exe -m pip install --dry-run -c venv_freeze_before.txt "sentence-transformers"
.venv\Scripts\python.exe -m pip install -c venv_freeze_before.txt "sentence-transformers==6.1.0"
.venv\Scripts\python.exe -m pip freeze > venv_freeze_after.txt
# compare: every difference must be an ADDED line (">"), never a changed or removed one ("<")
```

The result was 15 added packages and 0 changed (torch stayed `2.11.0+cu128`, numpy `2.5.2`, pillow `12.3.0`,
pydantic `2.13.5`, httpx `0.28.1`). Why the constraints: `-c` lets pip add new packages but forbids it to
upgrade or downgrade any package named in the file, so a transitive requirement can never swap the CUDA torch
for PyPI's CPU build or move numpy under EasyOCR. The two freeze files are in the session scratchpad
(`...\b90661d9-fc40-4a81-bd34-103e0decce24\scratchpad\venv_freeze_before.txt` / `_after.txt`); on a new PC,
`pip install -r requirements.txt` after torch gives the same set. The embedding model itself is not a pip
package: see §3.11 step 2.

`pytest` is needed for the 1152-case suite in `tests\` but is **not** in `requirements.txt`; install it after
the requirements:

```powershell
.venv\Scripts\python.exe -m pip install pytest==9.1.1
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider   # expect: 1150 passed, 2 skipped (~45 s)
```

The 2 skips are by design in the live checkout: `tests\test_cloud.py:893` and `tests\test_cloud_bot_jobs.py:620`
start a real child process, which would read the real `.env` and could publish, so they skip wherever a `.env`
(or Supabase settings in the environment) exists; in a worktree without `.env` all 1152 pass. No plugin is
needed: the async tests drive coroutines with `asyncio.run(...)` inside ordinary test functions (no
`pytest-asyncio`). `tests\conftest.py` (new) adds the `slow` marker (tests that load the real gte-small; they
skip when it is not cached) and an autouse fixture `_no_real_supabase` that blanks `SUPABASE_URL` /
`SUPABASE_SECRET_KEY` and sets `CLOUD_PUBLISH_ENABLED=False` for every test, so **no test can ever publish**,
whatever `.env` says. Date-dependent tests pin "today" with `tests\test_foundation.pin_today` (`:136`); see
[10](10_TESTS_AND_VERIFICATION.md).

### 3.3 Check HTTPS from Python

```powershell
.venv\Scripts\python.exe -c "import urllib.request; urllib.request.urlopen('https://oauth2.googleapis.com/token', timeout=20)"
```

`HTTP Error 404` = HTTPS works (the normal result on this PC). `CERTIFICATE_VERIFY_FAILED` = antivirus or the
ISP intercepts TLS with a root Windows trusts and certifi does not: run
`powershell -ExecutionPolicy Bypass -File tools\export_windows_ca.ps1` (writes `data\windows-ca.pem` from the
LocalMachine/CurrentUser Root and CA stores), then append it to certifi's bundle as the script's header shows.
`src\__init__.py` sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `HTTPX_SSL_CERT_FILE` and
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to that file (via `os.environ.setdefault`) whenever it exists. On 26 Sep 2026
on the old PC this failure stopped the Google token refresh for nine hours.

### 3.4 Ollama, the model and its environment variables

```powershell
winget install Ollama.Ollama            # or the installer from ollama.com; installs per-user and adds Startup\Ollama.lnk
setx OLLAMA_FLASH_ATTENTION 1           # user environment variables for the Ollama SERVER (not .env)
setx OLLAMA_KV_CACHE_TYPE q8_0
# quit the Ollama tray app, kill any orphaned runner (section 8.3), start "ollama app.exe" again
ollama pull qwen3:4b-instruct           # 2.5 GB, Apache-2.0, the non-thinking edition
ollama list
```

This PC today:

```
NAME                 ID              SIZE      MODIFIED
qwen3:4b-instruct    0edcdef34593    2.5 GB    (pulled 27 Sep 2026)
qwen2.5:7b           845dbda0ea48    4.7 GB    (pulled 27 Sep 2026; no longer used, can be removed with `ollama rm qwen2.5:7b`)
```

* `Ollama.lnk` in Startup targets `C:\Users\User\AppData\Local\Programs\Ollama\ollama app.exe`; the tray
  app starts `ollama.exe serve` (listening on `127.0.0.1:11434`), which spawns a `llama-server.exe` runner per
  loaded model.
* `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (User scope, set 28 Sep 2026) shrank the resident
  brain from 2.82 GiB to 2.62 GiB at `num_ctx` 3072 (`/api/ps`). They only reach an Ollama started afterwards.
* `OLLAMA_MODELS`, `OLLAMA_HOST`, `OLLAMA_KEEP_ALIVE` are **not** set; the bot sends `keep_alive` on every call.
* MIGRATION.md §4 still says `ollama pull qwen2.5:7b` — outdated: the bot switched to `qwen3:4b-instruct` on
  28 Sep 2026 (see [06](06_LLM_AND_JENNIE_VOICE.md)). Without Ollama the bot still works; the brief loses its
  one-line summary, free-text falls back to label matching, and `/sendmail` uses a plain template.

### 3.5 Google sign-in (Sheets + Drive)

The bot signs in **as the owner's Google account through OAuth** (not a service account).

**Google from zero (a new agency, a new Google account).** The steps under "On this PC" further down assume the
existing project and folders. For a new one, do this first; the sheets, the missing-info report and the stage report cannot run
without it:

1. [console.cloud.google.com](https://console.cloud.google.com) → create a **Cloud project** (any name).
2. **APIs & Services → Library** → enable **Google Drive API** and **Google Sheets API** (the code calls Drive v3
   and Sheets v4, `cache_discovery=False`).
3. **OAuth consent screen** (Google Auth Platform → Branding / Audience / Data access): user type **External**,
   an app name, the support and developer e-mail; scopes `https://www.googleapis.com/auth/drive` and
   `https://www.googleapis.com/auth/spreadsheets`. Then **Audience → Publish app → In production**: a token
   made while it is in *Testing* expires after 7 days (the "26 September outage").
4. **Clients → Create client → Desktop app** → download the JSON as `C:\<BOT>\credentials.json`.
5. **In Drive**, create the parent folder (`ALL STUDENTS`) and **one subfolder per program**. The bot creates
   only the intake folders inside them (`progress_builder._intake_folder`, `:405-418`, creates e.g.
   `MARCH 2027` inside `PROGRAMS[k]["folder_id"]`) and, in Drive mode only, `VERIFIED STUDENT DOCUMENTS` under
   `PARENT_FOLDER_ID` (`verified_docs.py:39`, `:156`); the program folders must already exist. Copy each
   folder's id from its URL (`https://drive.google.com/drive/folders/<id>`) into `PARENT_FOLDER_ID`
   (`progress_builder.py:56`) and `PROGRAMS[*]["folder_id"]` (`:111`, `:117`, `:123`, `:129`); a rebuild should
   read them from `.env` instead ([12 Adaptation map](12_ADAPTATION_MAP.md)).
6. `.venv\Scripts\python.exe -m src.sheets.progress_builder --auth` (step 3 under "On this PC") to write
   `token.json`.
7. `.venv\Scripts\python.exe -m src.sheets.progress_builder --all --dry-run` (fetch and map, no Drive writes),
   read the output, then `--all`.

Note that **every 15-minute sync reads Drive** even in local mode: `verified_docs.run_local(root,
skip_drive_done=True)` calls `_drive_complete_names()` (`verified_docs.py:222`, `:345`), which lists folders with
the `appProperties` key `hangeul_docs_complete=1`. So a working `token.json` is needed even if nothing is kept
in Drive.

**On this PC (the existing project):**

1. Google Cloud Console → project **`hangeul-bo`** → Google Auth Platform. The OAuth consent screen must be
   **In production** (it is, since 27 Sep 2026): a sign-in made while it is "Testing" expires after 7 days.
2. **Clients** → the **Desktop** client → download its JSON (if the secret is hidden: **+ Add secret** and
   download at once). Save as `C:\Hangeul\BOT\credentials.json` (a `credentials.json.json` is also accepted).
3. Delete any old `token.json`, then `.venv\Scripts\python.exe -m src.sheets.progress_builder --auth`
   (or double-click `gauth.bat`). A browser opens: sign in as the owner's account; at "Google hasn't verified
   this app" click **Advanced → Go to Hangeul Bot (unsafe)**; allow **both** Drive and Sheets. It prints
   `Google login OK — token.json saved`.
4. Scopes: `https://www.googleapis.com/auth/drive`, `https://www.googleapis.com/auth/spreadsheets`
   (`progress_builder.py:49-51`). `_load_credentials()` refreshes the access token itself and rewrites
   `token.json`; when refresh fails it raises "Google login required. Run: python -m src.sheets.progress_builder --auth".

### 3.6 Gmail app password (for `/sendmail`)

Google Account → Security → **2-Step Verification** (must be on) → **App passwords** → create one (16
characters). Put the address in `GMAIL_ADDRESS` and the app password in `GMAIL_APP_PASSWORD`
(values in secrets/bot.env). The bot sends with `smtplib.SMTP_SSL("smtp.gmail.com", 465)` (telegram_bot.py:1166);
`/sendmail` stays disabled until both keys are set.

### 3.7 The Telegram bot

1. Telegram → **@BotFather** → `/newbot` → name and username (this bot: **@the_Jennie_bot**) → copy the token
   into `TELEGRAM_BOT_TOKEN` (value in secrets/bot.env). The placeholder `your_telegram_bot_token_here` is
   treated as "no token": the bot then runs the REST API only.
2. The admin **must press Start** in the bot's chat: Telegram does not let a bot message someone who has not,
   so the brief and alerts would fail silently.
3. Find the admin's numeric ID: with `TELEGRAM_ADMIN_CHAT_ID` empty the bot refuses everyone and answers
   `/start` with "⛔ Unauthorized access. Your Chat ID is: `<id>`". Put that number in `TELEGRAM_ADMIN_CHAT_ID`
   (this PC: value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID), the owner's own user id) and restart. Colleagues go in `TELEGRAM_AUTHORIZED_CHAT_IDS` and must press Start too.
4. No BotFather `/setcommands` is needed: at every start `post_init` calls `set_my_commands` with **13 menu
   commands** (`src\bot\telegram_bot.py:2316-2330`, ending with `/performance_today` and `/performance_month`;
   log line `Successfully set 13 bot menu commands (set_my_commands).`, `:2333`) and sends + pins the command
   cheat-sheet in the admin chat. Every start therefore posts one pinned message: two copies starting together
   post two (§9.6).
5. Before the very first start on a new PC the session cleared Telegram's queued updates (a `getUpdates` with
   `offset = last update_id + 1`), so the new bot did not answer a backlog of old messages.

### 3.8 `.env`

Copy `.env.example` to `.env` and fill it in (section 4). Check three things: `MOCK_MODE=false` (the code
default is `True`, i.e. made-up demo data), `TELEGRAM_ADMIN_CHAT_ID` set, and the admin has pressed Start.
Write paths without quotes (inside `"..."` a `\n` or `\t` becomes a control character).

### 3.9 The cold start (data rebuilt from the portal)

Run once per new PC, **phase by phase, reading each summary before the next** (never unattended), with games
closed (a game on the same GPU made OCR ten times slower). Phase 2 before phase 1, or the Passport Issue column
is written blank. **Never delete a main tab of the Drive progress sheets**: the code rewrites main tabs in place,
and a deleted main tab makes it overwrite the first remaining tab (usually a manager's university tab).

| Step | Command | Took (27 Sep 2026) | Look for |
|---|---|---|---|
| pre-flight | the CUDA check (§3.2), the `pyzbar` decode below, one EasyOCR reader build, one portal login | minutes | no errors; the decode prints `data=b'ok'` |
| 2 issue dates | `.venv\Scripts\python.exe bootstrap.py --only 2` | 2 min | "274 of 302 cached" is normal; `0 cached` = login failed |
| 1 progress sheets | `.venv\Scripts\python.exe bootstrap.py --only 1` | 35 s | `updating existing sheet` for all 7, no `FAILED` |
| 3 passport audit | `.venv\Scripts\python.exe bootstrap.py --only 3` | 33 min (326 students) | `program_audit_*.csv` per program, never `Found 0 students` |
| 4 documents | `.venv\Scripts\python.exe -m src.sheets.verified_docs --local "C:\Hangeul\VERIFIED STUDENT DOCUMENTS" --include-drive-done` | 15 min (146 students, 1.2 GB) | `N saved ... 0 failed` |
| 5 document check | the batch loop below | 2 h 26 min (144 students) | FAIL/REVIEW/INCOMPLETE/PASS counts |
| quiet seed sync | `.venv\Scripts\python.exe -m src.sheets.auto_sync --no-notify` | 1 min | records the starting state without messaging anyone |
| (optional) Supabase | §3.11 steps 1-8: dry-run backfill, real backfill, then `CLOUD_PUBLISH_ENABLED=true` | 17 min (30 Sep 2026: 13,540 records) | `Done in … s; 0 read(s) failed.`, then `Supabase publish (…): ok` lines |

The pyzbar pre-flight (it encodes a QR code with OpenCV, enlarges it and decodes it with pyzbar; checked on this
PC on 29 Sep 2026 with OpenCV 5.0.0):

```powershell
.venv\Scripts\python.exe -c "import cv2; from pyzbar.pyzbar import decode; i=cv2.QRCodeEncoder.create().encode('ok'); i=cv2.resize(i,None,fx=8,fy=8,interpolation=cv2.INTER_NEAREST); print(decode(i))"
```

Expected: `[Decoded(data=b'ok', type='QRCODE', ...)]`. A `FileNotFoundError` or "Could not find module
libzbar-64.dll" means the VC++ 2013 runtime is missing (§3.1); do not start phase 5 until this passes, or every
apostille is failed for "no QR".

Phase 5 must run in fresh processes of 5 students (one long process grows its GPU memory until Windows spills it
into system RAM and each student slows from ~70-90 s to ~570 s):

```powershell
do {
    $out = .venv\Scripts\python.exe -m src.verify.auto_verify --budget 5 2>&1
    $out | Select-String "Documents checked|more waiting|could not"
} while ($LASTEXITCODE -eq 0 -and ($out -match "more waiting"))
```

### 3.10 Start it and make it survive restarts

```powershell
wscript.exe "C:\Hangeul\BOT\start_background.vbs"   # start hidden now
C:\Hangeul\BOT\install_autostart.bat                  # Startup\HangeulBot.lnk: start at sign-in
C:\Hangeul\BOT\install_watchdog.bat                   # task HangeulBotWatchdog: restart within 5 min if it dies
```

Then send the bot `/stats`: the answer must be live numbers, not demo data. The voice service has its own
installer (`C:\Hangeul\JARVIS\jennie_voice\install_jennie_voice.bat`, see [06](06_LLM_AND_JENNIE_VOICE.md)); it
is **off** on this PC and needs nothing for the bot to run.

### 3.11 Supabase publishing (optional, for Jeannie)

Since 30 Sep 2026 22:27 the bot also writes everything it reads from the portal and every report it builds
(rows, a text form and 384-number gte-small embeddings) to the owner's Supabase project, so the owner's web
assistant **Jeannie** can answer from it while this PC sleeps. Drive, Sheets, the `.xlsx` files and Telegram
are unchanged and never wait for it; a Supabase failure is one log line. The design (the owner's decisions
D1-D13, the kinds, the `hg_sync` contract) is in [13](13_SUPABASE_PUBLISHING.md); this section is only how to
set it up. The steps must be done in this order, and nothing is published until step 8.

1. **Packages**: `sentence-transformers==6.1.0` + `transformers==5.17.0` in the bot's venv, under a constraints
   file of the existing freeze (§3.2).
2. **The embedding model, once, while online** (it is then read offline for ever):
   ```powershell
   .venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download as d; print(d('thenlper/gte-small', revision='17e1f347d17fe144873b1201da91788898c639cd', allow_patterns=['*.json','*.txt','model.safetensors','1_Pooling/*']))"
   ```
   It lands in `C:\Users\User\.cache\huggingface\hub\models--thenlper--gte-small\snapshots\17e1f347…\` (MIT
   licence, 67.7 MB). Check it the way the publisher loads it, offline and with the GPU hidden:
   ```powershell
   $env:CUDA_VISIBLE_DEVICES = '-1'; $env:HF_HUB_OFFLINE = '1'
   .venv\Scripts\python.exe -c "import torch; from sentence_transformers import SentenceTransformer as S; m = S('thenlper/gte-small', revision='17e1f347d17fe144873b1201da91788898c639cd', device='cpu', model_kwargs={'dtype': torch.float32}); v = m.encode(['test'], normalize_embeddings=True); print(torch.cuda.is_available(), v.shape, round(float((v**2).sum()), 4))"
   ```
   Expected: `False (1, 384) 1.0`. Measured on this PC: ~14 ms a record (1.4 s per 100), ~1 GB RAM,
   deterministic. Two traps, both hit here: **(a) `model_kwargs={"dtype": torch.float32}` is required** —
   transformers 5 otherwise loads gte-small as float16, which is ~7× slower on this CPU and gives vectors that
   differ slightly from the float32 ones Supabase holds (Jeannie embeds her questions with the same model,
   `Supabase/gte-small`, its ONNX export; the 30 Sep postcheck recomputed stored chunks in float32 at cosine
   0.9998-1.0005); **(b) hide CUDA with `-1`, never an empty value** — on Windows CPython
   drops a variable set to `""` from the real process environment, so torch still saw the GPU (fixed in
   `752cd53`; `src\cloud\embed.py:41-43`, `NO_GPU = "-1"`). The pinned revision is `CLOUD_EMBED_REVISION`
   (`src\config.py:92`): every vector in Supabase must come from exactly these weights.
3. **The Jeannie repo, which owns the schema.** The bot writes rows only; the `hg_*` tables, `hg_sync`,
   `hg_match` and `hg_changes_since` are created by the Jeannie repo's migrations:
   ```powershell
   git clone https://github.com/munim430-ai/Jeenie-saem-bot.git C:\Hangeul\JARVIS\Jeenie-saem-bot
   git -C C:\Hangeul\JARVIS\Jeenie-saem-bot config core.autocrlf false
   Remove-Item C:\Hangeul\JARVIS\Jeenie-saem-bot\supabase\migrations\*.sql -Force
   git -C C:\Hangeul\JARVIS\Jeenie-saem-bot checkout -- supabase/migrations
   ```
   The re-checkout makes the four `.sql` files byte-exact (LF) instead of the CRLF copies a default Git for
   Windows checkout writes. Clone at `31202e9` ("Merge pull request #8 ..."), migrations in
   `supabase\migrations\`: `20260928000000_jeannie_memory.sql`, `20260928180000_jeannie_memory_revoke_public.sql`,
   `20260929030000_hangeul_context.sql` (the one the bot needs), `20260929030100_jeannie_memory_grant_service_role.sql`.
   `git status` in the clone lists many other files as modified: line endings of the first checkout, harmless;
   never commit or push from this clone (the repo is Jeannie's, not the bot's).
4. **The Supabase CLI** (v2.118.0, 25 Sep 2026; no installer, no PATH change, no system setting):
   ```bash
   D="C:/Hangeul/JARVIS/tools/supabase"; mkdir -p "$D"; cd "$D"
   curl -sSL -o supabase_2.118.0_windows_amd64.zip https://github.com/supabase/cli/releases/download/v2.118.0/supabase_2.118.0_windows_amd64.zip
   curl -sSL -o checksums.txt https://github.com/supabase/cli/releases/download/v2.118.0/checksums.txt
   grep " supabase_2.118.0_windows_amd64.zip$" checksums.txt; sha256sum supabase_2.118.0_windows_amd64.zip   # must be equal
   ```
   then `Expand-Archive C:\Hangeul\JARVIS\tools\supabase\supabase_2.118.0_windows_amd64.zip C:\Hangeul\JARVIS\tools\supabase\bin -Force`
   and `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe --version` → `2.118.0`. The zip is 64,064,034 bytes,
   SHA-256 `e8eb5871b2a9e9b496d19f3fca4851d0c2a1bb8059613692d8906b5dc5fc2aad` (checked on 29 Sep 2026).
5. **The personal access token (for the CLI only).** Supabase dashboard → your avatar (Account) → **Access
   Tokens → Generate new token** (`sbp_…`). It is written in `C:\Hangeul\BOT\.env` as `SUPABASE_ACCESS_TOKEN`
   (value in secrets/bot.env (SUPABASE_ACCESS_TOKEN)); it is **not** a Windows user variable on this PC. The
   bot never reads it (`Settings` has no such field and ignores unknown keys, `extra="ignore"`). It is
   **account-wide**: it can manage every project of the owner's Supabase account, not just this one. Load it
   into the one PowerShell process that runs the CLI, never print it:
   ```powershell
   $line = Get-Content C:\Hangeul\BOT\.env | Where-Object { $_ -like 'SUPABASE_ACCESS_TOKEN=*' } | Select-Object -First 1
   $env:SUPABASE_ACCESS_TOKEN = $line.Substring('SUPABASE_ACCESS_TOKEN='.Length).Trim()
   $sb = 'C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe'
   Set-Location C:\Hangeul\JARVIS\Jeenie-saem-bot
   & $sb link --project-ref dcbcbpwpmdtaanboetiz     # -> {"project_ref":"dcbcbpwpmdtaanboetiz","message":""}
   & $sb db push --dry-run                            # "Would push these migrations:" + exactly the 4 files
   & $sb db push --yes                                # "Applying migration 2026...sql..." x4
   & $sb migration list                               # local = remote for all 4
   ```
   **No database password is needed**: this CLI version starts with `Initialising login role...` (a temporary
   login role made through the access token). `link` stores its state in
   `C:\Hangeul\JARVIS\Jeenie-saem-bot\supabase\.temp\` (`project-ref`, `pooler-url`, `linked-project.json`,
   versions). On 29 Sep 10:31 the result was `migration list` = local and remote `20260928000000`,
   `20260928180000`, `20260929030000`, `20260929030100`; no seeds, no roles. A `supabase projects list` before
   `link` prints "Cannot find project ref. Have you run supabase link?" on stderr and still lists the project:
   harmless. Apply **only** the repo's migration files; never write SQL for Jeannie's schema from the bot side.
6. **The bot's two keys** in `.env` (§4): `SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co` and
   `SUPABASE_SECRET_KEY` = the project's **secret** key (Project Settings → API Keys → `sb_secret_…`, value in
   secrets/bot.env (SUPABASE_SECRET_KEY)), never the publishable key. Leave `CLOUD_PUBLISH_ENABLED` out (or
   `false`) for now. Check read-only through PostgREST with that key: `GET /rest/v1/<table>?select=…&limit=1` on
   `hg_runs`, `hg_records`, `hg_chunks`, `hg_changes`, `memory_documents`, `memory_chunks` → 200; the OpenAPI
   listing (`GET /rest/v1/` with `Accept: application/openapi+json`) shows `/rpc/hg_sync` (`p_run, p_kind,
   p_scope, p_rows, p_all_keys`), `/rpc/hg_match` and `/rpc/hg_changes_since`; the same GET **without** a key
   must be refused (401).
7. **The backfill: a dry run first, then the real copy** (from `C:\Hangeul\BOT`, never in the quiet windows
   18:00-18:10, 08:25-08:40, 09:00-09:10 or during a sync: it refuses unless `--force`):
   ```powershell
   .venv\Scripts\python.exe -m src.cloud.backfill --dry-run      # payloads to data\cloud\dry_run\<run>\, nothing sent
   ```
   Read the counts and a few masked payloads, then the real one, with publishing switched on **for that
   process only** (a Windows environment variable beats `.env`) so the bot keeps publishing off meanwhile:
   ```bash
   cd C:/Hangeul/BOT && mkdir -p data/cloud && CLOUD_PUBLISH_ENABLED=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m src.cloud.backfill > data/cloud/backfill_20260930.log 2>&1; echo "exit $?" >> data/cloud/backfill_20260930.log
   ```
   On 30 Sep 2026 21:48-22:05 (1025 s): 13,540 records, 15,629 chunks, 0 failed reads, `hg_runs` status ok.
   Other flags: `--only <kinds>`, `--skip-portal`, `--skip-disk`, `--days N`, `--ignore-state` (moves the hash
   state to `cloud_state.json.bak` and sends everything), `--data-dir`, `--verification-dir`, `--docs-root`,
   `--force` (`src\cloud\backfill.py:614-627`).
8. **Switch it on**: add the line `CLOUD_PUBLISH_ENABLED=true` to `.env` (line 43 here; never `CLOUD_PUBLISH_ENABLED=`
   with an empty value — pydantic cannot read `""` as a bool and **`Settings` then fails at import, so the bot
   does not start at all**), and restart the bot (§9.2). Check: the start line ends `…, missing-info report
   09:05, Supabase full picture every 60m.`, and within ~8 minutes `hangeul_sync.log` shows
   `Supabase publish (full_picture): ok, …` (§6). On 30 Sep: restart 22:27, full picture 22:35 (3 upserted,
   779 unchanged, 6.9 s), portal sync 22:43 (0 upserted, 976 unchanged).

To switch publishing **off**: `CLOUD_PUBLISH_ENABLED=false` (or delete the line) and restart. Then
`handoff.enabled()` is False everywhere: no record is built, no file written, no process started, no request
sent (`src\cloud\publish.py:103-107`); the hash state and Supabase's rows stay as they are, and switching it on
again sends only what changed meanwhile.

---

## 4. Every `.env` key

Read by `C:\Hangeul\BOT\src\config.py` (`class Settings(BaseSettings)`, `env_file = BOT_ROOT / ".env"`,
`encoding utf-8`, `extra="ignore"`). Precedence: **Windows environment variable > `.env` > code default**.
`BOT_ROOT` is the folder holding `run.py` (resolved from `src\config.py`), so the bot can be moved.
Secrets are never written here: see [secrets/README.md](secrets/README.md).

| Key | Type | Code default | This PC | Meaning / rule |
|---|---|---|---|---|
| `MOCK_MODE` | bool | **`True`** | `false` | `false` = live portal. `true` = the basic lookups answer with fake demo data from `src\scraper\mock_data.py`; it is **not** an offline switch (the sheet sync, passport watcher, issue-date refresh and missing report still reach the real portal and Google). |
| `HANGEUL_BASE_URL` | str | `https://hangeul.com.bd/admin` | `https://hangeul.com.bd/admin` | Base of every portal URL (`login.php`, `students.php`, `consult_requests.php`, `calendar.php`, ...). |
| `HANGEUL_USERNAME` | str | `admin` | value in secrets/bot.env (HANGEUL_USERNAME) | Portal login. The bot is strictly read-only: GETs plus the login POST. |
| `HANGEUL_PASSWORD` | str | `password` | value in secrets/bot.env (HANGEUL_PASSWORD) | Portal password. |
| `OLLAMA_BASE_URL` | str | `http://127.0.0.1:11434` | `http://127.0.0.1:11434` | Ollama server. Use 127.0.0.1: `localhost` tries IPv6 `::1` first and lost ~2 s per new connection on this PC. |
| `OLLAMA_MODEL` | str | `qwen3:4b-instruct` | `qwen3:4b-instruct` | The one model for all LLM calls ("Jennie's brain"). |
| `OLLAMA_NUM_CTX` | int | `3072` | (default) | Context window of every call; one value for all calls, because Ollama reloads the model when it changes. 2048 cuts the brief's summary prompt; 4096 left too little VRAM for speech. |
| `TELEGRAM_BOT_TOKEN` | str | `""` | value in secrets/bot.env (TELEGRAM_BOT_TOKEN) | Empty or `your_telegram_bot_token_here` = no Telegram side (API only). |
| `TELEGRAM_ADMIN_CHAT_ID` | str | `""` | value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID) (the owner's user id) | Always authorised; the ONLY recipient of the 18:05 brief, passport-watcher alerts and the pinned command list. Empty = everyone is refused (and those three are skipped). |
| `TELEGRAM_AUTHORIZED_CHAT_IDS` | str | `""` | (default) | Extra allowed user IDs, separated by comma, semicolon or space (`Settings.authorized_ids()`). |
| `TELEGRAM_BRIEF_CHAT_IDS` | str | `""` | (default) | Recipients of the 15-minute sync summaries and the 09:05 missing-information report (`brief_recipient_ids()`); empty = all authorised IDs. Does not change who gets the brief or passport alerts. |
| `DAILY_REPORT_TIME` | str | `18:05` | `18:05` | HH:MM (24 h) of the daily brief; unparsable → 18:05. |
| `REPORT_TIMEZONE` | str | `Asia/Dhaka` | `Asia/Dhaka` | Zone for every cron job and for "today" (needs the `tzdata` package on Windows). |
| `ENABLE_SCHEDULED_REPORTS` | bool | `True` | `true` | `false` = `setup_scheduler` adds no job at all (brief, sync, watcher, 08:30, 09:05, brain keep-warm). |
| `GMAIL_ADDRESS` | str | `""` | value in secrets/bot.env (GMAIL_ADDRESS) | Sender for `/sendmail`. |
| `GMAIL_APP_PASSWORD` | str | `""` | value in secrets/bot.env (GMAIL_APP_PASSWORD) | 16-char Google app password. |
| `JENNIE_VOICE_ENABLED` | bool | `False` | `false` | `true` = register the voice-note handler (`filters.VOICE \| filters.AUDIO`, `block=False`), pin the brain in VRAM, render filler clips. |
| `JENNIE_VOICE_URL` | str | `http://127.0.0.1:8765` | (default) | Voice service; refused unless the host is 127.0.0.1 / localhost / ::1 (`voice._service_url`). |
| `JENNIE_SPOKEN_BRIEF` | bool | `True` | `false` | Also send a spoken brief after the text brief (only while the voice is on). |
| `BRAIN_ALWAYS_LOADED` | bool | `False` | (default) | `true` pins the brain (keep_alive -1) even with the voice off. |
| `BRAIN_IDLE_UNLOAD` | str | `5m` | (default) | keep_alive sent when not pinned (any Ollama duration string). |
| `API_HOST` | str | `0.0.0.0` | `0.0.0.0` | REST API interface. `0.0.0.0` exposes it to the LAN **without a password** — kept by the owner's choice; use `127.0.0.1` for this PC only. |
| `API_PORT` | int | `8000` | `8000` | REST API port (`/docs`, `/healthz`, `/api/...`). |
| `DOCS_ROOT` | path | `""` → `<parent of BOT>\VERIFIED STUDENT DOCUMENTS` | (default) = `C:\Hangeul\VERIFIED STUDENT DOCUMENTS` | Relative paths count from BOT_ROOT (`_folder()`). |
| `DOCS_ORIGINALS_ROOT` | path | `""` → `<parent of BOT>\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB` | (default) | Originals of shrunk files. |
| `KONYANG_ROOT` | path | `""` → `<parent of BOT>\KONYANG DOCUMENTS` | (default; folder absent) | Skipped when it does not exist. |
| `VERIFICATION_DIR` | path | `""` → `<BOT>\data\verification` | (default) | OCR cache, `results.json`, check reports. |
| `SUPABASE_URL` | str | `""` (`src\config.py:86`) | `https://dcbcbpwpmdtaanboetiz.supabase.co` | The Supabase project the bot publishes to. One of the three switches: publishing runs only when this, `SUPABASE_SECRET_KEY` and `CLOUD_PUBLISH_ENABLED` are all set (`publish.enabled()`, `src\cloud\publish.py:103-107`). |
| `SUPABASE_SECRET_KEY` | str | `""` (`:87`) | value in secrets/bot.env (SUPABASE_SECRET_KEY) | The project's **secret** key (`sb_secret_…`), sent as `apikey` + `Authorization: Bearer` to PostgREST (`/rest/v1/rpc/hg_sync`, `/rest/v1/hg_runs`). It bypasses RLS: whoever holds it reads and writes every `hg_*` row. Never the publishable key. Redacted from every log line (`src\__init__.py:41-50`). |
| `CLOUD_PUBLISH_ENABLED` | bool | `False` (`:88`) | `true` (since 30 Sep 2026 22:27, `.env` line 43) | The on/off switch of the whole publish layer. **Never write it with an empty value**: `CLOUD_PUBLISH_ENABLED=` fails `Settings` validation at import and the bot cannot start. `false` (or no line) = nothing is built, written, started or sent. |
| `CLOUD_EMBED_MODEL` | str | `thenlper/gte-small` (`:91`) | (default) | The embedding model (384 dimensions, CPU). Must be the model Jeannie embeds her questions with; every chunk carries `embed_model = "<model>@<revision>"` and a process with another model publishes nothing (one log line) until the chunks are re-embedded. |
| `CLOUD_EMBED_REVISION` | str | `17e1f347d17fe144873b1201da91788898c639cd` (`:92`) | (default) | The exact model revision (a Hugging Face commit), so every vector comes from the same weights; it must be in the local cache (the publisher is offline). |
| `SUPABASE_ACCESS_TOKEN` | — (not a `Settings` field; ignored by the bot) | — | value in secrets/bot.env (SUPABASE_ACCESS_TOKEN) (`.env` line 42) | The owner's Supabase **personal access token** (`sbp_…`) for the **Supabase CLI only** (`link`, `db push`, `migration list`, §3.11 step 5). It is kept in `.env` only as a place to store it; the CLI reads it from the process environment, so it is loaded into that one shell. **Account-wide**: it controls every project of the owner's Supabase account. |

This PC's `.env` (43 lines, 1,455 bytes on 30 Sep 22:27) has 21 keys: `MOCK_MODE, HANGEUL_BASE_URL,
HANGEUL_USERNAME, HANGEUL_PASSWORD, OLLAMA_BASE_URL, OLLAMA_MODEL, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID,
DAILY_REPORT_TIME, REPORT_TIMEZONE, ENABLE_SCHEDULED_REPORTS, API_HOST, API_PORT, GMAIL_ADDRESS,
GMAIL_APP_PASSWORD, JENNIE_VOICE_ENABLED, JENNIE_SPOKEN_BRIEF` (the 17 of 29 Sep) plus `SUPABASE_URL` (line 39),
`SUPABASE_SECRET_KEY` (40), `SUPABASE_ACCESS_TOKEN` (42) and `CLOUD_PUBLISH_ENABLED` (43, appended at 22:27 with
a newline check first so it did not join the previous line); everything else runs on its default. The
non-secret values: `MOCK_MODE=false`, `HANGEUL_BASE_URL=https://hangeul.com.bd/admin`,
`OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:4b-instruct`, `TELEGRAM_ADMIN_CHAT_ID=<the owner's user id: value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID)>`,
`DAILY_REPORT_TIME=18:05`, `REPORT_TIMEZONE=Asia/Dhaka`, `ENABLE_SCHEDULED_REPORTS=true`, `API_HOST=0.0.0.0`,
`API_PORT=8000`, `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false`,
`SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co`, `CLOUD_PUBLISH_ENABLED=true`.

**Environment variables that are NOT `.env` keys** (set with `setx`, reach only programs started afterwards):

| Variable | Read by | Default | Meaning |
|---|---|---|---|
| `TELEGRAM_DNS_FIX` | `src\net_fix.py` | `true` | `0/false/no/off` disables the startup probe. |
| `TELEGRAM_API_IP` | `src\net_fix.py` | empty | Force `api.telegram.org` to this IP inside the bot process. |
| `SSL_CERT_FILE` etc. | `src\__init__.py` | set to `data\windows-ca.pem` only if that file exists | CA bundle for Python HTTPS. |
| `OLLAMA_FLASH_ATTENTION` | Ollama server | (Ollama default) | This PC: `1` (User). |
| `OLLAMA_KV_CACHE_TYPE` | Ollama server | `f16` | This PC: `q8_0` (User). |
| `JENNIE_TTS_IDLE_S`, `JENNIE_TTS_MAX_S`, `JENNIE_HUNG_S`, `JENNIE_STT_GPU_KEEP_S`, `JENNIE_GPU`, `JENNIE_LOCK_WAIT_S` | voice service | 300, 100, 600, 0, 1, 120 | See [06](06_LLM_AND_JENNIE_VOICE.md). |
| `CUDA_VISIBLE_DEVICES=-1`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_PROGRESS_BARS=1`, `TQDM_DISABLE=1`, `TRANSFORMERS_VERBOSITY=error`, `TOKENIZERS_PARALLELISM=false` | set **by the code** in its own embedding processes (`embed.prepare_process`, `src\cloud\embed.py:60-73`; `handoff.child_env`, `src\cloud\handoff.py:93-98`; the `__main__` guards of `publish.py:60-61`, `backfill.py`, `full_picture.py`) | not set on the PC | Never set them yourself for the bot: a user-wide `CUDA_VISIBLE_DEVICES` would hide the GPU from the document check's EasyOCR too. |
| `SUPABASE_ACCESS_TOKEN` | the Supabase CLI | not set on the PC (checked 30 Sep: no User variable) | Loaded from `.env` into the CLI's shell only (§3.11 step 5). |
| `CLOUD_PUBLISH_ENABLED` (as an environment variable) | `Settings` (environment beats `.env`) | not set | Used once on purpose: `CLOUD_PUBLISH_ENABLED=true` for the backfill process only, while the bot kept publishing off (§3.11 step 7). |

`src\net_fix.py`: at start `apply_telegram_dns_fix()` resolves `api.telegram.org`; if no resolved IP accepts a
TCP connection on 443 within 3 s, it tries a list of known Bot API front ends (`149.154.167.99`,
`149.154.167.220`, `149.154.166.110`, `149.154.167.50`, `149.154.167.51`, `149.154.167.91`, `149.154.175.50`,
`91.108.4.200`, `91.108.56.100`) and monkey-patches `socket.getaddrinfo` for that host only, inside this process
(no hosts-file edit, no admin rights). The network the bot was built on returned an unreachable Telegram IP.

---

## 5. How the bot runs

### 5.1 One process: `run.py`

`C:\Hangeul\BOT\run.py` (110 lines) is the only entry point:

1. When started by `pythonw.exe` (no console), `sys.stdout`/`sys.stderr` are `None`; they are reopened as
   `hangeul_stdout.log` / `hangeul_stderr.log` (append, UTF-8, line-buffered) so no library print can crash it.
2. `logging.basicConfig(level=INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")` with a
   `FileHandler(hangeul_bot.log)` plus a `StreamHandler(sys.stdout)` (so `hangeul_stdout.log` repeats the log).
3. `start_all()`: prints a `rich` banner (mode, API URL, token set or not, model), runs
   `apply_telegram_dns_fix()`, checks Ollama (`ollama_client.check_health()` → `GET /api/tags`), builds
   `uvicorn.Config("src.api.main:app", host=API_HOST, port=API_PORT, log_level="info")`.
4. `build_telegram_application()` (src\bot\telegram_bot.py): returns `None` without a valid token; otherwise
   `Application.builder().token(token).post_init(post_init).build()`, registers every `CommandHandler`,
   `CallbackQueryHandler` (`^missing:`, `^stage:`, `^stagei:`), the free-text `MessageHandler(filters.TEXT &
   ~filters.COMMAND)`, the voice handler when `JENNIE_VOICE_ENABLED`, then `setup_scheduler(app)`.
5. With Telegram: `async with telegram_app: await telegram_app.start(); await post_init(telegram_app);
   await telegram_app.updater.start_polling(); await server.serve()` and, on exit, `updater.stop()`, `stop()`.
   **Long polling, not a webhook.** Without a token: `await server.serve()` only.
6. `post_init` (`src\bot\telegram_bot.py:2314`): `set_my_commands` (13 menu commands; log `Successfully set 13
   bot menu commands (set_my_commands).`), send + pin the cheat-sheet to `TELEGRAM_ADMIN_CHAT_ID`, then either
   `warm_brain()` (brain pinned: voice on or `BRAIN_ALWAYS_LOADED`, `:2360-2362`) or `ollama_client.unload()`
   (brain on demand, `:2365`: release any copy an earlier run pinned). With the voice off (this PC) it is the
   `unload()`.

The heavy jobs are **separate processes**: `scheduler._run_module(module, label)` runs
`<venv python.exe> -m <module>` (the console-less twin of `pythonw.exe`) with `cwd=C:\Hangeul\BOT`,
`PYTHONIOENCODING=utf-8`, `creationflags=0x08000000` (CREATE_NO_WINDOW), stdout+stderr appended to
`hangeul_sync.log`, killed after 3600 s. A crash in a job can never take the bot down. Since `8317741` there
are two more kinds of child process, both CPU-only (CUDA hidden with `CUDA_VISIBLE_DEVICES=-1`):

* **the publisher**, `python.exe -m src.cloud.publish --from data\cloud\pending\<file>.json --timeout 3600`,
  started by `handoff.spawn` (`src\cloud\handoff.py:109-115`) from whichever process read the data: the bot
  itself (the passport watcher, the 18:05 brief, command answers) or a job process (the sync, the 09:05
  report, `/missing`, `/stage`, the 08:30 refresh). Same settings as `_run_module` plus stdin closed
  (`subprocess.DEVNULL`), output appended to `hangeul_sync.log` (never the caller's pipe: a button report's
  parent reads that pipe to its end) and `child_env()`; the caller never waits for it. It stops itself after
  `CHILD_TIMEOUT = 3600` s.
* **the hourly full picture**, `python.exe -m src.cloud.full_picture`, through `_run_module` like the sync
  (`scheduler.run_full_picture`, `src\bot\scheduler.py:369-389`): it re-reads the portal's lists and publishes
  what changed, so Jeannie is complete even on a day nobody asks the bot anything. It stops itself after
  `DEADLINE = 45 min` (`src\cloud\full_picture.py:58`).

**The venv interpreter is a redirector.** `C:\Hangeul\BOT\.venv\Scripts\pythonw.exe run.py` starts the real
`C:\Users\User\AppData\Local\Programs\Python\Python312\pythonw.exe run.py` as its child, so the bot is always two
PIDs (since the 22:27 restart on 30 Sep: `12204` → `12676`). Every script that looks for the bot matches both.
The same holds for every job and publisher (`.venv\Scripts\python.exe -m …` plus its Python312 child).

### 5.2 Scheduled jobs (APScheduler `AsyncIOScheduler`, inside the bot process)

| Job id | Trigger | What runs | Options |
|---|---|---|---|
| `daily_executive_briefing` | `CronTrigger(hour=18, minute=5, timezone=Asia/Dhaka)` (from `DAILY_REPORT_TIME`) | `send_daily_briefing`: `compose_brief()` → `_send_brief` to the admin chat; then the spoken brief if the voice is on | `max_instances=1, coalesce=True, misfire_grace_time=600` |
| `passport_upload_watcher` | `IntervalTrigger(minutes=30)` counted from bot start | `check_new_passport_uploads` (OCR on the CPU via `asyncio.to_thread`, at most `WATCHER_BUDGET_SECONDS=1200` per run) | `max_instances=1, coalesce=True` |
| `portal_sync` | `IntervalTrigger(minutes=15)` from bot start | subprocess `-m src.sheets.auto_sync` (sheets, newly verified students' documents, their GPU document check, at most six students a run) | `max_instances=1, coalesce=True` |
| `missing_info_report` | `CronTrigger(hour=9, minute=5)` | subprocess `-m src.sheets.missing_report` | `misfire_grace_time=3600` |
| `passport_issue_refresh` | `CronTrigger(hour=8, minute=30)` | subprocess `-m src.sheets.passport_issue --refresh` | `misfire_grace_time=3600` |
| `brain_keep_warm` | `IntervalTrigger(minutes=10)` | `keep_brain_warm()`: returns at once unless the brain is pinned (it is not, on this PC); else reloads it if Ollama lost it or it sits partly on the CPU | `max_instances=1, coalesce=True` |
| `cloud_full_picture` (new) | `IntervalTrigger(minutes=60, start_date=now + 7.5 min)` (`FULL_PICTURE_MINUTES = 60`, `FULL_PICTURE_FIRST_MINUTES = 7.5`, `src\bot\scheduler.py:365-366`, job at `:501-509`), so it falls midway between the 15- and 30-minute beats | `run_full_picture`: returns at once while publishing is off; skipped (one log line `Full picture publish skipped: <reason>.`) in or less than 5 min before a quiet window (18:00-18:10, 08:25-08:40, 09:00-09:10) or while a sync holds `data\auto_sync.lock`; else subprocess `-m src.cloud.full_picture` (log `Full picture publish finished (exit 0).`) | `max_instances=1, coalesce=True` |

The start log line: `Scheduler active: daily briefing set for 18:05 (Asia/Dhaka), passport watcher running every
30m, portal sync every 15m, missing-info report 09:05, Supabase full picture every 60m.` (the last clause only
while publishing is on; with it off the line ends `… 09:05.`). Details of each job, and what each one publishes:
[05](05_TELEGRAM_COMMANDS_AND_JOBS.md), [13](13_SUPABASE_PUBLISHING.md).

### 5.3 The launch scripts

| Script | What it does exactly |
|---|---|
| `start.bat` | `cd /d "%~dp0"`, `PYTHON_EXE=%~dp0.venv\Scripts\python.exe`, runs `"%PYTHON_EXE%" run.py` in a console window, `pause` at exit; error box text if the venv is missing. For watching the bot live. |
| `start_background.vbs` | Finds its own folder (`fso.GetParentFolderName(WScript.ScriptFullName)`), checks `.venv\Scripts\pythonw.exe` (MsgBox if missing), sets `CurrentDirectory`, `WshShell.Run """<pythonw>"" run.py", 0, False` (hidden, no wait). This is what autostart and the watchdog use. |
| `stop.bat [nopause]` | One PowerShell pipeline over `Get-CimInstance Win32_Process`: `$v = BOT_DIR + '.venv\Scripts\'`; **bot** = venv `python(w).exe` whose command line matches `\brun\.py\b` + their children (the Python312 twin); **jobs** = venv processes matching `\s-m\s+src\.` whose parent is the bot or no longer exists (orphans) + their children. `Stop-Process -Force` on each, printing `Stopped PID: <pid> <cmd>`, or `The bot is not running.` Other Python processes on the PC are untouched. `nopause` (first argument) skips the final `pause`. |
| `check_status.bat` | The same matching, printed as a table (`ProcessId, ParentProcessId, Name, CommandLine`), then the last 25 lines of `hangeul_bot.log`. |
| (effect on the Supabase processes) | `stop.bat`'s "jobs" rule also matches every **publisher** (`-m src.cloud.publish`) and the **full picture** (`-m src.cloud.full_picture`): a publisher started by the bot has the bot as parent, and one started by a sync or a report has a parent that already exited (an orphan). So `stop.bat` kills a publisher mid-run. Nothing is corrupted (`cloud_state.json` is replaced atomically and advances only for rows Supabase accepted; `hg_sync` is one transaction per call), but that handoff file stays in `data\cloud\pending\` (pruned after 6 h) and is not re-sent: its unsent rows go out only when a later read shows them again (the hourly full picture re-reads the lists; a one-off record such as a Telegram notification or a command's answer is lost), and the `hg_runs` row of the killed run stays without `finished_at`. `check_status.bat` lists them too. So restart at a quiet moment (§9.2). |
| `apply_bot_update.bat` | Legacy "one click" updater from before git: `call stop.bat nopause`, copies the **root** `telegram_bot.py` → `src\bot\telegram_bot.py` and root `config.py` → `src\config.py` (or the newest `telegram_bot*.py`/`config*.py` in Downloads), clears `__pycache__` under the bot and `src`, `findstr`-checks for `crosscheck_range` and `def authorized_ids`, then `start "" start.bat`. **Because of it, the root copies must stay byte-identical to the src files** (every commit that changes `src\bot\telegram_bot.py` or `src\config.py` also updates the root copy). Prefer git (section 9) over this script. |

**From PowerShell, call `stop.bat` by its full path:** `cmd /c "C:\Hangeul\BOT\stop.bat" nopause`.
A bare `cmd /c stop.bat nopause` fails with "'stop.bat' is not recognized as an internal or external command"
because PowerShell/cmd start in the session's current directory, not in `C:\Hangeul\BOT` (seen on 28 Sep 2026).

### 5.4 Autostart and the watchdog

**Startup shortcut** (created by `install_autostart.bat`):
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HangeulBot.lnk` → Target
`C:\Windows\system32\wscript.exe`, Arguments `"C:\Hangeul\BOT\start_background.vbs"`, WorkingDirectory
`C:\Hangeul\BOT`, WindowStyle 7 (minimised). It starts the bot when `User` signs in.

**Watchdog task** (created by `install_watchdog.bat` with
`schtasks /Create /TN "HangeulBotWatchdog" /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"<BOT>\watchdog.ps1\"" /SC MINUTE /MO 5 /RL LIMITED /F`;
schtasks refuses a `/TR` longer than 261 characters, so the bot folder path must stay short). State: **Ready**.
`Export-ScheduledTask -TaskName HangeulBotWatchdog`:

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2026-09-27T11:46:53</Date>
    <Author>SAEMPC\User</Author>
    <URI>\HangeulBotWatchdog</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-<machine SID>-1001</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
  </Settings>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-09-27T11:46:00</StartBoundary>
      <Repetition>
        <Interval>PT5M</Interval>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\Hangeul\BOT\watchdog.ps1"</Arguments>
    </Exec>
  </Actions>
</Task>
```

`InteractiveToken` + `/RL LIMITED`: it runs only while `User` is signed in, without admin rights (hence the BIOS
power-on + auto sign-in for power cuts).

**`watchdog.ps1`** (`$ErrorActionPreference = "SilentlyContinue"`):
1. `$venv = <script folder>\.venv\Scripts\`; `Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"`.
2. `$redirect` = processes whose `ExecutablePath` starts with `$venv` (case-insensitive) and whose command line
   matches `\brun\.py\b`; `$running` = those + their children.
3. Running → append `yyyy-MM-dd HH:mm  running (pid <ids>)` to `hangeul_watchdog.log`, exit 0.
4. `pythonw.exe` missing → log `not running - cannot start it, ... is missing`, exit 1.
5. Otherwise log `not running - starting it` and
   `Start-Process wscript.exe "<folder>\start_background.vbs" -WindowStyle Hidden`.

The watchdog has **no start-up grace**: right after a sign-in the Startup shortcut's copy may not have a
`run.py` process yet, so a watchdog tick in the same minute starts a second copy (30 Sep 2026 20:36, §9.6).
The second copy then loses the port-8000 bind and exits by itself (§5.5), after re-pinning the cheat-sheet.
A grace period after boot (and a start-up wait for Ollama) was offered to the owner and is not answered.

### 5.5 One bot per token, always

Two copies polling one token fight (Telegram answers the loser's `getUpdates` with **HTTP 409 Conflict**), both
run the scheduled jobs, and both write the same Google Sheets and send the same alerts. How this is prevented:

| Layer | Mechanism |
|---|---|
| The watchdog | Starts a copy only when no `run.py` under **this folder's** venv exists (either PID of the redirector pair counts). |
| `stop.bat` / `check_status.bat` | Match only this folder's `run.py` and its `-m src.*` jobs (and orphaned jobs whose parent died), so stop → start never leaves a second bot or a half-finished sync. |
| Port 8000 | A second copy's uvicorn cannot bind: `[Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)` (twice in `hangeul_stderr.log`, the second time after the reboot of 30 Sep 2026 20:36: that copy logged `Hangeul Admin API shut down cleanly.` at 20:36:47, 3 s after it started), after which `serve()` exits and `run.py` stops the updater and exits. Note the order in `run.py`: polling starts *before* `serve()`, so such a copy briefly polls (409 for one of them) and re-pins the cheat-sheet before it dies. This is a backstop, not the design. |
| Job locks | `data\auto_sync.lock` (holds the PID; ignored if that PID is dead or the file is older than 2 h, `LOCK_STALE_SECONDS = 7200`; prints `Another sync is still running — skipped.`) and `data\verification\auto_verify.lock`; APScheduler `max_instances=1, coalesce=True` on every job. |
| Publishers | `data\cloud\publish.lock`: one Supabase publisher at a time on this PC (the others wait up to 20 min, the full picture 120 s), so two processes never write `cloud_state.json` together. A **second PC running a copy of this bot with the same Supabase keys would have its own hash state** and fight over the same scopes (each complete read deletes what the other's read does not show): never run two publishers against one project. |
| A second PC | The old PC had to be retired first, in this order so its watchdog could not restart it: `schtasks /Delete /TN "HangeulBotWatchdog" /F`, delete `Startup\HangeulBot.lnk`, `stop.bat`, then check no `python -m src.*` job still runs (a sync in progress keeps writing after the bot stops). **Done:** by 30 Sep 2026 the owner had deleted the old PC's bot and the old Telegram bot. |
| Check from outside | `GET https://api.telegram.org/bot<token>/getUpdates?timeout=0&limit=1` → `409` means another copy is polling this token right now (the session's pre-flight used this). |
| Voice service | Separately single-instance: `service.py` binds `127.0.0.1:8765` with `SO_EXCLUSIVEADDRUSE` before loading any model and exits at once with "already in use" if it cannot. |

For a new bot: give it its **own** token (never reuse this one) and, if it also runs on this PC, its own
folder, venv, port and task names.

---

## 6. Logs

| Log | Written by | Content | Rotation |
|---|---|---|---|
| `C:\Hangeul\BOT\hangeul_bot.log` | `run.py` `logging.FileHandler` (every `hangeul.*`, `telegram.ext`, `httpx`, `apscheduler` logger at INFO) | the main log: startup lines (`Scheduler active ...`, `Application started`, `Successfully set 13 bot menu commands (set_my_commands).`, `Successfully pinned command cheat-sheet to admin chat on startup.`; `Brain ... resident on the GPU ...` only when the brain is pinned), every portal/Telegram request URL (token redacted), job results (`Portal sync finished (exit 0).`, `Full picture publish finished (exit 0).`), warnings. A publish handed over by the bot process itself fails with one line `Supabase publish failed (<job>): …` here | none (~41,000 lines by 30 Sep) |
| `C:\Hangeul\BOT\hangeul_stdout.log` | `run.py` when run by `pythonw.exe` (stdout reopened) | the same log lines again (the StreamHandler) + the `rich` banner | none |
| `C:\Hangeul\BOT\hangeul_stderr.log` | `run.py` when run by `pythonw.exe` | uvicorn's own lines (`Started server process [516]`, `Uvicorn running on http://0.0.0.0:8000`), tracebacks | none |
| `C:\Hangeul\BOT\hangeul_sync.log` | `scheduler._run_module` subprocesses and every Supabase publisher (`handoff.spawn` appends to it) | stdout/stderr of `auto_sync`, `missing_report`, `passport_issue --refresh`, `full_picture`; **one line per publisher run**, e.g. `2026-09-30 22:35:33,477 [INFO] hangeul.cloud: Supabase publish (full_picture): ok, 3 upserted, 0 deleted, 779 unchanged, 3 row(s) sent, 0 failed, 0 read(s) failed; 3 record(s) embedded in 0.1 s; 6.9 s in all, peak memory 0.87 GB.`, the full picture's `Full picture: 12 batch(es) read in 18.3 s, 0 read(s) failed; 68 publish(es), 0 failed.`, and a failure as `Supabase publish failed (<kind or job>): <HTTP status / Postgres code only>` (never data: a server message can quote a key, and keys hold passport numbers) | none |
| `C:\Hangeul\BOT\data\cloud\backfill_YYYYMMDD.log` | the shell that ran the backfill (redirected output) | per-kind counts of the one-time copy (§2.1) | one file per run |
| `C:\Hangeul\BOT\hangeul_watchdog.log` | `watchdog.ps1` every 5 min | `2026-09-29 05:01  running (pid 10188 516)` or `not running - starting it` | none |
| `C:\Hangeul\JARVIS\jennie_voice\jennie_voice.log` | `service.py` | one line per request: timing, device, VRAM/RAM; never more than 40 characters of anything said | `RotatingFileHandler`, 3 × 2 MB |
| `...\jennie_voice\jennie_voice_stdout.log` / `_stderr.log` | `service.py` under `pythonw.exe` | library prints | none |
| `...\jennie_voice\jennie_watchdog.log` | `watchdog_jennie_voice.ps1` | `healthy (pid ...)`, restarts | none |

Log hygiene rules (copy them):
* **The Telegram token is redacted from every log line.** httpx logs each request URL at INFO and a Bot API URL
  carries the token (`https://api.telegram.org/bot<token>/sendMessage`). `src\__init__.py` adds a
  `logging.Filter` to the `httpx` logger that replaces `bot\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}` with
  `bot<token>` (the `%3A` form appears in file-download URLs). When this was added (commit `0fce479`), 2,831
  leaked tokens were scrubbed from the old logs. A search on 29 Sep 2026 found 0 token matches in all five bot logs.
* **The Supabase keys are redacted the same way** (since the publish layer): `src\__init__.py:41-56`,
  `_SECRET_PATTERNS` + `redact(text)`, replaces `Bearer <x>` → `Bearer <redacted>`, `apikey: <x>` →
  `apikey: <redacted>`, `sb_secret_…` → `sb_secret_<redacted>`, `sb_publishable_…`, `sbp_…` (the CLI's token)
  and any JWT (`eyJ….….…` → `<jwt>`). The filter is attached to `httpx`, `httpcore` and its five per-module
  loggers (a filter on a logger does not see its children's records) and `hangeul.cloud` (`:76-79`).
* Logs quote student names and portal responses, so `*.log` is git-ignored and logs are never shared.
* Voice notes are logged as metadata only (`Voice note from <chat>: 4.1s audio, ko, verified_today | filler
  +0.14s, stt 3.39s, ...`), never the words.
* The bot's own logs do not rotate; archive or truncate them by hand when they grow (stop the bot first).

---

## 7. The REST API (port 8000)

`uvicorn` serves `src.api.main:app` (FastAPI, title "Hangeul Korean Language & Visa — Admin API", CORS
`allow_origins=["*"]`) inside the same process: `GET /` (status), `GET /healthz`, `GET /docs` and `/redoc`
(Swagger/ReDoc), and under `/api`: `GET /api/auth/csrf`, `POST /api/auth/login`, `GET /api/auth/status`,
`GET /api/dashboard/stats`, `GET /api/dashboard/alerts`, `GET /api/applications`, `GET /api/applications/inquiries`,
`GET /api/applications/consultations`, `POST /api/crawler/parse-page`. It binds `0.0.0.0:8000` with **no
authentication** (known and accepted). Known leftovers: it still reads the 500-row consultation page, and a
portal failure gives HTTP 500.

---

## 8. GPU memory budget and lessons learned

### 8.1 Who uses the 8 GB card

Card total: 8151 MiB (7.96 GiB). Figures are device-wide `nvidia-smi` or Ollama `/api/ps` measurements from 27-30 Sep 2026.

| Consumer | VRAM | When | Source |
|---|---|---|---|
| Windows desktop + apps (**the monitor is plugged into the RTX card**): explorer ~432 MB, dwm ~381 MB, Chrome ~217 MB, Imou camera app ~163 MB, NVIDIA Overlay ~68 MB, others | **~1.2-1.4 GB** typical (0.9-1.0 GB desktop alone; ~2 GB on 28 Sep morning with more apps) | always | per-process GPU memory, 28 Sep 05:34; `nvidia-smi` 29 Sep: 1158 MiB with nothing else loaded |
| Brain `qwen3:4b-instruct`, `num_ctx` 3072, flash attention + q8_0 KV cache | **2.62 GiB** (2.81 GB) | voice on: always (pinned); voice off: while answering + 5 min | `/api/ps`; log `Brain qwen3:4b-instruct resident on the GPU: 2.62 GB, num_ctx 3072` |
| — same without FA/q8 | 2.82 GiB at 3072; 2.68 GiB at 2048; 2.96 GiB at 4096 | (before 28 Sep) | `src\config.py` comment; brain trial |
| `qwen2.5:7b` (old brain, still pulled) | 4.42-4.7 GB | not used | brain trial |
| Voice service idle | ~0.25-0.3 GB (CUDA context only) | while running | README of jennie_voice |
| Speech-to-text (faster-whisper large-v3-turbo fp16) | **~2.2 GB** (+2.0 loaded, +0.13 transcribing); loaded per note, unloaded right after | per voice note; only if ≥3.0 GB free (`STT_GPU_MIN_FREE_GB`) | bench / smoke test |
| Text-to-speech (CosyVoice2-0.5B) | **~3.4-3.5 GB** peak (weights 2.6 + work 0.9); 3.3-3.9 GB torch-reserved peaks per render; stays 2.6 GB for 5 idle min | per reply; moved to the GPU only if `TTS_GPU_NEED_GB = 3.8` free (1.2 if already there) | README, latency harness |
| EasyOCR in the 15-minute sync's document check (`doc_verifier`, `gpu=torch.cuda.is_available()`) | ~1.5-2.4 GB, peaks ~3.9 GB | during syncs with newly verified students | HANDOFF, session notes |
| Passport watcher OCR (`ocr_validator`, `easyocr.Reader(['en'], gpu=False)`) | 0 (CPU) | every 30 min | code |
| **Supabase publishers, the backfill and the hourly full picture** (gte-small, `device="cpu"`, float32) | **0** — CUDA is hidden (`CUDA_VISIBLE_DEVICES=-1`) before torch is imported, so `torch.cuda.is_available()` is False and `device_count()` 0 | every publish (after jobs, commands, hourly) | the three dry runs of 29 Sep: `nvidia-smi` 678-1157 MiB before, during and after (desktop + the live bot), and the embedding process's PID never appeared in the compute-app list (82-369 samples) |
| A game (EA SPORTS FC 25) | ~3-4 GB | if the owner plays | session notes |

Resulting states:

| State | Used | Headroom |
|---|---|---|
| **Now: voice off, brain on demand, idle** (measured 30 Sep 2026: 950 MiB at 23:4x, 678-1157 MiB during the dry runs) | **~1.0-1.2 GB** | ~6.8 GB |
| **Now, peak**: the brain loaded for a typed question or the brief's summary (2.62 GiB for 5 min), or EasyOCR in a sync's document check (peaks ~3.9 GB) | **~3.8-3.9 GB** | ~4.1 GB |
| Voice on, idle (desktop + pinned brain + voice context) | ~4.6-4.8 GB | ~3.2-3.4 GB |
| Voice on, during a Korean reply | 7.1-7.8 GB peaks (8-9.8 GB with extra apps = spill) | at the edge |

### 8.2 Lessons (each one cost time)

1. **The monitor on the RTX card costs ~1.2-1.4 GB.** Windows puts explorer, dwm and every app window on the
   GPU the display is attached to. The Ryzen 5 8600G has its own Radeon 760M: **plugging the monitor into the
   motherboard's HDMI/DisplayPort** moves all of that off the RTX. Recommended on 28 Sep 2026 as the single
   biggest free VRAM win; it is the owner's action and had not been confirmed done (29 Sep: 1158 MiB still used
   with nothing loaded; 30 Sep 23:4x: 950 MiB; both suggest the display is still on the RTX).
2. **Windows does not fail on VRAM overcommit, it pages.** With the WDDM "system memory fallback", an
   allocation that does not fit silently spills into shared system RAM and everything on the card slows:
   Korean TTS renders went 2-7× slower (11 characters 10.5 s, 27 characters 99 s, while other runs of the same
   lines took 3.8-5.2 s), one live voice note took 25.8 s instead of ~12 s, and one long OCR process slowed from
   ~90 s to ~570 s per student (7 GB VRAM + 6 GB spilled). `PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold`
   made it worse. Budget VRAM on paper, and run OCR in fresh processes of 5 students.
3. **`torch.cuda.mem_get_info` is not a reliable gate on this setup**: it did not see the resident brain before
   the TTS model was moved to the GPU, so `TTS_GPU_NEED_GB` did not stop the move; the latency harness logged
   `tts_move cuda ... free_gb 0.31`. Start the voice service first (let it finish its GPU warm-up), then the bot.
4. **Killing `ollama.exe` / "ollama app" orphans `llama-server.exe`.** The runner child survives its parent and
   keeps the model in VRAM (~3 GB found on 28 Sep, alongside the new runner). After any Ollama restart, kill
   runners whose parent is gone (section 8.3).
5. **Flash attention + a q8_0 KV cache** (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, Ollama server
   env) saved 0.2 GiB at `num_ctx` 3072 (2.82 → 2.62 GiB); the brain has run with them since 28 Sep 2026.
6. **One `num_ctx` for every call.** Ollama reloads the model whenever a load option differs from the copy in
   VRAM (seconds each time). Only `num_predict` varies per call (load 0.002 s).
7. **A 7B brain does not fit beside the voice.** `qwen2.5:7b` (4.4-4.7 GB) left ~2.2 GB, so both Whisper and
   CosyVoice fell back to the CPU (a 4 s Korean reply took 64 s). It was replaced by `qwen3:4b-instruct` (2.6 GB).
8. **The brain is loaded on demand when the voice is off** (commit `c17d887`, approved 28 Sep 2026):
   `brain_pinned() = JENNIE_VOICE_ENABLED or BRAIN_ALWAYS_LOADED`. Pinned → every call sends `keep_alive: -1`,
   `post_init` runs `warm_brain()` (3 attempts, 30 s apart, reload if partly on the CPU) and `brain_keep_warm`
   checks every 10 min. Not pinned → every call sends `keep_alive: BRAIN_IDLE_UNLOAD` ("5m"), `post_init` sends
   `{"model": ..., "keep_alive": 0}` to release a copy an earlier run pinned, and `keep_brain_warm` does nothing.
   Cost: the first typed answer after a quiet spell waits ~3 s for the load. The GPU idles at ~1.0 GB.
9. **Games share the GPU.** With a game open, OCR went from 1.8 s to ~17 s per A4 page; game + EasyOCR + brain
   exceed 8 GB and an out-of-memory during OCR can cache truncated text as final. No VRAM guard was added (open
   question): never run a cold start or a full re-check with a game open.
10. **RAM is tight too.** The voice service holds ~5.5 GB working set (private 7.8-10.4 GB: Windows commits
    system memory for VRAM allocations), the bot ~5.4 GB private, the resident brain's `llama-server.exe` 0.7 GB
    working set / 3.9 GB committed; free RAM was 1.7-2.7 GB with everything running.
11. The voice was **switched off on 28 Sep 2026 17:08** because it was "maxing" the GPU (8-9.8 GB at peak);
    GPU use fell to 3.8 GB, then to ~1.0 GB with the brain on demand. It was still off on 30 Sep 2026
    (`JennieVoiceWatchdog` Disabled, `JennieVoice.lnk` in `C:\Hangeul\JARVIS\disabled\`, nothing answering on
    127.0.0.1:8765, both `.env` flags `false`, `ollama ps` empty when idle).
12. **Keep new CPU work off the GPU explicitly, not only by `device="cpu"`.** The embedder asks for the CPU,
    and on top of that the publisher, backfill and full-picture processes hide the GPU before torch loads, so
    no library in them can create a CUDA context or allocation on the card the brain and EasyOCR share (rule
    R12 in [09](09_BLUEPRINT_RULES_AND_LESSONS.md): the 8 GB GPU stays with Ollama and the OCR). Only `-1` works on Windows: an
    empty `CUDA_VISIBLE_DEVICES` is dropped from the real process environment, so torch still found the GPU
    (found in dry run 2, fixed in `752cd53`). A process that imported torch before hiding it refuses to embed
    (`embed.prepare_process` raises `EmbedError`).
13. **transformers 5 loads gte-small as float16 unless told otherwise**, which is ~7× slower on the CPU:
    `SentenceTransformer(..., device="cpu", model_kwargs={"dtype": torch.float32})` (`src\cloud\embed.py:221-222`).

### 8.3 Checking and cleaning the GPU (read-only first)

```powershell
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
ollama ps                                                  # the loaded model, its size and UNTIL
(Invoke-RestMethod http://127.0.0.1:11434/api/ps).models | Select-Object name, size_vram, context_length, expires_at
# orphaned runners (parent process gone) after an Ollama restart:
Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
  Where-Object { -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) } |
  Select-Object ProcessId, ParentProcessId, CommandLine
# then, only for those: Stop-Process -Id <pid> -Force
```

Restarting Ollama safely: quit the tray icon (or `Stop-Process -Name "ollama app","ollama"`), kill orphaned
`llama-server.exe` as above, start `C:\Users\User\AppData\Local\Programs\Ollama\ollama app.exe`, then (voice on)
let `brain_keep_warm` reload the brain within 10 minutes or restart the bot.

---

## 9. Day-2 operations

### 9.1 Daily health check

| Check | How | Healthy |
|---|---|---|
| Bot process | `C:\Hangeul\BOT\check_status.bat`, or the last line of `hangeul_watchdog.log` | two PIDs (`...\.venv\Scripts\pythonw.exe run.py` and its Python312 child) |
| Answers | send `/stats` in Telegram | live figures, not demo data |
| 18:05 brief | `hangeul_bot.log`: `Daily brief composed: portal read in N s ...` then `Scheduled briefing dispatched successfully.` | both lines around 18:05-18:07 |
| Sync | `hangeul_sync.log`, `hangeul_bot.log`: `Portal sync finished (exit 0).` | exit 0 every 15 min |
| GPU | `nvidia-smi` | ~1.0-1.2 GB idle with the voice off (950 MiB on 30 Sep 23:4x) |
| Ollama | `ollama ps` | empty when idle (voice off); `qwen3:4b-instruct` listed with no near expiry when pinned (`/api/ps` then shows an `expires_at` in the year 2319, i.e. keep_alive -1) |
| Supabase | `Select-String "hangeul.cloud" C:\Hangeul\BOT\hangeul_sync.log \| Select-Object -Last 8` | a `Supabase publish (portal_sync): ok, …` line every 15 min and `Supabase publish (full_picture): ok, …` + `Full picture: 12 batch(es) read …, 0 read(s) failed` every hour; no `Supabase publish failed` lines; `data\cloud\pending\` empty between runs. From outside: the newest `hg_runs` rows (Supabase dashboard, or PostgREST with the secret key) have `status` ok and a `finished_at` |

### 9.2 Deploying a change

1. **Edit in `C:\Hangeul\BOT`** on `main` (for a larger change: a branch or a git worktree, merged with
   `git merge --ff-only`). If you change `src\bot\telegram_bot.py`, `src\config.py` or
   `src\sheets\progress_builder.py`, copy it over its root twin (`telegram_bot.py`, `config.py`,
   `progress_builder.py`) and check `fc /b` (or `cmp`) reports them identical.
2. **Test** (never a bare `pytest` from the bot folder: old root scripts are not tests):
   ```powershell
   .venv\Scripts\python.exe -m py_compile src\bot\telegram_bot.py src\bot\scheduler.py src\bot\voice.py
   .venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider   # 1150 passed, 2 skipped at 8317741
   .venv\Scripts\python.exe -c "import src.bot.telegram_bot, src.bot.scheduler, src.bot.voice, src.cloud.publish; print('imports ok')"
   ```
   The tests mock the portal, Telegram (fake PTB objects), Ollama, the voice service and Supabase
   (`httpx.MockTransport`; `tests\conftest.py` switches publishing off for every test); they never touch the
   live portal or the live project. For behaviour against the live portal, the sessions ran read-only
   harnesses with fake Telegram objects (`C:\Hangeul\JARVIS\brain-trial\brief_crosscheck.py`,
   `latency_harness.py`, the `command-audit\*` scripts) and, for Supabase, guarded dry runs (the portal allowed
   GET + the login POST only, `publish.TRANSPORT` raising on any Supabase request), never the real bot. Larger
   changes were built in git worktrees under `C:\Hangeul\JARVIS\` (`cloud\*`, `perf\build`, `perf2\build`) and
   fast-forwarded onto `main`.
3. **Commit** one change per commit with a message that says why
   (`git add <files>`, `git commit`; the commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).
   Nothing is pushed.
4. **Restart at a quiet moment**: not between 18:00 and 18:10 (brief), 08:25-08:40, 09:00-09:10, not while a
   sync runs (`check_status.bat` shows a `-m src.sheets.auto_sync` process; `stop.bat` would kill it mid-write),
   and preferably not while a `-m src.cloud.publish` or `-m src.cloud.full_picture` process is listed (`stop.bat`
   kills those too, §5.3). The restart used on 30 Sep 2026 (21:47 and 22:27), which also refuses to start a
   second copy if anything is left:
   ```powershell
   cmd /c "C:\Hangeul\BOT\stop.bat" nopause; Start-Sleep -Seconds 3
   if (@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run\.py' }).Count -eq 0) {
       Start-Process wscript.exe -ArgumentList '"C:\Hangeul\BOT\start_background.vbs"'; Start-Sleep -Seconds 35
   } else { "STILL RUNNING - not starting" }
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run\.py' } | Select-Object ProcessId, CreationDate, CommandLine
   ```
   Always the **full path** of `stop.bat` (a bare `stop.bat` from PowerShell is "not recognized", §5.3), or
   leave it to the watchdog: it restarts the bot within 5 minutes. **Never** stop python processes by name
   (`Stop-Process -Name python*`): other agents and jobs run on this PC too, and an unexplained 5-minute
   outage on 29 Sep 16:36-16:41 (watchdog `not running - starting it` at 16:41; the bot was killed with no
   error line) happened during agent test runs (cause unconfirmed; some agent transcripts show kill /
   `Stop-Process` calls). Restarting shifts the phase of the 15- and 30-minute jobs and of the hourly full picture (first run
   7.5 min after the start).
5. **Verify**: `hangeul_bot.log` shows `Scheduler active ..., Supabase full picture every 60m.`, `Application
   started`, `Successfully set 13 bot menu commands (set_my_commands).`, and no Traceback in
   `hangeul_stderr.log` (the new uvicorn `Started server process [<pid>]` must not be followed by `[Errno 10048]`);
   the admin chat gets one pinned cheat-sheet; send `/stats` and the command you changed; ~8 minutes later
   `hangeul_sync.log` has a `Supabase publish (full_picture): ok` line.
6. If the change touched `.env`, keep a copy of the previous file (e.g. `.env.bak-YYYYMMDD`, it is git-ignored
   by `.env.*`) before editing. Append a line only after checking the file ends with a newline, and never
   leave a bool key with an empty value (`CLOUD_PUBLISH_ENABLED=` stops `Settings`, so the bot cannot start).

### 9.3 Rolling back

```powershell
git -C C:\Hangeul\BOT log --oneline -10
git -C C:\Hangeul\BOT revert --no-edit <bad-commit>        # preferred: keeps history
#   or restore one file:  git -C C:\Hangeul\BOT checkout <good-commit> -- src\bot\brief.py
#   (and copy it over its root twin if it is telegram_bot.py / config.py / progress_builder.py)
.venv\Scripts\python.exe -m pytest tests -q
cmd /c "C:\Hangeul\BOT\stop.bat" nopause
Start-Process wscript.exe -ArgumentList '"C:\Hangeul\BOT\start_background.vbs"' -WorkingDirectory C:\Hangeul\BOT
```

The commit list is the rollback map (oldest first): `366dec0` baseline GitHub snapshot → `f74e45d` two FAIL rules
to FLAG → `c5c1a7c` refuse all when no admin ID → `a012bcb` pinned requirements → `4154aa5` configurable paths →
`053efc5` self-locating launchers → `d659983` OCR verbose=False → `03ccf15` phase 3 all students → `b0245df`
MIGRATION rewrite → `0fce479` token redaction → `d7a5817` Jennie's voice → `e205327` %3A redaction + plain-text
fallback → `7241465` watcher OCR off the event loop → `d9bbecc` fast Jennie (qwen3:4b-instruct resident) →
`cd0277a` consultations by column name → `f8fefa4` factual brief → `e0d47ab` … `344a247` all-commands fix
(foundation, inquiries, crosscheck, freetext, jobs, merges) → `e164679` repairs → `c17d887` last re-verify
cases + brain on demand (the pack's first edition) → then, on 29-30 Sep 2026:

| Commit(s) | What | Deployed to `main` |
|---|---|---|
| `36ae72e` `a0572ba` `cfd10f1` | the publish layer core (`src\cloud`: records, hash state, `hg_sync`, runs, handoff, backfill) | 30 Sep 21:47 (with the rest of `cloud/release`) |
| `2b6798f` `5048a07` `41055de` + merges `44c9378` `112325b` `969f917`, `cb16394` | the hooks: command handlers and free-text answers, the brief / watcher / hourly full picture, the sheet jobs | same |
| `3caa393` `752cd53` `9ead47d` | review fixes; the dry-run fixes (portal fillers blanked + `blank_on_portal`, one log line a run, `CUDA_VISIBLE_DEVICES=-1`, 1 MB body cap); Cloudflare e-mail decoding (`parsers.decode_cf_emails`) | same |
| `bbd8f98` `a721066` | performance commands v1 (self-computed tally) | 30 Sep 10:31 (**replaced** by the next row) |
| `ce23535` `314afdb` | `/performance_today`, `/performance_month` = only the portal's Consultant Performance page (`consult_performance.php?period=today\|month`) | 30 Sep 14:06 |
| `e5e532e` (merge main into `cloud/release`) `e4d1cea` `8317741` | the kind `consultant_performance` (scope `<period>\|<first ISO day>`), the backfill reads the page | 30 Sep 21:47, fast-forward to `8317741` |

To roll back **only the publishing**, do not revert commits: set `CLOUD_PUBLISH_ENABLED=false` and restart
(§3.11, last paragraph); the code then does nothing at all. Reverting `src\cloud` would also need the hooks in
`src\sheets\*`, `src\bot\scheduler.py`, `src\bot\telegram_bot.py` (+ its root twin), `src\bot\brief.py`,
`src\bot\ask.py` and `src\bot\performance.py` reverted, and would leave Supabase's rows as they are. Data files
(`data\`, `results.json`, `cloud_state.json`) are not in git: back up `data\verification\results.json` (the
only copy of the Corrections history) and `data\cloud_state.json` before anything risky.
Rolling back the model: `OLLAMA_MODEL=qwen2.5:7b` in `.env` would work (still pulled) but does not fit beside the voice.

### 9.4 Re-enabling Jennie's voice (fully built, switched off on 28 Sep 2026 17:08)

State checked on 30 Sep 2026 (read-only): `.env` `JENNIE_VOICE_ENABLED=false` and `JENNIE_SPOKEN_BRIEF=false`;
`Get-ScheduledTask JennieVoiceWatchdog` → **Disabled** (`HangeulBotWatchdog` Ready); the Startup folder holds
`HangeulBot.lnk`, `Ollama.lnk` and the owner's `Send to OneNote.lnk` only, `JennieVoice.lnk` is parked in
`C:\Hangeul\JARVIS\disabled\`; `http://127.0.0.1:8765/health` does not answer; the brain is on demand
(`brain_pinned()` False, so `post_init` unloads it and `brain_keep_warm` does nothing). Nothing else in the
bot depends on the voice. The why and the voice design are in [06 §5](06_LLM_AND_JENNIE_VOICE.md).

```powershell
# 1. .env flags (edit C:\Hangeul\BOT\.env):
#      JENNIE_VOICE_ENABLED=true
#      JENNIE_SPOKEN_BRIEF=true            (optional: the spoken 18:05 brief)
# 2. autostart shortcut back into Startup:
Move-Item "C:\Hangeul\JARVIS\disabled\JennieVoice.lnk" "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\"
# 3. the watchdog task:
Enable-ScheduledTask -TaskName JennieVoiceWatchdog
# 4. start the service FIRST and wait for it (35-60 s):
wscript.exe "C:\Hangeul\JARVIS\jennie_voice\start_jennie_voice.vbs"
do { Start-Sleep 5; try { $h = Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 5 } catch { $h = $null } } until ($h.ok)
# 5. then restart the bot so it registers the voice handler and pins the brain:
cmd /c "C:\Hangeul\BOT\stop.bat" nopause
Start-Process wscript.exe -ArgumentList '"C:\Hangeul\BOT\start_background.vbs"' -WorkingDirectory C:\Hangeul\BOT
```

Expect in `hangeul_bot.log`: `Jennie voice replies enabled (voice service http://127.0.0.1:8765).` and
`Brain qwen3:4b-instruct resident on the GPU: 2.62 GB, num_ctx 3072, ready in ...`; `ollama ps` keeps
listing the model (no idle expiry); the GPU idles at ~4.6 GB. Test with a short voice note. Consider moving the monitor cable first.

**Switching it off again** (what was done on 28 Sep): `.env` both flags `false`;
`Disable-ScheduledTask -TaskName JennieVoiceWatchdog` (or `schtasks /Change /TN "JennieVoiceWatchdog" /DISABLE`);
move `JennieVoice.lnk` from Startup to `C:\Hangeul\JARVIS\disabled\`;
`cmd /c "C:\Hangeul\JARVIS\jennie_voice\stop_jennie_voice.bat" nopause`; restart the bot (it then releases the
brain). Disable the watchdog before stopping the service, or it starts it again within 5 minutes.

### 9.5 Other routine tasks

| Task | How |
|---|---|
| Add a colleague | They press Start on @the_Jennie_bot and send `/start` (the refusal shows their ID); add it to `TELEGRAM_AUTHORIZED_CHAT_IDS`; restart. |
| Google says "login required" | Delete `token.json`, run `gauth.bat`. If the consent screen shows "Testing", publish it first. |
| HTTPS breaks (`CERTIFICATE_VERIFY_FAILED`) | `tools\export_windows_ca.ps1`, append to certifi (section 3.3), restart. |
| Telegram unreachable | The DNS probe logs `Telegram DNS override active: api.telegram.org -> <ip>`; force one with `setx TELEGRAM_API_IP <ip>` and sign out/in. |
| Full document re-check | Stop nothing; run the 5-student batch loop (section 3.9) while no game runs. |
| Remove autostart / watchdog | `schtasks /Delete /TN "HangeulBotWatchdog" /F`; delete `Startup\HangeulBot.lnk`. |
| Rotate a secret | [secrets/README.md](secrets/README.md) section 4, then restart. |
| Move to another PC | Follow `C:\Hangeul\BOT\MIGRATION.md` (written from the real move) and this file; retire the old copy first (section 5.5). Copy `data\cloud_state.json` and `data\cloud\student_index.json` with `data\` (without them the new PC re-sends everything once), install the gte-small cache (§3.11 step 2) and never let both PCs publish (§5.5). |
| Switch Supabase publishing off / on | `CLOUD_PUBLISH_ENABLED=false` / `true` in `.env` (never empty), restart (§3.11). |
| Apply a new Jeannie migration | Pull the Jeannie repo (`git -C C:\Hangeul\JARVIS\Jeenie-saem-bot pull`, keep `core.autocrlf false`), then the CLI block of §3.11 step 5 (`db push --dry-run` first: it must list only the new file). Migrations are Jeannie's; the bot side never writes SQL. |
| Re-run the backfill (e.g. after Supabase lost data) | Outside the quiet windows: `.venv\Scripts\python.exe -m src.cloud.backfill --dry-run`, then without `--dry-run` (publishing on in `.env`, or `CLOUD_PUBLISH_ENABLED=true` for that process); `--ignore-state` re-sends every record (Supabase answers "unchanged" for identical rows). Output to `data\cloud\backfill_YYYYMMDD.log`. |
| A publish failed | `hangeul_sync.log`: `Supabase publish failed (<kind>): <reason>` (`publish._reason`, `src\cloud\publish.py:353-372`): `HTTP 401/403 … (the key was refused)` = the secret key; `HTTP 404 … (hg_sync or hg_runs not found: is the Jeannie migration applied?)` = schema missing; `HTTP 5xx … (Supabase server error)`; `Supabase did not answer in time (…)` / `could not connect to Supabase (…)` = network. After any of those the rest of that run is skipped without more lines. Nothing to repair by hand: the hash state did not advance, so the next read sends those rows. |
| Remove the build worktrees | `git -C C:\Hangeul\BOT worktree remove C:\Hangeul\JARVIS\cloud\<name>` for `core jobs inproc commands all release`, then `git -C C:\Hangeul\BOT branch -d cloud/<name>`: only when the owner agrees (`cloud\all` holds the dry-run payloads with student data). |

### 9.6 What a reboot does (observed 30 Sep 2026, 20:35)

The PC rebooted by itself at about 20:35 (not an action of the sessions). Everything came back without help,
with two blemishes that show the start-up races:

| Time | What happened (from `hangeul_watchdog.log`, `hangeul_bot.log`, `hangeul_stderr.log`) |
|---|---|
| 20:31 | last `running (pid 15920 14800)` of the old boot |
| 20:36:34-39 | copy 1 (Startup `HangeulBot.lnk`): `Telegram reachable via normal DNS (149.154.166.110); no override needed.`, then `Ollama not reachable at http://127.0.0.1:11434:` — `Ollama.lnk` starts at the same sign-in and was not listening yet. The bot does not wait: it starts anyway (free text falls back to label matching until Ollama answers) |
| 20:36 | the watchdog tick found no `run.py` yet → `not running - starting it` → copy 2 |
| 20:36:40-41 | copy 1: `Application started`, `Successfully set 13 bot menu commands`, cheat-sheet sent + pinned |
| 20:36:44-47 | copy 2: the same (a **second pinned cheat-sheet** in the admin chat), its `unload()` reached Ollama (`POST /api/generate 200`: Ollama was up by then), then uvicorn `[Errno 10048]` on port 8000 → `Hangeul Admin API shut down cleanly.`, `Application.stop() complete`: it stopped itself 3 s after starting |
| 20:41 | `running (pid 22524 1256)`: one bot. No scheduled job fired in copy 2's three seconds (the interval jobs count from the start, the cron jobs were hours away) |

What this means for operations: after a reboot expect two "Ollama not reachable" warnings and possibly two
pinned cheat-sheets; both are harmless. The Supabase layer needs nothing at boot (no process of its own;
`data\cloud\pending\` files older than 6 h are pruned by the next handoff). Two fixes were offered to the
owner and are **not decided**: wait up to 60 s for Ollama at start-up before warning, and give the watchdog a
grace period after boot (for example, skip its first tick when the system has been up for less than 3
minutes). See [11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md).
