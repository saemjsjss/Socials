# 08 — History, stage by stage

**What's in this file:** the full chronological story of Hangeul BOT on this PC, from the lost old PC (before 27 Sep 2026) through the first reference pack (29 Sep), the Supabase publish layer, the two versions of the performance commands, the real backfill and publishing going live (30 Sep 22:27), to this refresh of the pack (30 Sep 2026). For every stage: the goal, the decisions (and who made them, in the owner's words where they were decisive), what was built or changed (files, commits), the problems and their fixes, and how each result was verified. Times are Asia/Dhaka (+06:00); commit times come from `git -C C:\Hangeul\BOT log`.
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), at `main` = `8317741` (48 commits). First written 29 Sep 2026 at `c17d887`; §0 rows from 29 Sep 05:00 on and §8–§18 are new in this refresh, and the appendices were extended.
**Read with:** [Open items](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md) (what is still open), [Supabase publishing](13_SUPABASE_PUBLISHING.md) (the layer built in §10–§17, as a spec), [Files: src/cloud](03d_FILES_src_cloud.md), [Blueprint rules and lessons](09_BLUEPRINT_RULES_AND_LESSONS.md), [Architecture](01_ARCHITECTURE.md), [Portal](04_PORTAL_INTEGRATION.md), [Sheets and document check](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), [Commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md), [LLM and Jennie](06_LLM_AND_JENNIE_VOICE.md), [Environment](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md), [Tests](10_TESTS_AND_VERIFICATION.md), [Index](00_INDEX.md).

Who decides: **Owner** = the agency owner (the user; also the git author of every commit, see `git log`). **Claude** = the Claude Code agent (it recommended an option; the owner chose). Every decision in this file was made by the owner unless it says otherwise. Secrets are never quoted here: a secret is named as "value in secrets/bot.env (KEY)", for keys such as `TELEGRAM_BOT_TOKEN`, `HANGEUL_PASSWORD`, `GMAIL_APP_PASSWORD`, `SUPABASE_SECRET_KEY` and `SUPABASE_ACCESS_TOKEN`. Student personal data is replaced by placeholders, and staff appear by role (consultant, the top performer), never by name.

---

## 0. Timeline at a glance

| When | Stage | Commits / runs |
|---|---|---|
| ≤ 26 Sep 2026 | The bot runs on the old PC (i3-14100, RTX 5060 8 GB, `E:\BOT`, Python 3.11). HANDOFF.md (25 Sep), MIGRATION.md "clean-start version" and PC_BUILD.md (26 Sep) written there | on GitHub (`hangeul-bot-main` zip) |
| 26 Sep | "26 September outage": the Google sign-in token expired (OAuth app still in *Testing*, 7-day token life) | — |
| 27 Sep 04:44 | Session 1 starts: "read the migration markdown files and execute /grill-me" | transcript `3b9b6ced-…jsonl` |
| 27 Sep 04:51–05:20 | Pre-grill audit of MIGRATION.md (workflow `wd9k5egdv`, 9 agents, 126 findings) and the grill-me interview (decisions 1–13) | — |
| 27 Sep 05:22–06:43 | Pre-cold-start code changes | `366dec0` → `f74e45d`, `c5c1a7c`, `a012bcb`, `4154aa5`, `053efc5`, `d659983`, `03ccf15` |
| 27 Sep 05:55–07:35 | Ollama install; `.env`; new Telegram bot; Google OAuth; Konyang-in-Drive decision | — |
| 27 Sep 07:17–11:46 | Cold start phases 2 → 1 → 3 → 4 → 5, quiet sync, bot started 11:46 | — |
| 27 Sep 14:35–14:37 | Decision 18 (apostille-first stays FAIL); MIGRATION.md rewritten | `b0245df` |
| 27 Sep 14:53–20:02 | Jennie voice: interview J1–J9, three trial workflows, build workflow, deploy | `0fce479`, `d7a5817` |
| 27 Sep 20:03–20:19 | First Telegram voice test; token `%3A` leak; Markdown fallback; Korean-as-English fix (voice service) | `e205327` |
| 27 Sep 20:21–23:57 | "Too slow" → brain trial → qwen3:4b-instruct; bot "not replying" (watcher blocks loop); build approved | — |
| 28 Sep 01:51 | Fast Jennie + non-blocking passport watcher deployed | `7241465`, `d9bbecc` |
| 28 Sep 10:31 (session 2) | Slow voice (full GPU) and inquiries report all zeros | transcript `b90661d9-…jsonl` |
| 28 Sep 11:24 | Consultation reader by column name; Ollama memory settings; orphaned runner killed | `cd0277a` |
| 28 Sep 11:50–13:51 | LLM brief invented facts → factual brief (workflow `wnhlel5f5`); command-accuracy audit (workflow `wup29tzrh`) | `f8fefa4` |
| 28 Sep 13:55–17:45 | All-commands fix workflow `wyjyqe0pz` (11 agents): foundation, 4 parallel branches, merge, verify, repair, re-verify, last fixes | `e0d47ab`, `46cdf03`, `9dcd9ad`, `40da0e6`, `7f42ad0`, merges `65fdba1` `638655b` `df021de` `981d63d`, `344a247`, `e164679`, `c17d887` |
| 28 Sep 17:07–17:19 | Voice turned off; brain on demand approved | (in `c17d887`) |
| 28 Sep 18:05–18:06 | 18:05 brief sent from `f8fefa4`; `c17d887` deployed at 18:06 | — |
| 28 Sep 20:22–20:23 | Passport false alarm for one student (`<uid>`) found; fix designed | the diagnosis script in `C:\Hangeul\JARVIS\fix\scratch\final\` |
| 29 Sep 04:54–04:57 | Reference pack requested; passport fix **deferred** ("not now") | this pack |
| 29 Sep 05:00–06:31 | First reference pack written, checked (31 issues) and fixed (§8) | workflow `w1vzele87`; pack as of `c17d887` |
| 29 Sep 07:58–08:02 | GPU usage question: 15 % now, 50 % peak with voice off, 100 % with voice on (§9) | — |
| 29 Sep 09:04–09:23 | The Supabase prompt; owner decisions (public Jeannie accepted, full PII stands, project `dcbcbpwpmdtaanboetiz`, download yes, wait for preconditions); model download (§10.1–10.3) | — |
| 29 Sep 09:27–10:33 | Key mix-ups (placeholder in `.env`; personal access token vs secret key); Supabase CLI v2.118.0; the 4 Jeannie migrations applied; every precondition passes (§10.4–10.5) | — |
| 29 Sep 10:34–15:03 | Supabase build workflow: core, 3 hook branches, merge, network drop 12:16 and resume 13:23, 3 reviews (21 issues), fix, dry run 1 (§11) | `36ae72e` → `cb16394`, `3caa393` |
| 29 Sep 15:05–16:45 | Dry-run fixes (fillers, log flood, CUDA hiding, body cap), dry run 2 finds Cloudflare e-mail stand-ins, fix, dry run 3 "ready" (§12) | `752cd53`, `9ead47d` |
| 29 Sep 16:36–16:41 | Bot down ~5 minutes, no error; watchdog restart; cause unconfirmed (§12.5) | — |
| 29 Sep 20:08 | Owner: "I'll inspect the payloads first" (nothing uploaded) | — |
| 29 Sep 21:12 → 30 Sep 10:31 | Performance v1 (self-computed team figures): build, live verify, review; fix interrupted by the session end, resumed, deployed (§13) | `bbd8f98`, `a721066` |
| 29 Sep 22:06 | Owner reports the old PC's bot (28 Sep) and the old Telegram bot (29 Sep) deleted | — |
| 30 Sep 13:11–14:06 | Owner correction: performance = the portal's Consultant Performance page only → v2, deployed (§14) | `ce23535`, `314afdb` |
| 30 Sep 20:35–20:53 | PC reboot: Ollama late, duplicate bot stopped itself; startup fixes offered (§15) | — |
| 30 Sep 20:54–21:47 | "let's start uploading supabase": release merge, new kind `consultant_performance`, preflight, scope fix, deploy with publishing off (§16) | `e5e532e`, `e4d1cea`, `8317741` |
| 30 Sep 21:48–22:27 | Real backfill (13,540 records, 15,629 chunks), independent postcheck "verified", publishing on (§17) | — |
| 30 Sep 22:35 / 22:43 | First automatic runs: `full_picture` (3 upserted) and `portal_sync` (0 upserted) (§17) | — |
| 30 Sep 23:38– | This refresh of the pack (§18) | pack as of `8317741` |

---

## 1. The old PC and why the system moved

**Goal before this work:** keep the agency's Telegram bot, the 15-minute portal-to-Sheets sync and the OCR document verifier running.

**The old machine** (from `PC_BUILD.md` and `HANDOFF.md` in the baseline commit `366dec0`):

| Fact | Value |
|---|---|
| CPU / GPU | Intel i3-14100 (4 cores) / RTX 5060 8 GB |
| Disk | one Colorful CN600 512 GB SSD; system drive C: had 9 GB free of 119 GB (`.ollama` 4.4 GB + Python/torch 5.4 GB) |
| Layout | bot in `E:\BOT`, documents in `E:\VERIFIED STUDENT DOCUMENTS`, `E:\KONYANG DOCUMENTS` (48 students) |
| Python | 3.11 (launchers hard-coded `Python311\pythonw.exe`) |
| Measured limits | OCR ~50 s/student cold, ~6 s cached; full re-check of 154 students ≈ 90 min; `CUDA out of memory — 7.93 GiB` when a second OCR process started (EasyOCR ~1.5 GB + qwen2.5:7b ~4.7 GB); RAM at 2133 MT/s (XMP off) |
| Verdicts (HANDOFF §5.1) | PASS 1 · REVIEW 8 · FAIL 123 · INCOMPLETE 22 of 154, "mostly four rules" known to give false FAILs |

**Why a move:** `PC_BUILD.md` (26 Sep) proposed a new workstation (i7-14700, RTX 5080 16 GB) because the CPU and single disk were the limits, and planned a **split** (old PC keeps bot + sync; new PC does OCR). `MIGRATION.md` (26 Sep, "clean-start version") planned a **full move** that rebuilds everything from the portal instead of copying the old machine's caches ("nothing stale follows the system across"). On the same day the bot's Google access broke (the "26 September outage": the OAuth app was still in *Testing*, whose tokens expire after 7 days); the pre-grill audit noted that the docs disagree on its cause.

**What actually happened:** the owner downloaded the GitHub zip onto a *different* PC: Ryzen 5 8600G (with iGPU), RTX 5060 8 GB, ~16 GB RAM, one 1 TB C: drive, **no E:**, only Python 3.12. The old PC was **gone, with no access** (decision 2), so no `.env`, `token.json`, `credentials.json`, `data\` or Konyang folder could be copied. The GitHub zip became the only source of the code; the untouched original stays at `C:\Users\User\Downloads\hangeul-bot-main\hangeul-bot-main`.

---

## 2. Pre-grill audit of the docs (27 Sep 04:44–05:13)

**Goal:** before asking the owner anything, check every claim in MIGRATION.md, PC_BUILD.md and HANDOFF.md against the code and this PC.

**Run:** workflow `wd9k5egdv` "Read-only audit of MIGRATION.md against the code and this machine, before grilling the user" (9 agents). Log: *126 findings; 47 blocker/high non-confirmed findings go to adversarial verification*. Output: `C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Downloads-hangeul-bot-main-hangeul-bot-main\3b9b6ced-8eb2-4579-8655-1be5b8ddc988\tasks\wd9k5egdv.output`.

**Blocker / high findings that shaped the grill** (verbatim titles, shortened):

| Severity | Finding |
|---|---|
| blocker | `E:` hard-coded in **11** runtime files, not the 5 MIGRATION §6 lists: `bootstrap.py:35/:104`, `verified_docs`, `auto_verify`, `doc_verifier`, `page_checks:294`, `auto_sync:44`, `start_background.vbs` (also `Python311`), `install_autostart.bat`, `install_watchdog.bat`, `watchdog.ps1`, `check_status.bat`, plus `start.bat`'s Python311 path |
| blocker | Without E:, phase 4 downloads every ZIP, discards it, and still reports success; phase 5 then crashes |
| blocker | MIGRATION's pip line omits `rich` → `run.py` cannot start; `pypdf` missing too (PDF passports read as invalid) |
| high | Install order lets `easyocr` pull CPU-only torch; the cu128 command then does nothing |
| high | The "must be 3.11" reason does not hold; the only real 3.11 tie is one launcher line |
| high | Phases 1–4 exit 0 even when they did nothing; bootstrap never stops |
| high | Phase 4 skips students already marked complete in Google Drive |
| high | MIGRATION §8 "clear the old sheets" can wipe a university sub-tab (`progress_builder.py:485-489` fallback) |
| high | Two of HANDOFF's four known-false FAIL rules still return FAIL |
| high | Empty admin chat ID → the first person to message the bot becomes admin (again after every restart) |
| high | Code defaults to mock mode; the §9 `/stats` check passes on fake data |
| high | REST API on `0.0.0.0:8000` with no password; can GET any portal page and relay login POSTs |
| high | Leaving `data\` behind erases the FIELD CHECK "Corrections" history |
| high | Docs disagree on what caused the 26 Sep outage; publish the Google app before signing in again |

---

## 3. The grill-me interview: every decision

Source: memory note `hangeul-migration-decisions.md` and the AskUserQuestion answers in transcript `3b9b6ced-…jsonl` (27 Sep 04:51–14:35). "Rec." = the option Claude recommended.

| # | Time | Question (short) | Owner's answer | Rec.? | Consequence |
|---|---|---|---|---|---|
| 1 | 04:52 | Which role is this PC? | **The new PC** (full move per MIGRATION.md; PC_BUILD split rejected) | yes | One machine runs bot, sync and OCR |
| 2 | 04:53 | State of the old PC? | **Gone / no access** | no (rec. "running normally") | Nothing copied; secrets recreated from source services; GitHub zip is the only code; MIGRATION §10 "retire old PC" becomes a rotation question |
| 3 | 04:54 | Rotate credentials? | **Reuse existing values** | no (rec. "rotate mine") | Owner types portal login, Telegram token, Gmail app password into blank `.env` lines; `credentials.json` re-downloaded; `token.json` recreated by `progress_builder --auth` |
| 4 | 04:58 | Copy of `E:\KONYANG DOCUMENTS`? | **No copy, doesn't matter** | — | Konyang rebuilt from what the portal marks verified; code must tolerate a missing/empty Konyang folder |
| 5 | 05:16 | How should the system find its folders? | **Configurable, `C:\Hangeul`** | yes | Rejects a real E: partition and a `subst`/registry mapping (subst is per-session, lost at reboot, split by UAC) |
| 6 | 05:16 | Which Python? | **venv on 3.12** at `C:\Hangeul\BOT\.venv` | yes | Launchers call `.venv\Scripts\pythonw.exe`; torch `2.11.0+cu128`/torchvision `0.26.0+cu128` installed from the cu128 index before `easyocr`; add `rich`, `pypdf` |
| 7 | 05:17 | Downgrade the two known-false FAIL rules? | **Both to FLAG** | yes | solvency vs statement date (`doc_verifier.py:735`) and apostille "not all for one qualification" (`page_checks.py:433`); back to FAIL only once proven (HANDOFF §8.1). Apostille subject mismatch (`page_checks.py:440`) dormant: `apostille.json` was lost |
| 8 | 05:17 | Clear the progress sheets first (MIGRATION §8)? | **Skip it** | yes | Sheets stay; `build_target` rewrites main tabs in place (`progress_builder.py:488-489`); run phase 2 before phase 1 so Passport Issue is not blank |
| 9 | 05:18 | Which safety fixes before first start? (4 offered) | **Only "close the auto-claim hole"** | partly (rec. all four) | `c5c1a7c`. **Declined:** `API_HOST` stays `0.0.0.0`; watcher keeps "mark all, send 3" (`scheduler.py:81,94-95`); portal re-login loop stays uncapped (`verified_docs.py:74-76`). Mitigation: phase 3 CSVs are the full passport-problem list; portal login tested once before bootstrap. "Don't re-propose unless asked" |
| 10 | 05:19 / 05:55 | Install Ollama + qwen2.5:7b? May I download now? | **Install, same as before**; **Yes, install now** | yes | OllamaSetup.exe (1.57 GB) from ollama.com, MIT licence accepted on the owner's behalf; model in default C: location; `OLLAMA_MODELS=E:\ollama` skipped (698 GB free) |
| 11 | 05:20 | Power-cut recovery? | **BIOS "power on when AC returns" + Windows auto sign-in** (set by the owner) | yes | Launchers stay logon-based (Startup shortcut + watchdog). Account "User", local, "Password required: No"; no UPS |
| 12 | 05:20 | How should the cold start run? | **Phase by phase, checked** | yes | Pre-flight (torch.cuda, a pyzbar decode, EasyOCR model build, one portal login) → 2 → 1 → 3 → 4 `--include-drive-done` → 5 → one `auto_sync --no-notify` → start bot. Stop on any "FAILED", "0 … cached", "N failed" |
| 13 | 05:20 | Version control? | **Local Git, baseline first** | yes | `C:\Hangeul\BOT` repo; first commit = untouched snapshot; one commit per change; nothing pushed unless asked (no remote exists) |
| 14 | 06:04 → 06:20 | Gaming on the same GPU (FC 25 open: OCR 1.8 s → ~17 s/page)? VRAM guard? | "i won't play game right now, continue" | — | **No decision**; no guard added. Game ~3–4 GB + EasyOCR 3.9 GB peak + qwen2.5:7b 4.7 GB > 8 GB; an OOM during OCR can cache truncated text as final. Open item |
| 15 | 06:44–07:11 | (not a question) Telegram token rejected (HTTP 401) | Owner created **@the_Jennie_bot** in BotFather, pasted the new token ("new api for telegram", "tg done"), pressed Start | — | Old bot dead; only the admin authorised (`TELEGRAM_ADMIN_CHAT_ID` = the owner's user id, value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID)); colleagues must press Start later |
| 16 | 07:35 | A Drive copy of Konyang exists (41 folders, 473 files, 346 MB, last changed 21 Sep; holds 4 of the 11 at-risk students). Restore? | **Leave it in Drive only** | no (rec. restore) | `KONYANG_ROOT` stays absent; phase 5 skips Konyang; 7 students' Konyang files truly gone. Restorable later (flat layout accepted; fresh verified copy wins via `setdefault`) |
| 17 | (measured, not asked) | Long single-process OCR degrades | — | — | Phase 5 in batches of 5 (see §4.8) |
| 18 | 12:03 → 14:35 | 47 of 61 FAILs come from "page 1 of the academic file must be the e-Apostille" (`page_checks.py:403`); 57 FLAGs say "apostille not followed by its certificate". Downgrade? | **Keep FAIL: the rule is right** | no (rec. FLAG) | Apostille-first is the real guideline; staff must re-assemble the 47 files. "Don't propose downgrading it again" |

Why the owner's answers matter for a copy: decisions 2/3 mean every secret was re-entered by hand from its source service; decisions 9 and 14 left known risks open on purpose (see [Open items](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).

---

## 4. Migration execution (27 Sep 05:22–14:37)

### 4.1 Pre-cold-start code changes

| Commit | Time | What | Why |
|---|---|---|---|
| `366dec0` | 05:22 | Baseline: GitHub snapshot as downloaded (71 files, 14,709 lines) | Every later edit diffable and revertible (decision 13) |
| `f74e45d` | 05:23 | Solvency-vs-statement-date (`src/verify/doc_verifier.py`) and apostille "one qualification" (`src/verify/page_checks.py`) return FLAG instead of FAIL; message text unchanged | Decision 7 |
| `c5c1a7c` | 05:23 | `is_authorized(update)` (`src/bot/telegram_bot.py:22`) (and the root staging copy `telegram_bot.py`): with `TELEGRAM_ADMIN_CHAT_ID` and `TELEGRAM_AUTHORIZED_CHAT_IDS` empty it **refuses everyone** and logs the sender's chat id (`logger.warning("TELEGRAM_ADMIN_CHAT_ID is not set; refused chat …")`, now `telegram_bot.py:33`) | Before: the first sender became admin in memory, getting student data and `/sendmail` from the agency Gmail; recurred after every restart. Root copy kept byte-identical because `apply_bot_update.bat` copies it over `src/bot/` |
| `a012bcb` | 05:30 | `requirements.txt` pinned to versions proven in the 3.12 venv, torch-first cu128 install spelled out | It lacked easyocr, torch, pymupdf, opencv, pyzbar, pillow, openpyxl, pypdf and Google libs; MIGRATION omitted `rich` and `pypdf`. Verified: torch 2.11.0+cu128 sees the RTX 5060, all imports load, pyzbar's zbar DLL decodes, `pip -r --dry-run` satisfied |
| `4154aa5` | 05:53 | `src/config.py` gains `BOT_ROOT` and `.env` keys `DOCS_ROOT`, `DOCS_ORIGINALS_ROOT`, `KONYANG_ROOT`, `VERIFICATION_DIR`; empty → folders beside the bot folder (`E:\BOT` → old paths; `C:\Hangeul\BOT` → `C:\Hangeul\VERIFIED STUDENT DOCUMENTS` …). Module names `DOCS_ROOTS`, `REPORT_DIR`, `BACKUP_ROOT`, `APOSTILLE_SUBJECTS`, `DOCS_ROOT` kept; `.env.example` documents every key read (18 files) | Decision 5; the passport-alert cache, scans and bot log followed the start folder |
| `053efc5` | 05:53 | Launchers self-locating (`%~dp0`, `WScript.ScriptFullName`, `$PSScriptRoot`) and pinned to `.venv\Scripts\python(w).exe`, failing visibly if missing; `stop.bat`/`check_status.bat`/`watchdog.ps1` match the bot by exe path under this `.venv` (plus the Python312 child the venv redirector starts); `apply_bot_update.bat` calls `stop.bat nopause`; CRLF pinned by `.gitattributes` | Old launchers hard-coded `E:\BOT` and Python 3.11. Also fixed: an unescaped `)` in an echo inside an if-block (apply_bot_update never reached start), unescaped `&` in titles, `__pycache__` sweep recursing into `.venv` |

Built by workflow `wh481c6m5` ("Make Hangeul BOT paths configurable and launchers self-locating, then adversarially review and fix", 8 agents, done 05:52): each side reviewed by two agents before a fix pass.

### 4.2 Secrets, `.env` and the new Telegram bot (06:22–07:11)

- Claude created `.env` with `MOCK_MODE=false` and **blank** secret lines ("FILL IN"). The owner pasted the portal login and Gmail app password in chat (06:39); Claude wrote them into `.env` without echoing them and warned that pasted secrets are now in the transcript (rotation advised; owner kept decision 3).
- Gmail: `_send_gmail(to_list, subject, body)` (`src/bot/telegram_bot.py:1044`) strips spaces from `GMAIL_APP_PASSWORD` itself (`.replace(" ", "")`, line 1051) and sends over `smtplib.SMTP_SSL("smtp.gmail.com", 465)` (line 1062), so the 16-letter app password went in exactly as Google shows it. Values: `secrets/bot.env` (`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`).
- Telegram pre-flight: the old token returned **401** (the old bot is dead). The owner created **@the_Jennie_bot** in @BotFather and supplied its token (06:56–07:06, `TELEGRAM_BOT_TOKEN` in `secrets/bot.env`), then pressed Start (07:11), because Telegram does not let a bot message someone who has not.

### 4.3 Pre-flight and the EasyOCR cp1252 crash (`d659983`, 06:21)

- Checks: `torch.cuda.is_available()` on the RTX 5060; a pyzbar QR decode; the EasyOCR model build; one portal login (326 students across 7 pages).
- **Problem:** on a fresh PC EasyOCR downloads its detection and recognition models when the reader is first built. With `verbose=True` (default) it draws a progress bar with "█", which a Windows console in **cp1252** cannot encode → `UnicodeEncodeError` at 2%, reader never built. In the cold start every scanned document would have been stored as "could not read the file", as final.
- **Fix:** `src/verify/doc_verifier.py` builds the reader with `verbose=False` (the passport validator already did). Verified: the reader builds on CUDA from a cp1252 console; both models cached in `~/.EasyOCR`.

### 4.4 Phase 2: passport issue dates (2 min)

`bootstrap.py --only 2` → **274 of 302** issue dates cached (the other 28 are blank on the portal). Rule: `0 cached` means the portal login failed.

### 4.5 Phase 3: passport audit coverage (`03ccf15`, 06:43; ran 07:17, 33 min)

- **Problem:** the audit silently covered 78 of 326 students. `bootstrap.py` passed program names `"KLP"` and `"EAP"`, which match no student on the portal (all 214 KLP and 29 EAP skipped; the script printed "Nothing to check" and exited 0, which bootstrap counted as success); `audit_program.py` read only page 1 of each program list (50/page), so Bachelor's stopped at 50 of 55.
- **Fix:** `audit_program.py` follows "Page X of N" with `&pg=N` (as `verified_docs` already did) and exits 1 when a program matches nobody; `bootstrap.py` passes the portal's own names, matched case-insensitively. Read-only check: 214 + 29 + 55 + 28 = **326**, the full `students.php` count.
- **Result:** 326 checked; 225 all match; **36 students (40 fields)** differ between portal and passport MRZ (a list of questions for staff, not confirmed errors); 29 no scan; 35 scan unreadable. Per program: KLP 214 (149 match, 15 differ, 27 no scan, 22 unreadable), EAP 29 (18/6/2/3), Bachelor's 55 (41/7/0/7), Master's 28 (17/8/0/3). Output: four `program_audit_*.csv` in `C:\Hangeul\BOT`.

### 4.6 Google Sheets and Drive sign-in (07:12–07:38)

1. Google Cloud project `hangeul-bo` (the owner's account). The OAuth consent screen was moved from **Testing to In production** (Testing tokens expire after 7 days, the cause of the 26 Sep outage). Branding filled first: app name "Hangeul Bot", support and developer email, home page `https://hangeul.com.bd`, privacy link.
2. Google Auth Platform → Clients → the **Desktop** OAuth client → Download JSON → saved as `C:\Hangeul\BOT\credentials.json` (the owner left it in Downloads; Claude moved and renamed it). Copy: `secrets/credentials.json`.
3. `.venv\Scripts\python.exe -m src.sheets.progress_builder --auth` (`progress_builder.py:556` `main()`, `--auth` at 559; `InstalledAppFlow.from_client_secrets_file(...)` at 382) → browser → "Google hasn't verified this app" → **Advanced → Go to Hangeul Bot (unsafe)** → allow both scopes `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/spreadsheets` (`SCOPES`, line 49) → `token.json` (copy: `secrets/token.json`). No service account exists.
4. Pre-flight row: "Google (In production) … pass" at 07:38.

