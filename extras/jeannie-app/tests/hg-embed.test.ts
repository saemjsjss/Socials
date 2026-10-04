// The hg-embed Edge Function's pure logic under Node: the key check, input validation and the
// response shape, with a stubbed Supabase.ai session (no model, no network). Synthetic keys and
// texts only.

import { describe, expect, it } from "vitest";
import {
  DIMENSIONS,
  MAX_BODY_BYTES,
  MAX_TEXT_CHARS,
  MAX_TEXTS,
  MODEL,
  acceptedKeys,
  createHandler,
  main,
  parseTexts,
  presentedKeys,
  toVector,
  type EdgeGlobals,
  type EmbedSession,
} from "../supabase/functions/hg-embed/index";

const SECRET = "sb_secret_TESTONLY_default_000000000000";
const SECRET_NAMED = "sb_secret_TESTONLY_jeannie_11111111111";
const LEGACY = "eyJTESTONLY.service-role.legacy-jwt-000000000000";
const PUBLISHABLE = "sb_publishable_TESTONLY_default_22222222";
const ANON = "eyJTESTONLY.anon.legacy-jwt-3333333333333333";

const PROJECT_ENV: Record<string, string> = {
  SUPABASE_SECRET_KEYS: JSON.stringify({ default: SECRET, jeannie: SECRET_NAMED }),
  SUPABASE_SERVICE_ROLE_KEY: LEGACY,
  SUPABASE_PUBLISHABLE_KEYS: JSON.stringify({ default: PUBLISHABLE }),
  SUPABASE_ANON_KEY: ANON,
};

const QUESTION = "How many consultancies were closed today?";

/** A deterministic unit vector per text (1 at an index taken from its length). */
function vectorFor(text: string): number[] {
  const hot = text.length % DIMENSIONS;
  return Array.from({ length: DIMENSIONS }, (_, i) => (i === hot ? 1 : 0));
}

interface Stub {
  session: EmbedSession;
  calls: Array<{ input: string; options: unknown }>;
}

function stubSession(output: (text: string) => unknown = vectorFor): Stub {
  const calls: Stub["calls"] = [];
  return {
    calls,
    session: {
      run: async (input, options) => {
        calls.push({ input, options });
        return output(input);
      },
    },
  };
}

type Handler = (req: Request) => Promise<Response>;

interface Harness {
  handle: Handler;
  stub: Stub;
  created: () => number;
  logs: string[];
}

function harness(
  env: Record<string, string | undefined> = PROJECT_ENV,
  opts: { output?: (text: string) => unknown; createSession?: () => EmbedSession } = {},
): Harness {
  const stub = stubSession(opts.output);
  const logs: string[] = [];
  let created = 0;
  const handle = createHandler({
    env: (name) => env[name],
    createSession: () => {
      created++;
      return opts.createSession ? opts.createSession() : stub.session;
    },
    log: (message) => logs.push(message),
  });
  return { handle, stub, created: () => created, logs };
}

