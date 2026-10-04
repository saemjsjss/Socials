# 04 — Portal integration (hangeul.com.bd/admin, read-only scraping)

**What's in this file:** every page of the agency's admin portal that Hangeul BOT touches, with its URL, query parameters, HTML structure and exactly how the bot parses it (by header names and CSS classes, never by position), the read-only rules and the guardrails file, Cloudflare's e-mail obfuscation on every page and how it is undone, the Consultant Performance page (`consult_performance.php`), the layout changes that broke the bot in September 2026, and every guard that stops a failed or changed page from being reported as a confident 0. Section 8 is the survey checklist (with the masking helper) for deriving the same contracts from a *different* portal.
**Pack refreshed:** 30 September 2026 (Asia/Dhaka), at `main` = `8317741` (first written 29 Sep 2026 from `c17d887`; the 20 commits between them are in [08](08_HISTORY_STAGE_BY_STAGE.md)).
Sources: `C:\Hangeul\BOT` at HEAD `8317741` (`src\scraper\client.py` 778 lines, `src\scraper\parsers.py` 1351 lines, `src\bot\ask.py`, `src\bot\performance.py`, `src\sheets\*.py`, `src\cloud\backfill.py`, `src\cloud\full_picture.py`, `src\cloud\records.py`), the synthetic page fixtures that copy the live markup (`tests\test_performance.py:55-195`, `tests\test_cloud_cf_email.py:48-80`, `tests\test_foundation.py`, `tests\test_consultations.py`), the workflow results of 29-30 Sep (the Consultant Performance page survey of 30 Sep, the three Supabase dry runs of 29 Sep), `C:\Hangeul\BOT\data\cloud\backfill_20260930.log`, and page snapshots saved by the audit in `C:\Hangeul\JARVIS\command-audit\` and `C:\Hangeul\JARVIS\fix\scratch\` (structure only is quoted here; no student data).
Sibling file: [Telegram commands and jobs](05_TELEGRAM_COMMANDS_AND_JOBS.md) (who calls each reader, and what the replies look like). Also: the code-level map of the client and parsers in [03b](03b_FILES_src_scraper_llm_api_config.md), the Supabase publish layer that re-uses these readers in [13](13_SUPABASE_PUBLISHING.md) and [03d](03d_FILES_src_cloud.md), the sheet jobs' portal reads in [07](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md), the system view in [01_ARCHITECTURE.md](01_ARCHITECTURE.md), the rules these guards came from in [09](09_BLUEPRINT_RULES_AND_LESSONS.md), and the pack index in [00_INDEX.md](00_INDEX.md).

All student values below are placeholders (`<student name>`, `<uid>`, `HNG-2026-<n>`, `<address>`). Aggregate figures (330 students, 999 requests...) are the live values of 28 Sep 2026 (with 30 Sep values where the page is new or the count moved: 340 students, 1,035 requests) and are given only so a rebuilder knows the orders of magnitude. Consultants on the Consultant Performance page appear only as placeholders (`<consultant A>` …); the example replies are in [05 §5.15](05_TELEGRAM_COMMANDS_AND_JOBS.md).

---

## 1. The connection

| Item | Value | Where |
|---|---|---|
| Base URL | `https://hangeul.com.bd/admin` (`.env` `HANGEUL_BASE_URL`; the code default is the same) | `src\config.py:24` |
| Credentials | value in `secrets/bot.env` (`HANGEUL_USERNAME`, `HANGEUL_PASSWORD`); `secrets/bot.env` is the copy of `C:\Hangeul\BOT\.env` | `src\config.py:25-26` |
| Mock mode | `.env` `MOCK_MODE=false` (code default `True`; mock data in `src\scraper\mock_data.py`) | `src\config.py:21` |
| HTTP library | `httpx==0.28.1` `AsyncClient(headers=..., follow_redirects=True, timeout=15.0, verify=False)` | `client.py:113-118` |
| Parser | `beautifulsoup4==4.15.0` with the stdlib `"html.parser"` (no lxml); **every** soup is built as `decode_cf_emails(BeautifulSoup(html, "html.parser"))` (section 1.4) | `parsers.py` |
| User-Agent | a desktop Chrome 122 string; `Accept: text/html,...`; `Accept-Language: en-US,en;q=0.9` | `client.py:107-111` |
| Singleton | `admin_client = HangeulAdminClient()` shared by the whole bot process | `client.py:778` |
| Separate sessions | every subprocess job has its own session (a new process has its own `admin_client`; the issue-date refresh uses that one, `passport_issue.py:61`); the sync and the stage report build fresh clients (`auto_sync.py:89-93`, `stage_report.py:44-54`, `:78`); and the Supabase jobs: the hourly full picture (`PortalSession(HangeulAdminClient)`, `src\cloud\full_picture.py:77-92`) and the one-time backfill (`src\cloud\backfill.py:504`) | as listed |
| In front of the portal | **Cloudflare** (the dry run's outside `netstat` monitor saw only the portal's Cloudflare IPs 104.26.0.102 and 104.26.1.102). It rewrites every e-mail address in every page (section 1.4) | — |

TLS verification is off (`verify=False`, commented "Allow flexible SSL handling"). **No reason is recorded** anywhere (repo docs, commit messages, session transcripts): it is inherited from the baseline `366dec0`, and the audit and verification scripts copied it. **Rebuild rule:** `verify=True`; on a network that intercepts TLS, export the Windows roots to `data\windows-ca.pem` with `tools\export_windows_ca.ps1` so the hook below trusts them ([03b §3.4](03b_FILES_src_scraper_llm_api_config.md)). Separately, `src\__init__.py:16-22` points `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `HTTPX_SSL_CERT_FILE` etc. at `data\windows-ca.pem` (exported by `tools\export_windows_ca.ps1`) because antivirus/ISP TLS interception on the old PC broke certifi-based verification for Google and PyPI (26 Sep 2026). On this PC `data\windows-ca.pem` does not exist, so that hook is inactive.

### 1.1 The one session path: `portal_get` / `fetch_html`

`HangeulAdminClient.portal_get(path, params=None, timeout=60.0) -> httpx.Response` (`client.py:314-337`) is the one way new code reads a page:

1. `_ensure_session()` (`client.py:294-301`): if `is_authenticated` is False, call `login()`; a failed login raises `PortalUnavailable("couldn't log in to the portal: <why>", unreachable=...)`.
2. One GET (`_get_once`, `client.py:303-312`) with `httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT))`, `CONNECT_TIMEOUT = 10.0` (`client.py:48`: a host that does not take the connection is given up on after 10 s; a slow 2 MB page still gets its full `timeout`). `params` are URL-encoded by httpx, so `"Admission & Tuition"` stays one value.
3. If the final URL path ends with `login.php` (`_ended_on_login`, `client.py:93-95`), the session expired: set `is_authenticated=False`, log in once more, repeat the GET. If it still ends on `login.php` -> `PortalUnavailable("<path>: the portal kept sending its login page after a fresh login")`.
4. `status_code >= 400` -> `PortalUnavailable("<path>: the portal answered HTTP <code>")`.
5. `httpx.TimeoutException` -> `PortalUnavailable("<path>: the portal did not answer in time (<Type>)", unreachable=True)`; `httpx.TransportError` -> `PortalUnavailable("<path>: could not connect to the portal (<Type>)", unreachable=True)`.

`fetch_html(path, timeout=60.0, params=None) -> str` (`client.py:339-342`) is `portal_get(...).text`.

`class PortalUnavailable(RuntimeError)` (`client.py:66-77`) has `.reason` (a short plain-English reason for the reply) and `.unreachable` (True = the portal did not answer at all; the daily brief uses it to skip its remaining reads, and so do the full picture's `PortalSession` and the backfill's collectors). `portal_error_reason(e)` (`client.py:80-90`) turns any exception into that reason: `PortalUnavailable.reason`, `"the portal did not answer in time"` for timeouts, `"could not connect to the portal (<Type>)"` for transport errors, else `"<Type>: <text>"` (never an empty string: `_error_text`, `client.py:61-63`, falls back to the type name because `str(httpx.ReadTimeout(''))` is `''`).

**Design rule:** a page that cannot be read is an exception, never an empty list or `0`. Every reply turns it into `❌ Couldn't read the portal: <why>. <what>: not available right now. Please try again in a minute.` (`src\bot\replies.py:159-165`). The Supabase layer applies the same rule one step further: a read that failed publishes nothing, and only a *whole* read may delete rows there ([13](13_SUPABASE_PUBLISHING.md)).

### 1.2 Legacy raw reads that bypass `portal_get`

These still call `self.client.get(...)` directly with a hand-rolled "ended on login.php -> log in again" check. They are older code; a rebuild should route them through `portal_get`.

| Method | Page | Behaviour on failure |
|---|---|---|
| `get_consultation_requests(target_date)` `client.py:269-285` | `consult_requests.php` (unfiltered, newest 500 only) | returns `[]` (silent). Used only by the REST API `/api/applications/consultations` and `/inquiries` (known leftover). Since `9ead47d` its `contact` carries the decoded address (`<phone> <address>`) instead of the stand-in |
| `get_calendar_events()` `client.py:570-590` | `calendar.php` | returns `{"today_reminders": [], "upcoming_events": [], "error": <text>, "layout_ok": False}`; callers treat `"error" in` or `layout_ok False` as "not available" |
| `get_student_full_profile(id)` `client.py:592-628` | `student_edit.php?id=N` | returns `{}` (used only by the `/sendmail` fallback lookup); its soup is decoded too (`client.py:614`) |
| `_find_student_in_export(q)` `telegram_bot.py:1187-1226` | `students.php?export=csv` | raises `RuntimeError` when the export has no `Student ID` column; caller falls back to the all-pages list reader |
| `_fetch_all_students_async()` `progress_builder.py:223` | `students.php?export=csv` | `raise_for_status()`; raises if the response is neither `text/csv` nor contains `Full Name` in its first 2000 chars |
| `_download_zip(client, uid)` `verified_docs.py:208` | `download_docs.php?uid=N&zip=1` | raises when `content-type` does not contain `zip` |
| `crawl_page(path)` `client.py:741-775` | any path (REST API `/api/crawler/parse-page`) | returns `{"error": ...}`; see the warning in section 2.3 |

### 1.3 Timeouts per read

