// Live Search Agent: decides when a message needs fresh web data and fetches
// it through a Tavily → Google Custom Search → DuckDuckGo fallback chain.
// Everything here is fetch + regex so it runs on the Edge runtime (no DOM).

import { tool } from "ai";
import { z } from "zod";
import { getEnv, type JeannieEnv } from "../env";
import type { SearchProvider, SearchResponse, SearchResult, SourceLink } from "../types";
import { truncate } from "../utils";

const PROVIDER_TIMEOUT_MS = 8_000;
const MAX_QUERY_CHARS = 400;
const MAX_SNIPPET_CHARS = 500;

/** DuckDuckGo serves a bot challenge to obviously scripted clients. */
export const BROWSER_USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

/**
 * Signal that fires after `ms` or when `parent` aborts. Never throws: AbortSignal.any
 * is missing on some runtimes and rejects a request signal created by the host
 * (Vercel's Edge runtime), in which case the parent is forwarded by hand or, if
 * even that fails, only the timeout applies.
 */
export function withTimeout(ms: number, parent?: AbortSignal | null): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  if (!parent) return timeout;
  if (typeof AbortSignal.any === "function") {
    try {
      return AbortSignal.any([parent, timeout]);
    } catch {
      // Fall through to manual forwarding.
    }
  }
  const controller = new AbortController();
  const forward = (source: AbortSignal) => () => controller.abort(source.reason);
  try {
    if (parent.aborted) controller.abort(parent.reason);
    parent.addEventListener("abort", forward(parent), { once: true });
  } catch {
    return timeout;
  }
  timeout.addEventListener("abort", forward(timeout), { once: true });
  return controller.signal;
}

// ─── Routing heuristic ──────────────────────────────────────────────────────
// Cues are deliberately scoped: bare "now", "schedule", "search" or 결과 show up
// in ordinary follow-ups ("now make it shorter", "binary search", "결과를 요약해줘")
// that must stay with the core agent and its conversation context. Time words
// ("today", 오늘, 최근, a year) also fill small talk ("I had a rough day
// today", "오늘 저녁 메뉴 추천해줘"), so they only count next to a factual cue.

