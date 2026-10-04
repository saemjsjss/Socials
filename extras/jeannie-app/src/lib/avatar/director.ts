// Avatar clip state machine. The base state follows the app (idle, listening
// while the mic is held, talking while speech plays); one-shot emotes play once
// over it and hand back. At most one emote waits behind the one playing.
// While idle she plays the idle sequence back-to-back; the plain idle clip only
// shows before the first clip (the greeting) and under listening.

import type { Emote, OneShotEmote, ReplyEmote } from "@/lib/emote";

export type BaseState = "idle" | "listening" | "talking";

/** What she plays, in order and non-stop, while idle. Every clip starts and ends on the neutral pose. */
export const IDLE_SEQUENCE = ["spin", "playful", "shyness", "heartbeat", "sway"] as const satisfies readonly OneShotEmote[];

export interface DirectorState {
  base: BaseState;
  /** One-shot emote currently playing. */
  playing: OneShotEmote | null;
  /** Next one-shot, played when `playing` ends (queue of one: newer replaces older). */
  queued: OneShotEmote | null;
  /** Bumped every time a one-shot starts, so a repeat of the same emote restarts the clip. */
  seq: number;
  /** `playing` is a step of the idle sequence (dropped as soon as she talks or listens). */
  ambient: boolean;
  /** Index of the next idle-sequence step: the order carries on across interruptions. */
  idleNext: number;
}

export type DirectorEvent =
  | { type: "base"; base: BaseState }
  /** A reply / greeting / check-in emote. */
  | { type: "emote"; emote: ReplyEmote }
  /** The one-shot started as `seq` finished (stale ends are ignored). */
  | { type: "ended"; seq: number };

// Nothing playing yet: the greeting on open must not queue behind the idle sequence.
export const INITIAL_DIRECTOR: DirectorState = { base: "idle", playing: null, queued: null, seq: 0, ambient: false, idleNext: 0 };

export function baseStateOf(flags: { listening: boolean; speaking: boolean }): BaseState {
  return flags.listening ? "listening" : flags.speaking ? "talking" : "idle";
}

const start = (state: DirectorState, emote: OneShotEmote | null): DirectorState =>
  emote
    ? { ...state, playing: emote, queued: null, seq: state.seq + 1, ambient: false }
    : { ...state, playing: null, queued: null, ambient: false };

/** Idle with nothing to play: start the next step of the idle sequence. */
function settle(state: DirectorState): DirectorState {
  if (state.base !== "idle" || state.playing || state.queued) return state;
  const emote = IDLE_SEQUENCE[state.idleNext % IDLE_SEQUENCE.length]!;
  return { ...start(state, emote), ambient: true, idleNext: (state.idleNext + 1) % IDLE_SEQUENCE.length };
}

export function directorReducer(state: DirectorState, event: DirectorEvent): DirectorState {
  switch (event.type) {
    case "base": {
      if (event.base === state.base) return state;
      // Holding the mic cuts any emote: she is listening now.
      if (event.base === "listening") return { ...state, base: "listening", playing: null, queued: null, ambient: false };
      const next = { ...state, base: event.base };
      // She never spins while speaking: the idle sequence gives way to talking (and a waiting reply emote).
      if (state.ambient) return start(next, state.queued);
      // Emotes that arrived while listening play once the mic is released.
      return settle(state.base === "listening" && state.queued ? start(next, state.queued) : next);
    }
    case "emote":
      // Behind an idle-sequence clip too: it hands over on its last (neutral) frame.
      if (state.base === "listening" || state.playing) return { ...state, queued: event.emote };
      return start(state, event.emote);
    case "ended":
      if (!state.playing || event.seq !== state.seq) return state;
      return settle(start(state, state.queued));
  }
}

export interface ClipCue {
  emote: Emote;
  /** Changes whenever the player must (re)start a clip. */
  key: string;
  loop: boolean;
  /** Listening: the idle loop plus the CSS focus treatment. */
  focus: boolean;
}

/** What the stage should show for a state. Listening shares idle's key so the loop is not restarted. */
export function cueOf(state: DirectorState): ClipCue {
  const focus = state.base === "listening";
  if (state.playing) return { emote: state.playing, key: `${state.playing}#${state.seq}`, loop: false, focus };
  const emote: Emote = state.base;
  return { emote, key: state.base === "talking" ? "talking" : "idle", loop: true, focus };
}

/**
 * Every clip meets the neutral pose only at its first and last frame, so a cut into the middle
 * of the idle loop jumps. A one-shot that arrives over idle therefore waits for idle's loop point
 * (at most one idle cycle); everything else (voice, mic, one-shots over talking) cuts at once.
 */
export function shouldDeferCue(shown: ClipCue | null, next: ClipCue): boolean {
  return shown !== null && shown.loop && shown.key === "idle" && !next.loop;
}
