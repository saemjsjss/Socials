// One Hangeul answer, end to end, for the chat orchestrator and POST
// /api/hangeul/ask: plan → code-built facts (answer.ts) → at most two
// sentences from the language model around them → the number check. The
// facts and tables are always shown verbatim; the prose is dropped sentence by
// sentence when it holds a number the facts do not. Runs on Edge and Node.js.

import { generateText, type ModelMessage } from "ai";
import { buildSystemPrompt } from "../agents/persona";
import type { ResolvedModel } from "../agents/llm";
import { withTimeout } from "../agents/search-agent";
import { parseEmote, type ReplyEmote } from "../emote";
import type { Honorific, LlmProvider, ResolvedLang } from "../types";
import {
  checkProse,
  cleanSearchRewrite,
  factsForModel,
  planFor,
  renderAnswer,
  runPlan,
  SEARCH_REWRITE_SYSTEM,
} from "./answer";
import { businessDay } from "./days";
import type { AnswerResult, AnswerSource, HangeulReaders, Plan } from "./types";

const PROSE_TIMEOUT_MS = 8_000;
const REWRITE_TIMEOUT_MS = 4_000;

export interface HangeulAnswerInput {
  question: string;
  lang: ResolvedLang;
  readers: HangeulReaders;
  now: Date;
  timeZone: string;
  honorific?: Honorific;
  /** The conversation so far (latest user turn last), for the prose. Defaults to the question alone. */
  messages?: ModelMessage[];
  /** Recalled memory block for the system prompt. */
  memory?: string;
  /** The language model for the prose and the search rewrite; null answers with the facts alone. */
  model?: ResolvedModel | null;
  /** What the PWA computed on the device: the question's vector and/or its own search hits. */
  device?: { embedding?: readonly number[] | null; hits?: readonly AnswerSource[] | null } | null;
  signal?: AbortSignal | null;
}

export interface HangeulAnswer {
  /** The full reply: `[emote:x] prose\n\nfacts…` (just the facts without a model). */
  text: string;
  /** The code-built part alone (facts, tables, notes, as-of line). */
  rendered: string;
  /** The prose after the number check ("" when there is none). */
  prose: string;
  emote: ReplyEmote | null;
  /** Prose sentences the number check dropped. */
  dropped: string[];
  plan: Plan;
  result: AnswerResult;
  /** The provider that wrote the prose, or "none". */
  provider: LlmProvider;
}

function errorSummary(error: unknown): string {
  if (error && typeof error === "object") {
    const e = error as { name?: unknown; statusCode?: unknown };
    const name = typeof e.name === "string" ? e.name : "Error";
    return typeof e.statusCode === "number" ? `${name} (HTTP ${e.statusCode})` : name;
  }
  return "Error";
}

function lowEffort(model: ResolvedModel, tokens: number) {
  const claude = model.provider === "anthropic";
  return {
    // Claude thinks adaptively and thinking counts toward the cap, so give it room and ask for low effort.
    maxOutputTokens: claude ? 1_024 : tokens,
    providerOptions: claude ? { anthropic: { ...model.providerOptions?.anthropic, effort: "low" } } : model.providerOptions,
  };
}

/** Korean/Bangla → English search query, or null (the question is then searched as written). */
function rewriter(model: ResolvedModel, signal?: AbortSignal | null) {
  return async (question: string): Promise<string | null> => {
    try {
      const { text } = await generateText({
        model: model.model,
        system: SEARCH_REWRITE_SYSTEM,
        prompt: question,
        ...lowEffort(model, 80),
        maxRetries: 0,
        abortSignal: withTimeout(REWRITE_TIMEOUT_MS, signal),
      });
      return cleanSearchRewrite(text);
    } catch {
      return null;
    }
  };
}

export async function answerHangeul(input: HangeulAnswerInput): Promise<HangeulAnswer> {
  const { now, timeZone, lang } = input;
  const plan = planFor(input.question, { today: businessDay(now, timeZone), now, timeZone });
  const model = input.model ?? null;
  const result = await runPlan(plan, input.readers, {
    now,
    timeZone,
    embedding: input.device?.embedding ?? null,
    hits: input.device?.hits ?? null,
    rewrite: model ? rewriter(model, input.signal) : undefined,
  });
  const rendered = renderAnswer(result, lang, { now, timeZone });
  const bare: HangeulAnswer = { text: rendered, rendered, prose: "", emote: null, dropped: [], plan, result, provider: "none" };
  if (!model || result.unavailable) return bare;

  let raw: string;
  try {
    const context = `Code-built answer to the user's latest message (JSON; every value is real data from Hangeul BOT's records):\n${JSON.stringify(
      factsForModel(result, { now, timeZone }),
    )}`;
    const { text } = await generateText({
      model: model.model,
      system: buildSystemPrompt({ agent: "hangeul", lang, honorific: input.honorific, memory: input.memory, context }),
      ...(input.messages?.length ? { messages: input.messages } : { prompt: input.question }),
      ...lowEffort(model, 220),
      maxRetries: 0,
      abortSignal: withTimeout(PROSE_TIMEOUT_MS, input.signal),
    });
    raw = text;
  } catch (error) {
    console.error(`[hangeul] ${model.provider} prose failed: ${errorSummary(error)}`);
    return bare;
  }

  const { emote, text: said } = parseEmote(raw, { final: true });
  const checked = checkProse(said.trim(), rendered);
  const tag = emote ? `[emote:${emote}] ` : "";
  const text = checked.text ? `${tag}${checked.text}\n\n${rendered}` : `${tag}${rendered}`;
  return { text, rendered, prose: checked.text, emote, dropped: checked.dropped, plan, result, provider: model.provider };
}
