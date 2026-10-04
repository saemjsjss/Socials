// hg-embed: question embeddings for Jeannie's server (spec §4 and D12,
// .scratch/hangeul-cloud-context/spec.md).
//
// POST {"texts": ["..."]} -> {"embeddings": [[...384 numbers], ...], "model": "gte-small", "dims": 384}
//
// The vectors come from the Edge Runtime's built-in gte-small (`Supabase.ai.Session`, mean pooled
// and normalised): the ONNX export of thenlper/gte-small, the model Hangeul BOT embeds every chunk
// with. Jeannie's server calls it to embed a question before a device has its own model loaded, then
// searches the chunks with `hg_match`.
//
// Auth: deployed with verify_jwt off (`supabase functions deploy hg-embed --no-verify-jwt`), because
// the gateway's JWT check does not understand `sb_secret_…` keys. The function checks the key itself
// against the project's secret keys (`SUPABASE_SECRET_KEYS`, a JSON object of named keys, plus the
// legacy `SUPABASE_SERVICE_ROLE_KEY`; Supabase sets both) and fails closed when none is configured.
// Publishable and anon keys are never accepted.
//
// Errors are JSON `{"error", "code"}` (the app's `errorResponse` shape) and never repeat a text or a key.
//
// One file on purpose: Deno needs ".ts" import paths and the app's tsc refuses them, so the pure logic
// (tested under Node by tests/hg-embed.test.ts) and the Deno wiring (`main`) live together. `main`
// only serves inside the Edge Runtime, so importing this file anywhere else has no effect.

export const MODEL = "gte-small";
export const DIMENSIONS = 384;
/** Texts per call. The server embeds one question (maybe with a rewritten search query). */
export const MAX_TEXTS = 16;
/** Characters (UTF-16 units) per text. gte-small reads 512 tokens; a question is far shorter. */
export const MAX_TEXT_CHARS = 2_000;
/**
 * Request body cap, checked before parsing. MAX_TEXTS texts of MAX_TEXT_CHARS characters fit even as
 * Korean UTF-8 (3 bytes a character, about 96 KB).
 */
export const MAX_BODY_BYTES = 128 * 1024;
/** Configured keys shorter than this are ignored, so a stray short value can never be the key. */
export const MIN_KEY_LENGTH = 20;

/** Exactly what Supabase.ai's gte-small is run with (spec §4). */
export const RUN_OPTIONS: Readonly<{ mean_pool: true; normalize: true }> = Object.freeze({
  mean_pool: true,
  normalize: true,
});

/** The part of `Supabase.ai.Session` this function uses. */
export interface EmbedSession {
  run(input: string, options: { mean_pool: boolean; normalize: boolean }): Promise<unknown>;
}

export interface HandlerDeps {
  /** Reads one environment variable (`Deno.env.get` in the Edge Runtime). */
  env: (name: string) => string | undefined;
  /** Makes the gte-small session. Called on the first authorised request, again only if it threw. */
  createSession: () => EmbedSession;
  /** Where failures are logged, never with a text or a key. Default `console.error`. */
  log?: (message: string) => void;
}

type Failure = { status: number; code: string; error: string };

function failure(status: number, code: string, error: string): Failure {
  return { status, code, error };
}

function json(body: unknown, status: number, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

function errorJson(f: Failure, headers?: Record<string, string>): Response {
  return json({ error: f.error, code: f.code }, f.status, headers);
}

/** Constant-time string comparison (same as `timingSafeEqual` in src/lib/utils.ts). */
export function timingSafeEqual(a: string, b: string): boolean {
  const ea = new TextEncoder().encode(a);
  const eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  const len = Math.max(ea.length, eb.length);
  for (let i = 0; i < len; i++) diff |= (ea[i] ?? 0) ^ (eb[i] ?? 0);
  return diff === 0;
}

/**
 * The keys a caller may present: every value of `SUPABASE_SECRET_KEYS` (all named secret keys of the
 * project) and the legacy `SUPABASE_SERVICE_ROLE_KEY`. Malformed JSON, non-strings and short values
 * are ignored. Nothing else is read, so a publishable or anon key can never match.
 */
export function acceptedKeys(env: (name: string) => string | undefined): string[] {
  const keys = new Set<string>();
  const add = (value: unknown) => {
    if (typeof value !== "string") return;
    const key = value.trim();
    if (key.length >= MIN_KEY_LENGTH) keys.add(key);
  };

  const named = env("SUPABASE_SECRET_KEYS")?.trim();
  if (named) {
    try {
      const parsed: unknown = JSON.parse(named);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) Object.values(parsed).forEach(add);
    } catch {
      // Not JSON: no keys from it.
    }
  }
  add(env("SUPABASE_SERVICE_ROLE_KEY"));
  return [...keys];
}

/** Keys the request presents: the `apikey` header and an `Authorization: Bearer` token. */
export function presentedKeys(req: Request): string[] {
  const keys: string[] = [];
  const apikey = req.headers.get("apikey")?.trim();
  if (apikey) keys.push(apikey);
  const bearer = /^Bearer\s+(\S+)$/i.exec(req.headers.get("authorization")?.trim() ?? "");
  if (bearer) keys.push(bearer[1]);
  return keys;
}

/** True when any presented key equals any accepted key. Compares every pair (no early exit). */
export function isAuthorized(req: Request, accepted: readonly string[]): boolean {
  let ok = false;
  for (const presented of presentedKeys(req)) {
    for (const key of accepted) ok = timingSafeEqual(presented, key) || ok;
  }
  return ok;
}

