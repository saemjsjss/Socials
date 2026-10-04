-- Defense in depth: Jeannie's memory is server-only (service_role). RLS with no
-- policies already blocks the public roles; also drop their table privileges so
-- an accidentally added policy can never expose the notes.
revoke all on table public.memory_documents, public.memory_chunks, public.jeannie_sessions, public.jeannie_audit_log from anon, authenticated;
revoke all on sequence public.memory_chunks_id_seq, public.jeannie_audit_log_id_seq from anon, authenticated;
