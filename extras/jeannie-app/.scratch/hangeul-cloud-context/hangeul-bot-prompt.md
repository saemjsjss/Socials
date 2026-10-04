# Prompt for Claude Code on the Hangeul PC: publish every finding to Supabase too

Status: resolved (run on the Windows PC in `C:\Hangeul\BOT`: the bot's one-time backfill wrote 13,540 records and
15,629 chunks on 30 Sep 22:05, and the bot keeps them current; kept as the record of what was asked. The source of
truth for every kind is now the bot's `src/cloud/records.py` and the pack's `13_SUPABASE_PUBLISHING.md`; see the
comments.)

Paste everything below the line into a Claude Code session opened in `C:\Hangeul\BOT`.

---

## Goal

Hangeul BOT (@the_Jennie_bot) already writes its findings to Google Drive/Sheets, to local `.xlsx`
reports and to Telegram. Add a **second, independent destination**: the owner's Supabase project
`dcbcbpwpmdtaanboetiz`. Everything the bot parses from `https://hangeul.com.bd/admin`, and every report
it generates, must also be written there as **structured rows plus text plus vector embeddings**.
The owner's web/PWA assistant "Jeannie" reads that data, so the owner can ask for anything on their phone
and get an answer instantly, without the PC being awake.

Drive, Sheets, the `.xlsx` files and Telegram stay exactly as they are. Supabase is added next to them;
it never replaces, delays or blocks them.

