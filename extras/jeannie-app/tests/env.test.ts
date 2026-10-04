import { afterEach, describe, expect, it, vi } from "vitest";
import { getEnv } from "@/lib/env";

afterEach(() => {
  vi.unstubAllEnvs();
});

function stubClean() {
  vi.stubEnv("DEEPSEEK_API_KEY", "");
  vi.stubEnv("ANTHROPIC_API_KEY", "");
  vi.stubEnv("OPENAI_API_KEY", "");
  vi.stubEnv("LLM_PROVIDER", "");
  vi.stubEnv("OLLAMA_BASE_URL", "");
  vi.stubEnv("VERCEL", "");
}

describe("LLM provider selection", () => {
  it("prefers OpenAI when a key is set", () => {
    stubClean();
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubEnv("OLLAMA_BASE_URL", "http://localhost:11434");
    expect(getEnv().llm.provider).toBe("openai");
  });

  it("treats .env.example placeholders as unset", () => {
    stubClean();
    vi.stubEnv("OPENAI_API_KEY", "your_openai_api_key_here");
    expect(getEnv().llm.provider).toBe("none");
  });

  it("uses a local Ollama outside Vercel", () => {
    stubClean();
    vi.stubEnv("OLLAMA_BASE_URL", "http://localhost:11434");
    expect(getEnv().llm.provider).toBe("ollama");
  });

  it("ignores a loopback Ollama URL on Vercel", () => {
    stubClean();
    vi.stubEnv("VERCEL", "1");
    vi.stubEnv("OLLAMA_BASE_URL", "http://127.0.0.1:11434");
    expect(getEnv().llm.provider).toBe("none");
  });

  it("keeps a reachable Ollama server on Vercel", () => {
    stubClean();
    vi.stubEnv("VERCEL", "1");
    vi.stubEnv("OLLAMA_BASE_URL", "https://ollama.example.com");
    expect(getEnv().llm.provider).toBe("ollama");
  });
});
