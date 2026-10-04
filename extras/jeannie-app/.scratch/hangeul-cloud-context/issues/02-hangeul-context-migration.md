# hangeul_context migration

Status: ready-for-human (written, tested and applied to dcbcbpwpmdtaanboetiz; review only)

Ticket 2 of the spec's §10. See spec §4, D6, D13, D14, D16.

## What

`supabase/migrations/20260929030000_hangeul_context.sql`: `hg_runs`, `hg_records`, `hg_chunks` (vector(384), HNSW),
`hg_changes` with its trigger, the RPCs `hg_sync`, `hg_match` and `hg_changes_since`, RLS on with no policies, and
execute granted to `service_role` only. It is applied to the project, and Hangeul BOT's backfill (30 Sep 22:05)
wrote 13,540 records and 15,629 chunks through it.

**Never change or re-apply it.** A schema change is a new migration, and the bot's contract
(`C:\Hangeul\BOT\src\cloud\records.py`, `C:\Hangeul\REFERENCE\13_SUPABASE_PUBLISHING.md`) changes with it.

## Tests

`tests/hangeul-migration.test.ts` (PGlite with pgvector and pg_trgm, synthetic rows).

## Facts the readers depend on (from the live checks, 30 Sep and 1 Oct)

- PostgREST caps every response at 1,000 rows, `hg_changes_since` included (`p_limit` 5000 returns 1000).
- A select on `hg_chunks` returns the vector as pgvector text `"[...]"`; `hg_changes_since` returns a JSON array.
- `read_at` moves only when a record's content changes (`hg_sync` skips same-hash rows). The "as of" time comes from
  `hg_runs` (`counts.by_kind` names every kind a run read), never from `read_at` alone.

## Comments
