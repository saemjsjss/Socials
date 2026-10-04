// Whether Jeannie can be reached (spec D10): the browser's own online flag plus
// whether the API answered. Offline means "show the banner and disable the
// input", never "answer from the device copy". Pure, so it is tested without a
// DOM; the hook (src/hooks/useOnlineStatus.ts) feeds it events.

export interface Reachability {
  /** navigator.onLine and the window's online/offline events. */
  browserOnline: boolean;
  /** The last API request got an answer (any HTTP status); false after one never reached the server. */
  apiReachable: boolean;
}

export type ReachabilityEvent = { type: "browser"; online: boolean } | { type: "api"; reachable: boolean };

/** Before hydration and before any request: assume online, so the server markup has no banner. */
export const INITIAL_REACHABILITY: Reachability = { browserOnline: true, apiReachable: true };

export function reduceReachability(state: Reachability, event: ReachabilityEvent): Reachability {
  if (event.type === "browser") {
    if (state.browserOnline === event.online) return state;
    return { ...state, browserOnline: event.online };
  }
  if (state.apiReachable === event.reachable) return state;
  return { ...state, apiReachable: event.reachable };
}

export function isOffline(state: Reachability): boolean {
  return !state.browserOnline || !state.apiReachable;
}

/**
 * A request that never reached the server: status 0 with code "network_error"
 * (fetch itself threw). A timeout is not one: a long answer can time out on a
 * working connection.
 */
export function isUnreachable(error: unknown): boolean {
  if (!(error instanceof Error) || error.name !== "ApiRequestError") return false;
  const e = error as Error & { status?: unknown; code?: unknown };
  return e.status === 0 && e.code === "network_error";
}

const FIRST_PROBE_MS = 2_000;
const MAX_PROBE_MS = 30_000;

/** Delay before re-probing GET /api/status after `attempt` failed probes: 2 s, 4 s, 8 s ... up to 30 s. */
export function probeDelay(attempt: number): number {
  const n = Math.max(0, Math.min(10, Math.trunc(attempt)));
  return Math.min(MAX_PROBE_MS, FIRST_PROBE_MS * 2 ** n);
}

/**
 * The one send the HUD uses (composer, quick commands, smart-home tiles, DAILY
 * REPORT, voice): nothing is sent while offline, and the caller is told (false).
 */
export function sendUnlessOffline<A extends unknown[]>(isOffline: () => boolean, send: (...args: A) => boolean): (...args: A) => boolean {
  return (...args: A) => (isOffline() ? false : send(...args));
}

/** Composer rule: something to send (text or an image), not still preparing an image, and online. */
export function canSendMessage(input: { draft: string; hasAttachment: boolean; preparing: boolean; disabled: boolean }): boolean {
  return (input.draft.trim().length > 0 || input.hasAttachment) && !input.preparing && !input.disabled;
}

/**
 * Re-probes until `probe` resolves: after 2 s, then 4, 8, 16 and every 30 s
 * (probeDelay). Returns a stop function. The timers are injected so the loop is
 * tested without a browser; useOnlineStatus runs it with setTimeout.
 */
export function startProbeLoop(
  probe: () => Promise<unknown>,
  timers: { set: (run: () => void, ms: number) => unknown; clear: (handle: unknown) => void } = {
    set: (run, ms) => setTimeout(run, ms),
    clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  },
): () => void {
  let attempt = 0;
  let stopped = false;
  let handle: unknown;
  const schedule = () => {
    handle = timers.set(() => {
      probe().catch(() => {
        if (stopped) return;
        attempt += 1;
        schedule();
      });
    }, probeDelay(attempt));
  };
  schedule();
  return () => {
    stopped = true;
    if (handle !== undefined) timers.clear(handle);
  };
}

/** The banner's words, in both of the HUD's languages. */
export const OFFLINE_LINE = {
  en: "Offline: Jeannie needs a connection",
  ko: "오프라인: 지니는 인터넷 연결이 필요해요",
} as const;