### 4.7 Phase 1 (35 s) and phase 4 (15 min)

- Phase 1 (run after phase 2 per decision 8): **7 sheets rebuilt in place**, 324 students, issue dates filled; the Bachelor's sheet kept its 2 university sub-tabs; every sheet said "updating existing sheet", none FAILED.
- Phase 4: `python -m src.sheets.verified_docs --local "C:\Hangeul\VERIFIED STUDENT DOCUMENTS" --include-drive-done` → **146** document-verified students, **1,212 MB**, 0 failed. `--include-drive-done` is required, or students once uploaded to Drive are silently skipped.

### 4.8 Phase 5: the GPU-memory growth, fixed by batches (08:14–~11:40, 2 h 26 min)

- **Problem 1:** the first `auto_verify` run used ~11 GB (7.4 GB VRAM + 3.7 GB spilled to system RAM via the Windows NVIDIA sysmem fallback) at ~143 s/student. Trying `PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold` (08:14) made it worse.
- **Problem 2:** at 08:21 the Bash tool's shell was torn down and took the background job with it (17 students saved; no crash). A restart crawled at ~570 s/student (heading for ~21 h), so it was stopped.
- **Diagnosis:** one long process grows GPU memory student by student (7 GB VRAM + 6 GB spilled). Not the documents: one "slow" student profiled `read_document` in 30 s with a 2.2 GB peak (ordinary A4 scans).
- **Fix (procedure, no code change):** a fresh process per 5 students: `auto_verify --budget 5` in a loop (scratch script `phase5_batches.ps1`; the loop is now in `MIGRATION.md` §8) → steady **~93 s/student**. Long jobs are started detached (`Start-Process`), never as a Bash-tool background job. The live bot is unaffected: it checks ≤ 6 students per 15-min sync in a fresh subprocess.
- **Result:** 144 students checked (the head of branch is excluded by standing rule): **FAIL 61 / REVIEW 65 / INCOMPLETE 15 / PASS 3**; field check **2,801 MATCH, 1 DIFFERS** (same as the old PC). Reports: `C:\Hangeul\BOT\data\verification\DOCUMENT CHECK.xlsx`, `FIELD CHECK.xlsx`.

### 4.9 Quiet seed sync, bot start, autostart and watchdog (11:43–11:47)

- `python -m src.sheets.auto_sync --no-notify` recorded the starting state without messaging anyone (otherwise the first 15-min run announces every sheet as new).
- Bot started **11:46** via `wscript.exe start_background.vbs` (pythonw from the venv); the command list was pinned in the admin chat. `install_autostart.bat` created `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HangeulBot.lnk` (11:46:53); `install_watchdog.bat` created the scheduled task **HangeulBotWatchdog** (restarts the bot within 5 minutes); the watchdog correctly detected the running bot.
- By 14:36: 12 clean syncs, and one newly verified student auto-downloaded. The `/stats` acceptance check was left to the owner.
- Owner questions answered (14:38, 14:48): where to see portal-vs-OCR differences (`FIELD CHECK.xlsx` for documents vs portal; `program_audit_*.csv` for portal vs passport MRZ; `DOCUMENT CHECK.xlsx` for rule verdicts); why Excel asks to save an unchanged `DOCUMENT CHECK.xlsx` (openpyxl-written files are recalculated on open → click **Don't Save**; an open file blocks the bot's next write; open a copy or **Open Read-Only**).

### 4.10 Konyang in Drive (07:34, decision 16) and apostille-first (14:35, decision 18)

See the decision table. Konyang: `KONYANG_ROOT` absent; the Drive copy under `PARENT_FOLDER_ID` stays there. Apostille: rule `page_checks.py:403` stays FAIL; the ordering (certificate → apostille) in 47 files is a staff re-assembly job.

### 4.11 MIGRATION.md rewritten (`b0245df`, 14:37)

The guide now records the real move: configurable folders; Python 3.12 venv with torch first; Google sign-in against the published OAuth app; the three `.env` checks (`MOCK_MODE=false`, admin chat id set, Start pressed on the new bot); phases 2-1-3-4-5 one at a time with real timings; phase 5 in batches of five; the order for retiring an old PC (delete `HangeulBotWatchdog` task and `HangeulBot.lnk` **before** `stop.bat`); a closing table of fixed vs knowingly-left items. 9 local commits by then, none pushed.

A task chip was spawned in session 1 for the pre-existing `/brief` ImportError (`brief_command` imported `compose_daily_brief` and `_send_brief`, which did not exist). It was superseded by `f8fefa4` (§7.4).

---

## 5. Ollama (27 Sep 05:55 → 28 Sep 18:06)

| When | Change | Why / measured |
|---|---|---|
| 27 Sep ~06:02 | Ollama **0.34.4** installed silently from OllamaSetup.exe; `Startup\Ollama.lnk` (06:02); `qwen2.5:7b` (4.7 GB) pulled to the default C: location | Decision 10; used by the 18:05 brief, `/sendmail` drafting and free-text answers |
| 27 Sep 20:52 | Brain trial finding: **`localhost` costs ~2.03 s per new connection** (resolves to `::1` first); warm qwen2.5:7b answers in 0.46–0.58 s; the real delays were cold reloads (7.8–9.9 s, `keep_alive` 0/30 s) | `.env` changed to `OLLAMA_BASE_URL=http://127.0.0.1:11434` (active from the 23:49 restart) |
| 27 Sep 21:24–21:36 | `qwen3:4b` and `qwen3:1.7b` pulled for the trial, then **removed** (owner approved); `qwen3:4b-instruct` pulled | qwen3:4b's Ollama tag is the Thinking-2507 edition and leaks reasoning even with `think:false` |
| 28 Sep 01:51 | `.env` `OLLAMA_MODEL=qwen3:4b-instruct`; one option set (`num_ctx` 3072 — `OLLAMA_NUM_CTX`, `src/config.py:42`), `keep_alive -1`, warmed at start, `keep_brain_warm` job every 10 min | Fast Jennie (§6.9); resident 2.82 GB, warm in 3.5 s |
| 28 Sep ~11:20 | User env vars **`OLLAMA_FLASH_ATTENTION=1`** and **`OLLAMA_KV_CACHE_TYPE=q8_0`**, Ollama restarted | Brain 2.82 → **2.62 GB** (owner approved at 11:21) |
| 28 Sep 18:06 | Brain on demand (`c17d887`): pinned only while `JENNIE_VOICE_ENABLED` or `BRAIN_ALWAYS_LOADED`; else `keep_alive = BRAIN_IDLE_UNLOAD` ("5m") | GPU idles at ~1.0 GB (§7.8) |

Current models (`ollama list`, 29 Sep): `qwen3:4b-instruct` (2.5 GB), `qwen2.5:7b` (4.7 GB, kept but unused).

---

## 6. Jennie, the voice assistant (27 Sep 14:53 → 28 Sep 01:51)

