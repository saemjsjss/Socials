// A tiny in-memory PostgREST for the Hangeul tables, enough for the store's
// queries: eq/in/gt/gte/lte/like/ilike/cs filters, and=(...), order, limit
// (capped at 1,000 like the real max-rows), offset, Prefer: count=exact, and
// the read RPCs hg_match and hg_changes_since. Synthetic data only.
import { vi } from "vitest";
import type { HgRecord, HgRun } from "@/lib/hangeul/types";

export const URL_BASE = "https://proj.supabase.co";
export const SECRET = "sb_secret_test_key_value";

export interface FakeChunk {
  kind: string;
  key: string;
  ord: number;
  content: string;
  embedding: number[];
  embed_model: string;
}

export interface FakeChange {
  seq: number;
  kind: string;
  key: string;
  op: "upsert" | "delete";
  changed_at: string;
  run_id?: string | null;
}

export interface FakeDb {
  records: HgRecord[];
  chunks: FakeChunk[];
  runs: (HgRun & { counts?: Record<string, unknown> })[];
  changes: FakeChange[];
  hits?: Record<string, unknown>[];
}

export interface FakeCall {
  url: string;
  path: string;
  params: URLSearchParams;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

export function unit(i: number, dims = 384): number[] {
  const v = new Array(dims).fill(0);
  v[i % dims] = 1;
  return v;
}

function parseList(value: string): string[] {
  // ("a","b\"c") or (a,b)
  const inner = value.replace(/^\(/, "").replace(/\)$/, "");
  const out: string[] = [];
  let i = 0;
  while (i < inner.length) {
    if (inner[i] === '"') {
      let s = "";
      i++;
      while (i < inner.length && inner[i] !== '"') {
        if (inner[i] === "\\") i++;
        s += inner[i++];
      }
      out.push(s);
      i += 2; // closing quote and comma
    } else {
      const end = inner.indexOf(",", i);
      out.push(inner.slice(i, end === -1 ? inner.length : end));
      i = end === -1 ? inner.length : end + 1;
    }
  }
  return out;
}

function like(value: string, pattern: string, insensitive: boolean): boolean {
  const v = insensitive ? value.toLowerCase() : value;
  const p = insensitive ? pattern.toLowerCase() : pattern;
  const parts = p.split("*");
  if (parts.length === 1) return v === p;
  let pos = 0;
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (i === 0) {
      if (!v.startsWith(part)) return false;
      pos = part.length;
    } else if (i === parts.length - 1) {
      if (part && !v.slice(pos).endsWith(part)) return false;
    } else {
      const found = v.indexOf(part, pos);
      if (found === -1) return false;
      pos = found + part.length;
    }
  }
  return true;
}

function column(row: Record<string, unknown>, name: string): unknown {
  const arrow = /^(\w+)->>(\w+)$/.exec(name);
  if (arrow) {
    const obj = row[arrow[1]] as Record<string, unknown> | undefined;
    const v = obj?.[arrow[2]];
    return v === undefined || v === null ? null : String(v);
  }
  const json = /^(\w+)->(\w+)$/.exec(name);
  if (json) return (row[json[1]] as Record<string, unknown> | undefined)?.[json[2]];
  return row[name];
}

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T/;

/** timestamptz compares as instants ("…+00:00" vs "…Z"), everything else as text. */
function compare(a: string, b: string): number {
  if (TIMESTAMP.test(a) && TIMESTAMP.test(b)) return new Date(a).getTime() - new Date(b).getTime();
  return a < b ? -1 : a > b ? 1 : 0;
}

function test(row: Record<string, unknown>, name: string, expr: string): boolean {
  const dot = expr.indexOf(".");
  const op = expr.slice(0, dot);
  const value = expr.slice(dot + 1);
  const actual = column(row, name);
  const text = actual === null || actual === undefined ? null : String(actual);
  switch (op) {
    case "eq":
      return text === value;
    case "neq":
      return text !== value;
    case "gt":
      return text !== null && (typeof actual === "number" ? actual > Number(value) : compare(text, value) > 0);
    case "gte":
      return text !== null && (typeof actual === "number" ? actual >= Number(value) : compare(text, value) >= 0);
    case "lte":
      return text !== null && (typeof actual === "number" ? actual <= Number(value) : compare(text, value) <= 0);
    case "in":
      return text !== null && parseList(value).includes(text);
    case "like":
      return text !== null && like(text, value, false);
    case "ilike":
      return text !== null && like(text, value, true);
    case "not":
      return value === "is.null" ? actual !== null && actual !== undefined : true;
    case "cs": {
      const want = JSON.parse(value) as Record<string, unknown>;
      const have = (actual ?? {}) as Record<string, unknown>;
      return Object.keys(want).every((k) => k in have);
    }
    default:
      throw new Error(`fake PostgREST: unsupported operator ${op}`);
  }
}

