# Hangeul store and API routes

Status: ready-for-human (implemented on saem/hangeul-context-reader; owner review, merge and deploy)

Ticket 4 of the spec's §10. See spec §5 ("API routes"), D8, D9, D13, D14.

## What was built

- `src/lib/hangeul/store.ts` (server, Edge-safe: fetch and btoa only). Typed PostgREST reads with the secret key,
  read-only (never `hg_sync`, never a write):
  - `readRecords(kind, filter)`: every `RecordFilter` field (`key`, `keys`, `keySuffix`, `scope`, `scopePrefix`,
    `day`, `from`/`to`, `studentUid`, `studentHngId`, `passportNo`, `dataEq`, `order`, `limit`) becomes a PostgREST
    parameter, and every row is re-checked with `filter.ts` (the same meaning the device copy uses). Values in
    `in.(...)` are double-quoted with `\` and `"` escaped (keys hold `|`, spaces, `#`, `.` and parentheses).
    Lists page past the 1,000-row cap until a short page. A long key list goes out 50 keys a request.
  - `findStudents`: HNG id, uid (the student key), passport (exact), then name: exact (`ilike`, any case), then
    every token (`and=(student_name.ilike.*t*,...)`), ranked in code (`rankStudents`).
  - `readRuns(kinds)`: the 200 newest finished runs (ok or partial), plus, for a kind none of them read (the
    backfill-only kinds), the newest run whose `counts->by_kind` contains it (`cs.{"kind":[]}`).
  - `readChanges(sinceIso)` (keyset by seq), `readMaxSeq`, `readChangesSince(seq, limit)` (the RPC, vectors
    re-encoded as base64 float32, cut to a 3 MB page), `readSnapshotPage(cursor)`, `matchChunks` (hg_match),
    `embedQuestion` (the hg-embed function of ticket 3), `countRecords` (`Prefer: count=exact`), `readDataStatus`.
  - Timeouts: 3 s for answer reads, 10 s for the bulk device sync (snapshot, changes), 6 s for hg_match (a cold HNSW
    scan passed 3 s once in the live check; warm it is ~0.3 s). Every failure is a `HangeulReadError` with a plain
    reason ("Hangeul data unreachable (timeout)", "Hangeul tables are missing (not migrated)") and a code; never an
    empty list, never a silent 0 (R5). Reasons and logs never hold row data, keys or URLs.
- Snapshot paging: a keyset cursor over the 26 kinds of `HG_KINDS` (the bot's `CLOUD_KINDS` order), then key
  order: `kind=eq.K&key=gt.<last>&order=key.asc`, with the chunks of the same key range. Offsets are not stable under
  deletes; the keyset is. The first page reads `max_seq` before anything else, and every page carries it. Pages are
  cut to ~3 MB of UTF-8 (Vercel's cap is 4.5 MB, in bytes; Bangla or Korean OCR text is 3 bytes a character, so the
  budget counts bytes, not characters). A chunk whose text equals its record's text leaves `content` out.
- Routes (Node runtime, `force-dynamic`), all behind the memory-style gate (`src/lib/hangeul/http.ts`): 403 when
  `JEANNIE_ACCESS_KEY` is not set, 401 when it is not presented, 503 when Supabase is not configured or the tables
  are missing, 502 when Supabase fails. This is stricter than `requireAccess` alone, which is open on a deployment
  with no key: the data holds full student records (D2).
  - `GET /api/hangeul/snapshot?cursor=`, `GET /api/hangeul/changes?since=&limit=`, `POST /api/hangeul/ask`.
  - `GET /api/hangeul`: the HUD panel's data status (records, latest run per job, latest brief and report keys; no
    student data). It replaces the portal bridge's `?action=report|status` and `POST` actions.
  - `GET /api/status` (Edge, still open) adds `hangeul: {configured, records, lastRuns}`; `records` and `lastRuns`
    only for a caller with the key, read with a 1.5 s timeout that falls back to null.

## Wire formats (for tickets 6 and 7)

Every route: send the key as `x-jeannie-key: <key>` (or `Authorization: Bearer <key>`). Errors are JSON
`{"error": "<plain text>", "code": "<code>"}` with `cache-control: no-store`: 403 `access_key_not_configured`,
401 `access_key_required`, 503 `hangeul_not_configured` / `hangeul_not_migrated`, 502 `hangeul_unavailable`,
400 `invalid_request` / `invalid_json` / `invalid_cursor`.

A record (`HgRecord`, `src/lib/hangeul/types.ts`) is the `hg_records` row: `{kind, key, scope, student_uid,
student_hng_id, student_name, passport_no, day ("YYYY-MM-DD" | null), data, content, content_hash?, source?, read_at
(ISO, UTC), run_id, updated_at?}`. A chunk on the wire (`WireChunk`, `store.ts`) is `{kind, key, ord, content?,
embedding, embed_model}`: `embedding` is base64 of 384 little-endian float32 (2,048 characters; `decodeVector` in
`src/lib/hangeul/vectors.ts`), and `content` is absent when it equals the record's `content`.

- `GET /api/hangeul/snapshot` (first page) then `?cursor=<next>` until `next` is null →
  `{max_seq, records: HgRecord[], chunks: WireChunk[], next: string | null, vector: {encoding: "base64-float32le",
  dimensions: 384}}`. Keep the first page's `max_seq`: the device's changes start there. A cursor is opaque; one the
  server did not issue is 400 `invalid_cursor`.
