# 03a — File map: `src\bot\` and `src\__init__.py`

**What's in this file:** a file-by-file, function-by-function map of the Telegram layer of Hangeul BOT (`C:\Hangeul\BOT\src\bot\*.py`, including the new `performance.py`, the root staging copy `telegram_bot.py`, and the package initialiser `src\__init__.py` with its CA-bundle and secret-redaction code). For every file: purpose, public API with exact signatures, private helpers, constants/regexes/selectors, I/O, imports and callers, error handling, the Supabase publish hooks it calls, and git history.
**Pack written/refreshed:** written 29 Sep 2026 from `c17d887`; refreshed 30 Sep 2026 (Asia/Dhaka) from repo `C:\Hangeul\BOT`, branch `main`, HEAD `8317741` (48 commits; 20 since `c17d887`, 4 of them merges), working tree clean. Line numbers are `path:line` at `8317741`. The command-by-command user view (what each command replies, the job schedule) is in [Commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md); this file is the code view. The libraries it calls are mapped in [03b](03b_FILES_src_scraper_llm_api_config.md) (client, parsers, dates, Ollama) and [03c](03c_FILES_sheets_verify_root_scripts.md) (sheet jobs); the Supabase layer the hooks hand their reads to is mapped in [03d](03d_FILES_src_cloud.md) and explained in [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md); the prompts and Jennie's design in [06](06_LLM_AND_JENNIE_VOICE.md); the request flows and concurrency model in [01_ARCHITECTURE.md](01_ARCHITECTURE.md); the stage-by-stage history in [08](08_HISTORY_STAGE_BY_STAGE.md); the pack index in [00_INDEX.md](00_INDEX.md).

Secret values are never shown here. Where one matters it is written as "value in secrets\bot.env (KEY_NAME)" (the pack's copy of `C:\Hangeul\BOT\.env`). Student data is shown only as placeholders (`<name>`, `<uid>`, `HNG-YYYY-NNN`); consultants in examples are `<consultant A>`, `<consultant B>`.

---

## 0. Scope at a glance

`git -C C:\Hangeul\BOT ls-files` gives 10 tracked files in scope (all read in full for this map):

| File | Lines | Role | Created | Last changed | Tests that import it (grep of `src.bot.<name>` / `bot.<name>`) |
|---|---|---|---|---|---|
| `src\__init__.py` | 79 | Package init: trust the Windows CA bundle; redact the bot token **and the Supabase keys** from log lines (`redact()`) | `366dec0` (CA part) | `36ae72e` | test_cloud (`src.redact`) |
| `src\bot\__init__.py` | 1 | Package marker (`"""Telegram bot and scheduler package."""`) | `366dec0` | `366dec0` | — |
| `src\bot\replies.py` | 165 | Splitting long text under Telegram's 4096 limit, Markdown→plain resend, the two stock error replies | `e0d47ab` | `e0d47ab` | test_crosscheck, test_foundation, test_freetext, test_inquiries, test_jobs, test_performance, test_repair_voice, test_voice, test_voice_fast |
| `src\bot\brief.py` | 687 | The factual daily brief (18:05 and `/brief`, `/report`), and `claims_problem`, the fact-checker for any LLM sentence; `Brief.reads` for the Supabase copy | `f8fefa4` | `5048a07` | test_brief, test_cloud_bot_jobs, test_final_fixes, test_repair, test_voice, test_voice_fast |
| `src\bot\scheduler.py` | 515 | APScheduler jobs: brief, passport watcher, sheet sync/reports (as subprocesses), brain keep-warm, **the hourly Supabase full picture**; hand-over of the brief and watcher reads | `366dec0` | `e4d1cea` | test_brief, test_cloud_all, test_cloud_bot_jobs, test_cloud_fixes, test_final_fixes, test_jobs, test_voice, test_voice_fast, test_watcher_nonblocking |
| `src\bot\ask.py` | 1411 | Free-text router `classify()` (now with the **performance** route), `performance_route`, and the live answers no menu command gives (pending, dashboard, intakes, applied, calendar) | `7f42ad0` | `314afdb` (merged in `e5e532e`) | test_brief, test_cloud, test_cloud_all, test_cloud_bot_jobs, test_cloud_cf_email, test_cloud_commands, test_cloud_fixes, test_final_fixes, test_foundation, test_freetext, test_performance, test_repair |
| `src\bot\performance.py` | 303 | **New.** `/performance_today`, `/performance_month`: the portal's own Consultant Performance page (`consult_performance.php?period=today\|month`) shown as it is, split between whole records | `bbd8f98` | `e4d1cea` | test_performance, test_cloud_performance |
| `src\bot\voice.py` | 1877 | "Jennie": voice notes in → STT → LLM router → command → checked spoken sentence → TTS voice note out; spoken brief. **Unchanged since `e164679`; disabled** | `d7a5817` | `e164679` | test_brief, test_freetext, test_repair, test_repair_voice, test_voice, test_voice_fast |
| `src\bot\telegram_bot.py` | 2437 | Every command handler (now 3 performance handlers), the `/sendmail` flow, cross-checks, the free-text dispatcher, application build and `post_init` (13 menu entries); publish hooks after each reply | `366dec0` | `e4d1cea` | 16 of the 25 test files |
| `telegram_bot.py` (repo root) | 2437 | **Byte-identical** staging copy of `src\bot\telegram_bot.py` (see §8.12; `cmp` confirms at `8317741`) | `366dec0` | `e4d1cea` | — |

Library versions (from `requirements.txt`, confirmed in `.venv`): `python-telegram-bot==22.8`, `apscheduler==3.11.3`, `httpx==0.28.1`, `beautifulsoup4==4.15.0`, `pydantic-settings==2.15.0`, Python 3.12. (New since `c17d887`, used only by `src\cloud` in its own processes: `sentence-transformers==6.1.0`, `transformers==5.17.0`; see [03d](03d_FILES_src_cloud.md).) The whole suite is 1152 tests (2 skip in the live checkout by design, because the real `.env` is present).

### Import graph (who imports whom)

```
run.py ──► src.bot.telegram_bot (build_telegram_application, post_init)
src.bot.telegram_bot ──(top level)──► src.config.settings, src.scraper.client.admin_client,
                                      src.llm.ollama_client.ollama_client, src.bot.scheduler.setup_scheduler
                     ──(lazy, inside functions)──► src.bot.replies, src.bot.brief, src.bot.ask, src.bot.voice,
                                      src.bot.performance, src.cloud.command_hooks,
                                      src.dates, src.scraper.parsers, src.scraper.client.PortalUnavailable
src.bot.scheduler ──► src.config (BOT_ROOT, settings), src.scraper.client, src.llm.ollama_client,
                      src.bot.brief, src.bot.replies, src.cloud.bot_jobs (→ src.cloud.handoff, src.cloud.records) ;
                      lazy: src.bot.voice, src.llm.ollama_client.brain_pinned, src.cloud.full_picture.skip_reason
src.bot.brief ──► src.bot.replies, src.config, src.dates, src.llm.ollama_client, src.scraper.client ;
                  lazy: src.bot.voice (_numbers_in, _WORD_VALUES, _WORD_SCALES, _plain), src.scraper.parsers
src.bot.ask ──► src.dates (has_date_hint, local_today, parse_user_date, user_date_problem) ;
                lazy: src.bot.brief.esc, src.bot.replies, src.scraper.client, src.scraper.parsers
                (incl. decode_cf_emails), src.llm.ollama_client, src.cloud.command_hooks
src.bot.performance ──► src.bot.brief.esc, src.scraper.client (PERFORMANCE_PAGE, PERFORMANCE_PERIODS),
                        src.scraper.parsers._label_key ;
                        lazy: src.dates (MONTHS, parse_portal_date, local_today), src.bot.replies,
                        src.cloud.command_hooks, src.scraper.client (admin_client, portal_error_reason)
src.bot.voice ──► src.config (BOT_ROOT, settings), src.llm.ollama_client ; lazy: src.bot.telegram_bot (as bot),
                  src.bot.ask, src.bot.brief.claims_problem, src.bot.replies.date_error_reply, src.dates
src.bot.replies ──► telegram.error.BadRequest, telegram.helpers.escape_markdown ;
                    lazy: src.dates.user_date_problem, src.scraper.client.portal_error_reason
Outside src\bot: src\sheets\auto_sync.py:340 and src\sheets\missing_report.py:251 import replies.split_text;
                 audit_program.py:72 and inspect_passports.py:20 import scheduler.passport_scan;
                 src\cloud\backfill.py:268 / :283 import ask.dashboard_facts / ask.calendar_items (the full
                 picture and the backfill parse index.php and calendar.php with the bot's own code);
                 src\cloud\records.py:816 imports performance._range_dates (the page's range as dates).
```

Why the lazy imports: `telegram_bot` imports `scheduler` at the top, `scheduler` imports `brief`; `voice` needs `telegram_bot`'s handlers and `telegram_bot` optionally needs `voice`. Importing inside functions breaks every cycle, and keeps `voice` (and its `httpx` client) out of the process unless a voice path runs. `src.cloud.command_hooks` is imported lazily in every handler so a problem in the cloud package can never stop the bot importing; `scheduler` imports `src.cloud.bot_jobs` at the top (it imports only `handoff` and `records`, which are pure Python: torch and the embedder load only in the publisher process).

**Must keep (used from outside src\bot):** `ask.dashboard_facts`, `ask.calendar_items`, `performance._range_dates`, `replies.split_text`, `scheduler.passport_scan`.

---

## 1. `src\__init__.py` — CA bundle and secret-redacting log filter

**Purpose.** Runs once, when any `src.*` module is first imported (the bot via `run.py`, every scheduled job, which runs as `python -m src.sheets.<job>`, and every `src\cloud` process). Two side effects.

**1a. Trust the Windows certificate stores (`src\__init__.py:7-22`).**
```python
_CA = _Path(__file__).resolve().parent.parent / "data" / "windows-ca.pem"
if _CA.exists():
    for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                 "HTTPX_SSL_CERT_FILE", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"):
        _os.environ.setdefault(_var, str(_CA))
```
- Why: on the old PC, antivirus HTTPS scanning / the ISP presented certificates chaining to a root Windows trusts but `certifi` does not; on 26 Sep 2026 that stopped the Google token refresh for nine hours.
- `setdefault` only: an explicitly set environment variable wins.
- `data\windows-ca.pem` is built by `tools\export_windows_ca.ps1` (exports `Cert:\LocalMachine\Root`, `CurrentUser\Root`, `LocalMachine\CA`, `CurrentUser\CA`, de-duplicated by thumbprint). `*.pem` and `data/` are git-ignored.
- **State on this PC:** `C:\Hangeul\BOT\data\windows-ca.pem` does **not** exist, so this block is a no-op here (the new PC does not need it). `bootstrap.py:32` does `import src` before any HTTPS call for the same reason.

**1b. Redact secrets from every log line (`src\__init__.py:25-79`).**
```python
_TOKEN_RE = _re.compile(r"bot\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}")

_SECRET_PATTERNS = (                                              # src\__init__.py:41-49
    (_TOKEN_RE, "bot<token>"),
    (_re.compile(r"(?i)(bearer\s+)(?!<)[A-Za-z0-9._~+/=-]{8,}"), r"\1<redacted>"),
    (_re.compile(r"""(?i)(apikey['"]?\s*[:=,]\s*b?['"]?)(?!<)[A-Za-z0-9._~+/=-]{8,}"""), r"\1<redacted>"),
    (_re.compile(r"sb_secret_[A-Za-z0-9_-]{6,}"), "sb_secret_<redacted>"),
    (_re.compile(r"sb_publishable_[A-Za-z0-9_-]{6,}"), "sb_publishable_<redacted>"),
    (_re.compile(r"sbp_[A-Za-z0-9_-]{16,}"), "sbp_<redacted>"),
    (_re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"), "<jwt>"),
)

def redact(text: str) -> str:            # every pattern applied in order; public: used by src\cloud and tests
    ...

class _RedactBotToken(_logging.Filter):
    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True                  # a record that cannot be formatted is passed on untouched
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True

_REDACTOR = _RedactBotToken()
for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2",
              "httpcore.proxy", "httpcore.socks", "hangeul.cloud"):
    _logging.getLogger(_name).addFilter(_REDACTOR)
```
- Why the bot token: `httpx` logs every request URL at INFO, and a Telegram API URL is `https://api.telegram.org/bot<token>/sendMessage`, so `hangeul_bot.log` held the token in plain text (anyone who could read the log could take over the bot). `%3A`: file-download URLs (`api.telegram.org/file/bot<id>%3A<secret>/...`) URL-encode the colon; missed at first, found on the first live voice note, fixed in `e205327`.
- Why the Supabase patterns (`36ae72e`): `src\cloud` publishes with the project's secret key (value in secrets\bot.env (SUPABASE_SECRET_KEY)), sent as `apikey:` and `Authorization: Bearer` headers; the CLI's personal access token (value in secrets\bot.env (SUPABASE_ACCESS_TOKEN), CLI only, `sbp_…`) and the older JWT-shaped keys (`eyJ….….…`) are caught too, wherever a request or its headers get printed. The `(?!<)` stops a line being redacted twice.
- Why so many loggers: a filter on a logger does not see its children's records, so each logger that can print a request (httpx's own, and httpcore's per-module loggers at DEBUG) and the cloud layer's `hangeul.cloud` gets one. Other loggers are not filtered.
- The request lines are kept (they help diagnose portal, Telegram and Supabase problems); only the secret becomes a marker. The filter formats the record once, replaces `msg`, clears `args` so the formatter does not re-apply them, and never drops a record (`return True`). The class name is kept from when it covered the bot token only.

**Other contents:** module docstring `"""Hangeul Admin API, Local LLM & Telegram Reporting Bot package."""`, `__version__ = "1.0.0"`. Private names use `_os`, `_Path`, `_logging`, `_re` aliases so `from src import *` exports nothing (`redact` is the one public function).

**History.** `366dec0` baseline (docstring, version, CA block: 22 lines) → `0fce479` token filter (+24) → `e205327` `%3A` form (+2 −1) → `36ae72e` `redact()`, the Supabase key/JWT patterns, eight loggers (+36 −4).

---

## 2. `src\bot\__init__.py`

One line: `"""Telegram bot and scheduler package."""`. No code, no re-exports; every caller imports submodules by full path (`from src.bot.replies import reply_long`). Unchanged since the baseline.

---

## 3. `src\bot\replies.py` — long text, Markdown fallback, stock error replies

**Purpose.** Every reply whose size grows with portal data goes through here. Telegram refuses a message over 4096 characters ("Message is too long") and refuses a whole message whose legacy Markdown it cannot parse ("Can't parse entities"); this module turns both into non-events. Created in `e0d47ab` ("Foundation"); unchanged since (also at `8317741`).

**Constants.**
| Name | Value | Meaning |
|---|---|---|
| `TELEGRAM_LIMIT` | `4096` | Telegram's per-message limit |
| `CHUNK_CHARS` | `3900` | the most a piece gets (leaves room for headers) — imported by `brief`, `scheduler`, `telegram_bot`, `performance` |
| `Send` | `Callable[[str, Optional[str]], Awaitable[Any]]` | any `send(text, parse_mode)` coroutine |
| `logger` | `logging.getLogger("hangeul.replies")` | |

**Public functions.**
| Signature | Contract |
|---|---|
| `telegram_len(text: str) -> int` | Length as Telegram counts it: UTF-16 code units, `len(text.encode("utf-16-le")) // 2` (an emoji outside the BMP counts 2). |
| `split_text(text: str, limit: int = CHUNK_CHARS) -> List[str]` | Pieces of at most `limit` Telegram characters, split **between lines**; a single line longer than `limit` is cut at its last space that fits (`_cut`). `"\n".join(pieces)` gives the text back (bar the spaces an overlong line was cut at). Blank text → `[]`. |
| `markdown_to_plain(text: str) -> str` | Legacy Markdown as plain text: unescaped `*`, `_`, `` ` `` dropped (regex `` (?<!\\)[*_`] ``), then escaping backslashes removed (regex `` \\([_*`\[]) `` → `\1`), e.g. `First\_Last` → `First_Last`. |
| `is_markdown_error(error: Exception) -> bool` | `isinstance(error, BadRequest)` and its text contains `"parse"` or `"entit"`. |
| `async send_pieces(send: Send, text: str, parse_mode: Optional[str] = "Markdown", *, first: Optional[Send] = None, limit: int = CHUNK_CHARS) -> int` | Sends every `split_text` piece through `send`. A piece refused for its Markdown is sent again as `markdown_to_plain(piece)` with `parse_mode=None`. With `first`, piece 0 goes through `first` (editing a "please wait" message); if that edit fails with `"not modified"` it counts as sent, any other `BadRequest` logs a warning and piece 0 is sent through `send` instead. Returns the number of pieces. Non-Markdown errors are **not** swallowed (re-raised). |
| `async reply_long(message, text: str, parse_mode: Optional[str] = "Markdown", *, edit=None) -> int` | `message.reply_text` for every piece; with `edit=<the ⏳ message>`, that message is edited (`edit.edit_text(piece, parse_mode=mode)`) into piece 0 and the rest are replies. The standard way every command sends its answer. |
| `async send_long(bot, chat_id, text: str, parse_mode: Optional[str] = "Markdown") -> int` | `bot.send_message(chat_id=..., text=piece, parse_mode=mode)` for every piece. (Only used by tests; the scheduler builds its own lambda.) |
| `date_error_reply(raw: str, command: str = "", reason: Optional[str] = None) -> str` | Markdown reply for a date the bot could not read. Line 1: `⚠️ I couldn't read “<raw, whitespace-collapsed, ≤60 chars, escaped>” as a date (<why>).` where `why = reason or src.dates.user_date_problem(raw, prefer_past=True) or "it is not a date"`. Line 2: ``Please send a date like `12 Sep 2026`, `yesterday` or `2026-09-12`, for example `<command> 12 Sep 2026`.`` (the "for example" part only when `command` is given). **Never falls back to another day.** |
| `portal_error_reply(what: str, error: Exception) -> str` | Markdown reply for a live read that failed: `❌ Couldn't read the portal: <src.scraper.client.portal_error_reason(error), escaped>.\n<what>: not available right now. Please try again in a minute.` `what` is the caller's own already-safe Markdown (e.g. `"Verified students for 12 September 2026"`, `"The portal's Consultant Performance page (Today)"`). **Never a 0, "none" or an empty list.** |

**Private helpers.** `_cut(line, limit) -> int` (walks the line counting UTF-16 units, returns the last space index that keeps the head within `limit`, else the hard cut, at least 1); `async _send_one(send, piece, parse_mode)` (one piece with the Markdown→plain retry; logs `"A reply piece was not accepted as Markdown (...); sent as plain text."`); `_quoted(raw, most=60)` (collapse whitespace, truncate with `…`, `escape_markdown(version=1)`).

**Design note.** Legacy Markdown entities (`*bold*`, `_italic_`, `` `code` ``) never span lines in the bot's messages, so splitting between lines never cuts an entity in half. Every formatter in the bot keeps entities on one line for this reason. `split_text` may still cut a multi-line *record* in two; where that matters (the performance leaderboard) the caller packs whole records first (`performance.message_pieces`, §6a.5).

**Reads/writes.** Nothing on disk; Telegram only through the callables it is given.

**Callers.** `telegram_bot` (almost every command), `ask.reply` / `ask.answer_*`, `performance` (`CHUNK_CHARS`, `split_text`, `telegram_len`, `portal_error_reply`), `brief.send_brief_text` / `split_brief`, `scheduler._send_alerts`, `voice._dispatch` (`date_error_reply`), `src\sheets\auto_sync.py` and `src\sheets\missing_report.py` (`split_text`).

---

## 4. `src\bot\brief.py` — the factual daily brief and the claim checker

**Purpose.** Builds the daily brief in code from live, read-only portal GETs (plus one local file, labelled "not live"). Nothing is estimated: an unreadable figure is `"not available"`, an empty section says `None today`. It replaced (in `f8fefa4`) an LLM-written "executive report" that invented passport matches, visa counts and conversion rates. The local LLM may add **one** summary sentence at the end, kept only if every claim in it checks out against the facts (`claims_problem`), which is also the gate for Jennie's spoken English. Since `5048a07` the composed `Brief` also carries what its reads returned (`reads`), which the 18:05 job hands to the Supabase layer after sending (§5.2); the text and facts never depend on it.

### 4.1 Constants
| Name | Value | Meaning |
|---|---|---|
| `NA` | `"not available"` | the only word for an unknown figure |
| `DONE` | `("Consulted", "File Opened")` | consultation statuses that count as done |
| `KNOWN_STATUSES` | `("Consulted", "File Opened", "New", "No Answer", "Wrong Number")` | the portal's consultation status tabs |
| `VERDICT_ORDER` | `("FAIL", "REVIEW", "INCOMPLETE", "PASS")` | order of document-check verdicts in section 5 |
| `MAX_REMINDERS_LISTED` | `8` | calendar reminders listed by name |
| `SUMMARY_MAX_TOKENS` | `120` | `num_predict` of the summary call |
| `SUMMARY_TIMEOUT` | `30.0` s | a warm call takes ~1 s |
| `SUMMARY_MAX_CHARS` | `350` | a longer summary is dropped |
| `READ_TIMEOUT` | `75.0` s | one portal read (the consultation page is ~2 MB) |
| `PORTAL_BUDGET` | `150.0` s | all the brief's portal reads together |
| `PORTAL_DOWN` | `"the portal did not answer"` | reason text once the portal stops answering |
| `Section` | `Tuple[List[str], List[str]]` | (Markdown lines, plain one-figure facts) |

`class Brief(NamedTuple)` (`brief.py:76`): `text: str` (Telegram Markdown), `facts: List[str]` (one plain figure a line: what the summary and Jennie may say), `reads: Optional[Dict[str, Any]] = None` (what `compose_brief`'s portal reads returned, for `src.cloud.bot_jobs.brief_batches`; None when a Brief is built by hand, e.g. in tests).

### 4.2 Small helpers
`_now() -> datetime` (now in `settings.REPORT_TIMEZONE`); `esc(value) -> str` (`escape_markdown(str(value), version=1)` — **the bot-wide Markdown escaper**, imported by `telegram_bot`, `ask`, `performance`); `brief_plain(text)` (= `markdown_to_plain`; tests only); `_fig(value)` (None → `NA`); `_plural(n, word)`; `_amount(text) -> Optional[float]` (first `\d[\d,]*(?:\.\d+)?`, commas removed); `_day(text)` (`"%d %b %Y"` parse; unused); `_na(why, default)` → `"not available (<why or default>)"`.

### 4.3 Sections (each returns `Section`)
The brief always has these five, in this order; the page behind each:

| # | Function | Signature | Portal source |
|---|---|---|---|
| 1 | `section_consultations` | `(on_day: Optional[Dict], portal_day: str, is_today: bool, why: Optional[str] = None, totals: Optional[Dict[str,int]] = None, totals_why: Optional[str] = None)` | `consult_requests.php?status=all&from=DAY&to=DAY` (via `admin_client.read_consultation_day(day)`) and its status tabs (`read_consultation_totals()`) |
| 2 | `section_verified` | `(verified: Optional[List[Dict]], portal_day: str, is_today: bool, why: Optional[str] = None)` | every page of `students.php` (`read_verified_students(portal_day, all_pages=True)`) |
| 3 | `section_portal` | `(pending: Optional[Dict], review: Optional[int], dashboard: Optional[Dict], why: Optional[str] = None)` | `students.php?status=pending`, `window_applications.php?status=under_review`, `index.php` |
| 4 | `section_calendar` | `(cal: Optional[Dict], is_today: bool, why: Optional[str] = None)` | `calendar.php` (today only) |
| 5 | `section_documents` | `(doc: Optional[Dict])` | local `settings.verification_dir()\results.json` (`read_document_check()`), labelled "not live" |

Details that matter:
- **1)** `on_day` shape (from `client.read_consultation_day`): `{"counts": {"All": n, "Consulted": n, ...}, "rows": [{"status", "handled_by", "consultant", "name", "program", "city"}...], "complete": bool}`. Figures are the portal's **own tab counts** under its date filter; rows only say who handled the done ones (`handled_by` = the row's "Last updated by", `""` shown as "no name on the portal", never credited to anyone). Lines: `• Received: N  |  Done: N (N consulted, N file opened)`, `• New / pending: N  |  No answer: N  |  Wrong number: N`, optional `• Other status: ...`, `• Done by: <counsellor> N, ...` (+ `(among the N the portal lists)` when `complete` is False). Facts: `Consultation requests received today: N`, `Consultations done today: N`, `Marked Consulted today: N`, `Marked File Opened today: N`, `Requests still new today: N`, `No answer today: N`, `Wrong number today: N`, and (only when complete) `Handled today by counsellor <name>: N`. For a past day the facts say `on the day` instead of `today`.
- `consultation_totals_line(totals, why=None) -> str`: `• All time on the portal (its own status counts): N requests, N done (N consulted, N file opened), N new, N no answer, N wrong number[, <other status> N]`. Why: the unfiltered list shows only the newest 500 requests, so counting its rows halved the real totals (fixed in `46cdf03`).
- **2)** `verified_day_problem(day, today)` = `src.dates.yearless_day_problem`: the portal writes verification times **without a year** (`"27 Sep, 17:19"`), so a day whose day-and-month has come round again since cannot be told apart. Head line `• N students  |  Total: 28,000.00 BDT (<source>)` where source is `verified income` / `verified income, or the amount paid where no income is shown` / `amounts paid`; `(the N with an amount on the portal; M without)` when some rows lack an amount. Each student: `  i. <name> — <program> — <payment_text(v)> — verified by <verifier> at HH:MM` (`_clock` extracts `\b\d{1,2}:\d{2}\b`). `payment_text` (src.scraper.parsers) shows "Paid" and "Verified income" apart when they differ.
- **3)** `_separate_line(label, value, tile, source, why)`: `• Pending payments: N (students.php?status=pending)[; the dashboard tile says T]`, or the tile when the page failed, or `not available (why)`. **Guardrail 2**: pending payments and window applications under review are two separate lines, followed by `  _(two separate figures, never added together)_`, and two separate facts. The remaining dashboard tiles are grouped by `t["group"]` (tiles whose normalised label starts with `pending payment` or equals `under review` are skipped as already shown).
- **4)** `cal` from `admin_client.get_calendar_events()`: needs `layout_ok`; uses `today_reminders` (`title`, `type`, `date_range`, `days_left`), `skipped_untitled`, `heading_count`. A page that lists entries but none could be read is `not available`, never "None today". Not today → `• shown for today only (the calendar page lists today's reminders)`, no facts.
- **5)** `read_document_check() -> Optional[Dict]`: `results.json` → `{"students": len(docs), "verdicts": Counter(verdict), "last_checked": max(checked)}`; any exception → `None` (logged at INFO). No facts: local data is never summarised.

