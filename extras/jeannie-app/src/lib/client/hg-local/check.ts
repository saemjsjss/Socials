// The embed-model check (spec §6): on the first sync, embed three stored chunk
// texts on the device and compare with the vectors the bot stored for them.
// The bot embeds with thenlper/gte-small (sentence-transformers, fp32); the
// device runs Supabase/gte-small (its ONNX export, quantized). Close enough
// scores ≥ 0.98; below that the device's vectors would find the wrong records,
// so search falls back to the server (hg-embed + hg_match) instead of silently
// returning wrong hits. Vectors are compared, never the embed_model strings
// (the bot's is "thenlper/gte-small@<revision>").

import { cosine } from "@/lib/hangeul/vectors";
import type { HgLocalStore, LocalChunk, ModelCheckResult } from "./db";

export const MODEL_CHECK_MIN = 0.98;
export const MODEL_CHECK_SAMPLES = 3;
/** Texts short enough to embed quickly on a phone (and well inside gte-small's 512 tokens). */
const MIN_TEXT = 20;
const MAX_TEXT = 1_500;

export interface CheckSample {
  text: string;
  embedding: Float32Array;
}

/**
 * Up to `n` stored chunks from different kinds, with their texts (a chunk with
 * no content has its record's). Deterministic: the first fitting chunk of each
 * kind in storage order.
 */
export async function pickCheckSamples(store: HgLocalStore, chunks: readonly LocalChunk[], n = MODEL_CHECK_SAMPLES): Promise<CheckSample[]> {
  const out: CheckSample[] = [];
  const kinds = new Set<string>();
  for (const chunk of chunks) {
    if (out.length >= n) break;
    if (kinds.has(chunk.kind)) continue;
    let text = chunk.content;
    if (text === undefined) {
      const [record] = await store.getRecords([{ kind: chunk.kind, key: chunk.key }]);
      text = record?.content;
    }
    if (!text || text.length < MIN_TEXT || text.length > MAX_TEXT) continue;
    kinds.add(chunk.kind);
    out.push({ text, embedding: chunk.embedding });
  }
  return out;
}

/** Embeds the samples' texts and compares with their stored vectors. Never throws. */
export async function checkEmbedModel(
  samples: readonly CheckSample[],
  embed: (texts: string[]) => Promise<ArrayLike<number>[]>,
  now: Date = new Date(),
): Promise<ModelCheckResult> {
  const at = now.toISOString();
  if (samples.length === 0) return { status: "unavailable", min: null, scores: [], at };
  let vectors: ArrayLike<number>[];
  try {
    vectors = await embed(samples.map((s) => s.text));
  } catch {
    return { status: "unavailable", min: null, scores: [], at };
  }
  if (vectors.length !== samples.length) return { status: "unavailable", min: null, scores: [], at };
  const scores = samples.map((s, i) => cosine(vectors[i], s.embedding));
  const min = Math.min(...scores);
  const status = min >= MODEL_CHECK_MIN ? "ok" : "mismatch";
  if (status === "mismatch") {
    // Numbers only: no text, no keys.
    console.warn(`[hg-local] embed model check: min cosine ${min.toFixed(4)} < ${MODEL_CHECK_MIN}; search falls back to the server`);
  }
  return { status, min, scores, at };
}
