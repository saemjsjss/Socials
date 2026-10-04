// Typed fetch wrappers for the HUD. Every call carries the stored access key and
// a timeout, and every failure surfaces as an ApiRequestError so the UI can show
// a calm system line instead of crashing. User-initiated aborts are rethrown as
// the original AbortError so callers can tell "stopped" from "failed".

import {
  ACCESS_KEY_HEADER,
  CHAT_HEADERS,
  TTS_ENGINE_HEADER,
  type AgentId,
  type ApiError,
  type ChatRequestBody,
  type HangeulDataStatus,
  type LlmProvider,
  type MemoryDocument,
  type ResolvedLang,
  type SessionGreeting,
  type SourceLink,
  type SystemStatus,
  type TtsEngine,
  type TtsRequestBody,
} from "@/lib/types";
import type { ChangesPage, SnapshotPage } from "@/lib/hangeul/store";
import type { HgRun } from "@/lib/hangeul/types";
import { decodeHeaderJson } from "@/lib/utils";
import { isUnreachable } from "./reachability";

const ACCESS_KEY_STORAGE = "jeannie.accessKey";

const STATUS_TIMEOUT_MS = 8_000;
const CHAT_TIMEOUT_MS = 180_000; // covers the whole streamed answer, not just the headers
const TTS_TIMEOUT_MS = 30_000;
const HANGEUL_TIMEOUT_MS = 15_000;
const HANGEUL_SYNC_TIMEOUT_MS = 60_000;
const HANGEUL_CHANGES_LIMIT = 200;
const MEMORY_TIMEOUT_MS = 30_000;

// ── Access key storage ───────────────────────────────────────────────────────
// Storage can throw (private mode, blocked site data), so every access is guarded,
// and the key is also kept in memory: with storage blocked it still works until reload.

/** Printable ASCII: a header value must be a ByteString, or fetch throws before sending. */
const ACCESS_KEY_PATTERN = /^[\x20-\x7E]{1,256}$/;

/** The key in use; `undefined` until the first read from storage. */
let memoryKey: string | null | undefined;

export function isValidAccessKey(key: string): boolean {
  return ACCESS_KEY_PATTERN.test(key.trim());
}

export function readAccessKey(): string | null {
  if (memoryKey !== undefined) return memoryKey;
  if (typeof window === "undefined") return null;
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(ACCESS_KEY_STORAGE);
  } catch {
    stored = null;
  }
  memoryKey = stored && isValidAccessKey(stored) ? stored.trim() : null;
  return memoryKey;
}

/** Stores a valid key (or clears it with null); an invalid key is ignored. */
export function writeAccessKey(key: string | null): void {
  if (key !== null && !isValidAccessKey(key)) return;
  memoryKey = key === null ? null : key.trim();
  try {
    if (memoryKey) window.localStorage.setItem(ACCESS_KEY_STORAGE, memoryKey);
    else window.localStorage.removeItem(ACCESS_KEY_STORAGE);
  } catch {
    // Not persisted: the in-memory copy serves this page until it is reloaded.
  }
}

// ── Errors ──────────────────────────────────────────────────────────────────

