// Server-side configuration. Reads process.env lazily on every call so tests can
// stub variables, and so nothing is inlined into client bundles.
// Works on both the Edge and Node.js runtimes.

import type { LlmProvider, SearchProvider, TtsEngine } from "./types";

function read(name: string): string | undefined {
  const value = process.env[name];
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  // Treat the placeholders shipped in .env.example as "not configured".
  if (trimmed === "" || /^your_[a-z0-9_]+$/i.test(trimmed)) return undefined;
  return trimmed;
}

function readBool(name: string, fallback: boolean): boolean {
  const value = read(name);
  if (value === undefined) return fallback;
  return /^(1|true|yes|on)$/i.test(value);
}

/** A loopback Ollama URL can never be reached from a Vercel function. */
function reachableOllamaUrl(): string | undefined {
  const url = read("OLLAMA_BASE_URL");
  if (!url || !process.env.VERCEL) return url;
  try {
    const host = new URL(url).hostname;
    return /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|0\.0\.0\.0)$/i.test(host) ? undefined : url;
  } catch {
    return undefined;
  }
}

/**
 * Provider for image analysis. DeepSeek's chat models can't read images, so a
 * Claude or OpenAI key wins; with only DeepSeek configured, images go to its
 * (experimental) vision model.
 */
function visionProviderFor(
  text: LlmProvider,
  keys: { anthropic?: string; openai?: string; ollama?: string },
): LlmProvider {
  if (text === "anthropic" || text === "openai" || text === "ollama") return text;
  if (keys.anthropic) return "anthropic";
  if (keys.openai) return "openai";
  return text === "deepseek" ? "deepseek" : "none";
}

function modelFor(provider: LlmProvider, models: Record<Exclude<LlmProvider, "none">, string>): string {
  return provider === "none" ? models.openai : models[provider];
}

/**
 * DeepSeek discontinued the deepseek-chat / deepseek-reasoner names on 24 July 2026, so a
 * deployment still configured with one would fail every request: map them to a live model.
 */
function deepseekModel(name: string): string | undefined {
  const value = read(name);
  return value && /^deepseek-(?:chat|reasoner)$/i.test(value) ? "deepseek-v4-flash" : value;
}

