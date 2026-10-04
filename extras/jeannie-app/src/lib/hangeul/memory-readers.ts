// HangeulReaders over rows already in memory: the device copy (rows read from
// IndexedDB) and the tests use it, with the same filter meaning as the server
// store (filter.ts). Isomorphic.

import { applyFilter, rankStudents } from "./filter";
import type { HangeulReaders, HgChange, HgHit, HgRecord, HgRun, MatchOptions } from "./types";

export interface MemoryReadersInput {
  records: readonly HgRecord[];
  runs?: readonly HgRun[];
  /** Change-log rows (the server has them; a device does not). */
  changes?: readonly HgChange[];
  match?: (embedding: readonly number[], options?: MatchOptions) => Promise<HgHit[]>;
  embed?: (texts: readonly string[]) => Promise<number[][]>;
}

export function readersFromRecords(input: MemoryReadersInput): HangeulReaders {
  const byKind = new Map<string, HgRecord[]>();
  for (const r of input.records) {
    const list = byKind.get(r.kind);
    if (list) list.push(r);
    else byKind.set(r.kind, [r]);
  }
  const runs = [...(input.runs ?? [])].sort((a, b) => ((a.finished_at ?? "") < (b.finished_at ?? "") ? 1 : -1));
  const readers: HangeulReaders = {
    records: async (kind, filter) => applyFilter(byKind.get(kind) ?? [], filter),
    runs: async () => runs.filter((r) => r.finished_at !== null && (r.status === "ok" || r.status === "partial")),
    findStudents: async (query) => rankStudents(byKind.get("student") ?? [], query),
  };
  if (input.changes) {
    const changes = [...input.changes].sort((a, b) => a.seq - b.seq);
    readers.changes = async (sinceIso, limit = 20_000) => {
      const since = new Date(sinceIso).getTime();
      return changes.filter((c) => new Date(c.changed_at).getTime() >= since).slice(0, limit);
    };
  }
  if (input.match) readers.match = input.match;
  if (input.embed) readers.embed = input.embed;
  return readers;
}