const RESERVED = new Set(["select", "order", "limit", "offset", "and"]);

function query(rows: Record<string, unknown>[], params: URLSearchParams): Record<string, unknown>[] {
  let out = rows.filter((row) => {
    for (const [name, expr] of params.entries()) {
      if (RESERVED.has(name)) continue;
      if (!test(row, name, expr)) return false;
    }
    const and = params.get("and");
    if (and) {
      for (const part of and.replace(/^\(/, "").replace(/\)$/, "").split(",")) {
        const [col, op, ...rest] = part.split(".");
        if (!test(row, col, `${op}.${rest.join(".")}`)) return false;
      }
    }
    return true;
  });
  const order = params.get("order");
  if (order) {
    const keys = order.split(",").map((o) => o.split("."));
    out = [...out].sort((a, b) => {
      for (const [col, dir = "asc"] of keys) {
        const va = column(a, col);
        const vb = column(b, col);
        if (va === vb) continue;
        if (va === null || va === undefined) return 1;
        if (vb === null || vb === undefined) return -1;
        const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va) < String(vb) ? -1 : 1;
        return dir === "desc" ? -cmp : cmp;
      }
      return 0;
    });
  }
  const offset = Number(params.get("offset") ?? 0);
  const limit = Math.min(Number(params.get("limit") ?? 1000), 1000);
  return out.slice(offset, offset + limit);
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

/** Serves `db` over fetch and records every call. `override` may answer a call first (errors, delays). */
export function stubPostgrest(db: FakeDb, override?: (call: FakeCall) => Response | Promise<Response> | null | undefined) {
  const calls: FakeCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input);
    const parsed = new URL(url);
    const call: FakeCall = {
      url,
      path: parsed.pathname,
      params: parsed.searchParams,
      method: init?.method ?? "GET",
      headers: Object.fromEntries(new Headers(init?.headers).entries()),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const custom = await override?.(call);
    if (custom) return custom;
    if (!url.startsWith(`${URL_BASE}/rest/v1/`)) return json({ message: "not found" }, 404);
    const table = parsed.pathname.replace("/rest/v1/", "");
    if (table === "rpc/hg_changes_since") {
      const { p_seq, p_limit } = call.body as { p_seq: number; p_limit: number };
      const rows = db.changes
        .filter((c) => c.seq > p_seq)
        .sort((a, b) => a.seq - b.seq)
        .slice(0, Math.min(p_limit, 1000, 5000));
      return json(
        rows.map((c) => {
          const record = c.op === "upsert" ? db.records.find((r) => r.kind === c.kind && r.key === c.key) : undefined;
          return {
            ...c,
            record: record ?? null,
            chunks: record
              ? db.chunks.filter((ch) => ch.kind === c.kind && ch.key === c.key).map((ch) => ({ ord: ch.ord, content: ch.content, embedding: ch.embedding, embed_model: ch.embed_model }))
              : null,
          };
        }),
      );
    }
    if (table === "rpc/hg_match") return json(db.hits ?? []);
    let rows: Record<string, unknown>[];
    if (table === "hg_records") rows = db.records as unknown as Record<string, unknown>[];
    else if (table === "hg_chunks") rows = db.chunks.map((c) => ({ ...c, embedding: `[${c.embedding.join(",")}]` }));
    else if (table === "hg_changes") rows = db.changes as unknown as Record<string, unknown>[];
    else if (table === "hg_runs") {
      rows = db.runs.map((r) => ({ ...r, counts: r.counts ?? { by_kind: r.byKind, failed_reads: r.failedReads } }));
    } else return json({ code: "PGRST205", message: "no table" }, 404);
    const result = query(rows, parsed.searchParams);
    let body: unknown = result;
    if (table === "hg_runs") {
      body = result.map((r) => ({
        job: r.job,
        started_at: r.started_at,
        finished_at: r.finished_at,
        status: r.status,
        by_kind: (r.counts as Record<string, unknown>).by_kind,
        failed_reads: (r.counts as Record<string, unknown>).failed_reads,
      }));
    }
    const headers: Record<string, string> = {};
    if ((call.headers.prefer ?? "").includes("count=exact")) {
      const total = query(rows, new URLSearchParams([...parsed.searchParams.entries()].filter(([k]) => k !== "limit" && k !== "offset"))).length;
      headers["content-range"] = `0-${Math.max(0, result.length - 1)}/${total}`;
    }
    return json(body, 200, headers);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function configureSupabase() {
  vi.stubEnv("SUPABASE_URL", `${URL_BASE}/`);
  vi.stubEnv("SUPABASE_SECRET_KEY", SECRET);
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
}

export function clearSupabase() {
  for (const name of ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "NEXT_PUBLIC_SUPABASE_URL"]) vi.stubEnv(name, "");
}
