#!/usr/bin/env node
// Copies onnxruntime-web's WASM runtime (the lockfile's copy in node_modules)
// to public/ort/, so the question embedder's worker loads it from Jeannie's own
// origin instead of cdn.jsdelivr.net (src/lib/client/hg-local/ort-runtime.ts).
// Runs before `next dev` and `next build` (npm's predev / prebuild). The
// copies are build output: public/ort/ is git-ignored.

import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const files = JSON.parse(readFileSync(join(root, "src/lib/client/hg-local/ort-files.json"), "utf8"));
// The onnxruntime-web that transformers.js itself imports ("onnxruntime-web/webgpu" lives in its dist/).
const fromTransformers = createRequire(join(dirname(createRequire(join(root, "package.json")).resolve("@huggingface/transformers")), "index.js"));
const dist = dirname(fromTransformers.resolve("onnxruntime-web/webgpu"));
const out = join(root, "public", "ort");

mkdirSync(out, { recursive: true });
let copied = 0;
for (const name of files) {
  const from = join(dist, name);
  if (!existsSync(from)) {
    console.error(`copy-ort: ${name} is missing from onnxruntime-web/dist (was the package updated?).`);
    process.exit(1);
  }
  const to = join(out, name);
  const same = existsSync(to) && statSync(to).size === statSync(from).size && statSync(to).mtimeMs >= statSync(from).mtimeMs;
  if (!same) {
    copyFileSync(from, to);
    copied++;
  }
}
// Nothing else is served from there.
for (const name of readdirSync(out)) {
  if (!files.includes(name)) rmSync(join(out, name), { recursive: true, force: true });
}
const { version } = JSON.parse(readFileSync(join(dist, "..", "package.json"), "utf8"));
console.log(`copy-ort: onnxruntime-web ${version} → public/ort/ (${files.length} files, ${copied} copied)`);