| Read | Timeout (s) |
|---|---|
| `login.php` GET (CSRF) | 30 |
| `login.php` POST | client default 15 |
| `index.php` (`get_dashboard`, `ask._dashboard`, the backfill's `collect_dashboard`) | 30 |
| `students.php` pages, `consult_requests.php`, `calendar.php`, `consult_performance.php` (`fetch_html` default) | 60 (connect 10) |
| `student_edit.php` in the passport audit | 30 |
| `student_edit.php` in the issue-date refresh | 60 |
| `view_doc.php` scan download | 60 |
| `progress.php` | 30 |
| `students.php?export=csv` | 60 |
| `download_docs.php` ZIP | 300 |
| Daily brief: each read / all reads together | `READ_TIMEOUT=75.0` / `PORTAL_BUDGET=150.0` (`brief.py:69-70`) |
| Hourly full picture: the whole process | `DEADLINE = 45 * 60` s (`src\cloud\full_picture.py:58`; it `os._exit(3)`s after that, long before the next hour) |

### 1.4 Cloudflare's e-mail obfuscation (every page)

`hangeul.com.bd` is served through Cloudflare, whose "Email Address Obfuscation" rewrites **every e-mail address in the HTML of every page** before it reaches the bot. A browser runs Cloudflare's script and shows the address again; a parser reading the HTML sees the stand-in text `[email protected]` (with a no-break space: the HTML is `[email&#160;protected]`, the parsed text `"[email\xa0protected]"`). Found by the second Supabase dry run (29 Sep 2026 15:37), fixed in `9ead47d` (29 Sep 16:19).

**The markup** (three forms, plus one script tag per page):

```html
<!-- 1. the "a form": an address in the page's text -->
<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</a>
<!-- 2. the "span form" (same, as a span) -->
<span class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</span>
<!-- 3. the "link form": a mailto link; the address hides in the fragment, the text is usually the span form -->
<a href="/cdn-cgi/l/email-protection#HEX"><span class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</span></a>
<!-- the decoder a browser runs (the bot never fetches it) -->
<script data-cfasync="false" src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script>
```

**Where it appears (live counts, 29 Sep 2026):**

| Page | What is rewritten | Count |
|---|---|---|
| `students.php` | 2 per student: the Student cell's `<div class="pii stu-mail">` (a form) and the details row's "Email" `.det-item` | 100 `data-cfemail` on a page of 50; 666 over all pages (333 students) |
| `consult_requests.php` | the contact line's mailto (link form), a name typed as an address inside `a.cr-name` (span form), addresses inside the details (a form) | 1,013 `data-cfemail` elements and 1,020 protection links over all days; one day's page had 12 link-form contacts |
| `progress.php`, `calendar.php`, `index.php`, `window_applications.php`, `student_edit.php` (text, not input values) | any address in their text | decoded the same way (pinned by tests) |
| `consult_performance.php` | nothing seen on 30 Sep (decoded anyway, as a precaution) | 0 |
| `students.php?export=csv` | **not** rewritten: the CSV carries plain addresses | — |
| form fields' `value` attributes (`student_edit.php` inputs) | **not** rewritten | — |

An address typed without a domain dot (`<local>@<word>`, 9 consultation contacts on 29 Sep) is not obfuscated as text (only its mailto `href` is), so it is kept exactly as the page shows it.

**The decoding** (`parsers._cf_address(hexstr)`, `parsers.py:24-39`): the first byte of HEX is the key; each following byte XOR the key is one byte of the UTF-8 address. Worked (synthetic) example: `422302206c212d` -> key `0x42`, bytes `23 02 20 6c 21 2d` -> `a@b.co`. The result is `""` (not an address) when HEX is shorter than 4 characters, of odd length, not hex, not UTF-8, has no `@`, or holds a space or control character (a mailto link's `?subject=` query is URL-encoded, so it has none either).

**`decode_cf_emails(node) -> node`** (`parsers.py:64-97`; `_CF_CLASS = "__cf_email__"`, `_CF_LINK = "/cdn-cgi/l/email-protection#"`, `parsers.py:19-21`; the element test `_is_cf_email`, `parsers.py:42-44`): puts back, in place, every hidden address in a parsed page or tag, as a browser shows it:
* an element with class `__cf_email__` and `data-cfemail` (the a or span form) becomes the address as **plain text joined to the text on either side of it** (`_put_text`, `parsers.py:47-61`), so `get_text(strip=True)` reads `"Email: <address>"`, not `"Email:<address>"`;
* a link to `/cdn-cgi/l/email-protection#HEX` gets `href="mailto:<address>"` and keeps its own text (a span form inside it becomes the address);
* an element whose HEX is empty or malformed is **left exactly as served** (its text still the stand-in; see "stand-ins" below); `value` attributes are never touched; nothing is fetched; calling it twice is calling it once.

**The rule that keeps it complete:** it is called once, right after the soup is built and before any `get_text`. Every `BeautifulSoup(` in `src\` is written `decode_cf_emails(BeautifulSoup(`, pinned by `tests\test_cloud_cf_email.py::test_every_page_parse_in_src_decodes_right_after_building_its_soup` (13 in `parsers.py`: login, `parse_tables`, `parse_dashboard_metrics`, the dashboard, `students.php`, `progress.php`, three consultation readers, pending, window applications, `consult_performance.php`, calendar; 2 in `client.py`: `get_student_full_profile` and `_profile_fields`; 1 in `ask.py`: `dashboard_facts`; 1 in `verified_docs.py`). The old partial decoder of `c17d887` (`_cf_email` / `_decode_cf_emails`: the span form inside `.cr-name` only) was replaced by `9ead47d`; the performance parser's last calls to it went at the release merge `e5e532e`, which also raised the pinned count from 12 to 13.

**Stand-ins that cannot be decoded are never published as an address:**
* `students.php` name: `.stu-name` text with `_EMAIL_HIDDEN_RE = r"\[email\s*protected\]"` removed (`parsers.py:327`); the no-`.stu-name` fallback now also skips a line that is an address (`_EMAIL_RE = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"`, `parsers.py:329`), so the address line is never taken for the name;
* `consult_requests.php` contact and details: `_without_hidden_email(text)` (`parsers.py:707-710`, `_EMAIL_HIDDEN_GAP_RE`, `parsers.py:328`) drops the stand-in from a longer text (`"01700000000 [email protected]"` -> `"01700000000"`); the old strip matched only an ASCII space, Cloudflare writes `&#160;`;
* Supabase records: `src\cloud\records.py:206-207` `FILLER_WORDS` holds `"emailprotected"`, so `records.is_filler(value, field)` (`records.py:230-239`) treats a whole cell that reads `[email protected]` (any spacing or case) as **no value**: it is blanked and named in `data.blank_on_portal` (e.g. `"details.Email"`, `"name"`); a consultant whose name is a stand-in gets no `consultant_performance` record and the read is not complete ([13 §6](13_SUPABASE_PUBLISHING.md));
* `/sendmail`: `_pick_student_email` (`telegram_bot.py:1289-1309`) never takes the stand-in as an address.

Before the fix, the stand-in was the whole value of `details.Email` in all 333 student records and in 1,005 of 1,014 consultation contacts of the dry-run payloads, and the bot's own `/inquiries` log showed it for a request whose name is an address in any markup but the span form. After it: 0 stand-ins in 657,652 scanned strings of dry run 3, and 0 in Supabase after the real backfill (postcheck of 30 Sep).

---

## 2. The read-only rules

### 2.1 What the code actually does (verified in the logs)

* **Only one POST to the portal exists in the whole bot: the login** (`client.py:184`). `hangeul_bot.log` (27 Sep 11:46 to 29 Sep 05:11, the bot process only; subprocess jobs log to `hangeul_sync.log`) shows GETs of `student_edit.php` (2268), `students.php` (258: 107 bare, 150 `?pg=N`, 1 `?status=pending`), `index.php`, `consult_requests.php`, `login.php`, `view_doc.php`, `calendar.php`, `window_applications.php`, and exactly one POST URL: `https://hangeul.com.bd/admin/login.php` (10 times). Since 30 Sep it also GETs `consult_performance.php?period=today|month` (the first live one in the log: 30 Sep 14:58, `?period=month`).
* The one-time Supabase backfill's network guard (dry run 3, 29 Sep) counted `students.php` 13, `progress.php` 333, `consult_requests.php` 65, `index.php` 1, `calendar.php` 1, `window_applications.php` 1 (all GET), `login.php` 2 GET and 2 POST, nothing blocked. The hourly full picture reads, GET only: every page of `students.php`, every page of `students.php?status=pending`, `consult_requests.php` for yesterday and today and `?status=file_opened`, `window_applications.php?status=under_review`, `index.php`, `calendar.php`, `consult_performance.php?period=today` and `?period=month` (`src\cloud\full_picture.py:95-119`).
* The only other non-GET requests the bot makes go **elsewhere, never to the portal**: Telegram's Bot API (`getUpdates`, `sendMessage`...), Gmail SMTP for an approved `/sendmail`, and the Supabase publisher's `POST /rest/v1/hg_runs`, `PATCH /rest/v1/hg_runs?id=eq.<n>` and `POST /rest/v1/rpc/hg_sync` to `SUPABASE_URL` (`src\cloud\publish.py:409`, `:442`, `:780`; [13](13_SUPABASE_PUBLISHING.md)).
* The pages the bot reads are full of mutation forms, all `method="POST"`, that it **reads but never submits**: on `students.php` the `verify_payment` form (`inl-form`, with a JavaScript prompt for amount, account and date), the stage form (`stg-form`), the intake-transfer form (`xp-card xfer`, which asks for an admin password), the delete buttons (`showDel(uid, name)`), the document review forms (`doc_status`, `reason_*`); on `consult_requests.php` three POST forms per row (remarks textarea, `set_status` select, delete: 1500 forms on the 500-row page); on `calendar.php` 43 POST forms (`rm-done` "Done/Complete" buttons with hidden `_csrf` + `id`, edit, delete); on `student_edit.php` the one POST profile form (hidden `_csrf`, `id`, `save`). The parsers only read text and attributes out of them (e.g. `_profile_fields` skips `_csrf`, password, submit and button inputs; the consultation reader takes the rows' hidden `id` as the request's id). `consult_performance.php` has one **GET** form, the Custom range (`form.pf-range`): the bot never submits it either (section 3.10).
* No portal AI feature is ever called, and `signed_students.php` is never requested (it appears only in a docstring, `progress_builder.py:225`).
* Tests enforce it: the synthetic portal fixture raises `AssertionError("the portal is read-only: <METHOD> <path>")` on any non-GET (`tests\test_foundation.py:109-122`, the raise at `:119`).
* Findings are reported, never corrected: the passport watcher's alert ends with `_(Strict Read-Only Alert: Please update in admin portal manually if required)_` and gives a `student_edit.php?id=<uid>` link for a human.

### 2.2 The guardrails file, rule by rule

File: `C:\Hangeul\BOT\.agents\rules\hangeul_operational_guardrails.md` (front matter `trigger: always_on`; present since the baseline commit `366dec0`, i.e. written by the owner before this work). Summary of every rule:

| # | Rule | How the code honours it |
|---|---|---|
| 1 | **Absolute read-only.** Never POST/PUT/DELETE or automate edits to `student_edit.php` or any portal mutation endpoint. Only GET for scraping, auditing, cross-checking and reports. Discrepancies are reported in audit tables, never auto-corrected without explicit permission. | One POST to the portal (login). Watcher alerts link to the edit page for staff. The Supabase copy is written to Supabase, never back to the portal. |
| 2 | **Metric decoupling.** Pending payments = `students.php?status=pending` only; window applications under review = `window_applications.php` (or the dashboard) only. Never sum them into one "pending" figure; always report separately. (The file's "Currently 0" / "Currently 2" figures are stale: on 28 Sep the tiles read Pending payment 2, Under review 0.) | Two separate lines everywhere, each with the note "never added together" (`brief.section_portal`, `ask.answer_pending`, `ask.answer_window_review`, `/stats`). The LLM summary prompt forbids combining them. In Supabase they are two kinds (`pending_payment`, `window_application`). |
| 3 | **Verified-student audit standard.** Capture name and program; amount and method (bKash, Bank Transfer, Cash); counselor and verification timestamp; document status against the passport scan and its MRZ; verdict class `100% Match`, `Typo / Discrepancy`, `Pending Document` (e.g. "WILL APPLY"), or `Invalid Document`. | `/verified` and the cross-check cards show exactly these fields; OCR statuses `MATCH`, `TYPO`, `DISCREPANCY`, `CHECK_BY_EYE`, `MISSING_DOCUMENT`, `MRZ_UNREADABLE`... (`ocr_validator.py`). |
| 4 | **Calendar and deadlines.** Parse both today's active items (with progress and days left) and the upcoming 45-day timeline from `calendar.php`. | `parse_calendar_events` reads both; `ask.calendar_items` merges them with the page's `var EV` list. |
| 5 | **Live auditing, zero stale data.** Audits, cross-checks, verification and document inspection always query the live portal by GET (`students.php`, `student_edit.php`, `view_doc.php`), never static registries, hard-coded dictionaries or cached records; OCR + MRZ checksum in real time; the audit reflects the exact current state. | The hard-coded `AUDIT_REGISTRY` of 10 Sep and the static `/passports` text were deleted (`40da0e6`). A scan is re-downloaded unless this exact upload (file name carries the upload epoch) is already saved. Supabase is a *copy* for Jeannie; no command answers from it. |
| 6 | **Scope: `students.php` ("All Students") only; exclude `signed_students.php`.** Signed students are finalised contracts and out of scope. `/crosscheck`, `/passports`, `/verified`, `/admitted` and every watcher source only from `students.php` and `student_edit.php?id=...`. | All readers use `students.php` (list, `?export=csv`, filters) and its profile/progress/doc endpoints. |
| 7 | **No AI or actions on the portal.** Never run `ask_ai.php`, `ai_training.php`, `team_assistant.php`; never press a button or submit a form (other than the login). Portal access is read-only GETs that fetch data: `students.php?export=csv`, the list pages, `download_docs.php` ZIPs. All analysis (cross-checks, OCR, MRZ, reports) runs only on local copies (the file still names the old path `E:\VERIFIED STUDENT DOCUMENTS`; on this PC it is `C:\Hangeul\VERIFIED STUDENT DOCUMENTS`, `settings.docs_root()`). | The bot also GETs `index.php`, `consult_requests.php`, `calendar.php`, `window_applications.php`, `progress.php`, `student_edit.php`, `view_doc.php` and (since 30 Sep) `consult_performance.php` through its own period links: all read-only data pages, which the owner accepted as within the rule's intent ("read-only (GET only, plus the login POST). No forms, no AI features, never signed_students.php" is the standing instruction repeated in the second session). The owner himself named `consult_performance.php` on 30 Sep. |

`HANDOFF.md` section 1 restates it: "The portal is read-only. One POST exists in the entire codebase — login.php ... Findings are reported; corrections are made by staff on the portal by hand", and adds that one head-of-branch record on the portal is excluded from all document checks.

### 2.3 Caveats a rebuild must fix

* The REST API (uvicorn on `0.0.0.0:8000`, `src\api\main.py`, CORS `*`, no authentication) exposes `POST /api/crawler/parse-page`, which GETs **any** portal path given (`crawl_page`), so it could fetch `signed_students.php` or an AI page if asked; and `POST /api/auth/login` logs in with caller-supplied credentials. Nothing in the bot calls these. Since `9ead47d` its `parse_tables` / `parse_dashboard_metrics` return decoded addresses too, which makes the unauthenticated API a way to read student e-mails. Put an allow-list of pages in `crawl_page` and bind the API to `127.0.0.1` in a rebuild.
* A GET can still have side effects on a badly designed server; the bot never GETs URLs that look like actions (`?delete=`, `?approve=`...), and never a filter form it was not told to use (the Custom range of `consult_performance.php`). Keep an allow-list of read-only pages and parameters.

---

## 3. Page by page

### 3.1 `login.php`

| | |
|---|---|
| URL | `GET https://hangeul.com.bd/admin/login.php` then `POST` the same URL |
| Code | `get_login_page()` `client.py:124-148`, `login(username=None, password=None)` `client.py:150-200` (the POST at `:184`), `extract_csrf_token(html)` `parsers.py:114-134` |
| CSRF | first of: `<input name="_csrf" value=...>`; then inputs named `csrf_token`, `token`, `_token`, `csrf`; then `<meta name="csrf-token" content=...>`. None -> `{"success": False, "error": "Could not extract CSRF token from login page"}` |
| POST body (form-encoded) | `{"_csrf": <token>, "username": <HANGEUL_USERNAME>, "password": <HANGEUL_PASSWORD>}` (values in `secrets/bot.env`) |
| Success test | the response after redirects does **not** end on `login.php`. Still on `login.php` -> `{"success": False, "error": "the portal refused the login (wrong username or password?)"}`, whatever the page says. A good login redirects to `index.php` (one extra GET, seen in the request log of every fresh session) |
| Session | the PHP session cookie lives in the `httpx.AsyncClient` cookie jar; `is_authenticated` is a local flag |
| Result dict | `{"success": True, "status_code", "redirected_url", "message": "Authentication successful"}` or `{"success": False, "error": why, "unreachable": True when the portal did not answer}` |

### 3.2 `index.php` (dashboard)

| | |
|---|---|
| URL | `GET index.php` (no params), timeout 30 s |
| Readers | `get_dashboard()` (`client.py:202-212`) -> `parse_hangeul_live_dashboard(html)` (`parsers.py:269-310`); `ask._dashboard()` (`ask.py:770-776`) -> `ask.dashboard_facts(html)` (`ask.py:683-714`); the backfill's and full picture's `collect_dashboard` (`backfill.py:265-277`, `dashboard_facts` again) |
| `get_dashboard` failure | never raises: returns `{"error": why}`; callers print "not available" |

**Structure (28 Sep 2026):** two sections, each `<div class="dash-sec">` with the title in `.ds-t` (inside `.ds-txt`), followed by a `<div class="stats-row">` of tiles. A tile is `<a class="stat-card kpi" href="...">` containing `.stat-num` (the figure) and `.stat-lbl` (the label), sometimes wrapped in `.kpi-txt`. Then cards: `<section class="card">` with `.card-title` (an `<h2>` inside `.card-head`).

| Section (`.ds-t`) | Tile label (`.stat-lbl`) | href | Value 28 Sep | Summary key (`_DASHBOARD_TILES`, `parsers.py:217-229`) |
|---|---|---|---|---|
| Admissions flow | Open windows | `admission_windows.php?status=active` | 3 | `open_windows` |
| Admissions flow | Draft windows | `admission_windows.php?status=draft` | 0 | `draft_windows` |
| Admissions flow | Submitted apps | `window_applications.php?status=submitted` | 0 | `submitted_window_apps` |
| Admissions flow | Under review | `window_applications.php?status=under_review` | 0 | `window_apps_under_review` |
| Admissions flow | **Docs to review** | `review_queue.php` | 44 | `window_docs_to_review` |
| Admissions flow | Accepted | `window_applications.php?status=accepted` | 3 | `window_apps_accepted` (accepted window applications, **not visas**) |
| Direct / legacy pipeline | Total students | `students.php` | 330 | `total_students` (also `total_applicants`) |
| Direct / legacy pipeline | Pending payment | `students.php?status=pending` | 2 | `pending_payment` |
| Direct / legacy pipeline | Verified | `students.php?status=verified` | 328 | `verified_students` |
| Direct / legacy pipeline | **Docs to review** | `students.php?filter_docs=unverified` | 11 | `students_docs_to_review` (also `pending_document_verification`) |
| Direct / legacy pipeline | Admitted | `students.php?stage=Admitted+%2F+Completed` | 0 | `admitted` |

**How tiles are parsed** (`_dashboard_tiles`, `parsers.py:232-254`): for every `.stat-card` with both `.stat-num` and `.stat-lbl` -> `{"group": the previous sibling .dash-sec's .ds-t text, "label", "value": int or None, "text": the figure as printed, "href": the card's own href or its parent <a>'s}`. `_int_or_none` (`parsers.py:109-112`) accepts only `\d[\d,]*` ("1,234" -> 1234). Older layout fallback (no `.stat-card`): `.stats-row` with `.stat-num`/`.stat-lbl` zipped in order, no href.

**Label matching** (`_label_key`, `parsers.py:100-106`): lower-case, non-alphanumerics to spaces, and a plural last word loses its `s` (not `ss`/`us`/`is`), so "Pending payment", "pending  Payments" and "Pending-payment" are one key. The same function matches the Consultant Performance page's headers and period labels (section 3.10).

**The two "Docs to review" tiles** (`_tile_value`, `parsers.py:257-266`): when a label is shared by two summary keys, the tile's href decides: `review_queue` -> window documents, `students.php` -> student documents. If no single tile matches, the value is `None` (never a guess). In `live_stats` (label -> text), a label that appears twice gets its group appended: `"Docs to review (Admissions flow)"`, `"Docs to review (Direct / legacy pipeline)"`.

`parse_hangeul_live_dashboard` returns `{"status": "success", "portal": "...", "last_synced": iso, "summary": {key: int or None}, "live_stats": {label: text}, "tiles": [...], "recent_activity": up to 5 texts of <a href*="window_application_view">}`.

**Cards read by `ask.dashboard_facts`** (`ask.py:683-714`, card names `_CARDS`, `ask.py:671`; each figure becomes `Fact(group, label, value, text, note)`, `ask.py:657-668`):

| Card (`.card-title` starts with) | Items | Parsed as |
|---|---|---|
| At a glance | `.gl` with `.gl-v` (value) and `.gl-l` (label): Applied this week 25, Applied this month 114, Docs approved 145, Total docs 170 | `Fact("At a glance", label, value)` |
| Needs attention | `a.wf-item` with `.wf-info strong` (label), `.wf-info span` (note), `.wf-count`: Payment verification 2 (`students.php?status=pending`), Document review 11 (`?filter_docs=unverified`), Rejected documents 14 (`?filter_docs=rejected`), Missing documents 158 (`?source=direct&filter_docs=missing`) | `Fact(card, label, value, text, note)` |
| Application pipeline | `a.wf-item.pipe-row` with `.pipe-top strong` (stage) and `.pipe-c` (count); 10 rows, hrefs `students.php?stage=<Stage>` | `Fact("Application pipeline", stage, n)` |
| Applications by program | `.wf-item` per program (KLP, Bachelor's, EAP, Master's) | as Needs attention |
| Top universities | `.wf-item` per university (6 on 28 Sep) | as Needs attention |

Cards on the page that the bot ignores: "Partner & University Messages", "Reminders for today", "Upcoming · next 7 days", "Expiring documents", "Recent window activity", "Recent applications". On 30 Sep the backfill made 39 `dashboard_fact` records of the tiles and cards.

The dashboard has **no visa figure**; a question about visas is answered with the pipeline stages VIN Application / Embassy Submission / Visa Result / Admitted / Completed and the Accepted tile, each labelled for what it is (`ask._dashboard_answer`, `ask.py:779-867`, topic `visa`).

### 3.3 `students.php` (the All Students list)

| | |
|---|---|
| URL | `GET students.php`, 50 students a page, newest application first; later pages `?pg=2..N`; every filter param is kept on every page |
| Readers | `read_student_pages(params=None, *, all_pages=True) -> List[str]` (`client.py:454-499`); `read_students(params=None, *, all_pages=True) -> List[dict]` (`client.py:501-520`); `parse_students_page(html)` (`parsers.py:413-483`) |
| Size | ~1 MB per page (~950 KB); parsing runs in `asyncio.to_thread` |
| Totals | 330 students on 28 Sep (7 pages), 340 on 30 Sep (backfill) |

**Query parameters seen and used**

| Param | Values | Used by |
|---|---|---|
| `pg` | 2..N (page 1 has no `pg`) | every all-pages read |
| `status` | `pending`, `verified`, `rejected` (payment status; the portal **ignores** `status=admitted`, it returns the whole list) | `?status=pending`: pending payments |
| `stage` | `Application Received`, `Payment Verified`, `Documents Under Review`, `Documents Verified`, `University Applied`, `Admission & Tuition`, `VIN Application`, `Embassy Submission`, `Visa Result`, `Admitted / Completed`, `Payment Rejected`, `Documents Requested` | only as the dashboard tile's link (the bot filters stages in code) |
| `source` | `direct` (partner students are "B2B") | `?source=direct&filter_docs=verified` (document download list) |
| `filter_docs` | `verified`, `unverified`, `rejected`, `missing` | the sync's download list |
| `prog` | the program name (e.g. `KOREAN LANGUAGE PROGRAM (KLP)`) | root script `audit_program.py` |
| `q` | free search; its placeholder reads "Name, email, ID, passport, phone, consultant..." (it does **not** search universities or programs, so `/admitted` filters in code) | not used by commands |
| `uni`, `vin`, `vin_status`, `visa`, `consultant`, `intake`, `issue` | the other selects of the `<form method="GET" class="sf">` search form | not used |
| `export` | `csv` | the CSV export (below) |

**Pager:** `<div class="stu-pager"><span>Page 1 of 7 · 330 students</span> <a class="btn-sm btn-outline" href="?pg=2">Next ...</a></div>`. Regex `_PAGER_RE = r"Page\s+(\d+)\s+of\s+(\d+)(?:\s*·\s*([\d,]+)\s+students?)?"` (case-insensitive, `parsers.py:325`) -> `student_pager(html) -> {"page", "pages", "total"}` (`parsers.py:348-355`), each `None` when absent (a one-page list has no pager).

**All-pages loop** (`read_student_pages`):
* `STUDENTS_PER_PAGE = 50`, `MAX_STUDENT_PAGES = 40` (`client.py:44-45`).
* Page 1: if there is no pager but 50 or more rows -> `PortalUnavailable("students.php shows N students but no 'Page 1 of N', so its later pages cannot be found")`.
* Each page: no `<table` -> `PortalUnavailable("students.php has no student table ...")`; the pager's page number must be the page asked for (else "the list changed while it was read"); `pages = max(pages, pager.pages)` so a page count that grows while reading is followed; more than 40 pages -> error.
* uids are collected by the cheap regex `_UID_RE = r"student_edit\.php\?id=(\d+)"` (`parsers.py:326`, `student_uids`, `parsers.py:358-361`); at the end, fewer unique uids than the pager's total -> `PortalUnavailable("the student list says 330 students but its 7 pages hold N ...")`.
* `read_students` parses each page and de-duplicates by `uid` (a row can shift onto the next page when a student registers during the read), falling back to `("row", student_id, name, applied_date)`.

**Table:** `<table class="tbl stu-tbl">`, header `<thead><tr>` cells: `''` (`th.c-chk`, bulk checkbox), `SL`, `Student`, `University`, `Program · Intake`, `Docs`, `Payment`, `Stage · Applied`, `''` (`th.c-exp`). Columns are found **by header name** (`_STUDENT_COLUMNS`, `parsers.py:321-323`): each key takes the first unused header whose `_label_key` starts with its word: `sl`<-"sl", `student`<-"student", `university`<-"universit", `program`<-"program", `docs`<-"doc", `payment`<-"payment", `stage`<-"stage". Required (`_REQUIRED_STUDENT_COLUMNS`, `parsers.py:324`): `sl`, `student`, `program`, `stage`; missing -> `StudentListLayoutError("the student table's header has no ... column (it reads [...])")`.

**Each student is two `<tr>`s:**

1. The list row `<tr class="stu-row" onclick="toggleExp('exp<app_id>')">` (note: the expand id is the application id, not the user id). Recognised as a row when it has as many direct cells as the header and its SL cell is all digits. Cells (`_student_row`, `parsers.py:499-533`):
   * `td.c-chk`: `<input type="checkbox" class="bulk-chk" data-uid=... data-name=... data-passport=...>` (not read).
   * `td.c-sl`: the SL number.
   * `td.c-stu`: `<strong class="pii stu-name">` (name), `<div class="pii stu-mail">` holding Cloudflare's `<a class="__cf_email__" data-cfemail="HEX">[email protected]</a>` (decoded to the address, section 1.4), `<div class="stu-tags"><span class="stu-sid">HNG-2026-<n></span></div>`. Name = `.stu-name` text with any stand-in removed; without `.stu-name`, the first line that is neither an HNG id nor an address. HNG id by `_HNG_RE = r"HNG-\d{4}-\d+"` (`parsers.py:330`).
   * `td.c-uni`: `<div class="stu-uni">` (the university itself) plus zero or more `.upr` lines "Applied: <University> · <Program>" (other applications, kept as the `applications` list, not the university).
   * `td.c-prog`: the program as own text, then `<div class="stu-sub" title="Intake">` MARCH 2027 (`_main_and_sub`, `parsers.py:486-496`: own text vs `.stu-sub`).
   * `td.c-docs`, `td.c-pay`: text (`<span class="badge badge-warn">Pending</span>` etc.); `—` (`.stu-dash`) means empty.
   * `td.c-stage`: the stage as own text ("Application Received") and `<div class="stu-sub" title="Applied on">28 Sep 2026</div>`.
2. The details row `<tr class="xp-row"><td colspan="9" class="xp-td"><div class="expand-panel" id="exp<app_id>">...` (`_student_details`, `parsers.py:364-410`):
   * `.det-item` pairs `<label>` / `<span>` (first of each label kept; `—` becomes `""`). Labels on 28 Sep (50): Full Name, DOB, Gender, Mobile, District, Address, Father, Mother, SSC, HSC, College, Passport, Surname, Given Name, Email, Guardian WhatsApp, Father Occupation, Study Status, SSC Year/GPA/Group/School, HSC Year/GPA/Group/College, University, Subject, Degree, CGPA, Program, Preferred University, Final University, Intake, Field, Korean Level, IELTS/TOEFL, Passport Status, Passport Expiry, Passport No, Applied to Korea Before, Visa Rejection History, Sponsor, Sponsor Occupation, Bank Solvency, How Heard, Consultant, Payment Status, Payment Amount, Applied On. The "Email" span is Cloudflare-obfuscated (decoded).
   * The portal types **filler words** for "no value" in many details (`N/A`, `None`, `NA`, `--`, `PENDING` in the passport number...): the bot's replies show them as the page does; the Supabase records blank them and list them in `data.blank_on_portal` (found by dry run 1, fixed in `752cd53`; [13](13_SUPABASE_PUBLISHING.md)).
   * `uid`: from `student_edit.php?id=N`, else `showDel(N`, else `progress.php?uid=N`.
   * `files`: every `view_doc.php?f=<file>` in the row, de-duplicated in order (on the list page only `passport_...` and `receipt_...`).
   * Payment facts `<div class="pay-facts">`: `<a class="pf receipt" href="view_doc.php?f=receipt_<uid>_<epoch>.jpg">`, `<span class="pf paid">Paid: 20,000.00 BDT</span>`, `<span class="pf method">Cash</span>` (Cash, bKash, Bank), `<span class="pf verified">Verified income: 20,000.00 BDT</span>`. Read by class (`pf(".pf.paid", "Paid:")` etc.); text regexes `_PAID_RE` / `_INCOME_RE` (`parsers.py:333-334`) only as a fallback when the chips are absent.
   * The verification stamp `<div class="pf-by"><i class="fas fa-user-check"></i> <span>Payment verified by <strong>NAME</strong> · 27 Sep, 17:19</span></div>`: the verifier is the `<strong>`; the stamp is matched **inside the `.pf-by` element** (only when a row has no `.pf-by` at all does the parser fall back to the whole details-row text) with `_VERIFIED_BY_RE = rf"Payment verified by\s+([^·\n]{1,80}?)\s*·\s*({_STAMP_TEXT})"`, `_STAMP_TEXT = r"\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?(?:,\s*\d{1,2}:\d{2})?"` (`parsers.py:331-332`). **The stamp has no year.** `verified_line` records whether the row has a "Payment verified by" line at all, so an unreadable stamp is told apart from no stamp.
   * `applied_on`: the "Applied On" det-item ("27 Sep 2026, 17:16").
   * The row also holds the stage `<select name="stage">` and the transfer-intake select (`SEPTEMBER 2027`...): their option words are never read as the student's stage or as a date (this was a real bug: "2027 SEPTEMBER" matched "27 Sep").
3. Other rows: `tr.empty-row` or a one-cell row saying "No students found" -> `empty`; any other non-blank row that cannot be read -> `StudentListLayoutError("the student table has N row(s) the parser cannot read")`.

**Student record shape** (`parse_students_page` docstring): `uid`, `sl`, `student_id` (= `id`, the HNG id or `""`), `student_name`, `target_university`, `applications` (list), `program`, `target_intake`, `docs_status`, `payment_status`, `status` (= the stage), `applied_date`, `details` (dict), `files` (list), `details_text`, `verified_line` (bool), `verified_by`, `verified_stamp` ("27 Sep, 17:19"), `paid`, `method`, `verified_income`, `applied_on`. Nothing is filled in: absent is `""`.

**Pick-by-stamp** (`parsers.verification(student, day)`, `parsers.py:814-844`): `parse_stamp(verified_stamp)`; `stamp_on_day(stamp, day, applied)`: whole day and month tokens must equal the day's; a stamp with a year must have the day's year; a yearless stamp counts only if the student applied on or before `day`. Returns `{"student_id", "uid", "name", "program", "amount" (verified income, else paid), "paid", "verified_income", "method", "verified_by", "verified_time"}`. `payment_text(v)` (`parsers.py:851-859`) shows `"Paid 8,160.00 BDT bKash (verified income 8,000.00 BDT)"` when the two differ, else `"8,000.00 BDT bKash"`.

**The yearless-stamp rule** (`src\dates.py:245-259` `yearless_day_problem(day, today)`): a day in the future -> "a date in the future"; a day whose day and month have come round again since (`day.replace(year+1) <= today`) -> "the portal writes verification times without a year, so 27 Sep 2025 cannot be told apart from 27 Sep 2026". Every verified/cross-check/brief caller asks this first and says "not available (...)". The Supabase `verification` kind is complete only inside the same one-year window (`records.verification_window`).

**Stamp guard** (`client.read_verified_students`, `client.py:522-545`, and `telegram_bot._stamp_guard`, `telegram_bot.py:1555-1568`; the Supabase copy uses the same rule, `command_hooks.stamps_readable`): student rows but no "Payment verified by" line on any of them -> `PortalUnavailable("... (layout not recognised)")`; any line whose stamp `parse_stamp` cannot read -> `PortalUnavailable`. On 28 Sep, 322 of 330 rows had a stamp; on 30 Sep the backfill published 333 `verification` records (57 stamp days) from the 340 students.

**Admitted** (`get_admitted_students(query=None)`, `client.py:236-267`): read `index.php`, find the tile whose letters-only label is `admitted` and whose href contains `students.php`, take its `stage` query value (`Admitted / Completed`; fallback constant `ADMITTED_STAGE`, `parsers.py:317`), then read every page and keep students whose `status` has the same `_label_key`. The query is matched in code by `student_matches` (`parsers.py:549-558`: name, HNG id, university, program, intake, application lines). Returns `{"students", "admitted", "checked", "stage", "tile", "query", "listed" (every student read: the whole list), "dashboard" (the `get_dashboard()` read, None in mock mode)}`; the last two exist since the Supabase layer, so `/admitted` can publish the whole list and the tiles it read.

**`?status=pending`**:
* `read_pending_payments()` (`client.py:553-559`) fetches `students.php?status=pending` (page 1 only) -> `parse_pending_payments(html)` (`parsers.py:890-917`) -> `{"count", "listed", "badge"}`. `badge` is the sidebar link on every page, `<a href="students.php?status=pending">Pending Payments <span class="badge">N</span></a>`, read by `r"pending\s+payments?\D{0,5}(\d+)"`; `listed` counts rows with a digit SL cell (header-found). Badge wins; a paged list with no badge returns `None` (not counted).
* `ask.answer_pending()` (`ask.py:882-934`) and the Supabase `collect_pending` (`backfill.py:215-239`) read **every** page of `{"status": "pending"}` and count only rows whose own Payment cell (letters only) is `pending`, then compare with the badge (1 on 30 Sep).

**`?export=csv`** (the whole list in one GET, all pages; 63 columns, UTF-8 with BOM, decode `utf-8-sig`; **plain e-mail addresses**, Cloudflare does not rewrite it): `Source, Partner Code, Partner Company, Student ID, Full Name, Surname, Given Name, Email, Mobile, Guardian WhatsApp, DOB, Gender, District, Address, Father, Mother, Study Status, SSC Year, SSC GPA, SSC Group, SSC School, HSC Year, HSC GPA, HSC Group, HSC College, Previous University, Subject, Degree, CGPA, Program, Preferred University, Final University, Intake, Field, Korean Level, IELTS/TOEFL, Passport Status, Passport No, Passport Issue Date, Passport Expiry, Applied to Korea Before, Visa Rejection History, Sponsor, Sponsor Occupation, Bank Certificate, How Heard, Questions / Notes, Consultant, Payment Status, Payment Amount, Payment Method, Verified Amount, Verified By, Current Stage, Current Status, Progress %, VIN Required, VIN App, VIN Status, Visa Result, Issue/Remarks, Next Step, Applied On`.
* Used by the progress sheets (`progress_builder.fetch_all_students`, Direct students only: `Source` = `direct`), `/stage` (program and intake), `/missing` (portal record index), `/sendmail` (student lookup), and the Supabase `student_export` kind (`backfill.collect_export`, `backfill.py:107-122`: complete only when it holds at least 90 % of the list's own count, as the export has no pager).
* **Not trusted:** `Current Stage`, `Current Status`, `Progress %` (stale for many students: 64 of 329 statuses and 89 of 329 % disagreed with the progress pages on 28 Sep). `Passport Issue Date` was added in Sep 2026; before that the issue date existed only on the edit page. Two students' CSV addresses differed from their list-page addresses on 29 Sep (so `/sendmail`'s CSV path and its list-page fallback can pick different addresses for them).

### 3.4 `student_edit.php?id=N` (one student's profile)

| | |
|---|---|
| URL | `GET student_edit.php?id=<uid>` (uid = portal user id, the `N` of the list row's Edit link) |
| Readers | `audit_student_passport` (`client.py:630-713`) via `fetch_html(f"student_edit.php?id={sid}", timeout=30)` -> `_profile_fields(html)` (`client.py:716-736`); `passport_issue._fetch_async` via `fetch_html("student_edit.php", params={"id": uid}, timeout=60)` + regex; `get_student_full_profile` (legacy) |
| Structure | one `<form method="post">` with hidden `_csrf`, `id`, `save`; inputs `name`, `email`, `phone`, `full_name`, `surname`, `given_name`, `dob` (date), `gender`, `mobile`, `guardian_wa`, `district`, `address`, `father_name`, `mother_name`, `sponsor`, `sponsor_occ`, `ssc_*`, `hsc_*`, `university`, `subject`, `degree`, `cgpa`, `degree_year`, `korean_level`, `ielts`, selects `program`, `preferred_uni`, `final_university_name`, `intake`, inputs `consultant`, `passport_status`, `passport_number`, `passport_issue_date` (date), `passport_expiry` (date), `bank_solvency_date`, `korea_before`, `visa_rejection`; a sidebar `sbFind` search |
| Parse | `{field name: value}`: an input's `value` (kept as the page has it: Cloudflare leaves `value` attributes alone), a textarea's text (decoded if Cloudflare hid an address in it), a select's `option[selected]` (never the text of all options); skips `_csrf`, password, submit, button; empty fields left out |
| Cache | the audit keeps the last profile per uid in `admin_client._profile_cache` (`client.py:660-662`); the Supabase hooks read it after an audit to publish a `student_profile` record (`command_hooks.profile_of`, `bot_jobs.profile_now`), never the legacy full-page read (which carries `_csrf`) |
| Guards | no `name`/`full_name` in the result -> `unchecked_result(sid, "student_edit.php?id=N shows no student profile")`; a failed read -> `unchecked_result(sid, "the student's profile (...) could not be read: <why>")` (status `PORTAL_UNREADABLE`, never a verdict about fields not read) |
| Issue date | `_ISSUE_RE = r'name="passport_issue_date"[^>]*value="([^"]*)"'` |

### 3.5 `view_doc.php?f=<file>` (an uploaded document)

| | |
|---|---|
| URL | `GET view_doc.php?f=passport_<uid>_<epoch>.<ext>` (also `receipt_<uid>_<epoch>.jpg`) |
| File naming | the portal puts the uid and the Unix upload time in every name, so a re-upload is a new name: the watcher keys scans by `uid\|file`, and `_UPLOAD_TIME_RE = r"passport_\d+_(\d{9,11})\b"` orders them (newest first; the same rule is copied in `src\cloud\bot_jobs.py:250-254`, pinned together by a test) |
| Reader | `audit_student_passport` via `portal_get(f"view_doc.php?f={doc_filename}", timeout=60)` |
| Name guard | `re.fullmatch(r"[A-Za-z0-9._-]+", name)` and no `..`, else "not one the bot can save" |
| Local copy | `C:\Hangeul\BOT\passports\<uid>_<file>` (never open these images: student data). A saved copy is reused only if it exists, is >= 1000 bytes and does not start with `<` (a saved login page). Written to `.<uid>_<file>.part` then `os.replace`d, re-checking after the GET so two audits never write one file |
| Content guards | body starts with `<` or has `<html` in its first 1000 bytes -> "the portal sent a web page instead of the passport scan"; <= 1000 bytes -> "only N bytes" (both `PORTAL_UNREADABLE`) |
| After | OCR + MRZ in `asyncio.to_thread(validate_passport_data, ...)` so the bot keeps answering Telegram |

`download_docs.php?uid=N&zip=1` (all of one student's documents as a ZIP, content-type must contain `zip`, timeout 300 s) is used only by the 15-minute sync (`verified_docs.py`), for students listed on `students.php?source=direct&filter_docs=verified` (rows found by their `download_docs.php?uid=` links; the set of `view_doc.php?f=` names in the row is the fingerprint stored in the local done-marker, so changed documents are fetched again). The same list, every page, is the Supabase `student_documents` kind (160 students on 30 Sep).

### 3.6 `consult_requests.php` (consultation requests / inquiries)

| | |
|---|---|
| URL | `GET consult_requests.php` with optional `status`, `from`, `to` (and `q`, `cons` in its form) |
| Readers | `read_consultation_view(params)` (`client.py:351-366`) -> `parsers.consultation_view(html)` (`parsers.py:671-704`); `read_consultation_totals()` (`client.py:368-380`); `read_consultation_day(day)` (`client.py:382-423`); the backfill's `_range_count(first, last)` and `oldest_consultation_day` (`backfill.py:154-175`) |
| Size | unfiltered ~2.1 MB (500 rows); one day ~110 KB; parsed in a worker thread |

**Structure (28 Sep 2026):**
* Status tabs `<nav class="cr-tabs" aria-label="Filter by status">`: `<a class="st-all on" href="?status=all">All <span class="n">999</span></a>`, `st-new` New 8, `st-no_answer` No Answer 154, `st-wrong_number` Wrong Number 40, `st-consulted` Consulted 791, `st-file_opened` File Opened 6. The open tab has class `on`. **The tab counts count every request the date filter lets through, whichever tab is open**; under a date filter the hrefs carry `&from=...&to=...`. (Proven again by the 29 Sep dry run: the days' listed counts add up to the range's `All` tab.) Tab values (the `status=` a tab links to): `all`, `new`, `no_answer`, `wrong_number`, `consulted`, `file_opened`.
* Search form `<form class="cr-search" method="get">`: hidden `status`, `q`, select `cons` (consultant), `<input type="date" name="from">`, `<input type="date" name="to">`. The form **echoes the filter it applied** in its `value`s.
* Caption `<b>500</b> requests · newest first` (regex `r"<b>\s*(\d[\d,]*)\s*</b>\s*requests?\s*·\s*newest first"`). **The list shows at most the newest 500 requests** (`CONSULT_LIST_LIMIT = 500`, `client.py:52`).
* Table `<table class="cr">`, header (7 columns, found by name by `_consult_columns`, `parsers.py:592-605`; rows by `_consultation_table_rows`, `parsers.py:718-781`, on the page decoded first, section 1.4):

| Header | Cell class | Inner classes read | Record key |
|---|---|---|---|
| Student | `td.c-stu` | `.cr-who` > `a.cr-name` (name; a name typed as an address is Cloudflare's span form, decoded), `.cr-contact` (`a.ph` phone, then the address as Cloudflare's **link form**, decoded; a stand-in that cannot be decoded is dropped by `_without_hidden_email`) | `name`, `contact` (`"<phone> <address>"`) |
| Consultant | `td.c-cons` | `.cr-cons` (assigned consultant; `—` -> `"Unassigned"`) | `consultant` |
| City & program | `td.c-loc` | `.cr-loc` > `.city`, `.prog`; `<details class="crd">` > `.crd-body` (`.kv` pairs: extra details; addresses in it decoded, stand-ins dropped) | `city`, `program` (`—` -> `""`), `details` |
| Received | `td.c-recv.cr-when` | `.d` ("28 Sep 2026"), `.t` ("10:15") | `received` ("28 Sep 2026 10:15"), `received_date` (`.d`) |
| Status | `td.c-st` | `.stbadge` (`<span class="dot"></span>Consulted`), optional `.cr-by` (title "Last updated by") | `status`, `handled_by` (`""` when absent, never the consultant) |
| Remarks | `td.c-rmk` | `textarea.rmk` (a POST form; only read) | `remarks` |
| Update status | `td.c-act` | `select.stsel name="set_status"`, delete button (POST forms; the column is skipped: header containing "update") | — |
| (the row's forms) | `form input[type="hidden"][name="id"]` | the request's own id, when every form of the row that has one agrees on one all-digit value, else `""` | `id` (since the Supabase layer: the `consultation` record's key, e.g. request 1078) |

Header words: `name`<-"student"/"name", `contact`<-"contact"/"phone", `city`<-"city", `program`<-"program", `consultant`<-"consultant", `details`<-"detail", `received`<-"received"/"date", `status`<-"status", `remarks`<-"remark". `name` and `status` are required, else no rows. The empty state is `<tr class="cr-empty-row"><td class="cr-empty">No consultation requests yet.</td></tr>` -> a real `[]`. The Details also hold filler words (`N/A`, `None`, `NA`, `Pending` inside longer text), kept as the page has them.

Statuses (`CONSULT_STATUSES`, `parsers.py:642`): `New`, `No Answer`, `Wrong Number`, `Consulted`, `File Opened`. "Done" = Consulted + File Opened.

**`consultation_view(html)` -> `{"rows": [...] or [] or None (rows present but unreadable), "tabs": {label: n} or None, "status": open tab value ("all", "file_opened"...), "from", "to" (echoed; "" none; None when there is no form), "listed": caption count or None}`.** `_consultation_tabs` (`parsers.py:645-668`) returns `(None, None)` if the nav is missing, has no `All` tab, or any `.n` is not a number.

**How the bot uses the date filter and the tabs now** (every use reads counts from the tabs, never from a row count of the capped list):

| Use | Query | Who | Checks |
|---|---|---|---|
| All-time totals | `?status=file_opened` (`CONSULT_TOTALS_VIEW`, `client.py:53`: the lightest tab, a handful of rows instead of 2 MB; its tabs still count every request) | `/inquiries*`, brief section 1, full picture hourly, backfill (`consultation_totals`) | tabs present, open tab is `file_opened`, no `from`/`to` echoed; else `PortalUnavailable` |
| One day | `?status=all&from=YYYY-MM-DD&to=YYYY-MM-DD` (the query the page's own tab links and GET form produce) | `/inquiries*`, `/consultations`, brief section 1; full picture: **yesterday and today** every hour; backfill: **every day** from the oldest request to today | the five checks below |
| A range's count | `?status=all&from=A&to=B`, the `All` tab only (`backfill._range_count`, `backfill.py:154-160`) | the backfill's search for the oldest request | the form must echo `from == A` and `to == B`, else `PortalUnavailable("consult_requests.php did not apply the date filter (layout not recognised)")` |
| The oldest request | a binary search over `_range_count(2015-01-01, mid)` (`oldest_consultation_day`, `backfill.py:163-175`; `CONSULT_FLOOR = date(2015, 1, 1)`, `backfill.py:55`; ~13 reads) | backfill only | a range count of 0 since the floor -> none |
| Unfiltered list (newest 500) | no params | only the legacy REST API reader (section 1.2) | none (known leftover) |

On 30 Sep the backfill found the oldest request on **11 Aug 2026** and read 51 days (11 Aug – 30 Sep) -> 1,034 requests, one `consultation` scope per day; the all-time `All` tab read 1,035 after request 1078 arrived at 22:12 Dhaka (postcheck).

**One day, in detail** (`read_consultation_day(day)`): `day = target_day(day)`; GET `?status=all&from=YYYY-MM-DD&to=YYYY-MM-DD`. Every check raises `PortalUnavailable`:
1. the form must echo `from == to == day` and the open tab must be `all` ("did not apply the date filter");
2. every row's `received_date` must parse (`parse_portal_date`) to `day`;
3. `listed` (caption) must equal the rows read;
4. rows must not exceed the `All` tab, and fewer rows than `All` is allowed only when the caption exists or the portal hit its 500 cap;
5. when complete (rows == All), `Counter(row statuses)` must equal the non-zero tab counts.
Returns `{"day", "counts" (the day's tab counts; "All" = received), "rows", "complete"}`. The figures shown are the **tab counts**; rows only give the "handled by" breakdown and the log. In Supabase a day's `consultation` scope is complete (may delete) only when `complete` is True; the `consultation_day` counts are complete only for the backfill's whole range.

### 3.7 `calendar.php` (reminders, timeline, event list)

| | |
|---|---|
| URL | `GET calendar.php` (no params; the page itself links `calendar.php?ym=2026-09&view=month&edit=<id>`) |
| Readers | `get_calendar_events()` (`client.py:570-590`) -> `parse_calendar_events(html)` (`parsers.py:1313-1350`); `ask.answer_calendar(q)` (`ask.py:1395-1411`) -> `fetch_html("calendar.php")` -> `ask.calendar_items(html, today)` (`ask.py:1243-1299`); the Supabase `collect_calendar` (`backfill.py:280-291`, `calendar_items` again: never a complete read, the page shows only this month and the next 45 days; 22 items on 30 Sep) |
| Size | ~200 KB |

**Structure (28 Sep 2026):** `.cal-layout`; cards `.cal-card` each with a heading `.sec-h`: "Reminders for today `<small>`· Monday, 28 Sep 2026 · 11 items`</small>`", "Completed · 1 item" (`.done-item`), "Upcoming · next 45 days"; an aside ("At a glance"); a pop-up `.rm-modal` that repeats today's reminders as `.rm-row` (**not read**, so nothing counts twice); a `<script>` with `var EV = [...]`, `var H`, `SIX`, `EDIT_MODE`, `EDIT_BASE`.

* **Reminder** `.rm-item` (11 on 28 Sep): icon `<span><i class="fas fa-truck-fast"></i></span>`, then a flex `<div>` holding `<a class="rm-title" href="calendar.php?ym=2026-09&view=month&edit=19">SEJONG DHL</a>`, a sub-line div `<span style="font-weight:700">DHL to send</span> · 26 Sep–28 Sep · 14:00 · Sejong University [· today]`, an optional progress div "64% of window elapsed · 4 days left", an optional note div ("EAP PROGRAM" or free text; an address in it is decoded); then a `<form method="post">` with hidden `_csrf`, `id` and a `button.rm-done` (never pressed).
  `_cal_reminder` (`parsers.py:1272-1294`) -> `{"id" (edit=N, else the form's hidden id), "title", "type", "date_range", "time", "where", "today" (bool), "progress", "days_left" (int from "N days left"), "program" (note if it matches `_CAL_PROGRAM_RE` program words), "note"}`. The sub-line is split on `·` (`_cal_sub`, `parsers.py:1232-1256`): `_CAL_RANGE_RE` for "26 Sep–28 Sep", `_CAL_TIME_RE` `\d{1,2}:\d{2}`, `"today"`, anything else -> `where`.
* **Upcoming row** `.ev-row` (15 on 28 Sep): `.li-date` (`.d` day, `.w` month), `.ev-ic`, `.ev-main` (`a.ev-title` edit link, `.ev-sub` "`<span>`Application period`</span>` · 01 Sep – 09 Oct 2026 · FAR EAST UNIVERSITY" or, with a start time, "21 Sep · `<b>`14:00`</b>` – 02 Oct 2026 · Jeonbuk National University", optional note div), `span.st` (classes `ok`/`soon`; text "Closes in 11 days", "Today", "In 7 days", "Opens in 9 days"), `.acts` (edit/done/delete). The time-then-end-date form is joined into a range by `_CAL_TIME_END_RE` (`parsers.py:1213`; "08 Oct · 14:00 – 23 Oct 2026" -> range "08 Oct – 23 Oct 2026", time 14:00).
  `_cal_upcoming` (`parsers.py:1297-1310`) -> `{"id", "date" ("1 Sep"), "type", "title", "university", "date_range", "program", "note", "status"}`.
* **`var EV = [...]`** (JSON, 18 events on 28 Sep, **the current month's events only**): each `{"id", "title", "type": "period" | "dhl", "uni", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "time", "done": 0|1, "notes", "link"}`. Read by `ask._ev_items` (`ask.py:1209-1236`) with `json.JSONDecoder().raw_decode` right after the `var EV =` match; types map to "Application period" / "DHL to send".

`parse_calendar_events` -> `{"today_reminders" (titled only), "upcoming_events", "layout_ok", "upcoming_ok", "skipped_untitled", "heading_count" (the "· N items")}`. `layout_ok` is True only if `.rm-item` entries were found **or** the card itself says none (`· 0 items`, or `_CAL_EMPTY_RE`, `parsers.py:1215-1216`: "No reminders", "nothing due", "all clear"...). A card with no recognisable entries and no "none" wording is a layout change -> "not available", never 0.

`ask.calendar_items` merges the three sources into `CalItem(title, kind, where, start, end, done, note, id)` (`ask.py:1097-1105`): EV items first (de-duplicated by id), then reminders and timeline rows are merged into an existing item **by the portal's own event id** when both have one (so a university's Master's and Bachelor's periods with one title and the same dates stay two items), else by title + start + note. Timeline status words fill missing dates (`_status_days`, `ask.py:1188-1206`: "Opens in 9 days" -> start, "Closes in 4 days"/"In 7 days" -> end, "Today"). Rows whose status says done/completed are skipped. Returns `(items, ok)` with `ok = EV present or layout_ok or upcoming_ok`.

### 3.8 `window_applications.php` (university admission-window applications)

| | |
|---|---|
| URL | `GET window_applications.php?status=under_review` (the path string includes the query) |
| Reader | `read_window_apps_under_review()` (`client.py:561-568`) -> `parse_window_applications(html)` (`parsers.py:920-945`) -> `count_under_review(rows)` (`parsers.py:948-950`); the Supabase `collect_window_applications` (`backfill.py:245-262`: complete only when the page has no pager and its rows can be told apart from a layout change) |
| Structure | `<table class="tbl wa-tbl">`, header `''`, Student, Window, Status, Docs, Submitted, Updated, Actions; status in `<span class="status-pill s-<status>">`; empty state is a one-cell row "No applications match the filters Try a different search or ..."; filter `<form class="wa-filter" method="GET">` with `select name="status"`: `started`, `submitted`, `under_review`, `documents_verified`, `accepted`, `rejected`, `waitlisted`, `withdrawn`; export link `?status=under_review&export=csv` |
| Parse | the first `<table>` whose header has a `status` column (by `_label_key`); rows with too few cells (the empty state) are skipped -> `[]`; `{"student", "window", "status" (the pill text)}`. No table with a Status column -> `None` ("not available") |
| Count | rows whose status `_label_key` is `under review` (so "under_review" and "Under Review" both count), i.e. each row's **own** status, not the filter (0 on 28 and 30 Sep) |

It is always reported beside, never added to, pending payments (guardrail 2), with the dashboard's "Under review" tile as a cross-check.

### 3.9 `progress.php?uid=N` (one student's progress page) — used by `/stage`

| | |
|---|---|
| URL | `GET progress.php?uid=<uid>` (timeout 30) |
| Reader | `stage_report.read_progress(uids)` (`stage_report.py:68-105`) -> `parse_progress_page(html)` (`parsers.py:561-573`); the backfill reads every student's page this way once (340 pages, 4 at a time, `backfill.collect_progress`, `backfill.py:135-151`: `student_progress`, complete only when every page was read) |
| Structure | `.pg-sum-top` > `<div class="pg-ring" style="--p:11" title="Overall progress"><b>11%</b></div>` and `.pg-now` > `.pg-k` "Current stage", `.pg-stage` "Payment Verified", `.pg-status` "Pending verification"; below, 10 timeline `li.tm-item` (classes `done`, `current`, `upcoming`, `warn`); one POST form (never submitted) |
| Parse | `{"pct": int from "(\d{1,3})\s*%" in .pg-ring, "stage": .pg-now .pg-stage, "status": .pg-now .pg-status}`; no ring % or no stage -> `StudentListLayoutError` |
| Concurrency | own `HangeulAdminClient`; the first page alone (it logs in), then the rest with `asyncio.Semaphore(PROGRESS_READERS=4)` (`stage_report.py:65`); once the portal stops answering (unreachable, or a failed login) the remaining uids get the same error without a request |

### 3.10 `consult_performance.php` (Leads > Performance, the "Consultant Performance" page) — used by `/performance_today`, `/performance_month`

The owner's own definition of "performance" (30 Sep 2026, 13:11): this page, and only this page's data. The bot had first computed "performance" itself from `consult_requests.php` and `students.php` (`bbd8f98`, `a721066`, deployed 30 Sep 10:31); that was replaced by reading this page (`ce23535`, `314afdb`, deployed 14:06). History in [08](08_HISTORY_STAGE_BY_STAGE.md); the replies in [05 §5.15](05_TELEGRAM_COMMANDS_AND_JOBS.md).

| | |
|---|---|
| URL | `GET consult_performance.php?period=today` or `?period=month` (`fetch_html(PERFORMANCE_PAGE, params={"period": period})`, `client.py:442`; default timeout 60 s, connect 10). **Only these two**: `PERFORMANCE_PAGE = "consult_performance.php"`, `PERFORMANCE_PERIODS = {"today": "Today", "month": "This Month"}` (`client.py:57-58`) |
| Reader | `read_consult_performance(period)` (`client.py:425-452`) -> `parse_consult_performance(html)` in a worker thread (`parsers.py:1088-1208`); callers: `src\bot\performance.build_performance_report` (`performance.py:281-303`), the hourly full picture and the backfill (`backfill.collect_performance`, `backfill.py:294-313`) |
| Page title | `Consultant Performance — Hangeul Admin`; sidebar link `<a href="consult_performance.php" class="sb-item sb-subitem active"><i class="fas fa-chart-line"></i> Performance</a>` under Leads |
| Size / speed | small; one GET 0.3 s (1.2 s with a fresh login) on 30 Sep |
| Read-only | one GET per period; no form is ever submitted (the Custom range is a GET form, but the bot never uses it) |

**Structure (live, 30 Sep 2026; the synthetic fixture `tests\test_performance.py:132-182` `perf_page(...)` copies it)**, everything inside `main.content`:

```html
<div class="pf-bar">
  <nav class="pf-tabs" aria-label="Period">
    <a class="on" href="?period=today">Today</a>
    <a class="" href="?period=week">This Week</a>
    <a class="" href="?period=month">This Month</a>
    <a class="" href="?period=all">All Time</a>
    <label for="pf-from"><i class="fas fa-calendar-days"></i> Custom range</label>
  </nav>
  <form method="get" class="pf-range">                      <!-- the Custom range: NEVER used -->
    <input type="hidden" name="period" value="custom">
    <div class="pf-f"><label for="pf-from">From</label><input type="date" id="pf-from" name="from" value="2026-09-01"></div>
    <div class="pf-f"><label for="pf-to">To</label><input type="date" id="pf-to" name="to" value="2026-09-30"></div>
    <button type="submit" class="pf-btn"><i class="fas fa-filter"></i> Apply range</button>
    <p class="pf-showing"><i class="fas fa-calendar-day"></i> Showing <strong>Today</strong><span class="pf-dates">30 Sep – 30 Sep 2026</span></p>
  </form>
</div>
<p class="pf-scope"></p>                                     <!-- staff-only scope note; empty for owner/admin -->
<div class="pf-stats">                                       <!-- 4 tiles -->
  <div class="pf-stat"><span class="ic inf"><i class="fas fa-headset"></i></span><div><div class="n">5</div><div class="l">Consultancies done</div></div></div>
  ... Files opened (folder icon) · Conversion (file open) (percent) · Docs ready (clipboard)
</div>
<section class="pf-top" aria-label="Top performer">
  <div class="pf-top-who"><div class="pf-top-av">F<span class="medal"><i class="fas fa-trophy"></i></span></div>
    <div><div class="pf-top-k"><i class="fas fa-star"></i> Top performer · Today</div><h2 class="pf-top-name">&lt;consultant&gt;</h2></div></div>
  <div class="pf-top-m"><div><b>2.3</b><span>Score</span></div><div><b>100%</b><span>Conversion</span></div>
    <div><b>1</b><span>Files opened</span></div><div><b>1</b><span>Consultancies</span></div></div>
</section>
<div class="card pf-card">
  <div class="card-head"><div class="card-title"><i class="fas fa-ranking-star"></i> Leaderboard <span class="pf-count">4</span></div>
    <span class="pf-note"><i class="fas fa-arrow-down-wide-short"></i> Sorted by score, highest first</span></div>
  <div class="tbl-wrap"><table class="tbl pf">
    <thead><tr><th class="c-rank">#</th><th>Consultant</th>
      <th title="Balanced score = files opened × (0.5 + conversion) × program weight">Score<i class="fas fa-circle-info"></i></th>
      <th>Conversion</th><th>Files Opened</th><th>Consultancies</th>
      <th title="Weighted workload: Bachelor/Master/PhD ×1.5, KLP/EAP ×1">Points<i class="fas fa-circle-info"></i></th>
      <th>Docs Ready</th></tr></thead>
    <tbody>
      <tr style="background:#f0fdf4" class="is-top">
        <td class="c-rank"><span class="rank g1">1</span></td>
        <td class="c-who"><div class="pf-who"><span class="cav">F</span><div class="pf-who-t"><strong class="pf-name">&lt;consultant&gt;</strong>
            <span class="pf-crown" title="Top performer"><i class="fas fa-trophy"></i> Top</span></div></div></td>
        <td class="c-score"><span class="pf-score">2.3</span></td>
        <td class="c-conv" data-l="Conversion"><div class="pf-conv"><span class="convbar"><i style="width:100%"></i></span><b>100%</b></div></td>
        <td class="c-mini" data-l="Files opened"><span class="pill green">1</span></td>
        <td class="c-mini" data-l="Consultancies"><span class="pill blue">1</span></td>
        <td class="c-mini pf-dim" data-l="Points">1.5</td>
        <td class="c-mini pf-dim" data-l="Docs ready">0</td>
      </tr> ...
    </tbody></table></div></div>
<section class="pf-legend" aria-label="How the numbers are worked out"><dl class="pf-defs">
  <div class="d-files"><dt><i class="fas fa-folder-open"></i> Files opened</dt><dd>Payments you <b>verified</b> in this period. ...</dd></div>
  <div class="d-score"><dt>Score</dt><dd>Balanced score = ...</dd></div> ... Conversion, Points
</dl></section>
```

What each part is and how the bot treats it:

| Part | Detail | Bot |
|---|---|---|
| Period tabs `nav.pf-tabs` | links `?period=today`, `week`, `month`, `all` (Today, This Week, This Month, All Time); the open one has class `on`; a "Custom range" label beside them | the open tab's `href` `period=` value (`parse_qs`) is `page["period"]` (`parsers.py:1188`) |
| Custom range `form.pf-range` | GET form: hidden `period=custom`, `input[type=date]` `from` / `to`, button "Apply range" | **never used** (not a command, not a free-text route; `performance_other_reply` sends the user to the portal for it) |
| Range line `p.pf-showing` (inside the form) | `Showing <strong>This Month</strong><span class="pf-dates">01 Sep – 30 Sep 2026</span>`; Today reads `Showing Today · 30 Sep – 30 Sep 2026` (the `·` is drawn by CSS, not in the HTML); on All Time the span has class `is-hidden` and holds a placeholder (`01 Jan – 31 Dec 2999`) | `period_label` = the `<strong>` (else the open tab's text); `range_text` = `.pf-dates` text, `""` when `is-hidden` (`parsers.py:1186-1193`) |
| **Fallback to This Month** | a request with no `period` (and, presumably, an unknown one) shows **This Month** | the reader refuses any page whose open tab or Showing label is not the period asked for (below) |
| Scope note `p.pf-scope` | a staff-only note of which requests a consultant sees; empty (and hidden by CSS `:empty`) for owner/admin | `scope_note`; shown as `ℹ️ The page notes: ...` when not empty |
| Tiles `div.pf-stats > div.pf-stat` | 4 tiles, each `.n` (figure) and `.l` (label): Consultancies done, Files opened, Conversion (file open), Docs ready. 30 Sep: today 5 / 1 / 20% / 0; this month 716 / 108 / 15% / 8 | `tiles` = `{label: figure}` in page order, first of a label kept (`parsers.py:1123-1131`) |
| Top performer card `section.pf-top[aria-label="Top performer"]` | `.pf-top-av` (initial and `span.medal` trophy), `.pf-top-k` "Top performer · Today" / "· This Month", `h2.pf-top-name`, `.pf-top-m > div` each `<b>figure</b><span>label</span>`: Score, Conversion, Files opened, Consultancies | `_perf_top` (`parsers.py:1047-1072`): `{"label", "name", "score", "conversion", "files_opened", "consultancies", "metrics": [(label, figure)]}`; a missing card, or a card with no name or a dash, is `None` (no top performer); a card lacking one of the four figures raises |
| Leaderboard card `div.card.pf-card` | `.card-title` "Leaderboard" with `span.pf-count` (number of rows); `span.pf-note` "Sorted by score, highest first" | `count` (must be an int equal to the rows), `sort_note` |
| Leaderboard table `table.tbl.pf` | header: `th.c-rank "#"`, Consultant, Score, Conversion, Files Opened, Consultancies, Points, Docs Ready; Score and Points carry `title` tooltips with an `fa-circle-info` icon | columns by header text (`_PERF_COLUMNS`); `score_help` / `points_help` = the `th` titles, else the legend's `dd` |
| Rows | top row `tr.is-top` (inline green background) with `span.pf-crown` "Top" in its name cell; `td.c-rank span.rank(.g1/.g2/.g3)`; `td.c-who .pf-who` (`span.cav` initial, `.pf-who-t strong.pf-name`); `td.c-score span.pf-score`; `td.c-conv` (`.convbar` + `<b>18%</b>`); `td.c-mini span.pill.green` (files opened); `td.c-mini span.pill.blue` (consultancies); `td.c-mini.pf-dim` (points, docs ready); each cell has a `data-l` label | `rank, name, top, score, conversion, files_opened, consultancies, points, docs_ready, extra` |
| Empty state | **never seen live** (neither period was empty on 30 Sep, and reaching an empty day would need the forbidden Custom range); the page's own CSS defines `tr.pf-empty-row > td > div.pf-empty` (`span.ic` icon, `<b>` title, `<span>` text) inside `tbody`; the top card is then presumably absent | the empty leaderboard, `empty_text` = the box's words; the **only** one-cell row accepted |
| Legend `section.pf-legend` > `dl.pf-defs` | `dt`/`dd`: Files opened = payments you verified in this period (verifying a payment counts as opening a file); Score = the formula above, the table is ranked by it; Conversion = Files opened ÷ consultancies; Points = the weighted workload | fallback source of the Score / Points help (`_perf_help`, `parsers.py:1075-1085`) |
| E-mail | no Cloudflare address on 30 Sep | decoded anyway (a consultant whose name is an address) |
| This Week / All Time | `?period=week` ("28 Sep – 30 Sep 2026", Monday to today) and `?period=all` have the same layout (6 and 8 rows on 30 Sep) | not read by the bot |
| Self-consistency | the tiles equal the sums of their leaderboard columns (this month: 146+101+117+146+111+95+0 = 716 consultancies), and the top card equals the crowned row | checked in the reply, never corrected (below) |

Raw page dumps of the 30 Sep survey (`raw_today/month/week/all/none.html`: staff names and aggregate counts only) are in `C:\Hangeul\JARVIS\perf2\scratch`, outside the repo, left for the owner to delete ([11 §F](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).

**The parser, `parse_consult_performance(html) -> dict`** (`parsers.py:1088-1208`), by labels, header texts and classes, never by position, on the decoded soup:
* **Columns** (`_PERF_COLUMNS`, `parsers.py:963-972`), each key takes the first unused header its test accepts on the `_label_key` (a plural's `s` dropped: "Consultancies" -> "consultancie"): `rank` <- key in `rank`/`no`/`pos`/`position`/`sl`, or an empty key with `#` in the raw text; `name` <- starts with `consultant`/`counsellor`/`counselor`/`staff`/`name`; `score` <- `score`; `conversion` <- `conversion`; `files_opened` <- `file`; `consultancies` <- `consultanc`; `points` <- `point`; `docs_ready` <- `doc`/`document`. **All eight are required**; an unknown extra column is kept by its own header text in the row's `extra`. The leaderboard is the first table whose header row (`thead tr`, else the first `tr`) names a Consultant **and** a Score column (`_perf_table`, `parsers.py:1020-1031`), so the sidebar's menu table is never taken for it.
* **Figure shapes** (`_PERF_SHAPES`, `parsers.py:976-984`; `_PERF_NUMBER = r"-?\d[\d,]*(?:\.\d+)?"`): rank `\d+`; score, points `_PERF_NUMBER`; conversion `_PERF_NUMBER\s*%?`; files opened, consultancies, docs ready `\d[\d,]*`; tiles `_PERF_TILE_SHAPE = _PERF_NUMBER\s*%?`. The portal's dashes `—`, `–`, `-`, `--` (`_PERF_DASHES`) are kept as they are. Every figure is kept **exactly as printed** (`"17.9"`, `"18%"`, `"149.5"`, `"1,304"`), never converted.
* **Names** (`_perf_name`, `parsers.py:1034-1044`): `.pf-name` (else `strong`), else the cell without `.cav`, `.pf-crown`, `.medal`; the crown (`is-top` class or a `.pf-crown`) is the row's `top`.
* **Returns** `{"period", "period_label", "range_text", "scope_note", "tiles", "top", "columns": [(key or None, header text)], "leaderboard": [rows], "count", "empty_text", "sort_note", "score_help", "points_help"}`.
* **Raises `PerformanceLayoutError`** (`parsers.py:955-957`, a `ValueError`) when: no tiles ("its tiles (Consultancies done, Files opened, ...) were not found"); no leaderboard table ("a header with Consultant and Score"); a required column missing ("the leaderboard's header has no points column (it reads [...])"); a figure not of its shape ("... reads '...', which is not a figure"); a one-cell row that is not the page's empty state ("leaderboard row 1 is one cell that is not the page's empty state (it reads 'Could not load the leaderboard ...')"), so a portal error is never "nobody is listed"; a row whose cell count differs from the header's; a row with no name; rows and the empty state at once; a count badge that is not a number or does not equal the rows; a top card missing one of its four figures.

**The reader, `read_consult_performance(period)`** (`client.py:425-452`):
1. `period` not `today`/`month` -> `ValueError`; mock mode -> `PortalUnavailable("the bot is in mock mode, so there is no live portal to read")`.
2. One GET of the period link; the parse in `asyncio.to_thread`; a `PerformanceLayoutError` becomes `PortalUnavailable("consult_performance.php: <why> (layout not recognised)")`.
3. **The period echo** (`client.py:448`): `_label_key(page["period_label"])` must equal `_label_key("Today" / "This Month")` and `page["period"]` must be `None` or the period asked; else `PortalUnavailable("consult_performance.php?period=today shows 'This Month' instead of 'Today' (layout not recognised)")`. This matters because the page falls back to This Month for a period it does not take.

**Checks of the page against itself** (in the reply, `src\bot\performance.py`; each is a `⚠️` line, nothing is corrected):
* `_range_warning` (`performance.py:108-123`): Today's range must be today..today in Dhaka; This Month's must start on the 1st and end today or on the month's last day; else `⚠️ The page's range is <range>, but today in Dhaka is DD Mon YYYY: the figures are the portal's, for the range it shows.` A range that cannot be read as dates gives no line (and, in Supabase, no record: no stand-in day).
* `_top_warnings` (`performance.py:126-143`): a leaderboard with no top card; a top card with an empty leaderboard; the card and the crowned row naming different people; or differing on score, conversion, files opened, consultancies.
* `_total_warnings` (`performance.py:146-163`): the Consultancies done, Files opened and Docs ready tiles must equal their column's sum (Conversion is a ratio, not summed).

### 3.11 Pages the bot does not read

| Page | Why |
|---|---|
| `signed_students.php` | guardrail 6: finalised contracts, out of scope |
| `ask_ai.php`, `ai_training.php`, `team_assistant.php` | guardrail 7: no portal AI |
| `review_queue.php`, `admission_windows.php` | appear only as dashboard tile hrefs (used to tell the tiles apart) |
| `consult_performance.php?period=week`, `?period=all`, `?period=custom&from=...&to=...` | the owner asked for today and this month only; the Custom range form is never submitted |
| `/cdn-cgi/l/email-protection`, `/cdn-cgi/scripts/.../email-decode.min.js` | Cloudflare's; the addresses are decoded offline (section 1.4) |
| `inbox.php` | linked from the list page, never fetched |
| `payments.php`, `settings.php` | mentioned only as examples in the REST crawler's docstring |

---

## 4. Known layout changes and the fixes (September 2026)

| Page | What changed / what was wrong | Symptom | Fix (commit) |
|---|---|---|---|
| `consult_requests.php` | 8+ fixed columns became 7 named ones (Student, Consultant, City & program, Received, Status, Remarks, Update status) | both readers required 8 columns: all 500 rows skipped, "Total All-Time Done: 0" | header-driven `consultation_rows` with the cells' own classes (`cd0277a`, 28 Sep 11:24) |
| `consult_requests.php` | the unfiltered list shows only the newest 500 | all-time figures about half the real ones (500/367 vs 999/797); days older than ~3 weeks read 0; an unanchored optional-year regex counted 18 and 28 Sep as 8 Sep | per day: the portal's own date filter; all-time: the status tabs (`46cdf03`) |
| `index.php` | tile labels are "Total students", "Under review" (not "Total Students", "Under Review") | case-sensitive `dict.get(label, <placeholder>)` silently returned hard-coded placeholders (262 applicants, 31 week registrations, 2 under review, 21 docs) that fed the LLM brief | case/plural-insensitive `_label_key` matching, href-disambiguated "Docs to review", `None` -> "not available", placeholders removed (`f8fefa4`) |
| `calendar.php` | upcoming events moved from `div.ag-item` to `.ev-row` / `var EV`; reminders to `.rm-item` with `.rm-title` | 0 upcoming events; 11 reminders with every field empty ("eleven deadlines") | new `rm-item`/`ev-row` parser (`f8fefa4`), EV merge by event id, time-then-end-date ranges, done items excluded (`7f42ad0`, `e164679`) |
| `students.php` | pagination (50 a page, 7 pages on 28 Sep) | every reader saw page 1 only: 12 Sep read 0 (truth 10), 23 Jul 0 (truth 62); watcher saw 42 of 301 scans | `read_student_pages` all-pages loop (`e0d47ab`, `9dcd9ad`, `40da0e6`) |
| `students.php` | positional cell parsing, shifted by one | every student's intake read "March 2027" | header-name columns (`e0d47ab`) |
| `students.php` | no amount chip on older rows (209 of 322 stamps had no "Verified income") | a hard-coded `"20,000.00 BDT"` stand-in amount inflated revenue | amounts only from `.pf.verified` / `.pf.paid`, else "not available" (`e0d47ab`) |
| `students.php` | yearless stamp "27 Sep, 17:19" | 27 Sep 2025 listed 2026's verifications | `yearless_day_problem` + applied-date rule (`e0d47ab`) |
| `students.php` | `?status=admitted` is ignored; `q` does not search universities | `/admitted` returned 20 non-admitted students | stage from the Admitted tile's link, filtered in code (`e0d47ab`) |
| `students.php?export=csv` | stale `Current Stage/Status/Progress %` | wrong `/stage` groups (both pending-payment applicants showed "Payment Verified") | stage from the list's "Stage · Applied" cell, status/% from `progress.php` (`9dcd9ad`, `e164679`) |
| `students.php`, export | the portal types filler words for "no value" (`N/A`, `None`, `NA`, `--`, `PENDING` as a passport number...) | dry run 1 (29 Sep 14:39) would have published them as data | the Supabase records blank them and name them in `data.blank_on_portal`; "Pending" stays only in status fields (`752cd53`) |
| **every page** (Cloudflare) | e-mail obfuscation: every address is `[email protected]` + `data-cfemail` hex (section 1.4) | `details.Email` = the stand-in in all 333 student records and 1,005 of 1,014 consultation contacts of dry run 2; a request whose name is an address read as the stand-in except in one markup form | `decode_cf_emails` on every soup, `_without_hidden_email`, `records.is_filler` blanks what cannot be decoded (`9ead47d`, 29 Sep 16:19) |
| `consult_performance.php` (new to the bot) | "performance" is the portal's own page, not a count the bot makes | the first performance commands (`bbd8f98`, `a721066`) showed self-computed tallies the owner had not asked for | read the page, only its data (`ce23535`, `314afdb`); its Supabase scope made stable over a month (`8317741`) |

---

## 5. Guards against silent zeros (checklist to copy)

1. **Exceptions, not empties.** Every reader raises `PortalUnavailable` (or `StudentListLayoutError` / `PerformanceLayoutError` -> re-raised as `PortalUnavailable`) instead of returning `[]`, `0` or `"none"`. The reply is always `❌ Couldn't read the portal: <why>. <what>: not available right now.` and a figure the page does not show is printed as `not available`.
2. **Login is checked.** A POST that still ends on `login.php` is a refused login; a GET that ends on `login.php` gets one fresh login and one retry, then an error (a login page is never parsed as data).
3. **Layout recognition before counting.** Required header columns (students: SL/Student/Program/Stage; consultations: Student/Status; window apps: Status; performance: all eight), unreadable rows raise, tabs must exist with numeric counts and an `All` tab, calendar cards must show entries or say "none", the dashboard must yield at least one fact, the performance tiles must exist and every figure must look like one.
4. **Cross-checks between the page's own numbers.** Pager total vs uids read; consultation caption vs rows vs `All` tab vs per-status tabs; the filter echoed by the search form (per day, and per range in the backfill); the pending badge vs rows; the Admitted tile vs the stage count; the Under review tile vs the window rows; the performance count badge vs its rows, its tiles vs their columns' sums, its top card vs its crowned row. A mismatch is either an error or printed as a `⚠️` line, never silently resolved.
5. **The page must say it shows what was asked.** The consultation form echoes the date filter; the Consultant Performance page's open tab and "Showing" label must be the period asked for, because it falls back to This Month for a period it does not take.
6. **Real empty states are recognised** (`tr.empty-row` "No students found", `cr-empty-row` "No consultation requests yet.", the window empty row, "· 0 items", `tr.pf-empty-row` with its `.pf-empty` box) so a true 0 can still be reported; any other one-cell row is a layout error, never "nobody".
7. **Dates are strict.** Unreadable user dates get "I couldn't read that date", yearless portal stamps refuse days a year back, future days are "not available"; a performance range that cannot be read as days gives no Supabase record.
8. **Budgets and "down" detection.** The brief stops reading after the first unreachable answer (`_PortalReads`), the full picture's `PortalSession` and the backfill's collectors likewise, the watcher stops starting OCR after 20 minutes, progress reads stop once the portal stops answering; the skipped parts say "not read: the portal did not answer".
9. **Nothing invented.** No placeholder figures, no stand-in amounts or methods, no stand-in addresses (Cloudflare's text is decoded or blanked), no LLM-written numbers (the LLM only picks existing facts or writes a summary whose every number is checked, see [05](05_TELEGRAM_COMMANDS_AND_JOBS.md)).

---

## 6. Reader -> page -> caller map

| Reader (`src\scraper\client.py` unless noted) | Page(s) | Callers |
|---|---|---|
| `login` | `login.php` GET+POST | every session |
| `get_dashboard` | `index.php` | `/stats`, `/admitted` (tile), brief section 3 |
| `ask._dashboard` / `dashboard_facts` | `index.php` | free-text dashboard answers, `/alerts`, `ask.answer_unknown`, window-review tile; Supabase full picture and backfill (`collect_dashboard`) |
| `read_students` / `read_student_pages` | `students.php` (+`pg`, filters) | `/verified*`, `/crosscheck*`, `/passports`, `/admitted`, `/students` (page 1), pending (all pages), intake and applied answers, passport watcher, `/stage`, issue-date refresh, sync download list, `/sendmail` fallback; full picture (`collect_students`, `collect_pending`) and backfill |
| `read_verified_students` | `students.php` all pages | `/verified*`, brief section 2 |
| `read_pending_payments` | `students.php?status=pending` | brief section 3 |
| `read_window_apps_under_review` | `window_applications.php?status=under_review` | brief section 3, window-review answer (full picture and backfill parse the page themselves: `collect_window_applications`) |
| `read_consultation_day` | `consult_requests.php?status=all&from=D&to=D` | `/inquiries*`, `/consultations`, brief section 1; full picture (yesterday, today); backfill (every day) |
| `read_consultation_totals` | `consult_requests.php?status=file_opened` | `/inquiries*`, brief section 1; full picture; backfill |
| `read_consultation_view` | `consult_requests.php?status=all&from=A&to=B` | backfill `_range_count` / `oldest_consultation_day` |
| `read_consult_performance` | `consult_performance.php?period=today` / `?period=month` | `/performance_today`, `/perf_today`, `/performance_month`, `/perf_month`, `/performance [today\|month]`, free text; full picture and backfill (`collect_performance`) |
| `get_calendar_events` | `calendar.php` | `/calendar` (bare), brief section 4 |
| `ask.answer_calendar` / `ask.calendar_items` | `calendar.php` | `/calendar <words>`, `/deadlines <words>`, calendar free text; full picture and backfill (`collect_calendar`) |
| `audit_student_passport` | `student_edit.php?id=N`, `view_doc.php?f=...` | `/crosscheck*`, `/passports`, passport watcher |
| `stage_report.read_progress` | `progress.php?uid=N` | `/stage` intake report; backfill (`collect_progress`, every student) |
| `progress_builder.fetch_all_students` | `students.php?export=csv` | sync, `/missing`, `/stage`; backfill (`collect_export`) |
| `verified_docs.fetch_verified_students`, `_download_zip` | `students.php?source=direct&filter_docs=verified`, `download_docs.php?uid=N&zip=1` | sync; backfill (`collect_documents`, the list only) |
| `passport_issue._fetch_async` | `students.php` all pages, `student_edit.php?id=N` per passport | 08:30 refresh |

## 7. Rebuild checklist

1. One client class with `portal_get` (login check, one re-login on a `login.php` redirect, connect timeout 10 s, `PortalUnavailable(reason, unreachable)`), and an allow-list of read-only pages and parameters; no other HTTP method to the portal than the login POST.
2. If the site is behind Cloudflare (or any CDN that rewrites content), decode its e-mail obfuscation right after building every soup, and treat an undecodable stand-in as no value; pin "every soup is decoded" with a source test.
3. Parse by header names and CSS classes; keep a synthetic fixture per page (see `tests\test_foundation.py`, `tests\test_consultations.py`, `tests\test_brief.py`, `tests\test_repair.py`, `tests\test_performance.py`, `tests\test_cloud_cf_email.py`) and a test that fails on any non-GET.
4. Follow `Page X of N` with `?pg=N`, cap pages, de-duplicate by uid, compare with the pager total.
5. Use the portal's own counters (status tabs, badges, tiles, count badges) for totals, and its own date filter for days; compare them with the rows; make every filtered page prove it applied the filter (an echo, an open tab, a "Showing" label).
6. Treat yearless stamps with the one-year rule; never match dates as substrings.
7. Run heavy parsing and OCR in threads; keep portal GETs async.

---

## 8. Portal survey checklist (deriving the contracts for a different portal)

Sections 3-5 describe how *this* portal looks. For another agency's portal, derive the same contracts **before writing a parser**, from saved pages that no longer carry personal data. The method used here (28 Sep 2026, [10 §4](10_TESTS_AND_VERIFICATION.md); again for the Consultant Performance page on 30 Sep, with a network guard that allowed only GET plus the login POST): fetch each page read-only (GET, plus the login POST), save it, and study a **masked** copy in which letters become `x` and digits `9` except for known label and status words, so the structure (tags, classes, label words, date shapes, pager text) stays readable while names, numbers and e-mails do not.

The mask helper, as used by the audit (`C:\Hangeul\JARVIS\command-audit\crosscheck\common.py:25-41`); extend `KEEP_WORDS` with the new portal's own label and status words:

```python
import re

KEEP_WORDS = {
    "full", "name", "dob", "passport", "no", "expiry", "program", "preferred", "paid", "bdt",
    "verified", "payment", "by", "status", "view", "edit", "father", "mother", "address", "district",
    "sep", "aug", "oct", "jan", "feb", "mar", "apr", "may", "jun", "jul", "nov", "dec", "receipt",
    "will", "apply", "pending", "id", "student", "students", "intake", "date", "created", "submitted",
}


def mask(text: str) -> str:
    """letters -> x, digits -> 9, except known label/status words."""
    def _w(m):
        w = m.group(0)
        if w.lower() in KEEP_WORDS:
            return w
        return re.sub(r"[A-Za-z]", "x", w)
    t = re.sub(r"[A-Za-z]+", _w, text)
    return re.sub(r"\d", "9", t)
```

Mask the **text nodes**, not the markup, when you want class names kept (e.g. walk BeautifulSoup's `soup.find_all(string=True)` and replace each string with `mask(s)`); a masked dump still holds the page's layout, so keep it out of anything shared. Note that a masked dump of a Cloudflare-served page shows `[xxxxx xxxxxxxxx]` where an address is: look at the markup (`__cf_email__`, `data-cfemail`) to see it. Delete the raw pages afterwards ([11 §F](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).

**Record, for every page the bot will read:**

| # | Question | Why it matters here (Hangeul answer) |
|---|---|---|
| 1 | The pager: its text, the page size, and the total it states | the students list showed 50 a page and `Page X of N · T students`; page 1 alone hid most verifications (§3.3) |
| 2 | Do filters survive paging? Does the page echo the filter back (a selected option, a heading)? | the query must be repeated on every `?pg=N`; an unechoed filter cannot be proven applied |
| 3 | The page's own counters: status tabs, badges, dashboard tiles, date-filter views, count badges | a capped list (500 consultation rows) undercounts; the tab counts are exact (§3.6); the performance count badge must equal its rows (§3.10) |
| 4 | The markup of a **real empty state** (e.g. `tr.empty-row` "No students found") | "no rows because empty" must be told apart from "no rows because the layout changed" (§5); if it cannot be seen live, take it from the page's own CSS and accept only that (§3.10) |
| 5 | Date formats, and whether they carry a year | verification stamps have no year (`27 Sep, 17:19`), hence the one-year rule (§3.3, [03b §2](03b_FILES_src_scraper_llm_api_config.md)) |
| 6 | Export endpoints (CSV, Excel) and their column list | `students.php?export=csv` gives all students in one request, 63 columns, with plain addresses (§3.3) |
| 7 | File-name conventions of uploads | `passport_<uid>_<unixtime>.<ext>`: the upload epoch dates a scan without opening it (§3.5) |
| 8 | The login form: field names, the CSRF field name, where an expired session redirects | `_csrf`; an expired session ends on `login.php`, detected by `_ended_on_login` (§3.1, §1.1) |
| 9 | Every mutation form and state-changing link on the page, and every filter form the bot must *not* use | list them so the client never touches them (§2.1: verify, stage, transfer, delete, remarks, "Done" buttons; the performance page's Custom range) |
| 10 | Size and speed of the page | `consult_requests.php` is ~2 MB and needs a long read timeout (§1.3) |
| 11 | Is the site behind a CDN that rewrites content? Search the raw HTML for `__cf_email__`, `data-cfemail`, `/cdn-cgi/` | Cloudflare hid every e-mail address on every page (§1.4) |
| 12 | What does a page show for a parameter it does not take? | `consult_performance.php` falls back to This Month, so the reader checks the open tab and the "Showing" label (§3.10) |

**From these, derive:** (a) the **required columns / labels** per page, found by header name, never by position (`_STUDENT_COLUMNS` and the required set, `_PERF_COLUMNS`, [03b §4.4](03b_FILES_src_scraper_llm_api_config.md)); (b) the **layout guards**: a page with rows but none readable, a full first page with no pager, a missing required column, a page that shows another filter or period than asked, raises `PortalUnavailable`, never returns 0 (§5); (c) a **synthetic fixture builder** per page that emits the same classes and label words with made-up data, in the pattern of `tests\test_foundation.py`: `row(uid, sl, name, hng="", uni="—", program=KLP, intake="MARCH 2027", docs="All Missing", pay="Verified", stage="Payment Verified", applied="12 Jul 2026", by="", when="", paid="", method="", income="")` returns one `tr.stu-row` plus its `tr.xp-row` details (including the mutation `<form method="POST">` and the `showDel(...)` button, so a parser that trips on them fails a test), and `page(*rows, pg=1, pages=1, total=None)` wraps them in `table.tbl.stu-tbl` with the `div.stu-pager` text or the real empty row; `tests\test_performance.py` `perf_page(period, label, dates, tiles, top, rows, columns, count, scope, dates_class, empty, extra_th)` does the same for the Consultant Performance page (with a decoy sidebar table and the unused Custom range form), and `tests\test_cloud_cf_email.py` `a_form` / `span_form` / `link_form` / `hide(address, key)` produce Cloudflare's three markups from synthetic addresses; the `portal` fixture serves them from a dict and raises on any non-GET ([10 §2.1](10_TESTS_AND_VERIFICATION.md)).
