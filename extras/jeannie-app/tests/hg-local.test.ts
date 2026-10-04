// Ticket 7: the device copy (src/lib/client/hg-local/). Synthetic data only
// (tests/hangeul-fixtures.ts), a fake snapshot/changes feed, no network, no
// model: the store is the in-memory Map and, for the same suite, the real
// IndexedDB code over the in-memory shim (tests/idb-shim.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isMistakeAudit } from "@/lib/agents/audit-flow";
import { routeQuery } from "@/lib/agents/orchestrator";
import { prepareHangeul, copyIsFresh, FRESH_MS, routesToHangeul, type DeviceCopy } from "@/lib/client/hg-local/ask";
import { checkEmbedModel, MODEL_CHECK_MIN, pickCheckSamples } from "@/lib/client/hg-local/check";
import { createMemoryStore, openIndexedDbStore, type HgLocalStore, type LocalChunk } from "@/lib/client/hg-local/db";
import { buildIndex, hitRecords, searchIndex } from "@/lib/client/hg-local/search";
import { firstSyncNeedsConsent, HgSyncError, runDelta, runFirstSync, syncOnce, type HgTransport, type WireChange, type WireChunk } from "@/lib/client/hg-local/sync";
import { planFor, renderAnswer, runPlan } from "@/lib/hangeul/answer";
import { readersFromRecords } from "@/lib/hangeul/memory-readers";
import type { HgRecord, HgRun } from "@/lib/hangeul/types";
import { decodeVector, encodeVector } from "@/lib/hangeul/vectors";
import { NOW, rec, records, runs, TZ } from "./hangeul-fixtures";
import { unit } from "./hangeul-postgrest";
import { compareKeys, fakeIndexedDb, FakeKeyRange } from "./idb-shim";

const MODEL = "thenlper/gte-small@test";
const MAX_SEQ = 500;
const BANK = "A00000001|08 Bank Solvency & Statement";

/** Each fixture record gets its own unit vector; the bank statement verdict has a second chunk. */
function vectorOf(i: number): number[] {
  return unit(i);
}

function wireChunks(all: HgRecord[]): WireChunk[] {
  const out: WireChunk[] = [];
  all.forEach((r, i) => {
    out.push({ kind: r.kind, key: r.key, ord: 0, embedding: encodeVector(vectorOf(i)), embed_model: MODEL });
    if (r.key === BANK) out.push({ kind: r.kind, key: r.key, ord: 1, content: "Page 2: opening balance 12,000.00 BDT", embedding: encodeVector(unit(300)), embed_model: MODEL });
  });
  return out;
}

interface Feed {
  transport: HgTransport;
  calls: string[];
  changes: WireChange[];
  all: HgRecord[];
  runs: HgRun[];
  failSnapshotAt?: number;
}

/** A fake server: the snapshot in pages of `pageSize`, the change log in pages of `changePage`. */
function feed(pageSize = 7, changePage = 2): Feed {
  const all = records();
  const chunks = wireChunks(all);
  const state: Feed = { transport: null as unknown as HgTransport, calls: [], changes: [], all, runs: runs() };
  state.transport = {
    snapshot: async (cursor) => {
      state.calls.push(`snapshot:${cursor ?? "first"}`);
      const start = cursor ? Number(cursor) : 0;
      if (state.failSnapshotAt !== undefined && start >= state.failSnapshotAt) throw new Error("network down");
      const page = all.slice(start, start + pageSize);
      const keys = new Set(page.map((r) => `${r.kind}|${r.key}`));
      return {
        max_seq: MAX_SEQ,
        records: structuredClone(page),
        chunks: chunks.filter((c) => keys.has(`${c.kind}|${c.key}`)),
        next: start + pageSize < all.length ? String(start + pageSize) : null,
      };
    },
    changes: async (since) => {
      state.calls.push(`changes:${since}`);
      const after = state.changes.filter((c) => c.seq > since).sort((a, b) => a.seq - b.seq);
      const page = after.slice(0, changePage);
      return { changes: structuredClone(page), next_seq: page.length ? page[page.length - 1].seq : since, more: after.length > changePage };
    },
    runs: async () => {
      state.calls.push("runs");
      return structuredClone(state.runs);
    },
  };
  return state;
}

const idb = fakeIndexedDb();

