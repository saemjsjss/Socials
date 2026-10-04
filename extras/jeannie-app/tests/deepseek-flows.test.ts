// DeepSeek as the brain, the honorific on every reply, memory in the prompt,
// the audit → approval flow, and the /api/session and /api/memory routes.

import { generateText, simulateReadableStream } from "ai";
import { MockLanguageModelV4 } from "ai/test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as chat } from "@/app/api/chat/route";
import { DELETE as memoryDelete, GET as memoryGet, PATCH as memoryPatch, POST as memoryPost } from "@/app/api/memory/route";
import { GET as sessionGet } from "@/app/api/session/route";
import { GET as statusGet } from "@/app/api/status/route";
import { APPROVAL_MARKER, APPROVAL_REQUEST_LINE } from "@/lib/agents/audit-flow";
import { getLanguageModel, supportsTools } from "@/lib/agents/llm";
import { runOrchestratorToText } from "@/lib/agents/orchestrator";
import { resetSearchState } from "@/lib/agents/search-agent";
import { EMOTE_DIRECTIVE } from "@/lib/emote";
import { getEnv } from "@/lib/env";
import type { ChatMessage, SessionGreeting, SystemStatus } from "@/lib/types";

type StreamPart = Awaited<ReturnType<MockLanguageModelV4["doStream"]>>["stream"] extends ReadableStream<infer T> ? T : never;

const usage = {
  inputTokens: { total: 10, noCache: 10, cacheRead: 0, cacheWrite: 0 },
  outputTokens: { total: 5, text: 5, reasoning: 0 },
};
const textParts = (...deltas: string[]) => [
  { type: "text-start", id: "t" },
  ...deltas.map((delta) => ({ type: "text-delta", id: "t", delta })),
  { type: "text-end", id: "t" },
  { type: "finish", usage, finishReason: { unified: "stop", raw: "stop" } },
];

function mockModel(...deltas: string[]) {
  return new MockLanguageModelV4({
    doStream: async () => ({
      stream: simulateReadableStream({ chunks: textParts(...deltas) as StreamPart[], initialDelayInMs: null, chunkDelayInMs: null }),
    }),
  });
}

function systemPrompt(model: MockLanguageModelV4): string {
  const first = model.doStreamCalls[0]?.prompt[0];
  return first?.role === "system" ? first.content : "";
}

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string): ChatMessage => ({ role: "assistant", content });

const ENV = [
  "DEEPSEEK_API_KEY",
  "DEEPSEEK_MODEL",
  "DEEPSEEK_VISION_MODEL",
  "DEEPSEEK_BASE_URL",
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "OLLAMA_BASE_URL",
  "LLM_PROVIDER",
  "TAVILY_API_KEY",
  "GOOGLE_CSE_API_KEY",
  "GOOGLE_CSE_ID",
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "NEXT_PUBLIC_SUPABASE_URL",
  "SUPABASE_SECRET_KEY",
  "JEANNIE_ACCESS_KEY",
  "JEANNIE_TIMEZONE",
  "ELEVENLABS_API_KEY",
  "ELEVENLABS_VOICE_ID",
  "VERCEL",
  "MOCK_MODE",
];

