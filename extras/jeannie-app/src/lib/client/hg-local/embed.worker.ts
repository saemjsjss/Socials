// The question embedder (spec §6, D12), in a Web Worker so the model never
// blocks the HUD: transformers.js loads Supabase/gte-small (quantized) once,
// the browser caches it (Cache Storage "transformers-cache", which the service
// worker leaves alone), and each question becomes a mean-pooled, L2-normalised
// 384-d vector, the same recipe as the bot's stored vectors. Only question text
// and stored chunk texts (the model check) ever come here, and nothing leaves
// the device: the model runs locally (WASM). The WASM runtime's code comes from
// Jeannie's own origin (/ort/, copied from the lockfile's onnxruntime-web), never
// from a CDN (ort-runtime.ts).

import { env, pipeline } from "@huggingface/transformers";
import { EMBED_MODEL_DTYPE, EMBED_MODEL_ID, type EmbedRequest, type EmbedResponse } from "./embed-protocol";
import { selfHostOnnxRuntime } from "./ort-runtime";

// The model comes from the Hugging Face Hub only (no /models/ path on Jeannie's origin), cached by the browser.
env.allowLocalModels = false;
env.useBrowserCache = true;
// transformers.js defaults the runtime to cdn.jsdelivr.net; without our own copy, no model loads.
const runtimeSelfHosted = selfHostOnnxRuntime(env);

// The DOM lib has no worker scope types: the two members used here.
const scope = self as unknown as {
  addEventListener(type: "message", listener: (event: MessageEvent<EmbedRequest>) => void): void;
  postMessage(message: EmbedResponse, transfer?: Transferable[]): void;
};

type Extractor = (texts: string[], options: { pooling: "mean"; normalize: boolean }) => Promise<{ data: ArrayLike<number>; dims: number[] }>;

let loading: Promise<Extractor> | null = null;

function load(): Promise<Extractor> {
  if (!runtimeSelfHosted) return Promise.reject(new Error("The WASM runtime could not be pointed at this origin."));
  if (!loading) {
    loading = pipeline("feature-extraction", EMBED_MODEL_ID, {
      dtype: EMBED_MODEL_DTYPE,
      device: "wasm",
      progress_callback: (info) => {
        if (info.status === "progress") scope.postMessage({ type: "progress", file: info.file, progress: info.progress });
      },
    }).then((extractor) => extractor as unknown as Extractor);
    // A failed load (offline, blocked) may be retried by the next request.
    loading.catch(() => {
      loading = null;
    });
  }
  return loading;
}

function reasonOf(error: unknown): string {
  return error instanceof Error && error.name ? error.name : "Error";
}

scope.addEventListener("message", (event) => {
  const request = event.data;
  void (async () => {
    try {
      const extractor = await load();
      if (request.type === "load") {
        scope.postMessage({ type: "ready", id: request.id });
        return;
      }
      const output = await extractor(request.texts, { pooling: "mean", normalize: true });
      const width = output.dims[output.dims.length - 1] ?? 0;
      const flat = Float32Array.from(output.data);
      const vectors = request.texts.map((_, i) => flat.slice(i * width, (i + 1) * width));
      scope.postMessage({ type: "result", id: request.id, vectors }, vectors.map((v) => v.buffer));
    } catch (error) {
      scope.postMessage({ type: "error", id: request.id, reason: reasonOf(error) });
    }
  })();
});
