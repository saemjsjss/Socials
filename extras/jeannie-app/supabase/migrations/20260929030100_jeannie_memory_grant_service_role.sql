-- New Supabase projects no longer grant table access to the API roles
-- automatically (changelog, 28 Apr 2026: "Tables not exposed to Data and
-- GraphQL API automatically"). The memory tables relied on that default for the
-- service role, so grant it explicitly. Idempotent; a no-op on older projects.

grant select, insert, update, delete
  on table public.memory_documents, public.memory_chunks, public.jeannie_sessions, public.jeannie_audit_log
  to service_role;
grant usage, select on sequence public.memory_chunks_id_seq, public.jeannie_audit_log_id_seq to service_role;
