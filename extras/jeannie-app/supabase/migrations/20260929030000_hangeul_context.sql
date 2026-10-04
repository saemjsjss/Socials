-- Hangeul context: everything Hangeul BOT reads from the portal and every report
-- it builds, published from the office PC so Jeannie can answer from it.
-- Contract: .scratch/hangeul-cloud-context/spec.md §4 and hangeul-bot-prompt.md
-- ("The data contract"). A change here means a change there too.
--
-- Access model (same as the memory tables): RLS is on for every table with NO
-- policies, and the public roles lose every privilege, so the anon and
-- authenticated keys can read or write nothing. Only the secret / service-role
-- key gets through: Jeannie's server, and the office bot writing via hg_sync.
--
-- Safe to run again: every statement is idempotent.

create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- Refuse to adopt hg_* tables that some other script created with a different
-- shape: this file marks its own tables, and re-running it is fine.
do $$
begin
  if to_regclass('public.hg_records') is not null
     and coalesce(obj_description(to_regclass('public.hg_records'), 'pg_class'), '') not like 'hangeul_context v1%' then
    raise exception 'public.hg_records already exists but was not created by the hangeul_context migration. Drop the hg_* tables (or ask Jeannie''s maintainer) before running this.';
  end if;
end;
$$;

-- ─── Tables ──────────────────────────────────────────────────────────────────

-- One row per bot job run. The bot inserts it at the start (status null) and
-- patches it at the end.
create table if not exists public.hg_runs (
  id          uuid primary key default gen_random_uuid(),
  job         text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text check (status in ('ok', 'partial', 'failed')),
  counts      jsonb not null default '{}'::jsonb,
  note        text
);

-- The latest state of every entity: one row per (kind, key).
create table if not exists public.hg_records (
  kind           text not null check (kind <> ''),
  key            text not null check (key <> ''),
  scope          text not null check (scope <> ''),   -- what one complete read covers (for deletes)
  student_uid    integer,                              -- portal user id (student_edit.php?id=N)
  student_hng_id text,                                 -- HNG-YYYY-N
  student_name   text,
  passport_no    text,
  day            date,                                 -- business day, Asia/Dhaka
  data           jsonb not null check (jsonb_typeof(data) = 'object'),
  content        text not null,                        -- text form, built by the bot's code
  content_hash   text not null check (content_hash <> ''),
  source         text not null,
  read_at        timestamptz not null,
  run_id         uuid references public.hg_runs (id) on delete set null,
  updated_at     timestamptz not null default now(),
  primary key (kind, key)
);

comment on table public.hg_records is 'hangeul_context v1: latest state of everything Hangeul BOT publishes';

-- Embeddings of each record (gte-small, 384-d, mean pooled, L2-normalised).
create table if not exists public.hg_chunks (
  kind        text not null,
  key         text not null,
  ord         integer not null check (ord >= 0),
  content     text not null,
  embedding   extensions.vector(384) not null,
  embed_model text not null check (embed_model <> ''),
  primary key (kind, key, ord),
  foreign key (kind, key) references public.hg_records (kind, key) on delete cascade
);

-- Change log for device sync. Filled only by the trigger below; the bot never writes it.
create table if not exists public.hg_changes (
  seq        bigint generated always as identity primary key,
  kind       text not null,
  key        text not null,
  op         text not null check (op in ('upsert', 'delete')),
  data       jsonb,                                    -- null for a delete (only kind, key and time are kept)
  changed_at timestamptz not null default now(),
  run_id     uuid                                      -- no foreign key: the log outlives runs
);

-- ─── Indexes ─────────────────────────────────────────────────────────────────

create index if not exists hg_runs_job_started_idx on public.hg_runs (job, started_at desc);
create index if not exists hg_records_kind_scope_idx on public.hg_records (kind, scope);
create index if not exists hg_records_kind_day_idx on public.hg_records (kind, day);
create index if not exists hg_records_student_uid_idx on public.hg_records (student_uid) where student_uid is not null;
create index if not exists hg_records_hng_id_idx on public.hg_records (student_hng_id) where student_hng_id is not null;
create index if not exists hg_records_passport_idx on public.hg_records (passport_no) where passport_no is not null;
create index if not exists hg_records_name_trgm_idx on public.hg_records using gin (lower(student_name) extensions.gin_trgm_ops);
create index if not exists hg_records_updated_idx on public.hg_records (updated_at);
create index if not exists hg_records_run_idx on public.hg_records (run_id);
create index if not exists hg_chunks_embedding_idx on public.hg_chunks using hnsw (embedding extensions.vector_cosine_ops);

-- ─── Change-log trigger ──────────────────────────────────────────────────────
-- An insert logs an upsert; an update logs only when content_hash changed; a
-- delete logs data = null. The run comes from hg_sync (hangeul.run_id setting).

