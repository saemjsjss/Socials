"use client";

import { useEffect, useState } from "react";
import { LAST_SEEN_KEY, awayMsFrom } from "@/lib/avatar/view-mode";

function writeLastSeen() {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, String(Date.now()));
  } catch {
    // Storage blocked: the greeting just won't know how long the user was away.
  }
}

/**
 * How long the user was away before this load (for the greeting), read once,
 * then keeps `jeannie.lastSeen` fresh on load, tab switches and page exit.
 * `undefined` until hydrated; `null` once read when nothing usable was stored.
 */
export function useLastSeen(): number | null | undefined {
  const [awayMs, setAwayMs] = useState<number | null | undefined>(undefined);

  useEffect(() => {
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(LAST_SEEN_KEY);
    } catch {
      raw = null;
    }
    setAwayMs(awayMsFrom(raw, Date.now()) ?? null);
    writeLastSeen();
    document.addEventListener("visibilitychange", writeLastSeen);
    window.addEventListener("pagehide", writeLastSeen);
    return () => {
      document.removeEventListener("visibilitychange", writeLastSeen);
      window.removeEventListener("pagehide", writeLastSeen);
    };
  }, []);

  return awayMs;
}