const STORES: [string, () => Promise<HgLocalStore>][] = [
  ["in-memory store", async () => createMemoryStore()],
  ["IndexedDB (in-memory shim)", async () => openIndexedDbStore(fakeIndexedDb().indexedDB)],
];

beforeEach(() => {
  vi.stubGlobal("IDBKeyRange", FakeKeyRange);
  vi.stubGlobal("indexedDB", idb.indexedDB);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const minuteAgo = () => new Date(NOW.getTime() - 60_000);

describe.each(STORES)("sync (%s)", (_name, open) => {
  it("pages the snapshot into the store, keeps the first page's max_seq and completes", async () => {
    const store = await open();
    const f = feed();
    const progress: number[] = [];
    const first = await runFirstSync(store, f.transport, { now: minuteAgo, onProgress: (p) => progress.push(p.records) });
    const pages = Math.ceil(f.all.length / 7);
    expect(first).toEqual({ pages, records: f.all.length, maxSeq: MAX_SEQ });
    expect(f.calls[0]).toBe("snapshot:first");
    expect(f.calls).toHaveLength(pages);
    expect(progress).toEqual(Array.from({ length: pages }, (_, i) => Math.min(f.all.length, (i + 1) * 7)));
    const meta = await store.meta();
    expect(meta).toMatchObject({ complete: true, max_seq: MAX_SEQ, snapshot_next: null, embed_model: MODEL, synced_at: minuteAgo().toISOString() });
    expect(await store.counts()).toEqual({ records: f.all.length, chunks: f.all.length + 1 });
    // A chunk whose text is its record's keeps no copy of it; vectors come back as Float32Array.
    const chunks = await store.chunks();
    const bank = chunks.filter((c) => c.key === BANK).sort((a, b) => a.ord - b.ord);
    expect(bank.map((c) => c.content)).toEqual([undefined, "Page 2: opening balance 12,000.00 BDT"]);
    expect(bank[0].embedding).toBeInstanceOf(Float32Array);
    expect(bank[0].student_uid).toBe(101);
    const students = await store.recordsOfKind("student");
    expect(students.map((r) => r.key)).toEqual(["101", "102", "103"]);
    // A second call does nothing: the copy is complete.
    expect(await runFirstSync(store, f.transport)).toEqual({ pages: 0, records: 0, maxSeq: MAX_SEQ });
  });

  it("resumes a first sync cut short at its saved cursor", async () => {
    const store = await open();
    const f = feed();
    f.failSnapshotAt = 14;
    await expect(runFirstSync(store, f.transport)).rejects.toThrow("network down");
    const half = await store.meta();
    expect(half).toMatchObject({ complete: false, snapshot_next: "14", snapshot_seq: MAX_SEQ, max_seq: null });
    expect((await store.counts()).records).toBe(14);
    f.failSnapshotAt = undefined;
    f.calls.length = 0;
    await runFirstSync(store, f.transport);
    expect(f.calls[0]).toBe("snapshot:14");
    expect(await store.meta()).toMatchObject({ complete: true, max_seq: MAX_SEQ });
    expect((await store.counts()).records).toBe(f.all.length);
  });

  it("applies upserts and deletes from the change log, in seq order, across pages", async () => {
    const store = await open();
    const f = feed();
    await runFirstSync(store, f.transport);
    const bank = f.all.find((r) => r.key === BANK) as HgRecord;
    const pending = f.all.find((r) => r.kind === "pending_payment") as HgRecord;
    const calendar = f.all.find((r) => r.kind === "calendar_item") as HgRecord;
    const changed = { ...bank, data: { ...bank.data, verdict: "PASS" }, content: "doc_verdict bank statement, now PASS" };
    const recreated = { ...calendar, data: { ...calendar.data, title: "TEST UNIVERSITY second round" } };
    const newcomer = rec("student", "104", { student_uid: 104, student_name: "TEST STUDENT SEVEN", student_hng_id: "HNG-2026-932" });
    f.changes = [
      // The bank statement changed: one chunk now (the old second chunk must go).
      { seq: 501, kind: "doc_verdict", key: BANK, op: "upsert", changed_at: "2026-09-30T11:00:00Z", record: changed, chunks: [{ kind: "doc_verdict", key: BANK, ord: 0, embedding: encodeVector(unit(301)), embed_model: MODEL }] },
      { seq: 502, kind: "pending_payment", key: pending.key, op: "delete", changed_at: "2026-09-30T11:01:00Z" },
      // Added, then deleted before this device synced: the upsert carries no record, the delete follows.
      { seq: 503, kind: "student", key: "999", op: "upsert", changed_at: "2026-09-30T11:02:00Z", record: null, chunks: null },
      { seq: 504, kind: "student", key: "999", op: "delete", changed_at: "2026-09-30T11:03:00Z" },
      // Deleted, then created again: it must be there at the end.
      { seq: 505, kind: "calendar_item", key: calendar.key, op: "delete", changed_at: "2026-09-30T11:04:00Z" },
      { seq: 506, kind: "calendar_item", key: calendar.key, op: "upsert", changed_at: "2026-09-30T11:05:00Z", record: recreated, chunks: [{ kind: "calendar_item", key: calendar.key, ord: 0, embedding: encodeVector(unit(302)), embed_model: MODEL }] },
      { seq: 507, kind: "student", key: "104", op: "upsert", changed_at: "2026-09-30T11:06:00Z", record: newcomer, chunks: [{ kind: "student", key: "104", ord: 0, embedding: encodeVector(unit(303)), embed_model: MODEL }] },
    ];
    const delta = await runDelta(store, f.transport, { now: minuteAgo });
    expect(delta).toEqual({ pages: 4, upserts: 3, deletes: 3, behind: false, maxSeq: 507 });
    expect(f.calls.filter((c) => c.startsWith("changes:"))).toEqual(["changes:500", "changes:502", "changes:504", "changes:506"]);

    const [nowBank] = await store.getRecords([{ kind: "doc_verdict", key: BANK }]);
    expect(nowBank.data.verdict).toBe("PASS");
    const bankChunks = (await store.chunks()).filter((c) => c.key === BANK);
    expect(bankChunks).toHaveLength(1);
    expect(Array.from(bankChunks[0].embedding)).toEqual(unit(301));
    expect(await store.recordsOfKind("pending_payment")).toEqual([]);
    expect((await store.chunks()).some((c) => c.kind === "pending_payment")).toBe(false);
    expect((await store.getRecords([{ kind: "student", key: "999" }])).length).toBe(0);
    expect((await store.getRecords([{ kind: "calendar_item", key: calendar.key }]))[0].data.title).toBe("TEST UNIVERSITY second round");
    expect((await store.recordsOfKind("student")).map((r) => r.key)).toEqual(["101", "102", "103", "104"]);
    expect(await store.meta()).toMatchObject({ max_seq: 507, synced_at: minuteAgo().toISOString() });
    expect(await store.counts()).toEqual({ records: f.all.length, chunks: f.all.length });

    // Nothing new: one call, nothing applied, the cursor stays.
    f.calls.length = 0;
    expect(await runDelta(store, f.transport)).toMatchObject({ pages: 1, upserts: 0, deletes: 0, maxSeq: 507 });
    expect(f.calls).toEqual(["changes:507"]);
  });

  it("reads the bot's runs before the change log, and keeps them with the copy", async () => {
    const store = await open();
    const f = feed(100);
    f.changes = [{ seq: 501, kind: "notification", key: "gone", op: "delete", changed_at: "2026-09-30T11:00:00Z" }];
    const outcome = await syncOnce(store, f.transport, { now: minuteAgo });
    expect(outcome).toMatchObject({ firstSync: true, snapshotPages: 1, records: f.all.length, deletes: 1, behind: false, maxSeq: 501 });
    expect(f.calls).toEqual(["snapshot:first", "runs", "changes:500"]);
    const meta = await store.meta();
    expect(meta.runs).toEqual(runs());
    expect(meta.runs_at).toBe(minuteAgo().toISOString());
    // The next sync: no snapshot, runs then changes again.
    f.calls.length = 0;
    await syncOnce(store, f.transport);
    expect(f.calls).toEqual(["runs", "changes:501"]);
  });

  it("fails closed on a malformed page and keeps its cursor", async () => {
    const store = await open();
    const f = feed(100);
    await runFirstSync(store, f.transport);
    const broken: HgTransport = { ...f.transport, changes: async () => ({ changes: "nope" }) as never };
    await expect(runDelta(store, broken)).rejects.toBeInstanceOf(HgSyncError);
    const badVector: HgTransport = {
      ...f.transport,
      changes: async () => ({
        changes: [{ seq: 501, kind: "student", key: "101", op: "upsert", changed_at: "x", record: f.all.find((r) => r.key === "101") ?? null, chunks: [{ kind: "student", key: "101", ord: 0, embedding: encodeVector([1, 2, 3]), embed_model: MODEL }] }],
        next_seq: 501,
        more: false,
      }),
    };
    await expect(runDelta(store, badVector)).rejects.toThrow("a stored vector is not 384 numbers");
    expect((await store.meta()).max_seq).toBe(MAX_SEQ);
  });

  it("keeps the FIRST page's max_seq even when later pages report a newer one", async () => {
    const store = await open();
    const f = feed();
    const moving: HgTransport = { ...f.transport, snapshot: async (cursor, signal) => ({ ...(await f.transport.snapshot(cursor, signal)), max_seq: cursor ? 900 : MAX_SEQ }) };
    expect((await runFirstSync(store, moving)).maxSeq).toBe(MAX_SEQ);
    expect((await store.meta()).max_seq).toBe(MAX_SEQ);
  });

  it("starts the first sync over when the server no longer opens its saved cursor (a rotated key)", async () => {
    const store = await open();
    const f = feed();
    f.failSnapshotAt = 14;
    await expect(runFirstSync(store, f.transport)).rejects.toThrow("network down");
    f.failSnapshotAt = undefined;
    const refused = Object.assign(new Error("cursor is not one this server issued."), { status: 400, code: "invalid_cursor" });
    // The saved cursor was sealed under the old key; the cursors issued after the restart open again.
    let stale = true;
    const rotated: HgTransport = {
      ...f.transport,
      snapshot: async (cursor, signal) => {
        if (cursor === "14" && stale) {
          stale = false;
          throw refused;
        }
        return f.transport.snapshot(cursor, signal);
      },
    };
    f.calls.length = 0;
    const first = await runFirstSync(store, rotated);
    expect(f.calls[0]).toBe("snapshot:first");
    expect(first.records).toBe(f.all.length);
    expect(await store.meta()).toMatchObject({ complete: true, max_seq: MAX_SEQ, snapshot_next: null });
    expect((await store.counts()).records).toBe(f.all.length);
    // Refused again after the restart: that is an error, not a loop.
    const always: HgTransport = { ...f.transport, snapshot: async (cursor) => (cursor ? Promise.reject(refused) : f.transport.snapshot(null)) };
    await store.write({ ops: [], meta: { complete: false, snapshot_next: "7", snapshot_seq: MAX_SEQ } });
    await expect(runFirstSync(store, always)).rejects.toBe(refused);
  });

  it("clear() removes every record, chunk and the sync state", async () => {
    const store = await open();
    await syncOnce(store, feed(100).transport);
    await store.clear();
    expect(await store.counts()).toEqual({ records: 0, chunks: 0 });
    expect(await store.meta()).toMatchObject({ complete: false, max_seq: null, runs: null, model_check: null });
  });
});

describe("IndexedDB key ranges (the shim follows the spec's key order)", () => {
  it("orders numbers before strings before arrays, and a prefix first", () => {
    expect(compareKeys(5, "a")).toBe(-1);
    expect(compareKeys("z", [])).toBe(-1);
    expect(compareKeys(["k", "a"], ["k", "a", 0])).toBe(-1);
    expect(compareKeys(["k", "a", 99], ["k", "a", []])).toBe(-1);
    expect(compareKeys(["k", "a|b"], ["k", "a"])).toBe(1);
  });
});

// ── Local search ─────────────────────────────────────────────────────────────

async function syncedStore(): Promise<{ store: HgLocalStore; f: Feed }> {
  const store = createMemoryStore();
  const f = feed(100);
  await syncOnce(store, f.transport, { now: minuteAgo });
  return { store, f };
}

function blend(a: number[], b: number[], wa: number): number[] {
  return a.map((x, i) => wa * x + (1 - wa) * b[i]);
}

describe("local search", () => {
  it("cosine search returns the right record", async () => {
    const { store, f } = await syncedStore();
    const index = buildIndex(await store.chunks());
    expect(index.size).toBe(f.all.length + 1);
    const bankAt = f.all.findIndex((r) => r.key === BANK);
    const otherAt = f.all.findIndex((r) => r.kind === "calendar_item");
    // A question close to the bank statement's vector, with a little of another record's.
    const query = blend(vectorOf(bankAt), vectorOf(otherAt), 0.8);
    const hits = searchIndex(index, query);
    expect(hits[0]).toMatchObject({ kind: "doc_verdict", key: BANK, ord: 0 });
    expect(hits[0].similarity).toBeGreaterThan(0.95);
    expect(hits[1]).toMatchObject({ kind: "calendar_item" });
    // The second chunk (page 2) is found by its own vector.
    expect(searchIndex(index, unit(300))[0]).toMatchObject({ key: BANK, ord: 1 });
    // Filters: kinds, the student, the day range.
    expect(searchIndex(index, query, { kinds: ["calendar_item"] })[0].kind).toBe("calendar_item");
    expect(searchIndex(index, query, { studentUid: 102 }).every((h) => h.key.startsWith("102|") || h.key === "102")).toBe(true);
    expect(searchIndex(index, vectorOf(otherAt), { from: "2026-10-01", to: "2026-10-31" })[0]).toMatchObject({ kind: "calendar_item" });
    expect(searchIndex(index, vectorOf(bankAt), { from: "2026-10-01" }).some((h) => h.key === BANK)).toBe(false);
  });

  it("sends the records near the best hit, one per record, at most five", () => {
    const hits = [
      { kind: "doc_verdict", key: "A", ord: 0, similarity: 0.95 },
      { kind: "doc_verdict", key: "A", ord: 1, similarity: 0.94 },
      { kind: "doc_page_text", key: "B", ord: 0, similarity: 0.93 },
      { kind: "doc_check", key: "C", ord: 0, similarity: 0.89 },
    ];
    expect(hitRecords(hits)).toEqual([
      { kind: "doc_verdict", key: "A" },
      { kind: "doc_page_text", key: "B" },
    ]);
    const many = Array.from({ length: 9 }, (_, i) => ({ kind: "doc_page_text", key: `K${i}`, ord: 0, similarity: 0.9 - i * 0.001 }));
    expect(hitRecords(many)).toHaveLength(5);
    expect(hitRecords([])).toEqual([]);
  });
});

// ── The embed-model check ────────────────────────────────────────────────────

/** A slightly different vector in the same direction (cosine ≈ 0.995), like a quantized model's. */
function nearly(v: Float32Array): number[] {
  const out = Array.from(v);
  out[(out.findIndex((x) => x !== 0) + 1) % out.length] += 0.1;
  return out;
}

/** A unit vector at exactly cosine `c` to the one-hot `v`: c along v, the rest along the next axis. */
function atCosine(v: Float32Array, c: number): number[] {
  const out = Array.from(v, (x) => x * c);
  out[(Array.from(v).findIndex((x) => x !== 0) + 1) % out.length] += Math.sqrt(1 - c * c);
  return out;
}

async function copyOf(store: HgLocalStore, embed: DeviceCopy["embed"]): Promise<DeviceCopy> {
  const meta = await store.meta();
  return { store, meta, index: async () => buildIndex(await store.chunks()), embed };
}

describe("embed-model check", () => {
  it("passes when the device's vectors match the stored ones", async () => {
    const { store } = await syncedStore();
    const samples = await pickCheckSamples(store, await store.chunks());
    expect(samples).toHaveLength(3);
    expect(new Set(samples.map((s) => s.text)).size).toBe(3);
    const result = await checkEmbedModel(samples, async () => samples.map((s) => nearly(s.embedding)), NOW);
    expect(result.status).toBe("ok");
    expect(result.min).toBeGreaterThanOrEqual(MODEL_CHECK_MIN);
    expect(result.at).toBe(NOW.toISOString());
  });

  it("a model mismatch falls back to the server, never to wrong hits", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { store, f } = await syncedStore();
    const samples = await pickCheckSamples(store, await store.chunks());
    const check = await checkEmbedModel(samples, async () => samples.map(() => unit(383)), NOW);
    expect(check.status).toBe("mismatch");
    expect(check.min).toBeLessThan(MODEL_CHECK_MIN);
    // The log line holds numbers only, no text.
    expect(warn).toHaveBeenCalledTimes(1);
    for (const s of samples) expect(String(warn.mock.calls[0][0])).not.toContain(s.text);
    await store.write({ ops: [], meta: { model_check: check } });

    const bankAt = f.all.findIndex((r) => r.key === BANK);
    const embed = vi.fn(async () => vectorOf(bankAt));
    const question = "What does HNG-2026-012's bank statement say about the opening balance?";
    const prepared = await prepareHangeul({ question, lang: "en", now: NOW, timeZone: TZ, copy: await copyOf(store, embed) });
    // To the server with no device vector and no device hits: it embeds and searches itself (hg-embed + hg_match).
    expect(prepared).toEqual({ mode: "server", reason: "model_not_ok", hints: null });
    expect(embed).not.toHaveBeenCalled();
  });

  it("with a passing check, the device's vector and hits go to the server", async () => {
    const { store, f } = await syncedStore();
    await store.write({ ops: [], meta: { model_check: { status: "ok", min: 0.995, scores: [0.995, 0.996, 0.997], at: NOW.toISOString() } } });
    const bankAt = f.all.findIndex((r) => r.key === BANK);
    const question = "What does HNG-2026-012's bank statement say about the opening balance?";
    const prepared = await prepareHangeul({ question, lang: "en", now: NOW, timeZone: TZ, copy: await copyOf(store, async () => vectorOf(bankAt)) });
    expect(prepared).toMatchObject({ mode: "server", reason: "device_search" });
    const hints = prepared?.mode === "server" ? prepared.hints : null;
    expect(Array.from(decodeVector(String(hints?.embedding)))).toEqual(vectorOf(bankAt));
    // Only that student's documents are searched (HNG-2026-012 is uid 101); the best one leads.
    expect(hints?.hits?.[0]).toEqual({ kind: "doc_verdict", key: BANK });
  });

  it("the floor is 0.98: a sample at cosine 0.97 fails the check, one at 0.985 passes", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(MODEL_CHECK_MIN).toBe(0.98);
    const { store } = await syncedStore();
    const samples = await pickCheckSamples(store, await store.chunks());
    const at = (c: number) => async () => samples.map((s) => atCosine(s.embedding, c));
    const low = await checkEmbedModel(samples, at(0.97), NOW);
    expect(low.status).toBe("mismatch");
    expect(low.min).toBeCloseTo(0.97, 4);
    const high = await checkEmbedModel(samples, at(0.985), NOW);
    expect(high.status).toBe("ok");
    expect(high.min).toBeCloseTo(0.985, 4);
  });

  it("a model that cannot load is 'unavailable' (checked again later), not a mismatch", async () => {
    const { store } = await syncedStore();
    const samples = await pickCheckSamples(store, await store.chunks());
    expect((await checkEmbedModel(samples, async () => Promise.reject(new Error("offline")))).status).toBe("unavailable");
    expect((await checkEmbedModel([], async () => [])).status).toBe("unavailable");
  });
});

