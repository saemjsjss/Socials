# 11 — Open items and known limits

**What's in this file:** everything still open on 30 Sep 2026 (HEAD `8317741`): what was closed since the first pack (29 Sep, `c17d887`), known limits in the code with their source lines, owner decisions still pending (including fixes offered and not yet answered), the deferred passport false-alarm fix with its planned design, the known limits of the Supabase publish layer and of the Consultant Performance commands, what the Jeannie side still has to learn, items that older notes still list as open but are already fixed, data-hygiene leftovers (the merged-but-not-removed worktrees and the dry-run folders that hold full student data), and the verification verdicts (the command audit, the performance checks and the Supabase checks).
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), at `main` = `8317741` (first written 29 Sep 2026 at `c17d887`).
**Read with:** [History](08_HISTORY_STAGE_BY_STAGE.md) (how each item arose; §8–§18 for everything since 29 Sep), [Supabase publishing](13_SUPABASE_PUBLISHING.md), [Files: src/cloud](03d_FILES_src_cloud.md), [Commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md), [Portal integration](04_PORTAL_INTEGRATION.md), [LLM and Jennie](06_LLM_AND_JENNIE_VOICE.md), [Environment](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md), [Tests and verification](10_TESTS_AND_VERIFICATION.md), [Blueprint rules](09_BLUEPRINT_RULES_AND_LESSONS.md), [Architecture](01_ARCHITECTURE.md), [Index](00_INDEX.md).

Line numbers are in `C:\Hangeul\BOT` at `8317741` unless marked "(at c17d887)" or "(at cd0277a)". Secret values are never shown: a secret is named as "value in secrets/bot.env (KEY)".

---

## A. At a glance

