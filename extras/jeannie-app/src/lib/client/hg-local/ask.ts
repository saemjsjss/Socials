// What the HUD does with a Hangeul question before (or instead of) the server
// (spec §6). The device copy is for speed while online, never for offline
// answers (D10):
//
//   - a structured plan (student card, verified on a day, consultancies done...)
//     renders straight from IndexedDB with the isomorphic answer.ts, when the
//     copy caught up within the last few minutes and holds the bot's runs (the
//     "as of" line). No network round trip, no prose.
//   - a semantic question is embedded on the device (transformers.js worker)
//     and searched over the local vectors; the vector and the top records go to
//     the server as hints, which re-reads those records from current rows.
//   - everything else goes to the server as a plain question: plans that need
//     the change log or the run table (SERVER_ONLY_INTENTS), Korean or Bangla
//     searches (the server's model rewrites them into English first), a copy
//     that is stale or not synced, a failed model check, or an answer that found
//     nothing on the device (absence may only be the copy lagging behind).

import { isMistakeAudit } from "@/lib/agents/audit-flow";
import { checkIoTQuery } from "@/lib/agents/iot-interceptor";
import { isHangeulContextQuery, needsSearchRewrite, planFor, renderAnswer, runPlan } from "@/lib/hangeul/answer";
import { businessDay } from "@/lib/hangeul/days";
import { SERVER_ONLY_INTENTS, type AnswerResult, type Plan } from "@/lib/hangeul/types";
import { encodeVector } from "@/lib/hangeul/vectors";
import type { HangeulDeviceHints, ResolvedLang } from "@/lib/types";
import type { HgLocalMeta, HgLocalStore } from "./db";
import { deviceReaders } from "./readers";
import { hitRecords, searchIndex, type VectorIndex } from "./search";

/** The delta runs every 5 minutes while the HUD is open; a copy older than this answers nothing itself. */
export const FRESH_MS = 6 * 60_000;

export interface DeviceCopy {
  store: HgLocalStore;
  meta: HgLocalMeta;
  /** The vector index over every local chunk (built once, rebuilt after a sync changed chunks). */
  index: () => Promise<VectorIndex | null>;
  /** The question's gte-small vector from the Web Worker; null while the model is not usable. */
  embed: ((text: string) => Promise<ArrayLike<number>>) | null;
}

export interface PrepareInput {
  question: string;
  lang: ResolvedLang;
  now: Date;
  timeZone: string;
  copy: DeviceCopy | null;
}

export type ServerReason =
  | "no_copy"
  | "server_only"
  | "stale"
  | "rewrite"
  | "model_not_ok"
  | "embed_failed"
  | "device_search"
  | "local_unavailable"
  | "nothing_local";

export type Prepared =
  | { mode: "local"; plan: Plan; result: AnswerResult; text: string }
  | { mode: "server"; reason: ServerReason; hints: HangeulDeviceHints | null };

const toServer = (reason: ServerReason, hints: HangeulDeviceHints | null = null): Prepared => ({ mode: "server", reason, hints });

/** Caught up recently, and holding the runs that date an answer. */
export function copyIsFresh(meta: HgLocalMeta, now: Date): boolean {
  if (!meta.complete || !meta.synced_at || !meta.runs?.length) return false;
  const age = now.getTime() - new Date(meta.synced_at).getTime();
  return Number.isFinite(age) && age >= 0 && age <= FRESH_MS;
}

async function deviceSearch(plan: Extract<Plan, { intent: "semantic" }>, copy: DeviceCopy): Promise<Prepared> {
  if (needsSearchRewrite(plan.question)) return toServer("rewrite");
  if (copy.meta.model_check?.status !== "ok" || !copy.embed) return toServer("model_not_ok");
  let vector: ArrayLike<number>;
  let index: VectorIndex | null;
  try {
    [vector, index] = await Promise.all([copy.embed(plan.question), copy.index()]);
  } catch {
    return toServer("embed_failed");
  }
  const embedding = encodeVector(vector);
  if (!index) return toServer("device_search", { embedding });
  let studentUid: number | undefined;
  if (plan.student) {
    const [student] = await deviceReaders(copy.store, []).findStudents(plan.student).catch(() => []);
    // Not on the device (yet): the server resolves the name itself.
    if (!student || student.student_uid === null) return toServer("device_search", { embedding });
    studentUid = student.student_uid;
  }
  const hits = hitRecords(searchIndex(index, vector, { kinds: plan.kinds, from: plan.from, to: plan.to, studentUid }));
  return toServer("device_search", hits.length ? { embedding, hits } : { embedding });
}

/**
 * Whether the server's router would give this text to the Hangeul agent: the
 * same order as routeQuery (smart-home commands and mistake audits first).
 */
export function routesToHangeul(question: string): boolean {
  return checkIoTQuery(question) === null && !isMistakeAudit(question) && isHangeulContextQuery(question);
}

/** Null when the question is not a Hangeul one (the chat handles it as usual). Never throws. */
export async function prepareHangeul(input: PrepareInput): Promise<Prepared | null> {
  const question = input.question.trim();
  if (!question || !routesToHangeul(question)) return null;
  const { copy, now, timeZone } = input;
  if (!copy || !copy.meta.complete) return toServer("no_copy");
  try {
    const plan = planFor(question, { today: businessDay(now, timeZone), now, timeZone });
    if (plan.intent === "semantic") return await deviceSearch(plan, copy);
    if (SERVER_ONLY_INTENTS.has(plan.intent)) return toServer("server_only");
    if (!copyIsFresh(copy.meta, now)) return toServer("stale");
    const result = await runPlan(plan, deviceReaders(copy.store, copy.meta.runs ?? []), { now, timeZone });
    if (result.unavailable) return toServer("local_unavailable");
    if (result.sources.length === 0) return toServer("nothing_local");
    return { mode: "local", plan, result, text: renderAnswer(result, input.lang, { now, timeZone }) };
  } catch {
    return toServer("local_unavailable");
  }
}
