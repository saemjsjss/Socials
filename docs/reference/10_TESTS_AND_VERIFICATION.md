# 10 — Tests and verification

**What's in this file:** the pytest suite in `C:\Hangeul\BOT\tests\` (**1152 tests** in 24 files plus `conftest.py` at `8317741`): how to run it, the two safety skips in a checkout that has a real `.env`, the fake-portal, fake-Telegram and **fake-Supabase** (`httpx.MockTransport`) patterns, the `pin_today` date pin, and what each test file pins. It also covers the independent-audit method used on 28 Sep 2026 to prove every command's figures against the live portal (handlers run with fakes, every number re-derived by separate read-only reads) and the workflows that fixed what the audit found, plus the live-check tools as code to copy (§4.6: the network and Google guards, `mask()`, the legacy Markdown parser). And it covers **how the Supabase release of 29-30 Sep 2026 was verified** (§4.7-§4.12): three code reviews, three guarded dry runs, the preflight of the merged release, the real backfill and the independent postcheck, with their numbers.
The modules under test are mapped in [03c_FILES_sheets_verify_root_scripts.md](03c_FILES_sheets_verify_root_scripts.md) (sheets, verify, root scripts) and the command surface is in [05_TELEGRAM_COMMANDS_AND_JOBS.md](05_TELEGRAM_COMMANDS_AND_JOBS.md). The document-check rules the tests assume are in [07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md). The `src\bot\` and scraper modules under test are mapped in [03a](03a_FILES_src_bot.md) and [03b](03b_FILES_src_scraper_llm_api_config.md), the Supabase publish layer `src\cloud\` in [03d](03d_FILES_src_cloud.md) and what it publishes in [13_SUPABASE_PUBLISHING.md](13_SUPABASE_PUBLISHING.md); the audit verdicts per command are in [11 §G](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md); the method as a reusable recipe is in [09 Part B](09_BLUEPRINT_RULES_AND_LESSONS.md); the history of each step in [08](08_HISTORY_STAGE_BY_STAGE.md); the pack index is [00_INDEX.md](00_INDEX.md).

**Pack written:** 29 Sep 2026 from `c17d887` (659 tests). **Refreshed:** 30 Sep 2026 (Asia/Dhaka) to `main` = `8317741` (48 commits). Line numbers are `path:line` at `8317741`.

No real student data appears here. The tests themselves use invented names and synthetic pages; the verification numbers below are counts only. Secrets are named, never shown: "value in `secrets/bot.env` (KEY)".

---

## 1. Running the suite

```powershell
cd C:\Hangeul\BOT
.venv\Scripts\python.exe -m pytest tests -q
```
- **Result at `8317741`: 1152 tests.** Measured on 30 Sep 2026 in a clean copy (`git archive 8317741`, no `.env`), run with the bot's venv: **`1152 passed in 54.70s`**, 0 skipped. In the live checkout `C:\Hangeul\BOT`, which has the real `.env`, **2 of the 1152 skip by design** (the two safety skips below; recorded at the deploy of 30 Sep 21:47, not re-run for this pack because a run there would write `__pycache__`/`.pytest_cache` into the live folder unless both are switched off). Earlier milestones: `659 passed in 20.14s` at `c17d887` (28 Sep); `1150 passed in 47 s` at `e4d1cea` (the release preflight, run in the worktree `C:\Hangeul\JARVIS\cloud\release` with `-p no:cacheprovider`).
- **The slowest tests** (30 Sep, `--durations=8`): the watcher's no-freeze test 7.5 s, the real gte-small test 7.2 s (loads the model on the CPU), the missing-model child process 6.9 s, the GPU-hiding probe child 2.4 s; everything else is under 1.6 s.
- **pytest is not in `requirements.txt`.** The venv has `pytest 9.1.1` (with `pluggy 1.6.0`, `iniconfig 2.3.0`, and `anyio 4.15.1` from httpx). There is **no** `pytest-asyncio`: async code is driven with `asyncio.run(...)` inside ordinary test functions. There is no `pytest.ini` or `pyproject.toml`.
- **`tests\conftest.py` (29 lines, since 36ae72e)** does three things for every file: puts the bot folder on `sys.path`; registers the marker `slow` ("loads a real model (skipped when the model is absent)"); and an **autouse fixture `_no_real_supabase`** that sets `settings.SUPABASE_URL = ""`, `settings.SUPABASE_SECRET_KEY = ""` and `settings.CLOUD_PUBLISH_ENABLED = False` with `monkeypatch`. Why: the live `.env` has publishing on since 30 Sep 22:27, and a test must never write to the real Supabase whatever `.env` or the environment says; with those three off, `src\cloud` does nothing at all (no file, no process, no request). A test that wants publishing uses `test_cloud`'s `cloud` fixture (§2.4), which switches it on against the fake.
- Each test file still makes itself importable: `BOT_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(BOT_ROOT))`. Files that reuse another test file's builders also insert `tests\` (for example `from test_foundation import page, portal, row`); the cloud files import each other's fixtures by name (`from test_cloud import cloud`).
- One file at a time: `.venv\Scripts\python.exe -m pytest tests\test_jobs.py -q`. One test: `-k test_every_count_is_exact`.
- To look without writing anything (no `.pytest_cache`, no `__pycache__`): set `PYTHONDONTWRITEBYTECODE=1` and use `-p no:cacheprovider --collect-only -q` (`1152 tests collected in 2.56s`).
- **To run every test, including the two safety-skipped ones, never in the live folder:** `git -C C:\Hangeul\BOT archive HEAD | tar -x -C <scratch folder>`, then from that folder `C:\Hangeul\BOT\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` with `PYTHONDONTWRITEBYTECODE=1` (and `HF_HUB_OFFLINE=1`). This is how the 30 Sep numbers above were measured; the copy has no `.env` and no `data\`, and none was left behind.
- **Offline by construction.** No test reaches the portal, Telegram, Google, SMTP, Ollama, the voice service, Hugging Face or a real Supabase, and none writes to `data\` or `passports\`. Every file path is monkeypatched into pytest's `tmp_path` (the cloud tests also move `publish.STATE_PATH`, the lock, the dry-run folder, `handoff.PENDING_DIR`, `handoff.LOG_PATH` and `student_index.INDEX_PATH` there).

### The safety skips in a checkout with a real `.env` (and the other conditional skips)

| Test | Skips when | Why |
|---|---|---|
| `tests\test_cloud.py:888` `test_the_real_publisher_process_starts_and_tidies_up` | `(BOT_ROOT / ".env").exists()` or any of `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `CLOUD_PUBLISH_ENABLED` is in `os.environ` | It starts a **real** child with `handoff.spawn` (`python -m src.cloud.publish --from <file>`). The child loads its settings from `.env` itself, out of reach of the conftest monkeypatch, so in the live folder it could publish for real. Skip reason: `this checkout has a .env (or Supabase settings in the environment): the child could publish` |
| `tests\test_cloud_bot_jobs.py:617` `test_the_real_full_picture_process_does_nothing_while_publishing_is_off` | the same condition | It runs `python -m src.cloud.full_picture` as a real process and expects `Full picture skipped: publishing is off.` in its stderr; with the live `.env` the child would read the whole portal and publish |
| `tests\test_cloud.py:1085` `test_the_real_gte_small_gives_384_unit_float32_numbers_on_the_cpu` (`@pytest.mark.slow`) | the model is not in the cache: `<HF_HUB_CACHE or HF_HOME\hub or ~\.cache\huggingface\hub>\models--thenlper--gte-small\snapshots\<CLOUD_EMBED_REVISION>` is missing | Loads the real model in a child: 384 dimensions, unit length, `torch.float32`, `torch.cuda.is_initialized()` False, 4 tokens for "hello world", model id `thenlper/gte-small@17e1f347…` |
| `tests\test_cloud_dry_run.py:259` `test_the_publisher_process_started_as_the_handoff_starts_it_sees_no_gpu` | `torch` is not installed | Starts a child exactly as `handoff.start` does and checks `CUDA_VISIBLE_DEVICES` is `-1` inherited and after `embed.prepare_process()`, and torch sees no GPU |
| `tests\test_cloud_cf_email.py:365` `test_a_missing_model_costs_the_embedding_process_exactly_one_log_line` | `sentence_transformers` is not installed | A child with an empty `HF_HOME` must log exactly one line and download nothing |

On this PC the model is cached and torch and sentence-transformers are installed, so only the first two ever skip, and only in `C:\Hangeul\BOT`. The memory note of 30 Sep records it the same way: "1152 tests; 2 skip in the live checkout because of the real .env".

### Collected tests per file (`8317741`)

| File | Tests | Added in | Subject |
|---|---|---|---|
| `tests\test_performance.py` | 225 | bbd8f98 (rewritten ce23535, extended 314afdb) | `/performance_today`, `/performance_month`, `/perf_today`, `/perf_month`, `/performance [today\|month]` and the free-text routes: the portal's Consultant Performance page only |
| `tests\test_foundation.py` | 102 | e0d47ab | Strict dates, long replies, the one portal session, the all-pages students reader, `/verified*`, `/admitted`, `/students`; `pin_today` (bbd8f98) |
| `tests\test_freetext.py` | 107 | 7f42ad0 | Free-text routing (`src\bot\ask.py`), live answers, `/calendar` words, the LLM's fact pick, Jennie's spoken checks |
| `tests\test_voice_fast.py` | 105 | d9bbecc | Fast Jennie: filler clip, one-call routing, memory, one-sentence reply, number checks, Ollama options, warm-up |
| `tests\test_brief.py` | 90 | f8fefa4 | The factual 18:05 brief and its readers |
| `tests\test_crosscheck.py` | 72 | 40da0e6 | `/crosscheck*`, `/passports`, and the MRZ/OCR validator with a stub OCR engine |
| `tests\test_jobs.py` | 42 | 9dcd9ad | Passport watcher, portal sync, `/stage`, `/missing`, passport issue dates, verified-docs download |
| `tests\test_inquiries.py` | 36 | 46cdf03 | `/inquiries_today`, `/inquiries_date`, `/consultations`, `/inquiries` and their free-text routes |
| `tests\test_voice.py` | 29 | d7a5817 | Jennie's voice path against a fake voice service (its fakes are reused by 3 other files) |
| `tests\test_repair_voice.py` | 22 | e164679 | Jennie: impossible spoken dates, failed reads worded in code |
| `tests\test_repair.py` | 19 | e164679 | The verifiers' repair list: date re-ask, `/admitted` university cell, paid vs verified income, OCR claims, calendar ranges, sync edits, missing-report failure |
| `tests\test_watcher_nonblocking.py` | 10 | 7241465 | The 30-minute watcher's OCR runs off the event loop |
| `tests\test_integration.py` | 9 | 344a247 | What the merge of the fix branches put right: `/alerts`, `/stats`, the `/sendmail` lookup, prompts, root scripts |
| `tests\test_consultations.py` | 8 | cd0277a | `consult_requests.php` read by column name |
| `tests\test_final_fixes.py` | 8 | c17d887 | The last cases found partly wrong by re-verification, and the brain on demand |
| `tests\test_cloud.py` | 61 | 36ae72e | The Supabase publish layer: records, `content_hash`, only-changed rows, deletes by key list, 200 rows a call, failures, `hg_runs`, dry run, handoff, backfill, embedder, secrets; defines `FakeSupabase` and the `cloud` fixture |
| `tests\test_cloud_commands.py` | 38 | 2b6798f | What the command handlers and free-text answers publish, after the reply |
| `tests\test_cloud_bot_jobs.py` | 33 | 5048a07 | The passport watcher, the 18:05 brief and the hourly full picture publishing |
| `tests\test_cloud_fixes.py` | 32 | 3caa393 | One block per finding of the three reviewers of 29 Sep |
| `tests\test_cloud_cf_email.py` | 28 | 9ead47d | Cloudflare's hidden e-mails decoded at every page parse; one log line for a missing model |
| `tests\test_cloud_performance.py` | 27 | e4d1cea | The `consultant_performance` kind (2 more in 8317741: the stable month scope, the backfill reads the page) |
| `tests\test_cloud_jobs.py` | 26 | 41055de | The four sheet jobs' hand-over to the publisher ([03c §1.8](03c_FILES_sheets_verify_root_scripts.md)) |
| `tests\test_cloud_dry_run.py` | 17 | 752cd53 | The first dry run's findings: portal fillers, one log line, `CUDA_VISIBLE_DEVICES=-1`, the 1 MB body cap |
| `tests\test_cloud_all.py` | 6 | cb16394 | Where the three hook branches meet |
| **Total** | **1152** | | 659 from `c17d887` (all 659 test ids still present), 225 performance, 268 Supabase |

