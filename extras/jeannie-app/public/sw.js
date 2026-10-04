// Jeannie service worker: app shell + avatar clip cache. Hand-written, no build step.
//
//   /api/*               network only, never cached, never handled (navigations too)
//   /avatar/*, /icons/*  cache first (clips are immutable per deploy; bump VERSION to refresh)
//   /_next/static/*      stale-while-revalidate (content-hashed file names)
//   page navigations     network first, falling back to the cached shell when offline
//
// No student data ever enters this cache (spec §6): the Hangeul records live in
// IndexedDB ("jeannie-hg"), and putInCache refuses any /api/ URL whatever asked.
// The transformers.js model cache ("transformers-cache") is not ours and is kept.
//
// <video> always sends Range requests. Those are answered from a cached full
// response when there is one (sliced into a 206); otherwise they go to the
// network untouched and the full clip is fetched in the background for next time.

const VERSION = "v4";
const CACHE = `jeannie-${VERSION}`;
const SHELL_URL = "/";

// Clip URLs with a background full fetch in flight, so parallel Range requests start only one.
const filling = new Set();

/** Pick the caching strategy for a request, or null to let the browser handle it. */
function strategyFor(url, method, origin) {
  if (method !== "GET" || url.origin !== origin) return null;
  const path = url.pathname;
  if (path.startsWith("/api/")) return "network-only";
  if (/^\/avatar\/[^/]+\.(mp4|jpg)$/.test(path) || path.startsWith("/icons/")) return "cache-first";
  if (path.startsWith("/_next/static/")) return "stale-while-revalidate";
  return null;
}

/** Parse a single-range `bytes=` header against a body of `size` bytes. Returns null when unsatisfiable. */
function parseRange(header, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match || (match[1] === "" && match[2] === "")) return null;
  let start;
  let end;
  if (match[1] === "") {
    start = Math.max(0, size - Number(match[2]));
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] === "" ? size - 1 : Math.min(Number(match[2]), size - 1);
  }
  if (start > end || start >= size) return null;
  return { start, end };
}

/** The API (and so every Hangeul record) is never cached, whatever strategy asked. */
function isApiPath(url) {
  return new URL(typeof url === "string" ? url : url.url, self.location.origin).pathname.startsWith("/api/");
}

function cacheable(response) {
  return response.ok && response.status === 200 && response.type === "basic";
}

async function putInCache(request, response) {
  if (isApiPath(request) || !cacheable(response)) return;
  const cache = await caches.open(CACHE);
  await cache.put(request, response);
}

async function rangeResponse(cached, header) {
  const body = await cached.arrayBuffer();
  const range = parseRange(header, body.byteLength);
  if (!range) {
    return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${body.byteLength}` } });
  }
  const headers = new Headers(cached.headers);
  headers.set("Content-Range", `bytes ${range.start}-${range.end}/${body.byteLength}`);
  headers.set("Content-Length", String(range.end - range.start + 1));
  return new Response(body.slice(range.start, range.end + 1), { status: 206, statusText: "Partial Content", headers });
}

async function cacheFirst(event) {
  const { request } = event;
  const range = request.headers.get("range");
  // Match by URL alone so a Range request finds the full clip cached from a plain request.
  const cached = await caches.match(request.url, { cacheName: CACHE });
  if (cached) return range ? rangeResponse(cached, range) : cached;
  if (range) {
    if (!filling.has(request.url)) {
      filling.add(request.url);
      event.waitUntil(
        fetch(request.url)
          .then((full) => putInCache(request.url, full))
          .catch(() => {})
          .finally(() => filling.delete(request.url)),
      );
    }
    return fetch(request);
  }
  const response = await fetch(request);
  event.waitUntil(putInCache(request.url, response.clone()));
  return response;
}

async function staleWhileRevalidate(event) {
  const { request } = event;
  const cached = await caches.match(request, { cacheName: CACHE });
  const network = fetch(request).then(async (response) => {
    await putInCache(request, response.clone());
    return response;
  });
  if (cached) {
    event.waitUntil(network.catch(() => {}));
    return cached;
  }
  return network;
}

async function networkFirstShell(event) {
  try {
    const response = await fetch(event.request);
    if (new URL(event.request.url).pathname === SHELL_URL) event.waitUntil(putInCache(SHELL_URL, response.clone()));
    return response;
  } catch (error) {
    const shell = await caches.match(SHELL_URL, { cacheName: CACHE });
    if (shell) return shell;
    throw error;
  }
}

self.addEventListener("install", (event) => {
  // Best effort: a failed shell fetch must not block installation.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(SHELL_URL))
      .catch(() => {})
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("jeannie-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate" && request.method === "GET" && url.origin === self.location.origin) {
    event.respondWith(networkFirstShell(event));
    return;
  }
  switch (strategyFor(url, request.method, self.location.origin)) {
    case "cache-first":
      event.respondWith(cacheFirst(event));
      break;
    case "stale-while-revalidate":
      event.respondWith(staleWhileRevalidate(event));
      break;
    // "network-only" and unknown requests fall through to the browser's own fetch.
    default:
      break;
  }
});