const EN_LIVE_CUES: RegExp[] = [
  /\bas of (?:now|today)\b|\bcurrent time\b|\bwhat time is it in\b|\bwhat(?:'s| is) the time in\b/i,
  /\b(?:latest|newest|up[- ]to[- ]date|breaking|trending)\b/i,
  /\bnews\b|\bheadlines?\b/i,
  /\b(?:scores?|standings|who won|who is winning|winner of|final result)\b/i,
  /\b(?:weather|forecast)\b/i,
  /\b(?:prices?|pricing|stock (?:price|market|quote)s?|stocks|share price|market cap|exchange rates?|crypto(?:currency|currencies)?|bitcoin|ethereum)\b/i,
  /\b(?:elections?|release date|launch date|box office)\b/i,
  /\b(?:game|match|fixture|tour|concert|release|flight|train|bus|exam|topik|tv|broadcast)\s+(?:schedule|timetable)s?\b/i,
  /\b(?:schedule|timetable)s?\s+(?:for|of)\s+(?:the\s+)?(?:next|upcoming|game|match|tour|concert|flight|train|bus|exam|topik)\b/i,
  /^\s*search\b|\bsearch\s+(?:for|the web|online|the internet|up|about|news)\b|\b(?:web|online|internet)\s+search\b|\b(?:can you|please|could you)\s+search\b/i,
  /\blook(?:\s+|-)?up\b|\bgoogle\s+(?:it|that|this|for)\b|\bfind out\b/i,
  /\bverify\b|\bfact[- ]?check\b|\b(?:is|was) (?:it|that|this) true\b|\btrue or false\b|\bdebunk\b|\brumou?rs?\b/i,
];

const EN_TIME_CUE =
  /\b(?:today|tonight|tomorrow|yesterday|current(?:ly)?|recent(?:ly)?)\b|\bright now\b|\bat the moment\b|\bnow\s*\?|\bthis (?:week|weekend|month|year|season)\b|\b(?:last|next) (?:week|weekend|month|year|night)\b|\b20(?:2[4-9]|3[0-5])\b/i;

const EN_FACT_CUE =
  /\b(?:temperature|rain(?:ing)?|snow(?:ing)?|traffic|results?|fixtures?|match(?:es)?|events?|happen(?:ed|ing)|going on|flights?|trains?|concerts?|releases|launch(?:es|ed)?|updates|update on|announce(?:d|ment|ments)?|holidays?|open|opening hours|closed|ceo|president|prime minister|minister|champions?|winners?|leading|population|rankings?|showing|airing)\b|\bwho (?:is|are|was)\b|\bwhat time\b|\bwhen (?:is|does|will|do)\b|\bwhat(?:'s| is| are)\s+(?:new|happening|on)\b|\b(?:what|when)(?:'s| is| are)?\b[^.?!\n]{0,30}\bschedule/i;

// A year alone ("a greeting card for 2026") is not a lookup; "best phones of 2026" is.
const EN_YEAR_FACT_CUE = /\b(?:best|top|upcoming|trends?|predictions?|calendar)\b/i;
const EN_YEAR = /\b20(?:2[4-9]|3[0-5])\b/;

const KO_LIVE_CUES: RegExp[] = [
  /요즘\s*(?:유행|인기|뜨는|핫한|화제)/,
  /지금\s*몇\s*시|최신/,
  /뉴스|속보|헤드라인/,
  /날씨|기온|일기\s?예보|예보/,
  /가격|시세|주가|주식|환율|비트코인|코인|암호화폐/,
  /검색|찾아\s?봐|알아\s?봐|인터넷에서\s*찾|웹에서\s*찾/,
  /(?:경기|선거|시합|투표|개표|시험|추첨|발표)\s?결과|결과\s?발표|누가\s?(?:이겼|우승|당선)|선거|스코어/,
  /(?:경기|공연|콘서트|투어|개봉|발매|시험|토픽)\s?일정|개봉일|출시일|발매일/,
  // "확인해줘" alone is also "check my code"; it counts next to a fact word.
  /사실(?:이야|인가|이에요|인지|여부)|진짜야|팩트\s?체크|(?:사실|뉴스|소식|정보|진짜)[^.?!\n]{0,20}확인해\s?(?:줘|봐|주세요)/,
];

const KO_TIME_CUE = /오늘|어제|내일|모레|올해|이번\s?(?:주|달|시즌)|현재|최근|지금/;

const KO_FACT_CUE =
  /소식|경기|결과|일정|몇\s*시|몇\s*도|무슨\s*일|사건|개봉|발표|순위|이슈|교통|항공편|비행기|열차|운행|영업|휴무|공휴일|휴일|행사|축제|공연|업데이트|출시|(?<![가-힯])비\s*(?:가\s*)?(?:와|오|올|내)|(?<![가-힯])눈\s*(?:이\s*)?(?:와|오|올|내)|미세\s*먼지|황사|우산/;

/** True when a message asks for time-sensitive or verifiable facts. */
export function needsLiveSearch(text: string): boolean {
  const normalized = text.normalize("NFC");
  if (!normalized.trim()) return false;
  if (EN_LIVE_CUES.some((re) => re.test(normalized)) || KO_LIVE_CUES.some((re) => re.test(normalized))) return true;
  if (EN_TIME_CUE.test(normalized) && EN_FACT_CUE.test(normalized)) return true;
  if (EN_YEAR.test(normalized) && EN_YEAR_FACT_CUE.test(normalized)) return true;
  return KO_TIME_CUE.test(normalized) && KO_FACT_CUE.test(normalized);
}

// ─── Follow-ups ─────────────────────────────────────────────────────────────
// "And tomorrow?" after "What's the weather in Busan today?" means nothing on
// its own, so both routing and the search query borrow the earlier turns.

const FOLLOW_UP_START =
  /^\s*(?:and|also|what\s+about|how\s+about|what\s+if)\b|^\s*(?:그럼|그러면|그리고|그런데|근데|그건|그거는)(?![가-힯])/i;
const MAX_FOLLOW_UP_WORDS = 4;

/** A short question that continues the previous turn ("And tomorrow?", "What about Daegu?", "내일은?"). */
export function isFollowUp(text: string): boolean {
  const t = text.normalize("NFC").trim();
  if (!t) return false;
  if (FOLLOW_UP_START.test(t)) return true;
  return t.split(/\s+/).length <= MAX_FOLLOW_UP_WORDS && (/\?\s*$/.test(t) || /[은는]\s*\?*\s*$/.test(t));
}

/** Earlier user turns (oldest first) that a follow-up builds on: the last one, plus earlier ones while those are follow-ups too. */
function followUpChain(previous: readonly string[]): string[] {
  const chain: string[] = [];
  for (let i = previous.length - 1; i >= 0 && chain.length < 3; i--) {
    const turn = previous[i].trim();
    if (!turn) continue;
    chain.unshift(turn);
    if (!isFollowUp(turn)) break;
  }
  return chain;
}

/** A follow-up to a conversation that was already about live facts. */
export function isSearchFollowUp(text: string, previous: readonly string[]): boolean {
  return isFollowUp(text) && followUpChain(previous).some(needsLiveSearch);
}

/**
 * Search query for the latest turn without an LLM: a follow-up gets the
 * earlier turns it builds on ("What's the weather in Busan today? And
 * tomorrow?"), when those were live-fact questions or it opens with "and",
 * "what about", 그럼, ...
 */
export function contextualSearchQuery(text: string, previous: readonly string[]): string {
  const latest = text.trim();
  if (!isFollowUp(latest)) return latest;
  const chain = followUpChain(previous);
  if (chain.length === 0 || !(FOLLOW_UP_START.test(latest) || chain.some(needsLiveSearch))) return latest;
  return [...chain.map((turn) => truncate(turn, 150)), latest].join(" ");
}

// ─── Result normalization ───────────────────────────────────────────────────

const NAMED_ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

export function decodeHtmlEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match, entity: string) => {
    if (entity[0] === "#") {
      const code = entity[1] === "x" || entity[1] === "X" ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10);
      return Number.isInteger(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match;
    }
    return NAMED_ENTITIES[entity.toLowerCase()] ?? match;
  });
}