| # | Item | Kind | Owner of the next step | Severity |
|---|---|---|---|---|
| A2 | Done since the first pack | reference | — | — |
| B1 | Verification stamps carry no year | portal limit, handled | — (portal change needed) | low |
| B2 | `/verified_students` is a date alias | design leftover | developer | cosmetic |
| B3 | REST API: 500-row consultation page, HTTP 500 on portal failure, no auth; it now also returns real e-mail addresses | code leftover | developer (+ owner for `API_HOST`) | medium |
| B4 | `/stage` status and % | **resolved** in `e164679` (residual portal inconsistency) | staff | low |
| B5 | 6 students (14–15 Jul) verified but without a stamp | portal data gap | staff | low |
| C | Passport false alarm (one student, `<uid>`): fix designed, **deferred** by the owner | code | owner said "not now" | medium |
| B6 | Monitor cable on the RTX 5060 (GPU 15 % idle, 50 % peak with voice off) | hardware | owner | medium (only with voice on) |
| B7 | Credentials exposed in chat and old logs, including the Supabase access token; rotation **deferred by the owner** (D13) | security, accepted risk | owner | high |
| B8 | Jeannie's access model: one access key (`JEANNIE_ACCESS_KEY`), no Supabase Auth login, over full student data | security, **accepted risk** (29 Sep) | owner (do not re-raise) | — |
| B9 | "Jennie Call" web app | undecided idea | owner | — |
| B10 | Optional fp16 voice trial | undecided idea | owner | — |
| B11–B23 | Other leftovers found in code, audits and docs | mixed | see rows | mixed |
| B24 | Startup after a reboot: wait for Ollama; watchdog grace period (offered 30 Sep, no answer) | owner decision | owner | low |
| B25 | `progress_builder.clean_value` blanks Bangla-only cells in the Google Sheets | code | developer | medium |
| B26 | The Jeannie side must learn `doc_check`, `consultant_performance`, `blank_on_portal`, and does not use the `hg_*` data yet (its reader was approved 30 Sep 23:48 and is being built, unmerged, in `C:\Hangeul\JARVIS\jeannie-hg`) | other repo | Jeannie repo | medium |
| B27 | Known limits of the Supabase publish layer | design limits | developer / Jeannie side | low–medium |
| B28 | The 29 Sep 16:36–16:41 outage: cause unconfirmed | operations | operator | low |
| B29 | GPU history logger (offered 29 Sep, no answer) | undecided idea | owner | — |
| B30 | Consultant Performance commands: limits | design limits | developer | low |
| B31 | Portal data quirks the dry runs found (two e-mails for one student, addresses without a domain dot) | portal data | staff | low |
| F | Student data in scratch and dry-run folders (FULL student data in the Supabase dry runs) | privacy | owner's OK, then operator | high |
| H | Worktrees and branches merged but not removed (`C:\Hangeul\JARVIS\cloud\`) | hygiene | owner's OK, then operator | low |
| G | Verification verdicts: command audit, performance, Supabase | reference | — | — |

---

## A2. Done since the first pack (29 Sep 06:31 → 30 Sep 22:44)

| What | Where it is described |
|---|---|
| **Supabase publishing is live:** the `src/cloud/` layer (11 files) built, reviewed (21 issues, 18 fixed in `3caa393`; of the 3 declined, `read_at` and `calendar_item` are limits in B27, and the secrets README was done by Claude on 29 Sep 15:05), dry-run three times, merged with main, backfilled (13,540 records, 15,629 chunks, 0 failed reads), verified independently (22 kinds by key set, 388/388 fields), publishing on since 30 Sep 22:27, first automatic runs at 22:35 (`full_picture`) and 22:43 (`portal_sync`) | [History](08_HISTORY_STAGE_BY_STAGE.md) §10–§17, [Supabase publishing](13_SUPABASE_PUBLISHING.md) |
| The Jeannie migrations applied to project `dcbcbpwpmdtaanboetiz` (the owner's delegation, with the CLI) | 08 §10.5 |
| **The 6 date-dependent tests** fixed test-only: `tests/test_foundation.py:136` `pin_today(monkeypatch)` patches both `src.dates.local_today` and `src.bot.ask.local_today`; a 7th, inherited from `cloud/all`, pinned with `pin_job_clock` (`tests/test_cloud_jobs.py:456`). The suite passes on any date | 08 §10.3, §13, §16 |
| **Cloudflare e-mail stand-ins decoded** at every portal page parse (`src/scraper/parsers.py:64` `decode_cf_emails`); the bot's replies, the Supabase records and the REST API now show the real addresses; an undecodable one is blanked, never stored | 08 §12.3 |
| The portal's filler words ("N/A", "None", "--", "PENDING" outside a status field) blanked in the Supabase records and named in `data.blank_on_portal` (`src/cloud/records.py:230` `is_filler`) | 08 §12.2 |
| The consultation key in Supabase is the portal's own hidden id (was a sha1 fallback) | 08 §11 |
| **Performance commands** show only the portal's Consultant Performance page (the self-computed v1 is removed); the owner's spelling "performence" routes; the Telegram menu has **13 entries** (the startup log used to say "7" while there were 11: it now logs `len(commands)`, `src/bot/telegram_bot.py:2333`) | 08 §13–§14 |
| The inquiries report's day section is headed "📅 Consultations on <date>" (`src/bot/telegram_bot.py:498`; at `c17d887` it said "Performance on <date>", which read like the performance report) | 08 §14 |
| The new setting names are in `secrets\README.md` §3 (names only) and `secrets\bot.env` is re-copied | 08 §8 |
| The old PC's bot (deleted 28 Sep) and the old Telegram bot (deleted 29 Sep 22:06) are gone: @the_Jennie_bot is the only bot | 08 §12.5 |
| The GPU question answered with measurements (B6) | 08 §9 |
| The reference pack refreshed to `8317741` (this version) | 08 §18 |

---

## B. Known limits and leftovers

### B1. Yearless verification stamps

- **What:** `students.php` writes "Payment verified by NAME · 27 Sep, 17:19" with **no year** (all stamps seen were `DD Mon, HH:MM`, spanning Jul–Sep 2026).
- **How the code handles it:** `src/dates.py:245` `yearless_day_problem(day, today)` returns a reason (e.g. "the portal writes verification times without a year, so 27 Sep 2025 cannot be told apart from 27 Sep 2026") when the day's day+month has come round again since, or "a date in the future". `/verified_date`, `/crosscheck*` and the brief then answer **"not available"** instead of guessing. `stamp_on_day` (`src/dates.py:230`) also rejects a stamp dated before the student's "Applied On" date. The brief's `verified_day_problem` delegates to it. In Supabase, `verification` records are published per stamp day and are **complete only inside the one-year window** (`records.verification_window`, `src/cloud/records.py:564`); a day the stamps cannot tell apart publishes no verification at all.
- **Remaining limit:** once the portal holds more than a year of stamps (from about Jul 2027), a stamp from exactly one year earlier on the same day and month is indistinguishable from today unless the Applied-On check excludes it. The audit's derived "0" for 27 Sep 2025 was deliberately not adopted (fix workflow, foundation `not_fixed`).
- **Real fix:** the portal would need to print the year.

### B2. `/verified_students` is an alias

`src/bot/telegram_bot.py:2415` registers `CommandHandler("verified_students", verified_command)`: the same date-based report as `/verified`. The name suggests "all verified students"; it is not in the BotCommand menu. Left as is by the foundation fixer (changing it widens scope). Reports correctly for its date.

### B3. REST API (`src/api`, uvicorn on `API_HOST=0.0.0.0`, `API_PORT=8000`)

The Telegram commands were fixed; the API routes were not (fix workflow integration `leftovers`), and the Supabase work did not touch them.

| Route | File | Limit |
|---|---|---|
| `GET /applications/inquiries`, `GET /applications/consultations?date=` | `src/api/routes/applications.py` → `client.get_consultation_requests` (`src/scraper/client.py:269`) → `parsers.parse_consultation_requests` (`src/scraper/parsers.py:784`) | Reads the **unfiltered** `consult_requests.php`, which lists only the newest 500 requests (days older than ~3 weeks look empty); raw session (`self.client.get`, `client.py:276`, `:280`), not `portal_get`; any error (including an unreadable date, which raises `ValueError` in `normalize_target_date`, `parsers.py:576`) returns `[]` |
| `GET /applications` | → `client.get_applications` (`client.py:214`) | Raises `PortalUnavailable` when the list cannot be read; FastAPI turns it into **HTTP 500** (a 503 mapping was left to "whoever owns the API") |
| `GET /dashboard/alerts` | `src/api/routes/dashboard.py:15` | Reads `urgent_alerts`, which the live dashboard does not have → always `{"alerts": []}` (the Telegram `/alerts` was fixed in `344a247` to show the "Needs attention" card) |
| `POST /crawler/parse-page` | `src/api/routes/crawler.py` → `client.crawl_page` (`client.py:741`) | GETs **any** admin page with the bot's session; `parsers.parse_dashboard_metrics` (`parsers.py:183-231`) has **no `return`**, so `dashboard_summary` is always `None` |
| `POST /auth/login`, `GET /auth/csrf`, `GET /auth/status` | `src/api/routes/auth.py` | Relays a portal login POST |
| whole API | `run.py:79` (`uvicorn.Config(host=settings.API_HOST…)`) | Listens on every interface with **no authentication**. Since `9ead47d` every page it parses has its e-mail addresses decoded, so the API now returns **real addresses** where it used to show Cloudflare's stand-in. Owner **declined** changing `API_HOST` (grill decision 9); do not re-propose unless asked |

Unused: the pydantic `DashboardSummary` in `src/api/schemas.py:15` still declares int fields. The root debug script `get_consultations.py` also reads the unfiltered list, with the old fixed-column layout, so it is broken regardless (the Cloudflare fixer left it alone).

### B4. `/stage` status and progress % — resolved, with a residual

- That the status and % "still come from the CSV" was true at `344a247` (verifier: 89 of 329 % values and 64 statuses wrong; 46 students shown "Pending verification — 10/11%" although verified). **Fixed in `e164679`:** `src/sheets/stage_report.py:68` `read_progress(uids)` reads each student's own `progress.php?uid=N` (read-only GETs, 4 at a time, own session, stops once the portal stops answering), parsed by `parsers.parse_progress_page` (`.pg-ring`, `.pg-now .pg-stage` / `.pg-status`); the report says "Status and % from each student's own progress page (progress.php), read just now" (`stage_report.py:228`). Re-verify: 10 of 10 `/stage` cases correct. Since `41055de` the `/stage` button also hands its reads to Supabase (`student_progress`, never complete, plus a `stage_report:<KEY>:<INTAKE>|<day>` report); stdout is byte-identical with publishing on or off.
- **Residual (portal data):** for 4 students `progress.php`'s "Current stage" disagrees with the stage stored in the list (e.g. page "Documents Under Review", list "Documents Verified"). The bot buckets by the stored stage (what the portal's filter and dashboard count) and labels the line "progress page: <stage> · <status> — N%". Staff must fix the portal data.
- **Cost:** `/stage` logs in 3 times (CSV export, student list, progress pages) and takes 12–28 s, inside the 180 s subprocess limit (`_run_report_module`, `src/bot/telegram_bot.py:2215`, `asyncio.wait_for(…, timeout=180)` at `:2232`).

### B5. Six students from 14–15 Jul with no verification stamp

On 28 Sep the portal marked 329 students payment-verified but only 323 rows carried a "Payment verified by" stamp; 6 students from 14–15 Jul have none, so no date query (`/verified_date`, `/crosscheck_date`, the brief, the Supabase `verification` kind) can count them. On 30 Sep the postcheck counted 333 stamped rows among 340 listed students. A portal data gap, not a bot bug; staff can re-stamp them.

### B6. The monitor cable is on the RTX 5060

- Windows and apps (desktop ~0.8 GB, Chrome ~0.2, a camera app ~0.16, NVIDIA overlay, explorer, dwm) use **~1–1.4 GB of the 8 GB card** because the monitor is plugged into it. The Ryzen 5 8600G has an iGPU.
- **Measured 29 Sep 07:58** (08 §9): idle **1.2 GB (15 %)**; peak with voice off **3.9 GB (50 %)** (desktop + the brain's 2.8 GB while answering; the sync's GPU EasyOCR, ~2.4 GB, runs only when newly verified documents arrive); peak with voice on (27–28 Sep) **100 %**, with spill to system RAM.
- **Action (owner, physical):** plug the monitor into the motherboard's HDMI/DisplayPort. Frees ~1 GB+; the biggest single win if the voice is turned back on (brain 2.6 + voice 3.4 + STT 2.2 + desktop ~1.4 ≈ 8–9.8 GB vs 7.96 GB usable → spill → 25 s replies). Also a precondition for "Jennie Call" (B9). With voice off and the brain on demand, it matters only for voice. The Supabase embeddings run on the CPU (`CUDA_VISIBLE_DEVICES=-1`) and add nothing to the GPU.

### B7. Credentials exposed; rotation deferred by the owner

- **Exposed in chat and logs:** the portal password, the Gmail app password and the Telegram bot token were pasted into the session-1 chat (`3b9b6ced-…jsonl`, also copied into `b90661d9-…jsonl`); the old logs held the bot token **2,831 times** until `0fce479` (plus `%3A` copies until `e205327`), all scrubbed. On 29 Sep 10:31 the owner also pasted the **Supabase personal access token** in the session-2 chat (value in secrets/bot.env (SUPABASE_ACCESS_TOKEN)); it controls the whole Supabase account, not just this project. The project's secret key (value in secrets/bot.env (SUPABASE_SECRET_KEY)) was typed only into `.env`, never into chat.
- **Owner decision:** rotation is deferred (grill decision 3; the Supabase spec's D13, "accepted risk"), and on 29 Sep 10:31 the owner said "You don't need to suggest me that I need to rotate". Do not propose it again. The steps stay here for when the owner chooses: Telegram @BotFather → the bot → Revoke token (`TELEGRAM_BOT_TOKEN`); Google Account → Security → App passwords (`GMAIL_APP_PASSWORD`); the portal password via the portal administrator (`HANGEUL_PASSWORD`); Supabase Account → Access Tokens → revoke the `sbp_` token (the bot never reads it, only the CLI does, so it can simply be removed from `.env` between migrations); Supabase Project Settings → API Keys → a new secret key (`SUPABASE_SECRET_KEY` in `.env` line 40, and Jeannie's `SUPABASE_SERVICE_ROLE_KEY` on Vercel). Then update `C:\Hangeul\BOT\.env` and the copy in `REFERENCE\secrets\`, and restart the bot (`cmd /c "C:\Hangeul\BOT\stop.bat" nopause`, then `wscript.exe C:\Hangeul\BOT\start_background.vbs`).
- The reference pack contains the secrets as files (`secrets\bot.env`, `credentials.json`, `token.json`): share the pack without that folder.

### B8. Jeannie's access model (one access key; accepted risk)

`jeenie-saem-bot.vercel.app` (shown by the owner on 28 Sep as a demo with mock data, 08 §7.4) is **Jeannie**, the owner's assistant that reads the Supabase data (repo `munim430-ai/Jeenie-saem-bot`, clone at `C:\Hangeul\JARVIS\Jeenie-saem-bot`, which owns the `hg_*` schema). Its "HANGEUL BRIDGE" panel is configured with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Since 30 Sep 22:27 the bot publishes **full student data** there (D1: names, phones, e-mails, passport numbers, DOB, parents' names, addresses, the OCR text of documents).

- **28-29 Sep (history, 08 §10.2):** the app's HUD showed "ACCESS: OPEN" (no key, no login). On 29 Sep 09:18 the owner answered the options (upload only after a login; lock Jeannie first; mask the sensitive fields) with **"You don't need to worry about the fact that Jenny is public."**
- **30 Sep 23:46 (current):** the owner's screenshot of the live app shows the HUD row "ACCESS 보안 KEY REQUIRED": access is protected by the single **`JEANNIE_ACCESS_KEY`** (the Jeannie repo's `.env.example:16`; its spec `.scratch\hangeul-cloud-context\spec.md:26`, decision D8: "Protection stays the single `JEANNIE_ACCESS_KEY`. No Supabase Auth login."). There is no per-user login and no Supabase Auth; whoever holds the one key sees everything.

This is the owner's accepted risk: **do not raise it again**. What still holds: Jeannie's server needs the project URL and the secret (service) key, never the `sbp_` token; never put portal credentials into it; the access key's value is Jeannie's (on Vercel), never written into this pack.

### B9. "Jennie Call" (undecided)

A phone-call-like Jennie: a private web app hosted on this PC, reached from the phone over a private encrypted link (e.g. Tailscale), live two-way audio ~2–3 s after the speaker stops, interruptible, real portal data, all local. Needs brain + voice + ears loaded at once → only after freeing the GPU (B6). Alternatives offered: cloud realtime voice (student data leaves the PC), a real phone number (Twilio). The owner compared it with the Vercel app (B8); no decision. Voice is currently off (B12).

### B10. Optional half-precision (fp16) voice trial

Offered on 28 Sep 11:33 as option B for freeing 0.3–1 GB. CosyVoice's fp16 flag only enables autocast; the weights stay fp32, so a real saving needs a converted model and an ear check. Not started.

### B11. The last seven fixes of the command audit are unit-tested only

`c17d887` fixed the 7 cases the re-verify found partly wrong (no-digit mistyped date answers such as "tomorow"/"foo" closing the prompt; `SCAN_UNREADABLE` counted as "checked by OCR just now"; a sibling leaving and one joining with the same family mobile merged into a false sync edit; dated calendar answers silently dropping items marked done; the brief's/`/report`'s unlabelled verified total). Covered by `tests/test_final_fixes.py`; **not re-run against the live portal** (the 30 Sep preflight checked `/performance_*` and `/inquiries_today` live, not these).

### B12. Voice is off (fully built); the brain is loaded on demand

`.env` `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false`; task JennieVoiceWatchdog **Disabled**; `JennieVoice.lnk` in `C:\Hangeul\JARVIS\disabled\`; service stopped. Voice notes are ignored (the handler is registered only when enabled, `src/bot/telegram_bot.py:2429-2432`). The brain `qwen3:4b-instruct` is pinned only while `JENNIE_VOICE_ENABLED` or `BRAIN_ALWAYS_LOADED` (`src/config.py:75`) is true; otherwise it unloads after `BRAIN_IDLE_UNLOAD` = "5m" (`src/config.py:76`), and the `keep_brain_warm` job, still registered, returns at once. Re-enable voice: flip both flags, move the `.lnk` back to `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`, `Enable-ScheduledTask JennieVoiceWatchdog`, start `C:\Hangeul\JARVIS\jennie_voice\start_jennie_voice.vbs`, restart the bot (the brain is then pinned again, `ollama_client.brain_pinned()`). Known voice limits when back on:

- Tested only on synthetic voices; real noisy or Bangladeshi-accented speech untested.
- RAM tight: ~1.7–2.7 GB free of 16 GB with the service running (~5.5 GB working set); a Supabase publisher child adds about 1–1.6 GB while it embeds (1.05 GB peak for a batch of about 100 records, 1.57 GB for the whole backfill).
- The service loads CosyVoice code/weights and Whisper medium from `C:\Hangeul\JARVIS\voice-trials\cosyvoice\repo` and `…\voice-trials\whisper\hf_home` at run time: do not delete them.
- Spoken line caps `REPLY_MAX_CHARS = {"ko": 32, "en": 120}` (`src/bot/voice.py:65`); the filler clip's language follows the previous turn; Korean renders occasionally run long (re-render with another seed, 16–33 s).
- The sync's GPU EasyOCR (~2.4 GB) can squeeze TTS during a sync.

### B13. The passport watcher never surfaces "check by eye" results

By design the watcher alerts only on confirmed discrepancies and `MRZ_UNREADABLE`; results in `uncertain` (possible OCR misreads, failed check digits) are **remembered as audited and never shown** (verifier note (c)). A digest of uncertain scans would close this. (Audits made since publishing went on are published as `passport_audit` records whose result carries the `uncertain` list; earlier audit results were never stored on disk, so the backfill could not send them.)

### B14. Long cross-checks block typed commands

Date and range cross-checks have **no cap on OCR runs** (`/crosscheck 23 Jul 2026` = 62 OCR runs ≈ 10 min; a 92-day range could be ~300), and `CommandHandler`s use the default `block=True`; only the voice handler is `block=False` (`src/bot/telegram_bot.py:2429-2432`). Other typed commands wait meanwhile. (Name searches are capped at 10 students; `/passports` OCRs at most 5.) The Supabase hand-over after a cross-check runs in a worker thread and never adds to the wait.

### B15. OCR address comparison

`compare_address` (`src/scraper/ocr_validator.py:673`) counts a district-only hit as "✅ Match"; `parse_visual_text_lines` can miss an OCR-garbled "Emergency Contact" label, so garbage text is shown as the address and still "matches".

### B16. `/missing` can create a Drive folder (latent)

`missing_report.read_sheets` (`src/sheets/missing_report.py:109`, `pb.find_sheet` at `:115`) → `progress_builder.find_sheet` (`src/sheets/progress_builder.py:421-423`) → `_intake_folder` (`:405-418`), which **creates** the intake folder when missing: a Google write triggered by a read-only command, after which those students are skipped silently (the "X of Y" totals undercount). Not observed live. Fix: a lookup-only folder search in `read_sheets` and a line "no sheet yet for <intake> (N students)".

### B17. Cosmetic and small leftovers

| Item | Where |
|---|---|
| `/missing` and `/stage` lines end in `\r` (child stdout decoded without normalising `\r\n`) | `src/bot/telegram_bot.py:2233` (`_run_report_module`) |
| Cheat sheet lists "🔟 `/stage`" with no description | `src/bot/telegram_bot.py:308` |
| `/crosscheck_between <one date>` replies "I couldn't read two dates there" | `src/bot/telegram_bot.py:1891` |
| Bare `/consultations` and `/inquiries` ask for a date instead of answering for today (audit rated correct) | inquiries fixer `not_fixed` |
| Free text "cross-check <name>" (no number) asks for a date; `/crosscheck <name>` works | integration `leftovers` |
| `/sendmail` profile read (`client.get_student_full_profile`, `src/scraper/client.py:592`) uses the raw session; a failed page gives `{}` → "no email address on that record" instead of "couldn't read the portal" | integration `leftovers` |
| `/sendmail`'s list-page fallback docstring still says the list hides the address (Cloudflare's stand-in) and takes it from the edit page; since `9ead47d` the list already carries the real address. Behaviour is correct; only the text is stale (changing it means re-copying the root staging copy) | `src/bot/telegram_bot.py:1229-1234` |
| A failed `/calendar` default view gives no reason and does not mention the timeline; `/admitted`'s Universities breakdown shows the top 4 without saying so; "February has 29 days" for a yearless date | re-verify minor points |
| The LLM summary in the brief is strict by design: a true summary such as "2 payments worth 28,000 BDT were verified" can be dropped; some days have no summary line | brief fix `Limits` |
| `annotate()` in `page_checks.py` is dead code; `attendance.py` reads the office attendance sheet but is not wired into the 09:05 report (office start time and grace period never confirmed) | HANDOFF §5.2 |

### B18. Document-check rules (from HANDOFF and the grill)

- Solvency-vs-statement date and apostille "one qualification" are **FLAG** since `f74e45d`; they go back to FAIL only once proven against real documents (HANDOFF §8.1). The other two known-false rules of HANDOFF §5.1 (ID number differs between pages; opening balance below minimum) were already non-FAIL in the snapshot (the pre-grill audit found only these two still returning FAIL).
- Apostille subject mismatch (`page_checks.py:440`) is **dormant**: its data file `apostille.json` was lost with the old PC.
- "Page 1 of the academic file must be the e-Apostille" (`page_checks.py:403`) **stays FAIL** (decision 18): 47 files need re-assembly by staff (apostille first).
- HANDOFF §5.2 items still open: TIN taxpayer name unreadable for 17 students (TIN-vs-trade-licence rule cannot run); the FIELD CHECK "Corrections" sheet cannot tell a staff edit from a cache refresh (85 of 246 entries were the passport-issue refresh); one student is never checked because his portal record carries the head of branch's passport number (a staff edit on the portal fixes it); the passport seal-placement check is disabled (it flagged all 12 test passports).
- `data\verification\results.json` is the **only local copy** of the Corrections history: archive it outside `data\` before any clean start. (Its `corrections` list was empty on 29–30 Sep, so Supabase's append-only `field_correction` kind holds 0 records so far.)

### B19. Gaming shares the GPU (decision 14: no decision)

With EA SPORTS FC 25 open, OCR slowed from 1.8 s to ~17 s per A4 page; game (~3–4 GB) + EasyOCR (3.9 GB peak) + a resident brain exceed 8 GB, and an OOM during OCR can cache truncated text as final. A VRAM guard (postpone an OCR pass to the next 15-min tick when free VRAM is low) was offered; the owner replied "i won't play game right now, continue". Raise again before long-term use; never run a full re-check with a game open.

### B20. Konyang documents

No local `KONYANG DOCUMENTS` (`KONYANG_ROOT` absent; the verifier skips it). 41 student folders (473 files, 346 MB, last changed 21 Sep) stay in Google Drive under the bot's `PARENT_FOLDER_ID`, by the owner's choice (decision 16); 7 of the 11 at-risk students' Konyang files are gone for good. Restorable later: the verifier accepts the flat layout and the fresh verified copy wins (`setdefault`).

### B21. Repository and deployment

- **48 commits, local only**; `git remote` is empty; GitHub still has only the baseline snapshot. Push only when the owner asks and gives the URL. `main` now contains merge commits (the `cloud/*` merges and `e5e532e`), so `git log --graph` is the readable view.
- Autostart is logon-based (Startup `HangeulBot.lnk`, `Ollama.lnk`; task HangeulBotWatchdog every 5 minutes). Power-cut recovery relies on the BIOS "power on when AC returns" setting and Windows auto sign-in, both set by the owner; no UPS. The 30 Sep 20:35 reboot showed the Startup shortcut and the watchdog can both start the bot (the duplicate stops itself) and that Ollama can come up after the bot (B24).
- The scheduler holds **7 jobs**: 18:05 brief, 30-min watcher, 15-min sync, 09:05 missing report, 08:30 issue refresh, 10-min keep-warm (a no-op while the brain is on demand) and the hourly `cloud_full_picture` (registered always, `src/bot/scheduler.py:500-509`; a no-op while publishing is off, `run_full_picture` at `:369`).
- Publishing is on through the single `.env` line `CLOUD_PUBLISH_ENABLED=true` (line 43). Write `true` or `false`, never an empty value: `CLOUD_PUBLISH_ENABLED=` makes `Settings` raise and the bot will not start.
- Only the admin (`TELEGRAM_ADMIN_CHAT_ID`) is authorised; `TELEGRAM_AUTHORIZED_CHAT_IDS` is not in `.env`. Colleagues must press Start on @the_Jennie_bot and send their Telegram ids.
- The owner's `/stats` acceptance check after the first start (27 Sep) was requested; its result is not recorded.

### B22. Docs that are now stale

| Doc | Stale statement | Now |
|---|---|---|
| `README.md:3,15,102`, `MIGRATION.md:83` | model `qwen2.5:7b` | `.env` / `.env.example` use `qwen3:4b-instruct` (the 7B is still installed, unused) |
| `README.md`, `MIGRATION.md` | no word of the Supabase layer, its five settings, the hourly full picture, the backfill, or the performance commands | only `.env.example:106-118` documents the settings; this pack ([Supabase publishing](13_SUPABASE_PUBLISHING.md), [Commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md)) |
| `MIGRATION.md` §12 | "Passport watcher sends 3 alerts per run and marks the rest sent — Known, left as is" | fixed in `9dcd9ad` (every alert sent, marked only after Telegram accepts) |
| `MIGRATION.md` §11 | "18:05 Executive brief" | factual brief (`src/bot/brief.py`) |
| `.agents/rules/hangeul_operational_guardrails.md` rule 2 | "(Currently 0)" pending payments, "(Currently 2)" window applications | live values differ; the bot uses live values |
| same file, rule 7 | local copies in `E:\VERIFIED STUDENT DOCUMENTS` | `C:\Hangeul\VERIFIED STUDENT DOCUMENTS` (`DOCS_ROOT`) |
| `src/bot/telegram_bot.py:1229-1234` | the `/sendmail` fallback docstring on Cloudflare-hidden addresses | decoded at parse time (B17) |
| root `get_consultations.py` | reads the fixed-column consultation layout | broken since the 28 Sep layout change; unused (B3) |
| decision 9 (grill) | "portal re-login loop stays uncapped (`verified_docs.py:74-76`)" | the verified-documents list goes through the shared `read_student_pages` session path since `9dcd9ad` |
| memory note `hangeul-jarvis-plan.md` | the owner's performance correction "around 10:40" on 30 Sep | the transcript shows 13:11:47 (08 §14) |

### B23. Code hygiene checks

- `git grep` finds **no** `TODO`, `FIXME`, `XXX` or `HACK` in code (the only hits are the phone format `8801XXXXXXXXX` in `progress_builder.py`).
- **Tests:** 1152 at `8317741` (604 `def test_` functions in 24 test files plus `tests\conftest.py`; the rest parametrized). In `C:\Hangeul\BOT`: **1150 passed, 2 skipped by design**: `tests/test_cloud.py:893` and `tests/test_cloud_bot_jobs.py:620` skip when a real `.env` (or Supabase settings) is present, because their child process could publish. Other skip guards, which do not fire on this PC: `tests/test_cloud.py:1084` (the gte-small model not cached), `tests/test_cloud_cf_email.py:363` (no `sentence_transformers`), `tests/test_cloud_dry_run.py:258` (no torch). No `xfail`. `tests/conftest.py` forces publishing off in every test whatever `.env` says. The root `test_system.py`, `test_verified.py` are manual scripts, not part of the suite.

### B24. Startup after a reboot (offered 30 Sep 20:53, no answer)

On the 20:35 reboot the bot started before Ollama was up, so `run.py:48` `check_ollama_status` (called at `run.py:76`) logged "Ollama not reachable at http://127.0.0.1:11434" (`src/llm/ollama_client.py:118`, `:183`) twice, and anything needing the LLM in those seconds used the fallback. Both the Startup shortcut and the watchdog (`watchdog.ps1`, task HangeulBotWatchdog) started a copy; the duplicate stopped itself, but the owner got two startup messages. Offered fixes: (1) wait up to 60 s for Ollama at startup; (2) a watchdog grace period of a couple of minutes after boot. Waiting on the owner.

### B25. `progress_builder.clean_value` blanks Bangla-only cells in the Google Sheets

Found by the dry-run fixer (29 Sep): `clean_value` compares against ASCII characters only, so a cell written only in Bangla looks like "marks only" and is blanked in the progress sheets. The Supabase export no longer uses it (it uses `records.is_filler`, which keeps Bangla text), but the 15-minute sheet sync does. Not fixed: outside that task, and changing `src/sheets/progress_builder.py` means re-copying its root staging copy (R24). Worth a separate, tested fix.

### B26. What the Jeannie side still has to learn (and Jeannie does not use the data yet)

The Jeannie repo owns the schema (D12), so these are hand-overs, not bot changes:

- **New kinds** beyond the spec: `doc_check` (key = passport, scope `all`; the student-level document verdict) and `consultant_performance` (scope `"<period>|<first ISO day>"`, keys `<period>|<first ISO day>|<name>` for each leaderboard row and `<period>|<first ISO day>|summary` for the tiles and top performer; `day` = the range's last day; figures as printed; no student columns). "Who is top" is the summary's `top` or the row with `top=true`.
- **New data key** `data.blank_on_portal`: the fields the portal left as a filler word, to be answered as "not given on the portal".
- **Contract points where the SQL won over the prompt:** `hg_sync` also returns `unchanged`; `hg_runs.counts` also has `older`; a same-hash row keeps its old `read_at`, so `read_at` means "last changed" and freshness ("as of HH:MM") must come from the newest `hg_runs.finished_at` of the kind's job; `field_correction` is append-only; `hg_runs.job` values include `full_picture` and `command`, which the spec's list lacks.
- **Observed 30 Sep 23:45:** a screenshot from the owner showed Jeannie saying she could not count today's consultancies, although every consultation and today's performance page were published at 22:35. Jeannie has no code that reads the `hg_*` data: her old `src\lib\agents\hangeul-bridge.ts` calls portal JSON endpoints that the portal does not have, so it serves demo data.
- **The reader build (in progress, unmerged):** at 30 Sep 23:48 the owner answered "Yes, build it here (Recommended)" to building Jeannie's side of the spec (its §5-§9). The work is workflow `wf_1a222cb1-960` (task `wj3vsplug`), in the worktree `C:\Hangeul\JARVIS\jeannie-hg`, branch `saem/hangeul-context-reader`, based on `origin/main` `f7bbdca` (PR #12); the local clone `C:\Hangeul\JARVIS\Jeenie-saem-bot` is still at `31202e9` (so the remote is known to be ahead of the clone). Node.js v22.23.3 (no system install) is at `C:\Hangeul\JARVIS\tools\node\node-v22.23.3-win-x64` and must be put on `PATH` for that worktree. Nothing is pushed or deployed until the owner grants write access and merges; check the branch's state with `git -C C:\Hangeul\JARVIS\jeannie-hg log` (its first commit, the `hg-embed` Edge Function, is `8a1bbd2`, 1 Oct 00:17).

### B27. Known limits of the Supabase publish layer

| Limit | Why / where | Effect |
|---|---|---|
| A `student_profile` of a student who left the portal is never deleted | each uid is its own scope; no helper walks `publish.known_scopes("student_profile")` against a complete student list | stale profiles stay until done by hand |
| No re-embedding after a model change | the content hash does not include the model; the publisher refuses to publish when `CLOUD_EMBED_MODEL`/`CLOUD_EMBED_REVISION` differ from `state["embed_model"]` (one log line) | a model change needs `hg_records` cleared on the Jeannie side and `data\cloud_state.json` deleted, then a backfill |
| `calendar_item` is never complete | `calendar.php` shows only this month and the next 45 days; the contract fixes the scope as `all` (declined review issue) | an event deleted on the portal stays in Supabase; a per-month scope from the page's `var EV` was suggested to the Jeannie side |
| `read_at` means "last changed" | the migration skips same-hash rows (declined review issue) | B26 |
| A failed upload of an already published passport's audit or documents is re-sent only when that student is next checked | the sync's catch-up covers only passports Supabase never accepted, at most `CATCH_UP_PASSPORTS = 6` a run (`src/cloud/sheet_hooks.py:48`) | Supabase can lag one check behind; a re-run of the backfill repairs it |
| `student_export` is complete only with its header and ≥ 90 % of the students the last whole list counted | `records.export_complete`, fed by `sheet_hooks.listed_students()` (`src/cloud/sheet_hooks.py:216`) | a short export is published as partial and deletes nothing (the safe direction) |
| Filler words inside longer texts are kept | only whole cells are blanked; e.g. consultation details "N/A" ~27, "None" 12, a details "Passport" answer "<text> / PENDING" | faithful to the portal's wording; a strict R1 regex over `content` still finds them |
| Evidence kinds are not blanked | `passport_audit` (form and result), `field_check.portal`, `doc_verdict`, `dashboard_fact` hold the evidence of a check or a reader-built label | a card label "Pending" stays |
| No retention for `hg_runs` / `hg_changes` | one `hg_runs` row per publisher run (~96 syncs, ~48 watcher runs, 24 full pictures, 1 brief a day, plus one per command that read something); the migration has no pruning | the tables grow; for the Jeannie side to decide |
| The gateway's real body limit was never measured | calls are capped at `MAX_BODY = 1_000_000` bytes (`src/cloud/publish.py:91`), at most `MAX_ROWS = 200` rows and `MAX_CHUNKS = 250` chunks | the backfill's 600+ calls of up to ~1 MB were all accepted |
| Extra portal load | the hourly full picture reads about 16 pages (7 `students.php` pages, pending, today's and yesterday's consultations, the totals tab, window applications, `index.php`, `calendar.php`, 2 performance pages) plus a login; it skips 18:00–18:10, 08:25–08:40, 09:00–09:10 and a running sync | GET only, off the sync's and the watcher's beat (first run 7.5 min after start) |
| Consultation key fallback | a row whose forms do not agree on one hidden id is keyed `sha1(name + contact + received)`, which changes when the name or contact is edited | a delete plus a new record instead of an edit (not seen: all 1,034 backfilled keys were portal ids) |
| Worktree dry runs cannot see a live sync | the backfill's lock and quiet-window check looks at `<BOT_ROOT>\data\auto_sync.lock` | a dry run from a worktree must watch `C:\Hangeul\BOT\data\auto_sync.lock` itself (as all four did) |

### B28. The 29 Sep 16:36–16:41 outage: cause unconfirmed

The bot's last log line was 16:36:21 with no error; the watchdog restarted it at 16:41:02 ("not running - starting it"). It coincided with dry run 3 and its verifier's live bot-command check; some agent transcripts mention kill/Stop-Process. The cause was never confirmed. Standing rule for agent prompts since: never stop, restart or kill a process the agent did not start.

### B29. GPU history logger (offered 29 Sep 08:02, no answer)

There is no continuous GPU log on this PC; history came from the voice service's 283 readings (27–28 Sep). A small per-minute logger of GPU memory and load, as a scheduled task, was offered for a proper record; to be set up only on the owner's word.

### B30. Consultant Performance commands: limits

- The page's real **empty state** was never seen live (no period was empty, and the Custom range form is never used): the parser accepts only `tr.pf-empty-row` or a lone `.pf-empty`. A different real empty state gives an honest "layout not recognised" reply, never zeros.
- The bot reads only `?period=today` and `?period=month`; This Week, All Time and a custom range are not read (the reply points to the page's own tabs).
- `build_performance_report` catches every exception from the reader (`src/bot/performance.py:296`), so a bug in the parser would be reported to the owner as "Couldn't read the portal … not available right now", with one log line and no traceback (low, from the v2 review; not fixed).
- The portal ends every period at today ("01 Oct – 02 Oct", then "01 Oct – 03 Oct"), which is why the Supabase scope holds only the first day (fixed in `8317741`). Past windows (each day's "today", each month) stay in Supabase as history by design.

### B31. Portal data quirks found by the dry runs

- 2 students show two different e-mail addresses on `students.php`: the Student cell (the same as the CSV export) and the details view (another). Supabase follows each source (`student.details.Email` vs `student_export.Email`), and `/sendmail`'s CSV path and its list-page fallback would pick different addresses for them. Staff should correct one.
- 9 consultation contacts hold an address typed without a dot in the domain; Cloudflare leaves such text visible, and it is kept as the portal shows it.
- Since the Cloudflare decoding, real e-mail addresses appear in the bot's replies (the `/sendmail` fallback, the inquiries report) and in the REST API (B3), where the stand-in used to show.

---

## C. Deferred: the passport false-alarm fix

**Case (28 Sep, from the first full watcher run after the deploy):** an alert "Passport No mismatch" for one student (`<uid>`); diagnosed with the diagnosis script in `C:\Hangeul\JARVIS\fix\scratch\final\`. MRZ line 2 was garbled: nationality read "AZ7" (should equal line 1's state "BGD"), the DOB and expiry check digits failed, but the passport-number check digit **passed by chance** (roughly 1 in 10). `ocr_validator._validate_passport_data` (`src/scraper/ocr_validator.py:767`) trusts `mrz["passport_no_ok"]` alone (`pass_ok`, line 799) and reports `MISMATCH` (lines 809-812). The printed page's number differs from the portal's by one character: a possible portal typo or a misread, to be checked by eye by staff. (Since publishing went on, the same alert also sits in Supabase as a `passport_alert` record.)

**Owner decision:** 29 Sep 04:57, "not now". Nothing was changed. `ocr_validator.py` is unchanged through `8317741`.

**Planned design:**

1. **No chance matches.** In `_validate_passport_data`, trust `passport_no_ok` only when line 2 is otherwise sane: the nationality (`_line2_at`/`parse_mrz_line2` → `"nationality"`, `ocr_validator.py:287`) equals line 1's issuing state (`parse_mrz_line1` → `"state"`, line 243), **or** at least 2 check digits agree (`"checks"`, the sum of `doc_ok, dob_ok, exp_ok, comp_ok`, line 291). Otherwise the field becomes `NOT_READ`: "couldn't read it reliably, check by eye" (into `uncertain`, no alert).
2. **Flag a near-match.** When the printed page's number (`visual_passport_no`) differs from the portal's by exactly one character, say which position and both characters, as a "check by eye" line rather than a mismatch.
3. **Name the document in the alert.** `scheduler._alert_block` (`src/bot/scheduler.py:91`) adds the scan's file name, its upload date (from `passport_<uid>_<unixtime>`) and a `view_doc.php` link, next to the existing `student_edit.php?id=<uid>` link.
4. **Re-check the alerts** with the new rule (the 31 alerts sent at 18:56 and 19:23 on 28 Sep) and report which still stand; the watcher's next complete run then corrects the `passport_alert` records in Supabase.
5. Tests: a synthetic line 2 with a bad nationality and failing DOB/expiry digits but a passing document digit must give `NOT_READ`, not `MISMATCH`; a clean line 2 with a different number must still give `MISMATCH`.

---

## D. Deliberate scope decisions (not bugs)

From the all-commands fix workflow (`wyjyqe0pz.output` `not_fixed` lists):

| Item | Reason given |
|---|---|
| `/verified_students` stays a date alias | optional in the audit; changing behaviour widens scope |
| A day a year or more back → "not available" (not the audit's 0) | consistent with the brief's yearless rule (B1) |
| 6 students without a stamp | portal data gap (B5) |
| API routes and `get_consultation_requests`/`get_inquiries` still on the 500-row page; API returns 500 on portal failure | outside the Telegram commands (B3) |
| Bare `/consultations`, `/inquiries` ask for a date | audit rated correct |
| `/crosscheck_between` with a single date | audit rated correct |
| Typed and spoken passport questions go to the live cross-check for the day (not `/passports`) | cross-check is live, handles any day and checks all of the day's verified students (`/passports` OCRs 5) |
| Portal's progress page vs stored stage for 4 students | portal data (B4) |
| No real GPU OCR run for the all-scans-checked header | to avoid competing with the live bot and the resident model; covered by a synthetic test |

From the Supabase build and its fix workflows (`wwn0lrljq`, `w02m6lyyu`, `wd0c6zkf8`, `w07j1ddbg`):

| Item | Reason given |
|---|---|
| `read_at` refreshed only when the hash changes | the applied migration's upsert skips same-hash rows; the SQL wins (B26) |
| `calendar_item` never complete | the contract fixes its scope as `all` and the page never shows every item; per-window scopes could delete live events if misjudged (B27) |
| Jobs hand over through `handoff.submit`, never `publish.publish` in-process | the subprocess jobs have CUDA loaded or never call `embed.prepare_process`, and embedding in-process would delay the `/missing` and `/stage` button replies |
| Bare `/calendar` publishes nothing | its legacy reader lacks the page's `var EV` list; publishing it would overwrite the hourly job's fuller records and flip hashes |
| `/students` publishes page 1 as partial; `/verified` publishes only the day's verifications; manual `/brief` and `/report` replies are not published (the scheduled 18:05 brief is) | the readers those commands share with the brief were not widened, to keep the 18:05 path unchanged |
| `/sendmail`'s legacy `get_student_full_profile` read is never published | it can carry `_csrf`; profiles come only from `_profile_fields`, which drops `_csrf` and `password` |
| No handoff FIFO ordering | the read-time rules make the order in which publishers get the lock irrelevant: an older complete read published later deletes and rolls back nothing |
| The pending-payment, window-application and calendar rows are not built from the brief's reads | the brief's readers return counts or parsed reminders, not whole rows; the hourly full picture publishes those kinds from whole reads |
| `consultant_performance` is not backfilled from history | the page shows only live periods; the backfill reads today and this month (since `8317741`) |
| `get_consultations.py` and the `/sendmail` docstring left alone | outside the parsers and the cloud package; the docstring needs a staging-copy re-copy (B17, B22) |

---

## E. Resolved items that older notes list as open

`/brief` ImportError (fixed `f8fefa4`); watcher "mark all, send 3" (fixed `9dcd9ad`); watcher blocking the event loop (fixed `7241465`); `/passports` static 10 Sep text and `AUDIT_REGISTRY` (removed `40da0e6`); naive `datetime.now()` vs `REPORT_TIMEZONE` noted by the inquiries auditor (now `src/dates.py:76` `local_today()` uses `ZoneInfo(settings.REPORT_TIMEZONE)`); the legacy-Markdown `[Program]` link problem (escaped in `46cdf03`); the 18:05 job's 1 s misfire grace (now `misfire_grace_time=600`, `f8fefa4`); `/alerts` always "No urgent alerts" (Telegram side fixed `344a247`; API side B3); `/stage` CSV status (B4).

Resolved since the first pack: the 6 date-dependent test failures (`pin_today`, A2); "/stage status and progress % still come from the CSV" in the memory note (fixed long before, `e164679`); the Cloudflare "[email protected]" stand-in in `/sendmail`'s fallback, the inquiries names and every other parse (`9ead47d`); the "7 exclusive bot menu commands" log line (13 now, logged by count); the secrets README missing the Supabase setting names (29 Sep 15:05); "whether the old bot and the Vercel demo were deleted is not recorded" (the old PC's bot and the old Telegram bot are deleted; the Vercel app is Jeannie, B8); the consultation records keyed by a sha1 fallback (the portal's hidden id since `3caa393`); the `consultant_performance` month scope that would have moved every day (`8317741`).

---

## F. Student data left in scratch and dry-run folders (delete after the owner's OK)

The auditors, verifiers and dry runs saved raw portal pages, scans, payloads and copies of the bot's data files to compare against the bot. They are outside the bot, were never opened for this pack, and should be deleted once the owner agrees (none of it is needed to run the bot; the live data is in `C:\Hangeul\BOT\data\` and in Supabase):

| Folder | Contents (as reported by the agent that wrote it) | Files now |
|---|---|---|
| `C:\Hangeul\JARVIS\cloud\all\data\cloud\dry_run\20260929-143923-backfill-1e3ac770\`, `…\20260929-153713-backfill-bbac263b\`, `…\20260929-162254-backfill-244bfaa8\` | the exact `hg_sync` bodies of dry runs 1–3: **FULL student data** (names, phones, e-mails from run 3 on, passport numbers, DOB, parents, addresses, OCR text of documents) | 594, 603, 603 (≈ 99 MB each) |
| `C:\Hangeul\JARVIS\cloud\release\data\cloud\dry_run\20260930-212240-backfill-826ef04d\` | dry run 4 (preflight): **FULL student data** | 617 (102 MB) |
| `C:\Hangeul\JARVIS\cloud\all\data\` and `C:\Hangeul\JARVIS\cloud\release\data\` (besides `dry_run`) | copies of `results.json`, the OCR text caches, `alerted_passport_issues.json`, `passport_issue.json`, the missing-information reports, `student_index.json` | 1,959 and 780 in all (306 MB and 111 MB with the dry runs) |
| `C:\Hangeul\JARVIS\cloud\scratch\` (`dryrun`, `verify`, `verify_cf`, `verify_release`, `postcheck`, review and fix folders) | harnesses and results; the agents reported counts, field names and masked text only | 28 MB in all |
| Session scratchpad `…\b90661d9-…\scratchpad\postcheck_cache\` | the postcheck's portal page and Supabase table caches (student data, never printed) | 60 MB |
| Session scratchpad `…\scratchpad\perf_live\`, `…\scratchpad\live\`; `C:\Hangeul\JARVIS\perf2\scratch\raw_*.html` | Consultant Performance pages and dry-run payloads: staff names and aggregate counts only, no student data | small |
| `C:\Hangeul\JARVIS\command-audit\inquiries\` (`snap_*.html`, `bot_get_*.html`) | consultation pages with phone numbers and emails | 24 of 39 files |
| `C:\Hangeul\JARVIS\command-audit\crosscheck\data\` | saved portal pages with student details | 15 |
| `C:\Hangeul\JARVIS\command-audit\free_text\raw\` | raw portal HTML | 13 |
| `C:\Hangeul\JARVIS\command-audit\critic\data\` | watcher truth rows (names, uids, upload times) | 6 |
| `C:\Hangeul\JARVIS\fix\scratch\verify-data-commands\data\missing_reports\missing_information_2026-09-28.xlsx` | captured report with mobile numbers | 1 |
| `C:\Hangeul\JARVIS\fix\scratch\verify-crosscheck-jobs\data\` | run outputs, watcher memory copies | 97 |
| `C:\Hangeul\JARVIS\fix\scratch\verify-freetext-voice\raw\` and `botroot\passports\` | portal HTML; 5 passport scans | 17 + 5 |
| `C:\Hangeul\JARVIS\fix\scratch\verify-reverify\raw\` (`t1`, `t2`, `figs`) and `botroot\passports\` | student pages, CSVs, progress data; 2 passport scans | 29 + 2 |
| `C:\Hangeul\JARVIS\fix\scratch\repair\raw\` | raw pages used by the repair step | 10 |

The frozen audit worktree `C:\Hangeul\JARVIS\command-audit\repo` (and its copied scans) is already removed. The two session transcripts contain pasted secrets (B7).

---

## H. Worktrees and branches merged but not removed

All six `cloud/*` branches are merged into `main` (`git branch --merged main` lists them) and their worktrees are clean apart from the git-ignored `data\` folders of F:

| Worktree | Branch | Head |
|---|---|---|
| `C:\Hangeul\JARVIS\cloud\core` | `cloud/core` | `cfd10f1` |
| `C:\Hangeul\JARVIS\cloud\jobs` | `cloud/jobs` | `41055de` |
| `C:\Hangeul\JARVIS\cloud\inproc` | `cloud/inproc` | `5048a07` |
| `C:\Hangeul\JARVIS\cloud\commands` | `cloud/commands` | `2b6798f` |
| `C:\Hangeul\JARVIS\cloud\all` | `cloud/all` | `9ead47d` (holds the dry runs 1–3) |
| `C:\Hangeul\JARVIS\cloud\release` | `cloud/release` | `8317741` (= `main`; holds dry run 4) |

The performance worktrees (`C:\Hangeul\JARVIS\perf\build`, `C:\Hangeul\JARVIS\perf2\build`) and their branches were already removed at each deploy. **Cleanup needs the owner's OK** (the folders hold full student data, F): delete the `data\` folders, then `git -C C:\Hangeul\BOT worktree remove C:\Hangeul\JARVIS\cloud\<name>` for each, then `git -C C:\Hangeul\BOT branch -d cloud/core cloud/jobs cloud/inproc cloud/commands cloud/all cloud/release` (`-d` succeeds because every branch is merged). Never touch `C:\Hangeul\JARVIS\Jeenie-saem-bot` (the Jeannie repo) or `C:\Hangeul\JARVIS\tools\supabase\` (the CLI) in this cleanup.

---

## G. Verification verdicts

Verdicts: **correct** (every figure matches an independent live read), **partly_wrong** (some figures or wording wrong), **wrong**, **broken** (crash, no answer, or an unusable message), **not_testable**.

### G1. Command audit, by run

| Run | Code | Cases | correct | partly_wrong | wrong | broken | not_testable |
|---|---|---|---|---|---|---|---|
| Audit (`wup29tzrh`) | `cd0277a` | 119 | 38 | 25 | 46 | 8 | 2 |
| Verify (`wyjyqe0pz` verdicts) | `344a247` | 191 | 164 | 17 | 9 | 0 | 1 |
| Re-verify (`wyjyqe0pz` reverify; scope + variants/edges) | `e164679` | 58 | 51 | 7 | 0 | 0 | 0 |
| After `c17d887` | — | the 7 partly-wrong cases fixed with unit tests only (B11) | | | | | |

### G2. Audit at `cd0277a`, by group

| Group | Cases | correct | partly_wrong | wrong | broken | not_testable |
|---|---|---|---|---|---|---|
| verified | 18 | 13 | 0 | 5 | 0 | 0 |
| inquiries | 17 | 2 | 10 | 4 | 1 | 0 |
| crosscheck | 23 | 4 | 4 | 10 | 5 | 0 |
| admitted / missing / stage | 24 | 14 | 3 | 7 | 0 | 0 |
| free text | 26 | 3 | 6 | 16 | 1 | 0 |
| critic (jobs, voice) | 11 | 2 | 2 | 4 | 1 | 2 |

Verify at `344a247`, by verifier group: data-commands 77 (68 correct, 9 partly wrong); crosscheck-jobs 53 (49 correct, 3 partly wrong, 1 not testable); freetext-voice 61 (47 correct, 5 partly wrong, 9 wrong).

### G3. By command (case counts: c = correct, p = partly wrong, w = wrong, b = broken, n = not testable)

| Command / job | Audit @ `cd0277a` | Verify @ `344a247` | Re-verify @ `e164679` | Main causes before → fix | Status at HEAD |
|---|---|---|---|---|---|
| `/verified_today` | 1c 1w | 3c | — | failure shown as "no payments" → `PortalUnavailable` + `portal_error_reply` (`e0d47ab`) | correct |
| `/verified_date` | 5c 4w | 14c 1p | 2c 1p | page 1 only, placeholder amount, year dropped → all pages, `yearless_day_problem`; prompt re-arm (`e164679`, `c17d887`) | correct (last case unit-tested) |
| `/verified` | 3c | 4c | — | Paid vs verified income shown as one → `parsers.payment_text` (`e164679`) | correct |
| `/verified_students` | 2c | 2c | — | alias | correct (alias, B2) |
| `/inquiries_today` | 1p | 2c | — | all-time from 500 rows → status tabs (`46cdf03`) | correct (live again in the 30 Sep preflight) |
| `/inquiries_date` | 7p 4w 1b | 11c 1p | 1c 1p | 500-row window, unanchored day regex, today for bad dates, expired session → date filter, strict dates, `portal_get` | correct (last case unit-tested); its day section is headed "Consultations on <date>" since `314afdb` |
| `/consultations`, `/inquiries` | 2c 2p | 4c | — | as above | correct |
| `/crosscheck` | 1c 2p 4w 2b | 17c 1p | 2c 1p | intake-option substring (48 vs 2), page 1, names as dates, OCR overclaim → stamp picking, all pages, strict query, `_ocr_note` | correct (last case unit-tested) |
| `/audit` | 1c 1w | 3c | — | page 1 only | correct |
| `/crosscheck_today` | 1c | 1c | — | latent substring bug | correct |
| `/crosscheck_date` | 3b | 7c | 1c | substring + "Message is too long" → stamps + `_send_blocks` | correct |
| `/crosscheck_range`, `_period` | 2p 3w | 6c | — | substring on "Applied On"/intake, page 1 | correct |
| `/crosscheck_between` | 1c | 1c | — | single date unsupported (B17) | correct |
| `/passports`, `/passport_audit` | 2w | 2c | 1c | static 10 Sep text → live read (`40da0e6`) | correct |
| `/admitted` | 1c 1p 4w | 7c 1p | 2c | ignored `?status=admitted`, shifted parser → stage filter in code (`e0d47ab`), `.stu-uni` (`e164679`) | correct |
| `/missing` (+ 09:05 report) | 6c 1p | 8c | — | university fields skipped → portal record (`9dcd9ad`) | correct |
| `/stage`, `/stages` | 7c 1p 3w | 6c 6p | 10c | CSV "Current Stage", then CSV status/% → list stage (`9dcd9ad`), `progress.php` (`e164679`) | correct |
| `/stats`, `/students` | not audited (fixed in `f8fefa4`/`e0d47ab`) | 4c | — | placeholders, shifted parser | correct |
| `/calendar`, `/events`, `/deadlines` | (via free text) 1w 1b | 5c 1p 6w (+ via free text 3c 1p) | 15c 1p (+ via free text 2c) | dead `div.ag-item` parser; same-title events merged; end date lost after a time; `/deadlines` name dropped → `ask.calendar_*`, `_cal_sub`, `_cal_id` | correct (done-items note unit-tested) |
| `/report`, `/brief` | (via free text) 2w | 4c 1p (+ via free text 1c) | 2p | LLM report invented facts → factual brief; unlabelled total | correct (label unit-tested) |
| `/performance_today`, `/performance_month` (+ `/perf_*`, `/performance`, free text) | new on 29–30 Sep | — | — | v1 self-computed (161 figures × 2 runs, 0 mismatches, but the wrong definition) → v2 the portal's page only (G4) | correct (608 comparisons, 0 mismatches at `ce23535`; preflight 36/36 and 42/42 at `e4d1cea`) |
| Free-text routes | 5c 3p 4w | 13c 1p | 2c | bare-substring routing → `ask.classify` whole words | correct |
| Free text → LLM agent / fallback | 3p 9w | 13c | — | placeholders, duplicated inquiries in prompt → fact picking only (`7f42ad0`) | correct |
| Voice (Jennie) | 1w | 11c 1p 3w | 8c | static passports route; brain's invented dates; "no pending payments" on a failed read → live cross-check, `_words_dates`, fixed failure sentence | correct; voice now **off** |
| Job: passport watcher (30 min) | 1c 1p 2w 1b | 5c | — | alerts lost (3 per run), page 1, bottom-30% MRZ crop, misreads as discrepancies → every page, grouped alerts, rotations, check digits | correct; **one passport false alarm (C)** |
| Job: portal sync (15 min) | 1c 1p 1w | 3c 1p | 1c 1p | "1 new + 1 removed" per verification, wrong header → `sheet_changes`, `_likely_same`, sibling rule | correct (sibling case unit-tested) |
| Job: missing-info report (09:05) | (in `/missing`) | 1c 1p | 2c | silent failure → one plain failure message, exit 1 | correct |
| Job: passport issue refresh (08:30) | 1n | 1c | — | PENDING key gave 12 students another's value; failed read emptied the cache | correct |
| Job: Supabase full picture (hourly, new) | — | — | — | — | first run 30 Sep 22:35 ok (G5) |
| Edge cases (long replies, expired session, portal down) | — | 2c | 2c | `reply_long`, `portal_get` | correct |
| Not covered by any group (critic's completeness list) | 1n | 1n | — | listed for completeness only | — |

Sources: `C:\Hangeul\JARVIS\fix\audit\audit_results.json` (= `…\b90661d9-…\tasks\wup29tzrh.output`), `…\tasks\wyjyqe0pz.output` (`verdicts`, `bad`, `repair`, `reverify`), and `C:\Hangeul\JARVIS\fix\audit\brief_workflow_results.json` (brief verify: 32 checks, 29 match; the 3 mismatches were the "all time" consultation line, relabelled before `f8fefa4`).

### G4. The performance commands

| Run | Code | What was compared, against an independent read | Result |
|---|---|---|---|
| v1 live verify (29 Sep 21:48) | `bbd8f98` | team totals and every person's figures: 161 figures per run, 2 runs (own session; 29 day reads, all 7 `students.php` pages) | 0 mismatches; review 7 issues (0 high) → `a721066` |
| v2 live check (30 Sep 13:35) | `ce23535` | 8 invocations (both commands, the aliases, free text): title, range, open tab, 4 tiles, top card, count badge, every row and column, tooltips | **608 comparisons, 0 mismatches**; review 9 issues (1 high) → `314afdb` |
| v2 live re-run after the fix | `314afdb` | both commands and free text "performence this month / today" | one GET each, same replies, valid Markdown |
| Release preflight (30 Sep 21:2x) | `e4d1cea` | today 4/4 tiles, 6/6 rows, 36/36 figures; month 4/4 tiles, 7/7 rows, 42/42 figures; the handoff payloads complete with the page's keys | match |

### G5. The Supabase publish layer

| Check | Code | Result |
|---|---|---|
| Dry run 1 (29 Sep 14:39) | `3caa393` | 21/21 kinds equal the independent reads; **R1 failed** (portal fillers); log flood, CUDA "", 1.98 MB body found |
| Dry run 2 (15:37) | `752cd53` | 21/21 kinds; the four fixes hold; **R1 failed** (Cloudflare e-mail stand-ins) |
| Dry run 3 (16:22) | `9ead47d` | checks a–l all pass: **ready** |
| Release preflight + dry run 4 (30 Sep 21:22) | `e4d1cea` | 6/6 checks pass; one low issue (the moving month scope), fixed in `8317741` |
| Postcheck of the real backfill (22:06–22:26) | `8317741`, live Supabase | **verified**: 22 kinds = 13,540 records by key set; one `embed_model` on 15,629 chunks; 0 fillers, 0 stand-ins; 388/388 spot-checked fields; `hg_changes` 13,540 upserts, 0 deletes; keyless access 401 |
| First automatic runs | `8317741` | `full_picture` 22:35 ok (3 upserted, 779 unchanged, 0 deleted, 0 failed); `portal_sync` 22:43 ok (0 upserted, 976 unchanged) |

Sources: `…\b90661d9-…\tasks\wwn0lrljq.output` (`reviews`, `fix`, `dry`), `w02m6lyyu.output`, `wd0c6zkf8.output`, `w56wkwh83.output`, `wfp0dh5ak.output`, `w07j1ddbg.output` (`integ`, `pre`), `w9tx2ubg3.output`, and `C:\Hangeul\BOT\data\cloud\backfill_20260930.log`.
