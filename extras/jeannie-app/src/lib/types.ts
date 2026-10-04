// Shared contracts between the HUD (client), the API routes and the agents.
// Keep this file dependency-free so it can be imported from any runtime.

/** Language the user picked in the HUD. `auto` detects from the message text. */
export type LangMode = "auto" | "en" | "ko" | "bilingual";

/** Language Jeannie actually answers in, after resolving `auto`. */
export type ResolvedLang = "en" | "ko" | "bilingual";

/** Which specialist handled a message. */
export type AgentId =
  | "iot" // IoT Interceptor: deterministic smart-home confirmation
  | "search" // Live Search Agent
  | "vision" // Multimodal Vision & Korean/English Localization Agent
  | "hangeul" // Hangeul Admin & Reporting Bridge
  | "audit" // Mistake audit: framed recommendations, then approval → execution confirmation
  | "core" // General Cognitive Agent (LLM, may still call the search tool)
  | "offline"; // No LLM configured/reachable: canned or search-only answers

export type LlmProvider = "deepseek" | "anthropic" | "openai" | "ollama" | "none";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Optional image as a data URL (`data:image/jpeg;base64,...`). User messages only. */
  image?: string | null;
}

/** POST /api/chat body. */
export interface ChatRequestBody {
  messages: ChatMessage[];
  /** Image for the latest user message (data URL). Same as setting `image` on that message. */
  image?: string | null;
  lang?: LangMode;
  /** What the PWA computed on the device for a Hangeul question (used only when it routes to Hangeul). */
  hangeul?: HangeulDeviceHints;
}

/** The device's question vector (384 numbers, or their base64 float32 form) and/or its own search hits. */
export interface HangeulDeviceHints {
  embedding?: number[] | string;
  hits?: { kind: string; key: string }[];
}

/**
 * /api/chat response contract:
 *  - 200, `Content-Type: text/plain; charset=utf-8`, body = streamed answer text.
 *  - Metadata in headers (see CHAT_HEADERS). Sources are `encodeHeaderJson(SourceLink[])`.
 *  - Errors: JSON `ApiError` with 4xx/5xx.
 */
export const CHAT_HEADERS = {
  agent: "x-jeannie-agent",
  lang: "x-jeannie-lang",
  provider: "x-jeannie-provider",
  sources: "x-jeannie-sources",
  /** How Jeannie addressed the user in this reply (URI-encoded: 부장님 / 자기야). */
  honorific: "x-jeannie-honorific",
} as const;

/** How Jeannie addresses the user: 부장님 in work/business context, 자기야 in affectionate/personal moments. */
export type Honorific = "부장님" | "자기야";

/** Header carrying the access key from the HUD (alternatively `Authorization: Bearer`). */
export const ACCESS_KEY_HEADER = "x-jeannie-key";

export interface SourceLink {
  title: string;
  url: string;
}

export interface ApiError {
  error: string;
  code: string;
}

export type SearchProvider = "deepseek" | "tavily" | "google" | "duckduckgo";

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  source: SearchProvider;
  publishedDate?: string;
}

/** GET/POST /api/search response. */
export interface SearchResponse {
  query: string;
  provider: SearchProvider | "none";
  /** Short synthesized answer when the provider offers one (DeepSeek, Tavily, DuckDuckGo instant answers). */
  answer?: string;
  results: SearchResult[];
  /** Human-readable note when every provider failed or none is configured. */
  error?: string;
}

/** POST /api/tts body. Response: `audio/mpeg` bytes, or JSON ApiError (503 = use browser voice). */
export interface TtsRequestBody {
  text: string;
  lang?: "en" | "ko";
}

export type TtsEngine = "elevenlabs" | "edge" | "browser";

/** Header on /api/tts audio responses naming the engine that produced it. */
export const TTS_ENGINE_HEADER = "x-jeannie-tts-engine";

/** The newest finished run of one Hangeul BOT job (hg_runs). */
export interface HangeulRunSummary {
  job: string;
  /** ISO time. */
  finishedAt: string;
  status: "ok" | "partial" | "failed" | null;
}

/** A report record's key and times (no content). */
export interface HangeulReportSummary {
  key: string;
  /** The report's name (its scope): "brief", "missing_report", "document_check"... */
  report: string;
  day: string | null;
  read_at: string;
}

/** GET /api/hangeul response: the state of the data Hangeul BOT publishes (no student data). */
export interface HangeulDataStatus {
  configured: true;
  records: number;
  lastRuns: HangeulRunSummary[];
  latestBrief: HangeulReportSummary | null;
  latestReport: HangeulReportSummary | null;
}

/** GET /api/status response: which capabilities are configured (never secrets). */
export interface SystemStatus {
  app: string;
  voiceName: string;
  accessKeyRequired: boolean;
  llm: {
    provider: LlmProvider;
    model: string | null;
    /** Image analysis can use a different provider than text (DeepSeek has no vision). */
    visionProvider: LlmProvider;
    visionModel: string | null;
  };
  memory: { configured: boolean };
  search: { providers: SearchProvider[] };
  voice: { engines: TtsEngine[] };
  telegram: { configured: boolean };
  /** The Hangeul data in Supabase. `records` and `lastRuns` only for a caller with the access key (else null). */
  hangeul: { configured: boolean; records: number | null; lastRuns: HangeulRunSummary[] | null };
  /** The business time zone (JEANNIE_TIMEZONE): Hangeul days and "as of" times, also for answers built on the device. */
  timeZone: string;
  time: string;
}

/** GET /api/session response: Jeannie's opening line for a new session. */
export interface SessionGreeting {
  greeting: string;
  honorific: Honorific;
  /** Local wall-clock time used for the greeting, e.g. "08:15". */
  localTime: string;
  timeZone: string;
  /** "ai" = written by the language model; "template" = the fixed fallback. */
  source: "ai" | "template";
}

/** A document stored in Jeannie's Supabase memory. */
export interface MemoryDocument {
  id: string;
  title: string;
  source_name: string;
  kind: "markdown" | "jsonl";
  pinned: boolean;
  bytes: number;
  chunks: number;
  updated_at: string;
}