**The fact templates, exactly.** The facts list is the whole vocabulary `claims_problem` accepts (§4.5), so a rebuild must produce these strings and no others. `{said}` is `today` for today's brief and `on the day` for a past day (`brief.py:147`, `:213`); `NA` is `not available`.

| Section | Condition | Facts (in this order) | Code |
|---|---|---|---|
| 1 | the day could not be read | `Consultation requests received {said}: not available` | `:151` |
| 1 | read, 0 received | `Consultation requests received {said}: 0` (only this one) | `:159` |
| 1 | read, some received | `Consultation requests received {said}: N`, `Consultations done {said}: N`, `Marked Consulted {said}: N`, `Marked File Opened {said}: N`, `Requests still new {said}: N`, `No answer {said}: N`, `Wrong number {said}: N`; then, only when `complete`, one `Handled {said} by counsellor {name}: N` per named counsellor | `:159`, `:182-189` |
| 2 | the student list could not be read | `Students whose payment was verified {said}: not available` | `:217` |
| 2 | read | `Students whose payment was verified {said}: N`; then, if N > 0: every row has an amount → `Total amount verified {said}: X BDT`; some rows lack one → `Total amount verified {said} (only the rows with an amount): X BDT`; no row has one → `Total amount verified {said}: not available`. `X` is `f"{sum:,.2f}"`, e.g. `28,000.00 BDT` | `:218-237` |
| 3 | always | `Pending payments: N` and `Window applications under review (a separate figure): N`. `N` is the page's count (`students.php?status=pending`, `window_applications.php`), else the matching dashboard tile (`summary["pending_payment"]`, `summary["window_apps_under_review"]`), else `not available` | `:289-292` |
| 4 | not today | none | `:300` |
| 4 | page failed, layout not recognised, or entries listed but none readable | `Calendar reminders for today: not available` | `:303-312` |
| 4 | no reminders | `Calendar reminders for today: 0` | `:313` |
| 4 | reminders | `Calendar reminders for today: N`, then one `Calendar reminders for today of type {kind}: n` per type (`r["type"]` or `Other`, most common first) | `:326-327` |
| 5 | always | none | `:345-359` |

**What is never a fact:** the other dashboard tiles (listed in section 3's lines only), the all-time consultation totals line, the per-student lines of section 2, the reminder titles, and all local data (section 5). The two tiles above are used only as a fallback value for the two section-3 facts. So the summary can never mention them without being dropped.

### 4.4 Composition and sending
- `class _PortalReads` (`brief.py:562`): the reads run **one after another** (one portal session, no parallel logins). `read(what, job)` wraps each in `asyncio.wait_for(job(), timeout=min(READ_TIMEOUT, left))`. Every failed read's exception is kept in `self.errors[what]` (added `5048a07`, for the Supabase run's failed-read list). Once a read hits `asyncio.TimeoutError`, `httpx.TransportError` or `PortalUnavailable` with `.unreachable`, `self.down = PORTAL_DOWN` and every later read is skipped with `why[what] = "not read: the portal did not answer"`; running out of `PORTAL_BUDGET` does the same ("the portal reads ran out of time"). Any other error makes only that section "not available". Why: a hung portal delays the brief by about a minute, not ten. The `what` names are `consultations`, `verified students`, `consultation totals`, `pending payments`, `window applications`, `dashboard`, `calendar` (matched by `src.cloud.bot_jobs.BRIEF_READS`).
- `async compose_brief(day: Optional[date] = None, with_summary: bool = True) -> Brief` (`brief.py:600`). Read order: consultations of the day → verified students (skipped when `verified_day_problem`) → consultation totals → pending payments → window applications → dashboard → calendar (only when `is_today`) → document check (`asyncio.to_thread`). A future `day` reads no day-specific data (`"a date in the future"`). Header: today `📋 *HANGEUL DAILY BRIEF* — 29 September 2026, 18:05 (Asia/Dhaka)`; past day `📋 *HANGEUL BRIEF FOR 12 September 2026* — read 29 Sep 2026, 10:00 (Asia/Dhaka)`; then `_Facts only, read live from the portal (read-only) unless marked otherwise. Nothing is estimated._`, blank, sections. Optional last line `🤖 _Summary by the local AI, its numbers checked against the facts:_ <summary>`. Logs one INFO line: read seconds, total seconds, characters, summary added/none. Returns `Brief(text, facts, read)` where `read` (`brief.py:657-662`) is:
  ```python
  {"day": day, "today": today, "at": now, "is_today": is_today, "mock": admin_client.mock_mode,
   "consultations": ..., "verified": ..., "verified_why": ..., "consultation totals": ...,
   "pending payments": ..., "window applications": ..., "dashboard": ..., "calendar": ...,
   "documents": ..., "why": dict(reads.why), "errors": dict(reads.errors), "down": reads.down}
  ```
  each value exactly as its reader returned it (None: not read).
- `async compose_daily_brief(day=None, with_summary=True) -> str` — the text alone (`/brief`, `/report`, dry runs). These two commands do **not** publish to Supabase; only the 18:05 job does.
- `split_brief(text, limit=CHUNK_CHARS)` = `split_text` (tests only). `async send_brief_text(send, text) -> int` = `send_pieces(send, text, "Markdown")`. `async _send_brief(bot, chat_id, text) -> int` — `bot.send_message` lambda (18:05 job and `/brief`).

