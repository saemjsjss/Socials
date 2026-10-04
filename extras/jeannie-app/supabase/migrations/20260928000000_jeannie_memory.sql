-- Jeannie memory: uploaded markdown / JSON Lines knowledge, searchable with
-- Postgres full-text search, plus per-chat state for the audit approval flow.
--
-- Access model: RLS is on for every table and there are NO policies, so the
-- anon and authenticated roles (the public API keys) can read or write nothing.
-- Only Jeannie's server, using the service-role / secret key, gets through.
-- Functions are revoked from public roles for the same reason.

-- ─── Documents and chunks ────────────────────────────────────────────────────

create table if not exists public.memory_documents (
  id          uuid primary key default gen_random_uuid(),
  source_name text not null unique,                  -- upload file name; re-uploading replaces it
  title       text not null,
  kind        text not null check (kind in ('markdown', 'jsonl')),
  pinned      boolean not null default false,        -- always included in Jeannie's prompt
  content     text not null,
  bytes       integer not null default 0,
  chunks      integer not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.memory_chunks (
  id          bigint generated always as identity primary key,
  document_id uuid not null references public.memory_documents (id) on delete cascade,
  ord         integer not null,
  heading     text not null default '',
  content     text not null,
  record_id   text,                                  -- JSONL record id, stable across re-uploads
  type        text,
  entity      text,
  tags        text[] not null default '{}',
  keywords    text not null default '',              -- tags joined, so the generated column stays immutable
  fts         tsvector generated always as (
                setweight(to_tsvector('simple'::regconfig, coalesce(heading, '') || ' ' || coalesce(entity, '') || ' ' || keywords), 'A')
                || setweight(to_tsvector('simple'::regconfig, content), 'B')
              ) stored,
  unique (document_id, ord)
);

create unique index if not exists memory_chunks_record_idx on public.memory_chunks (document_id, record_id) where record_id is not null;
create index if not exists memory_chunks_fts_idx on public.memory_chunks using gin (fts);
create index if not exists memory_documents_pinned_idx on public.memory_documents (updated_at desc) where pinned;

alter table public.memory_documents enable row level security;
alter table public.memory_chunks enable row level security;

-- ─── Audit approval state (Telegram sends single messages, so state lives here) ─

create table if not exists public.jeannie_sessions (
  chat_key   text primary key,                       -- e.g. "telegram:123456789"
  state      text not null default 'idle' check (state in ('idle', 'awaiting_approval')),
  pending    text,                                   -- the audit reply awaiting approval
  updated_at timestamptz not null default now()
);

create table if not exists public.jeannie_audit_log (
  id         bigint generated always as identity primary key,
  chat_key   text not null,
  decision   text not null check (decision in ('approved', 'rejected')),
  items      jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.jeannie_sessions enable row level security;
alter table public.jeannie_audit_log enable row level security;

-- ─── Upsert a document and replace its chunks in one transaction ─────────────

create or replace function public.upsert_memory_document(
  p_source_name text,
  p_title       text,
  p_kind        text,
  p_pinned      boolean,
  p_content     text,
  p_chunks      jsonb                                -- [{ord, heading, content, record_id?, type?, entity?, tags?}]
) returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  doc_id uuid;
begin
  insert into public.memory_documents as d (source_name, title, kind, pinned, content, bytes, chunks)
  values (p_source_name, p_title, p_kind, p_pinned, p_content, octet_length(p_content), jsonb_array_length(p_chunks))
  on conflict (source_name) do update
    set title = excluded.title, kind = excluded.kind, pinned = excluded.pinned, content = excluded.content,
        bytes = excluded.bytes, chunks = excluded.chunks, updated_at = now()
  returning d.id into doc_id;

  delete from public.memory_chunks where document_id = doc_id;

  insert into public.memory_chunks (document_id, ord, heading, content, record_id, type, entity, tags, keywords)
  select doc_id,
         (c ->> 'ord')::integer,
         coalesce(c ->> 'heading', ''),
         c ->> 'content',
         c ->> 'record_id',
         c ->> 'type',
         c ->> 'entity',
         coalesce(array(select jsonb_array_elements_text(coalesce(c -> 'tags', '[]'::jsonb))), '{}'),
         coalesce((select string_agg(t, ' ') from jsonb_array_elements_text(coalesce(c -> 'tags', '[]'::jsonb)) as t), '')
  from jsonb_array_elements(p_chunks) as c;

  return doc_id;
end;
$$;

-- ─── Search: any term may match (prefix), more matching terms rank higher ────

create or replace function public.match_memory(terms text[], match_count integer default 5)
returns table (
  document_title text,
  source_name    text,
  heading        text,
  content        text,
  record_id      text,
  rank           real
)
language sql
stable
security invoker
set search_path = ''
as $$
  with cleaned as (
    -- Drop tsquery operators and quotes; the app already lowercases and splits terms.
    select distinct regexp_replace(lower(t), '[\s&|!():*<>''\\]+', '', 'g') as term
    from unnest(terms) as t
  ),
  q as (
    select to_tsquery('simple'::regconfig, string_agg(term || ':*', ' | ')) as tsq
    from cleaned
    where term <> ''
  )
  select d.title, d.source_name, c.heading, c.content, c.record_id, ts_rank_cd(c.fts, q.tsq) as rank
  from q
  join public.memory_chunks c on c.fts @@ q.tsq
  join public.memory_documents d on d.id = c.document_id
  where q.tsq is not null
  order by rank desc, c.document_id, c.ord
  limit least(greatest(match_count, 1), 20);
$$;

revoke all on function public.upsert_memory_document(text, text, text, boolean, text, jsonb) from public, anon, authenticated;
revoke all on function public.match_memory(text[], integer) from public, anon, authenticated;
grant execute on function public.upsert_memory_document(text, text, text, boolean, text, jsonb) to service_role;
grant execute on function public.match_memory(text[], integer) to service_role;
