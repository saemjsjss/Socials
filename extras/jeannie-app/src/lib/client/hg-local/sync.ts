// Keeping the device copy current (spec D9, D13, D14, §6).
//
// First sync: GET /api/hangeul/snapshot, then ?cursor=<next> until next is
// null, one IndexedDB transaction per page with its cursor, so a first sync cut
// short resumes where it stopped. The first page's max_seq is where the change
// log starts. After that: GET /api/hangeul/runs (what dates the device's "as of"
// lines), then GET /api/hangeul/changes?since=<max_seq> while `more`. An upsert
// replaces the record and all its chunks; a delete drops both.
//
// Pure: the transport (fetch with the access key) and the store (IndexedDB)
// are injected, so the tests drive it with a fake feed and a Map. `allowed`
// (device.ts) is read before every request and write: a copy deleted in any
// tab is never downloaded again by a sync that started before.

// The wire formats are the server's own (ticket 4, "Wire formats"); type-only, so nothing server-side is bundled.
import type { ChangesPage, SnapshotPage, WireChange, WireChunk } from "@/lib/hangeul/store";
import type { HgRecord, HgRun } from "@/lib/hangeul/types";
import { decodeVector, EMBEDDING_DIMENSIONS } from "@/lib/hangeul/vectors";
import type { HgLocalStore, LocalChunk, LocalOp } from "./db";

export type { ChangesPage, SnapshotPage, WireChange, WireChunk };

/** How the sync reaches the server: the HUD's fetch with the access key, or a fake feed in the tests. */
export interface HgTransport {
  snapshot(cursor: string | null, signal?: AbortSignal): Promise<SnapshotPage>;
  changes(since: number, signal?: AbortSignal): Promise<ChangesPage>;
  runs(signal?: AbortSignal): Promise<HgRun[]>;
}

export interface SyncProgress {
  phase: "snapshot" | "changes";
  /** Pages applied in this sync. */
  pages: number;
  /** Records written in this sync (snapshot) or changes applied (delta). */
  records: number;
  chunks: number;
}

export interface SyncOptions {
  signal?: AbortSignal;
  now?: () => Date;
  onProgress?: (progress: SyncProgress) => void;
  /** Most change pages one sync reads; the rest waits for the next sync (default 100). */
  maxChangePages?: number;
  /**
   * Read before the sync starts and before each request and write: false (the
   * copy was deleted, maybe in another tab) stops it with an AbortError, so a
   * sync never downloads a deleted copy again.
   */
  allowed?: () => boolean;
}

export interface SyncOutcome {
  /** A first sync ran (fully) in this call. */
  firstSync: boolean;
  snapshotPages: number;
  records: number;
  upserts: number;
  deletes: number;
  /** The log had more than maxChangePages: the copy is not caught up yet. */
  behind: boolean;
  maxSeq: number;
}

/** A sync failed on data it could not use (never a network error: those come from the transport). */
export class HgSyncError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HgSyncError";
  }
}

const refKey = (kind: string, key: string) => `${kind}\u0000${key}`;

/** Cancelled, or the copy was turned off (in any tab): stop before the next request or write. */
function stopIfAsked(options: SyncOptions): void {
  if (options.signal?.aborted) throw new DOMException("Sync cancelled", "AbortError");
  if (options.allowed && !options.allowed()) throw new DOMException("The device copy is turned off", "AbortError");
}

function isRecord(value: unknown): value is HgRecord {
  if (!value || typeof value !== "object") return false;
  const r = value as Partial<HgRecord>;
  return typeof r.kind === "string" && typeof r.key === "string" && typeof r.content === "string" && typeof r.read_at === "string";
}

/** Wire chunks of one record → device chunks (decoded vectors, the record's day and student). */
export function localChunks(wire: readonly WireChunk[], record: HgRecord): LocalChunk[] {
  return wire.map((c) => {
    let embedding: Float32Array;
    try {
      embedding = decodeVector(c.embedding);
    } catch {
      throw new HgSyncError("a stored vector could not be read");
    }
    if (embedding.length !== EMBEDDING_DIMENSIONS) throw new HgSyncError("a stored vector is not 384 numbers");
    const chunk: LocalChunk = {
      kind: record.kind,
      key: record.key,
      ord: Number(c.ord) || 0,
      embedding,
      embed_model: String(c.embed_model ?? ""),
      day: record.day ?? null,
      student_uid: record.student_uid ?? null,
    };
    if (typeof c.content === "string" && c.content !== record.content) chunk.content = c.content;
    return chunk;
  });
}

