// The question embedder's WASM runtime comes from Jeannie's own origin
// (src/lib/client/hg-local/ort-runtime.ts), copied from the lockfile's
// onnxruntime-web by scripts/copy-ort.mjs, never from cdn.jsdelivr.net.
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ORT_BASE, ORT_FILES, selfHostedWasmPaths, selfHostOnnxRuntime, type OnnxEnvLike } from "@/lib/client/hg-local/ort-runtime";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (path: string) => readFileSync(`${root}/${path}`, "utf8");
const CDN = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.31.0/dist/";

describe("the ORT runtime paths", () => {
  it("move transformers.js's choice to /ort/, one variant for the factory and the binary", () => {
    expect(selfHostedWasmPaths({ mjs: `${CDN}ort-wasm-simd-threaded.asyncify.mjs`, wasm: `${CDN}ort-wasm-simd-threaded.asyncify.wasm` })).toEqual({
      mjs: "/ort/ort-wasm-simd-threaded.asyncify.mjs",
      wasm: "/ort/ort-wasm-simd-threaded.asyncify.wasm",
    });
    // Safari before 26 without WebGPU: transformers.js picks the plain build.
    expect(selfHostedWasmPaths({ mjs: `${CDN}ort-wasm-simd-threaded.mjs`, wasm: `${CDN}ort-wasm-simd-threaded.wasm` })).toEqual({
      mjs: "/ort/ort-wasm-simd-threaded.mjs",
      wasm: "/ort/ort-wasm-simd-threaded.wasm",
    });
  });

  it("never point off the origin, whatever was set before", () => {
    for (const before of [undefined, null, "https://cdn.example/dist/", { mjs: "https://cdn.example/x.mjs" }, { mjs: 42 }]) {
      const paths = selfHostedWasmPaths(before);
      expect(paths).toEqual({ mjs: "/ort/ort-wasm-simd-threaded.asyncify.mjs", wasm: "/ort/ort-wasm-simd-threaded.asyncify.wasm" });
    }
  });

  it("are set on the env the worker imports, or the worker loads no model", () => {
    const env: OnnxEnvLike = { backends: { onnx: { wasm: { wasmPaths: { mjs: `${CDN}ort-wasm-simd-threaded.asyncify.mjs`, wasm: `${CDN}x.wasm` } } } } };
    expect(selfHostOnnxRuntime(env)).toBe(true);
    expect(JSON.stringify(env)).not.toContain("jsdelivr");
    expect((env.backends.onnx?.wasm?.wasmPaths as { mjs: string }).mjs.startsWith(ORT_BASE)).toBe(true);
    expect(selfHostOnnxRuntime({ backends: {} })).toBe(false);
    expect(selfHostOnnxRuntime({ backends: { onnx: {} } })).toBe(false);
  });

  it("name only files the lockfile's onnxruntime-web has, the version transformers.js pins", () => {
    const pinned = JSON.parse(read("node_modules/@huggingface/transformers/package.json")).dependencies["onnxruntime-web"];
    expect(JSON.parse(read("node_modules/onnxruntime-web/package.json")).version).toBe(pinned);
    for (const name of ORT_FILES) expect(existsSync(`${root}/node_modules/onnxruntime-web/dist/${name}`), name).toBe(true);
    const both = [selfHostedWasmPaths({ mjs: "ort-wasm-simd-threaded.mjs" }), selfHostedWasmPaths(undefined)];
    for (const paths of both) {
      expect(ORT_FILES).toContain(paths.mjs.slice(ORT_BASE.length));
      expect(ORT_FILES).toContain(paths.wasm.slice(ORT_BASE.length));
    }
  });

  it("cover the file names transformers.js's web build defaults to", () => {
    const web = read("node_modules/@huggingface/transformers/dist/transformers.web.js");
    expect(web).toContain("ort-wasm-simd-threaded${wasmPathSuffix}.mjs");
    const suffixes = [...web.matchAll(/wasmPathSuffix = "([^"]*)"/g)].map((m) => m[1]);
    expect(suffixes.sort()).toEqual(["", ".asyncify"]);
    for (const suffix of suffixes) {
      expect(ORT_FILES).toContain(`ort-wasm-simd-threaded${suffix}.mjs`);
      expect(ORT_FILES).toContain(`ort-wasm-simd-threaded${suffix}.wasm`);
    }
  });

  it("are applied by the worker before its first pipeline, and copied before dev and build", () => {
    const worker = read("src/lib/client/hg-local/embed.worker.ts");
    const set = worker.indexOf("selfHostOnnxRuntime(env)");
    expect(set).toBeGreaterThan(0);
    expect(set).toBeLessThan(worker.indexOf("pipeline(\"feature-extraction\""));
    const scripts = JSON.parse(read("package.json")).scripts as Record<string, string>;
    expect(scripts.prebuild).toContain("scripts/copy-ort.mjs");
    expect(scripts.predev).toContain("scripts/copy-ort.mjs");
    expect(read(".gitignore")).toContain("/public/ort/");
  });
});
