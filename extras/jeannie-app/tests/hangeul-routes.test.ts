import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as chat } from "@/app/api/chat/route";
import { POST as ask } from "@/app/api/hangeul/ask/route";
import { GET as changes } from "@/app/api/hangeul/changes/route";
import { GET as dataStatus } from "@/app/api/hangeul/route";
import { GET as runsRoute } from "@/app/api/hangeul/runs/route";
import { GET as snapshot } from "@/app/api/hangeul/snapshot/route";
import { GET as status } from "@/app/api/status/route";
import type { SystemStatus } from "@/lib/types";
import { NOW, rec, records, runs } from "./hangeul-fixtures";
import { clearSupabase, configureSupabase, stubPostgrest, unit, type FakeDb } from "./hangeul-postgrest";

const KEY = "hud-access-key";
const MODEL = "thenlper/gte-small@test";

function db(): FakeDb {
  const all = records();
  return {
    records: all,
    chunks: all.map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL })),
    runs: runs(),
    changes: [
      { seq: 1, kind: "consultation", key: "900", op: "upsert", changed_at: "2026-09-30T05:00:00+00:00" },
      { seq: 2, kind: "notification", key: "gone", op: "delete", changed_at: "2026-09-30T06:00:00+00:00" },
    ],
  };
}

function request(path: string, init: { method?: string; body?: unknown; key?: string | null } = {}): Request {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (init.key !== null) headers["x-jeannie-key"] = init.key ?? KEY;
  return new Request(`http://localhost${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : typeof init.body === "string" ? init.body : JSON.stringify(init.body),
  });
}

const askBody = (body: unknown, key?: string | null) => request("/api/hangeul/ask", { method: "POST", body, key });

const ROUTES: [string, () => Request, (req: Request) => Promise<Response>][] = [
  ["GET /api/hangeul", () => request("/api/hangeul"), dataStatus],
  ["GET /api/hangeul/snapshot", () => request("/api/hangeul/snapshot"), snapshot],
  ["GET /api/hangeul/changes", () => request("/api/hangeul/changes?since=0"), changes],
  ["GET /api/hangeul/runs", () => request("/api/hangeul/runs"), runsRoute],
  ["POST /api/hangeul/ask", () => askBody({ question: "how many consultancies were closed today?" }), ask],
];

beforeEach(() => {
  for (const name of ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "LLM_PROVIDER", "CRON_SECRET"]) vi.stubEnv(name, "");
  vi.stubEnv("JEANNIE_ACCESS_KEY", KEY);
  configureSupabase();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe.each(ROUTES)("%s", (_name, make, handler) => {
  it("needs JEANNIE_ACCESS_KEY set (403), then presented (401), then Supabase (503)", async () => {
    const { fetchMock } = stubPostgrest(db());
    vi.stubEnv("JEANNIE_ACCESS_KEY", "");
    let res = await handler(make());
    expect(res.status).toBe(403);
    expect((await res.json()).code).toBe("access_key_not_configured");

    vi.stubEnv("JEANNIE_ACCESS_KEY", KEY);
    const wrong = make();
    wrong.headers.set("x-jeannie-key", "wrong");
    res = await handler(wrong);
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("access_key_required");

    clearSupabase();
    res = await handler(make());
    expect(res.status).toBe(503);
    expect((await res.json()).code).toBe("hangeul_not_configured");
    expect(fetchMock).not.toHaveBeenCalled();

    configureSupabase();
    res = await handler(make());
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});

describe("GET /api/hangeul", () => {
  it("shows volume, runs and the latest report without student data", async () => {
    stubPostgrest(db());
    const res = await dataStatus(request("/api/hangeul"));
    const raw = await res.text();
    expect(JSON.parse(raw)).toMatchObject({ configured: true, records: records().length, latestBrief: null });
    expect(raw).not.toContain("TEST STUDENT");
    expect(raw).not.toContain("A00000001");
  });

  it("503 when the tables are missing, 502 when Supabase is down", async () => {
    stubPostgrest(db(), () => new Response(JSON.stringify({ code: "PGRST205" }), { status: 404 }));
    const missing = await dataStatus(request("/api/hangeul"));
    expect(missing.status).toBe(503);
    expect((await missing.json()).code).toBe("hangeul_not_migrated");
    stubPostgrest(db(), () => new Response("{}", { status: 500 }));
    const down = await dataStatus(request("/api/hangeul"));
    expect(down.status).toBe(502);
    expect((await down.json()).error).toContain("Hangeul data unreachable (HTTP 500)");
  });
});

describe("GET /api/hangeul/runs", () => {
  it("gives a device the bot's runs (what dates its 'as of' lines), without student data", async () => {
    stubPostgrest(db());
    const res = await runsRoute(request("/api/hangeul/runs"));
    const raw = await res.text();
    const body = JSON.parse(raw) as { runs: { job: string; finished_at: string; byKind: Record<string, number[]> }[] };
    expect(body.runs.map((r) => r.job)).toEqual(["portal_sync", "passport_watcher", "full_picture", "full_picture", "backfill"]);
    expect(body.runs[2].byKind).toHaveProperty("consultant_performance");
    expect(raw).not.toContain("TEST STUDENT");
    expect(raw).not.toContain("A00000001");
  });

  it("502 when Supabase is down", async () => {
    stubPostgrest(db(), () => new Response("{}", { status: 500 }));
    const res = await runsRoute(request("/api/hangeul/runs"));
    expect(res.status).toBe(502);
    expect((await res.json()).code).toBe("hangeul_unavailable");
  });
});

describe("GET /api/hangeul/snapshot", () => {
  it("pages through every record with a stable cursor and base64 vectors", async () => {
    const data = db();
    // Enough rows for several pages.
    data.records.push(...Array.from({ length: 1_200 }, (_, i) => rec("doc_verdict", `B${String(i).padStart(8, "0")}|01 Passport`, { scope: "x", content: "z".repeat(2_500) })));
    data.chunks.push(...data.records.slice(-1_200).map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL })));
    stubPostgrest(data);
    const keys = new Set<string>();
    let cursor: string | null = null;
    let pages = 0;
    do {
      const res: Response = await snapshot(request(`/api/hangeul/snapshot${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`));
      expect(res.status).toBe(200);
      const body = (await res.json()) as { max_seq: number; records: { kind: string; key: string }[]; chunks: { embedding: string }[]; next: string | null; vector: unknown };
      expect(body.max_seq).toBe(2);
      expect(body.vector).toEqual({ encoding: "base64-float32le", dimensions: 384 });
      for (const r of body.records) {
        expect(keys.has(`${r.kind}|${r.key}`)).toBe(false);
        keys.add(`${r.kind}|${r.key}`);
      }
      for (const c of body.chunks) expect(c.embedding).toHaveLength(2_048);
      cursor = body.next;
      pages++;
    } while (cursor && pages < 20);
    expect(pages).toBeGreaterThan(1);
    expect(keys.size).toBe(data.records.length);
  });

  it("400 for a cursor it did not issue", async () => {
    stubPostgrest(db());
    const res = await snapshot(request("/api/hangeul/snapshot?cursor=garbage"));
    expect(res.status).toBe(400);
    expect((await res.json()).code).toBe("invalid_cursor");
  });
});

describe("GET /api/hangeul/changes", () => {
  it("returns the delta after since, with next_seq and more", async () => {
    stubPostgrest(db());
    const res = await changes(request("/api/hangeul/changes?since=0&limit=10"));
    const body = (await res.json()) as { changes: { seq: number; op: string; record?: unknown }[]; next_seq: number; more: boolean };
    expect(body.changes.map((c) => [c.seq, c.op])).toEqual([
      [1, "upsert"],
      [2, "delete"],
    ]);
    expect(body.changes[1]).toEqual({ seq: 2, kind: "notification", key: "gone", op: "delete", changed_at: "2026-09-30T06:00:00+00:00" });
    expect(body).toMatchObject({ next_seq: 2, more: false });
  });

  it.each([
    ["/api/hangeul/changes", "since: missing"],
    ["/api/hangeul/changes?since=-1", "since: expected a whole number"],
    ["/api/hangeul/changes?since=abc", "since: expected a whole number"],
    ["/api/hangeul/changes?since=0&limit=0", "limit: expected 1 to 1000"],
    ["/api/hangeul/changes?since=0&limit=5000", "limit: expected 1 to 1000"],
  ])("400 for %s", async (path, message) => {
    stubPostgrest(db());
    const res = await changes(request(path));
    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(message);
  });
});

describe("POST /api/hangeul/ask", () => {
  it("answers the owner's question with code-built figures and the as-of line (no model configured)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    stubPostgrest(db());
    const res = await ask(askBody({ question: "how many consultancies were closed today?" }));
    const body = (await res.json()) as { provider: string; text: string; plan: { intent: string }; result: { facts: { value: string }[] }; as_of: string };
    expect(body.provider).toBe("none");
    expect(body.plan).toEqual({ intent: "consultancies_closed_today", day: "2026-09-30" });
    expect(body.text).toContain("Consultancies done today (30 Sep): 20");
    expect(body.text).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    expect(body.as_of).toBe("As of 17:35 (full picture)");
    expect(body.result.facts[0].value).toBe("20");
  });

  it("re-reads the device's hits from current rows", async () => {
    stubPostgrest(db());
    const res = await ask(
      askBody({ question: "what does the bank statement say?", hits: [{ kind: "doc_verdict", key: "A00000001|08 Bank Solvency & Statement" }], embedding: unit(4) }),
    );
    const body = (await res.json()) as { plan: { intent: string }; text: string; result: { sources: unknown[] } };
    expect(body.plan.intent).toBe("semantic");
    expect(body.text).toContain("verdict: FLAG");
    expect(body.result.sources).toEqual([{ kind: "doc_verdict", key: "A00000001|08 Bank Solvency & Statement" }]);
  });

  it.each([
    [{ question: "" }, "question: question is empty"],
    [{ question: "x", embedding: [1, 2, 3] }, "embedding"],
    [{ question: "x", embedding: "AAAA" }, "embedding: expected 384 numbers"],
    [{ question: "x", hits: Array.from({ length: 25 }, () => ({ kind: "student", key: "1" })) }, "at most 24 hits"],
    ["{not json", "Request body must be JSON."],
  ])("400 for a bad body %#", async (body, message) => {
    stubPostgrest(db());
    const res = await ask(askBody(body));
    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(message);
  });
});

describe("POST /api/chat and the Hangeul data", () => {
  const CRON = "cron-secret-value";
  const chatRequest = (headers: Record<string, string>) =>
    new Request("http://localhost/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify({ messages: [{ role: "user", content: "Who is HNG-2026-12?" }], lang: "en" }),
    });

  it("an open deployment (no access key) gives the cron bearer the key line, and reads no student data", async () => {
    vi.stubEnv("JEANNIE_ACCESS_KEY", "");
    vi.stubEnv("CRON_SECRET", CRON);
    const { calls } = stubPostgrest(db());
    const res = await chat(chatRequest({ authorization: `Bearer ${CRON}` }));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-jeannie-agent")).toBe("hangeul");
    const text = await res.text();
    expect(text).toContain("access key");
    expect(text).not.toContain("TEST STUDENT ONE");
    expect(text).not.toContain("A00000001");
    expect(calls.filter((c) => c.path.startsWith("/rest/v1/hg_"))).toEqual([]);
  });

  it("the access key itself unlocks the student card", async () => {
    vi.stubEnv("CRON_SECRET", CRON);
    stubPostgrest(db());
    const text = await (await chat(chatRequest({ "x-jeannie-key": KEY }))).text();
    expect(text).toContain("TEST STUDENT ONE (HNG-2026-012, portal uid 101): Documents Verified.");
    // With the key set, the cron bearer is not even let in.
    expect((await chat(chatRequest({ authorization: `Bearer ${CRON}` }))).status).toBe(401);
  });
});

describe("GET /api/status", () => {
  it("says Hangeul is configured to everyone, and adds volume and runs only with the key", async () => {
    stubPostgrest(db());
    const open = (await (await status(request("/api/status", { key: null }))).json()) as SystemStatus;
    expect(open.hangeul).toEqual({ configured: true, records: null, lastRuns: null });

    const keyed = (await (await status(request("/api/status"))).json()) as SystemStatus;
    expect(keyed.hangeul.configured).toBe(true);
    expect(keyed.hangeul.records).toBe(records().length);
    expect(keyed.hangeul.lastRuns?.map((r) => r.job)).toEqual(["portal_sync", "passport_watcher", "full_picture", "backfill"]);
  });

  it("falls back to null volumes when Supabase does not answer, and reports unconfigured", async () => {
    stubPostgrest(db(), () => new Response("{}", { status: 500 }));
    const keyed = (await (await status(request("/api/status"))).json()) as SystemStatus;
    expect(keyed.hangeul).toEqual({ configured: true, records: null, lastRuns: null });
    clearSupabase();
    const off = (await (await status(request("/api/status"))).json()) as SystemStatus;
    expect(off.hangeul).toEqual({ configured: false, records: null, lastRuns: null });
  });
});