export class ApiRequestError extends Error {
  /** HTTP status, or 0 for network failures and timeouts. */
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }

  get needsAccessKey(): boolean {
    return this.status === 401 && this.code === "access_key_required";
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function fallbackMessage(status: number): string {
  if (status === 404) return "Endpoint not deployed yet.";
  if (status === 401) return "Access key required.";
  if (status === 413) return "Payload too large.";
  if (status === 429) return "Rate limited. Try again in a moment.";
  if (status >= 500) return "Upstream service error.";
  return `Request failed (${status}).`;
}

async function errorFromResponse(res: Response): Promise<ApiRequestError> {
  let body: Partial<ApiError> | null = null;
  try {
    body = (await res.json()) as Partial<ApiError>;
  } catch {
    body = null;
  }
  const code = typeof body?.code === "string" ? body.code : `http_${res.status}`;
  const message = typeof body?.error === "string" && body.error ? body.error : fallbackMessage(res.status);
  return new ApiRequestError(res.status, code, message);
}

// ── Reachability ────────────────────────────────────────────────────────────
// Every request reports whether it reached the server, so the offline banner
// (useOnlineStatus) knows without polling while things work.

type ReachabilityListener = (reachable: boolean) => void;

const reachabilityListeners = new Set<ReachabilityListener>();

/** Called with false when a request could not reach the server at all, true when one got any answer. */
export function onReachability(listener: ReachabilityListener): () => void {
  reachabilityListeners.add(listener);
  return () => {
    reachabilityListeners.delete(listener);
  };
}

function reportReachability(reachable: boolean): void {
  for (const listener of reachabilityListeners) listener(reachable);
}

function reportFailure(error: unknown): unknown {
  if (isUnreachable(error)) reportReachability(false);
  return error;
}

// ── Fetch core ──────────────────────────────────────────────────────────────

/** Combines the caller's signal with a timeout. AbortSignal.any is missing in older Safari. */
function withTimeout(ms: number, signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  if (!signal) return timeout;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([signal, timeout]);
  const controller = new AbortController();
  const forward = (source: AbortSignal) => () => controller.abort(source.reason);
  for (const source of [signal, timeout]) {
    if (source.aborted) controller.abort(source.reason);
    else source.addEventListener("abort", forward(source), { once: true });
  }
  return controller.signal;
}

function authHeaders(extra?: Record<string, string>): Headers {
  const headers = new Headers(extra);
  const key = readAccessKey();
  if (key) headers.set(ACCESS_KEY_HEADER, key);
  return headers;
}

async function request(
  path: string,
  init: { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown; signal?: AbortSignal; timeoutMs: number },
): Promise<Response> {
  let res: Response;
  try {
    // FormData sets its own multipart content type (with the boundary).
    const form = typeof FormData !== "undefined" && init.body instanceof FormData;
    const json = init.body !== undefined && !form;
    const headers = authHeaders(json ? { "content-type": "application/json" } : undefined);
    res = await fetch(path, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : form ? (init.body as FormData) : JSON.stringify(init.body),
      signal: withTimeout(init.timeoutMs, init.signal),
      cache: "no-store",
    });
  } catch (error) {
    throw reportFailure(normalizeFetchError(error, init.signal));
  }
  // Any HTTP answer, even an error, means the server was reached.
  reportReachability(true);
  if (!res.ok) throw await errorFromResponse(res);
  return res;
}

function normalizeFetchError(error: unknown, userSignal?: AbortSignal): unknown {
  if (userSignal?.aborted) return new DOMException("Aborted by user", "AbortError");
  if (error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError")) {
    return new ApiRequestError(0, "timeout", "The uplink timed out.");
  }
  if (error instanceof ApiRequestError) return error;
  return new ApiRequestError(0, "network_error", "Uplink unreachable. Check your connection.");
}

// ── Status ──────────────────────────────────────────────────────────────────

export async function fetchSystemStatus(signal?: AbortSignal): Promise<SystemStatus> {
  const res = await request("/api/status", { signal, timeoutMs: STATUS_TIMEOUT_MS });
  try {
    return (await res.json()) as SystemStatus;
  } catch {
    throw new ApiRequestError(res.status, "invalid_response", "Status feed returned malformed data.");
  }
}

// ── Session greeting ────────────────────────────────────────────────────────

/**
 * The opening line. `awayMs` (time since the user was last seen) lets the
 * server mention the absence; the server answers within ~4 s either way.
 */
export async function fetchSessionGreeting(options: { awayMs?: number; signal?: AbortSignal } = {}): Promise<SessionGreeting> {
  const away = options.awayMs;
  const query = away !== undefined && Number.isFinite(away) && away >= 0 ? `?awayMs=${Math.round(away)}` : "";
  const res = await request(`/api/session${query}`, { signal: options.signal, timeoutMs: STATUS_TIMEOUT_MS });
  try {
    return (await res.json()) as SessionGreeting;
  } catch {
    throw new ApiRequestError(res.status, "invalid_response", "Session greeting returned malformed data.");
  }
}