beforeEach(() => {
  resetSearchState();
  for (const name of ENV) vi.stubEnv(name, "");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ─── DeepSeek provider ──────────────────────────────────────────────────────

describe("DeepSeek as the brain", () => {
  it("is picked first in auto mode, with its default model", () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
    vi.stubEnv("OPENAI_API_KEY", "sk-openai-test");
    // DeepSeek retired the deepseek-chat / deepseek-reasoner aliases on 24 July 2026.
    expect(getEnv().llm).toMatchObject({ provider: "deepseek", model: "deepseek-v4-flash" });
  });

  it("honours LLM_PROVIDER=deepseek and DEEPSEEK_MODEL, and stays offline without a key", () => {
    vi.stubEnv("LLM_PROVIDER", "deepseek");
    vi.stubEnv("OPENAI_API_KEY", "sk-openai-test");
    expect(getEnv().llm.provider).toBe("none");
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubEnv("DEEPSEEK_MODEL", "deepseek-v4-pro");
    expect(getEnv().llm).toMatchObject({ provider: "deepseek", model: "deepseek-v4-pro" });
  });

  it("maps the retired deepseek-chat / deepseek-reasoner names to a live model", () => {
    // A stale DEEPSEEK_MODEL=deepseek-chat in the deployment would otherwise break every reply.
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubEnv("DEEPSEEK_MODEL", "deepseek-chat");
    vi.stubEnv("DEEPSEEK_SEARCH_MODEL", " DeepSeek-Reasoner ");
    const env = getEnv();
    expect(env.llm.model).toBe("deepseek-v4-flash");
    expect(env.search.deepseekSearchModel).toBe("deepseek-v4-flash");
    vi.stubEnv("DEEPSEEK_MODEL", "deepseek-reasoner");
    expect(getEnv().llm.model).toBe("deepseek-v4-flash");
  });

  it("sends images to Claude or OpenAI when set, else to DeepSeek's vision model", () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    expect(getEnv().llm).toMatchObject({ visionProvider: "deepseek", visionModel: "deepseek-v4-flash-vision-exp" });
    expect(getLanguageModel("vision")).toMatchObject({ provider: "deepseek", modelId: "deepseek-v4-flash-vision-exp" });
    vi.stubEnv("DEEPSEEK_VISION_MODEL", "deepseek-vl-custom");
    expect(getEnv().llm.visionModel).toBe("deepseek-vl-custom");

    vi.stubEnv("OPENAI_API_KEY", "sk-openai-test");
    expect(getEnv().llm).toMatchObject({ visionProvider: "openai", visionModel: "gpt-4o" });
    expect(getLanguageModel("vision")?.provider).toBe("openai");

    vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
    expect(getEnv().llm).toMatchObject({ visionProvider: "anthropic", visionModel: "claude-opus-5" });
    expect(getLanguageModel("vision")?.provider).toBe("anthropic");
    expect(getLanguageModel("text")?.provider).toBe("deepseek");
  });

  it("calls the DeepSeek chat completions endpoint with thinking off", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    const urls: string[] = [];
    const auth: string[] = [];
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      urls.push(String(input));
      auth.push(new Headers(init?.headers).get("authorization") ?? "");
      bodies.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
      return new Response(
        JSON.stringify({
          id: "c1",
          object: "chat.completion",
          created: 0,
          model: "deepseek-v4-flash",
          choices: [{ index: 0, message: { role: "assistant", content: "Hello, sir." }, finish_reason: "stop" }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const resolved = getLanguageModel("text");
    expect(resolved).toMatchObject({ provider: "deepseek", modelId: "deepseek-v4-flash" });
    const { text } = await generateText({
      model: resolved!.model,
      prompt: "Hi",
      providerOptions: resolved!.providerOptions,
      maxRetries: 0,
    });
    expect(text).toBe("Hello, sir.");
    expect(urls[0]).toBe("https://api.deepseek.com/chat/completions");
    expect(auth[0]).toBe("Bearer sk-deepseek-test");
    // V4 models think before answering by default; Jeannie speaks, so she answers straight away.
    expect(bodies[0]).toMatchObject({ model: "deepseek-v4-flash", thinking: { type: "disabled" } });
  });

  it("uses tools on DeepSeek chat models but not on deepseek-reasoner", () => {
    expect(supportsTools({ provider: "deepseek", modelId: "deepseek-v4-flash" })).toBe(true);
    expect(supportsTools({ provider: "deepseek", modelId: "deepseek-chat" })).toBe(true);
    expect(supportsTools({ provider: "deepseek", modelId: "deepseek-reasoner" })).toBe(false);
    expect(supportsTools({ provider: "ollama", modelId: "llama3.1" })).toBe(false);
    expect(supportsTools({ provider: "anthropic", modelId: "claude-opus-5" })).toBe(true);
  });

  it("shows up in /api/status with the vision provider and memory", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test_key_value");
    vi.stubEnv("ELEVENLABS_API_KEY", "eleven-test");
    const raw = await statusGET();
    const body = JSON.parse(raw) as SystemStatus;
    expect(body.llm).toEqual({
      provider: "deepseek",
      model: "deepseek-v4-flash",
      visionProvider: "deepseek",
      visionModel: "deepseek-v4-flash-vision-exp",
    });
    expect(body.memory).toEqual({ configured: true });
    // ElevenLabs is the main voice with only the API key set (default voice id).
    expect(body.voice.engines[0]).toBe("elevenlabs");
    for (const secret of ["sk-deepseek-test", "sb_secret_test_key_value", "eleven-test"]) expect(raw).not.toContain(secret);
  });
});

async function statusGET(): Promise<string> {
  return (await statusGet(new Request("http://localhost/api/status"))).text();
}

// ─── Orchestrator: honorific, memory, audit flow ────────────────────────────

describe("honorific on every reply", () => {
  it("puts the chosen title in the system prompt and the result", async () => {
    const model = mockModel("네, 부장님.");
    const result = await runOrchestratorToText({ messages: [user("hello")] }, { trusted: false, model, honorific: "부장님" });
    expect(result).toMatchObject({ agent: "core", honorific: "부장님", text: "네, 부장님." });
    expect(systemPrompt(model)).toContain('Address the user as "부장님" in this reply');
  });

  it("chooses one from the message when the caller does not fix it", async () => {
    const work = mockModel("ok");
    expect((await runOrchestratorToText({ messages: [user("Draft the budget memo")] }, { trusted: false, model: work })).honorific).toBe("부장님");
    const personal = mockModel("ok");
    const result = await runOrchestratorToText({ messages: [user("오늘 너무 피곤해")] }, { trusted: false, model: personal });
    expect(result.honorific).toBe("자기야");
    expect(systemPrompt(personal)).toContain('Address the user as "자기야" in this reply');
  });

  it("ends every system prompt with the emote protocol", async () => {
    const model = mockModel("[emote:nod] 네, 부장님.");
    const result = await runOrchestratorToText({ messages: [user("hello")] }, { trusted: false, model, honorific: "부장님" });
    expect(systemPrompt(model).trimEnd().endsWith(EMOTE_DIRECTIVE)).toBe(true);
    // The chat stream keeps the tag; the client parses it.
    expect(result.text).toBe("[emote:nod] 네, 부장님.");
  });

  it("travels URI-encoded in the chat response header", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0.1);
    const res = await chat(
      new Request("http://localhost/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: [user("turn off the lights")] }),
      }),
    );
    expect(res.headers.get("x-jeannie-agent")).toBe("iot");
    expect(decodeURIComponent(res.headers.get("x-jeannie-honorific") ?? "")).toBe("부장님");
  });
});

