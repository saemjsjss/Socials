"use client";

import { useCallback, useEffect, useReducer, useState } from "react";
import { CLIP_MANIFEST_URL, DEFAULT_CLIPS, clipNameFor, mergeClipManifest, type ClipTable } from "@/lib/avatar/clips";
import { INITIAL_DIRECTOR, baseStateOf, cueOf, directorReducer, type ClipCue } from "@/lib/avatar/director";
import type { ReplyEmote } from "@/lib/emote";

// Grace on top of a one-shot's duration before we assume its `ended` event is lost
// (stage unmounted, decode error, tab throttled) and hand back to the base state.
// Generous: on a cold load the clip itself may take a few seconds to arrive.
const ENDED_GRACE_MS = 5000;

/** Longest a one-shot can take to hand back: it may first wait out one idle cycle (stage deferral). */
export function oneShotDeadlineMs(clips: ClipTable, emote: Parameters<typeof clipNameFor>[0]): number {
  return (clips[clipNameFor(emote)].duration + clips.idle.duration) * 1000 + ENDED_GRACE_MS;
}

export interface AvatarDirector {
  cue: ClipCue;
  clips: ClipTable;
  /** Reply / greeting / check-in emote: interrupts the loop, waits behind another one-shot. */
  play: (emote: ReplyEmote) => void;
  /** The stage finished the one-shot for `cue.key`. */
  ended: () => void;
}

export function useAvatarDirector({ listening, speaking }: { listening: boolean; speaking: boolean }): AvatarDirector {
  const [state, dispatch] = useReducer(directorReducer, INITIAL_DIRECTOR);
  const [clips, setClips] = useState<ClipTable>(DEFAULT_CLIPS);

  const base = baseStateOf({ listening, speaking });
  useEffect(() => dispatch({ type: "base", base }), [base]);

  // The static table already works; the manifest only refreshes durations / placeholders.
  useEffect(() => {
    const controller = new AbortController();
    fetch(CLIP_MANIFEST_URL, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((manifest: unknown) => setClips((prev) => mergeClipManifest(prev, manifest)))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const { playing, seq } = state;
  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => dispatch({ type: "ended", seq }), oneShotDeadlineMs(clips, playing));
    return () => clearTimeout(timer);
  }, [playing, seq, clips]);

  const play = useCallback((emote: ReplyEmote) => dispatch({ type: "emote", emote }), []);
  const ended = useCallback(() => dispatch({ type: "ended", seq }), [seq]);

  return { cue: cueOf(state), clips, play, ended };
}
