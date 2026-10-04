import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as chat } from "@/app/api/chat/route";
import { GET as hangeulGet } from "@/app/api/hangeul/route";
import { GET as searchGet, POST as searchPost } from "@/app/api/search/route";
import { GET as statusGet } from "@/app/api/status/route";
import { resetSearchState } from "@/lib/agents/search-agent";
import type { ChatMessage, SearchResponse, SourceLink, SystemStatus } from "@/lib/types";
import { decodeHeaderJson } from "@/lib/utils";

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const SECRETS: Record<string, string> = {
  OPENAI_API_KEY: "sk-secret-openai",
  TAVILY_API_KEY: "tvly-secret",
  GOOGLE_CSE_API_KEY: "google-secret",
  GOOGLE_CSE_ID: "cse-id-secret",
  ELEVENLABS_API_KEY: "eleven-secret",
  ELEVENLABS_VOICE_ID: "voice-id-secret",
  TELEGRAM_BOT_TOKEN: "999:telegram-secret",
  TELEGRAM_ADMIN_CHAT_ID: "31337",
  TELEGRAM_WEBHOOK_SECRET: "webhook-secret",
  SUPABASE_URL: "https://supabase-secret.example",
  SUPABASE_SECRET_KEY: "sb_secret_supabase_value",
  JEANNIE_ACCESS_KEY: "access-key-secret",
  CRON_SECRET: "cron-secret-value",
};

const ENV_NAMES = [
  ...Object.keys(SECRETS),
  "DEEPSEEK_API_KEY",
  "ANTHROPIC_API_KEY",
  "NEXT_PUBLIC_SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "LLM_PROVIDER",
  "OLLAMA_BASE_URL",
  "OPENAI_BASE_URL",
  "MOCK_MODE",
];

/** GET /api/status, optionally with the access key. */
const status = (key?: string) => statusGet(request("/api/status", { headers: key ? { "x-jeannie-key": key } : {} }));

