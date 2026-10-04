# Code-built answers, the router and the orchestrator; the portal bridge removed

Status: ready-for-human (implemented on saem/hangeul-context-reader; owner review, merge and deploy; see the cron flag below)

Ticket 5 of the spec's §10. See spec §5, D2, D10, D11.

## The question that failed

"How many consultancies were closed today?" went to the web-search agent: the portal bridge's cues did not know it,
and only "Hangeul daily report" reached the bridge, which served demo data. It now routes to the Hangeul agent and is
answered from Hangeul BOT's rows:

```
Consultancies done today (30 Sep): 20 — <consultant> 8, <consultant> 4, <consultant> 3, <consultant> 2, <consultant> 2, <consultant> 1.
Requests received today (30 Sep): 10 (Consulted 6, New 4).
• Consultancies done: 20 · Files opened: 5 · Conversion (file open): 25% · Docs ready: 1 · Top performer …
By consultant: • <consultant>: Consultancies 8, Files opened 1 …
"Consultancies done" is the Consultant Performance page's tile; requests are counted by the day they were received, with their current status.
As of 23:35 (full picture)
```

The portal has no "Closed" status: "closed" or "done" is the performance page's **Consultancies done** tile
(`consultant_performance`, key `today|<day>|summary`), and the consultation rows of the day (by the day received, with
their current status) are a different figure, so both are shown and labelled. When the business day has rolled over
and the bot has not read the new day yet, the answer says "Consultancies done today (1 Oct): not available yet" and
names the latest day on file with its read time. It never shows yesterday's tiles as today's.

## What was built

