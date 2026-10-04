import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLanguageModel } from "@/lib/agents/llm";
import { runOrchestratorToText } from "@/lib/agents/orchestrator";
import { resetSearchState } from "@/lib/agents/search-agent";
import { GET as statusGET } from "@/app/api/status/route";
import { getEnv } from "@/lib/env";

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

/** A minimal Anthropic Messages API stream that answers with `text`. */
function claudeStream(text: string): Response {
  const events: Array<[string, unknown]> = [
    ["message_start", { type: "message_start", message: { id: "msg_1", type: "message", role: "assistant", model: "claude-opus-5", content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 12, output_tokens: 1 } } }],
    ["content_block_start", { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } }],
    ["content_block_delta", { type: "content_block_delta", index: 0, delta: { type: "text_delta", text } }],
    ["content_block_stop", { type: "content_block_stop", index: 0 }],
    ["message_delta", { type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null }, usage: { output_tokens: 6 } }],
    ["message_stop", { type: "message_stop" }],
  ];
  const body = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

interface CapturedRequest {
  url: string;
  headers: Headers;
  body: Record<string, unknown>;
}

function mockClaude(answer: string): CapturedRequest[] {
  const calls: CapturedRequest[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input);
    calls.push({ url, headers: new Headers(init?.headers), body: JSON.parse(String(init?.body ?? "{}")) });
    return claudeStream(answer);
  });
  return calls;
}

function useClaude(extra: Record<string, string> = {}) {
  vi.stubEnv("LLM_PROVIDER", "auto");
  vi.stubEnv("DEEPSEEK_API_KEY", "");
  vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
  vi.stubEnv("OPENAI_API_KEY", "");
  vi.stubEnv("OLLAMA_BASE_URL", "");
  vi.stubEnv("ANTHROPIC_MODEL", "");
  vi.stubEnv("ANTHROPIC_VISION_MODEL", "");
  for (const [key, value] of Object.entries(extra)) vi.stubEnv(key, value);
}

beforeEach(() => {
  resetSearchState();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Claude provider selection", () => {
  it("picks Claude Opus 5 when ANTHROPIC_API_KEY is set", () => {
    useClaude();
    expect(getEnv().llm).toMatchObject({ provider: "anthropic", model: "claude-opus-5", visionModel: "claude-opus-5" });
  });

  it("prefers Claude over OpenAI in auto mode", () => {
    useClaude({ OPENAI_API_KEY: "sk-openai" });
    expect(getEnv().llm.provider).toBe("anthropic");
  });

  it("honours an explicit LLM_PROVIDER and custom models", () => {
    useClaude({ OPENAI_API_KEY: "sk-openai", LLM_PROVIDER: "openai" });
    expect(getEnv().llm.provider).toBe("openai");

    useClaude({ LLM_PROVIDER: "anthropic", ANTHROPIC_MODEL: "claude-sonnet-5", ANTHROPIC_VISION_MODEL: "claude-haiku-4-5" });
    expect(getEnv().llm).toMatchObject({ provider: "anthropic", model: "claude-sonnet-5", visionModel: "claude-haiku-4-5" });
  });

  it("stays offline when LLM_PROVIDER=anthropic but the key is missing or a placeholder", () => {
    useClaude({ LLM_PROVIDER: "anthropic", ANTHROPIC_API_KEY: "your_anthropic_api_key" });
    expect(getEnv().llm.provider).toBe("none");
    expect(getLanguageModel("text")).toBeNull();
  });
});

describe("Claude requests through the orchestrator", () => {
  it("streams a core answer from the Messages API with tools and refusal fallbacks", async () => {
    useClaude();
    const calls = mockClaude("Hello from Claude.");

    const result = await runOrchestratorToText(
      { messages: [{ role: "user", content: "Explain photosynthesis in one line" }] },
      { trusted: false },
    );

    expect(result).toMatchObject({ agent: "core", provider: "anthropic", text: "Hello from Claude." });
    expect(calls).toHaveLength(1);
    const [call] = calls;
    expect(call.url).toBe("https://api.anthropic.com/v1/messages");
    expect(call.headers.get("x-api-key")).toBe("sk-ant-test");
    expect(call.headers.get("anthropic-beta")).toContain("server-side-fallback-2026-07-01");
    expect(call.body).toMatchObject({ model: "claude-opus-5", stream: true, fallbacks: "default" });
    expect((call.body.tools as Array<{ name: string }>).map((t) => t.name)).toContain("webSearch");
    // Claude Opus 5 rejects sampling parameters.
    expect(call.body).not.toHaveProperty("temperature");
    expect(call.body).not.toHaveProperty("top_p");
  });

  it("sends an attached image as a base64 image block to the vision model", async () => {
    useClaude({ ANTHROPIC_VISION_MODEL: "claude-sonnet-5" });
    const calls = mockClaude("A single pink pixel.");

    const result = await runOrchestratorToText(
      { messages: [{ role: "user", content: "What is in this picture?", image: PNG }] },
      { trusted: false },
    );

    expect(result).toMatchObject({ agent: "vision", provider: "anthropic", text: "A single pink pixel." });
    const body = calls[0].body as { model: string; messages: Array<{ content: Array<Record<string, unknown>> }> };
    expect(body.model).toBe("claude-sonnet-5");
    const blocks = body.messages.at(-1)!.content;
    expect(blocks).toContainEqual(
      expect.objectContaining({ type: "image", source: expect.objectContaining({ type: "base64", media_type: "image/png" }) }),
    );
  });

  it("still answers smart-home commands without calling Claude", async () => {
    useClaude();
    const calls = mockClaude("should not be used");

    const result = await runOrchestratorToText({ messages: [{ role: "user", content: "Turn on the lights" }] }, { trusted: false });

    expect(result).toMatchObject({ agent: "iot", provider: "none", text: "Yes, it is done." });
    expect(calls).toHaveLength(0);
  });
});

describe("/api/status with Claude", () => {
  it("reports the Claude models without exposing the key", async () => {
    useClaude();
    const res = await statusGET(new Request("http://localhost/api/status"));
    const status = (await res.json()) as { llm: unknown };

    expect(status.llm).toEqual({
      provider: "anthropic",
      model: "claude-opus-5",
      visionProvider: "anthropic",
      visionModel: "claude-opus-5",
    });
    expect(JSON.stringify(status)).not.toContain("sk-ant-test");
  });
});
