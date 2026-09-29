"""Publishing to Supabase: a second, independent copy of everything the bot reads.

Everything Hangeul BOT parses from the portal and every report it builds is also written to the
owner's Supabase project as structured rows, a text form and gte-small embeddings, so Jeannie
(the owner's web assistant) can answer from it while this PC is asleep. Drive, Sheets, the
.xlsx files and Telegram stay exactly as they are: Supabase is added next to them and never
delays or blocks them (a failure there is one log line).

  records.py   one pure function per kind: reader output -> {key, scope, student_*, day, data,
               content, source, read_at, content_hash}
  embed.py     gte-small on the CPU (384 dimensions, mean pooling, unit length), loaded once
  publish.py   hg_sync calls, the hash state data/cloud_state.json (only changed rows are sent),
               hg_runs rows, the dry run; `python -m src.cloud.publish --from <handoff file>`
  handoff.py   what every job calls: submit(job, batches) writes data/cloud/pending/<time>-<job>.json
               and starts the publisher process without waiting for it
  backfill.py  `python -m src.cloud.backfill [--dry-run]`: the one-time copy of everything

The schema belongs to the Jeannie repo (supabase/migrations/20260929030000_hangeul_context.sql);
this package only writes rows through the hg_sync RPC and the hg_runs table.
"""

# hg_runs.job values. The Supabase side does not check them; these are the names the bot uses.
JOBS = ("portal_sync", "passport_watcher", "daily_brief", "missing_report", "issue_refresh",
        "stage_report", "command", "backfill", "full_picture")
