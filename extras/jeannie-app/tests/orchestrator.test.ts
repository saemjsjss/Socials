import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { simulateReadableStream } from "ai";
import { MockLanguageModelV4 } from "ai/test";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { routeQuery, runOrchestrator, runOrchestratorToText } from "@/lib/agents/orchestrator";
import { resetSearchState } from "@/lib/agents/search-agent";
import { IMAGE_PLACEHOLDER } from "@/lib/agents/vision-agent";
import { readersFromRecords } from "@/lib/hangeul/memory-readers";
import type { ChatMessage } from "@/lib/types";
import { NOW, records, runs } from "./hangeul-fixtures";

/** LanguageModelV4 stream part, derived from the mock so tests need no transitive import. */
type StreamPart = Awaited<ReturnType<MockLanguageModelV4["doStream"]>>["stream"] extends ReadableStream<infer T> ? T : never;

const usage = {
  inputTokens: { total: 10, noCache: 10, cacheRead: 0, cacheWrite: 0 },
  outputTokens: { total: 5, text: 5, reasoning: 0 },
};
const finish = (reason: "stop" | "tool-calls" = "stop") => ({ type: "finish", usage, finishReason: { unified: reason, raw: reason } });
const textParts = (...deltas: string[]) => [
  { type: "text-start", id: "t" },
  ...deltas.map((delta) => ({ type: "text-delta", id: "t", delta })),
  { type: "text-end", id: "t" },
];

/** Mock model: each call to doStream plays the next script (the last one repeats). */
function mockModel(...scripts: unknown[][]) {
  let call = 0;
  return new MockLanguageModelV4({
    doStream: async () => {
      const chunks = scripts[Math.min(call++, scripts.length - 1)] as StreamPart[];
      return { stream: simulateReadableStream({ chunks, initialDelayInMs: null, chunkDelayInMs: null }) };
    },
  });
}

function systemPrompt(model: MockLanguageModelV4, call = 0): string {
  const first = model.doStreamCalls[call]?.prompt[0];
  return first?.role === "system" ? first.content : "";
}

const user = (content: string, image?: string): ChatMessage => ({ role: "user", content, image });
const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const DDG_INSTANT = {
  Heading: "Seoul",
  AbstractText: "Seoul is the capital of South Korea.",
  AbstractURL: "https://en.wikipedia.org/wiki/Seoul",
  Results: [],
  RelatedTopics: Array.from({ length: 7 }, (_, i) => ({
    FirstURL: `https://duckduckgo.com/Topic_${i}`,
    Text: `${"Very long topic title ".repeat(5)}${i} - snippet ${i}`,
    Result: `<a href="https://duckduckgo.com/Topic_${i}">${"Very long topic title ".repeat(5)}${i}</a> - snippet ${i}`,
  })),
};

