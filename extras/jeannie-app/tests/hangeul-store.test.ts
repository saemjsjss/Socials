import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  countRecords,
  createHangeulStore,
  decodeCursor,
  embedQuestion,
  encodeCursor,
  filterParams,
  findStudents,
  quoteValue,
  readChanges,
  readChangesSince,
  readDataStatus,
  readRecords,
  readRuns,
  readSnapshotPage,
  READ_TIMEOUT_MS,
} from "@/lib/hangeul/store";
import { HangeulReadError, HG_KINDS, type HgRecord } from "@/lib/hangeul/types";
import { decodeVector } from "@/lib/hangeul/vectors";
import { rec, records, runs } from "./hangeul-fixtures";
import { clearSupabase, configureSupabase, SECRET, stubPostgrest, unit, URL_BASE, type FakeDb } from "./hangeul-postgrest";

const MODEL = "thenlper/gte-small@test";

function db(extra: Partial<FakeDb> = {}): FakeDb {
  const all = records();
  return {
    records: all,
    chunks: all.map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL })),
    runs: runs(),
    changes: [],
    ...extra,
  };
}

beforeEach(() => {
  configureSupabase();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("request shapes", () => {
  it("sends the secret key as apikey on a GET to /rest/v1/hg_records with a kind filter", async () => {
    const { calls } = stubPostgrest(db());
    const rows = await readRecords("consultation", { day: "2026-09-30" });
    expect(rows).toHaveLength(10);
    expect(calls).toHaveLength(1);
    expect(calls[0].url.startsWith(`${URL_BASE}/rest/v1/hg_records?select=*&kind=eq.consultation&day=eq.2026-09-30&order=key.asc&limit=1000&offset=0`)).toBe(true);
    expect(calls[0].headers.apikey).toBe(SECRET);
    // A new-style secret is not a JWT, so it is not sent as a bearer token.
    expect(calls[0].headers.authorization).toBeUndefined();
    expect(calls[0].method).toBe("GET");
  });

  it("quotes values inside in.(...) and encodes every value (keys hold |, spaces, # and quotes)", () => {
    expect(quoteValue('a|b "c"\\d')).toBe('"a|b \\"c\\"\\\\d"');
    const params = filterParams("doc_verdict", { keys: ["A1|CROSS-CHECK name#3", 'x"y'], dataEq: { verdict: "FLAG", "bad field": "x" }, scope: "A1" });
    const decoded = new URLSearchParams(params.join("&"));
    expect(decoded.get("key")).toBe('in.("A1|CROSS-CHECK name#3","x\\"y")');
    expect(decoded.get("data->>verdict")).toBe("eq.FLAG");
    expect(params.join("&")).not.toContain("bad field");
    expect(params.join("&")).toContain("%23");
  });

  it("maps every filter to PostgREST and re-checks the rows", () => {
    const params = filterParams("report", { scopePrefix: "stage_report:", keySuffix: "|summary", from: "2026-09-01", to: "2026-09-30", order: "day.desc" });
    const p = new URLSearchParams(params.join("&"));
    expect(p.get("scope")).toBe("like.stage_report:*");
    expect(p.get("key")).toBe("like.*|summary");
    expect(p.getAll("day")).toEqual(["gte.2026-09-01", "lte.2026-09-30"]);
    expect(p.get("order")).toBe("day.desc.nullslast,key.asc");
  });

  it("pages past PostgREST's 1,000-row cap until a short page", async () => {
    const many: HgRecord[] = Array.from({ length: 2_345 }, (_, i) => rec("doc_verdict", `A${String(i).padStart(8, "0")}|01 Passport`, { scope: "all" }));
    const { calls } = stubPostgrest(db({ records: many }));
    const rows = await readRecords("doc_verdict");
    expect(rows).toHaveLength(2_345);
    expect(calls.map((c) => c.params.get("offset"))).toEqual(["0", "1000", "2000"]);
    expect(new Set(rows.map((r) => r.key)).size).toBe(2_345);
  });

  it("splits a long key list into short requests", async () => {
    const keys = Array.from({ length: 120 }, (_, i) => `k${i}`);
    const { calls } = stubPostgrest(db());
    await readRecords("student", { keys });
    expect(calls).toHaveLength(3);
  });

  it("finds a student by HNG id, uid, passport, exact name, then every name token", async () => {
    const { calls } = stubPostgrest(db());
    expect((await findStudents({ hngId: "HNG-2026-012" })).map((r) => r.key)).toEqual(["101"]);
    expect((await findStudents({ uid: 102 })).map((r) => r.key)).toEqual(["102"]);
    expect((await findStudents({ passport: "A00000001" })).map((r) => r.key)).toEqual(["101"]);
    expect((await findStudents({ name: "test student two" })).map((r) => r.key)).toEqual(["102"]);
    expect((await findStudents({ name: "two test" })).map((r) => r.key)).toEqual(["102"]);
    const tokenCall = calls.at(-1)!;
    expect(tokenCall.params.get("and")).toBe("(student_name.ilike.*two*,student_name.ilike.*test*)");
    expect(calls.every((c) => c.params.get("kind") === "eq.student")).toBe(true);
  });
});

describe("fails closed with a plain reason", () => {
  it("times out after 3 s by default", async () => {
    expect(READ_TIMEOUT_MS).toBe(3_000);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    stubPostgrest(db(), () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    const error = await readRecords("student").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HangeulReadError);
    expect((error as HangeulReadError).message).toBe("Hangeul data unreachable (timeout)");
    expect(timeout).toHaveBeenCalledWith(3_000);
  });

  it.each([
    [() => new Response(JSON.stringify({ code: "PGRST205", message: "Could not find the table hg_records with TEST STUDENT" }), { status: 404 }), "Hangeul tables are missing (not migrated)", "not_migrated"],
    [() => new Response("{}", { status: 503 }), "Hangeul data unreachable (HTTP 503)", "unreachable"],
    [
      () => {
        throw new TypeError("fetch failed");
      },
      "Hangeul data unreachable (network error)",
      "unreachable",
    ],
  ])("maps a failure to a reason with no row data", async (respond, reason, code) => {
    stubPostgrest(db(), respond);
    const error = (await readRecords("student").catch((e: unknown) => e)) as HangeulReadError;
    expect(error.message).toBe(reason);
    expect(error.code).toBe(code);
    expect(error.message).not.toContain("TEST STUDENT");
  });

  it("refuses without configuration and never calls the network", async () => {
    clearSupabase();
    const { fetchMock } = stubPostgrest(db());
    const error = (await readRuns().catch((e: unknown) => e)) as HangeulReadError;
    expect(error.code).toBe("not_configured");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("runs, the as-of source", () => {
  it("reads the recent finished runs, and asks for the newest run of a kind none of them read", async () => {
    // 200 recent portal syncs push the backfill (the only run of field_correction) out of the recent window.
    const recent = Array.from({ length: 200 }, (_, i) => ({
      job: "portal_sync",
      started_at: `2026-09-30T1${Math.floor(i / 60)}:${String(i % 60).padStart(2, "0")}:00+00:00`,
      finished_at: `2026-09-30T1${Math.floor(i / 60)}:${String(i % 60).padStart(2, "0")}:30+00:00`,
      status: "ok" as const,
      byKind: { consultant_performance: [0, 0, 1] },
      failedReads: [],
    }));
    const backfill = runs().find((r) => r.job === "backfill")!;
    const { calls } = stubPostgrest(db({ runs: [...recent, backfill, { ...backfill, job: "old", finished_at: null, status: null }] }));
    const result = await readRuns(["consultant_performance", "field_correction", "brief_fact"]);
    expect(calls[0].params.get("finished_at")).toBe("not.is.null");
    expect(calls[0].params.get("status")).toBe("in.(ok,partial)");
    expect(calls[0].params.get("order")).toBe("finished_at.desc");
    expect(calls[0].params.get("limit")).toBe("200");
    // consultant_performance is in the recent runs; the other two need their own query.
    const extra = calls.slice(1).map((c) => c.params.get("counts->by_kind"));
    expect(extra).toEqual(['cs.{"field_correction":[]}', 'cs.{"brief_fact":[]}']);
    expect(result).toHaveLength(201);
    expect(result.at(-1)).toMatchObject({ job: "backfill" });
    expect(result.at(-1)?.byKind).toHaveProperty("field_correction");
    // An unfinished run is never an "as of".
    expect(result.some((r) => r.job === "old")).toBe(false);
  });
});

describe("change log", () => {
  const changes = Array.from({ length: 5 }, (_, i) => ({
    seq: i + 1,
    kind: "consultation",
    key: `${900 + i}`,
    op: "upsert" as const,
    changed_at: `2026-09-30T0${i}:00:00+00:00`,
  }));

  it("light rows since a time, keyset by seq", async () => {
    const { calls } = stubPostgrest(db({ changes }));
    const rows = await readChanges("2026-09-30T02:00:00.000Z");
    expect(rows.map((r) => r.seq)).toEqual([3, 4, 5]);
    expect(calls[0].params.get("changed_at")).toBe("gte.2026-09-30T02:00:00.000Z");
    expect(calls[0].params.get("seq")).toBe("gt.0");
  });

  it("device delta: current records, base64 vectors, deletes as kind/key/op/changed_at only", async () => {
    const withDelete = [
      ...changes.slice(0, 2),
      { seq: 6, kind: "notification", key: "gone", op: "delete" as const, changed_at: "2026-09-30T06:00:00+00:00" },
      { seq: 7, kind: "consultation", key: "deleted-later", op: "upsert" as const, changed_at: "2026-09-30T07:00:00+00:00" },
    ];
    const { calls } = stubPostgrest(db({ changes: withDelete }));
    const page = await readChangesSince(0, 200);
    expect(calls[0].path).toBe("/rest/v1/rpc/hg_changes_since");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({ p_seq: 0, p_limit: 200 });
    expect(page.changes.map((c) => c.seq)).toEqual([1, 2, 6, 7]);
    const [first, , del, later] = page.changes;
    expect(first.record?.key).toBe("900");
    expect(first.chunks).toHaveLength(1);
    expect(decodeVector(first.chunks![0].embedding)).toHaveLength(384);
    // A single chunk equal to the record's text is sent once.
    expect(first.chunks![0].content).toBeUndefined();
    expect(del).toEqual({ seq: 6, kind: "notification", key: "gone", op: "delete", changed_at: "2026-09-30T06:00:00+00:00" });
    expect(later).toMatchObject({ op: "upsert", record: null, chunks: null });
    expect(page).toMatchObject({ next_seq: 7, more: false });
  });

  it("reports more when the page is full and caps the limit at 1,000", async () => {
    const { calls } = stubPostgrest(db({ changes }));
    const page = await readChangesSince(0, 2);
    expect(page).toMatchObject({ next_seq: 2, more: true });
    await readChangesSince(0, 50_000);
    expect((calls[1].body as { p_limit: number }).p_limit).toBe(1_000);
  });
});

describe("snapshot paging", () => {
  function big(): FakeDb {
    // Enough OCR text that the student and page-text kinds need several ~3 MB pages.
    const students = Array.from({ length: 700 }, (_, i) =>
      rec("student", String(1000 + i), { student_uid: 1000 + i, student_name: `TEST STUDENT ${i}`, content: `Student TEST STUDENT ${i}. ${"x".repeat(1_500)}` }),
    );
    const pages = Array.from({ length: 400 }, (_, i) =>
      rec("doc_page_text", `A${String(i).padStart(8, "0")}|scan.pdf|p1`, { scope: `A${i}`, content: `Document scan.pdf, page 1:\n${"y".repeat(4_000)}` }),
    );
    const all = [...students, ...pages, rec("report", "missing_report|2026-09-30", { scope: "missing_report" })];
    return {
      records: all,
      chunks: all.flatMap((r, i) =>
        r.kind === "doc_page_text"
          ? [0, 1].map((ord) => ({ kind: r.kind, key: r.key, ord, content: `${r.content.slice(0, 30)} part ${ord}`, embedding: unit(i + ord), embed_model: MODEL }))
          : [{ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL }],
      ),
      runs: [],
      changes: [{ seq: 41, kind: "student", key: "1000", op: "upsert", changed_at: "2026-09-30T00:00:00+00:00" }],
    };
  }

  it("reads max_seq first, then walks every kind in keyset order within the byte budget", async () => {
    const data = big();
    const { calls } = stubPostgrest(data);
    const seen: string[] = [];
    let chunks = 0;
    let cursor: string | null = null;
    let pages = 0;
    do {
      const page = await readSnapshotPage(cursor);
      expect(page.max_seq).toBe(41);
      expect(JSON.stringify(page).length).toBeLessThan(4_500_000);
      seen.push(...page.records.map((r) => `${r.kind}|${r.key}`));
      chunks += page.chunks.length;
      for (const c of page.chunks) expect(decodeVector(c.embedding)).toHaveLength(384);
      cursor = page.next;
      pages++;
    } while (cursor && pages < 50);
    expect(calls[0].path).toBe("/rest/v1/hg_changes");
    expect(calls[0].params.get("order")).toBe("seq.desc");
    expect(pages).toBeGreaterThan(2);
    // Every record exactly once, and every chunk.
    expect(seen).toHaveLength(data.records.length);
    expect(new Set(seen).size).toBe(data.records.length);
    expect(chunks).toBe(data.chunks.length);
    // Kinds come in HG_KINDS order.
    const kindOrder = [...new Set(seen.map((s) => s.split("|")[0]))];
    expect(kindOrder).toEqual(HG_KINDS.filter((k) => kindOrder.includes(k)));
  });

  it("budgets pages in UTF-8 bytes, so Bangla or Korean OCR text stays under Vercel's cap", async () => {
    // 3 bytes a character: 400 pages of 4,000 Bangla characters are ~4.8 MB, in far fewer than 3 M characters.
    const pages = Array.from({ length: 400 }, (_, i) =>
      rec("doc_page_text", `A${String(i).padStart(8, "0")}|nid.pdf|p1`, { scope: `A${i}`, content: `Document nid.pdf, page 1:\n${"অ".repeat(4_000)}` }),
    );
    stubPostgrest({
      records: pages,
      chunks: pages.map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL })),
      runs: [],
      changes: [],
    });
    let cursor: string | null = null;
    let count = 0;
    let n = 0;
    do {
      const page = await readSnapshotPage(cursor);
      expect(new TextEncoder().encode(JSON.stringify(page)).length).toBeLessThan(4_500_000);
      count += page.records.length;
      cursor = page.next;
      n++;
    } while (cursor && n < 20);
    expect(n).toBeGreaterThan(1);
    expect(count).toBe(400);
  });

  it("stays stable when records are deleted between pages (keyset, not offsets)", async () => {
    const data = big();
    stubPostgrest(data);
    const first = await readSnapshotPage(null);
    // The bot deletes rows already sent; nothing still present may be skipped.
    const sent = new Set(first.records.map((r) => r.key));
    data.records = data.records.filter((r) => !(r.kind === "student" && sent.has(r.key) && Number(r.key) % 2 === 0));
    const seen = new Set(first.records.map((r) => `${r.kind}|${r.key}`));
    let cursor = first.next;
    while (cursor) {
      const page = await readSnapshotPage(cursor);
      for (const r of page.records) {
        expect(seen.has(`${r.kind}|${r.key}`)).toBe(false);
        seen.add(`${r.kind}|${r.key}`);
      }
      cursor = page.next;
    }
    for (const r of data.records) expect(seen.has(`${r.kind}|${r.key}`)).toBe(true);
  });

  it("rejects a cursor it did not issue", async () => {
    stubPostgrest(db());
    expect(await decodeCursor("not-a-cursor")).toBeNull();
    expect(await decodeCursor(await encodeCursor({ v: 1, s: 5, k: 2, a: "k|1" }))).toEqual({ v: 1, s: 5, k: 2, a: "k|1" });
    const error = (await readSnapshotPage("bm9wZQ").catch((e: unknown) => e)) as HangeulReadError;
    expect(error.message).toBe("invalid snapshot cursor");
  });

  it("seals the cursor: it goes out in a GET query string, so no record key can be read from it", async () => {
    // Keys of the kinds most pages end inside: a passport number and a file name that holds a student's name.
    const pages = Array.from({ length: 300 }, (_, i) =>
      rec("doc_page_text", `A${String(i).padStart(8, "0")}|TEST STUDENT ONE bank statement.pdf|p1`, { scope: `A${i}`, content: `Page:\n${"y".repeat(20_000)}` }),
    );
    stubPostgrest({ records: pages, chunks: pages.map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, content: r.content, embedding: unit(i), embed_model: MODEL })), runs: [], changes: [] });
    const issued: string[] = [];
    let cursor: string | null = null;
    do {
      const page = await readSnapshotPage(cursor);
      cursor = page.next;
      if (cursor) issued.push(cursor);
    } while (cursor && issued.length < 20);
    expect(issued.length).toBeGreaterThan(1);
    for (const c of issued) {
      const decoded = Buffer.from(c, "base64url").toString("latin1");
      for (const needle of ["A000", "TEST STUDENT", "bank statement", "|p1", '"a"', '"k"']) expect(decoded).not.toContain(needle);
      expect(() => JSON.parse(decoded)).toThrow();
    }
    // Two cursors for the same position differ (a fresh IV each time), and each still opens.
    const same = { v: 1 as const, s: 3, k: 20, a: "A00000001|x.pdf|p1" };
    const [one, two] = [await encodeCursor(same), await encodeCursor(same)];
    expect(one).not.toBe(two);
    expect(await decodeCursor(two)).toEqual(same);
  });

  it("refuses a cursor that was altered, sealed under another key, or in the old readable form", async () => {
    stubPostgrest(db());
    const cursor = await encodeCursor({ v: 1, s: 5, k: 2, a: "k|1" });
    const bytes = Buffer.from(cursor, "base64url");
    bytes[bytes.length - 1] ^= 1;
    expect(await decodeCursor(bytes.toString("base64url"))).toBeNull();
    const readable = Buffer.from(JSON.stringify({ v: 1, s: 5, k: 2, a: "k|1" })).toString("base64url");
    expect(await decodeCursor(readable)).toBeNull();
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_another_key");
    expect(await decodeCursor(cursor)).toBeNull();
    const error = (await readSnapshotPage(cursor).catch((e: unknown) => e)) as HangeulReadError;
    expect(error.message).toBe("invalid snapshot cursor");
  });

  it("reads chunks 100 at a time (content and vector together are slow in bulk)", async () => {
    const { calls } = stubPostgrest(big());
    await readSnapshotPage(null);
    const chunkCalls = calls.filter((c) => c.path === "/rest/v1/hg_chunks");
    expect(chunkCalls.length).toBeGreaterThan(0);
    for (const c of chunkCalls) expect(c.params.get("limit")).toBe("100");
    const recordCalls = calls.filter((c) => c.path === "/rest/v1/hg_records");
    for (const c of recordCalls) expect(Number(c.params.get("limit"))).toBeLessThanOrEqual(200);
  });

  it("ends a page inside its time budget, and the pages still cover every record once", async () => {
    const data = big();
    let clock = 0;
    // Every request takes 7 s: a page starts no batch after 30 s, so it ends well inside the route's 60 s.
    stubPostgrest(data, () => {
      clock += 7_000;
      return null;
    });
    const seen = new Set<string>();
    let cursor: string | null = null;
    let pages = 0;
    do {
      clock = 0;
      const page = await readSnapshotPage(cursor, { now: () => clock });
      expect(clock).toBeLessThanOrEqual(60_000);
      for (const r of page.records) {
        expect(seen.has(`${r.kind}|${r.key}`)).toBe(false);
        seen.add(`${r.kind}|${r.key}`);
      }
      cursor = page.next;
      pages++;
    } while (cursor && pages < 100);
    expect(seen.size).toBe(data.records.length);
  });

  it("a batch that times out after others were gathered ends the page with those; the next page resumes", async () => {
    const data = big();
    let chunkCalls = 0;
    stubPostgrest(data, (call) => {
      if (call.path === "/rest/v1/hg_chunks" && ++chunkCalls === 4) throw new DOMException("slow", "TimeoutError");
      return null;
    });
    const first = await readSnapshotPage(null);
    expect(first.records.length).toBeGreaterThan(0);
    expect(first.next).not.toBeNull();
    const seen = new Set(first.records.map((r) => `${r.kind}|${r.key}`));
    let cursor = first.next;
    while (cursor) {
      const page = await readSnapshotPage(cursor);
      for (const r of page.records) seen.add(`${r.kind}|${r.key}`);
      cursor = page.next;
    }
    expect(seen.size).toBe(data.records.length);
    // With nothing gathered yet, a timeout is the plain reason.
    stubPostgrest(data, (call) => {
      if (call.path === "/rest/v1/hg_records") throw new DOMException("slow", "TimeoutError");
      return null;
    });
    const error = (await readSnapshotPage(null).catch((e: unknown) => e)) as HangeulReadError;
    expect(error.message).toBe("Hangeul data unreachable (timeout)");
  });

  it("a body that stops arriving is a timeout with its reason, not a bare 'unreachable'", async () => {
    stubPostgrest(db(), (call) =>
      call.path === "/rest/v1/hg_records"
        ? new Response(
            new ReadableStream({
              start(controller) {
                controller.enqueue(new TextEncoder().encode("[{"));
                controller.error(new DOMException("The operation timed out.", "TimeoutError"));
              },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          )
        : null,
    );
    const error = (await readRecords("student").catch((e: unknown) => e)) as HangeulReadError;
    expect(error).toBeInstanceOf(HangeulReadError);
    expect(error.message).toBe("Hangeul data unreachable (timeout)");
  });
});

describe("search and status", () => {
  it("embeds a question through hg-embed, and fails closed while it is not deployed", async () => {
    stubPostgrest(db(), (call) => (call.url === `${URL_BASE}/functions/v1/hg-embed` ? new Response("not found", { status: 404 }) : null));
    const error = (await embedQuestion(["hello"]).catch((e: unknown) => e)) as HangeulReadError;
    expect(error.message).toBe("search not available (embedding function not deployed)");

    const { calls } = stubPostgrest(db(), (call) =>
      call.url === `${URL_BASE}/functions/v1/hg-embed` ? Response.json({ embeddings: [unit(3)] }) : null,
    );
    expect(await embedQuestion(["hello"])).toEqual([unit(3)]);
    // hg-embed's contract: an sb_secret_ key in apikey only (a legacy JWT would also go as the bearer).
    expect(calls[0].headers.apikey).toBe(SECRET);
    expect(calls[0].headers.authorization).toBeUndefined();
    expect(calls[0].body).toEqual({ texts: ["hello"] });
    // Within its limits: 2,000 characters a text.
    await embedQuestion(["x".repeat(5_000)]);
    expect((calls[1].body as { texts: string[] }).texts[0]).toHaveLength(2_000);
  });

  it("calls hg_match with the vector and filters", async () => {
    const { calls } = stubPostgrest(db({ hits: [{ kind: "student", key: "101", ord: 0, content: "x", similarity: 0.9, data: {}, day: null, read_at: "t", student_uid: 101, student_hng_id: null, student_name: "TEST STUDENT ONE" }] }));
    const hits = await createHangeulStore().match!(unit(1), { kinds: ["student"], studentUid: 101, count: 500 });
    expect(hits[0]).toMatchObject({ kind: "student", key: "101", similarity: 0.9 });
    expect(calls[0].body).toMatchObject({ p_count: 100, p_kinds: ["student"], p_student_uid: 101, p_day_from: null });
    expect((calls[0].body as { p_embedding: number[] }).p_embedding).toHaveLength(384);
  });

  it("counts records from Content-Range and summarises the latest run per job and the latest reports", async () => {
    stubPostgrest(db());
    expect(await countRecords()).toBe(records().length);
    const status = await readDataStatus();
    expect(status.records).toBe(records().length);
    expect(status.lastRuns.map((r) => r.job)).toEqual(["portal_sync", "passport_watcher", "full_picture", "backfill"]);
    expect(status.latestBrief).toBeNull();
    expect(status.latestReport).toMatchObject({ key: "missing_report|2026-09-30", report: "missing_report", day: "2026-09-30" });
  });
});
