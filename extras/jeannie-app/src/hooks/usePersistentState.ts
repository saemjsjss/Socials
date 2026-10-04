"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * useState mirrored to localStorage for per-browser conveniences (language
 * mode, voice toggle). The first render always uses `initial` so server and
 * client markup match; the stored value is applied after mount.
 */
export function usePersistentState<T>(
  key: string,
  initial: T,
  isValid: (value: unknown) => value is T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(initial);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return;
      const parsed: unknown = JSON.parse(raw);
      if (isValid(parsed)) setValue(parsed);
    } catch {
      // Storage blocked or corrupt: keep the default.
    }
    // `isValid` is expected to be a stable module-level guard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Not persisted; the in-memory value still applies.
      }
    },
    [key],
  );

  return [value, update];
}
