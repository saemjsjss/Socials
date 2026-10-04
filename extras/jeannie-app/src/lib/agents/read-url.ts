// readUrl tool: fetch a web page as clean text. Jina Reader
// (https://r.jina.ai/<url>) does the rendering; when it fails we fetch the page
// ourselves and strip the HTML. Only public http(s) URLs on standard ports are
// allowed, so the tool cannot be pointed at localhost or the private network.
// Fetch + regex only, so it runs on the Edge runtime (no DOM).

import { tool } from "ai";
import { z } from "zod";
import type { SourceLink } from "../types";
import { BROWSER_USER_AGENT, withTimeout } from "./search-agent";

export const READ_URL_TIMEOUT_MS = 10_000;
/** Jina gets most of the budget; our own fetch still has time to run after it. */
const JINA_TIMEOUT_MS = 6_000;
export const MAX_READ_CHARS = 12_000;
/** Bytes read from a response body before giving up on the rest. */
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const MAX_REDIRECTS = 3;
const JINA_READER = "https://r.jina.ai/";

// ─── URL safety ─────────────────────────────────────────────────────────────

const BLOCKED_HOST_SUFFIXES = [".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa"];

function ipv4Octets(host: string): number[] | null {
  const parts = host.split(".");
  if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p))) return null;
  const octets = parts.map(Number);
  return octets.every((o) => o <= 255) ? octets : null;
}

function isPrivateIpv4([a, b, c]: number[]): boolean {
  return (
    a === 0 || // "this" network
    a === 10 ||
    a === 127 || // loopback
    (a === 100 && b! >= 64 && b! <= 127) || // carrier-grade NAT
    (a === 169 && b === 254) || // link-local (cloud metadata)
    (a === 172 && b! >= 16 && b! <= 31) ||
    (a === 192 && b === 168) ||
    (a === 192 && b === 0 && (c === 0 || c === 2)) || // IETF protocol assignments, TEST-NET-1
    (a === 198 && (b === 18 || b === 19)) || // benchmarking
    a! >= 224 // multicast and reserved
  );
}

function isPrivateIpv6(host: string): boolean {
  const ip = host.replace(/^\[|\]$/g, "").toLowerCase();
  if (ip === "::" || ip === "::1") return true;
  // IPv4-mapped (::ffff:7f00:1 after URL normalization, or ::ffff:127.0.0.1).
  const mapped = /^::ffff:(?:(\d+\.\d+\.\d+\.\d+)|([0-9a-f]{1,4}):([0-9a-f]{1,4}))$/.exec(ip);
  if (mapped) {
    if (mapped[1]) return isPrivateIpv4(ipv4Octets(mapped[1]) ?? [0]);
    const hi = parseInt(mapped[2]!, 16);
    const lo = parseInt(mapped[3]!, 16);
    return isPrivateIpv4([hi >> 8, hi & 0xff, lo >> 8, lo & 0xff]);
  }
  if (ip.startsWith("::")) return true; // IPv4-compatible and other reserved low addresses
  const [first = 0, second = 0] = ip.split(":").map((group) => parseInt(group || "0", 16));
  return (
    (first === 0x64 && second === 0xff9b) || // NAT64: embeds an IPv4 address the gateway reaches for us
    first === 0x2002 || // 6to4: embeds an IPv4 address
    (first === 0x2001 && second === 0) || // Teredo
    (first & 0xfe00) === 0xfc00 || // unique local fc00::/7
    (first & 0xffc0) === 0xfe80 || // link-local fe80::/10
    (first & 0xffc0) === 0xfec0 || // deprecated site-local fec0::/10
    (first & 0xff00) === 0xff00 // multicast
  );
}

/**
 * The URL when it is a public http(s) address on a standard port, else the
 * reason it was refused. Hostnames are checked as written: a public name that
 * resolves to a private address is not caught here (no DNS on Edge).
 */
export function checkPublicUrl(raw: string): { url: URL } | { error: string } {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return { error: "Not a valid URL." };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return { error: "Only http and https URLs can be read." };
  if (url.username || url.password) return { error: "URLs with credentials are not allowed." };
  if (url.port && url.port !== "80" && url.port !== "443") return { error: "Only the standard ports (80, 443) are allowed." };

  // WHATWG parsing already normalized decimal/hex/octal IPv4 forms to dotted quads.
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (host.startsWith("[")) {
    return isPrivateIpv6(host) ? { error: "Private and loopback addresses are not allowed." } : { url };
  }
  const octets = ipv4Octets(host);
  if (octets) return isPrivateIpv4(octets) ? { error: "Private and loopback addresses are not allowed." } : { url };
  if (host === "localhost" || BLOCKED_HOST_SUFFIXES.some((s) => host.endsWith(s)) || !host.includes(".")) {
    return { error: "Local and internal hostnames are not allowed." };
  }
  return { url };
}

// ─── HTML → text ────────────────────────────────────────────────────────────

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  mdash: "—",
  ndash: "–",
  hellip: "…",
  rsquo: "’",
  lsquo: "‘",
  rdquo: "”",
  ldquo: "“",
  middot: "·",
  copy: "©",
};

export function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, name: string) => {
    if (name[0] === "#") {
      const code = name[1] === "x" || name[1] === "X" ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
    }
    return NAMED_ENTITIES[name.toLowerCase()] ?? whole;
  });
}

