// Language model resolution. DeepSeek (Jeannie's default brain) goes through
// the AI SDK's DeepSeek provider and Claude through the Anthropic provider;
// OpenAI and Ollama both go through the OpenAI provider's Chat Completions
// client (Ollama exposes an OpenAI-compatible `/v1` API). DeepSeek's chat
// models have no image input, so vision resolves through its own provider and
// model (see env.ts).
// Runs on Edge and Node.js.

import { createAnthropic, type AnthropicLanguageModelOptions } from "@ai-sdk/anthropic";
import { createDeepSeek, type DeepSeekLanguageModelOptions } from "@ai-sdk/deepseek";
import { createOpenAI } from "@ai-sdk/openai";
import type { LanguageModel, streamText } from "ai";
import { getEnv } from "../env";
import type { LlmProvider } from "../types";

export interface ResolvedModel {
  model: LanguageModel;
  provider: Exclude<LlmProvider, "none">;
  modelId: string;
  /** Per-provider request options, passed through to streamText / generateText. */
  providerOptions?: ModelProviderOptions;
}

export type ModelProviderOptions = NonNullable<Parameters<typeof streamText>[0]["providerOptions"]>;

/** `http://host:11434/`, `http://host:11434/v1` → `http://host:11434/v1`. */
export function ollamaApiBase(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  let end = trimmed.length;
  while (end > 0 && trimmed[end - 1] === "/") end--; // linear, unlike /\/+$/ on long input
  return `${trimmed.slice(0, end).replace(/\/v1$/i, "")}/v1`;
}

/** The configured model for plain text or image analysis, or null when no LLM is configured. */
export function getLanguageModel(kind: "text" | "vision"): ResolvedModel | null {
  const { llm } = getEnv();
  const provider = kind === "vision" ? llm.visionProvider : llm.provider;
  const modelId = kind === "vision" ? llm.visionModel : llm.model;

  if (provider === "deepseek" && llm.deepseekApiKey) {
    // Always pass a base URL, for the same reason as OpenAI below (DEEPSEEK_BASE_URL may be blank).
    const deepseek = createDeepSeek({ apiKey: llm.deepseekApiKey, baseURL: llm.deepseekBaseUrl ?? "https://api.deepseek.com" });
    return {
      model: deepseek(modelId),
      provider: "deepseek",
      modelId,
      // V4 models think before answering by default. Jeannie speaks her replies,
      // so she answers straight away.
      providerOptions: { deepseek: { thinking: { type: "disabled" } } satisfies DeepSeekLanguageModelOptions },
    };
  }

  if (provider === "anthropic" && llm.anthropicApiKey) {
    const anthropic = createAnthropic({ apiKey: llm.anthropicApiKey });
    return {
      model: anthropic(modelId),
      provider: "anthropic",
      modelId,
      // When a safety classifier declines a request, the API re-runs it on a
      // fallback model inside the same call instead of returning an empty turn.
      providerOptions: { anthropic: { fallbacks: "default" } satisfies AnthropicLanguageModelOptions },
    };
  }

  if (provider === "openai" && llm.openaiApiKey) {
    // Always pass a base URL: left undefined, the SDK reads OPENAI_BASE_URL raw, and the
    // blank value shipped in .env.example would then break every request.
    const openai = createOpenAI({ apiKey: llm.openaiApiKey, baseURL: llm.openaiBaseUrl ?? "https://api.openai.com/v1" });
    return { model: openai.chat(modelId), provider: "openai", modelId };
  }

  if (provider === "ollama") {
    // Ollama ignores the key, but the OpenAI client refuses to run without one.
    const ollama = createOpenAI({ baseURL: ollamaApiBase(llm.ollamaBaseUrl), apiKey: "ollama", name: "ollama" });
    return { model: ollama.chat(modelId), provider: "ollama", modelId };
  }

  return null;
}

/** DeepSeek's reasoning model has no tool calling. */
export function supportsTools(resolved: Pick<ResolvedModel, "provider" | "modelId">): boolean {
  if (resolved.provider === "ollama") return false; // many Ollama models ignore or garble tools
  return !(resolved.provider === "deepseek" && /reasoner/i.test(resolved.modelId));
}
