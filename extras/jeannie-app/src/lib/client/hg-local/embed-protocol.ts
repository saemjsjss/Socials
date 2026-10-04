// Messages between the HUD and the embedding Web Worker (embed.worker.ts).
// Kept apart from the worker so the main bundle never imports transformers.js.

/**
 * The question model (spec D12): gte-small's ONNX export on the Hugging Face
 * Hub, quantized (q8, ~34 MB, cached by the browser once). The bot's stored
 * vectors come from thenlper/gte-small; check.ts compares the two.
 */
export const EMBED_MODEL_ID = "Supabase/gte-small";
export const EMBED_MODEL_DTYPE = "q8";

export type EmbedRequest = { type: "load"; id: number } | { type: "embed"; id: number; texts: string[] };

export type EmbedResponse =
  | { type: "ready"; id: number }
  | { type: "result"; id: number; vectors: Float32Array[] }
  /** `reason` is an error name or a fixed phrase, never text that was embedded. */
  | { type: "error"; id: number; reason: string }
  /** Model download progress, 0-100 per file. */
  | { type: "progress"; file: string; progress: number };