function post(body: unknown, headers: Record<string, string> = { apikey: SECRET }): Request {
  return new Request("https://project.test/functions/v1/hg-embed", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function errorOf(res: Response): Promise<{ status: number; code: string; error: string }> {
  expect(res.headers.get("content-type")).toContain("application/json");
  expect(res.headers.get("cache-control")).toBe("no-store");
  const body = (await res.json()) as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual(["code", "error"]);
  expect(typeof body.error).toBe("string");
  expect(typeof body.code).toBe("string");
  return { status: res.status, code: body.code as string, error: body.error as string };
}

describe("acceptedKeys", () => {
  it("accepts every named secret key and the legacy service-role key, once each", () => {
    const env: Record<string, string> = {
      SUPABASE_SECRET_KEYS: JSON.stringify({ default: SECRET, jeannie: SECRET_NAMED, copy: SECRET }),
      SUPABASE_SERVICE_ROLE_KEY: ` ${LEGACY} `,
    };
    expect(acceptedKeys((name) => env[name]).sort()).toEqual([LEGACY, SECRET, SECRET_NAMED].sort());
  });

  it("reads only the secret-key variables, so publishable and anon keys never match", () => {
    const reads: string[] = [];
    acceptedKeys((name) => {
      reads.push(name);
      return PROJECT_ENV[name];
    });
    expect(new Set(reads)).toEqual(new Set(["SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY"]));
  });

  it("ignores malformed JSON, arrays, non-strings and short values", () => {
    const read = (env: Record<string, string>) => acceptedKeys((name) => env[name]);
    expect(read({ SUPABASE_SECRET_KEYS: "{not json" })).toEqual([]);
    expect(read({ SUPABASE_SECRET_KEYS: JSON.stringify([SECRET]) })).toEqual([]);
    expect(read({ SUPABASE_SECRET_KEYS: JSON.stringify(SECRET) })).toEqual([]);
    expect(read({ SUPABASE_SECRET_KEYS: JSON.stringify({ a: 42, b: null, c: { d: SECRET }, e: "short" }) })).toEqual(
      [],
    );
    expect(read({ SUPABASE_SERVICE_ROLE_KEY: "   " })).toEqual([]);
    expect(read({})).toEqual([]);
  });
});

describe("presentedKeys", () => {
  it("takes the apikey header and a Bearer token, and nothing from other schemes", () => {
    const req = (headers: Record<string, string>) => new Request("https://project.test/", { headers });
    expect(presentedKeys(req({ apikey: ` ${SECRET} ` }))).toEqual([SECRET]);
    expect(presentedKeys(req({ authorization: `Bearer ${LEGACY}` }))).toEqual([LEGACY]);
    expect(presentedKeys(req({ authorization: `bearer   ${LEGACY}  ` }))).toEqual([LEGACY]);
    expect(presentedKeys(req({ apikey: SECRET, authorization: `Bearer ${LEGACY}` }))).toEqual([SECRET, LEGACY]);
    expect(presentedKeys(req({ authorization: `Basic ${SECRET}` }))).toEqual([]);
    expect(presentedKeys(req({ authorization: "Bearer" }))).toEqual([]);
    expect(presentedKeys(req({ authorization: `Bearer ${SECRET} extra` }))).toEqual([]);
    expect(presentedKeys(req({}))).toEqual([]);
  });
});

describe("hg-embed auth", () => {
  it("fails closed with 503 when no secret key is configured, without loading the model", async () => {
    const h = harness({ SUPABASE_PUBLISHABLE_KEYS: PROJECT_ENV.SUPABASE_PUBLISHABLE_KEYS, SUPABASE_ANON_KEY: ANON });
    const res = await h.handle(post({ texts: [QUESTION] }, { apikey: PUBLISHABLE }));
    expect(await errorOf(res)).toMatchObject({ status: 503, code: "not_configured" });
    expect(h.created()).toBe(0);
    expect(h.logs.join("\n")).toContain("no secret key");
  });

  const REFUSED: Array<[string, Record<string, string>]> = [
    ["no key", {}],
    ["a wrong key", { apikey: "sb_secret_TESTONLY_wrong_999999999999999" }],
    ["a prefix of the key", { apikey: SECRET.slice(0, -1) }],
    ["the key plus a character", { apikey: `${SECRET}x` }],
    ["the publishable key", { apikey: PUBLISHABLE }],
    ["the anon key as Bearer", { authorization: `Bearer ${ANON}` }],
    ["the secret key in another scheme", { authorization: `Basic ${SECRET}` }],
  ];

  it.each(REFUSED)("answers 401 with %s and embeds nothing", async (_label, headers) => {
    const h = harness();
    const res = await h.handle(post({ texts: [QUESTION] }, headers));
    const error = await errorOf(res);
    expect(error).toMatchObject({ status: 401, code: "unauthorized" });
    expect(error.error).not.toContain(SECRET);
    expect(h.created()).toBe(0);
    expect(h.stub.calls).toEqual([]);
  });

  const ACCEPTED: Array<[string, Record<string, string>]> = [
    ["the default secret key in apikey", { apikey: SECRET }],
    ["a named secret key in apikey", { apikey: SECRET_NAMED }],
    ["a secret key as Bearer", { authorization: `Bearer ${SECRET}` }],
    ["the legacy service-role key as Bearer", { authorization: `Bearer ${LEGACY}` }],
    ["a valid apikey beside another Bearer token", { apikey: SECRET, authorization: `Bearer ${ANON}` }],
  ];

  it.each(ACCEPTED)("accepts %s", async (_label, headers) => {
    const h = harness();
    const res = await h.handle(post({ texts: [QUESTION] }, headers));
    expect(res.status).toBe(200);
  });

  it("checks the key before reading the body", async () => {
    const h = harness();
    const res = await h.handle(post("x".repeat(MAX_BODY_BYTES + 10), {}));
    expect((await errorOf(res)).status).toBe(401);
  });

  it("reads keys at request time, so a newly set secret works without a redeploy", async () => {
    const env: Record<string, string | undefined> = {};
    const h = harness(env);
    expect((await h.handle(post({ texts: [QUESTION] }))).status).toBe(503);
    env.SUPABASE_SECRET_KEYS = JSON.stringify({ default: SECRET });
    expect((await h.handle(post({ texts: [QUESTION] }))).status).toBe(200);
  });
});

describe("hg-embed input validation", () => {
  it.each(["GET", "PUT", "DELETE", "OPTIONS"])("answers %s with 405 and Allow: POST", async (method) => {
    const h = harness();
    const res = await h.handle(new Request("https://project.test/functions/v1/hg-embed", { method, headers: { apikey: SECRET } }));
    expect(res.headers.get("allow")).toBe("POST");
    expect(await errorOf(res)).toMatchObject({ status: 405, code: "method_not_allowed" });
  });

  const INVALID: Array<[string, unknown, number, string]> = [
    ["invalid JSON", "{texts: [", 400, "invalid_json"],
    ["an empty body", "", 400, "invalid_json"],
    ["a JSON array", [QUESTION], 400, "invalid_body"],
    ["a JSON string", JSON.stringify(QUESTION), 400, "invalid_body"],
    ["null", "null", 400, "invalid_body"],
    ["no texts field", { text: QUESTION }, 400, "invalid_body"],
    ["texts as a string", { texts: QUESTION }, 400, "invalid_body"],
    ["an empty texts array", { texts: [] }, 400, "no_texts"],
    ["too many texts", { texts: Array.from({ length: MAX_TEXTS + 1 }, () => QUESTION) }, 400, "too_many_texts"],
    ["a number among the texts", { texts: [QUESTION, 7] }, 400, "invalid_text"],
    ["a null text", { texts: [null] }, 400, "invalid_text"],
    ["a blank text", { texts: [QUESTION, "  \n\t "] }, 400, "empty_text"],
    ["a text over the limit", { texts: ["a".repeat(MAX_TEXT_CHARS + 1)] }, 400, "text_too_long"],
  ];

  it.each(INVALID)("rejects %s and embeds nothing", async (_label, body, status, code) => {
    const h = harness();
    const res = await h.handle(post(body));
    expect(await errorOf(res)).toMatchObject({ status, code });
    expect(h.stub.calls).toEqual([]);
    expect(h.created()).toBe(0);
  });

  it("names the offending index, never the text", async () => {
    const secretText = "PRIVATE-TEXT-THAT-MUST-NOT-ECHO ".repeat(70);
    const h = harness();
    const error = await errorOf(await h.handle(post({ texts: [QUESTION, secretText] })));
    expect(error).toMatchObject({ code: "text_too_long" });
    expect(error.error).toContain("texts[1]");
    expect(error.error).not.toContain("PRIVATE-TEXT");
  });

  it("accepts exactly the limits", async () => {
    const h = harness();
    const res = await h.handle(
      post({ texts: Array.from({ length: MAX_TEXTS }, (_, i) => (i === 0 ? "가".repeat(MAX_TEXT_CHARS) : QUESTION)) }),
    );
    expect(res.status).toBe(200);
    expect(h.stub.calls).toHaveLength(MAX_TEXTS);
  });

  it("refuses a body declared over the cap with 413", async () => {
    const h = harness();
    const req = post({ texts: [QUESTION] }, { apikey: SECRET, "content-length": String(MAX_BODY_BYTES + 1) });
    expect(await errorOf(await h.handle(req))).toMatchObject({ status: 413, code: "body_too_large" });
    expect(h.stub.calls).toEqual([]);
  });

  it("refuses a streamed body over the cap with 413, even with no content-length", async () => {
    const chunk = new TextEncoder().encode("x".repeat(16 * 1024));
    let sent = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent > MAX_BODY_BYTES * 2) return controller.close();
        sent += chunk.byteLength;
        controller.enqueue(chunk);
      },
    });
    const req = new Request("https://project.test/functions/v1/hg-embed", {
      method: "POST",
      headers: { apikey: SECRET, "content-type": "application/json" },
      body: stream,
      duplex: "half",
    } as RequestInit & { duplex: "half" });
    expect(req.headers.get("content-length")).toBeNull();
    const h = harness();
    expect(await errorOf(await h.handle(req))).toMatchObject({ status: 413, code: "body_too_large" });
    expect(sent).toBeLessThan(MAX_BODY_BYTES * 2);
  });

  it("parseTexts returns the texts unchanged", () => {
    expect(parseTexts({ texts: [" padded ", QUESTION], other: 1 })).toEqual({ texts: [" padded ", QUESTION] });
  });
});

