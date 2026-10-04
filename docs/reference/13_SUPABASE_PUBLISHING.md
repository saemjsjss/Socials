# 13 — Supabase publishing: a second copy of everything the bot reads, for Jeannie

**What's in this file:** the Supabase publish layer (`src\cloud\`) as a spec you can rebuild from. It covers why the layer exists (Jeannie answers from it) and the owner's decisions D1-D13. It gives the server contract of the Jeannie migration: the four `hg_*` tables, the `hg_sync` body exactly, upsert by content hash, deletes by `p_all_keys` per (kind, scope), `hg_match` and `hg_changes_since`, and the whole migration file verbatim (§3.11). It defines the record and its `content_hash`, then every one of the 26 kinds: key, scope, day, source, data, text template, when a read counts as complete, who writes it, and the live count. It explains the portal's "no value" words, Cloudflare's hidden e-mails and `data.blank_on_portal`. It describes the publish engine (hash state, read ordering, batching at 200 rows / 250 chunks / 1 MB, runs, the lock, the dry run), gte-small on the CPU, the handoff file and the publisher process, failure isolation (D6), the hourly full picture, the backfill CLI, and settings and packages. For day-2 operations it covers turning publishing on and off, re-running the backfill, reading `hg_runs` and the dry-run and postcheck method. It ends with the live numbers after the 30 Sep backfill, the first automatic runs, and what is still open.
**Pack written:** 30 September 2026 (Asia/Dhaka), from `C:\Hangeul\BOT` at `main` = `8317741`. This file is new in the pack's refresh from `c17d887` (29 Sep) to `8317741`. The server side is read from `C:\Hangeul\JARVIS\Jeenie-saem-bot` at `31202e9`, `supabase\migrations\20260929030000_hangeul_context.sql` (cited as `hangeul_context.sql:line`). Bot line numbers are `path:line` at `8317741`.
**Read with:** [03d](03d_FILES_src_cloud.md) (every function of `src\cloud\` with its signature, and every hook call site in the rest of the code), [01](01_ARCHITECTURE.md) (the processes; the quiet windows are in §5.4), [04](04_PORTAL_INTEGRATION.md) (the portal pages), [05](05_TELEGRAM_COMMANDS_AND_JOBS.md) (the jobs and commands that publish), [07](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md) (`results.json` and the OCR text caches), [09](09_BLUEPRINT_RULES_AND_LESSONS.md) (R1, R2, R5, R11, R12, R14), [10](10_TESTS_AND_VERIFICATION.md) (the test suite), [08](08_HISTORY_STAGE_BY_STAGE.md) (the history), [11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md) (open items), [02](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md) (install and `.env`), [secrets/README.md](secrets/README.md) and the index [00](00_INDEX.md). Secret values never appear here; each is written "value in secrets/bot.env (KEY)". Student data never appears; keys and texts are shown with `<placeholders>`.

---

## 0. At a glance

Every portal page the bot parses, every report it builds and every local store it keeps (`results.json`, the OCR text caches, the watcher's memory, the issue dates) is also written to the owner's Supabase project **`dcbcbpwpmdtaanboetiz`** (`https://dcbcbpwpmdtaanboetiz.supabase.co`, region ap-northeast-1). It goes there in three forms: structured rows, an English text form, and 384-number gte-small embeddings of that text. Drive, Sheets, the `.xlsx` reports and Telegram are unchanged. Supabase is added beside them; it never delays or blocks them, and a failure there costs one log line.

```
 what a job already read or built (after the job's own work: Drive, Sheets, .xlsx, Telegram)
        │
        ▼
 src.cloud.records ── one pure function per kind: reader output -> records
        │              {kind, key, scope, student_uid, student_hng_id, student_name, passport_no,
        │               day, data, content, content_hash, source, read_at}
        │              grouped as batch(kind, scope, rows, complete[, all_keys, read_at])
        │                     or batches(kind, rows, complete[, scope_range, read_at])
        ▼
 bot process (watcher, brief, commands)            CPU-only processes (CUDA_VISIBLE_DEVICES=-1):
 and sheet jobs (auto_sync, reports):
 src.cloud.handoff.submit(job, batches) ─────────► python -m src.cloud.publish --from data\cloud\pending\<time>-<job>.json
   one JSON file + a child process,                 python -m src.cloud.full_picture   (hourly, reads the portal itself)
   never waited for                                 python -m src.cloud.backfill       (once, by hand)
                                                         │ publish_batches -> publish(kind, scope, rows, complete)
                                                         │ hash state data\cloud_state.json: only changed rows go
                                                         │ gte-small @17e1f347, float32, CPU -> chunks of <=350 words
                                                         │ POST /rest/v1/hg_runs         (status null)
                                                         │ POST /rest/v1/rpc/hg_sync     (<=200 rows, <=1,000,000 bytes, p_all_keys on the last call)
                                                         │ PATCH /rest/v1/hg_runs?id=eq.<run>
                                                         ▼
                             Supabase: hg_runs, hg_records, hg_chunks, hg_changes (filled by a trigger)
                                                         │
                                                         ▼
                             Jeannie (server and PWA): PostgREST reads, hg_match, hg_changes_since
```

**The live state on 30 Sep 2026.** The real backfill ran 21:48-22:05: 13,540 records, 15,629 chunks, 0 failed reads, `hg_runs` status ok. An independent postcheck verified every kind key for key. Publishing went on at 22:27 (`CLOUD_PUBLISH_ENABLED=true`). The first automatic runs were `full_picture` at 22:35 (3 upserted, 779 unchanged) and `portal_sync` at 22:43 (976 unchanged). The numbers are in §16.

---

## 1. Purpose: who reads it

- **Jeannie** is the owner's web/PWA assistant (the repo `munim430-ai/Jeenie-saem-bot`, cloned at `C:\Hangeul\JARVIS\Jeenie-saem-bot`). The goal is that the owner asks anything about the agency on the phone and Jeannie answers at once from rows the bot already read, with an "as of HH:MM" label, while the office PC may be asleep. There is no inbound connection to the PC (D4).
- **The reader side is specified and being built, not yet merged.** Jeannie's design is `.scratch\hangeul-cloud-context\spec.md` (at `31202e9` its status line reads "needs-triage", a draft awaiting the owner). It has code-built answers from rows, `hg_match` for semantic search, a phone copy in IndexedDB synced through `hg_changes_since`, and an embed-model check with cosine at or above 0.98. The clone at `31202e9` still answers Hangeul questions through its old portal bridge (`src\lib\agents\hangeul-bridge.ts`), which serves demo data: it calls portal JSON endpoints (`HANGEUL_REPORT_PATH`, `HANGEUL_STATUS_PATH`) that the portal does not have, and any failed live request falls back to demo data (`hangeul-bridge.ts:395`), as do mock mode, an unconfigured portal and a caller without the access key (`:378-382`). At 30 Sep 23:48 the owner approved building the reader here ("Yes, build it here (Recommended)"): workflow `wf_1a222cb1-960` (task `wj3vsplug`), in the worktree `C:\Hangeul\JARVIS\jeannie-hg`, branch `saem/hangeul-context-reader`, based on `origin/main` `f7bbdca` (PR #12; the local clone's `main` is still `31202e9`, behind the remote), with Node.js v22.23.3 from `C:\Hangeul\JARVIS\tools\node\node-v22.23.3-win-x64` (no system install). It is in progress and unmerged ([11 B26](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)). So on 30 Sep the data is complete in Supabase and Jeannie does not read it yet. The owner still has to tell Jeannie's side about the two added kinds (`doc_check`, `consultant_performance`) and the added data key `blank_on_portal` ([11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)).
- **Why structured rows and text and vectors (D3):** every figure Jeannie states must come from a row (the pack's R7: the LLM never states a figure). The text and vectors are only for finding the right rows from a fuzzy question.

---

## 2. The owner's decisions (D1-D13) and the decisions taken in the build

The owner's spec is `C:\Users\User\Downloads\hangeul-bot-prompt.md` (the same file is in the Jeannie repo as `.scratch\hangeul-cloud-context\hangeul-bot-prompt.md`). Its decisions were not re-opened:

| # | Decision | Where it lives in the code |
|---|---|---|
| D1 | **Full student data** goes to Supabase, nothing masked: names, phones, e-mails, passport numbers, DOB, parents' names, addresses, every parsed field. | `records.py` keeps every reader field in `data` (only the volatile ones, §5.1, are dropped) |
| D2 | **Scope = everything parsed from the portal plus every report the bot builds**, including the **full OCR text** of student documents (one record per page). **No binary files** (no PDF, JPG, PNG, ZIP, scans). | 26 kinds (§5); `doc_page_text` from the OCR caches; `.xlsx` reports are published from the data they are built from, never uploaded |
| D3 | **Both** structured rows (the source of every figure) **and** text with embeddings. | `data` + `content` + `hg_chunks` |
| D4 | Answers are snapshots: every row carries `read_at`; no inbound connection to the PC. | `records.as_read_at` (`records.py:75`) |
| D5 | The bot writes with the project's **secret key** from `.env` (PostgREST + RPC), not through an Edge Function. | `publish._client` (`publish.py:342`) |
| D6 | Supabase is **independent**: down or refusing, it costs **one log line** and the job goes on. No outbox, no retries in a run, no Telegram alert, never blocking Drive, Sheets or Telegram. A row that failed goes again next run because the hash state advances only on acceptance. | §10 |
| D7 | Embeddings **on this PC, on the CPU**, with **gte-small** (384 dimensions, mean pooling, L2-normalised), the model Jeannie uses (`Supabase/gte-small`, the ONNX export of `thenlper/gte-small`). | `embed.py` (§8) |
| D8 | **One record per entity** (a student, a request, a verification, a verdict, an alert, a calendar item, one OCR page); reports split into one record per section or student line; not fixed-size chunks. | `records.py`; `report` + `report_section` |
| D9 | Upload **only changed rows** (content hash), like `data\sheet_state.json` for the sheets. | the hash state `data\cloud_state.json` (§7.2) |
| D10 | What disappears from a **complete** read is **hard-deleted** in Supabase (the change log keeps only kind, key and the time). | `p_all_keys` (§3.8, §7.4) |
| D11 | A **one-time backfill** of all existing data, including `data\verification\results.json` (the only copy of the Corrections history), the OCR caches and the watcher memory. | `python -m src.cloud.backfill` (§12) |
| D12 | The **schema is owned by the Jeannie repo** (`supabase\migrations\`). The bot only writes rows and never creates or alters tables. | the bot makes no DDL call; the migrations were applied with the Supabase CLI from the Jeannie clone (§3.1) |
| D13 | Credential rotation is **deferred** by the owner (accepted risk). Still never print, log or commit a secret value. | the log redaction in `src\__init__.py:38-79` (§14.2) |

Decisions taken during the build (29-30 Sep), each with its reason:

| # | Decision | Why |
|---|---|---|
| B1 | The hourly job is named **`full_picture`** (`src\cloud\__init__.py:23`, `full_picture.py:57`). | The spec's job list had no name for it; `hg_runs.job` has no check constraint. |
| B2 | Kind **`doc_check`** is added (one record per passport: the student-level verdict and its counts). | No document row carries the student's overall verdict. |
| B3 | Kind **`consultant_performance`** is added: the portal's Consultant Performance page, one record per leaderboard row plus a summary, scope `"<period>\|<first ISO day>"`. | The page's data fits no spec kind. The scope leaves out the last day because the portal ends every period at today, so a scope holding it would change daily and old rows would never be deleted (fixed in `8317741` before publishing went on). |
| B4 | The portal's own filler words ("N/A", "None", "--", "PENDING", Cloudflare's "[email protected]"...) are `""` in `data` and left out of the text, and their field names go into **`data.blank_on_portal`**. | R1: no placeholder may be presented as data. The first live dry run found 45 "N/A" and 7 "PENDING" cells kept as values. The list lets Jeannie say "not given on the portal". |
| B5 | Cloudflare's e-mail obfuscation is decoded at every soup (`parsers.decode_cf_emails`). | The second dry run found every student's e-mail stored as "[email protected]" (333 records) and 1,005 consultation contacts with it. |
| B6 | CUDA is hidden with **`CUDA_VISIBLE_DEVICES=-1`**, not `""`. | On Windows an empty value never reaches the real process environment (§8.1). |
| B7 | Calls are split to **at most 1,000,000 bytes** of JSON. | Dry run 1 had a 1.98 MB body (200 students with full details); the gateway's real limit was never measured. |
| B8 | A model that cannot load, or a Supabase that is down, costs **one line for the whole run**, not one per publish. | Dry run 1 would have written about 600 identical lines (one per (kind, scope)). |
| B9 | A local **student index** (`data\cloud\student_index.json`) gives passport-keyed records their portal uid and HNG id. | `results.json` and the OCR caches know a student by passport number only, and Jeannie filters by `student_uid`. |
| B10 | Reads are **ordered by `read_at`**: an older complete read never deletes what a newer read showed, and an older version of a record is never sent over a newer one. | The watcher hands its list over up to 20 minutes after reading it, so publishers can see reads out of order. |
| B11 | **One publisher at a time** (an OS lock on `data\cloud\publish.lock`). | Two publishers on one (kind, scope) could let an older key list delete a row a newer call just inserted, while the newer state marks it sent. |
| B12 | Publishing is **off by default** (`CLOUD_PUBLISH_ENABLED=False`). Nothing is published while it is off. In mock mode the bot-process hooks (commands, the brief, the watcher: `command_hooks.active`, `command_hooks.py:74-84`; `bot_jobs.hand_over`, `bot_jobs.py:75`) and the full picture (`full_picture.run`, `full_picture.py:137`) publish nothing, while the sheet jobs (which read the live portal whatever `MOCK_MODE` says; `sheet_hooks.on` / `hand_over` check only `handoff.enabled()`, `sheet_hooks.py:56-77`) and the backfill (no mock check of its own, `backfill.py:638`; its disk part publishes as usual) still publish (§7.1). | The code was deployed first with publishing off (21:47) and switched on only after the backfill and the postcheck. |
| B13 | The backfill also reads the performance page (2 GETs) (`8317741`). | The preflight recommended it (an INFO item, optional), so the one-time copy covers every kind the portal shows. |

---

## 3. The server contract (the Jeannie migration)

The contract below is taken from the SQL, which is authoritative where it differs from the spec (the differences are §3.10; the whole SQL is §3.11). Nothing in the bot creates or changes it.

### 3.1 The migrations and how they were applied

`C:\Hangeul\JARVIS\Jeenie-saem-bot\supabase\migrations\` holds four files, all applied on 29 Sep 2026 around 10:30 with `supabase link --project-ref dcbcbpwpmdtaanboetiz` then `supabase db push --yes` (after a `db push --dry-run`). `supabase migration list` then showed local = remote for all four. No database password was needed (the CLI used a temporary login role).

| File | What it does |
|---|---|
| `20260928000000_jeannie_memory.sql` | Jeannie's own memory: `memory_documents`, `memory_chunks`, `jeannie_sessions`, `jeannie_audit_log`, RPCs `upsert_memory_document` and `match_memory` (service_role only) |
| `20260928180000_jeannie_memory_revoke_public.sql` | Revokes the memory tables and sequences from `anon` and `authenticated` |
| `20260929030000_hangeul_context.sql` | **The Hangeul context:** `hg_runs`, `hg_records`, `hg_chunks`, `hg_changes`, the change-log trigger, RPCs `hg_sync`, `hg_match`, `hg_changes_since`, the access model (337 lines) |
| `20260929030100_jeannie_memory_grant_service_role.sql` | Grants the memory tables to `service_role` explicitly (new projects no longer grant table access to the API roles automatically) |

The CLI is `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe` (v2.118.0, checksum-verified). It was run from the Jeannie clone with its personal access token taken from `.env` into the CLI's own process environment, never on a command line: value in secrets/bot.env (SUPABASE_ACCESS_TOKEN). The bot never reads that key. The migration refuses to adopt an `hg_records` it did not create (`hangeul_context.sql:18-25`: the table comment must start `hangeul_context v1`). Every statement is idempotent.

### 3.2 Access model (`hangeul_context.sql:321-337`)

- RLS is **enabled with no policies** on all four tables, and every privilege is revoked from `public`, `anon` and `authenticated`. Only the secret (service_role) key gets through: Jeannie's server, and the bot writing through `hg_sync`.
- `service_role` gets select/insert/update/delete on the four tables, `usage, select` on `hg_changes_seq_seq`, and execute on `hg_sync`, `hg_match` and `hg_changes_since`. The trigger function `public.hg_log_change()` is revoked from `public`, `anon` and `authenticated` and granted to no API role; the trigger still fires on every write through `hg_sync` (the postcheck found 13,540 upserts logged in `hg_changes`). The exact block is in §3.11 (`:319-337`).
- The postcheck confirmed that a GET with no key gets **HTTP 401** on every table, and so does an invented publishable key.
- Extensions: `vector` and `pg_trgm`, in schema `extensions` (`hangeul_context.sql:13-14`). The linked project runs PostgREST v14.5 and Postgres 17.6 (from the CLI cache).

### 3.3 `hg_runs`: one row per job run (`hangeul_context.sql:31-39`)

| Column | Type | Rule |
|---|---|---|
| `id` | uuid, PK, default `gen_random_uuid()` | the bot sends its own `uuid4` |
| `job` | text, not null | **no check constraint**; the bot's names are `src.cloud.JOBS` (§7.7) |
| `started_at` | timestamptz, not null, default now() | |
| `finished_at` | timestamptz, null | set by the bot's closing PATCH |
| `status` | text, check in (`ok`, `partial`, `failed`) or null | null while running |
| `counts` | jsonb, **not null**, default `{}` | never send null (23502) |
| `note` | text, null | a short plain reason |

Index `hg_runs_job_started_idx (job, started_at desc)`. Never delete a run: `hg_records.run_id` is `on delete set null`, and no change-log entry is written for that.

### 3.4 `hg_records`: the latest state of every entity (`hangeul_context.sql:42-61`)

| Column | Type | Rule |
|---|---|---|
| `kind` | text, not null, `<> ''` | any non-empty text (no list) |
| `key` | text, not null, `<> ''` | stable id within the kind |
| `scope` | text, not null, `<> ''` | what one complete read covers (for deletes) |
| `student_uid` | integer, null | portal user id (`student_edit.php?id=N`) |
| `student_hng_id` | text, null | `HNG-YYYY-N` |
| `student_name` | text, null | as the portal prints it |
| `passport_no` | text, null | for joins and exact lookups |
| `day` | date, null | business day, Asia/Dhaka |
| `data` | jsonb, not null, must be an object | every parsed field |
| `content` | text, not null (`""` allowed) | the text form |
| `content_hash` | text, not null, `<> ''` | opaque to the server: compared for equality only |
| `source` | text, not null | where it came from |
| `read_at` | timestamptz, not null | |
| `run_id` | uuid, FK `hg_runs(id)` on delete set null | |
| `updated_at` | timestamptz, not null, default now() | set by the server |

Primary key `(kind, key)`: a key lives in exactly one scope at a time. The table comment is `hangeul_context v1: ...`. Indexes (`:88-97`): `(kind, scope)`, `(kind, day)`, `student_uid`, `student_hng_id` and `passport_no` (each partial, where not null), a trigram GIN index on `lower(student_name)`, `updated_at` and `run_id`.

### 3.5 `hg_chunks` and `hg_changes` (`hangeul_context.sql:64-84`, trigger `:103-128`)

- **`hg_chunks`**: `kind`, `key`, `ord` (integer, at least 0), `content` (text), `embedding extensions.vector(384)`, `embed_model` (text, `<> ''`). PK `(kind, key, ord)`, FK `(kind, key)` to `hg_records` **on delete cascade**, and an HNSW index with `vector_cosine_ops`.
- **`hg_changes`** is the change log for device sync. `seq` (bigint identity PK), `kind`, `key`, `op` (`upsert` or `delete`), `data` (jsonb, **null for a delete**: D10), `changed_at` (default now()), `run_id` (no FK: the log outlives runs). It is filled **only by the trigger** `hg_records_log_change`, which runs `after insert or update or delete ... for each row execute function public.hg_log_change()` (a `plpgsql`, `security invoker`, `set search_path = ''` function):
  - an insert logs `upsert` with the new `data`;
  - an update logs only when `content_hash` changed (`new.content_hash is not distinct from old.content_hash` → nothing logged);
  - a delete logs `delete` with `data` null.
  The run id is `v_run := nullif(current_setting('hangeul.run_id', true), '')::uuid`, the transaction-local setting that `hg_sync` sets from `p_run` (`perform set_config('hangeul.run_id', coalesce(p_run::text, ''), true)`). An insert or update logs `coalesce(v_run, new.run_id)` (the setting, else the row's `run_id`); **a delete logs `v_run` only**, so it is null outside `hg_sync` (for example when `hg_records` is cleared by hand, as in §15.6). The bot never writes this table. The function verbatim is in §3.11 (`:103-128`).

### 3.6 `hg_sync`: the bot's one write call (`hangeul_context.sql:137-240`)

`POST {SUPABASE_URL}/rest/v1/rpc/hg_sync`. It must be POST: a GET would run in a read-only transaction. The headers are `apikey: <key>`, `Authorization: Bearer <key>`, `Content-Type: application/json` and `Accept: application/json`, where the key is the value in secrets/bot.env (SUPABASE_SECRET_KEY). The client timeout is 30 s. The signature is `hg_sync(p_run uuid, p_kind text, p_scope text, p_rows jsonb, p_all_keys text[] default null) returns jsonb`, security invoker, `search_path ''`.

The body exactly as the bot writes it (compact JSON, `ensure_ascii=False`, `allow_nan=False`, `publish._body`, `publish.py:338`):

```json
{"p_run": "<uuid of the run, or null when its hg_runs POST failed>",
 "p_kind": "student",
 "p_scope": "all",
 "p_rows": [
   {"key": "<uid>",
    "student_uid": <uid as a JSON integer>, "student_hng_id": "HNG-2026-<n>", "student_name": "<name>",
    "passport_no": "<passport>", "day": "2026-09-12",
    "data": {"uid": "<uid>", "student_id": "HNG-2026-<n>", "...": "every parsed field"},
    "content": "Student <name> (HNG-2026-<n>, portal uid <uid>). Program ...",
    "content_hash": "<sha256 hex>",
    "source": "students.php",
    "read_at": "2026-09-30T21:49:02+06:00",
    "chunks": [{"ord": 0, "content": "<chunk text>",
                "embedding": [0.0123, -0.0456, "... 384 numbers ..."],
                "embed_model": "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd"}]}
 ],
 "p_all_keys": ["<every key of the (kind, scope)>", "..."]}
```

- `p_run`, `p_kind`, `p_scope` and `p_rows` are required and `p_all_keys` is optional (`default null`); the bot always sends all five. PostgREST matches argument names, so any other top-level key, or a missing required one, gives PGRST202 (404). `p_all_keys` is `null` except on the **last call of a complete read** (§7.4).
- `p_rows` may be `[]`: that is a delete-only call. At most 200 rows (checked first; 22023). The server ignores `kind`, `scope`, `run_id` and `updated_at` on a row: the call-level values are used.
- `student_uid` must be a JSON integer (a digit string also casts; a float such as `<uid>.0` fails 22P02), `day` must be `YYYY-MM-DD`, and `read_at` needs an offset (without one the server reads it as UTC). `null` and `""` become SQL NULL for the optional columns.
- Each embedding number is written with 8 significant digits (`float(f"{x:.8g}")`, `publish.py:582`).
- **The answer** is HTTP 200 `{"upserted": n, "deleted": m, "unchanged": k}`, with upserted + unchanged = the rows sent. Each call is **one transaction**: a 2xx means every row was taken; anything else means none was, and no delete happened either.

Validation, in order, for every row before it is written (errors 22023 unless noted):

1. `p_kind` and `p_scope` not null or `""`; `p_rows` a JSON array of at most 200.
2. The row is an object with a non-empty `key`.
3. `data` is an object.
4. `content` is a JSON string, and `content_hash`, `source` and `read_at` are non-empty.
5. `chunks` (missing counts as `[]`, but `null` fails) is an array.
6. Every chunk has an `embedding` array of exactly 384 numbers and a non-empty `embed_model` that is **the same for every chunk in the whole call**.

Implicit errors: 22P02 (a bad uuid, a non-integer `student_uid` or `ord`, a non-number in an embedding); 22003 (`student_uid` out of int4); 22007/22008 (a bad `day` or `read_at`); **23503 (409) when `p_run` is not an `hg_runs.id`** (hence `p_run` null when the run POST failed, `publish.py:759`); 23502/23514/23505 for a missing, negative or duplicate `ord`; 22P05 for a NUL character or an unpaired surrogate (removed by `records.clean_text`); 42501 for the wrong role; 57014 for a statement timeout (the project's role timeout applies). Server messages that name "row K" quote the key, and keys hold passport numbers, so the bot never logs a server message (§7.6).

### 3.7 Upsert by hash (`hangeul_context.sql:198-229`)

`insert ... on conflict (kind, key) do update set <every column> ... where r.content_hash is distinct from excluded.content_hash`, then `get diagnostics v_changed = row_count`: 0 rows affected means the hash was the same (`unchanged`), 1 means inserted or updated (`upserted`). A changed row's chunks are then replaced with `delete from public.hg_chunks where kind = p_kind and key = v_key` and an insert of each sent chunk as `(c ->> 'ord')::integer, c ->> 'content', (c -> 'embedding')::text::extensions.vector(384), c ->> 'embed_model'` (the JSON array's text is cast to a vector). The loop verbatim is in §3.11 (`:198-229`).

- **New row, or a different hash:** counted `upserted`. Every column is rewritten, **all the record's chunks are deleted and exactly the chunks sent are inserted**. A changed row sent with no chunks would lose its vectors and become unfindable by `hg_match`, so the bot always embeds a changed row.
- **Same hash:** counted `unchanged`, and **nothing** is written: not `read_at`, `run_id`, `scope`, `source`, the `student_*` columns, `day` or the chunks.
- Consequences the bot is built around:
  1. Everything outside the hash (the `student_*` columns, `day`, `source`, `read_at`, the chunks and `embed_model`) is written only when the hash changes. So these values must be **derived from the hashed fields** (key, scope, data, content). That is why passport-keyed kinds put the uid and HNG id into `data` (`records._with_ids`, `records.py:1148`).
  2. A model change never replaces chunks by itself. Hence the local `embed_model` guard (§7.9).
  3. `read_at` is the time of the read that last **changed** the row. "As of" freshness comes from `hg_runs` (`finished_at`, `status`), and the bot never changes a hash just to refresh `read_at`.
  4. A scope is part of the hash, so a changed update can move a record to another scope.
  5. Resending is safe: a call that committed but was never answered gives `unchanged` when repeated.

### 3.8 Deletes with `p_all_keys` (`hangeul_context.sql:232-236`)

After all rows, in the same transaction:

```sql
if p_all_keys is not null and not (p_kind = any (array['field_correction'])) then
  delete from public.hg_records
  where kind = p_kind and scope = p_scope and not (key = any (p_all_keys));
```

- `null` (or left out) deletes nothing. **`[]` deletes every row of that (kind, scope)**: send it only when a complete read proved there are zero items (the backfill did this for `window_application`).
- The list must hold **every key of the (kind, scope)**, including the rows upserted in the same call; a key sent in `p_rows` but missing from the list is upserted and then deleted. A `null` element weakens the delete (NULL logic), so never send one. Keys match as exact, case-sensitive text.
- Deletes cascade to the chunks, write one `delete` change each, and are **per (kind, scope) only**: removing a student removes none of their profile, progress or verification rows.
- `field_correction` is append-only: the list is ignored there and 0 is deleted.
- **The server cannot know whether a read was complete; the bot is the only safeguard** (R2, R5). Every kind's complete rule is in §5.

### 3.9 Reads: `hg_match` and `hg_changes_since` (used by Jeannie; the bot never calls them)

```sql
hg_match(p_embedding extensions.vector(384), p_count integer default 12, p_kinds text[] default null,
         p_day_from date default null, p_day_to date default null, p_student_uid integer default null)
  returns table (kind, key, ord, content, similarity double precision, data jsonb, day date,
                 read_at timestamptz, student_uid integer, student_hng_id text, student_name text)
```

Both read functions are `language sql stable security invoker set search_path = ''` (§3.11). `hg_match` joins chunks to records, filters by kinds, `day` range and `student_uid`, orders by cosine distance (`<=>`) and returns `similarity = 1 - distance`, with `limit least(greatest(coalesce(p_count, 12), 1), 100)` (`hangeul_context.sql:244-280`). A record without chunks, `day` or `student_uid` cannot be found by the matching filter, which is why the bot fills them wherever they apply.

```sql
hg_changes_since(p_seq bigint, p_limit integer default 1000)
  returns table (seq bigint, kind text, key text, op text, changed_at timestamptz, run_id uuid,
                 record jsonb, chunks jsonb)
```

It returns the changes after `p_seq` in `seq` order, limited to `least(greatest(coalesce(p_limit, 1000), 1), 5000)`. For an `upsert` it carries the **current** record (`to_jsonb(r)`) and its chunks (`[{ord, content, embedding as real[], embed_model}]` by `ord`); both are null when the record has been deleted since, and that delete follows later in the feed (`hangeul_context.sql:286-317`).

### 3.10 Where the SQL and the spec differ (the bot follows the SQL)

1. `hg_sync` also returns `unchanged`; the bot reads all three counts.
2. The server replaces chunks only when the hash changes (§3.7).
3. `p_run` must exist in `hg_runs` or be null; the spec did not say so.
4. `p_all_keys: []` deletes a whole scope, and the list must include the keys upserted in the same call.
5. The scope is per call, so records are grouped by (kind, scope) and one set of calls is made per group.
6. `hg_runs.counts` is not null, `hg_runs.job` is unchecked, and the spec's job list lacked the hourly job.
7. Any non-empty kind is accepted, so `doc_check` and `consultant_performance` needed no migration (Jeannie still has to learn them).
8. There is no byte limit on the server; the 1 MB cap is the bot's own (§7.5).
9. `embed_model` "identical on every row" is enforced by the server only **within one call**; across calls it is the bot's guard (§7.9).

### 3.11 The migration verbatim (`20260929030000_hangeul_context.sql`, Jeenie-saem-bot@`31202e9`)

The whole 337-line file, copied byte for byte from `C:\Hangeul\JARVIS\Jeenie-saem-bot\supabase\migrations\20260929030000_hangeul_context.sql` (it holds no secret and no student data). A rebuild puts this file into the reader repo's `supabase\migrations\` and applies it as in §3.1; the sections above explain it line by line.

```sql
-- Hangeul context: everything Hangeul BOT reads from the portal and every report
-- it builds, published from the office PC so Jeannie can answer from it.
-- Contract: .scratch/hangeul-cloud-context/spec.md §4 and hangeul-bot-prompt.md
-- ("The data contract"). A change here means a change there too.
--
-- Access model (same as the memory tables): RLS is on for every table with NO
-- policies, and the public roles lose every privilege, so the anon and
-- authenticated keys can read or write nothing. Only the secret / service-role
-- key gets through: Jeannie's server, and the office bot writing via hg_sync.
--
-- Safe to run again: every statement is idempotent.

create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- Refuse to adopt hg_* tables that some other script created with a different
-- shape: this file marks its own tables, and re-running it is fine.
do $$
begin
  if to_regclass('public.hg_records') is not null
     and coalesce(obj_description(to_regclass('public.hg_records'), 'pg_class'), '') not like 'hangeul_context v1%' then
    raise exception 'public.hg_records already exists but was not created by the hangeul_context migration. Drop the hg_* tables (or ask Jeannie''s maintainer) before running this.';
  end if;
end;
$$;

-- ─── Tables ──────────────────────────────────────────────────────────────────

-- One row per bot job run. The bot inserts it at the start (status null) and
-- patches it at the end.
create table if not exists public.hg_runs (
  id          uuid primary key default gen_random_uuid(),
  job         text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text check (status in ('ok', 'partial', 'failed')),
  counts      jsonb not null default '{}'::jsonb,
  note        text
);

-- The latest state of every entity: one row per (kind, key).
create table if not exists public.hg_records (
  kind           text not null check (kind <> ''),
  key            text not null check (key <> ''),
  scope          text not null check (scope <> ''),   -- what one complete read covers (for deletes)
  student_uid    integer,                              -- portal user id (student_edit.php?id=N)
  student_hng_id text,                                 -- HNG-YYYY-N
  student_name   text,
  passport_no    text,
  day            date,                                 -- business day, Asia/Dhaka
  data           jsonb not null check (jsonb_typeof(data) = 'object'),
  content        text not null,                        -- text form, built by the bot's code
  content_hash   text not null check (content_hash <> ''),
  source         text not null,
  read_at        timestamptz not null,
  run_id         uuid references public.hg_runs (id) on delete set null,
  updated_at     timestamptz not null default now(),
  primary key (kind, key)
);

comment on table public.hg_records is 'hangeul_context v1: latest state of everything Hangeul BOT publishes';

-- Embeddings of each record (gte-small, 384-d, mean pooled, L2-normalised).
create table if not exists public.hg_chunks (
  kind        text not null,
  key         text not null,
  ord         integer not null check (ord >= 0),
  content     text not null,
  embedding   extensions.vector(384) not null,
  embed_model text not null check (embed_model <> ''),
  primary key (kind, key, ord),
  foreign key (kind, key) references public.hg_records (kind, key) on delete cascade
);

-- Change log for device sync. Filled only by the trigger below; the bot never writes it.
create table if not exists public.hg_changes (
  seq        bigint generated always as identity primary key,
  kind       text not null,
  key        text not null,
  op         text not null check (op in ('upsert', 'delete')),
  data       jsonb,                                    -- null for a delete (only kind, key and time are kept)
  changed_at timestamptz not null default now(),
  run_id     uuid                                      -- no foreign key: the log outlives runs
);

-- ─── Indexes ─────────────────────────────────────────────────────────────────

create index if not exists hg_runs_job_started_idx on public.hg_runs (job, started_at desc);
create index if not exists hg_records_kind_scope_idx on public.hg_records (kind, scope);
create index if not exists hg_records_kind_day_idx on public.hg_records (kind, day);
create index if not exists hg_records_student_uid_idx on public.hg_records (student_uid) where student_uid is not null;
create index if not exists hg_records_hng_id_idx on public.hg_records (student_hng_id) where student_hng_id is not null;
create index if not exists hg_records_passport_idx on public.hg_records (passport_no) where passport_no is not null;
create index if not exists hg_records_name_trgm_idx on public.hg_records using gin (lower(student_name) extensions.gin_trgm_ops);
create index if not exists hg_records_updated_idx on public.hg_records (updated_at);
create index if not exists hg_records_run_idx on public.hg_records (run_id);
create index if not exists hg_chunks_embedding_idx on public.hg_chunks using hnsw (embedding extensions.vector_cosine_ops);

-- ─── Change-log trigger ──────────────────────────────────────────────────────
-- An insert logs an upsert; an update logs only when content_hash changed; a
-- delete logs data = null. The run comes from hg_sync (hangeul.run_id setting).

create or replace function public.hg_log_change()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_run uuid := nullif(current_setting('hangeul.run_id', true), '')::uuid;
begin
  if tg_op = 'DELETE' then
    insert into public.hg_changes (kind, key, op, data, run_id) values (old.kind, old.key, 'delete', null, v_run);
    return old;
  end if;
  if tg_op = 'UPDATE' and new.content_hash is not distinct from old.content_hash then
    return new;
  end if;
  insert into public.hg_changes (kind, key, op, data, run_id)
  values (new.kind, new.key, 'upsert', new.data, coalesce(v_run, new.run_id));
  return new;
end;
$$;

drop trigger if exists hg_records_log_change on public.hg_records;
create trigger hg_records_log_change
  after insert or update or delete on public.hg_records
  for each row execute function public.hg_log_change();

-- ─── RPC: the bot's one write call ───────────────────────────────────────────
-- Upserts each changed row on (kind, key) and replaces its chunks; unchanged
-- rows (same content_hash) are left alone. When p_all_keys is given (a COMPLETE
-- read of that kind and scope), every other row of that (kind, scope) is
-- deleted. Append-only kinds are never deleted. All or nothing: any invalid row
-- rejects the whole call.

create or replace function public.hg_sync(
  p_run      uuid,
  p_kind     text,
  p_scope    text,
  p_rows     jsonb,
  p_all_keys text[] default null
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  append_only constant text[] := array['field_correction'];
  v_row       jsonb;
  v_chunk     jsonb;
  v_key       text;
  v_model     text;
  v_changed   integer;
  v_upserted  integer := 0;
  v_unchanged integer := 0;
  v_deleted   integer := 0;
begin
  if coalesce(p_kind, '') = '' or coalesce(p_scope, '') = '' then
    raise exception 'hg_sync: p_kind and p_scope are required' using errcode = '22023';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'hg_sync: p_rows must be a JSON array' using errcode = '22023';
  end if;
  if jsonb_array_length(p_rows) > 200 then
    raise exception 'hg_sync: at most 200 rows per call (got %)', jsonb_array_length(p_rows) using errcode = '22023';
  end if;

  perform set_config('hangeul.run_id', coalesce(p_run::text, ''), true);

  for v_row in select value from jsonb_array_elements(p_rows) loop
    v_key := v_row ->> 'key';
    if jsonb_typeof(v_row) <> 'object' or coalesce(v_key, '') = '' then
      raise exception 'hg_sync: every row needs a non-empty key' using errcode = '22023';
    end if;
    if jsonb_typeof(v_row -> 'data') is distinct from 'object' then
      raise exception 'hg_sync: row %: data must be a JSON object', v_key using errcode = '22023';
    end if;
    if jsonb_typeof(v_row -> 'content') is distinct from 'string'
       or coalesce(v_row ->> 'content_hash', '') = ''
       or coalesce(v_row ->> 'source', '') = ''
       or coalesce(v_row ->> 'read_at', '') = '' then
      raise exception 'hg_sync: row %: content, content_hash, source and read_at are required', v_key using errcode = '22023';
    end if;
    if jsonb_typeof(coalesce(v_row -> 'chunks', '[]'::jsonb)) <> 'array' then
      raise exception 'hg_sync: row %: chunks must be a JSON array', v_key using errcode = '22023';
    end if;
    for v_chunk in select value from jsonb_array_elements(coalesce(v_row -> 'chunks', '[]'::jsonb)) loop
      if jsonb_typeof(v_chunk -> 'embedding') is distinct from 'array' or jsonb_array_length(v_chunk -> 'embedding') <> 384 then
        raise exception 'hg_sync: row %: every chunk embedding must have 384 numbers', v_key using errcode = '22023';
      end if;
      if coalesce(v_chunk ->> 'embed_model', '') = '' or (v_model is not null and v_chunk ->> 'embed_model' <> v_model) then
        raise exception 'hg_sync: one embed_model per call (row %)', v_key using errcode = '22023';
      end if;
      v_model := v_chunk ->> 'embed_model';
    end loop;

    insert into public.hg_records as r (
      kind, key, scope, student_uid, student_hng_id, student_name, passport_no, day,
      data, content, content_hash, source, read_at, run_id, updated_at
    ) values (
      p_kind, v_key, p_scope,
      nullif(v_row ->> 'student_uid', '')::integer,
      nullif(v_row ->> 'student_hng_id', ''),
      nullif(v_row ->> 'student_name', ''),
      nullif(v_row ->> 'passport_no', ''),
      nullif(v_row ->> 'day', '')::date,
      v_row -> 'data', v_row ->> 'content', v_row ->> 'content_hash', v_row ->> 'source',
      (v_row ->> 'read_at')::timestamptz, p_run, now()
    )
    on conflict (kind, key) do update set
      scope = excluded.scope, student_uid = excluded.student_uid, student_hng_id = excluded.student_hng_id,
      student_name = excluded.student_name, passport_no = excluded.passport_no, day = excluded.day,
      data = excluded.data, content = excluded.content, content_hash = excluded.content_hash,
      source = excluded.source, read_at = excluded.read_at, run_id = excluded.run_id, updated_at = now()
    where r.content_hash is distinct from excluded.content_hash;

    get diagnostics v_changed = row_count;
    if v_changed = 0 then
      v_unchanged := v_unchanged + 1;
      continue;
    end if;
    v_upserted := v_upserted + 1;

    delete from public.hg_chunks where kind = p_kind and key = v_key;
    insert into public.hg_chunks (kind, key, ord, content, embedding, embed_model)
    select p_kind, v_key, (c ->> 'ord')::integer, c ->> 'content',
           (c -> 'embedding')::text::extensions.vector(384), c ->> 'embed_model'
    from jsonb_array_elements(coalesce(v_row -> 'chunks', '[]'::jsonb)) as c;
  end loop;

  if p_all_keys is not null and not (p_kind = any (append_only)) then
    delete from public.hg_records
    where kind = p_kind and scope = p_scope and not (key = any (p_all_keys));
    get diagnostics v_deleted = row_count;
  end if;

  return jsonb_build_object('upserted', v_upserted, 'deleted', v_deleted, 'unchanged', v_unchanged);
end;
$$;

-- ─── RPC: semantic search (server path, before a device has synced) ──────────

create or replace function public.hg_match(
  p_embedding   extensions.vector(384),
  p_count       integer default 12,
  p_kinds       text[] default null,
  p_day_from    date default null,
  p_day_to      date default null,
  p_student_uid integer default null
) returns table (
  kind           text,
  key            text,
  ord            integer,
  content        text,
  similarity     double precision,
  data           jsonb,
  day            date,
  read_at        timestamptz,
  student_uid    integer,
  student_hng_id text,
  student_name   text
)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.kind, c.key, c.ord, c.content,
         1 - (c.embedding operator(extensions.<=>) p_embedding) as similarity,
         r.data, r.day, r.read_at, r.student_uid, r.student_hng_id, r.student_name
  from public.hg_chunks c
  join public.hg_records r on r.kind = c.kind and r.key = c.key
  where (p_kinds is null or c.kind = any (p_kinds))
    and (p_day_from is null or r.day >= p_day_from)
    and (p_day_to is null or r.day <= p_day_to)
    and (p_student_uid is null or r.student_uid = p_student_uid)
  order by c.embedding operator(extensions.<=>) p_embedding
  limit least(greatest(coalesce(p_count, 12), 1), 100);
$$;

-- ─── RPC: device delta sync ──────────────────────────────────────────────────
-- Changes after p_seq, with the CURRENT record and chunks for upserts (null when
-- the record has since been deleted; that delete follows later in the feed).

create or replace function public.hg_changes_since(p_seq bigint, p_limit integer default 1000)
returns table (
  seq        bigint,
  kind       text,
  key        text,
  op         text,
  changed_at timestamptz,
  run_id     uuid,
  record     jsonb,
  chunks     jsonb
)
language sql
stable
security invoker
set search_path = ''
as $$
  select ch.seq, ch.kind, ch.key, ch.op, ch.changed_at, ch.run_id,
         case when ch.op = 'upsert' and r.kind is not null then to_jsonb(r) end,
         case when ch.op = 'upsert' and r.kind is not null then (
           select coalesce(jsonb_agg(jsonb_build_object(
                    'ord', c.ord, 'content', c.content,
                    'embedding', to_jsonb(c.embedding::real[]), 'embed_model', c.embed_model
                  ) order by c.ord), '[]'::jsonb)
           from public.hg_chunks c
           where c.kind = ch.kind and c.key = ch.key
         ) end
  from public.hg_changes ch
  left join public.hg_records r on r.kind = ch.kind and r.key = ch.key
  where ch.seq > coalesce(p_seq, 0)
  order by ch.seq
  limit least(greatest(coalesce(p_limit, 1000), 1), 5000);
$$;

-- ─── Access ──────────────────────────────────────────────────────────────────

alter table public.hg_runs enable row level security;
alter table public.hg_records enable row level security;
alter table public.hg_chunks enable row level security;
alter table public.hg_changes enable row level security;

revoke all on table public.hg_runs, public.hg_records, public.hg_chunks, public.hg_changes from public, anon, authenticated;
revoke all on sequence public.hg_changes_seq_seq from public, anon, authenticated;
grant select, insert, update, delete on table public.hg_runs, public.hg_records, public.hg_chunks, public.hg_changes to service_role;
grant usage, select on sequence public.hg_changes_seq_seq to service_role;

revoke all on function public.hg_log_change() from public, anon, authenticated;
revoke all on function public.hg_sync(uuid, text, text, jsonb, text[]) from public, anon, authenticated;
revoke all on function public.hg_match(extensions.vector, integer, text[], date, date, integer) from public, anon, authenticated;
revoke all on function public.hg_changes_since(bigint, integer) from public, anon, authenticated;
grant execute on function public.hg_sync(uuid, text, text, jsonb, text[]) to service_role;
grant execute on function public.hg_match(extensions.vector, integer, text[], date, date, integer) to service_role;
grant execute on function public.hg_changes_since(bigint, integer) to service_role;
```

---

## 4. The record

### 4.1 Shape (`records.make`, `records.py:297-313`)

Every kind is built by one pure function in `src\cloud\records.py` from what a reader or report **already returns**. Nothing is re-parsed (except the edit pages' forms, by the client's own `_profile_fields`) and nothing is filled in. The helpers outside `src\cloud\` that shape a key, a scope or a day (`passport_key`, `auto_sync._row_key`, `yearless_day_problem`, `parsers.verification`, `performance._range_dates` and the rest) are listed with their contracts and links in [03d §12.8](03d_FILES_src_cloud.md).

```python
{"kind": str, "key": str, "scope": str,
 "student_uid": int | None,        # _uid(): digits only, 0 < n < 2**31
 "student_hng_id": str | None, "student_name": str | None,
 "passport_no": str | None,        # passport_key(): whitespace removed, upper-cased; "" unless it has
                                   #   at least 6 characters and a digit (blank, "—", PENDING -> ""); 03c §1.6
 "day": "YYYY-MM-DD" | None,       # iso_day()
 "data": dict,                     # every field the reader parsed, the reader's own keys, jsonable()
 "content": str,                   # the text form, built here, from fields that exist only (R1)
 "content_hash": str,              # sha256 hex, below
 "source": str,                    # "students.php", "results.json", "brief", ...
 "read_at": "2026-09-30T21:49:02+06:00"}   # as_read_at()
```

### 4.2 The content hash (`records.py:160-167`)

```python
canonical = json.dumps({"kind": kind, "key": key, "scope": scope, "data": data, "content": content},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`publish._normalise` (`publish.py:518-549`) recomputes it from the cleaned values before sending, so a record is always sent with the hash of exactly what is sent. The dry runs recomputed all 13,194 hashes with 0 mismatches.

### 4.3 Value rules

- **`as_read_at(value)`** (`records.py:75-93`): `None` or `""` is now. A naive datetime is Dhaka time (the stores write local time without a zone). A date is its midnight. A text is read as ISO with `datetime.fromisoformat(value.strip().replace("Z", "+00:00"))` (`"2026-09-27T15:19:01"`, `"2026-09-29 18:21"`), and a text that is no time at all is now. Naive times and dates get the Asia/Dhaka offset `+06:00` (`REPORT_TIMEZONE`); an input that already has an offset **keeps it** (`Z` becomes `+00:00`; there is no `astimezone`, so it is not converted to Dhaka time). The output is always ISO with seconds precision (`isoformat(timespec="seconds")`).
- **`iso_day(value)`** (`:96-114`): a date, a datetime, an ISO text (first `YYYY-MM-DD`), or a portal text through `src.dates.parse_portal_date` (`"27 Sep 2026"`, `"Applied On 27 Sep 2026, 17:16"`). `None` when it names no full day.
- **`clean_text`** (`:125-133`) removes NUL characters and replaces unpaired surrogates, which Postgres rejects and OCR text can hold. **`jsonable`** (`:136-157`) turns dates into ISO, named tuples and mappings into objects, tuples into lists, sets into sorted lists, and a non-finite float into `None`; every text is cleaned.
- **Keys that repeat** within one build get `"#2"`, `"#3"`... in order (`unique_keys`, `:316-335`), and the hash is recomputed. This is the sheet sync's own rule for its row keys.
- **The rows sent** (`_normalise`): `key` (cleaned, non-empty), the five columns `student_uid`, `student_hng_id`, `student_name`, `passport_no`, `day` (`""` becomes `null`; a `student_uid` that is not an int32 of digits becomes `null`), `data`, `content`, `content_hash`, `source`, `read_at`, and `chunks` added at embedding. A row that is not a dict, has no key or no source, has no `data` object, names another kind or scope, or repeats a key is **left out**. The (kind, scope) is then not complete (one log line, §7.3).

---

## 5. Every kind

`records.CLOUD_KINDS` (`records.py:41-47`) has 26 kinds: the spec's 24 plus `doc_check` and `consultant_performance`. The summary comes first, then each kind in detail. "Count" is the backfill of 30 Sep 21:48-22:05 (`C:\Hangeul\BOT\data\cloud\backfill_20260930.log`), confirmed by the postcheck. A dash means the backfill does not publish the kind.

| Kind | Key | Scope | Complete (p_all_keys sent) when | Count |
|---|---|---|---|---|
| `student` | uid | `all` | a whole `read_students()` (every page, pager total matched) | 340 |
| `pending_payment` | uid | `all` | the Pending rows equal the portal's badge; without a badge, some row says Pending or the list shows its own empty state | 1 |
| `verification` | uid | stamp ISO day | every "Payment verified by" stamp was readable; empty days in the last year are emptied | 333 in 57 scopes |
| `student_documents` | uid | `all` | the verified-documents list was read whole | 160 |
| `student_export` | sheet row key | `all` | header has Student ID and Full Name, and rows ≥ 90% of the students the list counts | 340 |
| `student_profile` | uid | uid | always (one record per scope) | – |
| `student_progress` | uid | `all` | every student's `progress.php` read with no error (backfill); `/stage` never | 340 |
| `consultation` | portal id (else sha1) | received ISO day | the portal listed every request of the day | 1,034 in 51 scopes |
| `consultation_day` | ISO day | `all` | only a backfill over every day from the oldest request, with no day failed | 51 |
| `consultation_totals` | `all` | `all` | always | 1 |
| `consultant_performance` | `<period>\|<first day>\|<name>` and `...\|summary` | `<period>\|<first day>` | the page is the period's own, its range reads as days, and its count badge equals its rows, each with a name | 15 (7 today + 8 month) |
| `window_application` | `<student>\|<window>` | `all` | no pager on the page, and either its own empty table or a row under review | 0 |
| `dashboard_fact` | `<group>\|<label>` | `all` | all 7 groups (2 tile sections, 5 cards) are on the page; tiles-only reads never | 39 |
| `calendar_item` | event id (else `t:`sha1) | `all` | never (the page shows this month and 45 days ahead only) | 22 |
| `passport_audit` | `<uid>\|<file>` | `all` | the watcher's run, over every scan the list shows (`all_keys`); commands never | – |
| `passport_alert` | `<uid>\|<file>` | `all` | over each listed student's newest scan (`all_keys`), when the whole list is known | 311 |
| `passport_issue` | passport number | `all` | a refresh of every student (no `--limit`); the backfill (the whole file) | 282 |
| `doc_verdict` | `<passport>\|<document>` | passport | always (a passport's rows are the whole of it) | 2,717 in 158 scopes |
| `field_check` | `<passport>\|<field>` | passport | always | 3,490 in 158 scopes |
| `doc_check` | passport | `all` | the whole store was readable | 158 |
| `field_correction` | sha1 of the entry | `all` | never (append-only; the server ignores the list) | 0 |
| `doc_page_text` | `<passport>\|<file>\|p<n>` (or `\|all`) | passport | always (the cache file is the whole of it) | 3,469 in 158 scopes |
| `report` | `<report>\|<day or run time>` | report name | never (a day's report never deletes another's) | 3 |
| `report_section` | `<report>\|<when>\|<n>` | `<report>\|<when>` | always | 434 |
| `brief_fact` | `<ISO day>\|<n>` | ISO day | always | – |
| `notification` | sha1 of text + time | ISO day of sending | never | – |

The one general rule behind the "complete" column: **a batch is complete only for a whole read.** That means every page was read, the pager total or the page's own count matched, there was no `PortalUnavailable`, no layout error and no timeout (R2, R5). A read that failed sends **no batch at all**, never `rows=[]` with `complete=True`, and adds a plain reason to the run's `failed_reads`.

### 5.1 `student` (`records.student`, `records.py:474-487`; text `:416-456`)

- **From** `client.read_students()`: every page of `students.php`, which raises unless the pager total matched.
- **Key** is the uid (a row without a uid is no record: its fallback key is not stable, R11). **Scope** `all`. **Day** is `applied_on`, else `applied_date`. **Source** `students.php`.
- **Columns:** `student_uid` = uid, `student_hng_id` = `student_id`, `student_name` = `student_name` or `details["Full Name"]`, `passport_no` = `passport_key(details["Passport No"])`.
- **Data:** every field of the reader except the volatile ones: `STUDENT_VOLATILE = ("sl", "details_text", "id")` (the row number shifts with every registration; the whole details text changes with every select option; `id` repeats `student_id`) and any `_`-prefixed field. What stays: `uid`, `student_id`, `student_name`, `target_university`, `applications`, `program`, `target_intake`, `docs_status`, `payment_status`, `status` (the stage), `applied_date`, `applied_on`, `details` (the ~50 det-items), `files`, `verified_line`, `verified_by`, `verified_stamp`, `paid`, `method`, `verified_income`. Fillers are blanked in the list cells and in `details` (named `details.<label>`), a placeholder "Passport No" is blanked, and `blank_on_portal` is added when anything was blanked.
- **Text:** each sentence appears only when its value exists:
  `Student <name> (<HNG id>, portal uid <uid>). Program <program>, intake <intake>. Stage: <stage>, applied <applied_date>. [Applied on <applied_on>. — only without applied_date] University: <university>. Applications: <a>; <b>. Documents: <docs_status>. Payment status: <payment_status>. Payment <amount and method>, verified by <verifier> on <stamp>. Passport <no>, expires <date>, status <status>. Date of birth <dob>. Gender <g>. Mobile <phone>. Email <email>. Guardian WhatsApp <phone>. Father <name>. Mother <name>. Address <address>, district <district>. Consultant <name>. Other details: <Label>: <value>; <Label>: <value>.`
  "Other details" lists every details label not among the 18 named ones (`_STUDENT_TEXT_LABELS`, `records.py:411-413`): Full Name, Program, Intake, Applied On, Payment Status, Passport No, Passport Expiry, Passport Status, DOB, Gender, Mobile, Email, Guardian WhatsApp, Father, Mother, Address, District, Consultant. The payment words come from `parsers.payment_text`.
- **Complete:** always from a whole list. Writers: the watcher every 30 min (dated by its list read), the full picture hourly, the backfill, and the commands that read the whole list (`/passports`, `/crosscheck*`, `/admitted`, and the free-text intake and applied answers). `/students` reads page 1 only, and that batch is **partial**.

### 5.2 `pending_payment` (`records.py:501-537`)

- **From** every page of `students.php?status=pending`. The page also lists others, so a row counts only when its own `payment_status`, letters only and lower-cased, is `pending`. Each uid appears once.
- **Key** uid, **scope** `all`, and **day**, **columns** and **data** as `student`, plus `"badge"`: the portal's own Pending Payments badge, or `None` when the page showed none. **Source** `students.php?status=pending`.
- **Text:** `Pending payment (students.php?status=pending). <the student text> The portal's Pending Payments badge shows <n>.`
- **Complete** (`pending_complete`, `:527-537`): with a badge, the rows must be exactly that many. Without a badge, some row must say Pending, or the list must show its own empty state ("No students found"). Rows none of which say Pending mean the Payment column was not read (a renamed header), not "nobody". The backfill and the full picture pass the empty state. The free-text answer has only the badge, so without one it is complete only when some row says Pending.

### 5.3 `verification` (`records.py:540-607`)

- **From** `parsers.verification()` of a students.php record: verifier, time, amount, method, paid and verified income. **Key** uid, **scope** the stamp's ISO day, **day** the same. **Source** `students.php`.
- **Data:** the verification dict (`student_id`, `uid`, `name`, `program`, `amount`, `paid`, `verified_income`, `method`, `verified_by`, `verified_time`) plus `day`, with fillers blanked.
- **Text:** `Payment verification of <name> (<HNG id>, portal uid <uid>), <program>. Verified by <verifier>, on <time> (<DD Mon YYYY>). Amount <amount and method>.`
- **Dating** (`verification_day`, `:574-593`): the stamps are yearless ("29 Sep, 13:07"). The day is the one day that `parsers.verification` accepts, trying the stamp's own year if it has one, else this year and then last year, never a future day, and only where `src.dates.yearless_day_problem` allows. Too old to date means no record.
- **Complete, from a whole list** (`verifications` + `records.batches(..., scope_range=verification_window(today))`): every scope with records is complete only when every "Payment verified by" line's stamp is readable (`stamps_readable`: a list with students has such lines, and all parse). The known empty days in `verification_window(today)` are then published empty and complete, so the days whose verifications are gone get emptied. That window runs from today minus 367 days, moved forward until `yearless_day_problem` clears, up to today (on 30 Sep 2026: `2025-10-01` to `2026-09-30`). When a stamp is unreadable, the batches are partial and the run records "students.php: a verification stamp could not be read (layout not recognised)".
- **From one day:** `read_verified_students(day)` reads every page and raises when the stamp guard fails. `/verified_*` publishes the day complete when the day passes `yearless_day_problem` (`command_hooks.verification_day`). The brief publishes the day only when it passes, and complete only when every row became a record (`bot_jobs.brief_reads`).

### 5.4 `student_documents` (`records.py:610-634`)

- **From** `verified_docs.fetch_verified_students(client)`: every page of `students.php?source=direct&filter_docs=verified`. **Key** uid, **scope** `all`, no day. **Source** `students.php?source=direct&filter_docs=verified`.
- **Data:** the row (`uid`, `name`, `passport` (a placeholder becomes `""`), `program`, `docs` joined by "|"), plus `files` (the list), plus `blank_on_portal`. The set of file names is the fingerprint the sync uses. **File names only, never the files** (D2).
- **Text:** `Verified documents on the portal of <name> (passport <no>, <program>, portal uid <uid>). <n> files: <file>, <file>, ...`
- **Complete:** always when the list was read (the reader raises otherwise). In the sync, an empty list is treated as a failed read ("no student listed"), never an empty complete scope.

### 5.5 `student_export` (`records.py:637-677`)

- **From** `students.php?export=csv`: 63 columns, B2B and Direct. **Key** is the sheet sync's own row key, `auto_sync._row_key` (`auto_sync.py:109-116`) of the row with Mobile normalised by `progress_builder.normalize_phone`: `Student ID:<clean_value(Student ID).upper()>`, else `Passport No:<passport>` (`_passport_no`: `clean_value`, whitespace removed, upper-cased, kept only with at least 6 characters and a digit), else `NAME:<_norm_key(Full Name)><_norm_key(Mobile)>`, plus `#2`, `#3`... for a repeat (`unique_keys`; [03c §1.2](03c_FILES_sheets_verify_root_scripts.md)). On 30 Sep that was 339 by Student ID and 1 by Passport No. **Scope** `all`, **day** `Applied On`. There is no uid (the export has none), so `student_uid` is null. `student_hng_id` = Student ID, `student_name` = Full Name, passport from `Passport No`. **Source** `students.php?export=csv`.
- **Data:** every column trimmed, fillers blanked (the same rule as the list, which also keeps a Bangla-only text, §6.1), a placeholder passport blanked, `stale_columns: ["Current Stage", "Current Status", "Progress %"]` (the export's stage columns are not trusted, [04 §3.3](04_PORTAL_INTEGRATION.md)), and `blank_on_portal`.
- **Text:** `Student export row (students.php?export=csv): <name> (<HNG id>). <Column>: <value>; <Column>: <value>; ...` (every column with a value except the three stale ones, Full Name and Student ID).
- **Complete** (`export_complete`, `:665-677`): the header must have Student ID and Full Name, and there must be at least `EXPORT_SHARE = 0.9` of the students a whole list read counts. The export has no pager, and a stream cut short after its header still parses. The sync takes that count from the hash state (`sheet_hooks.listed_students()` = `len(publish.known_keys("student", "all"))`); the backfill uses the list it just read. With no count known, the batch is partial.

### 5.6 `student_profile` (`records.py:680-695`)

- **From** `student_edit.php?id=N` as `HangeulAdminClient._profile_fields` reads it: every filled field by its form name (an input's value, a textarea's text, a select's chosen option). **Key = scope = uid**, no day. **Source** `student_edit.php`.
- **Data:** the fields with fillers blanked and a placeholder `passport_number` blanked. There is no record when there is no `full_name` or `name` (the page was not the profile). The legacy full-page read, which carries the form's `_csrf`, is never used.
- **Text:** `Student profile (student_edit.php) of <name> (portal uid <uid>). <field name with spaces>: <value>; ...` (without `id` and `save`).
- **Complete:** always (its own scope). Writers: the watcher (the profiles its audits read, the last read of a uid wins), the cross-check commands (`audited()`), and the 08:30 issue-date refresh (every edit page it read, parsed after the cache file is written).

### 5.7 `student_progress` (`records.py:698-726`)

- **From** `stage_report.read_progress(uids)`: `{uid: {"pct", "stage", "status"}}`, 4 at a time with a session of its own. An entry that could not be read (`{"error"}`) is left out. **Key** uid, **scope** `all`, no day. **Source** `progress.php`.
- **Data:** `pct`, `stage`, `status`, plus the student's `student_id` and `student_name` from the list when known. Fillers are blanked, but "Pending" in the stage and status is a state and is kept.
- **Text:** `Progress of <name> (<HNG id>, portal uid <uid>) on progress.php: <pct>% overall, current stage <stage>, status <status>.`
- **Complete:** in the backfill only, when every listed student's page was read with no error. `/stage` reads one program and intake, so it is partial.

### 5.8 `consultation`, `consultation_day`, `consultation_totals` (`records.py:731-793`)

- **`consultation`**: one row of `read_consultation_day(day)` (the portal's own date filter).
  - **Key:** the request's portal id, i.e. the hidden `id` of its row's forms (`parsers._consultation_table_rows`), when all the row's forms agree on one number. Otherwise the key is `sha1(name + contact + received)`, which changes when the name or contact is edited; that is a delete plus a new record, not an edit. All 1,034 keys were portal ids on 30 Sep.
  - **Scope** and **day** are the received ISO day. **Source** `consult_requests.php?status=all&from=<day>&to=<day>`. `student_name` is the requester's name.
  - **Data:** `id`, `name`, `contact` (the phone and the decoded e-mail), `city`, `program`, `consultant` (the reader's "Unassigned" becomes `""`), `details`, `received`, `received_date`, `status`, `handled_by`, `remarks`. Whole-cell fillers are blanked; filler words inside the free-text `details` are the form's own words and stay.
  - **Text:** `Consultation request from <name> (<contact>), received <received>. City <city>. Program <program>. Consultant <name>. Status: <status>, last updated by <handled_by>. Details: <details>. Remarks: <remarks>.`
  - **Complete** when the reader's own `complete` flag says the portal listed every request of the day.
- **`consultation_day`**: **key** the ISO day, **scope** `all`, **day** the day. **Data:** `{day, counts: {tab: n}, listed, complete}`. **Text:** `Consultation requests received on <DD Mon YYYY> (the portal's date filter): All <n>; New <n>; No Answer <n>; Wrong Number <n>; Consulted <n>; File Opened <n>.` **Complete only in the backfill** over every day from the oldest request with no day failed (`whole_range`). A read of one or two days must never delete the others.
- **`consultation_totals`**: **key** `all`, **scope** `all`. **Data:** `{counts}` from the status tabs, which count every request of all time. **Text:** `All-time consultation requests (the status tabs of consult_requests.php): All <n>; New <n>; ...` **Source** `consult_requests.php?status=file_opened`. Always complete.

### 5.9 `consultant_performance` (added; `records.py:798-955`)

- **From** `client.read_consult_performance(period)` (`client.py:425`): one GET of `consult_performance.php?period=today|month`, the page's own period links (the Custom range form is never used), parsed by `parsers.parse_consult_performance`. The reader raises for any other period and for a page that does not say it shows the period asked for (the page falls back to This Month).
- **Window:** `performance_window(page)` reads the page's own range (`"01 Sep – 30 Sep 2026"`) as `(first, last)` ISO days, through `src.bot.performance._range_dates`. If the range cannot be read as two days in order, **nothing is published** (R4: no stand-in day), and the run records the reason.
- **Scope** `"<period>|<first ISO day>"`, for example `month|2026-09-01` and `today|2026-09-30` (`performance_scope`, `:823-829`). **Day** = the last day of the range. **Source** `consult_performance.php?period=<period>`. The `student_*` columns are always null (these are consultants).
- **One record per leaderboard row:** key `"<period>|<first day>|<consultant name as printed>"` (`#2` for a repeated name). **Data:** `{period, period_label ("Today" / "This Month"), range (as printed), first_day, last_day, name, top (the row's crown, true or false), rank, score, conversion, files_opened, consultancies, points, docs_ready, extra?: {header: figure}, blank_on_portal?}`. Every figure is a string exactly as printed (`"17.9"`, `"18%"`, `"149.5"`), and the portal's "—" becomes `""` and is named. **Text:** `Consultant performance, <Today|This Month> (<range>): <name> — score <x>, conversion <y>, files opened <n>, consultancies <n>, points <n>, docs ready <n>.` (a blank figure is left out; extra columns follow as `<header> <value>`).
- **One summary per window, first:** key `"<period>|<first day>|summary"`. **Data:** the same base fields plus `tiles` ({label: figure} in page order: Consultancies done, Files opened, Conversion (file open), Docs ready), `top` (null, or the top-performer card with `label`, `name`, `score`, `conversion`, `files_opened`, `consultancies`, `metrics: [[label, figure], ...]`), `sort_note`, `score_help`, `points_help`, `count` (the leaderboard's own badge), and `empty_text` when the leaderboard shows nobody. **Text:** `Consultant performance, <title> (<range>): <tile> <fig>; ... Top performer: <name> — score ..., conversion ..., files opened ..., consultancies .... Leaderboard: <n> consultants[; the page says: <empty text>]. <sort note>. Score: <help>. Points: <help>.`
- **Complete** (`performance_complete`, `:923-943`): the page must be for that period, its range must read as days, the count badge must be present and equal the rows, and every row must have become a record. A name that is an undecodable Cloudflare stand-in has no identity and is left out, and then the read is not complete.
- **Why the scope has no last day:** the portal ends every period at today (`"01 Oct – 02 Oct"`, then `"01 Oct – 03 Oct"`). With the last day in the scope, each day's read would move the same keys into a new scope, and a consultant missing from a later read would stay forever in yesterday's scope, which no read covers again (against D10). Old windows, i.e. each past day's `today` window and each past month, are never deleted by a later window, so they stay as history.
- **Writers:** `/performance_today`, `/performance_month`, `/perf_today`, `/perf_month`, `/performance [today|month]` and the free-text routes (including the owner's spelling "performence"), all as job `command` after the reply. Also the hourly full picture (2 GETs) and the backfill.

### 5.10 `window_application`, `dashboard_fact`, `calendar_item` (`records.py:960-1053`)

- **`window_application`**: the rows of `window_applications.php?status=under_review` whose own status label key is `under review` (the rule of `parsers.count_under_review`). **Key** `"<student>|<window>"`, **scope** `all`, `student_name` = the student. **Source** `window_applications.php?status=under_review`. **Text:** `Window application of <student> for <window>: <status> (window_applications.php).` **Complete** (`window_complete`): the page has no pager (`_PAGED_RE = r"Page\s+\d+\s+of\s+\d+|[?&](?:pg|page)=\d"`, `backfill.py:242`), and it is either its own empty table or has a row under review. Rows none of which say under review mean the wording changed. On 30 Sep the page had only its empty-state row, so the backfill sent one call with `p_rows []` and `p_all_keys []`.
- **`dashboard_fact`**: `ask.dashboard_facts(html)` of `index.php`, each `Fact(group, label, value, text, note)`: the tiles and the five cards. **Key** `"<group>|<label>"` (`#2` for a repeat), **scope** `all`. The reader's group "Dashboard", used for a tile outside every group, becomes `""`. **Data** is the fact. **Text:** `Dashboard (index.php), <group>: <label> — <note>: <text>.` **Complete** only when all 7 `DASHBOARD_GROUPS` are on the page: Admissions flow, Direct / legacy pipeline, At a glance, Needs attention, Application pipeline, Applications by program, Top universities (`records.py:1016-1024`). A card missing from the page cannot be told from a card with no items. `get_dashboard()`'s tiles (the brief, `/stats`, `/admitted`) go through `records.tile_facts` (`:1005-1012`) so that a tile is **one record with one hash** whichever read it came from. Tiles-only batches are partial.
- **`calendar_item`**: `ask.calendar_items(html, today)`, which merges the month's event list, today's reminders and the 45-day timeline. **Key** is the portal's event id, else `"t:" + sha1(title|start|note)`. **Scope** `all`, **day** = end, else start. The reader's kind "Event" becomes `""`. **Data:** `title`, `kind`, `where`, `start`, `end`, `done`, `note`, `id`. **Text:** `Calendar (calendar.php): <title> — <kind> at <where>, from <DD Mon YYYY> to <DD Mon YYYY> | on <day>, done. Note: <note>.` **Never complete**: `calendar.php` shows only this month and the next 45 days, so nothing is ever deleted.

### 5.11 `passport_audit`, `passport_alert`, `passport_issue` (`records.py:1058-1138`)

- **`passport_audit`**: one `audit_student_passport` result.
  - **Key** `"<uid>|<file>"`, **scope** `all`. **Source** `view_doc.php + student_edit.php`.
  - **Data:** `{uid, file, result (the whole result: status, is_valid, fields compared, MRZ and visual readings, discrepancies, uncertain, verdict), form? (the portal values it was compared with), student_id?, student_name?}`. The passport comes from `fields.passport_no.portal`, else the form. Audits that checked nothing (`UNCHECKED_AUDITS = ("MISSING_DOCUMENT", "PORTAL_UNREADABLE", "OCR_UNAVAILABLE", "ERROR")`) are **no record**: they would overwrite a real audit of the same scan.
  - **Text:** `Passport audit of <name> (<HNG id>, portal uid <uid>), scan <file>: <status>. <verdict>. Discrepancies: <...>. Check by eye: <...>. Compared: <field>: portal <x>, scan <y>, <status>; ...`
  - **Complete** only from the watcher, over every scan the list shows (`all_keys = bot_jobs.listed_scans(students)`, all `"uid|passport_*"` files). An older scan still listed keeps its audit, for example one from a cross-check. Cross-check commands publish partial.
- **`passport_alert`**: each entry of the watcher's memory, `data\alerted_passport_issues.json` version 2.
  - **Key** `"<uid>|<file>"`, **scope** `all`, **day** the checked day, `read_at` = `sent_at`, else `checked`. **Source** `alerted_passport_issues.json`.
  - **Data:** the entry (`uid`, `student_id`, `status`, `checked`, `alert`, `sent`, `sent_at`) plus `file`.
  - **Text:** `Passport watcher memory for portal uid <uid> (<HNG id>), scan <file>: status <status>, checked <when>.` followed by one of `Alert sent <sent_at>: <alert>`, `Alert sent: <alert>`, `Alert not sent yet: <alert>` or `No alert was raised.`
  - **Complete over `bot_jobs.watched_scans(students)`**: each listed student's newest passport scan, by the upload time in the file name, `passport_\d+_(\d{9,11})`, the rule of `scheduler.passport_scan`, which a test pins. An alert is deleted only once the portal no longer lists its scan, never because a memory that was lost and is being rebuilt (its budget is 20 minutes a run) lacks it. Without the list, the batch is partial.
- **`passport_issue`**: `data\passport_issue.json` `{"by_passport": {passport: "YYYY-MM-DD"}}`. **Key** = `passport_key(passport)`, **scope** `all`. **Data:** `{passport_no, issue_date}`. **Text:** `Passport <no>: issue date <YYYY-MM-DD> (student_edit.php, read by the daily refresh).` **Complete** after a refresh of every student (no `--limit`), and in the backfill (the whole file).

### 5.12 The document check: `doc_verdict`, `doc_check`, `field_check`, `field_correction`, `doc_page_text` (`records.py:1143-1344`)

All five come from local files ([07](07_SHEETS_REPORTS_AND_DOCUMENT_CHECK.md)). `ids` = `{passport: (uid, HNG id)}` from the student index (§7.10) gives each its student. For the per-passport kinds the ids go into `data` (`uid`, `student_id`) so the hash, and with it the `student_uid` column, follows them.

- **`doc_verdict`**: `results.json` `documents[P].rows`. **Key** `"<P>|<document>"` (`#2` for a document checked twice, for example two NIDs or the three CROSS-CHECK name rows). **Scope** = P. **Day** and `read_at` are the entry's `checked`. **Data:** `doc`, `file`, `verdict`, `detail`, plus `student`, `program`, `uid?`, `student_id?`. **Text:** `Document check of <student> (<P>, <program>, <HNG id>, portal uid <uid>): <doc>, file <file> — <verdict>. <detail>.`
- **`doc_check`** (added): one per passport, **key** P, **scope** `all`. **Data:** `{student, program, verdict, checked, document_rows: {verdict: n}, field_rows: {result: n}, uid?, student_id?}`. **Text:** `Document check result of <student> (<P>, <program>, <HNG id>, portal uid <uid>): <verdict>, checked <checked>. Documents: FLAG 5, PASS 12, FAIL 2. Fields: MATCH 20, UNREADABLE 2.` The batch is dated by when the store was read (`read_at` on the batch), while each record's own `read_at` is its check time. Complete when the store was readable.
- **`field_check`**: `results.json` `fields[P].rows`. **Key** `"<P>|<field>"`, **scope** P. **Data:** `field`, `portal`, `result` (MATCH, DIFFERS, UNREADABLE, NO DOCUMENT or BLANK), `detail`, plus `student`, `program`, ids. **Text:** `Field check of <student> (<P>, <program>, <HNG id>, portal uid <uid>): <field>, portal value <v> — <result>. <detail>.`
- **`field_correction`**: `results.json` `corrections[]`, a portal field that changed after a check and whether that settled it. **Key** = `sha1(canonical(entry))`, **scope** `all`, **day** `noticed`. **Append-only**: never deleted, by the server's rule too. **Data** is the entry as it is. The ids fill only the columns, because the key is the entry itself. **Text:** `Portal correction noticed <when> for <student> (<passport>, <program>): <field> was <v> (<result>), now <v> (<result>). <detail>.` `results.json` is the only copy of this history (D11); on 30 Sep it was empty.
- **`doc_page_text`**: `data\verification\text\<PASSPORT>.json`, the OCR text cache, one record per page.
  - Cache keys are `"<file>:<size>:<mtime>:<max pages>"` for a whole-text entry, or `"PAGES:<file>:<size>:<mtime>:<max pages>"` for a per-page one (`_cache_entry`).
  - For each file the version is the one whose size and mtime match the file now in the student's folder (`<DOCS_ROOT>\<PROGRAM>\<NAME (PASSPORT)>\`), else the newest.
  - A per-page entry gives `p1`, `p2`, .... A file read only whole gives `p1` if it has one page, else one record keyed `...|all` ("all <n> pages").
  - Pages that read `[unreadable ...` are left out.
  - **Key** `"<P>|<file>|p<n>"`, **scope** P, `read_at` = the cache file's mtime. **Source** `verification/text/<P>.json`.
  - **Data:** `{file, page, pages (true for "all"), size, mtime, sideways, words, uid?, student_id?}`.
  - **Text:** `Document <file> of <name> (<P>), page <n>:\n<the OCR text>`. The first line is the heading that every chunk repeats (§8.2).

### 5.13 Reports: `report`, `report_section`, `brief_fact`, `notification` (`records.py:1349-1491`, `bot_jobs.py:185-199`, `sheet_hooks.py:130-413`, `command_hooks.py:308-324`)

- **`report`**: a generated report whole. **Key** `"<report>|<when>"`, **scope** = the report name, **day** `iso_day(when)`. **Data:** `{report, when, facts?}`. **Content:** the text as sent. **Never complete**, so a day's report never deletes another day's.
- **`report_section`**: the same report, one section or one student line a record. **Key** `"<report>|<when>|<n>"` (n from 1), **scope** `"<report>|<when>"`. **Data:** `{report, when, n, heading, lines}`. **Content:** the heading and its lines joined by newlines. **Complete** (the report as built now is all of it). `split_sections(text)` splits a text into blocks between blank lines, each (first line, the rest). The sync summary uses `sheet_hooks.line_sections`: each margin line opens a section, and the indented lines under it are its lines.
- The report names and their facts:

| Report (key) | Built by | Facts in `data` | Sections |
|---|---|---|---|
| `brief\|<ISO day>` | 18:05 brief, `bot_jobs.brief_batches` | `lines` (the facts), `pending_payments` `{count, listed, badge}`, `window_apps_under_review`, `calendar_today` (today's reminders, when read today), `document_check` (the local counts), `not_read` | `split_sections(text)` |
| `inquiries_report\|<ISO day>` | `/inquiries_*`, `command_hooks.inquiries_report` | `day`, `counts`, `listed`, `complete`, `totals?` | `split_sections(text)` |
| `sync_summary\|<run start, ISO time>` | portal sync, `sheet_hooks.sync_batches` (only when the summary had lines) | `lines` | `line_sections(lines)` |
| `missing_report\|<ISO day>` | 09:05 report (`missing_daily`), and the backfill from the newest `data\missing_reports\missing_information_YYYY-MM-DD.xlsx` | `rows`: `[{program, intake, student_id, full_name, mobile, missing_count, missing_fields}]` | one per incomplete student: `<program> <intake> — <HNG id> <name> — <n> missing: <fields>` |
| `missing_program:<KEY>\|<ISO day>` | `/missing` button (`missing_report --program`) | `program`, `rows` (as `build_report` counts them) | `split_sections(text)` |
| `stage_report:<KEY>:<INTAKE>\|<ISO day>` | `/stage` button (`stage_report --program --intake`) | `program`, `intake`, `counts {stage: n}`, `students [{student_id, full_name, stage, uid?, progress_pct?, progress_stage?, progress_status?, progress_error?}]` | `split_sections(text)` |
| `document_check\|<day of the newest check>` | the sync after `auto_verify.run`, and the backfill | `students`, `verdicts {verdict: n}` | one per student: heading `<student> (<P>, <program>): <verdict>`, line `MISSING a, FAIL b, FLAG c, PASS d; checked <when>` |
| `field_check\|<day of the newest check>` | the same | `students`, `corrections` | one per student: `<student> (<P>, <program>): MATCH a, DIFFERS b, UNREADABLE c, NO DOCUMENT d, BLANK e`, with the DIFFERS rows as lines; plus `Corrections (<n>)` when there are any |

  When the missing report's text is not given (the backfill), it is built as `Missing-information report — <DD Mon YYYY>` / `<k> students have missing information.` / one line per student. DOCUMENT CHECK and FIELD CHECK are published from `results.json`, the data `DOCUMENT CHECK.xlsx` and `FIELD CHECK.xlsx` are built from, never from the files (D2).
- **`brief_fact`**: each fact line of `Brief(text, facts)`. **Key** `"<ISO day>|<n>"`, **scope** the ISO day. **Data:** `{day, n, fact}`. **Text:** `Daily brief for <DD Mon YYYY>, fact <n>: <fact>`. Complete.
- **`notification`**: a Telegram message a job sent, **as sent**. **Key** `sha1(full text + "|" + sent_at)`, **scope** the ISO day of sending. **Data:** `{text, sent_at, source}`. **Content:** `"<title>\n\n<text>"` when a title is given and the text does not already start with it. Never complete. The messages are the sync summary and the document-check notice (source `auto_sync`), the watcher's alert messages that Telegram accepted (`passport_watcher`), and the 09:05 report or its failure notice (`missing_report`). The document-check notice is published only as a notification: the `sync_summary` report is built from the sync's own lines, taken before the check's lines are added.

---

## 6. The portal's "no value" words, Cloudflare's hidden e-mails and `blank_on_portal`

### 6.1 The filler rule (`records.py:195-276`)

- **`is_filler(value, field="")`** (`:230-239`) applies to **a whole cell** only. The cell's letters and digits, case-folded, after trimming (`_filler_key`), must be one of `FILLER_WORDS = {"na", "none", "null", "nil", "pending", "tbd", "notavailable", "notapplicable", "notprovided", "emailprotected"}`. So "N/A", "n.a." and "NA" are the same word, and "Not Available" is `notavailable`. A cell of marks only ("—", "--", "–", "-", "...") is a filler too.
- **Not fillers:** "NO", "NOT YET" and "0" are answers. A text in another script (Bangla) is a value; `progress_builder.clean_value` compares ASCII letters only and would wrongly blank it.
- **"Pending" is data in a status field** (`is_status_field`, `:223-227`): a name that contains the whole word `status`, `stage`, `result` or `step` (after `_` and runs of spaces become one space, lower-cased), or one of `STATUS_FIELDS = {"payment", "bank certificate", "bank solvency", "vin app", "vin required"}`. This covers students.php `status` (the stage), `payment_status` and `docs_status`; the details' Payment, Passport and Study Status; the export's Payment Status, Passport Status, Study Status, VIN Status, Visa Result, Current Stage, Current Status and Next Step; progress.php's stage and status; the status of a consultation or window application; and student_edit.php's `*_status` fields. Other fillers in those fields (for example "N/A") are still blanked.
- **Where it is applied:** to the whole-cell string fields of `student` (the list cells, plus `details` as `details.<label>`), `pending_payment`, `student_export`, `student_profile`, `student_progress`, `student_documents`, `verification`, `consultation`, `window_application`, `calendar_item`, and `consultant_performance` (`tiles.<label>`, `top.<field>`, `extra.<header>`).
- **Where it is not applied, and why:** `passport_audit` (form and result), `field_check.portal`, `doc_verdict` and `dashboard_fact`. They are the evidence of a check or reader-built labels (a card label "Pending" is a real label), so blanking them could change what a check reports. None held a whole-cell filler in the dry runs. Filler words **inside longer texts** also stay: they are the portal's or the student's own wording, for example a consultation's `details` and `remarks`, or the details' composite "Passport" answer `<text> / PENDING`.
- **Placeholder passport numbers** ("PENDING", "—", blank) are no identity (R11) and no value: `_passport_value` / `_passport_cell` blank them in data (named in `blank_on_portal`), and `passport_key` gives `""` for the column and the keys.
- **The reader's own stand-in words** are no value either: `FILLED_CONSULTANT = "Unassigned"` (`parsers._consultation_table_rows`), `FILLED_CALENDAR_KIND = "Event"` (`ask.calendar_items`) and `FILLED_TILE_GROUP = "Dashboard"` (`ask.dashboard_facts`) become `""` (`records.py:280-282`). These were found by the code review of the first build (`3caa393`).

### 6.2 `data.blank_on_portal`

When a record blanked anything, `data["blank_on_portal"]` is the **sorted list** of the blanked field names (`_mark_blank`, `:266-271`): a top-level name (`"name"`), `"details.<label>"` for a students.php details field (for example `"details.IELTS/TOEFL"`), `"tiles.<label>"`, `"top.<field>"`, `"extra.<header>"`, and passport fields that held no passport number. The key is **present only when the list is not empty**, so records without a filler kept their hash when the rule arrived. On 29 Sep, 69 student and 69 export records carried it (78 and 80 cells: IELTS/TOEFL 54 each, Passport No 14 each, Passport Expiry 3, Questions / Notes 3, HSC GPA 2, CGPA 1, Field 1, Passport Issue Date 2 in the export). Jeannie uses it to say "not given on the portal" without a value being lost or made up. It is a new data key the Jeannie side must learn; no schema change is needed.

### 6.3 Cloudflare's e-mail protection (`parsers.py:12-97`)

- **The problem:** `hangeul.com.bd` is served through Cloudflare, whose e-mail obfuscation rewrites every address in the HTML. An address in the text becomes `<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="HEX">[email&#160;protected]</a>` (or a `span` with that class), and a `mailto:` link becomes `<a href="/cdn-cgi/l/email-protection#HEX">`. A browser's script puts the addresses back, but a parser sees "[email protected]". On 29 Sep the second dry run found that stand-in in all 333 student `details.Email` values and in 1,005 of 1,014 consultation contacts, and the bot's own replies showed it too. The CSV export is not HTML and always carried the real addresses.
- **The decoding** (`_cf_address`, `:24-39`): HEX must be at least 4 hex digits, of even length. The first byte is the key, and each following byte XOR the key is one byte of the UTF-8 text. The result must contain "@", be printable, and have no space or control character (a mailto link's `?subject=...` query is URL-encoded, so it has none); otherwise it is `""`.
- **`decode_cf_emails(node)`** (`:64-97`) works in place on a soup or a tag and returns the node:
  - an element with class `__cf_email__` and `data-cfemail` becomes the address as plain text, joined to the text beside it (`_put_text`), so `get_text(strip=True)` reads "Email: <email>";
  - a link to `/cdn-cgi/l/email-protection#HEX` gets `href="mailto:<address>"` and keeps its own text;
  - form fields' `value` attributes are not touched (Cloudflare does not rewrite them);
  - it is idempotent and fetches nothing.
  **It is called once, right after building the soup and before any `get_text`, at every soup in `src\`:** 13 in `parsers.py` (`extract_csrf_token`, `parse_tables`, `parse_dashboard_metrics`, `parse_hangeul_live_dashboard`, `parse_students_page`, `parse_progress_page`, `consultation_rows`, `consultation_table`, `consultation_view`, `parse_pending_payments`, `parse_window_applications`, `parse_consult_performance`, `parse_calendar_events`), 2 in `client.py` (the `student_edit.php` profile read at `:614` and `_profile_fields` at `:721`), `ask.dashboard_facts` (`ask.py:690`) and `verified_docs._parse_rows` (`verified_docs.py:47`). A test asserts that every `BeautifulSoup(` line in `src\` is wrapped.
- **What cannot be decoded stays "[email protected]"**, and `is_filler` reads it as no value (`"emailprotected"`), so no stand-in is ever published as an address. In a longer text the parser removes it: `_without_hidden_email` with `_EMAIL_HIDDEN_GAP_RE = re.compile(r"\s*\[email\s*protected\]\s*", re.I)` (`parsers.py:328`, `:707-710`) turns `"<phone> [email protected]"` into `"<phone>"`. A consultant whose name is an address is read as the address. A row whose name stays a stand-in has no identity and is left out, which makes the read partial.
- **Found live on 29 Sep:**
  - 2 students show two different addresses on students.php (the details' Email and the Student cell or CSV); each record follows its own source faithfully.
  - 9 consultation contacts hold an address typed without a domain dot, which Cloudflare leaves visible; it is kept as the portal shows it.

---

## 7. The publish engine (`src\cloud\publish.py`)

### 7.1 On or off (`enabled`, `publish.py:103-107`)

Publishing runs only when **all three** are set: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (both non-blank after trimming) and `CLOUD_PUBLISH_ENABLED` true. While it is off, nothing is kept, built, written or started anywhere: every hook checks `handoff.enabled()` (`publish.enabled`) first, and `command_hooks.active()` and `bot_jobs.hand_over` also refuse mock mode (demo data is not the portal's, R1). A dry run skips the check. `_start` also refuses a `SUPABASE_URL` that does not start with `https://` (`publish.py:405-408`).

### 7.2 The hash state: `data\cloud_state.json` (`publish.py:142-205`)

```json
{"version": 1,
 "embed_model": "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd",
 "records": {"<kind>|<key>": {"h": "<content_hash>", "s": "<scope>", "t": "<read_at ISO>"}},
 "scopes":  {"<kind>|<scope>": "<sha256 of the sorted, newline-joined keys of its last complete publish>"},
 "reads":   {"<kind>|<scope>": "<read time of its last complete publish, ISO>"}}
```

- Written with `.part` + `os.replace` (`save_state`). A missing file, one that cannot be read, or a wrong version gives an empty state: everything is sent again, which is harmless, because Supabase answers `unchanged` for rows it has. A state key is split on the **first** "|" only, because a record key may hold "|" itself.
- **Why the scope is kept beside each hash:** so that a complete read can forget the keys Supabase just deleted. Otherwise an identical record coming back later would never be sent again.
- **Why the read time is kept:** to order reads that reach the publisher out of order (§7.4).
- `known_scopes(kind)` and `known_keys(kind, scope)` read it. They are used to empty verification days and passports and to count the students for the export rule.
- On 30 Sep at 23:28 it held 13,543 records, 600 scope digests and 599 read times (2.2 MB).

### 7.3 `publish(kind, scope, rows, complete, *, all_keys=None, read_at=None, dry_run=None, job=None) -> Result` (`publish.py:639-804`)

It never raises. Step by step:

1. **Off** means `Result.skipped = "publishing is off"`. No kind or no scope means one line and `ok=False`.
2. **Hand over when this process may not embed** (`_can_embed_here`: no stub embedder and not a CPU-only process, `:634-636`): the batch goes to `handoff.submit(job or current_job(), [records.batch(...)])`, with `Result.delegated=True`. This is how the bot process, which has torch on the GPU for the passport OCR, never embeds.
3. **Join or open a run** (`run(job)`, §7.7), then `_publish`:
   1. `_normalise` (§4.3). If anything was left out, `complete=False` (a record that could not be sent proves nothing by its absence), with one line: "Supabase publish (<kind>): <n> record(s) left out (no key, another scope or no data); nothing is deleted this time."
   2. `listed` = the rows' keys ∪ `all_keys`. The read time is `read_at` if given, else the earliest `read_at` of the rows.
   3. Take the publisher lock (§7.8), then load the state.
   4. **An older complete read** than the scope's last complete read (`reads`) becomes partial: `older_read=True`, one INFO line, nothing deleted.
   5. **Changed rows:** those whose `(h, s)` in the state differ from `(content_hash, scope)`. A row older than the version last sent (`t`) is counted `older` and not sent: a newer read is never rolled back.
   6. **Gone keys** (complete only): the state's keys of this (kind, scope) not in `listed`. A key whose last sent read is newer than this read goes into the list to keep; this read cannot say it is gone. `keys = sorted(listed ∪ keep)` becomes `p_all_keys`.
   7. **Nothing to do** is `skipped="no changes"`: no changed row, no gone key, and, for a complete read, the scope digest already equals the digest of `keys`. The rows count as `unchanged`.
   8. If Supabase was already given up on in this run (`r.down`), the publish fails with `"skipped (<why>)"` and the rest is silent.
   9. **`embed_model` guard** (§7.9).
   10. **Chunk** each changed row (`emb.chunks(content)`), **group** (§7.5), **embed** each group, and split it into calls by size.
   11. **Before the first real call**, the scope digest is removed from the state and saved. It is set again only after the last call succeeds (or restored after a partial publish), so a call Supabase took but never answered can never make a later read look already sent.
   12. **Each call:** `POST /rest/v1/rpc/hg_sync`. On a 2xx (one transaction), every row of the call is recorded as `{"h", "s", "t"}`, and the answer's `upserted`/`deleted`/`unchanged` are added to the result and the run. On the last call of a complete read, the gone keys are dropped from the state **only now that Supabase said so**, and the scope digest and read time are set. `state["embed_model"]` is set, and the state is saved after every accepted call.
   13. **A refused call** means `ok=False` with the short reason and one line. The state is not advanced for that call's rows, so they go again next run (D6).

`Result` (`publish.py:120-137`): `kind`, `scope`, `rows`, `changed`, `upserted`, `unchanged`, `deleted`, `calls`, `left_out`, `older`, `older_read`, `ok`, `skipped`, `error`, `delegated`.

`publish_scopes(kind, rows, complete, scope_range=None, *, read_at, dry_run, job)` (`:817-833`) makes one publish per record scope. With `complete` and `scope_range (lo, hi)`, every scope the state knows in lo..hi (text order: ISO days) that has no record now is published **empty and complete**, so Supabase deletes what it holds there. `publish_batches(job, batches, failed_reads, *, dry_run)` (`:836-866`) takes the lock for the whole run and publishes each batch of a handoff file; a batch with `scope: null` goes through `publish_scopes`.

### 7.4 Read ordering, in one place

| Case | Rule | Why |
|---|---|---|
| A complete read older than the last complete read of its (kind, scope) | published as partial (no `p_all_keys`) | The watcher hands its list over up to 20 minutes after reading it; its gaps prove nothing against a newer read. |
| A record older than the version last sent | not sent (`older`) | A newer read of it already went; never roll back. |
| A key missing from a complete read but sent by a newer read | kept (it goes into `p_all_keys`) | This read cannot say it is gone. |
| A key missing from an accepted complete read | forgotten from the state only after Supabase accepted the delete | A delete that failed is sent again next time. |
| The scope's key digest (the "nothing changed" shortcut) | dropped before the first call, set after the last | A committed call that was never answered cannot make a later read look sent. |

### 7.5 Batching (`publish.py:89-91`, `:552-631`)

- **`MAX_ROWS = 200`**: `hg_sync` refuses more.
- **`MAX_CHUNKS = 250`**: chunks embedded at a time (384 numbers each, about 5 KB of JSON each). `_groups` packs `(row, chunk texts)` pairs into groups of at most 200 rows and 250 chunks, and each group is embedded at once.
- **`MAX_BODY = 1_000_000` bytes** per `hg_sync` body. `_by_size` splits each embedded group into calls by the **exact bytes `_body` writes**: the empty body's size (`p_rows: []`, `p_all_keys: null`), plus each row's own JSON, plus a comma between rows.
  - A row whose body alone would exceed the cap goes into a call of its own, with one line naming its size, never its content.
  - The last call of a complete read leaves room for `p_all_keys`. If the list does not fit beside the last call's rows, the call keeps the rows at its end that fit and the rest move before it. A key list alone over the cap is sent in a call of its own, with one line.
- Dry run 3 had 601 calls, the largest 999,493 bytes, 0 over the cap, and at most 183 rows a call. Dry run 1, before the cap, had a 1.98 MB body. The Supabase gateway's real limit has never been measured.

### 7.6 The HTTP client and the short reasons (`publish.py:342-396`)

`httpx.Client(base_url=SUPABASE_URL without the trailing "/", timeout=30.0, transport=publish.TRANSPORT, follow_redirects=False)`, with the four headers of §3.6. `TRANSPORT` is `None` in production; tests put an `httpx.MockTransport` there. `_reason(resp)` builds the reason from the **HTTP status and the Postgres code only**. The code is added only when it matches `^[A-Z0-9]{5,10}$` (for example `42501`, `PGRST202`). A server message can quote a key, and keys hold passport numbers.

| Outcome | Short reason | Rest of the run |
|---|---|---|
| Timeout | `Supabase did not answer in time (<ExceptionType>)` | given up (silent) |
| Connection error | `could not connect to Supabase (<ExceptionType>)` | given up |
| 401 / 403 | `HTTP <status> <code> (the key was refused)` | given up |
| 404 | `HTTP 404 <code> (hg_sync or hg_runs not found: is the Jeannie migration applied?)` | given up |
| 5xx | `HTTP <status> <code> (Supabase server error)` | given up |
| 409 | `HTTP 409 <code> (conflict)` | goes on |
| Other 4xx | `HTTP <status> <code> (refused)` | goes on |
| URL not https | `SUPABASE_URL is not an https:// address` | given up |

### 7.7 Runs: `hg_runs` (`publish.py:274-481`)

- **`run(job="command", failed_reads=(), *, dry_run=None)`** is a context manager: one `hg_runs` row around every publish inside it. A nested run joins the outer one (its failed reads are added). It yields `None` while publishing is off.
- **Start:** `POST /rest/v1/hg_runs` with `Prefer: return=minimal` and the body `{"id", "job", "started_at", "counts": {}}`. If it fails, `p_run` is `null` in every call (a missing run would fail every call with 23503).
- **End, always, even after Supabase was given up on:** one `PATCH /rest/v1/hg_runs?id=eq.<id>` with `{"finished_at", "status", "counts", "note"}`, so a failed run never looks like one still going. The PATCH also sends `Prefer: return=minimal` (`publish.py:442`); the `hg_sync` POST sends **no** `Prefer` header (`publish.py:780`), because its JSON answer (the three counts) is needed.
  - **status** (`_status`): `failed` when there are failures and (Supabase was given up on, or failures ≥ publishes); `partial` when there is any failure or failed read; else `ok`.
  - **note:** `"<n> read(s) failed; <m> publish(es) failed"`, the parts that apply, or `null`.
  - **counts:** `{"upserted", "deleted" (Supabase's answers), "unchanged" (the hash state's skips plus Supabase's unchanged), "older", "sent" (rows sent), "failed_reads": [...], "failed": ["<kind>: <reason>", ...], "by_kind": {kind: [upserted, deleted, unchanged]}, "embedded" (records embedded), "chunks"}`.
- **Job names** (`src\cloud\__init__.py:23`): `portal_sync`, `passport_watcher`, `daily_brief`, `missing_report`, `issue_refresh`, `stage_report`, `command`, `backfill`, `full_picture`. The server does not check them; a test pins every hook's name to this list.

### 7.8 One publisher at a time (`publish.py:208-271`)

`publisher_lock(wait=LOCK_WAIT)` holds an OS lock on `data\cloud\publish.lock`: `msvcrt.locking(fd, LK_NBLCK, 1)` on Windows, `fcntl.flock` elsewhere, retried every 0.25 s. The OS releases it if the process dies. It is re-entrant within one process. `LOCK_WAIT = 20 * 60` s for publishers and the backfill; the full picture waits only 120 s and then skips the hour. A publisher that cannot get it logs "Supabase publish failed (<job>): another publisher held the lock for over 20 minutes" and drops that handoff (D6). One lock means one model in memory and one writer of the hash state.

### 7.9 The `embed_model` guard (`publish.py:743-753`)

Once the state records an `embed_model`, a process whose embedder has another `model_id` publishes **nothing** (deletes included). It logs one line naming both ids and "nothing is published until the chunks are re-embedded (clear hg_records on the Jeannie side, then delete data/cloud_state.json)", the rest of the run is skipped, and the run is closed as failed. The reason: `hg_sync` replaces chunks only when a hash changes (§3.7), so unchanged records would keep the old model's vectors, and Jeannie would compare her question vectors against a mix. `backfill --ignore-state` keeps the old model id in the new empty state, so the guard still holds.

### 7.10 The student index: `data\cloud\student_index.json` (`student_index.py`)

```json
{"version": 1, "by_passport": {"<PASSPORT>": {"uid": "<uid>", "hng": "HNG-2026-<n>"}}}
```

It is updated from every list that is read: `from_students` (details Passport No, uid, HNG id), `from_documents` (passport, uid) and `from_export` (Passport No, Student ID). A newer reading replaces the older one; a list that does not show a field leaves it as it was. A passport that two students share in one list gets `""` for that field (R11: no guessing). A placeholder passport is no passport. `remember(*readings, save=True)` merges and saves with `.part` + `os.replace` (not in a dry run). `load()` gives `{passport: (uid, hng)}`. Any failure is one line, and the records are then built without ids. The index exists because the verified-documents list can fail and the backfill can skip the portal: without it, a record's ids, and so its hash, would flip run after run. On 30 Sep it was 14.7 KB.

### 7.11 The dry run

`set_dry_run(True)` (the backfill's `--dry-run`), or `dry_run=True` on a call, makes every publish in the process write each request body, **exactly as it would be sent**, to `data\cloud\dry_run\<YYYYMMDD-HHMMSS>-<job>-<run id first 8>\<NNNN>-<label>.json`. The labels are `POST-hg_runs`, `rpc-hg_sync-<kind>` and `PATCH-hg_runs`. The hash state is left as it was, `enabled()` is not required, and no request is made to Supabase. It ends with one INFO line: "Supabase dry run (<job>): <n> request(s) written to <dir> in <t> s (<k> record(s) embedded, <c> chunk(s), <t> s embedding, peak memory <g> GB)."

---

## 8. Embeddings (`src\cloud\embed.py`)

### 8.1 The model, and hiding the GPU

- **`thenlper/gte-small` at revision `17e1f347d17fe144873b1201da91788898c639cd`** (`CLOUD_EMBED_MODEL`, `CLOUD_EMBED_REVISION`, `src\config.py:91-92`). It has 384 dimensions, mean pooling, L2-normalised output (`normalize_embeddings=True`) and float32. It is MIT-licensed, 67.7 MB, in `%USERPROFILE%\.cache\huggingface`. Every chunk carries `embed_model = "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd"` (`embed.model_id()`). Jeannie embeds her questions with `Supabase/gte-small`, the ONNX export of the same model, so the vectors must come from exactly this model.
- **Loaded once per process, lazily** (`GteSmall._load`, `embed.py:208-226`): `SentenceTransformer(name, revision=revision, device="cpu", model_kwargs={"dtype": torch.float32})`. The dtype matters: **transformers 5 loads it as float16 otherwise, which is about 7 times slower** on this CPU. Encoding uses `batch_size=32`, `convert_to_numpy=True` and `show_progress_bar=False`. Every vector is checked to have 384 finite numbers, else `EmbedError`.
- **Only in a process that was started to embed** (`cpu_only_process()`: `os.environ["CUDA_VISIBLE_DEVICES"] == "-1"`). `prepare_process()` (`:60-73`) must run before anything imports torch; it raises `EmbedError` if torch is already imported with CUDA visible. It sets:
  - `CUDA_VISIBLE_DEVICES=-1`;
  - `HF_HUB_OFFLINE=1` (the pinned model must already be in the cache; nothing is downloaded);
  - `HF_HUB_DISABLE_PROGRESS_BARS=1` and `TQDM_DISABLE=1`;
  - `TRANSFORMERS_VERBOSITY=error` and `TOKENIZERS_PARALLELISM=false` (defaults only);
  - and it quiets the loggers `sentence_transformers`, `transformers` and `huggingface_hub` to WARNING (`quiet_libraries`), so a missing model costs exactly its one `hangeul.cloud` line.
  The three entry points (`publish`, `backfill`, `full_picture`) also set `-1` at the top of the file under `if __name__ == "__main__"`, and the handoff child's environment carries it (§9).
- **Why `-1` and not `""`:** no device has index −1, so the CUDA runtime sees none. `""` fails on Windows, because CPython removes a variable set to an empty value from the process's real environment. The CUDA runtime then never saw it, and in dry run 1 `torch.cuda.is_available()` was True in the embedding process; only torch's own Python-level check kept `device_count()` at 0. With `-1`, the OS-level value (read with `GetEnvironmentVariableW`) is `-1`, `is_available()` is False, and the process never appeared in `nvidia-smi` (369 samples, 997 MiB before and 998 after). The reason is R12: the 8 GB GPU stays with Ollama and the document OCR ([02 §8](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)).
- **Measured on this PC:**
  - about 14 ms a record for short texts (1.4 s per 100) and 5.5 s per 100 records on average in the backfill (0.4-12.5 s by text length; OCR pages 7.8 s per 100 chunks);
  - the model loads in about 5 s;
  - peak working set about 1.5-1.57 GB in a full backfill, and 0.86-0.87 GB in a small publisher run;
  - the embeddings are deterministic: re-embedding 56 stored chunks in the postcheck gave cosine 0.99979-1.00048 to the stored vectors.

### 8.2 Chunks (`embed.py:92-192`)

gte-small reads at most 512 tokens. `MAX_WORDS = 350` words a chunk, `MAX_TOKENS = 510` (512 minus `[CLS]` and `[SEP]`) and `HEADING_WORDS = 40`.

1. `chunk_texts(content, 350, count_tokens)`: the whole text when it has at most 350 words **and** at most 510 tokens by the model's own tokenizer (`count_tokens`, `add_special_tokens=True`, `truncation=False`). Most records have exactly one chunk.
2. Otherwise, if the text's first line is at most 40 words and something follows it, that line is the **heading**. It is repeated at the top of every chunk, so each chunk says what it is (`Document <file> of <name> (<P>), page 3:`). The word budget is then `max(20, 350 - heading words)`.
3. `split_text(body, budget)` cuts **between paragraphs** (`_PARAGRAPH_RE = r"\n[ \t]*\n+"`), else **between sentences or lines** (`_SENTENCE_RE = r"(?<=[.!?])[ \t]+|\n+"`: OCR text is line-shaped), else **between words**. Whole units are packed together while they fit, and the original breaks are kept inside a chunk.
4. A chunk that still reads as more than 510 tokens is halved by words until it fits (or it is 20 words or fewer).

After the backfill: 15,629 chunks for 13,540 records. 757 `doc_page_text`, 3 `report`, 1 `student` and 1 `student_export` records had more than one chunk. The longest chunk is 510 tokens.

### 8.3 Stand-ins for tests

`StubEmbedder` (`embed.py:247-266`) gives a deterministic 384-number unit vector per text from its sha256, with no torch, and records every text asked for. `set_embedder(e)` sets it (it returns the old one; `None` goes back to gte-small). `custom_embedder()` is True for a stand-in, which needs no CPU-only process. One slow test loads the real cached model: 384 numbers, unit length, CUDA never initialised.

---

## 9. The handoff and the publisher process (`src\cloud\handoff.py`)

**Why:** the bot process must stay light and keep its event loop free (01 §5, R12). It also has torch on the GPU for the passport OCR, so it cannot hide CUDA. A button report's answer is its stdout, which the bot reads to its end, so a child must never hold that pipe. So **no job embeds or uploads itself**. It builds its records and calls:

```python
handoff.submit(job, batches, failed_reads=()) -> Optional[Path]      # handoff.py:118
await handoff.submit_async(job, batches, failed_reads=())             # to_thread, for the bot process
```

- `submit` returns at once and never raises. It does nothing at all (no file, no process) unless publishing is on **and** at least one non-empty batch is given (falsy batches are dropped first, `handoff.py:120-125`).
- It writes **one file** atomically (`.part` + `os.replace`): `data\cloud\pending\<YYYYMMDD-HHMMSS-ffffff>-<job slug>.json`. The slug keeps `[A-Za-z0-9_-]` only, 40 characters at most.

```json
{"version": 1, "job": "passport_watcher", "created_at": "2026-09-30T22:57:46+06:00",
 "failed_reads": ["calendar.php: the portal did not answer in time"],
 "batches": [
   {"kind": "student", "scope": "all", "complete": true, "rows": ["<records>"],
    "read_at": "2026-09-30T22:57:40+06:00"},
   {"kind": "passport_audit", "scope": "all", "complete": true, "rows": [],
    "all_keys": ["<uid>|passport_<uid>_<time>.jpg", "..."], "read_at": "..."},
   {"kind": "verification", "scope": null, "complete": true, "rows": ["<records, each in its own day scope>"],
    "scope_range": ["2025-10-01", "2026-09-30"], "read_at": "..."}]}
```

- It then **starts the publisher without waiting**: `python -m src.cloud.publish --from <file> --timeout 3600`, through `handoff.start(args, log)` (`:101-106`):
  - `subprocess.Popen([python, *args], cwd=C:\Hangeul\BOT, stdin=DEVNULL, stdout=log, stderr=log, env=child_env(), close_fds=True, creationflags=CREATE_NO_WINDOW (0x08000000))`;
  - `python` is the venv's **console `python.exe`**, never `pythonw.exe` (`_python`, `:86-90`);
  - `log` is `hangeul_sync.log`, opened for append;
  - `child_env()` (`:93-98`) is this environment plus `PYTHONIOENCODING=utf-8`, `CUDA_VISIBLE_DEVICES=-1` and `HF_HUB_OFFLINE=1`;
  - a reference to each child is kept so it is not reaped mid-run.
  If the process cannot start, the file is deleted and there is one line: "Supabase publish failed (<job>): the handoff could not be written or started (<type>)".
- **The publisher** (`publish.main`, `:911-930`; `process_file`, `:871-892`):
  1. `prepare_process()` (on failure: one line, the file deleted, exit 2);
  2. a **deadline timer** of `--timeout` seconds (default `CHILD_TIMEOUT = 3600`), which logs "the publisher ran over <n> s and was stopped", deletes the file and calls `os._exit(3)`, the OS releasing the lock;
  3. it reads the file (unreadable: one line, exit 1), then `publish_batches(job, batches, failed_reads)`;
  4. it **deletes the file, sent or failed** (D6: there is no queue beyond the hash state).
  Its INFO lines go to `hangeul_sync.log` (`logging.basicConfig(level=INFO)`, httpx at WARNING).
- **Stale files:** a file left by a publisher that was killed (stop.bat, a power cut) is removed by the next `write` when it is older than `STALE_HOURS = 6` (`_prune`).
- **Waiting:** the bot's jobs wrap the build and the submit in `asyncio.to_thread` with `HANDOFF_WAIT = 30` s (`bot_jobs.hand_over`). Commands use a background task holding a strong reference (`command_hooks._background`). Sheet jobs call `sheet_hooks.hand_over` synchronously as their very last step; it never prints, because a button report's stdout is its reply.
- **Sizes:** a full student list makes a handoff file of about 1 MB (hence `submit_async` off the loop).

---

## 10. Failure isolation (D6)

The rule: **a Supabase problem is one log line, the job's work and messages are exactly what they are without Supabase, and nothing raises into a job.**

| Failure | Where it is caught | What happens | Lines |
|---|---|---|---|
| Publishing off | every hook | nothing kept, built, written or started | 0 |
| Mock mode | the bot-process hooks (`command_hooks.active`, `bot_jobs.hand_over`) and `full_picture.run` only | nothing published by commands, the brief, the watcher or the full picture; the sheet jobs (which read the live portal whatever `MOCK_MODE` says) and the backfill still publish (§2 B12) | bot jobs: 1 INFO "Supabase publish skipped (<job>): the bot is in mock mode (demo figures)."; full picture: 1 WARNING "Full picture skipped: the bot is in mock mode (MOCK_MODE), so nothing is live."; commands: 0 |
| A record build raises | `bot_jobs.hand_over`, `sheet_hooks.hand_over`, `command_hooks._build_and_submit` | nothing handed over | 1: "Supabase publish failed (<job>): its records could not be built (<type>)" (bot jobs, `bot_jobs.py:88`) / "Supabase publish failed (<job>): the records could not be built (<type>)" (sheet jobs, `sheet_hooks.py:76`; commands, `command_hooks.py:175`) |
| The build takes longer than 30 s (bot jobs) | `bot_jobs.hand_over` | the job goes on; the thread finishes on its own | 1: "the handoff took over 30 s (the job itself was done)" |
| The handoff cannot be written or started | `handoff.submit` | file deleted | 1 |
| Supabase times out, cannot be reached, refuses the key, 404, 5xx | `publish._request` | this publish fails; **the rest of the run is skipped silently**; the run is PATCHed as failed | 1 for the whole run |
| A 409 or other 4xx on one call | `publish._request` | this (kind, scope) fails, other kinds still go | 1 each |
| gte-small cannot load or embed (`EmbedError`) | `publish._model_unavailable` | this publish fails and the rest of the run is skipped | 1 for the whole run |
| Another model in the state | `_publish` guard | nothing published this run | 1 |
| The lock is held too long | `_publish`, `publish_batches` | the handoff is dropped | 1 |
| The publisher runs over 3600 s (the full picture over 2700 s) | deadline timer | the process stops; the lock is freed by the OS | 1 |
| Any unexpected exception | `publish`, `publish_batches`, `run`, `full_picture.main` | "internal error (<type>)" | 1 |

- The **hash state is advanced only for rows Supabase accepted**, so everything that failed goes again on the next publish of that (kind, scope). There are no retries within a run and no Telegram alert about Supabase.
- **No student data in a log line**, ever: reasons are built from exception types, HTTP statuses and Postgres codes; counts and timings only (R14). `sheet_hooks.reason` also replaces URLs with `<url>` and cuts at 200 characters.
- The tests pin all of it ([03d §13](03d_FILES_src_cloud.md) and [10 §3](10_TESTS_AND_VERIFICATION.md) list the files): a Supabase 500, a timeout and a refused key; the job finishes, one line is written, the state is not advanced, and Drive, Sheets and Telegram still happen.

---

## 11. The hourly full picture (`src\cloud\full_picture.py`)

**Why:** so Jeannie is complete even on a day nobody asks the bot anything.

- **Scheduling** (`scheduler.py:363-389`, `:500-508`): job id `cloud_full_picture`, `IntervalTrigger(minutes=60, start_date=now + 7.5 minutes)`, `max_instances=1`, `coalesce=True`. That puts it midway between the sync's 15-minute and the watcher's 30-minute beats. The job is always registered. `run_full_picture()` does nothing while publishing is off, and skips (one INFO line) when `full_picture.skip_reason()` gives a reason. Otherwise it starts `python -m src.cloud.full_picture` through `scheduler._run_module` (venv console python, UTF-8, no window, output appended to `hangeul_sync.log`, 3600 s cap). The scheduler's start line then ends "..., Supabase full picture every 60m."
- **Quiet windows** (`skip_reason`, `full_picture.py:66-74`, from `backfill.quiet_reason`): 18:00-18:10, 08:25-08:40 and 09:00-09:10 (the scheduled jobs, [01 §5.4](01_ARCHITECTURE.md)), **or less than `LEAD_MINUTES = 5` before one**, or while a portal sync holds `data\auto_sync.lock` (a lock younger than 2 hours whose PID is alive; the lock is only read). The check runs four times: in the scheduler, again when the process starts, again once it holds the publish lock (which can take up to `LOCK_WAIT = 120` s), and **before each of the 8 read steps** (students, pending, consultations, totals, window applications, dashboard, calendar, performance; `full_picture.py:103-116`; one step can read many pages, e.g. every `students.php` page or both performance periods). A run that began just before a quiet window stops reading there, and one failed read says why ("the full picture's last <n> page read(s): not read (<reason>)", where `<n>` counts the steps left, not pages). Pages already read are each a whole read of their own page and are published as they are.
- **What it reads, in order** (`collect`, `:95-119`), with the backfill's own readers and a portal session of its own, GET only through `portal_get` plus the login POST (R17):

| Page | Kinds |
|---|---|
| every page of `students.php` | `student` (complete), `verification` (per stamp day, complete within the last year when every stamp is readable) |
| every page of `students.php?status=pending` | `pending_payment` |
| `consult_requests.php`, yesterday and today (date filter) | `consultation` (per day), `consultation_day` (partial) |
| `consult_requests.php?status=file_opened` | `consultation_totals` |
| `window_applications.php?status=under_review` | `window_application` |
| `index.php` | `dashboard_fact` (tiles and cards; complete when all 7 groups) |
| `calendar.php` | `calendar_item` (never complete) |
| `consult_performance.php?period=today` and `?period=month` | `consultant_performance` (per window) |

- **The portal down:** `PortalSession(HangeulAdminClient)` (`:77-92`) remembers the first unreachable answer (a timeout, a refused connection, a login that could not reach the portal). Every later page is then refused at once with "<page>: not read: the portal did not answer". Each failed page becomes a failed read, and nothing is published for it.
- **Publishing:** `publish.publish_batches("full_picture", batches, failed)`, in one run, under the publish lock. Only what changed is embedded and sent, and only whole reads delete anything. It ends with "Full picture: <n> batch(es) read in <t> s, <r> read(s) failed; <p> publish(es), <f> failed." It also does nothing in mock mode. It stops itself after `DEADLINE = 45 * 60` s. It sends nothing to Telegram and never logs student data.
- **Live:** 22:35 on 30 Sep: 12 batches read in 18.3 s, 0 failed; 68 publishes (one per verification day and per consultation day included), 3 upserted, 779 unchanged, 6.9 s in all, peak 0.87 GB. 23:35: 782 unchanged, 1.6 s.

---

## 12. The backfill CLI (`src\cloud\backfill.py`)

The one-time copy of everything (D11), run by the owner from `C:\Hangeul\BOT`:

```
.venv\Scripts\python.exe -m src.cloud.backfill --dry-run     # payloads to data\cloud\dry_run\ first
.venv\Scripts\python.exe -m src.cloud.backfill               # then for real
```

| Option | Meaning |
|---|---|
| `--dry-run` | write the payloads to `data\cloud\dry_run\`, send nothing, leave the hash state and the student index as they are (publishing need not be on) |
| `--only k1,k2` | publish only these kinds (default: every kind). The other portal pages are still read, except `progress.php` and the consultation days, which are read only when `student_progress` or a consultation kind is asked for |
| `--skip-portal` | publish only what is on disk (no quiet-window check then) |
| `--skip-disk` | publish only what the portal shows |
| `--days N` | consultations: only the last N days (then `consultation_day` is not complete); default: every day from the oldest request |
| `--ignore-state` | send every record, not only changed ones: the hash state is moved to `data\cloud_state.json.bak` and a new empty state keeps only the `embed_model` (Supabase answers `unchanged` for the same rows) |
| `--data-dir D` | read the watcher memory, the issue dates and the missing reports here (default `data\`) |
| `--verification-dir D` | read `results.json` and `text\` here (default `settings.verification_dir()`) |
| `--docs-root D` | the student document folders, to match OCR cache versions (default `settings.docs_root()`); files are only listed and stat-ed, never opened |
| `--force` | run even in a quiet window or during a portal sync |

- **Refusals** (exit 2): it cannot embed in this process ("Run it as python -m src.cloud.backfill"); publishing is off and it is not a dry run ("Nothing was read"); or it is a quiet window or a sync is running, without `--force` ("Not now: <reason>. Try again in a few minutes (or --force)"). Exit 1 means another publisher holds the lock.
- **What it reads, in order** (`_portal`, `:500-578`, one `HangeulAdminClient` of its own; `_disk`, `:581-611`):
  1. every page of `students.php` → `student`, `verification`;
  2. every student's `progress.php`, 4 at a time in a worker thread (`stage_report.read_progress`) → `student_progress`;
  3. `students.php?export=csv` (60 s timeout, BOM-decoded, refused unless the content type is `text/csv` or "Full Name" appears) → `student_export`;
  4. the verified-documents list → `student_documents`;
  5. the oldest consultation day (`oldest_consultation_day`), found by **bisection on the portal's own date-filter counts** from `CONSULT_FLOOR = 2015-01-01` to today, in about 13 reads. The date filter must echo the dates asked for, or the read fails as "layout not recognised". Then every day from that day to today, one date-filter read a day → `consultation` per day and `consultation_day` complete. It stops at the first unreachable answer.
  6. the totals → `consultation_totals`; every page of `students.php?status=pending` → `pending_payment`; `window_applications.php?status=under_review`; `index.php`; `calendar.php`; `consult_performance.php` today and month;
  7. from disk: the student index is updated from the list just read (or loaded when the portal was skipped); `results.json` → `doc_verdict` and `field_check` (per passport, with `scope_range ALL_SCOPES = ("", chr(0xFFFF))`, so a passport gone from the store is emptied), `doc_check`, `field_correction`, and the DOCUMENT CHECK and FIELD CHECK reports; every `text\*.json` → `doc_page_text` (one batch per passport); the watcher's memory (complete over the list when it was read) → `passport_alert`; `passport_issue.json`; and the newest `missing_information_YYYY-MM-DD.xlsx` (read with openpyxl, `read_only`, `data_only`; the file is never uploaded).
- **Its output** is progress per kind, counts only, never student data. For example `  student: 340 record(s), 340 sent: 340 upserted, 0 unchanged, 0 deleted`, `(not a complete read: nothing deleted)` for a partial kind, and `; FAILED: <reason>` for a failure. A dry run says `<n> to send, <k> request(s) written`. It ends with "Done in <s> s; <n> read(s) failed." and up to 20 "not read:" lines.
- **The one run** is `publish.run("backfill")` under the publisher lock; every publish is made in-process (it is itself a CPU-only process).
- **The `collect_*` functions** return `(batches, failed reads)`, so the full picture reads the same way.

---

## 13. Who writes what

Call sites with `path:line` are in [03d §12](03d_FILES_src_cloud.md).

| Kind | backfill | full_picture (60 min) | portal_sync (15 min) | passport_watcher (30 min) | daily_brief (18:05) | missing / stage / issue jobs | command |
|---|---|---|---|---|---|---|---|
| `student` | complete | complete | | complete | | | complete from whole lists; `/students` partial |
| `verification` | per day, complete | per day, complete | | | the day | | `/verified_*` the day; whole lists per day |
| `student_progress` | complete | | | | | `/stage`: partial | |
| `student_export` | complete if ≥ 90% | | complete if ≥ 90% | | | | |
| `student_documents` | complete | | complete | | | | |
| `student_profile` | | | | each audited uid | | issue refresh: each page read | cross-check audits |
| `consultation` | every day | yesterday, today | | | the day | | `/inquiries_*` the day |
| `consultation_day` | complete | partial | | | partial | | partial |
| `consultation_totals` | ✓ | ✓ | | | ✓ | | `/inquiries_*` |
| `pending_payment` | ✓ | ✓ | | | (not published: the brief reads page 1 only) | | free-text pending |
| `window_application` | ✓ | ✓ | | | (count only, in the brief's facts) | | |
| `dashboard_fact` | complete | complete | | | tiles, partial | | `/stats` and `/admitted` tiles, partial; free-text index reads, complete when all groups |
| `calendar_item` | ✓ | ✓ | | | (today's reminders go in the brief's facts) | | `/calendar <words>`, `/events <words>`, `/deadlines <words>`, calendar free text (only `ask.answer_calendar` publishes, `ask.py:1410`; a bare `/calendar`, `/events` or `/deadlines`, which `calendar_query` makes today's default view, publishes nothing: `calendar_command` publishes only on its `if not question.default:` branch, `telegram_bot.py:1129-1136`) |
| `consultant_performance` | ✓ | ✓ | | | | | `/performance_*`, `/perf_*`, free text |
| `passport_audit` | | | | complete over listed scans | | | `/passports`, `/crosscheck*`: partial |
| `passport_alert` | complete over the list | | | complete over the list | | | |
| `passport_issue` | complete | | | | | issue refresh (complete without `--limit`) | |
| `doc_verdict`, `field_check`, `doc_page_text` | every passport | | the passports just checked + up to 6 never accepted | | | | |
| `doc_check`, `field_correction` | ✓ | | ✓ (from the whole store) | | | | |
| `report` / `report_section` | document_check, field_check, missing_report | | sync_summary, document_check, field_check | | brief | missing_report, missing_program, stage_report | inquiries_report |
| `brief_fact` | | | | | ✓ | | |
| `notification` | | | sync summary, document-check notice | alert messages accepted | | 09:05 report or its failure notice | |

- **The catch-up:** the sync publishes the passports it just checked, plus up to `CATCH_UP_PASSPORTS = 6` passports whose records Supabase never accepted (a publish that failed, or checks made before publishing began), found through `publish.known_scopes`.
- **The order within the sync:** each passport's details are published before the store-wide kinds, so a run cut short never leaves `doc_check` newer than the rows it counts. When `results.json` was unreadable before the check (`sheet_hooks.store_readable` False: `auto_verify` then started from an empty store), the store-wide kinds are **not** sent, and the run records why.
- **What the brief reads but does not publish** (`bot_jobs.py:23-29`): pending payments (the brief reads the first page only), window applications (the count only) and calendar items (the brief's reader returns the parsed reminders, not the page). Their figures go into the brief report's `data`; the hourly full picture publishes them from whole reads.

---

## 14. Settings, secrets, packages

### 14.1 `.env` keys (`src\config.py:82-92`; `.env.example:106-118`)

| Key | Type, default | On this PC | Meaning |
|---|---|---|---|
| `SUPABASE_URL` | str, `""` | `https://dcbcbpwpmdtaanboetiz.supabase.co` (`.env` line 39) | the project's API URL; must be `https://` |
| `SUPABASE_SECRET_KEY` | str, `""` | value in secrets/bot.env (SUPABASE_SECRET_KEY) (`sb_secret_...`, line 40) | the project's **secret** (service_role) key, never the publishable key; never printed or logged |
| `CLOUD_PUBLISH_ENABLED` | bool, `False` | `true` since 30 Sep 22:27 (line 43) | the switch; publishing needs all three |
| `CLOUD_EMBED_MODEL` | str, `"thenlper/gte-small"` | not set | leave at the default unless Jeannie changes her model too |
| `CLOUD_EMBED_REVISION` | str, `"17e1f347d17fe144873b1201da91788898c639cd"` | not set | the pinned revision |
| `SUPABASE_ACCESS_TOKEN` | not a setting | value in secrets/bot.env (SUPABASE_ACCESS_TOKEN) (`sbp_...`, line 42) | **the Supabase CLI's personal access token only**; the bot never reads it (`Settings` has `extra="ignore"`) |

- Write `CLOUD_PUBLISH_ENABLED=true` or `false`, **never an empty value**: `CLOUD_PUBLISH_ENABLED=` raises a pydantic `ValidationError` when `Settings` loads, and the bot does not start (found by the preflight). An OS environment variable of the same name overrides `.env` (the pydantic-settings order, [03b §1.1](03b_FILES_src_scraper_llm_api_config.md)). The backfill used that: `CLOUD_PUBLISH_ENABLED=true` only in its own process while the bot ran with publishing off.
- Jeannie's access model (`jeenie-saem-bot.vercel.app`): on 28-29 Sep it showed "ACCESS: OPEN" and the owner accepted that risk (29 Sep 09:18, 08 §10.2); on 30 Sep 23:46 its HUD showed "ACCESS: KEY REQUIRED", protected by the single `JEANNIE_ACCESS_KEY` (Jeannie spec D8), with no Supabase Auth login ([11 B8](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md)). The owner also deferred rotating the keys (D13). Neither is re-raised.

### 14.2 Log redaction (`src\__init__.py:38-79`)

`redact(text)` applies every `(pattern, marker)` of `_SECRET_PATTERNS` in order with `pattern.sub(marker, text)`. Verbatim from `src\__init__.py:36-49` (patterns only, no secret):

```python
# The ":" is URL-encoded as "%3A" in file-download URLs (api.telegram.org/file/bot<token>/...).
_TOKEN_RE = _re.compile(r"bot\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}")

# The Supabase keys (src/cloud publishes with the secret key): the new-style secret and
# publishable keys, the CLI's personal access token, and the older JWT-shaped keys, also after
# "apikey:" / "Authorization: Bearer" wherever a request's headers get printed.
_SECRET_PATTERNS = (
    (_TOKEN_RE, "bot<token>"),
    (_re.compile(r"(?i)(bearer\s+)(?!<)[A-Za-z0-9._~+/=-]{8,}"), r"\1<redacted>"),
    (_re.compile(r"""(?i)(apikey['"]?\s*[:=,]\s*b?['"]?)(?!<)[A-Za-z0-9._~+/=-]{8,}"""), r"\1<redacted>"),
    (_re.compile(r"sb_secret_[A-Za-z0-9_-]{6,}"), "sb_secret_<redacted>"),
    (_re.compile(r"sb_publishable_[A-Za-z0-9_-]{6,}"), "sb_publishable_<redacted>"),
    (_re.compile(r"sbp_[A-Za-z0-9_-]{16,}"), "sbp_<redacted>"),
    (_re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"), "<jwt>"),
)
```

Notes: the `(?!<)` lookahead keeps an already-redacted `Bearer <redacted>` / `apikey: <redacted>` from being matched again; the `apikey` pattern covers `apikey: x`, `apikey=x` and httpx's header tuples `'apikey', b'x'`; the JWT pattern is any three dot-separated segments of 6+ URL-safe characters with the first starting `eyJ` (the second need not).

The filter `_RedactBotToken` is attached to each logger that can print a request: `httpx`, `httpcore`, `httpcore.connection`, `httpcore.http11`, `httpcore.http2`, `httpcore.proxy`, `httpcore.socks` and `hangeul.cloud`. A filter on a logger does not see its children's records, so each gets its own.

### 14.3 Packages and the model cache

- `requirements.txt:38-44`: `sentence-transformers==6.1.0` and `transformers==5.17.0` are pinned (the two whose versions decide how the model loads). Also installed on 29 Sep, into the bot's venv, with a constraints file of the old freeze so that nothing existing changed: `huggingface_hub 1.33.0`, `tokenizers 0.23.2`, `safetensors 0.8.0`, `scikit-learn 1.9.1` and small dependencies. torch stays 2.11.0+cu128 (the embedding process uses it on the CPU).
- The model is downloaded once into `%USERPROFILE%\.cache\huggingface` (`C:\Users\User\.cache\huggingface`). The embedding processes run with `HF_HUB_OFFLINE=1`, so a new PC must fetch the pinned revision once by hand, for example with `SentenceTransformer("thenlper/gte-small", revision="17e1f347...")` in a normal Python session (M7: ask the owner before downloading).
- The Supabase CLI v2.118.0 is at `C:\Hangeul\JARVIS\tools\supabase\bin\supabase.exe` (for migrations only).

---

## 15. Operations

### 15.1 Turning publishing on and off

- **On:**
  1. `.env` has `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and the line `CLOUD_PUBLISH_ENABLED=true`.
  2. Restart the bot with the full-path `C:\Hangeul\BOT\stop.bat`, then `start_background.vbs` ([02 §9.2](02_ENVIRONMENT_SETUP_AND_OPERATIONS.md)), outside 18:00-18:10 (M6).
  3. `hangeul_bot.log` should show "Scheduler active: daily briefing set for 18:05 (Asia/Dhaka), passport watcher running every 30m, portal sync every 15m, missing-info report 09:05, Supabase full picture every 60m."
  4. Within 15 minutes the first `portal_sync` run appears in `hg_runs`, and within 7.5 minutes the first `full_picture`.
  This is what was done at 22:27 on 30 Sep (a newline was ensured at the end of `.env`, then the line was appended).
- **Off:** `CLOUD_PUBLISH_ENABLED=false` (or remove the line) and restart. Every hook becomes a no-op: no records built, no handoff file, no process, and the full picture is not started. Supabase keeps what it has.
- The subprocess jobs (sync, reports) read `.env` at each start, so they follow the file even before a restart. The bot process, which hosts the watcher, the brief, the commands and the full-picture trigger, follows it only after a restart.

### 15.2 Re-running the backfill

1. Wait for a moment outside the quiet windows and a running sync (it refuses otherwise). Keep the bot running: the lock serialises it with the handoff publishers.
2. Run `.venv\Scripts\python.exe -m src.cloud.backfill` from `C:\Hangeul\BOT`. The 30 Sep run was `CLOUD_PUBLISH_ENABLED=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m src.cloud.backfill > data/cloud/backfill_20260930.log 2>&1`.
3. With the hash state in place, a second run sends only what changed, plus the deletes that whole reads prove. Most kinds say `0 sent`. Use `--ignore-state` to resend everything (Supabase answers `unchanged`), and `--only` to limit it to some kinds.
4. It takes about 17 minutes (1,025 s on 30 Sep; the portal part is about 3-5 minutes, the OCR pages about 7 minutes). Peak RAM is about 1.5 GB of CPU memory; there is no GPU use.

### 15.3 Reading `hg_runs`, and what the numbers mean

- **Read `hg_runs` with a plain REST GET** (the same headers as §3.6, the key being the value in secrets/bot.env (SUPABASE_SECRET_KEY)):

```
GET https://dcbcbpwpmdtaanboetiz.supabase.co/rest/v1/hg_runs?select=job,started_at,finished_at,status,counts,note&job=neq.backfill&order=started_at.desc&limit=20
```

  Or in the Supabase SQL editor: `select job, started_at, finished_at, status, counts->>'upserted', counts->>'unchanged', counts->>'deleted', note from hg_runs order by started_at desc limit 20;`. To count records per kind, use `select kind, count(*) from hg_records group by kind order by kind;`, or a PostgREST `HEAD /rest/v1/hg_records?kind=eq.<kind>` with `Prefer: count=exact` (the count is in `Content-Range`).
- **Reading a row:**
  - `status` null means the run is still going (or its process was killed before the PATCH).
  - `ok` means nothing failed. `partial` means some read failed (see `counts.failed_reads`) or one publish failed. `failed` means Supabase or the model was given up on, or every publish failed (`counts.failed` has one "<kind>: <reason>" each).
  - `upserted` is records new or changed; `unchanged` is records whose hash was already there (mostly skipped locally, never sent); `deleted` is records removed by complete reads; `sent` is rows actually sent; `older` is records not sent because a newer read of them was sent; `embedded` / `chunks` is what was embedded; `by_kind` is `{kind: [upserted, deleted, unchanged]}`.
- **Example 1, `full_picture` at 22:35 on 30 Sep:** 3 upserted, 779 unchanged, 0 deleted, 3 chunks. The 782 records it read are student 340, verification 333, dashboard 39, calendar 22, performance 15, consultation_day 2, totals 1, pending 1, and the consultations of 29 and 30 Sep (29, by subtraction). The 3 upserted are one new consultation request received at 22:12 (after the backfill), its day's counts, and the all-time totals.
- **Example 2, `portal_sync` at 22:43:** 0 upserted, 976 unchanged. That is export 340 + verified documents 160 + doc_check 158 + the 2 check reports + their 316 sections. The sync summary had no lines, so there was no report and no notification.
- **Example 3, `portal_sync` at 23:13 and 23:28:** 2 and 3 upserted. That is 1 and 2 changed export rows, plus one document-check notice each (a `notification`).
- **The log lines** (counts only) go to `hangeul_sync.log` for the publisher, the full picture and the backfill children. They go to `hangeul_bot.log` for handoff failures inside the bot process:

```
2026-09-30 22:35:33,477 [INFO] hangeul.cloud: Supabase publish (full_picture): ok, 3 upserted, 0 deleted, 779 unchanged, 3 row(s) sent, 0 failed, 0 read(s) failed; 3 record(s) embedded in 0.1 s; 6.9 s in all, peak memory 0.87 GB.
2026-09-30 22:35:33,478 [INFO] hangeul.cloud: Full picture: 12 batch(es) read in 18.3 s, 0 read(s) failed; 68 publish(es), 0 failed.
```

  A publish with nothing to do still writes its summary line (it counts as a publish). **`hg_runs` is the reliable record, not the log** (see the caveat in §18: two processes appending to `hangeul_sync.log` at the same moment can overwrite each other's line).

### 15.4 The dry-run method (used three times on 29 Sep and once on 30 Sep)

1. **Harness:** run the real entry point (`python -m src.cloud.backfill --dry-run`, or through `runpy` as `__main__`) from a worktree with copies of the gitignored inputs (`results.json`, the OCR caches, the watcher memory, `passport_issue.json`, the newest missing report). Use `--docs-root` pointing at the real document folders, because a worktree's default resolves beside the worktree.
2. **Guard it:** a network guard allowing only the portal host (GET, plus the login page's GET and POST) at the HTTP, DNS and connect layers; `publish.TRANSPORT` set to raise on any request; Supabase settings removed from the environment. The Hugging Face lookups are answered "offline" in-process.
3. **Timing:** wait for the live sync to release `C:\Hangeul\BOT\data\auto_sync.lock` first. The backfill's own check looks at the worktree's `data\`, so from a worktree it cannot see the live sync.
4. **Check the payloads with your own code:**
   - (a) per-kind counts equal independent reads of the portal (your own httpx session and parsers, before and after) and of the files;
   - (b) no whole-value filler or Cloudflare stand-in in any data leaf, content or chunk ("Pending" only in status fields);
   - (c) `blank_on_portal` exactly where the raw pages have fillers;
   - (d) every body ≤ 1,000,000 bytes, `p_all_keys` only on the last call of each (kind, scope) and holding every key sent there;
   - (e) every chunk 384 finite floats of norm 1 ± 1e-7, one `embed_model`, at most 510 tokens;
   - (f) keys unique per kind, and `content_hash` recomputes;
   - (g) CUDA hidden (the OS-level variable, `torch.cuda.is_available()`, `nvidia-smi` polling);
   - (h) with the model missing, exactly one line per run;
   - (i) nothing reached any host but the portal;
   - (j)-(l) decoded e-mails equal your own decode of the raw pages.
5. **The results:**
   - 29 Sep 14:39: "not ready". It found the portal's typed fillers (R1). Fixed by `752cd53`.
   - 29 Sep 15:37: "not ready". It found the Cloudflare stand-in. Fixed by `9ead47d`.
   - 29 Sep 16:22: **ready**. 13,194 records, 15,234 chunks, 601 calls, all checks passed.
   - 30 Sep 21:22 (the release preflight, from `e4d1cea`): ready. 615 calls, largest body 999,526 bytes. Its one low finding, the performance scope, was fixed in `8317741`.

### 15.5 The postcheck method (30 Sep 22:06-22:26, task `w9tx2ubg3`)

An independent verifier used its own `httpx` code with **GETs only** on Supabase: its guard refused every other method, any `/rpc/` and any other host. It read the portal with its own session (GET plus the login POST) and the disk files with its own code. It checked six things, all of which passed:

1. **Per kind:** `hg_records` count and key set equal its own reads. 13,540 = 13,540. The one later difference was a consultation request received at 22:12, which also moved that day's counts and the all-time totals.
2. **Embeddings:** `embed_model` is one value on all 15,629 chunks. 669 sampled vectors had 384 finite numbers and norm 1.000000, and PostgREST declares `vector(384)`. 56 chunks were re-embedded offline with cosine 0.99979-1.00048.
3. **Chunks and fillers:** every record has a chunk (0 orphans, 0 `ord` gaps, 0 empty texts). There are 0 fillers and 0 stand-ins across 157,187 data leaves, 13,540 contents and 15,629 chunk contents.
4. **Spot checks:** two random draws, 30 records over 15 kinds, 388 fields compared, 388 equal.
5. **Runs and changes:** `hg_runs` has one backfill row with status ok, and its counts equal the tables (upserted 13,540, chunks 15,629, deleted 0). `hg_changes` has 13,540 upserts and 0 deletes, all carrying the backfill's run id.
6. **Access:** GETs without a key, or with an invented publishable key, get 401.

Its scripts are in `C:\Hangeul\JARVIS\cloud\scratch\postcheck\`, with masked results only.

### 15.6 Re-embedding with another model

1. Set `CLOUD_EMBED_MODEL` / `CLOUD_EMBED_REVISION`, and change Jeannie to the same model first.
2. Clear `hg_records` on the Jeannie side (the chunks cascade).
3. Delete `data\cloud_state.json`.
4. Run the backfill.

Without step 2 the guard of §7.9 stops every publish, on purpose.

### 15.7 Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| No `hg_runs` rows after turning it on | the flag not read (bot not restarted), or `.env` has an empty value | check "Supabase full picture every 60m" in the start line; fix `.env`; restart |
| `HTTP 404 ... (is the Jeannie migration applied?)` | wrong project or the migration missing | `supabase migration list` from the Jeannie clone |
| `HTTP 401/403 ... (the key was refused)` | the publishable key was used, or the key changed | put the secret key in `.env` (value in secrets/bot.env (SUPABASE_SECRET_KEY)) |
| `gte-small could not be loaded (OSError)` | the model is not in the Hugging Face cache (the hub is offline in these processes) | fetch the pinned revision once (§14.3) |
| `this process did not hide CUDA before torch` | an embedding entry point imported torch first | run it with `python -m src.cloud.<module>` |
| `Supabase holds chunks embedded with ...` | the model setting changed | §15.6 |
| `another publisher held the lock for over 20 minutes` | a backfill running, or a hung publisher | wait; check for `src.cloud` processes (read-only) |
| Files piling up in `data\cloud\pending\` | publishers killed | they are pruned after 6 hours; look for the cause |
| `status` null rows in `hg_runs` | a publisher killed before its PATCH (deadline, power cut) | harmless; the next run republishes what was not accepted |

---

## 16. The live numbers

### 16.1 After the backfill (30 Sep 2026, 21:48-22:05, `data\cloud\backfill_20260930.log`)

| Kind | Records | Scopes | | Kind | Records | Scopes |
|---|---|---|---|---|---|---|
| `student` | 340 | 1 | | `consultant_performance` | 15 (7 + 8) | 2 (`today\|2026-09-30`, `month\|2026-09-01`) |
| `student_export` | 340 | 1 | | `doc_verdict` | 2,717 | 158 |
| `student_progress` | 340 | 1 | | `field_check` | 3,490 | 158 |
| `verification` | 333 | 57 | | `doc_check` | 158 | 1 |
| `student_documents` | 160 | 1 | | `field_correction` | 0 | – |
| `consultation` | 1,034 | 51 (11 Aug – 30 Sep) | | `report` | 3 | 3 |
| `consultation_day` | 51 | 1 | | `report_section` | 434 (158 + 158 + 118) | 3 |
| `consultation_totals` | 1 | 1 | | `doc_page_text` | 3,469 | 158 |
| `pending_payment` | 1 | 1 | | `passport_alert` | 311 | 1 |
| `window_application` | 0 (one empty call) | 1 | | `passport_issue` | 282 | 1 |
| `dashboard_fact` | 39 | 1 | | `calendar_item` | 22 (never complete) | 1 |
| **All** | **13,540 records, 15,629 chunks** | | | | | |

- The run took 1,025 s: 340 students, 51 consultation days from the oldest request (11 Aug 2026), and 0 failed reads.
- Its one `hg_runs` row is `backfill`, status ok, 15:48:09Z-16:05:13Z, upserted 13,540, sent 13,540, embedded 13,540, chunks 15,629, deleted 0, unchanged 0.
- `hg_changes` has 13,540 upserts.
- 22 of the 26 kinds came from the backfill (20 with rows, and `window_application` and `field_correction` at 0). `student_profile`, `passport_audit`, `brief_fact` and `notification` come only from the jobs and commands.
- The `consultation_totals` read at 22:12 were All 1034, New 10, Consulted 818, No Answer 159, Wrong Number 41, File Opened 6. The report sections are 158 DOCUMENT CHECK, 158 FIELD CHECK (no Corrections section) and 118 incomplete students of `missing_information_2026-09-30.xlsx`.

### 16.2 The first automatic runs (30 Sep, all ok)

| Time | Job | Upserted | Unchanged | Deleted | Seconds |
|---|---|---|---|---|---|
| 22:35 | full_picture | 3 | 779 | 0 | 6.9 (reads 18.3) |
| 22:43 | portal_sync | 0 | 976 | 0 | 0.4 |
| 22:57 | passport_watcher | first complete `passport_audit` scope (0 audits this run, so a call with `p_rows []` and every listed scan as `p_all_keys`) | | | |
| 22:58 | portal_sync | 0 | 976 | 0 | |
| 23:13 | portal_sync | 2 | 1,036 | 0 | 7.5 |
| 23:27 | passport_watcher | the student list (a changed student record) | | | |
| 23:28 | portal_sync | 3 | 1,031 | 0 | 5.9 |
| 23:35 | full_picture | 0 | 782 | 0 | 1.6 |
| 23:43 | portal_sync | 0 | 976 | 0 | 1.0 |

The two watcher rows are read from the hash state (their scope read times, 22:57:46 and 23:27:45); their log lines are missing (§18). At 23:28 the local state held 13,543 records: the 13,540, the 22:12 request and 2 notifications. No run has deleted anything yet.

---

## 17. Timeline (full story in [08](08_HISTORY_STAGE_BY_STAGE.md))

| When (Dhaka) | What |
|---|---|
| 29 Sep ~10:30 | Preconditions: `.env` keys added by the owner; migrations applied with the CLI; the tables answer 200; sentence-transformers and gte-small installed (the owner's OK, M7) |
| 29 Sep 11:28-12:15 | The build: `36ae72e` (the package), `a0572ba`, `cfd10f1`; three hook branches `41055de` (sheet jobs), `5048a07` (brief, watcher, full picture), `2b6798f` (commands), merged into `cloud/all` (`44c9378`, `112325b`, `969f917`, `cb16394`) |
| 29 Sep 14:25 | `3caa393`: the three reviews' findings (gone keys forgotten only after an accepted delete, read ordering, the digest drop, the model guard, `pending_complete` / `window_complete` / `export_complete`, the watched-scan rule for alerts, the student index, the reader fillers) |
| 29 Sep 14:39 | Dry run 1: R1 fails on the portal's fillers; about 600 lines on a missing model; `""` does not hide CUDA; a 1.98 MB body |
| 29 Sep 15:26 | `752cd53`: `is_filler`, `blank_on_portal`, one line a run, `-1`, the 1 MB cap |
| 29 Sep 15:37 | Dry run 2: R1 fails on Cloudflare's "[email protected]" |
| 29 Sep 16:19 | `9ead47d`: `decode_cf_emails` at every soup; the library loggers quieted |
| 29 Sep 16:22 | Dry run 3: ready. The owner chose to inspect the payloads first; nothing was uploaded |
| 29 Sep 16:36-16:41 | The bot was down about 5 minutes during agent test runs (cause unconfirmed; the watchdog restarted it) |
| 29 Sep 21:12 → 30 Sep 14:06 | The performance commands: self-computed first (`bbd8f98`, `a721066`; asked 29 Sep 21:12, deployed 30 Sep 10:31), then replaced by the portal's own page (`ce23535`, `314afdb`; the owner's correction 13:11, deployed 14:06) |
| 30 Sep 21:04-21:16 | `e5e532e` (main merged into `cloud/release`), `e4d1cea` (kind `consultant_performance`); preflight ready with one low finding |
| 30 Sep 21:45 | `8317741`: the performance scope `<period>\|<first day>`; the backfill reads the page |
| 30 Sep 21:47 | main fast-forwarded to `8317741` (1,152 tests); bot restarted with publishing **off** |
| 30 Sep 21:48-22:05 | **The real backfill**: 13,540 records, 15,629 chunks, 0 failed reads |
| 30 Sep 22:06-22:26 | The independent postcheck: verified |
| 30 Sep 22:27 | **Publishing on**; bot restarted |
| 30 Sep 22:35 / 22:43 | The first `full_picture` and `portal_sync` runs, both ok |

---

## 18. Open items and caveats (also in [11](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md))

1. **Jeannie does not read it yet** (§1): her reader was approved at 30 Sep 23:48 and is being built, unmerged, in `C:\Hangeul\JARVIS\jeannie-hg` (branch `saem/hangeul-context-reader`, workflow `wf_1a222cb1-960`). The owner still has to tell Jeannie's side about `doc_check`, `consultant_performance` and `data.blank_on_portal`.
2. **Log lines can be lost.** Several processes append to `hangeul_sync.log` through separate handles: the sync from `scheduler._run_module`, each publisher from `handoff.spawn`, the full picture. On Windows the C runtime's append mode is per process, so a writer with an older file position can overwrite another's line. Evidence on 30 Sep: the watcher and the sync start in the same second every half hour (22:57:37, 23:27:37, 23:57:37 in `hangeul_bot.log`). None of the watcher's publishes (22:57, 23:27, 23:57) left a "Supabase publish (passport_watcher)" line, although the hash state shows the first two ran (their scope read times). The sync's publisher lines at 22:58 and 23:58 are fused with the sync's own print (`[2026-09-2026-09-30 22:58:09,138 ...`). This is the likely cause, not proven. Until it is fixed, **read `hg_runs`, not the log**. A fix would be a log file per publisher, or `logging.FileHandler` in the child instead of the inherited handle.
3. **Stale docstrings and comments** (the code wins; none changes behaviour):
   - `src\cloud\command_hooks.py:45-49` still says the performance scope is `"<period>|<first day>|<last day>"`; the code (`records.performance_scope`, `8317741`) uses `"<period>|<first day>"`.
   - `src\cloud\backfill.py:22-27` says `collect_performance` covers the Consultant Performance page "which only the hourly job reads", and the module docstring's list of portal pages (`:6-16`) leaves out `consult_performance.php`. Since `8317741` the backfill reads it too: `_portal` runs `collect_performance(client)` as the step "consult_performance.php (today and this month)" (`backfill.py:568-569`).
   - `src\bot\scheduler.py:490` says "# 6. Jennie's brain stays in VRAM (loaded at startup by post_init)". Stale since `c17d887` (28 Sep): with the voice off the brain loads on demand, and `keep_brain_warm` (`scheduler.py:317-325`) returns at once unless `ollama_client.brain_pinned()` (`JENNIE_VOICE_ENABLED` or `BRAIN_ALWAYS_LOADED`, `ollama_client.py:37-39`).
4. **The gateway's body limit is unmeasured**; the 1,000,000-byte cap is an assumed budget.
5. **Deletes never cascade across kinds:** a student removed from the portal disappears from `student` at the next whole read, but their `student_profile`, `student_progress`, `verification` and document rows stay until their own scopes are read whole (per-passport scopes only by the backfill or a new check).
6. **Kinds that are never deleted by design:** `calendar_item` (events past the page's window stay), `report` (every day's report stays), `notification`, `field_correction`, the per-day `consultation_day` outside a backfill, and past `consultant_performance` windows. Jeannie must date what she says (`day`, `read_at`, `hg_runs`).
7. **Filler words inside longer texts are kept** (a consultation's details and remarks, the student details' composite Passport answer, "Pending" in `student.applications`): the portal's own wording. A strict R1 scan over whole texts will find them.
8. **`progress_builder.clean_value` blanks Bangla-only cells in the Google Sheets** (an ASCII-only comparison). The Supabase export no longer uses it, but the sheet sync still does. Fixing it touches the staging copy of `progress_builder.py` (R24).
9. **Two students show two different e-mail addresses** on students.php (the details and the Student cell / CSV); `/sendmail`'s CSV path and its list fallback would pick different ones.
10. **The first brief publish** will be 1 Oct 18:05; the brief, `/missing`, `/stage` and the issue refresh had not published by the time of writing (the path is covered by tests and the preflight's fake-Telegram check).
11. The old dry-run payload folders (about 100 MB each, full student data) are gitignored under `C:\Hangeul\JARVIS\cloud\all\data\cloud\dry_run\` and `C:\Hangeul\JARVIS\cloud\release\data\cloud\dry_run\`. They should be deleted after review, like the other scratch folders listed in [11 §F](11_OPEN_ITEMS_AND_KNOWN_LIMITS.md).

---

## 19. Rebuild checklist (for a new bot)

1. Get the schema from the reader's repo (or put §3.11's file, verbatim, into its `supabase\migrations\`). Apply it with the Supabase CLI from that repo. Never create tables from the bot (D12). Verify with a GET of `/rest/v1/hg_runs?select=id&limit=1` (200, not 404 / PGRST205).
2. Add the settings of §14.1 with publishing **off**, the redaction patterns of §14.2 on every request logger, and pin the embedding packages and the model revision. Fetch the model once, with the owner's OK.
3. Write `records.py` first: one pure function per kind from what the readers already return (§5; the helpers it takes from the rest of the bot, with their contracts, are in [03d §12.8](03d_FILES_src_cloud.md)), `make` / `content_hash` exactly as §4.2, the filler rule and `blank_on_portal` (§6). Test every kind from synthetic input, with no placeholder anywhere.
4. Write the engine (§7): the hash state with the scope and read time beside each hash, forgetting gone keys only after an accepted delete, dropping the digest before the first call, read ordering, 200 rows / 250 chunks / 1 MB, `p_all_keys` only on the last call of a complete read, the model guard, one lock, runs, the dry run, and short reasons from statuses and codes only.
5. Write the embedder (§8): CPU only with `CUDA_VISIBLE_DEVICES=-1` set before torch, float32, offline, chunks of at most 350 words and 510 tokens with the heading repeated, and a stub for tests.
6. Write the handoff (§9) and the publisher entry point with its deadline. Only then hook the jobs, always **after** their own work, never raising, never printing into a button report's stdout.
7. Decide each kind's complete rule with R2 and R5 (§5); when in doubt, partial. Never send a complete batch from a read that failed.
8. Write the tests before the hooks: a fake Supabase (`httpx.MockTransport`) that answers `hg_sync` like the SQL (upsert by `(kind, key)`, delete by `p_all_keys` in `(kind, scope)`) and fails on any other host or method; the failure cases of §10; the scheduler registration.
9. Dry-run against the live source with a network guard, and check the payloads with your own code (§15.4) until every check passes. Then run the real backfill, run an independent postcheck (§15.5), and only then turn publishing on after a scheduled job has run (M6). Watch `hg_runs`.
