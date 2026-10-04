// The device copy of the Hangeul data (spec D9, §6): IndexedDB database
// "jeannie-hg" with three stores:
//
//   records  [kind, key]       → HgRecord (the hg_records row)
//   chunks   [kind, key, ord]  → LocalChunk ({content?, embedding: Float32Array, ...})
//   meta     name              → the sync state (max_seq, embed_model, synced_at, ...)
//
// Behind the HgLocalStore interface, so the sync and search code runs against
// an in-memory Map in the tests. Every write is one transaction: a page of the
// snapshot or of the change log lands whole, with its cursor, or not at all.
// Student data lives here and nowhere else on the device (never in the
// service worker's cache).

import type { HgRecord, HgRun } from "@/lib/hangeul/types";

export const HG_DB_NAME = "jeannie-hg";
const HG_DB_VERSION = 1;
const RECORDS = "records";
const CHUNKS = "chunks";
const META = "meta";

/** One embedded chunk on the device. */
export interface LocalChunk {
  kind: string;
  key: string;
  ord: number;
  /** Absent when it equals the record's content (as on the wire). */
  content?: string;
  /** gte-small, 384-d, L2-normalised. */
  embedding: Float32Array;
  embed_model: string;
  /** The record's day and student, copied here so a search can filter without reading records. */
  day: string | null;
  student_uid: number | null;
}

/** The on-device embed-model check (spec §6): stored vectors vs the device's own for the same texts. */
export interface ModelCheckResult {
  /** ok: device search is used; mismatch: server search (cosine below the floor); unavailable: the model did not load, try again later. */
  status: "ok" | "mismatch" | "unavailable";
  /** The lowest cosine of the samples (null when nothing was embedded). */
  min: number | null;
  scores: number[];
  /** ISO time of the check. */
  at: string;
}

export interface HgLocalMeta {
  /** The change-log seq the copy has applied: the snapshot's max_seq, then each delta's next_seq. */
  max_seq: number | null;
  /** The bot's embed_model string on the chunks (informational: the check compares vectors, never this string). */
  embed_model: string | null;
  /** When the copy last caught up with the server (first sync finished, or a delta with nothing more to fetch). ISO. */
  synced_at: string | null;
  /** The first sync finished. */
  complete: boolean;
  /** A first sync in progress: the next page's cursor and the first page's max_seq (so it resumes). */
  snapshot_next: string | null;
  snapshot_seq: number | null;
  /** Hangeul BOT's recent runs: what dates the "as of" line of an answer built on the device. */
  runs: HgRun[] | null;
  runs_at: string | null;
  model_check: ModelCheckResult | null;
}

export const EMPTY_META: HgLocalMeta = {
  max_seq: null,
  embed_model: null,
  synced_at: null,
  complete: false,
  snapshot_next: null,
  snapshot_seq: null,
  runs: null,
  runs_at: null,
  model_check: null,
};

const META_KEYS = Object.keys(EMPTY_META) as (keyof HgLocalMeta)[];

export interface RecordRef {
  kind: string;
  key: string;
}

/** Applied in order: an upsert replaces the record and ALL its chunks; a delete drops both. */
export type LocalOp = { op: "upsert"; record: HgRecord; chunks: readonly LocalChunk[] } | { op: "delete"; kind: string; key: string };

export interface HgLocalBatch {
  ops: readonly LocalOp[];
  meta?: Partial<HgLocalMeta>;
}

export interface HgLocalStore {
  meta(): Promise<HgLocalMeta>;
  /** One atomic write: the ops in order, then the meta patch. */
  write(batch: HgLocalBatch): Promise<void>;
  recordsOfKind(kind: string): Promise<HgRecord[]>;
  getRecords(refs: readonly RecordRef[]): Promise<HgRecord[]>;
  chunks(): Promise<LocalChunk[]>;
  counts(): Promise<{ records: number; chunks: number }>;
  /** Removes every record, chunk and meta entry ("Delete local copy", "Re-sync everything"). */
  clear(): Promise<void>;
}

const refKey = (kind: string, key: string) => `${kind}\u0000${key}`;

function byKeyOrder(a: { key: string }, b: { key: string }): number {
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

// ─── In memory (tests, and nothing else) ────────────────────────────────────

export function createMemoryStore(): HgLocalStore {
  const records = new Map<string, HgRecord>();
  const chunks = new Map<string, LocalChunk[]>();
  let meta: HgLocalMeta = { ...EMPTY_META };
  return {
    meta: async () => ({ ...meta }),
    write: async (batch) => {
      for (const op of batch.ops) {
        if (op.op === "upsert") {
          const id = refKey(op.record.kind, op.record.key);
          records.set(id, structuredClone(op.record));
          chunks.set(id, [...op.chunks].sort((a, b) => a.ord - b.ord));
        } else {
          records.delete(refKey(op.kind, op.key));
          chunks.delete(refKey(op.kind, op.key));
        }
      }
      if (batch.meta) meta = { ...meta, ...batch.meta };
    },
    recordsOfKind: async (kind) => [...records.values()].filter((r) => r.kind === kind).sort(byKeyOrder),
    getRecords: async (refs) => refs.flatMap((r) => records.get(refKey(r.kind, r.key)) ?? []),
    chunks: async () => [...chunks.values()].flat(),
    counts: async () => ({ records: records.size, chunks: [...chunks.values()].reduce((n, list) => n + list.length, 0) }),
    clear: async () => {
      records.clear();
      chunks.clear();
      meta = { ...EMPTY_META };
    },
  };
}

// ─── IndexedDB (the browser) ────────────────────────────────────────────────

function promised<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"));
  });
}

