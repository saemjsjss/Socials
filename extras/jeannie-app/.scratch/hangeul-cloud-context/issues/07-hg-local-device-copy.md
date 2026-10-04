# hg-local: the device copy, local search and the model check

Status: ready-for-human (implemented on saem/hangeul-context-reader; owner review, merge and deploy; see the owner flags below)

Ticket 7 of the spec's §10. See spec §6 (local store, local search, embed-model check, settings), D9, D12, D13, D14.
Blocked by: none (ticket 4's routes and ticket 5's isomorphic answer code are done).

## What to build (`src/lib/client/hg-local/`)

- **Store** (`db.ts`): IndexedDB database `jeannie-hg` with `records` (`[kind, key]` → `HgRecord`), `chunks`
  (`[kind, key, ord]` → `{content, embedding: Float32Array}`) and `meta` (`max_seq`, `embed_model`, `synced_at`),
  behind an interface so tests use an in-memory Map. Call `navigator.storage.persist()`.
- **Sync** (`sync.ts`): first sync pages `GET /api/hangeul/snapshot` (follow `next` until null; keep the first page's
  `max_seq`), with progress and consent before starting on mobile data (tens of MB with the OCR text; the live dump
  is about 28-30 pages of ~3 MB). Then `GET /api/hangeul/changes?since=<max_seq>` on open, on focus and every 5 min
  while open, looping while `more`; an upsert replaces the record and all its chunks (a chunk with no `content` has
  its record's `content`), a delete drops the record and its chunks. Formats: ticket 4, "Wire formats".
- **Search** (`search.ts`): brute-force cosine over the local `Float32Array` vectors (`cosine` and `decodeVector` in
  `src/lib/hangeul/vectors.ts`). gte-small scores sit close together (unrelated rows still score ~0.86): rank by the
  gap to the best hit, not a fixed threshold (the server keeps hits within 0.04 of the best).
- **Embedding** (`embed.worker.ts`): transformers.js (`@huggingface/transformers`, the one allowed new dependency,
  pinned to an exact version) loading `Supabase/gte-small` in a Web Worker, mean pooling and normalising (384-d).
  `next.config.mjs` needs `config.resolve.alias` `{"sharp$": false, "onnxruntime-node$": false}`.
- **Model check** (`check.ts`): on first sync, embed three stored chunk texts and compare with their stored vectors;
  cosine below 0.98 logs it and falls back to the server (`POST /api/hangeul/ask` without an embedding, which uses
  hg-embed and hg_match). Compare vectors, never the `embed_model` string (the bot's is
  `thenlper/gte-small@17e1f347…`, not `Supabase/gte-small`).
- **Answering.** Send `{question, embedding, hits: [{kind, key}]}` (at most 24 hits) to `POST /api/hangeul/ask`, or
  as `hangeul: {embedding, hits}` beside `messages` in `POST /api/chat`: the server re-reads those records from
  current rows. Structured plans can render straight from the device copy with the same code:
  `readersFromRecords({records, runs?})` (`src/lib/hangeul/memory-readers.ts`), `planFor`, `runPlan`, `renderAnswer`
  (`src/lib/hangeul/answer.ts`); plans in `SERVER_ONLY_INTENTS` (`changes_since`, `data_status`) and every "as of"
  that needs `hg_runs` go to the server (the device keeps no runs).
- **Settings** panel "Hangeul data" in `TacticalMetrics` children (copy `MemoryPanel`): "Re-sync everything" and
  "Delete local copy" (confirm first), the only way to remove the data from a device.

## What was built

- `package.json`: `@huggingface/transformers` **4.3.0** (exact), the only new dependency. `.npmrc` sets
  `onnxruntime-node-install=skip` (see owner flag 1). `next.config.mjs`: the webpack aliases above.
- `src/lib/client/hg-local/db.ts`: the `HgLocalStore` interface, `openIndexedDbStore()` (database `jeannie-hg`,
  stores `records` [kind, key], `chunks` [kind, key, ord], `meta` by name) and `createMemoryStore()` for the tests.
  Every write is one transaction: a page of the snapshot or of the change log lands whole with its cursor, or not
  at all. A record's chunks are one key range, `[kind, key]` to `[kind, key, []]`; a kind's records,
  `[kind]` to `[kind, []]`. A chunk keeps no copy of its record's text (as on the wire) and carries the record's
  `day` and `student_uid`, so search filters without reading records. `requestPersistentStorage()` asks
  `navigator.storage.persist()` when the first sync starts.
- `sync.ts`: `runFirstSync` (snapshot pages, the first page's `max_seq`, resumes at its saved cursor after an
  interruption, clears half-written data on a fresh start), `runDelta` (the change log in seq order while `more`;
  an upsert whose record is null is skipped, its delete follows), `syncOnce` (first sync if needed, then the
  **runs**, then the changes), `firstSyncNeedsConsent` (cellular or data saver asks; Wi-Fi and Ethernet do not; a
  phone whose browser cannot tell asks). Malformed pages and vectors fail closed (`HgSyncError`), cursor unchanged.
- `search.ts`: `buildIndex` (one `Float32Array`, rows normalised), `searchIndex` (top 12 by cosine, filtered by
  kinds, student and day range), `hitRecords` (best chunk per record, within 0.04 of the best, at most 5: the
  server's own search shows 5 cards).
- `check.ts`: `pickCheckSamples` (three stored chunks of different kinds, 20-1,500 characters, a chunk with no text
  takes its record's) and `checkEmbedModel` (ok at cosine ≥ 0.98; `mismatch` logs the minimum, numbers only, and
  search stays on the server; `unavailable` when the model did not load: checked again later).
- `embed-protocol.ts`, `embed.worker.ts`, `embedder.ts`: the worker loads `Supabase/gte-small` with `dtype: "q8"` on
  WASM, `pooling: "mean", normalize: true`; the model comes from the Hugging Face Hub (cached by the browser in
  `transformers-cache`, which the service worker keeps), never from Jeannie's origin. Requests time out (3 min for
  the first load on a phone, 8 s a question).
- `readers.ts`: `deviceReaders(store, runs)`, `HangeulReaders` over IndexedDB with the server's filter meaning
  (`filter.ts`) and the synced runs.
- `ask.ts`: `prepareHangeul` decides, per question, in the server router's order (smart-home and mistake audits
  first, `routesToHangeul`):
  - a structured plan renders on the device (`planFor`, `runPlan`, `renderAnswer`) when the copy caught up within 6
    minutes, holds the runs and found something;
  - a semantic plan is embedded on the device and searched locally; the vector (base64) and the hits go to the
    server;
  - everything else goes to the server as a plain question: `SERVER_ONLY_INTENTS`, a stale copy, Korean or Bangla
    searches (the server rewrites them first), a model check that did not pass, and a device answer that found
    nothing (absence may only be the copy lagging).
