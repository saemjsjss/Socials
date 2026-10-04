#!/usr/bin/env node
// Builds the avatar clips in public/avatar/ from assets/avatar/source/ (dev-time only).
//
//   npm run avatar:clips
//   npm run avatar:clips -- --generated   # use assets/avatar/source/generated/<emote>.mp4 where present
//
// idle is cut before the eye close / hair artifact and dissolved back into its own start
// with HyperFrames, so it loops seamlessly. greeting and air_kiss placeholders crossfade
// through their frame sheets; talking and nod placeholders are short idle segments. Every
// clip other than idle, sadness and concern starts and ends on idle's first frame.
//
// Needs ffmpeg/ffprobe and `npx hyperframes` (Chrome: HYPERFRAMES_BROWSER_PATH, else the
// Playwright headless shell under /opt/pw-browsers when present, else HyperFrames' own).

import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { encode, ffmpeg, poster, run } from "./ffmpeg.mjs";
import { FPS, compositionHtml, manifestEntry, planLoop, planSequence, rgbToHex, toFrames } from "./plan.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = join(ROOT, "assets/avatar/source");
const OUT = join(ROOT, "public/avatar");
const WORK = join(ROOT, "scripts/avatar-clips/.work");
const HYPERFRAMES = `hyperframes@${process.env.HYPERFRAMES_VERSION || "0.8"}`;
const useGenerated = process.argv.includes("--generated");

// Idle loop: cut at frame 120 (5.0 s; eyes open again after the blink at ~4.1 s, before the
// hair artifact from ~5.3 s and the eye close at ~5.5 s) and dissolve the last 12 frames
// into a still of frame 0, the neutral pose sadness and concern also start and end on.
const IDLE_CUT = 120;
const IDLE_FADE = 12;
const FADE = toFrames(0.25);
const SEAM_TARGET = 0.97;

// Frame sheets: 5 cells of 300x533. Cell 1 is the neutral pose, so the sequences use 2-5.
const SHEET_CELL = { width: 300, height: 533, count: 5 };
const SHEETS = {
  greeting: { sheet: "greeting-sheet.webp", holds: { 2: 0.3, 3: 0.9, 4: 0.3, 5: 0.2 } },
  air_kiss: { sheet: "air-kiss-sheet.webp", holds: { 2: 0.5, 3: 0.7, 4: 0.3, 5: 0.2 } },
};
// Idle-segment placeholders: seconds of idle before dissolving back to its first frame.
const SEGMENTS = { talking: 2.5, nod: 1.6 };

function probe(file) {
  const out = execFileSync(
    "ffprobe",
    ["-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_read_frames,pix_fmt,codec_name:format=duration", "-of", "json", file],
    { encoding: "utf8" },
  );
  const json = JSON.parse(out);
  const s = json.streams[0];
  const hasAudio = execFileSync("ffprobe", ["-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", file], { encoding: "utf8" }).trim() !== "";
  return { width: s.width, height: s.height, frames: Number(s.nb_read_frames), pixFmt: s.pix_fmt, codec: s.codec_name, duration: Number(json.format.duration), hasAudio };
}

/** SSIM between frame `ia` of `a` and frame `ib` of `b`. */
function ssim(a, ia, b, ib) {
  const res = spawnSync(
    "ffmpeg",
    ["-v", "error", "-i", a, "-i", b, "-lavfi", `[0:v]select=eq(n\\,${ia})[x];[1:v]select=eq(n\\,${ib})[y];[x][y]ssim=stats_file=-`, "-f", "null", "-"],
    { encoding: "utf8" },
  );
  const m = /All:([0-9.]+)/.exec(res.stdout + res.stderr);
  if (!m) throw new Error(`ssim failed for ${a} vs ${b}`);
  return Number(m[1]);
}

/**
 * Undo the generator's reframing: it scaled the 720x1280 start frame to 768 wide and
 * cropped the height to 1344, so the figure sits ~2% larger and lower than in idle.
 * Scale back to 720x1260 and smear the missing 10px top and bottom rows back in
 * (found by aligning the first generated frame against idle's; mean abs diff 4.8/255).
 */
const GENERATED_UNFRAME = "scale=720:1260:flags=lanczos,pad=720:1280:0:10,fillborders=top=10:bottom=10:mode=smear,";

