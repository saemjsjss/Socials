// The hangeul_context migration against a real Postgres (PGlite, in-process),
// with the Supabase roles and `extensions` schema recreated. Covers the data
// contract Hangeul BOT writes to (.scratch/hangeul-cloud-context/).

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { PGlite } from "@electric-sql/pglite";
import { pg_trgm } from "@electric-sql/pglite/contrib/pg_trgm";
import { vector } from "@electric-sql/pglite-pgvector";
import { beforeAll, describe, expect, it } from "vitest";

const MIGRATIONS = join(process.cwd(), "supabase", "migrations");
const RUN = "00000000-0000-4000-8000-000000000001";
const MODEL = "thenlper/gte-small@test";

let db: PGlite;
/** A project created before 30 May 2026: new public tables were granted to the API roles automatically. */
let legacy: PGlite;

/** A unit vector with 1 at `hot` (so cosine similarity is 1 for the same index, 0 otherwise). */
function unit(hot: number): number[] {
  return Array.from({ length: 384 }, (_, i) => (i === hot ? 1 : 0));
}

interface RowInput {
  key: string;
  hash?: string;
  day?: string | null;
  uid?: number | null;
  data?: Record<string, unknown>;
  chunks?: Array<{ ord: number; content: string; embedding: number[]; embed_model?: string }>;
}

function row(r: RowInput) {
  return {
    key: r.key,
    student_uid: r.uid ?? null,
    student_hng_id: r.uid ? `HNG-2026-${904 + r.uid}` : null,
    student_name: r.uid ? `TEST STUDENT ${r.uid}` : null,
    passport_no: r.uid ? `A0000000${r.uid % 10}` : null,
    day: r.day ?? null,
    data: r.data ?? { key: r.key },
    content: `Record ${r.key}`,
    content_hash: r.hash ?? `hash-${r.key}`,
    source: "students.php",
    read_at: "2026-09-29T18:21:04+06:00",
    chunks: (r.chunks ?? [{ ord: 0, content: `Record ${r.key}`, embedding: unit(0) }]).map((c) => ({
      embed_model: MODEL,
      ...c,
    })),
  };
}

async function sync(kind: string, scope: string, rows: unknown[], allKeys: string[] | null = null) {
  const res = await db.query<{ r: { upserted: number; deleted: number; unchanged: number } }>(
    "select public.hg_sync($1::uuid, $2, $3, $4::jsonb, $5::text[]) as r",
    [RUN, kind, scope, JSON.stringify(rows), allKeys],
  );
  return res.rows[0].r;
}

async function count(sql: string, params: unknown[] = []): Promise<number> {
  const res = await db.query<{ n: number }>(`select count(*)::int as n from (${sql}) s`, params);
  return res.rows[0].n;
}

async function asRole(role: string, sql: string, target: PGlite = db): Promise<string> {
  try {
    await target.exec(`set role ${role}; ${sql}; reset role;`);
    return "ok";
  } catch (error) {
    await target.exec("reset role;");
    return error instanceof Error ? error.message : String(error);
  }
}