function snapshotOps(page: SnapshotPage): { ops: LocalOp[]; chunks: number; model: string | null } {
  const byRecord = new Map<string, WireChunk[]>();
  for (const c of page.chunks) {
    const id = refKey(c.kind, c.key);
    const list = byRecord.get(id);
    if (list) list.push(c);
    else byRecord.set(id, [c]);
  }
  const ops: LocalOp[] = [];
  let chunks = 0;
  for (const record of page.records) {
    if (!isRecord(record)) throw new HgSyncError("the snapshot returned a malformed record");
    const own = localChunks(byRecord.get(refKey(record.kind, record.key)) ?? [], record);
    chunks += own.length;
    ops.push({ op: "upsert", record, chunks: own });
  }
  return { ops, chunks, model: page.chunks[0]?.embed_model ?? null };
}

function checkSnapshotPage(page: unknown): SnapshotPage {
  const p = page as Partial<SnapshotPage> | null;
  if (!p || !Array.isArray(p.records) || !Array.isArray(p.chunks) || typeof p.max_seq !== "number" || !(p.next === null || typeof p.next === "string")) {
    throw new HgSyncError("the snapshot returned malformed data");
  }
  return p as SnapshotPage;
}

function checkChangesPage(page: unknown, since: number): ChangesPage {
  const p = page as Partial<ChangesPage> | null;
  if (!p || !Array.isArray(p.changes) || typeof p.next_seq !== "number" || typeof p.more !== "boolean" || p.next_seq < since) {
    throw new HgSyncError("the change log returned malformed data");
  }
  return p as ChangesPage;
}

/** The ops for one page of the change log, in seq order. */
export function changeOps(changes: readonly WireChange[]): { ops: LocalOp[]; upserts: number; deletes: number } {
  const ops: LocalOp[] = [];
  let upserts = 0;
  let deletes = 0;
  for (const change of [...changes].sort((a, b) => a.seq - b.seq)) {
    if (change.op === "delete") {
      ops.push({ op: "delete", kind: change.kind, key: change.key });
      deletes++;
    } else if (change.record) {
      if (!isRecord(change.record)) throw new HgSyncError("the change log returned a malformed record");
      ops.push({ op: "upsert", record: change.record, chunks: localChunks(change.chunks ?? [], change.record) });
      upserts++;
    }
    // An upsert whose record is null was deleted since: its delete follows in the feed.
  }
  return { ops, upserts, deletes };
}

/** The server no longer opens this cursor (it is sealed with the server's key, which may have been rotated). */
function isInvalidCursor(error: unknown): boolean {
  const e = error as { status?: unknown; code?: unknown } | null;
  return !!e && typeof e === "object" && e.status === 400 && e.code === "invalid_cursor";
}

/** Pages through the snapshot into the store (resuming a first sync cut short). No-op when the copy is complete. */
export async function runFirstSync(store: HgLocalStore, transport: HgTransport, options: SyncOptions = {}): Promise<{ pages: number; records: number; maxSeq: number }> {
  const now = options.now ?? (() => new Date());
  stopIfAsked(options);
  const meta = await store.meta();
  if (meta.complete && meta.max_seq !== null) return { pages: 0, records: 0, maxSeq: meta.max_seq };
  let cursor = meta.snapshot_next;
  let seq = cursor ? meta.snapshot_seq : null;
  // A fresh start: nothing half-written from an earlier attempt may stay behind.
  stopIfAsked(options);
  if (!cursor) await store.clear();
  let pages = 0;
  let records = 0;
  let chunks = 0;
  let restarted = false;
  for (;;) {
    stopIfAsked(options);
    let raw: SnapshotPage;
    try {
      raw = await transport.snapshot(cursor, options.signal);
    } catch (error) {
      // A saved cursor the server refuses would stop every later sync: start the first sync over, once.
      if (cursor && !restarted && isInvalidCursor(error)) {
        restarted = true;
        await store.clear();
        cursor = null;
        seq = null;
        pages = 0;
        records = 0;
        chunks = 0;
        continue;
      }
      throw error;
    }
    const page = checkSnapshotPage(raw);
    stopIfAsked(options);
    if (seq === null) seq = page.max_seq;
    const built = snapshotOps(page);
    const last = page.next === null;
    await store.write({
      ops: built.ops,
      meta: {
        snapshot_next: page.next,
        snapshot_seq: seq,
        ...(built.model ? { embed_model: built.model } : {}),
        ...(last ? { complete: true, max_seq: seq, synced_at: now().toISOString(), snapshot_next: null } : {}),
      },
    });
    pages++;
    records += built.ops.length;
    chunks += built.chunks;
    options.onProgress?.({ phase: "snapshot", pages, records, chunks });
    if (last) return { pages, records, maxSeq: seq };
    cursor = page.next;
  }
}