describe("memory in the prompt", () => {
  it("adds recalled notes for trusted callers only", async () => {
    const recall = vi.fn(async () => "Your memory: HGLC is at Green Landmark, Kalabagan.");
    const trustedModel = mockModel("HGLC is at Green Landmark.");
    await runOrchestratorToText({ messages: [user("Where is HGLC?")] }, { trusted: true, model: trustedModel, honorific: "자기야", recall });
    expect(recall).toHaveBeenCalledWith("Where is HGLC?", undefined);
    expect(systemPrompt(trustedModel)).toContain("HGLC is at Green Landmark, Kalabagan.");

    recall.mockClear();
    const openModel = mockModel("I don't know.");
    await runOrchestratorToText({ messages: [user("Where is HGLC?")] }, { trusted: false, model: openModel, honorific: "자기야", recall });
    expect(recall).not.toHaveBeenCalled();
    expect(systemPrompt(openModel)).not.toContain("Green Landmark");
  });

  it("never looks up memory for IoT commands", async () => {
    const recall = vi.fn(async () => "notes");
    const result = await runOrchestratorToText({ messages: [user("turn on the lights")] }, { trusted: true, recall, honorific: "자기야" });
    expect(result.agent).toBe("iot");
    expect(recall).not.toHaveBeenCalled();
  });

  it("answers without memory when recall fails", async () => {
    const model = mockModel("Hello.");
    const recall = vi.fn(async () => {
      throw new Error("supabase down");
    });
    const result = await runOrchestratorToText({ messages: [user("hello")] }, { trusted: true, model, honorific: "자기야", recall });
    expect(result.text).toBe("Hello.");
  });
});