Source: memory note `hangeul-jarvis-plan.md`, voice README `C:\Hangeul\JARVIS\jennie_voice\README.md`, workflow outputs in `…\3b9b6ced-…\tasks\`.

### 6.1 Interview J1–J6 (14:53–15:01)

Owner at 14:53: "MY CURRENT TG BOT IS OKAY BUT CAN I BUILT AN ASSITANT WITH VOICE CONTROLL??" ("like Jarvis").

| # | Decision | Rec.? | Notes |
|---|---|---|---|
| J1 | **Phone first** (Telegram voice notes in; text + voice out), a hands-free "Hey Jarvis" wake word at the PC later on the same brain | yes | Reuses the bot's login and access control; no always-on office mic |
| J2 | **English + Korean** | no (rec. English only) | Bangla offered, not picked (needs the largest Whisper, weak qwen Bangla, no good offline Bangla TTS → online service would receive student names) |
| — | Celebrity voice **declined by Claude** | — | No cloning a real person's voice without consent (incl. the film Jarvis actor; later also no idol voice such as BLACKPINK Jennie). Offered stock voices, the owner's own or a consenting colleague's |
| J3 | Voice **chosen by ear from samples** ("Try a few, then choose") | no | Trials in isolated venvs under `C:\Hangeul\JARVIS\voice-trials\<engine>`, samples in `C:\Hangeul\JARVIS\voice-samples` |
| J4 | v1 abilities: **answer questions, run reports by voice, spoken 18:05 brief**; "I WILL ADD FEW FEATURES LATER" | yes | Email by voice deferred (a misheard name could email the wrong person) |
| J5 | Reply = **voice note + text**, in the language spoken (EN/KR auto-detected), showing "what I heard" | yes | |
| J6 | Name **Jennie** (matches @the_Jennie_bot); future wake word "Hey Jennie"; shortlist must include female voices | yes | |

### 6.2 First voice trials: Kokoro, MeloTTS, Piper (workflow `wzsoeis3s`, done 15:15)

"Install three offline TTS engines in isolated venvs and render EN/KR voice samples" (3 agents). Results:

| Engine | Voices | Licence verdict |
|---|---|---|
| MeloTTS | `KR` (female) — **the only acceptable Korean**; EN accents en-us/en-br/en-au/en-india/en-default | MIT; Windows workaround: transformers pin + eunjeon, torch 2.5.1 CPU in its own venv |
| Kokoro | bf_emma, af_heart, af_bella, bf_isabella (female), bm_* (male); no Korean | Apache-2.0 |
| Piper | en_GB cori (public domain); ko_KR-kss **rejected** (CC BY-NC-SA); northern_english_male and vctk non-commercial | mixed |

A 5-EN + 1-KR shortlist was sent (15:16); the owner dismissed the English pick question.

### 6.3 Aegyo and "too AI" (15:58–16:03)

- 15:58 "CAN U RECOMMEND SOME VOICE WITH AGEYO?? LIKE CUTE VOICE IN KOREAN": 4 aegyo levels rendered from MeloTTS KR (`voice-trials\melotts\aegyo_samples.py` → `voice-samples\aegyo__{1_style-only,2_bright,3_cute,4_very-cute}__kr.wav`: speed 1.0/1.08/1.12/1.15, pitch +0/+2/+3.5/+5 semitones, sdp 0.2/0.5/0.6/0.6).
- 16:01 "A BIT MORE REALISTIC VOICE POSSIBLE? SOUND TOOO AI" → J7 (16:03): **"A; MORE REALISTIC WITH 애교"**: a more realistic **offline** model. Online Naver/Azure/ElevenLabs declined for privacy (answers contain student names). References may only be synthetic stock-voice output, never real people's recordings.

### 6.4 Realistic trial (workflow `w7p17p6ni`, done 17:32) and the voice choice (17:50)

"Trial realistic offline TTS (Chatterbox Multilingual, CosyVoice) for EN/KR aegyo, then check intelligibility with Whisper" (3 agents, 28 samples `voice-samples\real__<engine>__*.wav`). A Whisper character-error-rate (CER) round trip judged intelligibility.

| Engine | Licence | GPU peak | Speed | Notes |
|---|---|---|---|---|
| Chatterbox Multilingual | MIT | 4.3 GB | ~0.5× real time | Perth watermark in every output; torch 2.8 cu128 + GitHub master for the v3 checkpoint |
| CosyVoice 2 / 3 | Apache-2.0 | 2.9 / 3.5 GB | 0.6–0.9× RT | torch 2.7.1 cu128 on py3.12 with shims; no text normaliser (spell out numbers). 300M-SFT 韩语女 speaker **unintelligible (CER 0.53)**, rejected |
| STT | faster-whisper large-v3 fp16 GPU ~1.4 s per 12 s clip; medium int8 CPU ~7 s; large-v3 on CPU slower than real time; first CUDA call ~27 s (warm up at start) | | | |

- **J8 (17:50):** "nice. i found one. use this" → **CosyVoice2-0.5B zero-shot with the "krfemale" timbre**, sample `real__cosyvoice__v2-zeroshot-krfemale__kr-aegyo.wav` (best CER 0.034). English uses the same timbre via v2 cross-lingual (one persona). Reference clip `ref_v2xl_ko_female.wav` + transcript, seed 1234, in `C:\Hangeul\JARVIS\voice-trials\cosyvoice\ref\`.
- **J9:** "no i want same in english as well even with 애교" → English replies and the spoken brief use the same cute persona, `style="aegyo"` for `en` too.

### 6.5 The build (workflow `w36pyqr2g`, 8 agents, ~17:55–19:59) and deploy (20:02)

"Build the Jennie voice service (STT+TTS) and the Telegram bot integration, adversarially review and fix each side".

- **Voice service** `C:\Hangeul\JARVIS\jennie_voice\service.py` (not in git): FastAPI on `127.0.0.1:8765` (`GET /health`, `POST /stt`, `POST /tts`), local-clients-only guard. STT: faster-whisper **large-v3-turbo** fp16 on GPU per request (chosen by `bench_stt.py`: Korean CER 0.034, 0.59 s per ~12 s clip, ~2.2 GB VRAM, reload 1.9 s), CPU fallback **medium** int8 (7.6–8.1 s). TTS: CosyVoice2 zero-shot (ko) / cross-lingual (en), kept off the GPU when idle, moved on for a render (`TTS_GPU_NEED_GB`, 3.8), 5-min idle offload; ~5.5 GB RAM working set. Autostart `Startup\JennieVoice.lnk` (20:01) + scheduled task **JennieVoiceWatchdog** (`watchdog_jennie_voice.ps1`). It loads the CosyVoice repo/weights and Whisper medium from the `voice-trials` folders at run time (do not delete them).
- **Bot side** `d7a5817` (20:00:50): new `src/bot/voice.py` (796 lines: handler, service client, capture of routed replies, spoken summaries, spoken brief; one voice request at a time; notes capped at 60 s; if the service is down or busy the text answers still arrive with a note; logs metadata only); `handle_natural_language_message(update, context, query=None)` so a voice note (no `.text`) reuses the typed routing; a Korean request is rewritten by the LLM into English command wording first; `ollama_client` optional `keep_alive` so the summary call releases VRAM before speech renders; settings `JENNIE_VOICE_ENABLED` (default false), `JENNIE_VOICE_URL`, `JENNIE_SPOKEN_BRIEF`; handler registered only when enabled; `tests/test_voice.py` (29 tests, mocked service + fake PTB objects).
- English aegyo (J9) applied by Claude at 19:49 while the service's last fix pass ran (the owner asked at 19:48 to test Korean meanwhile): the `_CUTE_EN` prompt and style "aegyo" for en. The service accepts `style="aegyo"` for English; the cuteness comes from the wording, not a different voice.
- **Token leak found by two reviewers** → `0fce479` (20:00:50): `httpx` logs every request URL at INFO, and Telegram URLs carry `bot<token>`, so `hangeul_bot.log` held the token in plain text (**2,831 copies**, scrubbed). A `logging.Filter` subclass `_RedactBotToken` on the `"httpx"` logger, installed in `src/__init__.py` (imported by the bot and every job), rewrites `record.msg` with `_TOKEN_RE.sub("bot<token>", msg)`. Verified with a fake token (Telegram URL redacted; a portal GET line unchanged).
- `.env`: `JENNIE_VOICE_ENABLED=true`, `JENNIE_SPOKEN_BRIEF=true`; bot restarted.

### 6.6 Telegram testing (20:03–20:19) → `e205327`

- The owner could not find the mic (Telegram shows a camera icon until tapped once; the icon becomes a send arrow when the box has text; microphone permission). First note arrived as silence.
- Second note (20:15): heard "제니야 오늘 **수료** 검증된 학생 몇 명이야?" (서류 misheard as 수료, meaning intact); correct text answer (2 students); the voice note came ~70 s later. Breakdown: STT 5 s; a **36 s queue** behind an overlapping note's LLM call; qwen2.5:7b **reloaded twice** (keep_alive 0); TTS 5–9 s.
- Fixes: `e205327` (20:19): (1) the log filter missed the token in Telegram **file-download URLs**, where the colon is URL-encoded (`api.telegram.org/file/bot<id>%3A<secret>/…`); `_TOKEN_RE` is now `bot\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}` (`src/__init__.py:36`; filter class at 39, installed on `logging.getLogger("httpx")` at 47), and the `%3A` copies were scrubbed from the logs while the bot was stopped. (2) An LLM answer that is not valid Telegram Markdown ("Can't parse entities") produced an error instead of the answer; it is now resent without `parse_mode` (`from telegram.error import BadRequest`).
- **Korean misdetected as English** (a Korean note detected as English at probability 0.14): fixed in the voice service, not the bot: `STT_UNSURE_PROB = 0.6` (`service.py:104`) — below it, en vs ko is re-checked by transcribing both ways and keeping the better score; `STT_OTHER_LANG_MIN_PROB = 0.85` (line 103) forces a non-EN/KO detection back to the likelier of the two. Voice service restarted 20:19.

### 6.7 "Too slow": the brain trial and the small brain (20:21–23:40)

- 20:21 "its tooo late. i want something more conversational." → **J10** (20:23): **option 1, faster, chattier Telegram voice notes** (~10–15 s target, short replies, memory of recent turns, offline). Live "Hey Jennie" at the PC, phone live web and cloud realtime were offered; the owner first picked "Live talk at the PC", then chose 1 alone. **J11** (20:43): the chat **keeps all three messages** (heard, full text, voice).
- Workflow `wpctxscrl` (done 20:51, 1 agent) "Benchmark small local LLMs": only the 7B was installed, so only it was measured (12/12 commands, dates, JSON on 12 EN/KR utterances incl. follow-ups; its Korean reply said the date as "27 사월 이천육 년" = 27 April 2006 and dropped a total). Licences read from the Ollama tags: **qwen2.5:3b excluded** (Qwen Research Licence, non-commercial); gemma3:4b probably over the 3.5 GB budget (weights 3.34 GB with the vision encoder). Found the localhost 2 s penalty (§5).
- 21:24 downloads approved; trial (`C:\Hangeul\JARVIS\brain-trial\trial.py`, results `results_*.json`): qwen3:4b 2.96 GB, 12/12 but leaks reasoning; qwen3:1.7b 1.59 GB, **dates 5/12 → rejected**; qwen2.5:7b 4.55 GB, too big beside the voice. 21:36: pull **qwen3:4b-instruct** (Apache-2.0), remove the other two.
- **J13** (23:40): brain = **qwen3:4b-instruct**: 2.96 GB VRAM, 2.8 s load, routing/dates/JSON 12/12, route + reply 0.63 s; sample reply "짜잔! 오늘 서류 검증된 학생은 두 명이에요용~"; it adds emojis, which the bot strips.
- **J12** (23:01 "I dont want to wait 10 to 15 second. I want instant audio reply" → 23:05): **A: an instant pre-rendered filler clip (~1 s, cute, KO/EN) + a fast one-sentence real reply**. B (live streaming talk) and C (cloud) declined for now. Voice notes have a ~4–7 s floor. VRAM plan: brain resident at num_ctx 2048 (~2.8 GB) + TTS on demand (3.1) + Whisper per request (2.2, before TTS); desktop ~1.2 GB.
- 23:41 "Not now" to building it (paused); slow Jennie (`d7a5817` + `e205327`) stayed live.

### 6.8 The bot "not replying": the passport watcher blocked the event loop (23:48–23:57)

- 23:48 "Start start the bot again" → restart at 23:49 (activating `127.0.0.1`); one note was lost to the restart. The owner reported "not replying".
- **Cause:** the 30-min passport watcher (`scheduler.py:219` at the time, `IntervalTrigger(minutes=30)` from bot start) awaited `audit_student_passport`, whose CPU EasyOCR/MRZ work ran synchronously **inside the bot's asyncio loop**, freezing all Telegram handling for ~3.5 min every half hour.
- Owner: "Later, I'm testing now" (23:50) — Claude was to remind after the test. Test 23:52–23:53: voice replies 20–28 s (7B cold reloads 7–9 s; a 294-char English summary took 12 s of TTS). Other log findings: 22:20 "Voice reply unavailable: TimedOut" (GPU busy during the trial) and 23:07 "Error in crosscheck: Message is too long" (later traced to the intake-option substring bug, §7.5).
- 23:53 "Still jenny too slow I think." → **J14** (23:56): **build, with the small brain qwen3:4b-instruct everywhere** (voice, typed, brief; resident), because the card cannot hold the 7B and the voice together. **J15** (23:57): **include the watcher fix**.

### 6.9 Fast Jennie and the non-blocking watcher (workflow `w3tpqg1ox`, 9 agents; deployed 28 Sep 01:51)

"Fast conversational Jennie (instant filler, resident small brain, one-step routing with memory) + non-blocking passport watcher; review, fix, live latency test".

| Commit | What |
|---|---|
| `7241465` | `src/scraper/client.py`: the CPU-heavy `validate_passport_data` runs via `asyncio.to_thread`; portal GETs stay async; a new scan is saved once through a `.part` file renamed into place (no thread reads half a file). `src/scraper/ocr_validator.py`: one re-entrant lock (`RLock`) loads the shared CPU EasyOCR reader once and serialises OCR and audits. `tests/test_watcher_nonblocking.py`: the loop keeps ticking (< 0.5 s gaps) during an audit; result structure unchanged; two audits of one upload save the scan once |
| `d9bbecc` | `src/bot/voice.py` rewritten (977 lines changed): pre-rendered cute filler clip per language in `data\jennie_fillers` (gitignored, re-rendered if missing; ko: "잠시만용~ 찾아볼게요!", "음~ 찾아볼게용!", "금방 알려드릴게용~"; 3 English lines) sent **before** download and STT; **one JSON routing call** with the last turns of per-chat history (6 turns) replaces the rewrite call + keyword routing; commands dispatched directly; follow-ups ("그럼 어제는?" / "and yesterday?") and relative days resolved in code; unknown/failing commands fall back to the typed path; one-sentence spoken reply (Korean capped for VRAM) with a check that every spoken number appears in the answer or the question; one metadata-only timing line per note. `src/llm/ollama_client.py` (+136): one option set (num_ctx 3072), `keep_alive -1`, `chat()`, `warm_up()`, `residency()`, `unload()`; `scheduler.py`: `warm_brain()` at start and `keep_brain_warm` every 10 min. `tests/test_voice_fast.py`; 141 tests pass |

Deploy: `.env` `OLLAMA_MODEL=qwen3:4b-instruct`; resident 2.82 GB; GPU 4.58/8.15 GB after restart. Live latency harness `C:\Hangeul\JARVIS\brain-trial\latency_harness.py` (fake Telegram, real services): **filler 0.14 s, "heard" 2.2–3.6 s, full text 2.9–3.7 s, voice 5.9–9.5 s**; Korean occasionally 16–33 s (CosyVoice "ran long" → re-render with seed 1235, plus a VRAM spill). Open after this stage: the sync's GPU EasyOCR (~2.4 GB) can squeeze TTS; the typed agent prompt duplicated inquiries (could exceed 3072 tokens); the filler language follows the previous turn; the `/brief` ImportError.

---

## 7. The second session (28 Sep 10:31 → 18:06)

The second transcript (`b90661d9-…jsonl`) is a resumed copy of the first that continued from 10:31 and was compacted at 13:03 (a summary replaced the earlier context). The first transcript's last entries (12:10–12:13) are the owner asking where the chat went.

### 7.1 Slow voice caused by a full GPU; Ollama memory settings (08:55–11:34)

- A live note at 08:55 took **25.8 s** (STT 5.1 s; moving TTS to the GPU 8.7 s with "0.23 GB free"; render 12.7 s). Desktop/apps used ~2 GB (vs 1.6 GB in tests).
- 10:31 "whats wrong?" (screenshot: slow voice and an inquiries report of zeros). 10:34 options; 11:21 the owner chose **"Fix consultation report"** and **"Ollama memory settings"** (moving the monitor cable offered as the owner's own action, not done).
- Applied: user env `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, Ollama restarted → brain 2.82 → 2.62 GB.
- 11:32 "i did not get any voice reply from jenny": the logs showed it was sent (filler 11:30:31, answer 11:30:56).
- 11:34 "why my gpu memory is full?" — four things share one 8 GB card: brain 2.8 GB (always), voice 3.4 GB while speaking and held 5 min (0.6 idle), ears 2.2 GB while hearing, Windows + apps ~1.4 GB (desktop 0.8, Chrome 0.2, a camera app 0.16…) because **the monitor is plugged into the RTX**. Peak ~8–9.8 GB vs 7.96 GB usable → spill to system memory turns 6 s into 25 s. Not a leak. Options: (1) move the monitor cable to the motherboard (Ryzen iGPU; frees ~1–1.4 GB, the biggest win), (2) close apps (0.2–0.4 GB), (3) a half-precision voice trial (0.3–1 GB; CosyVoice's fp16 flag only enables autocast, weights stay fp32). Undecided (open item).

### 7.2 The orphaned Ollama runner (11:2x)

Killing `ollama.exe` / "ollama app" to apply the env vars left the child **`llama-server.exe` runner orphaned**, holding ~3 GB of VRAM (Claude first wrongly blamed it for the 08:55 slowness, then corrected: it only appeared because of the restart). Killed; idle GPU **4.57 / 8.15 GB**. **Rule:** after any Ollama restart, kill `llama-server.exe` processes whose parent is gone.

### 7.3 Inquiries report all zeros after a portal layout change (`cd0277a`, 11:24)

- **Problem:** `consult_requests.php` changed from 8+ fixed columns to **7 named columns** (Student, Consultant, City & program, Received, Status, Remarks, Update status). Both readers used old positions and required 8 cells, so all 500 rows were skipped: "Total All-Time Done: 0", 0 received; `parse_consultation_requests` returned nothing (it fed typed questions and the brief).
- **Fix:** `parsers.consultation_rows(html)`, one header-driven reader using the cells' own classes: `.cr-name`, `.cr-contact`, `.cr-cons`, `.city`/`.prog`, `.crd-body`, `.d`/`.t`, `.stbadge`, `.cr-by`, `textarea` remarks; helpers `_consult_columns(header)`, `cell()`, `text(tag, selector)`. Row keys: `name, contact, city, program, consultant, details, received, received_date, status, handled_by, remarks`. The Update-status forms are only read, never submitted. An unrecognised layout yields `[]`, not wrong rows. `parse_consultation_requests` and `build_inquiries_report` both use it. `tests/test_consultations.py` (4 tests: new layout, date filter, moved columns, unknown layout); 145 tests pass.
- **Live check (read-only GET):** 500 rows; all-time done 366 (364 Consulted + 2 File Opened); today 3 received / 1 done; yesterday 21 / 15; a new status "Wrong Number". (The audit later showed the "all-time" 366 was only the newest 500 rows: §7.5.) Bot restarted 11:25.

### 7.4 The LLM brief invented facts → the factual brief (`f8fefa4`, 13:51)

- 12:04 "for daily brief what time is set? and give me a daily brief now" → sent via `scheduler.send_daily_briefing` (scratch `brief_now.py`, admin chat only). The qwen3:4b-instruct brief **invented** passport numbers ("1234567890…"), DOBs, "Scanned Image: Matched", a visa YTD, a 28.4% conversion rate and filler; the prompt was ~2,728 of 3,072 tokens.
- 12:07 decision (Rec.): **Factual brief** — code builds every figure from live reads; the LLM adds only a number-checked 1–2 sentence summary; the same brief serves `/report`; `/brief` fixed. Must deploy before 18:05.
- 12:17 the first brief workflow (`wf_5c2f1525-536`, task `wjgdmt14w`) died with the session, having written nothing. 12:22 an **interim factual brief** was sent from scratch `factual_brief.py --send` (plain text, chunks of 3,900 chars, admin chat). Building it exposed two more broken readers: the dashboard summary (`parsers.py` ~150-165) looked up wrong-case tile labels ("Total Students", "Under Review", "Pending Payment", "This Week") and fell back to **placeholders** 262 / 2 / 0 / 31; the calendar parser returned 11 reminders with every field empty (calendar.php layout changed; hence "eleven deadlines"). Relaunched as `wf_29512f8c-a36` (task `wnhlel5f5`, 5 agents: implement, 2 reviews, fix, live verify); result copy: `C:\Hangeul\JARVIS\fix\audit\brief_workflow_results.json`.
- **Built** — new `src/bot/brief.py` (690 lines): `compose_daily_brief`, `_send_brief`, `send_brief_text`, `split_brief`, `brief_plain`, `check_summary`, `llm_summary`, section builders (consultations; payment-verified students from every `students.php` page; pending payments `students.php?status=pending` and window applications under review `window_applications.php` on **separate lines, never summed** (guardrail 2); dashboard tiles grouped as the portal groups them; today's calendar reminders; the last document check from `data\verification\results.json` labelled "not live"). Unknown figure → "not available", never 0 or a placeholder. `parsers.py`: tiles matched ignoring case/spacing/plurals, the two "Docs to review" tiles told apart by their link, no 262/2/0/21/31/101 placeholders, no garbage programs/top-universities regexes, "Accepted" kept as `window_apps_accepted` (no visa key); `parse_calendar_events` rewritten (`.rm-item` "Reminders for today", `.ev-row` "Upcoming"); `parse_verified_students` without the invented "20,000.00 BDT"/"Student" defaults. `ollama_client.generate_executive_report`, `prompts.SYSTEM_EXECUTIVE_REPORT` and `build_report_prompt` removed. `/stats` rebuilt from real tiles. `scheduler.send_daily_briefing` uses `compose_daily_brief` + `_send_brief` and re-exports them so `/brief`'s import works.
- **Review → 13 issues, all fixed**, e.g.: `claims_problem()` (each clause's numbers must be the figure of the fact its words point to; "no/none/nobody/zero" count as 0; words must come from the facts or a short connector list; vague count words, negations, off-topic subjects, non-English script refused), used by both `check_summary` and Jennie; Jennie's spoken brief gets only the fact lines (`Brief(text, facts)`); past days older than the 500-row window → "not available"; yearless verification stamps → `verified_day_problem` "not available"; verified reader layout guard (`scan_verified_students`, raises when rows exist but no "Payment verified by" line); verifier-name regex `([^·\n]{1,80}?)`; calendar false zero and empty timeout error; `_PortalReads` caps each read at 75 s (`READ_TIMEOUT`) and all at 150 s (`PORTAL_BUDGET`), stops after the first timeout (hung portal 270.1 s → 60.1 s); `fetch_html` `httpx.Timeout(60, connect=10)`; consultation parsing off the event loop; the 18:05 job `max_instances=1, coalesce=True, misfire_grace_time=600`.
- **Live verify (13:35):** 32 checks, **29 match**; verdict "inaccurate" only because the "All time" line (368 done, 98 no answer, 26 wrong number) was really the newest 500 rows (portal tabs: All 999, done 798, No Answer 153, Wrong Number 40). Before committing it was relabelled "latest 500 requests, 05 Sep–28 Sep". Independent checker: `C:\Hangeul\JARVIS\brain-trial\brief_crosscheck.py` (own session, regex parsing, imports nothing from `src`). Tests 145 → 179 → **234**.
- Committed 13:51, bot restarted 13:52; the 18:05 brief went out from this version ("Scheduled briefing dispatched successfully" 18:05:13).
- Owner questions in this window (11:50–11:59): a phone-call-like Jennie → options: **"Jennie Call"**, a PC-hosted private web app over Tailscale (~2–3 s turn-taking, all local; needs the GPU freed first), cloud realtime voice (student data leaves), a real phone number (Twilio). The owner showed a **Vercel demo** (`jeenie-saem-bot.vercel.app`): cloud-hosted, "ACCESS: OPEN" (anyone with the URL), "NEURAL CORE: OFFLINE MODE", **mock data**, Microsoft online voices. Advice: never put portal credentials into it; safe to delete. Undecided. 13:57 "I WILL DELETED THE OTHER BOT": keep @the_Jennie_bot; the old bot and the Vercel demo are safe to delete. **What happened later:** the owner deleted the old PC's bot on 28 Sep and the old Telegram bot on 29 Sep 22:06 (§12.5). The Vercel app was not deleted: it is **Jeannie**, the owner's assistant that reads the Supabase data the bot now publishes (§10); its being public was accepted by the owner on 29 Sep (§10.2).

### 7.5 The command-accuracy audit (workflow `wup29tzrh`, done 13:00)

- 12:26 the owner: "is it fixed only for daily brief? for individual tasks like / inquired_today, verified_today and all others as well?" → launched `wf_0a69c29b-8a0` (task `wup29tzrh`, 7 agents): a **frozen worktree** of HEAD `cd0277a` at `C:\Hangeul\JARVIS\command-audit\repo` (since removed); group auditors **verified, inquiries, crosscheck, admitted_missing_stage, free_text**, plus a **completeness critic**. Each ran the handlers exactly as Telegram calls them with fake PTB objects (copying Telegram's legacy-Markdown parser and 4,096-char limit, sending nothing) and **independently re-derived every number** from its own read-only portal session (GETs + the login POST; a guard refused any other POST, api.telegram.org, googleapis and `signed_students.php`). Scripts per group: `C:\Hangeul\JARVIS\command-audit\<group>\`; results: `C:\Hangeul\JARVIS\fix\audit\audit_results.json` (+ `audit_summary.txt`).
- **Verdicts: 119 cases — 38 correct, 25 partly wrong, 46 wrong, 8 broken, 2 not testable** (per-group and per-command tables in [Open items §G](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).
- **Root causes found** (line numbers are in the frozen `cd0277a` copy):

| Area | Root cause |
|---|---|
| verified | `client.get_verified_students` (`client.py:231-239`) read only `students.php` page 1 (50 of 330, newest first): 14 Sep 4 vs 9; 12 Sep 0 vs 10; 23 Jul 0 vs 62. Hard-coded `"20,000.00 BDT"` amount (`parsers.py:394`), case-sensitive method regex (`:384`). Year dropped (`date_regex '0?{day}\s+{Mon}'`, `:363-373`). `login()` failure ignored and every exception → `[]` → "No student payments were verified" (`client.py:228-242`). No message splitting (10,082-char report) |
| inquiries | Unfiltered `consult_requests.php` lists only the **newest 500** requests: all-time 500 / 367 where the portal tabs say 999 / 797; days older than ~3 weeks read 0 (20 Aug: 0 vs 19). Unanchored `rf"0?{day_num}\s+{month_name}(?:\s+{year_str})?"` with `re.search` (`telegram_bot.py:419-426`): 8 Sep also counted 18 and 28 Sep (34 vs 21). `normalize_date_input` returned **today** for "31 Sep". Expired session not handled. "(by X)" fell back to the assigned consultant; city "—" printed as a city |
| crosscheck | Date matched as a bare substring of the whole row (`telegram_bot.py:1458/1485`): every row's **Transfer-intake `<select>`** has option "2027 SEPTEMBER", which contains "27 sep" → **48 students** on 27 Sep instead of 2 → one 26,757-char message → "Message is too long" (the 23:07 error). "Applied On" dates also matched. Page 1 only. A student name containing "mar" (or "jan", "jun"…) was read as a date → silently today. Stray " E" in the stamp time (from "Edit Info"). "100% Match across All Fields" when Father/Mother/Address were not on the scan. `/passports` and `/passport_audit` printed **static 10 Sep text** (`AUDIT_REGISTRY`, `ocr_validator.py:14-198`) |
| admitted / stage / missing | `/admitted` requested `?status=admitted`, which the portal ignores (page 1 of all students shown as admitted), with a students.php parser **shifted one column** and a hard-coded intake "March 2027" (`parsers.py:181-199`; it also fed `/students`, `/report` and the LLM context). `/stage` grouped by the CSV's unreliable "Current Stage" (`stage_report.py:69`). `/missing` correct, except university fields skipped for programs with `drop_columns` |
| free text / LLM | Bare-substring routing (`"cross" in "across"`, `"pin" in "shipping"`, `"jan"` inside a name, `"oct" in "doctor"`, `"mar" in "summary"`, `"aug" in "daughter"`); "how many"/"today"/"done" sent to the LLM executive report; dashboard **placeholders** (262 applicants, 31 this week, 2 under review, "visas" = window Accepted tile, Hanyang "1565" taken from CSS colour `#1565c0`); the inquiry list put into the prompt **twice** (by evening ~11k tokens vs num_ctx 3072, cut to 1,538 → invented answers); calendar parser broken (`div.ag-item` gone; titles now `.rm-title`) |
| jobs (critic) | Passport watcher: cached every flagged uid and saved **before** sending, sent only `new_alerts[:3]`, logged `len(new_alerts)` (`scheduler.py:81,94-95,101`) → 5 of 8 alerts on 27 Sep never sent; page 1 only (42 of 301 scans); cache keyed by uid only (re-uploads never re-checked); MRZ read only from the **bottom 30%** of the upright image (`ocr_validator.py:309`), no rotations → 4 of 7 flagged scans were real passports called "not a valid passport"; one-letter OCR misreads (e.g. N read as M) reported as name discrepancies (`compare_names` token overlap 2/3 < 0.75 → TYPO). Portal sync: `_row_key` (Student ID → Passport No → name+mobile) changes when an ID is assigned, so every payment verification showed as "1 new + 1 removed"; document-check message under a hard-coded header; re-downloads reported as "newly verified". Voice: "passports" routed to the static text ("5 verified today, 4 passports 100% match" when the truth was 0); 12 Sep answered as "No students verified today" |

- Same day, 13:56: results reported to the owner; fixes to come **after** the brief workflow landed, to avoid edit conflicts.

### 7.6 The all-commands fix workflow (`wf_4b2a1e08-5c6`, task `wyjyqe0pz`, 11 agents, 13:55–17:42)

"Fix every command the accuracy audit found wrong: shared helpers first, 4 parallel fix branches, merge, live re-verify, repair". Worktrees under `C:\Hangeul\JARVIS\fix\` (`base`, `inquiries`, `crosscheck`, `freetext`, `jobs`, `all`; since removed); scratch scripts in `C:\Hangeul\JARVIS\fix\scratch\<step>\`; result: `…\tasks\wyjyqe0pz.output`. `C:\Hangeul\BOT` was not touched until the final fast-forward.

```
fix/base (e0d47ab) ──┬── fix/inquiries (46cdf03) ──┐
                     ├── fix/crosscheck (40da0e6) ─┤
                     ├── fix/freetext (7f42ad0) ───┼── fix/all: merges 65fdba1, 638655b, df021de, 981d63d
                     └── fix/jobs (9dcd9ad) ───────┘      → integrate 344a247 → verify (191 cases)
                                                          → repair e164679 → re-verify (58) → c17d887 → main (ff-only)
```

| Step | Commit / time | Result |
|---|---|---|
| **Foundation** | `e0d47ab` 14:31 | New `src/dates.py`: `parse_user_date` (whole-word months, day-first numbers, ISO; `None` for "31 Sep" or no date, never today), `user_date_problem`, `has_date_hint`, `parse_stamp`/`Stamp`, `stamp_on_day` (whole day and month tokens, year rules), `yearless_day_problem` (the brief's rule), `local_today()` in `REPORT_TIMEZONE`. New `src/bot/replies.py`: `split_text` (< 4096 at line breaks, counted in UTF-16), `send_pieces`/`reply_long`/`send_long` (plain-text resend when Markdown is refused; edits a "please wait" message into the first piece), `date_error_reply`, `portal_error_reply` ("Couldn't read the portal: …"). `client.py`: `PortalUnavailable`, one session path `portal_get`/`fetch_html` (URL-encoded params, checks `login()`'s result, logs in again once when a page ends on `login.php`), `read_student_pages`/`read_students` (follow "Page X of N" keeping the query, de-duplicate by uid, raise on a partial list or unknown layout). `parsers.parse_students_page` reads students.php by header names (fixes the one-cell shift and "March 2027"). `/verified*` read every page (12 Sep 0→10, 14 Sep 4→9, 23 Jul 0→62, split in 3 messages), `/admitted` picks the dashboard's Admitted stage ("Admitted / Completed") from every page and filters in code. **11 fixed, 5 not fixed**; 336 tests; 32 live cases match |
| **fix/inquiries** | `46cdf03` 15:00 | `client.read_consultation_day(day)`: `GET consult_requests.php?status=all&from=DAY&to=DAY` (the page's own GET filter), figures from the status tabs, raises when the filter is not echoed, a row is from another day, or rows/caption/tabs disagree. `client.read_consultation_totals()`: all-time counts from `nav.cr-tabs` `.n` on the light `?status=file_opened` view (~118 KB vs 2 MB). `parsers.consultation_view`. `handled_by` = the row's own `.cr-by` only; "(by X)" for done, "(last updated by X)", "(assigned to X)"; "—" → N/A; Cloudflare `data-cfemail` names decoded. Brief section uses the same reads; `consultation_coverage` removed. **11 fixed, 2 not fixed**; 375 tests; 14 live cases; all-time 1002 / 801 |
| **fix/jobs** | `9dcd9ad` 15:12 | Watcher reads every page (301 scans vs 42); memory `data/alerted_passport_issues.json` v2 keyed `uid\|passport_<uid>_<unixtime>.<ext>`, valid or not; every alert sent, packed into as few messages as fit under `CHUNK_CHARS` (3900, `src/bot/replies.py:33`; `_alert_messages`, `scheduler.py:102`), marked sent only after Telegram accepts; stops starting OCR after 20 min; one run at a time. Sync `auto_sync.sheet_changes`: rows whose key changed are paired by Student ID, then a real passport number, then name + mobile → "edited (columns)"; placeholder passports (PENDING) are no identity; `notify()` uses its title and splits; FAIL/INCOMPLETE lines name the first failing rule. `/stage` from the students.php "Stage · Applied" column of every page. `/missing` reads university fields for KLP/EAP/Bachelor's from the portal record. `passport_issue.py`: cache keyed by each student's own Passport No (the PENDING key had given 12 students another's value); a failed read keeps the last cache. **7 fixed, 5 not fixed**; 373 tests (37 new in `tests/test_jobs.py`) |
| **fix/crosscheck** | `40da0e6` 15:18 | One shared path via `read_students()`; students picked by the row's own "Payment verified by NAME · DD Mon, HH:MM" stamp (`parsers.verification`, `stamp_on_day`); strict query parsing (month names only as whole words; portal and HNG ids looked up on every page; a name search checks ≤ 10 students); `_send_blocks` splits between cards < 3900. `/passports`, `/passport_audit` live (with/without scan by Passport Status; OCR of today's verified, ≤ 5). `AUDIT_REGISTRY` and root `test_crosscheck.py` removed. `ocr_validator`: whole page read upright, then 270/90/180°; no MRZ → `MRZ_UNREADABLE` ("couldn't read the MRZ (the photo may be rotated or blurred, or it may not be a passport)"); `parse_mrz_line1` requires 44 chars TD3; `parse_mrz_line2` trusts each field only by its own check digit (failed → `NOT_READ`, "check by eye"); one-letter/partial/uncertain name differences → `OCR_UNCERTAIN` in a new `uncertain` list, not a discrepancy; `build_verdict` lists matched / "Not on the scan" / "Blank on the portal"; "All Fields" only when all 7 match. `audit_student_passport`: `PORTAL_UNREADABLE` when the profile/scan cannot be read; a web page is never saved as a scan. **14 fixed, 4 not fixed**; 408 tests (72 in `tests/test_crosscheck.py`; 70 fail on `e0d47ab`) |
| **fix/freetext** | `7f42ad0` 15:31 | New `src/bot/ask.py` (1,137 lines): `classify()` on whole words + `date_window()` for spans; live answers `answer_pending` (`students.php?status=pending`, every page), `answer_window_review`, `answer_dashboard` (tiles and cards), `answer_intake`, `answer_applied`, `cant_answer()` ("I can't answer that from the portal yet" + the commands that can); `calendar_query`/`calendar_items` (today→Sunday for "this week", next N days, month, weekday, DHL-only, deadline-only, university search; merges reminders, 45-day timeline and the month's EV list). LLM path: `answer_agent_query(query, facts)` only **picks numbered live facts** (JSON, `num_predict` 60, dropped when `prompt_fits` fails); picked facts shown word for word; no raw inquiry dicts/contacts/remarks in any prompt; `_generate_structured_report_fallback` removed. Report route only for report/brief/summary/overview/recap. Jennie uses the same routes; English line must pass `brief.claims_problem` for the answer's own day; Korean line built from the headline fact. **11 fixed, 5 not fixed**; 446 tests |
| **Merge** | `65fdba1` 15:34, `638655b` 15:34, `df021de` 15:37, `981d63d` 15:38 | Conflicts: `handle_natural_language_message` (kept the new `ask.classify` router + the inquiries branch's "a specific date" → `/inquiries_date` prompt rule); `tests/test_watcher_nonblocking.py` (one grouped message, newest upload first, HNG id + uid, new `MRZ_UNREADABLE` wording) |
| **Integrate** | `344a247` 15:53 | Cross-branch bugs: watcher now treats `PORTAL_UNREADABLE`, `OCR_UNAVAILABLE` (and `MISSING_DOCUMENT`) as `UNCHECKED_STATUSES` (retried, never alerted, never remembered; `scheduler.py:37`); a past-day brief drops an LLM summary that says "today"; `/alerts` shows the dashboard's live "Needs attention" card (it always said "No urgent alerts"); `/stats` via `reply_long`; `/sendmail` lookup fallback reads every page and ignores Cloudflare "[email protected]"; root scripts `test_verified.py`, `inspect_passports.py`, `download_passports.py`, `audit_program.py` read every page through the shared reader. 607 tests (`tests/test_integration.py`); import check: 41 handlers (42 with voice), 37 commands, 6 jobs |
| **Verify** | ~16:19–16:29 | 3 independent verifiers (data-commands 77 cases, crosscheck-jobs 53, freetext-voice 61) = **191 cases: 164 correct, 26 not correct** (+1 not testable), each against the verifier's own portal read |
| **Repair** | `e164679` 17:03 | All 25 verifier cases real and fixed: date prompt re-arms after a bad date (`_ask_date_again`); `/admitted` university = the cell's `.stu-uni`, application lines separate; **`/stage` status and % from each student's own `progress.php?uid=N`** (`stage_report.read_progress`, 4 at a time; `parsers.parse_progress_page` reads `.pg-ring`, `.pg-now .pg-stage/.pg-status`); OCR claim counted by `_ocr_checked`/`_ocr_note`; sync second pairing pass `_likely_same`; `missing_report.main()` guarded (one plain failure message, exit 1); `parsers.payment_text` "Paid X (verified income Y)"; calendar `_cal_sub` reads "HH:MM – DD Mon YYYY" as time + end date, `CALENDAR_UPCOMING_MAX=20`, items keyed by portal event id (`_cal_id`), `/deadlines` prefixes "deadlines"; DHL/deadline count labels carry status; Jennie checks the brain's date against the words (`_words_dates`) and speaks a fixed sentence on portal failure. 651 tests (`tests/test_repair.py`, `tests/test_repair_voice.py`) |
| **Re-verify** | ~17:37 | 58 cases: **51 correct, 7 partly wrong** (a no-digit mistyped answer such as "tomorow"/"foo" closed the date question; a `SCAN_UNREADABLE` card still got "checked by OCR just now"; a sibling leaving and another joining with the same family mobile merged into a false edit; a dated calendar view silently dropped items marked done; `/report` 12 and 19 Sep: an unlabelled verified total) |
| **Last fixes (Claude)** | `c17d887` 17:45 | The 7 fixed with unit tests only (`tests/test_final_fixes.py`), **not re-verified live**; plus brain on demand (§7.7). 659 tests |

Workflow log lines: "foundation committed e0d47ab: 11 fixed, 5 not fixed"; "fix:inquiries: 46cdf03, 11 fixed, 2 not fixed"; "fix:crosscheck: 40da0e6, 14 fixed, 4 not fixed"; "fix:freetext: 7f42ad0, 11 fixed, 5 not fixed"; "fix:jobs: 9dcd9ad, 7 fixed, 5 not fixed"; "verify: 191 cases, 26 still not correct".

Test fixtures use synthetic names; real names from audit evidence were replaced before committing. Portal traffic in every step: GETs + the login POST only.

### 7.7 Voice turned off; brain on demand (17:07–17:19)

- 17:07 owner: "i dont want bot to audio chat with me for now. its maxing my gpu. can i just keep using the older authentic version…" → `.env` `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false`; **JennieVoiceWatchdog disabled**; `JennieVoice.lnk` moved from Startup to `C:\Hangeul\JARVIS\disabled\`; voice service stopped; bot restarted 17:08. GPU 8–9.8 GB peak → **3.8 GB** (Windows/apps ~1.2 + brain 2.6).
- 17:19 "Good job… Go with your plan" → **brain on demand** in `c17d887`: `ollama_client.brain_pinned()` = `JENNIE_VOICE_ENABLED or BRAIN_ALWAYS_LOADED`; `keep_alive()` returns `-1` when pinned, else `settings.BRAIN_IDLE_UNLOAD` ("5m"); `keep_brain_warm` returns at once when not pinned; no warm-up at start, and startup lets go of a pinned copy (`src/config.py:75-76`: `BRAIN_ALWAYS_LOADED: bool = False`, `BRAIN_IDLE_UNLOAD: str = "5m"`). GPU idles at **~1.0 GB**; the first typed answer after a quiet spell takes a few seconds longer.
- To re-enable voice: set both `.env` flags true, move `JennieVoice.lnk` back to Startup, `Enable-ScheduledTask JennieVoiceWatchdog`, start the service (`start_jennie_voice.vbs`), restart the bot.

### 7.8 Deploy (18:05–18:08) and the first full watcher run

- The 18:05 brief went out from `f8fefa4` first; then `git merge --ff-only fix/all` on main (HEAD `c17d887`), restart with the full path `cmd /c "C:\Hangeul\BOT\stop.bat" nopause` (a bare `stop.bat` fails from PowerShell) → "Application started" 18:06:21. Worktrees and fix branches removed, audit worktree removed; `git branch` shows only `main`, working tree clean.
- Owner report (18:08): before/after table (e.g. `/verified_date 14 Sep` 4 → 9; `/verified_date 23 Jul` 0 + "Message too long" → 62 in 3 messages; `/inquiries_today` all-time → 1,006 requests / 806 done from the portal's own counts; `/inquiries_date 8 Sep` → 21; `/inquiries_date 31 Sep` → "September has 30 days"; `/admitted` → "0 of 330"; passport alerts all sent; a rotated photo no longer "not a passport").
- Watcher after deploy (`hangeul_bot.log`): 18:36 "Passport watcher memory is the old uid-only list … every current scan is checked again"; 18:56 "301 scans on the portal, 146 audited this run (20 with issues) … 155 waiting for the next run; 20 alert(s) sent in 2 message(s)" (20-min OCR cap); 19:23 "155 audited (11 with issues) … 11 alert(s) sent in 1 message(s)"; from 19:36 on "0 audited", ~9 s per run.

### 7.9 The passport false alarm for one student (20:22–20:23) — fix designed, deferred

- 20:22 the owner asked "which doc?" about one of those alerts: a **"Passport No mismatch"** for one student (`<uid>`, scan `passport_<uid>_<unixtime>.jpg`).
- Diagnosis (the diagnosis script in `C:\Hangeul\JARVIS\fix\scratch\final\`, OCR by the PC's reader; the image was not opened by the agent): MRZ line 2 was **garbled** — nationality read "AZ7" instead of "BGD", the DOB and expiry check digits failed — but the passport-number check digit **passed by chance** (~1 in 10), so `_validate_passport_data` (`ocr_validator.py:767`, `pass_ok = bool(mrz.get("passport_no_ok"))` at line 799 → `elif pass_ok: pass_status = "MISMATCH"` at lines 809-812) reported a confirmed mismatch. The printed page's number differs from the portal's in **one character**: either a portal typo or a misread; staff to check by eye.
- Planned fix (not built): see [Open items §C](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md). 29 Sep 04:57, asked when to do it: **"not now"** (owner).

---

## 8. The reference pack (29 Sep 04:54–06:31)

**Goal:** a description of everything done so far, detailed enough to copy. Owner (04:54): "give me a very detailed description of what was done till now. I am making another proprietary bot and this report will be used as a reference…". Answers (04:57): form **Markdown pack**; purpose **"Blueprint to copy"**; detail **"everything and the actual secrets and everything on the .env file"**; the passport fix **"not now"**.

**Decision (Claude, applied to the owner's "actual secrets"):** secrets go only as exact file copies in `C:\Hangeul\REFERENCE\secrets\` (`bot.env`, `credentials.json`, `token.json`, plus a `README.md` naming every `.env` key); the Markdown files name keys and never paste values; student data is left out.

**Run:** workflow `wf_2c5697c4-460` (task `w1vzele87`, 10 agents, 05:00–06:30):

| Step | Agents | Output |
|---|---|---|
| Write (05:00–05:28, in parallel) | files-bot, files-core, files-sheets-rest, portal-commands, env-llm-voice, history | 03a; 03b; 03c, 07, 10; 04, 05; 02, 06 and `secrets\`; 08, 11 |
| Synthesize (05:28–05:47) | 1 | 00, 01, 09 (12 was added during the check) |
| Critics (05:47–06:04) | accuracy (about 170 facts checked against the code), rebuild ("a new AI with only the pack" listing what it still lacked) | **31 issues (2 high)** |
| Fix (06:04–06:30) | 1 | all 31 applied |

One high issue was a real student's portal uid with identifying detail (scan pattern, upload date, which character differed) in 08 and 11; it became `<uid>` and "the diagnosis script in `C:\Hangeul\JARVIS\fix\scratch\final\`", which is why the passport case (§7.9) is anonymous. Another was a 62-vs-63 CSV column count.

**Verification:** Claude's own leak check (06:31) found no password, token, key, phone number or passport number outside `secrets\`. The Google login is a normal OAuth sign-in, not a service account, and `token.json` refreshes itself hourly, so a copied `token.json` goes stale. Result: 16 Markdown files, about 8,000 lines, citing path:line at `c17d887`.

**Later touches before this refresh:** 29 Sep 15:05 Claude added the new setting names (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_ACCESS_TOKEN`, `CLOUD_PUBLISH_ENABLED`, `CLOUD_EMBED_MODEL`, `CLOUD_EMBED_REVISION`) to `secrets\README.md` §3 by name, and re-copied `secrets\bot.env` (spec step 7, which the build agents could not do from their worktrees). §18 is this refresh.

---

## 9. The GPU usage question (29 Sep 07:58–08:02)

Owner (07:58): "what percentage of gpu im using now and Peak GPU usage when running the bot at full scale. with historic data."

| Reading | GPU memory | Notes |
|---|---|---|
| Now (07:58) | **1.2 of 8 GB (15 %)**; GPU load 1 % | Windows and apps only, because the monitor is plugged into the RTX 5060 (open item B6). The brain was not loaded: brain on demand (§7.7) |
| Peak at full scale, **voice off** (measured while the bot built a full brief with its LLM summary) | **3.9 GB (50 %)** | Windows/apps 1.0–1.2 GB + brain `qwen3:4b-instruct` +2.8 GB while answering, unloaded after 5 idle minutes (`BRAIN_IDLE_UNLOAD`, `src/config.py:76`). The watcher's passport OCR runs on the CPU (0 GB). GPU compute touched 93 % for about half a second. Not in this measurement: the 15-minute sync's document check uses GPU EasyOCR (~2.4 GB) while it runs, which is only when a newly verified student arrives ([Sheets and document check](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)) |
| Peak, **voice on** (27–28 Sep) | **100 %** | 97 % at 08:55 on 28 Sep, full for an hour on the evening of 27 Sep; demand 8–9.8 GB against 8 GB, so Windows spilled to system RAM: 78 of 152 voice replies took longer to render than to play; moving TTS onto the GPU took up to 9.4 s |

History source: there is **no continuous GPU log** on this PC. The figures came from the 283 memory readings the voice service logged (27 Sep 18:25 → 28 Sep 14:28) plus `nvidia-smi` spot checks since the voice was turned off; memory only, no compute history. Claude offered a per-minute GPU logger as a scheduled task, to be set up only on the owner's word; **no answer** (open item).

---

## 10. The Supabase publish task: prompt, decisions, preconditions (29 Sep 09:04–10:35)

### 10.1 The prompt

- 09:04 the owner attached `C:\Users\User\Downloads\hangeul-bot-prompt.md` (282 lines, "Status: ready-for-agent", written for "a Claude Code session opened in `C:\Hangeul\BOT`"): "Is it the markdown files very carefully use multi-agentic workflow to execute?"
- **Goal:** a second, independent destination next to Drive/Sheets, the `.xlsx` reports and Telegram: the owner's Supabase project `dcbcbpwpmdtaanboetiz`, written as **structured rows + text + vector embeddings**, read by the owner's web/PWA assistant **Jeannie** (repo `munim430-ai/Jeenie-saem-bot`, which owns the schema; cloned later to `C:\Hangeul\JARVIS\Jeenie-saem-bot`), "so the owner can ask for anything on their phone and get an answer instantly, without the PC being awake". Supabase "never replaces, delays or blocks" the existing outputs.
- **The owner's decisions, D1–D13** ("do not re-open them"):

| # | Decision |
|---|---|
| D1 | **Full student data**: names, phones, e-mails, passport numbers, DOB, parents' names, addresses and every other parsed field. Nothing masked |
| D2 | Everything parsed from the portal plus every report, including the full OCR text (one chunk per page); no binary files |
| D3 | Both structured rows and text with embeddings |
| D4 | Snapshots: every row carries `read_at`; no inbound connection to the PC |
| D5 | The bot writes with the project's **secret key** from `.env` (PostgREST + RPC), no Edge Function |
| D6 | Independent: if Supabase is down, log one line and carry on; no outbox, no retries inside a run, no Telegram alert; never block Drive, Sheets or Telegram |
| D7 | Embeddings on this PC, on the **CPU**, with **gte-small** (384 dims, mean pooling, L2-normalised); Jeannie uses `Supabase/gte-small` (the ONNX export), so vectors must match |
| D8 | One record per entity; reports split per section or per student line |
| D9 | Upload only changed rows (content hash) |
| D10 | Hard-delete what disappears from a **complete** read |
| D11 | A one-time backfill, including `data\verification\results.json`, the OCR text cache and the watcher memory |
| D12 | The schema belongs to the Jeannie repo (`supabase/migrations/`); the bot never creates or alters tables |
| D13 | Credential rotation deferred by the owner (accepted risk); still never print, log or commit a secret |

- **Preconditions** (stop if one fails): (1) `.env` has `SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co` and `SUPABASE_SECRET_KEY`; (2) the migration is applied: `GET /rest/v1/hg_runs?select=id&limit=1` answers 200, not 404/`PGRST205`; (3) ask before downloading `sentence-transformers` and the model (M7), and pin both; (4) work on a branch in a worktree (M4), `C:\Hangeul\BOT` untouched until the final fast-forward.

### 10.2 First checks and the owner's accepted risks (09:05–09:18)

- The Supabase MCP server connected to this session sees only a different project, "jennie" (`qmjenzloispkyfnksuqr`, created 18 Sep, Seoul), and gets "permission denied" on `dcbcbpwpmdtaanboetiz`, so nothing could be checked through it; every later check used the bot's own key over PostgREST.
- Jeannie's web app (`jeenie-saem-bot.vercel.app`, the "Vercel demo" of §7.4) is **public, with no login** (its HUD then showed "ACCESS: OPEN"); its "HANGEUL BRIDGE" panel asks for `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Claude's concern: with D1, anyone who has the URL could get answers built from full student data. (Later: by 30 Sep 23:46 the HUD showed "ACCESS: KEY REQUIRED", the single `JEANNIE_ACCESS_KEY`, §18 and [11 B8](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md).)
- Claude asked four questions at 09:06; the owner answered at 09:18:

| Question | Options (Rec. = recommended) | Owner's answer |
|---|---|---|
| The Jeannie web app is public: how to handle it? | Build all, upload after Jeannie has a login (Rec.); build and upload, the owner locks Jeannie first; mask passport numbers, DOBs, phones, addresses and parents' names (changes D1) | **"You don't need to worry about the fact that Jenny is public."** Accepted risk: full PII (D1) stands and Jeannie stays public. Not to be raised again |
| Which Supabase project? | `dcbcbpwpmdtaanboetiz` (as in the prompt); `qmjenzloispkyfnksuqr` ("jennie") | **`dcbcbpwpmdtaanboetiz`** |
| May I download the embedding model (~70 MB, pypi.org and Hugging Face)? | Yes / Not yet (stub embedder) | **"Yes, download it"** |
| Start building now, before the keys and migration? | Build and test offline (Rec.) / Wait | **"Wait for the preconditions"** (not Rec.) |

### 10.3 The model download (09:19–09:23)

- **15 new packages** in `C:\Hangeul\BOT\.venv`, installed against a constraints file made from the previous `pip freeze`, so no existing package changed (torch 2.11.0+cu128, numpy and EasyOCR stayed; EasyOCR and the GPU were re-checked afterwards): `sentence-transformers` 6.1.0, `transformers` 5.17.0, `huggingface_hub` 1.33.0, `tokenizers` 0.23.2, `safetensors` 0.8.0, `scikit-learn` 1.9.1 and small dependencies. `requirements.txt:38-44` pins the two that decide how the model loads (`sentence-transformers==6.1.0`, `transformers==5.17.0`).
- The model `thenlper/gte-small` (MIT, 67.7 MB) pinned at revision `17e1f347d17fe144873b1201da91788898c639cd`, cached in `%USERPROFILE%\.cache\huggingface`. On the CPU: 384 numbers per record, ~14 ms per record (1.4 s per 100), ~1 GB peak RAM, the same result every run.
- **Finding:** transformers 5 loads this model as **float16** unless told otherwise: 7× slower and not what D7 needs. The code loads it with `model_kwargs={"dtype": torch.float32}` (`src/cloud/embed.py:222`).
- **Finding:** 6 of the 659 tests now failed. Not the packages: they depend on the date. `ask.py` does `from src.dates import local_today`, so tests that monkeypatch `dates.local_today` did not pin `ask`'s copy and passed only on 28 Sep. The live bot was correct; the fix is test-only (in the build, §11, and on main in §13: `tests/test_foundation.py:136` `pin_today`).

### 10.4 The key mix-ups (09:27–10:31)

Claude asked for two lines in `.env`, typed there and never pasted in chat: `SUPABASE_URL` and `SUPABASE_SECRET_KEY` (the `sb_secret_…` key, or the legacy `service_role` JWT).

1. **The placeholder (09:27).** Owner: "I have added the keys to the environment variable files. Check. Again." The URL was right; the key line held Claude's own example text, `<your sb_secret_… or service_role key>`, verbatim. Claude named the line (40) and where the real key is: Project Settings → API Keys → the **secret** key; never the publishable or anon key, which cannot write and which the tables refuse.
2. **The empty project (09:30).** "done, check again": the key was accepted (41 characters, `sb_secret_` shape; a wrong key was refused, so it is the right one), but `hg_runs`, `hg_records`, `hg_chunks` and `hg_changes` answered **404 PGRST205** and `rpc/hg_sync` **404 PGRST202**: the project had no tables. Under D12 applying the migration is the Jeannie side's job; Claude offered the SQL editor (the 4 files in order) or `supabase link` + `db push`.
3. 10:10 the owner delegated it: "I'd rather you apply them. I'll give you a Supabase personal access token (Supabase dashboard → Account → Access Tokens) as the environment variable SUPABASE_ACCESS_TOKEN, not pasted in chat. … Apply only the four migration files in supabase/migrations/. Don't write any new SQL, and don't edit these files. … Report the output of supabase migration list so I can see all four markedown files applied."
4. **Personal access token vs secret key (10:12–10:31).** The token was in neither the user nor the system environment (checked in the registry), and not in `.env` (last saved 09:52). 10:20 "i have add a bot's .env file already check if it carries a supabase access key or not"; 10:24 "I have gathered a Superbase public access token … and … service keys". Claude spelled out the two different things: `SUPABASE_SECRET_KEY` = **`sb_secret_…`**, from Project Settings → API Keys, which the bot writes with; `SUPABASE_ACCESS_TOKEN` = **`sbp_…`**, from Account → Access Tokens, which only the CLI needs; no publishable key is needed anywhere. It opened `.env` in Notepad with the exact steps (Ctrl+End, a new line, Ctrl+S).
5. **Resolution (10:30–10:31).** The owner saved the `sbp_` line in `.env` at 10:30 **and also pasted the token in chat** at 10:31, so it is in the session transcript (value in secrets/bot.env (SUPABASE_ACCESS_TOKEN)), asking "Do I need to post this access key in my virtual server also?" and adding "You don't need to suggest me that I need to rotate the axis." Answer: no. The `sbp_` token is only for the CLI and Management API on the machine that runs migrations; a server running Jeannie needs `SUPABASE_URL` and the project's secret (service) key, which Vercel calls `SUPABASE_SERVICE_ROLE_KEY`. The bot never reads the token: `Settings` has `extra="ignore"` (`src/config.py:144`).

### 10.5 The Supabase CLI and the migrations (10:11–10:33)

- 10:11 Claude asked to download the official CLI; answer **"Yes, download it"**: `supabase_2.118.0_windows_amd64.zip` (64.1 MB, GitHub release of 25 Sep 2026), checked against the release's `checksums.txt`, unpacked to `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe`; no PATH or system change.
- The Jeannie repo was cloned to `C:\Hangeul\JARVIS\Jeenie-saem-bot` (commit `31202e9`) with `core.autocrlf=false`, so the four migrations stay byte-exact (git then lists every file as modified; nothing is).
- From that repo, with the token read from `.env` into the process environment only: `supabase link --project-ref dcbcbpwpmdtaanboetiz` (project healthy, Tokyo, ap-northeast-1) → `supabase db push --dry-run` (exactly the 4 files; no seeds, no roles; **no database password needed**, the CLI initialises a temporary login role) → `supabase db push --yes` → `supabase migration list`: local = remote for `20260928000000` (jeannie_memory), `20260928180000` (jeannie_memory_revoke_public), **`20260929030000` (hangeul_context, the one the bot needs)** and `20260929030100` (jeannie_memory_grant_service_role).
- **Verification** with the bot's own secret key over PostgREST: `hg_runs`, `hg_records`, `hg_chunks`, `hg_changes`, `memory_documents` and `memory_chunks` answer 200 (0 rows); `jeannie_audit_log` and `jeannie_sessions` exist; the RPCs are `hg_sync(p_run, p_kind, p_scope, p_rows, p_all_keys)`, `hg_match(p_embedding, p_count, p_kinds, p_student_uid, p_day_from, p_day_to)`, `hg_changes_since(p_seq, p_limit)`, `match_memory` and `upsert_memory_document`; a request without the key gets 401. **All four preconditions passed by 10:33.** The contract in full: [Supabase publishing](13_SUPABASE_PUBLISHING.md).

---

## 11. The build workflow, its network drop and the resume (29 Sep 10:34–15:03)

Workflow `wf_1eb48122-237` "Build the Supabase publish layer from hangeul-bot-prompt.md: contract + inventory, core package, 3 parallel hook branches, integrate, adversarial review, fix, live dry-run (nothing uploaded)" (first task `wkuzhz3at`, 11 agents; resumed as task `wwn0lrljq`, 12 agents). Worktrees under `C:\Hangeul\JARVIS\cloud\` (`core`, `jobs`, `inproc`, `commands`, `all`); scratch in `C:\Hangeul\JARVIS\cloud\scratch\<step>\`. `C:\Hangeul\BOT` stayed at `c17d887` with a clean tree and the live bot was never touched.

```
c17d887 ── cloud/core: 36ae72e → a0572ba → cfd10f1 ──┬── cloud/jobs     41055de ──┐
                                                     ├── cloud/inproc   5048a07 ──┼── cloud/all: merges 44c9378, 112325b, 969f917
                                                     └── cloud/commands 2b6798f ──┘   → cb16394 (integrate) → 3caa393 (review fixes)
                                                                                      → 752cd53 → 9ead47d (dry-run fixes, §12)
```

| Step | Time | Commit | Result |
|---|---|---|---|
| Contract | 10:34–10:41 | — | The server contract from the SQL (`20260929030000_hangeul_context.sql`, identical to its commit `e387ff2`): `POST /rest/v1/rpc/hg_sync` (a GET runs read-only and fails); only `service_role` may execute; PostgREST resolves the function by the body's keys (an extra top-level key → `PGRST202`); one call = one transaction. Where the SQL differs from the prompt, the SQL wins: it also returns `unchanged`; `p_all_keys=[]` empties a scope; a same-hash row keeps its old `read_at` and `run_id`; `field_correction` is append-only |
| Inventory | 10:34–10:50 | — | Every reader and writer of the bot at `c17d887`, with path:line |
| Core | 10:50–11:35 | `36ae72e` 11:28, `a0572ba` 11:30, `cfd10f1` 11:33 | The package `src/cloud/` (publish, records, embed, handoff, backfill), the five settings (`src/config.py:86-92`), the redaction filter extended to `Bearer`/`apikey:` values, `sb_secret_`, `sb_publishable_`, `sbp_` and JWT shapes on `httpx`, every `httpcore.*` logger and `hangeul.cloud` (each logger needs its own filter), `tests/conftest.py` forcing publishing off in every test, and the 6 date tests pinned. `a0572ba` writes two invisible characters as `chr()` calls; `cfd10f1` sends a complete key list for batches that carry only some records (the watcher audits only new scans, but its list names every scan). **720 tests** |
| Hooks (parallel) | 11:35–12:04 | `2b6798f` 11:58, `5048a07` 12:02, `41055de` 12:03 | commands: `src/cloud/command_hooks.py` (`seen()` after each read, `publish()` after the reply, never awaited; 758 tests). inproc: `src/cloud/bot_jobs.py` and `src/cloud/full_picture.py` (the 18:05 brief, the watcher, and a new hourly job `cloud_full_picture`, first run 7.5 min after start, `max_instances=1`, `coalesce=True`; 750). jobs: `src/cloud/sheet_hooks.py` (portal_sync, missing_report, stage_report, issue_refresh; 746) |
| Integrate | 12:04–12:16 | merges `44c9378`, `112325b`, `969f917` 12:05; `cb16394` 12:15 | No text conflicts. Meaning conflicts fixed: one tile conversion (`records.tile_facts`) for the brief and `/stats`, so a tile is one record with one hash; the watcher publishes its audits' `student_profile`s and its accepted alert messages as `notification`; `tests/test_cloud_all.py`. **823 tests**; import check: 41 handlers, 7 scheduler jobs, torch not imported by the bot |
| **Network drop** | 12:16–13:22 | — | The three reviewers and the dry run failed with "API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)" (12:28–12:32; the main session printed the same at 12:35). The run's log still said "review: 0 issues", which meant nothing. Owner 13:22: **"Try again"**. Claude checked the connection and the clean `cloud/all`, then **resumed the saved run** (13:23): the 7 finished agents came back cached; only the reviewers, the fixer and the dry run ran |
| Review | 13:23–13:41 | — | Three adversarial reviewers: contract (harnesses applying the SQL rules), delete safety and failure isolation, secrets and tests (18 source mutations). **21 issues (1 high)**. The high one: `_publish` forgot the gone keys from the hash state before the deleting call was accepted, so a failed delete was never sent again |
| Fix | 13:41–14:26 | `3caa393` 14:25 | Gone keys forgotten only after the last call of the scope is accepted; the scope digest removed before the first call; an **older complete read published later deletes and rolls back nothing** (read times `t` per record and `reads` per scope in `data\cloud_state.json`); `embed_model` enforced across runs; the `hg_runs` PATCH always sent; locally skipped rows counted as unchanged; `records.pending_complete`, `window_complete`, `export_complete` (the export is complete only with its header and ≥ 90 % of the students the last whole list counted); `passport_alert` complete only over `bot_jobs.watched_scans` (each listed student's newest scan), so a lost watcher memory deletes nothing; the full picture re-checks the quiet windows before each page; stand-in words removed from data and text ("a student", "Unassigned", "Event", "Dashboard"…); student ids on the passport-keyed kinds via the new `src/cloud/student_index.py` (`data\cloud\student_index.json`); the consultation key is the hidden `id` of the row's forms. Declined and reported: `read_at` means "last changed" under the SQL (freshness comes from `hg_runs.finished_at`); `calendar_item` is never complete; the secrets README was outside the worktree. **855 tests**; the fixer's 18 mutations all killed |
| Dry run 1 | 14:26–15:03 | — | §12 |

---

## 12. Dry runs 1–3 and their fixes (29 Sep 14:39–16:45)

**How each dry run was made:** `python -m src.cloud.backfill --dry-run --docs-root "C:\Hangeul\VERIFIED STUDENT DOCUMENTS"` in the `cloud/all` worktree, with byte-identical copies of `C:\Hangeul\BOT\data` inputs; a network guard allowed only portal GETs and the login POST (`C:\Hangeul\JARVIS\cloud\scratch\dryrun\guard.py`); `publish.TRANSPORT` raised on use (0 Supabase attempts); the run started between live syncs (the verifier watched `C:\Hangeul\BOT\data\auto_sync.lock`, which a worktree run cannot see itself). The exact request bodies went to `data\cloud\dry_run\<run>\`. An independent verifier re-derived every count with its own client and parsers, before and after.

| Run | Time | Code | Records / chunks | hg_sync calls | Verdict |
|---|---|---|---|---|---|
| 1 | 14:39:23–14:53:16 (833 s) | `3caa393` | 13,179 / 15,218 | 592 | not ready: R1 fillers; also log flood, CUDA "", 1.98 MB body |
| 2 | 15:37:13, 857 s | `752cd53` | 13,189 / 15,228 | 601 | not ready: Cloudflare e-mail stand-ins |
| 3 | 16:22:54–16:37:10 (856 s) | `9ead47d` | 13,194 / 15,234 | 601 | **ready** |

All 21 kinds' counts matched the independent reads in every run.

### 12.1 Dry run 1: the findings

- **R1, the portal's filler words (the one failing check):** `student` kept the portal's own typed fillers in `data.details`: "N/A" 45 times, "None" once, "--" once, "PENDING" 7 times; the export kept "PENDING" in 9 cells. The export already blanked "N/A" through `progress_builder.clean_value`, so the same field was "" in one kind and "N/A" in the other. The bot invented none of them: each was typed on the portal.
- **Log flood (D6):** with the model unavailable, every publish logged its own line, because an `EmbedError` did not mark the run down: 56 identical lines for `verification` alone in an aborted attempt, about 600 for a whole backfill.
- **CUDA "" (Windows):** `embed.prepare_process` set `CUDA_VISIBLE_DEVICES=''`. CPython on Windows **removes** a variable set to an empty value, and the CUDA runtime treats unset as "every GPU", so `torch.cuda.is_available()` was True in the embedding process. torch still refused the device and the model stayed on the CPU (the PID never appeared in `nvidia-smi`), but the hiding was not real.
- **Body size:** the largest `hg_sync` body was 1.98 MB (200 student rows with full details); the gateway's limit was unknown.
- Measured: model load 5.0 s; embedding 727 s for 13,179 records (5.5 s per 100 records; 12.5 s per 100 for OCR pages); peak working set 1.57 GB, CPU RAM. Portal traffic: 13 GETs of `students.php`, 331 of `progress.php`, 65 of `consult_requests.php`, 1 each of `index.php`, `calendar.php` and `window_applications.php`, plus the login.

### 12.2 Fix `752cd53` (15:26) and dry run 2 (15:37)

Workflow `wf_e7425917-377` (task `w02m6lyyu`, 2 agents, 15:05–16:00):

- **Fillers:** `records.is_filler(value, field)` and `records.is_status_field(name)` (`src/cloud/records.py:230`, `:223`; the words in `FILLER_WORDS`, `:206`): a whole cell of n/a, na, none, null, nil, pending, tbd, not available, not applicable or not provided (case-insensitive, compared on letters and digits only), or of marks only, is blanked in `data` and left out of the text. **"Pending" stays in status fields** (a name with the whole word status, stage, result or step, or Payment, Bank Certificate, Bank Solvency, VIN App, VIN Required). New data key **`data.blank_on_portal`**: the sorted names of the blanked fields (`details.<label>` for a students.php details field), present only when non-empty, so records without a filler keep their hash. The export now uses the same rule instead of `clean_value` (side effect: Bangla-only cells are kept).
- **One line a run:** both `EmbedError` branches call `_model_unavailable()`, which marks the run down; the rest of the run is silent.
- **Real CUDA hiding:** `embed.NO_GPU = "-1"` (`src/cloud/embed.py:43`), set at every `__main__`, in `embed.prepare_process` (`:60`) and in `handoff.child_env()`; `embed.cpu_only_process()` (`:87`) accepts only "-1". A test starts a real child the way the handoff does and reads the OS environment with `GetEnvironmentVariableW`.
- **Body cap:** `publish.MAX_BODY = 1_000_000` (`src/cloud/publish.py:91`) and `_by_size()`: calls are split by their exact serialised size, with `p_all_keys` counted in the last call. Offline re-split of run 1: 601 calls, the largest 999,959 bytes.
- 872 tests.

**Dry run 2:** all four fixes held (0 whole-value fillers; `blank_on_portal` exactly matched the raw pages: 69 students with 78 cells, 69 CSV rows with 80 cells; largest body 999,562 bytes; CUDA really hidden; one warning a run). R1 still failed on **a new placeholder that neither run had caught**: the portal is served through **Cloudflare**, whose e-mail obfuscation replaces every address with the text `[email protected]` inside `<a class="__cf_email__" data-cfemail="HEX">`. It was the whole of `data.details.Email` in 333 of 333 student records and in the pending-payment record, and inside the contact of 1,005 of 1,014 consultations; the bot's own replies showed it too. The CSV export carries the real addresses.

### 12.3 Fix `9ead47d` (16:19) and dry run 3 (16:22)

Workflow `wf_3b282e15-484` (task `wd0c6zkf8`, 2 agents, 16:01–16:44):

- `parsers.decode_cf_emails(soup_or_tag)` (`src/scraper/parsers.py:64`, the byte decoder `_cf_address` at `:24`): the first byte of HEX is the key, and each following byte XOR the key is one UTF-8 byte. It handles the `a` and `span` forms and links to `/cdn-cgi/l/email-protection#HEX` (which become `mailto:`); it is idempotent and offline; malformed HEX, or a result with no "@" or with a space, leaves the element as served. **Every `BeautifulSoup(` in `src/` is wrapped**, before any `get_text` (then 12 in `parsers.py`, 2 in `client.py`, 1 in `ask.py`, 1 in `verified_docs.py`; a source test pins the count). The old per-cell `_cf_email`/`_decode_cf_emails` (consultation names only, from `46cdf03`) was removed. `records.FILLER_WORDS` gained "emailprotected", so an undecodable stand-in is blanked and named, never stored.
- `embed.quiet_libraries()` raises the `sentence_transformers`, `transformers` and `huggingface_hub` loggers to WARNING (the extra "No modules.json found…" INFO line).
- 900 tests.

**Dry run 3, checks a–l all pass:** counts equal two independent reads (16:26 and 16:38); 0 fillers and 0 stand-ins across 657,652 strings; the decoded addresses equal the verifier's own decoding; every chunk has 384 finite floats with norm 1 ± 1e-7 under one `embed_model`; 0 duplicate keys and 0 hash mismatches; `CUDA_VISIBLE_DEVICES=-1` at the OS level and `is_available()` False; exactly one log line with the model missing; only the portal's Cloudflare IPs contacted. Payloads: `C:\Hangeul\JARVIS\cloud\all\data\cloud\dry_run\20260929-162254-backfill-244bfaa8\` (603 files, 99 MB, **full student data**). Portal-data notes, kept as served: 2 students show two different addresses (list cell vs details view), and 9 consultation contacts hold an address with no dot in the domain. Side finding, not fixed: `progress_builder.clean_value` blanks Bangla-only cells in the Google Sheets (an ASCII-only comparison), an open item.

### 12.4 The go question (16:45 → 20:08)

Claude reported (13,194 records, 15,234 chunks, one masked example per kind; the new field `blank_on_portal` and the new kind `doc_check` for the Jeannie side; real e-mails will now also appear in `/sendmail`'s fallback, the inquiries report and the REST API) and asked: "Go ahead with the real upload and the switch-over?" Options: backfill now and deploy after 18:05 (Rec.); backfill now, deploy tomorrow; inspect the payloads first. Answer at 20:08: **"I'll inspect the payloads first."** Claude then explained the folder (`0000-POST-hg_runs.json`, `0001…-student.json` and so on, one file per call in send order; `p_all_keys` only in the last file of a kind and scope) and offered a readable copy without the embeddings. Nothing was uploaded until 30 Sep 20:54 (§16).

### 12.5 Other events on 29 Sep

- **16:36–16:41, the bot was down about 5 minutes.** The last log line was 16:36:21 (the sync, the watcher and the keep-warm job had just fired), with no error; `hangeul_watchdog.log` at 16:41 "not running - starting it"; restart 16:41:02. It coincided with dry run 3 and its verifier's live bot-command check (16:37); some agent transcripts mention kill/Stop-Process. **Cause unconfirmed.** The 18:05 brief went out normally (18:05:20). Lesson: agent prompts now say never to stop, restart or kill a process the agent did not start.
- 20:15–20:38, `/learn` "workflow of this bot": every action starts from one of three triggers (the user, the clock, the bot's own results passed on to Sheets, Telegram and later Supabase); for `/verified_today`, reading the 7 `students.php` pages (about 1 MB each, about 8 s) is almost all of the wait. The owner asked "why u need this answer from me?" and got the plain walkthrough.
- 21:42 "/btw total how many bots this system has. How they run": **one Telegram bot** (@the_Jennie_bot), run by one program (`run.py`, seen as two `pythonw` processes because of the venv redirector: Telegram, the scheduler and the REST API on port 8000), the helper subprocess jobs, the HangeulBotWatchdog task, Ollama, and the voice service (built, off). The 16:36 outage was found while answering.
- 22:06 **"I have already deleted the old bot from old pc yesterday and old telegram bot now"**: the old PC's bot went on 28 Sep and the old Telegram bot on 29 Sep; @the_Jennie_bot is the only bot, and it was still polling Telegram normally at 22:07.

---

## 13. Performance v1: self-computed team figures (29 Sep 21:12 → 30 Sep 10:31)

- **Request (21:12):** "Can the bot give me report of performance like verified today or inquires today? If yes then add in telegram menu two more veriable one for today's performance for all and another for this month performance for all".
- **Claude's reading** (not the owner's words, and later corrected): team totals plus, per person, consultations done (the row's "Last updated by"), No Answer / Wrong Number follow-ups, requests assigned (the Consultant column) and payments verified (count and BDT).
- **Build:** workflow `wf_4b2e81a2-e8a` (task `w1188pjjm`, launched 21:15; branch `feature/performance` from `c17d887`, worktree `C:\Hangeul\JARVIS\perf\build`), kept apart from the Supabase work. `bbd8f98` 21:41: `src/bot/performance.py` (window, read_performance, tally, format_performance_report); `client.read_consultation_range(first, last)` (the date filter; when the list stops at its 500-row cap, the part before the oldest listed day is read as its own window; at most 16 reads) and `client.read_verified_window` (every `students.php` page once, the yearless-stamp rule); `/performance_today`, `/performance_month`, aliases `/perf_today`, `/perf_month`, `/performance [today|month]`; `set_my_commands` from 11 to **13 entries** (the log line had said "Successfully set 7 exclusive bot menu commands" while there were 11; it now logs `len(commands)`, `src/bot/telegram_bot.py:2333`); free-text routes; and the 6 date tests fixed on this branch with `tests/test_foundation.py` `pin_today(monkeypatch)`, which patches both `src.dates.local_today` and `src.bot.ask.local_today`. 724 tests.
- **Verification:** live check (21:48–21:49) with its own session and parser: 161 figures per run, two runs, **0 mismatches** (29 day reads summing to 636 requests; all 7 `students.php` pages, 335 students, 328 stamps). Code review: **7 issues (0 high)**, for example "this months performance" (no apostrophe, the owner's style) refused as "another month", a footer claiming reads that had failed, and another month named with "the month" answered with this month.
- **Interrupted and resumed:** the session ended during the fix step. On 30 Sep 10:10 the harness reported that the run "didn't finish"; at 10:11 the owner typed "/performance_today" into the Claude chat; Claude ran the verified version read-only (nothing sent) and showed the reply, then resumed the run (task `w56wkwh83`; build, verify and review came back cached; fix 10:12–10:30) → `a721066` 10:29 (honest last line, "this months", no stand-in month, other topics keep their routes). 775 tests.
- **Deployed 10:31:** `main` fast-forwarded `c17d887` → `a721066`, restart 10:31:25, "Successfully set 13 bot menu commands"; Telegram's `getMyCommands` showed 13 entries; worktree and branch removed. Live month on 30 Sep: 638 requests, 472 done, 108 payments verified, ৳1,544,165.

## 14. Performance v2: only the portal's Consultant Performance page (30 Sep 13:11 → 14:06)

- **Owner correction (13:11, with two screenshots of Leads › Performance):** **"by performence i meant this one. give me this datas only when i ask for performence this month or today"**. "Performance" means the portal's own page, and the reply must carry only its data.
- **Workflow** `wf_9efae077-816` (task `wfp0dh5ak`, 4 agents, 13:13–14:04; branch `feature/portal-performance` from `a721066`, worktree `C:\Hangeul\JARVIS\perf2\build`).
- **Build `ce23535` 13:34.** The layout was learned from masked GETs of `consult_performance.php?period=today|month|week|all` and with no period (which shows This Month): period tabs `nav.pf-tabs a[href="?period=…"]` (the open one has class `on`); the range line `p.pf-showing` ("Showing This Month · 01 Sep – 30 Sep 2026"); 4 tiles `div.pf-stats > div.pf-stat` with `.n` and `.l` (Consultancies done, Files opened, Conversion (file open), Docs ready); the top card `section.pf-top`; the leaderboard `table.tbl.pf` (#, Consultant, Score, Conversion, Files Opened, Consultancies, Points, Docs Ready; the crowned row `tr.is-top`); tooltips as `th[title]`; the empty state `tr.pf-empty-row > .pf-empty`. New: `parsers.parse_consult_performance` (`src/scraper/parsers.py:1088`; labels, classes and header words, never positions; `PerformanceLayoutError` at `:955`), `client.read_consult_performance(period)` (`src/scraper/client.py:425`; one GET, refusing a page whose open tab or Showing label is another period) and `performance.format_consult_performance`. **All self-computed code was removed** (tally, read_performance, read_consultation_range, read_verified_window, verified_between, ensure_session). 813 tests.
- **Verification:** the live check (13:35–13:49) ran 8 invocations against its own regex parse: **608 comparisons, 0 mismatches**; the tiles equal the column sums (month 716 / 108 / 8) and the top card equals the crowned row. Review: **9 issues (1 high)**. The high one: the owner's own spelling "performence" (and "perfomance", "performances") was classified as unknown. Others: "consultant performance yesterday" went to `/inquiries_date` under the heading "Performance on <date>"; a long leaderboard could split one consultant's record across two messages; any one-cell row counted as the empty state; "ytd performance" got Today's page; and a merge with `cloud/all` would silently break the feature (`_decode_cf_emails` no longer exists there).
- **Fix `314afdb` 14:04:** `ask._PERFORMANCE_WORDS` (`src/bot/ask.py:103`: `perform[ae]nces?|perfom[ae]nces?|performaces?|perfromances?|preformances?|productivity|leader[\s-]?boards?|performers?`, whole words only, so "outperform" does not match); a "performance" question about another day gets the honest other-period reply; the inquiries report's day section, headed "Performance on <date>" since before this work, now reads "📅 Consultations on <date>" (`src/bot/telegram_bot.py:498`); `performance.message_pieces` (`src/bot/performance.py:247`) packs whole records under the limit; only `tr.pf-empty-row` or a lone `.pf-empty` is the empty state; ytd, this year and all time get the other-period reply. 884 tests. Left for the merge: the `decode_cf_emails` fix (§16).
- **Deployed 14:06:** `main` `a721066` → `314afdb` (fast-forward), restart 14:06:37; the menu descriptions read "the portal's Consultant Performance page: tiles, top performer, leaderboard". The month reply matched the owner's screenshot except for consultations logged since.

## 15. The reboot of 30 Sep 20:35 ("fallback is offline?")

- The PC restarted at 20:35 (no agent command was running). At 20:36 both the Startup shortcut and the watchdog (`hangeul_watchdog.log` 20:36 "not running - starting it") started the bot. Ollama was still starting, so the startup health check logged "Ollama not reachable at http://127.0.0.1:11434" twice (20:36:39, 20:36:44). The second copy found the first and stopped itself (20:36:47 "Application.stop() complete"), so the owner received the startup cheat-sheet twice.
- 20:51 owner: "fallback is offline?" Answer: no. Ollama answered seconds later with `qwen3:4b-instruct` ready. The LLM fallback affects only the brief's one-line summary and the wording of typed answers, never the commands that read the portal.
- **Offered, no answer yet:** wait up to 60 s for the AI at startup, and a watchdog grace period after boot (open item).

## 16. The release merge and the scope fix (30 Sep 20:54 → 21:47)

- **Go (20:54):** **"let's start uploading supabase"**. Plan, in the prompt's order: (1) merge `cloud/all` (built on `c17d887`) with today's main, a real merge and a re-check; (2) deploy with publishing OFF; (3) the real backfill; (4) an independent count check; (5) publishing ON.
- **Workflow** `wf_c194037b-cbc` (task `w07j1ddbg`, 2 agents, 20:55–21:42); worktree `C:\Hangeul\JARVIS\cloud\release`, branch `cloud/release` from `cloud/all`:
  - **`e5e532e` 21:04**, `git merge --no-ff main`. Text conflicts only in two import blocks (`parsers.py`: `urllib.parse` beside `bs4 … NavigableString, Tag`; `client.py`: `_label_key` beside `decode_cf_emails`). Meaning conflicts: `parse_consult_performance` decodes its whole soup with `decode_cf_emails` (the wrapped-soup count in `parsers.py` goes 12 → 13), main's `_decode_cf_emails`/`_cf_email` removed, `test_performance` uses `parsers._cf_address`; one date pin kept (`pin_today`; cloud's autouse `pinned_today` copies removed); a date-dependent test inherited from `cloud/all` pinned with `pin_job_clock` (`tests/test_cloud_jobs.py:456`). 1125 tests.
  - **`e4d1cea` 21:16**, the new kind **`consultant_performance`** (`records.consultant_performance`, `src/cloud/records.py:847`; `performance_complete` `:923`; `consultant_performance_batch` `:946`): one record per leaderboard row, key `<period>|<first ISO day>|<name>`, plus one summary per window, key `<period>|<first ISO day>|summary`; figures kept as printed; no student columns. Published by the performance commands (job `command`, after the reply) and by the hourly full picture (`backfill.collect_performance`, `src/cloud/backfill.py:294`, 2 GETs). 1150 tests; a guarded live dry run gave today 7 records and month 8, both complete.
  - **Preflight, 6 checks, all pass:** `main` fast-forwards to `cloud/release`; 1150 tests and byte-identical staging copies (R24); nothing lost from either parent; guarded dry run 4 (21:22:40, 1064 s: 615 calls, 15,614 chunks, 0 fillers or stand-ins, largest body 999,526 bytes; payloads in `C:\Hangeul\JARVIS\cloud\release\data\cloud\dry_run\20260930-212240-backfill-826ef04d\`); `/performance_*` and `/inquiries_today` live against its own reads; publishing OFF publishes nothing. Also found: `.env` had no `CLOUD_PUBLISH_ENABLED` line, and an empty value (`CLOUD_PUBLISH_ENABLED=`) makes `Settings` raise, so the bot would not start: write `true` or `false`, never nothing.
  - **Problem (low, fix before publishing on):** the scope was `<period>|<first>|<last>`, but the portal ends every period at today, so from 1 Oct the month scope would change every day. Deletes only look inside the call's own scope, so a consultant who dropped off the leaderboard would stay forever in an old scope (against D10). The backfill also did not read the page.
- **Fix `8317741` 21:45 (Claude):** `records.performance_scope` returns `"<period>|<first ISO day>"` (`src/cloud/records.py:823-830`); the last day stays in `day` and `data.range`; the backfill reads `consult_performance.php` for today and this month. 1152 tests on `cloud/release`; staging copies cmp-identical.
- **Deploy with publishing OFF:** `main` fast-forwarded `314afdb` → `8317741`. In `C:\Hangeul\BOT`: **1150 passed, 2 skipped by design** (`tests/test_cloud.py:893` and `tests/test_cloud_bot_jobs.py:620`: "this checkout has a .env (or Supabase settings in the environment): the child could publish"). Restart 21:47 (`cmd /c "C:\Hangeul\BOT\stop.bat" nopause`, then `wscript.exe C:\Hangeul\BOT\start_background.vbs`): 13 menu commands, 0 errors, no `data\cloud_state.json` yet.

## 17. The backfill, the postcheck, publishing on, the first automatic runs (30 Sep 21:48 → 22:44)

- **The real backfill (21:48:08):** from `C:\Hangeul\BOT`, `CLOUD_PUBLISH_ENABLED=true PYTHONIOENCODING=utf-8 .venv\Scripts\python.exe -m src.cloud.backfill > data\cloud\backfill_20260930.log 2>&1`: publishing on **in that process's environment only**, the bot itself still off (background task `blabnftop`). Its `hg_runs` row `backfill`: 21:48:09 → 22:05:13, status ok. "Done in 1025 s; 0 read(s) failed." **13,540 records and 15,629 chunks**, all upserted, 0 unchanged, 0 deleted:

| Kind | Records | Kind | Records |
|---|---|---|---|
| student | 340 | consultant_performance | 15 (today 7 + month 8) |
| student_export | 340 | doc_verdict | 2,717 (158 scopes) |
| student_progress | 340 | field_check | 3,490 |
| verification | 333 (57 day scopes) | doc_check | 158 |
| student_documents | 160 | field_correction | 0 |
| consultation | 1,034 (51 days, from 11 Aug) | report / report_section | 3 / 434 |
| consultation_day | 51 | doc_page_text | 3,469 |
| consultation_totals | 1 | passport_alert | 311 |
| pending_payment / window_application | 1 / 0 | passport_issue | 282 |
| dashboard_fact / calendar_item | 39 / 22 | **Total** | **13,540** |

  The log `C:\Hangeul\BOT\data\cloud\backfill_20260930.log` holds counts only. `data\cloud_state.json` now exists.
- **Independent postcheck:** workflow `wf_1387fada-bf6` (task `w9tx2ubg3`, 1 agent, 22:06–22:26; GETs only on Supabase, GET plus the login POST on the portal). Verdict **"verified"**, 6 of 6: (1) all 22 kinds equal its own reads by key set, 13,540 = 13,540 (the only change since was one consultation received at 22:12); (2) one `embed_model` on all 15,629 chunks; 669 sampled vectors are 384 finite floats with norm 1; 56 chunks re-embedded from their text gave cosine 0.99979–1.00048; (3) every record has chunks, 0 fillers, 0 Cloudflare stand-ins; (4) 30 random records, **388 of 388 fields equal**; (5) `hg_runs` has one ok backfill row whose counts equal the tables, and `hg_changes` 13,540 upserts and 0 deletes; (6) keyless and invented-publishable-key GETs get 401 (no real publishable key was available to test).
- **Publishing ON (22:27):** `CLOUD_PUBLISH_ENABLED=true` appended to `C:\Hangeul\BOT\.env` (line 43; `Settings` reads it back as True); restart 22:27:37. The startup line now ends ", Supabase full picture every 60m.", and the scheduler holds 7 jobs (`run_full_picture` added).
- **The first automatic runs** (watched by the background poll `wait_runs.py`, task `bbnty9wt3`): **22:35:26–22:35:33 `full_picture`** ok: 3 sent and upserted (the 22:12 request, 30 Sep's day counts and the all-time totals), 779 unchanged, 0 deleted, 0 failed reads, about 7 s (`hangeul_bot.log` 22:35:34 "Full picture publish finished (exit 0)"); **22:43:14–22:43:15 `portal_sync`** ok: 0 upserted, 976 unchanged. Supabase publishing is live. Left for the Jeannie side: the data key `blank_on_portal` and the kinds `doc_check` and `consultant_performance` (open item).

## 18. This refresh of the pack (30 Sep 23:38–)

- Owner (23:38): "refresh the reference pack". Workflow `wf_2c62f85f-036` (task `w477hcn5y`): seven writers move every file from `c17d887` to `8317741` and add [Files: src/cloud](03d_FILES_src_cloud.md) and [Supabase publishing](13_SUPABASE_PUBLISHING.md); then a synthesis (00, 01, 09, 12), two critics (accuracy; coverage and leaks) and a fixer; `secrets\bot.env` and `secrets\token.json` are re-copied.
- 23:45: a screenshot from the owner showed Jeannie saying she could not count today's consultancies, although the data had been published at 22:35: Jeannie does not use the `hg_*` data yet ([Open items](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md) B26). Her old `hangeul-bridge.ts` calls portal JSON endpoints the portal does not have, so it serves demo data.
- 23:46: the text of the owner's Jeannie screenshot shows the HUD row "ACCESS 보안 KEY REQUIRED": since 29 Sep ("ACCESS: OPEN", §10.2) Jeannie has been put behind the single `JEANNIE_ACCESS_KEY` (her spec's D8; no Supabase Auth login) ([11 B8](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).
- 23:48: the owner answered "Yes, build it here (Recommended)" to building Jeannie's side of her spec (§5-§9). Workflow `wf_1a222cb1-960` (task `wj3vsplug`) builds it in the worktree `C:\Hangeul\JARVIS\jeannie-hg`, branch `saem/hangeul-context-reader`, from `origin/main` `f7bbdca` (the local clone stays at `31202e9`), with Node.js v22.23.3 unpacked to `C:\Hangeul\JARVIS\tools\node\` (no system install). In progress and unmerged when this pack was refreshed; nothing is pushed until the owner grants write access.
- 1 Oct about 01:52: a usage limit interrupted the work. The Jeannie build was resumed as task `wc4a2hc5m`, and this refresh as task `wnaquruor`, with only the accuracy critic and the fixer re-run.

---

## Appendix A — all 48 commits

Rows 1–28 lead to `c17d887` (the first pack). Rows 29–48 are the Supabase branches (`cloud/*`, from `c17d887`) and the performance branches (from main), in commit-time order; `e5e532e` joins the two lines, so `main` is no longer linear (`git log --graph --oneline c17d887..8317741`). "merge" = a merge commit; the other counts are `git show --stat`.

| # | Hash | Time (+06) | Subject | Files changed |
|---|---|---|---|---|
| 1 | `366dec0` | 27 Sep 05:22 | Baseline: GitHub snapshot of hangeul-bot as downloaded | 71 |
| 2 | `f74e45d` | 05:23 | Downgrade the two known-false FAIL rules to FLAG before the cold start | 2 |
| 3 | `c5c1a7c` | 05:23 | Refuse all Telegram users when no admin chat ID is configured | 2 |
| 4 | `a012bcb` | 05:30 | Pin requirements to the versions proven on this PC, torch-first | 1 |
| 5 | `4154aa5` | 05:53 | Make every data location configurable, defaulting beside the bot folder | 18 |
| 6 | `053efc5` | 05:53 | Make launchers self-locating and pin them to the bot's venv | 13 |
| 7 | `d659983` | 06:21 | Build the OCR reader with verbose=False so its first download cannot crash | 1 |
| 8 | `03ccf15` | 06:43 | Audit every student in phase 3, not 78 of 326 | 2 |
| 9 | `b0245df` | 14:37 | Rewrite MIGRATION.md from the move that actually happened | 1 |
| 10 | `0fce479` | 20:00 | Redact the Telegram bot token from every log line | 1 |
| 11 | `d7a5817` | 20:00 | Add Jennie's voice: Telegram voice notes in, text and voice notes out | 9 |
| 12 | `e205327` | 20:19 | Redact URL-encoded bot tokens, and send unparseable LLM answers as plain text | 3 |
| 13 | `7241465` | 28 Sep 01:51 | Run the passport watcher's OCR off the event loop so the bot never goes deaf | 3 |
| 14 | `d9bbecc` | 01:51 | Make Jennie fast and conversational: instant filler, resident brain, memory | 10 |
| 15 | `cd0277a` | 11:24 | Read consultation requests by column name; the portal's new layout zeroed every count | 4 |
| 16 | `f8fefa4` | 13:51 | Factual daily brief: every figure counted from live portal reads | 13 |
| 17 | `e0d47ab` | 14:31 | Foundation: strict dates, long replies, one portal session, all-pages students reader | 9 |
| 18 | `46cdf03` | 15:00 | Inquiries: read each day with the portal's date filter, all-time from its tabs | 8 |
| 19 | `9dcd9ad` | 15:12 | Scheduled jobs and sheet reports: every page, no lost alerts, real stages | 13 |
| 20 | `40da0e6` | 15:18 | Cross-check and passport commands: pick students by their own verification stamp… | 7 |
| 21 | `7f42ad0` | 15:31 | Free text, Jennie and /calendar: whole-word routes to live reads, no LLM guesses | 11 |
| 22 | `65fdba1` | 15:34 | Merge fix/inquiries | merge |
| 23 | `638655b` | 15:34 | Merge fix/crosscheck | merge |
| 24 | `df021de` | 15:37 | Merge fix/freetext (conflict in `handle_natural_language_message`) | merge |
| 25 | `981d63d` | 15:38 | Merge fix/jobs (conflict in `tests/test_watcher_nonblocking.py`) | merge |
| 26 | `344a247` | 15:53 | Integrate the fix branches: merge leftovers, honest /alerts, every page for the last raw reads | 11 |
| 27 | `e164679` | 17:03 | Repair the verifiers' last cases: live progress pages, calendar ids, honest dates and OCR claims | 15 |
| 28 | `c17d887` | 17:45 | Last re-verify cases, and the brain on demand when the voice is off | 11 |
| 29 | `36ae72e` | 29 Sep 11:28 | Publish layer for Supabase: records, hash state, hg_sync, runs, handoff, backfill (`cloud/core`) | 15 |
| 30 | `a0572ba` | 11:30 | Write two invisible characters in the cloud code as chr() calls | 2 |
| 31 | `cfd10f1` | 11:33 | A complete key list for batches that carry only some records | 5 |
| 32 | `2b6798f` | 11:58 | Publish what the command handlers and free-text answers read, after the reply (`cloud/commands`) | 6 |
| 33 | `5048a07` | 12:02 | Publish the bot's own jobs to Supabase: the brief, the watcher, an hourly full picture (`cloud/inproc`) | 5 |
| 34 | `41055de` | 12:03 | Hook the sheet jobs into the Supabase publish layer (`cloud/jobs`) | 7 |
| 35 | `44c9378` | 12:05 | Merge cloud/jobs: the sheet jobs hand their reads to the Supabase publish layer | merge |
| 36 | `112325b` | 12:05 | Merge cloud/inproc: the brief, the watcher and the hourly full picture publish too | merge |
| 37 | `969f917` | 12:05 | Merge cloud/commands: command handlers and free-text answers publish what they read | merge |
| 38 | `cb16394` | 12:15 | Integrate the Supabase hooks: one tile record, the watcher's profiles and alerts | 6 |
| 39 | `3caa393` | 14:25 | Fix the review findings of the Supabase publish layer | 12 |
| 40 | `752cd53` | 15:26 | Fix the dry run's findings: portal fillers, one line a run, real CUDA hiding, body cap | 11 |
| 41 | `9ead47d` | 16:19 | Decode Cloudflare's hidden e-mail addresses; one log line for a missing model | 7 |
| 42 | `bbd8f98` | 21:41 | Team performance today and this month: /performance_today, /performance_month (`feature/performance`) | 9 |
| 43 | `a721066` | 30 Sep 10:29 | Performance report: honest last line, "this months", no stand-in month, other topics keep their routes | 5 |
| 44 | `ce23535` | 13:34 | Performance is the portal's Consultant Performance page, and only its data (`feature/portal-performance`) | 7 |
| 45 | `314afdb` | 14:04 | Performance: the owner's spelling, "performance" for another day, whole records, the real empty state | 7 |
| 46 | `e5e532e` | 21:04 | Merge main into cloud/release: the Consultant Performance page next to the Supabase layer | merge |
| 47 | `e4d1cea` | 21:16 | Publish the Consultant Performance page to Supabase: kind consultant_performance | 11 |
| 48 | `8317741` | 21:45 | consultant_performance: a scope that stays put all month; the backfill reads the page | 4 |

`git diff --stat c17d887..8317741`: 42 files, +12,641 / −133 lines (11 new files in `src/cloud/`, the new `src/bot/performance.py`, and 11 new files under `tests\`: `conftest.py` plus 10 test files).

Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Root staging copies (`telegram_bot.py`, `config.py`, `progress_builder.py`) are kept byte-identical to `src/bot/telegram_bot.py`, `src/config.py`, `src/sheets/progress_builder.py` (checked with `cmp` in every step).

## Appendix B — test count over time

| At | Tests passing |
|---|---|
| `d7a5817` | 29 (`tests/test_voice.py`) |
| `d9bbecc` | 141 |
| `cd0277a` | 145 |
| brief workflow | 179 → 234 at `f8fefa4` |
| `e0d47ab` | 336 |
| `46cdf03` / `9dcd9ad` / `40da0e6` / `7f42ad0` (each on base) | 375 / 373 / 408 / 446 |
| `344a247` | 607 |
| `e164679` | 651 |
| `c17d887` (first pack) | 659 (319 `def test_` functions in 14 files; the rest are parametrized cases); 6 of them fail on any date but 28 Sep (§10.3) |
| `cfd10f1` (`cloud/core`) | 720 |
| `41055de` / `5048a07` / `2b6798f` (each on core) | 746 / 750 / 758 |
| after the three merges / `cb16394` | 814 / 823 |
| `3caa393` / `752cd53` / `9ead47d` | 855 / 872 / 900 |
| `bbd8f98` / `a721066` (performance v1, from `c17d887`) | 724 / 775 |
| `ce23535` / `314afdb` (performance v2) | 813 / 884 |
| `e5e532e` (after the date-test fix) / `e4d1cea` | 1125 / 1150 |
| `8317741` (HEAD) | **1152** passed in the `cloud/release` worktree; in `C:\Hangeul\BOT` **1150 passed + 2 skipped by design** (a real `.env` is present). 604 `def test_` functions in 24 test files plus `tests\conftest.py` |

## Appendix C — bot restarts and workflow runs

Restarts: 27 Sep 11:46 (first start), ~20:02 (voice on), 20:19 (`e205327`), 23:49 (127.0.0.1); 28 Sep 01:51 (fast Jennie), 11:25 (`cd0277a`), 13:52 (`f8fefa4`), 17:08 (voice off), 18:06 (`c17d887`); 29 Sep 16:41 (the watchdog, after the unexplained stop at 16:36); 30 Sep 10:31 (`a721066`), 14:06 (`314afdb`), 20:36 (PC reboot; a duplicate started by the watchdog stopped itself at 20:36:47), 21:47 (`8317741`, publishing off), 22:27 (publishing on; still running at this refresh). Source: "Application started" lines in `C:\Hangeul\BOT\hangeul_bot.log` and "not running - starting it" in `hangeul_watchdog.log`.

| Task id | Run | Purpose | Agents |
|---|---|---|---|
| `wd9k5egdv` | — | Read-only audit of MIGRATION.md against code and PC | 9 |
| `wh481c6m5` | — | Configurable paths, self-locating launchers, adversarial review | 8 |
| `wzsoeis3s` | — | Kokoro / MeloTTS / Piper samples | 3 |
| `w7p17p6ni` | — | Chatterbox / CosyVoice realistic trial + Whisper CER | 3 |
| `w36pyqr2g` | `wf_a666ddfc-01c` | Build voice service + bot integration | 8 |
| `wpctxscrl` | `wf_41035b36-57f` | Small-LLM benchmark | 1 |
| `w3tpqg1ox` | `wf_eb5ed15e-d0e` | Fast Jennie + non-blocking watcher + latency harness | 9 |
| `wjgdmt14w` | `wf_5c2f1525-536` | Factual brief (died with the session, nothing written) | — |
| `wup29tzrh` | `wf_0a69c29b-8a0` | Command-accuracy audit | 7 |
| `wnhlel5f5` | `wf_29512f8c-a36` | Factual brief: implement, review, fix, verify | 5 |
| `wyjyqe0pz` | `wf_4b2a1e08-5c6` | All-commands fix | 11 |
| `w1vzele87` | `wf_2c5697c4-460` | First reference pack: 6 writers, synthesis, 2 critics, fixer | 10 |
| `wkuzhz3at` → `wwn0lrljq` | `wf_1eb48122-237` | Supabase publish layer: contract, inventory, core, 3 hooks, integrate, 3 reviews, fix, dry run 1 (4 agents lost to the network drop; resumed with the finished 7 cached) | 11 / 12 |
| `w02m6lyyu` | `wf_e7425917-377` | Dry-run 1 fixes (`752cd53`) + dry run 2 | 2 |
| `wd0c6zkf8` | `wf_3b282e15-484` | Cloudflare e-mail decoding (`9ead47d`) + dry run 3 | 2 |
| `w1188pjjm` → `w56wkwh83` | `wf_4b2e81a2-e8a` | Performance v1: build, live verify, review, fix (interrupted at the fix by the session end, resumed 30 Sep 10:12) | 4 |
| `wfp0dh5ak` | `wf_9efae077-816` | Performance v2: the portal's Consultant Performance page | 4 |
| `w07j1ddbg` | `wf_c194037b-cbc` | Release merge, kind `consultant_performance`, independent preflight | 2 |
| `w9tx2ubg3` | `wf_1387fada-bf6` | Independent post-backfill check of Supabase (read-only) | 1 |
| `w477hcn5y` | `wf_2c62f85f-036` | This refresh of the pack | — |

Background commands: `blabnftop` (the real backfill, 30 Sep 21:48–22:05) and `bbnty9wt3` (the poll for the first automatic `hg_runs` rows, 22:28–22:43).

Session-1 outputs: `C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Downloads-hangeul-bot-main-hangeul-bot-main\3b9b6ced-8eb2-4579-8655-1be5b8ddc988\tasks\`; session-2 outputs: `…\b90661d9-fc40-4a81-bd34-103e0decce24\tasks\` (copies of the audit and brief results in `C:\Hangeul\JARVIS\fix\audit\`).
