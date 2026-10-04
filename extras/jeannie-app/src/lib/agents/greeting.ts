// Session greeting written by the model: one or two short Korean sentences for
// the Dhaka time of day, how long the user was away and, for trusted callers,
// one thing recalled from memory. Anything slow or wrong (no model, MOCK_MODE,
// a failed or late call, an odd answer) falls back to the template greeting
// in etiquette.ts, so the page always has a line within the budget.
// Runs on Edge and Node.js.

import { generateText, type LanguageModel } from "ai";
import { stripEmotes } from "../emote";
import { getEnv } from "../env";
import { recallMemory } from "../memory/store";
import type { Honorific, SessionGreeting } from "../types";
import { truncate } from "../utils";
import { greetingHonorific, localClock, sessionGreeting } from "./etiquette";
import { getLanguageModel, type ResolvedModel } from "./llm";
import { CORE_PERSONA } from "./persona";
import { withTimeout } from "./search-agent";

/** Whole budget: memory recall plus the model call. */
export const GREETING_TIMEOUT_MS = 4_000;
const RECALL_TIMEOUT_MS = 1_500;
const MAX_MEMORY_CHARS = 1_200;
const MAX_GREETING_CHARS = 200;
/** Absences shorter than this are not mentioned. */
const AWAY_MENTION_MS = 60 * 60 * 1000;
const MAX_AWAY_MS = 365 * 24 * 60 * 60 * 1000;
const RECALL_QUERY = "the user's current projects, plans, schedule and preferences";

/** Korean time-of-day word for a local hour. */
export function partOfDay(hour: number): string {
  if (hour >= 5 && hour < 12) return "아침";
  if (hour >= 12 && hour < 18) return "오후";
  if (hour >= 18 && hour < 22) return "저녁";
  return "늦은 밤";
}

/** "약 3시간", "2일", "약 5주"; null below an hour or for a missing/invalid value. */
export function describeAway(awayMs: number | null | undefined): string | null {
  if (awayMs == null || !Number.isFinite(awayMs) || awayMs < AWAY_MENTION_MS) return null;
  const hours = Math.min(awayMs, MAX_AWAY_MS) / 3_600_000;
  if (hours < 24) return `약 ${Math.round(hours)}시간`;
  const days = hours / 24;
  if (days < 14) return `${Math.round(days)}일`;
  if (days < 60) return `약 ${Math.round(days / 7)}주`;
  return `약 ${Math.round(days / 30)}개월`;
}

/** The `awayMs` query parameter as a non-negative integer, else null. */
export function parseAwayMs(value: string | null): number | null {
  if (value === null || !/^\d{1,15}$/.test(value.trim())) return null;
  return Number(value.trim());
}

export interface GreetingFacts {
  localTime: string;
  hour: number;
  timeZone: string;
  honorific: Honorific;
  away: string | null;
  memory: string;
}

/** The user message the model writes the greeting from. */
export function greetingPrompt(facts: GreetingFacts): string {
  const lines = [
    `Local time: ${facts.localTime} (${partOfDay(facts.hour)}) in ${facts.timeZone}.`,
    facts.away
      ? `The user has been away for ${facts.away}. Mention it warmly (you missed them), without guilt-tripping.`
      : "The user was here recently; do not mention being away.",
    `Address the user as ${facts.honorific}.`,
  ];
  if (facts.memory) {
    lines.push(
      `Things you remember about the user (you may mention at most one, briefly and naturally, or none if nothing fits):\n${facts.memory}`,
    );
  }
  return lines.join("\n");
}

const GREETING_DIRECTIVE = `Task: write your opening line as the user opens the app.
- Korean only, polite 해요체, one or two short sentences (under 80 characters in total).
- Affectionate, calm and elegant; greet for the time of day.
- Use the given title exactly once.
- Plain text only: no emote tag, no emoji, no markdown, no quotation marks, no English.`;

/** The model's line cleaned up, or null when it is not a usable Korean greeting. */
export function cleanGreeting(raw: string): string | null {
  const text = stripEmotes(raw)
    .replace(/\[[^\]]*\]/g, "")
    .replace(/[*_#`]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^["'“‘「]+|["'”’」]+$/g, "")
    .trim();
  if (!text || text.length > MAX_GREETING_CHARS || !/[가-힣]/.test(text)) return null;
  return text;
}

function honorificIn(text: string, fallback: Honorific): Honorific {
  if (text.includes("자기야")) return "자기야";
  if (text.includes("부장님")) return "부장님";
  return fallback;
}

export interface GreetingOptions {
  timeZone?: string;
  /** Milliseconds since the user was last seen (client localStorage). */
  awayMs?: number | null;
  /** Caller proved a configured secret; only then is memory recalled. */
  trusted: boolean;
  now?: Date;
  signal?: AbortSignal | null;
  /** Test overrides. */
  model?: LanguageModel;
  recall?: (query: string, signal?: AbortSignal | null) => Promise<string>;
  timeoutMs?: number;
  rng?: () => number;
}

function resolveModel(options: GreetingOptions): ResolvedModel | null {
  if (options.model) return { model: options.model, provider: "openai", modelId: "override" };
  return getLanguageModel("text");
}

/** AI greeting within the budget, else the template. Never throws. */
export async function buildSessionGreeting(options: GreetingOptions): Promise<SessionGreeting> {
  const env = getEnv();
  const timeZone = options.timeZone ?? env.timeZone;
  const now = options.now ?? new Date();
  const { hour, time } = localClock(now, timeZone);
  const honorific = greetingHonorific(hour);
  const template: SessionGreeting = {
    ...sessionGreeting({ now, timeZone, honorific, rng: options.rng }),
    source: "template",
  };

  const resolved = env.mockMode && !options.model ? null : resolveModel(options);
  if (!resolved) return template;

  const deadline = withTimeout(options.timeoutMs ?? GREETING_TIMEOUT_MS, options.signal);
  try {
    // Memory holds personal notes: only for callers that proved a secret, as in the orchestrator.
    const recall = options.recall ?? recallMemory;
    const memory = options.trusted
      ? await recall(RECALL_QUERY, withTimeout(RECALL_TIMEOUT_MS, deadline)).catch(() => "")
      : "";
    const claude = resolved.provider === "anthropic";
    const { text } = await generateText({
      model: resolved.model,
      system: `${CORE_PERSONA}\n\n${GREETING_DIRECTIVE}`,
      prompt: greetingPrompt({
        localTime: time,
        hour,
        timeZone,
        honorific,
        away: describeAway(options.awayMs),
        memory: memory ? truncate(memory, MAX_MEMORY_CHARS) : "",
      }),
      // Claude's thinking counts toward the cap, so give it room and ask for low effort.
      maxOutputTokens: claude ? 1_024 : 160,
      providerOptions: claude ? { anthropic: { ...resolved.providerOptions?.anthropic, effort: "low" } } : resolved.providerOptions,
      maxRetries: 0,
      abortSignal: deadline,
    });
    const greeting = deadline.aborted ? null : cleanGreeting(text);
    if (!greeting) return template;
    return { greeting, honorific: honorificIn(greeting, honorific), localTime: time, timeZone, source: "ai" };
  } catch {
    return template;
  }
}