// ── Memory ──────────────────────────────────────────────────────────────────

export interface MemoryUploadResult {
  title: string;
  kind: "markdown" | "jsonl";
  chunks: number;
  issues: { line: number; message: string }[];
}

export async function listMemory(signal?: AbortSignal): Promise<MemoryDocument[]> {
  const res = await request("/api/memory", { signal, timeoutMs: MEMORY_TIMEOUT_MS });
  const body = (await res.json().catch(() => null)) as { documents?: MemoryDocument[] } | null;
  return Array.isArray(body?.documents) ? body.documents : [];
}

export async function uploadMemory(file: File, pinned: boolean): Promise<MemoryUploadResult> {
  const form = new FormData();
  form.set("file", file);
  form.set("pinned", String(pinned));
  const res = await request("/api/memory", { method: "POST", body: form, timeoutMs: MEMORY_TIMEOUT_MS });
  const body = (await res.json().catch(() => null)) as { document?: MemoryUploadResult } | null;
  if (!body?.document) throw new ApiRequestError(res.status, "invalid_response", "Memory upload returned malformed data.");
  return body.document;
}

export async function setMemoryPinned(id: string, pinned: boolean): Promise<void> {
  await request(`/api/memory?id=${encodeURIComponent(id)}`, { method: "PATCH", body: { pinned }, timeoutMs: MEMORY_TIMEOUT_MS });
}

export async function deleteMemory(id: string): Promise<void> {
  await request(`/api/memory?id=${encodeURIComponent(id)}`, { method: "DELETE", timeoutMs: MEMORY_TIMEOUT_MS });
}

// ── Chat ────────────────────────────────────────────────────────────────────

export interface ChatStreamMeta {
  agent: AgentId | null;
  lang: ResolvedLang | null;
  provider: LlmProvider | null;
  sources: SourceLink[];
}

const AGENTS: readonly AgentId[] = ["iot", "audit", "search", "vision", "hangeul", "core", "offline"];
const LANGS: readonly ResolvedLang[] = ["en", "ko", "bilingual"];
const PROVIDERS: readonly LlmProvider[] = ["deepseek", "anthropic", "openai", "ollama", "none"];

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  const normalized = value?.trim().toLowerCase();
  return normalized && (allowed as readonly string[]).includes(normalized) ? (normalized as T) : null;
}

function safeSources(value: unknown): SourceLink[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (item): item is SourceLink =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as SourceLink).url === "string" &&
        /^https?:\/\//i.test((item as SourceLink).url),
    )
    .map((item) => ({ url: item.url, title: typeof item.title === "string" && item.title ? item.title : item.url }))
    .slice(0, 5);
}

export function readChatMeta(headers: Headers): ChatStreamMeta {
  return {
    agent: pick(headers.get(CHAT_HEADERS.agent), AGENTS),
    lang: pick(headers.get(CHAT_HEADERS.lang), LANGS),
    provider: pick(headers.get(CHAT_HEADERS.provider), PROVIDERS),
    sources: safeSources(decodeHeaderJson<unknown>(headers.get(CHAT_HEADERS.sources))),
  };
}

export interface ChatStream {
  meta: ChatStreamMeta;
  /** Decoded text chunks as they arrive. */
  chunks: AsyncGenerator<string, void, undefined>;
}

/** POST /api/chat. Resolves once headers arrive; iterate `chunks` for the streamed answer. */
export async function openChatStream(body: ChatRequestBody, signal?: AbortSignal): Promise<ChatStream> {
  const res = await request("/api/chat", { method: "POST", body, signal, timeoutMs: CHAT_TIMEOUT_MS });
  if (!res.body) throw new ApiRequestError(res.status, "empty_response", "The reply stream was empty.");
  return { meta: readChatMeta(res.headers), chunks: readTextStream(res.body, signal) };
}

async function* readTextStream(stream: ReadableStream<Uint8Array>, signal?: AbortSignal) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        throw reportFailure(normalizeFetchError(error, signal));
      }
      if (result.done) break;
      const text = decoder.decode(result.value, { stream: true });
      if (text) yield text;
    }
    const tail = decoder.decode();
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}

