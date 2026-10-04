// HangeulReaders over the device copy (IndexedDB), with the same filter meaning
// as the server store (src/lib/hangeul/filter.ts) and the bot's runs synced with
// the copy, so answer.ts builds the same answer, with the same "as of" line,
// from the phone's rows as the server does from Supabase's.

import { applyFilter, rankStudents } from "@/lib/hangeul/filter";
import { HangeulReadError, type HangeulReaders, type HgRecord, type HgRun } from "@/lib/hangeul/types";
import type { HgLocalStore } from "./db";

function usable(run: HgRun): boolean {
  return run.finished_at !== null && (run.status === "ok" || run.status === "partial");
}

/** Readers for one answer: each kind is read from IndexedDB once. No change log, no server search. */
export function deviceReaders(store: HgLocalStore, runs: readonly HgRun[]): HangeulReaders {
  const byKind = new Map<string, Promise<HgRecord[]>>();
  const ofKind = (kind: string): Promise<HgRecord[]> => {
    let list = byKind.get(kind);
    if (!list) {
      list = store.recordsOfKind(kind).catch(() => {
        throw new HangeulReadError("the device copy could not be read");
      });
      byKind.set(kind, list);
    }
    return list;
  };
  const sorted = runs.filter(usable).sort((a, b) => ((a.finished_at ?? "") < (b.finished_at ?? "") ? 1 : -1));
  return {
    records: async (kind, filter) => applyFilter(await ofKind(kind), filter),
    runs: async () => sorted,
    findStudents: async (query) => rankStudents(await ofKind("student"), query),
  };
}