function request(path: string, init: { method?: string; body?: unknown; headers?: Record<string, string> } = {}): Request {
  const { method = "GET", body, headers = {} } = init;
  return new Request(`http://localhost${path}`, {
    method,
    headers: { "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });
}

const chatRequest = (body: unknown, headers?: Record<string, string>) => request("/api/chat", { method: "POST", body, headers });
const user = (content: string, image?: string): ChatMessage => ({ role: "user", content, image });

const DDG_INSTANT = {
  Heading: "Seoul",
  AbstractText: "Seoul is the capital of South Korea.",
  AbstractURL: "https://en.wikipedia.org/wiki/Seoul",
  Results: [],
  RelatedTopics: [
    { FirstURL: "https://duckduckgo.com/Busan", Text: "Busan - Second city.", Result: '<a href="https://duckduckgo.com/Busan">Busan</a> - Second city.' },
  ],
};

function stubFetch() {
  const urls: string[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input instanceof Request ? input.url : input);
    urls.push(url);
    if (url.startsWith("https://api.duckduckgo.com/")) return new Response(JSON.stringify(DDG_INSTANT), { status: 202 });
    if (url.startsWith("https://api.telegram.org/")) return Response.json({ ok: true, result: { message_id: 1 } });
    return new Response("nope", { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, urls };
}

beforeEach(() => {
  resetSearchState();
  for (const name of ENV_NAMES) vi.stubEnv(name, "");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("POST /api/chat", () => {
  it("answers IoT commands with the exact sentence and metadata headers", async () => {
    const { fetchMock } = stubFetch();
    const res = await chat(chatRequest({ messages: [user("Turn off the bedroom lights")] }));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/plain; charset=utf-8");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("x-jeannie-agent")).toBe("iot");
    expect(res.headers.get("x-jeannie-provider")).toBe("none");
    expect(res.headers.get("x-jeannie-lang")).toBe("en");
    expect(res.headers.has("x-jeannie-sources")).toBe(false);
    expect(await res.text()).toBe("Yes, it is done.");

    const ko = await chat(chatRequest({ messages: [user("에어컨 꺼줘")], lang: "auto" }));
    expect(ko.headers.get("x-jeannie-lang")).toBe("ko");
    expect(await ko.text()).toBe("네, 처리되었습니다.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("intercepts appliance commands and lets translation requests through", async () => {
    const { fetchMock } = stubFetch();
    const mute = await chat(chatRequest({ messages: [user("Mute the TV")] }));
    expect(mute.headers.get("x-jeannie-agent")).toBe("iot");
    expect(await mute.text()).toBe("Yes, it is done.");

    const washer = await chat(chatRequest({ messages: [user("세탁기 돌려줘")] }));
    expect(washer.headers.get("x-jeannie-agent")).toBe("iot");
    expect(await washer.text()).toBe("네, 처리되었습니다.");

    const translate = await chat(chatRequest({ messages: [user("Translate 'the lights are off' into Korean")], lang: "bilingual" }));
    expect(translate.headers.get("x-jeannie-agent")).toBe("offline");
    expect(await translate.text()).not.toBe("Yes, it is done.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("answers Korean prompts with English terms in Korean", async () => {
    const res = await chat(chatRequest({ messages: [user("React useEffect 설명해줘")], lang: "auto" }));
    expect(res.headers.get("x-jeannie-lang")).toBe("ko");
    expect(await res.text()).toContain("오프라인 모드");
  });

  it("does not search the web for small talk", async () => {
    const { fetchMock } = stubFetch();
    const res = await chat(chatRequest({ messages: [user("I had a rough day today")] }));
    expect(res.headers.get("x-jeannie-agent")).toBe("offline");
    expect(res.headers.has("x-jeannie-sources")).toBe(false);
    await res.text();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("searches a follow-up together with the question it continues", async () => {
    const { urls } = stubFetch();
    const messages: ChatMessage[] = [user("What's the weather in Busan today?"), { role: "assistant", content: "Sunny." }, user("And tomorrow?")];
    const res = await chat(chatRequest({ messages }));
    expect(res.headers.get("x-jeannie-agent")).toBe("search");
    await res.text();
    expect(new URL(urls[0]).searchParams.get("q")).toBe("What's the weather in Busan today? And tomorrow?");
  });

  it("sends an image of a daily report to vision, not to the Hangeul bridge", async () => {
    const res = await chat(chatRequest({ messages: [user("Summarize this daily report")], image: PNG }));
    expect(res.headers.get("x-jeannie-agent")).toBe("offline"); // vision needs a model
    expect(await res.text()).toMatch(/vision/i);
  });

  it("streams offline answers when no model is configured", async () => {
    const res = await chat(chatRequest({ messages: [user("Write a poem about neon")] }));
    expect(res.headers.get("x-jeannie-agent")).toBe("offline");
    expect(await res.text()).toContain("OPENAI_API_KEY");
  });

  it("sends search sources as base64 JSON in a header", async () => {
    stubFetch();
    const res = await chat(chatRequest({ messages: [user("latest news about Seoul")] }));
    expect(res.headers.get("x-jeannie-agent")).toBe("search");
    const sources = decodeHeaderJson<SourceLink[]>(res.headers.get("x-jeannie-sources"));
    expect(sources).toEqual([
      { title: "Seoul", url: "https://en.wikipedia.org/wiki/Seoul" },
      { title: "Busan", url: "https://duckduckgo.com/Busan" },
    ]);
    expect(await res.text()).toContain("[1] Seoul");
  });

  it.each([
    ["invalid JSON", "{nope", "invalid_json"],
    ["no messages", { messages: [] }, "invalid_request"],
    ["last message from the assistant", { messages: [user("hi"), { role: "assistant", content: "hello" }] }, "invalid_request"],
    ["an empty last message", { messages: [user("   ")] }, "invalid_request"],
    ["a non-image data URL", { messages: [user("look")], image: "data:text/plain;base64,aGVsbG8=" }, "invalid_request"],
    ["a remote image URL", { messages: [user("look", "https://example.com/cat.png")] }, "invalid_request"],
    ["an image over 3 MB", { messages: [user("look")], image: `data:image/png;base64,${"A".repeat(4_200_000)}` }, "invalid_request"],
    ["more than 50 messages", { messages: Array.from({ length: 51 }, () => user("hi")) }, "invalid_request"],
    ["a message over 20k characters", { messages: [user("x".repeat(20_001))] }, "invalid_request"],
    ["an unknown language", { messages: [user("hi")], lang: "fr" }, "invalid_request"],
  ])("400 on %s", async (_label, body, code) => {
    const res = await chat(chatRequest(body));
    expect(res.status).toBe(400);
    expect((await res.json()).code).toBe(code);
  });

  it("accepts an image-only message", async () => {
    const res = await chat(chatRequest({ messages: [user("")], image: PNG }));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-jeannie-agent")).toBe("offline"); // vision needs a model
  });

  it("401 when JEANNIE_ACCESS_KEY is set and missing or wrong", async () => {
    vi.stubEnv("JEANNIE_ACCESS_KEY", SECRETS.JEANNIE_ACCESS_KEY);
    const body = { messages: [user("turn on the lights")] };
    expect((await chat(chatRequest(body))).status).toBe(401);
    expect((await chat(chatRequest(body, { "x-jeannie-key": "wrong" }))).status).toBe(401);
    const ok = await chat(chatRequest(body, { "x-jeannie-key": SECRETS.JEANNIE_ACCESS_KEY }));
    expect(ok.status).toBe(200);
    expect(await ok.text()).toBe("Yes, it is done.");
  });
});

describe("GET /api/status", () => {
  it("reports capabilities without secrets and without requiring the access key", async () => {
    for (const [name, value] of Object.entries(SECRETS)) vi.stubEnv(name, value);
    const { fetchMock } = stubFetch();
    const res = await status();
    expect(res.status).toBe(200);
    const raw = await res.text();
    for (const secret of Object.values(SECRETS)) expect(raw).not.toContain(secret);
    const body = JSON.parse(raw) as SystemStatus;
    expect(body).toMatchObject({
      app: "Jeannie AI",
      accessKeyRequired: true,
      llm: { provider: "openai", model: "gpt-4o", visionModel: "gpt-4o" },
      search: { providers: ["tavily", "google", "duckduckgo"] },
      voice: { engines: ["elevenlabs", "edge", "browser"] },
      telegram: { configured: true },
      // Without the key, no volumes: Supabase is not even asked.
      hangeul: { configured: true, records: null, lastRuns: null },
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an offline LLM and unlinked Hangeul data when nothing is configured", async () => {
    const body = (await (await status()).json()) as SystemStatus;
    expect(body.accessKeyRequired).toBe(false);
    expect(body.llm).toEqual({ provider: "none", model: null, visionProvider: "none", visionModel: null });
    expect(body.memory).toEqual({ configured: false });
    expect(body.search.providers).toEqual(["duckduckgo"]);
    expect(body.hangeul).toEqual({ configured: false, records: null, lastRuns: null });
    expect(body.telegram.configured).toBe(false);
  });

  it("an open deployment (no access key) never shows Hangeul volumes", async () => {
    vi.stubEnv("SUPABASE_URL", SECRETS.SUPABASE_URL);
    vi.stubEnv("SUPABASE_SECRET_KEY", SECRETS.SUPABASE_SECRET_KEY);
    const { fetchMock } = stubFetch();
    expect(((await (await status("anything")).json()) as SystemStatus).hangeul).toEqual({ configured: true, records: null, lastRuns: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("/api/search", () => {
  it("GET ?q= returns a SearchResponse", async () => {
    stubFetch();
    const res = await searchGet(request("/api/search?q=Seoul"));
    expect(res.status).toBe(200);
    const body = (await res.json()) as SearchResponse;
    expect(body.provider).toBe("duckduckgo");
    expect(body.results[0].url).toBe("https://en.wikipedia.org/wiki/Seoul");
  });

  it("POST honours maxResults and validates input", async () => {
    stubFetch();
    const res = await searchPost(request("/api/search", { method: "POST", body: { query: "Seoul", maxResults: 1 } }));
    expect(((await res.json()) as SearchResponse).results).toHaveLength(1);
    expect((await searchPost(request("/api/search", { method: "POST", body: { query: "Seoul", maxResults: 11 } }))).status).toBe(400);
    expect((await searchPost(request("/api/search", { method: "POST", body: { query: "  " } }))).status).toBe(400);
    expect((await searchGet(request("/api/search"))).status).toBe(400);
  });

  it("requires the access key when configured", async () => {
    vi.stubEnv("JEANNIE_ACCESS_KEY", SECRETS.JEANNIE_ACCESS_KEY);
    stubFetch();
    expect((await searchGet(request("/api/search?q=Seoul"))).status).toBe(401);
    const ok = await searchGet(request("/api/search?q=Seoul", { headers: { authorization: `Bearer ${SECRETS.JEANNIE_ACCESS_KEY}` } }));
    expect(ok.status).toBe(200);
  });
});

describe("/api/hangeul (the portal bridge is gone)", () => {
  it("never serves demo data: an open API gets 403, and the old actions are just the data status", async () => {
    const { urls } = stubFetch();
    for (const path of ["/api/hangeul", "/api/hangeul?action=report", "/api/hangeul?action=status"]) {
      const res = await hangeulGet(request(path));
      expect(res.status).toBe(403);
      const raw = await res.text();
      expect(raw).not.toMatch(/demo|mock/i);
    }
    expect(urls).toEqual([]);
  });

  it("the old daily cron call pushes nothing to Telegram", async () => {
    vi.stubEnv("CRON_SECRET", SECRETS.CRON_SECRET);
    vi.stubEnv("JEANNIE_ACCESS_KEY", SECRETS.JEANNIE_ACCESS_KEY);
    vi.stubEnv("TELEGRAM_BOT_TOKEN", SECRETS.TELEGRAM_BOT_TOKEN);
    vi.stubEnv("TELEGRAM_ADMIN_CHAT_ID", SECRETS.TELEGRAM_ADMIN_CHAT_ID);
    const { fetchMock } = stubFetch();
    const res = await hangeulGet(request("/api/hangeul", { headers: { authorization: `Bearer ${SECRETS.CRON_SECRET}` } }));
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
