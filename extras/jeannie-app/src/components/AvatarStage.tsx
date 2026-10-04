"use client";

import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import {
  AVATAR_BACKDROP,
  AVATAR_FLOOR,
  CLIP_NAMES,
  DEFAULT_CLIPS,
  ESSENTIAL_CLIPS,
  clipNameFor,
  type ClipTable,
} from "@/lib/avatar/clips";
import { IDLE_SEQUENCE, shouldDeferCue, type ClipCue } from "@/lib/avatar/director";
import { INITIAL_GATE, atRest, gateStep, nextRest } from "@/lib/avatar/voice-gate";
import { cn } from "@/lib/utils";

// Two stacked muted videos: the next clip starts on the hidden one and fades in
// over the current one (~400 ms), so cuts between clips never flash. The CSS
// transition on .avatar-video matches this.
const FADE_MS = 400;
/** Background clip downloads running at once after the essential clips. */
const WARM_CONCURRENCY = 2;

interface AvatarStageProps {
  cue: ClipCue;
  clips: ClipTable;
  /** The current one-shot clip finished. */
  onEnded: () => void;
  /** Her voice's output level (0..1), read every frame while she talks. */
  voiceLevel?: () => number;
  /** The level is measured from the real audio; otherwise talking just loops as before. */
  voiceMeasured?: boolean;
  className?: string;
}