Before you change anything, read these parts of `C:\Hangeul\REFERENCE\`: `01_ARCHITECTURE.md` (§1.3
data stores, §4 mechanisms, §5 concurrency), `04_PORTAL_INTEGRATION.md`, `05_TELEGRAM_COMMANDS_AND_JOBS.md`,
`07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md`, `09_BLUEPRINT_RULES_AND_LESSONS.md` (R1-R24, M1-M7) and
`10_TESTS_AND_VERIFICATION.md`. Every rule there still holds.

## Decisions the owner has already made (do not re-open them)

| # | Decision |
|---|---|
| D1 | **Full student data** goes to Supabase: names, phone numbers, e-mails, passport numbers, DOB, father's and mother's names, addresses, and every other parsed field. Nothing is masked. |
| D2 | **Scope = everything parsed from the portal plus every report the bot generates**, including the **full OCR text** of student documents (one chunk per page). **No binary files**: never upload `.pdf`, `.jpg`, `.png`, ZIPs or passport scans. |
| D3 | Store **both** structured rows (the source of every figure) **and** text with embeddings (for fuzzy search). |
| D4 | Answers are snapshots: every row carries the time the bot read it (`read_at`); Jeannie says "as of HH:MM". No inbound connection to the PC. |
| D5 | The bot writes with the project's **secret key** held in `.env` (PostgREST + RPC), not through an Edge Function. |
| D6 | Supabase is **independent**: if it is down or refuses a write, log one line and carry on. No outbox, no retries inside a run, no Telegram alert about it, and never block Drive, Sheets or Telegram. (A row whose upload failed is simply sent again on the next run, because the local hash state is only updated after Supabase accepts it; see "Changed rows only".) |
| D7 | Embeddings are computed **on this PC**, on the **CPU**, with **gte-small** (384 dimensions, mean pooling, L2-normalised). Jeannie uses the same model (`Supabase/gte-small`, the ONNX export of `thenlper/gte-small`) in the browser and on the server, so vectors must match. |
| D8 | One record per entity (a student, a consultation request, a verification, a verdict, an alert, a calendar item, one page of OCR text), and reports split into one record per section or per student line. Not fixed-size chunks. |
| D9 | Upload **only changed rows** (content hash), like `data\sheet_state.json` does for the sheets. |
| D10 | When a thing disappears from a **complete** read of the portal, **hard-delete** it in Supabase (the change log keeps only `kind`, `key` and the time). |
| D11 | A **one-time backfill** of all existing data, including `data\verification\results.json` (the only copy of the Corrections history), the OCR text cache and the watcher memory. |
| D12 | The schema is owned by the Jeannie repo (`munim430-ai/Jeenie-saem-bot`, `supabase/migrations/`). This bot only writes rows. Do **not** create or alter tables from here. |
| D13 | Credential rotation is deferred by the owner (accepted risk). Still never print, log or commit a secret value. |

## Preconditions (check first; stop and tell the owner if one fails)

1. `.env` has `SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co` and `SUPABASE_SECRET_KEY=<value>`
   (an `sb_secret_…` key or the legacy `service_role` key). Ask the owner to add them; never echo the value.
2. The Jeannie migration is applied: a GET of `/rest/v1/hg_runs?select=id&limit=1` with the key answers 200
   (not 404 / `PGRST205`). If it does not, stop: the owner must apply the Jeannie migration first.
3. `sentence-transformers` and the `thenlper/gte-small` weights are not installed yet: **ask the owner before
   downloading** (M7). Pin the package version in `requirements.txt` and the model revision in code.
4. Work on a branch in a git worktree (M4); `C:\Hangeul\BOT` stays untouched until the final fast-forward.

## The data contract (must match the Jeannie migration exactly)

All tables are in `public`, with RLS enabled and no policies (only the secret key can reach them).

### `hg_runs`: one row per job run

| column | type | notes |
|---|---|---|
| `id` | uuid | generated by the bot (`uuid4`) |
| `job` | text | `portal_sync`, `passport_watcher`, `daily_brief`, `missing_report`, `issue_refresh`, `stage_report`, `command`, `backfill` |
| `started_at`, `finished_at` | timestamptz | |
| `status` | text | `ok`, `partial` (some reads failed), `failed` |
| `counts` | jsonb | e.g. `{"upserted": 12, "deleted": 1, "unchanged": 318, "failed_reads": ["calendar.php: …"]}` |
| `note` | text | a short plain reason when not `ok` (never a secret, never a stack trace with URLs) |

Write it via `POST /rest/v1/hg_runs` at the start (`status` null) and `PATCH` it at the end.

### `hg_records`: the latest state of every entity

| column | type | notes |
|---|---|---|
| `kind` | text | one of the kinds below |
| `key` | text | stable id **within** the kind (see the table of kinds). Primary key is `(kind, key)` |
| `scope` | text | the unit a complete read covers, for deletes: `all` for whole lists, the ISO day for per-day reads, the passport number for one student's OCR pages |
| `student_uid` | integer, null | the portal user id (`student_edit.php?id=N`) when the record is about one student |
| `student_hng_id` | text, null | `HNG-YYYY-N` when known |
| `student_name` | text, null | as the portal prints it |
| `passport_no` | text, null | when known (for joins and exact lookups) |
| `day` | date, null | the business day the record is about (stamp day, received day, report day), in Asia/Dhaka |
| `data` | jsonb | **every parsed field**, with the parser's own keys. Absent stays absent or `""`; never a placeholder (R1) |
| `content` | text | the text form for search, built by code (see "Text form") |
| `content_hash` | text | sha256 hex of the canonical JSON of `{kind, key, scope, data, content}` (sorted keys, UTF-8) |
| `source` | text | where it came from: `students.php`, `consult_requests.php?from=…&to=…`, `results.json`, `DOCUMENT CHECK.xlsx`, `brief`… |
| `read_at` | timestamptz | when the bot read the portal (or built the report) for this value |
| `run_id` | uuid | → `hg_runs.id` |

### `hg_chunks`: the embeddings of each record

| column | type | notes |
|---|---|---|
| `kind`, `key` | text | → `hg_records(kind, key)`, cascade delete |
| `ord` | integer | 0, 1, 2… Most records have exactly one chunk |
| `content` | text | the chunk's text (≤ about 350 words so gte-small does not truncate at 512 tokens) |
| `embedding` | vector(384) | gte-small, mean pooled, L2-normalised, float32 |
| `embed_model` | text | e.g. `thenlper/gte-small@<revision>`; must be identical on every row |

### `hg_changes`: the change log

The Jeannie side fills this with a trigger on `hg_records`: `seq bigserial`, `kind`, `key`, `op` (`upsert`
or `delete`), `data` (the new `data` for an upsert; **null for a delete**, D10), `changed_at`, `run_id`.
The bot never writes to it.

### The one write call: RPC `hg_sync`

`POST /rest/v1/rpc/hg_sync` with JSON:

```json
{
  "p_run": "<uuid>",
  "p_kind": "student",
  "p_scope": "all",
  "p_rows": [
    {"key": "425", "student_uid": 425, "student_hng_id": "HNG-2026-12", "student_name": "…",
     "passport_no": "…", "day": "2026-09-09", "data": {…}, "content": "…", "content_hash": "…",
     "source": "students.php", "read_at": "2026-09-29T18:21:04+06:00",
     "chunks": [{"ord": 0, "content": "…", "embedding": [0.0123, …384 floats…], "embed_model": "…"}]}
  ],
  "p_all_keys": ["425", "426", "…"]
}
```

- `p_rows` holds only the **changed** rows (D9), at most 200 per call; split larger sets into several calls
  (send `p_all_keys` only on the **last** call of that kind and scope).
- `p_all_keys` is the complete list of keys a **complete** read of that `(kind, scope)` saw. The server deletes
  every other row in that `(kind, scope)` (D10). **Send it only when the read was complete**: the pager total
  matched, no `PortalUnavailable`, no layout error, no timeout (R2, R5). For a partial or failed read, send
  `p_all_keys: null`, so nothing is ever deleted because the bot failed to read it.
- The server upserts on `(kind, key)` and replaces that record's chunks. It returns `{"upserted": n, "deleted": m}`.
- Headers: `apikey: <secret>`, `Authorization: Bearer <secret>`, `Content-Type: application/json`.
  Timeout 30 s per call.

### Kinds and keys (the inventory to cover)

Map every reader and report in the codebase to one of these. If you find parsed data that fits none, add a
kind with the same pattern, and list it in your final report so the Jeannie side can learn it.

| kind | key | scope | from (reader or report) |
|---|---|---|---|
| `student` | uid | `all` | every page of `students.php` (`read_students`): all list columns, `details` (the ~50 det-items), `files` names, payment chips, verification stamp, `applications` |
| `student_export` | the sheet row key (`Student ID:` / `Passport No:` / `NAME:`) | `all` | `students.php?export=csv` (all 63 columns). Put `"stale_columns": ["Current Stage","Current Status","Progress %"]` in `data` (04 §3.3: those columns are not trusted) |
| `student_profile` | uid | uid | `student_edit.php?id=N` (`_profile_fields`), whenever the bot reads one (audits, sendmail lookup, issue refresh) |
| `student_progress` | uid | `all` | `progress.php?uid=N` (`/stage`) |
| `student_documents` | uid | `all` | the verified-documents list (`?source=direct&filter_docs=verified`): file names and fingerprint, **not the files** |
| `verification` | uid | the stamp's ISO day | `parsers.verification` for each verified student: verifier, time, amount, method, paid vs verified income |
| `consultation` | the row's portal id (hidden `id` in its forms); fallback `sha1(name + contact + received)` | the received ISO day | `read_consultation_day(day)` rows: name, contact, consultant, city, program, details, received, status, handled_by, remarks |
| `consultation_day` | ISO day | `all` | the day's tab counts from `read_consultation_day` |
| `consultation_totals` | `all` | `all` | `read_consultation_totals()` |
| `pending_payment` | uid | `all` | every page of `students.php?status=pending` (rows whose own Payment is Pending) plus the badge in `data` |
| `window_application` | `student + "|" + window` | `all` | `window_applications.php?status=under_review` |
| `dashboard_fact` | `group + "|" + label` | `all` | `index.php` tiles and cards (`dashboard_facts`) |
| `calendar_item` | portal event id | `all` | `calendar.php` (`calendar_items`: EV, reminders, timeline, merged) |
| `passport_audit` | `uid + "|" + file` | `all` | every `audit_student_passport` result (watcher and cross-checks): status, matched, discrepancies, `uncertain`, MRZ fields |
| `passport_alert` | `uid + "|" + file` | `all` | the watcher memory entries (`data\alerted_passport_issues.json`): alert text, sent, sent_at |
| `passport_issue` | passport number | `all` | `data\passport_issue.json` |
| `doc_verdict` | `passport + "|" + document` | passport | `results.json` `documents` (verdict, failing rules, flags) |
| `doc_check` | passport | `all` | added by the bot: `results.json` `documents[P]` as one student-level result (student, program, verdict, checked) with its document rows' and field rows' verdict counts |
| `field_check` | `passport + "|" + field` | passport | `results.json` `fields` (FIELD CHECK rows) |
| `field_correction` | sha1 of the correction entry | `all` | `results.json` `corrections` (append-only history; never deleted) |
| `doc_page_text` | `passport + "|" + file + "|p" + page` | passport | the OCR text cache `data\verification\text\<PASSPORT>.json`, one record per page; long pages become several chunks |
| `report` | `<report>|<ISO day or run time>` | report name | each generated report as a whole: `brief`, `missing_report`, `stage_report`, `document_check`, `field_check`, `sync_summary`, `inquiries_report`… The text as sent, plus the structured facts in `data` |
| `report_section` | `<report>|<day>|<section or student line n>` | `<report>|<day>` | the same reports split per section or per student line (D8) |
| `brief_fact` | `<ISO day>|<n>` | ISO day | each numbered fact of `Brief(text, facts)` |
| `notification` | sha1 of text plus time | ISO day | each Telegram notification the jobs send (sync summaries, document-check notices, alerts), as sent |
| `consultant_performance` | `<period>|<first ISO day>|<name>` (`#2` for a repeated name), and `<period>|<first ISO day>|summary` | `<period>|<first ISO day>` | added by the bot: `consult_performance.php?period=today|month`, one record per leaderboard row (rank, score, conversion, files opened, consultancies, points, docs ready) and a summary record with the tiles ("Consultancies done", "Files opened", "Conversion (file open)", "Docs ready") and the top performer; `day` = the range's last day |

