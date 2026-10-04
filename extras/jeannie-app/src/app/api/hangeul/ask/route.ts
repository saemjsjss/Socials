// POST /api/hangeul/ask : a server-side Hangeul answer (spec §5): for a device
// that has not synced yet, for plans that need the server (changes, runs),
// or to have the device's own search hits re-read from current rows and
// phrased. Body: {question, lang?, embedding?, hits?, prose?}. The answer's
// figures are code-built; the model only adds up to two checked sentences.

import { z } from "zod";
import { getLanguageModel } from "@/lib/agents/llm";
import { asOfLine } from "@/lib/hangeul/answer";
import { hangeulGate } from "@/lib/hangeul/http";
import { answerHangeul } from "@/lib/hangeul/respond";
import { createHangeulStore } from "@/lib/hangeul/store";
import { EMBEDDING_DIMENSIONS, readEmbedding } from "@/lib/hangeul/vectors";
import { getEnv } from "@/lib/env";
import { stripEmotes } from "@/lib/emote";
import { errorResponse, jsonResponse, resolveLanguage } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const askSchema = z.object({
  question: z.string().trim().min(1, "question is empty").max(2_000, "question is longer than 2000 characters"),
  lang: z.enum(["auto", "en", "ko", "bilingual"]).optional(),
  embedding: z.union([z.array(z.number().finite()).length(EMBEDDING_DIMENSIONS), z.string().max(4_096)]).optional(),
  hits: z
    .array(z.object({ kind: z.string().min(1).max(40), key: z.string().min(1).max(512) }))
    .max(24, "at most 24 hits")
    .optional(),
  /** false: the code-built answer alone, no language model call. */
  prose: z.boolean().optional(),
});

export async function POST(req: Request): Promise<Response> {
  const denied = hangeulGate(req);
  if (denied) return denied;

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }
  const parsed = askSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
    return errorResponse(400, "invalid_request", `${where}${issue?.message ?? "invalid request body"}`);
  }
  const body = parsed.data;
  const embedding = body.embedding !== undefined ? readEmbedding(body.embedding) : null;
  if (body.embedding !== undefined && embedding === null) {
    return errorResponse(400, "invalid_request", "embedding: expected 384 numbers or their base64 float32 form");
  }

  const now = new Date();
  const timeZone = getEnv().timeZone;
  const lang = resolveLanguage(body.lang, body.question);
  const answer = await answerHangeul({
    question: body.question,
    lang,
    readers: createHangeulStore({ signal: req.signal }),
    now,
    timeZone,
    honorific: "부장님",
    model: body.prose === false ? null : getLanguageModel("text"),
    device: { embedding, hits: body.hits ?? null },
    signal: req.signal,
  });
  const { plan, result } = answer;
  return jsonResponse({
    lang,
    provider: answer.provider,
    emote: answer.emote,
    text: stripEmotes(answer.text),
    prose: answer.prose,
    answer: answer.rendered,
    plan,
    result: {
      headline: result.headline,
      facts: result.facts,
      tables: result.tables,
      notes: result.notes,
      asOf: result.asOf,
      sources: result.sources,
      unavailable: result.unavailable ?? null,
    },
    as_of: asOfLine(result, lang === "ko" ? "ko" : "en", { now, timeZone }),
  });
}
