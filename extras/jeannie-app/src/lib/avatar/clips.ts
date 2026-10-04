// Avatar clip table. Mirrors public/avatar/manifest.json (written by the clip
// pipeline) so the player works before, or without, fetching the manifest.

import { EMOTES, isEmote, type Emote } from "@/lib/emote";

export interface ClipInfo {
  src: string;
  poster: string;
  /** Seconds. */
  duration: number;
  loop: boolean;
  /** Built from frame sheets until the generated clip lands. */
  placeholder: boolean;
  /** Talking only: times (s) where her mouth is closed or barely parted, to rest on during silence. */
  rests?: number[];
}

/** Emotes that have their own clip file ("listening" is the idle loop plus a CSS focus). */
export type ClipName = Exclude<Emote, "listening">;

export type ClipTable = Record<ClipName, ClipInfo>;

export const CLIP_MANIFEST_URL = "/avatar/manifest.json";

/**
 * Carried on every clip URL as `?v=`: a phone whose service worker still holds an older clip set
 * misses its cache and fetches the new files. Must match scripts/avatar-clips/kling.mjs.
 */
export const CLIP_VERSION = "k3";

/** Page backdrop behind the clips, sampled from the clip background (top edge / floor). */
export const AVATAR_BACKDROP = "#dbc7c7";
export const AVATAR_FLOOR = "#f3e3e3";

const clip = (name: ClipName, duration: number, loop: boolean, placeholder: boolean, versioned = true): ClipInfo => ({
  src: `/avatar/${name}.mp4${versioned ? `?v=${CLIP_VERSION}` : ""}`,
  poster: `/avatar/${name}.jpg${versioned ? `?v=${CLIP_VERSION}` : ""}`,
  duration,
  loop,
  placeholder,
});

export const DEFAULT_CLIPS: ClipTable = {
  idle: clip("idle", 6.042, true, false),
  talking: clip("talking", 8.042, true, false),
  sway: clip("sway", 8.042, false, false),
  greeting: clip("greeting", 5.167, false, false, false),
  air_kiss: clip("air_kiss", 5.167, false, false, false),
  nod: clip("nod", 5.167, false, false, false),
  supportive: clip("supportive", 6.042, false, false),
  concern: clip("concern", 6.042, false, false),
  sadness: clip("sadness", 7.042, false, false),
  love: clip("love", 6.042, false, false),
  heartbeat: clip("heartbeat", 6.042, false, false),
  shyness: clip("shyness", 6.042, false, false),
  curiosity: clip("curiosity", 5.042, false, false),
  excitement: clip("excitement", 6.042, false, false),
  playful: clip("playful", 6.042, false, false),
  stress: clip("stress", 6.042, false, false),
  frustration: clip("frustration", 6.042, false, false),
  peek: clip("peek", 6.042, false, false),
  spin: clip("spin", 8.042, false, false),
};

export const CLIP_NAMES = EMOTES.filter((e): e is ClipName => e !== "listening");

/** Fetched first on load: every state the player can enter before a reply arrives. */
export const ESSENTIAL_CLIPS: readonly ClipName[] = ["idle", "greeting", "talking"];

/** The clip file an emote plays: "listening" is idle plus a CSS focus. */
export function clipNameFor(emote: Emote): ClipName {
  return emote === "listening" ? "idle" : emote;
}

function isClipInfo(value: unknown): value is ClipInfo {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.src === "string" &&
    v.src.startsWith("/") &&
    typeof v.poster === "string" &&
    typeof v.duration === "number" &&
    Number.isFinite(v.duration) &&
    v.duration > 0 &&
    typeof v.loop === "boolean"
  );
}

/** Ascending, finite times inside the clip. */
function isRestList(value: unknown, duration: number): value is number[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((t, i) => typeof t === "number" && Number.isFinite(t) && t >= 0 && t <= duration && (i === 0 || t > value[i - 1]))
  );
}

/** Overlays valid manifest entries on `base`; anything malformed keeps the static entry. */
export function mergeClipManifest(base: ClipTable, manifest: unknown): ClipTable {
  if (!manifest || typeof manifest !== "object") return base;
  const next: ClipTable = { ...base };
  for (const [name, entry] of Object.entries(manifest as Record<string, unknown>)) {
    if (!isEmote(name) || name === "listening" || !isClipInfo(entry)) continue;
    const rests = (entry as { rests?: unknown }).rests;
    next[name] = {
      src: entry.src,
      poster: entry.poster,
      duration: entry.duration,
      loop: entry.loop,
      placeholder: Boolean((entry as { placeholder?: unknown }).placeholder),
      ...(isRestList(rests, entry.duration) ? { rests } : {}),
    };
  }
  return next;
}