export function AvatarStage({ cue, clips, onEnded, voiceLevel, voiceMeasured = false, className }: AvatarStageProps) {
  const videoA = useRef<HTMLVideoElement>(null);
  const videoB = useRef<HTMLVideoElement>(null);
  const [front, setFront] = useState<0 | 1>(0);
  const frontRef = useRef<0 | 1>(0);
  const startedRef = useRef(false);
  // The cue key each video element was last loaded for, and the current cue's key:
  // a clip that ends after the cue moved on must not end the new one-shot.
  const loadedKeys = useRef<[string | null, string | null]>([null, null]);
  const cueKeyRef = useRef<string | null>(null);
  // The cue on screen now (it may lag `cue` while a one-shot waits for idle's loop point).
  const shownCueRef = useRef<ClipCue | null>(null);
  const onEndedRef = useRef(onEnded);

  useEffect(() => {
    onEndedRef.current = onEnded;
  });

  const info = clips[clipNameFor(cue.emote)];
  const { emote, key, loop } = cue;

  useEffect(() => {
    const videos = [videoA.current, videoB.current] as const;
    cueKeyRef.current = key;
    const next: ClipCue = { emote, key, loop, focus: false };
    let cancelled = false;
    let pauseTimer: ReturnType<typeof setTimeout> | undefined;
    let release: (() => void) | undefined;

    const begin = () => {
      if (cancelled) return;
      const target: 0 | 1 = startedRef.current ? (frontRef.current === 0 ? 1 : 0) : 0;
      startedRef.current = true;
      const video = videos[target];
      if (!video) return;
      loadedKeys.current[target] = key;
      shownCueRef.current = next;
      // React only sets `muted` as a property after mount; autoplay needs it before play().
      video.muted = true;
      video.loop = loop;
      video.poster = info.poster;
      if (video.getAttribute("src") !== info.src) video.src = info.src;
      else video.currentTime = 0;

      const reveal = () => {
        if (cancelled) return;
        frontRef.current = target;
        setFront(target);
        const other = videos[target === 0 ? 1 : 0];
        // Hold the outgoing clip until it has faded out, then stop decoding it.
        if (other && other !== video) pauseTimer = setTimeout(() => other.pause(), FADE_MS + 60);
      };
      // Muted inline playback is allowed without a gesture; if it is refused anyway
      // (data saver, decode error) show the poster rather than a stale clip.
      video.play().then(reveal, reveal);
    };

    const shown = videos[frontRef.current];
    if (shown && !shown.paused && shouldDeferCue(shownCueRef.current, next)) {
      // Let idle finish its cycle: its last frame is the neutral pose the one-shot starts on.
      shown.loop = false;
      shown.addEventListener("ended", begin, { once: true });
      release = () => {
        shown.removeEventListener("ended", begin);
        // Still waiting (the cue moved on first): idle keeps looping until the next cue decides.
        if (shownCueRef.current?.loop) shown.loop = true;
      };
    } else {
      begin();
    }

    return () => {
      cancelled = true;
      clearTimeout(pauseTimer);
      release?.();
    };
  }, [emote, key, loop, info.src, info.poster]);

  // Mouth rests while her voice pauses: during a silence the talking loop runs on to the next
  // frame where her mouth is closed or barely parted and holds there, then plays on when the
  // voice comes back. Only with a measured level; the synthetic one would gate on noise.
  const rests = clips.talking.rests;
  const talkingShown = emote === "talking";
  useEffect(() => {
    if (!talkingShown || !voiceMeasured || !voiceLevel || !rests?.length) return;
    let raf = 0;
    let gate = INITIAL_GATE;
    let rest: number | null = null;
    let held: HTMLVideoElement | null = null;
    const tick = () => {
      gate = gateStep(gate, voiceLevel(), performance.now());
      const video = (frontRef.current === 0 ? videoA : videoB).current;
      if (video && shownCueRef.current?.key === "talking") {
        if (gate.silent && !video.paused) {
          rest ??= nextRest(rests, video.currentTime);
          if (rest !== null && atRest(video.currentTime, rest)) {
            video.pause();
            video.currentTime = rest;
            held = video;
            rest = null;
          }
        } else if (!gate.silent) {
          rest = null;
          if (held === video && video.paused) void video.play().catch(() => undefined);
          held = null;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Leaving talking mid-rest needs nothing: the next talking cue restarts the clip.
    return () => cancelAnimationFrame(raf);
  }, [talkingShown, voiceMeasured, voiceLevel, rests]);

  // Warm the HTTP / service-worker cache so later clips start instantly: the clips
  // every state needs first, then the idle sequence and the rest a couple at a time so a phone on mobile
  // data is not asked for every file at once. A clip not warmed yet still streams.
  useEffect(() => {
    const controller = new AbortController();
    // Read the whole body: fetch() resolves at the headers, and the limit below only
    // holds if a worker waits for the download itself.
    const warm = (name: (typeof CLIP_NAMES)[number]) =>
      fetch(clips[name].src, { signal: controller.signal })
        .then((res) => res.blob())
        .then(
          () => undefined,
          () => undefined,
        );
    // The idle sequence plays right after the greeting, so its clips come first.
    const sequence: readonly (typeof CLIP_NAMES)[number][] = IDLE_SEQUENCE;
    const rest = [
      ...sequence,
      ...CLIP_NAMES.filter((name) => !ESSENTIAL_CLIPS.includes(name) && !sequence.includes(name)),
    ];
    const worker = async () => {
      for (let name = rest.shift(); name && !controller.signal.aborted; name = rest.shift()) await warm(name);
    };
    void Promise.all(ESSENTIAL_CLIPS.map(warm)).then(() =>
      Promise.all(Array.from({ length: WARM_CONCURRENCY }, worker)),
    );
    return () => controller.abort();
    // Once per mount: the table only changes in durations after the manifest loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Browsers pause background video; resume the visible clip on return.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      const video = frontRef.current === 0 ? videoA.current : videoB.current;
      if (video && video.paused && !video.ended) void video.play().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // A clip that fails to load never leaves her frozen: a one-shot hands back to the
  // base loop, a loop falls back to idle.
  const errorFor = (index: 0 | 1) => (event: SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    if (loadedKeys.current[index] !== cueKeyRef.current) return;
    if (!video.loop) {
      onEndedRef.current();
      return;
    }
    const idle = clips.idle;
    if (video.getAttribute("src") === idle.src) return;
    video.poster = idle.poster;
    video.src = idle.src;
    void video.play().catch(() => undefined);
  };

  const endedFor = (index: 0 | 1) => (event: SyntheticEvent<HTMLVideoElement>) => {
    if (index !== frontRef.current || event.currentTarget.loop) return;
    if (loadedKeys.current[index] === cueKeyRef.current) onEndedRef.current();
  };

  return (
    <div
      className={cn("avatar-stage", className)}
      data-focus={cue.focus}
      style={{
        background: `linear-gradient(to bottom, ${AVATAR_BACKDROP} 0%, ${AVATAR_BACKDROP} 62%, ${AVATAR_FLOOR} 100%)`,
      }}
      aria-hidden="true"
    >
      {([videoA, videoB] as const).map((ref, index) => (
        <video
          key={index}
          ref={ref}
          className="avatar-video"
          data-front={front === index}
          // Every clip starts on the neutral idle pose; the effect sets each clip's own poster.
          poster={index === 0 ? DEFAULT_CLIPS.idle.poster : undefined}
          muted
          playsInline
          preload="auto"
          disablePictureInPicture
          disableRemotePlayback
          onEnded={endedFor(index as 0 | 1)}
          onError={errorFor(index as 0 | 1)}
        />
      ))}
      <div className="avatar-vignette" />
    </div>
  );
}