- `GET /api/hangeul/changes?since=<seq>&limit=<1-1000, default 200>` → `{changes: WireChange[], next_seq, more,
  vector}`. An upsert is `{seq, kind, key, op: "upsert", changed_at, record: HgRecord | null, chunks: WireChunk[] |
  null}` (`record` null: deleted since, its delete follows in the feed). A delete is only `{seq, kind, key, op:
  "delete", changed_at}`: drop the record and its chunks. Store `next_seq`, and call again while `more` is true.
  `since` is required (0 for none).
- `POST /api/hangeul/ask` with `{question (1-2000 chars), lang?: "auto" | "en" | "ko" | "bilingual", embedding?:
  number[384] | base64 float32, hits?: {kind, key}[] (at most 24), prose?: boolean}` → `{lang, provider, emote, text,
  prose, answer, plan, result: {headline, facts, tables, notes, asOf, sources, unavailable}, as_of}`. `text` is the
  whole reply (prose then the code-built answer, emote tags stripped), `answer` the code-built part alone, `prose`
  the checked sentences ("" without a model; `prose: false` skips the model). With `hits`, the server re-reads those
  records from current rows; with only `embedding`, it searches with it (`hg_match`).
- `GET /api/hangeul` → `{configured: true, records, lastRuns: [{job, finishedAt, status}], latestBrief: {key, report,
  day, read_at} | null, latestReport: {…} | null}` (no student data).
- `GET /api/hangeul/runs` (added by ticket 7) → `{runs: HgRun[]}`: `{job, started_at, finished_at, status, byKind,
  failedReads}`, the newest 200 finished runs plus the newest run of every kind none of them read. A device syncs
  them before each change-log read, to date its answers. No student data.
- `GET /api/status` (open) → `hangeul: {configured, records: number | null, lastRuns: [{job, finishedAt, status}] |
  null}`; the two volumes only with the key. Also `timeZone` (the business time zone, added by ticket 7).
- `POST /api/chat` accepts `hangeul: {embedding?, hits?}` beside `messages`, used only when the question routes to
  the Hangeul agent.

## Tests

- `tests/hangeul-store.test.ts`: request shapes, quoting, paging, name lookup, the 3 s timeout and every failure
  reason, runs, the delta (base64 vectors, deletes, the byte cut), snapshot paging (every record once, kind order,
  stable when rows are deleted between pages, pages of Bangla OCR text under 4.5 MB of UTF-8), hg-embed and hg_match
  calls, counts.
- `tests/hangeul-routes.test.ts`: every route 403 → 401 → 503 → 200, snapshot paging through the route, change and
  ask validation, `/api/status` with and without the key.
- `tests/hangeul-postgrest.ts`: a small in-memory PostgREST (filters, order, the 1,000-row cap, counts, the read
  RPCs) the two suites run against.

## Live check (1 Oct 00:53-00:55 Dhaka, read-only: PostgREST selects, hg_match, hg_changes_since)

13,546 records. Latest runs: portal sync 00:43, full picture 00:35, passport watcher 00:27, backfill 30 Sep 22:05
(all ok). Snapshot pages: 491 / 689 / 833 records at 3.00 / 2.74 / 2.78 MB, 2-4 s each, vectors of norm 1.0000.
Changes since max_seq-5: 5 rows, 17 KB. hg_match with a stored vector returns that record first (similarity 1.0000),
~0.3 s warm.

Again at 1 Oct 01:56-02:06 Dhaka (same read-only calls): snapshot page 1 was 491 records and 494 chunks, 3.01 MB of
UTF-8, in 2.1 s, `max_seq` 13553; the changes after `max_seq - 50` were 50 rows, 172 KB, in 0.2 s, `more` false.

## Comments

- 1 Oct 2026 (review fixes, "snapshot pages that finish in time, and a sealed cursor"): from this PC the first sync failed part-way at the default timeouts (500 chunks
  with content and vector, 1.6-2.1 MB, often took over the 10 s that covered the body read), and the body-read
  timeout surfaced as a bare "unreachable". Chunks are now read 100 a request, records 200 a batch (60 for the OCR
  pages); a page has a time budget inside the route's 60 s (no new batch after 30 s, no request past 50 s, a batch
  that times out after others ends the page with those), and a body that stops arriving is "unreachable
  (timeout)". The cursor held the last record key (a passport number and a file name) in the GET query string: it
  is now sealed with AES-256-GCM under a key derived by HKDF from the server's secret key, and the device starts its
  first sync over once when the server refuses a saved cursor (a rotated key). The cron bearer no longer unlocks
  student data through the chat on a deployment without JEANNIE_ACCESS_KEY ("the cron bearer never unlocks student
  data through the chat").
- 1 Oct 2026, 04:1x Dhaka, live and read-only after the fixes (`readSnapshotPage` from this PC, default timeouts):
  the whole dump in 20 pages, 13,546 records and 15,635 chunks, 364 s, every page between 11 and 29 s (the slowest
  28.5 s, inside the 60 s route limit); every cursor 80-155 characters, opaque. Still to check: the page time from
  the Vercel region, before the owner's first sync (ticket 8).
