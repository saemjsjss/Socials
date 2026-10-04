"use client";

import { useRef, type MouseEvent as ReactMouseEvent, type PointerEvent } from "react";
import type { SpeechRecognitionState } from "@/hooks/useSpeechRecognition";

// Same semantics as the HUD composer's mic: press and hold to talk, release to
// send; a quick tap toggles instead (a tap would otherwise stop before a word).
const HOLD_TO_TALK_MS = 450;

export interface HoldToTalkHandlers {
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
  onPointerLeave: () => void;
  onClick: (event: ReactMouseEvent<HTMLElement>) => void;
  onContextMenu: (event: ReactMouseEvent<HTMLElement>) => void;
}

export function useHoldToTalk(recognition: SpeechRecognitionState): HoldToTalkHandlers {
  const pressRef = useRef<{ startedByPress: boolean; at: number; down: boolean }>({
    startedByPress: false,
    at: 0,
    down: false,
  });

  const release = (force: boolean) => {
    const press = pressRef.current;
    if (!press.down) return;
    press.down = false;
    if (press.startedByPress && (force || performance.now() - press.at > HOLD_TO_TALK_MS)) recognition.stop();
  };

  return {
    onPointerDown: (event) => {
      if (event.button !== 0) return;
      const startedByPress = !recognition.listening;
      if (startedByPress) recognition.start();
      pressRef.current = { startedByPress, at: performance.now(), down: true };
    },
    onPointerUp: () => release(false),
    onPointerCancel: () => release(true),
    // The finger slid off the button: treat it as a release.
    onPointerLeave: () => release(false),
    onClick: (event) => {
      if (event.detail === 0) {
        // Keyboard activation (Enter / Space): plain toggle.
        if (recognition.listening) recognition.stop();
        else recognition.start();
        return;
      }
      // Tap while already listening: stop and send.
      if (!pressRef.current.startedByPress) recognition.stop();
    },
    // Long-press must not open the context menu / text selection.
    onContextMenu: (event) => event.preventDefault(),
  };
}
