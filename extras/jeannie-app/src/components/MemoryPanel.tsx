"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, Pin, PinOff, Trash, Upload } from "lucide-react";
import { ApiRequestError, deleteMemory, isAbortError, listMemory, setMemoryPinned, uploadMemory } from "@/lib/client/api";
import type { MemoryDocument } from "@/lib/types";
import { cn } from "@/lib/utils";
import { HudPanel } from "./HudPanel";

const ACCEPT = ".md,.markdown,.txt,.jsonl,.ndjson,text/markdown,text/plain,application/x-ndjson";
const MAX_BYTES = 1024 * 1024;

interface MemoryPanelProps {
  /** Supabase memory is configured on the server. */
  configured: boolean;
  /** The server has an access key (memory refuses to run without one). */
  accessKeyRequired: boolean;
  hasAccessKey: boolean;
  statusReady: boolean;
  /** Adds a system line to the chat (upload results, errors). */
  onNotice: (text: string) => void;
}

function errorText(error: unknown): string {
  return error instanceof ApiRequestError ? error.message : "Memory request failed.";
}

function sizeLabel(bytes: number): string {
  return bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`;
}

/** Jeannie's long-term memory: markdown / JSON Lines notes stored in Supabase. */
export function MemoryPanel({ configured, accessKeyRequired, hasAccessKey, statusReady, onNotice }: MemoryPanelProps) {
  const [documents, setDocuments] = useState<MemoryDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pinUploads, setPinUploads] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const blocked = !configured
    ? "Not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
    : !accessKeyRequired
      ? "Locked: set JEANNIE_ACCESS_KEY on the server to use memory."
      : !hasAccessKey
        ? "Locked: access key required."
        : null;

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      setDocuments(await listMemory(signal));
      setError(null);
    } catch (err) {
      if (!isAbortError(err)) setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    if (!statusReady || blocked) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [statusReady, blocked, refresh]);

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    for (const file of Array.from(files)) {
      if (file.size > MAX_BYTES) {
        onNotice(`Memory: ${file.name} is larger than 1 MB, skipped.`);
        continue;
      }
      try {
        const result = await uploadMemory(file, pinUploads);
        const skipped = result.issues.length ? ` (${result.issues.length} line${result.issues.length === 1 ? "" : "s"} skipped)` : "";
        onNotice(`Memory: stored ${file.name} as ${result.chunks} note${result.chunks === 1 ? "" : "s"}${pinUploads ? ", pinned" : ""}${skipped}.`);
      } catch (err) {
        onNotice(`Memory: ${file.name} was not stored. ${errorText(err)}`);
      }
    }
    if (inputRef.current) inputRef.current.value = "";
    await refresh();
    setBusy(false);
  };

  const togglePin = async (doc: MemoryDocument) => {
    setBusy(true);
    try {
      await setMemoryPinned(doc.id, !doc.pinned);
      await refresh();
    } catch (err) {
      onNotice(`Memory: ${errorText(err)}`);
    }
    setBusy(false);
  };

  const remove = async (doc: MemoryDocument) => {
    if (!window.confirm(`Forget "${doc.source_name}"? Jeannie will no longer remember it.`)) return;
    setBusy(true);
    try {
      await deleteMemory(doc.id);
      await refresh();
    } catch (err) {
      onNotice(`Memory: ${errorText(err)}`);
    }
    setBusy(false);
  };

  const actions = (
    <>
      <label className="flex cursor-pointer items-center gap-1 font-mono text-[0.58rem] tracking-[0.12em] text-petal-soft/70">
        <input
          type="checkbox"
          checked={pinUploads}
          onChange={(e) => setPinUploads(e.target.checked)}
          disabled={Boolean(blocked) || busy}
          className="accent-[#ff007f]"
        />
        PIN
      </label>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={Boolean(blocked) || busy}
        aria-label="Upload markdown or JSON Lines files to Jeannie's memory"
        title="Upload .md / .jsonl"
        className="hud-btn -my-1 border-transparent bg-transparent lg:h-8 lg:min-h-0 lg:w-8 lg:min-w-0"
      >
        <Upload aria-hidden="true" className={cn("h-3.5 w-3.5", busy && "animate-pulse")} />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => void upload(e.target.files)}
      />
    </>
  );

  let body;
  if (blocked) {
    body = <p className="text-[0.72rem] leading-relaxed text-petal-soft/65">{blocked}</p>;
  } else if (error) {
    body = <p className="text-[0.72rem] leading-relaxed text-neon-hot">{error}</p>;
  } else if (documents === null) {
    body = <p className="font-mono text-[0.66rem] tracking-[0.12em] text-petal-soft/60">LOADING…</p>;
  } else if (documents.length === 0) {
    body = (
      <p className="text-[0.72rem] leading-relaxed text-petal-soft/65">
        No notes yet. Upload .md or .jsonl files; pinned notes (like your profile) are always in mind.
      </p>
    );
  } else {
    body = (
      <ul className="max-h-48 divide-y divide-neon/10 overflow-y-auto overscroll-contain pr-1">
        {documents.map((doc) => (
          <li key={doc.id} className="flex min-h-[28px] items-center gap-1.5 py-[3px]">
            <span className={cn("led", doc.pinned ? "led-on" : "")} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[0.72rem] text-petal-soft" title={doc.title}>
                {doc.source_name}
              </span>
              <span className="block font-mono text-[0.56rem] tracking-[0.1em] text-petal-soft/50">
                {doc.kind.toUpperCase()} · {doc.chunks} NOTE{doc.chunks === 1 ? "" : "S"} · {sizeLabel(doc.bytes)}
              </span>
            </span>
            <button
              type="button"
              onClick={() => void togglePin(doc)}
              disabled={busy}
              aria-label={doc.pinned ? `Unpin ${doc.source_name}` : `Pin ${doc.source_name}`}
              data-active={doc.pinned}
              className="hud-btn h-7 min-h-0 w-7 min-w-0"
            >
              {doc.pinned ? <Pin aria-hidden="true" className="h-3 w-3" /> : <PinOff aria-hidden="true" className="h-3 w-3" />}
            </button>
            <button
              type="button"
              onClick={() => void remove(doc)}
              disabled={busy}
              aria-label={`Forget ${doc.source_name}`}
              className="hud-btn h-7 min-h-0 w-7 min-w-0"
            >
              <Trash aria-hidden="true" className="h-3 w-3" />
            </button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <HudPanel title="Memory" subtitle="기억" icon={<Brain />} actions={actions} delay={0.36}>
      {body}
    </HudPanel>
  );
}
