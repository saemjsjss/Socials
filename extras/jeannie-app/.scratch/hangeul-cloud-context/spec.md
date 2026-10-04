# Spec: Hangeul context in Jeannie (Supabase + offline PWA)

Status: ready-for-human (approved by the owner on 30 Sep 2026; tickets 3-7 are implemented on branch
saem/hangeul-context-reader, not yet merged or deployed; ticket 8 is the owner's live check. The tickets are split
into [`issues/`](issues/).)

Companion: [`hangeul-bot-prompt.md`](hangeul-bot-prompt.md) is the prompt that makes Hangeul BOT publish
its data. Both files share **one data contract** (the tables below). A change to one means a change to the other.

## 1. Goal

The owner opens Jeannie as an installed PWA on their phone and asks anything about the agency: a student,
today's verifications, a document verdict, a passport alert, a deadline, yesterday's inquiries, what changed
since this morning. Jeannie answers **instantly**, from data Hangeul BOT has already read, with exact figures
and an "as of HH:MM" label. The PC does not need to be awake.

## 2. Decisions (from the grill, 29 Sep 2026)

| # | Decision |
|---|---|
| D1 | Supabase project **`dcbcbpwpmdtaanboetiz`** only; ES_bot (`qmjenzloispkyfnksuqr`) is dropped (PR #6). |
| D2 | **Full student data** in Supabase, nothing masked (passport, phone, DOB, parents, address…). |
| D3 | Everything Hangeul BOT parses **plus** every report it generates, **including full OCR text** of documents (one chunk per page). **No binary files.** |
| D4 | Structured rows (source of every figure) **and** text + vectors (fuzzy search). |
| D5 | Snapshots with `read_at` ("as of"); no link from Jeannie to the PC. |
| D6 | Hangeul BOT writes with the **secret key** directly (RPC `hg_sync`). |
| D7 | Supabase is an independent second destination: failures are logged by the bot, no outbox, no blocking. |
| D8 | Protection stays the single **`JEANNIE_ACCESS_KEY`**. No Supabase Auth login. |
| D9 | The phone keeps the **full dataset** (rows + vectors) in IndexedDB. |
| D10 | **Offline = "offline" banner, nothing else.** The on-device copy exists for speed while online (retrieval with no network round trip), not for offline answers. |
| D11 | **Code builds every table and figure** from Supabase rows. DeepSeek receives the question, the field names **and the values, PII included**, and only writes the words around code-built facts. |
| D12 | Embeddings: **gte-small** (384-d, mean pooled, normalised). Computed **on the PC** for data; for questions, in the browser (`Supabase/gte-small` via transformers.js) or, before the phone has synced, by a Supabase Edge Function (`Supabase.ai` `gte-small`). |
| D13 | Latest state **plus a change log**; the phone syncs by change-log cursor. |
| D14 | **Hard delete**; the change log keeps only `{kind, key, op: delete, changed_at}`. |
| D15 | One-time **backfill** (done by the bot's `src.cloud.backfill`). |
| D16 | This repo owns the schema (`supabase/migrations/`). |
| D17 | Credential rotation deferred (accepted risk). |

### Accepted risks (recorded, not re-proposed)

- Every student's passport number, phone, DOB and parents' names are readable by anyone holding the one access
  key, sit in plain IndexedDB on the owner's phone, and are sent to DeepSeek when relevant to a question.
- The PC's `.env` will hold a key that can read and delete all of it; that `.env` and the Google token were already
  exposed in chats (B7) and rotation is deferred.
- If the access key leaks, rotating `JEANNIE_ACCESS_KEY` in Vercel cuts off new reads, but data already synced to a
  device stays there.

## 3. Current state (what exists today)

- Memory: `memory_documents`, `memory_chunks`, `jeannie_sessions`, `jeannie_audit_log` + `upsert_memory_document`,
  `match_memory` (FTS, `simple` config). Migrations were applied to **ES_bot only**; the new project is empty.
- `src/lib/memory/supabase.ts`: small PostgREST fetch client (Edge-safe), reads `SUPABASE_URL` /
  `SUPABASE_SERVICE_ROLE_KEY ?? SUPABASE_SECRET_KEY`.
- `src/lib/agents/hangeul-bridge.ts` calls portal JSON endpoints (`HANGEUL_REPORT_PATH=/api/reports/daily`) that the
  portal **does not have** (reference pack 01 §7: "the portal has no API"), so it always falls back to **demo data**.
  That violates the pack's R1 (never present placeholders as data) and is replaced here.
- No PWA: no manifest, no service worker.

## 4. Supabase schema (migration `supabase/migrations/<ts>_hangeul_context.sql`)

Load the `supabase` and `supabase-postgres-best-practices` skills before writing it.

- `create extension if not exists vector with schema extensions;`
- **`hg_runs`** `(id uuid pk, job text not null, started_at timestamptz not null, finished_at timestamptz,
  status text check (status in ('ok','partial','failed')), counts jsonb not null default '{}', note text)`.
- **`hg_records`** `(kind text, key text, scope text not null, student_uid integer, student_hng_id text,
  student_name text, passport_no text, day date, data jsonb not null, content text not null,
  content_hash text not null, source text not null, read_at timestamptz not null, run_id uuid references hg_runs,
  updated_at timestamptz not null default now(), primary key (kind, key))`.
  Indexes: `(kind, scope)`, `(kind, day)`, `(student_uid)`, `(student_hng_id)`, `(passport_no)`,
  `lower(student_name) gin_trgm_ops` (pg_trgm, for name lookups), `(updated_at)`.
- **`hg_chunks`** `(kind text, key text, ord integer, content text not null, embedding extensions.vector(384) not null,
  embed_model text not null, primary key (kind, key, ord), foreign key (kind, key) references hg_records on delete cascade)`.
  HNSW index `embedding vector_cosine_ops`.
- **`hg_changes`** `(seq bigserial pk, kind text, key text, op text check (op in ('upsert','delete')), data jsonb,
  changed_at timestamptz default now(), run_id uuid)`, index `(seq)`. Filled by an `after insert or update or delete`
  trigger on `hg_records`: an update logs only when `content_hash` changed; a delete logs `data = null` (D14).
- **RPC `hg_sync(p_run uuid, p_kind text, p_scope text, p_rows jsonb, p_all_keys text[] default null) returns jsonb`**:
  upsert each row on `(kind, key)` where the hash differs, replace its chunks, then, if `p_all_keys` is not null, delete
  rows of `(p_kind, p_scope)` whose key is not in it. Kinds listed as append-only (`field_correction`) are never deleted.
  Returns `{"upserted", "deleted", "unchanged"}`. Validates `jsonb_typeof`, 384-length vectors and a single
  `embed_model` per call; rejects batches over 200 rows.
- **RPC `hg_match(p_embedding vector(384), p_count int default 12, p_kinds text[] default null, p_day_from date default null,
  p_day_to date default null, p_student_uid int default null)`** → `kind, key, ord, content, similarity` + the record's
  `data`, `day`, `read_at`, `student_*`, ordered by cosine distance. For the server path (before the phone has synced).
- **RPC `hg_changes_since(p_seq bigint, p_limit int default 1000)`**: rows of `hg_changes` after `p_seq`, joined to the
  current record and chunks for upserts (so the phone gets data + vectors in one call).
- **Security** (same as the memory tables): RLS enabled on all four tables with **no policies**; `revoke all` on the
  tables and functions from `anon`, `authenticated`, `public`; `grant execute` on the RPCs to `service_role` only;
  functions `security invoker`, `set search_path = ''`. Only Jeannie's server routes (secret key) and the PC bot touch them.
- Also apply the two existing memory migrations to this project (they were only on ES_bot).

**Edge Function `hg-embed`** (`supabase/functions/hg-embed/index.ts`): `POST {texts: string[]}` → `{embeddings}` using the
built-in `Supabase.ai.Session('gte-small')` (`mean_pool: true, normalize: true`). Requires the secret key in
`Authorization` (verify_jwt off, checks the key itself). Used only by Jeannie's server for question embeddings before a
device has its own model loaded.

## 5. Jeannie server (`src/lib/hangeul/`, new; replaces the portal-API bridge)

- `store.ts`: typed reads over PostgREST: `findStudents(query)` (HNG id, uid, passport, exact then trigram name),
  `records(kind, {day, from, to, studentUid})`, `latestRuns()` (for "as of"), `match(embedding, opts)`,
  `changesSince(seq)`, `snapshotPage(cursor)`. Timeouts (3 s), fail closed with a plain reason (never a silent 0, R5).
- `answer.ts`: **code-built answers** (D11). An intent router (whole-word rules, like the pack's `ask.classify`) maps a
  question to a **query plan**: `student_card`, `verified_on_day`, `inquiries_on_day`, `pending_payments`,
  `window_review`, `doc_verdicts`, `passport_alerts`, `calendar_window`, `missing_for_student`, `changes_since`,
  `report(brief|missing|stage|document_check|field_check, day)`, or `semantic` (vector search). Each plan returns
  `{facts: Fact[], tables: Table[], asOf: {kind: read_at}, sources}`, all computed in code from rows.
- **DeepSeek's role**: it gets the question, the facts and tables (values included, D11) and writes at most two
  sentences around them. The reply shows the code-built facts and tables **verbatim**; the prose passes a number check
  (every number in it must appear in the facts; else the prose is dropped and the facts stand alone), which is the pack's
  `claims_problem` rule in its simplest form (R7).
- `semantic` plan: embed the question (device vector sent by the PWA, or `hg-embed`), `hg_match` (or the device's own
  results, see §6), then group hits by record and render each record's structured `data` as a card. Korean or Bangla
  questions: DeepSeek first rewrites the question into an English search query (the stored text is English).
- Every answer ends with the as-of line: `As of 18:21 (portal sync) · brief 18:05`. A kind never published says
  "not available yet", never 0.
- Orchestrator: route Hangeul questions (the existing `hangeul-bridge` routing cues) to this module; remove the demo-data
  path and the `HANGEUL_*` portal credentials from Jeannie (Jeannie never talks to the portal).

### API routes (all behind `requireAccess`, Node runtime)

| Route | Purpose |
|---|---|
| `GET /api/hangeul/snapshot?cursor=` | paged full dump for a device's first sync: records + chunks (vectors as base64 float32), `max_seq` to start the delta from; ~500 records a page, gzip |
| `GET /api/hangeul/changes?since=<seq>` | delta for a device (D13, D14) |
| `POST /api/hangeul/ask` | server-side answer when the device has not synced yet or for plans that need fresh server state; body may include the device's question embedding |
| `GET /api/status` | adds `hangeul: {configured, records, lastRuns}` |

## 6. PWA (`public/manifest.webmanifest`, service worker, `src/lib/client/hg-local/`)

- Installable PWA: manifest (name "Jeannie", icons, `display: standalone`, theme colours from the HUD), a service worker
  that caches the app shell only. **No student data in the SW cache**; data lives in IndexedDB.
- **Offline** (D10): when `navigator.onLine` is false or the API is unreachable, show a clear "Offline: Jeannie needs a
  connection" banner and disable the input. No offline answers.
- **Local store** (D9): IndexedDB database `jeannie-hg` with stores `records` (`[kind,key]` → row), `chunks`
  (`[kind,key,ord]` → `{content, embedding: Float32Array}`), `meta` (`max_seq`, `embed_model`, `synced_at`).
  First sync pages through `/api/hangeul/snapshot` (ask before starting on mobile data; show progress: expect tens of MB
  with the OCR text), then `/api/hangeul/changes` on open, on focus, and every 5 min while open; deletes remove the record
  and its chunks.
- **Local search**: transformers.js loads `Supabase/gte-small` (quantized, cached by the browser once) in a Web Worker;
  the question's vector is compared against all local chunk vectors (brute-force cosine over Float32 arrays; tens of
  thousands of 384-d vectors take well under 100 ms on a phone). The top hits' records go to `/api/hangeul/ask` as
  `{question, embedding, hits: [{kind,key}]}` so the server answers from **current** rows (it re-reads those keys) and
  DeepSeek phrases it. Structured plans (student card, verified on day…) can render straight from IndexedDB for speed,
  with the same code (`answer.ts` is isomorphic: no Node APIs).
- **Embed-model check**: on first sync, embed three stored chunk texts on the device and compare with their stored vectors;
  cosine < 0.98 → log it and fall back to server search (`hg-embed` + `hg_match`) so a model mismatch never returns
  wrong hits silently.
- Settings: "Re-sync everything" and "Delete local copy" buttons (the only way to remove the data from a device).

## 7. Config

- Vercel: `SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co`, `SUPABASE_SECRET_KEY` (new project),
  `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` only if still used; remove `HANGEUL_BASE_URL`,
  `HANGEUL_USERNAME`, `HANGEUL_PASSWORD`, `HANGEUL_REPORT_PATH`, `HANGEUL_STATUS_PATH` from Vercel and `.env.example`.
- Re-upload `profile.md` (pinned) and `saemur-knowledge.jsonl` through the Memory panel after the memory migrations are
  applied to the new project.

## 8. Tests (vitest, no network)

- Migration: a SQL test script (run against a Supabase branch or local stack) for `hg_sync` upsert/unchanged/delete
  semantics, the `p_all_keys` null guard, append-only kinds, the change-log trigger (upsert logs data; delete logs null),
  `hg_match` ordering, and that `anon` / `authenticated` get permission denied on every table and RPC.
- `store.ts`: request shapes with a mocked fetch; timeouts fail closed with a reason.
- `answer.ts`: each plan from synthetic rows gives exact figures; missing kind → "not available yet"; as-of line;
  the prose number check drops a sentence with a number not in the facts.
- Router: whole-word intents (no "across" → cross-check class of bugs).
- `hg-local`: sync applies upserts and deletes from a fake changes feed; cosine search returns the right record; model
  mismatch falls back to the server.
- Routes: all require the access key; snapshot paging is stable.

## 9. Verification (live, after the bot's backfill)

1. `hg_records` counts per kind match the bot's report; every chunk 384-d, one `embed_model`.
2. On the phone: install the PWA, first sync completes, airplane mode shows the offline banner.
3. Ask: "Who is HNG-2026-12?", "How many payments were verified on 12 Sep?" (compare with `/verified_date 12 Sep`
   on Telegram), "Any passport alerts today?", "What does <name>'s bank statement say about the opening balance?"
   (OCR page hit), "What changed since this morning?". Each answer shows code-built figures and an as-of time.
4. Delete test: a record removed by the bot disappears from the phone after the next delta.

## 10. Tickets (split into [`issues/`](issues/), one file each)

1. Apply the memory migrations to the new project; point Vercel at it; re-upload memory files.
2. `hangeul_context` migration (tables, trigger, RPCs, grants) + SQL tests.
3. `hg-embed` Edge Function.
4. `src/lib/hangeul/store.ts` + routes (`snapshot`, `changes`, `ask`, status).
5. `answer.ts` plans + number check; wire into the orchestrator; remove the portal-API bridge and demo data.
6. PWA shell: manifest, service worker, offline banner.
7. `hg-local`: IndexedDB sync, transformers.js worker, local search, model check, settings buttons.
8. Live verification with the owner after the Hangeul BOT backfill.

## Comments

- 1 Oct 2026: approved by the owner on 30 Sep and built on `saem/hangeul-context-reader`. Two kinds beyond the
  tables above are published and used: `doc_check` (one verdict per passport) and `consultant_performance` (the
  portal's Consultant Performance page: keys `<period>|<first ISO day>|<name>`, scope `<period>|<first ISO day>`,
  and a `|summary` record with the tiles "Consultancies done", "Files opened", "Conversion (file open)", "Docs ready"
  and the top performer). The owner's question "how many consultancies were closed today?" is answered from that
  summary and the day's consultation rows (ticket 5). The source of truth for every kind is the bot's
  `src/cloud/records.py` and the pack's `13_SUPABASE_PUBLISHING.md`.
