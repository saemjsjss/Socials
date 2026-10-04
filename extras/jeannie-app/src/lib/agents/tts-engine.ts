// Jeannie's server voice: ElevenLabs (when configured) → Microsoft Edge neural
// voices → TtsUnavailableError (the HUD then falls back to browser speech).
// Node.js runtime only (Edge TTS uses `ws`).

import { getEnv } from "../env";
import { containsHangul, detectLanguage, stripMarkdownForSpeech } from "../utils";
import { EdgeTtsError, removeIncompatibleCharacters, synthesizeEdgeTts } from "./edge-tts";

export type ServerTtsEngine = "elevenlabs" | "edge";

export interface SpeechResult {
  audio: Uint8Array<ArrayBuffer>;
  engine: ServerTtsEngine;
  contentType: "audio/mpeg";
}

export interface EngineFailure {
  engine: ServerTtsEngine;
  /** Short, secret-free reason ("not configured", "HTTP 401", "timeout"...). */
  reason: string;
}

/** Every server engine failed or is unconfigured. Message and failures never contain secrets. */
export class TtsUnavailableError extends Error {
  readonly failures: EngineFailure[];

  constructor(failures: EngineFailure[]) {
    const detail = failures.map((f) => `${f.engine}: ${f.reason}`).join("; ");
    super(`No server voice available (${detail}).`);
    this.name = "TtsUnavailableError";
    this.failures = failures;
  }
}

/**
 * The text has nothing speakable once markdown, code, URLs and control characters
 * are removed, or the voice produced no audio for it.
 */
export class TtsInputError extends Error {
  constructor(message = "Nothing to speak after removing markdown, code and links.") {
    super(message);
    this.name = "TtsInputError";
  }
}

export const ELEVENLABS_TIMEOUT_MS = 20_000;
// Stay inside the route's 30 s maxDuration even when ElevenLabs used its full timeout.
const TOTAL_BUDGET_MS = 27_000;
const EDGE_MAX_MS = 25_000;
const EDGE_MIN_MS = 2_000;

/**
 * Edge voice for English text that contains Hangul. English-only voices such as
 * JennyNeural silently skip every Hangul word (and return no audio for Korean-only
 * text); this one was verified live to speak both. Override with EDGE_TTS_VOICE_MIXED.
 */
export const DEFAULT_EDGE_VOICE_MIXED = "en-US-EmmaMultilingualNeural";

// Edge ends the turn silently for punctuation-only text ("...", "?!", "—", "。"), but reads
// symbols, emoji and the punctuation marks listed here aloud (all checked live).
const SPEAKABLE = /[\p{L}\p{N}\p{S}%&@#*/\\§¶‰_]/u;

export const ELEVENLABS_VOICE_SETTINGS = {
  stability: 0.5,
  similarity_boost: 0.75,
  style: 0.25,
  use_speaker_boost: true,
} as const;

class EngineError extends Error {}

function withTimeout(ms: number, signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

// The request and the body download share one signal, so both fail the same way.
function requestFailure(error: unknown): EngineError {
  const name = error instanceof Error ? error.name : "";
  return new EngineError(name === "TimeoutError" ? "timeout" : name === "AbortError" ? "aborted" : "network error");
}

async function synthesizeElevenLabs(
  text: string,
  config: { apiKey: string; voiceId: string; modelId: string },
  signal?: AbortSignal,
): Promise<Uint8Array<ArrayBuffer>> {
  const url =
    `https://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(config.voiceId)}` +
    "?output_format=mp3_44100_128";
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "xi-api-key": config.apiKey, "Content-Type": "application/json", Accept: "audio/mpeg" },
      body: JSON.stringify({ text, model_id: config.modelId, voice_settings: ELEVENLABS_VOICE_SETTINGS }),
      signal: withTimeout(ELEVENLABS_TIMEOUT_MS, signal),
    });
  } catch (error) {
    throw requestFailure(error);
  }
  if (!res.ok) {
    await res.body?.cancel().catch(() => undefined);
    throw new EngineError(`HTTP ${res.status}`);
  }
  let body: ArrayBuffer;
  try {
    body = await res.arrayBuffer();
  } catch (error) {
    throw requestFailure(error);
  }
  const audio = new Uint8Array(body);
  if (audio.byteLength === 0) throw new EngineError("empty audio");
  return audio;
}

