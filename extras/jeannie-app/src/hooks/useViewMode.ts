"use client";

import { useCallback, useEffect, useState } from "react";
import { PHONE_QUERY, VIEW_STORAGE_KEY, isViewMode, resolveView, type ViewMode } from "@/lib/avatar/view-mode";

export interface ViewModeState {
  /** null until hydrated: render nothing mode-specific before then. */
  view: ViewMode | null;
  /** The device matches the phone query (drives the default and the HUD's avatar button). */
  isPhone: boolean;
  setView: (view: ViewMode) => void;
}

/** Avatar on portrait phones, HUD elsewhere; a manual choice persists per device in `jeannie.view`. */
export function useViewMode(): ViewModeState {
  const [override, setOverride] = useState<ViewMode | null>(null);
  const [isPhone, setIsPhone] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(VIEW_STORAGE_KEY);
      const parsed: unknown = raw === null ? null : JSON.parse(raw);
      if (isViewMode(parsed)) setOverride(parsed);
    } catch {
      // Storage blocked or corrupt: follow the device.
    }
    const query = window.matchMedia?.(PHONE_QUERY);
    setIsPhone(Boolean(query?.matches));
    setHydrated(true);
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) => setIsPhone(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const setView = useCallback((next: ViewMode) => {
    setOverride(next);
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Not persisted; the in-memory choice still applies.
    }
  }, []);

  return { view: hydrated ? resolveView(override, isPhone) : null, isPhone, setView };
}
