// Minimal Supabase REST (PostgREST) client over fetch, so the Edge chat route
// gets memory without bundling supabase-js. Server only: it uses the
// service-role / secret key, which must never reach the browser.
// Runs on Edge and Node.js.

import { withTimeout } from "../agents/search-agent";
import { getEnv } from "../env";

/** Supabase call failed. The message never contains the key or the request body. */
export class MemoryError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "MemoryError";
    this.status = status;
  }
}

export interface SupabaseRequest {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Extra PostgREST headers, e.g. `Prefer`. */
  headers?: Record<string, string>;
  signal?: AbortSignal | null;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 8_000;

export function memoryConfigured(): boolean {
  return getEnv().memory.enabled;
}

/**
 * Calls `/rest/v1/<path>` and returns the parsed JSON body (null for 204).
 * New `sb_secret_…` keys go in `apikey` only; legacy service-role JWTs also
 * go in `Authorization`, which is what makes PostgREST run as service_role.
 */
export async function supabaseRest<T = unknown>(path: string, request: SupabaseRequest = {}): Promise<T> {
  return (await supabaseRestResponse<T>(path, request)).data;
}

/** Same as supabaseRest, with the response headers (e.g. `Content-Range` for `Prefer: count=exact`). */
export async function supabaseRestResponse<T = unknown>(
  path: string,
  request: SupabaseRequest = {},
): Promise<{ data: T; headers: Headers }> {
  const { memory } = getEnv();
  if (!memory.supabaseUrl || !memory.serviceKey) throw new MemoryError("memory not configured");

  const headers: Record<string, string> = {
    apikey: memory.serviceKey,
    accept: "application/json",
    ...request.headers,
  };
  if (memory.serviceKey.startsWith("eyJ")) headers.authorization = `Bearer ${memory.serviceKey}`;
  if (request.body !== undefined) headers["content-type"] = "application/json";

  const signal = withTimeout(request.timeoutMs ?? DEFAULT_TIMEOUT_MS, request.signal);

  let res: Response;
  try {
    res = await fetch(`${memory.supabaseUrl}/rest/v1/${path}`, {
      method: request.method ?? "GET",
      headers,
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      signal,
      cache: "no-store",
    });
  } catch (error) {
    throw new MemoryError(failureReason(error));
  }

  if (!res.ok) {
    // PostgREST errors are {code, message}; keep only the code (messages can echo data).
    let code = "";
    try {
      const data = (await res.json()) as { code?: unknown };
      if (typeof data.code === "string") code = ` ${data.code.slice(0, 20)}`;
    } catch {
      // not JSON
    }
    throw new MemoryError(`HTTP ${res.status}${code}`, res.status);
  }
  if (res.status === 204) return { data: null as T, headers: res.headers };
  // The timeout covers the body too: a large page can arrive in 0.5 s of headers and many seconds of body.
  let text: string;
  try {
    text = await res.text();
  } catch (error) {
    throw new MemoryError(failureReason(error));
  }
  return { data: (text ? JSON.parse(text) : null) as T, headers: res.headers };
}

/** A fetch or body read that failed: "timeout", "aborted" (the caller cancelled) or "network error". */
function failureReason(error: unknown): "timeout" | "aborted" | "network error" {
  const name = error && typeof error === "object" && "name" in error ? String((error as { name: unknown }).name) : "";
  return name === "TimeoutError" ? "timeout" : name === "AbortError" ? "aborted" : "network error";
}