/** A valid IANA time zone, else Asia/Dhaka (where Jeannie's operator lives). */
function timeZone(): string {
  const tz = read("JEANNIE_TIMEZONE") ?? DEFAULT_TIMEZONE;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return tz;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

export const DEFAULT_TIMEZONE = "Asia/Dhaka";

/** ElevenLabs premade "Rachel", used when only the API key is set; speaks Korean with the multilingual models. */
export const DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM";

export function getEnv() {
  const deepseekKey = read("DEEPSEEK_API_KEY");
  const anthropicKey = read("ANTHROPIC_API_KEY");
  const openaiKey = read("OPENAI_API_KEY");
  const requestedProvider = (read("LLM_PROVIDER") ?? "auto").toLowerCase();
  const ollamaBaseUrl = reachableOllamaUrl();

  let llmProvider: LlmProvider = "none";
  if (requestedProvider === "deepseek") llmProvider = deepseekKey ? "deepseek" : "none";
  else if (requestedProvider === "anthropic") llmProvider = anthropicKey ? "anthropic" : "none";
  else if (requestedProvider === "openai") llmProvider = openaiKey ? "openai" : "none";
  else if (requestedProvider === "ollama") llmProvider = ollamaBaseUrl ? "ollama" : "none";
  else
    llmProvider = deepseekKey
      ? "deepseek"
      : anthropicKey
        ? "anthropic"
        : openaiKey
          ? "openai"
          : ollamaBaseUrl
            ? "ollama"
            : "none";

  const anthropicModel = read("ANTHROPIC_MODEL") ?? "claude-opus-5";
  const defaultModel = read("DEFAULT_MODEL") ?? "gpt-4o";
  const ollamaModel = read("OLLAMA_MODEL") ?? "llama3.1";
  const textModels = {
    deepseek: deepseekModel("DEEPSEEK_MODEL") ?? "deepseek-v4-flash",
    anthropic: anthropicModel,
    openai: defaultModel,
    ollama: ollamaModel,
  };
  const visionModels = {
    deepseek: deepseekModel("DEEPSEEK_VISION_MODEL") ?? "deepseek-v4-flash-vision-exp",
    anthropic: read("ANTHROPIC_VISION_MODEL") ?? anthropicModel,
    openai: read("VISION_MODEL") ?? defaultModel,
    ollama: read("OLLAMA_VISION_MODEL") ?? "llava",
  };
  const visionProvider = visionProviderFor(llmProvider, { anthropic: anthropicKey, openai: openaiKey });

  // The project URL is public, so the Next.js-style NEXT_PUBLIC_ name works too. The key
  // must be the server-only secret (sb_secret_… or legacy service_role): the memory
  // tables refuse the publishable/anon key by design.
  const supabaseUrl = read("SUPABASE_URL") ?? read("NEXT_PUBLIC_SUPABASE_URL");
  const supabaseServiceKey = read("SUPABASE_SERVICE_ROLE_KEY") ?? read("SUPABASE_SECRET_KEY");
  const supabaseBase = supabaseUrl?.replace(/\/+$/, "");

  return {
    appName: read("NEXT_PUBLIC_APP_NAME") ?? "Jeannie AI",
    voiceName: read("NEXT_PUBLIC_VOICE_NAME") ?? "Jeannie",
    accessKey: read("JEANNIE_ACCESS_KEY"),
    cronSecret: read("CRON_SECRET"),
    timeZone: timeZone(),
    /** MOCK_MODE: the session greeting uses its template instead of the model. */
    mockMode: readBool("MOCK_MODE", false),

    llm: {
      provider: llmProvider,
      deepseekApiKey: deepseekKey,
      deepseekBaseUrl: read("DEEPSEEK_BASE_URL"),
      anthropicApiKey: anthropicKey,
      openaiApiKey: openaiKey,
      openaiBaseUrl: read("OPENAI_BASE_URL"),
      ollamaBaseUrl: ollamaBaseUrl ?? "http://localhost:11434",
      model: modelFor(llmProvider, textModels),
      visionProvider,
      visionModel: modelFor(visionProvider, visionModels),
    },

    memory: {
      supabaseUrl: supabaseBase,
      serviceKey: supabaseServiceKey,
      enabled: Boolean(supabaseUrl && supabaseServiceKey),
    },

    // The Hangeul context (what Hangeul BOT publishes) lives in the same Supabase project as
    // memory and uses the same server-only key; Jeannie never talks to the portal itself.
    hangeul: {
      enabled: Boolean(supabaseUrl && supabaseServiceKey),
      /** The hg-embed Edge Function: question embeddings before a device has its own model. */
      embedUrl: supabaseBase ? `${supabaseBase}/functions/v1/hg-embed` : undefined,
    },

    search: {
      // DeepSeek's native web_search server tool (Anthropic-compatible Messages API): no extra key.
      deepseekApiKey: deepseekKey,
      deepseekAnthropicBaseUrl: (read("DEEPSEEK_ANTHROPIC_BASE_URL") ?? "https://api.deepseek.com/anthropic").replace(/\/+$/, ""),
      deepseekSearchModel: deepseekModel("DEEPSEEK_SEARCH_MODEL") ?? "deepseek-v4-flash",
      tavilyApiKey: read("TAVILY_API_KEY"),
      googleApiKey: read("GOOGLE_CSE_API_KEY"),
      googleCseId: read("GOOGLE_CSE_ID"),
    },

    tts: {
      elevenLabsApiKey: read("ELEVENLABS_API_KEY"),
      elevenLabsVoiceId: read("ELEVENLABS_VOICE_ID") ?? DEFAULT_ELEVENLABS_VOICE_ID,
      elevenLabsModelId: read("ELEVENLABS_MODEL_ID") ?? "eleven_multilingual_v2",
      edgeVoiceEn: read("EDGE_TTS_VOICE_EN") ?? "en-US-JennyNeural",
      edgeVoiceKo: read("EDGE_TTS_VOICE_KO") ?? "ko-KR-SunHiNeural",
      edgeEnabled: readBool("EDGE_TTS_ENABLED", true),
    },

    telegram: {
      botToken: read("TELEGRAM_BOT_TOKEN"),
      adminChatId: read("TELEGRAM_ADMIN_CHAT_ID"),
      webhookSecret: read("TELEGRAM_WEBHOOK_SECRET"),
    },
  };
}

export type JeannieEnv = ReturnType<typeof getEnv>;

export function configuredSearchProviders(env: JeannieEnv = getEnv()): SearchProvider[] {
  const providers: SearchProvider[] = [];
  if (env.search.deepseekApiKey) providers.push("deepseek");
  if (env.search.tavilyApiKey) providers.push("tavily");
  if (env.search.googleApiKey && env.search.googleCseId) providers.push("google");
  providers.push("duckduckgo"); // keyless fallback, always available
  return providers;
}

export function configuredTtsEngines(env: JeannieEnv = getEnv()): TtsEngine[] {
  const engines: TtsEngine[] = [];
  if (env.tts.elevenLabsApiKey && env.tts.elevenLabsVoiceId) engines.push("elevenlabs");
  if (env.tts.edgeEnabled) engines.push("edge");
  engines.push("browser"); // client-side speechSynthesis, always available
  return engines;
}
