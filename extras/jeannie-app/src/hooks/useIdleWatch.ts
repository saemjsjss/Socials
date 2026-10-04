"use client";

import { useEffect, useRef } from "react";
import { holdIdle, idleStep, resetIdle, type IdleState } from "@/lib/avatar/idle";

const TICK_MS = 1000;
const INTERACTION_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

interface IdleWatchOptions {
  /** Only watches while true (avatar mode). */
  enabled: boolean;
  /** Speaking, listening or waiting for a reply: not silence. */
  busy: boolean;
  onCheckIn: () => void;
}

/** Fires the one-off check-in after a long silence; any interaction resets it. */
export function useIdleWatch({ enabled, busy, onCheckIn }: IdleWatchOptions): void {
  const stateRef = useRef<IdleState | null>(null);
  const busyRef = useRef(busy);
  const callbacksRef = useRef({ onCheckIn });

  useEffect(() => {
    busyRef.current = busy;
    callbacksRef.current = { onCheckIn };
  });

  useEffect(() => {
    if (!enabled) return;
    stateRef.current = resetIdle(Date.now());
    const onInteraction = () => {
      stateRef.current = resetIdle(Date.now());
    };
    for (const type of INTERACTION_EVENTS)
      window.addEventListener(type, onInteraction, { capture: true, passive: true });

    const timer = setInterval(() => {
      const now = Date.now();
      const current = stateRef.current ?? resetIdle(now);
      // A hidden tab is not someone sitting in silence.
      if (busyRef.current || document.visibilityState === "hidden") {
        stateRef.current = holdIdle(current, now);
        return;
      }
      const { state, action } = idleStep(current, now);
      stateRef.current = state;
      if (action === "check-in") callbacksRef.current.onCheckIn();
    }, TICK_MS);

    return () => {
      clearInterval(timer);
      for (const type of INTERACTION_EVENTS) window.removeEventListener(type, onInteraction, { capture: true });
    };
  }, [enabled]);
}
