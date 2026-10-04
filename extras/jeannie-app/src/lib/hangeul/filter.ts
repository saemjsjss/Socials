// The meaning of a RecordFilter, as plain code. The server store turns a filter
// into PostgREST query parameters and then re-checks every row with this, and
// the device copy (IndexedDB) filters with it directly, so both answer from
// exactly the same rows. Isomorphic.

import type { HgRecord, RecordFilter, StudentQuery } from "./types";

export function matchesFilter(record: HgRecord, filter: RecordFilter = {}): boolean {
  if (filter.key !== undefined && record.key !== filter.key) return false;
  if (filter.keys !== undefined && !filter.keys.includes(record.key)) return false;
  if (filter.keySuffix !== undefined && !record.key.endsWith(filter.keySuffix)) return false;
  if (filter.scope !== undefined && record.scope !== filter.scope) return false;
  if (filter.scopePrefix !== undefined && !record.scope.startsWith(filter.scopePrefix)) return false;
  if (filter.day !== undefined && record.day !== filter.day) return false;
  if (filter.from !== undefined && !(record.day !== null && record.day >= filter.from)) return false;
  if (filter.to !== undefined && !(record.day !== null && record.day <= filter.to)) return false;
  if (filter.studentUid !== undefined && record.student_uid !== filter.studentUid) return false;
  if (filter.studentHngId !== undefined && record.student_hng_id !== filter.studentHngId) return false;
  if (filter.passportNo !== undefined && record.passport_no !== filter.passportNo) return false;
  if (filter.dataEq) {
    for (const [field, value] of Object.entries(filter.dataEq)) {
      const actual = record.data?.[field];
      if (actual === undefined || actual === null || String(actual) !== value) return false;
    }
  }
  return true;
}

/** Filter, order ("key" or newest day first, then key) and limit, the way the store returns rows. */
export function applyFilter(records: readonly HgRecord[], filter: RecordFilter = {}): HgRecord[] {
  const kept = records.filter((r) => matchesFilter(r, filter));
  kept.sort((a, b) => {
    if (filter.order === "day.desc") {
      const da = a.day ?? "";
      const db = b.day ?? "";
      if (da !== db) return da < db ? 1 : -1;
    }
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  });
  return filter.limit !== undefined ? kept.slice(0, Math.max(0, filter.limit)) : kept;
}

function tokens(name: string): string[] {
  return name
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((t) => t.length >= 2);
}

/**
 * Student records (kind "student") matching a query, best first: an HNG id,
 * uid or passport must match exactly; a name matches exactly (ignoring case)
 * first, else by every token, ranked by how many name tokens it covers.
 */
export function rankStudents(candidates: readonly HgRecord[], query: StudentQuery): HgRecord[] {
  const students = candidates.filter((r) => r.kind === "student");
  if (query.hngId) return students.filter((r) => r.student_hng_id?.toUpperCase() === query.hngId!.toUpperCase());
  if (query.uid !== undefined) return students.filter((r) => r.student_uid === query.uid || r.key === String(query.uid));
  if (query.passport) return students.filter((r) => r.passport_no?.toUpperCase() === query.passport!.toUpperCase());
  if (!query.name) return [];
  const wanted = query.name.trim().toLowerCase();
  const exact = students.filter((r) => (r.student_name ?? "").trim().toLowerCase() === wanted);
  if (exact.length) return exact;
  const want = tokens(query.name);
  if (want.length === 0) return [];
  const scored = students
    .map((r) => {
      const have = tokens(r.student_name ?? "");
      const hits = want.filter((t) => have.some((h) => h.includes(t))).length;
      return { r, hits, extra: have.length - hits };
    })
    .filter((s) => s.hits === want.length);
  scored.sort((a, b) => a.extra - b.extra || (a.r.student_name ?? "").localeCompare(b.r.student_name ?? ""));
  return scored.map((s) => s.r);
}
