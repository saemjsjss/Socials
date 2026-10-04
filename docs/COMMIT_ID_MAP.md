# Commit id map

Every commit of the bot's history was rewritten before publishing (see [SCRUB_NOTES.md](SCRUB_NOTES.md)):
authors, dates and order are unchanged, but every commit id changed. The reference documents under
[reference/](reference/) and the bot's older documents quote the OLD ids from the office PC; use this table
to find the same commit here.

| date | old id (office PC) | new id (this repository) | subject |
|---|---|---|---|
| Mon Sep 28 01:51 | `7241465` | `55bcc14` | Run the passport watcher's OCR off the event loop so the bot never goes deaf |
| Mon Sep 28 01:51 | `d9bbecc` | `681ad1c` | Make Jennie fast and conversational: instant filler, resident brain, memory |
| Mon Sep 28 11:24 | `cd0277a` | `622314f` | Read consultation requests by column name; the portal's new layout zeroed every count |
| Mon Sep 28 13:51 | `f8fefa4` | `476a690` | Factual daily brief: every figure counted from live portal reads |
| Mon Sep 28 14:31 | `e0d47ab` | `76cae6b` | Foundation: strict dates, long replies, one portal session, all-pages students reader |
| Mon Sep 28 15:00 | `46cdf03` | `7be92d0` | Inquiries: read each day with the portal's date filter, all-time from its tabs |
| Mon Sep 28 15:12 | `9dcd9ad` | `7abb075` | Scheduled jobs and sheet reports: every page, no lost alerts, real stages |
| Mon Sep 28 15:18 | `40da0e6` | `515984b` | Cross-check and passport commands: pick students by their own verification stamp on every page, live /passports, honest OCR verdicts |
| Mon Sep 28 15:31 | `7f42ad0` | `9797406` | Free text, Jennie and /calendar: whole-word routes to live reads, no LLM guesses |
| Mon Sep 28 15:34 | `65fdba1` | `771aebb` | Merge fix/inquiries: consultation days via the portal's date filter, all-time totals from its status tabs |
| Mon Sep 28 15:34 | `638655b` | `30e8b8f` | Merge fix/crosscheck: stamp-picked cross-checks on every page, live /passports, honest OCR verdicts |
| Mon Sep 28 15:37 | `df021de` | `f340d71` | Merge fix/freetext: whole-word free-text routes to live reads, /calendar dates, honest Jennie |
| Mon Sep 28 15:38 | `981d63d` | `d0bb6bb` | Merge fix/jobs: watcher on every page with no lost alerts, real stages, honest sync |
| Mon Sep 28 15:53 | `344a247` | `cb9a260` | Integrate the fix branches: merge leftovers, honest /alerts, every page for the last raw reads |
| Mon Sep 28 17:03 | `e164679` | `72b71d9` | Repair the verifiers' last cases: live progress pages, calendar ids, honest dates and OCR claims |
| Mon Sep 28 17:45 | `c17d887` | `8577347` | Last re-verify cases, and the brain on demand when the voice is off |
| Sun Sep 27 05:22 | `366dec0` | `db347d9` | Baseline: GitHub snapshot of hangeul-bot as downloaded |
| Sun Sep 27 05:23 | `c5c1a7c` | `1b0c07a` | Refuse all Telegram users when no admin chat ID is configured |
| Sun Sep 27 05:23 | `f74e45d` | `81bf06a` | Downgrade the two known-false FAIL rules to FLAG before the cold start |
| Sun Sep 27 05:30 | `a012bcb` | `36ba743` | Pin requirements to the versions proven on this PC, torch-first |
| Sun Sep 27 05:53 | `053efc5` | `78d1990` | Make launchers self-locating and pin them to the bot's venv |
| Sun Sep 27 05:53 | `4154aa5` | `8c0a0da` | Make every data location configurable, defaulting beside the bot folder |
| Sun Sep 27 06:21 | `d659983` | `e0117b5` | Build the OCR reader with verbose=False so its first download cannot crash |
| Sun Sep 27 06:43 | `03ccf15` | `2500a17` | Audit every student in phase 3, not 78 of 326 |
| Sun Sep 27 14:37 | `b0245df` | `3721de1` | Rewrite MIGRATION.md from the move that actually happened |
| Sun Sep 27 20:00 | `0fce479` | `2a50cec` | Redact the Telegram bot token from every log line |
| Sun Sep 27 20:00 | `d7a5817` | `ba77413` | Add Jennie's voice: Telegram voice notes in, text and voice notes out |
| Sun Sep 27 20:19 | `e205327` | `a867c45` | Redact URL-encoded bot tokens, and send unparseable LLM answers as plain text |
| Tue Sep 29 11:28 | `36ae72e` | `9748475` | Publish layer for Supabase: records, hash state, hg_sync, runs, handoff, backfill |
| Tue Sep 29 11:30 | `a0572ba` | `5ec0a40` | Write two invisible characters in the cloud code as chr() calls |
| Tue Sep 29 11:33 | `cfd10f1` | `fafe786` | A complete key list for batches that carry only some records |
| Tue Sep 29 11:58 | `2b6798f` | `1610e67` | Publish what the command handlers and free-text answers read, after the reply |
| Tue Sep 29 12:02 | `5048a07` | `6f0f794` | Publish the bot's own jobs to Supabase: the brief, the watcher, an hourly full picture |
| Tue Sep 29 12:03 | `41055de` | `62bb448` | Hook the sheet jobs into the Supabase publish layer |
| Tue Sep 29 12:05 | `112325b` | `3233807` | Merge cloud/inproc: the brief, the watcher and the hourly full picture publish too |
| Tue Sep 29 12:05 | `44c9378` | `9348ce1` | Merge cloud/jobs: the sheet jobs hand their reads to the Supabase publish layer |
| Tue Sep 29 12:05 | `969f917` | `b679f34` | Merge cloud/commands: command handlers and free-text answers publish what they read |
| Tue Sep 29 12:15 | `cb16394` | `f2b41ee` | Integrate the Supabase hooks: one tile record, the watcher's profiles and alerts |
| Tue Sep 29 14:25 | `3caa393` | `4f2d52d` | Fix the review findings of the Supabase publish layer |
| Tue Sep 29 15:26 | `752cd53` | `c24d165` | Fix the dry run's findings: portal fillers, one line a run, real CUDA hiding, body cap |
| Tue Sep 29 16:19 | `9ead47d` | `eb83425` | Decode Cloudflare's hidden e-mail addresses; one log line for a missing model |
| Tue Sep 29 21:41 | `bbd8f98` | `bde5af4` | Team performance today and this month: /performance_today, /performance_month |
| Wed Sep 30 10:29 | `a721066` | `9405524` | Performance report: honest last line, "this months", no stand-in month, other topics keep their routes |
| Wed Sep 30 13:34 | `ce23535` | `4242585` | Performance is the portal's Consultant Performance page, and only its data |
| Wed Sep 30 14:04 | `314afdb` | `6a76100` | Performance: the owner's spelling, "performance" for another day, whole records, the real empty state |
| Wed Sep 30 21:04 | `e5e532e` | `13bea5c` | Merge main into cloud/release: the Consultant Performance page next to the Supabase layer |
| Wed Sep 30 21:16 | `e4d1cea` | `8e7959b` | Publish the Consultant Performance page to Supabase: kind consultant_performance |
| Wed Sep 30 21:45 | `8317741` | `e1a3638` | consultant_performance: a scope that stays put all month; the backfill reads the page |

48 commits. The documentation commit and the merge with this repository's first commit come after them.
