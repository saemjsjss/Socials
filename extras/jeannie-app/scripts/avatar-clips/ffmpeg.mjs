// Shared ffmpeg helpers for the avatar clip scripts (dev-time only).
// FFMPEG overrides the binary (default: `ffmpeg` on PATH).

import { spawnSync } from "node:child_process";
import { FPS, HEIGHT, WIDTH } from "./plan.mjs";

export const FFMPEG = process.env.FFMPEG || "ffmpeg";

export function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: opts.quiet ? "pipe" : "inherit", encoding: "utf8", ...opts });
  if (res.status !== 0) {
    if (opts.quiet) process.stderr.write(res.stderr || res.stdout || "");
    throw new Error(`${cmd} ${args.slice(0, 3).join(" ")}... exited with ${res.status}`);
  }
  return res.stdout;
}

export const ffmpeg = (...args) => run(FFMPEG, ["-v", "error", "-y", ...args], { quiet: true });

/** Final web encode: 720x1280 cover, 24 fps, H.264 yuv420p, no audio, faststart. */
export function encode(input, output, { prefilter = "" } = {}) {
  ffmpeg(
    "-i", input, "-an",
    "-vf", `${prefilter}scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=increase,crop=${WIDTH}:${HEIGHT},fps=${FPS},format=yuv420p`,
    "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-profile:v", "high", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", output,
  );
}

export function poster(video, output) {
  ffmpeg("-i", video, "-frames:v", "1", "-q:v", "3", output);
}

/** Decoded frame count (no ffprobe needed). */
export function countFrames(file) {
  const res = spawnSync(FFMPEG, ["-v", "info", "-i", file, "-map", "0:v:0", "-f", "null", "-"], { encoding: "utf8" });
  const matches = [...(res.stderr || "").matchAll(/frame=\s*(\d+)/g)];
  if (res.status !== 0 || matches.length === 0) throw new Error(`could not count frames of ${file}`);
  return Number(matches.at(-1)[1]);
}

/** Mouth region of the 720x1280 frame (every clip is anchored to the same neutral pose). */
const MOUTH = { x: 338, y: 160, w: 44, h: 22 };
/** A pixel darker than this inside the mouth crop is the gap between the lips. */
const LIP_GAP_LUMA = 110;
/** A frame counts as a rest when it has at most this many more gap pixels than the closed mouth. */
const REST_SLACK = 18;

/**
 * Times (s) of the frames where her mouth is closed or barely parted, so a talking clip can be
 * paused there during a silence without freezing on an open mouth. Frame 0 is the neutral,
 * closed mouth and sets the baseline.
 */
export function mouthRestTimes(file) {
  const res = spawnSync(
    FFMPEG,
    ["-v", "error", "-i", file, "-vf", `crop=${MOUTH.w}:${MOUTH.h}:${MOUTH.x}:${MOUTH.y}`, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    { maxBuffer: 1 << 28 },
  );
  if (res.status !== 0) throw new Error(`could not read the mouth region of ${file}`);
  const size = MOUTH.w * MOUTH.h;
  const gaps = [];
  for (let off = 0; off + size <= res.stdout.length; off += size) {
    let dark = 0;
    for (let i = off; i < off + size; i++) if (res.stdout[i] < LIP_GAP_LUMA) dark++;
    gaps.push(dark);
  }
  const limit = gaps[0] + REST_SLACK;
  return gaps.flatMap((dark, i) => (dark <= limit ? [Math.round((i / FPS) * 1000) / 1000] : []));
}
