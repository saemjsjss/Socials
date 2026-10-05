# Code review, 5 Oct 2026

A read-only correctness review of the live bot at office-PC commit `8317741` (`e1a3638` here). It ran in five passes: tests plus secrets, Telegram and the scheduler, the sheets sync, the verify/OCR pipeline, and the Supabase publish layer with the API. **Nothing was changed.** Each finding was checked against the code; *confirmed* means the code path was read end to end, and *plausible* means the trigger depends on something not proven.

Left out because the owner already decided them: `API_HOST` stays `0.0.0.0`, the passport watcher marks every alert as sent but sends only 3, the portal re-login loop has no cap, "page 1 is not an e-Apostille" stays FAIL, and the two rules downgraded to FLAG stay FLAG. The OCR limits (6 pages per file in the automatic pass, a failed first read cached as FLAG, rotation retries that swallow errors) are covered in [ocr-checker/](ocr-checker/README.md).

## Tests and secrets

- `pytest -q`: **1149 passed, 1 failed, 2 skipped.** The failure, `tests/test_cloud_commands.py::test_nothing_is_kept_or_started_while_publishing_is_off` (line 126), comes from the PC's state, not the code. The test looks at the real `data/cloud/pending` folder (`BOT_ROOT`, line 32), and that folder now exists, empty. The test should use a temporary folder.
- **No real token, password or key** is in the code. Every token-shaped string is a test value or a redaction pattern.
- Real passport numbers and names in the office PC's repo (`HANDOFF.md`, `PC_BUILD.md`, `SKIP_PASSPORTS`, comments) and `test_passport.jpg` were already replaced or removed in this repository ([SCRUB_NOTES.md](SCRUB_NOTES.md)).

## Most important

| # | Where | Defect | Confidence |
|---|---|---|---|
| 1 | `src/api/routes/*`, `src/api/main.py:33-45` | No API route checks who is calling. Anyone on the LAN can read student lists, inquiries and consultations. CORS `*` with credentials lets any web page a staff member opens call the routes too. | confirmed |
| 2 | `src/api/routes/crawler.py:8-12` → `client.py:741-767` | `POST /api/crawler/parse-page` GETs any portal path the caller chooses, using the admin session. | confirmed |
| 3 | `src/api/routes/auth.py:13-19` → `client.py:155-156` | `POST /api/auth/login` with `{}` logs in with the `.env` account. | confirmed |
| 4 | `doc_verifier.py:599-601`, `field_check.py:121-122` | The GPA check strips trailing zeros, so "5.00" becomes "5", which matches almost any text. A wrong GPA of 5.00 or 4.00 passes. | confirmed |
| 5 | `doc_verifier.py:897-905` | Tax paid is read with `find_money_taka`, which only returns amounts of 100,000 or more. Real tax amounts (10k-99k) are always FLAGged, and an income figure is reported as tax paid. | confirmed |
| 6 | `doc_verifier.py:295, 689` | Any bare run of 6-9 digits counts as taka. A reference number or a date like 20260915 can pass the bank minimum. | plausible |
| 7 | `doc_verifier.py:453-455` | The NID name check uses the first name token as a substring and doesn't skip titles. "MD" matches almost anything. `name_tokens` exists but isn't used here. | confirmed |
| 8 | `cloud/publish.py:689-726` | An empty complete batch with no `read_at` skips the ordering check and deletes the whole scope. A late empty `/verified` batch can wipe a newer record. | confirmed |
| 9 | `auto_sync.py:237-242`, `progress_builder.py:236-274` | An export that parses but has no Direct rows empties every progress sheet and resets change tracking. | plausible |
| 10 | `telegram_bot.py:1446` | `/sendmail` sends SMTP inside the event loop, which freezes the bot for up to about 90 s. | confirmed |

## Telegram and scheduler

- `telegram_bot.py:2374`: the bot handles one update at a time, so `/crosscheck_range` (up to about 92 days of OCR) holds every other command for minutes. *confirmed*
- `telegram_bot.py:2232-2240`: when `_run_report_module` times out, it never kills the child process, so orphaned processes pile up. *confirmed*
- `telegram_bot.py:2004`: an unanswered `/crosscheck_date` prompt takes over a later typed question; "how many inquiries today" starts an OCR cross-check. *confirmed*
- `run.py:92-100`: if uvicorn exits, for example because port 8000 is in use, the Telegram bot stops with it. *plausible*
- `telegram_bot.py:1388-1402`: Markdown in `/sendmail` has no plain-text fallback, so a `*`, `_` or backtick in a name or query loses the reply. *plausible*
- `scheduler.py:448-509`: the interval jobs keep the default 1 s misfire grace, so a busy loop silently skips a 15 or 30 minute run. *plausible*

## Sheets sync and downloads

- `auto_sync.py:243-270`: the sync is all-or-nothing. One failing sheet loses every sheet's report and saved state for that run. *confirmed*
- `progress_builder.py:492-519`: clear, resize and write are separate calls, so an error after the clear leaves a blank main tab until the next run. *confirmed, temporary*
- `progress_builder.py:441` / `missing_report.py:119` vs `progress_builder.py:488`: the code disagrees on which tab is the main one. Moving a university tab to the front causes a "restored" message every 15 min. *confirmed logic*
- `auto_sync.py:439, 448`: `sheet_state.json` is not written atomically. A torn write crashes every later run before any alert goes out. *confirmed path, rare*
- `auto_sync.py:252`: drift -1 (sheet deleted) never triggers a rebuild. *confirmed*
- `auto_sync.py:76-77, 414-417, 480` and `auto_verify.py:465-468`: the locks are check-then-write, a lock is treated as stale after 2 h even when its process is alive, and each run unlinks the lock without checking it owns it. Two runs can overwrite each other's results. *plausible*
- `verified_docs.py:91-93, 357`: two students with the same name and no passport number share one folder. *plausible*
- `verified_docs.py:373-376`: an empty marker is treated as a legacy marker, and changed documents are skipped silently. *confirmed logic*
- `progress_builder.py:443, 493, 516`, `missing_report.py:121`: the apostrophe in a tab name ("BACHELOR'S") isn't doubled inside the A1 range. *Likely harmless:* the Bachelor's sheet rebuilt fine during the 27 Sep cold start.
- `passport_issue.py:71, 109`: `--refresh --limit N` replaces the whole cache with N entries. *confirmed, CLI only*

## Verify and OCR

- `doc_verifier.py:133-150`: an unreadable or zero-page PDF gives FAIL "no notarisation found" instead of "could not read". *confirmed*
- `doc_verifier.py:540-541`: the family certificate's age is counted in whole months, so up to 3 months 30 days passes the 3-month rule. *confirmed*
- `compress_docs.py:91-103`: a PNG is re-encoded as JPEG but keeps the `.png` name. *confirmed*
- `compress_docs.py:57-82`: a failed later profile can leave a truncated temp file that then replaces the original. *plausible, data loss*
- `auto_verify.py:242`: the OCR text cache is not written atomically. *plausible*
- `ocr_validator.py:133-148`: the first decodable embedded image (it may be a logo) is cached permanently as the passport image. *plausible*

## Publishing and API (lower)

- `cloud/records.py:665-677`: an export reaching 90% of the student count counts as complete, so a stream cut off at 90-99% deletes the missing students' rows. *plausible*
- `cloud/backfill.py:515-575`: the backfill makes blocking publish calls inside async code. *low*

The publish layer is otherwise sound: upsert keys are unique, hash state advances only after a 2xx, and every hook is wrapped.