/** Validates the parsed body: `{texts}` with 1..MAX_TEXTS non-blank strings of at most MAX_TEXT_CHARS. */
export function parseTexts(body: unknown): { texts: string[] } | Failure {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return failure(400, "invalid_body", 'Send a JSON object: {"texts": ["..."]}.');
  }
  const texts = (body as { texts?: unknown }).texts;
  if (!Array.isArray(texts)) return failure(400, "invalid_body", '"texts" must be an array of strings.');
  if (texts.length === 0) return failure(400, "no_texts", '"texts" is empty.');
  if (texts.length > MAX_TEXTS) return failure(400, "too_many_texts", `At most ${MAX_TEXTS} texts per call.`);
  for (let i = 0; i < texts.length; i++) {
    const text: unknown = texts[i];
    if (typeof text !== "string") return failure(400, "invalid_text", `texts[${i}] is not a string.`);
    if (!text.trim()) return failure(400, "empty_text", `texts[${i}] is empty.`);
    if (text.length > MAX_TEXT_CHARS) {
      return failure(400, "text_too_long", `texts[${i}] is over ${MAX_TEXT_CHARS} characters.`);
    }
  }
  return { texts: texts as string[] };
}

/** The model's output as a plain array of DIMENSIONS finite numbers, or null. */
export function toVector(output: unknown): number[] | null {
  let values: unknown[];
  if (Array.isArray(output)) values = output;
  else if (output instanceof Float32Array || output instanceof Float64Array) values = Array.from(output);
  else return null;
  if (values.length !== DIMENSIONS) return null;
  for (const v of values) if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return values as number[];
}

/** The body as text, or null when it is over `max` bytes (declared or actual). */
async function readCapped(req: Request, max: number): Promise<string | null> {
  const declared = Number(req.headers.get("content-length") ?? "");
  if (Number.isFinite(declared) && declared > max) return null;
  if (!req.body) return "";

  const reader = req.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    parts.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    bytes.set(part, offset);
    offset += part.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function errorName(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
}

/**
 * The request handler. Order: method, configuration, key, body size, JSON, texts, then the model, so an
 * unauthorised caller never gets the body read or the model loaded.
 */
export function createHandler(deps: HandlerDeps): (req: Request) => Promise<Response> {
  const log = deps.log ?? ((message: string) => console.error(message));
  let session: EmbedSession | null = null;
  const getSession = (): EmbedSession => (session ??= deps.createSession());

  return async function handle(req: Request): Promise<Response> {
    if (req.method !== "POST") {
      return errorJson(failure(405, "method_not_allowed", "Use POST."), { allow: "POST" });
    }

    const accepted = acceptedKeys(deps.env);
    if (accepted.length === 0) {
      log("hg-embed: no secret key is configured (SUPABASE_SECRET_KEYS, SUPABASE_SERVICE_ROLE_KEY)");
      return errorJson(failure(503, "not_configured", "hg-embed has no secret key configured."));
    }
    if (!isAuthorized(req, accepted)) {
      return errorJson(
        failure(401, "unauthorized", "A secret key is required (apikey header or Authorization: Bearer)."),
      );
    }

    let raw: string | null;
    try {
      raw = await readCapped(req, MAX_BODY_BYTES);
    } catch {
      return errorJson(failure(400, "unreadable_body", "The request body could not be read."));
    }
    if (raw === null) {
      return errorJson(failure(413, "body_too_large", `The request body is over ${MAX_BODY_BYTES} bytes.`));
    }

    let body: unknown;
    try {
      body = JSON.parse(raw);
    } catch {
      return errorJson(failure(400, "invalid_json", "The request body is not valid JSON."));
    }
    const parsed = parseTexts(body);
    if ("error" in parsed) return errorJson(parsed);

    let model: EmbedSession;
    try {
      model = getSession();
    } catch (error) {
      log(`hg-embed: the gte-small session could not be created (${errorName(error)})`);
      return errorJson(failure(503, "model_unavailable", "The embedding model is not available."));
    }

    const embeddings: number[][] = [];
    for (let i = 0; i < parsed.texts.length; i++) {
      let output: unknown;
      try {
        output = await model.run(parsed.texts[i], RUN_OPTIONS);
      } catch (error) {
        log(`hg-embed: gte-small failed on texts[${i}] (${errorName(error)})`);
        return errorJson(failure(500, "embed_failed", "The model could not embed the texts."));
      }
      const vector = toVector(output);
      if (!vector) {
        log(`hg-embed: gte-small returned no ${DIMENSIONS}-number vector for texts[${i}]`);
        return errorJson(failure(500, "bad_embedding", `The model did not return ${DIMENSIONS} numbers.`));
      }
      embeddings.push(vector);
    }
    return json({ embeddings, model: MODEL, dims: DIMENSIONS }, 200);
  };
}

/** The Edge Runtime globals this function uses (typed here, so the app's tsc checks this file too). */
export interface EdgeGlobals {
  Deno?: {
    serve?: (handler: (req: Request) => Promise<Response>) => unknown;
    env: { get(name: string): string | undefined };
  };
  Supabase?: { ai: { Session: new (model: string) => EmbedSession } };
}

/** Serves the handler when running in the Edge Runtime. Returns false (and does nothing) elsewhere. */
export function main(runtime: EdgeGlobals = globalThis as unknown as EdgeGlobals): boolean {
  const deno = runtime.Deno;
  if (!deno || typeof deno.serve !== "function") return false;
  deno.serve(
    createHandler({
      env: (name) => {
        try {
          return deno.env.get(name);
        } catch {
          return undefined;
        }
      },
      createSession: () => {
        const ai = runtime.Supabase?.ai;
        if (!ai) throw new Error("Supabase.ai is not available in this runtime");
        return new ai.Session(MODEL);
      },
    }),
  );
  return true;
}

main();