// Inline tags (DuckDuckGo bolds query words: "<b>Seoul</b>,") vanish without a
// space so punctuation stays attached; any other tag separates words.
const INLINE_TAG = /<\/?(?:a|b|strong|i|em|u|mark|span|wbr)\b[^>]*>/gi;

function htmlToText(fragment: string): string {
  return decodeHtmlEntities(fragment.replace(INLINE_TAG, "").replace(/<[^>]*>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function httpUrl(raw: string | undefined | null): URL | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function normalizeResult(
  raw: { title?: unknown; url?: unknown; snippet?: unknown; publishedDate?: unknown },
  source: SearchProvider,
): SearchResult | null {
  const url = httpUrl(typeof raw.url === "string" ? raw.url.trim() : null);
  if (!url) return null;
  const title = typeof raw.title === "string" ? raw.title.replace(/\s+/g, " ").trim() : "";
  const snippet = typeof raw.snippet === "string" ? raw.snippet.replace(/\s+/g, " ").trim() : "";
  const result: SearchResult = {
    title: title || url.hostname,
    url: url.toString(),
    snippet: truncate(snippet, MAX_SNIPPET_CHARS),
    source,
  };
  if (typeof raw.publishedDate === "string" && raw.publishedDate.trim()) result.publishedDate = raw.publishedDate.trim();
  return result;
}

function urlKey(value: string): string {
  const url = new URL(value);
  const path = url.pathname.replace(/\/+$/, "");
  return `${url.hostname.replace(/^www\./, "").toLowerCase()}${path}${url.search}`;
}

export function dedupeResults(results: SearchResult[]): SearchResult[] {
  const seen = new Set<string>();
  return results.filter((result) => {
    const key = urlKey(result.url);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function toSourceLinks(results: SearchResult[], max = 5): SourceLink[] {
  return results.slice(0, max).map((r) => ({ title: truncate(r.title, 80), url: r.url }));
}

// ─── Providers ──────────────────────────────────────────────────────────────

class ProviderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProviderError";
  }
}

interface ProviderOutcome {
  results: SearchResult[];
  answer?: string;
}

type ProviderRun = (query: string, maxResults: number, signal: AbortSignal) => Promise<ProviderOutcome>;

async function ensureOk(res: Response): Promise<void> {
  if (res.ok) return;
  await res.body?.cancel().catch(() => undefined);
  throw new ProviderError(`HTTP ${res.status}`);
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

// DeepSeek's Anthropic-compatible Messages API runs the native `web_search` server tool
// itself: one request = one model turn that searches, then answers with citations.
interface DeepSeekSearchBlock {
  type?: unknown;
  text?: unknown;
  content?: unknown;
  citations?: Array<{ type?: unknown; url?: unknown; title?: unknown; cited_text?: unknown }>;
}

interface DeepSeekWebResult {
  type?: unknown;
  url?: unknown;
  title?: unknown;
  page_age?: unknown;
}

/** Messages API response → results (+ the model's cited summary). Exported for tests. */
export function parseDeepSeekSearch(data: { content?: DeepSeekSearchBlock[] }): ProviderOutcome {
  const blocks = Array.isArray(data.content) ? data.content : [];
  const cited = new Map<string, string[]>();
  const texts: string[] = [];
  for (const block of blocks) {
    if (block.type !== "text") continue;
    if (typeof block.text === "string") texts.push(block.text);
    for (const c of block.citations ?? []) {
      if (typeof c.url !== "string" || typeof c.cited_text !== "string") continue;
      cited.set(c.url, [...(cited.get(c.url) ?? []), c.cited_text]);
    }
  }
  const results: SearchResult[] = [];
  for (const block of blocks) {
    if (block.type !== "web_search_tool_result" || !Array.isArray(block.content)) continue;
    for (const item of block.content as DeepSeekWebResult[]) {
      if (item.type !== "web_search_result" || typeof item.url !== "string") continue;
      const result = normalizeResult(
        { title: item.title, url: item.url, snippet: (cited.get(item.url) ?? []).join(" … "), publishedDate: item.page_age },
        "deepseek",
      );
      if (result) results.push(result);
    }
  }
  return { results, answer: nonEmptyString(texts.join("").replace(/\s+/g, " ")) };
}

function deepseek(apiKey: string, baseUrl: string, model: string): ProviderRun {
  return async (query, maxResults, signal) => {
    const res = await fetch(`${baseUrl}/v1/messages`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": apiKey,
        authorization: `Bearer ${apiKey}`,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model,
        max_tokens: 1024,
        tools: [{ type: "web_search_20250305", name: "web_search", max_uses: 2 }],
        messages: [
          {
            role: "user",
            content: `Search the web for: ${query}\nThen summarise in 2-4 sentences what the ${maxResults} most relevant results say, citing them.`,
          },
        ],
      }),
      signal,
    });
    await ensureOk(res);
    return parseDeepSeekSearch((await res.json()) as { content?: DeepSeekSearchBlock[] });
  };
}

interface TavilyResponse {
  answer?: unknown;
  results?: Array<{ title?: unknown; url?: unknown; content?: unknown; published_date?: unknown }>;
}

function tavily(apiKey: string): ProviderRun {
  return async (query, maxResults, signal) => {
    const res = await fetch("https://api.tavily.com/search", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ query, max_results: maxResults, search_depth: "basic", include_answer: true }),
      signal,
    });
    await ensureOk(res);
    const data = (await res.json()) as TavilyResponse;
    const results = (data.results ?? [])
      .map((r) => normalizeResult({ title: r.title, url: r.url, snippet: r.content, publishedDate: r.published_date }, "tavily"))
      .filter((r): r is SearchResult => r !== null);
    return { results, answer: nonEmptyString(data.answer) };
  };
}

