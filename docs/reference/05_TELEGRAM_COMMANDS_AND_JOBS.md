# 05 — Telegram commands, free-text router and scheduled jobs

**What's in this file:** every Telegram command and alias the bot registers (what it reads, its arguments and date handling, its reply format with a placeholder example, its failure messages), the 13-entry BotCommand menu and the pinned cheat-sheet, the performance commands (the portal's Consultant Performance page, with real example replies whose consultants are placeholders), the free-text router (`src\bot\ask.py` + `handle_natural_language_message`) and when the local LLM is used, the "which date?" prompts, every scheduled job with its trigger, time zone and output (including the hourly Supabase full picture), the long-message splitting with its Markdown fallback, and how every handler hands what it read to the Supabase publisher after the reply.
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), at `main` = `8317741` (first written 29 Sep 2026 from `c17d887`; the 20 commits between them are in [08](08_HISTORY_STAGE_BY_STAGE.md)).
Sources: `C:\Hangeul\BOT` at HEAD `8317741`: `src\bot\telegram_bot.py` (2437 lines; the root `telegram_bot.py` is a byte-identical copy), `src\bot\ask.py` (1411 lines), `src\bot\performance.py` (303 lines), `src\bot\brief.py`, `src\bot\scheduler.py` (515 lines), `src\bot\replies.py`, `src\dates.py`, `src\sheets\*.py`, `src\cloud\command_hooks.py`, `src\cloud\bot_jobs.py`, `src\cloud\full_picture.py`, `src\cloud\handoff.py`, `src\llm\ollama_client.py`, `hangeul_bot.log` and `hangeul_sync.log` (to 30 Sep 23:44), and the performance workflow results of 30 Sep (live runs whose replies are quoted in §5.15).
Sibling file: [Portal integration](04_PORTAL_INTEGRATION.md) (every page, parser and guard these commands rely on). Also: the code view of every handler in [03a](03a_FILES_src_bot.md), the Supabase publish layer in [13](13_SUPABASE_PUBLISHING.md) and [03d](03d_FILES_src_cloud.md), the LLM prompts and Jennie in [06](06_LLM_AND_JENNIE_VOICE.md), the sheet jobs in [07](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), the request flows and concurrency model in [01_ARCHITECTURE.md](01_ARCHITECTURE.md), and the pack index in [00_INDEX.md](00_INDEX.md).

Placeholders: `<student name>`, `<uid>`, `HNG-2026-<n>`, `<staff name>`. Figures in examples are aggregates of 28 Sep 2026 or invented small numbers. The performance examples (§5.15) are real replies of 30 Sep 2026 with every figure as the portal printed it; the consultants in them appear only as placeholders (`<consultant A>` … `<consultant F>`), and `Owner` is the owner's own account as the leaderboard names it.

---

## 1. Runtime