// ── Voice ───────────────────────────────────────────────────────────────────

export interface SpeechAudio {
  audio: Blob;
  engine: TtsEngine;
}

/** POST /api/tts. A 503 (`tts_unavailable`) means "use the browser voice". */
export async function requestSpeech(payload: TtsRequestBody, signal?: AbortSignal): Promise<SpeechAudio> {
  const res = await request("/api/tts", { method: "POST", body: payload, signal, timeoutMs: TTS_TIMEOUT_MS });
  const type = res.headers.get("content-type") ?? "";
  if (!type.startsWith("audio/"))
    throw new ApiRequestError(res.status, "invalid_response", "Voice engine sent no audio.");
  let audio: Blob;
  try {
    audio = await res.blob();
  } catch (error) {
    throw normalizeFetchError(error, signal);
  }
  const engine = res.headers.get(TTS_ENGINE_HEADER) === "elevenlabs" ? "elevenlabs" : "edge";
  return { audio, engine };
}

// ── Hangeul data ───────────────────────────────────────────────────────────

// The device copy (ticket 7). Pages are ~3 MB, a few seconds each on a phone.

async function hangeulJson<T>(path: string, what: string, signal: AbortSignal | undefined, valid: (body: T) => boolean): Promise<T> {
  const res = await request(path, { signal, timeoutMs: HANGEUL_SYNC_TIMEOUT_MS });
  let body: T;
  try {
    body = (await res.json()) as T;
  } catch (error) {
    // Malformed JSON, or the body stopped arriving (dropped connection, timeout, abort).
    if (error instanceof SyntaxError) throw new ApiRequestError(res.status, "invalid_response", `${what} returned malformed data.`);
    throw reportFailure(normalizeFetchError(error, signal));
  }
  if (!body || !valid(body)) throw new ApiRequestError(res.status, "invalid_response", `${what} returned malformed data.`);
  return body;
}

/** GET /api/hangeul/snapshot (first page) or ?cursor=<next>: one page of the full dump. */
export function fetchHangeulSnapshot(cursor: string | null, signal?: AbortSignal): Promise<SnapshotPage> {
  const path = cursor ? `/api/hangeul/snapshot?cursor=${encodeURIComponent(cursor)}` : "/api/hangeul/snapshot";
  return hangeulJson<SnapshotPage>(path, "The Hangeul snapshot", signal, (b) => Array.isArray(b.records) && Array.isArray(b.chunks));
}

/** GET /api/hangeul/changes?since=<seq>: the change log after the device's cursor. */
export function fetchHangeulChanges(since: number, signal?: AbortSignal): Promise<ChangesPage> {
  const path = `/api/hangeul/changes?since=${Math.max(0, Math.trunc(since))}&limit=${HANGEUL_CHANGES_LIMIT}`;
  return hangeulJson<ChangesPage>(path, "The Hangeul change log", signal, (b) => Array.isArray(b.changes) && typeof b.next_seq === "number");
}

/** GET /api/hangeul/runs: the bot's recent runs, which date the device's "as of" lines. */
export async function fetchHangeulRuns(signal?: AbortSignal): Promise<HgRun[]> {
  const body = await hangeulJson<{ runs: HgRun[] }>("/api/hangeul/runs", "The Hangeul runs", signal, (b) => Array.isArray(b.runs));
  return body.runs;
}

/** GET /api/hangeul: how much data Hangeul BOT has published, its latest runs and latest brief. */
export async function fetchHangeulData(signal?: AbortSignal): Promise<HangeulDataStatus> {
  const res = await request("/api/hangeul", { signal, timeoutMs: HANGEUL_TIMEOUT_MS });
  try {
    const data = (await res.json()) as Partial<HangeulDataStatus>;
    if (data.configured !== true || typeof data.records !== "number" || !Array.isArray(data.lastRuns)) throw new Error("missing fields");
    return data as HangeulDataStatus;
  } catch {
    throw new ApiRequestError(res.status, "invalid_response", "Hangeul data status returned malformed data.");
  }
}
