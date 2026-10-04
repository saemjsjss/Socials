// The HUD's side of the embedding worker: a promise per request, a timeout on
// each, and the worker started only when first needed (browser only).

import type { EmbedRequest, EmbedResponse } from "./embed-protocol";

/** First load downloads the model (~34 MB) on a phone connection; later loads come from the browser cache. */
export const MODEL_LOAD_TIMEOUT_MS = 180_000;
/** One question once the model is loaded (tens of ms; a slow phone may take a second). */
export const EMBED_TIMEOUT_MS = 8_000;

export interface Embedder {
  /** The model is loaded in the worker. */
  readonly ready: boolean;
  load(): Promise<void>;
  embed(texts: string[], timeoutMs?: number): Promise<Float32Array[]>;
  dispose(): void;
}

interface Pending {
  resolve: (value: Float32Array[] | null) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export function workerSupported(): boolean {
  return typeof window !== "undefined" && typeof Worker !== "undefined";
}

export function createWorkerEmbedder(onProgress?: (progress: number) => void): Embedder {
  let worker: Worker | null = null;
  let ready = false;
  let next = 1;
  let loading: Promise<void> | null = null;
  const pending = new Map<number, Pending>();

  const failAll = (reason: string) => {
    for (const [id, p] of pending) {
      clearTimeout(p.timer);
      p.reject(new Error(reason));
      pending.delete(id);
    }
  };

  const start = (): Worker => {
    if (worker) return worker;
    const w = new Worker(new URL("./embed.worker.ts", import.meta.url), { type: "module" });
    w.onmessage = (event: MessageEvent<EmbedResponse>) => {
      const msg = event.data;
      if (msg.type === "progress") {
        onProgress?.(msg.progress);
        return;
      }
      const p = pending.get(msg.id);
      if (!p) return;
      pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.type === "error") p.reject(new Error(`embedding failed (${msg.reason})`));
      else {
        ready = true;
        p.resolve(msg.type === "result" ? msg.vectors : null);
      }
    };
    w.onerror = () => {
      // The worker itself died (it could not load): start a fresh one next time.
      ready = false;
      failAll("embedding worker failed");
      w.terminate();
      if (worker === w) worker = null;
    };
    worker = w;
    return w;
  };

  const send = (message: { type: "load" } | { type: "embed"; texts: string[] }, timeoutMs: number): Promise<Float32Array[] | null> =>
    new Promise((resolve, reject) => {
      const id = next++;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error("embedding timed out"));
      }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
      const request: EmbedRequest = message.type === "load" ? { type: "load", id } : { type: "embed", id, texts: message.texts };
      start().postMessage(request);
    });

  return {
    get ready() {
      return ready;
    },
    load() {
      if (ready) return Promise.resolve();
      loading ??= send({ type: "load" }, MODEL_LOAD_TIMEOUT_MS)
        .then(() => undefined)
        .finally(() => {
          loading = null;
        });
      return loading;
    },
    async embed(texts, timeoutMs) {
      const out = await send({ type: "embed", texts }, timeoutMs ?? (ready ? EMBED_TIMEOUT_MS : MODEL_LOAD_TIMEOUT_MS));
      if (!out || out.length !== texts.length) throw new Error("embedding returned no vectors");
      return out;
    },
    dispose() {
      failAll("embedding stopped");
      worker?.terminate();
      worker = null;
      ready = false;
    },
  };
}