### 4.5 The LLM summary and `claims_problem` (the fact gate)
- `_SUMMARY_SYSTEM` (`brief.py:364`): one- or two-sentence plain-English summary, ONLY the facts, each number next to the words of its own fact, never add/compare/total/percent/date/time, never combine pending payments and window applications, no visas/passports/intakes/conversion, no Markdown/emojis, ≤280 characters.
- `async llm_summary(facts: List[str], *, is_today: bool = True) -> Optional[str]` (`:541`): skipped (None) when no fact has a digit (portal unreadable). One `ollama_client.chat([system, user "Facts:\n- ...\n\nSummary:"], num_predict=120, timeout=30.0)`; any exception → None; else `check_summary`. With the brain not pinned (the current state) this call loads the model on demand.
- `check_summary(summary, facts: str, *, is_today=True) -> Optional[str]` (`:519`): `voice._plain` the text, strip quotes and a leading `Summary:`/`In short:`, keep the first two sentences; None if empty or > 350 chars; for a past-day brief, None if it says `today|tonight|yesterday|tomorrow|this morning/afternoon/evening` (`_RELATIVE_DAY_RE`, added `344a247`); None if `claims_problem` finds anything (logged `Brief summary dropped: <reason>.`).
- `claims_problem(text: str, facts: Iterable[str], extra_words: Iterable[str] = ()) -> Optional[str]` (`brief.py:456`) — returns why `text` may not be shown, or None. Checks, in order:
  1. empty → `"empty"`;
  2. `_FOREIGN_RE = [^\x00-\x7F‘’“”–—…\u00a0]` → `"not plain English"` (another script's number words would pass the number check);
  3. `_OFF_TOPIC_RE` (`visas?|passports?|conversion|intakes?|rates?|percent(age)?|per cent|prepared by|ytd|%`) → off-topic;
  4. `_VAGUE_NUMBER_RE` (dozen, half, twice, double, both, couple, several, few, many, most, all, every, each, some, any, more, less, average, ratio, than, compared, increased, higher, trend, record, ordinals first…thousandth, `\d+(st|nd|rd|th)`) → `"a vague or comparing count word"`;
  5. after folding `_PHRASES` (`no answer` → `noanswer`, `not available` → `notavailable`), `_NEGATION_RE` (`not|never|without|cannot|neither|nor|n't`) → `"a negation"`;
  6. numbers (digits or English words, via `voice._numbers_in`, plus a lone "one") not in the facts → `"numbers not in the facts [...]"`; non-integer decimals not in the facts → refused;
  7. every word must be a fact word, a `_STOP_WORDS` connecting word, or an `extra_words` word (after `_stem`: `ies→y`, trailing `s` dropped unless `ss/us/is`, then `_SYNONYMS` such as `inquiry/enquiry/lead→request`, `came/arrived→received`, `taka/tk→bdt`, `counselor/consultant→counsellor`) → `"words the facts do not use [...]"`;
  8. per clause (`_CLAUSE_RE` splits on `,` `.` not inside a number, `; ! ? ( ) [ ] \n`, and `and|but|while|whereas|plus|with|also|then`): the clause's numbers (a `no/none/nothing/nobody/nil` adds 0) must be the figure of the fact its keywords point to. Scoring: each shared keyword counts `Fraction(1, df[k])` (rarer keywords weigh more), ties broken by fewest fact keywords the clause does not use; the allowed numbers are the union over the best-scoring facts → otherwise `"[n] is not the figure of what it describes (...)"`.
  Used by `check_summary`, `voice._fact_problem` (Jennie's English answers) and `voice.spoken_brief`.
- The word lists (`_STOP_TEXT`, `_SYNONYMS`, `_PHRASES`, `_NEGATION_RE`, `_NOTHING_RE`, `_OFF_TOPIC_RE`, `_VAGUE_NUMBER_RE`, `_FOREIGN_RE`, `_CLAUSE_RE`) are reproduced verbatim in [06 §3.1](06_LLM_AND_JENNIE_VOICE.md).
- **Must port: the number reader lives in `voice.py`.** `brief._numbers` (`:414`) imports `voice._numbers_in` (`voice.py:900-929`) and `brief._number_word` (`:423`) imports `voice._WORD_VALUES` and `voice._WORD_SCALES` (`voice.py:1380-1381`). A rebuild without voice must still carry them; move them to a neutral module (e.g. `src\numbers.py`). What `_numbers_in(text) -> set` reads: (a) digits, `(\d[\d,]*)(?:\.(\d+))?`, the comma thousands group removed (`28,000.50` → 28000 and 50; a zero decimal part such as `.00` adds nothing); (b) English number words `zero`…`nineteen` and `twenty`…`ninety` summed, `hundred` multiplying the running value, `thousand`/`million`/`billion` closing a group, `and` skipped inside a number ("two hundred and five" → 205), and a number made of the lone word `one` ignored ("one sec"); (c) Korean numbers (`_ko_numbers_in`) only when the text contains Hangul. `brief._numbers` then adds `1` back for a lone `\bone\b`, so the brief's check does count "one".

**Error handling summary.** Nothing in `brief` raises to the caller for a portal problem: every read failure becomes `not available (<why>)` in its section. `compose_brief` can still raise for programming errors; `scheduler.send_daily_briefing` catches and logs.

**Callers.** `scheduler.send_daily_briefing` (`compose_brief`, `_send_brief`; then `bot_jobs.brief_batches` reads `Brief.reads`), `telegram_bot.brief_command` (via `scheduler` re-export), `telegram_bot.report_command` (`compose_daily_brief`, `send_brief_text`), `esc` everywhere, `voice` (`claims_problem`).

**History.** `f8fefa4` created (690 lines; also fixed dashboard tile parsing, calendar parser for the `rm-item/ev-row` layout, per-read timeouts, `/brief`) → `e0d47ab` uses `replies.split_text/send_pieces` → `46cdf03` consultations via the date filter and tab totals (dropped "latest N requests" line and `consultation_coverage`) → `344a247` past-day summary may not say "today" → `e164679`, `c17d887` verified total says what it adds up → `5048a07` `Brief.reads` and `_PortalReads.errors` for the Supabase copy (+12 −1).

---

## 5. `src\bot\scheduler.py` — the scheduled jobs

**Purpose.** One module-level `AsyncIOScheduler()` (`scheduler.py:24`, created with the scheduler's default local timezone) and every job the bot runs on a clock. Jobs that touch Google Sheets or publish the full picture run as **separate processes** so a crash, hang or memory spike in them can never take the bot down. The two in-process jobs that read the portal (the brief and the passport watcher) hand what they read to the Supabase layer **after** their own work (§5.6).

### 5.1 `setup_scheduler(bot_application) -> AsyncIOScheduler` (`scheduler.py:419`)
Called at the end of `telegram_bot.build_telegram_application()`. If `settings.ENABLE_SCHEDULED_REPORTS` is false it logs and returns without starting. Otherwise it parses `settings.DAILY_REPORT_TIME` (`"18:05"`, fallback 18:05 on any parse error), builds `tz = ZoneInfo(settings.REPORT_TIMEZONE)` (`Asia/Dhaka`), adds **seven** jobs (all `replace_existing=True, max_instances=1, coalesce=True`), calls `scheduler.start()`:

| Job id | Trigger | Callable | args | misfire_grace_time | Why |
|---|---|---|---|---|---|
| `daily_executive_briefing` | `CronTrigger(hour=18, minute=5, timezone=tz)` | `send_daily_briefing` | `[bot_application]` | 600 s | APScheduler's default grace is 1 s; a stalled moment at 18:05 must not drop the brief |
| `passport_upload_watcher` | `IntervalTrigger(minutes=30)` | `check_new_passport_uploads` | `[bot_application]` | default | one run at a time: a run with many unaudited scans audits for up to 20 min |
| `portal_sync` | `IntervalTrigger(minutes=15)` | `run_portal_sync` | — | default | portal → progress sheets + verified-documents sync (publishes its own reads through the sheet hooks, [03c](03c_FILES_sheets_verify_root_scripts.md)) |
| `missing_info_report` | `CronTrigger(hour=9, minute=5, timezone=tz)` | `run_missing_report` | — | 3600 s | daily missing-information report |
| `passport_issue_refresh` | `CronTrigger(hour=8, minute=30, timezone=tz)` | `run_issue_date_refresh` | — | 3600 s | before the 09:05 report |
| `brain_keep_warm` | `IntervalTrigger(minutes=10)` | `keep_brain_warm` | — | default | reload the LLM if Ollama lost it (no-op unless pinned) |
| `cloud_full_picture` | `IntervalTrigger(minutes=FULL_PICTURE_MINUTES=60, start_date=datetime.now(tz) + timedelta(minutes=FULL_PICTURE_FIRST_MINUTES=7.5))` | `run_full_picture` | — | default | the hourly Supabase "full picture" (§5.5a); registered always, a no-op while publishing is off |

Startup log: `Scheduler active: daily briefing set for 18:05 (Asia/Dhaka), passport watcher running every 30m, portal sync every 15m, missing-info report 09:05` + `, Supabase full picture every 60m.` when `bot_jobs.handoff.enabled()`, else `.` (it does not mention the 08:30 and 10-min jobs). Seen on 30 Sep 2026 at 22:27:37, right after `CLOUD_PUBLISH_ENABLED=true` was set; the first full picture then ran at 22:35 and the next at 23:35.

Why 7.5 minutes: the first run lands midway between the portal sync's 15-minute and the watcher's 30-minute beats (both counted from the start), so the full picture's portal reads do not overlap theirs.

### 5.2 Daily brief — `async send_daily_briefing(bot_application)` (`scheduler.py:248`)
- No `TELEGRAM_ADMIN_CHAT_ID` → warning, return. (It sends to the admin chat only; `settings.brief_recipient_ids()` / `TELEGRAM_BRIEF_CHAT_IDS` are used by the sheet jobs, not by the brief.)
- `composed = await compose_brief()`; `await _send_brief(bot_application.bot, chat_id, composed.text)`; any exception → `Failed to dispatch scheduled briefing: ...` and return (nothing is published then).
- Then, only if `settings.JENNIE_VOICE_ENABLED and settings.JENNIE_SPOKEN_BRIEF`: `voice.send_spoken_brief(bot, chat_id, "\n".join(composed.facts))` in its own try (nothing here may touch the text brief). Jennie gets the **facts**, not the text, whose dates, clock times and tile figures would let a number be said about the wrong thing. Both flags are `false` in the current `.env`.
- Last (`scheduler.py:278`): `await bot_jobs.hand_over("daily_brief", bot_jobs.brief_batches, composed)` — after everything was sent: the brief as sent (report `brief|<ISO day>`), its sections (`report_section`, scope `brief|<ISO day>`), its facts (`brief_fact`, scope `<ISO day>`) and what its reads returned (`Brief.reads`: consultation, consultation_day, verification, consultation_totals, dashboard_fact). Never raises; waits at most 30 s (§5.6).
- Re-exports `compose_brief, compose_daily_brief, _send_brief` from `brief` (`# noqa: F401 (/brief imports them from here)`).

### 5.3 Passport watcher — `async check_new_passport_uploads(bot_application)` (`scheduler.py:158`)
Audits every passport scan on the portal **once**, newest upload first, and alerts the admin chat about scans with issues.

Memory file: `ALERTED_CACHE_FILE = BOT_ROOT\data\alerted_passport_issues.json` (`:31`), `WATCHER_CACHE_VERSION = 2`, shape:
```json
{"version": 2,
 "scans": {"<uid>|passport_<uid>_<unix upload time>.<ext>":
            {"uid": "<uid>", "student_id": "HNG-YYYY-NNN", "status": "<validator status>",
             "checked": "YYYY-MM-DD HH:MM", "alert": "<Markdown block>" | null,
             "sent": false, "sent_at": "YYYY-MM-DD HH:MM"}}}
```
(On disk on 29 Sep: version 2, 301 scan entries.) The key includes the file name, and the portal names uploads `passport_<uid>_<unix time>.<ext>`, so a re-upload is a new key and is checked again; an unchanged scan is checked once, valid or not.

Algorithm:
1. No admin chat id → return. `students = await admin_client.read_students()` (every page); failure → `Passport audit check skipped: couldn't read the portal: <reason>` and return (nothing audited, nothing sent, nothing published). `listed_at = bot_jobs.now()` (the list's read time, for the Supabase copy); three lists start empty: `checked` (this run's audits), `profiles` (the student_edit.php profiles the audits read), `accepted` (the alert messages Telegram accepted).
2. `cache = load_watcher_cache()`; `current = {f"{uid}|{scan}": (student, scan)}` with `scan = passport_scan(student)`.
3. Forget keys no longer on the portal (replaced upload or removed student), unsent alerts included.
4. `todo` = current keys not in memory, sorted newest upload first (`-_upload_time`).
5. For each, stop starting new audits after `WATCHER_BUDGET_SECONDS = 20 * 60` (the rest wait for the next run). `form = {"name": details["Full Name"] or student_name, "dob": details["DOB"], "passport_no": details["Passport No"], "passport_expiry": details["Passport Expiry"]}`; `profile_before = bot_jobs.profile_now(uid)`; `result = await admin_client.audit_student_passport(uid, form, scan)` (OCR runs off the event loop since `7241465`). Exception → counted failed, retried next run. After a successful audit `bot_jobs.keep_profile(profiles, uid, profile_before)` (keeps the profile the client holds now only if it is another object than before: an audit whose profile read failed leaves the old one, which is not this read). `result["status"] in UNCHECKED_STATUSES = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE")` → nothing was checked: not alerted, **not remembered**, retried next run. Otherwise store the entry; `alert = _alert_block(...)` when `not result["is_valid"] and result["discrepancies"]`. `save_watcher_cache` after **every** audit (a restart loses none); `checked.append((s, scan, dict(form), result, bot_jobs.now()))`.
6. `pending` = remembered alerts with `sent` false, newest first → `_send_alerts(bot, chat_id, cache, pending, accepted)`. Final log: `Passport audit check: N scans on the portal, N audited this run (N with issues), N could not be checked, N waiting for the next run; N alert(s) sent in N message(s), N not sent yet.`
7. Last (`:243`): `await bot_jobs.hand_over("passport_watcher", bot_jobs.watcher_batches, students, listed_at, checked, cache, failed, accepted, profiles)` → student (scope all, complete), passport_audit (complete over the scans the list shows), passport_alert (from the memory as saved; complete over the watched scans, so a lost memory being rebuilt never deletes one), one student_profile per uid read, one notification per accepted alert message; `N passport scan(s) could not be checked` as a failed read when `failed > 0`.
8. Whole body in `try/except Exception` → `Error in check_new_passport_uploads: ...` (never raises into APScheduler).

Helpers:
- `load_watcher_cache() -> Dict` (`:43`) — missing/unreadable file, a non-dict, wrong version, or the **old uid-only list** (which had marked alerts as sent that never went out) → empty memory (every current scan checked once more).
- `save_watcher_cache(cache) -> None` (`:63`) — atomic: write `<file>.part`, `os.replace`; errors logged, not raised.
- `passport_scan(student: Dict) -> Optional[str]` (`:74`) — the newest `files` entry starting `passport_` (by `_UPLOAD_TIME_RE = r"passport_\d+_(\d{9,11})\b"`), else None. Also used by root scripts `audit_program.py` and `inspect_passports.py`.
- `_upload_time(file_name) -> int` (0 when no stamp); `_plain_name(text)` (drops the characters `` *_`[] `` and collapses spaces for use inside bold; `"(no name on the portal)"` when empty).
- `_alert_block(student, form, result) -> str` (`:91`) — one alert:
  ```
  • *Student:* *<name>* (`HNG-YYYY-NNN`, `ID <uid>`)
  • *Status:* `<status>`
  • *Issue:* <discrepancies joined by "; ", escaped>
  • 🔗 *Direct Review Link:* [Edit Student #<uid>](<HANGEUL_BASE_URL>/student_edit.php?id=<uid>)
  ```
  (a link only; the bot never edits the portal).
- `_alert_messages(blocks, limit=CHUNK_CHARS) -> List[(keys, text)]` (`:104`) — packs whole blocks into as few messages as fit (reserve = 80 + footer length). Header `🚨 *Automated Document Audit Alert*` for one alert, else `🚨 *Automated Document Audit: N alerts* (part i of n)`. Footer `_ALERT_FOOTER = "_(Strict Read-Only Alert: Please update in admin portal manually if required)_"`.
- `async _send_alerts(bot, chat_id, cache: Dict, keys: List[str], accepted: Optional[List[Tuple[str, Any]]] = None) -> Tuple[int, int]` (`:131`) — (alerts sent, messages sent). Each message via `send_pieces(..., "Markdown")`; on success marks its alerts `sent=True, sent_at=<now>`, saves, and `bot_jobs.note_sent(accepted, text)` (keeps `(text, time)` only while publishing is on); the first refused message stops sending (it and the rest stay pending for the next run). **An alert is marked sent only after Telegram accepted it.**

### 5.4 Jobs run as subprocesses
- `SYNC_LOG_FILE = <BOT_ROOT>\hangeul_sync.log` (`:340`, computed as three `dirname`s up from `scheduler.py`).
- `async _run_module(module: str, label: str)` (`:392`) — `asyncio.create_subprocess_exec(exe, "-m", *module.split(), cwd=BOT_ROOT, stdout=log, stderr=log, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=0x08000000 (CREATE_NO_WINDOW) on Windows)`, where `exe = sys.executable` with `pythonw.exe` swapped for the console-less `python.exe` twin. Output **appended** to `hangeul_sync.log`. Timeout 3600 s → `proc.kill()` and `"<label> took over an hour and was stopped."`. Logs `"<label> finished (exit N)."`; never raises.
- `async run_portal_sync()` (`:344`) → `_run_module("src.sheets.auto_sync", "Portal sync")` (sends its own Telegram summary when something changed).
- `async run_issue_date_refresh()` (`:350`) → `_run_module("src.sheets.passport_issue --refresh", "Passport issue dates")` (the portal keeps the issue date only on the edit page, so it cannot ride along with the CSV export).
- `async run_missing_report()` (`:357`) → `_run_module("src.sheets.missing_report", "Missing-information report")` (sends its own summary + Excel file).

### 5.5 The brain (local LLM) keep-warm
- `async warm_brain(attempts: int = 3, retry_after: float = 30.0) -> bool` (`scheduler.py:280`): up to 3 × `ollama_client.warm_up()`; success when `state["loaded"] and state["on_gpu"]` (logs `Brain qwen3:4b-instruct resident on the GPU: X GB, num_ctx N, ready in S s.`); partly on CPU → warning, `unload()`, sleep 30 s, retry; not loaded → "is Ollama running?". Then, if voice is enabled, `voice.prepare_fillers()`. Never raises. Returns whether the whole model is on the GPU.
- `async keep_brain_warm()` (`scheduler.py:317`): returns at once unless `ollama_client.brain_pinned()` (= `JENNIE_VOICE_ENABLED or BRAIN_ALWAYS_LOADED`; both false now, so this job is a no-op and the model loads on demand, unloading after `BRAIN_IDLE_UNLOAD = "5m"`). When pinned: `residency()`; if loaded on GPU, nothing; if partly on CPU, unload; then `warm_brain(attempts=1)`. Why: Ollama never moves a loaded model and with `keep_alive -1` never unloads it, so a model that loaded while the voice service held the GPU would answer slowly until a restart.

### 5.5a The Supabase full picture — `async run_full_picture()` (`scheduler.py:369`)
Constants `FULL_PICTURE_MINUTES = 60`, `FULL_PICTURE_FIRST_MINUTES = 7.5` (`:365-366`).
1. `if not bot_jobs.handoff.enabled(): return` — publishing is on only when `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (value in secrets\bot.env (SUPABASE_SECRET_KEY)) and `CLOUD_PUBLISH_ENABLED` are all set (`src.cloud.publish.enabled`). Silent: no log line while off.
2. `reason = src.cloud.full_picture.skip_reason()` — a quiet window of the scheduled jobs now or within 5 minutes (`LEAD_MINUTES`): **18:00-18:10** (the brief), **08:25-08:40** (issue dates), **09:00-09:10** (missing report), or a portal sync running (`data\auto_sync.lock`). Any exception in steps 1-2 → `Full picture publish could not start: <Type>: <e>` and return.
3. A reason → `Full picture publish skipped: <reason>.` and return.
4. Else `_run_module("src.cloud.full_picture", "Full picture publish")` — its own CPU-only process (`CUDA_VISIBLE_DEVICES=-1` set before torch can load; gte-small embeds only what changed) that reads, GET only with its own portal session: every page of `students.php` and `students.php?status=pending`, the consultation requests of today and yesterday and the all-time counts, `window_applications.php?status=under_review`, `index.php`, `calendar.php`, and `consult_performance.php?period=today` and `?period=month`; then publishes them in one run (job `full_picture`). It checks the quiet windows again when it starts, sends nothing to Telegram, stops itself after 45 minutes. Its log goes to `hangeul_sync.log`; the bot logs `Full picture publish finished (exit N).` First live runs: 30 Sep 22:35 (3 upserted, 779 unchanged, 0 deleted, 0 failed, 6.9 s) and 23:35. Details in [03d](03d_FILES_src_cloud.md) and [13](13_SUPABASE_PUBLISHING.md).

### 5.6 The hand-over contract (`src.cloud.bot_jobs`, called from §5.2 and §5.3)
| Function | Signature | Contract |
|---|---|---|
| `bot_jobs.now()` | `-> datetime` | now in the business time zone (read times) |
| `bot_jobs.profile_now(uid)` | `-> Optional[Dict]` | the profile `admin_client._profile_cache` holds for `uid` now; None while publishing is off (so nothing is kept then). Never raises |
| `bot_jobs.keep_profile(profiles, uid, before)` | `-> None` | appends `(uid, profile, time)` when the client now holds another profile object than `before`. Never raises |
| `bot_jobs.note_sent(accepted, text)` | `-> None` | appends `(text, time)` when `accepted` is a list and publishing is on. Never raises |
| `bot_jobs.hand_over(job, build, *args)` | `async -> Optional[Path]` | None at once when publishing is off, or in mock mode (`Supabase publish skipped (<job>): the bot is in mock mode (demo figures).`); else runs `build(*args) -> (batches, failed_reads)` and `handoff.submit(job, batches, failed)` in `asyncio.to_thread`, waiting at most `HANDOFF_WAIT = 30.0` s. `submit` writes `data\cloud\pending\<time>-<job>.json` and starts the publisher process (`python -m src.cloud.publish --from <file>`) without waiting. Timeout → `Supabase publish failed (<job>): the handoff took over 30 s (the job itself was done)`; any other error → `Supabase publish failed (<job>): its records could not be built (<Type>)` (the type only: an exception text can quote student data). **Never raises.** |

Why this shape: the bot process also runs the passport OCR (it loads torch), so it never embeds or uploads; it only builds plain dicts in a worker thread (the event loop stays free) and hands them to a separate process. A job's own work (sending the brief, saving the watcher's memory, sending alerts) is always finished before the hand-over, so publishing can never change or stop what a job does or sends.

**History.** `366dec0` baseline (uid-only watcher cache, page-1 reads, the LLM-written brief) → `4154aa5` cache path from `BOT_ROOT` instead of `os.getcwd()` → `d7a5817` spoken brief → `d9bbecc` `warm_brain`, `keep_brain_warm` and the 10-min job → `7241465` (in client/ocr_validator: OCR off the event loop, fixing ~3.5-minute freezes every half hour) → `f8fefa4` brief moved to `brief.py` → `9dcd9ad` watcher rewritten (every page: 301 scans instead of 42; uid+file memory; grouped alerts marked sent only when accepted; 20-min budget) → `344a247` `UNCHECKED_STATUSES` (a PORTAL_UNREADABLE/OCR_UNAVAILABLE scan had been remembered as audited and never checked again) → `c17d887` keep-warm only when pinned → `5048a07` brief and watcher hand-over, `run_full_picture` and job 7 → `cb16394` the watcher's profiles and accepted alert messages (`profile_now`/`keep_profile`, `_send_alerts(accepted=)`, `note_sent`) → `e4d1cea` the full picture also reads the Consultant Performance page (docstring).

---

## 6. `src\bot\ask.py` — free-text router and live answers

**Purpose.** Reads a typed (or Jennie-routed English) question on **whole words and real dates** and says which answer it asks for (`classify`); decides which view of the Consultant Performance page a performance question asks for (`performance_route`); builds the live answers that no menu command gives. Created in `7f42ad0` to replace an LLM-guessing path and substring matching ("across" matched "cross", "shipping" matched "pin", "Janan" matched January, "summary" matched March). Nothing here writes anything; every figure has its source written under it. Each `answer_*` now takes `*, reads: Optional[Dict] = None` and records what it read for the Supabase copy (§8.13); `reply` publishes after the answer is sent.

Test note: `ask` does `from src.dates import local_today` (`ask.py:37`), so a test that pins today must patch `src.bot.ask.local_today` as well as `src.dates.local_today` (`tests/test_foundation.py:136 pin_today`). The 6 date-dependent tests that passed only on 28 Sep were fixed this way.

### 6.1 Constants
`MAX_NAMES_LISTED = 30` (pending-payment names in one reply), `MAX_CALENDAR_LISTED = 25`, `ONE_DAY_KINDS = ("inquiries", "verified", "passports")` (answered one day at a time; `ask.py:380`), `SOURCE_DASHBOARD = "_Read live from the portal dashboard (index.php) just now._"`, `_CARDS = ("At a glance", "Needs attention", "Application pipeline", "Applications by program", "Top universities")`, `_STAGES` (the ten pipeline stages: `Application Received`, `Payment Verified`, `Documents Under Review`, `Documents Verified`, `University Applied`, `Admission & Tuition`, `VIN Application`, `Embassy Submission`, `Visa Result`, `Admitted / Completed`), `_STAGE_ONLY` (the seven stage names that mean the stage without the word "stage": all except Payment Verified, Documents Verified, Admitted / Completed), `_PROGRAM_KEYS` (klp/eap/bachelor/master/phd → needle `KLP`/`EAP`/`BACHELOR`/`MASTER`/`PHD`), `_PROGRAM_NAMES`, `_FILLER` (a word set: articles, question words, "students", "portal", "hangeul", "jennie", "bot"…).

### 6.2 The word regexes (`ask.py:47-152`, all built by `_re(words) = re.compile(r"\b(?:" + words + r")\b", re.I)` unless noted)
```python
_HELLO_RE = re.compile(
    r"^\W*(?:hi+|hello|hey|hiya|salam|assalamu?\s*alaikum|good\s+(?:morning|afternoon|evening|night)|thanks?|"
    r"thank\s+you|thx|ok(?:ay)?|cool|great|nice|bye)(?:\s+(?:jennie|bot|there|so\s+much|a\s+lot))?\W*$", re.I)
_PIN_RE = _re(r"pp\s*pin|pin(?:ned)?|pin\s+it|cheat\s*-?\s*sheet|command\s+list|list\s+of\s+commands|all\s+commands"
              r"|commands|menu")
_REPORT_RE = _re(r"reports?|brief(?:ing)?|summary|summari[sz]e|overview|recap|round-?up")
_CONSULT_RE = _re(r"consult(?:ation|ations|ancy|ancies)?|inquir(?:y|ies)|enquir(?:y|ies)|leads?|counsell?ors?"
                  r"|consultants?")
_CROSS_RE = _re(r"cross[\s-]*check(?:ed|ing|s)?|crosscheck(?:ed|ing|s)?|audit(?:ed|ing|s)?")
_CROSS_FIELD_RE = _re(r"father'?s?|mother'?s?|address(?:es)?|parents?'?|dob|date\s+of\s+birth")
_CHECK_RE = _re(r"check(?:ed|ing|s)?")
_PASSPORT_RE = _re(r"passports?|mrz")
_VERIFY_RE = _re(r"verif(?:y|ied|ies|ication|ications)")
_PAY_RE = _re(r"pay(?:s|ing|ment|ments|ed)?|paid")
_PENDING_WORD_RE = _re(r"pending|waiting|awaiting|outstanding|due|unconfirmed|approval")
_UNPAID_RE = _re(r"unpaid|not\s+(?:yet\s+)?paid|payment\s+approvals?")
_DOCS_RE = _re(r"docs?|documents?|papers?|files?|uploads?")
_DOC_STATE_RE = _re(r"review(?:s|ed|ing)?|verif\w*|waiting|pending|approv\w*|reject\w*|check(?:ed|ing)?|unverified"
                    r"|queue|to\s+verify")
_UNDER_REVIEW_RE = _re(r"under\s+review|in\s+review|being\s+reviewed|reviewing")
_APPLICATION_RE = _re(r"app(?:lication)?s?")
_WINDOW_APP_RE = _re(r"window\s+app(?:lication)?s?|admission\s+window\s+app(?:lication)?s?")
_MISSING_RE = _re(r"missing|incomplete")
_STAGE_RE = _re(r"stages?")
_PIPELINE_RE = _re(r"pipeline|funnel")
_ADMIT_RE = _re(r"admit(?:ted|s)?")
_CALENDAR_RE = _re(r"calendar|events?|deadlines?|due|dhl|shipping|shipments?|ship|courier|reminders?|schedule[sd]?"
                   r"|closing|closes|opening|application\s+(?:windows?|periods?)|open\s+for\s+applications?"
                   r"|accepting\s+applications?|(?:admissions?|applications?)\s+(?:is\s+|are\s+)?open")
_OPEN_WINDOWS_RE = _re(r"(?:open|active|draft)\s+(?:admission\s+)?windows?")
_VISA_RE = _re(r"visas?")
_INTAKE_WORD_RE = _re(r"intakes?|batch(?:es)?")
_MONTH_WORDS = (r"january|february|march|april|may|june|july|august|september|october|november|december"
                r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec")
_INTAKE_RE = re.compile(rf"\b(?P<month>{_MONTH_WORDS})\.?\s*(?:,\s*)?(?P<year>20\d\d)\b(?!\s*[-/.]\d)", re.I)
_PROGRAM_RE = _re(r"programs?|programmes?|courses?|klp|eap|bachelor'?s?|masters?|master'?s|degrees?|phd"
                  r"|language\s+program")
_UNIVERSITY_RE = _re(r"universit(?:y|ies)|unis?|colleges?")
_STUDENTS_RE = _re(r"students?|applicants?|people|enrol(?:l)?ments?|admissions?")
_APPLIED_RE = _re(r"registered|registrations?|registering|sign(?:ed)?[\s-]*ups?|signups?|joined|enrolled"
                  r"|new\s+(?:students?|applicants?|applications?)|applied|applications?\s+(?:received|came)")
_ATTENTION_RE = _re(r"urgent|alerts?|attention|to[\s-]*dos?|action\s+items?|needs?\s+attention")
_STATS_RE = _re(r"stats|statistics|dashboard|figures|kpis?|metrics|numbers")
_REJECT_RE = _re(r"reject\w*")
_APPROVE_RE = _re(r"approv\w*")
_MOST_RE = _re(r"most|top|biggest|largest|popular|highest|leading|best")

# Performance (ask.py:98-152; added bbd8f98, rewritten ce23535/314afdb)
_PERFORMANCE_WORDS = (r"perform[ae]nces?|perfom[ae]nces?|performaces?|perfromances?|preformances?"
                      r"|productivity|leader[\s-]?boards?|performers?")
_PERFORMANCE_RE = _re(_PERFORMANCE_WORDS +
                      r"|how\s+(?:did|does|do|has|have|is|are|was|were)\s+(?:the\s+|our\s+|my\s+)?(?:whole\s+)?"
                      r"(?:team|staff|everyone|everybody|counsell?ors?|consultants?)\s+"
                      r"(?:do|done|doing|did|perform(?:ed|ing)?|go|going|gone)"
                      r"|(?:team|staff)(?:'s)?\s+(?:activity|stats|statistics|report|summary|scores?|results?)")
_PERFORMANCE_WORD_RE = _re(_PERFORMANCE_WORDS + r"|perform(?:s|ed|ing)?")
_OTHER_MONTH_RE = _re(r"(?:last|previous|past|next|coming|following)\s+(?:\w+\s+)?months?(?:'s)?|months")
_THIS_MONTH_RE = _re(r"monthly|month(?:'s)?|mtd")
_OTHER_PERIOD_RE = _re(r"all[\s-]*time|overall|lifetime|ever|in\s+total|altogether"
                       r"|ytd|(?:(?:this|the|current)\s+)?year[\s-]+to[\s-]+date"
                       r"|(?:last|previous|past|next|coming|following)\s+years?(?:'s)?|(?:a\s+)?years?\s+(?:ago|back)"
                       r"|yearly|annual(?:ly)?|(?:(?:this|the|current|a)\s+)?year(?:'s)?|quarter(?:ly)?"
                       r"|custom(?:\s+range)?|range")
_WEEK_RE = _re(r"(?:(?:this|current|last|previous|past|next)\s+)?(?:weekly|weeks?(?:'s)?|fortnight(?:ly)?)|wtd")
_PERIOD_NAMES = ((re.compile(r"all time|overall|lifetime|ever|in total|altogether"), "all time"),
                 (re.compile(r"(?:(?:this|the|current) )?(?:ytd|year to date)"), "the year to date"),
                 (re.compile(r"(?:this|the|current) year|year"), "this year"),
                 (re.compile(r"yearly|annual(?:ly)?"), "yearly figures"),
                 (re.compile(r"quarter(?:ly)?"), "a quarter"),
                 (re.compile(r"weekly"), "weekly figures"),
                 (re.compile(r"fortnight(?:ly)?"), "a fortnight"),
                 (re.compile(r"wtd"), "the week to date"),
                 (re.compile(r"custom(?: range)?|range"), "a custom range"))
_THIS_MONTHS_RE = re.compile(r"\b(this|current)\s+months\b")          # "this months" (no apostrophe) = this month's
_THE_MONTH_RE = re.compile(r"\b(?:this|the|current)\s+month(?:'s)?(?:\s+of)?\b")
_YEAR_WORD_RE = re.compile(r"(?<![\w/.:-])(?:19|20)\d\d(?![\w/:-]|\.\d)")   # a year alone, not in "HNG-2025-001" / "2025-09-01"
_OTHER_YEAR_RE = re.compile(r"\b(?:(?:last|previous|past|next|coming|following)\s+years?|years?\s+ago"
                            r"|a\s+year\s+(?:ago|back))\b")
_CROSS_WORD_RE = _re(r"cross[\s-]*check(?:ed|ing|s)?|crosscheck(?:ed|ing|s)?")
_CALENDAR_TOPIC_RE = _re(r"calendar|events?|deadlines?|dhl|shipping|shipments?|courier|reminders?")
```
Why the misspellings: the owner writes "performence" (the request that started the feature said it twice), "perfomance", "this months", "todays"; the review found they classified as `unknown` and `314afdb` added them. Still whole words, so "outperform", "outperformance" and "performing arts" match nothing.

Also `_DAY_NUMBERS_RE` (`ask.py:192`): numbers that are part of a date (`12 Sep`, `Sep 12`, `2026-09-12`, `12/9`), removed before looking for a 2–5 digit student id.

Word helpers: `_words(text)` (`[a-z0-9]+(?:'[a-z]+)?`), `_leftover(text, *drop)` (words that are neither filler nor matched), `_stage_named(low) -> List[str]` (stages whose words appear; "applied to a university" → University Applied), `_program_filter(low) -> Optional[(key, needle)]`.

### 6.3 Date windows
- `class Window(NamedTuple)` (`ask.py:221`): `first: date`, `last: Optional[date]` (None = open-ended "coming up"), `label: str`; `span()` → `'Mon 28 Sep – Sun 04 Oct 2026'` / `'Mon 28 Sep 2026'` / `'from Mon 28 Sep 2026 on'`; `title()` → `'this week (Mon 28 Sep – Sun 04 Oct 2026)'`.
- `date_window(text: str, today: Optional[date] = None, *, forward: bool = True, months: bool = True) -> Tuple[Optional[Window], Optional[str]]` (`ask.py:266`): `(Window, None)`, `(None, None)` when no date is named, `(None, why)` for a date-like part that cannot be read (`"31 Sep: September has 30 days"`). Tries, in order: a range (`_RANGE_RE`: `from/between A to/until/till/through/thru/and/–/—/ - B`, both sides via `parse_user_date`; **since `a721066`**, read past-facing, an end that came out before the start is re-read forward when that lands on or after the start, so on 29 Sep "1 Sep to 30 Sep" is 1–30 Sep 2026, not 30 Sep 2025 – 1 Sep 2026); one date (`src.dates.parse_user_date`); a hard `user_date_problem` (contains `:` or "it names more than one"); `weekend`; `next week`; `last/previous/past week`; `this/the/current week` or bare `week` (not with a span); `next month`; `last month`; `this month`; `_SPAN_RE` `next|coming|upcoming|following|past|last|previous N days|weeks` (N digits or `_NUMBER_WORDS`, 1–400 days); `coming up|upcoming|soon|ahead|from now on|future|next` → `Window(today, None, "coming up")`; a weekday (`this|next|last|coming <weekday>`); a month alone (`_MONTH_ALONE_RE`, only with `months=True`; bare "may" needs a year or `in/during/for may`); finally `has_date_hint` → `(None, problem or "it is not a date")`. `forward=True` (deadlines): this week/month run from today to their end and a month alone is the coming one; `forward=False`: from their start to today and the latest month not after today.
- `_when(low, today) -> (day, window, problem)` (`:383`) — `date_window(..., forward=False, months=False)`: a one-day window → the day; an open-ended window → nothing ("upcoming" means nothing for a past day); a month without a day is a date that cannot be read here.

### 6.4 `classify(text: str, today: Optional[date] = None) -> Route` (`ask.py:529`)
`class Route(NamedTuple)` (`:370`): `kind: str`, `day: Optional[date] = None`, `window: Optional[Window] = None`, `topic: str = ""`, `words: str = ""`, `problem: Optional[str] = None`. Text is lower-cased, `’`→`'`, whitespace collapsed. **Tried in this exact order (first match wins):**

| # | Test | Route |
|---|---|---|
| 1 | empty | `unknown` |
| 2 | `_HELLO_RE.match` (whole message is a greeting/thanks) | `hello` |
| 3 | starts with `/report` or `/brief` | `report` |
| 4 | `_PIN_RE` | `pin` |
| 5 | `_PERFORMANCE_RE` and not `_names_another_topic(low)` | `performance_route(low, today)` (§6.5) — **unless** that route names another single day (no topic, a `day`) and the words say neither performance itself (`_PERFORMANCE_WORD_RE`) nor anything but consultations/verifications (`_CONSULT_RE` or `_VERIFY_RE`): then fall through, so "how did the counsellors do yesterday" is that day's `inquiries`, while "consultant performance yesterday" stays `performance` |
| 6 | `_CROSS_RE` or `_CROSS_FIELD_RE` or (`_CHECK_RE` and `_VERIFY_RE`) | `crosscheck`, with `window` from `_when` only when no 2–5 digit number remains after removing date numbers |
| 7 | `_PASSPORT_RE` | `passports` (day/window/problem) |
| 8 | `_UNPAID_RE` or (`_PAY_RE` and `_PENDING_WORD_RE`) | `pending` |
| 9 | `_stage_named(low)` non-empty | `dashboard`, topic `pipeline`, words `"Stage A\|Stage B"` (the stage names joined by a pipe) |
| 10 | `_DOCS_RE` and (`_DOC_STATE_RE` or `_UNDER_REVIEW_RE`) and not `_MISSING_RE` | `dashboard`/`documents` |
| 11 | `_CONSULT_RE` | `inquiries` (day/window/problem) |
| 12 | `_VERIFY_RE` | `dashboard`/`verified_total` when `in total`, `overall`, `altogether`, `all time`, `so far`, `ever`, `in all`, `on record` and no date hint and no today/yesterday/tonight; else `verified` (day/window/problem) |
| 13 | `_MISSING_RE` | `missing` |
| 14 | `_PIPELINE_RE` | `dashboard`/`pipeline` |
| 15 | `_ADMIT_RE` | `admitted` |
| 16 | `_STAGE_RE` | `stage` |
| 17 | `_VISA_RE` | `dashboard`/`visa` |
| 18 | `_UNDER_REVIEW_RE` or `_WINDOW_APP_RE` | `window_review` |
| 19 | `\baccepted\b` / `\bsubmitted\b` with `_APPLICATION_RE` | `dashboard`/`accepted` or `submitted` |
| 20 | `_OPEN_WINDOWS_RE` | `dashboard`/`windows` |
| 21 | `_CALENDAR_RE` | `calendar` |
| 22 | `_INTAKE_RE` not preceded by a day number (so `07 Sep 2026` is a date), or `_INTAKE_WORD_RE` | `intake`, words `"MARCH 2027"` (upper-cased full month + year) |
| 23 | `_APPLIED_RE` | `dashboard`/`applied` for this/the/current week or month; else `applied` with day/window/problem; else `dashboard`/`applied` |
| 24 | (`_PROGRAM_RE` and `_STUDENTS_RE`) or `per/by/each/every/across program` | `dashboard`/`program` |
| 25 | `_UNIVERSITY_RE` and (`_MOST_RE` or `_STUDENTS_RE` or per/by university) | `dashboard`/`university` |
| 26 | `_ATTENTION_RE` | `dashboard`/`attention` |
| 27 | `_STUDENTS_RE` and nothing left but filler | `dashboard`/`total_students` |
| 28 | `_REPORT_RE` | `report` |
| 29 | `_STATS_RE` | `stats` |
| 30 | — | `unknown` |

`_names_another_topic(low) -> bool` (`ask.py:490`): true when the words name a subject the Consultant Performance page does not show (it shows consultancies, files opened, conversion and docs ready per consultant): `_UNPAID_RE` or (`_PAY_RE` and `_PENDING_WORD_RE`), `_UNDER_REVIEW_RE`, `_WINDOW_APP_RE`, `_OPEN_WINDOWS_RE`, `_INTAKE_WORD_RE`, `_PROGRAM_RE`, `_UNIVERSITY_RE`, `_stage_named`, `_STAGE_RE`, `_PIPELINE_RE`, (`_DOCS_RE` and (`_DOC_STATE_RE` or `_UNDER_REVIEW_RE`)), `_MISSING_RE`, `_ADMIT_RE`, `_VISA_RE`, `_CALENDAR_TOPIC_RE`, `_PASSPORT_RE`, `_CROSS_WORD_RE`, `_CROSS_FIELD_RE`, `_APPLIED_RE`. So "how is the team doing with pending payments" is `pending`, "academic performance of the March 2027 intake" is `intake`. "March 2027" alone is no intake here, so "performance for September 2026" stays a month.

`classify` reads nothing from the portal. The dispatcher that acts on a Route is `telegram_bot.handle_natural_language_message` (§8.10).

### 6.5 Performance routes (`ask.py:395-526`)
- `performance_route(text: str, today: Optional[date] = None) -> Route` (`:395`) — always `kind="performance"`. `topic="today"` (no day named, or today) or `"month"` (this month so far: "this month", "monthly", "month's", "mtd", the month's own name, "1 Sep to 30 Sep" on 30 Sep; on the 1st, "this month" is that one day). Anything else has **no topic**, and carries the `day`, the `window`, the `words` (a period by a readable name) or the `problem` of an unreadable date; it is answered with `performance_other_reply`, **never with a stand-in period**. Steps: (1) `this/current months` → `month's`; (2) `_OTHER_MONTH_RE` → the window `date_window` reads, else words `"another month"`; (3) `_WEEK_RE` → a multi-day window if one is named, else words `_period_name(<week words>)` — the page's This Week is never Today, even on a Monday; (4) `date_window(low, today, forward=False)`: a window starting on the 1st of this month and reaching today → `_this_month_route`; a one-day window → `day` (topic `today` when it is today); another window → `window`; (5) "month" with no other date-like part → `_this_month_route`; (6) `_OTHER_PERIOD_RE` → words `_period_name(...)`; (7) a year alone (`_YEAR_WORD_RE`) → words `"2025"`; (8) a date problem → `problem`; (9) else topic `today`. Steps 5-7 are skipped when the date problem is a hard one (contains `:` or starts `it names`).
- `_period_name(said) -> str` (`:445`): the period as the reply says it back, via `_PERIOD_NAMES` (`ever`/`overall`/`lifetime` → `all time`; `ytd` → `the year to date`; `this year's` → `this year`; `wtd` → `the week to date`; `custom` → `a custom range`); anything else as written (`yearly`, `last week`).
- `_other_period_named(low, today) -> str` (`:453`): the words that name a month or year other than today's (`august`, `september 2025`, `2025`, `last year`), joined by `, `; "May" counts only as `May 2026`, `in/during/for May` or `the month of May`.
- `_this_month_route(low, today, window=None) -> Route` (`:473`): topic `month` unless the words also name another month or year; then the day or span those words name without "this/the month", else the words themselves, with no topic ("performance for the month of august" is August; "performance this month 2025" is "2025").
- `performance_other_reply(route: Route) -> str` (`:508`), Telegram Markdown:
  ```
  📈 /performance\_today and /performance\_month show the portal's Consultant Performance page for *today* and for *this month*<asked>.
  The page itself (Leads › Performance, consult\_performance.php) also offers This Week, All Time and a custom range: open it on the portal for those.
  ```
  `<asked>` is ` (I couldn't read the date there: <problem>)`, `, and you asked about <window.title()>`, `, and you asked about Tue 29 Sep 2026` (a day, `%a %d %b %Y`), `, and you asked about <words>`, or nothing. The bot never uses the page's Custom range form, so it reads nothing for these.

Routes as they come out (run on 30 Sep 2026, `ask.classify`):

| Words | Route |
|---|---|
| `performance today`, `todays performence`, `how did the team do today`, `team activity`, `performance`, `/performance` with no words | topic `today` |
| `performence this month`, `this months performance`, `monthly leaderboard`, `top performer this month` | topic `month` |
| `performance yesterday`, `consultant performance yesterday` | no topic, day 29 Sep → other-period reply |
| `how did the counsellors do yesterday` | `inquiries`, day 29 Sep (that day's own answer) |
| `performance last week` | window last week (21–27 Sep) → other-period reply |
| `this week performance` | window this week (28–30 Sep) → other-period reply |
| `all time performance` / `ytd performance` | words `all time` / `the year to date` |
| `performance for the month of august` | window August 2026 |
| `month performance 2025` | words `2025` |
| `performance 31 Sep` | problem `31 sep: September has 30 days` |
| `how is the team doing with pending payments` | `pending` |
| `outperform` | `unknown` |

### 6.6 Dashboard facts (index.php)
- `class Fact(NamedTuple)` (`:657`): `group`, `label`, `value: Optional[int]`, `text`, `note = ""`; `line()` → `'Total students (Direct / legacy pipeline): 330'` (with `— note` when present). One fact a line is what the LLM and Jennie see.
- `dashboard_facts(html: str) -> List[Fact]` (`ask.py:683`): tiles from `src.scraper.parsers.parse_hangeul_live_dashboard(html)["tiles"]` (`{"group","label","value","text"}`), then, on `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (Cloudflare's hidden e-mail addresses put back first, `9ead47d`), for each `.card` whose `.card-title` starts with one of `_CARDS`: `.gl` items (`.gl-l` label, `.gl-v` value); `.pipe-row` items (`.pipe-top strong` label, `.pipe-c` value); `.wf-item` items that are not `.pipe-row` (`.wf-info strong` label, `.wf-info span` note, `.wf-count` value). `_number` accepts only `\d[\d,]*`. Also called by `src.cloud.backfill` for the full picture (must keep).
- `_find(facts, group, label)` (case/spacing-insensitive, group by prefix), `_group(facts, group)`, `_fact_line(f, esc)` → ``• <label> — <note> (<group>): `<text>` ``.
- `async _dashboard() -> List[Fact]` (`:770`): `admin_client.fetch_html("index.php", timeout=30.0)`, parse in a thread; no facts → `PortalUnavailable("index.php: none of the dashboard's figures could be read (layout not recognised)")`.
- `_dashboard_answer(route, facts, query) -> str` (`:779`) per topic: `total_students` (Direct / legacy → Total students, plus "By program" from Applications by program); `verified_total` (Direct / legacy → Verified, and a hint to ask for one day); `program` (filtered to one program unless "per/by/each/every/across/all"); `university` (Top universities, `• *Most students:*` when asked "most/top"); `applied` (At a glance "Applied this week/month", filtered by week/month words); `documents` (Rejected documents / Docs approved + Total docs / Docs to review + Documents Under Review); `pipeline` (Application pipeline, filtered to the named stages); `attention` (Needs attention card); `visa` (says the portal has **no count of approved visas**, then shows the VIN Application / Embassy Submission / Visa Result / Admitted stages and the Accepted tile, each labelled for what it is); `accepted` / `submitted` / `windows` (tiles `accepted`, `submitted apps`, `open windows` / `draft windows`). A figure the page lacks: `• <X>: not available (the dashboard does not show it right now)`. Ends with `SOURCE_DASHBOARD`.

### 6.7 The live answers
| Signature | Reads | Kept for Supabase (`reads`) | Reply |
|---|---|---|---|
| `async answer_dashboard(route, query, *, reads=None) -> str` (`:870`) | index.php | `facts` | `_dashboard_answer`, or `portal_error_reply("The dashboard's figures", e)` |
| `async answer_pending(*, reads=None) -> str` (`:882`) | `admin_client.read_student_pages({"status": "pending"})` (every page) + `parse_pending_payments(pages[0])["badge"]` + `parse_students_page` per page, de-duplicated by uid | `pending=(students, badge)` | `💳 *Pending payments*`, `` • Pending payments: `N` (students.php?status=pending, every page read) ``, up to 30 names (`` i. *<name>* (`HNG-…`) — program, intake — applied <date> — stage <stage> ``), a warning for rows whose own Payment column is not Pending (not counted), the portal badge compared, and `_Window applications under review are a separate figure, never added to this one._`. A row counts only when its `payment_status` letters equal `pending`. `StudentListLayoutError` → `PortalUnavailable`. |
| `async answer_window_review(*, reads=None) -> str` (`:937`) | `read_window_apps_under_review()` + the dashboard's `Under review` tile | `facts` (the dashboard only) | `` • Window applications under review: `N` (window\_applications.php, each row's own status) `` plus the tile cross-check; "_Pending payments are a separate figure, never added to this one._" |
| `async answer_intake(route, query, *, reads=None) -> str` (`:975`) | `admin_client.read_students()` (every page; the dashboard has no intake figure) | `students` | one intake (`🗓 *MARCH 2027 intake*`, count, by program) or all intakes by count; optional program filter; source line with the number of students read |
| `async answer_applied(route, *, reads=None) -> str` (`:1009`) | `read_students()` | `students` | students whose Applied date (`src.dates.parse_portal_date(applied_date or applied_on)`) falls in the day/window; unreadable dates counted and reported, not included |
| `async answer_unknown(query, *, reads=None) -> str` (`:1038`) | index.php | `facts` | first `ollama_client._answer_query_fallback(query, lines)` (facts whose **whole label** the question names, no LLM); else `ollama_client.answer_agent_query(query, lines)` (the LLM only **picks** facts by number, JSON; shown word for word, so no figure is the LLM's); else `cant_answer()` |
| `async reply(message, route, query) -> None` (`:1065`) | — | owns `reads = {}` | Sends `🤔 _Reading the live portal..._`, runs the answer for `route.kind` (`pending`, `window_review`, `dashboard`, `intake`, `applied`, else `unknown`) with `reads=reads`, any exception → `portal_error_reply("The answer", e)`, then `reply_long(message, text, edit=status)`, **then** `command_hooks.publish(reads)` (not awaited) |

Stock texts: `CANT_ANSWER` (`:736-747`, the list of commands that can answer; `bbd8f98` added a performance line (`• The whole team's performance: /performance\_today · /performance\_month`); `ce23535` reworded it to `• The portal's Consultant Performance page (tiles, top performer, leaderboard): /performance\_today · /performance\_month`, the text at `ask.py:745`), `HELLO` (`👋 Hi! I read the Hangeul portal live for you. Ask me things like …` + `CANT_ANSWER`), `cant_answer(why=None)` → `🤷 I can't answer that from the portal yet[ (<why>)].\n<CANT_ANSWER>`, `one_day_reply(kind, window)` → `📅 <Consultations are / Verified payments are / Passport cross-checks are> counted one day at a time, and you asked about <window.title()>.\nPlease send the day you want (e.g. `<first day>`), or use <command> <date>.`

### 6.8 Calendar (`calendar.php`)
- `class CalItem(NamedTuple)` (`:1097`): `title`, `kind` (`"DHL to send"`, `"Application period"`, …), `where` (university), `start: Optional[date]`, `end: Optional[date]` (closing / DHL-due day), `done: bool`, `note` (program or free text), `id: str = ""` (the portal's event id).
- `class CalendarQuery(NamedTuple)` (`:1108`): `window`, `deadlines: bool`, `dhl: bool`, `words: List[str]`, `problem: Optional[str]`, `default: bool` (nothing asked beyond the calendar itself → today's view).
- `calendar_query(text, today=None) -> CalendarQuery` (`ask.py:1127`): strips `/calendar|/events|/deadlines`; `date_window(forward=True)`; `deadlines` = `deadlines?|due|closing|closes?|close|last day|expir…|submit… by`; `dhl` = `dhl|shipping|shipments?|ship|courier|parcels?`; `words` = what is left after `_CAL_FILLER_RE`, month and weekday names, digits and `_FILLER`; with words/dhl/deadlines but no date → `Window(today, None, "coming up")`.
- `_ev_items(html) -> Optional[List[CalItem]]` (`:1209`): the month's event list the page carries as data, found with `\bvar\s+EV\s*=\s*` and decoded with `json.JSONDecoder().raw_decode`; per event keys `id`, `title`, `type` (`dhl` → "DHL to send", `period` → "Application period", else title-cased), `uni`, `start`, `end` (ISO; `end` defaults to `start`), `done`, `notes`.
- `_cal_day(day, month_word, year, near)` (the date of that day nearest `near`, or in `year`), `_CAL_DATE_RE = (\d{1,2})\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?`, `_cal_range(text, near)` (`'26 Sep–05 Oct'`, `'07 Oct – 14 Oct 2026'`; crossing a year handled), `_status_days(status, today)` (`Opens in N days`, `Opens today/tomorrow`, `Closes in N days`, `In N days`, `Today`, `Tomorrow` → start or end).
- `calendar_items(html, today=None) -> Tuple[List[CalItem], bool]` (`ask.py:1243`): merges the EV list, `parse_calendar_events(html)["today_reminders"]` and `["upcoming_events"]` (the 45-day timeline; rows whose status says done/completed are skipped). An entry is matched **by the portal's event id** when both have one; else by title key, start and note. Two different ids are never one item (a university's Master's and Bachelor's periods with one title stay two; fixed `e164679`). Returns `(unique items, layout recognised)`. Also called by `src.cloud.backfill` for the full picture (must keep).
- `_when_due(item, today)` → `closes *today* (Tue 29 Sep)`, `due tomorrow (…)`, `closed …`, `was due … (not marked done)`, `closes Fri 02 Oct (3 days left)`, `opens …`, `end date not shown`.
- `calendar_answer(items, q, today) -> str` (`:1317`): filters (not done; DHL; all search words in title/where/kind/note; window overlap, or for deadlines the end inside the window), sorts by end/start, heads `📅 *<Deadlines|DHL shipments|Calendar items>[ matching “…”][ — <window title>]*`, count line whose words say where they stand (`DHL shipments still to send`, `Deadlines still open`, `Deadlines already passed`; Jennie speaks from this line), up to 25 items, `ℹ️ None on the calendar …`, the done items it left out (`_Not counted, marked done on the portal: …_`, added `c17d887`), and for deadlines the next one after the window. Last line `_Read live from calendar.php: today's reminders, the 45-day timeline and the month's event list._`
- `async answer_calendar(q, *, reads=None) -> str` (`:1395`): `fetch_html("calendar.php")`, `calendar_items` in a thread, layout not recognised → `PortalUnavailable`; errors → `portal_error_reply("The calendar", e)`; keeps `calendar=items` for Supabase.

**Error handling.** Every `answer_*` catches its read errors and returns `portal_error_reply(...)` (logged at WARNING) — never a 0, never an empty list standing for "could not read". A failed read keeps nothing in `reads`.

**Callers.** `telegram_bot.handle_natural_language_message` (`classify`, `reply`, `HELLO`, `one_day_reply`, `ONE_DAY_KINDS`, `_CROSS_FIELD_RE`, `performance_other_reply`), `telegram_bot.performance_command` (`performance_route`, `performance_other_reply`), `telegram_bot.calendar_command` (`calendar_query`, `answer_calendar`), `telegram_bot.alerts_command` (`reply(..., Route("dashboard", topic="attention"), "/alerts")`), `telegram_bot.parse_user_report_intent` (`classify`), `voice._dispatch` / `voice._answer_voice` (`classify`, `calendar_query`, `ONE_DAY_KINDS`), `src.cloud.backfill` (`dashboard_facts`, `calendar_items`).

**History.** `7f42ad0` created (1137 lines) → `e164679` calendar event ids, time-then-end-date ranges, "still open / already passed" counts, full timeline → `c17d887` dated calendar answers name the done items left out → `2b6798f` `reads=` on every answer, `reply` publishes after the answer → `9ead47d` `dashboard_facts` decodes Cloudflare's e-mails → `bbd8f98` the performance route (first form, self-computed report) → `a721066` "this months", no stand-in month, other topics keep their routes, `date_window`'s one-year range → `ce23535` performance = the portal page: `performance_route`, `performance_other_reply` (This Week, All Time, custom range) → `314afdb` the owner's spellings, `_PERFORMANCE_WORD_RE` for another day, ytd / this year / wtd, `_period_name` → `e5e532e` merged with the Supabase side without a conflict.

---

## 6a. `src\bot\performance.py` — the portal's Consultant Performance page (new)

**Purpose.** "Performance", as the owner means it: the portal's own **Consultant Performance** page (Leads › Performance, `consult_performance.php`), read live for `/performance_today` and `/performance_month` (also `/perf_today`, `/perf_month`, `/performance [today|month]` and the free-text routes). **Only this page's data is shown; nothing is counted from other pages.** One read-only GET of `consult_performance.php?period=today` or `?period=month` (the page's own period links; its Custom range form is never used). Every figure is the portal's own, exactly as printed (`17.9`, `18%`, `149.5`). Where the page disagrees with itself a ⚠️ line says so; nothing is corrected. A page that cannot be read, or whose layout is not recognised, is said plainly (`Couldn't read the portal: ...`), never shown as zeros. After the reply, the page read is published to Supabase as kind `consultant_performance` (§8.13).

Why it exists in this form: on 29 Sep 21:12 the owner asked for today's and this month's performance "for all"; the first build (`bbd8f98`, `a721066`, deployed 30 Sep 10:31) **computed** its own team and per-person tallies from consultation requests and verified payments. On 30 Sep 13:11 the owner corrected that: performance means the portal's page (4 tiles, a top-performer card, a leaderboard). `ce23535` rewrote the module and removed the self-computed code; `314afdb` fixed the review findings; both deployed 30 Sep 14:06. An independent live check matched 34/34 + 9/9 figures.

### 6a.1 Imports and constants (`performance.py:31-51`)
Top level: `calendar, logging, re, time`, `date`, `src.bot.brief.esc`, `src.scraper.client.PERFORMANCE_PAGE` (`"consult_performance.php"`, `client.py:57`) and `PERFORMANCE_PERIODS` (`{"today": "Today", "month": "This Month"}`, `client.py:58`), `src.scraper.parsers._label_key` (a label compared by meaning: case, spacing, punctuation and a plural last word ignored). Logger `hangeul.performance`.

| Name | Value | Meaning |
|---|---|---|
| `KINDS` | `tuple(PERFORMANCE_PERIODS)` = `("today", "month")` | the two periods the bot reads |
| `RULE` | `"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"` (28 × U+2501) | the rule line, as in the cheat-sheet |
| `_TILE_EMOJI` | `(("consultanc", "🎧"), ("file", "📂"), ("conversion", "🎯"), ("doc", "📋"))` | a tile's emoji by its label key's first word (the page's own icons: headset, folder, percent, clipboard); anything else `•` |
| `_TILE_COLUMN` | `(("consultanc", "consultancies"), ("file", "files_opened"), ("doc", "docs_ready"))` | tiles that are the total of a leaderboard column |
| `_TOP_FIGURES` | `("score", "conversion", "files_opened", "consultancies")` | the top card's figures compared with the crowned row |
| `_RANGE_START_RE` | `^\s*(\d{1,2})\s+([A-Za-z]{3,9})\.?` | the first day of the page's range text |

### 6a.2 What it is given: the page dict
From `admin_client.read_consult_performance(period)` (`client.py:425`; [03b](03b_FILES_src_scraper_llm_api_config.md)), which does one `fetch_html("consult_performance.php", params={"period": period})`, parses in a worker thread with `parsers.parse_consult_performance(html)` (`parsers.py:1088`, on a `decode_cf_emails` soup) and **refuses** (as `PortalUnavailable`) a page whose Showing label or open tab is not the period asked for (the page falls back to This Month for an unknown period), an unrecognised layout (`PerformanceLayoutError` → `consult_performance.php: <why> (layout not recognised)`), mock mode, and any period but today/month (`ValueError`). The dict:
```python
{"period": "today" | "month" | None,          # the open tab's ?period= value
 "period_label": "Today" | "This Month",      # "Showing <strong>…</strong>"
 "range_text": "30 Sep – 30 Sep 2026",        # "" when the page hides it (All Time)
 "scope_note": "",                            # staff-only note; empty for the owner/admin
 "tiles": {"Consultancies done": "5", "Files opened": "1", "Conversion (file open)": "20%", "Docs ready": "0"},
 "top": {"label": "Top performer · Today", "name": "<consultant A>",
         "metrics": [("Score", "2.3"), ("Conversion", "100%"), ("Files opened", "1"), ("Consultancies", "1")],
         "score": "2.3", "conversion": "100%", "files_opened": "1", "consultancies": "1"} | None,
 "columns": [("rank", "#"), ("name", "Consultant"), ("score", "Score"), ("conversion", "Conversion"),
             ("files_opened", "Files Opened"), ("consultancies", "Consultancies"), ("points", "Points"),
             ("docs_ready", "Docs Ready")],     # (None, "<header>") for a column the bot does not know
 "leaderboard": [{"rank", "name", "top": bool, "score", "conversion", "files_opened", "consultancies",
                  "points", "docs_ready", "extra": {"<header>": "<figure>"}}, ...],   # portal order
 "count": 4 | None,                           # the leaderboard's own count badge
 "empty_text": "",                            # the empty state's words ("" when it has rows)
 "sort_note": "Sorted by score, highest first",
 "score_help": "Balanced score = files opened × (0.5 + conversion) × program weight",
 "points_help": "Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1"}
```
The page's selectors (from the live inspection, 30 Sep 2026): period tabs `nav.pf-tabs a[href="?period=today|week|month|all"]` (open one `.on`); range `p.pf-showing` with `<strong>` and `span.pf-dates`; tiles `div.pf-stats > div.pf-stat` with `.n` (figure) and `.l` (label); top card `section.pf-top` (`.pf-top-k` label, `h2.pf-top-name`, `.pf-top-m > div` each `<b>value</b><span>label</span>`); leaderboard `table.tbl.pf` (header-driven; Score and Points tooltips in `th[title]`), crowned row `tr.is-top` with `span.pf-crown` "Top", count `span.pf-count`, sort note `span.pf-note`; the only accepted empty state `tr.pf-empty-row` with `.pf-empty` inside.

### 6a.3 Functions, one by one
| Signature | Line | Contract |
|---|---|---|
| `title(kind: str) -> str` | `:54` | `"Today"` / `"This Month"`; `ValueError("no such performance period: …")` for anything else |
| `source(kind: str) -> str` | `:61` | `"consult_performance.php?period=<kind>"` |
| `waiting_text(kind: str) -> str` | `:66` | `⏳ _Reading the portal's Consultant Performance page (Today) live..._` (one italic entity, no underscore inside) |
| `_bold_safe(text) -> str` | `:71` | `*` → `∗` (U+2217): legacy Markdown reads a bold entity literally up to its closing `*`, so a backslash would show |
| `_code(value) -> str` | `:77` | `` `value` `` with a backtick of its own changed to `ʼ` (U+02BC) |
| `_int(text) -> Optional[int]` | `:82` | `"1,234"` → 1234; None when not a plain integer (`"18%"`, `"17.9"`) |
| `_same_name(a, b) -> bool` | `:87` | whitespace-collapsed, `casefold` equality |
| `_range_dates(text) -> Optional[Tuple[date, date]]` | `:93` | `"01 Sep – 30 Sep 2026"` → (1 Sep, 30 Sep 2026): the end via `src.dates.parse_portal_date`, the start's month via `src.dates.MONTHS`, its year one less when its month is after the end's (a range across New Year). None when unreadable. **Also used by `src.cloud.records` (must keep).** |
| `_range_warning(kind, range_text, today) -> Optional[str]` | `:108` | None when Today's range is exactly `today..today`, or This Month's is `1st..today` or `1st..month end` (in Dhaka); else `⚠️ The page's range is <range>, but today in Dhaka is DD Mon YYYY: the figures are the portal's, for the range it shows.` Unreadable range → None |
| `_top_warnings(page) -> List[str]` | `:126` | no top card but rows → `⚠️ The page shows no top performer card, though its leaderboard lists N consultant(s).`; a card but no rows → `⚠️ The page shows a top performer card but no one on its leaderboard.`; card and crowned row name different people → `⚠️ The top performer card names X, the leaderboard crowns Y.`; same person, figures differ → `⚠️ The top performer card and the leaderboard's top row differ on: score, conversion.` |
| `_total_warnings(page) -> List[str]` | `:146` | for each tile in `_TILE_COLUMN` whose figure is an integer and every row's column is an integer: sum ≠ tile → `⚠️ The leaderboard's <column header> add up to N, the <tile> tile says T.` (both are the portal's own; the difference is said, never resolved) |
| `_tile_lines(tiles) -> List[str]` | `:168` | `` 🎧 *Consultancies done:* `5` `` one per tile, page order |
| `_top_lines(page, kind) -> List[str]` | `:176` | `🏆 *<card label or "Top performer · <title>">:* <name>` then `` ␣␣␣Score `2.3` · Conversion `100%` · … `` (the card's own labels); no card → `🏆 *Top performer:* none shown on the page for this period.` |
| `_row_lines(row, columns) -> List[str]` | `:188` | `*<rank>. <name>*` (+ ` 🏆 Top` for the crowned row), then every other column in header order with the header's own text, **two a line**, `├` / last `└`, three-space indent; an empty value is `(blank)`; an unknown column's value from `row["extra"][header]` |
| `_leaderboard_lines(page) -> List[str]` | `:202` | `🏅 *Leaderboard* (N consultant(s))` (N = the badge, else the row count); no rows → `• Nobody is listed for this period (the page says: “<empty_text>”).`; then all rows; then, after a blank line, `ℹ️ *Score:* <score_help>` and `ℹ️ *Points:* <points_help>` when present |
| `format_consult_performance(kind, page, today) -> str` | `:218` | the whole reply (below) |
| `message_pieces(text, limit=None) -> List[str]` | `:247` | the reply cut only between records (§6a.5) |
| `async build_performance_report(kind, today=None, reads=None) -> str` | `:281` | §6a.6 |

### 6a.4 The reply (Telegram legacy Markdown), exactly
`format_consult_performance` joins: `📈 *Consultant Performance — <title>*`; `📅 Showing *<period_label>* · <range_text>`; optional `ℹ️ The page notes: <scope_note>`; optional range warning; `RULE`; the tile lines; blank; the top lines; blank; the leaderboard lines; optional blank + `_top_warnings` + `_total_warnings`; blank; the footer `🔗 Read live just now, read-only, from the portal's Consultant Performance page (consult\_performance.php?period=<kind>). <sort note>.` All portal text is escaped with `esc` outside entities and `_bold_safe` inside bold. The footer writes the path as **escaped text, not a code span**: the plain-text resend (`markdown_to_plain`) keeps an escaped underscore but would drop one inside a code span. The live reply on 30 Sep 2026 (names replaced):
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
…

ℹ️ *Score:* Balanced score = files opened × (0.5 + conversion) × program weight
ℹ️ *Points:* Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1

🔗 Read live just now, read-only, from the portal's Consultant Performance page (consult\_performance.php?period=today). Sorted by score, highest first.
```
Sizes seen live: Today 1188 UTF-16 units (4 rows), This Month 1624–1634 (7 rows, one of them the owner/admin account); both one message, no warning line (the tiles equalled their columns' totals: month 716/108/8, today 5/1/0).

### 6a.5 `message_pieces(text: str, limit: Optional[int] = None) -> List[str]` — whole records only
`limit = limit or replies.CHUNK_CHARS` (3900). (1) Group lines into records: a line starting with three spaces (the `├`/`└` figure lines and the top performer's figures line) or a blank line joins the line above it, so no piece starts with figures or ends on a name. (2) Pack records greedily: a record that would push the current piece over `limit` (`telegram_len(current) + 1 + telegram_len(record)`) starts a new piece; a record longer than `limit` on its own (never on the live page) is split between its lines with `replies.split_text`. (3) Drop blank pieces. `"\n".join(pieces)` gives the text back. Why (rule R6 of the build, whole records per message): `reply_long`/`split_text` cut between any two lines, so from about 25 consultants a message could end on a consultant's name and the next start with that person's figures and no name (review finding, fixed `314afdb`; tested with 120 rows).

### 6a.6 `async build_performance_report(kind: str, today: Optional[date] = None, reads: Optional[Dict[str, Any]] = None) -> str`
- `page = await admin_client.read_consult_performance(kind)`; **any** exception (portal down, timeout, HTTP 404, refused login, unknown layout, another period shown, mock mode) → ERROR log `Consultant performance <kind>: not read (<portal_error_reason>)` and `portal_error_reply("The portal's Consultant Performance page (<title>)", e)`, i.e. `❌ Couldn't read the portal: <why>.\nThe portal's Consultant Performance page (Today): not available right now. Please try again in a minute.` Never raises, never zeros.
- `command_hooks.seen(reads, performance=(kind, page))` (nothing while publishing is off; a page that was not read keeps nothing).
- `text = format_consult_performance(kind, page, today or local_today())`; INFO `Consultant performance <kind>: read in 0.3 s, 7 leaderboard row(s); 1624 characters.`; return `text`.
- Network: login GET/POST when the session is new, then exactly one GET of `consult_performance.php?period=<kind>` (measured 1.2 s cold, 0.3 s warm).

**Callers.** `telegram_bot._send_performance_report` (`waiting_text`, `build_performance_report`, `message_pieces`), `src.cloud.records` (`_range_dates`). The hourly full picture reads the page through `src.cloud.backfill.collect_performance` (2 GETs), not through this module's formatter.

**Tests.** `tests/test_performance.py` (52 test functions; 225 collected cases with their parameters at `314afdb`: exact parses of synthetic pages copying the live structure with a decoy table and the unused form; reordered/renamed headers and an unknown column; the empty state; 10 layout-guard cases; the period echo; every failure mode; the self-checks; the plain-text fallback; the 120-row split; legacy-Markdown validity; menu/cheat-sheet/start texts; routes both ways; the removed self-computed code staying removed; the root copy byte-identical). `tests/test_cloud_performance.py` (20 functions / 25 tests: the publish after the reply, the reply identical with publishing on or off, nothing kept when the page was not read).

**History.** `bbd8f98` created: team totals and per-person consultations done (`handled_by`), No Answer / Wrong Number follow-ups, requests assigned, payments verified (count and BDT), from `client.read_consultation_range(first, last)` and `client.read_verified_window` → `a721066` honest last line, "this months", no stand-in month → `ce23535` **replaced**: only the portal's page (`format_consult_performance`, `build_performance_report`); removed `tally`, `Person`, `Tally`, `Reads`, `read_performance`, `window` and the consultation/verification sections here, and `read_consultation_range`, `_consultation_window_read`, `_ListChanged`, `_span`, `CONSULT_RANGE_MAX_READS`, `ensure_session`, `read_verified_window` (client) and `verified_between` (parsers) → `314afdb` `message_pieces` (whole records), the real empty state only → `e4d1cea` `reads=` and the `seen(..., performance=...)` hook.

---

## 7. `src\bot\voice.py` — Jennie, the voice assistant (built, currently disabled)

**Status (30 Sep 2026, `8317741`).** Fully built; **disabled** since 28 Sep 2026 and still off: `JENNIE_VOICE_ENABLED=false`, `JENNIE_SPOKEN_BRIEF=false` in `.env`, to free GPU memory (the owner's decision in the second session: GPU use fell from 8–9.8 GB peak to 3.8 of 8 GB). With the flag off, the voice handler is not registered (§8.2), no filler clips are rendered, and the brain is not pinned: `post_init` unloads any pinned copy at start and the model loads on demand for the first question that needs it. The voice service lives in `C:\Hangeul\JARVIS\jennie_voice\`; its watchdog task is disabled and its Startup shortcut (`.lnk`) moved to `C:\Hangeul\JARVIS\disabled\`. **`voice.py` is unchanged since `e164679`** (no commit in `c17d887..8317741` touched it), so every line number below is still valid. If the voice were switched back on, a spoken performance question would reach the page through the `stats` route (`_dispatch` asks `ask.classify`, gets `performance`, and hands the words to `handle_natural_language_message`, ran value `stats:performance`); `ROUTE_COMMANDS` has no performance command of its own.

**Purpose.** A voice note (or audio file) from an authorised user gets: an instant pre-rendered filler clip; speech-to-text on the local voice service; "🎧 heard: …"; ONE local-LLM call routing the words (with the chat's last turns) to one of the bot's own commands, which runs **exactly as when typed**, its text answer appearing as usual while being captured; then ONE short spoken sentence about that answer, checked against the facts the answer states, rendered as an OGG/Opus voice note. Everything stays on this PC.

### 7.1 Voice service contract (127.0.0.1 only)
```
POST /stt  multipart field "audio"  -> 200 {"text", "language", "duration_s", "seconds"}
POST /tts  JSON {"text", "language": "en"|"ko", "style": "aegyo"|"neutral"}
           -> 200 OGG/Opus body (must start b"OggS"), headers X-Duration, X-Seconds
           text over 600 chars -> 413 ; busy -> 503
```
`JENNIE_VOICE_URL` default `http://127.0.0.1:8765`. `_service_url()` refuses any host not in `_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}` (raises `VoiceServiceError`). `_http(timeout)` = `httpx.AsyncClient(base_url=..., timeout=httpx.Timeout(timeout, connect=5.0), trust_env=False)` (never through a proxy).

### 7.2 Constants
| Name | Value | Why |
|---|---|---|
| `STT_TIMEOUT` / `TTS_TIMEOUT` | 60.0 / 120.0 s | the service queues one request at a time |
| `TTS_MAX_CHARS` | 600 | the service refuses longer (413) |
| `REPLY_MAX_CHARS` | `{"ko": 32, "en": 120}` | hard limit after clean-up |
| `REPLY_TARGET_CHARS` | `{"ko": 22, "en": 90}` | what the prompt asks for |
| `BRIEF_MAX_CHARS` | 160 | ~12 s of speech; fits the service's 100 s limit even on CPU |
| `ANSWER_MAX_CHARS` | 2000 | how much of a written answer the prompt sees |
| `MAX_VOICE_SECONDS` | 60 | longer notes are refused (CPU STT runs just under real time) |
| `MAX_DOWNLOAD_BYTES` | 20 MiB | Telegram's bot download limit |
| `VOICE_TURN_WAIT` | 240.0 s | wait for our turn at the voice service |
| `LLM_TIMEOUT` | 30.0 s | one brain call (cold ~3 s, warm ~0.4 s) |
| `ROUTE_MAX_TOKENS` / `REPLY_MAX_TOKENS` | 160 / 120 | |
| `HISTORY_TURNS` / `PROMPT_TURNS` | 6 / 3 | turns kept per chat (memory only) / turns the brain sees |
| `FILLER_DIR` | `BOT_ROOT\data\jennie_fillers` | `ko_1..3.ogg`, `en_1..3.ogg`, `fillers.json` (present on disk) |
| `FILLER_LINES` | ko: `잠시만용~ 찾아볼게요!`, `음~ 찾아볼게용!`, `금방 알려드릴게용~`; en: `Ooh, one sec~ let me check!`, `Hehe, checking now!`, `Okie, give me a moment~` | picked because they render in 1.4–2.8 s |
| `FILLER_MAX_SECONDS` | 3.5 | a longer clip is never sent |
| `UNAVAILABLE_NOTE` | `🔇 Voice reply unavailable right now — the answer is in the text above.` | |
| `EMAIL_FLOW_NOTE` | `✉️ An email is waiting for your answer — please type it (SEND / EDIT / DENY or the detail I asked for). I don't handle emails from voice notes.` | a misheard "send" must never email a student |

The VRAM rationale for the Korean 32-character cap is written at `voice.py:56-64` (measured 28 Sep 2026: resident brain 2.82 GiB at num_ctx 3072 + desktop + idle voice service ≈ 4.6–4.8 of 7.96 GiB; a render peaks at 3.55–3.67 GiB; some runs spilled into shared memory and slowed 2–7×).

### 7.3 Errors, turns, service client
- `class VoiceServiceError(Exception)` — unreachable or refused. `class VoiceServiceBusy(VoiceServiceError)` — timed out, 503, or no turn.
- `_voice_turn()` (async context manager): one `asyncio.Lock` per event loop (created lazily, `_turn = (loop, lock)`); `asyncio.timeout(VOICE_TURN_WAIT)` on acquire → `VoiceServiceBusy`. Every voice-service request (STT, TTS, filler renders, spoken brief) takes a turn, so the bot never has two requests in flight and each timeout counts only its own work.
- `_service_error(resp, what)` (503 → Busy), `_request_error(e, what, timeout)` (a non-connect timeout → Busy, else Error).
- `async transcribe(audio: bytes, filename: str = "voice.ogg", mime_type: str = "audio/ogg") -> dict` → `{"text", "language" (lower-case), "duration_s", "seconds"}`; raises the two errors on HTTP/JSON problems.
- `async synthesize(text: str, language: str, style: str) -> Tuple[bytes, float]` → `(ogg bytes, X-Duration)`; text `_fit` to 600; non-OGG body → `VoiceServiceError`.

### 7.4 Filler clips
`_filler_manifest()`, `_filler_wanted()` (yields `(language, "<lang>_<n>.ogg", line)`), `missing_fillers() -> list` (clips not rendered or rendered for another line), `_write_atomic(path, data)` (`.tmp` then `os.replace`), `async prepare_fillers() -> int` (renders missing clips, one voice turn each, style `aegyo`; writes the manifest `{name: {"line", "duration"}}`; a clip over 3.5 s is kept on disk but never used; never raises), `_prepare_fillers_later()` (background re-render after a note), `_pick_filler(language) -> Optional[dict]` (random ready clip; cached in `_filler_clips` with Telegram's `file_id` after the first upload), `async _send_filler(bot, chat_id, language, timings)` (tries `file_id` then raw audio; never raises).

### 7.5 Per-chat memory
`_history: {chat_id: deque(maxlen=6)}` of turns `{"user", "language", "command", "date", "jennie"}` (in memory only, lost on restart). `_turns(chat_id)`, `_remember(chat_id, user, language, command, day, jennie)` (day as ISO or `"first to last"`), `last_language(chat_id) -> str` (`"ko"` until someone has spoken), `_history_text(turns, commands: bool)` (last 3 turns as `User: …` / `Jennie (<command> <date>): …`).

### 7.6 The router (one LLM call)
- `ROUTE_COMMANDS = ("verified_today", "verified_date", "inquiries_today", "inquiries_date", "calendar", "passports", "stats", "missing_report", "crosscheck", "chat")`.
- `_ROUTER_SYSTEM` (`voice.py:385`, proven in `C:\Hangeul\JARVIS\brain-trial\trial.py`: 12/12 commands, dates and valid JSON with qwen3:4b-instruct, ~0.35 s warm). It lists each command with a Korean gloss, gives `Today is <TODAY>. The seven days before it were: <DAYS>.`, says a short follow-up ("and yesterday?") keeps the previous topic and changes only the date, and asks for JSON `{"command", "date": "YYYY-MM-DD"|null, "english_query", "language": "ko"|"en"}`.
- `_ROUTER_SCHEMA`: JSON schema passed as Ollama `format` (structured output), `command` enum = `ROUTE_COMMANDS`.
- `async route(heard: str, turns=()) -> Optional[dict]` (`voice.py:534`) → `{"command", "date": Optional[date], "english_query" (≤200 chars, plain), "date_problem": Optional[str]}`; None when the brain is down or answered nonsense (tries `json.loads`, then the first `{...}`). For dated commands (`_DATED_COMMANDS`), a relative day in the words (`_relative_day`: 오늘/어제/그저께/today/yesterday/weekday names, only when no calendar date is spoken) replaces the brain's date (the brain miscounts weekdays); otherwise `_words_date` checks the brain's date against the dates the words name.
- Date helpers: `_MONTH_WORD`, `_CALENDAR_RE` (a calendar date in the words: `25일`, `9월 1일`, `이십오일`, `September 20`, `20th`, `2026-09-25`, `25/9`), `_QUERY_DAY_RE` (named groups `iy/im/id`, `dd/dm/dy`, `mm/md/my`, `km/kd`, `dby`, `yday`, `tday`), `_RANGE_WORD_RE` (`to|until|till|through|thru|between|~|–|—|부터|까지`), `_query_days(text, today) -> list`, `_one_day(text, today)`, `_span(text, today, need_range_word=True)` (a lone "to" is not a range), `_spoken_day`, `_relative_day`, `_KO_DATE_RE`, `_ORDINAL_DAY_RE`, `_KO_DAY_RE`, `_ko_number`, `_words_dates(text, today) -> (dates, days-of-month alone, problem)`, `_words_date(day, heard, english, today) -> (day, problem)` (a spoken date that does not exist — `31 September`, `February 30`, `the 45th`, `9월 31일` — is `(None, why)`, never another day; added `e164679`), `_portal_day(day)` → `'26 Sep 2026'`.

### 7.7 `async _dispatch(routed, update, context, heard) -> (ran, day)` (`voice.py:644`)
Runs the routed command directly on the capturing update. `ran` values: `"<kind>:date_error"` (the command's own date-error reply, no portal read, a pending date question stays open), `"crosscheck_range"` (answer to the range question, or a spoken range), `"<awaiting>_date"` (a date answering the bot's own "which date?"), `"chat"`, `"verified_today"`, `"verified_date"`, `"inquiries_today"`, `"inquiries_date"`, `"crosscheck_today"`, `"crosscheck_date"`, `"crosscheck_student"` (a 2–5 digit id → `override_text = "student <id>"`), `"calendar"` (the English words go as `override_text` so `/calendar` applies their dates), `"stats:<kind>"` (a specific figure goes through the typed route, `voice.py:756-763`; this is also how `performance` would be reached) / `"stats"`, `"missing_report"`, or `None` (let the typed-question routing handle it). It sets `context.user_data["override_text"]` before calling `telegram_bot.<x>_command`, and honours `awaiting_date_for` (see §8.6). `passports` goes to the live cross-check for the day (today when none), never a stored list.

### 7.8 Spoken reply — what Jennie may say
- Prompts: `_REPLY_SYSTEM_EN` (cute bubbly English, ONE short sentence ≤ `<LIMIT>` chars, only the facts, digits, the day exactly as given or none, "none" for 0, no Markdown/emojis/URLs), `_REPLY_SYSTEM_KO` (Korean 애교 endings ~요/~용, ≤ `<LIMIT>` chars, 없어요 for 0), `_BRIEF_SYSTEM_EN` (the evening update); shared rule fragments `_CUTE_EN`, `_FACT_RULES`, `_ASK_RULE`, `_DAY_RULE`. Fallbacks `_FALLBACK[(lang, has_answer)]`, `_BRIEF_FALLBACK = "Good evening! Today's brief is in the chat, hehe."`, `_PORTAL_DOWN_LINE` (en/ko fixed sentences for a failed read).
- Numbers: `_numbers_in(text) -> set` (digits incl. `28,000.50` → {28000, 50}; English number words `twenty-eight thousand` → 28000, a lone "one" ignored; Korean native `세 명` → 3 and Sino `이십 건` → 20 via `_KO_NATIVE_RE` / `_KO_SINO_RE` / `_ko_sino_value`) — also used by `brief.claims_problem`. `_NOTHING_RE` (the written answer says there is nothing), `_SAID_NOTHING_RE` (Jennie says 0 in words), `_facts_ok(said, *sources)`.
- `answer_facts(answer: str) -> list` (`voice.py:1036`): the facts a command's written answer states, one figure a line, at most 8: `label: figure` lines (`_FACT_LINE_RE`, labels with a date in them excluded, a label that appears more than once is a per-student detail and dropped), `Label (N items)` headings (`_ITEMS_LINE_RE`), and `_NOTHING_FACTS` (`No student payments were verified…` → `Students whose payment was verified: 0`, `No (new) consultation requests were recorded/received…` → `Consultation requests received: 0`, `No payment-verified students found…` → `Payment-verified students cross-checked: 0`, `No admitted students on the portal…` → `Admitted students: 0`).
- `async _say(system, prompt, language, limit, *sources, check=None, numbers=None) -> str`: up to two brain calls; the second adds hints before `\n\nJennie says:` (`(The only numbers you may say: …)` / `(Do not say any numbers.)` / `(Too long: … at most 0.7×limit characters.)`); "" when the brain is down or kept getting facts wrong.
- `_fact_problem(said, facts, question, language, day, today)`: Korean always refused (Korean cannot be checked word by word); the days named must be the answer's own (`_day_problem`); a figure (or "none") must be said; then `brief.claims_problem(_checkable(rest, facts), facts, _JENNIE_WORDS + _MONTH_AND_DAY_WORDS + question words)`. `_checkable` maps "consultation(s)" → "inquiries" and lets `intake/passport/visa` through when the facts are about them.
- Korean line built in code: `_KO_TOPICS` (regex on the fact label → Korean words, counter, timed), `_headline(facts)`, `_fact_value`, `_korean_line(facts, day, today)` → e.g. `짜잔! 어제 상담 요청은 21건이에용!` (copula 이에용/예용 by final consonant; `없어용!` for 0; the cheer dropped if it would exceed 32 chars). `_english_line` → `Okie! <label> <when>: <value>, hehe!` / `Aww, <label> <when>: none, hehe!`.
- `async spoken_reply(question, language, answer="", turns=(), day=None) -> str` (`voice.py:1240`): small talk → brain, numbers only from the question; an answer with facts → Korean: `_korean_line`; English: brain + `_fact_problem` check, else `_english_line`; a failed portal read (`_PORTAL_DOWN_RE`) → the fixed `_PORTAL_DOWN_LINE`; an answer with no figure (a question back) → brain with a no-number check.
- `async spoken_brief(brief_text) -> str`: brain on the brief's facts (limit 140), `claims_problem(said, facts, _BRIEF_CHEER_WORDS)`, else `_BRIEF_FALLBACK`.

### 7.9 Text for speech
`_plain(text)` (Markdown → plain lines: links to their text, URLs, `→`/`➔` → " to ", emojis (`_EMOJI_RE`), markup `` [*_`#|<>\[\]{}] `` removed; `~` kept, the service turns a closing `~` into "!"), `_speech_text(text, language, limit)` (drops a `Jennie:` prefix, one paragraph, `৳`/`BDT` → `taka`/`타카`, numbers spelled out, `_fit`), `_fit(text, limit)` (cut at a sentence end ≥ limit/3, else a space), `_spell_numbers_en` (ISO dates, `12 Sep` → `the twelfth of September`, clock `17:19` → `seventeen nineteen`, ordinals, amounts, `%` → percent; phone numbers/long ids digit by digit via `_is_code`), `_spell_numbers_ko` (ISO → `2026년 9월 12일`, native numbers before `명/개/시간/시/살/…`, Sino otherwise, 6월/10월 → 유월/시월, 첫 번째), `_en_words`, `_en_ordinal`, `_ko_sino`, `_ko_native`. `spoken_language(code, text) -> str` (Korean when Whisper says `ko` or ≥30% of letters are Hangul).

### 7.10 Capturing what a command sends
- `class _Capture`: ordered texts; `add(text) -> slot`, `replace(slot, text)` (an edited message counts with its final text), `remove(slot)` (a deleted "⏳" note does not count), `text()` (joined by blank lines).
- `class _CapturingMessage` (`__slots__`): wraps one PTB `Message`; `reply_text`, `edit_text`, `delete` go to the real message and are recorded; everything else via `__getattr__`. Needed because PTB objects are frozen (nothing can be set on them).
- `class _CapturingUpdate`: `.message` / `.effective_message` are the capturing message; all else the real update. Only this update's objects are wrapped, so nothing else is captured.

### 7.11 The Telegram handler
- `async handle_voice_message(update, context)` (`voice.py:1693`): registered only when `JENNIE_VOICE_ENABLED` (with `block=False`). Wraps `_answer_voice` in `try/except` (**nothing ever raises out of the handler**); in `finally` logs one metadata-only INFO line (`Voice note from <chat>: 4.2s audio, ko, verified_today | filler +0.14s, download 0.30s, stt 1.10s, route 0.40s, command 2.90s, reply 0.50s, tts 3.80s, voice sent 0.20s, total 9.40s` — never what was said), schedules missing filler renders, awaits the filler task.
- `async _answer_voice(update, context, timings, facts)` — order: not authorised → log, **no reply** (as for typed messages); too long/large → note; filler in the background (or a typing action while `/sendmail` waits for typed input); download (`media.get_file()`, `download_as_bytearray()`); STT in a voice turn (Busy → "the voice service is busy…", Error → "I can't listen to voice notes right now…"); empty text → note; `🎧 heard: <text>` in the background (≤3900 chars); `email_flow` → `EMAIL_FLOW_NOTE` and stop (checked again after routing, with no await before the command, because a `/sendmail` typed meanwhile must not get the voice query as its answer); `route`; `_dispatch` on the capturing update (`override_text` always popped afterwards); `ran is None` → `telegram_bot.handle_natural_language_message(proxy, context, query=<english query or heard>)` (`"fallback"`); no captured answer (and not chat) → stop; the day answered for derived from `ask.classify` for fallback/stats; `spoken_reply`; chat → `💬 <speech>` as the text answer; `_remember`; TTS in a voice turn; `send_voice(filename="jennie.ogg", write_timeout=60)`; any TTS/send failure → `UNAVAILABLE_NOTE`. Helpers: `_Timings` (`elapsed`, `lap(stage)`, `summary`), `_seconds`, `_media_facts` (PTB 22 duration warning suppressed), `_audio_name` (MIME → extension map), `_voice_duration`, `_background(coro)` (keeps a strong reference in `_tasks`), `_chat_action`, `_note` (never raises).
- `async send_spoken_brief(bot, chat_id, brief_text) -> bool` (`voice.py:1863`): `spoken_brief` → TTS (`en`, `aegyo`) → `send_voice(filename="jennie-brief.ogg")`; never raises; False = skipped (logged).

Supabase: a voice note that runs a command publishes exactly what that command publishes (the handler's own hooks run on the capturing update); the voice path itself publishes nothing.

**Callers.** `telegram_bot.build_telegram_application` (`handle_voice_message`), `scheduler.send_daily_briefing` (`send_spoken_brief`), `scheduler.warm_brain` (`prepare_fillers`), `brief` (`_numbers_in`, `_WORD_VALUES`, `_WORD_SCALES`, `_plain`).

**History.** `d7a5817` created (796 lines; Korean rewritten by the LLM into English, then typed routing; 29 tests) → `d9bbecc` fast and conversational (reply time 20–28 s → 5.9–9.5 s: filler clips, one JSON routing call with history, direct dispatch, one short sentence, qwen3:4b-instruct resident with `keep_alive -1`, `OLLAMA_BASE_URL` 127.0.0.1 because `localhost` cost 2 s per connection) → `f8fefa4` spoken brief from facts, checked → `e0d47ab` small → `7f42ad0` same routes as typed text; English checked by `claims_problem`; Korean built from the headline fact → `e164679` impossible spoken dates, fixed portal-down sentence. No change since.

---

## 8. `src\bot\telegram_bot.py` — commands, flows and the application

**Purpose.** Every Telegram command handler, the interactive date prompts, the `/sendmail` conversation, the cross-check engine, the performance commands, the free-text dispatcher, the inline-button flows (`/missing`, `/stage`), the Supabase publish hooks after each reply (§8.13), and the application factory. Module-level imports: `logging, re`; `typing.Optional, Dict, Any, List`; `telegram.Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup`; `telegram.error.BadRequest`; `telegram.ext.Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters`; `src.config.settings`; `src.scraper.client.admin_client`; `src.llm.ollama_client.ollama_client`; `src.bot.scheduler.setup_scheduler`. Logger `hangeul.bot`.

### 8.1 How `run.py` starts it
`run.py` (unchanged since `c17d887`) configures logging (`hangeul_bot.log` + stdout; `pythonw` has no console so stdout/stderr go to `hangeul_stdout.log` / `hangeul_stderr.log`), applies the Telegram DNS workaround (`src.net_fix.apply_telegram_dns_fix`), checks Ollama, builds a uvicorn server for `src.api.main:app` on `API_HOST:API_PORT` (`0.0.0.0:8000`), then:
```python
telegram_app = build_telegram_application()
if telegram_app:
    async with telegram_app:
        await telegram_app.start()
        await post_init(telegram_app)          # PTB calls post_init only from run_polling/run_webhook
        await telegram_app.updater.start_polling()
        try:
            await server.serve()               # the REST API runs in the same event loop
        finally:
            await telegram_app.updater.stop(); await telegram_app.stop()
else:
    await server.serve()                       # no token: the API still runs
```
`post_init` is also passed to `Application.builder().post_init(post_init)`, but PTB 22 runs that hook only inside `run_polling`/`run_webhook` (`_application.py:479`: `initialize()` "Does *not* call post_init"), which `run.py` does not use; so `post_init` runs **exactly once**, from `run.py`. (Seen on 30 Sep 20:35: after an unplanned reboot the bot and Ollama started together, so the startup health check said Ollama was not reachable, and the watchdog started a second copy that stopped itself — two startup messages and two `Scheduler active` lines 5 s apart in `hangeul_bot.log`.)

### 8.2 `build_telegram_application()` (`telegram_bot.py:2367`)
- `token = settings.TELEGRAM_BOT_TOKEN` (value in secrets\bot.env (TELEGRAM_BOT_TOKEN)); empty or the placeholder `"your_telegram_bot_token_here"` → warning `No valid TELEGRAM_BOT_TOKEN provided in .env. Telegram bot will not start.` and `return None`.
- `app = Application.builder().token(token).post_init(post_init).build()` (default PTB settings: updates processed one at a time; handlers `block=True` unless stated).
- Handlers, all in group 0, **in this registration order**:

| # | Handler | Callback |
|---|---|---|
| 1 | `CommandHandler("inquiries_today")` | `inquiries_today_command` |
| 2 | `CommandHandler("inquiries_date")` | `inquiries_date_command` |
| 3 | `CommandHandler("verified_today")` | `verified_today_command` |
| 4 | `CommandHandler("verified_date")` | `verified_date_command` |
| 5 | `CommandHandler("crosscheck_today")` | `crosscheck_today_command` |
| 6 | `CommandHandler("crosscheck_date")` | `crosscheck_date_command` |
| 7 | `CommandHandler("crosscheck_range")` | `crosscheck_range_command` |
| 8 | `CommandHandler("missing")` | `missing_command` |
| 9 | `CallbackQueryHandler(pattern=r"^missing:")` | `missing_button` |
| 10 | `CommandHandler("stage")`, `CommandHandler("stages")` | `stage_command` |
| 11 | `CallbackQueryHandler(pattern=r"^stage:")` | `stage_program_button` |
| 12 | `CallbackQueryHandler(pattern=r"^stagei:")` | `stage_intake_button` |
| 13 | `CommandHandler("sendmail")`, `("email")`, `("mail")` | `sendmail_command` |
| 14 | `CommandHandler("crosscheck_between")`, `("crosscheck_period")` | `crosscheck_range_command` |
| 15 | `CommandHandler("performance_today")`, `("perf_today")` | `performance_today_command` |
| 16 | `CommandHandler("performance_month")`, `("perf_month")` | `performance_month_command` |
| 17 | `CommandHandler("performance")` | `performance_command` |
| 18 | `CommandHandler("start")`, `("help")` | `start_command` |
| 19 | `CommandHandler("pin")`, `("commands")` | `pin_command` |
| 20 | `CommandHandler("admitted")` | `admitted_command` |
| 21 | `CommandHandler("report")` | `report_command` |
| 22 | `CommandHandler("brief")`, `("dailybrief")` | `brief_command` |
| 23 | `CommandHandler("stats")` | `stats_command` |
| 24 | `CommandHandler("students")` | `students_command` |
| 25 | `CommandHandler("consultations")` | `consultations_command` |
| 26 | `CommandHandler("inquiries")` | `inquiries_command` |
| 27 | `CommandHandler("verified")`, `("verified_students")` | `verified_command` |
| 28 | `CommandHandler("crosscheck")`, `("audit")` | `crosscheck_command` |
| 29 | `CommandHandler("passports")`, `("passport_audit")` | `passports_command` |
| 30 | `CommandHandler("calendar")`, `("events")`, `("deadlines")` | `calendar_command` |
| 31 | `CommandHandler("alerts")` | `alerts_command` |
| 32 | `MessageHandler(filters.TEXT & ~filters.COMMAND)` | `handle_natural_language_message` |
| 33 | **only if `settings.JENNIE_VOICE_ENABLED`**: `MessageHandler(filters.VOICE \| filters.AUDIO, handle_voice_message, block=False)` (lazy `from src.bot.voice import handle_voice_message`; logs `Jennie voice replies enabled (voice service <url>).`) | `voice.handle_voice_message` |

  Notes: the text handler excludes commands, so an unregistered `/xyz` gets no reply. The voice handler is `block=False` because a voice round trip can take a minute and must not hold up everyone's typed commands. Callback-data prefixes: `missing:<KEY>`, `stage:<KEY>`, `stagei:<KEY>|<INTAKE>` (KEY ∈ `KLP`, `EAP`, `BACHELOR`, `MASTER`). The comment above the first handler still says "Register the 6 official menu command handlers" (`:2376`, stale).
- Finally `setup_scheduler(app)` (§5.1) and `return app`.

### 8.3 `post_init(application: Application)` (`telegram_bot.py:2314`)
1. `set_my_commands` with **13** `BotCommand`s, in this order (the Telegram "/" menu; `getMyCommands` confirmed 13 on 30 Sep):
   `inquiries_today` "Total consultancy inquiries & how many done today"; `inquiries_date` "Total inquiries & how many done (ask specific date)"; `verified_today` "Total verified students today"; `verified_date` "Total verified students (ask specific date each time)"; `crosscheck_today` "Total crosscheck verified students live today"; `crosscheck_date` "Total crosscheck verified live (ask specific date each time)"; `crosscheck_range` "Total crosscheck verified live (ask start date → end date)"; `sendmail` "Email a student (ask ID → subject → brief; AI writes it; you approve)"; `brief` "Run today's full 6:05 PM operational brief now"; `missing` "Progress sheet missing information (KLP / EAP / Bachelor's / Master's)"; `stage` "Student stages — choose program → intake"; `performance_today` "Today: the portal's Consultant Performance page: tiles, top performer, leaderboard"; `performance_month` "This month: the portal's Consultant Performance page: tiles, top performer, leaderboard". Success → `Successfully set 13 bot menu commands (set_my_commands).` (the count is now `len(commands)`; `bbd8f98` fixed the old "7 exclusive" text); failure → ERROR log.
2. If `TELEGRAM_ADMIN_CHAT_ID` is set: send `get_commands_cheatsheet_text()` (Markdown) to it and `pin_chat_message(..., disable_notification=True)` — **on every start**. Any failure is logged at DEBUG only ("Startup pin notification skipped").
3. Brain: if `ollama_client.brain_pinned()` → `application.create_task(scheduler.warm_brain(), name="brain-warm-up")`; else `application.create_task(ollama_client.unload(), name="brain-release")` (lets go of a copy pinned by an earlier run so the GPU is free). Background tasks: startup never waits. (Current state: not pinned → unload at start; the brain loads on demand.)

### 8.4 Authorization — `is_authorized(update: Update) -> bool` (`telegram_bot.py:22`)
- No `update.effective_chat` → False.
- `allowed = settings.authorized_ids()` = `{TELEGRAM_ADMIN_CHAT_ID}` ∪ the comma/semicolon/space-separated `TELEGRAM_AUTHORIZED_CHAT_IDS` (both strings; current `.env`: the admin id only, no extra ids).
- Empty set → **refuse everyone** and log `TELEGRAM_ADMIN_CHAT_ID is not set; refused chat <id>. Put your own ID in .env as TELEGRAM_ADMIN_CHAT_ID and restart.` Why (`c5c1a7c`): the baseline bound the first sender as admin, handing student data and `/sendmail` from the agency Gmail to whoever found the bot first, again after every restart.
- Else `str(chat.id) in allowed`. It checks the **chat** id (in a private chat that equals the user id).

What an unauthorised sender gets (per entry point):

| Behaviour | Entry points |
|---|---|
| Reply ``⛔ Unauthorized access. Your Chat ID is: `<id>` `` (lets the owner copy the id into `.env`) | `/start` `/help`, `/report`, `/brief` `/dailybrief`, `/verified` `/verified_students`, `/passports` `/passport_audit`, `/calendar` `/events` `/deadlines`, `/sendmail` `/email` `/mail`, `/crosscheck_range` `_between` `_period`, `/crosscheck` `/audit`, `/performance_today` `/perf_today`, `/performance_month` `/perf_month`, `/performance` |
| Silent (no reply) | `/stats`, `/students`, `/pin` `/commands`, `/admitted`, `/inquiries_today`, `/inquiries_date` (and `/consultations`, `/inquiries`), `/verified_today`, `/verified_date`, `/crosscheck_today`, `/crosscheck_date`, `/alerts`, `/missing`, `/stage` `/stages`, all free text, voice notes (logged `Unauthorized voice message from chat_id`) |
| `query.answer("Not authorized", show_alert=True)` | the three inline-button callbacks |

### 8.5 Conversation state (`context.user_data` keys)
PTB keeps `user_data` per user in memory (lost on restart). Keys the bot uses:

| Key | Set by | Consumed by | Meaning |
|---|---|---|---|
| `override_text` | free-text dispatcher, voice `_dispatch`, `crosscheck_today/date_command`, the date-prompt answer | popped first by `report_command`, `inquiries_date_command`, `verified_date_command`, `verified_command` (then `strict=False`), `crosscheck_date_command`, `crosscheck_command`, `crosscheck_range_command`, `calendar_command` | the words the command should read instead of `context.args` / the message text |
| `override_date` | `verified_today_command` (`"today"`), `verified_date_command` (the raw date) | `verified_command` (`strict=True`) | a date given to a command must be a date |
| `override_query` | free-text `admitted` route | `admitted_command` | the search words |
| `crosscheck_date_only` | `crosscheck_today_command`, `crosscheck_date_command` | `crosscheck_command` (popped) | anything but a date is a date error (never a name search) |
| `awaiting_date_for` | `inquiries_date_command` / `verified_date_command` / `crosscheck_date_command` / `crosscheck_range_command` with no date; `_ask_date_again`; the free-text one-day-span route | popped by `handle_natural_language_message`; read by voice `_dispatch` | values `"inquiries"`, `"verified"`, `"crosscheck"`, `"crosscheck_range"` |
| `date_prompt_answer` (`DATE_PROMPT_KEY`, `:592`) | `handle_natural_language_message` around the answering call | `_ask_date_again` | "these words were typed in answer to the question" |
| `email_flow` | `sendmail_command`, `_handle_email_flow` | `handle_natural_language_message` (step 0), voice (refuses to route) | `{"step": <"id", "subject", "brief" or "confirm">, "student": {...}, "subject", "brief", "body"}` |

The performance commands keep no conversation state (they never ask a question back).

### 8.6 The date-prompt conversation (`DATE_PROMPT_KEY`, `awaiting_date_for`)
1. The user taps `/verified_date` (or `/inquiries_date`, `/crosscheck_date`, `/crosscheck_range`) with no date. The command sets `user_data["awaiting_date_for"] = "verified"` and replies e.g. `📅 *Total Verified Students*\n\nPlease enter the *specific date* to view verified students:\n(e.g. `12 Sep 2026`, `yesterday` or `2026-09-12`)` (no code spans inside italics: legacy Markdown does not nest entities, and the backticks showed).
2. The next text message reaches `handle_natural_language_message`. After the `email_flow` check it **pops** `awaiting_date_for`, maps it (`{"inquiries": inquiries_date_command, "verified": verified_date_command, "crosscheck": crosscheck_date_command, "crosscheck_range": crosscheck_range_command}`), sets `override_text = <the message>` and `DATE_PROMPT_KEY = <kind>`, calls the command, and in `finally` pops `DATE_PROMPT_KEY`.
3. The command reads the words strictly. If they are not a date it calls `_ask_date_again(context, kind, raw)` (`telegram_bot.py:595`): when `user_data[DATE_PROMPT_KEY] == kind` **and** (`src.dates.has_date_hint(raw)` or the answer is at most two words, e.g. a typo "tomorow") it sets `awaiting_date_for = kind` again; then it replies `date_error_reply(raw, "/verified_date")`. So the "12 Sep 2026" the error invites is read as the date, while a whole new question (3+ words, no date hint) is not swallowed by the old prompt. (Added `e164679`; the ≤2-words rule `c17d887`.)
4. The free-text one-day-span route also opens a prompt: a span asked of a one-day answer ("verified this week") sets `awaiting_date_for` (`passports` → `crosscheck`) and replies `ask.one_day_reply`.
5. Voice: `_dispatch` reads `awaiting_date_for` without popping; a spoken date answers the question (`handle_natural_language_message(query="26 Sep 2026")`, which pops it); a spoken new request drops it; an impossible spoken date gets the date error and the question stays open.

### 8.7 Function by function (source order, grouped)

#### Start and dates
- `async start_command(update, context)` (`:39`): unauthorised → the ⛔ reply. Else a welcome: mode (`🧪 *Mock Mode*` / `🌐 *Live Mode* (Connected to hangeul.com.bd)` from `MOCK_MODE`), LLM (`ollama_client.check_health()["reachable"]` → `🟢 Connected (<model>)` else `🟡 Standby (Internal Engine)`), `HANGEUL_BASE_URL`, the **twelve** numbered menu commands (1️⃣–🔟 as before, then `1️⃣1️⃣ /performance_today — Today on the portal's Consultant Performance page: tiles, top performer, leaderboard` and `1️⃣2️⃣ /performance_month — This month on …`; no `/brief`), and natural-language examples.
- `_DATE_FILLER_RE` (`:80`): the words a date request may have around its date; what is left once they are gone is the date:
  ```python
  r"/\w+(?:@\w+)?|[?!.,:;'\"()]|\b(?:reports?|consultations?|consultancy|inquir(?:y|ies)|enquir(?:y|ies)|requests?"
  r"|verified|verifications?|verify|students?|payments?|paid|crosscheck|cross\s*check|audit|check|only|specific"
  r"|specif|dates?|days?|for|of|on|in|at|the|a|an|and|to|by|please|pls|show|give|get|got|tell|me|us|how|many"
  r"|much|were|was|is|are|be|been|did|do|does|done|has|have|had|their|there|total|list|who|what|which|number"
  r"|count|all|any|brief|summary|daily|came|come|received|new)\b"   (re.I)
  ```
- `normalize_date_input(text: str, strict: bool = False) -> Optional[tuple]` (`:88`): → `(portal "DD Mon YYYY", display "DD Month YYYY")`. `src.dates.parse_user_date(text, local_today(), prefer_past=True)` (month names only as whole words; a date without a year is the latest one not after today). No date: strip `_DATE_FILLER_RE`; if something is left and (`strict` or `has_date_hint(rest)`) → **None**; else today. None means the caller replies `date_error_reply`. **Never a silent stand-in day** (since `e0d47ab`; the baseline returned today for anything).
- `parse_user_report_intent(text) -> tuple[bool, str, str]` (`:108`): whether text asks for the report (`/report` or `ask.classify(...).kind == "report"`) and its dates (`""` when unreadable). Only used by tests now.

#### Brief, report, stats, students
- `async report_command(update, context)` (`:122`): input from `override_text` → `context.args` → message text; `normalize_date_input` (non-strict) → None → `date_error_reply(raw, "/report")`; else `⏳ _Gathering live portal records for <date>..._`, `brief.compose_daily_brief(day=...)`, `send_brief_text(lambda t, m: update.message.reply_text(t, parse_mode=m), text)`, delete the ⏳ note; exception → ``❌ Failed to compile report: `<e>` ``. Publishes nothing.
- `async brief_command(update, context)` (`:163`): `⏳ _Reading today's figures from the live portal (this usually takes 10 to 30 seconds)..._`, `scheduler.compose_daily_brief()` and `scheduler._send_brief(context.bot, chat_id, text)` (the same path as 18:05, without the spoken part and without the Supabase copy), delete the note; exception → `❌ Failed to compile brief: ...`.
- `_fig(value)` (`:187`); `format_stats_report(dash: dict) -> str` (`:192`): `📊 *Hangeul Admin Quick Stats*`, then the portal's own tiles grouped by `group` (`` • <label>: `<text or not available>` ``), and `_Pending payment and Under review are separate figures._`. Tiles present but empty, or no summary → `• Dashboard figures: not available (the portal dashboard could not be read).` The old summary layout (Total Applicants, Visas Approved YTD, …) remains only for **mock mode** (`src\scraper\mock_data.py`).
- `async stats_command` (`:233`): `admin_client.get_dashboard()` (never raises: `{"error": why}` on failure) → `cloud.seen(reads, dashboard=dash)` → `format_stats_report` → `reply_long` → `cloud.publish(reads)`.
- `async students_command` (`:247`): `admin_client.get_applications()` (first page, 50 newest); `cloud.seen(reads, page=apps)` (page 1 only: never a complete list); up to 8 students, each: `• <✅|⏳|📝> *<name>* (<intake>)`, `  └ *Program:* …`, `` └ *Univ:* … | *Status:* `<stage>` ``; emoji ✅ for Approved/Admitted, ⏳ for Review; failure → `portal_error_reply("The student list", e)` (nothing published); empty → `ℹ️ The student list on the portal is empty.`; after the reply `cloud.publish(reads)`.

#### The pinned cheat-sheet
- `get_commands_cheatsheet_text() -> str` (`:279`): `📌 *HANGEUL ADMIN AI BOT — TELEGRAM MENU (PP PIN)*`, a rule line, **twelve** numbered commands with one-line descriptions and examples (`/inquiries_today`, `/inquiries_date [date]`, `/verified_today`, `/verified_date [date]`, `/crosscheck_today`, `/crosscheck_date [date]`, `/crosscheck_range [start → end]`, `/sendmail`, `/missing`, `/stage`, `/performance_today` "└ *Today: the portal's Consultant Performance page — tiles, top performer, leaderboard*", `/performance_month` "└ *This month: the portal's Consultant Performance page — tiles, top performer, leaderboard*"), an "Interactive Date Asking" note (a date command without arguments asks for the date), and a guardrail line claiming "100% Read-Only & Live Portal Verified (`students.php` only; Signed Students strictly excluded)" (the "students.php only" part is stale: the bot also reads consult_requests, calendar, index, window_applications, progress pages and now consult_performance).
- `async pin_command` (`:320`): sends the cheat-sheet, `pin_chat_message(disable_notification=False)`, confirms `📌 *Command Cheat-Sheet successfully PINNED to chat header! (PP Pin)*…`; pin failure (no "Pin Messages" right) → an italic note that the sheet was sent.

#### /admitted
- `async admitted_command` (`:346`): query from `context.args` or `override_query`; `🔍 _Retrieving admitted students live from portal..._`; `admin_client.get_admitted_students(query=...)` → `format_admitted_report`; `cloud.seen(reads, students=result.get("listed"), dashboard=result.get("dashboard"))` (every page of the list, complete, and the tiles it was read with); failure → `portal_error_reply("Admitted students", e)`; `reply_long(..., edit=status)`; `cloud.publish(reads)`.
- `ADMITTED_ROSTER_MAX = 12` (`:375`); `format_admitted_report(result: dict) -> str` (`:378`): `result = {"students", "query", "admitted", "checked", "stage", "tile", "listed", "dashboard"}` (`listed` = every student read, `dashboard` = `get_dashboard()`'s read; added for the Supabase copy). Head `` • *Admitted:* `N` — N of the M students on the portal are at the stage “<stage>” (every page of the student list read live) ``; the dashboard's Admitted tile only as a cross-check (`⚠️ … says T, but the student list shows N`); breakdown (top 4 universities, 3 programs, 6 intakes; one university however its case is written, via `casefold`); roster of 12 (name, id, university, program, `📝 *Applications:*` lines, payment, intake); `_...and N more._` + search tip. No students → `ℹ️ *No admitted students on the portal right now.*` (+ where line). The portal ignores `?status=admitted`, so admitted is picked in code from every page (`e0d47ab`); `.stu-uni` vs application lines separated in `e164679`.

#### Inquiries (consultations)
- `INQUIRIES_LOG_MAX = 10` (`:439`), `_DONE_STATUSES = ("Consulted", "File Opened")`.
- `_bold_safe(text)` (`:443`) — `*` → `∗` (U+2217) inside a bold entity (legacy Markdown reads bold literally up to its closing `*`, so a backslash would show). `_inquiry_who(r)` (`:449`) — `" (by X)"` only for a done request whose row names who handled it; `" (last updated by X)"` for another status; `" (assigned to X)"` when only a consultant (not `Unassigned`) is named.
- `format_inquiries_report(on_day, totals, display_date, totals_error=None) -> str` (`:464`): `📞 *Consultancy Inquiries Report — <date>*`, rule, all-time block (`` • *Total Inquiries on Portal:* `N` ``, `` • *Total All-Time Done:* `N` (N Consulted, N Files Opened) ``, `• *Still New:* … | *No Answer:* … | *Wrong Number:* …` with each figure in a code span, other statuses) or `• All-time figures: not available (couldn't read the portal's status counts: <why>)`; `📅 *Consultations on <date>:*` (was `Performance on <date>` until `314afdb`, renamed so the word "performance" means only the portal page) with Received, Done, ├ Consulted, └ File Opened, Pending / New, No Answer / Other with the split; `• *Consultations Handled by:*`; `📋 *Inquiries Log:*` up to 10 rows (`*i. <name>* [<program>]`, `` └ <✅|📁|⏳|📵> Status: `<status>`<who> | City: <city or N/A> ``), `_...and N more inquiries received on <date>._`; or `ℹ️ *No new consultation requests were recorded on <date>.*` (Jennie's `_NOTHING_FACTS` match this sentence).
- `async build_inquiries_report(target_date_input: str = "today", strict: bool = False, reads: Optional[Dict[str, Any]] = None) -> str` (`:534`): `normalize_date_input` → None → `date_error_reply(..., "/inquiries_date")`; a future day → `ℹ️ *Consultancy inquiries on <date>:* not available (a date in the future).`; `admin_client.read_consultation_day(day)` (the portal's own date filter, so any day) → failure → `portal_error_reply`; `cloud.seen(reads, consultations=on_day)`; `read_consultation_totals()` failure only blanks the all-time block; `cloud.seen(reads, totals=totals, totals_error=portal_error_reason(e) or None)`; the report; `cloud.seen(reads, inquiries_report=report)`.
- `async _send_inquiries_report(update, raw_input, waiting, strict)` (`:572`): owns `reads = {}`; `⏳ _<waiting>_`, build (any exception → `❌ Error building the inquiries report: <reason>`), `reply_long(edit=status)`, `cloud.publish(reads)`.
- `async inquiries_today_command` (`:607`) → `_send_inquiries_report(update, "today", "Consulting live portal for today's consultancy inquiries...", strict=True)`.
- `async inquiries_date_command` (`:614`): input `override_text` → `args`; none → prompt (§8.6); unreadable (strict) → `_ask_date_again` + `date_error_reply`; else report with `Consulting live portal for inquiries (<input with "_" replaced>)...` (an `_` of the user's own would end the italic early).
- `async consultations_command`, `async inquiries_command` (`:780-786`): aliases of `inquiries_date_command`.

#### Verified payments
- `async verified_today_command` (`:650`): sets `override_date = "today"` → `verified_command`.
- `async verified_date_command` (`:657`): input `override_text` → `args`; none → prompt; else `override_date = raw` → `verified_command`.
- `async verified_command` (`:858`): precedence `override_text` (**strict False**: words routed from free text may have no date, then today) → `override_date` (strict) → `args` (strict) → message text (strict). None → `_ask_date_again(context, "verified", raw)` + `date_error_reply(raw, "/verified_date")`. `yearless_day_problem(day, local_today())` → `ℹ️ *Verified students on <date>:* not available (<why>).` (nothing read, nothing published). Else `⏳ _Gathering verified student records for <date>..._`, `admin_client.get_verified_students(target_date=day)` (every page; raises instead of returning [] when it cannot read) → `cloud.seen(reads, verified=(day, verified_list))` → `format_verified_students_report`; failure → `portal_error_reply(f"Verified students for {display_date}", e)`; `reply_long(edit=status)`; `cloud.publish(reads)`.
- `format_verified_students_report(verified_list, display_date) -> str` (`:798`): empty → `ℹ️ *No student payments were verified on <date>.*`; else `✅ *Student Payment Verifications — <date>*`, `` • *Total Students Verified:* `N` ``, `` • *Total Verified Revenue:* `৳ 28,000.00 BDT` (<what it adds up>[; the N with an amount on the portal, M without]) ``, `📋 *Verified Student Records:*`, per student `*i. <name>*`, `├ 🎓 *Program:*`, `` ├ 💰 *Payment:* `<payment_text>` ``, `└ 👤 *Verified by:* <verifier> (<time>)`. Only what the rows show; a missing field is `—` (the baseline invented a `20,000.00 BDT` amount and "Student"/"Admin" stand-ins).
- `async alerts_command` (`:788`): `ask.reply(update.message, ask.Route("dashboard", topic="attention"), "/alerts")` — the dashboard's live "Needs attention" card (publishes the dashboard facts through `ask.reply`). (The old reply was always "No urgent alerts": the live dashboard has no urgent-alerts list; fixed `344a247`.)

#### Performance (`/performance_today`, `/performance_month`, `/perf_today`, `/perf_month`, `/performance`)
- `async _send_performance_report(update: Update, kind: str) -> None` (`:718`): owns `reads = {}`; sends `performance.waiting_text(kind)` (Markdown); `report = await performance.build_performance_report(kind, reads=reads)` (any exception, i.e. a bug, since the builder itself never raises for a portal problem → ERROR log and `❌ Error building the performance report: <portal_error_reason(e), escaped>`); then **for each** `piece` of `performance.message_pieces(report)`: `reply_long(update.message, piece, edit=status_msg if i == 0 else None)` (the ⏳ note becomes piece 1; a piece whose Markdown Telegram refuses goes as plain text); finally `cloud.publish(reads)` (not awaited).
- `async performance_today_command(update, context)` (`:742`) / `async performance_month_command(update, context)` (`:752`): ⛔ reply if unauthorised; else `_send_performance_report(update, "today" | "month")`. (Docstrings call them "Menu 12" / "Menu 13", their place in `set_my_commands`.)
- `async performance_command(update, context)` (`:762`): ⛔ if unauthorised; `route = ask.performance_route(" ".join(context.args or []), local_today())`; topic `today`/`month` → `_send_performance_report(update, route.topic)`; anything else → `ask.performance_other_reply(route)` (Markdown) — so `/performance` alone is today, `/performance month` this month, `/performance yesterday` the honest other-period reply, never a stand-in period.

#### /passports
- `PASSPORTS_OCR_MAX = 5` (`:915`). `async passports_command` (`:969`): `⏳ _Reading every student's passport scan live from the portal..._`; `admin_client.read_students()` → `cloud.seen(reads, students=students)`; `_stamp_guard(students)` then today's payment-verified students as cards (`_verified_between(students, today, today)`); a stamp problem blanks only the "verified today" part; OCR-checks the first 5 cards (`_audit_cards`) → `cloud.seen(reads, cards=cards[:5])`; `format_passports_report`; `_send_blocks`; `cloud.publish(reads)`.
- `format_passports_report(students, today_cards, display_date, read_at, today_problem="") -> str` (`:918`): `🛂 *Passport Scans — live from the portal (<read_at>)*`, students on the portal, with a scan (`files` entry starting `passport_`), without (by `details["Passport Status"]`), `` 📅 *Payment-verified today (<date>):* `N` `` with each card's verdict or `not checked here (see /crosscheck_today)`, and an honest OCR claim (`_ocr_checked`). The hard-coded 10 Sep text of the baseline is gone (`40da0e6`).

#### /calendar
- `CALENDAR_UPCOMING_MAX = 20` (`:1011`). `format_calendar_report(cal_data: dict, filter_query: Optional[str] = None) -> str` (`:1014`): today's view — `⚡ *Reminders for today (N items):*` (title, program, `type · `date_range``, `— *N days left*`), skipped untitled entries, `📌 *Upcoming (N on the 45-day timeline):*` up to 20 rows + `_…and N more (search one: /calendar <university>, or a week: /calendar next week)._`; an `"error"` key or `layout_ok` False → `ℹ️ Today's reminders are not available right now (the calendar page could not be read).` The `filter_query` branch (substring search) is legacy; `calendar_command` now sends only the default view here.
- `async calendar_command` (`:1095`): input `override_text` → `args` (with `/deadlines` and no deadline word → `"deadlines " + args`) → message text; `q = ask.calendar_query(raw)`; `q.problem` → `date_error_reply(raw, "/calendar", q.problem)`; not default → `ask.answer_calendar(q, reads=reads)` then `cloud.publish(reads)`; default → `admin_client.get_calendar_events()` → `format_calendar_report` (errors → `portal_error_reply("The calendar", e)`; **this default view publishes nothing**: `get_calendar_events` returns parsed reminders, not the page `calendar_items` needs); both after a `⏳ _Consulting live calendar & admission deadlines..._` note, via `reply_long(edit=...)`.

#### /sendmail (the only write outside the bot: an email via Gmail)
- `_send_gmail(to_list: list, subject: str, body: str) -> (ok: bool, info: str)` (`:1148`): sender = value in secrets\bot.env (GMAIL_ADDRESS), password = value in secrets\bot.env (GMAIL_APP_PASSWORD) with spaces removed (a Google **app password**); either missing → `(False, "Gmail is not configured. Add GMAIL_ADDRESS and a Google APP PASSWORD as GMAIL_APP_PASSWORD to your .env, then restart the bot.")`. `EmailMessage` → `smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30)`, `login`, `send_message`. Returns `(True, "sent from <sender> to <to>")` or `(False, "<Type>: <e>")`. Synchronous (blocks the loop for the SMTP round trip).
- `async _find_student_for_email(query)` (`:1174`): `_find_student_in_export` first; any exception → log and `_find_student_on_list_page`.
- `async _find_student_in_export(query)` (`:1187`): GET `<base>/students.php?export=csv` (60 s; re-login once if it lands on `login.php`), `csv.DictReader` on `utf-8-sig`; no rows or no `Student ID` column → `RuntimeError`. Match order: exact normalised `Student ID` (`HNG-YYYY-NNN`), then suffix of ≥3 digits, then a ≥3-letter substring of `Full Name`. → `{"id", "hng", "name", "email", "dob", "passport_no", "passport_expiry"}` from columns `Student ID`, `Full Name`, `Email`, `DOB`, `Passport No`, `Passport Expiry`.
- `async _find_student_on_list_page(query)` (`:1229`): every page via `admin_client.read_students()` (raises `PortalUnavailable` rather than "no student"); matches uid, HNG id, HNG suffix, or name; an email that is not an address (`re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+")` fails, e.g. Cloudflare's `[email protected]` stand-in when its hex could not be decoded) is not an email — since `9ead47d` the parsers put the real address back (`parsers.decode_cf_emails` at every soup), so this guard now only catches an undecodable one; missing email/HNG/name filled from `admin_client.get_student_full_profile(uid)`.
- `_pick_student_email(prof) -> str` (`:1289`): the `email` key first; then any key containing "email" but not guardian/parent/father/mother/whats; then any email-looking value.
- `async _ai_write_email(brief, student, subject) -> str` (`:1312`): `ollama_client.generate_response(prompt, system=...)`; the system prompt writes as `<manager name>, Manager at Hangeul Korean Language and Visa (HKLV) in Dhaka`, output only the body with the sign-off `<manager name>\nManager, HKLV`, no subject, no invented facts. The Ollama "AI is down" fallback text (markers `operational intelligence`, `ollama service is not currently responding`, `request processed successfully`, `please verify ollama is started`) or <15 chars → a plain template `Dear <name>,\n\n<brief>\n\nPlease let us know if you have any questions.\n\nThanks,\n<manager name>\nManager, HKLV`, so the fallback text never leaks into an email.
- `async _handle_email_flow(update, context, text)` (`:1354`) — steps:
  - any input step + `cancel|/cancel|stop|deny|quit` → pop flow, `❌ Cancelled — no email sent.`
  - `id`: `⏳ _Looking up the student…_`; lookup error → `portal_error_reply("The student lookup", e)` + "Send the *HNG number, ID, or name* again in a minute, or type *cancel*." (stay on `id`); no match → `ℹ️ No student found matching `<q>`…` (stay); no email → `⚠️ Found … but there is *no email address on that record*, so I can't send. Cancelled.`; found → `✅ Found *<name>*  ·  `<email>`` + "type the *SUBJECT*" → step `subject`.
  - `subject` → saved → step `brief`.
  - `brief` → `🤖 _Writing it professionally…_` → `_ai_write_email` → step `confirm`; preview `📧 *Draft ready — please review:*`, To, Subject, body, `Reply *SEND* to send it · *EDIT* to rewrite (you'll re-brief me) · *DENY* to cancel.` sent via `_chunk_message`, each chunk retried without Markdown if refused.
  - `confirm`: `send|yes|confirm|ok|okay|send it` → `_send_gmail` → `✅ Email sent — <info>` / `❌ Could not send: <info>` (flow popped either way); `edit|rewrite|change|redo` → back to `brief`; `deny|cancel|no|stop|quit` → `❌ Denied — the email was not sent.`; else "Please reply *SEND*, *EDIT*, or *DENY*."
  - unknown step → flow popped.
  **Nothing is sent without an explicit SEND** typed by an authorised user; voice notes never drive this flow. The flow publishes nothing to Supabase.
- `async sendmail_command` (`:1472`): ⛔ if unauthorised; sets `email_flow = {"step": "id"}`; with args → straight into the id step; else the step-1 prompt (examples `HNG-YYYY-NNN · NNN · <name>`).
- `_chunk_message(text, limit=3900) -> list` (`:1492`): `split_text` when longer than `limit`, else `[text]`.

#### Cross-checks (`/crosscheck`, `/audit`, `/crosscheck_today`, `/crosscheck_date`, `/crosscheck_range`)
Every cross-check reads the **whole** student list live (`admin_client.read_students()`: every page, session renewed when expired, a failed read raised), picks students by the row's own `Payment verified by NAME · 27 Sep, 17:19` stamp, and OCR-checks each passport scan right then (`admin_client.audit_student_passport`).
- `CROSSCHECK_NAME_MAX = 10` (`:1506`). `_CROSSCHECK_WORDS_RE` (`:1510`): the command, punctuation and words around what a cross-check asks for (`cross check`, `audit`, `verify`, `student(s)`, `id`, `uid`, `no`, `number`, `passport(s)`, `document(s)`, `father(s)`, `mother(s)`, `parent(s)`, `address(es)`, `name(s)`, `dob`, `records`, `payments`, pronouns, filler…).
- `_crosscheck_query(raw: str, date_only: bool = False) -> Dict` (`:1517`): `{"kind": "date", "day"}` (parse_user_date; nothing left → today) | `{"kind": "uid", "uid"}` (`#?\s*(\d{1,6})` — the N of `student_edit.php?id=N`) | `{"kind": "hng", "hng"}` (`\bHNG-\d{4}-\d+\b`, upper-cased) | `{"kind": "name", "name"}` (≥3 letters) | `{"kind": "error", "reply"}` (unreadable date, or too little: ``⚠️ I need a date, a student ID or at least 3 letters of a name to cross-check, e.g. `/crosscheck 27 Sep 2026`, `/crosscheck <uid>` or `/crosscheck <name>`.``). With `date_only`, anything but a date → `date_error_reply(body, "/crosscheck_date")`. Month names count only as whole words, so a name that merely contains a month's letters (for example one beginning "Jun" or ending "mar") is never read as a date.
- `_stamp_guard(students) -> None` (`:1555`): raises `PortalUnavailable` when there are student rows but no `verified_line` on any, or a `verified_stamp` that `src.dates.parse_stamp` cannot read ("DD Mon, HH:MM") — then no day's list can be told, not even "none".
- `_verified_between(students, first, last) -> list[(student, day)]` (`:1571`): `src.scraper.parsers.verification(student, day)` for each day in the range (whole day/month tokens; never the transfer-intake option "2027 SEPTEMBER", never the "Applied On" date, not before the student applied).
- `_stamp_minutes(student) -> int` (`:1588`, sort key within a day).
- `_crosscheck_card(student) -> Dict` (`:1597`): `{"id", "hng", "name", "name_raw", "program", "dob", "pass_no", "pass_exp", "passport_status", "passport_file", "has_pass_doc", "has_rcpt_doc" (a `receipt_` file), "payment" (paid or verified income + method), "verifier", "ver_time" (the stamp's clean text), "fields": {}, "verdict": "", "status": ""}` — only the portal's own values. (With publishing on, `_audit_cards` adds `"audit"`.)
- `async _audit_cards(cards, status_msg=None, what="") -> None` (`:1621`): edits the ⏳ note to `⏳ _Checking N passport scan(s) <what> by OCR (about 10 seconds each)..._`; no scan → `status="MISSING_DOCUMENT"`, `verdict="⏳ Pending Passport Scan (no scan uploaded on the portal)"`; else `profile_before = cloud.profile_of(c["id"])`, `audit_student_passport(id, {"name","dob","passport_no","passport_expiry"}, passport_file)`; an exception fails only that card (`status="ERROR"`, `❌ Couldn't check this scan: <reason>`); then `c.update(fields=…, status=…, verdict=…)` and `cloud.audited(c, res, form, profile_before)` (with publishing on only: `card["audit"] = {"result": dict(res), "form": form, "at": now, "profile": <the profile the audit read, or None>}`). One card at a time.
- `_NOT_OCR_CHECKED = ("", "MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "ERROR", "SCAN_UNREADABLE")` (`:1653`); `_ocr_checked(cards) -> int`; `_ocr_note(cards) -> str` (`; each scan was checked by OCR just now` only when all were; else "N of the M…"; or "no scan could be checked by OCR"). Why: the reports used to claim an OCR check for scans that were never read.
- `_format_crosscheck_results(results, header_title, checked=None, note="") -> str` (`:1675`): header `📋 *Verified Student Information Cross-Check — <title>*`, `` • *Total Records Audited:* `N` ``, `• _Read live from all N students on students.php<ocr note>._`; one card per student separated by blank lines: name + ids, `├ 🎓 *Program:*`, `` ├ 💰 *Payment:* `…` (receipt ✅ uploaded | no receipt uploaded) ``, `├ 👤 *Verified by:* <verifier> (<time>)`, `├ 🛂 *Passport Scan:* ✅ Uploaded | ⏳ None uploaded (Passport Status: …)`, `` ├ 📝 *Portal:* Pass `…` | Exp `…` | DOB `…` ``, optional `👨 Father` / `👩 Mother` / `🏠 Address` lines from the OCR `fields` (`{"father_name"|"mother_name"|"address": {"doc", "verdict"}}`, address cut to 40 chars), `└ 🔍 *Audit Verdict:* <verdict>`.
- `async _send_blocks(message, text, status_msg=None) -> int` (`:1720`): packs blank-line-separated blocks into as few messages as fit under `CHUNK_CHARS`, never cutting a card; an oversize block is split between lines; message 1 replaces the ⏳ note; each piece via `reply_long`.
- `async build_crosscheck_report(query, status_msg=None, reads: Optional[Dict[str, Any]] = None) -> str` (`:1745`): reads every page → `cloud.seen(reads, students=students)`; `date` → `_stamp_guard`, `_verified_between`, sorted by day and stamp time for ranges; none → `ℹ️ *No payment-verified students found for <title> to cross-check.*` + `_(All N students on students.php were read live.)_` + examples; `uid`/`hng` → exact match on `uid` / `student_id`; `name` → substring of the name, more than 10 matches → the first 10 checked and the rest listed with their uids; after `_audit_cards` → `cloud.seen(reads, cards=cards)`. Raises `PortalUnavailable` when the list cannot be read whole (so a failed read is never "no students found").
- `async _crosscheck_run(update, query, waiting, title)` (`:1803`): owns `reads = {}`; ⏳ note → build → `portal_error_reply(f"Cross-check for {title}", e)` on failure → `_send_blocks` → `cloud.publish(reads)`.
- `_parse_date_range(raw) -> (start, end, display) | (None, None, None)` (`:1820`): splits on `to|until|through|thru|till|–|—|..|=>|->`, else ` - ` (spaces, so ISO dates survive), else two ISO dates, else two `D Mon [YYYY]` groups; each side through `normalize_date_input(strict=True)` (an unreadable side is never today); swapped if reversed; display `DD Mon YYYY → DD Mon YYYY`.
- `async crosscheck_range_command` (`:1854`): ⛔ if unauthorised; no input → range prompt (`awaiting_date_for = "crosscheck_range"`); unreadable → `_ask_date_again` + `⚠️ I couldn't read two dates there (<why>). Please send a *start* and *end* date, e.g. `1 Sep 2026 to 15 Sep 2026`.`; span > 92 days → refused (OCR takes time); `yearless_day_problem(start)` → not available; an end after today is clamped to today (`(today)` in the display); then `_crosscheck_run` with `⏳ _Cross-checking every payment-verified student from <range> live against their passport documents… this can take a few minutes._`
- `async crosscheck_command` (`:1924`): pops `crosscheck_date_only`; ⛔ if unauthorised; input `override_text` → `args` → message text; `_crosscheck_query`; error → reply (and `_ask_date_again` when date-only); a date → `yearless_day_problem` check → `query.update(first=day, last=day, display="DD Month YYYY")`; then `_crosscheck_run` with `⏳ _Cross-checking student information, Father, Mother, DOB & Address against documents..._`.
- `async crosscheck_today_command` (`:682`): `override_text="today"`, `crosscheck_date_only=True` → `crosscheck_command`. `async crosscheck_date_command` (`:690`): input `override_text` → `args`; none → prompt; else `override_text=raw`, `crosscheck_date_only=True` → `crosscheck_command`.

#### The free-text dispatcher
- `async handle_natural_language_message(update, context, query: Optional[str] = None)` (`:1973`) — see §8.10.

#### /missing and /stage (inline buttons; reports run as subprocesses)
- `MISSING_PROGRAMS = [("KLP", "🇰🇷 KLP"), ("EAP", "📘 EAP"), ("BACHELOR", "🎓 Bachelor's"), ("MASTER", "🎓 Master's")]` (`:2172`).
- `async missing_command` (`:2180`): `📋 *Progress sheet — missing information*\nChoose a program:` + one button per program (`callback_data="missing:<KEY>"`).
- `async missing_button` (`:2192`): `query.answer()`, `⏳ Checking <label> progress sheets…`, `_run_report_module("src.sheets.missing_report", "--program", KEY)`; None → `❌ Could not build the <label> report right now. Please try again in a minute.`; delete the note; `_reply_long` (plain text).
- `async _run_report_module(module, *args) -> Optional[str]` (`:2215`): like `scheduler._run_module` but with `stdout/stderr=PIPE`, timeout 180 s, returns the printed stdout (UTF-8), or None on non-zero exit, empty output or any exception (stderr tail logged). Why a subprocess: the report uses its own read-only portal session and Google client, like the scheduled jobs, and a failure in it cannot touch the bot. The report process publishes its own reads to Supabase at its very end (`src.cloud.sheet_hooks`, [03c](03c_FILES_sheets_verify_root_scripts.md)); the bot adds nothing.
- `async _reply_long(message, text)` (`:2243`): `replies.reply_long(message, text, parse_mode=None)`.
- `async stage_command` (`:2249`): `📊 *Student stages*\nChoose a program:` + buttons `stage:<KEY>`.
- `async stage_program_button` (`:2260`): `_run_report_module("src.sheets.stage_report", "--program", KEY)` → JSON: a list `[{"intake": "MARCH 2027" | "NONE", "count": n}]` or a dict `{"error": why}`; dict/None → `❌ Couldn't read the portal: <why>.` + "Could not load <label> intakes right now…"; `[]` → `<label>: no students on the portal.`; else one button per intake (`"<intake> (<count>)"`, `"⚠️ No intake set (<count>)"`, `callback_data="stagei:<KEY>|<intake>"`).
- `async stage_intake_button` (`:2294`): parses `stagei:KEY|INTAKE`, runs `stage_report --program KEY --intake INTAKE`, sends the text plain.

#### Application
- `async post_init(application)` (`:2314`) — §8.3. `build_telegram_application()` (`:2367`) — §8.2.

### 8.8 Recurring conventions in this file
- **Input precedence** in every date command: `user_data["override_text"]` (popped) → `context.args` → `update.message.text` (for the commands that accept free text).
- **"Please wait" pattern:** send `⏳ _…_` (Markdown italic) → do the reads → `reply_long(update.message, text, edit=status_msg)` (the note becomes piece 1) or delete the note after sending.
- **Publish after the reply:** a handler that reads the portal owns a `reads = {}` dict, calls `cloud.seen(reads, <key>=<what the read returned>)` right after each successful read, sends its reply exactly as before, and only then calls `cloud.publish(reads)` (§8.13).
- **Honest failure:** a failed read → `portal_error_reply(...)`; an unreadable date → `date_error_reply(...)`; a day the yearless stamps cannot answer → `not available (<why>)`; a future day → `not available (a date in the future)`; a performance period the commands do not cover → `performance_other_reply`. Never 0, never "none", never today (or this month) in place of what was asked.
- **Escaping:** portal text through `brief.esc` (legacy Markdown v1) or `_bold_safe` inside bold; backticks stripped from values placed inside code spans.
- **Read-only:** every portal access is a GET through `admin_client` (plus its login POST); the only outgoing writes are `/sendmail`'s SMTP email after SEND, and the Supabase publish, which runs in a separate publisher process and never touches the portal.

### 8.9 Error handling summary
Every handler catches its own portal/OCR errors and replies; unhandled exceptions in a PTB handler are logged by PTB (no global error handler is registered). `stats_command` and `students_command` rely on `get_dashboard` never raising / `get_applications` raising `PortalUnavailable` (caught). The inline-button handlers always `query.answer()` first so the button stops spinning. The publish hooks (`seen`, `audited`, `profile_of`, `publish`) never raise into a handler and never delay a reply (§8.13).

### 8.10 `handle_natural_language_message(update, context, query=None)` step by step (`telegram_bot.py:1973`)
A typed question is answered by the command or live read it asks for, never by a guess. Voice notes (no `.text`) pass their English query as `query`.
1. Not authorised → return (silent). `query = update.message.text` when None; stripped.
2. `email_flow` in progress → `_handle_email_flow(update, context, query)`; return.
3. `awaiting_date_for` popped → the date-prompt answer (§8.6); return.
4. `route = ask.classify(query, local_today())`, then by `route.kind`:
   - `hello` → `ask.HELLO`. `pin` → `pin_command`.
   - `performance` → topic `month` → `performance_month_command`; topic `today` → `performance_today_command`; anything else (another day, span, month or period, or an unreadable date) → `ask.performance_other_reply(route)` (Markdown); return. (Examples in §6.5; "performence this month" reads the page exactly as the command does.)
   - a one-day kind (`inquiries`, `verified`, `passports`) with a **window**: passports with `w.first <= today` → `/crosscheck_range` over `first..min(last, today)`; else `awaiting_date_for = kind` (`passports` → `crosscheck`) and `ask.one_day_reply`.
   - `inquiries`: a date problem → `override_text=query` → `/inquiries_date` (which says it cannot read the date); no day but the words `date`/`specific` → `/inquiries_date` (asks); no day or today → `/inquiries_today`; else `override_text="DD Mon YYYY"` → `/inquiries_date`.
   - `crosscheck`: a real range in the words (`_parse_date_range`, start ≠ end) → `/crosscheck_range`; a window (e.g. "cross-check last week") → range to `min(last, today)`; a named day (today → `/crosscheck_today`, else `/crosscheck_date`); a student reference (`ask._CROSS_FIELD_RE` or a 2–5 digit number) → `crosscheck_command` with the words; an unreadable date hint → `/crosscheck_date` (says so); nothing → `/crosscheck_date` (asks).
   - `passports`: problem → `/crosscheck_date` with the words; no day or today → `/crosscheck_today`; else `/crosscheck_date` for the day (the live cross-check, never a stored list).
   - `verified`: today → `/verified_today`; a day or a problem → `override_text=query` → `/verified_date`; `date`/`specific` → `/verified_date` (asks); else `override_text=query` → `verified_command` (non-strict: no date = today).
   - `admitted`: question words stripped (`show, list, who, is, are, students, admitted, how, many, …`) → `override_query` → `admitted_command`.
   - `missing` → `missing_command`; `stage` → `stage_command`; `calendar` → `override_text=query` → `calendar_command`; `report` → `override_text=query` → `report_command`; `stats` → `stats_command`.
   - `applied` with a date problem → `date_error_reply(query, reason=problem)`.
   - everything else (`pending`, `window_review`, `dashboard`, `intake`, `applied`, `unknown`) → `ask.reply(update.message, route, query)` (which publishes what it read).

### 8.11 History of `telegram_bot.py` (non-merge commits)
| Commit | Change in this file |
|---|---|
| `366dec0` | Baseline from GitHub (1980 lines): first-sender binding in `is_authorized`, `normalize_date_input` always returning a date, page-1 scrapers for cross-checks (`_audit_crosscheck_row`, `build_crosscheck_range_report`), keyword free-text routing, hard-coded `/passports` text |
| `c5c1a7c` | `is_authorized` refuses everyone when no id is configured; root copy kept identical |
| `d7a5817` | voice handler registration behind `JENNIE_VOICE_ENABLED`; `handle_natural_language_message(..., query=None)` |
| `e205327` | an LLM answer Telegram cannot parse as Markdown is resent as plain text |
| `d9bbecc` | `post_init` starts `warm_brain()` in the background |
| `cd0277a` | inquiries read by column name (the portal's new 7-column consult_requests layout had zeroed every count) |
| `f8fefa4` | `/brief` added; `/report` uses the factual brief; stats "not available"; verified formatter without invented amounts |
| `e0d47ab` | strict dates (`normalize_date_input` → None), `reply_long` everywhere, `/verified` and `/admitted` from every page, `/students` real columns |
| `46cdf03` | inquiries via the portal's date filter and status-tab totals; `format_inquiries_report`, `_inquiry_who`, `_bold_safe` |
| `9dcd9ad` | `/stage` intake JSON error handling |
| `40da0e6` | cross-check engine rewritten (`_crosscheck_query`, `_stamp_guard`, `_verified_between`, cards, `_audit_cards`, `_send_blocks`); live `/passports` |
| `7f42ad0` | free text through `ask.classify`; `/calendar` through `ask.calendar_query` |
| `344a247` | `/alerts` → Needs attention; `/stats` via `reply_long`; `/sendmail` fallback reads every page; prompt formatting |
| `e164679` | `DATE_PROMPT_KEY` / `_ask_date_again`; `/admitted` applications lines; paid vs verified income; honest OCR counts; full calendar timeline; `/deadlines <words>` |
| `c17d887` | a ≤2-word mistyped answer keeps the date question open; `SCAN_UNREADABLE` not counted as OCR-checked; brain pinned only when voice is on, else unloaded at start |
| `2b6798f` | the Supabase command hooks: `reads` dicts, `cloud.seen` after each read, `cloud.publish` after each reply; `build_inquiries_report(reads=)`, `build_crosscheck_report(reads=)`; `_audit_cards` keeps the whole audit (`profile_of`, `audited`) |
| `bbd8f98` | `/performance_today`, `/performance_month` (+ `/perf_today`, `/perf_month`, `/performance`), menu 11 → 13 entries, cheat-sheet and `/start` lines, `post_init` log counts `len(commands)`; first (self-computed) report |
| `ce23535` | the handler shows only the portal page (`performance.build_performance_report`); menu/cheat-sheet/start texts name the page |
| `314afdb` | `_send_performance_report` sends `performance.message_pieces` one by one; free-text `performance` with no topic → `performance_other_reply`; inquiries heading `Consultations on <date>` |
| `e4d1cea` | `_send_performance_report` keeps the page (`reads=`) and publishes it after the reply |

(`e5e532e`, the merge of `main` into `cloud/release`, joined the hooks and the performance handlers without a text conflict; the root copy stayed byte-identical.)

### 8.12 The root `telegram_bot.py` must be byte-identical
- `C:\Hangeul\BOT\telegram_bot.py` is a **staging copy** of `C:\Hangeul\BOT\src\bot\telegram_bot.py`; `cmp` confirms they are identical at `8317741` (2437 lines each), and every commit that touched one touched the other with the same diff (`tests/test_performance.py::test_the_root_staging_copies_are_byte_identical` checks it).
- Why: `apply_bot_update.bat` (the owner's one-click update) stops the bot (`stop.bat nopause`), takes `telegram_bot.py` from the bot folder (else the newest `%USERPROFILE%\Downloads\telegram_bot*.py`) and **copies it over `src\bot\telegram_bot.py`**, does the same for `config.py` → `src\config.py`, clears `__pycache__` under the bot and `src` (not `.venv`), verifies with `findstr /C:"crosscheck_range"` and `findstr /C:"def authorized_ids"`, then runs `start.bat`. A stale root copy would silently roll back every fix on the next update (and would now drop the performance commands and every publish hook).
- Rule for any change: edit `src\bot\telegram_bot.py`, copy it to the root, check with `cmp` (or `fc /b`). The same rule holds for root `config.py` ↔ `src\config.py` (both gained the Supabase settings in `36ae72e`) and root `progress_builder.py` ↔ `src\sheets\progress_builder.py`.
- Nothing imports the root copy (`run.py` imports `src.bot.telegram_bot`).

### 8.13 The Supabase publish hooks in the handlers (`src.cloud.command_hooks`)
The contract every handler follows (module docstring of `src\cloud\command_hooks.py`; full layer in [03d](03d_FILES_src_cloud.md), [13](13_SUPABASE_PUBLISHING.md)):
```python
reads = {}
students = await admin_client.read_students()
command_hooks.seen(reads, students=students)       # the read's result and the time it was read
...                                                # the reply is built and sent exactly as before
command_hooks.publish(reads)                       # after the reply: returns at once
```
| Function | Signature | Contract |
|---|---|---|
| `active()` | `-> bool` | publishing is on (`handoff.enabled()`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `CLOUD_PUBLISH_ENABLED` all set) **and** `admin_client.mock_mode is False` (demo data is never the portal's). Never raises |
| `seen(reads, **values)` | `-> None` | does nothing unless `active()` and `reads` is a dict; drops None values; `reads.update(values)`, `reads["at"][key] = now()` for each, `reads["today"] = local_today()` once. Failure → WARNING `Supabase publish failed (command): a read could not be kept (<Type>)`. Never raises |
| `profile_of(uid)` | `-> Optional[Dict]` | the profile `admin_client._profile_cache` holds for `uid` now |
| `audited(card, result, form, before)` | `-> None` | with publishing on: `card["audit"] = {"result": dict(result), "form": form, "at": now(), "profile": <after, if another object than before, else None>}` |
| `publish(reads, job="command")` | `-> Optional[asyncio.Future]` | nothing for an empty `reads` or when not active; else a background task (strong reference kept in `_tasks`) runs `build(reads)` and `handoff.submit("command", batches, failed)` in a worker thread (`asyncio.to_thread`; with no running loop, a daemon thread `cloud-handoff`). `submit` writes `data\cloud\pending\<time>-command.json` and starts the publisher process without waiting. A build that fails is one WARNING line with the exception **type only** (an exception text can quote student data). Never raises, never awaited by a handler |
| `drain(timeout=None)` | `async` | waits for this loop's handoffs (tests, clean shutdown) |

What each handler keeps, and what it becomes (`command_hooks.build`):

| Handler (entry points) | `seen(...)` keys | Kinds published |
|---|---|---|
| `stats_command` (`/stats`) | `dashboard` | `dashboard_fact` (tiles only, partial); a `{"error"}` read → failed read `index.php` |
| `students_command` (`/students`) | `page` | `student` (scope all, partial: page 1 only) |
| `admitted_command` (`/admitted`, free text) | `students` (every page), `dashboard` | `student` (complete) + `verification` per stamp day; `dashboard_fact` (partial) |
| `_send_inquiries_report` → `build_inquiries_report` (`/inquiries_today`, `/inquiries_date`, aliases, free text) | `consultations`, `totals`, `totals_error`, `inquiries_report` | `consultation` (scope day; complete only when the portal listed every request of the day), `consultation_day`, `consultation_totals`, report `inquiries_report\|<day>` (partial) + its `report_section` rows |
| `verified_command` (`/verified_today`, `/verified_date`, `/verified`) | `verified=(day, list)` | `verification` (scope day, complete) — only for a day the yearless rule allows |
| `passports_command` (`/passports`) | `students`, `cards` (first 5) | `student`, `verification`, `passport_audit` (partial), `student_profile` |
| `_crosscheck_run` → `build_crosscheck_report` (every cross-check command and route) | `students`, `cards` (+ `card["audit"]` from `_audit_cards`) | `student`, `verification`, `passport_audit` (scope all, partial; audits that checked nothing left out), `student_profile` (scope uid, complete) |
| `calendar_command` non-default → `ask.answer_calendar` | `calendar` | `calendar_item` (never complete: the page shows this month and the next 45 days) |
| `ask.reply` → `answer_pending` | `pending=(students, badge)` | `pending_payment` (complete only when the rows saying Pending equal the badge) |
| `ask.reply` → `answer_dashboard`, `answer_unknown`, `answer_window_review`; `alerts_command` | `facts` | `dashboard_fact` (complete only when every tile group and card is on the page) |
| `ask.reply` → `answer_intake`, `answer_applied` | `students` | `student` + `verification` |
| `_send_performance_report` → `performance.build_performance_report` (`/performance_today`, `/performance_month`, `/perf_*`, `/performance`, free text) | `performance=(kind, page)` | `consultant_performance`: one record per leaderboard row (key `<period>\|<first ISO day>\|<name>`) + one summary (`…\|summary`), scope **`<period>\|<first ISO day>`** (since `8317741`: the portal ends every period at today, so a scope holding the last day changed daily and would strand a dropped consultant); complete only for a whole read |

**Publishes nothing:** `/start`, `/help`, `/pin`, `/report`, `/brief` (only the 18:05 job's brief is published, §5.2), `/calendar`'s default view, `/sendmail`, `hello`, `performance_other_reply`, date errors, a failed read (a failed read keeps nothing, so it can never become `rows=[]` with `complete=True`, which would empty a scope). `/missing` and `/stage` publish from their own report subprocess (sheet hooks, [03c](03c_FILES_sheets_verify_root_scripts.md)).

**Why after the reply and never awaited:** a reply must never be delayed, changed or stopped by publishing (`tests/test_cloud_performance.py` and `tests/test_cloud_commands.py` check that the reply is the same with publishing on or off). The bot process never embeds or uploads (it holds torch for the OCR and must keep its event loop free); the publisher process does both. State on 30 Sep 2026: publishing ON since 22:27 (`CLOUD_PUBLISH_ENABLED=true` on `.env` line 43), after the one-time backfill (21:48–22:05: 13,540 records, 15,629 chunks, 0 failed reads) and an independent postcheck.

---

## 9. Stale strings and quirks worth knowing (all verified at `8317741`)
- `post_init`'s log is now right (`Successfully set 13 bot menu commands`), but `apply_bot_update.bat:78` still tells the user to look for `"Successfully set 9 ... bot menu commands"`, and the comment above the handlers (`telegram_bot.py:2376`) still says "Register the 6 official menu command handlers".
- `start_command` and the cheat-sheet list **12** numbered commands (no `/brief`), so `/performance_today` and `/performance_month` are numbered 1️⃣1️⃣ and 1️⃣2️⃣ there, while their docstrings call them "Menu 12" and "Menu 13" (their place among the 13 `set_my_commands` entries).
- The cheat-sheet guardrail line says "`students.php` only; Signed Students strictly excluded"; the bot reads several other portal pages (now also `consult_performance.php`).
- `scheduler`'s startup log omits the 08:30 issue-date refresh and the 10-minute brain job; it mentions the full picture only while publishing is on, although the job is always registered.
- The comment `scheduler.py:490` ("# 6. Jennie's brain stays in VRAM (loaded at startup by post_init); reload it if Ollama lost it") is stale since `c17d887` (28 Sep): with the voice off the brain loads on demand, and `keep_brain_warm` (`scheduler.py:317-325`) returns at once unless `ollama_client.brain_pinned()` (`JENNIE_VOICE_ENABLED` or `BRAIN_ALWAYS_LOADED`, `ollama_client.py:37-39`).
- `src\cloud\backfill.py`'s docstring (`:6-16`, `:22-27`) still says only the hourly job reads the Consultant Performance page; since `8317741` the backfill reads it too (`backfill.py:568-569`, [03d §6](03d_FILES_src_cloud.md)).
- `src\cloud\command_hooks.py`'s docstring still gives the `consultant_performance` scope as `"<period>|<first day>|<last day>"`; since `8317741` it is `"<period>|<first ISO day>"` (`records.performance_scope`, `records.py:823`).
- `_RedactBotToken` keeps its name although it now redacts the Supabase keys and JWTs too.
- `_find_student_on_list_page`'s docstring still speaks of the list hiding e-mails as `[email protected]`; since `9ead47d` the parsers decode them, and the guard only catches an undecodable one.
- `AsyncIOScheduler()` is created without a timezone; the cron jobs pass `tz` explicitly, the interval jobs do not need one (the full picture's `start_date` is `datetime.now(tz)`).
- The daily brief goes to `TELEGRAM_ADMIN_CHAT_ID` only; `TELEGRAM_BRIEF_CHAT_IDS` / `brief_recipient_ids()` govern the sheet jobs' messages, not the brief.
- The cheat-sheet is re-sent and re-pinned on every bot start (silently, `disable_notification=True`); after the 30 Sep 20:35 reboot the watchdog's duplicate start sent it twice.
- `_send_gmail` is synchronous inside an async handler (the event loop waits for SMTP, up to its 30 s timeout).
- Helpers kept only for tests: `telegram_bot.parse_user_report_intent`, `brief.brief_plain`, `brief.split_brief`, `replies.send_long`; `brief._day` is unused.
- `data\windows-ca.pem` is absent on this PC, so `src\__init__.py`'s CA block does nothing here.
- Voice: `JENNIE_VOICE_ENABLED=false` and `JENNIE_SPOKEN_BRIEF=false` in `.env`; `JENNIE_VOICE_URL` is not set (default `http://127.0.0.1:8765`); `BRAIN_ALWAYS_LOADED` / `BRAIN_IDLE_UNLOAD` not set (defaults `False` / `"5m"`), so the brain loads on demand and unloads after 5 idle minutes.

## 10. Rebuild checklist for this layer
1. `src\__init__.py`: the redaction filter (bot token with `:` and `%3A`, `Bearer`/`apikey` values, `sb_secret_`, `sb_publishable_`, `sbp_`, JWTs) on `httpx`, every `httpcore` logger and the cloud logger, before any Telegram or Supabase call; optional CA-bundle env vars.
2. `replies.py` first: UTF-16 length, line-boundary splitting at 3900, Markdown→plain resend, edit-the-wait-message, `date_error_reply`, `portal_error_reply`. Route every reply through it.
3. Authorization by an explicit allow-list; refuse everyone when it is empty; show the chat id in the refusal.
4. A strict date parser that returns None (never today) for anything it cannot read; a yearless-stamp rule; a date-prompt conversation keyed in `user_data` with re-ask on a short or date-like wrong answer.
5. Every figure from a live read, counted in code; every unknown "not available (why)"; pending payments and window applications never added together.
6. Performance = the portal's own Consultant Performance page only: one GET per period through its own period link (never the Custom range form), refuse a page showing another period, keep every figure as printed, say where the page disagrees with itself, split between whole records, route the owner's spellings, and answer any other period honestly without reading anything.
7. LLM only where its output is checked: the brief's summary and Jennie's English through `claims_problem`; the free-text fallback lets the LLM pick facts by number, shown word for word; Korean speech built from the fact in code.
8. Jobs that touch other systems as subprocesses with timeouts; the watcher's memory keyed by uid + upload file name, saved atomically after each audit, alerts marked sent only after Telegram accepted them.
9. A second copy of what was read (Supabase): keep each read's result in a per-request dict, publish only after the reply (or after the job's own work), never await it in a handler, never raise, do nothing while off or in mock mode, keep nothing for a failed read, and do the embedding and upload in a separate process.
10. Keep any staging copy byte-identical to the file it is copied over.