const AUDIT_REPLY = `■ 점검 결과 (Audit)
One issue.
1. 문제 / Issue — 3 x 4 is 12, not 13 · 원인 / Cause — arithmetic slip · 권장 조치 / Recommendation — correct the total to 12`;

describe("audit → approval flow", () => {
  it("routes an audit request to the audit agent and always ends with the approval request", async () => {
    const model = mockModel(AUDIT_REPLY);
    const result = await runOrchestratorToText(
      { messages: [user("Please do a mistake audit: 3 x 4 = 13")] },
      { trusted: false, model, honorific: "부장님" },
    );
    expect(result.agent).toBe("audit");
    expect(systemPrompt(model)).toContain("Role: Mistake Audit Agent");
    expect(systemPrompt(model)).toContain(APPROVAL_REQUEST_LINE);
    expect(result.text).toBe(`${AUDIT_REPLY}\n\n${APPROVAL_REQUEST_LINE}`);
  });

  it("confirms execution on approval without calling the model", async () => {
    const model = mockModel("must not be used");
    const onAuditDecision = vi.fn();
    const pending = `${AUDIT_REPLY}\n\n${APPROVAL_REQUEST_LINE}`;
    const result = await runOrchestratorToText(
      { messages: [user("audit this: 3 x 4 = 13"), assistant(pending), user("승인")] },
      { trusted: false, model, honorific: "부장님", onAuditDecision },
    );
    expect(result).toMatchObject({ agent: "audit", provider: "none", lang: "ko", honorific: "부장님" });
    expect(result.text).toBe(
      "네, 부장님. 승인하신 권장 조치를 진행하겠습니다. 완료되면 보고드리겠습니다.\n\n승인된 항목:\n1. 문제 / Issue — 3 x 4 is 12, not 13 · 원인 / Cause — arithmetic slip · 권장 조치 / Recommendation — correct the total to 12",
    );
    expect(model.doStreamCalls).toHaveLength(0);
    expect(onAuditDecision).toHaveBeenCalledWith("approved", [expect.stringContaining("3 x 4 is 12")]);
  });

  it("acknowledges a rejection in English", async () => {
    const onAuditDecision = vi.fn();
    const result = await runOrchestratorToText(
      { messages: [user("check my mistakes"), assistant(`${AUDIT_REPLY}\n${APPROVAL_MARKER}: ...`), user("cancel")] },
      { trusted: false, honorific: "자기야", onAuditDecision },
    );
    expect(result.text).toContain("Understood, 자기야. I've put the recommendations on hold.");
    expect(onAuditDecision).toHaveBeenCalledWith("rejected", expect.any(Array));
  });

  it("treats an approval with nothing pending as a normal message", async () => {
    const model = mockModel("Approve what, sir?");
    const result = await runOrchestratorToText({ messages: [user("hi"), assistant("Hello."), user("approve")] }, { trusted: false, model, honorific: "자기야" });
    expect(result).toMatchObject({ agent: "core", text: "Approve what, sir?" });
  });

  it("explains that an audit needs a model when none is connected", async () => {
    const result = await runOrchestratorToText({ messages: [user("실수 점검해줘: 3 x 4 = 13")] }, { trusted: false, honorific: "자기야" });
    expect(result).toMatchObject({ agent: "offline", lang: "ko" });
    expect(result.text).toContain("DEEPSEEK_API_KEY");
  });
});

// ─── /api/session ───────────────────────────────────────────────────────────

