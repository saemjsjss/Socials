"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutDashboard, Mic, MicOff } from "lucide-react";
import { AvatarStage } from "@/components/AvatarStage";
import { EmotePicker } from "@/components/EmotePicker";
import type { AvatarDirector } from "@/hooks/useAvatarDirector";
import { useHoldToTalk } from "@/hooks/useHoldToTalk";
import type { SpeechRecognitionState } from "@/hooks/useSpeechRecognition";
import { OFFLINE_LINE } from "@/lib/client/reachability";
import { cn } from "@/lib/utils";

// The phone screen: Jeannie full height, her words as subtitles over the lower
// third, and two floating buttons (switch to the HUD, hold to talk).

// A finished line stays readable this long after she stops talking, then fades.
const SUBTITLE_LINGER_MS = 7000;

interface AvatarScreenProps {
  director: AvatarDirector;
  /** Her latest reply / greeting / check-in, emote tag already removed. */
  subtitle: string;
  /** Still streaming or being spoken: keep the subtitle up. */
  subtitleLive: boolean;
  recognition: SpeechRecognitionState;
  onSwitchToHud: () => void;
  /** Her voice's output level (0..1) and whether it is measured from the real audio. */
  voiceLevel: () => number;
  voiceMeasured: boolean;
  /** No connection (spec D10): hold-to-talk is disabled (the page shows the offline banner). */
  offline?: boolean;
}

/** QA "voice test": 1.2 s of voice, 0.8 s of silence, four times over. */
const VOICE_TEST_PATTERN_MS = { on: 1200, off: 800, cycles: 4 };
const TALKING_CUE = { emote: "talking", key: "talking", loop: true, focus: false } as const;

export function AvatarScreen({
  director,
  subtitle,
  subtitleLive,
  recognition,
  onSwitchToHud,
  voiceLevel,
  voiceMeasured,
  offline = false,
}: AvatarScreenProps) {
  const hold = useHoldToTalk(recognition);
  const [lingering, setLingering] = useState(true);

  // Preview-only QA: plays talking against a scripted voice level so the mouth rests can be
  // checked on a phone without waiting for a real spoken reply.
  const [voiceTest, setVoiceTest] = useState(false);
  const voiceTestStart = useRef(0);
  const startVoiceTest = useCallback(() => {
    voiceTestStart.current = performance.now();
    setVoiceTest(true);
  }, []);
  useEffect(() => {
    if (!voiceTest) return;
    const { on, off, cycles } = VOICE_TEST_PATTERN_MS;
    const timer = setTimeout(() => setVoiceTest(false), (on + off) * cycles);
    return () => clearTimeout(timer);
  }, [voiceTest]);
  const testLevel = useCallback(() => {
    const { on, off } = VOICE_TEST_PATTERN_MS;
    return (performance.now() - voiceTestStart.current) % (on + off) < on ? 0.5 : 0;
  }, []);

  useEffect(() => {
    setLingering(true);
    if (subtitleLive) return;
    const timer = setTimeout(() => setLingering(false), SUBTITLE_LINGER_MS);
    return () => clearTimeout(timer);
  }, [subtitle, subtitleLive]);

  const showSubtitle = subtitle.trim().length > 0 && (subtitleLive || lingering);
  const heard = recognition.listening ? recognition.interim : "";

  return (
    <div className="avatar-screen fixed inset-0 z-20 overflow-hidden">
      <AvatarStage
        className="absolute inset-0"
        cue={voiceTest ? TALKING_CUE : director.cue}
        clips={director.clips}
        onEnded={director.ended}
        voiceLevel={voiceTest ? testLevel : voiceLevel}
        voiceMeasured={voiceTest || voiceMeasured}
      />
      <EmotePicker director={director} onVoiceTest={startVoiceTest} voiceTestRunning={voiceTest} />

      <div className="pointer-events-none absolute inset-x-0 bottom-[calc(7.5rem+env(safe-area-inset-bottom))] flex flex-col items-center gap-3 px-4">
        {heard ? <p className="avatar-heard">{heard}</p> : null}
        <div className="avatar-subtitle" data-visible={showSubtitle} aria-live="polite">
          <p>{subtitle}</p>
        </div>
        {recognition.error && !recognition.listening ? (
          <p className="avatar-heard" role="status">
            {recognition.error}
          </p>
        ) : null}
      </div>

      <div className="absolute inset-x-0 bottom-0 flex items-end justify-between px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <button
          type="button"
          className="avatar-fab avatar-fab-sm"
          onClick={onSwitchToHud}
          aria-label="Switch to HUD view"
          title="HUD view"
        >
          <LayoutDashboard className="h-5 w-5" aria-hidden="true" />
        </button>

        <button
          type="button"
          className={cn("avatar-fab avatar-fab-lg touch-hold", recognition.listening && "avatar-fab-live")}
          // A mic already open can still be released.
          disabled={!recognition.supported || (offline && !recognition.listening)}
          aria-pressed={recognition.listening}
          aria-label={
            !recognition.supported
              ? "Voice input is not supported in this browser"
              : recognition.listening
                ? "Listening. Release to send"
                : offline
                  ? OFFLINE_LINE.en
                  : "Hold to talk to Jeannie"
          }
          title={!recognition.supported ? "Voice input unavailable" : offline ? OFFLINE_LINE.en : "Hold to talk"}
          data-hold-to-talk=""
          {...hold}
        >
          {recognition.supported ? (
            <Mic className="h-8 w-8" aria-hidden="true" />
          ) : (
            <MicOff className="h-8 w-8" aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  );
}

interface AvatarReturnButtonProps {
  onClick: () => void;
}

/** Floating button on the phone HUD to go back to the avatar. */
export function AvatarReturnButton({ onClick }: AvatarReturnButtonProps) {
  return (
    <button
      type="button"
      className="avatar-return fixed bottom-[max(1rem,env(safe-area-inset-bottom))] left-4 z-30"
      onClick={onClick}
      aria-label="Switch to avatar view"
      title="Avatar view"
    >
      {/* Her face, from the idle poster, cropped to the head. */}
      <span className="avatar-return-face" aria-hidden="true" />
    </button>
  );
}