Every kind read from the portal's own fields also carries `data.blank_on_portal` (added by the bot): the names of
the fields the portal left as a filler ("N/A", "PENDING", "—"...), blanked in `data` and left out of the text, so
Jeannie says "not given on the portal" instead of a made-up value.

Reports that are also `.xlsx` files (`DOCUMENT CHECK.xlsx`, `FIELD CHECK.xlsx`, the missing report) are
published from the data they are built from, never by uploading the file.

### Text form (`content`)

Built by code, one short English paragraph per record, with labels, e.g.
`Student <name> (HNG-2026-12, portal uid 425). Program KLP, intake MARCH 2027. Stage: Payment Verified,
applied 12 Sep 2026. Payment: Paid 1,000.00 BDT Cash, verified by <name> on 12 Sep 17:19. Passport <no>,
expires <date>. Mobile <…>. Father <…>. Mother <…>.` Only fields that exist. No invented words (R1).
OCR pages: `Document <file> of <name> (<passport>), page 3:` followed by the OCR text. Reports: the section
heading followed by its lines.

## How to build it

1. **One package, `src\cloud\`** (new):
   - `publish.py`: `hg_sync` calls with a plain `httpx.Client`, the hash state `data\cloud_state.json`
     (`{"<kind>|<key>": "<content_hash>"}`, written with `.part` + `os.replace`, updated **only for rows
     Supabase accepted**), batching, run rows, and a `publish(kind, scope, rows, complete)` entry point.
     It never raises: every failure is logged as one line
     (`Supabase publish failed (<kind>): <short reason>`) and the call returns.
   - `records.py`: one pure function per kind that turns what a reader or report already returns into
     `{key, scope, student_*, day, data, content, source, read_at}`. Reuse the existing parsers' output; do not
     re-parse pages.
   - `embed.py`: loads gte-small once per process, on the **CPU** (`device="cpu"`), `normalize_embeddings=True`,
     splits long text into chunks of ≤ ~350 words on paragraph or sentence boundaries, and returns float32 lists.
   - `__main__.py` / `backfill.py`: `python -m src.cloud.publish --from <handoff file>` and
     `python -m src.cloud.backfill [--dry-run]`.
2. **Keep the bot process light and the loop free** (01 §5, R12). Embedding and uploading run in a **separate
   subprocess**, the same way the sync and reports do (`scheduler._run_module` style: venv `python.exe -m …`,
   UTF-8, no window, timeout). In-process code (watcher, brief, command answers) only writes a small JSON
   **handoff file** (`data\cloud\pending\<time>-<job>.json`, atomic write) and starts
   `python -m src.cloud.publish --from <file>` without awaiting it. The subprocess deletes the file when it is done
   (sent or failed; D6: no retry queue beyond the hash state). Subprocess jobs (`auto_sync`, `missing_report`,
   `passport_issue`, `stage_report`, `auto_verify`) call `src.cloud.publish` directly at the **end** of their
   work, after Drive, Sheets and Telegram are done.
3. **Where to hook** (find the exact lines; these are the places the reference pack names):
   - `auto_sync` after each step: students CSV (`student_export`), verified-documents list
     (`student_documents`), the notification text (`notification`), and after `auto_verify.run`: the
     `doc_verdict`, `field_check`, `field_correction`, `doc_page_text` of the students it just checked,
     plus `report`/`report_section` for DOCUMENT CHECK and FIELD CHECK.
   - `scheduler.send_daily_briefing` after the brief is sent: `report`, `report_section`, `brief_fact`, plus the
     reads `_PortalReads` made (consultation day and totals, verifications, pending payments, window
     applications, dashboard facts, calendar items).
   - `scheduler` passport watcher after it saves its memory: `student` (the full list it read, complete),
     `passport_audit`, `passport_alert`.
   - `missing_report`, `stage_report` (`student_progress`), `passport_issue --refresh` (`passport_issue`,
     `student_profile`).
   - Command handlers that read the portal (`/verified*`, `/inquiries*`, `/crosscheck*`, `/admitted`,
     `/calendar`, `/stats`, `/students`, free-text answers): publish the rows they already parsed.
     Hash dedup makes repeats free.
4. **Add a periodic "full picture" publish** so Jeannie is complete even on days nobody types a command: once an
   hour (a new `IntervalTrigger(minutes=60)` job, `max_instances=1, coalesce=True`), run a subprocess that reads
   every page of `students.php`, `students.php?status=pending`, `consult_requests.php` for today and yesterday
   plus the totals, `window_applications.php?status=under_review`, `index.php` and `calendar.php`, and publishes
   them. **GET only, through `portal_get`** (R17). It must not run in the quiet windows of 01 §5.4.
5. **Backfill** (`python -m src.cloud.backfill`), run once by the owner after deploy:
   every page of `students.php`, the CSV export, every student's `progress.php` (4 at a time, as `/stage` does),
   `consult_requests.php` for every day from the oldest `Received` date the portal's date filter returns up to today,
   the totals, pending, window applications, dashboard, calendar, then from disk: `results.json` (documents, fields,
   corrections), every `data\verification\text\*.json` (OCR pages), `data\alerted_passport_issues.json`,
   `data\passport_issue.json`, and the most recent missing report. Print progress per kind; `--dry-run` writes
   the payloads to `data\cloud\dry_run\` instead of sending, so the owner can inspect them first.
6. **Secrets** (R14): add a redaction filter for the Supabase key (`sb_secret_…`, `sb_publishable_…`, and JWT-shaped
   strings after `apikey:` / `Bearer `) to the loggers that can print requests (`httpx`, `httpcore`). Never log
   `data` or `content` (student data); log counts and timings only.
7. **Config**: in `src\config.py` `Settings`: `SUPABASE_URL: str = ""`, `SUPABASE_SECRET_KEY: str = ""`,
   `CLOUD_PUBLISH_ENABLED: bool = False` (publishing runs only when all three are set), `CLOUD_EMBED_MODEL:
   str = "thenlper/gte-small"`, `CLOUD_EMBED_REVISION: str = "<pinned>"`. Document them in `.env.example` by
   name only, and add them to `REFERENCE\secrets\README.md` §3 by name.

## Rules that stay in force

- The portal stays **read-only**: GET plus the login POST (R17, guardrails 1 and 7). Nothing here writes to
  the portal.
- R1: no placeholders in `data` or `content`. R2: complete means every page, proven by the pager total.
  R5: a failed read is never published as zero or as an empty list, and never triggers deletes. R11: stable keys,
  where placeholders such as `PENDING` are no identity.
- R12: embeddings on the CPU only; do not load torch onto the GPU for this; measure RAM and time per 100
  records and report them.
- Keep the root staging copies byte-identical (R24) if you touch `telegram_bot.py`, `config.py` or
  `progress_builder.py`.
- Never open student images. Test fixtures use synthetic names only.

## Tests (pytest, no network)

- A fake Supabase with `httpx.MockTransport` that records every call, answers `hg_sync` like the server
  (upsert by `(kind, key)`, delete by `p_all_keys` in `(kind, scope)`), and **fails the test on any other host
  or method**, the same way the fake portal does.
- Per kind: `records.py` builds the expected `key`, `scope`, `day`, `data` and `content` from synthetic reader
  output; no placeholder appears.
- Only changed rows are sent (second identical run sends 0 rows); a changed field sends exactly that row.
- A partial read (`PortalUnavailable` on page 3, or pager total mismatch) sends `p_all_keys: null` and deletes
  nothing; a complete read without a student deletes exactly that student.
- A Supabase 500, a timeout and a refused key: the job still finishes, Drive/Sheets/Telegram calls still happen,
  one log line is written, and the hash state is **not** advanced for the failed rows.
- The redaction filter hides a fake `sb_secret_…` key and a Bearer token.
- Embedding: a stub embedder in unit tests; one marked-slow test (skipped only when the model is absent, not
  in CI) checks 384 dimensions and unit length.
- All 659 existing tests still pass.

## Verify before deploy (M5)

1. `python -m src.cloud.backfill --dry-run`: inspect a few payloads per kind (show the owner counts and one
   **synthetic-looking** example per kind with personal values masked in your report, not in the payload).
2. Run the backfill for real, then check from an independent script (its own `httpx`, own SQL-free REST reads):
   `hg_records` counts per kind equal the counts the portal and files show (students = pager total; consultation
   totals = the tabs; OCR pages = the cache's page count), and every `hg_chunks.embedding` has 384 dimensions
   and one `embed_model`.
3. Deploy after the 18:05 brief has gone out (M6), full-path `stop.bat`, watch the next runs in the logs:
   `hg_runs` gets a row per job, `unchanged` grows, deletes only after complete reads.
4. Give the owner a before/after table and the list of kinds with row counts.

## Out of scope here

Creating or changing tables (the Jeannie repo owns them), Supabase Auth, the PWA, Jeannie's answers, and
uploading any binary file.

## Comments

- 1 Oct 2026: done on the PC. The bot's one-time backfill (`src.cloud.backfill`) wrote 13,540 records and 15,629
  chunks on 30 Sep 22:05, and the bot keeps them current (hourly, after its jobs and after commands). It added two
  kinds to the table above, now listed there, and the `blank_on_portal` data key: `doc_check` (one result per
  passport) and `consultant_performance` (the portal's Consultant Performance page, which answers the owner's "how
  many consultancies were closed today?"). The spec's comment of the same day records them too. From here the
  data contract's source of truth is the bot's `src/cloud/records.py` (every kind's key, scope, day, data fields
  and text) and the reference pack's `13_SUPABASE_PUBLISHING.md`; this prompt is not re-run.
