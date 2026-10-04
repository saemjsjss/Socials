// Mouth rests while her voice pauses: the talking loop plays only while sound is coming out,
// and during a silence it runs on to the next frame where her mouth is closed or barely parted
// (precomputed "rests") and holds there. Pure, so the timing is unit-tested.

/** Level below this counts as silence (0..1, the smoothed output level). */
export const SILENT_LEVEL = 0.04;
/** Level at or above this counts as voice again (hysteresis against flicker). */
export const VOICE_LEVEL = 0.08;
/** Silence must last this long before the mouth rests (gaps inside a word are shorter). */
export const SILENCE_MS = 180;
/** Voice must last this long before the mouth moves again. */
export const RESUME_MS = 60;
/** How close (s) the playhead must be to a rest frame to pause on it: about two frames at 24 fps. */
export const REST_WINDOW_S = 0.09;

export interface GateState {
  silent: boolean;
  /** When the level first crossed towards the other state (ms), or null while it has not. */
  since: number | null;
}

export const INITIAL_GATE: GateState = { silent: false, since: null };

export function gateStep(state: GateState, level: number, now: number): GateState {
  const crossing = state.silent ? level >= VOICE_LEVEL : level < SILENT_LEVEL;
  if (!crossing) return state.since === null ? state : { ...state, since: null };
  const since = state.since ?? now;
  const hold = state.silent ? RESUME_MS : SILENCE_MS;
  return now - since >= hold ? { silent: !state.silent, since: null } : { ...state, since };
}

/** The first rest at or after `t` (wrapping round the loop), or null when there are none. */
export function nextRest(rests: readonly number[], t: number): number | null {
  if (rests.length === 0) return null;
  return rests.find((r) => r >= t - 1e-3) ?? rests[0]!;
}

/** The playhead has reached the rest frame (it may still need to wrap round the loop first). */
export function atRest(t: number, rest: number): boolean {
  return t >= rest - 1e-3 && t < rest + REST_WINDOW_S;
}