/** Applies the change log after the copy's max_seq (looping while `more`, up to maxChangePages). */
export async function runDelta(
  store: HgLocalStore,
  transport: HgTransport,
  options: SyncOptions = {},
): Promise<{ pages: number; upserts: number; deletes: number; behind: boolean; maxSeq: number }> {
  const now = options.now ?? (() => new Date());
  stopIfAsked(options);
  const meta = await store.meta();
  if (!meta.complete || meta.max_seq === null) throw new HgSyncError("the device copy has no first sync yet");
  const limit = options.maxChangePages ?? 100;
  let since = meta.max_seq;
  let pages = 0;
  let upserts = 0;
  let deletes = 0;
  let more = true;
  while (more && pages < limit) {
    stopIfAsked(options);
    const page = checkChangesPage(await transport.changes(since, options.signal), since);
    stopIfAsked(options);
    const built = changeOps(page.changes);
    more = page.more;
    await store.write({ ops: built.ops, meta: { max_seq: page.next_seq, ...(more ? {} : { synced_at: now().toISOString() }) } });
    pages++;
    upserts += built.upserts;
    deletes += built.deletes;
    since = page.next_seq;
    options.onProgress?.({ phase: "changes", pages, records: upserts + deletes, chunks: 0 });
    // A page that moved nothing while claiming more would loop forever.
    if (more && page.changes.length === 0) break;
  }
  return { pages, upserts, deletes, behind: more, maxSeq: since };
}

/**
 * One sync: the first sync if the copy is not complete, then the runs, then the
 * change log. The runs are read BEFORE the changes, so every run the device
 * dates an answer by has all its changes in the log it then applies.
 */
export async function syncOnce(store: HgLocalStore, transport: HgTransport, options: SyncOptions = {}): Promise<SyncOutcome> {
  const now = options.now ?? (() => new Date());
  stopIfAsked(options);
  const before = await store.meta();
  let snapshotPages = 0;
  let records = 0;
  const firstSync = !before.complete;
  if (firstSync) {
    const first = await runFirstSync(store, transport, options);
    snapshotPages = first.pages;
    records = first.records;
  }
  stopIfAsked(options);
  const runs = await transport.runs(options.signal);
  if (!Array.isArray(runs)) throw new HgSyncError("the runs returned malformed data");
  stopIfAsked(options);
  await store.write({ ops: [], meta: { runs, runs_at: now().toISOString() } });
  const delta = await runDelta(store, transport, options);
  return { firstSync, snapshotPages, records, upserts: delta.upserts, deletes: delta.deletes, behind: delta.behind, maxSeq: delta.maxSeq };
}

// ─── Mobile data ────────────────────────────────────────────────────────────

/** What the Network Information API says (Chrome on Android has it; Safari does not). */
export interface ConnectionHint {
  type?: string;
  saveData?: boolean;
}

/**
 * The first sync is tens of MB (the OCR text) plus the search model: ask before
 * starting it on mobile data. When the browser cannot tell (no connection
 * type), a phone asks too.
 */
export function firstSyncNeedsConsent(connection: ConnectionHint | null | undefined, phone: boolean): boolean {
  if (connection?.saveData) return true;
  const type = connection?.type;
  if (type === "cellular") return true;
  if (type === "wifi" || type === "ethernet") return false;
  return type === undefined || type === "unknown" ? phone : false;
}