interface GoogleResponse {
  items?: Array<{
    title?: unknown;
    link?: unknown;
    snippet?: unknown;
    pagemap?: { metatags?: Array<Record<string, unknown>> };
  }>;
}

function google(apiKey: string, cseId: string): ProviderRun {
  return async (query, maxResults, signal) => {
    const url = new URL("https://www.googleapis.com/customsearch/v1");
    url.searchParams.set("key", apiKey);
    url.searchParams.set("cx", cseId);
    url.searchParams.set("q", query);
    url.searchParams.set("num", String(Math.min(maxResults, 10)));
    const res = await fetch(url, { headers: { accept: "application/json" }, signal });
    await ensureOk(res);
    const data = (await res.json()) as GoogleResponse;
    const results = (data.items ?? [])
      .map((item) => {
        const meta = item.pagemap?.metatags?.[0];
        const published = meta?.["article:published_time"] ?? meta?.["og:updated_time"];
        return normalizeResult({ title: item.title, url: item.link, snippet: item.snippet, publishedDate: published }, "google");
      })
      .filter((r): r is SearchResult => r !== null);
    return { results };
  };
}

interface DdgTopic {
  FirstURL?: unknown;
  Text?: unknown;
  Result?: unknown;
  Topics?: DdgTopic[];
}

interface DdgInstantAnswer {
  Heading?: unknown;
  Answer?: unknown;
  Definition?: unknown;
  AbstractText?: unknown;
  AbstractURL?: unknown;
  AbstractSource?: unknown;
  Results?: DdgTopic[];
  RelatedTopics?: DdgTopic[];
}

function flattenTopics(topics: DdgTopic[] | undefined): DdgTopic[] {
  return (topics ?? []).flatMap((t) => (Array.isArray(t.Topics) ? flattenTopics(t.Topics) : [t]));
}

