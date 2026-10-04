import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { describe, expect, it, vi } from "vitest";
import manifest from "@/app/manifest";
import { ApiRequestError } from "@/lib/client/api";
import {
  INITIAL_REACHABILITY,
  isOffline,
  isUnreachable,
  OFFLINE_LINE,
  probeDelay,
  reduceReachability,
} from "@/lib/client/reachability";

const root = fileURLToPath(new URL("..", import.meta.url));

/** Width and height from a PNG's IHDR chunk. */
function pngSize(path: string): [number, number] {
  const bytes = readFileSync(`${root}/public${path}`);
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

interface SwGlobals {
  strategyFor: (url: URL, method: string, origin: string) => string | null;
  parseRange: (header: string, size: number) => { start: number; end: number } | null;
  rangeResponse: (cached: Response, header: string) => Promise<Response>;
  listeners: Record<string, unknown>;
}

/** Evaluate public/sw.js in a sandbox and expose its top-level functions. */
function loadServiceWorker(): SwGlobals {
  const listeners: Record<string, unknown> = {};
  const context = vm.createContext({
    self: {
      location: { origin: "https://jeannie.test" },
      addEventListener: (type: string, fn: unknown) => (listeners[type] = fn),
    },
    URL,
    Headers,
    Response,
    Set,
  });
  vm.runInContext(readFileSync(`${root}/public/sw.js`, "utf8"), context);
  return { ...(context as unknown as SwGlobals), listeners };
}

describe("web app manifest", () => {
  const m = manifest();

  it("is installable as a standalone portrait app", () => {
    expect(m).toMatchObject({ name: "Jeannie", short_name: "Jeannie", display: "standalone", orientation: "portrait", start_url: "/" });
    expect(m.theme_color).toMatch(/^#[0-9a-f]{6}$/i);
    expect(m.background_color).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("ships 192, 512 and maskable 512 icons that exist at their declared size", () => {
    const icons = m.icons ?? [];
    expect(icons.map((icon) => `${icon.sizes}:${icon.purpose}`)).toEqual(["192x192:any", "512x512:any", "512x512:maskable"]);
    for (const icon of icons) {
      const [w, h] = pngSize(icon.src);
      expect(`${w}x${h}`).toBe(icon.sizes);
    }
  });
});

describe("service worker", () => {
  const sw = loadServiceWorker();
  const origin = "https://jeannie.test";
  const strategy = (path: string, method = "GET", host = origin) => sw.strategyFor(new URL(path, host), method, origin);

  it("registers install, activate and fetch handlers", () => {
    expect(Object.keys(sw.listeners).sort()).toEqual(["activate", "fetch", "install"]);
  });

  it("routes requests by path", () => {
    expect(strategy("/api/chat")).toBe("network-only");
    expect(strategy("/api/greeting?awayMs=5")).toBe("network-only");
    expect(strategy("/avatar/idle.mp4")).toBe("cache-first");
    // Versioned clip URLs (CLIP_VERSION) stay cache-first; the query only changes the cache key.
    expect(strategy("/avatar/idle.mp4?v=k3")).toBe("cache-first");
    expect(strategy("/avatar/air_kiss.jpg")).toBe("cache-first");
    expect(strategy("/icons/icon-192.png")).toBe("cache-first");
    expect(strategy("/_next/static/chunks/main.js")).toBe("stale-while-revalidate");
    expect(strategy("/audio/beep.mp3")).toBeNull();
    expect(strategy("/avatar/nested/x.mp4")).toBeNull();
  });

  it("leaves non-GET and cross-origin requests alone", () => {
    expect(strategy("/avatar/idle.mp4", "POST")).toBeNull();
    expect(strategy("/avatar/idle.mp4", "GET", "https://cdn.example")).toBeNull();
  });

  it("parses single byte ranges", () => {
    expect(sw.parseRange("bytes=0-", 100)).toEqual({ start: 0, end: 99 });
    expect(sw.parseRange("bytes=10-19", 100)).toEqual({ start: 10, end: 19 });
    expect(sw.parseRange("bytes=90-500", 100)).toEqual({ start: 90, end: 99 });
    expect(sw.parseRange("bytes=-10", 100)).toEqual({ start: 90, end: 99 });
    expect(sw.parseRange("bytes=100-", 100)).toBeNull();
    expect(sw.parseRange("bytes=-", 100)).toBeNull();
    expect(sw.parseRange("bytes=0-1,5-6", 100)).toBeNull();
    expect(sw.parseRange("items=0-1", 100)).toBeNull();
  });

  it("slices a cached clip into a 206 partial response", async () => {
    const cached = new Response(new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]), { headers: { "Content-Type": "video/mp4" } });
    const res = await sw.rangeResponse(cached, "bytes=2-4");
    expect(res.status).toBe(206);
    expect(res.headers.get("Content-Range")).toBe("bytes 2-4/10");
    expect(res.headers.get("Content-Length")).toBe("3");
    expect(res.headers.get("Content-Type")).toBe("video/mp4");
    expect([...new Uint8Array(await res.arrayBuffer())]).toEqual([2, 3, 4]);
  });

  it("answers an unsatisfiable range with 416", async () => {
    const res = await sw.rangeResponse(new Response(new Uint8Array(4)), "bytes=9-");
    expect(res.status).toBe(416);
    expect(res.headers.get("Content-Range")).toBe("bytes */4");
  });

  it("routes every Hangeul API path to the network only", () => {
    for (const path of ["/api/hangeul", "/api/hangeul/snapshot", "/api/hangeul/snapshot?cursor=abc", "/api/hangeul/changes?since=0", "/api/hangeul/runs"]) {
      expect(strategy(path)).toBe("network-only");
    }
    expect(strategy("/api/hangeul/ask", "POST")).toBeNull();
  });
});

// ── The service worker never stores student data ─────────────────────────────

interface FakeFetchEvent {
  request: { url: string; method: string; mode: string; headers: Headers };
  respondWith: ReturnType<typeof vi.fn>;
  waitUntil: ReturnType<typeof vi.fn>;
}

/** A same-origin 200, typed "basic" as the browser would (clones too). */
function basic(body: string): Response {
  const res = new Response(body, { status: 200, headers: { "content-type": "application/json" } });
  Object.defineProperty(res, "type", { value: "basic" });
  const clone = res.clone.bind(res);
  Object.defineProperty(res, "clone", {
    value: () => {
      const copy = clone();
      Object.defineProperty(copy, "type", { value: "basic" });
      return copy;
    },
  });
  return res;
}

/** sw.js with a recording Cache Storage and a network that answers with (synthetic) student JSON. */
function loadServiceWorkerWithCaches() {
  const listeners: Record<string, (event: unknown) => void> = {};
  const stored: string[] = [];
  const cache = {
    put: vi.fn(async (request: string | { url: string }) => {
      stored.push(typeof request === "string" ? request : request.url);
    }),
    add: vi.fn(async (url: string) => {
      stored.push(url);
    }),
  };
  const caches = {
    open: vi.fn(async () => cache),
    match: vi.fn(async () => undefined),
    keys: vi.fn(async () => []),
    delete: vi.fn(async () => true),
  };
  const network = vi.fn(async () =>
    basic(JSON.stringify({ records: [{ kind: "student", student_name: "TEST STUDENT ONE", passport_no: "A00000001" }] })),
  );
  const context = vm.createContext({
    self: {
      location: { origin: "https://jeannie.test" },
      addEventListener: (type: string, fn: (event: unknown) => void) => (listeners[type] = fn),
      skipWaiting: vi.fn(),
      clients: { claim: vi.fn() },
    },
    caches,
    fetch: network,
    URL,
    Headers,
    Response,
    Set,
  });
  vm.runInContext(readFileSync(`${root}/public/sw.js`, "utf8"), context);
  const g = context as unknown as { putInCache: (request: string, response: Response) => Promise<void> };
  const dispatch = (path: string, method = "GET", mode = "cors"): FakeFetchEvent => {
    const event: FakeFetchEvent = {
      request: { url: `https://jeannie.test${path}`, method, mode, headers: new Headers() },
      respondWith: vi.fn(),
      waitUntil: vi.fn(),
    };
    listeners.fetch(event);
    return event;
  };
  return { dispatch, putInCache: g.putInCache, stored, cache, network };
}

describe("service worker and student data", () => {
  it("never answers or caches a /api/hangeul request, fetched or navigated to", async () => {
    const sw = loadServiceWorkerWithCaches();
    const events = [
      sw.dispatch("/api/hangeul/snapshot"),
      sw.dispatch("/api/hangeul/snapshot?cursor=abc"),
      sw.dispatch("/api/hangeul/changes?since=13553&limit=200"),
      sw.dispatch("/api/hangeul/runs"),
      sw.dispatch("/api/hangeul"),
      sw.dispatch("/api/hangeul/ask", "POST"),
      sw.dispatch("/api/chat", "POST"),
      // Someone opening the dump's URL in a tab: straight to the network, no shell fallback.
      sw.dispatch("/api/hangeul/snapshot", "GET", "navigate"),
    ];
    for (const event of events) {
      expect(event.respondWith).not.toHaveBeenCalled();
      expect(event.waitUntil).not.toHaveBeenCalled();
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(sw.cache.put).not.toHaveBeenCalled();
    expect(sw.network).not.toHaveBeenCalled();
  });

  it("refuses an /api/ URL even when a strategy asks to store it", async () => {
    const sw = loadServiceWorkerWithCaches();
    const ok = () => basic("{}");
    await sw.putInCache("/api/hangeul/snapshot", ok());
    await sw.putInCache("https://jeannie.test/api/hangeul/changes?since=0", ok());
    expect(sw.stored).toEqual([]);
    // The rule is about the API only: the app shell and icons are still cached.
    await sw.putInCache("/icons/icon-192.png", ok());
    expect(sw.stored).toEqual(["/icons/icon-192.png"]);
  });

  it("still caches the app shell on a page navigation", async () => {
    const sw = loadServiceWorkerWithCaches();
    const event = sw.dispatch("/", "GET", "navigate");
    expect(event.respondWith).toHaveBeenCalledTimes(1);
    await event.respondWith.mock.calls[0][0];
    await Promise.all(event.waitUntil.mock.calls.map((call) => call[0]));
    expect(sw.stored).toEqual(["/"]);
  });
});

// ── Offline banner logic (spec D10) ──────────────────────────────────────────

describe("reachability", () => {
  it("is offline when the browser is, or when the API did not answer", () => {
    let state = INITIAL_REACHABILITY;
    expect(isOffline(state)).toBe(false);
    state = reduceReachability(state, { type: "browser", online: false });
    expect(isOffline(state)).toBe(true);
    state = reduceReachability(state, { type: "browser", online: true });
    expect(isOffline(state)).toBe(false);
    state = reduceReachability(state, { type: "api", reachable: false });
    expect(isOffline(state)).toBe(true);
    state = reduceReachability(state, { type: "api", reachable: true });
    expect(isOffline(state)).toBe(false);
  });

  it("keeps the same state object when nothing changed (no re-render)", () => {
    const state = INITIAL_REACHABILITY;
    expect(reduceReachability(state, { type: "browser", online: true })).toBe(state);
    expect(reduceReachability(state, { type: "api", reachable: true })).toBe(state);
  });

  it("counts only a request that never reached the server as unreachable", () => {
    expect(isUnreachable(new ApiRequestError(0, "network_error", "Uplink unreachable."))).toBe(true);
    // A long answer can time out on a working connection; an HTTP error means the server answered.
    expect(isUnreachable(new ApiRequestError(0, "timeout", "The uplink timed out."))).toBe(false);
    expect(isUnreachable(new ApiRequestError(502, "hangeul_unavailable", "Upstream."))).toBe(false);
    expect(isUnreachable(new TypeError("Failed to fetch"))).toBe(false);
  });

  it("re-probes /api/status with a growing delay, capped at 30 s", () => {
    expect([0, 1, 2, 3, 4, 5, 20].map(probeDelay)).toEqual([2_000, 4_000, 8_000, 16_000, 30_000, 30_000, 30_000]);
  });

  it("has the banner line in both languages", () => {
    expect(OFFLINE_LINE.en).toBe("Offline: Jeannie needs a connection");
    expect(OFFLINE_LINE.ko).toMatch(/오프라인/);
  });
});