// ── Answering from the device ────────────────────────────────────────────────

describe("answering from the device copy", () => {
  const ask = async (question: string, store: HgLocalStore, lang: "en" | "ko" = "en", now = NOW) =>
    prepareHangeul({ question, lang, now, timeZone: TZ, copy: await copyOf(store, null) });

  it("renders a structured plan with the same code, and the same text, as the server", async () => {
    const { store } = await syncedStore();
    const question = "how many consultancies were closed today?";
    const prepared = await ask(question, store);
    expect(prepared?.mode).toBe("local");
    const text = prepared?.mode === "local" ? prepared.text : "";
    expect(text).toContain("Consultancies done today (30 Sep): 20");
    expect(text).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    expect(text.trim().split("\n").at(-1)).toBe("As of 17:35 (full picture)");
    // The server over the same rows and runs.
    const plan = planFor(question, { today: "2026-09-30", now: NOW, timeZone: TZ });
    const server = await runPlan(plan, readersFromRecords({ records: records(), runs: runs() }), { now: NOW, timeZone: TZ });
    expect(text).toBe(renderAnswer(server, "en", { now: NOW, timeZone: TZ }));
    // Korean too.
    const ko = await ask("오늘 상담 몇 건 끝났어?", store, "ko");
    expect(ko?.mode === "local" ? ko.text : "").toContain("기준: 17:35 (전체 점검)");
  });

  it("sends to the server what the device must not answer", async () => {
    const { store } = await syncedStore();
    // The change log and the run table live on the server.
    expect(await ask("What changed since this morning?", store)).toMatchObject({ mode: "server", reason: "server_only" });
    // Nothing on the device may only mean the copy lags behind: the server confirms it.
    expect(await ask("Who is HNG-2026-933?", store)).toMatchObject({ mode: "server", reason: "nothing_local" });
    // Korean or Bangla searches are rewritten into English by the server's model first.
    await store.write({ ops: [], meta: { model_check: { status: "ok", min: 0.99, scores: [], at: NOW.toISOString() } } });
    expect(await ask("HNG-2026-012 은행 잔고 증명서 내용 알려줘", store, "ko")).toMatchObject({ mode: "server", reason: "rewrite", hints: null });
    // Not a Hangeul question at all: the chat handles it as usual.
    expect(await ask("What's the weather in Seoul?", store)).toBeNull();
  });

  it("leaves to the server what its router sends elsewhere first (smart-home, mistake audits)", async () => {
    const { store } = await syncedStore();
    const audit = "check the payment verification errors on the portal today";
    // The server's order: IoT, then the mistake audit, then Hangeul; the device keeps it.
    expect(isMistakeAudit(audit)).toBe(true);
    expect(routesToHangeul(audit)).toBe(false);
    expect(await ask(audit, store)).toBeNull();
    expect(routesToHangeul("Dim the living room lights to 40%")).toBe(false);
    expect(routesToHangeul("how many consultancies were closed today?")).toBe(true);
    // The device and the server agree on what is a Hangeul question.
    const questions = [
      audit,
      "Dim the living room lights to 40%",
      "how many consultancies were closed today?",
      "Hangeul daily report",
      "Any passport alerts today?",
      "Who is HNG-2026-913?",
      "오늘 상담 몇 건 끝났어?",
      "What are today's top AI news headlines?",
    ];
    for (const question of questions) {
      expect(routeQuery({ text: question, hasImage: false }).agent === "hangeul", question).toBe(routesToHangeul(question));
    }
  });

  it("answers only from a copy that caught up in the last few minutes, with the bot's runs", async () => {
    const { store } = await syncedStore();
    const later = new Date(NOW.getTime() + FRESH_MS + 1_000);
    expect(await ask("how many consultancies were closed today?", store, "en", later)).toMatchObject({ mode: "server", reason: "stale" });
    const meta = await store.meta();
    // Six minutes: the delta runs every five while the HUD is open. Pinned as a number, not FRESH_MS.
    const synced = new Date(meta.synced_at ?? "").getTime();
    expect(copyIsFresh(meta, new Date(synced + 6 * 60_000 - 1_000))).toBe(true);
    expect(copyIsFresh(meta, new Date(synced + 6 * 60_000 + 1_000))).toBe(false);
    expect(copyIsFresh(meta, NOW)).toBe(true);
    expect(copyIsFresh({ ...meta, runs: null }, NOW)).toBe(false);
    expect(copyIsFresh({ ...meta, complete: false }, NOW)).toBe(false);
    // No copy at all.
    expect(await prepareHangeul({ question: "how many consultancies were closed today?", lang: "en", now: NOW, timeZone: TZ, copy: null })).toMatchObject({
      mode: "server",
      reason: "no_copy",
    });
  });

  it("a copy that cannot be read goes to the server", async () => {
    const { store } = await syncedStore();
    const broken: HgLocalStore = { ...store, recordsOfKind: async () => Promise.reject(new Error("IndexedDB closed")) };
    expect(await ask("how many consultancies were closed today?", broken)).toMatchObject({ mode: "server", reason: "local_unavailable" });
  });
});

describe("first sync on mobile data", () => {
  it("asks first on cellular or data saver, and on a phone that cannot tell", () => {
    expect(firstSyncNeedsConsent({ type: "cellular" }, false)).toBe(true);
    expect(firstSyncNeedsConsent({ type: "wifi", saveData: true }, false)).toBe(true);
    expect(firstSyncNeedsConsent({ type: "wifi" }, true)).toBe(false);
    expect(firstSyncNeedsConsent({ type: "ethernet" }, true)).toBe(false);
    expect(firstSyncNeedsConsent(null, true)).toBe(true);
    expect(firstSyncNeedsConsent({}, true)).toBe(true);
    expect(firstSyncNeedsConsent(null, false)).toBe(false);
  });
});

describe("device chunks", () => {
  it("carry their record's day and student for filtering", async () => {
    const { store } = await syncedStore();
    const chunks: LocalChunk[] = await store.chunks();
    const alert = chunks.find((c) => c.kind === "passport_alert" && c.key.startsWith("102|"));
    expect(alert).toMatchObject({ day: "2026-09-30", student_uid: 102, embed_model: MODEL });
  });
});