create or replace function public.hg_log_change()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_run uuid := nullif(current_setting('hangeul.run_id', true), '')::uuid;
begin
  if tg_op = 'DELETE' then
    insert into public.hg_changes (kind, key, op, data, run_id) values (old.kind, old.key, 'delete', null, v_run);
    return old;
  end if;
  if tg_op = 'UPDATE' and new.content_hash is not distinct from old.content_hash then
    return new;
  end if;
  insert into public.hg_changes (kind, key, op, data, run_id)
  values (new.kind, new.key, 'upsert', new.data, coalesce(v_run, new.run_id));
  return new;
end;
$$;

drop trigger if exists hg_records_log_change on public.hg_records;
create trigger hg_records_log_change
  after insert or update or delete on public.hg_records
  for each row execute function public.hg_log_change();

-- ─── RPC: the bot's one write call ───────────────────────────────────────────
-- Upserts each changed row on (kind, key) and replaces its chunks; unchanged
-- rows (same content_hash) are left alone. When p_all_keys is given (a COMPLETE
-- read of that kind and scope), every other row of that (kind, scope) is
-- deleted. Append-only kinds are never deleted. All or nothing: any invalid row
-- rejects the whole call.

create or replace function public.hg_sync(
  p_run      uuid,
  p_kind     text,
  p_scope    text,
  p_rows     jsonb,
  p_all_keys text[] default null
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  append_only constant text[] := array['field_correction'];
  v_row       jsonb;
  v_chunk     jsonb;
  v_key       text;
  v_model     text;
  v_changed   integer;
  v_upserted  integer := 0;
  v_unchanged integer := 0;
  v_deleted   integer := 0;
begin
  if coalesce(p_kind, '') = '' or coalesce(p_scope, '') = '' then
    raise exception 'hg_sync: p_kind and p_scope are required' using errcode = '22023';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'hg_sync: p_rows must be a JSON array' using errcode = '22023';
  end if;
  if jsonb_array_length(p_rows) > 200 then
    raise exception 'hg_sync: at most 200 rows per call (got %)', jsonb_array_length(p_rows) using errcode = '22023';
  end if;

  perform set_config('hangeul.run_id', coalesce(p_run::text, ''), true);

  for v_row in select value from jsonb_array_elements(p_rows) loop
    v_key := v_row ->> 'key';
    if jsonb_typeof(v_row) <> 'object' or coalesce(v_key, '') = '' then
      raise exception 'hg_sync: every row needs a non-empty key' using errcode = '22023';
    end if;
    if jsonb_typeof(v_row -> 'data') is distinct from 'object' then
      raise exception 'hg_sync: row %: data must be a JSON object', v_key using errcode = '22023';
    end if;
    if jsonb_typeof(v_row -> 'content') is distinct from 'string'
       or coalesce(v_row ->> 'content_hash', '') = ''
       or coalesce(v_row ->> 'source', '') = ''
       or coalesce(v_row ->> 'read_at', '') = '' then
      raise exception 'hg_sync: row %: content, content_hash, source and read_at are required', v_key using errcode = '22023';
    end if;
    if jsonb_typeof(coalesce(v_row -> 'chunks', '[]'::jsonb)) <> 'array' then
      raise exception 'hg_sync: row %: chunks must be a JSON array', v_key using errcode = '22023';
    end if;
    for v_chunk in select value from jsonb_array_elements(coalesce(v_row -> 'chunks', '[]'::jsonb)) loop
      if jsonb_typeof(v_chunk -> 'embedding') is distinct from 'array' or jsonb_array_length(v_chunk -> 'embedding') <> 384 then
        raise exception 'hg_sync: row %: every chunk embedding must have 384 numbers', v_key using errcode = '22023';
      end if;
      if coalesce(v_chunk ->> 'embed_model', '') = '' or (v_model is not null and v_chunk ->> 'embed_model' <> v_model) then
        raise exception 'hg_sync: one embed_model per call (row %)', v_key using errcode = '22023';
      end if;
      v_model := v_chunk ->> 'embed_model';
    end loop;

    insert into public.hg_records as r (
      kind, key, scope, student_uid, student_hng_id, student_name, passport_no, day,
      data, content, content_hash, source, read_at, run_id, updated_at
    ) values (
      p_kind, v_key, p_scope,
      nullif(v_row ->> 'student_uid', '')::integer,
      nullif(v_row ->> 'student_hng_id', ''),
      nullif(v_row ->> 'student_name', ''),
      nullif(v_row ->> 'passport_no', ''),
      nullif(v_row ->> 'day', '')::date,
      v_row -> 'data', v_row ->> 'content', v_row ->> 'content_hash', v_row ->> 'source',
      (v_row ->> 'read_at')::timestamptz, p_run, now()
    )
    on conflict (kind, key) do update set
      scope = excluded.scope, student_uid = excluded.student_uid, student_hng_id = excluded.student_hng_id,
      student_name = excluded.student_name, passport_no = excluded.passport_no, day = excluded.day,
      data = excluded.data, content = excluded.content, content_hash = excluded.content_hash,
      source = excluded.source, read_at = excluded.read_at, run_id = excluded.run_id, updated_at = now()
    where r.content_hash is distinct from excluded.content_hash;

    get diagnostics v_changed = row_count;
    if v_changed = 0 then
      v_unchanged := v_unchanged + 1;
      continue;
    end if;
    v_upserted := v_upserted + 1;

    delete from public.hg_chunks where kind = p_kind and key = v_key;
    insert into public.hg_chunks (kind, key, ord, content, embedding, embed_model)
    select p_kind, v_key, (c ->> 'ord')::integer, c ->> 'content',
           (c -> 'embedding')::text::extensions.vector(384), c ->> 'embed_model'
    from jsonb_array_elements(coalesce(v_row -> 'chunks', '[]'::jsonb)) as c;
  end loop;

  if p_all_keys is not null and not (p_kind = any (append_only)) then
    delete from public.hg_records
    where kind = p_kind and scope = p_scope and not (key = any (p_all_keys));
    get diagnostics v_deleted = row_count;
  end if;

  return jsonb_build_object('upserted', v_upserted, 'deleted', v_deleted, 'unchanged', v_unchanged);
end;
$$;

-- ─── RPC: semantic search (server path, before a device has synced) ──────────

create or replace function public.hg_match(
  p_embedding   extensions.vector(384),
  p_count       integer default 12,
  p_kinds       text[] default null,
  p_day_from    date default null,
  p_day_to      date default null,
  p_student_uid integer default null
) returns table (
  kind           text,
  key            text,
  ord            integer,
  content        text,
  similarity     double precision,
  data           jsonb,
  day            date,
  read_at        timestamptz,
  student_uid    integer,
  student_hng_id text,
  student_name   text
)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.kind, c.key, c.ord, c.content,
         1 - (c.embedding operator(extensions.<=>) p_embedding) as similarity,
         r.data, r.day, r.read_at, r.student_uid, r.student_hng_id, r.student_name
  from public.hg_chunks c
  join public.hg_records r on r.kind = c.kind and r.key = c.key
  where (p_kinds is null or c.kind = any (p_kinds))
    and (p_day_from is null or r.day >= p_day_from)
    and (p_day_to is null or r.day <= p_day_to)
    and (p_student_uid is null or r.student_uid = p_student_uid)
  order by c.embedding operator(extensions.<=>) p_embedding
  limit least(greatest(coalesce(p_count, 12), 1), 100);
$$;

-- ─── RPC: device delta sync ──────────────────────────────────────────────────
-- Changes after p_seq, with the CURRENT record and chunks for upserts (null when
-- the record has since been deleted; that delete follows later in the feed).

create or replace function public.hg_changes_since(p_seq bigint, p_limit integer default 1000)
returns table (
  seq        bigint,
  kind       text,
  key        text,
  op         text,
  changed_at timestamptz,
  run_id     uuid,
  record     jsonb,
  chunks     jsonb
)
language sql
stable
security invoker
set search_path = ''
as $$
  select ch.seq, ch.kind, ch.key, ch.op, ch.changed_at, ch.run_id,
         case when ch.op = 'upsert' and r.kind is not null then to_jsonb(r) end,
         case when ch.op = 'upsert' and r.kind is not null then (
           select coalesce(jsonb_agg(jsonb_build_object(
                    'ord', c.ord, 'content', c.content,
                    'embedding', to_jsonb(c.embedding::real[]), 'embed_model', c.embed_model
                  ) order by c.ord), '[]'::jsonb)
           from public.hg_chunks c
           where c.kind = ch.kind and c.key = ch.key
         ) end
  from public.hg_changes ch
  left join public.hg_records r on r.kind = ch.kind and r.key = ch.key
  where ch.seq > coalesce(p_seq, 0)
  order by ch.seq
  limit least(greatest(coalesce(p_limit, 1000), 1), 5000);
$$;

-- ─── Access ──────────────────────────────────────────────────────────────────

alter table public.hg_runs enable row level security;
alter table public.hg_records enable row level security;
alter table public.hg_chunks enable row level security;
alter table public.hg_changes enable row level security;

revoke all on table public.hg_runs, public.hg_records, public.hg_chunks, public.hg_changes from public, anon, authenticated;
revoke all on sequence public.hg_changes_seq_seq from public, anon, authenticated;
grant select, insert, update, delete on table public.hg_runs, public.hg_records, public.hg_chunks, public.hg_changes to service_role;
grant usage, select on sequence public.hg_changes_seq_seq to service_role;

revoke all on function public.hg_log_change() from public, anon, authenticated;
revoke all on function public.hg_sync(uuid, text, text, jsonb, text[]) from public, anon, authenticated;
revoke all on function public.hg_match(extensions.vector, integer, text[], date, date, integer) from public, anon, authenticated;
revoke all on function public.hg_changes_since(bigint, integer) from public, anon, authenticated;
grant execute on function public.hg_sync(uuid, text, text, jsonb, text[]) to service_role;
grant execute on function public.hg_match(extensions.vector, integer, text[], date, date, integer) to service_role;
grant execute on function public.hg_changes_since(bigint, integer) to service_role;