describe("hg-embed response", () => {
  it("returns one 384-number vector per text, in order, from gte-small with mean_pool and normalize", async () => {
    const h = harness();
    const texts = [QUESTION, "passport alerts today", "오늘 상담 몇 건 완료됐어?"];
    const res = await h.handle(post({ texts }));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(res.headers.get("cache-control")).toBe("no-store");

    const body = (await res.json()) as { embeddings: number[][]; model: string; dims: number };
    expect(Object.keys(body).sort()).toEqual(["dims", "embeddings", "model"]);
    expect(body.model).toBe(MODEL);
    expect(body.dims).toBe(DIMENSIONS);
    expect(body.embeddings).toEqual(texts.map(vectorFor));
    expect(h.stub.calls).toEqual(texts.map((input) => ({ input, options: { mean_pool: true, normalize: true } })));
  });

  it("turns a Float32Array from the model into plain JSON numbers", async () => {
    const h = harness(PROJECT_ENV, { output: (text) => Float32Array.from(vectorFor(text)) });
    const body = (await (await h.handle(post({ texts: [QUESTION] }))).json()) as { embeddings: unknown[] };
    expect(Array.isArray(body.embeddings[0])).toBe(true);
    expect(body.embeddings[0]).toEqual(vectorFor(QUESTION));
  });

  it("creates the session once and reuses it across requests", async () => {
    const h = harness();
    for (let i = 0; i < 3; i++) expect((await h.handle(post({ texts: [QUESTION] }))).status).toBe(200);
    expect(h.created()).toBe(1);
    expect(h.stub.calls).toHaveLength(3);
  });

  it("answers 503 when the session cannot be created, and retries on the next request", async () => {
    let attempts = 0;
    const stub = stubSession();
    const h = harness(PROJECT_ENV, {
      createSession: () => {
        attempts++;
        if (attempts === 1) throw new TypeError("Supabase.ai is not available");
        return stub.session;
      },
    });
    expect(await errorOf(await h.handle(post({ texts: [QUESTION] })))).toMatchObject({
      status: 503,
      code: "model_unavailable",
    });
    expect((await h.handle(post({ texts: [QUESTION] }))).status).toBe(200);
    expect(attempts).toBe(2);
  });

  it("answers 500 embed_failed when the model throws, without echoing the text or the key", async () => {
    const h = harness(PROJECT_ENV, {
      output: (text) => {
        throw new Error(`model choked on ${text}`);
      },
    });
    const error = await errorOf(await h.handle(post({ texts: [QUESTION] })));
    expect(error).toMatchObject({ status: 500, code: "embed_failed" });
    const everything = `${error.error}\n${h.logs.join("\n")}`;
    expect(everything).not.toContain(QUESTION);
    expect(everything).not.toContain(SECRET);
    expect(h.logs.join("\n")).toContain("texts[0]");
  });

  const BAD_OUTPUTS: Array<[string, () => unknown]> = [
    ["too few numbers", () => [0.1, 0.2]],
    ["too many numbers", () => Array.from({ length: DIMENSIONS + 1 }, () => 0)],
    ["a NaN", () => Array.from({ length: DIMENSIONS }, (_, i) => (i === 5 ? Number.NaN : 0))],
    ["strings", () => Array.from({ length: DIMENSIONS }, () => "0")],
    ["an object", () => ({ embedding: vectorFor(QUESTION) })],
  ];

  it.each(BAD_OUTPUTS)("answers 500 bad_embedding when the model returns %s", async (_label, output) => {
    const h = harness(PROJECT_ENV, { output });
    expect(await errorOf(await h.handle(post({ texts: [QUESTION] })))).toMatchObject({
      status: 500,
      code: "bad_embedding",
    });
  });

  it("toVector accepts 384 finite numbers only", () => {
    expect(toVector(vectorFor("a"))).toEqual(vectorFor("a"));
    expect(toVector(Float64Array.from(vectorFor("a")))).toEqual(vectorFor("a"));
    expect(toVector(new Uint8Array(DIMENSIONS))).toBeNull();
    expect(toVector(null)).toBeNull();
    expect(toVector([Infinity, ...vectorFor("a").slice(1)])).toBeNull();
  });
});

