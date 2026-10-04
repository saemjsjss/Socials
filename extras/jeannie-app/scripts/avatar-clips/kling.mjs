// Which accepted Kling clips go live, and under which app emote name (pure; unit-tested).

/** clips.json id -> app emote name. Ids not listed here are not shipped. */
export const KLING_NAMES = {
  idle_neutral: "idle",
  speaking: "talking",
  sway: "sway",
  sway_2: "playful",
  peek: "peek",
  spin: "spin",
  curiosity: "curiosity",
  shyness: "shyness",
  excitement: "excitement",
  love: "love",
  stress: "stress",
  sadness: "sadness",
  frustration: "frustration",
  concern: "concern",
  supportive: "supportive",
  heartbeat: "heartbeat",
};

/**
 * Bumped whenever the shipped clips change: clip URLs carry it as `?v=`, so a phone whose
 * service worker still holds the previous set fetches the new files on the first open.
 * Must match CLIP_VERSION in src/lib/avatar/clips.ts (a test checks both).
 */
export const CLIP_VERSION = "k3";

/** Clips the player loops while their state lasts (sway is played one cycle at a time). */
const LOOPS = new Set(["idle", "talking"]);

/**
 * @param {{ clips: { id: string, file: string | null, verdict: string }[] }} clipsJson
 * @returns {{ name: string, file: string, loop: boolean }[]}
 */
export function ingestPlan(clipsJson) {
  return clipsJson.clips
    .filter((c) => c.verdict === "accept" && typeof c.file === "string" && c.id in KLING_NAMES)
    .map((c) => ({ name: KLING_NAMES[c.id], file: c.file, loop: LOOPS.has(KLING_NAMES[c.id]) }));
}