/** Backdrop colour: mean of the left and right edge strips beside the figure (the part cover-crop hides). */
function sampleBackdrop(png) {
  const raw = execFileSync(
    "ffmpeg",
    ["-v", "error", "-i", png, "-filter_complex", "[0]split[a][b];[a]crop=48:400:0:200[l];[b]crop=48:400:672:200[r];[l][r]hstack", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
  );
  const sum = [0, 0, 0];
  for (let i = 0; i < raw.length; i++) sum[i % 3] += raw[i];
  return rgbToHex(sum.map((c) => c / (raw.length / 3)));
}

function findBrowser() {
  if (process.env.HYPERFRAMES_BROWSER_PATH) return process.env.HYPERFRAMES_BROWSER_PATH;
  const base = "/opt/pw-browsers";
  if (!existsSync(base)) return undefined;
  for (const dir of readdirSync(base).filter((d) => d.startsWith("chromium_headless_shell-")).sort().reverse()) {
    for (const sub of ["chrome-linux", "chrome-headless-shell-linux64"]) {
      const bin = join(base, dir, sub, sub === "chrome-linux" ? "headless_shell" : "chrome-headless-shell");
      if (existsSync(bin)) return bin;
    }
  }
  return undefined;
}

/** Render a planned sequence with HyperFrames into `output` (high quality intermediate). */
function renderHyperframes(name, plan, backdrop, assets, output) {
  const dir = join(WORK, `hf-${name}`);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  for (const [dest, src] of Object.entries(assets)) copyFileSync(src, join(dir, dest));
  writeFileSync(join(dir, "index.html"), compositionHtml({ id: name.replace(/_/g, "-"), plan, backdrop }));
  const browser = findBrowser();
  run("npx", ["--yes", HYPERFRAMES, "render", ".", "-o", output, "--fps", String(FPS), "--quality", "delivery", "--video-frame-format", "png", "--quiet"], {
    cwd: dir,
    quiet: true,
    env: { ...process.env, HYPERFRAMES_SKIP_SKILLS: "1", ...(browser ? { HYPERFRAMES_BROWSER_PATH: browser } : {}) },
  });
}

function main() {
  // Legacy pipeline: it rebuilds idle, talking, concern and sadness from assets/avatar/source.
  // Once the Kling set is ingested (scripts/avatar-clips/ingest-kling.mjs) it must not overwrite it.
  const current = join(OUT, "manifest.json");
  if (existsSync(current) && !process.argv.includes("--force")) {
    const entries = Object.values(JSON.parse(readFileSync(current, "utf8")));
    if (entries.some((entry) => entry?.source === "kling")) {
      console.error("public/avatar holds Kling clips: run `npm run avatar:ingest` instead (or pass --force to rebuild the legacy set).");
      process.exit(1);
    }
  }
  mkdirSync(OUT, { recursive: true });
  mkdirSync(WORK, { recursive: true });
  const manifest = {};
  const report = [];
  const clip = (emote, file, { loop, placeholder }) => {
    const info = probe(file);
    poster(file, join(OUT, `${emote}.jpg`));
    manifest[emote] = manifestEntry(emote, { duration: info.frames / FPS, loop, placeholder });
    return info;
  };

  // 1. idle: provisional backdrop from the raw source, loop rendered with HyperFrames.
  const idleSrc = join(SOURCE, "idle.mp4");
  ffmpeg("-i", idleSrc, "-frames:v", "1", join(WORK, "source-first.png"));
  let backdrop = sampleBackdrop(join(WORK, "source-first.png"));
  console.log(`idle: loop cut at frame ${IDLE_CUT}, ${IDLE_FADE}-frame dissolve (HyperFrames)`);
  const loop = planLoop({ cutFrame: IDLE_CUT, fadeFrames: IDLE_FADE, src: "idle.mp4", still: "first.png" });
  renderHyperframes("idle", loop, backdrop, { "idle.mp4": idleSrc, "first.png": join(WORK, "source-first.png") }, join(WORK, "idle.raw.mp4"));
  const idle = join(OUT, "idle.mp4");
  encode(join(WORK, "idle.raw.mp4"), idle);
  const idleInfo = clip("idle", idle, { loop: true, placeholder: false });
  const seam = ssim(idle, idleInfo.frames - 1, idle, 0);
  report.push(`idle loop seam SSIM (last vs first frame): ${seam.toFixed(4)}`);
  if (seam < SEAM_TARGET) console.warn(`warning: idle seam SSIM ${seam.toFixed(4)} is below ${SEAM_TARGET}`);

  // The shared neutral pose every other clip starts and ends on.
  const neutral = join(WORK, "neutral.png");
  ffmpeg("-i", idle, "-frames:v", "1", neutral);
  backdrop = sampleBackdrop(neutral);
  report.push(`backdrop colour: ${backdrop}`);

  // 2. sadness / concern: already start and end on the neutral pose, just re-encode.
  for (const emote of ["sadness", "concern"]) {
    console.log(`${emote}: re-encode`);
    encode(join(SOURCE, `${emote}.mp4`), join(OUT, `${emote}.mp4`));
    clip(emote, join(OUT, `${emote}.mp4`), { loop: false, placeholder: false });
  }

  // 3. Generated clips (issue 06) replace the placeholders when asked for and present.
  const generated = (emote) => {
    const file = join(SOURCE, "generated", `${emote}.mp4`);
    if (!useGenerated || !existsSync(file)) return false;
    console.log(`${emote}: generated clip`);
    encode(file, join(OUT, `${emote}.mp4`), { prefilter: GENERATED_UNFRAME });
    clip(emote, join(OUT, `${emote}.mp4`), { loop: emote === "talking", placeholder: false });
    return true;
  };

  // 4. Frame-sheet placeholders: idle start -> sheet cells -> idle first frame.
  for (const [emote, { sheet, holds }] of Object.entries(SHEETS)) {
    if (generated(emote)) continue;
    console.log(`${emote}: placeholder from ${sheet} (HyperFrames)`);
    const assets = { "idle.mp4": idle, "neutral.png": neutral };
    const steps = [{ kind: "video", src: "idle.mp4", mediaStart: 0, hold: toFrames(0.4) }];
    for (let cell = 1; cell <= SHEET_CELL.count; cell++) {
      if (!holds[cell]) continue;
      const name = `cell${cell}.png`;
      ffmpeg("-i", join(SOURCE, sheet), "-vf", `crop=${SHEET_CELL.width}:${SHEET_CELL.height}:${(cell - 1) * SHEET_CELL.width}:0`, join(WORK, `${emote}-${name}`));
      assets[name] = join(WORK, `${emote}-${name}`);
      steps.push({ kind: "image", src: name, hold: toFrames(holds[cell]) });
    }
    steps.push({ kind: "image", src: "neutral.png", hold: toFrames(0.35) });
    renderHyperframes(emote, planSequence(steps, FADE), backdrop, assets, join(WORK, `${emote}.raw.mp4`));
    encode(join(WORK, `${emote}.raw.mp4`), join(OUT, `${emote}.mp4`));
    clip(emote, join(OUT, `${emote}.mp4`), { loop: false, placeholder: true });
  }

  // 5. Idle-segment placeholders that dissolve back to the idle first frame.
  for (const [emote, seconds] of Object.entries(SEGMENTS)) {
    if (generated(emote)) continue;
    console.log(`${emote}: placeholder idle segment (HyperFrames)`);
    const steps = [
      { kind: "video", src: "idle.mp4", mediaStart: 0, hold: toFrames(seconds) },
      { kind: "image", src: "neutral.png", hold: 1 },
    ];
    renderHyperframes(emote, planSequence(steps, toFrames(0.4)), backdrop, { "idle.mp4": idle, "neutral.png": neutral }, join(WORK, `${emote}.raw.mp4`));
    encode(join(WORK, `${emote}.raw.mp4`), join(OUT, `${emote}.mp4`));
    clip(emote, join(OUT, `${emote}.mp4`), { loop: emote === "talking", placeholder: true });
  }

  // 6. Manifest in emote order, plus the seam checks for the clips that must meet idle.
  const order = ["idle", "greeting", "air_kiss", "talking", "concern", "sadness", "nod"];
  const sorted = Object.fromEntries(order.filter((e) => manifest[e]).map((e) => [e, manifest[e]]));
  writeFileSync(join(OUT, "manifest.json"), `${JSON.stringify(sorted, null, 2)}\n`);
  for (const emote of order.filter((e) => e !== "idle")) {
    const file = join(OUT, `${emote}.mp4`);
    const info = probe(file);
    report.push(
      `${emote}: ${info.frames} frames, ${(info.frames / FPS).toFixed(2)}s, SSIM vs idle first frame start ${ssim(file, 0, idle, 0).toFixed(4)} end ${ssim(file, info.frames - 1, idle, 0).toFixed(4)}`,
    );
  }
  console.log(`\n${report.join("\n")}\nwrote ${join(OUT, "manifest.json")}`);
}

main();
