# Memory on the new Supabase project

Status: ready-for-human (owner: Vercel settings and memory files; no code left)

Ticket 1 of the spec's §10. See spec §3, §7, D1.

## What

Jeannie's memory and the Hangeul context share one project, `dcbcbpwpmdtaanboetiz` (D1). ES_bot is dropped.

- Migrations for memory: `supabase/migrations/20260928000000_jeannie_memory.sql`,
  `20260928180000_jeannie_memory_revoke_public.sql`, `20260929030100_jeannie_memory_grant_service_role.sql`.
- The code needs no change: memory and the Hangeul store read the same `SUPABASE_URL` and
  `SUPABASE_SECRET_KEY` (`src/lib/env.ts`, `memory` and `hangeul` blocks).

## Owner steps

1. Check the three memory migrations are applied to `dcbcbpwpmdtaanboetiz`. If not, apply them in the SQL editor,
   in file-name order.
2. In Vercel, set `SUPABASE_URL=https://dcbcbpwpmdtaanboetiz.supabase.co` and `SUPABASE_SECRET_KEY` (the new
   project's secret key). Remove `HANGEUL_BASE_URL`, `HANGEUL_USERNAME`, `HANGEUL_PASSWORD`,
   `HANGEUL_REPORT_PATH` and `HANGEUL_STATUS_PATH` (Jeannie no longer reads them, spec §7).
3. Re-upload `profile.md` (pinned) and `saemur-knowledge.jsonl` through the HUD's Memory panel.

## Comments