function finished(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("IndexedDB transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("IndexedDB transaction aborted"));
  });
}

/** Every chunk of one record: [kind, key] sorts before [kind, key, ord], and any number before an array. */
function chunkRange(kind: string, key: string): IDBKeyRange {
  return IDBKeyRange.bound([kind, key], [kind, key, []]);
}

/** Every record of one kind: [kind] sorts before [kind, key], and any string before an array. */
function kindRange(kind: string): IDBKeyRange {
  return IDBKeyRange.bound([kind], [kind, []]);
}

export function indexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined" && typeof IDBKeyRange !== "undefined";
}

/** Opens (creating on first use) the "jeannie-hg" database. */
export async function openIndexedDbStore(factory: IDBFactory = indexedDB): Promise<HgLocalStore> {
  const open = factory.open(HG_DB_NAME, HG_DB_VERSION);
  open.onupgradeneeded = () => {
    const db = open.result;
    if (!db.objectStoreNames.contains(RECORDS)) db.createObjectStore(RECORDS, { keyPath: ["kind", "key"] });
    if (!db.objectStoreNames.contains(CHUNKS)) db.createObjectStore(CHUNKS, { keyPath: ["kind", "key", "ord"] });
    if (!db.objectStoreNames.contains(META)) db.createObjectStore(META);
  };
  const db = await promised(open);
  // Another tab upgrading or deleting the database: let it, this tab re-opens on its next load.
  db.onversionchange = () => db.close();

  return {
    async meta() {
      const tx = db.transaction(META, "readonly");
      const store = tx.objectStore(META);
      const [keys, values] = await Promise.all([promised(store.getAllKeys()), promised(store.getAll())]);
      const out: HgLocalMeta = { ...EMPTY_META };
      keys.forEach((k, i) => {
        if (typeof k === "string" && (META_KEYS as string[]).includes(k)) (out as unknown as Record<string, unknown>)[k] = values[i];
      });
      return out;
    },

    async write(batch) {
      const tx = db.transaction([RECORDS, CHUNKS, META], "readwrite");
      const done = finished(tx);
      const records = tx.objectStore(RECORDS);
      const chunks = tx.objectStore(CHUNKS);
      // Requests in one transaction run in the order they are made.
      for (const op of batch.ops) {
        if (op.op === "upsert") {
          chunks.delete(chunkRange(op.record.kind, op.record.key));
          records.put(op.record);
          for (const chunk of op.chunks) chunks.put(chunk);
        } else {
          records.delete([op.kind, op.key]);
          chunks.delete(chunkRange(op.kind, op.key));
        }
      }
      if (batch.meta) {
        const meta = tx.objectStore(META);
        for (const [name, value] of Object.entries(batch.meta)) meta.put(value, name);
      }
      await done;
    },

    async recordsOfKind(kind) {
      return promised(db.transaction(RECORDS, "readonly").objectStore(RECORDS).getAll(kindRange(kind))) as Promise<HgRecord[]>;
    },

    async getRecords(refs) {
      if (refs.length === 0) return [];
      const store = db.transaction(RECORDS, "readonly").objectStore(RECORDS);
      const found = await Promise.all(refs.map((r) => promised(store.get([r.kind, r.key]) as IDBRequest<HgRecord | undefined>)));
      return found.filter((r): r is HgRecord => r !== undefined);
    },

    async chunks() {
      return promised(db.transaction(CHUNKS, "readonly").objectStore(CHUNKS).getAll()) as Promise<LocalChunk[]>;
    },

    async counts() {
      const tx = db.transaction([RECORDS, CHUNKS], "readonly");
      const [records, chunks] = await Promise.all([promised(tx.objectStore(RECORDS).count()), promised(tx.objectStore(CHUNKS).count())]);
      return { records, chunks };
    },

    async clear() {
      const tx = db.transaction([RECORDS, CHUNKS, META], "readwrite");
      const done = finished(tx);
      tx.objectStore(RECORDS).clear();
      tx.objectStore(CHUNKS).clear();
      tx.objectStore(META).clear();
      await done;
    },
  };
}

/** Asks the browser not to evict the copy under storage pressure (best effort; the answer is not needed). */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    return typeof navigator !== "undefined" && navigator.storage?.persist ? await navigator.storage.persist() : false;
  } catch {
    return false;
  }
}