describe("hg-embed main", () => {
  it("does nothing outside the Edge Runtime", () => {
    expect(main({})).toBe(false);
  });

  it("serves the handler with Deno.env and Supabase.ai.Session('gte-small') inside it", async () => {
    const served: { handler?: Handler } = {};
    const models: string[] = [];
    const runtime: EdgeGlobals = {
      Deno: {
        serve: (handler) => {
          served.handler = handler;
        },
        env: {
          get: (name) => {
            if (name === "SUPABASE_ANON_KEY") throw new Error("not permitted");
            return PROJECT_ENV[name];
          },
        },
      },
      Supabase: {
        ai: {
          Session: class {
            constructor(model: string) {
              models.push(model);
            }
            async run(input: string) {
              return vectorFor(input);
            }
          },
        },
      },
    };
    expect(main(runtime)).toBe(true);
    expect(served.handler).toBeTypeOf("function");
    expect((await served.handler!(post({ texts: [QUESTION] }))).status).toBe(200);
    expect((await served.handler!(post({ texts: [QUESTION] }, { apikey: PUBLISHABLE }))).status).toBe(401);
    expect(models).toEqual(["gte-small"]);
  });

  it("answers 503 model_unavailable when Supabase.ai is missing", async () => {
    const served: { handler?: Handler } = {};
    main({
      Deno: {
        serve: (handler) => {
          served.handler = handler;
        },
        env: { get: (name) => PROJECT_ENV[name] },
      },
    });
    const res = await served.handler!(post({ texts: [QUESTION] }));
    expect(await errorOf(res)).toMatchObject({ status: 503, code: "model_unavailable" });
  });

  it("answers 503 not_configured when Deno.env cannot be read", async () => {
    const served: { handler?: Handler } = {};
    main({
      Deno: {
        serve: (handler) => {
          served.handler = handler;
        },
        env: {
          get: () => {
            throw new Error("not permitted");
          },
        },
      },
    });
    const res = await served.handler!(post({ texts: [QUESTION] }));
    expect(await errorOf(res)).toMatchObject({ status: 503, code: "not_configured" });
  });
});