describe("GET /api/session", () => {
  function deepseekReply(content: string, prompts: string[]) {
    return async (_input: RequestInfo | URL, init?: RequestInit) => {
      prompts.push(String(init?.body ?? ""));
      return new Response(
        JSON.stringify({
          id: "c1",
          object: "chat.completion",
          created: 0,
          model: "deepseek-chat",
          choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
  }

  it("falls back to the template greeting for the operator's local time without a model", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-28T03:30:00Z")); // 09:30 in Dhaka
    vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      const res = await sessionGet(new Request("http://localhost/api/session?awayMs=7200000"));
      const body = (await res.json()) as SessionGreeting;
      expect(body).toMatchObject({ honorific: "부장님", localTime: "09:30", timeZone: "Asia/Dhaka", source: "template" });
      expect(body.greeting.startsWith("좋은 아침입니다, 부장님. ")).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("asks the model for a Korean greeting with the time away, and strips a stray emote tag", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    const prompts: string[] = [];
    vi.stubGlobal("fetch", deepseekReply("[emote:greeting] 좋은 저녁이에요, 자기야. 세 시간 동안 보고 싶었어요.", prompts));
    const res = await sessionGet(new Request("http://localhost/api/session?awayMs=10800000"));
    const body = (await res.json()) as SessionGreeting;
    expect(body).toMatchObject({ source: "ai", greeting: "좋은 저녁이에요, 자기야. 세 시간 동안 보고 싶었어요.", honorific: "자기야" });
    expect(prompts[0]).toContain("away for 약 3시간");
  });

  it("uses the template when the model answers with something unusable", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubGlobal("fetch", deepseekReply("Good evening!", []));
    const body = (await (await sessionGet(new Request("http://localhost/api/session"))).json()) as SessionGreeting;
    expect(body.source).toBe("template");
  });

  it("uses the template in MOCK_MODE", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "sk-deepseek-test");
    vi.stubEnv("MOCK_MODE", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const body = (await (await sessionGet(new Request("http://localhost/api/session"))).json()) as SessionGreeting;
    expect(body.source).toBe("template");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses JEANNIE_TIMEZONE, ignores an invalid one, and needs the access key when set", async () => {
    const zone = async () => ((await (await sessionGet(new Request("http://localhost/api/session"))).json()) as SessionGreeting).timeZone;
    vi.stubEnv("JEANNIE_TIMEZONE", "Asia/Seoul");
    expect(await zone()).toBe("Asia/Seoul");
    vi.stubEnv("JEANNIE_TIMEZONE", "Mars/Olympus");
    expect(await zone()).toBe("Asia/Dhaka");
    vi.stubEnv("JEANNIE_ACCESS_KEY", "key-123");
    expect((await sessionGet(new Request("http://localhost/api/session"))).status).toBe(401);
    expect((await sessionGet(new Request("http://localhost/api/session", { headers: { "x-jeannie-key": "key-123" } }))).status).toBe(200);
  });
});

// ─── /api/memory ────────────────────────────────────────────────────────────

describe("/api/memory", () => {
  const KEY = "access-key-123";
  const memoryRequest = (method: string, init: { body?: unknown; query?: string; key?: string | null; form?: FormData } = {}) => {
    const headers: Record<string, string> = {};
    if (init.key !== null) headers["x-jeannie-key"] = init.key ?? KEY;
    let body: BodyInit | undefined;
    if (init.form) body = init.form;
    else if (init.body !== undefined) {
      headers["content-type"] = "application/json";
      body = JSON.stringify(init.body);
    }
    return new Request(`http://localhost/api/memory${init.query ?? ""}`, { method, headers, body });
  };

  function configure() {
    vi.stubEnv("JEANNIE_ACCESS_KEY", KEY);
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test_key_value");
  }

  function stubRest(respond: (url: string, init?: RequestInit) => Response) {
    const calls: { url: string; method: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? "GET", body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      return respond(String(input), init);
    });
    return calls;
  }

  it("refuses every method until an access key is configured", async () => {
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test_key_value");
    for (const res of [
      await memoryGet(memoryRequest("GET", { key: null })),
      await memoryPost(memoryRequest("POST", { key: null, body: { name: "a.md", content: "x" } })),
    ]) {
      expect(res.status).toBe(403);
      expect(await res.json()).toMatchObject({ code: "access_key_not_configured" });
    }
  });

  it("needs the right key, then a configured Supabase", async () => {
    vi.stubEnv("JEANNIE_ACCESS_KEY", KEY);
    expect((await memoryGet(memoryRequest("GET", { key: "wrong" }))).status).toBe(401);
    const res = await memoryGet(memoryRequest("GET"));
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ code: "memory_not_configured" });
  });

  it("uploads a markdown file as JSON and as multipart", async () => {
    configure();
    const calls = stubRest(() => new Response(JSON.stringify("0b8f6c1e-1111-4222-8333-444455556666"), { status: 200 }));
    const res = await memoryPost(memoryRequest("POST", { body: { name: "profile.md", content: "# Who I Am\nSaemur", pinned: true } }));
    expect(res.status).toBe(201);
    expect(await res.json()).toMatchObject({ document: { title: "Who I Am", kind: "markdown", chunks: 1 } });
    expect(calls[0]).toMatchObject({ url: "https://proj.supabase.co/rest/v1/rpc/upsert_memory_document", body: { p_pinned: true } });

    const form = new FormData();
    form.set("file", new File(["{\"id\":\"a\",\"text\":\"Fact\"}"], "k.jsonl", { type: "application/x-ndjson" }));
    form.set("pinned", "false");
    const multipart = await memoryPost(memoryRequest("POST", { form }));
    expect(multipart.status).toBe(201);
    expect(calls[1].body).toMatchObject({ p_source_name: "k.jsonl", p_kind: "jsonl", p_pinned: false });
  });

  it("rejects bad, oversized and secret-bearing files", async () => {
    configure();
    const calls = stubRest(() => new Response("null"));
    const pdf = await memoryPost(memoryRequest("POST", { body: { name: "a.pdf", content: "x" } }));
    expect(pdf.status).toBe(400);
    const secret = await memoryPost(memoryRequest("POST", { body: { name: "a.md", content: "sk-0000000000000000000000fakekey00" } }));
    expect(secret.status).toBe(400);
    expect(((await secret.json()) as { error: string }).error).toContain("contains secrets");
    const big = await memoryPost(memoryRequest("POST", { body: { name: "a.md", content: "x".repeat(1024 * 1024 + 1) } }));
    expect(big.status).toBe(413);
    const bad = await memoryPost(memoryRequest("POST", { body: { name: "a.jsonl", content: "nope" } }));
    expect(bad.status).toBe(400);
    expect(await bad.json()).toMatchObject({ issues: [{ line: 1, message: "not valid JSON" }] });
    expect(calls).toHaveLength(0);
  });

  it("lists, pins and deletes documents", async () => {
    configure();
    const docs = [{ id: "0b8f6c1e-1111-4222-8333-444455556666", title: "Who I Am", source_name: "profile.md" }];
    const calls = stubRest((url, init) => {
      if ((init?.method ?? "GET") === "GET") return new Response(JSON.stringify(docs));
      return new Response(JSON.stringify(url.includes("ffffffff") ? [] : docs));
    });
    expect(await (await memoryGet(memoryRequest("GET"))).json()).toEqual({ documents: docs });
    expect(calls[0].url).toContain("memory_documents?select=");

    const pin = await memoryPatch(memoryRequest("PATCH", { query: `?id=${docs[0].id}`, body: { pinned: false } }));
    expect(pin.status).toBe(200);
    expect(calls[1]).toMatchObject({ method: "PATCH", body: { pinned: false } });

    expect((await memoryDelete(memoryRequest("DELETE", { query: `?id=${docs[0].id}` }))).status).toBe(200);
    expect((await memoryDelete(memoryRequest("DELETE", { query: "?id=ffffffff-1111-4222-8333-444455556666" }))).status).toBe(404);
    expect((await memoryDelete(memoryRequest("DELETE", { query: "?id=not-a-uuid" }))).status).toBe(400);
    expect((await memoryDelete(memoryRequest("DELETE"))).status).toBe(400);
  });

  it("tells the operator to apply the migration when the tables are missing", async () => {
    configure();
    stubRest(() => new Response(JSON.stringify({ code: "42P01", message: "relation does not exist" }), { status: 404 }));
    const res = await memoryGet(memoryRequest("GET"));
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ code: "memory_not_migrated" });
  });
});

describe("Supabase variable names", () => {
  it("accepts NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SECRET_KEY, preferring the server names", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://pub.supabase.co/");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_alias");
    expect(getEnv().memory).toEqual({ supabaseUrl: "https://pub.supabase.co", serviceKey: "sb_secret_alias", enabled: true });

    vi.stubEnv("SUPABASE_URL", "https://server.supabase.co");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_main");
    expect(getEnv().memory).toMatchObject({ supabaseUrl: "https://server.supabase.co", serviceKey: "sb_secret_main" });
  });

  it("stays off with only the publishable key", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://pub.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_x");
    expect(getEnv().memory.enabled).toBe(false);
  });
});