- `src/hooks/useHangeulLocal.ts`: opens the store, syncs on open, on focus (at most every 30 s), every 5 minutes
  while visible and when the connection changes; asks before the first sync on mobile data; runs the model check
  after the first sync; warms the model and the index; `resync`, `deleteCopy`, `enable`, `prepare`.
- `src/hooks/useJeannieChat.ts`: `prepareHangeul` option: a device answer is shown at once as a Hangeul reply
  (provider "none", no request, spoken like any reply); hints go out as `hangeul: {embedding, hits}` in
  `POST /api/chat`. It gives up after 6 s and asks the server.
- `src/components/HangeulSyncPanel.tsx` ("Hangeul Sync" / 기기 사본, in `TacticalMetrics` children after Memory):
  state, first-sync progress, where search runs, **Re-sync everything** and **Delete local copy** (both confirm
  first), DOWNLOAD NOW on mobile data, SYNC TO THIS DEVICE after a delete.
  `src/components/HangeulSyncNotice.tsx`: the same consent question and progress on the phone's avatar screen.
- Server: `GET /api/hangeul/runs` (`{runs}`: `readRuns(HG_KINDS)`, same gate, no student data) and
  `GET /api/status` `timeZone` (the business time zone, `JEANNIE_TIMEZONE`).