- `src/lib/hangeul/router.ts` (isomorphic): `classify(text, {today, now, timeZone})` → a `Plan`, whole-word rules on
  `normalizeQuery` output (single spaces, raw input capped at 16,000 and routed text at 4,000 characters, bounded
  windows only, so 20,000 characters route in well under 50 ms). The old bridge's cues are kept, so every phrasing
  that reached the bridge still arrives, and its negatives stay out ("teach me hangeul", "pending payments on
  PayPal"). New negatives: "across" is not a cross-check, "student visa requirements" names no student, "10 decks"
  is not 10 Dec, "latest briefing on Ukraine", "deadline for US tax returns", "what changed in React 19".
  `isHangeulContextQuery(text)` routes; `HNG-2026-12` becomes `HNG-2026-012` (the portal zero-pads to 3 digits).
  - The loose cues (conversion, top performers, leaderboard, files opened, "any updates since yesterday", "how many
    students are there", passport problems) need the subject not to be someone else's: a `FOREIGN` word (currencies,
    markets, sport, news, software) keeps them out unless an `ANCHOR` (hangeul, portal, an HNG id, consultant,
    consultancy, inquiry, "our agency"...) says the agency is meant. A change question about a named topic ("any
    updates since yesterday on the Ukraine war?", "what's new since yesterday in AI?") is not ours; time phrases ("in
    the last 3 hours") and the data's own nouns do not count as a topic. Everyday passport words next to travel
    ("any passport problems when travelling to Japan?") stay out. "Consultations" needs a day or the agency ("how many
    consultations today?", not "how many consultations does a doctor do a day?"); a bare "verified" needs a payment,
    a student or a day with "anything"/"how many".
  - A calendar question that names a university ("application deadlines for Gachon University") keeps only the items
    that mention it, over 60 days; one the agency's calendar lacks ("…for Harvard") answers "No item on the agency's
    calendar mentions Harvard", not the whole calendar.
- `src/lib/hangeul/answer.ts` (isomorphic, no Node APIs, no "ai" import): `runPlan(plan, readers, options)` →
  `AnswerResult {plan, headline, facts, tables, notes, asOf, sources, unavailable?}`, `renderAnswer(result, lang)`,
  `asOfLine`, `factsForModel`, `checkProse` / `proseNumbersOk`, `needsSearchRewrite`, `SEARCH_REWRITE_SYSTEM`,
  `cleanSearchRewrite`, `planFor`. Plans: every one in spec §5 (`student_card`, `verified_on_day`,
  `inquiries_on_day`, `pending_payments`, `window_review`, `doc_verdicts`, `passport_alerts`, `calendar_window`,
  `missing_for_student`, `changes_since`, `report(brief|missing|stage|document_check|field_check|inquiries)`,
  `semantic`), plus `performance` (today or month), `consultancies_closed_today` (any day), `students_applied`,
  `dashboard` and `data_status`.
  - A kind no run has read and no row holds is "not available yet", never 0. A kind a run read with no rows is 0
    (e.g. "Window applications under review: 0", as of the full picture). When the missing figure is the answer's main
    one it leads the reply (the headline); a secondary one goes in the notes.
  - A performance window is used only when its summary's `first_day` is the day asked for: another day's tiles are
    never offered as today's, even from a mis-scoped record.
  - `data.blank_on_portal` fields are "not given on the portal" ("포털에 입력되지 않음").
  - As of: the newest finished run (ok or partial) whose `counts.by_kind` names the kind, shown in Asia/Dhaka and
    labelled by job; a past day's performance window by the last run of that day; a student's document check by its
    own check time; a report by when it was made. `As of 17:35 (full picture) · portal sync 17:58`. When one job
    dates two things at two times, each says what it dates: `As of 30 Sep 23:35 (consultant performance, full
    picture) · consultation requests 01:35 (full picture)`.
  - Semantic: the device's vector and hits, else hg-embed + hg_match; hits within 0.04 of the best (gte-small scores
    sit close together); Korean or Bangla questions are rewritten into an English query by the model first, and the
    rewritten query is embedded again. While hg-embed is not deployed: "Search is not available yet".
- `src/lib/hangeul/respond.ts`: `answerHangeul(input)` for the chat and `/api/hangeul/ask`. Without a model, the
  facts alone. With one, `generateText` (8 s) with the persona's rewritten `hangeul` directive and the facts as
  JSON, values and PII included (D11); the emote tag is stripped, `checkProse` drops every sentence with a number
  that is not in the rendered facts, at most two sentences stay, and the reply is `[emote:x] prose\n\nfacts`. It is
  sent whole, not streamed, because the check runs first.
- `src/lib/hangeul/filter.ts`, `memory-readers.ts`, `days.ts`, `vectors.ts`, `types.ts`: shared, isomorphic pieces
  (the filter meaning, readers over rows in memory, Dhaka days, base64 float32, the types).
- Orchestrator: `routeQuery` checks `isHangeulContextQuery` before the clock and search rules (the image rule stays:
  with an image, only text that names the portal stays with Hangeul). `runHangeul`: an untrusted caller gets a fixed
  "needs the access key" line and no data is read; no Supabase gives a fixed "not connected" line. Test seams:
  `ctx.hangeul` (readers), `ctx.now`, `ctx.hangeulDevice`. `/api/chat` accepts an optional
  `hangeul: {embedding?, hits?}` for the PWA.
- Removed: `src/lib/agents/hangeul-bridge.ts` and its demo generator, `HangeulReport` / `HangeulStatus` /
  `HangeulMetric`, the `HANGEUL_*` variables in `env.ts` and `.env.example`, `hangeulLiveConfigured`. `MOCK_MODE`
  moved to `env.mockMode` (the greeting still uses it).
- Telegram: `/report` (admin chat only) sends the code-built daily report, no model; `/status` says "Hangeul data:
  Supabase connected / not configured".
- HUD: the panel is "Hangeul Data" (records, latest brief, newest run; runs in the tooltip); DAILY REPORT still
  sends "Hangeul daily report"; the status row and header pill show the data link, not the portal.
- Speech: fact and table bullets and the "As of" line are not read aloud; the headline and notes are.

## Decisions (recorded here, not re-proposed)

1. **"Hangeul daily report"** is `report(brief)`: the latest `brief|<day>` report record (its facts lines, pending
   payments, window applications), with a note when it is not today's. With no brief at all (the first comes 1 Oct
   18:05), it leads with "Daily brief: not available yet", that the bot sends it at 18:05, and "From the portal's
   dashboard instead:", then the dashboard's "At a glance" and "Needs attention" figures. The HUD panel shows the
   latest brief's time, or, until there is one, "No brief yet" and the latest report the bot made.
2. **The daily cron is removed** (`vercel.json`). It pushed the bridge's demo report to Telegram at 03:00 UTC every
   day; Hangeul BOT already sends its own brief. **Owner flag:** merging removes that deployed Vercel cron.
3. **Every Hangeul route needs the key set and presented**, like memory (not just `requireAccess`, which is open when
   no key is set). The chat answers Hangeul questions only for a trusted caller (the HUD with the key, the Telegram
   admin chat).
4. Five plans beyond spec §5 (`performance`, `consultancies_closed_today`, `students_applied`, `dashboard`,
   `data_status`). A portal health question ("is the portal up?") is answered with the bot's latest runs: Jeannie
   never checks the portal herself.
5. hg_match gets a 6 s timeout (see ticket 4); every other answer read keeps 3 s.

## Tests

`tests/hangeul-router.test.ts` (the owner's question, the §9 questions, every plan, days, names, the old bridge's
positives and negatives plus new ones, the 20,000-character guard), `tests/hangeul-answer.test.ts` (exact figures from
synthetic rows, the day boundary, "not available yet", "not given on the portal", the as-of line, Korean and bilingual,
the number check dropping a sentence, the failure reason, semantic search with and without a vector, the rewrite),
plus the updated `orchestrator`, `api-routes`, `telegram` and `speech-text` suites. Synthetic data only
(`tests/hangeul-fixtures.ts`). The router suite also holds everyday questions that must stay out (currency
conversion, news since yesterday, sport leaderboards, "files opened in Excel", a traveller's passport) and the same
cues when the agency is meant.

## Live check (1 Oct 01:56-02:06 Dhaka, read-only, no model; names masked)

The same code against the live rows, through `answerHangeul` with the Supabase store:

- "How many consultancies were closed today?" (1 Oct, after the 00:35 full picture had opened the new day's window):
  "Consultancies done today (1 Oct): 0. Requests received today (1 Oct): 0.", the four tiles at 0, "As of 01:35 (full
  picture)". Correct for the start of a day.
- "…done yesterday?": "Consultancies done yesterday (30 Sep): 20 — <consultant> 8, <consultant> 4, <consultant> 3,
  <consultant> 2, <consultant> 2, <consultant> 1. Requests received yesterday (30 Sep): 10 (Consulted 6, New 4).",
  tiles 20 / 5 / 25% / 1, the six rows (they add up to 20), "As of 30 Sep 23:35 (consultant performance, full picture)
  · consultation requests 01:35 (full picture)". Korean ("오늘 상담 몇 건 끝났어?") the same, with "기준: 01:35 (전체 점검)".
- "How many payments were verified on 12 Sep?": 10, with the total, by verifier (6) and the list, as of the full
  picture. "Any passport alerts today?": 0 checked today, as of the passport watcher 01:57. "What changed since this
  morning?": 4 records (consultant performance 2, consultation day 1, calendar 1). "Hangeul daily report": "Daily
  brief: not available yet" then the dashboard, as of portal sync 01:58. Pending payments 1; window applications 0;
  calendar 12 items in 15 days; "…deadlines for Gachon University": 1; "…for Harvard": none on the agency's calendar.
- "Who is HNG-2026-12?" answers "No student matches HNG-2026-012." That is right: the live ids are not contiguous
  (339 ids up to 370; 006-009, 011, 012 and 015 are among the gaps). "Who is HNG-2026-913?" (a made-up stand-in for a live id) gives the full card (22
  facts), as of the passport watcher 01:57 · backfill (progress) · its document check time. **For the spec's §9 check,
  ask for an id that exists.**
- Search: with a stored `doc_page_text` vector as the device embedding, `hg_match` returned that record first and
  the card showed its page text, as of its own check time. Without a vector: "Search is not available yet" (hg-embed
  is not deployed).

## Comments

- 1 Oct 2026 (review fixes, "route the owner's performance phrasings; date answers by the runs that read them" and
  "never send a Hangeul reply to the voice engines"): the owner's own performance phrasings ("this month's performance",
  "today's performance", "performence this month", "how did the team do today", "team activity"...) and the bot's
  misspellings are routed; "student visa requirements", "student life", consultancy fees, a doctor's consultations
  and "consultancies in Dhaka" are not. Ranges ("this week", "the last 7 days") say that the portal shows only today
  and this month and add the requests day by day; a passport range filters by day. The prose number check compares
  typed tokens (a time only allows that time, a date that date), so the as-of line's 02:35 no longer lets "35
  consultancies" through. Consultation requests of a day are dated by the runs that re-read that day (full picture
  on D or D+1, a command on D, the backfill) or their own read_at; a missing brief is not dated by another report's
  run; the passport table's names are looked up for the rows it shows; a blank "Consultancies done" tile is Korean
  in the Korean headline. A Hangeul reply is never sent to the voice engines (ElevenLabs, Edge TTS): a fixed line
  is spoken instead.
- 1 Oct 2026, 04:1x Dhaka, live and read-only (server path, no model): "how many consultancies were closed today?"
  → "Consultancies done today (1 Oct): 0." and "Requests received today (1 Oct): 0.", the tiles, "By consultant:
  none", "As of 03:35 (full picture)"; the prose "Your team closed 35 / 2 / 20 consultancies today." is dropped
  each time. "…this week?" → not on the portal, 100 requests received 25 Sep – 1 Oct by day and by status, each
  day's Today window on file, "As of 30 Sep 23:35 (full picture) · backfill 30 Sep 22:05". "how many inquiries on
  12 Sep?" → "As of 30 Sep 22:05 (backfill)". "daily brief" → not available yet, the dashboard's figures, "As of
  03:35 (full picture)". "passport alerts" → the newest problem scans first, each with its student's name.