/** Readable text from an HTML page: title, then the body text with block elements on their own lines. */
export function htmlToText(html: string): { title: string | null; text: string } {
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  const title = titleMatch ? decodeEntities(titleMatch[1]!.replace(/\s+/g, " ").trim()) || null : null;
  const text = decodeEntities(
    html
      .replace(/<!--[\s\S]*?-->/g, " ")
      .replace(/<(script|style|noscript|svg|template|iframe|head|title|nav|footer|form)\b[\s\S]*?<\/\1\s*>/gi, " ")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<li\b[^>]*>/gi, "\n• ")
      .replace(/<\/?(?:p|div|section|article|main|header|aside|h[1-6]|ul|ol|tr|table|blockquote|pre|dd|dt|figcaption)\b[^>]*>/gi, "\n")
      .replace(/<[^>]+>/g, " "),
  )
    .replace(/[ \t\f\v ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { title, text };
}

// ─── Fetching ───────────────────────────────────────────────────────────────

/** Body as text, reading at most `MAX_BODY_BYTES`. */
async function readCapped(res: Response): Promise<string> {
  if (!res.body) return "";
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    text += decoder.decode(value, { stream: true });
    if (bytes >= MAX_BODY_BYTES) {
      await reader.cancel().catch(() => undefined);
      break;
    }
  }
  return text + decoder.decode();
}

export interface ReadUrlResult {
  url: string;
  title: string | null;
  text: string;
  truncated: boolean;
  via: "jina" | "direct";
}

export type ReadUrlOutcome = ReadUrlResult | { url: string; error: string };

function capText(text: string): { text: string; truncated: boolean } {
  if (text.length <= MAX_READ_CHARS) return { text, truncated: false };
  return { text: `${text.slice(0, MAX_READ_CHARS).trimEnd()}…`, truncated: true };
}

/** Jina Reader's plain-text answer: "Title: …\nURL Source: …\nMarkdown Content:\n…". */
export function parseJinaText(raw: string): { title: string | null; text: string } {
  const title = /^Title:\s*(.+)$/m.exec(raw)?.[1]?.trim() || null;
  const marker = raw.indexOf("Markdown Content:");
  const text = (marker >= 0 ? raw.slice(marker + "Markdown Content:".length) : raw).trim();
  return { title, text };
}

async function viaJina(url: URL, signal: AbortSignal): Promise<{ title: string | null; text: string } | null> {
  try {
    const res = await fetch(`${JINA_READER}${url.href}`, {
      headers: { accept: "text/plain", "x-no-cache": "true" },
      signal: withTimeout(JINA_TIMEOUT_MS, signal),
    });
    if (!res.ok) {
      await res.body?.cancel().catch(() => undefined);
      return null;
    }
    const parsed = parseJinaText(await readCapped(res));
    return parsed.text ? parsed : null;
  } catch {
    return null;
  }
}

/** Our own fetch, following redirects by hand so every hop passes the URL check. */
async function viaDirect(start: URL, signal: AbortSignal): Promise<{ title: string | null; text: string } | { error: string }> {
  let url = start;
  for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
    const res = await fetch(url.href, {
      headers: { "user-agent": BROWSER_USER_AGENT, accept: "text/html,text/plain;q=0.9,*/*;q=0.5" },
      redirect: "manual",
      signal,
    });
    const location = res.headers.get("location");
    if (res.status >= 300 && res.status < 400 && location) {
      await res.body?.cancel().catch(() => undefined);
      const next = checkPublicUrl(new URL(location, url).href);
      if ("error" in next) return { error: `Redirected to a blocked address: ${next.error}` };
      url = next.url;
      continue;
    }
    if (!res.ok) {
      await res.body?.cancel().catch(() => undefined);
      return { error: `The page answered HTTP ${res.status}.` };
    }
    const type = (res.headers.get("content-type") ?? "").toLowerCase();
    if (type && !/text\/|json|xml/.test(type)) {
      await res.body?.cancel().catch(() => undefined);
      return { error: `Unsupported content type (${type.split(";")[0]}).` };
    }
    const body = await readCapped(res);
    return type.includes("html") || (!type && /<html|<body/i.test(body)) ? htmlToText(body) : { title: null, text: body.trim() };
  }
  return { error: "Too many redirects." };
}

/** Reads a public web page as text (≤ 12k characters). Never throws. */
export async function readUrl(raw: string, options: { signal?: AbortSignal | null } = {}): Promise<ReadUrlOutcome> {
  const checked = checkPublicUrl(raw);
  if ("error" in checked) return { url: raw, error: checked.error };
  const { url } = checked;
  const deadline = withTimeout(READ_URL_TIMEOUT_MS, options.signal);

  const jina = await viaJina(url, deadline);
  if (jina) return { url: url.href, title: jina.title, ...capText(jina.text), via: "jina" };
  if (deadline.aborted) return { url: url.href, error: "Timed out reading the page." };

  try {
    const direct = await viaDirect(url, deadline);
    if ("error" in direct) return { url: url.href, error: direct.error };
    if (!direct.text) return { url: url.href, error: "The page has no readable text." };
    return { url: url.href, title: direct.title, ...capText(direct.text), via: "direct" };
  } catch {
    return { url: url.href, error: deadline.aborted ? "Timed out reading the page." : "Could not fetch the page." };
  }
}

export function createReadUrlTool(onSources?: (sources: SourceLink[]) => void) {
  return tool({
    description:
      "Read a public web page (http/https) as clean text, e.g. a link the user shared or a search result you need in full. Returns the title and up to 12,000 characters of text.",
    inputSchema: z.object({ url: z.string().min(1).describe("Full http(s) URL of the page") }),
    execute: async ({ url }, { abortSignal }) => {
      const result = await readUrl(url, { signal: abortSignal });
      if (!("error" in result)) onSources?.([{ title: result.title ?? result.url, url: result.url }]);
      return result;
    },
  });
}
