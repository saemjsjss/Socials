# Jeannie · Bilingual Multimodal Personal AI

Jeannie is a J.A.R.V.I.S.-style personal AI with a neon-pink holographic HUD. She speaks English and
Korean (한국어), sees through your camera, searches the live web, talks back with a neural voice,
answers questions about the agency from the data Hangeul BOT publishes, and answers every smart-home
command with instant composure.

| Layer | Service |
| --- | --- |
| **Brain** | [DeepSeek](https://platform.deepseek.com) (`deepseek-v4-flash`, thinking off for quick spoken replies). Images go to Claude or OpenAI when their key is set, else to DeepSeek's `deepseek-v4-flash-vision-exp`. Claude, OpenAI or Ollama still work as alternatives. |
| **Voice** | [ElevenLabs](https://elevenlabs.io) (`eleven_multilingual_v2`, English + Korean), with free Edge and browser voices as fallbacks. |
| **Memory** | [Supabase](https://supabase.com): markdown and JSON Lines notes you upload, searched with Postgres full-text search on every message. |

Built with Next.js 15 (App Router, TypeScript), Tailwind CSS, Framer Motion, the Vercel AI SDK, and
Canvas-based holographic visualizers. Ready for Vercel with zero extra configuration.

## Features

| Agent | What it does |
| --- | --- |
| **Orchestrator (Jeannie Core)** | Reads each text, voice, or image prompt and routes it to one specialist. |
| **IoT Interceptor** | Any smart-home or IoT command or query gets exactly `Yes, it is done.` (`네, 처리되었습니다.` in Korean). No tools, no LLM. |
| **Live Search Agent** | Time-sensitive or fact-checking questions go to DeepSeek's native web search (same `DEEPSEEK_API_KEY`), then Tavily and Google Custom Search if configured, then DuckDuckGo. The results are summarized with inline `[n]` citations. |
| **Vision & Localization Agent** | Image attachments (documents, screenshots, camera frames) get a structured bilingual analysis, with visible text transcribed and translated. |
| **Hangeul data** | Answers questions about the agency ("how many consultancies were closed today?", "who is HNG-2026-12?", "any passport alerts today?") from the records Hangeul BOT publishes to Supabase. Code builds every figure and table; the model only adds up to two checked sentences. Every answer ends with an "as of" time. Needs the access key. |
| **Mistake Audit Agent** | "Audit this for mistakes", "실수 점검해줘": answers in a fixed frame (Issue · Cause · Recommendation) and asks for approval. "승인" / "approve" gets a standard execution confirmation; "취소" / "cancel" puts it on hold. |
| **General Cognitive Agent** | Handles everything else and can call web search on its own. |

Also included:

- **Voice out:** ElevenLabs first, then Microsoft Edge neural voices (`en-US-JennyNeural`, `ko-KR-SunHiNeural`, no API key needed), then the browser's built-in speech. The audio drives the orb and the spectrum visualizer.
- **Voice in:** push-to-talk speech recognition in English or Korean, using the browser's Web Speech API.
- **HUD:** a canvas arc-reactor orb, a spectrum analyzer, a translucent chat terminal, tactical telemetry, IoT control tiles, and a camera scanner.
- **Telegram bridge:** two-way bot. Chat with Jeannie, send photos for analysis, run `/report`, `/search`, and `/status`.
- **Language modes:** Auto-detect, English, Korean, or bilingual (English then Korean). You can also ask for "both languages" in any message.
- **Honorifics:** replies call you 부장님 by default and 자기야 when the message is personal (tiredness, missing her, good night). Audit, Hangeul, search, vision and smart-home replies always use 부장님. Greetings use 부장님 from 09:00 to 18:00 local time and 자기야 otherwise.
- **Session greeting:** a new HUD session opens with a short Korean greeting written by the model for your local time of day and how long you were away, with the template greeting (좋은 아침입니다 05–11, 좋은 오후입니다 12–17, 좋은 저녁입니다 18–21, 늦은 시간까지 수고 많으십니다 at night) as the fallback. Telegram `/start` uses the template greeting. Set `JEANNIE_TIMEZONE` (default `Asia/Dhaka`).
- **Memory:** upload `.md` and `.jsonl` files from the HUD's Memory panel. Pinned notes (like your profile) are always in her prompt; the rest are recalled when a message matches them.
- **Installable PWA:** add Jeannie to the phone's home screen (standalone, portrait). The service worker caches the app shell and the avatar clips only, never `/api/*`. Offline, a banner says "Offline: Jeannie needs a connection" and the input is disabled: there are no offline answers.
- **Hangeul data on the device:** with the access key, the HUD keeps a copy of the Hangeul data in IndexedDB (first sync about 60 MB, then the change log every 5 minutes), so structured answers render on the phone at once and search runs there. The HUD's Hangeul Sync panel has "Re-sync everything" and "Delete local copy".

## Quick start

```bash
npm install
cp .env.example .env.local   # every key is optional; see below
npm run dev                  # http://localhost:3000
```

With no keys at all, Jeannie still runs in offline mode. IoT confirmations, live search (DuckDuckGo),
Edge neural voice and camera all work. Add `DEEPSEEK_API_KEY` for full reasoning. The Hangeul answers need
`SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `JEANNIE_ACCESS_KEY` (they work without a language model).
For image analysis, also add `ANTHROPIC_API_KEY` (Claude) or `OPENAI_API_KEY`, or run [Ollama](https://ollama.com)
with a vision model.

| Script | Purpose |
| --- | --- |
| `npm run dev` | Start the local dev server |
| `npm run build` / `npm start` | Build and serve for production |
| `npm test` | Unit and route tests (Vitest) |
| `npm run lint` / `npm run typecheck` | ESLint and TypeScript checks |
| `npm run memory:upload -- <files> [--pin]` | Upload notes to memory through `/api/memory` (uses `JEANNIE_URL` and `JEANNIE_ACCESS_KEY`) |

## Memory (Supabase)

1. **Create the tables.** Open your Supabase project → **SQL Editor**, paste
   [`supabase/migrations/20260928000000_jeannie_memory.sql`](supabase/migrations/20260928000000_jeannie_memory.sql)
   and run it (or `supabase db push` with the Supabase CLI).
   - Every table has row-level security on and no policies. The public anon key can't read anything; only the server's
     service-role key can.
2. **Set the keys.** Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. They're under **Project Settings → API**; use
   the `service_role` or `sb_secret_…` key, never with a `NEXT_PUBLIC_` prefix. Also set `JEANNIE_ACCESS_KEY`: memory is
   never used or editable without it, because the notes are personal.
3. **Upload notes.** In the HUD's **Memory** panel, tick **PIN** for your profile, then pick the files. Or use the CLI:
   ```bash
   npm run memory:upload -- memory/profile.md --pin
   npm run memory:upload -- memory/saemur-knowledge.jsonl
   ```
   - `.md` files are split by heading.
   - `.jsonl` files keep one record per note (`{id, type, title, text, tags, entity, updated}`), so re-uploading
     replaces them by file name.
   - Files that look like they contain API keys, tokens or ID numbers are refused.
   - `memory/` is gitignored, so personal notes stay out of the repo.

**How recall works.** Each message is reduced to search terms: stopwords are dropped and Korean particles are
stripped, so "HGLC는 어디에 있어?" becomes `hglc`. The terms are prefix-matched against the notes' titles, tags and
text. The best matches, plus the pinned notes, are added to the prompt as reference data. This happens for the HUD with
a valid access key and for the Telegram admin chat, and never for an open deployment. If Supabase is slow (over 1.5 s)
or down, Jeannie answers without memory.

`.mcp.json` registers the project's read-only Supabase MCP server for Claude Code (`claude /mcp` to authenticate).

## Hangeul question embeddings (Edge Function `hg-embed`)

[`supabase/functions/hg-embed/index.ts`](supabase/functions/hg-embed/index.ts) turns question text into gte-small
vectors (384 numbers, mean pooled, normalised) so Jeannie's server can search Hangeul BOT's chunks with `hg_match`
before a device has its own model loaded. It runs the Edge Runtime's built-in `Supabase.ai.Session('gte-small')`, the
ONNX export of the model the bot embeds with, so there is no model download and no extra key.

- **Request.** `POST https://dcbcbpwpmdtaanboetiz.supabase.co/functions/v1/hg-embed` with `{"texts": ["..."]}`:
  1 to 16 non-blank texts of at most 2,000 characters each, and a body of at most 128 KB.
- **Key.** A project secret key (`sb_secret_…`) in the `apikey` header, or the legacy `service_role` key in
  `Authorization: Bearer`. Any of the project's secret keys works: the function reads `SUPABASE_SECRET_KEYS` and
  `SUPABASE_SERVICE_ROLE_KEY`, which Supabase sets. Publishable and anon keys never do. With no key configured it
  answers 503 and embeds nothing.
- **Answer.** `{"embeddings": [[…384 numbers…], …], "model": "gte-small", "dims": 384}`, one vector per text, in order.
- **Errors.** JSON `{"error", "code"}`, never repeating a text or a key: 401 `unauthorized`; 405 `method_not_allowed`;
  400 `invalid_json`, `invalid_body`, `no_texts`, `too_many_texts`, `invalid_text`, `empty_text`, `text_too_long` or
  `unreadable_body`; 413 `body_too_large`; 503 `not_configured` or `model_unavailable`; 500 `embed_failed` or
  `bad_embedding`.

**Deploy.** The owner runs this after review. The repo has no `supabase/config.toml`, so the JWT setting goes on the
command:

```bash
supabase functions deploy hg-embed --no-verify-jwt --project-ref dcbcbpwpmdtaanboetiz
```

`--no-verify-jwt` is required. The gateway's JWT check doesn't understand `sb_secret_…` keys, so the function checks
the key itself. A later deploy without the flag turns the gateway check back on, and the secret key is then refused.

**Smoke test.** After deploying, send a question (never student data) and expect 384 numbers back:

```bash
curl -s -X POST "https://dcbcbpwpmdtaanboetiz.supabase.co/functions/v1/hg-embed" \
  -H "apikey: $SUPABASE_SECRET_KEY" -H "content-type: application/json" \
  -d '{"texts": ["How many consultancies were closed today?"]}' | head -c 300
```

The same call without the `apikey` header must answer 401.

## Deploy to Vercel

1. **Merge to `main`.** Merge the pull request (or push your branch) so `munim430-ai/Jeenie-saem-bot` has the code.
2. **Import the project.**
   - Go to [vercel.com/new](https://vercel.com/new) and select `munim430-ai/Jeenie-saem-bot`.
   - The framework preset is detected as **Next.js**.
3. **Set environment variables.**
   - Copy the keys you need from [`.env.example`](.env.example) into **Settings → Environment Variables**.
   - At minimum, set `DEEPSEEK_API_KEY`: it drives both the conversation and live web search (DeepSeek's native `web_search`). `TAVILY_API_KEY` and Google Custom Search are optional extra fallbacks before the keyless DuckDuckGo.
   - Also set `JEANNIE_ACCESS_KEY` on any public deployment.
4. **Deploy.** Click **Deploy**. `/api/chat` and `/api/search` run on the Edge runtime. Voice, Telegram, and the Hangeul data routes run as Node.js functions.
5. **No cron.** `vercel.json` schedules nothing. The old 03:00 UTC cron pushed the portal bridge's demo report to Telegram; Hangeul BOT sends its own brief at 18:05.

### Telegram webhook

Create a bot with [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET`.
Then register the webhook once:

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<your-app>.vercel.app/api/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

`TELEGRAM_WEBHOOK_SECRET` is required. Without it the webhook refuses every update (HTTP 503), so nobody can forge messages to your bot.
Until `TELEGRAM_ADMIN_CHAT_ID` is set, the bot answers only `/start`, `/help` and `/whoami`. Send `/whoami`, put the chat id it returns in
`TELEGRAM_ADMIN_CHAT_ID`, and redeploy. From then on only that chat gets answers, live search, and the Hangeul data.

## Configuration

Every variable is optional. Values left as the `your_…` placeholders from `.env.example` are treated as unset.

| Variable | Purpose |
| --- | --- |
| `JEANNIE_ACCESS_KEY` | Shared secret for every `/api` route (header `x-jeannie-key` or `Authorization: Bearer`). The HUD prompts for it once and remembers it in this browser. |
| `JEANNIE_TIMEZONE` | IANA time zone for the Korean session greeting. Default `Asia/Dhaka`. |
| `LLM_PROVIDER` | `auto` (default: DeepSeek if its key is set, then Claude, then OpenAI, then Ollama), `deepseek`, `anthropic`, `openai` or `ollama`. |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_VISION_MODEL`, `DEEPSEEK_BASE_URL` | DeepSeek, Jeannie's brain. `deepseek-v4-flash` (default) or `deepseek-v4-pro` (stronger); both call the web-search tool. DeepSeek retired the `deepseek-chat` / `deepseek-reasoner` names on 24 July 2026. Its chat models can't read images, so image analysis uses Claude or OpenAI when their key is set, else `DEEPSEEK_VISION_MODEL` (default `deepseek-v4-flash-vision-exp`, experimental). |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_VISION_MODEL` | Claude. The default model is `claude-opus-5`; `claude-sonnet-5` and `claude-haiku-4-5` are cheaper. If Claude's safety classifiers decline a request, it is retried on a fallback model automatically. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEFAULT_MODEL`, `VISION_MODEL` | OpenAI, or any OpenAI-compatible endpoint such as Groq or OpenRouter. The default model is `gpt-4o`. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL` | Local or self-hosted Ollama through its OpenAI-compatible API. |
| `DEEPSEEK_SEARCH_MODEL`, `DEEPSEEK_ANTHROPIC_BASE_URL` | Optional overrides for DeepSeek's native web search (defaults `deepseek-v4-flash`, `https://api.deepseek.com/anthropic`). |
| `TAVILY_API_KEY`, `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_ID` | Optional fallback search providers after DeepSeek. DuckDuckGo is the keyless last resort. |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` | Jeannie's main voice. `eleven_multilingual_v2` speaks Korean; `eleven_flash_v2_5` is faster. With only the key set, the premade voice "Rachel" is used; free plans must set the ID of a voice they created, since library voices return HTTP 402 there (Jeannie then falls back to the Edge voice). |
| `SUPABASE_URL` (or `NEXT_PUBLIC_SUPABASE_URL`), `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_SECRET_KEY`) | Memory and the Hangeul data (one project). The key is server-only; the publishable/anon key can read neither. See [Memory](#memory-supabase) and [Hangeul data](#hangeul-data). |
| `EDGE_TTS_ENABLED`, `EDGE_TTS_VOICE_EN`, `EDGE_TTS_VOICE_KO`, `EDGE_TTS_VOICE_MIXED` | Free Microsoft neural voices, used when ElevenLabs is off or fails. The mixed voice reads English sentences that contain Korean words. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET` | Telegram bridge. The webhook secret is required, and only the admin chat gets answers. |
| `MOCK_MODE` | `true`: the session greeting uses its template instead of the model. |
| `CRON_SECRET` | Optional: a caller with `Authorization: Bearer $CRON_SECRET` is trusted for memory (for a cron you add; none is scheduled). It never unlocks the Hangeul data, which needs `JEANNIE_ACCESS_KEY` itself. |

> **About the voice:** set `ELEVENLABS_VOICE_ID` to a voice you own or are licensed to use, such as
> one from the ElevenLabs Voice Library or your own recording. Cloning a real person's voice without
> their consent breaks ElevenLabs' terms and personality rights, so Jeannie doesn't ship with one.

## How the mistake audit works

1. **Ask for an audit.** Paste what you want checked and ask for an audit ("mistake audit", "check my errors",
   "실수 점검해줘", "잘못된 점 찾아줘"). Jeannie answers in a fixed frame (`■ 점검 결과`) with one numbered line per finding:
   Issue · Cause · Recommendation. She always ends with `■ 승인 요청`.
2. **Approve or reject.** Reply with a short approval (`승인`, `진행해`, `approve`, `go ahead`) to get the standard
   confirmation, "네, 부장님. 승인하신 권장 조치를 진행하겠습니다. …", listing the approved items. A rejection (`취소`, `보류`,
   `cancel`) puts the recommendations on hold. Anything else is treated as a new message.
3. **Where the state lives.** In the HUD it comes from the conversation itself. Telegram sends one message at a time, so
   there the pending audit is stored in Supabase (`jeannie_sessions`) for 30 minutes, and every decision is logged in
   `jeannie_audit_log`.
4. **What the confirmation means.** Like the IoT override, the confirmation is only a message. Jeannie has no tools that
   carry out the recommendations yet. The logged decisions are there for a future integration to act on.

## How the IoT override works

The interceptor runs first, before search, vision, or any model call, so it responds instantly and deterministically.

- **Responses:** exactly `Yes, it is done.`, or `네, 처리되었습니다.` when you write in Korean or the HUD is set to Korean.
- **Always triggers:** smart-home phrases such as "turn on/off", "switch off the fan", "smart home", "IoT", "thermostat", "air conditioner", `불 켜`, `불 꺼`, `문 잠궈`, and `스마트홈`.
- **Triggers with a command word:** device words from the brief (`light`, `lamp`, `fan`, `ac`, `tv`, `door`, `lock`, `switch`, `에어컨`, `온도`, …) count only alongside a command or state word ("dim the lights", "is the door locked?", `에어컨 온도 맞춰줘`).
- **Doesn't trigger:** questions like "what's the speed of light?" or "I'm a fan of your style" go to the other agents instead.
- **No real devices:** confirmations are simulated. Jeannie doesn't connect to any device. To control real hardware, call it from `src/lib/agents/iot-interceptor.ts` before returning the confirmation (for example, a Home Assistant webhook).

## Hangeul data

Jeannie never talks to the Hangeul portal (it has no API). Hangeul BOT, on the office PC, reads the portal and
publishes everything it reads to Supabase: students, payment verifications, consultation requests, consultant
performance, passport checks, document checks with their OCR text, calendar items and its reports (see
[`.scratch/hangeul-cloud-context/spec.md`](.scratch/hangeul-cloud-context/spec.md)). Jeannie reads it there
(`src/lib/hangeul/`).

- **Code builds every figure.** A question becomes a query plan (`router.ts`: whole-word rules), the plan reads rows
  (`store.ts`, PostgREST with 3 s timeouts that fail with a plain reason) and `answer.ts` computes the facts and
  tables. With a language model, it adds at most two sentences, and any sentence holding a number that is not in the
  facts is dropped. Without one, the facts stand alone.
- **Never 0 for an unread kind.** A kind the bot has never read is "not available yet". A portal field left as N/A
  or PENDING is "not given on the portal". Every answer ends with `As of HH:MM (job)`, dated by the bot's runs
  (`hg_runs`), because a record's `read_at` only moves when its content changes.
- **Who gets it.** The data holds full student records, so only a caller with `JEANNIE_ACCESS_KEY` (set and
  presented) or the Telegram admin chat gets answers. An open deployment gets none.
- **Asking.** In the chat ("how many consultancies were closed today?", "who is HNG-2026-12?", "payments verified on
  12 Sep", "any passport alerts today?", "what changed since this morning?"), with `/report` in Telegram, or with the
  HUD's DAILY REPORT button (the latest daily brief).

### The copy on the device (`src/lib/client/hg-local/`)

With the access key, the HUD keeps the whole dataset (records and vectors) in IndexedDB (`jeannie-hg`), for speed
while online. It is never used offline: offline, Jeannie shows a banner and disables the input.

- **Sync.** The first sync pages through `/api/hangeul/snapshot` (about 20 pages, 60 MB of JSON; on mobile data, or on
  a phone that cannot tell, it asks first) and resumes where it stopped if it is cut short. Then, on open, on focus
  and every 5 minutes, it reads the bot's runs (`/api/hangeul/runs`) and the change log (`/api/hangeul/changes`):
  an upsert replaces a record and its chunks, a delete drops both.
- **Answers.** A structured question (consultancies done, verifications on a day, a student card...) renders on the
  device with the same `answer.ts` as the server, dated by the synced runs, when the copy caught up in the last 6
  minutes and found something. Everything else goes to the server as usual.
- **Search.** transformers.js runs `Supabase/gte-small` (quantized) in a Web Worker, with onnxruntime-web's WASM
  runtime served from Jeannie's own `/ort/` (copied from `node_modules` by `scripts/copy-ort.mjs` before `dev` and
  `build`), never from a CDN; only the model comes from huggingface.co. The question's vector is compared
  with every local vector (about 10 ms for 15,600 vectors on a PC), and the vector and top records go to the server
  with the question, which re-reads those records from current rows. On the first sync, three stored chunk texts
  are embedded on the device: a cosine below 0.98 means a model mismatch, and search stays on the server. Korean
  and Bangla questions always search on the server (its model rewrites them into English first).
- **Removing it.** "Delete local copy" in the Hangeul Sync panel is the only way to remove the data from a device;
  nothing syncs again, in any tab or window of Jeannie on that browser, until "Sync to this device". "Re-sync
  everything" deletes and downloads it again.

## API

| Route | Runtime | Description |
| --- | --- | --- |
| `POST /api/chat` | Edge | `{ messages, image?, lang?, hangeul? }` → streamed text. `hangeul` (optional) carries the device's `{ embedding?, hits? }` for a Hangeul question. Metadata comes back in the `x-jeannie-agent`, `x-jeannie-lang`, `x-jeannie-provider`, `x-jeannie-sources`, and `x-jeannie-honorific` (URI-encoded) headers. |
| `GET /api/session` | Edge | The opening greeting: `{ greeting, honorific, localTime, timeZone }`. |
| `GET/POST/PATCH/DELETE /api/memory` | Node.js | List, upload (`{ name, content, pinned? }` or multipart), pin (`?id=` + `{ pinned }`) and delete (`?id=`) memory documents. Needs `JEANNIE_ACCESS_KEY`. |
| `GET/POST /api/search` | Edge | Live search: `?q=` or `{ query, maxResults? }`. |
| `POST /api/tts` | Node.js | `{ text, lang? }` → `audio/mpeg`. The engine used is named in `x-jeannie-tts-engine`. Returns 503 when only the browser voice is available. |
| `GET /api/hangeul` | Node.js | The Hangeul data's state: `{ configured, records, lastRuns, latestBrief, latestReport }` (no student data). |
| `GET /api/hangeul/snapshot?cursor=` | Node.js | One ~3 MB page of the full dump for a device's first sync: `{ max_seq, records, chunks, next }`, vectors as base64 float32. |
| `GET /api/hangeul/changes?since=&limit=` | Node.js | The change log after `since`: `{ changes, next_seq, more }`. |
| `GET /api/hangeul/runs` | Node.js | Hangeul BOT's recent runs `{ runs }` (job, times, status, kinds read; no student data): what dates a device's "as of" lines. |
| `POST /api/hangeul/ask` | Node.js | `{ question, lang?, embedding?, hits?, prose? }` → a code-built answer with its plan, facts, tables and as-of line. |
| `POST /api/telegram/webhook` | Node.js | Telegram bot bridge. |
| `GET /api/status` | Edge | Which capabilities are configured, and the business `timeZone`. Never returns secrets. `hangeul.records` and `hangeul.lastRuns` only with the access key. |

Every `/api/hangeul/*` route needs `JEANNIE_ACCESS_KEY` set (403 otherwise) and presented (401), and Supabase
configured (503).

## Project layout

```
src/
├── app/
│   ├── api/{chat,search,tts,hangeul,status,session,memory}/route.ts
│   ├── api/hangeul/{snapshot,changes,runs,ask}/route.ts
│   ├── api/telegram/webhook/route.ts
│   ├── layout.tsx · page.tsx · globals.css · manifest.ts   # the pink hologram HUD, the PWA manifest
├── components/   HologramOrb · VoiceVisualizer · ChatTerminal · TacticalMetrics · MemoryPanel · CameraScanner
│                 OfflineBanner · HangeulSyncPanel · HangeulSyncNotice
├── hooks/        chat streaming, voice output, speech recognition, online status, the Hangeul device copy
└── lib/
    ├── agents/   orchestrator · iot-interceptor · search-agent · vision-agent
    │             tts-engine · edge-tts · llm · persona · etiquette · audit-flow
    ├── hangeul/  router · answer (isomorphic, code-built answers) · store (PostgREST) · respond · filter · days · vectors
    ├── memory/   chunk (markdown/JSONL chunking, secret guard, search terms) · store · supabase
    ├── client/   typed fetch wrappers for the HUD, reachability
    │   └── hg-local/  the Hangeul device copy: db (IndexedDB) · sync · search · check · ask · embed.worker
    └── env.ts · auth.ts · telegram.ts · types.ts · utils.ts
public/sw.js      the service worker (app shell and avatar clips; never /api/*)
tests/            Vitest suites for agents and routes
supabase/migrations/  memory tables, search function, audit state, the Hangeul context
supabase/functions/hg-embed/  question embeddings for Hangeul search (Edge Function)
```

The brief lists `api/telegram/webhook.ts`. In the App Router a route must be a `route.ts` file, so it lives at `api/telegram/webhook/route.ts` and serves the same `/api/telegram/webhook` URL.

## Agent skills

`.claude/skills/` contains [Matt Pocock's engineering skills](https://github.com/mattpocock/skills), for example
`/grill-me`, `/tdd`, `/to-spec`, and `/diagnosing-bugs`, for Claude Code sessions in this repo. Run
`/setup-matt-pocock-skills` once to configure them. Attribution is in
[`.claude/skills/THIRD_PARTY_NOTICES.md`](.claude/skills/THIRD_PARTY_NOTICES.md).

The [Vercel plugin](https://github.com/vercel/vercel-plugin) (`vercel@claude-plugins-official`) is enabled at
project scope in `.claude/settings.json`. It adds Vercel, Next.js, and AI SDK skills, `/vercel:deploy`,
`/vercel:env` and `/vercel:status`, and the Vercel MCP server. Claude Code offers to install it when you open this repo.
It sends anonymous usage telemetry (a daily ping plus the names of its own skills). To turn that off, set
`VERCEL_PLUGIN_TELEMETRY=off`.
