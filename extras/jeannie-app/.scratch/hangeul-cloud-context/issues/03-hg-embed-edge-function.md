# hg-embed Edge Function

Status: ready-for-human

Built and tested on `saem/hangeul-context-reader`. Not deployed: the owner deploys it after review (steps below).
Ticket 3 of the spec's §10. See spec §4 (Edge Function `hg-embed`), D8 and D12.

## What

`supabase/functions/hg-embed/index.ts`: `POST {"texts": string[]}` returns
`{"embeddings": number[][], "model": "gte-small", "dims": 384}`, computed by the Edge Runtime's built-in
`Supabase.ai.Session('gte-small')` run with `{mean_pool: true, normalize: true}`. That is the ONNX export of
`thenlper/gte-small`, the model Hangeul BOT embeds every chunk with (`embed_model` =
`thenlper/gte-small@17e1f347…`). Jeannie's server uses it for question embeddings before a device has its own model
loaded.

## Contract (for ticket 4, `src/lib/hangeul/store.ts`)

- URL: `${SUPABASE_URL}/functions/v1/hg-embed`, method `POST`, `content-type: application/json`.
- Key: send the server's `SUPABASE_SECRET_KEY` in `apikey`. For a legacy `eyJ…` service-role key, also send
  `Authorization: Bearer`. That is the same header rule as `supabaseRest` in `src/lib/memory/supabase.ts`.
- The function accepts any value of `SUPABASE_SECRET_KEYS` (every named secret key) or `SUPABASE_SERVICE_ROLE_KEY`,
  compared in constant time. It never reads the publishable or anon keys. With neither variable set it answers 503
  `not_configured`: it fails closed, never open.
- Limits: 1 to `MAX_TEXTS` = 16 texts, each non-blank and at most `MAX_TEXT_CHARS` = 2,000 characters, and a body of
  at most `MAX_BODY_BYTES` = 128 KiB (checked from `content-length` and while reading).
- Errors: JSON `{"error", "code"}` (the app's `errorResponse` shape), with `cache-control: no-store`. They never
  repeat a text or a key. Logs carry only an index and an error name.

  | Status | Codes |
  |---|---|
  | 405 | `method_not_allowed` (with `Allow: POST`) |
  | 503 | `not_configured`, `model_unavailable` |
  | 401 | `unauthorized` |
  | 413 | `body_too_large` |
  | 400 | `unreadable_body`, `invalid_json`, `invalid_body`, `no_texts`, `too_many_texts`, `invalid_text`, `empty_text`, `text_too_long` |
  | 500 | `embed_failed`, `bad_embedding` (the model did not return 384 finite numbers) |

- Checks run in this order: method, configuration, key, body size, JSON, texts, model. So an unauthorised caller never
  has its body read or the model loaded.
- No CORS: it is for server-to-server calls only, so a browser can't call it cross-origin.
- The caller should keep its own timeout (store.ts uses 3 s) and fall back with a plain reason (R5), because the first
  call after a cold start loads the model.

## Why one file

Deno needs `.ts` import paths, and the app's `tsc` (which type-checks `**/*.ts`, this file included) refuses them. So
the pure logic (`createHandler`, `acceptedKeys`, `presentedKeys`, `isAuthorized`, `parseTexts`, `toVector`) and the
Deno wiring (`main`) live in one file. `main()` only serves when `Deno.serve` exists, so importing the file under Node
(vitest) does nothing. The Edge Runtime globals are typed locally (`EdgeGlobals`), with no
`jsr:@supabase/functions-js` import.

## verify_jwt

The repo has no `supabase/config.toml`, so the flag goes on the deploy command, `--no-verify-jwt`. The gateway's JWT
check does not understand `sb_secret_…` keys (Supabase docs, "Migrating to publishable and secret API keys", step 4).
A deploy without the flag turns that check back on and blocks the secret key.

## Tests

`tests/hg-embed.test.ts` has 56 tests, using a stubbed session with no model and no network, and synthetic keys and
texts only:

- **Auth.** Every named secret key and the legacy key work, in `apikey` or `Bearer`. These are refused: no key, a
  wrong key, a prefix of the key, the key with one extra character, the publishable key, the anon key, and the key
  under another scheme. The call fails closed with no key configured. The key is checked before the body is read, and
  keys are read at request time.
- **Input validation.** 405 for other methods. Every 400 code, with nothing embedded. Exactly at the limits is
  accepted. A body over the cap gets 413, whether its size is declared or streamed. Errors name the index, never the
  text.
- **Response shape.** One vector per text, in order, run with `{mean_pool: true, normalize: true}`, and a
  `Float32Array` becomes JSON numbers. The session is created once and retried if creating it threw. A model that throws
  gives 500 `embed_failed` without echoing anything. A wrong length, NaN, strings or an object give `bad_embedding`.
- **`main`.** It does nothing outside Deno. Inside the Edge Runtime it serves the handler, with
  `Supabase.ai.Session('gte-small')` and `Deno.env`. It answers 503 when `Supabase.ai` or the env is missing.

## Owner steps (after review)

1. Deploy: `supabase functions deploy hg-embed --no-verify-jwt --project-ref dcbcbpwpmdtaanboetiz`.
2. Smoke test (README, "Hangeul question embeddings"). A question returns 384 numbers, and the same call without the
   key returns 401.
3. Model check (spec §6, cosine ≥ 0.98). Embed the `content` of three stored `hg_chunks` rows through `hg-embed`, and
   compare each with its stored `embedding`. Below 0.98 means the Edge Runtime's gte-small does not match the bot's
   vectors, so the server path must not use `hg_match` with these vectors until that is resolved.

## Comments