function stubSearch(instant: unknown = DDG_INSTANT) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.startsWith("https://api.duckduckgo.com/")) return new Response(JSON.stringify(instant), { status: 202 });
    return new Response("<html></html>", { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  resetSearchState();
  for (const name of [
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_BASE_URL",
    "LLM_PROVIDER",
    "TAVILY_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
  ]) {
    vi.stubEnv(name, "");
  }
  for (const name of ["MOCK_MODE", "SUPABASE_SECRET_KEY", "NEXT_PUBLIC_SUPABASE_URL"]) vi.stubEnv(name, "");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("routeQuery", () => {
  it.each([
    [{ text: "Turn on the living room lights", hasImage: false }, "iot", "en"],
    [{ text: "거실 불 꺼줘", hasImage: false }, "iot", "ko"],
    [{ text: "set the thermostat to 22 degrees", hasImage: true }, "iot", "en"],
    [{ text: "불 켜줘", hasImage: false, lang: "en" as const }, "iot", "en"],
    [{ text: "Show me the Hangeul report", hasImage: false }, "hangeul", "en"],
    [{ text: "한글 포털 상태 확인해줘", hasImage: true }, "hangeul", "ko"],
    [{ text: "What does this sign say?", hasImage: true }, "vision", "en"],
    [{ text: "", hasImage: true, lang: "bilingual" as const }, "vision", "bilingual"],
    [{ text: "What's the latest news on the Fed?", hasImage: false }, "search", "en"],
    [{ text: "오늘 서울 날씨 어때?", hasImage: false }, "search", "ko"],
    [{ text: "Write me a haiku about neon rain", hasImage: false }, "core", "en"],
    [{ text: "Write me a haiku", hasImage: false, lang: "ko" as const }, "core", "ko"],
    [{ text: "Explain kimchi bilingually", hasImage: false }, "core", "bilingual"],
  ])("%j → %s (%s)", (input, agent, lang) => {
    const route = routeQuery(input);
    expect(route.agent).toBe(agent);
    expect(route.lang).toBe(lang);
    expect(route.reason).toBeTruthy();
  });

  it.each([
    ["Summarize this daily report", "en"],
    ["Read this daily report and translate it into Korean", "en"],
    ["Summarize the daily report", "en"],
    ["Here is a screenshot of the Hangeul portal, what's wrong?", "en"],
    ["이 일일 보고서 번역해줘", "ko"],
    ["이 관리자 보고서 스크린샷 요약해줘", "ko"],
  ])("sends an attached report image to vision: %j", (text, lang) => {
    expect(routeQuery({ text, hasImage: true })).toMatchObject({ agent: "vision", lang });
    expect(routeQuery({ text, hasImage: false }).agent).toBe("hangeul");
  });

  it("keeps explicit portal requests with the bridge even with an image", () => {
    expect(routeQuery({ text: "Show me the Hangeul report", hasImage: true }).agent).toBe("hangeul");
    expect(routeQuery({ text: "한글 포털 상태 확인해줘", hasImage: true }).agent).toBe("hangeul");
  });

  it.each([
    ["React useEffect 설명해줘", "core", "ko"],
    ["Next.js App Router 사용법", "core", "ko"],
    ["iPhone 15 Pro Max 가격 알려줘", "search", "ko"],
    ["Answer in Korean: what is photosynthesis?", "core", "ko"],
    ["영어로 대답해줘: 광합성이 뭐야?", "core", "en"],
    ["Explain photosynthesis in English and Korean", "core", "bilingual"],
    ["광합성 한영으로 설명해줘", "core", "bilingual"],
  ])("resolves the answer language of %j", (text, agent, lang) => {
    expect(routeQuery({ text, hasImage: false })).toMatchObject({ agent, lang });
  });

  it("gives an image-only turn the language of the previous user turn, else English", () => {
    expect(routeQuery({ text: "", hasImage: true, previous: ["사진 하나 보낼게요", ""] })).toMatchObject({ agent: "vision", lang: "ko" });
    expect(routeQuery({ text: " ", hasImage: true, previous: ["Here comes a photo"] }).lang).toBe("en");
    expect(routeQuery({ text: "", hasImage: true }).lang).toBe("en");
    expect(routeQuery({ text: "", hasImage: true, previous: ["사진 봐줘"], lang: "en" }).lang).toBe("en");
  });

  it.each([
    "I had a rough day today",
    "Good morning Jeannie, what should I focus on today?",
    "오늘 기분이 안 좋아",
    "오늘 저녁 메뉴 추천해줘",
    "최근에 스트레스를 많이 받아",
    "이 코드 맞는지 확인해줘: const x = 1",
    "Write a New Year greeting card for 2026",
  ])("keeps small talk with the core agent: %j", (text) => {
    expect(routeQuery({ text, hasImage: false }).agent).toBe("core");
  });

  it("routes follow-ups of a live search to search, but not pleasantries or unrelated turns", () => {
    const weather = ["What's the weather in Busan today?"];
    expect(routeQuery({ text: "And tomorrow?", hasImage: false, previous: weather }).agent).toBe("search");
    expect(routeQuery({ text: "내일은?", hasImage: false, previous: ["부산 오늘 날씨 어때?"] })).toMatchObject({ agent: "search", lang: "ko" });
    expect(routeQuery({ text: "thanks!", hasImage: false, previous: weather }).agent).toBe("core");
    expect(routeQuery({ text: "And tomorrow?", hasImage: false, previous: ["Write me a poem"] }).agent).toBe("core");
    expect(routeQuery({ text: "And tomorrow?", hasImage: false }).agent).toBe("core");
  });

  it("does not intercept a translation request as IoT, whatever the HUD mode", () => {
    const text = "Translate 'the lights are off' into Korean";
    expect(routeQuery({ text, hasImage: false }).agent).toBe("core");
    expect(routeQuery({ text, hasImage: false, lang: "bilingual" })).toMatchObject({ agent: "core", lang: "bilingual" });
  });
});

describe("IoT interceptor path", () => {
  it.each([
    ["Turn off the bedroom fan", undefined, "Yes, it is done."],
    ["에어컨 켜줘", undefined, "네, 처리되었습니다."],
    ["lock the front door", "ko" as const, "네, 처리되었습니다."],
  ])("answers %j with the exact sentence, no network and no LLM", async (text, lang, expected) => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    const fetchMock = vi.fn(async () => {
      throw new Error("network must not be used");
    });
    vi.stubGlobal("fetch", fetchMock);
    const model = mockModel(textParts("should not be used"));

    const result = await runOrchestratorToText({ messages: [user(text)], lang }, { trusted: true, model, honorific: "자기야" });
    expect(result).toEqual({
      agent: "iot",
      lang: expected === "Yes, it is done." ? "en" : "ko",
      provider: "none",
      honorific: "자기야",
      sources: [],
      text: expected,
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(model.doStreamCalls).toHaveLength(0);
  });
});

describe("offline mode (no LLM configured)", () => {
  it("core and vision answer with a short setup hint in the resolved language", async () => {
    const en = await runOrchestratorToText({ messages: [user("Write a poem")] }, { trusted: false });
    expect(en).toMatchObject({ agent: "offline", provider: "none", lang: "en", sources: [] });
    expect(en.text).toContain("OPENAI_API_KEY");
    expect(en.text).toContain("OLLAMA_BASE_URL");

    const ko = await runOrchestratorToText({ messages: [user("시 한 편 써줘")] }, { trusted: false });
    expect(ko.lang).toBe("ko");
    expect(ko.text).toContain("오프라인 모드");

    const vision = await runOrchestratorToText({ messages: [user("what is this?")], image: PNG }, { trusted: false });
    expect(vision.agent).toBe("offline");
    expect(vision.text).toMatch(/vision/i);
  });

  it("search still works and returns raw results with sources", async () => {
    stubSearch();
    const result = await runOrchestratorToText({ messages: [user("latest news about Seoul")] }, { trusted: false });
    expect(result.agent).toBe("search");
    expect(result.provider).toBe("none");
    expect(result.sources).toHaveLength(5);
    expect(result.sources[0]).toEqual({ title: "Seoul", url: "https://en.wikipedia.org/wiki/Seoul" });
    for (const s of result.sources) expect(s.title.length).toBeLessThanOrEqual(80);
    expect(result.text).toContain("[1] Seoul");
    expect(result.text).toContain("https://en.wikipedia.org/wiki/Seoul");
  });

  it("says live search failed (not the generic offline line) when search comes back empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input instanceof Request ? input.url : input);
        if (url.startsWith("https://api.duckduckgo.com/")) return new Response(JSON.stringify({ RelatedTopics: [] }), { status: 202 });
        return new Response('<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>', { status: 202 });
      }),
    );
    const en = await runOrchestratorToText({ messages: [user("latest news about Seoul")] }, { trusted: false });
    expect(en).toMatchObject({ agent: "offline", provider: "none", lang: "en", sources: [] });
    expect(en.text).toContain("Live search came back empty");
    expect(en.text).toContain("TAVILY_API_KEY");
    expect(en.text).not.toContain("live search and Hangeul reports still work");

    const ko = await runOrchestratorToText({ messages: [user("오늘 서울 날씨 어때?")] }, { trusted: false });
    expect(ko).toMatchObject({ agent: "offline", lang: "ko" });
    expect(ko.text).toContain("실시간 검색 결과를 받지 못했어요");
  });

  it("Hangeul data answers still work: code-built figures, no model, and never demo data", async () => {
    const fetchMock = stubSearch();
    const hangeul = readersFromRecords({ records: records(), runs: runs() });
    const result = await runOrchestratorToText(
      { messages: [user("how many consultancies were closed today?")] },
      { trusted: true, hangeul, now: NOW },
    );
    expect(result).toMatchObject({ agent: "hangeul", provider: "none", sources: [] });
    expect(result.text).toContain("Consultancies done today (30 Sep): 20");
    expect(result.text).toContain("As of 17:35 (full picture)");
    expect(result.text).not.toMatch(/demo|mock/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("without Supabase configured, a trusted Hangeul question says so", async () => {
    const result = await runOrchestratorToText({ messages: [user("hangeul report please")] }, { trusted: true });
    expect(result).toMatchObject({ agent: "hangeul", provider: "none" });
    expect(result.text).toContain("The Hangeul data isn't connected");
  });
});

describe("search agent", () => {
  it("returns sources up front and grounds the model in the briefing", async () => {
    stubSearch();
    const model = mockModel(textParts("Seoul is the capital [1]."));
    const result = await runOrchestrator({ messages: [user("latest news about Seoul")] }, { trusted: false, model });
    expect(result.agent).toBe("search");
    expect(result.provider).toBe("openai");
    expect(result.sources).toHaveLength(5);
    expect(await new Response(result.stream).text()).toBe("Seoul is the capital [1].");
    const system = systemPrompt(model);
    expect(system).toContain("Live Search Agent");
    expect(system).toContain("[1] Seoul — Seoul is the capital of South Korea. — https://en.wikipedia.org/wiki/Seoul");
    expect(model.doStreamCalls[0].tools ?? []).toHaveLength(0);
  });

  it("falls back to core (without the search tool) when search finds nothing", async () => {
    stubSearch({ Heading: "", AbstractText: "", AbstractURL: "", Results: [], RelatedTopics: [] });
    const model = mockModel(textParts("From memory: ..."));
    const result = await runOrchestratorToText({ messages: [user("latest news about nothing")] }, { trusted: false, model });
    expect(result.agent).toBe("core");
    expect(result.sources).toEqual([]);
    expect(result.text).toBe("From memory: ...");
    expect(systemPrompt(model)).toContain("Live web search returned nothing");
    expect(model.doStreamCalls[0].tools ?? []).toHaveLength(0);
  });

  it("serves the raw results when the model fails before any text", async () => {
    stubSearch();
    const model = mockModel([{ type: "error", error: new Error("rate limited") }]);
    const result = await runOrchestratorToText({ messages: [user("latest news about Seoul")] }, { trusted: false, model });
    expect(result.agent).toBe("search");
    expect(result.text).toContain("[1] Seoul");
  });
});

describe("search query for follow-ups", () => {
  const searchedFor = (fetchMock: ReturnType<typeof stubSearch>) =>
    fetchMock.mock.calls
      .map(([input]) => new URL(String(input instanceof Request ? input.url : input)))
      .filter((url) => url.hostname === "api.duckduckgo.com")
      .map((url) => url.searchParams.get("q"));

  it("without a model, prefixes a follow-up with the question it continues", async () => {
    const fetchMock = stubSearch();
    const en = await runOrchestratorToText(
      { messages: [user("What's the weather in Busan today?"), { role: "assistant", content: "Sunny, 24°C." }, user("And tomorrow?")] },
      { trusted: false },
    );
    expect(en.agent).toBe("search");
    expect(searchedFor(fetchMock)).toEqual(["What's the weather in Busan today? And tomorrow?"]);

    fetchMock.mockClear();
    const ko = await runOrchestratorToText(
      { messages: [user("부산 오늘 날씨 어때?"), { role: "assistant", content: "맑아요." }, user("내일은?")] },
      { trusted: false },
    );
    expect(ko).toMatchObject({ agent: "search", lang: "ko" });
    expect(searchedFor(fetchMock)).toEqual(["부산 오늘 날씨 어때? 내일은?"]);
  });

  it("searches a standalone question as it is", async () => {
    const fetchMock = stubSearch();
    await runOrchestratorToText(
      { messages: [user("Write me a poem"), { role: "assistant", content: "Roses..." }, user("latest news about Seoul")] },
      { trusted: false },
    );
    expect(searchedFor(fetchMock)).toEqual(["latest news about Seoul"]);
  });

  it("with a model, asks it for a standalone query from the recent turns", async () => {
    const fetchMock = stubSearch();
    const model = new MockLanguageModelV4({
      doGenerate: async () => ({
        content: [{ type: "text", text: '"Busan weather forecast tomorrow"\n' }],
        finishReason: { unified: "stop", raw: "stop" },
        usage,
        warnings: [],
      }),
      doStream: async () => ({
        stream: simulateReadableStream({ chunks: [...textParts("Rain [1]."), finish()] as StreamPart[], initialDelayInMs: null, chunkDelayInMs: null }),
      }),
    });
    const messages: ChatMessage[] = [user("What's the weather in Busan today?"), { role: "assistant", content: "Sunny, 24°C." }, user("And tomorrow?")];
    const result = await runOrchestratorToText({ messages }, { trusted: false, model });
    expect(result).toMatchObject({ agent: "search", text: "Rain [1]." });
    expect(searchedFor(fetchMock)).toEqual(["Busan weather forecast tomorrow"]);
    const prompt = JSON.stringify(model.doGenerateCalls[0].prompt);
    expect(prompt).toContain("User: What's the weather in Busan today?");
    expect(prompt).toContain("Assistant: Sunny, 24°C.");
    expect(prompt).toContain("User: And tomorrow?");
  });

  it("falls back to the heuristic query when the rewrite fails", async () => {
    const fetchMock = stubSearch();
    const model = mockModel(textParts("Rain."));
    const messages: ChatMessage[] = [user("What's the weather in Busan today?"), { role: "assistant", content: "Sunny." }, user("And tomorrow?")];
    const result = await runOrchestratorToText({ messages }, { trusted: false, model });
    expect(result.agent).toBe("search");
    expect(searchedFor(fetchMock)).toEqual(["What's the weather in Busan today? And tomorrow?"]);
  });
});

describe("language of the answer", () => {
  it("tells the model the language the message asked for", async () => {
    const ko = mockModel(textParts("광합성은..."));
    await runOrchestratorToText({ messages: [user("Answer in Korean: what is photosynthesis?")] }, { trusted: false, model: ko });
    expect(systemPrompt(ko)).toContain("Respond in Korean");

    const mixed = mockModel(textParts("useEffect는..."));
    await runOrchestratorToText({ messages: [user("React useEffect 설명해줘")] }, { trusted: false, model: mixed });
    expect(systemPrompt(mixed)).toContain("Respond in Korean");

    const en = mockModel(textParts("Photosynthesis is..."));
    await runOrchestratorToText({ messages: [user("영어로 대답해줘: 광합성이 뭐야?")] }, { trusted: false, model: en });
    expect(systemPrompt(en)).toContain("Respond in English.");
  });

  it("analyses an image-only turn in the language of the previous user turn", async () => {
    const model = mockModel(textParts("작은 픽셀이에요."));
    const messages: ChatMessage[] = [user("사진 하나 보낼게요"), { role: "assistant", content: "네, 보내 주세요." }, user("")];
    const result = await runOrchestratorToText({ messages, image: PNG }, { trusted: false, model });
    expect(result).toMatchObject({ agent: "vision", lang: "ko" });
    const latest = model.doStreamCalls[0].prompt.at(-1);
    expect(latest?.role === "user" ? latest.content[0] : null).toMatchObject({ type: "text", text: "이 이미지를 분석해 주세요." });
  });

  it("sends a photographed daily report to the vision agent with the image", async () => {
    const model = mockModel(textParts("A daily report."));
    const result = await runOrchestratorToText({ messages: [user("Summarize this daily report")], image: PNG }, { trusted: false, model });
    expect(result.agent).toBe("vision");
    const latest = model.doStreamCalls[0].prompt.at(-1);
    expect(latest?.role === "user" ? latest.content[1] : null).toMatchObject({ type: "file", mediaType: "image/png" });
  });

  it("keeps small talk away from the search providers", async () => {
    const fetchMock = stubSearch();
    const model = mockModel(textParts("Sorry to hear that."));
    const result = await runOrchestratorToText({ messages: [user("I had a rough day today")] }, { trusted: false, model });
    expect(result).toMatchObject({ agent: "core", sources: [], text: "Sorry to hear that." });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("core agent", () => {
  it("streams model text with the last 20 messages and the webSearch tool on OpenAI", async () => {
    const model = mockModel(textParts("Hello, ", "operator."));
    const history: ChatMessage[] = Array.from({ length: 30 }, (_, i) =>
      i % 2 === 0 ? user(`question ${i}`) : { role: "assistant", content: `answer ${i}` },
    );
    history.push(user("Write me a haiku"));
    const result = await runOrchestrator({ messages: history }, { trusted: false, model });
    expect(result).toMatchObject({ agent: "core", provider: "openai", lang: "en", sources: [] });
    expect(await new Response(result.stream).text()).toBe("Hello, operator.");

    const call = model.doStreamCalls[0];
    expect(call.prompt.filter((m) => m.role !== "system")).toHaveLength(20);
    expect(call.tools?.map((t) => t.name)).toEqual(["webSearch", "readUrl", "currentTime", "convertTime"]);
    expect(systemPrompt(model)).toContain("General Cognitive Agent");
  });

  it("skips tools for Ollama", async () => {
    const model = mockModel(textParts("hi"));
    const result = await runOrchestrator({ messages: [user("hello")] }, { trusted: false, model, provider: "ollama" });
    expect(result.provider).toBe("ollama");
    await new Response(result.stream).text();
    expect(model.doStreamCalls[0].tools ?? []).toHaveLength(0);
  });

  it("runs the webSearch tool and appends sources the answer did not cite", async () => {
    const fetchMock = stubSearch();
    const model = mockModel(
      [{ type: "tool-call", toolCallId: "c1", toolName: "webSearch", input: JSON.stringify({ query: "Seoul" }) }, finish("tool-calls")],
      [...textParts("Seoul is the capital."), finish()],
    );
    const result = await runOrchestratorToText({ messages: [user("Tell me about Seoul")] }, { trusted: false, model });
    expect(fetchMock).toHaveBeenCalled();
    expect(model.doStreamCalls).toHaveLength(2);
    expect(result.text.startsWith("Seoul is the capital.\n\nSources:\n[1] Seoul — https://en.wikipedia.org/wiki/Seoul")).toBe(true);
  });

  it("forbids tool calls on the last step so the model answers from what it found", async () => {
    stubSearch();
    const toolCall = (id: string) => [
      { type: "tool-call", toolCallId: id, toolName: "webSearch", input: JSON.stringify({ query: "Seoul" }) },
      finish("tool-calls"),
    ];
    let call = 0;
    const model = new MockLanguageModelV4({
      doStream: async (options) => ({
        stream: simulateReadableStream({
          chunks: (options.toolChoice?.type === "none" ? [...textParts("Seoul is the capital."), finish()] : toolCall(`c${++call}`)) as StreamPart[],
          initialDelayInMs: null,
          chunkDelayInMs: null,
        }),
      }),
    });
    const result = await runOrchestratorToText({ messages: [user("Tell me about Seoul")] }, { trusted: false, model });
    expect(model.doStreamCalls.map((c) => c.toolChoice?.type)).toEqual(["auto", "auto", "auto", "none"]);
    expect(model.doStreamCalls[3].tools?.map((t) => t.name)).toEqual(["webSearch", "readUrl", "currentTime", "convertTime"]);
    expect(result.text.startsWith("Seoul is the capital.\n\nSources:\n[1] Seoul — https://en.wikipedia.org/wiki/Seoul")).toBe(true);
  });

  it("keeps the sources when the model still ends without text", async () => {
    stubSearch();
    const model = mockModel([
      { type: "tool-call", toolCallId: "c1", toolName: "webSearch", input: JSON.stringify({ query: "Seoul" }) },
      finish("tool-calls"),
    ]);
    const result = await runOrchestratorToText({ messages: [user("Tell me about Seoul")] }, { trusted: false, model });
    expect(result.text.startsWith("I came up empty on that one.")).toBe(true);
    expect(result.text).toContain("\n\nSources:\n[1] Seoul — https://en.wikipedia.org/wiki/Seoul");
  });

  it("separates the text of consecutive tool-loop steps with a blank line", async () => {
    stubSearch();
    const model = mockModel(
      [
        ...textParts("Let me check that."),
        { type: "tool-call", toolCallId: "c1", toolName: "webSearch", input: JSON.stringify({ query: "Seoul" }) },
        finish("tool-calls"),
      ],
      [...textParts("Seoul is the capital."), finish()],
    );
    const result = await runOrchestratorToText({ messages: [user("Tell me about Seoul")] }, { trusted: false, model });
    expect(result.text.startsWith("Let me check that.\n\nSeoul is the capital.\n\nSources:")).toBe(true);
  });

  it("turns a mid-stream provider error into a graceful closing line", async () => {
    const model = mockModel([...textParts("Half an ans").slice(0, 2), { type: "error", error: new Error("socket hang up") }]);
    const result = await runOrchestratorToText({ messages: [user("Explain quantum tunnelling")] }, { trusted: false, model });
    expect(result.text.startsWith("Half an ans\n\n[Connection to the language model dropped mid-answer.")).toBe(true);
  });

  it("emits a friendly line when the model fails before any text", async () => {
    const failing = new MockLanguageModelV4({
      doStream: async () => {
        throw new Error("ECONNREFUSED 127.0.0.1:11434");
      },
    });
    const ko = await runOrchestratorToText({ messages: [user("안녕, 자기소개 해줘")] }, { trusted: false, model: failing });
    expect(ko.text).toBe("지금은 언어 모델에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.");

    const erroring = mockModel([{ type: "error", error: new Error("boom") }]);
    const en = await runOrchestratorToText({ messages: [user("hello")] }, { trusted: false, model: erroring });
    expect(en.text).toBe("I couldn't reach my language model just now. Please try again in a moment.");
  });

  it("closes quietly when the client aborts", async () => {
    const controller = new AbortController();
    const model = new MockLanguageModelV4({
      doStream: async () => ({
        stream: simulateReadableStream({ chunks: [...textParts("a", "b", "c"), finish()] as StreamPart[], chunkDelayInMs: 30 }),
      }),
    });
    const result = await runOrchestrator({ messages: [user("hello")] }, { trusted: false, model, signal: controller.signal });
    const reader = result.stream.getReader();
    const first = await reader.read();
    expect(new TextDecoder().decode(first.value)).toBe("a");
    controller.abort();
    let rest = "";
    for (let r = await reader.read(); !r.done; r = await reader.read()) rest += new TextDecoder().decode(r.value);
    expect(rest).not.toContain("Connection");
  });
});

describe("vision agent", () => {
  it("sends the image on the latest user turn only", async () => {
    const model = mockModel(textParts("A tiny pixel."));
    const messages: ChatMessage[] = [user("first photo", PNG), { role: "assistant", content: "A cat." }, user("")];
    const result = await runOrchestratorToText({ messages, image: PNG, lang: "ko" }, { trusted: false, model });
    expect(result).toMatchObject({ agent: "vision", lang: "ko", text: "A tiny pixel." });

    const prompt = model.doStreamCalls[0].prompt;
    expect(prompt[1]).toMatchObject({ role: "user", content: [{ type: "text", text: `first photo\n${IMAGE_PLACEHOLDER}` }] });
    const latest = prompt.at(-1);
    expect(latest?.role).toBe("user");
    const parts = latest?.role === "user" ? latest.content : [];
    expect(parts[0]).toMatchObject({ type: "text", text: "이 이미지를 분석해 주세요." });
    expect(parts[1]).toMatchObject({ type: "file", mediaType: "image/png" });
    expect(systemPrompt(model)).toContain("Vision & Localization Agent");
  });
});

describe("hangeul agent with a model", () => {
  /** A model for generateText (the Hangeul prose is checked before it is sent, so it is not streamed). */
  function proseModel(text: string | Error) {
    return new MockLanguageModelV4({
      doGenerate: async () => {
        if (text instanceof Error) throw text;
        return { content: [{ type: "text", text }], finishReason: { unified: "stop", raw: "stop" }, usage, warnings: [] };
      },
    });
  }
  const hangeul = () => readersFromRecords({ records: records(), runs: runs() });
  const ask = (content: string, model: MockLanguageModelV4, trusted = true) =>
    runOrchestratorToText({ messages: [user(content)] }, { trusted, model, hangeul: hangeul(), now: NOW });

  it("puts two checked sentences before the code-built facts; a sentence with a made-up number is dropped", async () => {
    const model = proseModel("[emote:nod] 20 consultancies done today, 부장님, with TEST CONSULTANT C on 8. That is 45% more than usual.");
    const result = await ask("how many consultancies were closed today?", model);
    expect(result).toMatchObject({ agent: "hangeul", provider: "openai" });
    expect(result.text.startsWith("[emote:nod] 20 consultancies done today, 부장님, with TEST CONSULTANT C on 8.\n\nConsultancies done today (30 Sep): 20")).toBe(true);
    expect(result.text).not.toContain("45%");
    expect(result.text).toContain("As of 17:35 (full picture)");
    // The model saw the directive and the facts with their values (D11).
    const prompt = JSON.stringify(model.doGenerateCalls[0].prompt);
    expect(prompt).toContain("Hangeul data desk");
    expect(prompt).toContain("TEST CONSULTANT C");
    expect(prompt).toContain("Every number you write must appear in that JSON");
  });

  it("shows the facts alone when the model fails", async () => {
    const result = await ask("how many consultancies were closed today?", proseModel(new Error("down")));
    expect(result.provider).toBe("none");
    expect(result.text.startsWith("Consultancies done today (30 Sep): 20")).toBe(true);
  });

  it("never reads the data for an untrusted caller", async () => {
    const model = proseModel("should not be used");
    const result = await ask("how many consultancies were closed today?", model, false);
    expect(result.text).toContain("access key");
    expect(result.text).not.toContain("20");
    expect(model.doGenerateCalls).toHaveLength(0);
  });
});

// ─── Real provider path: @ai-sdk/openai against a local OpenAI-compatible server ───

interface CapturedRequest {
  url: string;
  authorization: string | undefined;
  body: { model: string; tools?: Array<{ function: { name: string } }>; messages: Array<{ role: string }> };
}

type Script = (res: ServerResponse, call: number) => void;

const sse = (res: ServerResponse, chunks: unknown[], opts: { cut?: boolean } = {}) => {
  res.writeHead(200, { "content-type": "text/event-stream" });
  for (const chunk of chunks) res.write(`data: ${JSON.stringify(chunk)}\n\n`);
  if (opts.cut) {
    // Drop the connection mid-answer, after the first chunk has reached the client.
    setTimeout(() => res.destroy(), 50);
    return;
  }
  res.end("data: [DONE]\n\n");
};
const delta = (d: Record<string, unknown>, finish: string | null = null) => ({
  id: "c1",
  object: "chat.completion.chunk",
  created: 1,
  model: "m",
  choices: [{ index: 0, delta: d, finish_reason: finish }],
});

describe("real provider over a local OpenAI-compatible server", () => {
  let server: Server;
  let baseUrl = "";
  let script: Script = () => undefined;
  const captured: CapturedRequest[] = [];

  beforeAll(async () => {
    server = createServer((req: IncomingMessage, res: ServerResponse) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        captured.push({ url: req.url ?? "", authorization: req.headers.authorization, body: JSON.parse(raw) });
        script(res, captured.length);
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  beforeEach(() => {
    captured.length = 0;
  });

  it("streams an Ollama answer through /v1/chat/completions without tools", async () => {
    vi.stubEnv("LLM_PROVIDER", "ollama");
    vi.stubEnv("OLLAMA_BASE_URL", `${baseUrl}/`);
    vi.stubEnv("OLLAMA_MODEL", "llama3.1");
    script = (res) => sse(res, [delta({ role: "assistant", content: "Hello " }), delta({ content: "operator." }), delta({}, "stop")]);

    const result = await runOrchestratorToText({ messages: [user("Say hello")] }, { trusted: false });
    expect(result).toMatchObject({ agent: "core", provider: "ollama", text: "Hello operator." });
    expect(captured[0].url).toBe("/v1/chat/completions");
    expect(captured[0].body.model).toBe("llama3.1");
    expect(captured[0].body.tools).toBeUndefined();
  });

  it("runs the OpenAI tool loop (webSearch) and cites sources", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-local-test");
    vi.stubEnv("OPENAI_BASE_URL", `${baseUrl}/v1`);
    const realFetch = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.startsWith("https://api.duckduckgo.com/")) return new Response(JSON.stringify(DDG_INSTANT), { status: 202 });
      return realFetch(input, init);
    });
    script = (res, call) =>
      call === 1
        ? sse(res, [
            delta({
              role: "assistant",
              tool_calls: [{ index: 0, id: "call_1", type: "function", function: { name: "webSearch", arguments: '{"query":"Seoul"}' } }],
            }),
            delta({}, "tool_calls"),
          ])
        : sse(res, [delta({ role: "assistant", content: "Seoul is the capital [1]." }), delta({}, "stop")]);

    const result = await runOrchestratorToText({ messages: [user("Tell me about Seoul")] }, { trusted: false });
    expect(result.agent).toBe("core");
    expect(result.provider).toBe("openai");
    expect(captured).toHaveLength(2);
    expect(captured[0].authorization).toBe("Bearer sk-local-test");
    expect(captured[0].body.model).toBe("gpt-4o");
    expect(captured[0].body.tools?.map((t) => t.function.name)).toEqual(["webSearch", "readUrl", "currentTime", "convertTime"]);
    expect(captured[1].body.messages.map((m) => m.role)).toEqual(["system", "user", "assistant", "tool"]);
    expect(result.text).toContain("Seoul is the capital [1].");
    expect(result.text).toContain("Sources:\n[1] Seoul — https://en.wikipedia.org/wiki/Seoul");
  });

  it("appends a graceful line when the connection drops mid-stream", async () => {
    vi.stubEnv("LLM_PROVIDER", "ollama");
    vi.stubEnv("OLLAMA_BASE_URL", baseUrl);
    script = (res) => sse(res, [delta({ role: "assistant", content: "Partial answ" })], { cut: true });
    const result = await runOrchestratorToText({ messages: [user("Explain entropy")] }, { trusted: false });
    expect(result.text.startsWith("Partial answ\n\n[Connection to the language model dropped mid-answer.")).toBe(true);
  });

  it("answers with a friendly line when the server returns an HTTP error", async () => {
    vi.stubEnv("LLM_PROVIDER", "ollama");
    vi.stubEnv("OLLAMA_BASE_URL", baseUrl);
    script = (res) => {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message: "model 'llama3.1' not found" } }));
    };
    const result = await runOrchestratorToText({ messages: [user("안녕하세요")] }, { trusted: false });
    expect(result.text).toBe("지금은 언어 모델에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.");
  });
});
