#!/usr/bin/env node
// Ingests the accepted Kling clips (assets/avatar/kling/clips.json, verdict "accept") into
// public/avatar/ with the live web encode, and merges them into public/avatar/manifest.json.
// Entries it does not own (the legacy greeting / air_kiss / nod) are kept as they are.
//
//   npm run avatar:ingest                 # FFMPEG=/path/to/ffmpeg if it is not on PATH
//
// Every ingested clip should be re-checked afterwards with scripts/avatar-clips/gate.py.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { countFrames, encode, mouthRestTimes, poster } from "./ffmpeg.mjs";
import { FPS, manifestEntry } from "./plan.mjs";
import { CLIP_VERSION, ingestPlan } from "./kling.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const KLING = join(ROOT, "assets/avatar/kling");
const OUT = join(ROOT, "public/avatar");
const MANIFEST = join(OUT, "manifest.json");

function main() {
  mkdirSync(OUT, { recursive: true });
  const plan = ingestPlan(JSON.parse(readFileSync(join(KLING, "clips.json"), "utf8")));
  const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, "utf8")) : {};
  // Kling entries the plan no longer ships (e.g. listening, now idle plus a zoom) leave the manifest.
  const shipped = new Set(plan.map((p) => p.name));
  for (const [name, entry] of Object.entries(manifest)) {
    if (entry?.source === "kling" && !shipped.has(name)) delete manifest[name];
  }

  for (const { name, file, loop } of plan) {
    const out = join(OUT, `${name}.mp4`);
    console.log(`${name}: ${file}`);
    encode(join(KLING, file), out);
    poster(out, join(OUT, `${name}.jpg`));
    const frames = countFrames(out);
    const entry = manifestEntry(name, { duration: frames / FPS, loop, placeholder: false });
    manifest[name] = {
      ...entry,
      src: `${entry.src}?v=${CLIP_VERSION}`,
      poster: `${entry.poster}?v=${CLIP_VERSION}`,
      // Talking pauses on these frames while her voice is silent (mouth closed or barely parted).
      ...(name === "talking" ? { rests: mouthRestTimes(out) } : {}),
      source: "kling",
    };
  }

  writeFileSync(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`\ningested ${plan.length} clips; wrote ${MANIFEST}`);
}

main();
