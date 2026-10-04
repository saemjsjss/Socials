import { generateText } from "ai";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLanguageModel, ollamaApiBase } from "@/lib/agents/llm";

const COMPLETION = {
  id: "chatcmpl-1",
  object: "chat.completion",
  created: 0,
  model: "gpt-4o",
  choices: [{ index: 0, message: { role: "assistant", content: "Hello." }, finish_reason: "stop" }],
  usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
};

/** The URL the OpenAI client calls for one generateText round trip. */
async function requestedUrl(): Promise<string> {
  const urls: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    urls.push(String(input instanceof Request ? input.url : input));
    return new Response(JSON.stringify(COMPLETION), { status: 200, headers: { "content-type": "application/json" } });
  });
  const resolved = getLanguageModel("text");
  expect(resolved?.provider).toBe("openai");
  const { text } = await generateText({ model: resolved!.model, prompt: "Hi", maxRetries: 0 });
  expect(text).toBe("Hello.");
  return urls[0];
}

describe("getLanguageModel (OpenAI base URL)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it.each([
    ["blank, as shipped in .env.example", ""],
    ["a your_* placeholder", "your_openai_base_url"],
    ["unset", undefined],
  ])("falls back to api.openai.com when OPENAI_BASE_URL is %s", async (_label, value) => {
    vi.stubEnv("LLM_PROVIDER", "auto");
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubEnv("OPENAI_BASE_URL", value);
    expect(await requestedUrl()).toBe("https://api.openai.com/v1/chat/completions");
  });

  it("uses a configured OpenAI-compatible endpoint", async () => {
    vi.stubEnv("LLM_PROVIDER", "auto");
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubEnv("OPENAI_BASE_URL", "https://llm.example.com/v1");
    expect(await requestedUrl()).toBe("https://llm.example.com/v1/chat/completions");
  });
});

describe("ollamaApiBase", () => {
  it.each([
    ["http://host:11434", "http://host:11434/v1"],
    ["http://host:11434/", "http://host:11434/v1"],
    ["http://host:11434/v1", "http://host:11434/v1"],
    ["http://host:11434/v1/", "http://host:11434/v1"],
  ])("%s → %s", (input, expected) => {
    expect(ollamaApiBase(input)).toBe(expected);
  });
});