## Decisions (recorded here, not re-proposed)

1. **The device syncs the runs** (`GET /api/hangeul/runs`, new). Without them a device answer could only be dated
   by the rows' `read_at`, which does not move when content is unchanged, and a kind with no rows would read "not
   available yet" instead of 0. The runs are read before the change log each sync, so every run that dates an
   answer has all its changes in what the device then applies.
2. **Device hits go through `POST /api/chat`** (`hangeul: {embedding, hits}`, the ticket's second option): the same
   server code as `/api/hangeul/ask` (`answerHangeul`), with the conversation, the persona and the chat's streaming
   contract. `/api/hangeul/ask` is unchanged for other callers.
3. **A device answer has no prose.** It is the code-built answer alone (the server's answer without a model), shown
   at once; questions that need the model's words or fresh server state go to the server.
4. **Consent is per page load.** A yes to downloading on mobile data is not remembered; a first sync cut short
   resumes and asks again on mobile data. "Re-sync everything" confirms in its own dialog.
5. **"Delete local copy" stays deleted**: a per-browser flag (`jeannie.hg.device` = "off") stops every sync until
   "Sync to this device". Signing out of the key does not delete the copy (spec: accepted risk).

## Owner flags

1. `@huggingface/transformers` pulls `onnxruntime-node`, whose install script downloads CUDA binaries from NuGet on
   Linux x64 (Vercel's builders), and a failed download fails the install. The committed `.npmrc` sets
   `onnxruntime-node-install=skip` (checked: npm hands it to the script as `npm_config_onnxruntime_node_install`).
   Jeannie never runs the Node backend.
2. The build emits onnxruntime-web's 27 MB `.wasm` under `/_next/static/media/`, but transformers.js loads the WASM
   and its glue from its own paths (since the review fixes: Jeannie's `/ort/`, see the comments; before: its
   `cdn.jsdelivr.net` default) and the model from `huggingface.co`, so the emitted file is never fetched. Aliasing `onnxruntime-web/webgpu` to its extern-WASM build would drop it; not done without a
   phone test.
3. The model check has not run on a real device yet (no model download here): it is part of ticket 8. A mismatch
   only moves search to the server.

## Tests

`tests/hg-local.test.ts` (synthetic data, a fake snapshot and change feed, no network), each sync test against the
in-memory store **and** the real IndexedDB code over `tests/idb-shim.ts` (an in-memory IndexedDB with the spec's key
order; the repo has no fake-indexeddb and this ticket allows one dependency): the first sync (pages, `max_seq`,
progress, chunk text left out, Float32Array vectors), resuming a first sync cut short, the change log applying
upserts and deletes in seq order across pages (a changed record's old chunk removed, delete-then-recreate,
added-then-deleted), runs before changes, malformed pages and vectors failing closed, `clear()`. Cosine search returns
the right record (and chunk), with kind, student and day filters; `hitRecords`. The model check passes on matching
vectors; **a mismatch falls back to the server** with no device vector or hits (and logs numbers only); a passing
check sends the device's vector and the right hit; a model that does not load is `unavailable`. A structured answer on
the device is the server's answer, word for word, for the owner's question (and in Korean); server-only intents, an
empty result, Korean searches, a stale copy, no copy and an unreadable copy go to the server; the device and the
server's router agree on what is a Hangeul question. Mobile-data consent. `tests/hangeul-routes.test.ts`: the runs
route (gate, no student data, 502).

## Live check (1 Oct 02:43-02:44 Dhaka, read-only: the route handlers over PostgREST selects and hg_changes_since)

The phone's sync code, run in Node against the live project through the same route handlers the phone calls
(snapshot, runs, changes), into the in-memory store; names masked:

- First sync: 20 pages, 13,546 records, 15,635 chunks, 56.9 MB of JSON, 49 s (slowest page 6.0 s); `max_seq`
  13553; 31 runs; one embed model (`thenlper/gte-small`). Per kind: student 340, consultation 1,035, consultant
  performance 17, doc verdict 2,717, field check 3,490, doc page text 3,469, passport alert 311, report 3, report
  section 434.
- Index of all 15,635 vectors built in 23 ms; one search 9.9 ms (PC); a stored vector finds its own chunk first
  (1.0000).
- On the device copy: "how many consultancies were closed today?" → "Consultancies done today (1 Oct): 0.", "As of
  02:35 (full picture)"; "…done yesterday?" → "Consultancies done yesterday (30 Sep): 20 — <consultants>", "As of 30
  Sep 23:35 (consultant performance, full picture) · consultation requests 02:35 (full picture)"; "Hangeul daily
  report" → "Daily brief: not available yet.", "As of 02:43 (portal sync) · full picture 02:35". **Each is the
  server's answer word for word.** "Any passport alerts today?" found nothing checked today on the device, so it goes
  to the server (by design).

## Comments

- 1 Oct 2026: built on saem/hangeul-context-reader with ticket 6. `npx vitest run` 1169 passed and 8 skipped; `tsc`,
  `npm run lint` and `npm run build` are clean.
- 1 Oct 2026 (review fixes): "Delete local copy" did not survive a second tab of the same origin (the installed PWA
  and a Chrome tab share the one database): the other tab's in-memory choice stayed "auto", and its next sync read
  the cleared meta as a fresh start and downloaded everything again, while the deleting tab said "NOT ON THIS
  DEVICE" with Delete disabled. Now (`src/lib/client/hg-local/device.ts`): the choice is re-read from storage before
  a sync starts and before each of its requests and writes (`syncOnce`'s `allowed`), so a stale tab stops instead of
  downloading; a BroadcastChannel tells the other tabs at once, and they stop and clear once more (a page they were
  writing may have landed after the first clear); the deleting tab clears first and turns the copy off only after
  the clear worked (a failed clear keeps it on and the panel says it could not be deleted); the tabs sync one at a
  time (Web Locks), so a second tab never runs a second first sync; and the panel's "NOT ON THIS DEVICE" and its
  Delete button rest on the store's real counts ("SYNC OFF · N STILL HERE" otherwise). The panel also names a block
  as the Hangeul Data panel does: CHECKING…, NOT LINKED or LOCKED. Tests: `tests/hg-local-tabs.test.ts` (two handles
  on one in-memory IndexedDB, a shared storage, Node's BroadcastChannel).
- 1 Oct 2026 (review fixes): transformers.js loaded onnxruntime-web's JavaScript factory and `.wasm` from
  `cdn.jsdelivr.net` (its default when `wasmPaths` is unset) and ran them, unchecked, in the worker that gets every
  Hangeul question and the model check's stored chunk texts. `scripts/copy-ort.mjs` (npm `predev` / `prebuild`) now
  copies the four runtime files transformers.js may pick (asyncify, and the plain build it uses on Safari before 26
  without WebGPU; 41 MB) from the lockfile's `node_modules/onnxruntime-web/dist` to `public/ort/` (git-ignored), and
  the worker moves transformers.js's own choice to `/ort/` before its first pipeline (`ort-runtime.ts`); if it cannot,
  no model loads and search stays on the server. transformers.js still caches the files in its own cache, as it did
  from the CDN. `next start` serves them as `application/javascript` and `application/wasm` with `nosniff`. The
  model itself still comes from huggingface.co. Not done: a Content-Security-Policy (the HUD's Next inline scripts
  need nonces or `unsafe-inline`; worth its own change with a phone test). To check on the phone (ticket 8): the
  first model load fetches `/ort/…` and nothing from `cdn.jsdelivr.net`. Tests: `tests/ort-runtime.test.ts`.