**How the count grew** (from commit messages, workflow results and session logs): 29 voice tests (d7a5817) → 141 (d9bbecc) → 145 before the brief work → 179, then 234 (f8fefa4) → 336 on the foundation branch `fix/base` (e0d47ab) → branch runs of 373 (fix/jobs), 375 (fix/inquiries) and 446 (fix/freetext) → merged into `fix/all`: 447 after crosscheck, 558 after freetext, 595 after jobs → 607 (344a247) → 651 (e164679; on the unfixed 344a247, 17 of the 19 new `test_repair.py` tests and all of `test_repair_voice.py` failed) → 656 → **659** (c17d887). Then two lines of work ran in parallel from `c17d887`:
- **Supabase (branches under `C:\Hangeul\JARVIS\cloud\`):** `cloud/core` 720 (659 with the 6 date failures fixed + 61 in `test_cloud.py`; 36ae72e → cfd10f1) → the three hook branches each on 720: `cloud/jobs` 746 (+26, 41055de), `cloud/inproc` 750 (+30, 5048a07), `cloud/commands` 758 (+38, 2b6798f) → merged into `cloud/all` 814, then 823 after the integration commit cb16394 (+6 `test_cloud_all.py`, +3 `test_cloud_bot_jobs.py`) → 855 after the review fixes 3caa393 (+32) → 872 after the dry-run fixes 752cd53 (+17) → 900 after the Cloudflare fix 9ead47d (+28).
- **Performance (deployed to `main`):** 724 at bbd8f98 (+65 self-computed tests) → 775 at a721066 (+51; deployed 30 Sep 10:31) → 813 at ce23535 (the file rewritten for the portal's own page: 154) → **884** at 314afdb (225 in the file; deployed 14:06).
- **The release (`cloud/release`, fast-forwarded into `main`):** 1125 after the merge e5e532e (900 + 225; all passed once `test_cloud_jobs`' date-dependent missing-report test was pinned, a fix committed with e4d1cea) → 1150 at e4d1cea (+25 `test_cloud_performance.py`) → **1152** at 8317741 (+2).

### Legacy root "test" scripts (not pytest, and not part of the 1152)
- `test_system.py`: a five-part `rich` smoke run (config, parsers, the client, the LLM fallback, the FastAPI routes through `httpx.ASGITransport`). With `MOCK_MODE=false` its client part logs in to the **real** portal, so run it only in mock mode or when a live read is intended.
- `test_verified.py`: prints today's payment-verified students from the live portal (read-only).
- The root `test_crosscheck.py` was removed in 40da0e6 (it printed a stale hard-coded registry as if it were live results).

---

## 2. The fake patterns (copy these for a new bot)

### 2.1 The fake portal: `tests\test_foundation.py` fixture `portal`

```python
@pytest.fixture
def portal(monkeypatch):
    pages, asked = {}, []
    def handler(request):                                   # httpx.MockTransport handler
        key = request.url.path.rsplit("/", 1)[-1] + (f"?{request.url.query.decode()}" if request.url.query else "")
        asked.append((request.method, key))
        if request.method != "GET":
            raise AssertionError(f"the portal is read-only: {request.method} {key}")
        return httpx.Response(200, text=pages[key]) if key in pages else httpx.Response(404, text="not found")
    async def no_login(*a, **k): raise AssertionError("tests must not log in to the portal")
    monkeypatch.setattr(admin_client, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(admin_client, "is_authenticated", True)
    monkeypatch.setattr(admin_client, "mock_mode", False)
    monkeypatch.setattr(admin_client, "login", no_login)
    pin_today(monkeypatch)                                             # 28 Sep 2026, Dhaka (§2.5)
    monkeypatch.setattr(settings, "TELEGRAM_ADMIN_CHAT_ID", str(ADMIN_ID))  # 111111111
    return SimpleNamespace(pages=pages, asked=asked)
```
(`tests\test_foundation.py:108-133`; until bbd8f98 the fixture patched only `dates.local_today`, see §2.5.)
- Each page is keyed exactly as the bot asks for it: `"students.php"`, `"students.php?pg=2"`, `"students.php?source=direct&filter_docs=verified&pg=2"`, `"consult_requests.php?status=all&from=2026-09-08&to=2026-09-08"`. A page the test did not provide answers 404, so a reader that asks for the wrong page fails visibly.
- **Two invariants are enforced by every test that uses it:** any non-GET request fails the test (the portal is read-only), and any login fails the test (the session is pre-set).
- `portal.asked` lets a test assert which pages were read: every page was read (`student_reads(asked)`), none after a failure, nothing when the date could not be parsed.
- **Page builders that mirror the live layout (Sep 2026).** `row(uid, sl, name, hng="", uni="—", program=KLP, intake="MARCH 2027", docs="All Missing", pay="Verified", stage="Payment Verified", applied="12 Jul 2026", by="", when="", paid="", method="", income="")` emits a `tr.stu-row` (cells SL, Student with `.stu-name`, a Cloudflare-protected email and `.stu-sid`, University, Program · Intake with `.stu-sub`, Docs, Payment, Stage · Applied) and its `tr.xp-row` (`.det-item` label/value pairs, `.pf` payment chips, the `Payment verified by <strong>NAME</strong> · 27 Sep, 17:19` stamp, the **stage and transfer-intake `<select>`s**, whose words must never be read as the stage or as a date, the `view_doc.php?f=passport_<uid>_<time>.jpeg` link, and the `student_edit.php` and `progress.php` links). `page(*rows, pg=1, pages=1, total=None)` wraps them in the real header and a `.stu-pager` `Page X of N · T students`. `verified(...)` and `dashboard(...)` build the other common shapes.

### 2.2 The fake Telegram: `Sent`, `Chat`, `Message`, `fake_update`, `run` (`tests\test_foundation.py:143-188`)

```python
class Sent:                       # a message the bot sent; it can be edited or deleted
    def __init__(self, chat, text, parse_mode): ...; chat.append(self)
    async def edit_text(self, text, parse_mode=None, **kw):
        if replies.telegram_len(text) > replies.TELEGRAM_LIMIT: raise BadRequest("Message is too long")
        ...
    async def delete(self): self.deleted = True

class Chat(list):
    def shown(self): return [m.text for m in self if not m.deleted]

class Message:
    def __init__(self, chat, text="", refuse_markdown=False): ...
    async def reply_text(self, text, parse_mode=None, **kw):
        if replies.telegram_len(text) > replies.TELEGRAM_LIMIT: raise BadRequest("Message is too long")
        if parse_mode == "Markdown" and self.refuse_markdown:
            raise BadRequest("Can't parse entities: can't find end of the entity starting at byte offset 7")
        return Sent(self.chat, text, parse_mode)

def fake_update(text="", args=None, user_data=None):
    chat = Chat()
    update = SimpleNamespace(message=Message(chat, text), effective_chat=SimpleNamespace(id=ADMIN_ID),
                             effective_user=SimpleNamespace(id=ADMIN_ID), callback_query=None)
    context = SimpleNamespace(args=args, user_data=user_data if user_data is not None else {}, bot=SimpleNamespace())
    return update, context, chat

def run(handler, text="", args=None, user_data=None):
    update, context, chat = fake_update(text, args, user_data)
    asyncio.run(handler(update, context))
    return chat, context
```
Why this shape works:
- A handler is called exactly as python-telegram-bot calls it (`handler(update, context)`), with `context.args` holding the words after the command, and `context.user_data` carried between calls so two-step prompts can be tested (`/verified_date` → "which date?" → a typed answer).
- **Telegram's two refusals are simulated:** a message longer than 4096 UTF-16 units raises `BadRequest("Message is too long")`, and `refuse_markdown=True` raises the "Can't parse entities" error. The tests prove the bot splits long replies between lines, edits the "please wait" message into the first piece, and resends as plain text when Markdown is refused (`src\bot\replies.reply_long`).
- `Chat.shown()` gives what the user would actually see (deleted "please wait" notes excluded).

### 2.3 Other fakes

| Fake | File | What it stands in for and records |
|---|---|---|
| `Bot(refuse=(n,…), error=…)` with `send_message` | `test_jobs.py` | `application.bot` for scheduled jobs; refuses the n-th send, enforces 4096. Proves an alert is marked sent only after Telegram accepted it |
| `Http` (a context manager with `post`) | `test_jobs.py` | `httpx.Client` inside `auto_sync.notify` and `missing_report.send`; records every POST (url, data, files) |
| `export` fixture | `test_jobs.py` | `pb.fetch_all_students` → a `csv_rows(...)` list (the CSV export) |
| `listed(...)` records | `test_jobs.py` | `read_students` output for `/stage` matching |
| a `Client` class with `read_student_pages` and a ZIP `get` | `test_jobs.py` | the portal for `verified_docs.run_local`, including `zip_of(names)` in-memory ZIPs; the folder is in `tmp_path` |
| `FakeBrain.chat` | `test_brief.py` | `ollama_client.chat`; returns a set reply and records the system prompt, the user prompt and `num_predict` |
| `FakeBot(refuse_markdown=…)` | `test_brief.py`, `test_watcher_nonblocking.py` | `bot.send_message` |
| `portal` fixture (brief variant) | `test_brief.py` | as §2.1, plus `brief._now` fixed, `VERIFICATION_DIR` → `tmp_path` (a temporary `results.json` via `write_store`) |
| `FakeVoiceService` | `test_voice.py` | the local voice service's HTTP contract (`/stt`, `/tts`) on `httpx.MockTransport`, with failure modes `refused`, `timeout`, `503`, `500`, `not-json`, `not-ogg`, 413 over 600 characters; records requests and tracks the maximum in flight |
| `FakeLLM` | `test_voice.py` | `ollama_client.chat` for routing (JSON `format`), replies (KO/EN, small talk) and the spoken brief; a `down` switch |
| autouse `offline` | `test_voice.py` | a refusing `MockTransport` for the portal and Ollama clients, no login, `check_health` unreachable, a fixed `voice._now`, filler clips in `tmp_path`, empty per-chat history |
| `StubReader` + `engine` fixture | `test_crosscheck.py` | `easyocr.Reader` for **marked** synthetic images: a marker column tells the stub which page it is and how it is turned; only an upright read returns text. `mrz(surname, given, pno, dob, exp)` builds 44-character TD3 lines with real check digits |
| `BurningReader`, `FakePortal`, `burn(seconds)` | `test_watcher_nonblocking.py` | a CPU-burning OCR that holds the GIL like EasyOCR, records its threads and concurrency; a portal client whose `post` fails the test |
| `audits` fixture, `install_audit_wrapper`-style stubs | `test_crosscheck.py`, `test_jobs.py` | `admin_client.audit_student_passport` returning set results (`MATCH`, `DISCREPANCY`, `PORTAL_UNREADABLE`, …) |
| `perf_page(period, label, dates, tiles, top, rows, columns, count, scope, dates_class, empty, extra_th)`, `person(...)`, `td(key, r)`, `EMPTY_ROW`, `PORTAL_ERROR_ROW` | `test_performance.py` (also used by `test_cloud_performance.py`) | `consult_performance.php` as the live page lays it out on 30 Sep 2026: sidebar (with a decoy table), the period tabs `?period=today\|week\|month\|all`, the unused Custom range form, the "Showing" line, the scope note, the 4 tiles, the top performer card, the leaderboard (`table.pf`, header texts with the Score/Points tooltips, the crown `span.pf-crown`, the count badge, the sort note) and the legend. `columns` reorders the header and cells; `EMPTY_ROW` is the page's own empty state (`tr.pf-empty-row > .pf-empty`), `PORTAL_ERROR_ROW` a one-cell row that must **not** read as "nobody is listed". The month and today rows copy the owner's screenshots of 30 Sep (staff names and figures, no student data) |
| `parse_legacy_markdown` (a copy of the audit's `tg_markdown.py`) | `test_performance.py:1016` | Telegram's `parse_mode="Markdown"` v1: every performance reply piece must parse (`test_every_reply_is_valid_legacy_markdown`, `:625`) |
| `telegram(status=200, log=None)` context manager | `test_cloud_jobs.py:62` | `httpx.Client` inside the jobs' raw Bot API calls (`auto_sync.notify`, `missing_report.send`), answering every POST with `status`; records `{url, data, file}`. Only the job's `httpx.Client` is replaced; the publisher's own client stays the fake Supabase transport |
| `sync` fixture (and `sheets` for the missing report, `:437`) | `test_cloud_jobs.py:128` | `auto_sync.run_once` over fakes: one KLP MARCH 2027 sheet, the CSV export (`world.export`), the verified list (`world.documents`), a document check of one synthetic student (`results.json`, its OCR text cache and document folder in `tmp_path`), `world.listed` (the list count the 90 % export rule compares with). Set `.export` / `.documents` to an exception to make that read fail |
| `handed(cloud)` | `test_cloud_jobs.py:90` | The one handoff file the job wrote → `(document, {kind: [batches]})`; asserts there is exactly one |
| `pin_job_clock(monkeypatch, at)` | `test_cloud_jobs.py:456` | `missing_report`'s own `time` (`time.time`, `time.strftime`) fixed at `at`, beside `records.now`; without it the daily-report test passed only on 29 Sep (fixed in e4d1cea) |
| `hooked(handler, text, args, user_data)`, `handoffs`, `shape`, `kinds`, `batch_of`, `process`, `same_reply_either_way` | `test_cloud_commands.py:62-112` | Run a handler as Telegram does, then `await command_hooks.drain(timeout=60)` for the background hand-over the bot never waits for; read the handoff documents (all `job == "command"`, `version == 1`); `(kind, scope, complete, keys)` per batch; publish them into the fake with `publish.process_file`; and **the reply with publishing off and on must be identical** |
| `bodies` fixture | `test_cloud_dry_run.py:289` | The raw byte size of every `hg_sync` body the fake answered (the 1,000,000-byte cap) |
| `REAL_SPAWN` | `test_cloud.py:53` | The real `handoff.spawn`, kept before the `cloud` fixture replaces it with a recorder; used only by the `.env`-guarded child tests |

### 2.4 The fake Supabase: `tests\test_cloud.py` `FakeSupabase` (`:66`) and the `cloud` fixture (`:201`)

The publish layer talks to Supabase through one `httpx.Client` whose transport is the module attribute `src.cloud.publish.TRANSPORT` (`None` in production). The tests swap in an `httpx.MockTransport` whose handler is an in-memory copy of the Jeannie migration `20260929030000_hangeul_context.sql` (the `hg_runs` table and the `hg_sync` RPC). It fails the test on anything the real server would not accept, so the real client, batching, hashing and error handling all run.

```python
URL = "https://example.supabase.co"
KEY = "sb_secret_" + "Fak3KeyForTests0nly" * 2          # an obviously fake key

class FakeSupabase:
    def __init__(self):
        self.records, self.chunks, self.runs = {}, {}, {}   # (kind, key) -> row / chunks; run id -> row
        self.calls, self.changes = [], []                   # (method, path, body); ("upsert"|"delete", kind, key)
        self.fail = None          # request -> an httpx.Response, an exception to raise, or None

    def __call__(self, request):
        if request.url.scheme != "https" or request.url.host != "example.supabase.co":
            raise AssertionError(f"a request to another host: {request.url.host}")
        assert request.headers.get("apikey") == KEY                    # the secret key goes in apikey
        assert request.headers.get("authorization") == f"Bearer {KEY}"  # and as the Bearer token
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if self.fail is not None:                                       # failure injection
            out = self.fail(request)
            if isinstance(out, Exception): raise out
            if out is not None: return out
        if request.url.path == "/rest/v1/hg_runs" and request.method == "POST":  return self._run_insert(body)
        if request.url.path == "/rest/v1/hg_runs" and request.method == "PATCH": return self._run_update(request, body)
        if request.url.path == "/rest/v1/rpc/hg_sync" and request.method == "POST": return self._sync(body)
        raise AssertionError(f"Supabase: unexpected {request.method} {request.url.path}")
```

What `_run_insert`, `_run_update` and `_sync` enforce (each refusal is a PostgREST-shaped `{"code","message","details","hint"}` with the Postgres code the real SQL raises):
- **`hg_runs` POST:** only the columns `id, job, started_at, finished_at, status, counts, note`; `id` a UUID (a repeat → 409 `23505`); `job` a string and `counts` not null (400 `23502`); `status` one of `None, "ok", "partial", "failed"` (400 `23514`). **PATCH** only as `?id=eq.<uuid>` (asserted), same status and counts rules, 204.
- **`hg_sync`:** exactly `p_run, p_kind, p_scope, p_rows` plus optional `p_all_keys` (else 404 `PGRST202`, as PostgREST answers an unknown signature); non-empty kind and scope, `p_rows` a list of **at most 200** (400 `22023`); each row has a `key`, an object `data`, a string `content` and non-empty `content_hash`, `source`, `read_at`; `read_at` must match `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}` (400 `22007`: a zoned ISO time); `student_uid` null or an int in `1..2^31-1` (400 `22P02`); `day` null or an ISO date; each chunk has an `embedding` of **exactly 384** numbers, a non-empty `embed_model` that is the **same in the whole call**, and a unique non-negative int `ord` (400 `22023` / `23514`); no NUL character in any text (400 `22P05`: Postgres `text` cannot store it); `p_all_keys`, when given, is a list with no null element.
- **Semantics:** a row whose `content_hash` equals the stored one is `unchanged`; the others are upserted by `(kind, key)` (the row's scope and `run_id` updated, its chunks replaced); a call with changed rows and a `p_run` the table does not have → 409 `23503` and **the whole call rolls back**; with `p_all_keys`, every record of that `(kind, scope)` whose key is not in the list is deleted with its chunks, **except for `field_correction`, which is append-only**. The answer is `{"upserted", "deleted", "unchanged"}` (the SQL's three counts; the spec named only two).
- Views for assertions: `fake.syncs()` (every `hg_sync` body), `fake.keys(kind, scope=None)`, `fake.changes` (the change log a trigger would write), `fake.runs`.

The **`cloud` fixture** switches publishing on against it and isolates every file:

```python
@pytest.fixture
def cloud(monkeypatch, tmp_path):
    fake = FakeSupabase()
    monkeypatch.setattr(settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", KEY)
    monkeypatch.setattr(settings, "CLOUD_PUBLISH_ENABLED", True)
    monkeypatch.setattr(publish, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(publish, "STATE_PATH", tmp_path / "cloud_state.json")
    monkeypatch.setattr(publish, "LOCK_PATH", tmp_path / "cloud" / "publish.lock")
    monkeypatch.setattr(publish, "DRY_RUN_DIR", tmp_path / "cloud" / "dry_run")
    monkeypatch.setattr(publish, "_DRY_RUN", False)
    monkeypatch.setattr(handoff, "PENDING_DIR", tmp_path / "cloud" / "pending")
    monkeypatch.setattr(handoff, "LOG_PATH", tmp_path / "hangeul_sync.log")
    monkeypatch.setattr(student_index, "INDEX_PATH", tmp_path / "cloud" / "student_index.json")
    spawned = []
    monkeypatch.setattr(handoff, "spawn", lambda path, timeout=0: spawned.append(Path(path)))  # starts nothing
    stub = embed.StubEmbedder()
    old = embed.set_embedder(stub)
    try:
        yield SimpleNamespace(fake=fake, stub=stub, spawned=spawned, tmp=tmp_path)
    finally:
        embed.set_embedder(old)
```

- **`embed.StubEmbedder`** (`src\cloud\embed.py:247`): a deterministic 384-number **unit** vector per text from its sha256 (`raw[i] = ((seed[i % 32] + 7*i) % 251) - 125`, then normalised), no torch; it records every text it was asked to embed, so a test can prove an unchanged record is not embedded again. Its `model_id` is `"stub/gte-small@test"`. Only one slow test loads the real model (§1 table).
- **The launcher is a recorder:** `cloud.spawned` lists the handoff files a job or handler wrote; a test then reads them (`handed`, `handoffs`) and, when it wants the rows in the fake, publishes them in-process with `publish.process_file(path)`, which also proves the file is deleted afterwards.
- **Helpers:** `state()` (the hash state as saved), `cloud_warnings(caplog)` (the `hangeul.cloud` warnings: most failure tests assert **exactly one**), `no_placeholder(record)` (R1: none of `PLACEHOLDERS`, e.g. `"None"`, `"N/A"`, `"PENDING"`, `"Unassigned"`, `"a student"`, `"()"`, in the text form; no doubled separators; no `"—"`, `"N/A"`, `"PENDING"`, `"Unassigned"`, `"Event"`, `"Dashboard"` value anywhere in `data`), `listed(*rows)` and `student_rows(...)` (synthetic reader output built with the foundation's `row()`/`page()`).
- **Failure injection** covers what the spec asks. `test_cloud.py:681-688` is parametrised over the three failures and the one log line each must give: `httpx.Response(500, json={"code": "XX000", "message": "row 425: A1234567 ..."})` → `HTTP 500 XX000 (Supabase server error)`; `httpx.ReadTimeout("timed out", request=req)` → `Supabase did not answer in time (ReadTimeout)`; `httpx.Response(401, json={"code": "42501", …})` → `HTTP 401 42501 (the key was refused)`. Note the server message quotes a key that holds a (synthetic) passport number: the test proves it never reaches the log. Other files inject a 503 (`test_cloud.py:881`, `test_cloud_bot_jobs.py:259`), a `ConnectTimeout` (`test_cloud_jobs.py:499`), a timeout on one call only (`test_cloud_fixes.py` `timeout_once`) and a failed `hg_runs` POST (409; the run then publishes with `p_run` null). In each case the job finishes, costs one log line, and the hash state is not advanced for the calls that were not accepted.

Why this shape: the spec's safety rules are about what reaches the server (deletes only after a complete read, only changed rows, one embedding model, no secret in a log line), so the fake sits at the transport and **enforces the SQL's own constraints**. The secrets-and-tests reviewer of 29 Sep mutated the code 22 ways against the 164 cloud tests of that day: 15 mutations were killed (for example "state saved before the answer", "`p_all_keys` on a partial read", "exception text in a failed-read reason", "child output to the caller's pipe"), 3 survived harmlessly (a filter dropped from httpcore loggers that never log header values, the JWT pattern removed while the `apikey`/`Bearer` patterns still catch it, the conftest guard removed in a worktree that has no `.env`) and 4 survived and were reported; the fix commit 3caa393 then ran 18 mutations of its own, all killed (§4.8).

### 2.5 Pinning "today": `test_foundation.pin_today` (`:136`) and `test_cloud_jobs.pin_job_clock` (`:456`)

```python
def pin_today(monkeypatch, today=TODAY):              # TODAY = date(2026, 9, 28)
    """Today is `today` in Dhaka for every reader of it: src.dates.local_today, and src.bot.ask's
    own name for it (ask imports local_today by name, so patching src.dates alone misses it)."""
    monkeypatch.setattr(dates, "local_today", lambda: today)
    monkeypatch.setattr(ask, "local_today", lambda: today)
```

- **Why it exists.** `src\bot\ask.py` does `from src.dates import local_today`, which binds the function into `ask`'s own namespace; the old fixture patched only `src.dates.local_today`, so every free-text reader in `ask` still saw the real clock. The tests had been written on 28 Sep and passed only on that day. On the real clock of 29 Sep **6 tests failed** (the live bot was correct; it was a test-only fault). Re-run on 30 Sep against `c17d887` in a clean copy: `6 failed, 653 passed in 21.76s`, namely `test_freetext.py::test_the_report_route_fires_only_for_real_report_requests`, `::test_intakes_and_application_dates_are_counted_from_every_page`, `::test_deadlines_this_week_apply_real_dates`, `::test_dhl_questions_and_searches`, `test_repair.py::test_deadlines_with_words_are_deadlines_only[args0-3-titles0]` and `::test_the_deadlines_counts_say_where_they_stand`.
- **How it was proven robust** (the secrets-and-tests reviewer of 29 Sep, with a fake clock that patches `datetime` only): the old suite failed 6 on the real clock, 7 on 15 Oct 2026, 6 at 29 Sep 18:05 and 9 on 2 Jan 2027, and passed on 28 Sep; the fixed branch passed at every one of those times. No new test depends on the real date or on the quiet windows.
- **Where it is called:** by the `portal` fixture (so every test that uses the fake portal is pinned), explicitly in `test_freetext.py:342` (`test_the_report_route_fires_only_for_real_report_requests` has no portal), and by the autouse fixtures `pinned_today` in `test_cloud_commands.py:56` and `test_cloud_performance.py:71`. Two branches had fixed it separately (the performance branch with `pin_today`, the cloud branch with autouse `pinned_today` fixtures in `test_freetext.py` and `test_repair.py`); the release merge e5e532e kept `pin_today` and removed the duplicates.
- **`pin_job_clock(monkeypatch, at)`** does the same for a subprocess job that reads the clock itself: `missing_report` takes its heading from `time.strftime` and its send time from `time.time()`, so the test that fixes `records.now` must also replace `missing_report.time` with a namespace whose `time()` returns `at.timestamp()`. Without it `test_the_daily_missing_report_hands_over_the_report_its_sections_and_the_text_sent` passed only on 29 Sep (found and fixed in the release merge, e4d1cea).
- **Rule:** when a module imports a clock function by name, pin it in that module too; grep for `from src.dates import` and `import time` in the modules a test drives.

---

## 3. What each test file pins

### `test_foundation.py` (102)
- Unchanged in its tests since `c17d887`; since bbd8f98 it also defines `pin_today` (§2.5), which its `portal` fixture calls, so every file that uses the fake portal is pinned to 28 Sep 2026.
- `src\dates.py`: `parse_user_date` reads 24 real forms exactly (`today`, `8 Sep`, `Sep 8, 2026`, `the 8th of September`, `08/09/2026` day-first, `8.9.26`, ISO, a date inside a sentence) and returns **None** for impossible or missing dates (`31 Sep`, `29 Feb 2026`, `13/13/2026`, `Sep`), never today. Month words count only as whole words next to a day. A date without a year may mean the one just gone. Portal stamps match on whole tokens and their year rules.
- `normalize_date_input` never falls back to today, and every caller says "I couldn't read that date".
- `replies`: `split_text` splits between lines and counts like Telegram (UTF-16); `reply_long` edits the waiting message, then replies, then falls back to plain text; `send_long`; the stock error replies.
- Portal client: an expired session logs in again **once**; a failed login is raised, not ignored; the login's end URL is checked; an unreachable portal is `unreachable`, and an error status is not a page; query values are URL-encoded.
- `parse_students_page`: columns found by header name wherever they are; an unrecognised list raises, and an empty one is empty. Every page is read with its query and each student is listed once; a list that cannot be read whole raises.
- `/verified*`: every page read; a day matched on whole tokens; "none today" only after every page was read; a day a year back is "not available"; a failed read is never "no payments"; long reports are split; no amount or method is made up; the date prompt; free-text routes. `/admitted` picks by stage from every page (the portal ignores `?status=admitted`), says "none" plainly, shows a disagreeing dashboard figure, and says when it cannot read the portal. `/students` shows the real columns or why it could not.

### `test_jobs.py` (42): the scheduled jobs and the sheet reports
- **Passport watcher:** reads every page (60 students over 2 pages → 60 audits, newest upload first); each scan is audited once, keyed by uid + file name; a re-uploaded passport is checked again; the old uid-only memory is not trusted; every alert is sent, grouped under the limit, and **marked sent only after Telegram accepted it** (a refused one goes on the next run); a Markdown refusal is resent as plain text and counts as sent; the validator's own words go into the alert; a portal that cannot be read audits and sends nothing; an undownloadable scan, and the `PORTAL_UNREADABLE`/`OCR_UNAVAILABLE` statuses, are retried and never remembered; the run stops at its time budget; one run at a time.
- **Sync:** a student given an ID is "edited (Student ID)", not new + removed; a passport filled in is matched by name + mobile; real joins and leaves are still reported; `PENDING` is no identity (and an old saved key still pairs); a payment verification is one edit, and the next run reports nothing; the document-check message carries its own title; a FAIL/INCOMPLETE line names its rule or missing document; a long summary is split between lines, with no line cut; re-downloads are not "newly verified", and empty ones are dropped; `run_local` tells a re-download from a first download; the verified list fails loudly on a refused login (no login loop) and reads every page.
- **`/stage`:** the stage comes from the student list, not the CSV; two students of one name are told apart by mobile; the report reads every page with its own session; the progress page is read by its own classes; a page on another stage, or not read, is said so; reading stops once the portal is gone; a report that cannot read the portal says so; the intake menu shows why it could not load.
- **`/missing`:** university fields of KLP students come from the portal; a program complete but for one unchecked student is not called complete; Master's students are checked on their own sheet; students without an ID are matched by name + mobile; the daily report counts them and its Excel file is only captured (never sent); a report that cannot read says so.
- **Issue dates:** placeholder passports and shared numbers with disagreeing dates are skipped; a refresh that cannot log in keeps the last cache; the sheets take the date from the export first.

### `test_brief.py` (90): the factual daily brief
Every figure is counted exactly from synthetic `consult_requests.php` (per-day filter pages and status tabs), `students.php` pages, the pending list, `window_applications.php`, `index.php` and `calendar.php`. Missing data says "not available" and invents nothing; nothing today says "none", not zero rows; an unreadable calendar is not counted; **pending payments and window applications are never summed** (guardrail rule 2); a disagreeing dashboard tile is shown; a past day counts that day and skips the calendar. The LLM summary keeps only numbers that are the figure of their own fact (`brief.claims_problem`, parametrised in both directions), and a past-day summary that says "today" is dropped. Markdown is escaped, with a plain-text fallback; long briefs are split; the daily job sends the text and then the spoken brief. `/brief` no longer fails its import; `/report` uses the brief; tiles are read whatever their case; a missing tile is None, never a placeholder; the calendar is read from its current layout (an unknown one reads nothing); the verified reader never makes up an amount or name; timeouts and a silent host are "not available", with a short connect timeout; parsing runs off the event loop; the job survives a late start.

### `test_crosscheck.py` (72)
What a cross-check asks for (a date, a range, a portal ID, an HNG ID, a name; "Kumar" is a name, not a month); an unreadable date is an error, never today; **students are picked by their own "Payment verified by NAME · 27 Sep, 17:19" stamp only** (never the transfer-intake option "2027 SEPTEMBER" or "Applied On"); every page is read, and days match on whole tokens; ranges in day and time order; a year-back day is "not available"; IDs and names are found on every page; a name many students share checks the first 10 and lists the rest; an expired session is renewed; a failed read is said, never "none found"; long reports are split between students' cards. `/passports` is live, never the old registry. **OCR validator** (stub engine): a full match needs all seven fields; fields not on the scan are named; a turned scan is read after turning it; an MRZ high on the page is found; no MRZ at any turn is `MRZ_UNREADABLE`, not "not a passport"; MRZ lines are validated (44 characters, TD3) before any field is trusted; a failed check digit means "check by eye", not a mismatch; one-letter name differences; a badly read MRZ name is not a discrepancy; parent names are "check by eye" unless nothing matches; a blank portal field is never a match. `audit_student_passport`: the scan download renews an expired session; a web page is never saved as a scan; an unreadable profile is said; an old saved scan is never checked in place of the portal's; a file name that could leave the folder is refused.

### `test_freetext.py` (107)
(Since bbd8f98: `test_the_report_route_fires_only_for_real_report_requests` calls `pin_today` itself, and since 314afdb its sample inquiries reply is headed "Consultations on 27 September 2026", no longer "Performance on …". The performance routes themselves are pinned in `test_performance.py`.) Questions are read on whole words (`across` is no cross-check, `shipping` no `/pin`, `Janan`/`summary`/`doctor`/`daughter` are no months); the day a question names; date windows are real dates ("this week" is today to Sunday); each question reaches its command, the old substring traps never misroute, and a span of days for a one-day answer asks which day; the report route fires only for real report requests. Live answers on synthetic pages: pending payments from every page with names; window applications as their own figure; dashboard questions from live figures; intakes and application dates from every page; an unreadable portal is said plainly, never 0; a question the portal cannot answer is said honestly; the facts the LLM picks are shown word for word (it only picks indices, and skips the LLM when the facts do not fit the context); deadlines this week; DHL questions; the calendar merges its three lists; calendar query errors. Jennie: says only the figures of the facts, for their own day; Korean answers are built from the headline fact; no example day or figure leaks into the prompt rules; voice passport questions take the live cross-check; every live answer fits Telegram.

### `test_inquiries.py` (36) and `test_consultations.py` (8)
Inquiries: today's figures come from the portal's date filter (`?status=all&from=DAY&to=DAY`) and the all-time totals from the status tabs; "by" is said only for a handled request, and a `—` city is N/A; a day is read with the portal's own filter; **8 Sep is never 18 or 28 Sep**; a day with no requests is a real zero only from the portal's own empty row; a bad date is an error; a future day is not available; the date prompt; failures are said, never 0; an unreadable all-time figure is "not available" while the day is still shown; a day the portal lists only partly keeps its own counts; long reports are split and resent as plain text; free-text inquiry dates. Consultations: the 7-column named layout reads every field (`.cr-name`, `.cr-cons`, `.city`/`.prog`, `.d`/`.t`, `.stbadge`, `.cr-by`, `textarea.rmk`); `—` is no city; a Cloudflare-protected name shows as a browser shows it; a view gives its own counts, filter and caption; columns are found by name even when moved; **an unknown layout gives no rows rather than wrong ones**.

### `test_voice.py` (29), `test_voice_fast.py` (105), `test_repair_voice.py` (22)
Voice is **off** in production (`JENNIE_VOICE_ENABLED=false` since 28 Sep 2026 17:08) but fully tested. These files cover: unauthorised senders refused; Korean and English voice notes routed, answered and spoken; the capture of a command's final text; the voice service down or erroring (text answers still arrive, one short note); a brain that is down still answers through the typed routing; voice never drives the e-mail flow; recordings that are too long are not downloaded; voice flows take turns; the URL must stay on this PC; the spoken brief follows the text brief, is short and isolated, and is not spoken while voice is off; the handler is registered only when voice is enabled. The fast path: the filler goes first (in the last turn's language) and nothing waits for it; missing fillers are rendered after the note; direct dispatch per command; chat dispatches nothing; dates and relative days are worked out in code, and a relative word never overrides a calendar date; spoken ranges; fallbacks; per-chat history kept and capped; emojis stripped; one short sentence (Korean asked again shorter); a number not in the answer is never spoken (digits, words and Korean number words); a timing line with every stage and no words; one `num_ctx` per call and a resident model; warm-up and keep-warm reload a model that Ollama lost or that sits partly on the CPU; over-long prompts are logged. Repairs: an impossible spoken date ("31 September", "the 45th", 9월 31일) gets the date error and reads nothing; a failed portal read is said in words built in code, never "no pending payments".

### `test_watcher_nonblocking.py` (10)
The event loop keeps ticking (<0.5 s gaps) while an audit burns CPU in a worker thread (with a control test: the same audit on the loop freezes it); the result is identical to the old synchronous call; concurrent audits never share the OCR reader (max one inside `readtext`); two audits of one new upload save the scan once (through a `.part` file); the EasyOCR reader loads once even when threads race; the watcher sends the same alerts without freezing the loop.

### `test_integration.py` (9), `test_repair.py` (19), `test_final_fixes.py` (8)
Integration: `/alerts` shows the dashboard's live "Needs attention" card (it used to say "No urgent alerts" whatever the portal showed) or says it cannot read it; `/stats` is split and resent as plain text; the `/sendmail` lookup reads every page when the CSV export fails and says when the portal cannot be read; the `/inquiries_date` prompt has no code inside italics; `audit_program.classify` sorts the new OCR statuses honestly; the root passport scripts list every page. Repair: a date typed after an unreadable one answers the pending question (for verified, inquiries, crosscheck and range); a free-text bad date does not open a question; `/admitted` shows the university cell's own line and the applications apart; "Paid" and "Verified income" are shown apart, and a total says what it adds up; "checked by OCR" only for scans OCR read; timeline times and end dates; the whole timeline is listed; two events with one title stay two (by event id); `/deadlines <words>`; deadline counts say where they stand; an ID given with a name correction is one edit; a daily missing report that cannot be built says so as one plain message. Final fixes: a mistyped date answer keeps the question open, while a whole new question does not; an unreadable scan is not counted as OCR-checked; **a sibling with the same mobile and another DOB is not an edit**, while re-spelled or completed names still pair; dated calendar answers say what they left out as done; the brief's verified total says what it adds up; the brain is pinned only while voice is on, and keep-warm does nothing otherwise.

### `test_performance.py` (225): the Consultant Performance page (ce23535, 314afdb)
The two commands show **only** the portal's own page `consult_performance.php` (Leads > Performance); the self-computed report of bbd8f98/a721066 is gone (`test_the_self_counted_report_and_its_readers_are_gone`, `:998`: `read_consultation_range` and `read_verified_window` must not exist). Pinned: one read-only GET of `consult_performance.php?period=today` or `?period=month` (the page's own period links; the Custom range form is never used; no other page is read: `test_one_get_of_the_period_link_and_nothing_else`); tiles, top-performer card and the whole leaderboard parsed by labels and header words, every figure exactly as printed (`"17.9"`, `"18%"`, `"149.5"`); a reordered header reads the same, an unknown column is kept under its own header; the page must say it shows the period asked (it falls back to This Month for a period it does not take: `test_a_page_that_shows_another_period_is_refused`); only `tr.pf-empty-row` / `.pf-empty` is an empty leaderboard, and any other one-cell row (a portal error) is never "nobody is listed" (`:346`, `:351`); a page with no tiles, no leaderboard header, a missing column, an unreadable row or figure, or a count badge that disagrees with its rows is "layout not recognised" (10 layout-guard cases); a portal that cannot be read says so, never zeros; where the page disagrees with itself a ⚠️ line says so and nothing is "corrected"; replies in house style, split under 4096 between **whole consultant records**, resent as plain text when Markdown is refused, and **every reply parses as legacy Markdown** (the audit's parser, §4.6(d), copied at `:1016`); the 13-entry menu, the cheat-sheet and the welcome name the page; free-text routes on whole words (`this months performance`, the owner's spelling **`performence`**, `perfomance`, `performances`), `consultations today` still the inquiries, and another day or period (`consultant performance yesterday`, `ytd`, `this year`, another month) told what the commands cover, never answered with this month's page or that day's consultations; `format_inquiries_report`'s day line is headed "Consultations on …", not "Performance on …" (`:952`); the root staging copy is byte-identical. Test pages copy the live structure of 30 Sep; today is pinned to 28 Sep.

### `test_cloud.py` (61): the publish layer's core (36ae72e … 752cd53)
- **Records** (one test per kind): the key, scope, day, data and text form of `student` (every list field except the volatile ones; one per uid; a placeholder passport is no identity), `pending_payment` (rows whose own Payment is Pending, with the badge), `verification` (dated by its own "Payment verified by … · 27 Sep" stamp within the last year), `student_export` (every column, keyed like the sheet sync), `student_profile` (its own scope; a page without a name is none), `student_progress` (pages not read are left out), `student_documents` (file names only), `consultation` (keyed by its portal id, else by what it is), `window_application` (under review only), `dashboard_fact` (group\|label; complete only with every card), `calendar_item` (event id; never complete), `passport_audit` (only when it checked something), `passport_alert`, `passport_issue`, the document-check store → `doc_verdict` / `field_check` / `field_correction`, `doc_page_text` (one record a page, the version on disk), reports, sections, `brief_fact`, `notification`; `content_hash` is sha256 of the canonical JSON `{kind, key, scope, data, content}` (`sort_keys`, `ensure_ascii=False`, compact separators); text Postgres cannot store (NUL) is cleaned.
- **Publish:** only changed rows are sent (a second identical run sends nothing; one changed field sends that row alone); a complete read without a student deletes exactly that student and the state forgets it; a complete key list can cover records not sent this time (`all_keys`); a partial read sends `p_all_keys` null and deletes nothing; a list that cannot be read whole publishes nothing; at most 200 rows a call with the key list on the last call only; a long record gets several chunks, each led by its heading; Supabase 500 / timeout / refused key (parametrised) = one line, the job goes on, the state stays; failing mid-run skips the rest of the run silently; every run has its `hg_runs` row (POST then PATCH); a run whose row could not be written publishes with no run; the dry run writes the exact payloads and changes nothing; nothing happens while publishing is off; `test_no_test_publishes_for_real_whatever_the_env_says` (the conftest guard); `field_correction` never gets a key list; one publisher at a time (the lock).
- **Handoff:** `submit` writes one file and starts the publisher without waiting (UTF-8, no window, CUDA hidden, output to the sync log, never the caller's pipe) and never raises; the publisher publishes a file and deletes it (also when Supabase fails, and a bad JSON file); the real child (`.env`-guarded, §1).
- **Backfill** (`--skip-portal`, `--data-dir`, `--verification-dir`, `--docs-root`): consultation days, counts and totals; the oldest request found from the portal's own counts; progress complete only when every page was read; the export complete only when it came whole; from disk in a dry run; for real, then again sends nothing; refuses while publishing is off or in a quiet window.
- **Embeddings and secrets:** text split on paragraphs, then sentences (≤350 words); the stub gives 384 unit numbers; gte-small refuses to load where CUDA is not hidden; the real model (slow, §1); no `torch` import in the publish layer until it embeds; `sb_secret_…`, `sb_publishable_…`, `sbp_…`, JWTs, `apikey:` and `Bearer` values never reach a log line (`src.redact` also turns a bot URL into `bot<token>`); the root staging copies are byte-identical.

### `test_cloud_jobs.py` (26): the sheet jobs' hand-over ([03c §1.8](03c_FILES_sheets_verify_root_scripts.md))
The sync hands over, at its very end, the CSV export (`student_export`), the verified list (`student_documents`), the summary as a report with sections, each notice Telegram **accepted** (a refused one is no notification), then the checked passports' `doc_verdict` / `field_check` / `doc_page_text` and, from the whole store, `doc_check`, `field_correction` and the two check reports; a read that failed sends no batch and its reason goes to the run (no URL, no exception text); an export without its header, or with an empty list, is never complete; Supabase down, a slow publisher or a hook that raises changes nothing the sync does, prints or sends (`stamped()` compares the printed output with the time masked); an unreadable `results.json` sends only the passports just checked; passports Supabase never accepted go a few (6) a run; nothing is kept or built while publishing is off. The daily missing report hands over the report, one section per incomplete student and the text as sent; a report that could not be built hands over its notice and why; the `/missing` button prints exactly the same and hands over its program list (or nothing when it could not read); `/stage` prints the same and hands over `student_progress` **never complete** (or nothing); the issue refresh hands over the dates and every profile read, is not complete with `--limit`, keeps no page while publishing is off, and hands over nothing when it fails. Finally every record a job hands over is one the fake Supabase accepts.

### `test_cloud_bot_jobs.py` (33) and `test_cloud_all.py` (6)
Watcher: after saving its memory it hands over the whole list (`student`, complete), this run's audits (`passport_audit`, complete with every listed scan as the key list, so a cross-check's audit of an older listed scan survives), its memory (`passport_alert`) and the profiles its audits read; a replaced scan loses its audit and alert; a list it could not read whole hands over nothing; scans that could not be checked are a failed read, never an audit; it sends and remembers exactly the same whatever Supabase does (parametrised: down, slow handoff, a bug in the records); records are built off the event loop. Brief: after it was sent it hands over itself (`report`, `report_section`, `brief_fact`) and each read that succeeded (complete only when whole; a capped day and a tile read never are); a brief not sent, or demo data, is not published; it is the same and on time whatever Supabase does. Full picture: every page of the spec's step 4 plus the Consultant Performance page, GET only, one run; a partial read is never complete; once the portal does not answer the other pages are not tried; nothing is read while publishing is off, in mock mode, in a quiet window (18:00-18:10, 08:25-08:40, 09:00-09:10, and 5 minutes before each) or while a sync holds its lock; the scheduler job is hourly, one at a time, first 7.5 min after start; `nothing_the_bot_process_imports_for_supabase_imports_torch`. `test_cloud_all.py`: a dashboard tile is one record (one hash) whether the brief, `/stats` or a full `index.php` read made it (`records.tile_facts`); an older listed scan's audit survives the watcher; every hook's job name is in `src.cloud.JOBS`; the real bot registers the hourly job exactly once with publishing off and on; the hourly job starts no process while publishing is off.

### `test_cloud_commands.py` (38)
`/verified*`, `/inquiries*`, `/crosscheck*` and `/passports`, `/admitted`, `/calendar <words>`, `/stats`, `/students`, `/alerts` and the free-text answers hand the rows they already parsed to the publisher, one handoff (job `command`) per command, after the reply; only a whole read is complete (`/students` page 1, the dashboard's tiles alone, a capped day, the calendar and the cross-check audits are partial; a list whose stamps cannot be read publishes its verifications as partial; a failed read publishes nothing, never `rows=[]` with `complete=True`); the bare `/calendar` view publishes nothing; the reply is **identical** with publishing on or off (`same_reply_either_way`) and never waits for the handoff; a Supabase failure (500, timeout, refused key) or a failing build changes nothing the bot sends and is one line with no student data; nothing happens while publishing is off or in mock mode; a handoff outside an event loop runs in a thread of its own.

### `test_cloud_fixes.py` (32): the three reviews of 29 Sep, one block per finding
Hash state: keys a complete read no longer shows are forgotten only once the deleting call was accepted; a call Supabase took but did not answer never makes a later read look sent; locally unchanged records count as `unchanged`; a failed `hg_sync` leaves the state and closes the run as `failed`. Read order: an older complete read published later deletes nothing and rolls nothing back, and never deletes what a newer read showed. Embed model: a process with another model publishes nothing (the backfill with `--ignore-state` still checks it). Completeness: pending payments and window applications only when their rows agree with the page; the sync's export only with most (90 %) of the listed students; a lost watcher memory deletes no alert; the full picture stops reading once a quiet window is near and looks again once it holds the lock. Records: no stand-in word in any kind from sparse input; the passport-keyed kinds carry the student's uid (`student_index`); a consultation is keyed by the hidden id of its forms. Logs: an internal error logs its type only; an embedding failure logs no text.

### `test_cloud_dry_run.py` (17) and `test_cloud_cf_email.py` (28): what the dry runs found
Dry run 1: the portal's filler words (`N/A`, `None`, `--`, `PENDING`, `TBD`, …; whole cells only) are `""` in every portal kind's data and left out of its text, each named in `data["blank_on_portal"]` (only when there is one, so other records keep their hash; `details.<label>` inside the student details); a status field keeps its `Pending`; the list and the CSV export blank the same words (every marker `progress_builder.clean_value` blanks) and a Bangla text is a value in both; a model that cannot load costs **one** log line for the whole run and no call; `CUDA_VISIBLE_DEVICES=-1` in every entry point and in the child started as the handoff starts it (an empty value is not CPU-only on Windows); every body at most `MAX_BODY` = 1,000,000 bytes with the key list counted in the last call's size, and a record over the cap goes alone with one line of its size. Dry run 2: `parsers.decode_cf_emails` puts every Cloudflare-hidden address back (the `a` and `span` forms with class `__cf_email__` and `data-cfemail="HEX"` become plain text, a `/cdn-cgi/l/email-protection#HEX` link gets a `mailto:` href; the first HEX byte is the key, each following byte XOR the key is one UTF-8 byte), round-trips with keys 00, 01, 42, 5A, A7, FF, leaves malformed or empty HEX as served (11 cases), needs no network and is idempotent, keeps `student_edit.php` form values as they are; `students.php` (list and details), `consult_requests.php` (table and tabs), `progress.php`, `calendar.php`, `index.php`, `window_applications.php` and `consult_performance.php` decode first; **a source test** asserts every `BeautifulSoup(` line under `src\` is wrapped as `decode_cf_emails(BeautifulSoup(` and counts them: 13 in `parsers.py`, 2 in `client.py`, 1 in `ask.py`, 1 in `verified_docs.py`; `[email protected]` alone is a filler (any spacing, `&#160;`, any case), inside a longer text it is removed; the model libraries log nothing under WARNING.

### `test_cloud_performance.py` (27): kind `consultant_performance` (e4d1cea, 8317741)
One record per leaderboard row, key `<period>|<first ISO day>|<name as printed>` (`#2` for a repeat), and one summary per period window, key `<period>|<first ISO day>|summary`; **scope `<period>|<first ISO day>`**, day = the range's last day, source `consult_performance.php?period=<period>`, student columns null; figures as printed and the portal's dash as no figure (named in `blank_on_portal`); complete only for a whole read of that period's page (count badge present and equal to the rows, a readable range, every row keyed by a real name); a range that cannot be read publishes nothing; a changed figure changes that record only; the commands hand the page over after the reply from every route, and another period asked reads and publishes nothing; a later whole read without a consultant deletes exactly that one; the full picture makes 2 GETs and a period it cannot read is a failed read while the other still goes. The 2 tests of 8317741: **the month scope stays the same as the portal's range grows** (the portal ends every period at today: "01 Oct – 02 Oct", then "01 Oct – 03 Oct"; a scope holding the last day would have moved the keys daily and stranded a dropped consultant in an old scope), and the one-time backfill reads the page for both periods.

---

## 4. The independent audit and verification method (28-30 Sep 2026)

### 4.1 Why
On 28 Sep the LLM-written 18:05 brief **invented facts** (fake passport numbers, fake DOBs, "Scanned Image: Matched", visa year-to-date figures, conversion rates). The owner asked for every command, not only the brief, to be factually right. Unit tests alone could not prove that, because the portal's live layout had silently changed under several readers (for example `consult_requests.php` went from 8+ fixed columns to 7 named ones and zeroed every count, and `students.php` parsing had shifted by one cell). So each command was **run exactly as Telegram runs it, and its every figure was re-derived independently from the live portal**.

**Run ids.** §4.2-§4.4 name each run by its workflow id (`wf_…`); files 08, 09 and 11 use the task id (`w…`). The mapping is [08 Appendix C](08_HISTORY_STAGE_BY_STAGE.md): `wup29tzrh` = `wf_0a69c29b-8a0` (§4.2), `wjgdmt14w` = `wf_5c2f1525-536` and `wnhlel5f5` = `wf_29512f8c-a36` (§4.3), `wyjyqe0pz` = `wf_4b2a1e08-5c6` (§4.4). §4.7-§4.12 (the Supabase release, 29-30 Sep) name each run by its task id, which is also the name of its result file `<task>.output` in the session's `tasks\` folder, with the workflow id beside it where it is known.

### 4.2 The command-accuracy audit (workflow `wf_0a69c29b-8a0`, task `wup29tzrh`)
- **Frozen code.** A detached git worktree of HEAD `cd0277a` at `C:\Hangeul\JARVIS\command-audit\repo` (removed afterwards with `git worktree remove`). The live bot in `C:\Hangeul\BOT` was never touched. Audit scripts put the worktree first on `sys.path` and load `C:\Hangeul\BOT\.env` with `python-dotenv` (the portal login comes from the environment, never from a file in the audit folder).
- **One auditor per command group, plus a completeness critic**: `verified`, `inquiries`, `crosscheck`, `admitted_missing_stage`, `free_text`, then `critic` (the scheduled jobs, Jennie, anything missed). Scripts and saved pages are in `C:\Hangeul\JARVIS\command-audit\<group>\` (229 files).
- **Method, per command** (the workflow prompt's own words, summarised):
  1. **Run the handler exactly as Telegram would**, with realistic arguments (today, yesterday, a specific past date such as `27 Sep 2026`, a typed follow-up to a prompt, invalid dates such as `31 Sep`), using fake PTB objects that record everything and **send nothing**. The fakes (`crosscheck\harness.py`, `admitted_missing_stage\fakes.py`, `free_text\tg_fakes.py`) include a **re-implementation of Telegram's legacy Markdown parser** (tdlib `parse_markdown` v1, in `tg_markdown.py`) and the 4096-UTF-16 limit after parsing, so "would Telegram have refused this?" is answered too.
  2. **Independently re-derive every number, name and status it prints**, with the auditor's **own read-only GETs and own parsing**, never the bot's parser ("or you'd just repeat its mistakes"). Each group has its own minimal client (`crosscheck\common.py` `Portal`, `critic\portal.py`: GET plus the one login POST; it refuses `signed_students.php`) and its own parser (`verified\independent.py` pairs each `tr.stu-row` with its `tr.xp-row` in the DOM; `inquiries\my_parse.py` reads each row's selected `<option>`; `admitted_missing_stage\derive_*.py` recompute from the CSV plus every page plus the portal's own server-side filters).
  3. **Inspect the live structure first, masked:** letters → `x`, digits → `9`, except label and status words (`common.mask`), so page shapes could be studied without printing personal data. Raw pages were saved only inside the audit folder.
  4. **Compare** and give each case a verdict: `correct`, `partly_wrong`, `wrong`, `broken`, or `not_testable`, with `evidence`, `root_cause` (file:line) and `fix`.
- **Cost control for OCR:** `install_audit_wrapper` let the bot's real OCR audit run for only 3 named students (their results cached in `audit_cache.json`) and gave every other call a stub of the same shape. It copied only those 3 already-downloaded scans from `C:\Hangeul\BOT\passports` into the frozen copy. `critic\redact.py` stripped personal values from the saved watcher replay and deleted the copied scans afterwards.
- **Network guards** (`admitted_missing_stage\common.py` and later `fix\scratch\*\common.py`, `guard.py`): `httpx.Client.send` and `httpx.AsyncClient.send` are wrapped so that the portal allows only GET plus the `login.php` POST (optionally only an allow-list of pages), Telegram and every other host are blocked, and only `127.0.0.1` (Ollama) passes. **Google** (`gguard.py`): `httplib2.Http.request` may only GET; the only `requests` POST allowed is the OAuth token refresh, and the refreshed token is kept **in memory, never written back** to `token.json`; Drive folder creation is replaced by a read-only lookup. `report_wrapper.py` runs `python -m src.sheets.missing_report / stage_report` exactly as `_run_report_module` does, but under these guards, and redirects the Excel output into the audit folder. Child processes log their traffic (`child_net.txt`: e.g. `src.sheets.missing_report ['--program', 'KLP']: 3 requests; non-GET: [('POST', 'login.php')]; blocked: []`).
- **LLM nondeterminism:** free-text questions that reach the LLM were run 3–4 times each (`result_N.json`, `result_N_r1.json`, `result_N_r2.json`).
- **Result file:** `C:\Hangeul\JARVIS\fix\audit\audit_results.json` = `{"summary", "agentCount": 7, "logs", "result": {"setup", "results": [5 groups], "critic"}, "workflowProgress", "totalTokens": 1406130, "totalToolCalls": 383}`. Each group is `{"group", "commands": [{"command","args","verdict","evidence","root_cause","fix"}], "notes"}`. A readable dump is `audit_summary.txt`.

| Group | Cases | correct | partly_wrong | wrong | broken | not_testable |
|---|---|---|---|---|---|---|
| verified | 18 | 13 | 0 | 5 | 0 | 0 |
| inquiries | 17 | 2 | 10 | 4 | 1 | 0 |
| crosscheck | 23 | 4 | 4 | 10 | 5 | 0 |
| admitted_missing_stage | 24 | 14 | 3 | 7 | 0 | 0 |
| free_text | 26 | 3 | 6 | 16 | 1 | 0 |
| critic (jobs, voice, …) | 11 | 2 | 2 | 4 | 1 | 2 |
| **Total** | **119** | **38** | **25** | **46** | **8** | **2** |

Typical root causes found: page 1 of `students.php` read where there are 7 pages (the list is 50 per page); totals counted over the newest 500 consultation rows; unanchored date regexes (`8 Sep` matching `18 Sep`; every row matching "27 sep" through the transfer-intake options); the CSV's stale `Current Stage`; hard-coded texts (`/passports`); dashboard placeholders (262/31/…) when a tile label's case changed; substring routing (`across` → cross-check, `shipping` → `/pin`).

### 4.3 The factual-brief workflow (`wf_5c2f1525-536` / `wf_29512f8c-a36`, tasks `wjgdmt14w` / `wnhlel5f5`)
Phases **Build → Review (2 reviewers: facts, failure modes) → Fix → Verify (live)**. `C:\Hangeul\JARVIS\fix\audit\brief_workflow_results.json` = `{"result": {"impl": {"files_changed" (12), "summary", "checks_run" (12), "open_concerns" (8)}, "reviews": [{"verdict", "issues": [{"severity","file","line","problem","evidence","fix"}]} ×2 (6 and 7 issues)], "fix": {"fixed" (12), "declined" (0), "checks_run", "summary"}, "verify": {"brief_text", "checks" (32 × {"claim","brief_value","independent_value","match"}), "invented_content": [], "verdict", "notes"}}, "agentCount": 5, "totalTokens": 1227407, "totalToolCalls": 326}`.
- The verifier called `compose_daily_brief()` once, live and read-only, **without sending**, then re-derived every claim with its own GETs in `C:\Hangeul\JARVIS\brain-trial\brief_crosscheck.py`.
- 29 of 32 claims matched; `invented_content` was empty. The 3 mismatches were all the "all time" consultation line (counted over the 500 listed rows instead of the portal's status tabs). The verdict was "inaccurate" until that line was fixed: it was first relabelled and then read from the tabs (46cdf03).
- Checks run during the build: the baseline suite, masked structure dumps, live reader checks (dashboard tiles exact, pending 2 = badge 2, window applications under review 0), a live dry run (compose 11.1 s, 1911 characters), a Markdown marker-balance check, `cmp` of the staging copies, and a `git diff` showing mock data and `.env` untouched.

### 4.4 The fix-all workflow (`wf_4b2a1e08-5c6`, task `wyjyqe0pz`) and its re-verification
- **Phases:** Foundation (shared helpers + the verified/admitted fixes on branch `fix/base` → e0d47ab) → **4 parallel fix branches in their own worktrees** under `C:\Hangeul\JARVIS\fix\` (`fix/inquiries` 46cdf03, `fix/crosscheck` 40da0e6, `fix/freetext` 7f42ad0, `fix/jobs` 9dcd9ad) → Integrate (merge into `fix/all`, full tests; 344a247) → **Verify** (a live, read-only re-run of every audited case by 3 verifier groups: `verify-data-commands`, `verify-crosscheck-jobs`, `verify-freetext-voice`, in `C:\Hangeul\JARVIS\fix\scratch\verify-*`) → Repair (e164679) → Re-verify (`verify-reverify`).
- **The same method as the audit:** fake Update/Context/Message/Bot objects that record everything and send nothing; every figure re-derived with the verifier's own read-only GETs and parsing (the auditors' truth scripts could be reused); compare; re-run after repairs.
- **Numbers:** about 191 live cases; **164 correct at first**, 26 sent to repair; at re-verify 51 were correct and **7 partly wrong**. Those 7 were fixed directly with unit tests only (`tests\test_final_fixes.py`, c17d887) and were **not** re-verified live.
- **Deploy:** `git merge --ff-only fix/all` on `main` → c17d887; `cmp` confirmed the staging copies; 659 passed; the bot was restarted after the 18:05 brief; the worktrees, fix branches and audit worktree were removed. The scratch files remain in `C:\Hangeul\JARVIS\fix\scratch\` and `C:\Hangeul\JARVIS\command-audit\`.
- **Leftovers known at deploy:** `/verified_students` is a date alias; a verified date a year or more back is "not available" (the stamps carry no year); the REST API (`src\api`) still reads the 500-row consultation page and returns HTTP 500 on a portal failure; the portal lacks a verified stamp for 6 students from 14–15 Jul. (A memory note also lists "/stage status and % from the CSV", but HEAD reads `progress.php`: e164679.) After deploy, a passport false alarm was found (a garbled MRZ line 2 whose passport-number check digit passed by chance); its fix is **deferred** by the owner.

### 4.5 Earlier verification in the migration (27 Sep 2026)
- **Migration audit workflow** (`migration-audit`, first session): 7 read-only auditors, one per dimension (`paths`: hard-coded paths and portability; `bootstrap`: bootstrap.py and the cold-start phases; `coldstart`: behaviour with no `data\` folder; `env`: Python, packages, GPU/CUDA, Ollama and TLS on this machine; `runtime`: Google auth, the bot process, autostart, watchdog, retiring the old PC; `integrity`: whether the snapshot is the code the docs describe; `outbound`: side effects on the portal, Telegram, e-mail and Google). It produced 126 findings; the 47 blocker/high findings not already confirmed went to adversarial verification, and the 79 medium/low or confirmed ones were not re-verified. Examples: `E:` hard-coded in 11 runtime files (MIGRATION listed 5), `rich` and `pypdf` missing from the install list, and the CPU-only torch trap. The owner's grill-session decisions (the FAIL→FLAG downgrades, closing the auto-claim hole, the declined items) followed from these findings; see [07 §11](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md).
- **Pre-flight before the cold start:** `torch.cuda.is_available()` true on the RTX 5060, a pyzbar decode (the zbar DLL needs the MSVC++ redistributable), the EasyOCR model build (which exposed the cp1252 `verbose=True` crash → d659983), and one portal login.
- **Phase checks:** each cold-start phase's summary was read before the next started (`0 cached`, `FAILED` or `N failed` means stop). A read-only count against the live list confirmed phase 3 covered 214 + 29 + 55 + 28 = 326 students after 03ccf15 (it had covered 78).

### 4.6 The live-check tools, as code to copy

Sanitised copies of the four helpers the audits and verifiers relied on. Host names and page lists are parameters here; the originals hard-code the Hangeul portal. None of them contains a credential (the originals read the portal login from `C:\Hangeul\BOT\.env` with `python-dotenv`: value in secrets/bot.env (HANGEUL_USERNAME, HANGEUL_PASSWORD)).

**(a) The network guard** (from `C:\Hangeul\JARVIS\fix\scratch\jobs\guard.py`, 83 lines; import it before anything that makes HTTP calls). It lets the local host through (Ollama), lets the portal through only for a GET of an allow-listed page or the login POST, and refuses every other request, including Telegram and Google over httpx:

```python
import httpx

PORTAL_HOST = "portal.example"           # original: "hangeul.com.bd" (a substring test on the host)
LOGIN_PAGE = "login.php"
ALLOWED_PAGES = {"login.php", "students.php", "student_edit.php", "index.php"}   # per check
LOCAL_HOSTS = ("127.0.0.1", "localhost")
BLOCKED, NET_LOG = [], []


def _check(request: httpx.Request) -> None:
    host = request.url.host or ""
    m = request.method.upper()
    path = request.url.path.rsplit("/", 1)[-1]
    if host in LOCAL_HOSTS:
        return
    if PORTAL_HOST in host:
        if path not in ALLOWED_PAGES:
            BLOCKED.append((m, path))
            raise RuntimeError(f"GUARD: portal page not allowed: {m} {path}")
        if m == "GET":
            NET_LOG.append((m, path + ("?" + request.url.query.decode() if request.url.query else "")))
            return
        if m == "POST" and path == LOGIN_PAGE:
            NET_LOG.append((m, LOGIN_PAGE))
            return
        BLOCKED.append((m, path))
        raise RuntimeError(f"GUARD: non-GET to the portal refused: {m} {path}")
    BLOCKED.append((m, host))
    raise RuntimeError(f"GUARD: host refused: {m} {host}")


_orig_async_send = httpx.AsyncClient.send
_orig_sync_send = httpx.Client.send


async def _guarded_async_send(self, request, *a, **kw):
    _check(request)
    return await _orig_async_send(self, request, *a, **kw)


def _guarded_sync_send(self, request, *a, **kw):
    _check(request)
    return _orig_sync_send(self, request, *a, **kw)


httpx.AsyncClient.send = _guarded_async_send
httpx.Client.send = _guarded_sync_send


def summary() -> str:
    gets = sum(1 for m, _ in NET_LOG if m == "GET")
    posts = sum(1 for m, _ in NET_LOG if m == "POST")
    return f"portal requests: {gets} GET, {posts} login POST; blocked: {BLOCKED}"
```

Patching `send` (not `get`/`post`) catches every request the client makes, including redirects and the bot's own `portal_get`. The original also has `own_session()`: its **own** login (GET `login.php`, the `_csrf` value by regex, POST `_csrf`/`username`/`password`, fail if the final URL is still `login.php`), so the checker never shares the bot's parser or session.

**(b) The Google guard** (from `C:\Hangeul\JARVIS\fix\scratch\jobs\gguard.py`, 54 lines). The Google API client uses `httplib2`, the token refresh uses `requests`:

```python
import httplib2
import requests

GOOGLE_LOG = []
_orig_http_request = httplib2.Http.request
_orig_session_request = requests.Session.request
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _http_request(self, uri, method="GET", *a, **kw):          # Sheets / Drive: GET only
    if method.upper() != "GET":
        raise RuntimeError(f"GUARD: Google {method} refused: {uri.split('?')[0]}")
    GOOGLE_LOG.append(("GET", uri.split("?")[0]))
    return _orig_http_request(self, uri, method, *a, **kw)


def _session_request(self, method, url, *a, **kw):             # only the OAuth refresh
    if not (method.upper() == "POST" and url.startswith(TOKEN_URL)):
        raise RuntimeError(f"GUARD: requests {method} refused: {url.split('?')[0]}")
    GOOGLE_LOG.append(("POST", "oauth2 token refresh"))
    return _orig_session_request(self, method, url, *a, **kw)


httplib2.Http.request = _http_request
requests.Session.request = _session_request


def ro_credentials(token_path, scopes):
    """Refresh in memory only: the refreshed token is never written back to token.json."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(token_path, scopes)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return creds
```

The original then monkeypatches `progress_builder._load_credentials` with the read-only loader and replaces `progress_builder._intake_folder` with a lookup that raises `"GUARD: no intake folder <intake> (would have been created)"` instead of creating it.

**(c) `mask(text)`** (from `C:\Hangeul\JARVIS\command-audit\crosscheck\common.py:25-41`): letters → `x`, digits → `9`, except the `KEEP_WORDS` label and status words. The full code is in [04 §8](04_PORTAL_INTEGRATION.md).

**(d) Telegram's legacy Markdown parser** (from `C:\Hangeul\JARVIS\command-audit\critic\tg_markdown.py`, 61 lines; a re-implementation of tdlib's `parse_markdown` v1, the parser behind `parse_mode="Markdown"`):

```python
def parse_legacy_markdown(text: str):
    """Returns (ok, error_or_None, rendered_text, entities)."""
    out = []
    ents = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in "_*`[":
            out.append(text[i + 1]); i += 2; continue
        if c not in "_*`[":
            out.append(c); i += 1; continue
        begin = i
        end_ch = "]" if c == "[" else c
        is_pre = False
        i += 1
        if c == "`" and text[i:i + 2] == "``":
            is_pre = True
            i += 2
            # language line
            j = i
            while j < n and text[j] not in " \n`":
                j += 1
            if j < n and text[j] == "\n":
                i = j + 1
            end_ch = "`"
        start_len = len("".join(out))
        while i < n and (text[i] != end_ch or (is_pre and text[i + 1:i + 3] != "``")):
            out.append(text[i]); i += 1
        if i >= n:
            return False, f"Can't find end of the entity starting at offset {begin}", None, ents
        cur_len = len("".join(out))
        if cur_len != start_len:
            kind = {"_": "italic", "*": "bold", "`": "pre" if is_pre else "code", "[": "text_link"}[c]
            if c == "[":
                if i + 1 < n and text[i + 1] == "(":
                    i += 2
                    ub = i
                    while i < n and text[i] != ")":
                        i += 1
                    if i >= n:
                        return False, f"Can't find end of a URL at offset {ub}", None, ents
                    kind = "text_link"
            ents.append((kind, start_len, cur_len - start_len))
        if is_pre:
            i += 2
        i += 1
    return True, None, "".join(out), ents


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2
```

Its self-test inputs: ``"*a* [b] `c`"``, `"*a_b*"` (accepted: bold `a_b`), `"a_b"` (refused: an unclosed `_`), `"x [y"` (refused: no `]`), `"*1. Name* [Prog's]"`. Note that Telegram counts the 4096 limit in UTF-16 units **after** parsing (the rendered text), so check `utf16_len(rendered)`.

**Test rule for a new bot.** The unit-test fake Telegram (`tests\test_foundation.py` `Message`, `:165-175`) refuses Markdown only when a test sets `refuse_markdown=True`; it cannot catch malformed Markdown by itself. So add one test that runs **every formatter's output** (each command's reply builder, the brief, the alerts, the cheat-sheet) through `parse_legacy_markdown` and asserts `ok` and `utf16_len(rendered) <= 4096` for each piece that `split_text` produces. A name such as `<student name>_2` or an unescaped `[` then fails offline instead of in Telegram. **At `8317741` this exists for one command family only:** `tests\test_performance.py` carries a copy of the parser (`:1016`) and `test_every_reply_is_valid_legacy_markdown` (`:625`) runs every performance reply piece through it; the other formatters still rely on the live audits.

### 4.7 The Supabase release: what was verified, in what order (29-30 Sep 2026)

The Supabase publish layer (`src\cloud\`, 11 files) was built from the owner's spec `C:\Users\User\Downloads\hangeul-bot-prompt.md` (decisions D1-D13: full student data into the Supabase project `dcbcbpwpmdtaanboetiz`, whose `hg_*` tables belong to the Jeannie repo `C:\Hangeul\JARVIS\Jeenie-saem-bot`). Nothing was allowed to reach Supabase until the owner said "go", so the verification ran in this order, each step a separate workflow with its own agents and its own result file (`C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Downloads-hangeul-bot-main-hangeul-bot-main\b90661d9-fc40-4a81-bd34-103e0decce24\tasks\<task>.output`, JSON):

| Step | When (Dhaka) | Task (workflow) | Code | Result |
|---|---|---|---|---|
| Build: contract + inventory, `cloud/core`, three hook branches in parallel worktrees (`cloud/jobs`, `cloud/inproc`, `cloud/commands`), integrate into `cloud/all` | 29 Sep, morning | `wkuzhz3at` (`wf_1eb48122-237`; its result file stops after the integration) | 36ae72e … cb16394 | 823 passed (§1 growth) |
| Three adversarial reviews → fix | 29 Sep, before 14:39 | `wwn0lrljq` (the same workflow resumed after a network drop killed 4 agents) | 3caa393 | 11 + 5 + 5 issues; 855 passed; 18/18 mutations killed (§4.8) |
| **Dry run 1** (guarded, nothing uploaded) | 29 Sep 14:39-14:53 | `wwn0lrljq` | 3caa393 | NOT READY: R1 portal fillers (§4.9) |
| Fix → **dry run 2** | 29 Sep 15:37-15:51 | `w02m6lyyu` (`wf_e7425917-377`) | 752cd53 | NOT READY: Cloudflare e-mail stand-ins (§4.9) |
| Fix → **dry run 3** | 29 Sep 16:22-16:37 | `wd0c6zkf8` (`wf_3b282e15-484`) | 9ead47d | **READY**, checks a-l pass (§4.9) |
| Performance page (separate line of work on `main`): build, live check, review, fix | 29 Sep 21:48 (self-computed) and 30 Sep 13:11-14:06 (the portal's page) | `w56wkwh83`, `wfp0dh5ak` (`wf_9efae077-816`) | bbd8f98, a721066; ce23535, 314afdb | 775 then 884 passed; 161/161 then 34/34 + 9/9 figures matched live (§4.10) |
| Release merge + **preflight** | 30 Sep ~21:00-21:40 | `w07j1ddbg` (`wf_c194037b-cbc`) | e5e532e, e4d1cea; then 8317741 | 1150 passed; 6/6 checks pass; one low issue fixed in 8317741 (§4.11) |
| Deploy with publishing off, **real backfill**, **postcheck**, publishing on | 30 Sep 21:47-22:43 | `w9tx2ubg3` (`wf_1387fada-bf6`) for the postcheck | 8317741 | 13,540 = 13,540 records, verified (§4.12) |

Common to every live step (the same method as §4.2): read-only portal GETs plus the login POST only, under a network guard at the HTTP, DNS and connect layers; the Hugging Face hub answered "offline" inside the process (never contacted); the bot's `C:\Hangeul\BOT` never checked out, edited or restarted by the verifiers (they worked in worktrees under `C:\Hangeul\JARVIS\cloud\` and copied the git-ignored inputs from `C:\Hangeul\BOT\data` byte for byte); the dry runs waited for the live 15-minute sync to release `data\auto_sync.lock` and read the portal between two syncs; each dry run's own counts were **re-derived independently** with the verifier's own session and parsers (nothing imported from `src`); output masked (letters/digits/`<name>`/`<passport>`), with payloads and page caches left only in git-ignored folders.

### 4.8 The three code reviews of 29 Sep (task `wwn0lrljq`, on `cloud/all` at cb16394)

Three reviewers read the spec, the Jeannie migration SQL (`hg_sync`, `hg_match`, `hg_changes_since`, the table constraints), REFERENCE 01/09 and every `src\cloud` file plus the hook diffs, each with its own scratch harnesses in `C:\Hangeul\JARVIS\cloud\scratch\review-*\` (synthetic data, a `MockTransport` that applies the SQL rules, the stub embedder):
- **contract** (11 issues: 1 high, 4 medium, 6 low): the high one was the hash state forgetting deleted keys before the deleting call was accepted; others were `pending_payment` published complete whenever the page parsed, reader fillers (`Unassigned`, stand-in words) in data and text, the embed model not enforced across runs, the consultation key not the portal id, `student_uid` null on passport-keyed kinds. Confirmed OK: every `hg_sync` field against the SQL, the canonical `content_hash`, batching (450 changed rows → 200/200/50 with `p_all_keys` only on the 3rd call; 40 long OCR pages → 31 + 9 rows under `MAX_CHUNKS` 250), `hg_runs` POST then PATCH, chunks ≤350 words, one `embed_model` string.
- **safety** (5 issues, 3 medium): an older complete read published later won (rolled back newer rows); a failed read of the watcher's memory still led to a delete; the sync published `student_export` complete on its header alone. Confirmed clean: partial or failed reads never send `p_all_keys`; Supabase failures cannot touch Drive, Sheets, Telegram or the brief; the event loop stays free; no torch in the bot; the portal still GET-only.
- **secrets and tests** (5 issues, 1 medium: no test of a timeout or refused key on `hg_sync` itself): no path by which a key reaches a log line (the key travels only in headers, `follow_redirects=False`; every failure line is built from the HTTP status, a regex-checked Postgres code or the exception type, never the server's message, because the SQL's messages quote row keys that hold passport numbers); 22 mutations against the 164 cloud tests (§2.4); the date-fix proof with a fake clock (§2.5); all 659 old test ids still present; the staging copies identical.

The fixer (3caa393) fixed 17 items, declined 4 with reasons (`read_at` refreshed only when the hash changes, a SQL matter for the Jeannie side; `calendar_item` never complete, by design; the REFERENCE secrets README, outside the worktree; ordering pending handoffs, made unnecessary by the read-time rules) and added `tests\test_cloud_fixes.py` (32 tests): **855 passed**; its own 18 mutations on a scratch copy were all killed.

### 4.9 The three guarded dry runs (29 Sep 2026)

(The dry-run and postcheck methods as operating procedures are in [13 §15.4-§15.5](13_SUPABASE_PUBLISHING.md); this section is the record of what they found.) Each ran the real entry point `python -m src.cloud.backfill --dry-run --docs-root "C:\Hangeul\VERIFIED STUDENT DOCUMENTS"` (dry runs 2 and 3 through `runpy` as `__main__`) from the `cloud/all` worktree, with the guard `C:\Hangeul\JARVIS\cloud\scratch\dryrun\guard.py`; `publish.TRANSPORT` raised on any use. A dry run writes every `hg_sync` body it would have sent to `data\cloud\dry_run\<YYYYmmdd-HHMMSS>-backfill-<id>\` (plus the `hg_runs` POST and PATCH) and changes no state. Scripts and outputs: `C:\Hangeul\JARVIS\cloud\scratch\dryrun\` (run 1) and `scratch\verify\` (runs 2 and 3).

| | Dry run 1 | Dry run 2 | Dry run 3 |
|---|---|---|---|
| Code | 3caa393 | 752cd53 | 9ead47d |
| Time | 14:39:23-14:53:16, 833 s | 15:37:13, 857 s (portal 190 s, disk 666 s) | 16:22:54-16:37:10, 856 s (portal 199 s) |
| Payloads | `…\20260929-143923-backfill-1e3ac770\`: 594 files (592 `hg_sync` bodies), 97 MB | `…\20260929-153713-backfill-bbac263b\`: 603 files (601 bodies) | `…\20260929-162254-backfill-244bfaa8\`: 603 files (601 bodies), 99 MB |
| Records / chunks | 13,179 / 15,218 | 13,189 / 15,228 | 13,194 / 15,234 |
| Embedding | 727 s (5.5 s per 100 records; model load 5.0 s, CPU, float32, 384 dims) | 747 s, model load 5.2 s | 741 s, model load 5.2 s |
| Peak RAM (working set) | 1.57 GB (commit 2.77 GB); +740 MB when the model loads | 1.55 GB | 1.50 GB |
| Portal traffic (guard) | GET `students.php` 13, `progress.php` 331, `consult_requests.php` 65, `index.php` 1, `calendar.php` 1, `window_applications.php` 1, `login.php` 2; POST `login.php` 2; blocked 0; Supabase attempts 0 | the same with `progress.php` 333; blocked 0; Supabase 0 at the transport, HTTP, DNS and connect layers | the same; the outside `netstat` monitor saw only the portal's Cloudflare IPs and loopback |
| Largest body | 1.98 MB (student, 200 rows) | 999,562 bytes (0 over 1,000,000; at most 183 rows a call) | 999,493 bytes |
| Independent counts | all 21 kinds match (e.g. 331 students = pager total, 1013 consultations = the All tab from 11 Aug, 3377 OCR pages, 2643 `doc_verdict`, 3400 `field_check`, 302 `passport_alert`, 278 `passport_issue`) | all 21 match; every difference from run 1 (2 new students, 1 verification, 1 consultation, 1 pending payment, a dashboard figure) confirmed by key sets | all 21 match (1020 consultations, 327 verifications, 0 pending) |
| Verdict | **NOT READY**: R1, the portal's own typed fillers (`N/A` 45×, `None`, `--`, `PENDING` 7× in student details; `PENDING` in 9 export cells) kept in data and text; second: a missing model logged one line per publish (~600 for a backfill) | **NOT READY**: every fix holds (0 whole-value fillers in 13,189 records; `blank_on_portal` exact against the raw pages: 69 students / 78 cells, 69 export rows / 80 cells; CUDA really hidden, `-1` at the OS level; one log line a run), but **Cloudflare's `[email protected]` stand-in** sat in all 333 students' `details.Email` and 1,005 of 1,014 consultation contacts (already in run 1, caught by neither run's checks) | **READY** |

What each fix changed: after run 1, `records.is_filler` / `is_status_field` and `data["blank_on_portal"]`, one log line per run on `EmbedError`, `CUDA_VISIBLE_DEVICES=-1` (an empty value is removed from a Windows child's environment, and torch then still saw the GPU at the driver level), and the 1 MB body cap (752cd53, 872 tests). After run 2, `parsers.decode_cf_emails` at every soup (the stand-in is the address XOR-ed with the first byte of `data-cfemail`), `emailprotected` added to the filler words, and the `sentence_transformers`/`transformers`/`huggingface_hub` loggers kept at WARNING (9ead47d, 900 tests).

**Dry run 3's checks a-l, all passed:** (a) per-kind counts equal two independent reads (16:26 and 16:38, 90 and 88 GETs) and the previous run; (b) 0 whole-value fillers, `Pending` only in status fields; (c) `blank_on_portal` exactly where fillers were (69/69 students, 78/78 cells; 69/69 export rows, 80/80 cells); (d) 601 bodies ≤1 MB, `p_all_keys` only on the last call of each (kind, scope) and holding every key sent there, never on `field_correction`; (e) 15,234 chunks of 384 finite floats, norms 0.9999999-1.0000001, one `embed_model` `thenlper/gte-small@17e1f347…`, longest chunk 510 tokens (limit 512); (f) 0 duplicate keys, 0 `content_hash` mismatches in 13,194 rows; (g) CUDA hidden (`is_available` False, `device_count` 0, the process never in `nvidia-smi`'s list over 369 samples); (h) model unavailable (`HF_HOME` empty): exactly one WARNING per run, in-process and in a publisher child; (i) nothing reached any host but the portal; (j) **0 Cloudflare stand-ins in 657,652 strings** across all 603 files (the same scanner finds 333 + 1,005 + 1 in run 2's payloads); (k) every decoded address equals the verifier's own decode of its own raw GETs (666 `data-cfemail` elements on `students.php`, 1,013 elements and 1,020 protection links on `consult_requests.php`; no address printed); (l) the bot's own outputs (`/inquiries_today`, `/inquiries_date`, `/students`, the `/sendmail` list-page lookup) run with fake Telegram objects contain no stand-in. Suite at 9ead47d: 900 passed in 45 s. The owner then asked to inspect the payloads first; nothing was uploaded that day.

### 4.10 The performance page's live checks (29-30 Sep 2026, tasks `w56wkwh83`, `wfp0dh5ak`)

Same method, on `main`'s line of work (worktrees `C:\Hangeul\JARVIS\perf\build` and `perf2\build`): the handlers run with the foundation's fake `Update`/`Message`/`Sent` objects against the worktree code, a guard on httpx allowing only GETs of the pages concerned plus the login POST, and every figure re-derived by the verifier's own session and BeautifulSoup parsing (nothing imported from `src`).
- **The self-computed version (bbd8f98, 29 Sep 21:48-21:49):** 161 figures compared per run, 0 mismatches, in two runs; today 10 requests, month 9 (the date filter split past the 500-row list). A review then found 10 surviving mutations, which a721066 closed (22 mutations, all caught; 775 passed). The owner then **replaced** this meaning of "performance" (30 Sep 13:11): only the portal's own Consultant Performance page.
- **The portal's page (ce23535, 314afdb, 30 Sep):** `/performance_today` = GET `login.php`, POST `login.php`, GET `index.php` (the login redirect), GET `consult_performance.php?period=today`, 1.2 s, one message of 1,188 UTF-16 units, valid legacy Markdown; `/performance_month` one GET of `?period=month`, 0.3 s, 1,634 units; the tiles equal their columns' totals; free text `performence this month` / `performence today` gave the same replies; `consultant performance yesterday` and `ytd performance` made no portal request and got the other-period reply. Independent check: 34/34 and 9/9 figures matched. 71 of the new tests fail against ce23535's code, so they catch every fixed defect; 884 passed. The reviewer also found the merge trap for later: `cloud/all` had renamed `_decode_cf_emails` to `decode_cf_emails`, which would have auto-merged into a `NameError` in every performance reply (fixed in the release merge, §4.11).

### 4.11 The release merge and its preflight (30 Sep 2026, task `w07j1ddbg`)

`cloud/release` = `cloud/all` (9ead47d) + `git merge --no-ff main` (314afdb) = e5e532e, in the worktree `C:\Hangeul\JARVIS\cloud\release`; then e4d1cea added the kind `consultant_performance` (published by the performance commands and the hourly full picture). The merge's logical conflicts, with no conflict markers: `parse_consult_performance` called the removed `_decode_cf_emails` (now the whole soup is decoded; the wrapped-soup count went 12 → 13 in `parsers.py`); `test_performance.py` used `parsers._cf_email` (now `_cf_address`); both branches had pinned `ask.local_today` (kept `pin_today`, removed the duplicates); a date-dependent test inherited from `cloud/all` (`pin_job_clock`, §2.5). Suite: 1125 after the merge, **1150 passed, 0 failed, 0 skipped in about 46-47 s** at e4d1cea (`-p no:cacheprovider`).

The independent preflight's six checks (verdict: ready to deploy with publishing **off**):
1. `git merge-base --is-ancestor main cloud/release` exit 0: `main` can fast-forward; `C:\Hangeul\BOT` clean and untouched.
2. Full suite 1150 passed in 47 s; the three staging pairs byte-identical by hash.
3. Nothing lost from either parent: `src\cloud` has the same 11 files; hook call sites counted per file (`telegram_bot` 34 → 37 with the performance handler, `ask` 19, `scheduler` 9, `auto_sync` 2, `passport_issue` 2, `stage_report` 1); the removed self-computed readers exist only in a721066.
4. **A fourth guarded backfill dry run** (`C:\Hangeul\JARVIS\cloud\scratch\verify_release\run_dry4.py`, a copy of `run_dry2.py`, after the 21:22:21 sync released its lock, with fresh copies of the git-ignored inputs): rc 0, 0 failed reads, 0 blocked requests, 0 Supabase attempts, 0 warnings, `CUDA_VISIBLE_DEVICES=-1`, peak 1.53 GB, 1,064 s, 615 `hg_sync` calls; counts against dry run 3: students 333 → 340, verifications 327 → 333, `student_documents` 155 → 160, consultations 1,020 → 1,034 (51 days), passports in results 154 → 158, `passport_alert` 302 → 311, `passport_issue` 278 → 282 (only the dated report keys went away); 0 fillers, 0 stand-ins, largest body 999,526 bytes, 15,614 chunks of norm 1.000000 under one `embed_model`.
5. `/performance_today`, `/performance_month` and `/inquiries_today` live with fake Telegram and publishing on against a blocked fake host: today 4/4 tiles, count badge 6, 6/6 rows and 36/36 figures; month 4/4 tiles, count 7, 7/7 rows and 42/42 figures; the handoff payloads complete with 7 and 8 keys equal to the page's; the handler itself ran no publish (one background task wrote the handoff after the last reply).
6. Publishing off (the live `.env` had the URL and key but no `CLOUD_PUBLISH_ENABLED` line): replies of the same length (1,444, 1,622, 1,534 characters), 0 background tasks, 0 handoff files, 0 publishers; `run_full_picture` started nothing; `CLOUD_PUBLISH_ENABLED=` (empty) raises a pydantic `ValidationError` at start-up, so it must be `true` or `false`.

Problems it reported: **low**, the month scope `month|<first>|<last>` would change every day from 1 October (the portal ends each period at today), stranding a consultant who drops off in an older scope that no complete read covers again; **info**, the backfill did not read the performance page. Both were fixed in **8317741** (scope `<period>|<first ISO day>`; `backfill.collect_performance` for today and this month; +2 tests, 1152).

### 4.12 Deploy, the real backfill and the independent postcheck (30 Sep 2026)

- **21:47** `main` fast-forwarded to 8317741 and the bot restarted with publishing **off** (no `CLOUD_PUBLISH_ENABLED` line). The 4 Jeannie migrations (`20260928000000`, `20260928180000`, `20260929030000`, `20260929030100`) had been applied earlier with the Supabase CLI v2.118.0 (`C:\Hangeul\JARVIS\tools\supabase\bin\`, `supabase link` + `db push`; `migration list` local = remote).
- **21:48-22:05 the real backfill**, from `C:\Hangeul\BOT` with `CLOUD_PUBLISH_ENABLED=true` in that one process's environment only; log `C:\Hangeul\BOT\data\cloud\backfill_20260930.log` (counts only): **13,540 records, 15,629 chunks, 0 failed reads**, `Done in 1025 s; 0 read(s) failed.`, `hg_runs` status ok. Per kind: student 340, student_export 340, student_progress 340, verification 333 (57 day scopes), student_documents 160, consultation 1,034 (51 days from 11 Aug 2026), consultation_day 51, consultation_totals 1, pending_payment 1, window_application 0, dashboard_fact 39, calendar_item 22, consultant_performance 15 (7 today + 8 month), doc_verdict 2,717, field_check 3,490, doc_check 158, field_correction 0, report 3, report_section 434, doc_page_text 3,469, passport_alert 311, passport_issue 282. `data\cloud_state.json` exists from then on.
- **The independent postcheck (task `w9tx2ubg3`, verdict "verified", 0 problems)**, read-only on both sides (Supabase GETs only, a guard refusing any other method, `/rpc/` and any other host; the portal GET plus one login POST; its scripts in `C:\Hangeul\JARVIS\cloud\scratch\postcheck\`, page and table caches holding student data kept only in the session scratchpad):
  1. `hg_records` per kind vs the verifier's own reads of the live portal (22:11-22:13) and the data files, **by key set**: all 22 kinds equal, 13,540 = 13,540. The one difference since the backfill, consultation request 1078 received at 22:12, also explains 30 Sep's day counts and the all-time total 1,035.
  2. One `embed_model` on all 15,629 `hg_chunks` rows; 669 sampled vectors across 20 kinds all 384 finite numbers with L2 norm 1.000000; the column is `extensions.vector(384)`; 56 chunks re-embedded offline with gte-small at the pinned revision: cosine 0.99979-1.00048 to the stored vectors.
  3. Every record has a chunk (0 without, 0 orphans, 0 `ord` gaps, 0 empty texts); 157,187 data leaves, 13,540 contents and 15,629 chunk texts scanned: 0 whole-value fillers, 0 Cloudflare stand-ins, `Pending` only as a status value.
  4. Two independent random draws, one record per kind each: 30 records across 15 kinds, **388 of 388 fields equal** (student details, all 63 export columns, live `progress.php`, stamp days, document links, decoded consultation e-mails, calendar, consultant performance, document-check rows, whole OCR page texts, watcher memory, issue dates).
  5. `hg_runs` has one row (job `backfill`, status ok, 15:48:09Z-16:05:13Z) whose counts equal the tables (upserted 13,540, chunks 15,629, deleted 0, unchanged 0, `failed` and `failed_reads` empty, `by_kind` equal for all 22 kinds); `hg_changes` has 13,540 upserts and 0 deletes, all with the backfill's `run_id`.
  6. A GET with no key, or with an invented `sb_publishable_`-shaped key, gets HTTP 401 on `hg_records`, `hg_chunks`, `hg_runs` and `hg_changes` (the real publishable key could not be tried: none is on this PC).
- **22:27 publishing on:** `CLOUD_PUBLISH_ENABLED=true` added as `.env` line 43, the bot restarted; the start-up line now ends `, Supabase full picture every 60m.`. **First automatic runs** (from `hangeul_sync.log`): `full_picture` at 22:35:33, `ok, 3 upserted, 0 deleted, 779 unchanged` (request 1078, its day and the totals), 6.9 s in all, `12 batch(es) read in 18.3 s, 0 read(s) failed; 68 publish(es), 0 failed`; `portal_sync` at 22:43:15, `ok, 0 upserted, 0 deleted, 976 unchanged`, 0.4 s. By 23:43 four more sync runs (22:58, 23:13 with 2 rows sent, 23:28 with 3, 23:43) and a second full picture (23:35, 0 upserted, 782 unchanged) had all logged `ok`.
- **Incident noted during the dry runs:** on 29 Sep 16:36-16:41 the live bot was down about 5 minutes (killed with no error; the watchdog restarted it) while dry run 3 and its verifiers ran. The cause is unconfirmed (some agent transcripts mention `Stop-Process`). Every later agent prompt says: never stop or kill a `python`/`pythonw` process you did not start.

---

## 5. Rules for tests and audits in a new bot (what this project learned)

1. **Fake at the transport, not the function.** An `httpx.MockTransport` that serves HTML keyed by `page?query` exercises the real client, session, pagination and parsers. It must **fail the test on any non-GET** and on any login.
2. **Build synthetic pages from the live layout**, and update the builders when the portal changes (`row()`/`page()` copy the live `students.php` classes, including decoys such as the stage and intake `<select>`s).
3. **Model Telegram's refusals** (4096 UTF-16 units, Markdown parse errors) in the fake message, so splitting and plain-text fallbacks are tested, not assumed. And run every formatter's real output through `parse_legacy_markdown` + `utf16_len` (§4.6), because a fake that refuses only on request cannot find malformed Markdown.
4. **Test the failure words:** every reader has a test where the portal is down, the login is refused, the session has expired, or the layout is unknown, and the reply must say so, never 0, "none" or an empty list.
5. **Pin dates, in every module that holds a name for the clock:** a fixed `local_today` and `_now`, whole-word month parsing, impossible dates returning None. A module that did `from src.dates import local_today` keeps its own reference, so patch it there too (`pin_today`, §2.5), and a subprocess job that reads `time.time()` / `time.strftime` needs its own pin (`pin_job_clock`). Prove it with a fake clock at several dates (a month end, a year end, the day after the tests were written): the 6 date failures of 29 Sep were invisible on 28 Sep.
6. **After every portal change, re-run the independent audit:** run the handlers with recording fakes, re-derive the figures with a separate client and parser, compare, and keep the network guard on. Unit tests prove the logic; only the independent live comparison proves the figures.
7. **Keep staging copies byte-identical** (`cmp telegram_bot.py src\bot\telegram_bot.py`, `cmp config.py src\config.py`, `cmp progress_builder.py src\sheets\progress_builder.py`) as part of the test routine; since 36ae72e a test asserts it too.
8. **Fake every outside store at its transport, and make the fake enforce the server's own constraints.** `FakeSupabase` (§2.4) refuses what the SQL refuses (201 rows in a call, a 383-number embedding, two models in one call, a `read_at` without its time zone, a NUL in a text, an unknown run), applies the same upsert, unchanged and delete rules, and fails the test on any other host, path, method or a wrong key header. A stub embedder keeps the suite fast; one slow test proves the real model.
9. **Turn the side effect off for every test by default** (`conftest.py`'s autouse `_no_real_supabase`), and switch it on only through a fixture that points it at the fake. A test that starts a **real child process** cannot be reached by `monkeypatch`: skip it where a real `.env` exists (§1) and run it in a clean `git archive` copy.
10. **Test the invariant "the job is the same with or without the copy":** the reply with publishing on equals the reply with it off (`same_reply_either_way`); Supabase down, slow or buggy changes nothing the job sends, prints or remembers, and costs exactly one log line with no student data.
11. **Before the first real write to a new store, run guarded dry runs until one passes every check,** and re-derive every count independently. Each of the three dry runs of 29 Sep found something the unit tests and the reviewers had not (the portal's typed fillers; Cloudflare's hidden e-mails, present in both earlier runs), and each finding became a regression test file (`test_cloud_dry_run.py`, `test_cloud_cf_email.py`). Add a scanner for every placeholder shape found so far to the checks of the next run.
12. **After the real write, verify the store itself, read-only and by key set,** not by the writer's own counts: per-kind key sets against fresh independent reads, the vectors (dimension, norm, one model, re-embedded samples), no filler or stand-in, random field-by-field spot checks, the run log and change log, and that an unauthenticated read is refused (§4.12).
