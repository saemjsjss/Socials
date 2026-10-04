// Local search (spec §6): the question's gte-small vector against every chunk
// vector on the device, brute force over one Float32Array. Tens of thousands of
// 384-d rows are a few million multiply-adds: well under 100 ms on a phone, with
// no network round trip. The hits (records, not text) go to the server, which
// re-reads those records from current rows and answers.

import type { AnswerSource } from "@/lib/hangeul/types";
import { EMBEDDING_DIMENSIONS } from "@/lib/hangeul/vectors";
import type { LocalChunk } from "./db";

export interface VectorIndex {
  size: number;
  /** size × 384, every row L2-normalised, so a dot product is the cosine. */
  vectors: Float32Array;
  kinds: string[];
  keys: string[];
  ords: Int32Array;
  days: (string | null)[];
  uids: (number | null)[];
}

export interface LocalSearchOptions {
  /** Chunks to return (default 12, like hg_match). */
  count?: number;
  kinds?: readonly string[];
  /** Inclusive bounds on the record's day; a record with no day is left out when either is set. */
  from?: string;
  to?: string;
  studentUid?: number;
}

export interface LocalHit {
  kind: string;
  key: string;
  ord: number;
  similarity: number;
}

/** gte-small scores sit close together (unrelated rows still score ~0.86): keep the hits near the best, like the server. */
export const HIT_GAP = 0.04;
/** Records sent to the server as hits (the server's own search shows at most 5 cards). */
export const MAX_HIT_RECORDS = 5;

const D = EMBEDDING_DIMENSIONS;

export function buildIndex(chunks: readonly LocalChunk[]): VectorIndex {
  const usable = chunks.filter((c) => c.embedding && c.embedding.length === D);
  const vectors = new Float32Array(usable.length * D);
  const ords = new Int32Array(usable.length);
  const kinds: string[] = [];
  const keys: string[] = [];
  const days: (string | null)[] = [];
  const uids: (number | null)[] = [];
  usable.forEach((c, row) => {
    let norm = 0;
    for (let i = 0; i < D; i++) norm += c.embedding[i] * c.embedding[i];
    const scale = norm > 0 ? 1 / Math.sqrt(norm) : 0;
    const base = row * D;
    for (let i = 0; i < D; i++) vectors[base + i] = c.embedding[i] * scale;
    kinds.push(c.kind);
    keys.push(c.key);
    ords[row] = c.ord;
    days.push(c.day ?? null);
    uids.push(c.student_uid ?? null);
  });
  return { size: usable.length, vectors, kinds, keys, ords, days, uids };
}

/** The `count` nearest chunks by cosine, best first. */
export function searchIndex(index: VectorIndex, query: ArrayLike<number>, options: LocalSearchOptions = {}): LocalHit[] {
  if (query.length !== D || index.size === 0) return [];
  let norm = 0;
  for (let i = 0; i < D; i++) norm += query[i] * query[i];
  if (norm === 0) return [];
  const q = new Float32Array(D);
  const scale = 1 / Math.sqrt(norm);
  for (let i = 0; i < D; i++) q[i] = query[i] * scale;

  const count = Math.max(1, Math.min(100, options.count ?? 12));
  const kinds = options.kinds?.length ? new Set(options.kinds) : null;
  const ranged = options.from !== undefined || options.to !== undefined;
  // Top `count` so far, kept sorted best first (count is small).
  const topRows: number[] = [];
  const topScores: number[] = [];
  const { vectors } = index;
  for (let row = 0; row < index.size; row++) {
    if (kinds && !kinds.has(index.kinds[row])) continue;
    if (options.studentUid !== undefined && index.uids[row] !== options.studentUid) continue;
    if (ranged) {
      const day = index.days[row];
      if (day === null || (options.from !== undefined && day < options.from) || (options.to !== undefined && day > options.to)) continue;
    }
    const base = row * D;
    let dot = 0;
    for (let i = 0; i < D; i++) dot += vectors[base + i] * q[i];
    if (topScores.length === count && dot <= topScores[count - 1]) continue;
    let at = topScores.length;
    while (at > 0 && topScores[at - 1] < dot) at--;
    topScores.splice(at, 0, dot);
    topRows.splice(at, 0, row);
    if (topScores.length > count) {
      topScores.pop();
      topRows.pop();
    }
  }
  return topRows.map((row, i) => ({ kind: index.kinds[row], key: index.keys[row], ord: index.ords[row], similarity: topScores[i] }));
}

/** The records behind the hits: best chunk per record, within `gap` of the best hit, at most `max`. */
export function hitRecords(hits: readonly LocalHit[], gap = HIT_GAP, max = MAX_HIT_RECORDS): AnswerSource[] {
  const best = hits[0]?.similarity;
  if (best === undefined) return [];
  const out: AnswerSource[] = [];
  const seen = new Set<string>();
  for (const h of hits) {
    if (h.similarity < best - gap) break;
    const id = `${h.kind}\u0000${h.key}`;
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ kind: h.kind, key: h.key });
    if (out.length >= max) break;
  }
  return out;
}