| Item | Value |
|---|---|
| Library | `python-telegram-bot==22.8` (`Application`, `CommandHandler`, `MessageHandler`, `CallbackQueryHandler`), `apscheduler==3.11.3` (`AsyncIOScheduler`) |
| Bot | `@the_Jennie_bot`; token: value in `secrets/bot.env` (`TELEGRAM_BOT_TOKEN`). (The owner deleted the old PC's bot on 28 Sep and the old Telegram bot, with its old token, on 29 Sep; `@the_Jennie_bot` is the only one.) |
| Start | `run.py`: `apply_telegram_dns_fix()` (`src\net_fix.py`: if the DNS answer for `api.telegram.org` is dead on this network, probe known Telegram IPs and override resolution inside the process; `TELEGRAM_API_IP` forces one, `TELEGRAM_DNS_FIX=false` disables), then `build_telegram_application()`, `async with app: app.start(); post_init(app); app.updater.start_polling()` beside `uvicorn` (`src.api.main:app`, `0.0.0.0:8000`) in one asyncio loop. Long polling, no webhook |
| Build | `build_telegram_application()` `telegram_bot.py:2367-2437`: `Application.builder().token(token).post_init(post_init).build()`; returns `None` (API only) when the token is empty or `your_telegram_bot_token_here` |
| Logs | `hangeul_bot.log` (INFO, `%(asctime)s [%(levelname)s] %(name)s: %(message)s`); subprocess jobs and every Supabase publisher process append to `hangeul_sync.log`. Secrets are redacted from log lines by the filter `_RedactBotToken` (`src\__init__.py:59-71`) calling `redact()` (`:52-56`) with `_SECRET_PATTERNS` (`:41-49`): the bot token (`bot\d{6,}(?::\|%3[Aa])[A-Za-z0-9_-]{30,}` -> `bot<token>`), `Bearer <x>` and `apikey: <x>` values, `sb_secret_...`, `sb_publishable_...`, `sbp_...` and JWT-shaped keys; attached to the loggers `httpx`, `httpcore` (and `.connection`, `.http11`, `.http2`, `.proxy`, `.socks`) and `hangeul.cloud` (`:76-79`) |
| State | per-user `context.user_data` (in memory, lost on restart): `awaiting_date_for`, `date_prompt_answer`, `override_text`, `override_date`, `override_query`, `crosscheck_date_only`, `email_flow` |

### 1.1 Authorization

`is_authorized(update)` (`telegram_bot.py:22-37`): the chat id must be in `settings.authorized_ids()` = `TELEGRAM_ADMIN_CHAT_ID` (`.env`: the owner's user id, value in secrets/bot.env (TELEGRAM_ADMIN_CHAT_ID)) plus any ids in `TELEGRAM_AUTHORIZED_CHAT_IDS` (comma/space/semicolon separated; not set on this PC). **If none is configured, everyone is refused** (logged "TELEGRAM_ADMIN_CHAT_ID is not set; refused chat N"); the old behaviour of binding the first sender was removed (`c5c1a7c`).

Refusal behaviour differs by handler:
* reply `⛔ Unauthorized access. Your Chat ID is: `<id>`` (Markdown): `/start` `/help`, `/report`, `/brief` `/dailybrief`, `/verified` `/verified_students`, `/passports` `/passport_audit`, `/calendar` `/events` `/deadlines`, `/sendmail` `/email` `/mail`, `/crosscheck` `/audit`, `/crosscheck_range` `/crosscheck_between` `/crosscheck_period`, `/performance_today` `/perf_today`, `/performance_month` `/perf_month`, `/performance`;
* silent (no reply): `/stats`, `/students`, `/pin` `/commands`, `/admitted`, `/inquiries_today`, `/inquiries_date`, `/inquiries`, `/consultations`, `/verified_today`, `/verified_date`, `/crosscheck_today`, `/crosscheck_date`, `/alerts`, `/missing`, `/stage` `/stages`, free text;
* inline buttons: `query.answer("Not authorized", show_alert=True)`.

Who receives what: the daily brief and passport alerts go only to `TELEGRAM_ADMIN_CHAT_ID`; the portal-sync summary, the document check and the 09:05 missing report go to `settings.brief_recipient_ids()` = `TELEGRAM_BRIEF_CHAT_IDS` if set, else every authorized id (on this PC: the admin only). The Supabase jobs send nothing to Telegram.

---

## 2. Every registered handler (`build_telegram_application`, `telegram_bot.py:2376-2433`)

| Command(s) | Handler | In BotCommand menu | Reads |
|---|---|---|---|
| `/inquiries_today` | `inquiries_today_command` | yes (1) | `consult_requests.php` day filter + status tabs |
| `/inquiries_date [date]` | `inquiries_date_command` | yes (2) | same, for the day |
| `/inquiries [date]`, `/consultations [date]` | `inquiries_command`, `consultations_command` -> `inquiries_date_command` | no | same |
| `/verified_today` | `verified_today_command` -> `verified_command` | yes (3) | `students.php`, every page |
| `/verified_date [date]` | `verified_date_command` -> `verified_command` | yes (4) | same |
| `/verified [date]`, `/verified_students [date]` | `verified_command` | no | same |
| `/crosscheck_today` | `crosscheck_today_command` -> `crosscheck_command` | yes (5) | `students.php` all pages + `student_edit.php` + `view_doc.php` + OCR |
| `/crosscheck_date [date]` | `crosscheck_date_command` -> `crosscheck_command` | yes (6) | same |
| `/crosscheck_range [start to end]`, `/crosscheck_between`, `/crosscheck_period` | `crosscheck_range_command` | yes (7) | same |
| `/crosscheck [date / uid / HNG id / name]`, `/audit` | `crosscheck_command` | no | same |
| `/passports`, `/passport_audit` | `passports_command` | no | `students.php` all pages; OCR of today's verified (max 5) |
| `/sendmail [id]`, `/email`, `/mail` | `sendmail_command` (+ `_handle_email_flow` via free text) | yes (8) | `students.php?export=csv` (fallback: all list pages + `student_edit.php`); local LLM; Gmail SMTP |
| `/brief`, `/dailybrief` | `brief_command` | yes (9) | the whole daily brief (section 7.1) |
| `/missing` | `missing_command` + `CallbackQueryHandler(missing_button, pattern=r"^missing:")` | yes (10) | Google progress sheets + CSV export (subprocess) |
| `/stage`, `/stages` | `stage_command` + `stage_program_button` (`^stage:`) + `stage_intake_button` (`^stagei:`) | yes (11) | CSV export, `students.php` all pages, `progress.php?uid=N` (subprocess) |
| `/performance_today`, `/perf_today` | `performance_today_command` (`telegram_bot.py:742-749`) | yes (12) | `consult_performance.php?period=today` (section 5.15) |
| `/performance_month`, `/perf_month` | `performance_month_command` (`telegram_bot.py:752-759`) | yes (13) | `consult_performance.php?period=month` |
| `/performance [today \| month \| other words]` | `performance_command` (`telegram_bot.py:762-777`) | no | the page for today or this month, as the words say; any other period is told what the commands cover (reads nothing) |
| `/report [date]` | `report_command` | no | the brief for that day |
| `/stats` | `stats_command` | no | `index.php` tiles |
| `/students` | `students_command` | no | `students.php` page 1 |
| `/admitted [query]` | `admitted_command` | no | `index.php` + `students.php` all pages |
| `/calendar [words]`, `/events`, `/deadlines` | `calendar_command` | no | `calendar.php` |
| `/alerts` | `alerts_command` | no | `index.php` "Needs attention" card |
| `/pin`, `/commands` | `pin_command` | no | nothing (sends + pins the cheat-sheet) |
| `/start`, `/help` | `start_command` | no | Ollama `/api/tags` health |
| any text that is not a command | `MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_language_message)` | — | depends on the route (section 6) |
| voice / audio | `MessageHandler(filters.VOICE \| filters.AUDIO, handle_voice_message, block=False)` **only when `JENNIE_VOICE_ENABLED`** (now `false`: the owner turned the voice off, [06](06_LLM_AND_JENNIE_VOICE.md)) | — | Jennie voice service (disabled) |

Unknown slash commands match no handler (`~filters.COMMAND` excludes them from free text), so they get **no reply**. (The code comment above the first registrations still says "Register the 6 official menu command handlers": a stale label.)

---

## 3. Menu, cheat-sheet and welcome

### 3.1 BotCommand menu (`post_init`, `telegram_bot.py:2314-2365`)

`application.bot.set_my_commands(commands)` with **13** `BotCommand` entries. The log line counts them: `Successfully set 13 bot menu commands (set_my_commands).` (every start since 30 Sep 10:31; before it the line was a fixed, stale "7 exclusive"). Telegram's `getMyCommands` showed the same 13 on 30 Sep. The first 7 are the numbered "official" date commands:

| # | command | description (exact) |
|---|---|---|
| 1 | `inquiries_today` | Total consultancy inquiries & how many done today |
| 2 | `inquiries_date` | Total inquiries & how many done (ask specific date) |
| 3 | `verified_today` | Total verified students today |
| 4 | `verified_date` | Total verified students (ask specific date each time) |
| 5 | `crosscheck_today` | Total crosscheck verified students live today |
| 6 | `crosscheck_date` | Total crosscheck verified live (ask specific date each time) |
| 7 | `crosscheck_range` | Total crosscheck verified live (ask start date → end date) |
| 8 | `sendmail` | Email a student (ask ID → subject → brief; AI writes it; you approve) |
| 9 | `brief` | Run today's full 6:05 PM operational brief now |
| 10 | `missing` | Progress sheet missing information (KLP / EAP / Bachelor's / Master's) |
| 11 | `stage` | Student stages — choose program → intake |
| 12 | `performance_today` | Today: the portal's Consultant Performance page: tiles, top performer, leaderboard |
| 13 | `performance_month` | This month: the portal's Consultant Performance page: tiles, top performer, leaderboard |

A failure is logged (`Failed to set bot menu commands: <e>`) and startup continues. The aliases `/perf_today`, `/perf_month` and `/performance` are not in the menu.

### 3.2 The pinned cheat-sheet (`get_commands_cheatsheet_text`, `telegram_bot.py:279-318`)

Sent with `parse_mode="Markdown"` and pinned:
* at every startup to `TELEGRAM_ADMIN_CHAT_ID` (`pin_chat_message(..., disable_notification=True)`; failures only logged at DEBUG), so every restart posts a fresh copy;
* on `/pin`, `/commands` or free text matching the pin route (`disable_notification=False`), followed by `📌 *Command Cheat-Sheet successfully PINNED to chat header! (PP Pin)* ...`, or, if pinning fails, `ℹ️ _Note: Command cheat-sheet sent. To pin it to the chat header, ensure the bot has 'Pin Messages' admin permission in this chat._`.

Content (verbatim structure):
```
📌 *HANGEUL ADMIN AI BOT — TELEGRAM MENU (PP PIN)*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Official Menu Commands:*

1️⃣ `/inquiries_today`
└ *Total consultancy inquiries & how many done today*

2️⃣ `/inquiries_date [date]`
└ *Total consultancy inquiries & how many done (ask specific date)*
  _Examples:_ `/inquiries_date 12 Sep 2026` or just `/inquiries_date`

3️⃣ `/verified_today`            └ *Total verified students today*
4️⃣ `/verified_date [date]`      └ ... (same example pattern)
5️⃣ `/crosscheck_today`          └ *Total crosscheck verified students from live data today*
6️⃣ `/crosscheck_date [date]`    └ ... (same example pattern)
7️⃣ `/crosscheck_range [start → end]`
└ *Total crosscheck verified live over a DATE RANGE (ask start & end date)*
  _Examples:_ `/crosscheck_range 1 Sep 2026 to 15 Sep 2026` or just `/crosscheck_range`
8️⃣ `/sendmail`  └ *Email a student — asks ID → subject → short brief; the AI writes it professionally,*
                  *then you approve with SEND / EDIT / DENY before it goes.*
9️⃣ `/missing`   └ *Progress sheet missing information — tap KLP / EAP / Bachelor's / Master's*
🔟 `/stage`     └ *Student stages — tap a program, then an intake*

1️⃣1️⃣ `/performance_today`
└ *Today: the portal's Consultant Performance page — tiles, top performer, leaderboard*

1️⃣2️⃣ `/performance_month`
└ *This month: the portal's Consultant Performance page — tiles, top performer, leaderboard*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 *Interactive Date Asking:*
Whenever clicking a date command from the menu without arguments, the bot will ask you for the date and automatically process your reply!

🔒 *Guardrail:* 100% Read-Only & Live Portal Verified (`students.php` only; Signed Students strictly excluded).
```
(`/brief` is in the BotCommand menu but not in the cheat-sheet, so the cheat-sheet numbers the performance commands 11 and 12 while the menu has them at 12 and 13; the handlers' docstrings say "Menu 12" / "Menu 13".)

### 3.3 `/start`, `/help` (`start_command`, `telegram_bot.py:39-76`)

Calls `ollama_client.check_health()` then replies (Markdown):
```
👋 *Welcome to Hangeul Admin Operational AI Bot!*

• *Status:* 🌐 *Live Mode* (Connected to hangeul.com.bd)      (or 🧪 *Mock Mode* (Offline Simulation))
• *Local LLM:* 🟢 Connected (qwen3:4b-instruct)               (or 🟡 Standby (Internal Engine))
• *Portal Target:* `https://hangeul.com.bd/admin`

⚡ *Official Menu Commands:*
1️⃣ `/inquiries_today` — ... 🔟 `/stage` — Student stages: choose program → intake
1️⃣1️⃣ `/performance_today` — Today on the portal's Consultant Performance page: tiles, top performer, leaderboard
1️⃣2️⃣ `/performance_month` — This month on the portal's Consultant Performance page: tiles, top performer, leaderboard

💡 *Natural Language Assistant:*
• _'Total consultancy inquires and how many were done today'_
• _'Total verified students today'_  • _'Crosscheck 12 Sep 2026'_  • _'Crosscheck student <uid>'_
```
An unauthorized sender gets `⛔ Unauthorized access. Your Chat ID is: `<id>`` (the way a new colleague learns their id). "Standby" also shows while Ollama is still starting (after the 30 Sep 20:35 reboot the bot and Ollama started together and the first health check failed).

---

## 4. Dates: how every command reads them

### 4.1 The one strict parser (`src\dates.py`)

`parse_user_date(text, today=None, *, prefer_past=False) -> date | None` reads: `today`/`today's`/`tonight`, `yesterday`, `day before yesterday`, `tomorrow`; `8 Sep`, `8th Sep`, `8Sep`, `8 September 2026`, `the 8th of September`; `Sep 8`, `Sep 8, 2026`, `September 8th 2026`; day-first numbers `08/09/2026`, `8-9-2026`, `8.9.26`, `08/09` (slash only, this year); ISO `2026-09-08`, `2026/09/08`. Month names count **only as whole words next to a day number** (so "Janan", "summary", "may I", "Kumar" are no dates, and "8 Sep" is never found inside "18 Sep"). A day without a year is this year; with `prefer_past=True` (every command) a day still to come this year means last year's. It returns `None` for no date, two different dates, or an impossible one ("31 Sep", "29 Feb 2026", "13/13/2026"): **never a stand-in day**.

`user_date_problem(...)` gives the reason for a reply ("31 Sep: September has 30 days", "it names more than one date (...)", "it names a month but no day of it", "there is no month in it", "there is no date in it"). `has_date_hint(text)` is True for a digit, a month name (not "may"), a weekday, or `week(s)/month(s)/year(s)/ago/last/previous/next/tomorrow/fortnight`. `local_today()` is today in `REPORT_TIMEZONE` (`Asia/Dhaka`). (`ask.py` imports `local_today` by name, so a test that pins the day must patch `src.bot.ask.local_today` too: `tests\test_foundation.pin_today`, `tests\test_foundation.py:136`, does both; the 6 date-dependent tests that passed only on 28 Sep use it since `bbd8f98`.)

`ask.date_window(text, today, *, forward=True, ...)` (`ask.py:266-365`) reads spans ("this week", "1 Sep to 15 Sep"...). Since `a721066`, a range read past-facing stays in one year: on 29 Sep, "1 Sep to 30 Sep" is 1-30 Sep 2026, not 30 Sep 2025 - 1 Sep 2026.

### 4.2 `normalize_date_input(text, strict=False) -> (portal "DD Mon YYYY", display "DD Month YYYY") | None` (`telegram_bot.py:88-106`)

1. `parse_user_date(text, today, prefer_past=True)`; a date -> it.
2. Else remove the command (`/\w+(?:@\w+)?`), punctuation and the filler words of `_DATE_FILLER_RE` (`telegram_bot.py:80-85`: report(s), consultation(s), consultancy, inquiry/ies, enquiry/ies, request(s), verified, verification(s), verify, student(s), payment(s), paid, crosscheck, cross check, audit, check, only, specific, date(s), day(s), for, of, on, in, at, the, a, an, and, to, by, please, pls, show, give, get, got, tell, me, us, how, many, much, were, was, is, are, be, been, did, do, does, done, has, have, had, their, there, total, list, who, what, which, number, count, all, any, brief, summary, daily, came, come, received, new).
3. If something is left and (`strict` or it has a date hint) -> `None` (the caller replies `date_error_reply`); if nothing is left -> **today**.

So `/verified` alone, "how many students were verified" -> today; `/verified_date foo` (strict) -> error; "verified on 31 Sep" -> error.

Where the text comes from decides `strict` in `verified_command` (`telegram_bot.py:872-884`): words routed from free text (`override_text`) are non-strict; a date given to a command (`override_date`, `context.args`, the message text) is strict.

### 4.3 Portal-side limits applied before reading

* `yearless_day_problem(day, today)`: a future day -> "a date in the future"; a day a year or more back -> "the portal writes verification times without a year, so 27 Sep 2025 cannot be told apart from 27 Sep 2026". Used by `/verified*`, `/crosscheck*`, `/crosscheck_range` (on the start day) and the brief. Reply: `ℹ️ *Verified students on <date>:* not available (<reason>).` / `ℹ️ *Cross-check for <date>:* not available (<reason>).`
* `/inquiries*`: a future day -> `ℹ️ *Consultancy inquiries on <date>:* not available (a date in the future).` (any past day works: the portal's own date filter).
* `/crosscheck_range`: more than 92 days -> `⚠️ That range is N days. Please keep it to about 3 months or less — OCR on many passports takes time.`; an end after today is cut to today and the title says `(today)`.
* Performance: only today and this month exist as commands (the page's own period links); any other day, span, month or period gets `ask.performance_other_reply` and nothing is read (section 5.15).

### 4.4 The "which date?" prompts

A date command sent with no argument stores `context.user_data["awaiting_date_for"] = <kind>` and asks. The next typed (non-command) message is taken as the answer by `handle_natural_language_message` step 1 (`telegram_bot.py:2001-2016`): it pops `awaiting_date_for`, sets `override_text = <the message>` and `date_prompt_answer = <kind>` (`DATE_PROMPT_KEY`, `telegram_bot.py:592`), and calls the command.

| kind | Asked by | Prompt (Markdown, exact) |
|---|---|---|
| `inquiries` | `/inquiries_date`, `/inquiries`, `/consultations`, a consultation question with "date"/"specific" and no date | `📅 *Total Consultancy Inquiries*` / `Please enter the *specific date* you would like to check:` / `(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)` |
| `verified` | `/verified_date` | `📅 *Total Verified Students*` / `Please enter the *specific date* to view verified students:` / same examples |
| `crosscheck` | `/crosscheck_date` | `📅 *Live Crosscheck Verified Students*` / `Please enter the *specific date* to cross-check verified students:` / same examples |
| `crosscheck_range` | `/crosscheck_range` | `📅 *Live Crosscheck Verified — Date Range*` / `Send the *start* and *end* dates, and I'll cross-check every student whose payment was verified in that window against their passport documents.` / `_Reply in one message, e.g.:_` / `• `1 Sep 2026 to 15 Sep 2026`` `• `2026-09-01 to 2026-09-15`` `• `1 Sep - 15 Sep`` |

(Code spans are never nested inside `_italics_`: legacy Markdown shows the backticks otherwise.) The performance commands never prompt: with no argument they read today (or this month).

**Re-ask** (`_ask_date_again`, `telegram_bot.py:595-604`): when the answer cannot be read and it was typed in answer to the prompt (`date_prompt_answer == kind`) and it looks like a date try (`has_date_hint`) or is one or two words ("tomorow"), `awaiting_date_for` is set again, so the next message is again read as the date. A whole new question does not keep it open. An active `/sendmail` flow (`email_flow`) takes precedence over a pending date prompt.

**Span of days asked of a one-day answer** (`ask.ONE_DAY_KINDS = ("inquiries", "verified", "passports")`, `ask.py:380`): the router sets `awaiting_date_for` (`passports` -> `crosscheck`) and replies `ask.one_day_reply(kind, window)` (`ask.py:760-767`):
```
📅 Verified payments are counted one day at a time, and you asked about this week (Mon 28 Sep – Tue 29 Sep 2026).
Please send the day you want (e.g. `28 Sep 2026`), or use /verified_date <date>.
```
(A passport question over a past span instead runs the range cross-check.)

**Date error reply** (`replies.date_error_reply(raw, command="", reason=None)`, `replies.py:147-156`):
```
⚠️ I couldn't read “31 Sep” as a date (31 Sep: September has 30 days).
Please send a date like `12 Sep 2026`, `yesterday` or `2026-09-12`, for example `/verified_date 12 Sep 2026`.
```
Range variant (`/crosscheck_range`): `⚠️ I couldn't read two dates there (<why>). Please send a *start* and *end* date, e.g. `1 Sep 2026 to 15 Sep 2026`.`

---

## 5. Command details

Common patterns: most commands first send a `⏳ _..._` "please wait" message, then **edit it into the first piece** of the answer (`reply_long(..., edit=status_msg)`); portal failures become `portal_error_reply(what, e)` (`replies.py:159-165`):
```
❌ Couldn't read the portal: students.php: the portal did not answer in time (ReadTimeout).
Verified students for 12 September 2026: not available right now. Please try again in a minute.
```
Portal text inside Markdown is escaped with `esc()` = `telegram.helpers.escape_markdown(str(v), version=1)`; inside `*bold*` a literal `*` is replaced by `∗` (`_bold_safe`). After the reply is sent, a handler that read the portal hands what it read to the Supabase publisher without waiting (`cloud.publish(reads)`, section 9); nothing in a reply depends on it.

### 5.1 `/inquiries_today`, `/inquiries_date [date]`, `/inquiries`, `/consultations`

* Code: `inquiries_today_command` (`:607-612`), `inquiries_date_command` (`:614-648`), `build_inquiries_report(target_date_input="today", strict=False, reads=None)` (`:534-569`), `_send_inquiries_report` (`:572-587`), `format_inquiries_report(on_day, totals, display_date, totals_error=None)` (`:464-531`).
* Reads: `admin_client.read_consultation_day(day)` (`consult_requests.php?status=all&from=D&to=D`) and `read_consultation_totals()` (`?status=file_opened` tabs). Always `strict=True` from these commands.
* Waiting text: `⏳ _Consulting live portal for today's consultancy inquiries..._` / `⏳ _Consulting live portal for inquiries (<date as typed, "_" removed, max 60 chars>)..._`.
* Output (`INQUIRIES_LOG_MAX = 10` log lines, `:439`; done = Consulted + File Opened; "No Answer / Other" = received - done - New). The day's heading reads **"Consultations on <date>"** since `314afdb` (it said "Performance on <date>", which now means the Consultant Performance page):
```
📞 *Consultancy Inquiries Report — 28 September 2026*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 *Overall Portal Metrics (all time, the portal's own status counts):*
• *Total Inquiries on Portal:* `999`
• *Total All-Time Done:* `797` (791 Consulted, 6 Files Opened)
• *Still New:* `8` | *No Answer:* `154` | *Wrong Number:* `40`

📅 *Consultations on 28 September 2026:*
• *Inquiries Received:* `5`
• *Inquiries Done:* `2`
   ├ ✅ *Consulted:* `2`
   └ 📁 *File Opened:* `0`
• *Pending / New:* `3`
• *No Answer / Other:* `0`
• *Consultations Handled by:* <staff name>: 2

📋 *Inquiries Log:*
*1. <student name>* \[Bachelor's Degree]
   └ ✅ Status: `Consulted` (by <staff name>) | City: Dhaka
*2. <student name>*
   └ ⏳ Status: `New` (assigned to <staff name>) | City: N/A
```
  Status emoji: Consulted ✅, File Opened 📁, New ⏳, anything else 📵. Who: `(by X)` only for a done row with a "Last updated by" name, `(last updated by X)` for another status, `(assigned to X)` when only the consultant is known. More than 10: `_...and N more inquiries received on <date>._`. None: `ℹ️ *No new consultation requests were recorded on <date>.*`. Counts but no rows: `ℹ️ The portal counts N requests on <date> but lists none of them.`. A list the portal cut off adds `(among the N the portal lists)` to the handled-by line. A request whose name is an e-mail address shows the decoded address (Cloudflare, [04 §1.4](04_PORTAL_INTEGRATION.md)).
* Failures: date -> `date_error_reply(raw, "/inquiries_date")` (and re-ask); future day -> "not available (a date in the future)"; day read fails -> `portal_error_reply("Consultancy inquiries for <date>", e)`; only the totals fail -> the report still goes out with `• All-time figures: not available (couldn't read the portal's status counts: <why>)`.
* After the reply: the day's requests, its counts, the totals and the report text go to Supabase (`consultation`, `consultation_day`, `consultation_totals`, `report "inquiries_report|<day>"`, `report_section`).

### 5.2 `/verified_today`, `/verified_date [date]`, `/verified [date]`, `/verified_students [date]`

* Code: `verified_command` (`:858-913`), `format_verified_students_report(verified_list, display_date)` (`:798-856`).
* Reads: `admin_client.get_verified_students(target_date=day)` = `read_verified_students(day, all_pages=True)`: every page of `students.php`, students picked by their own "Payment verified by NAME · 27 Sep, 17:19" stamp (see [04](04_PORTAL_INTEGRATION.md) section 3.3), with the stamp guard.
* Waiting: `⏳ _Gathering verified student records for <DD Month YYYY>..._`.
* Output:
```
✅ *Student Payment Verifications — 27 September 2026*
• *Total Students Verified:* `2`
• *Total Verified Revenue:* `৳ 28,000.00 BDT` (the sum of the verified income)

📋 *Verified Student Records:*
*1. <student name>*
   ├ 🎓 *Program:* KOREAN LANGUAGE PROGRAM (KLP)
   ├ 💰 *Payment:* `20,000.00 BDT Cash`
   └ 👤 *Verified by:* <staff name> (27 Sep, 17:19)
```
  Revenue source wording: "the sum of the verified income" / "the verified income, and the amount paid for the N row(s) that show no verified income" / "the sum of the amounts paid"; rows without an amount add `; the N with an amount on the portal, M without`; no amounts at all -> `not available (no amount on the portal rows)`. Payment shows `Paid X (verified income Y)` when the two differ. A missing field is `—`.
* None: `ℹ️ *No student payments were verified on <date>.*` (only after every page was read).
* Failures: date error (`/verified_date` examples, re-ask when answering the prompt), yearless/future day "not available", `portal_error_reply("Verified students for <date>", e)`.
* After the reply: the day's `verification` scope (complete when the yearless rule allows the day).

### 5.3 `/crosscheck_today`, `/crosscheck_date [date]`, `/crosscheck [...]`, `/audit [...]`

* Code: `crosscheck_command` (`:1924-1971`), `_crosscheck_query(raw, date_only=False)` (`:1517-1552`), `build_crosscheck_report(query, status_msg, reads=None)` (`:1745-1800`), `_crosscheck_run` (`:1803-1817`), `_audit_cards` (`:1621-1648`), `_format_crosscheck_results` (`:1675-1717`), `_send_blocks` (`:1720-1742`).
* `/crosscheck_today` sets `override_text="today"`, `crosscheck_date_only=True`; `/crosscheck_date` sets `crosscheck_date_only=True` (anything but a date -> date error, never a name search).
* Query kinds (after removing the command, punctuation and the words of `_CROSSCHECK_WORDS_RE` (`:1510`): cross-check forms, audit, check, verify/verified/verification, student(s), id, uid, no, number, for, of, the, a, an, info(rmation), detail(s), please, pls, show, me, give, tell, about, on, only, specific, passport(s), document(s), doc(s), father(s), mother(s), parent(s), address(es), name(s), dob, and, with, against, record(s), payment(s), his, her, their, live, data, who, is):
  `{"kind": "date", "day"}` (a readable date, or nothing left = today); `{"kind": "hng", "hng": "HNG-2026-<n>"}`; `{"kind": "uid", "uid": "<uid>"}` for `<uid>`, `#<uid>`, `student <uid>`, `id: <uid>`; `{"kind": "name", "name"}` for 3+ letters; `{"kind": "error", "reply"}` for an unreadable date or `⚠️ I need a date, a student ID or at least 3 letters of a name to cross-check, e.g. `/crosscheck 27 Sep 2026`, `/crosscheck <uid>` or `/crosscheck <name>`.` (the code's own examples use a real uid and first name; replaced here)
* Reads: `read_students()` (every page); date: `_stamp_guard` (`:1555-1568`) + `_verified_between(students, first, last)` (`:1571-1585`; by stamp, sorted by day and stamp time for ranges); uid/HNG: exact match; name: case-insensitive substring of the list name or details "Full Name", at most `CROSSCHECK_NAME_MAX = 10` (`:1506`) checked (the rest listed: `• ⚠️ N students match; the first 10 are checked below. The others: <name> (`<uid>`), ... Send `/crosscheck <ID>` for one of them.`). Then for each card `admin_client.audit_student_passport(uid, {"name", "dob", "passport_no", "passport_expiry"}, passport_file)` one after another (profile from `student_edit.php`, scan from `view_doc.php`, EasyOCR + MRZ check digits in a thread); `cloud.audited(card, result, form, profile_before)` keeps each whole result for Supabase. The waiting message is edited to `⏳ _Checking N passport scan(s) for <title> by OCR (about 10 seconds each)..._`.
* Waiting: `⏳ _Cross-checking student information, Father, Mother, DOB & Address against documents..._`.
* Output (one block per student; blocks never split across messages):
```
📋 *Verified Student Information Cross-Check — 27 September 2026*
• *Total Records Audited:* `2`
• _Read live from all 330 students on students.php; each scan was checked by OCR just now._

*1. <student name>* (ID: `<uid>` · `HNG-2026-<n>`)
   ├ 🎓 *Program:* KOREAN LANGUAGE PROGRAM (KLP)
   ├ 💰 *Payment:* `20,000.00 BDT Cash` (receipt ✅ uploaded)
   ├ 👤 *Verified by:* <staff name> (27 Sep, 17:19)
   ├ 🛂 *Passport Scan:* ✅ Uploaded
   ├ 📝 *Portal:* Pass `<passport no>` | Exp `<date>` | DOB `<date>`
   ├ 👨 *Father:* `<as read from the scan>` (✅ Match)
   ├ 👩 *Mother:* `<as read>` (✅ Match)
   ├ 🏠 *Address:* `<first 40 chars>...` (✅ Match)
   └ 🔍 *Audit Verdict:* ✅ 100% Match across All Fields (Name, DOB, Passport No, Expiry, Father, Mother, Address)
```
  No scan: `🛂 *Passport Scan:* ⏳ None uploaded (Passport Status: <portal value>)` and verdict `⏳ Pending Passport Scan (no scan uploaded on the portal)` (status `MISSING_DOCUMENT`, no OCR). Other verdicts: `⚠️ Discrepancy Found: ...`, `🔎 Check by eye: ...`, `✅ Match: Name, DOB`, `ℹ️ Not on the scan: ...`, `ℹ️ Blank on the portal: ...`, `🔎 MRZ not read: couldn't read the MRZ (the photo may be rotated or blurred, or it may not be a passport); please check the scan by eye`, `❌ Couldn't read the portal: <why>. The passport was not checked.`, `❌ Couldn't check this scan: <why>`. The OCR note is honest (`_ocr_note`, `:1661-1672`): "each scan was checked by OCR just now" only when all were; else "N of the M scans were checked by OCR just now, K could not be checked (see their cards)" or "no scan could be checked by OCR". Statuses not counted as OCR-checked (`_NOT_OCR_CHECKED`, `:1653`): `""`, `MISSING_DOCUMENT`, `PORTAL_UNREADABLE`, `OCR_UNAVAILABLE`, `ERROR`, `SCAN_UNREADABLE`.
* None: `ℹ️ *No payment-verified students found for <date> to cross-check.*` + `_(All N students on students.php were read live.)_` + examples; `ℹ️ *No student found matching ID `<uid>`* (all N students on students.php were read live).`; `ℹ️ *No student found matching Name `<text>`* (...)`.
* Failures: date error, yearless/future "not available", `portal_error_reply("Cross-check for <title>", e)`.
* After the reply: the whole list (`student`, `verification`), the audits (`passport_audit`) and each profile the audits read (`student_profile`).

### 5.4 `/crosscheck_range`, `/crosscheck_between`, `/crosscheck_period`

* Code: `crosscheck_range_command` (`:1854-1921`), `_parse_date_range(raw) -> (d1, d2, "DD Mon YYYY → DD Mon YYYY") | (None, None, None)` (`:1820-1851`).
* Separators: `to`, `until`, `through`, `thru`, `till`, `–`, `—`, `..`, `=>`, `->`; else ` - ` with spaces (not inside `2026-09-01`); else two ISO dates; else two `D Mon[ YYYY]` dates. Each side goes through `normalize_date_input(strict=True)`; reversed ranges are swapped.
* Waiting: `⏳ _Cross-checking every payment-verified student from <range> live against their passport documents… this can take a few minutes._`. Output as 5.3 with the title `01 Sep 2026 → 15 Sep 2026`; none: `ℹ️ *No payment-verified students found between <range> to cross-check.*`. Publishes as 5.3.

### 5.5 `/passports`, `/passport_audit`

* Code: `passports_command` (`:969-1009`), `format_passports_report(students, today_cards, display_date, read_at, today_problem="")` (`:918-966`), `PASSPORTS_OCR_MAX = 5` (`:915`).
* Reads every page of `students.php`; counts students with a `passport_...` file; for students verified today (by stamp) builds cards and OCR-checks the first 5 (`/crosscheck_today` checks all). A stamp-guard failure keeps the counts and says the "verified today" part is not available.
```
🛂 *Passport Scans — live from the portal (29 Sep 2026, 10:15)*
• *Students on the portal:* `330`
• *With a passport scan uploaded:* `301`
• *Without a passport scan:* `29`
   └ Passport Status: WILL APPLY `20`, not given `9`

📅 *Payment-verified today (29 September 2026):* `1`
*1. <student name>* (ID: `<uid>`) — ✅ scan uploaded
   └ 🔍 ✅ 100% Match across All Fields (...)

_Read live from all 330 students on students.php; each verdict comes from an OCR check of the scan made just now._
```
  No verification today: `ℹ️ No payment was verified today, so no scan was checked. Another day: `/crosscheck_date 12 Sep 2026`; one student: `/crosscheck <uid>`.` Failure: `portal_error_reply("Passport scans", e)`. Publishes the list and the (at most 5) audited cards.

### 5.6 `/report [date]` and `/brief`, `/dailybrief`

* `/report` (`report_command`, `:122-161`): `normalize_date_input(raw)` (non-strict; `/report` alone = today), waiting `⏳ _Gathering live portal records for <DD Month YYYY>..._`, `compose_daily_brief(day=...)`, sent with `send_brief_text` as replies, then the waiting message is deleted. A past day gets the title `📋 *HANGEUL BRIEF FOR 12 September 2026* — read 29 Sep 2026, 10:15 (Asia/Dhaka)`, section 4 "shown for today only", and its facts say "on the day". Failure: `❌ Failed to compile report: `<error>`` (sent without parse mode). Free text routes here only for "report / brief / summary / overview / recap / round-up" with no other subject.
* `/brief` (`brief_command`, `:163-185`): waiting `⏳ _Reading today's figures from the live portal (this usually takes 10 to 30 seconds)..._`, `compose_daily_brief()` + `_send_brief(context.bot, chat_id, text)`, delete the waiting message; failure `❌ Failed to compile brief: `<error>``. Format: section 7.1.
* Neither publishes to Supabase (only the scheduled 18:05 brief does, section 7.1).

### 5.7 `/stats`

`format_stats_report(dash)` (`:192-230`) from `get_dashboard()`: the tiles grouped as the portal groups them, with its own labels; sent with `reply_long`.
```
📊 *Hangeul Admin Quick Stats*

*Admissions flow*
• Open windows: `3`
• Draft windows: `0`
• Submitted apps: `0`
• Under review: `0`
• Docs to review: `44`
• Accepted: `3`

*Direct / legacy pipeline*
• Total students: `330`
• Pending payment: `2`
• Verified: `328`
• Docs to review: `11`
• Admitted: `0`

_Pending payment and Under review are separate figures._
```
Failure: `• Dashboard figures: not available (the portal dashboard could not be read).` (Mock mode prints the mock summary.) Publishes the tiles (`dashboard_fact`, partial: tiles only).

### 5.8 `/students`

`get_applications()` = `read_students(all_pages=False)` (page 1: the 50 newest); shows the first 8:
```
🎓 *Recent Student Applications:*

• 📝 *<student name>* (MARCH 2027)
  └ *Program:* KOREAN LANGUAGE PROGRAM (KLP)
  └ *Univ:* HANYANG UNIVERSITY | *Status:* `Application Received`
```
Emoji: ✅ if the stage contains "Approved"/"Admitted", ⏳ if "Review", else 📝. Empty: `ℹ️ The student list on the portal is empty.`. Failure: `portal_error_reply("The student list", e)`. Publishes page 1 as `student` (partial: page 1 is never the whole list, so it deletes nothing).

### 5.9 `/admitted [query]`

`get_admitted_students(query)` (stage from the dashboard's Admitted tile link, filtered in code over every page); `format_admitted_report(result)` (`:378-437`), roster max `ADMITTED_ROSTER_MAX = 12` (`:375`). Waiting: `🔍 _Retrieving admitted students live from portal..._`.
```
🎓 *Hangeul Portal — Admitted Students*
• *Admitted:* `3` — 3 of the 330 students on the portal are at the stage “Admitted / Completed” (every page of the student list read live)
• *Matching* “hanyang”: `1`
The dashboard's Admitted tile says 3 too.            (or ⚠️ The dashboard's Admitted tile says X, but the student list shows Y at that stage.)

📊 *Breakdown:*
• *Universities:* HANYANG UNIVERSITY (1)
• *Programs:* ...  • *Intakes:* ...

📋 *Student Roster:*
*1. <student name>* (`HNG-2026-<n>`)
   🏛 *Univ:* ... | *Prog:* ...
   📝 *Applications:* Applied: <University> · <Program>
   💳 *Pay:* `Verified` | *Intake:* MARCH 2027
```
None: `ℹ️ *No admitted students on the portal right now.*` + the "0 of the 330 students ..." line (on 28 Sep the real answer was 0). More than 12: `_...and N more._` + `💡 Tip: search by name, ID, university or program: `/admitted <query>``. Publishes the whole list it read (`result["listed"]`) and the tiles (`result["dashboard"]`).

### 5.10 `/calendar [words]`, `/events`, `/deadlines`

* Code: `calendar_command` (`:1095-1146`), `format_calendar_report(cal_data, filter_query=None)` (`:1014-1093`), `ask.calendar_query(text, today)` (`ask.py:1127-1144`), `ask.answer_calendar(q, reads=None)` (`ask.py:1395-1411`), `ask.calendar_answer(items, q, today)` (`ask.py:1317-1392`).
* `calendar_query` returns `CalendarQuery(window, deadlines, dhl, words, problem, default)`: `window` from `date_window(text, forward=True)` ("this week" = today to Sunday, "this month" = today to month end, a month alone = the coming one, "next 7 days", "on Friday" = the next one, "from 1 Oct to 10 Oct", "coming up"/"upcoming"/"soon"/"next" = from today on); `deadlines` for deadline(s)/due/closing/close(s)/last day/expir*/submit* by; `dhl` for dhl/shipping/shipment(s)/ship/courier/parcel(s); `words` = what is left after `_CAL_FILLER_RE` (`ask.py:1118`), month and weekday names (a university or program search, all words must match); `default` = nothing asked beyond the calendar. `/deadlines <words>` gets "deadlines" prepended when the words do not already say so; bare `/deadlines` is today's view.
* Bare (default): `get_calendar_events()` + `format_calendar_report` (does not publish):
```
📅 *Hangeul Admin Calendar & Deadlines*

⚡ *Reminders for today (11 items):*
1. *SEJONG DHL*
   └ 🗓️ DHL to send · `26 Sep–28 Sep`
2. *Jeonbuk National University - Application open*
   └ 🗓️ Application period · `21 Sep–02 Oct` — *4 days left*

📌 *Upcoming (15 on the 45-day timeline):*
• *1 Sep:* FAR EAST UNIVERSITY- APPLICATION OPEN (EAP PROGRAM) (`01 Sep – 09 Oct 2026`) — Closes in 11 days

💡 _Tip: Search any university or date, e.g. `/calendar Hanyang` or `/calendar 11 Sep`_
```
  Up to `CALENDAR_UPCOMING_MAX = 20` (`:1011`) timeline rows, then `_…and N more (search one: `/calendar Hanyang`, or a week: `/calendar next week`)._`; untitled entries: `_(N entries without a title were skipped)_`; unreadable page or layout: `ℹ️ Today's reminders are not available right now (the calendar page could not be read).`.
* With words: `ask.answer_calendar` over the merged items (not done ones), sorted by end date, max `MAX_CALENDAR_LISTED = 25` (`ask.py:42`); publishes the items it read (`calendar_item`, never complete):
```
📅 *Deadlines — this week (Tue 29 Sep – Sun 04 Oct 2026)*
• Deadlines still open: `2`
1. *Jeonbuk National University - Application open* — Application period — 21 Sep–02 Oct — closes Fri 02 Oct (3 days left)
2. *SEOUL TECH DHL* — DHL to send · Seoul National University of Science and Technology — due today (Tue 29 Sep)
_Not counted, marked done on the portal: <title> (due 22 Sep)._
_The next one after that: <title>, closes Fri 09 Oct (10 days left)._
_Read live from calendar.php: today's reminders, the 45-day timeline and the month's event list._
```
  Count labels: "DHL shipments still to send", "Deadlines still open", "Deadlines already passed", else "Calendar items"/"Deadlines"/"DHL shipments". None: `ℹ️ None on the calendar for <window>.`. Date problem: `date_error_reply(raw, "/calendar", problem)`. Failure: `portal_error_reply("The calendar", e)`.

### 5.11 `/alerts`

`alerts_command` (`:788-796`) = `ask.reply(update.message, ask.Route("dashboard", topic="attention"), "/alerts")`: the dashboard's live "Needs attention" card (the old reply was always "No urgent alerts": the live dashboard has no alert list). Publishes the dashboard facts.
```
⚠️ *Needs attention*
• Payment verification — Students waiting for payment approval (Needs attention): `2`
• Document review — Documents waiting for verification (Needs attention): `11`
• Rejected documents — Awaiting student re-upload (Needs attention): `14`
• Missing documents — Verified students who haven't submitted docs (Needs attention): `158`
_Read live from the portal dashboard (index.php) just now._
```

### 5.12 `/sendmail [id]`, `/email`, `/mail` (the only command with an outside side effect)

A per-user state machine in `context.user_data["email_flow"]` (`_handle_email_flow`, `:1354-1469`), driven by the free-text handler:
1. `step "id"`: prompt `✉️ *Send an email to a student*` / `Step 1 — which student? Reply with the *HNG number, ID, or name*:` / `` `HNG-2026-<n>`   ·   `<last digits>`   ·   `<name>` `` ... (an argument skips the prompt). Lookup `_find_student_for_email(q)` (`:1174-1184`): the CSV export (`_find_student_in_export`, `:1187-1226`: exact normalized HNG id, else the last 3+ digits, else a 3+ letter name substring of "Full Name"), falling back to every list page + `student_edit.php` for the email (`_find_student_on_list_page`, `:1229-1286`; `_pick_student_email`, `:1289-1309`, prefers a plain `email` field over guardian/parent ones and takes only text shaped like an address, so Cloudflare's `[email protected]` is never taken; since `9ead47d` the list page's address is decoded, [04 §1.4](04_PORTAL_INTEGRATION.md)). Not found: `ℹ️ No student found matching `<text>`. Send the *HNG number, ID, or name* again, or type *cancel*.` (stays on "id"); portal failure: `portal_error_reply("The student lookup", e)` + "Send ... again in a minute, or type *cancel*."; no email on record: `⚠️ Found *<name>* (<HNG>), but there is *no email address on that record*, so I can't send. Cancelled.`; found: `✅ Found *<name>*  ·  `<email>`` + `✍️ Now type the *SUBJECT* of the email.`
2. `step "subject"` -> `📝 Subject saved.` + asks for a short brief.
3. `step "brief"` -> `🤖 _Writing it professionally…_`; `_ai_write_email(brief, student, subject)` (`:1312-1351`) calls `ollama_client.generate_response(prompt, system=...)` (system prompt: a polite business email for the agency's manager, body only, a fixed sign-off with the manager's name and "Manager, HKLV", no invented facts). The Ollama-down fallback text is detected by its phrases and replaced by a template (`Dear <name>, <brief>, Please let us know if you have any questions. Thanks, <sign-off>`). Preview: `📧 *Draft ready — please review:*`, To, Subject, body, `Reply *SEND* to send it · *EDIT* to rewrite (you'll re-brief me) · *DENY* to cancel.` (chunked by `_chunk_message`, `:1492-1496`; each chunk falls back to plain text).
4. `step "confirm"`: `send`/`yes`/`confirm`/`ok`/`okay`/`send it` -> `_send_gmail([email], subject, body)` (`:1148-1171`) via `smtplib.SMTP_SSL("smtp.gmail.com", 465)` with `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` (values in `secrets/bot.env`) -> `✅ Email sent — sent from <address> to <email>` or `❌ Could not send: <why>`; `edit`/`rewrite`/`change`/`redo` -> back to "brief"; `deny`/`cancel`/`no`/`stop`/`quit` -> `❌ Denied — the email was not sent.`; anything else -> `Please reply *SEND*, *EDIT*, or *DENY*.`. `cancel`/`/cancel`/`stop`/`deny`/`quit` at an input step -> `❌ Cancelled — no email sent.`.
Nothing is sent without an explicit `send` / `yes` / `confirm` / `ok` / `okay` / `send it` reply at the confirm step, after the full draft was shown. `/sendmail` publishes nothing to Supabase.

### 5.13 `/missing` (inline buttons)

`missing_command` (`:2180-2189`) shows `📋 *Progress sheet — missing information*` / `Choose a program:` with one button per `MISSING_PROGRAMS = [("KLP", "🇰🇷 KLP"), ("EAP", "📘 EAP"), ("BACHELOR", "🎓 Bachelor's"), ("MASTER", "🎓 Master's")]` (`:2172-2177`), `callback_data="missing:<KEY>"`. A tap (`missing_button`, `:2192-2212`): `query.answer()`, `⏳ Checking <label> progress sheets…`, then `_run_report_module("src.sheets.missing_report", "--program", KEY)` (`:2215-2240`): a subprocess `python.exe -m ...` (the venv's console `python.exe` even when the bot runs under `pythonw.exe`; `cwd` = bot root; `PYTHONIOENCODING=utf-8`; `CREATE_NO_WINDOW`; timeout 180 s) whose stdout is the reply, sent as **plain text** split under the limit. Output (`missing_report.program_report`, live from the Google progress sheets' main tabs plus the CSV export for university fields):
```
📋 Missing information — KOREAN LANGUAGE PROGRAM (KLP)
(live from the progress sheets, 29 Sep 2026 10:20)
12 of 216 students have missing information.
University fields of KLP, EAP and Bachelor's students are read from the portal (those sheets have no university columns).

🗂 MARCH 2027 — 7 of 120 incomplete
• HNG-2026-<n> <student name> — 3 missing: Father, Mother, SSC GPA
⚠️ University fields not checked for 1 student(s) (not found in the portal export): ...
```
Failure (non-zero exit or empty output): `❌ Could not build the <label> report right now. Please try again in a minute.`; the module itself prints `❌ Couldn't read the progress sheets or the portal: <why>. ...` on a read error. After printing, the subprocess hands the report to Supabase itself (`sheet_hooks.after_missing_program`, `missing_report.py:314`; job `missing_report`); it never prints anything more, because its stdout is the reply.

### 5.14 `/stage`, `/stages` (inline buttons, two levels)

1. `📊 *Student stages*` / `Choose a program:` with `callback_data="stage:<KEY>"` (`stage_command`, `:2249-2257`).
2. Tap (`stage_program_button`, `:2260-2291`): `⏳ Loading <label> intakes…`, subprocess `src.sheets.stage_report --program KEY` prints JSON `[{"intake": "MARCH 2027", "count": 46}, ..., {"intake": "NONE", "count": n}]` (Direct students of that program from the CSV, sorted by year then month) or `{"error": why}`. Buttons `MARCH 2027 (46)` / `⚠️ No intake set (n)` with `callback_data="stagei:<KEY>|<INTAKE>"`. Errors: `❌ Couldn't read the portal: <why>.` + `Could not load <label> intakes right now. Please try again in a minute.`; none: `<label>: no students on the portal.`
3. Tap (`stage_intake_button`, `:2294-2311`): `⏳ Checking <label> <intake> stages…`, subprocess `stage_report --program KEY --intake INTAKE`: the stage of each student from the `students.php` "Stage · Applied" cell (matched by Student ID, else name + mobile), and status + % from each student's own `progress.php?uid=N` (4 at a time):
```
📊 Stages — KOREAN LANGUAGE PROGRAM (KLP) MARCH 2027
(live from the portal, 29 Sep 2026 10:22) — 46 students

• Payment Verified: 30
• Documents Under Review: 10
• ⚠️ Stage not found on the student list: 1

🔹 Payment Verified (30)
   HNG-2026-<n> <student name> — Verified — 22%
   HNG-2026-<n> <student name> — progress page: Documents Under Review · Submitted — 33%

Status and % from each student's own progress page (progress.php), read just now.
```
  Stage order: `STAGE_ORDER` (Application Received ... Admitted / Completed, Accepted), then unknown stages, then "not found". Unread progress pages: `⚠️ N of the M progress pages could not be read (<why>): those lines show no status or %.` The `--intake` run hands its reads and report to Supabase last (`sheet_hooks.after_stage`, `stage_report.py:258`; job `stage_report`).

### 5.15 `/performance_today`, `/performance_month` (+ `/perf_today`, `/perf_month`, `/performance [today|month]`)

**What it is:** the portal's own **Consultant Performance** page (Leads > Performance, `consult_performance.php`), for today or this month, and **only that page's data**: its 4 tiles, its top performer card and its whole leaderboard, as the portal shows them ([04 §3.10](04_PORTAL_INTEGRATION.md)). Nothing is counted by the bot. (The first version, `bbd8f98` + `a721066`, deployed 30 Sep 10:31, computed "performance" itself from consultations and verifications; the owner corrected the meaning at 13:11 the same day, and `ce23535` + `314afdb`, deployed 14:06, replaced it. History: [08](08_HISTORY_STAGE_BY_STAGE.md).)

* Code: `performance_today_command` (`telegram_bot.py:742-749`, "Menu 12"), `performance_month_command` (`:752-759`, "Menu 13"), `performance_command` (`:762-777`), `_send_performance_report(update, kind)` (`:718-739`); `src\bot\performance.py`: `waiting_text` (`:66-68`), `format_consult_performance(kind, page, today)` (`:218-244`), `message_pieces(text, limit=None)` (`:247-278`), `build_performance_report(kind, today=None, reads=None)` (`:281-303`).
* Unauthorized: `⛔ Unauthorized access. Your Chat ID is: `<id>``.
* `/performance [words]`: `route = ask.performance_route(" ".join(context.args), local_today())`; topic `today` (no words, or today) or `month` -> the report; anything else -> `ask.performance_other_reply(route)` and no read. So `/performance`, `/performance today` = today; `/performance month`, `/performance this months`, `/performance monthly` = this month.
* Reads: `admin_client.read_consult_performance(kind)`: one GET of `consult_performance.php?period=today` or `?period=month` (the page's own period links; its Custom range form is never used), refused unless the page says it shows that period (it falls back to This Month).
* Waiting: `⏳ _Reading the portal's Consultant Performance page (Today) live..._` / `(This Month)`.
* Sending: `message_pieces(report)` cuts the reply under `CHUNK_CHARS = 3900` **between whole records only** (a line indented by three spaces, or a blank line, belongs to the line above it, so a consultant's `*N. NAME*` line and its `├`/`└` figure lines, and the top performer's name and figures line, always travel together; joining the pieces with `\n` gives the text back; a record over the limit on its own falls back to `split_text`); each piece goes through `reply_long`, the first one editing the `⏳` message, a piece Telegram refuses as Markdown is resent as plain text. Live on 30 Sep each reply was one message (1,188 and 1,634 UTF-16 units); the test splits a 120-row leaderboard.
* Log: `Consultant performance month: read in 0.3 s, 7 leaderboard row(s); 1624 characters.` (the owner's `/performance_month` of 30 Sep 14:58); a failure logs `Consultant performance <kind>: not read (<why>)`.

**Reply format** (Telegram Markdown; every figure is the portal's, exactly as printed):
* header `📈 *Consultant Performance — Today*` / `— This Month*`, then `📅 Showing *<period label>* · <range as the page prints it>`; `ℹ️ The page notes: <scope note>` when the page has one (empty for the owner/admin);
* a `⚠️` range line when the page's range is not today (Today) or the 1st of this month to today or month end (This Month) in Dhaka: `⚠️ The page's range is <range>, but today in Dhaka is DD Mon YYYY: the figures are the portal's, for the range it shows.`;
* the rule `━━━━━━━━━━━━━━━━━━━━━━━━━━━━`, then each tile `<emoji> *<label>:* `<figure>`` (emoji by the label's first word: `consultanc` 🎧, `file` 📂, `conversion` 🎯, `doc` 📋, else `•`);
* `🏆 *<card label>:* <name>` and `   Score `x` · Conversion `x` · Files opened `x` · Consultancies `x`` (the card's own labels, in its order); no card: `🏆 *Top performer:* none shown on the page for this period.`;
* `🏅 *Leaderboard* (N consultants)` (N = the page's count badge), then for each row in the portal's order `*<rank>. <NAME>*` (+ ` 🏆 Top` for the crowned row) and every other column in the header's order, labelled with the header's own text, two per line (`   ├ ... · ...`, the last `   └ ...`); an empty value shows `(blank)`; an empty leaderboard: `• Nobody is listed for this period (the page says: “<empty-state words>”).`;
* `ℹ️ *Score:* <tooltip>` and `ℹ️ *Points:* <tooltip>` (the header titles, else the page's legend);
* `⚠️` lines where the page disagrees with itself: `⚠️ The page shows no top performer card, though its leaderboard lists N consultants.`, `⚠️ The page shows a top performer card but no one on its leaderboard.`, `⚠️ The top performer card names X, the leaderboard crowns Y.`, `⚠️ The top performer card and the leaderboard's top row differ on: score, conversion.`, `⚠️ The leaderboard's Consultancies add up to N, the Consultancies done tile says M.` (the same for Files opened and Docs Ready);
* footer `🔗 Read live just now, read-only, from the portal's Consultant Performance page (consult\_performance.php?period=<period>). <sort note>.` (the path as escaped text, not a code span, because the plain-text resend keeps an escaped underscore but would lose one inside a code span).
Markdown safety: portal text outside entities through `esc()`; inside `*bold*` a `*` becomes `∗` (`_bold_safe`, `performance.py:71-74`); inside a `code` span a backtick becomes `ʼ` (`_code`, `:77-79`).

**Real example, `/performance_today`, 30 Sep 2026** (the final live run of the build; the portal prints each consultant's name in capitals, shown here as `<consultant A>` … `<consultant F>`, one letter per person across both examples):
```
📈 *Consultant Performance — Today*
📅 Showing *Today* · 30 Sep – 30 Sep 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎧 *Consultancies done:* `5`
📂 *Files opened:* `1`
🎯 *Conversion (file open):* `20%`
📋 *Docs ready:* `0`

🏆 *Top performer · Today:* <consultant A>
   Score `2.3` · Conversion `100%` · Files opened `1` · Consultancies `1`

🏅 *Leaderboard* (4 consultants)
*1. <consultant A>* 🏆 Top
   ├ Score `2.3` · Conversion `100%`
   ├ Files Opened `1` · Consultancies `1`
   └ Points `1.5` · Docs Ready `0`
*2. <consultant B>*
   ├ Score `0` · Conversion `0%`
   ├ Files Opened `0` · Consultancies `1`
   └ Points `1` · Docs Ready `0`
*3. <consultant C>*
   ├ Score `0` · Conversion `0%`
   ├ Files Opened `0` · Consultancies `1`
   └ Points `1` · Docs Ready `0`
*4. <consultant D>*
   ├ Score `0` · Conversion `0%`
   ├ Files Opened `0` · Consultancies `2`
   └ Points `3` · Docs Ready `0`

ℹ️ *Score:* Balanced score = files opened × (0.5 + conversion) × program weight
ℹ️ *Points:* Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1

🔗 Read live just now, read-only, from the portal's Consultant Performance page (consult\_performance.php?period=today). Sorted by score, highest first.
```

**Real example, `/performance_month`, 30 Sep 2026** (same run; the tiles equal their columns' sums, e.g. 146+101+117+146+111+95+0 = 716, so no `⚠️` line):
```
📈 *Consultant Performance — This Month*
📅 Showing *This Month* · 01 Sep – 30 Sep 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎧 *Consultancies done:* `716`
📂 *Files opened:* `108`
🎯 *Conversion (file open):* `15%`
📋 *Docs ready:* `8`

🏆 *Top performer · This Month:* <consultant B>
   Score `17.9` · Conversion `18%` · Files opened `26` · Consultancies `146`

🏅 *Leaderboard* (7 consultants)
*1. <consultant B>* 🏆 Top
   ├ Score `17.9` · Conversion `18%`
   ├ Files Opened `26` · Consultancies `146`
   └ Points `148` · Docs Ready `1`
*2. <consultant D>*
   ├ Score `15.8` · Conversion `16%`
   ├ Files Opened `16` · Consultancies `101`
   └ Points `151` · Docs Ready `5`
*3. <consultant C>*
   ├ Score `15.6` · Conversion `19%`
   ├ Files Opened `22` · Consultancies `117`
   └ Points `120` · Docs Ready `0`
*4. <consultant A>*
   ├ Score `14.6` · Conversion `11%`
   ├ Files Opened `16` · Consultancies `146`
   └ Points `218` · Docs Ready `2`
*5. <consultant E>*
   ├ Score `14.1` · Conversion `18%`
   ├ Files Opened `20` · Consultancies `111`
   └ Points `115` · Docs Ready `0`
*6. <consultant F>*
   ├ Score `5` · Conversion `6%`
   ├ Files Opened `6` · Consultancies `95`
   └ Points `141.5` · Docs Ready `0`
*7. Owner*
   ├ Score `1` · Conversion `0%`
   ├ Files Opened `2` · Consultancies `0`
   └ Points `0` · Docs Ready `0`

ℹ️ *Score:* Balanced score = files opened × (0.5 + conversion) × program weight
ℹ️ *Points:* Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1

🔗 Read live just now, read-only, from the portal's Consultant Performance page (consult\_performance.php?period=month). Sorted by score, highest first.
```

**Another day, span, month or period** (`ask.performance_other_reply(route)`, `ask.py:508-526`; nothing is read), e.g. "performance yesterday":
```
📈 /performance\_today and /performance\_month show the portal's Consultant Performance page for *today* and for *this month*, and you asked about Tue 29 Sep 2026.
The page itself (Leads › Performance, consult\_performance.php) also offers This Week, All Time and a custom range: open it on the portal for those.
```
The "you asked about ..." part names the day (`Tue 29 Sep 2026`), the span (`this week (Mon 28 Sep – Wed 30 Sep 2026)`, `August 2026 (Sat 01 Aug – Mon 31 Aug 2026)`), the period by a readable name (`all time` for all time/overall/lifetime/ever/in total/altogether; `the year to date` for ytd; `this year`; `yearly figures`; `a quarter`; `weekly figures`; `a fortnight`; `the week to date` for wtd; `a custom range`; else the words as written, e.g. `2025`), or, for a date it cannot read, `(I couldn't read the date there: 31 sep: September has 30 days)`.

**Failures** (never zeros; `build_performance_report` never raises): `portal_error_reply("The portal's Consultant Performance page (Today)", e)`, e.g.
```
❌ Couldn't read the portal: consult\_performance.php?period=today shows 'This Month' instead of 'Today' (layout not recognised).
The portal's Consultant Performance page (Today): not available right now. Please try again in a minute.
```
Other reasons: the portal down or slow (`... did not answer in time (ReadTimeout)`), `HTTP 404`, a refused login, an unrecognised layout (`consult_performance.php: the leaderboard's header has no points column (it reads [...]) (layout not recognised)`, `... leaderboard row 1 is one cell that is not the page's empty state ...`), mock mode (`the bot is in mock mode, so there is no live portal to read`). An unexpected exception in the handler itself gives `❌ Error building the performance report: <why>`.

**After the reply:** the page read goes to Supabase as kind `consultant_performance` (one record per leaderboard row plus one summary, scope `"<period>|<first ISO day of the page's range>"`, e.g. `month|2026-09-01`, stable through the month because the portal ends every period at today; section 9 and [13 §5.9](13_SUPABASE_PUBLISHING.md)).

---

## 6. The free-text router

### 6.1 `handle_natural_language_message(update, context, query=None)` (`telegram_bot.py:1973-2170`)

Order of work:
0. Not authorized -> silent. `query` = the message text (a voice note passes its English words as `query`).
1. An active `/sendmail` flow (`email_flow`) -> `_handle_email_flow`.
2. A pending date prompt (`awaiting_date_for` popped) -> the command for it with `override_text` = the text (section 4.4).
3. `route = ask.classify(query, today)` and dispatch:

| Route kind | Action |
|---|---|
| `hello` | reply `ask.HELLO` (`ask.py:749-750`: "👋 Hi! I read the Hangeul portal live for you. Ask me things like “how many students were verified today”, “show pending payments” or “any deadlines this week”." + `CANT_ANSWER` list) |
| `pin` | `pin_command` |
| `performance` | topic `month` -> `performance_month_command`; topic `today` -> `performance_today_command`; no topic (another day, span, month or period, or an unreadable date) -> `ask.performance_other_reply(route)` (Markdown), nothing read |
| one-day kind with a span (`route.window`) | passports over a past span -> `/crosscheck_range` with "D1 to D2"; else set `awaiting_date_for` and reply `one_day_reply` |
| `inquiries` | a date problem -> `inquiries_date_command` (it replies the date error); no day but "date"/"specific" -> the prompt; no day or today -> `inquiries_today_command`; another day -> `inquiries_date_command` with that day |
| `crosscheck` | a two-date range in the text -> `crosscheck_range_command`; a past window ("cross-check last week") -> range; the named day today -> `crosscheck_today_command`; another named day -> `crosscheck_date_command`; no student words (`_CROSS_FIELD_RE` or a 2-5 digit number) and a date hint -> `crosscheck_date_command` (date error); nothing -> the date prompt; else `crosscheck_command` with the text (id / HNG / name) |
| `passports` | date problem -> `crosscheck_date` (error); no day or today -> `crosscheck_today`; other day -> `crosscheck_date` |
| `verified` | today -> `verified_today_command`; a day or a problem -> `verified_date_command` with the text; "date"/"specific" -> the prompt; else `verified_command` with the text (no date = today) |
| `admitted` | strip question words (show, list, who, which, is, are, students, admitted, how many, to, in, at, for, ...); what is left becomes `override_query` -> `admitted_command` ("who is admitted to Hanyang?" -> "hanyang") |
| `missing`, `stage`, `stats` | `missing_command`, `stage_command`, `stats_command` |
| `calendar` | `calendar_command` with `override_text` = the text |
| `report` | `report_command` with `override_text` = the text |
| `applied` with a date problem | `date_error_reply(query, reason=problem)` |
| `pending`, `window_review`, `dashboard`, `intake`, `applied`, `unknown` | `ask.reply(message, route, query)` (`ask.py:1065-1092`): `🤔 _Reading the live portal..._`, the answer edited in its place, then what was read is published (section 9) |

### 6.2 `ask.classify(text, today) -> Route(kind, day, window, topic, words, problem)` (`ask.py:529-652`; `Route`, `ask.py:370-376`)

Text is lower-cased, `’` -> `'`, whitespace collapsed. **Every keyword is a whole-word regex** built by `_re(words) = re.compile(r"\b(?:" + words + r")\b", re.I)` (`ask.py:47-49`), so "across" is no "cross", "shipping" no "pin", "Janan" no January, "summary" no March, "doctor"/"daughter" no month, "outperform" and "performing arts" no performance. Tried in this order (first match wins):

| # | Kind | Rule (regexes in `ask.py:52-152`) |
|---|---|---|
| 1 | `hello` | whole message is a greeting/thanks: `^\W*(hi+\|hello\|hey\|hiya\|salam\|assalamu alaikum\|good morning/afternoon/evening/night\|thanks\|thank you\|thx\|ok(ay)\|cool\|great\|nice\|bye)( jennie\| bot\| there\| so much\| a lot)?\W*$` |
| 2 | `report` | text starts with `/report` or `/brief` |
| 3 | `pin` | `pp pin`, `pin`, `pinned`, `pin it`, `cheat sheet`, `command list`, `list of commands`, `all commands`, `commands`, `menu` |
| 4 | `performance` (topic `today` / `month` / none) | `_PERFORMANCE_RE` (`ask.py:105-109`): the performance words `_PERFORMANCE_WORDS` (`ask.py:103-104`) = `perform[ae]nces?\|perfom[ae]nces?\|performaces?\|perfromances?\|preformances?\|productivity\|leader[\s-]?boards?\|performers?` (so the owner's "performence", "perfomance", "performances" too); or `how did/does/do/has/have/is/are/was/were (the/our/my) (whole) team/staff/everyone/everybody/counsellor(s)/consultant(s) do/done/doing/did/perform(ed/ing)/go/going/gone`; or `team/staff('s) activity/stats/statistics/report/summary/score(s)/result(s)`. **Not** when the words name a subject the page does not show (`_names_another_topic`, `ask.py:490-505`: pending payments, window applications, open windows, an intake or program or university, a stage or pipeline, documents to review, missing, admitted, visa, the calendar, passports, cross-checks, registrations: "how is the team doing with pending payments" is `pending`). Then `performance_route` (below); the route is kept unless it names **another single day** and consultation or verification words **without** a performance word (`_PERFORMANCE_WORD_RE`, `ask.py:113`, = the performance words or `perform(s/ed/ing)`): "how did the counsellors do yesterday" falls through to that day's `inquiries`, but "consultant performance yesterday" stays `performance` |
| 5 | `crosscheck` | `cross[\s-]*check(ed\|ing\|s)?`, `crosscheck...`, `audit(ed\|ing\|s)?`; or a field word (`father's`, `mother's`, `address(es)`, `parents`, `dob`, `date of birth`); or `check` + `verif*`. If the text has no 2-5 digit number outside its dates, `window` = the span it names (past-facing) |
| 6 | `passports` | `passport(s)`, `mrz`; day/window/problem past-facing |
| 7 | `pending` | `unpaid`, `not (yet) paid`, `payment approval(s)`; or a pay word (`pay`, `paying`, `payment(s)`, `paid`...) + `pending/waiting/awaiting/outstanding/due/unconfirmed/approval` |
| 8 | `dashboard` topic `pipeline` | a pipeline stage named (`_stage_named`, `ask.py:197-208`: the 10 stage names; Payment Verified / Documents Verified / Admitted / Completed need the word "stage" beside them; "applied to a university" = University Applied) |
| 9 | `dashboard` topic `documents` | a docs word (`doc(s)`, `document(s)`, `paper(s)`, `file(s)`, `upload(s)`) + a state word (`review*`, `verif*`, `waiting`, `pending`, `approv*`, `reject*`, `check*`, `unverified`, `queue`, `to verify`, `under/in review`) and not `missing`/`incomplete` |
| 10 | `inquiries` | `consult(ation\|ations\|ancy\|ancies)`, `inquiry/ies`, `enquiry/ies`, `lead(s)`, `counsellor(s)`, `consultant(s)` |
| 11 | `verified` (or `dashboard` `verified_total`) | `verif(y\|ied\|ies\|ication\|ications)`; with `in total`, `overall`, `altogether`, `all time`, `so far`, `ever`, `in all`, `on record` and no date -> the dashboard's Verified tile |
| 12 | `missing` | `missing`, `incomplete` |
| 13 | `dashboard` `pipeline` | `pipeline`, `funnel` |
| 14 | `admitted` | `admit(ted\|s)` |
| 15 | `stage` | `stage(s)` |
| 16 | `dashboard` `visa` | `visa(s)` (no visa figure: said so) |
| 17 | `window_review` | `under review`, `in review`, `being reviewed`, `reviewing`, `window app(lication)s`, `admission window applications` |
| 18 | `dashboard` `accepted` / `submitted` | `accepted` / `submitted` + `app(lication)s` |
| 19 | `dashboard` `windows` | `open\|active\|draft (admission) window(s)` |
| 20 | `calendar` | `calendar`, `event(s)`, `deadline(s)`, `due`, `dhl`, `shipping`, `shipment(s)`, `ship`, `courier`, `reminder(s)`, `schedule(d/s)`, `closing`, `closes`, `opening`, `application window(s)/period(s)`, `open for application(s)`, `accepting applications`, `admissions/applications (is/are) open` |
| 21 | `intake` | a month + year like `March 2027` (not preceded by a day number, so "07 Sep 2026" is a date) -> `words="MARCH 2027"`; or `intake(s)`, `batch(es)` |
| 22 | `applied` (or `dashboard` `applied`) | `registered`, `registration(s)`, `sign(ed) up(s)`, `signups`, `joined`, `enrolled`, `new students/applicants/applications`, `applied`, `applications received/came`; "this/the/current week/month" -> the dashboard's "Applied this week/month"; a day/window -> counted from the list; nothing -> dashboard |
| 23 | `dashboard` `program` | a program word + a students word, or `per/by/each/every/across program(s)` |
| 24 | `dashboard` `university` | `universit(y\|ies)`, `uni(s)`, `college(s)` + `most/top/biggest/...` or a students word or `per/by university` |
| 25 | `dashboard` `attention` | `urgent`, `alert(s)`, `attention`, `to-do(s)`, `action item(s)`, `needs attention` |
| 26 | `dashboard` `total_students` | a students word (`student(s)`, `applicant(s)`, `people`, `enrolment(s)`, `admission(s)`) and nothing else but filler |
| 27 | `report` | `report(s)`, `brief(ing)`, `summary`, `summarise/ize`, `overview`, `recap`, `round-up` |
| 28 | `stats` | `stats`, `statistics`, `dashboard`, `figures`, `kpi(s)`, `metrics`, `numbers` |
| 29 | `unknown` | none of these |

Dates inside routes: `_when(low, today)` (`ask.py:383-392`) = `date_window(low, today, forward=False, months=False)`: one day -> `day`; a span -> `window`; "upcoming" -> nothing (meaningless for the past); a month without a day -> a date problem. `classify` itself never reads the portal.

**`performance_route(text, today) -> Route("performance", ...)`** (`ask.py:395-442`), in this order (the words `this months` / `current months` are read as `this month's` first, `_THIS_MONTHS_RE`, `ask.py:138`, because the owner writes without apostrophes):
1. another month (`_OTHER_MONTH_RE`, `ask.py:114`: "last/previous/past/next/coming/following (N) month(s)", "months") -> the window, else words "another month"; no topic;
2. a week (`_WEEK_RE`, `ask.py:124`: "(this/current/last/previous/past/next) week(s)/weekly/fortnight(ly)", "wtd") -> the span when it is more than one day, else the period's name; no topic (the page's This Week is never Today, even on a Monday);
3. this month so far (a window from the 1st to today or later: "this month", "September", "1 Sep to 30 Sep") -> topic `month`, unless the words also name another month or year (`_this_month_route`, `ask.py:473-487`; `_other_period_named`, `ask.py:453-470`: "performance for the month of august" is August, "this month last year" another year; "May" counts as a month only as "May 2026", "in/during/for May" or "the month of May");
4. one day -> topic `today` when it is today, else that `day` with no topic; a span -> that `window`;
5. "month's", "monthly", "mtd" (`_THIS_MONTH_RE`, `ask.py:115`) with no date named -> topic `month`;
6. the page's other periods (`_OTHER_PERIOD_RE`, `ask.py:118-122`: all time, overall, lifetime, ever, in total, altogether, ytd, year to date, last/next year(s), a year ago, yearly, annual(ly), (this/the/current/a) year('s), quarter(ly), custom (range), range) -> `words` = the readable name (`_period_name`, `ask.py:445-450`, with `_PERIOD_NAMES`, `ask.py:127-135`);
7. a year on its own (`_YEAR_WORD_RE`, `ask.py:143`, not inside an id or a date) -> `words` = the year;
8. a date that cannot be read -> `problem`;
9. else topic `today`.

Classified live on 30 Sep (offline run of `ask.classify`):

| Words | Route |
|---|---|
| performance today · perfomance today · performances today · how did the team do today · performance · leaderboard · team activity | `performance`, topic `today` |
| performence this month · this months performence · monthly performance · who is the top performer this month | `performance`, topic `month` |
| performance yesterday · consultant performance yesterday | `performance`, day 29 Sep, no topic (the other-period reply) |
| this week performance | `performance`, window Mon 28 Sep – Wed 30 Sep, no topic |
| all time performance · ytd performance · month performance 2025 | `performance`, words `all time` / `the year to date` / `2025` |
| performance for the month of august · performance 1 Sep to 15 Sep | `performance`, window (August 2026 / 1-15 Sep), no topic |
| performance 31 Sep | `performance`, problem `31 sep: September has 30 days` |
| how did the counsellors do yesterday · consultations today | `inquiries` (29 Sep / 30 Sep) |
| how is the team doing with pending payments | `pending` |
| outperform · performing arts | `unknown` |

### 6.3 Answers built in `ask.py` (each from read-only GETs made when asked)

| Kind/topic | Function | Source | Reply head |
|---|---|---|---|
| `pending` | `answer_pending(reads=None)` (`ask.py:882-934`) | every page of `students.php?status=pending`, rows whose own Payment is Pending, vs the sidebar badge | `💳 *Pending payments*` + `• Pending payments: `2` (students.php?status=pending, every page read)` + up to 30 names (`MAX_NAMES_LISTED`, `ask.py:41`) with HNG id, program, intake, applied day, stage; `_Window applications under review are a separate figure, never added to this one._` |
| `window_review` | `answer_window_review(reads=None)` (`ask.py:937-968`) | `window_applications.php?status=under_review` + the Under review tile | `🪟 *Window applications under review*` + `• Window applications under review: `0` (window\_applications.php, each row's own status)` + tile cross-check + `_Pending payments are a separate figure, never added to this one._` |
| `dashboard` | `answer_dashboard(route, query, reads=None)` (`ask.py:870-879`) -> `_dashboard_answer` (`ask.py:779-867`) | `index.php` tiles + cards (`dashboard_facts`) | topics: `total_students` (🎓 Students on the portal + by program), `verified_total`, `program` (one program when named), `university` (+ "Most students" for most/top), `applied` (At a glance week/month), `documents` (Docs to review both tiles + pipeline "Documents Under Review"; rejected; approved), `pipeline` (stages named or all), `attention`, `visa`, `accepted`/`submitted`/`windows`; each line `• <label> — <note> (<group>): `<figure>``, then `_Read live from the portal dashboard (index.php) just now._`; a figure not shown -> `• <label>: not available (the dashboard does not show it right now)` |
| `intake` | `answer_intake(route, query, reads=None)` (`ask.py:975-1006`) | every page of `students.php`, counted by intake (and program if named) | `🗓 *MARCH 2027 intake*` + `• Students in the MARCH 2027 intake: `46`` + by program; or `🗓 *Students by intake*` list; `_Counted from every page of the student list (330 students), read live just now._` |
| `applied` | `answer_applied(route, reads=None)` (`ask.py:1009-1035`) | every page of `students.php`, the Applied date of each | `📝 *Students who applied — <window>*` + `• Students who applied: `N`` (+ `⚠️ N student(s) ... have an Applied date the bot cannot read`) |
| `unknown` | `answer_unknown(query, reads=None)` (`ask.py:1038-1062`) | `index.php` facts | section 6.4 |

Any exception inside `ask.reply` -> `portal_error_reply("The answer", e)` (never a silent failure). What each answer read goes into the `reads` dict it is given, and `ask.reply` publishes it after the answer is sent (section 9).

### 6.4 When the LLM is used (and how it cannot invent a figure)

The local LLM (Ollama, `qwen3:4b-instruct`, `OLLAMA_NUM_CTX=3072`, temperature 0.3; loaded on demand and unloaded after `BRAIN_IDLE_UNLOAD=5m` while the voice is off) is used in exactly these places:

1. **Unknown free-text questions** (`ask.answer_unknown`): build the dashboard facts as lines `"<label> (<group>): <figure>"` (only facts with a numeric value). First `ollama_client._answer_query_fallback(query, lines)`: facts whose **whole label** (the words before the figure, parenthesis removed, plural `s` folded, stop words `a an the of to for in on and or by at with is are` dropped) is contained in the question (max 5); no LLM needed ("how many open windows?" -> `Open windows (Admissions flow): 3`). Only if none: `ollama_client.answer_agent_query(query, lines)`: system prompt `SYSTEM_AGENT_CHAT` (`src\llm\prompts.py`: pick the facts that answer the question directly, at most 4, never answer yourself, never calculate/add/compare, JSON only), user message `Facts:\n1. ...\n\nQuestion: ...\n\nJSON:`, structured output `AGENT_SCHEMA = {"facts": [int], "answered": bool}`, `num_predict=60`, timeout 30 s, skipped if the prompt might not fit `num_ctx` (`prompt_fits`, 2.4 chars/token estimate, 512-token answer budget). The picked facts are shown **word for word**:
   ```
   📊 *From the portal dashboard*
   • Open windows (Admissions flow): `3`
   _Read live just now; the local AI picked which figures answer it; each figure is the portal's own._
   ```
   No pick, `answered: false`, brain down, or garbage -> `cant_answer()`.
2. **The daily brief's one-line summary** (`brief.llm_summary`, section 7.1), dropped unless every claim checks out.
3. **`/sendmail` email bodies** (`_ai_write_email`), always shown for approval before sending.
4. Jennie's voice routing and spoken lines (disabled).

The performance commands never use the LLM: every figure in them is the page's own.

**The honest fallback** (`ask.cant_answer(why=None)`, `ask.py:753-757`, with `CANT_ANSWER`, `ask.py:736-747`):
```
🤷 I can't answer that from the portal yet.
Here is what I can read live for you:
• Payments verified on a day: /verified_today · /verified_date
• Consultations on a day: /inquiries_today · /inquiries_date
• Pending payments, applications under review, totals, programs, intakes and the dashboard's figures: just ask, e.g. “show pending payments”
• Deadlines and DHL: /calendar, or “any deadlines this week”
• Admitted students: /admitted · Stages: /stage · Missing information: /missing
• Passport and document cross-checks: /crosscheck_today · /crosscheck_date
• The portal's Consultant Performance page (tiles, top performer, leaderboard): /performance_today · /performance_month
• The day's brief: /brief
```
With a reason when the dashboard itself could not be read: `🤷 I can't answer that from the portal yet (the portal dashboard could not be read: <why>).`

---

## 7. Scheduled jobs (`setup_scheduler`, `scheduler.py:419-514`)

One `AsyncIOScheduler()` in the bot process (default time zone = the PC's local zone; cron jobs pass `ZoneInfo(settings.REPORT_TIMEZONE)` = `Asia/Dhaka` explicitly). Nothing is scheduled if `ENABLE_SCHEDULED_REPORTS` is false (`.env`: `true`). Every job has `replace_existing=True`, `max_instances=1`, `coalesce=True`. Interval jobs first fire one interval after start, except the full picture, which fires 7.5 minutes after start. After the 30 Sep 22:27:37 restart (publishing on): full picture at 22:35:07 (finished 22:35:34), sync at 22:42:37, watcher at 22:57:37, brain check every 10 min from 22:37:37. Startup log (`scheduler.py:512-513`, written after `scheduler.start()`): `Scheduler active: daily briefing set for 18:05 (Asia/Dhaka), passport watcher running every 30m, portal sync every 15m, missing-info report 09:05, Supabase full picture every 60m.` (the last clause only while publishing is on; else the line ends at `09:05.`).

| id | Function | Trigger | Grace | Runs as | Sends |
|---|---|---|---|---|---|
| `daily_executive_briefing` | `send_daily_briefing(app)` (`scheduler.py:248-278`) | `CronTrigger(hour, minute, timezone=Asia/Dhaka)` from `DAILY_REPORT_TIME="18:05"` (fallback 18:05 if unparsable) | `misfire_grace_time=600` | in the bot loop | the brief to `TELEGRAM_ADMIN_CHAT_ID` (Markdown), then Jennie's spoken version only if `JENNIE_VOICE_ENABLED and JENNIE_SPOKEN_BRIEF` (both `false`); then its Supabase copy |
| `passport_upload_watcher` | `check_new_passport_uploads(app)` (`scheduler.py:158-246`) | `IntervalTrigger(minutes=30)` | default | in the bot loop (OCR in a thread) | grouped alerts to the admin chat; then its Supabase copy |
| `portal_sync` | `run_portal_sync()` -> `_run_module("src.sheets.auto_sync")` | `IntervalTrigger(minutes=15)` | default | subprocess | its own plain-text summaries to brief recipients; then its Supabase copy |
| `missing_info_report` | `run_missing_report()` -> `_run_module("src.sheets.missing_report")` | `CronTrigger(hour=9, minute=5, timezone=Asia/Dhaka)` | 3600 | subprocess | summary + Excel to brief recipients; then its Supabase copy |
| `passport_issue_refresh` | `run_issue_date_refresh()` -> `_run_module("src.sheets.passport_issue --refresh")` | `CronTrigger(hour=8, minute=30, timezone=Asia/Dhaka)` | 3600 | subprocess | nothing (cache file); then its Supabase copy |
| `brain_keep_warm` | `keep_brain_warm()` (`scheduler.py:317-337`) | `IntervalTrigger(minutes=10)` | default | in the bot loop | nothing; returns at once unless the brain is pinned (`JENNIE_VOICE_ENABLED or BRAIN_ALWAYS_LOADED`, both false now) |
| `cloud_full_picture` | `run_full_picture()` (`scheduler.py:369-389`) -> `_run_module("src.cloud.full_picture")` | `IntervalTrigger(minutes=FULL_PICTURE_MINUTES, start_date=now + FULL_PICTURE_FIRST_MINUTES)`, 60 and 7.5 (`scheduler.py:365-366`, `:503-504`) | default | subprocess (CPU only) | nothing to Telegram (section 7.7) |

**Why these times; what can be configured.** The first six times and intervals are **inherited from the baseline** (`HANDOFF.md:120-123`) with no recorded reason. Only `DAILY_REPORT_TIME` is a setting; 30 min (`scheduler.py:450`), 15 min (`:461`), 09:05 (`:471`), 08:30 (`:482`), 10 min (`:493`) and the full picture's 60 / 7.5 min (`:365-366`) are literals. The full picture's 7.5-minute offset is deliberate: it puts the hourly run midway between the sync's 15-minute and the watcher's 30-minute beats. Constraints to keep: the 08:30 issue-date refresh must finish before the 09:05 report; an idle sync (~30 s) and an idle watcher run (~9 s) fit their intervals; the watcher's 20-minute OCR budget (`WATCHER_BUDGET_SECONDS`, `scheduler.py:35`) stays inside its 30-minute interval; the full picture must stay out of the **quiet windows** 18:00-18:10, 08:25-08:40 and 09:00-09:10 (`QUIET_WINDOWS`, `src\cloud\backfill.py:57`) and away from a running sync. A rebuild should put all of them in `.env` ([01 §5.4](01_ARCHITECTURE.md)). The exact Bot API calls of the subprocess jobs are in [07 §9](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md).

`_run_module(module, label)` (`scheduler.py:392-416`): `asyncio.create_subprocess_exec(<venv python.exe>, "-m", *module.split(), cwd=<bot root>, stdout/stderr appended to hangeul_sync.log, env PYTHONIOENCODING=utf-8, creationflags=CREATE_NO_WINDOW)`; killed after 3600 s (`"<label> took over an hour and was stopped."`); logs `"<label> finished (exit N)."`. A crash in a job can never take the bot down. Subprocess jobs send Telegram messages themselves through the raw Bot API with httpx: `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage` with `chat_id`, `text` (plain, no parse mode), `disable_web_page_preview=True`; files with `/sendDocument`.

**The Supabase copy of each job** is always its **last** step, after everything was sent: in the bot process through `bot_jobs.hand_over(job, build, *args)` (`src\cloud\bot_jobs.py:67-89`: builds the records in a worker thread, waits at most `HANDOFF_WAIT = 30` s, never raises, does nothing while publishing is off or in mock mode), in the subprocess jobs through `sheet_hooks.hand_over` (`src\cloud\sheet_hooks.py`). Both end in `handoff.submit`, which writes one handoff file and starts the publisher process without waiting for it (section 9). No job's messages, files or timing depend on Supabase; a failure is one log line `Supabase publish failed (<job>): <what> (<ExceptionType>)`.

Startup work in `post_init` (not scheduled): set the menu, pin the cheat-sheet, then `warm_brain()` (3 attempts, 30 s apart, reload if the model landed partly on the CPU; then voice filler clips if voice is on) when the brain is pinned, else `ollama_client.unload()` to free a copy pinned by an earlier run.

### 7.1 The daily brief at 18:05 (`src\bot\brief.py`)

`compose_brief(day=None, with_summary=True) -> Brief(text, facts, reads)` (`brief.py:600-662`; `Brief`, `brief.py:76-81`: `reads` = what its portal reads returned, for the Supabase copy only, never used by the text); `compose_daily_brief()` (`brief.py:665-667`) returns the text. The portal reads run **one after another** through `_PortalReads` (`brief.py:562-597`; one session, no parallel logins; each failed read's exception kept in `.errors`), each within `READ_TIMEOUT=75 s`, all within `PORTAL_BUDGET=150 s` (`brief.py:69-70`); after the first read the portal does not answer (timeout, transport error, `PortalUnavailable.unreachable`), the rest are skipped with `not read: the portal did not answer`. Order: consultations day -> verified students (unless the yearless rule forbids the day) -> consultation totals -> pending payments -> window applications -> dashboard -> calendar (today only) -> local document-check results. On 28 Sep 18:05 it took 11.4 s of portal reads, 12.9 s total, 2209 characters, "summary added".

The five sections (every figure counted in code; a figure that cannot be read is `not available (<why>)`; an empty section says so):

| # | Heading | Source | Content |
|---|---|---|---|
| 1 | `*1) CONSULTATIONS TODAY*` (`ON <DD Mon YYYY>` for another day) | `read_consultation_day` + `read_consultation_totals` | Received / Done (consulted, file opened); New / No answer / Wrong number; other statuses; "Done by" from the rows' "Last updated by" (`no name on the portal N`); the all-time line from the status tabs |
| 2 | `*2) PAYMENT-VERIFIED STUDENTS TODAY*` | `read_verified_students(day, all_pages=True)` | count and total (what it adds up), then `N. <name> — <program> — <payment_text> — verified by <staff> at HH:MM` |
| 3 | `*3) PORTAL FIGURES (live now)*` | `read_pending_payments`, `read_window_apps_under_review`, `get_dashboard` | Pending payments and Window applications under review on **two separate lines** (with the tile as a cross-check or fallback) + `_(two separate figures, never added together)_`; then the other tiles per dashboard group |
| 4 | `*4) TODAY'S CALENDAR REMINDERS*` | `get_calendar_events` | count by type, up to `MAX_REMINDERS_LISTED=8` lines `- <title> — <type> — <range> — N days left`, `… and N more`; only for today |
| 5 | `*5) DOCUMENT CHECK (from the last automated check, not live)*` | `data\verification\results.json` (`settings.verification_dir()`) | `N students: FAIL a, REVIEW b, INCOMPLETE c, PASS d` + `Last check: DD Mon YYYY, HH:MM` |

Example (placeholders; Markdown):
```
📋 *HANGEUL DAILY BRIEF* — 28 September 2026, 18:05 (Asia/Dhaka)
_Facts only, read live from the portal (read-only) unless marked otherwise. Nothing is estimated._

*1) CONSULTATIONS TODAY*
• Received: 5  |  Done: 2 (2 consulted, 0 file opened)
• New / pending: 3  |  No answer: 0  |  Wrong number: 0
• Done by: <staff name> 2
• All time on the portal (its own status counts): 999 requests, 797 done (791 consulted, 6 file opened), 8 new, 154 no answer, 40 wrong number

*2) PAYMENT-VERIFIED STUDENTS TODAY*
• None today

*3) PORTAL FIGURES (live now)*
• Pending payments: 2 (students.php?status=pending)
• Window applications under review: 0 (window\_applications.php)
  _(two separate figures, never added together)_
• Dashboard, Admissions flow: Open windows 3 · Draft windows 0 · Submitted apps 0 · Docs to review 44 · Accepted 3
• Dashboard, Direct / legacy pipeline: Total students 330 · Verified 328 · Docs to review 11 · Admitted 0

*4) TODAY'S CALENDAR REMINDERS*
• 11 reminders: Application period 7, DHL to send 4
  - SEJONG DHL — DHL to send — 26 Sep–28 Sep
  - Jeonbuk National University - Application open — Application period — 21 Sep–02 Oct — 4 days left
  … and 3 more

*5) DOCUMENT CHECK (from the last automated check, not live)*
• <n> students: FAIL <a>, REVIEW <b>, INCOMPLETE <c>, PASS <d>
• Last check: 28 Sep 2026, 17:40

🤖 _Summary by the local AI, its numbers checked against the facts:_ 5 consultation requests were received today and 2 were done.
```

**The LLM summary guard** (`llm_summary`, `check_summary`, `claims_problem`, `_SUMMARY_SYSTEM`, `brief.py:364-557`): the LLM gets only the facts list, one figure a line (e.g. `- Consultation requests received today: 5`), with `_SUMMARY_SYSTEM` (one or two plain sentences, numbers exactly as written, one figure per clause, no totals/rates/dates, never combine pending payments and window reviews, no visas/passports/intakes/conversion, no Markdown, at most 280 characters), `num_predict=120`, timeout 30 s. The answer is dropped unless: it is plain English (`_FOREIGN_RE`: no character outside ASCII except curly quotes, dashes, the ellipsis and a no-break space, so another script's number words cannot slip past the number check); at most 350 characters and two sentences; no off-topic word (visa, passport, conversion, intake, rate, percent, "prepared by", YTD, `%`); no vague or comparing count word (several, both, few, most, all, more, than, increased, ordinals...); no negation (not, never, n't...); every number (digits or words; "no/none/zero" = 0) exists in the facts; no decimal not in the facts; every word is a fact word, a plain connecting word or a synonym (`inquiry`->`request`, `taka`->`bdt`, `consultant`->`counsellor`...); and in each clause the numbers equal the figure of the fact whose telling words the clause shares most (rarer words weigh more). A brief for a past day also drops a summary that says today/yesterday/tomorrow. When the brain is down, or no fact has a number, there is no summary.

Sending: `_send_brief(bot, chat_id, text)` -> `send_brief_text` -> `send_pieces(..., "Markdown")` (section 8). A failure to compose or send is logged (`Failed to dispatch scheduled briefing`) and nothing is retried (and nothing is published). **After** the text and any voice note went out: `bot_jobs.hand_over("daily_brief", bot_jobs.brief_batches, composed)` (`scheduler.py:278`): the brief as sent (report `brief|<day>`, a `report_section` per section, a `brief_fact` per fact), and what its reads returned (the day's requests and tab counts, the payments verified that day, the all-time counts, the dashboard tiles; the pending, window and calendar figures go into the report's data, as the brief's own reads of those are partial). Publishing went on at 22:27 on 30 Sep, so the first published brief is 1 Oct's.

### 7.2 Passport watcher, every 30 min (`check_new_passport_uploads`, `scheduler.py:158-246`)

1. Skip if no admin chat id. `read_students()` (every page); a failed read logs `Passport audit check skipped: couldn't read the portal: <why>` and sends nothing.
2. Memory `C:\Hangeul\BOT\data\alerted_passport_issues.json` = `{"version": 2, "scans": {"<uid>|<file>": {"uid", "student_id", "status", "checked": "YYYY-MM-DD HH:MM", "alert": <Markdown block> | null, "sent": bool, "sent_at"}}}` (`WATCHER_CACHE_VERSION = 2`, `scheduler.py:32`; an older uid-only list is distrusted: every scan is checked again). Saved atomically (`.part` + `os.replace`) after every audit.
3. Current scans: each student's newest `passport_<uid>_<epoch>` file. Scans the portal no longer lists are forgotten (unsent alerts included). New keys are audited newest upload first, `audit_student_passport(uid, {name, dob, passport_no, passport_expiry from the details row}, scan)`, until `WATCHER_BUDGET_SECONDS = 20*60`; the rest wait for the next run. Before each audit the profile the client holds is noted (`bot_jobs.profile_now`), after it the one the audit read is kept (`bot_jobs.keep_profile`).
4. `UNCHECKED_STATUSES = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE")` (`scheduler.py:39`) are neither alerted nor remembered (retried next run). Otherwise the scan is remembered, valid or not; `not is_valid and discrepancies` -> an alert block.
5. Pending alerts (unsent), newest first, packed into as few messages as fit under 3900 characters (`_alert_messages`, `scheduler.py:104-128`), sent with the Markdown fallback (`_send_alerts`, `scheduler.py:131-155`); each alert is marked sent only after Telegram accepted its message (and the accepted text noted for Supabase, `bot_jobs.note_sent`); a refused message stops sending and the rest stay pending.
6. Log: `Passport audit check: 311 scans on the portal, 0 audited this run (0 with issues), 0 could not be checked, 0 waiting for the next run; 0 alert(s) sent in 0 message(s), 0 not sent yet.` (every run on 30 Sep evening, ~9 s; 301 scans on 29 Sep).
7. **Last:** `bot_jobs.hand_over("passport_watcher", bot_jobs.watcher_batches, students, listed_at, checked, cache, failed, accepted, profiles)` (`scheduler.py:243-244`): the whole list (`student`, complete), this run's audits (`passport_audit`, complete over the scans the list shows), the memory as saved (`passport_alert`), each profile read (`student_profile`) and each alert message Telegram accepted (`notification`).

Caveat seen in the logs: in `hangeul_sync.log` from 22:27 to 23:44 on 30 Sep there is a `Supabase publish (...)` line for every `portal_sync` and `full_picture` run but **none** for `passport_watcher` (runs at 22:57 and 23:27). The publishes did happen: the hash state `data\cloud_state.json` holds the watcher's scope read times (`passport_audit|all` at 22:57:46, `student|all` at 23:27:45). Those runs overlapped the portal sync (both at :27 / :57), several processes append to the same log without locking, and one line there is visibly garbled (`[2026-09-2026-09-30 22:58:09 ...`), so the watcher's publisher lines were most likely overwritten ([13 §16.2, §18](13_SUPABASE_PUBLISHING.md)). Read `hg_runs` (or the hash state), not the log, to confirm a watcher publish.

Alert format (one; several are headed `🚨 *Automated Document Audit: N alerts* (part i of k)`):
```
🚨 *Automated Document Audit Alert*

• *Student:* *<student name>* (`HNG-2026-<n>`, `ID <uid>`)
• *Status:* `DISCREPANCY`
• *Issue:* Passport No mismatch: Portal has '<value>', Doc has '<value>'
• 🔗 *Direct Review Link:* [Edit Student #<uid>](https://hangeul.com.bd/admin/student_edit.php?id=<uid>)

_(Strict Read-Only Alert: Please update in admin portal manually if required)_
```
Known open issue (deferred by the owner, 28 Sep evening): a garbled MRZ line 2 whose passport-number check digit passes by chance can raise a false "Passport No mismatch"; the planned fix is to trust that field only when line 2 is otherwise sane (nationality matches line 1, or at least two check digits agree), flag one-character differences against the printed page, and name the scan file and upload date in the alert.

### 7.3 Portal sync, every 15 min (`python -m src.sheets.auto_sync`)

`run_once(send=True, verify=True)` (`auto_sync.py:412-480`), guarded by `data\auto_sync.lock` (holds the PID; a lock older than 2 h or of a dead PID is cleared; the full picture and the backfill only *read* this lock, to stay away from a running sync):
1. **Progress sheets:** every Direct student from `students.php?export=csv`, one Google Sheet per program + intake (`progress_builder.all_targets()`); each is snapshotted by row key (`Student ID:`, else a real `Passport No:`, else name + mobile) and SHA-1 digest and compared with `data\sheet_state.json`. Only a changed sheet's main tab is rebuilt (other tabs untouched); an unchanged sheet whose main tab was hand-edited is restored (`sheet_drift`). A row whose key changed is paired as the same student (same Student ID, real passport number, name + mobile, or `_likely_same`) and reported as edited with the changed columns.
2. **Documents:** `verified_docs.run_local(DOCS_ROOT)`: newly document-verified students' ZIPs into `C:\Hangeul\VERIFIED STUDENT DOCUMENTS\<PROGRAM>\<FULL NAME> (<PASSPORT NO>)\`, files over 2 MB shrunk (originals kept in `...\VERIFIED STUDENT DOCUMENTS - ORIGINALS OVER 2MB`), re-downloaded when the portal's file names change.
3. **Telegram** (only when something changed): plain text, title `🔄 Portal sync — changes found` (`SYNC_TITLE`, `auto_sync.py:331`), lines such as `📄 <PROGRAM> <INTAKE>: sheet updated — now N students`, `   • N new: <name>; ...` (max 8 names), `🛠 <sheet>: N cell(s) had been changed by hand on the sheet — restored from the portal ...`, `📁 N newly verified student(s) — documents saved:`, `⚠️ Could not download documents for <name>: <error> (will retry next run)`. `notify` now returns whether Telegram accepted every piece (the Supabase copy records only what was really sent).
4. **Document check** after the summary (`auto_verify.run(budget=6)`), sent separately under `🔍 Document check` (`CHECK_TITLE`, `auto_sync.py:332`): `🔍 Documents checked: N`, `   • <name> (<program>) — FAIL (<first failing rule>), N field(s) differ from the portal`, `   N more waiting — they run on the next passes.`, `   Reports: DOCUMENT CHECK.xlsx / FIELD CHECK.xlsx in <folder>`.
5. **Last** (only while publishing is on): `sheet_hooks.after_sync(cloud)` (`auto_sync.py:477`; job `portal_sync`): the export, the verified-documents list, the document check's results and the messages as sent. Log examples: `Supabase publish (portal_sync): ok, 0 upserted, 0 deleted, 976 unchanged, 0 row(s) sent, 0 failed, 0 read(s) failed; 0 record(s) embedded in 0.0 s; 0.4 s in all, peak memory 0.06 GB.` (30 Sep 22:43, the first automatic run), and `ok, 3 upserted, ... 1031 unchanged ...; 3 record(s) embedded in 0.2 s` when a document check changed something (23:28).
Retries: each step 3 attempts 20 s apart with a fresh portal session; a failure is reported only after 3 consecutive failed runs (`⚠️ <step> has failed N times in a row: <error>`), and recovery once (`✅ <step> is working again (it had failed N times in a row).`). A run takes about 30 s when nothing changed.

### 7.4 Missing-information report, 09:05 (`python -m src.sheets.missing_report`)

Reads every progress sheet's main tab and the CSV export; required fields `REQUIRED` (Student ID, Full Name, Surname, Given Name, Email, Mobile, Guardian WhatsApp, DOB, Gender, District, Address, Father, Mother, Study Status, SSC Year/GPA/Group/School, HSC Year/GPA/Group/College, Program, Passport Status, Passport No, Passport Expiry, Visa Rejection History, Sponsor, Sponsor Occupation, Bank Certificate) plus university fields by study status (all four for Master's and graduates; university + subject for current undergraduates); IELTS/TOPIK and Passport Issue are not counted. Sends to brief recipients:
```
🗓 Missing-information report — 29 Sep 2026
<x> of <y> students have missing information.
University fields of KLP, EAP and Bachelor's students are read from the portal (those sheets have no university columns).

📋 KOREAN LANGUAGE PROGRAM (KLP) MARCH 2027 — 7 of 120 incomplete
   • HNG-2026-<n> <student name> — 3 missing: Father, Mother, SSC GPA
   … and N more (see the Excel file)

⚠️ N student(s) have NO INTAKE on the portal, so they are on no sheet:
```
then the Excel file `C:\Hangeul\BOT\data\missing_reports\missing_information_YYYY-MM-DD.xlsx` (sheet "Missing information": Program, Intake, Student ID, Full Name, Mobile, Missing count, Missing fields) via `sendDocument`, caption "Every incomplete student with the fields they are missing". Failure: one message `❌ Couldn't build today's missing-information report: <why>. It will run again tomorrow at 09:05 (or send /missing).` and exit code 1. Last: `sheet_hooks.after_missing_daily(lines, rows, sent_at)` (`missing_report.py:354`), or `after_missing_failed(notice, sent_at, e)` (`:347`) when the report could not be built; job `missing_report`.

### 7.5 Passport issue-date refresh, 08:30 (`python -m src.sheets.passport_issue --refresh`)

Reads every page of `students.php` (uid + the details row's "Passport No"), then `student_edit.php?id=<uid>` per passport number (~300 GETs, sequential) and the `passport_issue_date` input value. Writes `C:\Hangeul\BOT\data\passport_issue.json` `{"by_passport": {"<passport no>": "YYYY-MM-DD"}}`. Placeholders without a digit ("PENDING") are no key; a number shared by students with different dates is left out; up to `MAX_UNREAD = 10` unanswered edit pages keep their previous dates; a refused login or a portal that is down aborts and keeps the old cache. Sends nothing. (Since Sep 2026 the CSV export has its own "Passport Issue Date" column, which the sheets use first; the cache is the fallback.) While publishing is on, the edit pages read are kept in memory and, after the file is written, `sheet_hooks.after_issue_refresh(data, pages, complete)` (`passport_issue.py:139`; job `issue_refresh`) publishes the file (`passport_issue`, complete only for a refresh without `--limit`) and each profile read (`student_profile`).

### 7.6 `keep_brain_warm`, every 10 min

`if not brain_pinned(): return`. When pinned (voice on or `BRAIN_ALWAYS_LOADED`): `ollama_client.residency()` (`/api/ps`); fully on the GPU -> nothing; partly on the CPU -> unload and `warm_brain(attempts=1)` (`scheduler.py:280-314`); not loaded -> `warm_brain(attempts=1)`. Sends nothing. With the voice off (the owner's choice of 28 Sep 17:08: `JENNIE_VOICE_ENABLED=false` and `JENNIE_SPOKEN_BRIEF=false` in `.env`, the `JennieVoiceWatchdog` task disabled, `JennieVoice.lnk` moved from Startup to `C:\Hangeul\JARVIS\disabled\`; [06](06_LLM_AND_JENNIE_VOICE.md)) the brain is loaded on demand for the first question and unloaded after `BRAIN_IDLE_UNLOAD`.

### 7.7 The Supabase full picture, hourly (`python -m src.cloud.full_picture`)

So that Jeannie's copy is complete even on a day nobody asks the bot anything ([13 §11](13_SUPABASE_PUBLISHING.md)).
1. **In the bot** (`run_full_picture`, `scheduler.py:369-389`): nothing at all while publishing is off (`bot_jobs.handoff.enabled()`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `CLOUD_PUBLISH_ENABLED` all set); `full_picture.skip_reason()` (`full_picture.py:66-74`) skips it now or within `LEAD_MINUTES = 5` of a quiet window (18:00-18:10, 08:25-08:40, 09:00-09:10) or while a portal sync holds `data\auto_sync.lock` (log `Full picture publish skipped: <reason>.`); else `_run_module("src.cloud.full_picture", "Full picture publish")` (log `Full picture publish finished (exit N).`).
2. **In its own process** (`full_picture.main`, `:177-195`; `CUDA_VISIBLE_DEVICES=-1` is set before anything can import torch, so the gte-small embeddings run on the CPU, only for records that changed): skipped again for publishing off, mock mode, a quiet window, or another publisher (the backfill) holding the publish lock for `LOCK_WAIT = 120` s; checked again after taking the lock and before **every** page; stops itself after `DEADLINE = 45*60` s.
3. **Reads** (`collect`, `full_picture.py:95-119`, GET only, a portal session of its own, `PortalSession`: once the portal does not answer, the pages after it are not tried): every page of `students.php`; every page of `students.php?status=pending`; `consult_requests.php` for yesterday and today; `?status=file_opened`; `window_applications.php?status=under_review`; `index.php`; `calendar.php`; `consult_performance.php?period=today` and `?period=month`. Then one publish run, job `full_picture` (only what changed is embedded and sent; only a whole read deletes anything).
4. **Sends nothing to Telegram.** Log lines (in `hangeul_sync.log`): `Supabase publish (full_picture): ok, 3 upserted, 0 deleted, 779 unchanged, 3 row(s) sent, 0 failed, 0 read(s) failed; 3 record(s) embedded in 0.1 s; 6.9 s in all, peak memory 0.87 GB.` and `Full picture: 12 batch(es) read in 18.3 s, 0 read(s) failed; 68 publish(es), 0 failed.` (the first automatic run, 30 Sep 22:35: the 3 changes were a new consultation request, its day's counts and the all-time totals); the next, 23:35: 0 upserted, 782 unchanged, read in 12.5 s.

---

## 8. Long messages and the Markdown fallback (`src\bot\replies.py`)

* `TELEGRAM_LIMIT = 4096`, `CHUNK_CHARS = 3900` (`replies.py:32-33`); lengths counted as Telegram does, in UTF-16 code units (`telegram_len`, `replies.py:38-40`: an emoji can count 2).
* `split_text(text, limit=3900) -> List[str]` (`replies.py:55-76`): split **between lines**, never inside one (a single line over the limit is cut at its last space); joining the pieces with `\n` gives the text back; a blank text gives `[]`. Because the bot's legacy-Markdown entities never span lines, a split never cuts `*bold*`, `_italic_` or `` `code` `` in half.
* `send_pieces(send, text, parse_mode="Markdown", *, first=None, limit=3900)` (`replies.py:102-119`): sends each piece through `send(piece, parse_mode)`; a `BadRequest` whose text contains "parse" or "entit" ("Can't parse entities") -> the same piece again as plain text via `markdown_to_plain` (`replies.py:79-83`: drops unescaped `*`, `_`, `` ` `` and un-escapes `\_ \* \` \[`); other errors propagate. With `first` (edit the "please wait" message into the first piece): "message is not modified" is ignored; any other edit failure falls back to sending the piece as a new message, so nothing is lost.
* `reply_long(message, text, parse_mode="Markdown", *, edit=None)` (replies, `replies.py:122-131`) and `send_long(bot, chat_id, text, parse_mode="Markdown")` (send_message, `replies.py:134-137`) wrap it.
* `_send_blocks(message, text, status_msg=None)` (`telegram_bot.py:1720-1742`) for cross-check and passport reports: packs blank-line-separated blocks (one per student card) into as few messages as fit, never cutting a card; a block longer than the limit is split between its lines.
* `performance.message_pieces(text, limit=None)` (`performance.py:247-278`) for the performance reports: packs whole records (a line plus the three-space-indented and blank lines after it), then each piece through `reply_long` (section 5.15).
* `_chunk_message(text, limit=3900)` (`telegram_bot.py:1492-1496`) for the `/sendmail` preview; each chunk tries Markdown then plain.
* The brief, the watcher alerts and the ask answers all go through `send_pieces`; subprocess jobs use `split_text` and plain text.

---

## 9. Publishing what was read to Supabase, after the reply (`src\cloud\command_hooks.py`)

Every handler that reads the portal keeps what each read returned in a plain dict while it works, and hands it on only **after its reply was sent**, without waiting (the pattern of `command_hooks.py:1-18`):

```python
reads = {}
students = await admin_client.read_students()
command_hooks.seen(reads, students=students)    # the read's result and the time it was read
...                                              # the reply is built and sent exactly as before
command_hooks.publish(reads)                     # after the reply: returns at once
```

* `seen(reads, **values)` (`command_hooks.py:93-109`) keeps each non-None value and its read time (`reads["at"][key]`, business time zone) and today's date; it does nothing unless `active()` (`:74-84`): publishing is on (`handoff.enabled()`) **and** the client is not in mock mode (demo data is not the portal's). Never raises.
* `publish(reads, job="command")` (`:139-148`) returns at once: a background task (`asyncio.to_thread`, a strong reference kept in `_tasks` until done) builds the records (`build`, `:183-247`, with `src.cloud.records`) and calls `handoff.submit("command", batches, failed_reads)`. So a reply is never delayed, changed or stopped by publishing; a build that fails is one log line with the exception **type** only (an exception text can quote student data): `Supabase publish failed (command): the records could not be built (<Type>)`.
* **A failed read keeps nothing**, so it never becomes `rows=[]` with `complete=True` (that would empty a scope in Supabase); a partial read (page 1 of the list, one day's calendar items) is published with `complete=False` and deletes nothing.
* `handoff.submit(job, batches, failed_reads)` (`src\cloud\handoff.py:118-138`) writes one file `C:\Hangeul\BOT\data\cloud\pending\<YYYYmmdd-HHMMSS-ffffff>-<job>.json` (`{"version": 1, "job", "created_at", "failed_reads", "batches"}`, via `.part` + `os.replace`) and starts `python.exe -m src.cloud.publish --from <file> --timeout 3600` (`spawn`, `:109-115`: the venv's console `python.exe`, never `pythonw`; cwd the bot folder; env with `PYTHONIOENCODING=utf-8`, `CUDA_VISIBLE_DEVICES=-1`, `HF_HUB_OFFLINE=1`; stdin closed; output appended to `hangeul_sync.log`; `CREATE_NO_WINDOW`), not awaited. The publisher embeds the changed records on the CPU and writes them through the RPC `hg_sync`, then deletes the file; files a killed publisher left are removed after `STALE_HOURS = 6` ([13 §9](13_SUPABASE_PUBLISHING.md); every kind's key, scope and completeness rule in [13 §5](13_SUPABASE_PUBLISHING.md), who writes what in [13 §13](13_SUPABASE_PUBLISHING.md)).

What each handler keeps (`seen` keys) and what it becomes:

| Handler | Kept | Supabase kinds (scope; complete?) |
|---|---|---|
| `/stats` | `dashboard` (`get_dashboard()`) | `dashboard_fact` (all; partial: tiles only, no cards) |
| `/students` | `page` (page 1) | `student` (all; partial) |
| `/admitted` | `students` (the whole list read), `dashboard` | `student` (all; complete) + `verification` per stamp day (complete within the one-year window when every stamp is readable), `dashboard_fact` |
| `/inquiries*`, `/consultations` | `consultations`, `totals` / `totals_error`, `inquiries_report` (the text as sent) | `consultation` (the day; complete when every request of the day is listed), `consultation_day` (partial), `consultation_totals` (complete), `report` `inquiries_report\|<day>` (partial), `report_section` (complete) |
| `/verified*` | `verified = (day, list)` | `verification` (the day; complete when the yearless rule allows the day) |
| `/passports`, `/crosscheck*` | `students`, `cards` (+ each card's whole audit result, the form compared and the profile read, `audited`, `:124-136`) | `student`, `verification`, `passport_audit` (all; partial), `student_profile` (the uid; complete) |
| `/calendar <words>`, `/deadlines <words>`, calendar free text | `calendar` (the merged items) | `calendar_item` (all; never complete) |
| `/performance_today`, `/performance_month`, aliases, performance free text | `performance = (period, page)` | `consultant_performance` (`<period>\|<first ISO day>`; complete only for a whole read: the page's own period, a readable range, the count badge equal to the rows, every row keyed by a name) |
| free text through `ask.reply` (`pending`, `window_review`, `dashboard`, `intake`, `applied`, `unknown`), `/alerts` | `pending = (rows, badge)`, `facts` (`dashboard_facts`), `students` | `pending_payment` (all; complete when the Pending rows equal the badge), `dashboard_fact` (all; complete when every tile group and card is on the page), `student`, `verification` |
| `/missing` (button), `/stage` (intake button) | in their subprocess: `sheet_hooks.after_missing_program`, `after_stage` | `report`, `report_section`, `student_progress`... ([13](13_SUPABASE_PUBLISHING.md)) |
| not published | `/brief`, `/report`, bare `/calendar`, `/sendmail`, `/start`, `/pin`, `/performance` for another period (nothing read) | — |

(The docstring at `command_hooks.py:45-49` still gives the performance scope as `"<period>|<first day>|<last day>"`; since `8317741` it is `"<period>|<first ISO day>"`, `records.performance_scope`, and the last day is the records' `day` and `data.range`.)

---

## 10. Rebuild checklist

1. Register handlers exactly as in section 2 (aliases share one handler; free text excludes commands), refuse everyone when no admin id is configured, and set the BotCommand menu (13 entries) + pinned cheat-sheet at startup; log the menu's real count.
2. One strict date parser; strict for dates given to commands, lenient only for free-text routing; the yearless-stamp rule; a stored "which date?" state with a re-ask.
3. A whole-word keyword router tried in a fixed order, with dated routes and a live read behind every route; the LLM only picks facts or writes checked summaries; an honest "can't answer" list. Route the owner's own spellings ("performence"), and let a subject word win over a vague phrase ("how is the team doing with pending payments").
4. A page the portal already computes (the Consultant Performance page) is shown as the portal shows it, never recomputed; only the periods it offers as links are read, the page must say it shows the period asked for, and any other period is told where to find it.
5. Every reply that can grow goes through a line-safe splitter with a plain-text resend; edit the "please wait" message into the first piece; keep a record's lines in one message.
6. Heavy jobs as subprocesses with timeouts and their own portal session; cron jobs with an explicit time zone, `max_instances=1`, `coalesce=True` and a misfire grace; alert memory that marks an alert sent only after Telegram accepted it; bulk readers stay out of the other jobs' quiet windows.
7. Anything published to a second store (Supabase) happens after the reply or the job's own work, in another process, never awaited, never raising, and only a whole read may delete there.