/** A Supabase-like database: the API roles and the extensions schema, then every migration (twice). */
async function supabaseLike(autoGrants: boolean): Promise<PGlite> {
  const pg = await PGlite.create({ extensions: { vector, pg_trgm } });
  await pg.exec(`
    create schema if not exists extensions;
    create role anon nologin;
    create role authenticated nologin;
    create role service_role nologin bypassrls;
    grant usage on schema public, extensions to anon, authenticated, service_role;
  `);
  if (autoGrants) {
    await pg.exec(`
      alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
      alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
      alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
    `);
  }
  const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
  // Re-running every migration must be harmless (the owner may paste the bundle twice).
  for (const pass of [1, 2]) {
    for (const file of files) {
      try {
        await pg.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
      } catch (error) {
        throw new Error(`${file} (pass ${pass}): ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }
  return pg;
}

beforeAll(async () => {
  // Projects created after 30 May 2026 (like the Hangeul one) no longer auto-grant new tables.
  db = await supabaseLike(false);
  legacy = await supabaseLike(true);
  for (const pg of [db, legacy]) {
    await pg.query("insert into public.hg_runs (id, job, started_at) values ($1, 'portal_sync', now())", [RUN]);
  }
}, 120_000);

describe("hg_sync", () => {
  it("upserts new rows with their chunks and logs each as an upsert", async () => {
    const before = await count("select 1 from public.hg_changes");
    const r = await sync("student", "all", [row({ key: "1", uid: 1 }), row({ key: "2", uid: 2 })]);
    expect(r).toEqual({ upserted: 2, deleted: 0, unchanged: 0 });
    expect(await count("select 1 from public.hg_records where kind = 'student'")).toBe(2);
    expect(await count("select 1 from public.hg_chunks where kind = 'student'")).toBe(2);
    const log = await db.query<{ op: string; data: unknown; run_id: string }>(
      "select op, data, run_id from public.hg_changes order by seq desc limit 2",
    );
    expect(await count("select 1 from public.hg_changes")).toBe(before + 2);
    expect(log.rows.every((l) => l.op === "upsert" && l.data !== null && l.run_id === RUN)).toBe(true);
    const rec = await db.query<{ scope: string; run_id: string; student_hng_id: string }>(
      "select scope, run_id, student_hng_id from public.hg_records where kind = 'student' and key = '1'",
    );
    expect(rec.rows[0]).toEqual({ scope: "all", run_id: RUN, student_hng_id: "HNG-2026-905" });
  });

  it("leaves a row with the same content hash alone (no change logged)", async () => {
    const before = await count("select 1 from public.hg_changes");
    const r = await sync("student", "all", [row({ key: "1", uid: 1 })]);
    expect(r).toEqual({ upserted: 0, deleted: 0, unchanged: 1 });
    expect(await count("select 1 from public.hg_changes")).toBe(before);
  });

  it("replaces the chunks of a changed row", async () => {
    const r = await sync("student", "all", [
      row({
        key: "1",
        uid: 1,
        hash: "hash-1-v2",
        chunks: [
          { ord: 0, content: "part a", embedding: unit(1) },
          { ord: 1, content: "part b", embedding: unit(2) },
        ],
      }),
    ]);
    expect(r.upserted).toBe(1);
    const chunks = await db.query<{ ord: number; content: string }>(
      "select ord, content from public.hg_chunks where kind = 'student' and key = '1' order by ord",
    );
    expect(chunks.rows).toEqual([
      { ord: 0, content: "part a" },
      { ord: 1, content: "part b" },
    ]);
  });

  it("deletes rows a complete read no longer saw, logging data = null, and cascades chunks", async () => {
    const r = await sync("student", "all", [], ["1"]);
    expect(r).toEqual({ upserted: 0, deleted: 1, unchanged: 0 });
    expect(await count("select 1 from public.hg_records where kind = 'student' and key = '2'")).toBe(0);
    expect(await count("select 1 from public.hg_chunks where kind = 'student' and key = '2'")).toBe(0);
    const last = await db.query<{ op: string; key: string; data: unknown }>(
      "select op, key, data from public.hg_changes order by seq desc limit 1",
    );
    expect(last.rows[0]).toEqual({ op: "delete", key: "2", data: null });
  });

  it("deletes nothing when p_all_keys is null (a partial read)", async () => {
    await sync("verification", "2026-09-12", [row({ key: "7", uid: 7, day: "2026-09-12" })]);
    const r = await sync("verification", "2026-09-12", [], null);
    expect(r.deleted).toBe(0);
    expect(await count("select 1 from public.hg_records where kind = 'verification'")).toBe(1);
  });

  it("only deletes inside the same kind and scope", async () => {
    await sync("verification", "2026-09-13", [row({ key: "8", uid: 8, day: "2026-09-13" })]);
    const r = await sync("verification", "2026-09-12", [], []);
    expect(r.deleted).toBe(1); // key 7 in scope 2026-09-12
    expect(await count("select 1 from public.hg_records where kind = 'verification' and key = '8'")).toBe(1);
  });

  it("never deletes append-only field corrections", async () => {
    await sync("field_correction", "all", [row({ key: "c1" })]);
    const r = await sync("field_correction", "all", [], []);
    expect(r.deleted).toBe(0);
    expect(await count("select 1 from public.hg_records where kind = 'field_correction'")).toBe(1);
  });

  it.each([
    ["p_rows is not an array", () => sync("student", "all", { key: "x" } as unknown as unknown[]), /p_rows must be a JSON array/],
    ["more than 200 rows", () => sync("student", "all", Array.from({ length: 201 }, (_, i) => row({ key: `b${i}` }))), /at most 200/],
    ["a row without a key", () => sync("student", "all", [{ ...row({ key: "k" }), key: "" }]), /key/],
    ["data that is not an object", () => sync("student", "all", [{ ...row({ key: "k" }), data: [1] }]), /data must be a JSON object/],
    ["a 383-dimension embedding", () => sync("student", "all", [row({ key: "k", chunks: [{ ord: 0, content: "x", embedding: unit(0).slice(1) }] })]), /384/],
    [
      "two embedding models in one call",
      () =>
        sync("student", "all", [
          row({ key: "k1" }),
          row({ key: "k2", chunks: [{ ord: 0, content: "x", embedding: unit(0), embed_model: "other-model" }] }),
        ]),
      /one embed_model/,
    ],
    ["a blank kind", () => sync("", "all", [row({ key: "k" })]), /p_kind and p_scope/],
  ])("rejects %s and writes nothing", async (_label, call, message) => {
    const before = await count("select 1 from public.hg_records");
    await expect(call()).rejects.toThrow(message);
    expect(await count("select 1 from public.hg_records")).toBe(before);
  });
});

describe("hg_match", () => {
  beforeAll(async () => {
    await sync("doc_page_text", "A00000001", [
      row({ key: "A00000001|passport.pdf|p1", uid: 1, day: "2026-09-10", chunks: [{ ord: 0, content: "page one", embedding: unit(10) }] }),
      row({ key: "A00000001|bank.pdf|p1", uid: 1, day: "2026-09-11", chunks: [{ ord: 0, content: "bank page", embedding: unit(11) }] }),
    ]);
  });

  it("returns the closest chunk first, with its record", async () => {
    const res = await db.query<{ key: string; similarity: number; student_uid: number; data: unknown }>(
      "select * from public.hg_match($1::text::extensions.vector, 2, array['doc_page_text'])",
      [JSON.stringify(unit(11))],
    );
    expect(res.rows[0]).toMatchObject({ key: "A00000001|bank.pdf|p1", student_uid: 1 });
    expect(res.rows[0].similarity).toBeCloseTo(1, 5);
    expect(res.rows[1].similarity).toBeCloseTo(0, 5);
  });

  it("filters by day and student", async () => {
    const res = await db.query<{ key: string }>(
      "select key from public.hg_match($1::text::extensions.vector, 5, null, '2026-09-10', '2026-09-10', 1)",
      [JSON.stringify(unit(11))],
    );
    expect(res.rows.map((r) => r.key)).toEqual(["A00000001|passport.pdf|p1"]);
  });
});

describe("hg_changes_since", () => {
  it("returns upserts with the current record and 384-float chunks, and deletes with no record", async () => {
    const start = (await db.query<{ s: number }>("select coalesce(max(seq), 0)::int as s from public.hg_changes")).rows[0].s;
    await sync("calendar_item", "all", [row({ key: "ev1" }), row({ key: "ev2" })]);
    await sync("calendar_item", "all", [], ["ev1"]);
    const res = await db.query<{ op: string; key: string; record: { key: string } | null; chunks: Array<{ embedding: number[] }> | null }>(
      "select op, key, record, chunks from public.hg_changes_since($1)",
      [start],
    );
    expect(res.rows.map((r) => [r.op, r.key])).toEqual([
      ["upsert", "ev1"],
      ["upsert", "ev2"],
      ["delete", "ev2"],
    ]);
    expect(res.rows[0].record?.key).toBe("ev1");
    expect(res.rows[0].chunks?.[0].embedding).toHaveLength(384);
    // ev2 is gone now, so its earlier upsert carries no record and the delete follows it.
    expect(res.rows[1].record).toBeNull();
    expect(res.rows[2].record).toBeNull();
  });

  it("pages by seq", async () => {
    const res = await db.query<{ seq: number }>("select seq from public.hg_changes_since(0, 2)");
    expect(res.rows).toHaveLength(2);
  });
});

describe("existing tables", () => {
  it("refuses to adopt an hg_records table that another script created", async () => {
    const other = await PGlite.create({ extensions: { vector, pg_trgm } });
    await other.exec(`
      create schema if not exists extensions;
      create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
      create table public.hg_records (kind text, key text, payload jsonb);
    `);
    const sql = readFileSync(join(MIGRATIONS, "20260929030000_hangeul_context.sql"), "utf8");
    await expect(other.exec(sql)).rejects.toThrow(/was not created by the hangeul_context migration/);
    await other.close();
  }, 60_000);
});

describe.each([
  ["a new project (no automatic grants)", () => db],
  ["an older project (automatic grants)", () => legacy],
])("access on %s", (_label, pick) => {
  it.each(["anon", "authenticated"])("%s can read, write or call nothing", async (role) => {
    const pg = pick();
    for (const table of ["hg_runs", "hg_records", "hg_chunks", "hg_changes", "memory_documents"]) {
      expect(await asRole(role, `select * from public.${table}`, pg)).toMatch(/permission denied/);
    }
    expect(await asRole(role, `select public.hg_sync('${RUN}', 'student', 'all', '[]'::jsonb)`, pg)).toMatch(/permission denied/);
    expect(await asRole(role, "select * from public.hg_changes_since(0)", pg)).toMatch(/permission denied/);
    expect(
      await asRole(role, `select * from public.hg_match(array_fill(0, array[384])::real[]::extensions.vector)`, pg),
    ).toMatch(/permission denied/);
  });

  it("service_role (the secret key) can write runs, sync, search and use the memory tables", async () => {
    expect(
      await asRole(
        "service_role",
        `insert into public.hg_runs (job, started_at) values ('backfill', now());
         update public.hg_runs set status = 'ok', finished_at = now() where job = 'backfill';
         select public.hg_sync('${RUN}', 'student', 'svc', '[]'::jsonb, array[]::text[]);
         select * from public.hg_changes_since(0, 1);
         select * from public.hg_match(array_fill(0, array[384])::real[]::extensions.vector);
         select public.upsert_memory_document('t.md', 'T', 'markdown', false, 'x', '[{"ord":0,"content":"x"}]'::jsonb);
         insert into public.jeannie_sessions (chat_key) values ('test:1') on conflict do nothing;
         insert into public.jeannie_audit_log (chat_key, decision) values ('test:1', 'approved')`,
        pick(),
      ),
    ).toBe("ok");
  });
});

describe("row-level security", () => {

  it("has RLS on every table", async () => {
    const res = await db.query<{ relname: string; relrowsecurity: boolean }>(
      "select relname, relrowsecurity from pg_class where relname in ('hg_runs','hg_records','hg_chunks','hg_changes') order by relname",
    );
    expect(res.rows).toHaveLength(4);
    expect(res.rows.every((r) => r.relrowsecurity)).toBe(true);
  });
});
