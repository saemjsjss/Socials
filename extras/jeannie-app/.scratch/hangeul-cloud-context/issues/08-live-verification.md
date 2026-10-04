# Live verification with the owner

Status: ready-for-human (owner, after merge and deploy)

Ticket 8 of the spec's §10. See spec §9. Blocked by: 03, 04, 05, 06, 07 (merged and deployed).

## Before

- Vercel: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (project `dcbcbpwpmdtaanboetiz`) and `JEANNIE_ACCESS_KEY` set; the
  `HANGEUL_*` variables removed (ticket 1). Merging removes the old 03:00 UTC cron (ticket 5, decision 2).
- hg-embed deployed with `--no-verify-jwt` and its model check passed (ticket 3), or search stays "not available
  yet" and every structured plan still works.

## Steps (spec §9)

1. `hg_records` counts per kind match the bot's report; every chunk 384-d, one `embed_model`. (Checked read-only on
   1 Oct: 13,543+ records, one model, norm 1.0000.)
2. On the phone: install the PWA, the first sync completes, airplane mode shows the offline banner.
   (Ticket 7: on mobile data the first sync asks first; it is about 20 pages and 60 MB, 49 s from the PC. The HUD's
   Hangeul Sync panel then says where search runs: "search on this device" means the model check passed on the
   phone; "model check failed" means search stays on the server, as designed.)
3. Ask, with the access key: "How many consultancies were closed today?", "Who is HNG-2026-913?" (a made-up stand-in; use an id that
   exists: 012 is not assigned), "How many payments were verified on 12 Sep?" (compare with `/verified_date 12 Sep`
   on Telegram), "Any passport alerts today?", "What does <name>'s bank statement say about the opening balance?"
   (an OCR page hit; needs hg-embed or the device model), "What changed since this morning?". Each answer shows
   code-built figures and an "as of" time.
4. Delete test: a record removed by the bot disappears from the phone after the next delta.
5. "Delete local copy" in the Hangeul Sync panel empties the phone's copy, and nothing syncs until "Sync to this
   device" (ticket 7).

## Comments