function topicToResult(topic: DdgTopic, fallbackHeading?: string): SearchResult | null {
  const url = nonEmptyString(topic.FirstURL);
  const text = nonEmptyString(topic.Text);
  if (!url || !text || /duckduckgo\.com\/c\//.test(url)) return null; // category pages have no content
  const anchor = typeof topic.Result === "string" ? /<a\b[^>]*>([\s\S]*?)<\/a>/i.exec(topic.Result) : null;
  const title = anchor ? htmlToText(anchor[1]) : text.split(" - ")[0];
  let snippet = text.startsWith(title) ? text.slice(title.length).replace(/^[\s\-–—:]+/, "") : text;
  if (!snippet && fallbackHeading) snippet = `${fallbackHeading}: ${title}`;
  return normalizeResult({ title, url, snippet }, "duckduckgo");
}

/** DuckDuckGo Instant Answer JSON → results. Exported for tests. */
export function parseDuckDuckGoInstantAnswer(data: DdgInstantAnswer, query: string): ProviderOutcome {
  const heading = nonEmptyString(data.Heading);
  const results: SearchResult[] = [];
  const abstractUrl = nonEmptyString(data.AbstractURL);
  const abstractText = nonEmptyString(data.AbstractText);
  if (abstractUrl && abstractText) {
    const abstract = normalizeResult({ title: heading ?? nonEmptyString(data.AbstractSource) ?? query, url: abstractUrl, snippet: abstractText }, "duckduckgo");
    if (abstract) results.push(abstract);
  }
  for (const topic of [...flattenTopics(data.Results), ...flattenTopics(data.RelatedTopics)]) {
    const result = topicToResult(topic, heading);
    if (result) results.push(result);
  }
  return { results, answer: nonEmptyString(data.Answer) ?? nonEmptyString(data.Definition) };
}

function resolveDuckDuckGoHref(rawHref: string): string | null {
  let href = decodeHtmlEntities(rawHref.trim());
  if (href.startsWith("//")) href = `https:${href}`;
  else if (href.startsWith("/")) href = `https://duckduckgo.com${href}`;
  const url = httpUrl(href);
  if (!url) return null;
  if (url.hostname === "duckduckgo.com" || url.hostname.endsWith(".duckduckgo.com")) {
    // Organic results may be wrapped in /l/?uddg=<target>; anything else on
    // duckduckgo.com (ads via y.js, internal pages) is not a real result.
    const target = url.searchParams.get("uddg");
    return target && httpUrl(target) ? target : null;
  }
  return url.toString();
}

/** Where one DuckDuckGo result page keeps titles, snippets, dates and ad markers. */
interface DdgMarkup {
  title: RegExp; // group 1: <a> attributes, group 2: title HTML
  snippet: RegExp; // group 2: snippet HTML
  date?: RegExp; // group 1: date text
  /** True when the title at `index` belongs to an ad. */
  isAd: (html: string, index: number, blockStart: number) => boolean;
}

// Class attributes are double-quoted on html.duckduckgo.com and single-quoted on lite.duckduckgo.com.
const HTML_MARKUP: DdgMarkup = {
  title: /<a\b([^>]*\bclass=["'][^"']*\bresult__a\b[^"']*["'][^>]*)>([\s\S]*?)<\/a>/gi,
  snippet: /<(a|div|td|span)\b[^>]*\bclass=["'][^"']*\bresult__snippet\b[^"']*["'][^>]*>([\s\S]*?)<\/\1>/gi,
  isAd: (html, index, blockStart) => /\bresult--ad\b/.test(html.slice(blockStart, index)),
};

const LITE_MARKUP: DdgMarkup = {
  title: /<a\b([^>]*\bclass=["'][^"']*\bresult-link\b[^"']*["'][^>]*)>([\s\S]*?)<\/a>/gi,
  snippet: /<(td|div|span)\b[^>]*\bclass=["'][^"']*\bresult-snippet\b[^"']*["'][^>]*>([\s\S]*?)<\/\1>/gi,
  date: /<span\b[^>]*\bclass=["'][^"']*\btimestamp\b[^"']*["'][^>]*>([^<]*)<\/span>/gi,
  // Sponsored rows are `<tr class="result-sponsored">`; only the title's own row decides.
  isAd: (html, index) => {
    const rowStart = html.lastIndexOf("<tr", index);
    return rowStart !== -1 && /\bresult-sponsored\b/.test(html.slice(rowStart, html.indexOf(">", rowStart) + 1));
  },
};

function parseDuckDuckGoPage(html: string, markup: DdgMarkup): SearchResult[] {
  const titles = Array.from(html.matchAll(markup.title), (m) => ({
    index: m.index ?? 0,
    end: (m.index ?? 0) + m[0].length,
    href: /\bhref=(["'])(.*?)\1/i.exec(m[1])?.[2] ?? "",
    title: htmlToText(m[2]),
  }));
  const snippets = Array.from(html.matchAll(markup.snippet), (m) => ({ index: m.index ?? 0, text: htmlToText(m[2]) }));
  const dates = markup.date
    ? Array.from(html.matchAll(markup.date), (m) => ({ index: m.index ?? 0, text: m[1].trim() }))
    : [];

  const results: SearchResult[] = [];
  titles.forEach((t, i) => {
    const blockStart = i === 0 ? Math.max(0, t.index - 600) : titles[i - 1].end;
    if (markup.isAd(html, t.index, blockStart)) return;
    const nextIndex = titles[i + 1]?.index ?? Number.POSITIVE_INFINITY;
    const inBlock = (item: { index: number }) => item.index > t.index && item.index < nextIndex;
    const snippet = snippets.find(inBlock)?.text ?? "";
    const publishedDate = dates.find(inBlock)?.text;
    const result = normalizeResult(
      { title: t.title, url: resolveDuckDuckGoHref(t.href), snippet, publishedDate },
      "duckduckgo",
    );
    if (result) results.push(result);
  });
  return results;
}

/** html.duckduckgo.com result page → results (regex only; Edge has no DOM). Exported for tests. */
export function parseDuckDuckGoHtml(html: string): SearchResult[] {
  return parseDuckDuckGoPage(html, HTML_MARKUP);
}

/** lite.duckduckgo.com result page → results. Exported for tests. */
export function parseDuckDuckGoLite(html: string): SearchResult[] {
  return parseDuckDuckGoPage(html, LITE_MARKUP);
}

async function duckDuckGoInstant(query: string, signal: AbortSignal): Promise<ProviderOutcome> {
  const url = new URL("https://api.duckduckgo.com/");
  url.searchParams.set("q", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("no_html", "1");
  url.searchParams.set("skip_disambig", "1");
  url.searchParams.set("no_redirect", "1");
  const res = await fetch(url, { headers: { accept: "application/json", "user-agent": BROWSER_USER_AGENT }, signal });
  await ensureOk(res);
  // Served as application/x-javascript with status 202, so parse the text ourselves.
  const data = JSON.parse(await res.text()) as DdgInstantAnswer;
  return parseDuckDuckGoInstantAnswer(data, query);
}

// DuckDuckGo rate-limits each result page separately: after a few quick queries
// from one IP a page answers with a bot challenge for a minute or so, while the
// other page still works. So fail over between them, and skip a page that just
// challenged us instead of spending the next request on it.
const DDG_PAGES = [
  { id: "html", url: "https://html.duckduckgo.com/html/", form: { b: "" }, parse: parseDuckDuckGoHtml },
  { id: "lite", url: "https://lite.duckduckgo.com/lite/", form: {}, parse: parseDuckDuckGoLite },
] as const;
const DDG_CHALLENGE_COOLDOWN_MS = 60_000;
const ddgChallengedUntil = new Map<string, number>();

async function duckDuckGoPage(
  page: (typeof DDG_PAGES)[number],
  query: string,
  signal: AbortSignal,
): Promise<ProviderOutcome> {
  // POST: the GET form of these pages is answered with a bot challenge far more often.
  const res = await fetch(page.url, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      accept: "text/html,application/xhtml+xml",
      "accept-language": "en-US,en;q=0.9,ko;q=0.8",
      "user-agent": BROWSER_USER_AGENT,
      referer: page.url,
    },
    body: new URLSearchParams({ q: query, ...page.form }).toString(),
    signal,
  });
  await ensureOk(res);
  const html = await res.text();
  const results = page.parse(html);
  if (results.length === 0 && /anomaly-modal|bots use DuckDuckGo/i.test(html)) {
    ddgChallengedUntil.set(page.id, Date.now() + DDG_CHALLENGE_COOLDOWN_MS);
    throw new ProviderError("bot challenge");
  }
  return { results };
}

async function duckDuckGoResultPages(query: string, signal: AbortSignal): Promise<ProviderOutcome> {
  const now = Date.now();
  const cooling = (id: string) => (ddgChallengedUntil.get(id) ?? 0) > now;
  // Pages that are not cooling down go first; a cooling page is still tried last.
  const pages = [...DDG_PAGES].sort((a, b) => Number(cooling(a.id)) - Number(cooling(b.id)));
  let lastError: unknown = null;
  for (const page of pages) {
    if (signal.aborted) break;
    try {
      const outcome = await duckDuckGoPage(page, query, signal);
      if (outcome.results.length > 0) return outcome;
      lastError = new ProviderError("no results");
    } catch (error) {
      if (signal.aborted) throw error;
      lastError = error;
    }
  }
  throw lastError ?? new ProviderError("aborted");
}

function duckDuckGo(): ProviderRun {
  return async (query, _maxResults, signal) => {
    let instantError: unknown = null;
    try {
      const instant = await duckDuckGoInstant(query, signal);
      if (instant.results.length > 0 || instant.answer) return instant;
    } catch (error) {
      if (signal.aborted) throw error;
      instantError = error;
    }
    try {
      return await duckDuckGoResultPages(query, signal);
    } catch (error) {
      if (instantError && !signal.aborted) throw new ProviderError(`${describeError(instantError)}; html ${describeError(error)}`);
      throw error;
    }
  };
}

/** A DeepSeek search is a whole model turn (search + answer), so it gets a longer budget. */
const DEEPSEEK_TIMEOUT_MS = 20_000;

function providerChain(env: JeannieEnv): Array<{ id: SearchProvider; run: ProviderRun; timeoutMs?: number }> {
  const chain: Array<{ id: SearchProvider; run: ProviderRun; timeoutMs?: number }> = [];
  const { deepseekApiKey, deepseekAnthropicBaseUrl, deepseekSearchModel, tavilyApiKey, googleApiKey, googleCseId } = env.search;
  if (deepseekApiKey) {
    chain.push({ id: "deepseek", run: deepseek(deepseekApiKey, deepseekAnthropicBaseUrl, deepseekSearchModel), timeoutMs: DEEPSEEK_TIMEOUT_MS });
  }
  if (tavilyApiKey) chain.push({ id: "tavily", run: tavily(tavilyApiKey) });
  if (googleApiKey && googleCseId) chain.push({ id: "google", run: google(googleApiKey, googleCseId) });
  chain.push({ id: "duckduckgo", run: duckDuckGo() });
  return chain;
}

/** Short, secret-free reason (fetch errors can embed request URLs, which hold API keys). */
function describeError(error: unknown): string {
  if (error instanceof ProviderError) return error.message;
  // Name-based on purpose: DOMException is not a global on every Edge runtime,
  // and a throw from here would escape webSearch's provider loop.
  const name = errorName(error);
  if (name === "TimeoutError") return "timed out";
  if (name === "AbortError") return "aborted";
  if (name === "SyntaxError") return "invalid response";
  return `network error (${name})`;
}

function errorName(error: unknown): string {
  try {
    return typeof error === "object" && error !== null && "name" in error ? String(error.name) : typeof error;
  } catch {
    return "unknown";
  }
}

export interface WebSearchOptions {
  maxResults?: number;
  signal?: AbortSignal | null;
  /** Per-provider budget; 8 s by default, 20 s for DeepSeek (tests shorten it). */
  providerTimeoutMs?: number;
}

// Successful searches are reused for a few minutes (per server instance): the
// same question asked twice, or by the HUD and Telegram, should not spend
// provider quota or DuckDuckGo's per-IP rate limit again.
const CACHE_TTL_MS = 5 * 60_000;
const CACHE_MAX_ENTRIES = 100;
const searchCache = new Map<string, { expires: number; response: SearchResponse }>();

function readCache(key: string): SearchResponse | null {
  const entry = searchCache.get(key);
  if (!entry) return null;
  if (entry.expires <= Date.now()) {
    searchCache.delete(key);
    return null;
  }
  return { ...entry.response, results: entry.response.results.map((r) => ({ ...r })) };
}

function writeCache(key: string, response: SearchResponse): void {
  searchCache.delete(key);
  searchCache.set(key, { expires: Date.now() + CACHE_TTL_MS, response });
  // Map keeps insertion order, so the first key is the oldest entry.
  while (searchCache.size > CACHE_MAX_ENTRIES) searchCache.delete(searchCache.keys().next().value as string);
}

/** Forgets cached results and DuckDuckGo cooldowns (process-local state; used by tests). */
export function resetSearchState(): void {
  searchCache.clear();
  ddgChallengedUntil.clear();
}

/** Runs the provider chain; never throws. Each provider gets 8 s before the next one is tried. */
export async function webSearch(query: string, options: WebSearchOptions = {}): Promise<SearchResponse> {
  try {
    return await runProviderChain(query, options);
  } catch (error) {
    // Last line of defence so routes and agents always get a SearchResponse.
    const q = typeof query === "string" ? query.trim().slice(0, MAX_QUERY_CHARS) : "";
    console.error(`[jeannie] web search failed unexpectedly: ${errorName(error)}`);
    return { query: q, provider: "none", results: [], error: `Search failed unexpectedly (${errorName(error)}).` };
  }
}

async function runProviderChain(query: string, options: WebSearchOptions): Promise<SearchResponse> {
  const q = query.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY_CHARS);
  const maxResults = Math.min(10, Math.max(1, Math.floor(options.maxResults ?? 5)));
  if (!q) return { query: q, provider: "none", results: [], error: "Empty search query." };

  const chain = providerChain(getEnv());
  const cacheKey = `${chain.map((p) => p.id).join(",")}|${maxResults}|${q.toLowerCase()}`;
  const cached = readCache(cacheKey);
  if (cached) return cached;

  const failures: string[] = [];
  for (const { id, run, timeoutMs } of chain) {
    if (options.signal?.aborted) break;
    try {
      const budget = options.providerTimeoutMs ?? timeoutMs ?? PROVIDER_TIMEOUT_MS;
      const outcome = await run(q, maxResults, withTimeout(budget, options.signal));
      const results = dedupeResults(outcome.results).slice(0, maxResults);
      if (results.length > 0 || outcome.answer) {
        const response: SearchResponse = { query: q, provider: id, results };
        if (outcome.answer) response.answer = truncate(outcome.answer, 1000);
        writeCache(cacheKey, response);
        return response;
      }
      failures.push(`${id}: no results`);
    } catch (error) {
      failures.push(`${id}: ${describeError(error)}`);
    }
  }

  const error = options.signal?.aborted ? "Search cancelled." : `No live results (${failures.join("; ")}).`;
  return { query: q, provider: "none", results: [], error };
}

function formatDate(value: string | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? truncate(value, 20) : new Date(time).toISOString().slice(0, 10);
}

const PROVIDER_LABEL: Record<SearchProvider | "none", string> = {
  deepseek: "DeepSeek web search",
  tavily: "Tavily",
  google: "Google Custom Search",
  duckduckgo: "DuckDuckGo",
  none: "no provider",
};

/** Numbered briefing for the LLM (and plain-text offline answers): "[n] title (date) — snippet — url". */
export function formatSearchBriefing(res: SearchResponse): string {
  if (res.results.length === 0 && !res.answer) {
    return `No live web results for "${res.query}".${res.error ? ` ${res.error}` : ""}`;
  }
  const lines = [`Live web results for "${res.query}" (via ${PROVIDER_LABEL[res.provider]}):`];
  if (res.answer) lines.push(`Quick answer: ${res.answer}`);
  res.results.forEach((r, i) => {
    const date = formatDate(r.publishedDate);
    const parts = [`[${i + 1}] ${r.title}${date ? ` (${date})` : ""}`];
    if (r.snippet) parts.push(truncate(r.snippet, 300));
    parts.push(r.url);
    lines.push(parts.join(" — "));
  });
  return lines.join("\n");
}

/** The `webSearch` tool for the core agent. `onSources` sees every non-empty result set. */
export function createSearchTool(onSources?: (sources: SourceLink[]) => void) {
  return tool({
    description:
      "Search the live web for fresh, time-sensitive or verifiable facts (news, prices, scores, weather, releases, current events). Returns numbered results with title, url, snippet and date.",
    inputSchema: z.object({ query: z.string().min(1).describe("A concise web search query") }),
    execute: async ({ query }, { abortSignal }) => {
      const res = await webSearch(query, { maxResults: 5, signal: abortSignal });
      if (res.results.length > 0) onSources?.(toSourceLinks(res.results));
      return {
        provider: res.provider,
        answer: res.answer ?? null,
        results: res.results.map((r, i) => ({
          n: i + 1,
          title: r.title,
          url: r.url,
          snippet: truncate(r.snippet, 300),
          date: r.publishedDate ?? null,
        })),
        error: res.error ?? null,
      };
    },
  });
}
