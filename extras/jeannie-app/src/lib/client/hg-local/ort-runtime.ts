// The WASM runtime of the question embedder (spec §6, D12) comes from
// Jeannie's own origin, never from a CDN.
//
// transformers.js runs onnxruntime-web, and by default points it at
// cdn.jsdelivr.net for the runtime's JavaScript factory
// (ort-wasm-simd-threaded*.mjs) and its .wasm, fetched and executed at run
// time with no integrity check, in the worker that receives every Hangeul
// question and, for the model check, stored chunk texts. The same files are in
// node_modules/onnxruntime-web/dist, installed from the lockfile:
// scripts/copy-ort.mjs copies them to public/ort/ before `next dev` and
// `next build`, and the worker points the runtime there. transformers.js
// still picks the variant (asyncify, or the plain build on Safari before 26
// without WebGPU) and caches the files like the model; only the origin changes.
//
// The model itself (weights, not code) still comes from huggingface.co.

import files from "./ort-files.json";

/** Where the runtime is served on Jeannie's origin (public/ort/). */
export const ORT_BASE = "/ort/";

/** The runtime files scripts/copy-ort.mjs copies from onnxruntime-web/dist (both variants transformers.js may pick). */
export const ORT_FILES: readonly string[] = files;

const ASYNCIFY = { mjs: "ort-wasm-simd-threaded.asyncify.mjs", wasm: "ort-wasm-simd-threaded.asyncify.wasm" };
const PLAIN = { mjs: "ort-wasm-simd-threaded.mjs", wasm: "ort-wasm-simd-threaded.wasm" };

function fileName(url: unknown): string {
  if (typeof url !== "string") return "";
  return url.split(/[?#]/)[0].split("/").pop() ?? "";
}

/**
 * The runtime paths transformers.js chose, moved to `base`. The factory and
 * the .wasm always come as one variant (a factory with the other variant's
 * binary does not run); anything unknown is the default asyncify pair.
 */
export function selfHostedWasmPaths(paths: unknown, base: string = ORT_BASE): { mjs: string; wasm: string } {
  const chosen = paths && typeof paths === "object" ? (paths as { mjs?: unknown }).mjs : undefined;
  const variant = fileName(chosen) === PLAIN.mjs ? PLAIN : ASYNCIFY;
  return { mjs: `${base}${variant.mjs}`, wasm: `${base}${variant.wasm}` };
}

/** The part of transformers.js's `env` this touches (`env.backends.onnx` shares ORT's own `wasm` settings object). */
export interface OnnxEnvLike {
  backends: { onnx?: { wasm?: { wasmPaths?: unknown } } };
}

/**
 * Points onnxruntime-web at Jeannie's origin. Call once, after importing
 * transformers.js and before the first pipeline. False when there is no ORT
 * WASM setting to change: the worker then loads no model at all (search stays
 * on the server) rather than fall back to the CDN.
 */
export function selfHostOnnxRuntime(env: OnnxEnvLike, base: string = ORT_BASE): boolean {
  const wasm = env.backends.onnx?.wasm;
  if (!wasm || typeof wasm !== "object") return false;
  wasm.wasmPaths = selfHostedWasmPaths(wasm.wasmPaths, base);
  return true;
}