// Same rule as env.ts: blank values and the `your_*` placeholders count as unset.
function configuredMixedVoice(): string | undefined {
  const value = process.env.EDGE_TTS_VOICE_MIXED?.trim();
  return value && !/^your_[a-z0-9_]+$/i.test(value) ? value : undefined;
}

function edgeVoiceFor(
  text: string,
  lang: "en" | "ko",
  voices: { edgeVoiceEn: string; edgeVoiceKo: string },
): string {
  if (lang === "ko") return voices.edgeVoiceKo;
  if (!containsHangul(text)) return voices.edgeVoiceEn;
  // An English voice that is already multilingual keeps one voice across English replies.
  const englishSpeaksKorean = /Multilingual/i.test(voices.edgeVoiceEn);
  return configuredMixedVoice() ?? (englishSpeaksKorean ? voices.edgeVoiceEn : DEFAULT_EDGE_VOICE_MIXED);
}

function reasonOf(error: unknown): string {
  if (error instanceof EngineError) return error.message;
  if (error instanceof EdgeTtsError) return error.status ? `${error.code} (HTTP ${error.status})` : error.code;
  return "unexpected error";
}

/**
 * Speak `text` as Jeannie. Markdown is stripped first; `lang` picks the Edge
 * voice and defaults to the detected language of the text. English text with
 * Hangul in it goes to a voice that speaks both languages.
 * Throws TtsInputError (nothing speakable) or TtsUnavailableError.
 */
export async function synthesizeSpeech(options: {
  text: string;
  lang?: "en" | "ko";
  signal?: AbortSignal;
}): Promise<SpeechResult> {
  const text = removeIncompatibleCharacters(stripMarkdownForSpeech(options.text)).replace(/\s+/g, " ").trim();
  if (!SPEAKABLE.test(text)) throw new TtsInputError();
  const lang = options.lang ?? detectLanguage(text);
  const { tts } = getEnv();
  const deadline = Date.now() + TOTAL_BUDGET_MS;
  const failures: EngineFailure[] = [];

  if (tts.elevenLabsApiKey && tts.elevenLabsVoiceId) {
    try {
      const audio = await synthesizeElevenLabs(
        text,
        { apiKey: tts.elevenLabsApiKey, voiceId: tts.elevenLabsVoiceId, modelId: tts.elevenLabsModelId },
        options.signal,
      );
      return { audio, engine: "elevenlabs", contentType: "audio/mpeg" };
    } catch (error) {
      failures.push({ engine: "elevenlabs", reason: reasonOf(error) });
    }
  } else {
    failures.push({ engine: "elevenlabs", reason: "not configured" });
  }

  if (!tts.edgeEnabled) {
    failures.push({ engine: "edge", reason: "disabled" });
  } else if (options.signal?.aborted) {
    failures.push({ engine: "edge", reason: "aborted" });
  } else {
    try {
      const audio = await synthesizeEdgeTts({
        text,
        voice: edgeVoiceFor(text, lang, tts),
        signal: options.signal,
        timeoutMs: Math.min(EDGE_MAX_MS, Math.max(EDGE_MIN_MS, deadline - Date.now())),
      });
      return { audio, engine: "edge", contentType: "audio/mpeg" };
    } catch (error) {
      // A configured voice that is unknown fails as `socket`/`invalid_input`, so these two
      // mean the text itself has nothing this voice can say: skip it rather than report a
      // server outage (a 503 makes the HUD drop the server voice for a minute).
      if (error instanceof EdgeTtsError && (error.code === "no_audio" || error.code === "empty_text")) {
        throw new TtsInputError("The voice found nothing it can speak in this text.");
      }
      failures.push({ engine: "edge", reason: reasonOf(error) });
    }
  }

  throw new TtsUnavailableError(failures);
}
