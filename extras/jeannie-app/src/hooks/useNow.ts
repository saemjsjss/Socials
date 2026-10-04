"use client";

import { useEffect, useState } from "react";

/**
 * Current time, ticking every `intervalMs`. Returns null during server render
 * and the first client render so clocks never cause hydration mismatches.
 */
export function useNow(intervalMs = 1000): Date | null {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    // Align ticks to the wall-clock second so every clock on screen flips together.
    let interval: ReturnType<typeof setInterval> | undefined;
    const timeout = setTimeout(
      () => {
        setNow(new Date());
        interval = setInterval(() => setNow(new Date()), intervalMs);
      },
      intervalMs - (Date.now() % intervalMs),
    );
    return () => {
      clearTimeout(timeout);
      if (interval) clearInterval(interval);
    };
  }, [intervalMs]);

  return now;
}

const timeFormatters = new Map<string, Intl.DateTimeFormat>();

/** HH:MM:SS in a given IANA time zone (undefined = the viewer's own). */
export function formatClock(date: Date, timeZone?: string): string {
  const key = timeZone ?? "local";
  let formatter = timeFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone,
    });
    timeFormatters.set(key, formatter);
  }
  return formatter.format(date);
}

export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}
