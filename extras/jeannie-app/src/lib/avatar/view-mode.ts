// Which screen a device gets: the avatar on portrait phones, the HUD elsewhere,
// unless the user picked one on this device.

export type ViewMode = "avatar" | "hud";

export const VIEW_STORAGE_KEY = "jeannie.view";

/** Portrait phones around Galaxy S Ultra width (~412 CSS px). Keep in sync with `.view-pending` in globals.css. */
export const PHONE_QUERY =
  "(orientation: portrait) and (min-width: 360px) and (max-width: 480px) and (pointer: coarse)";

export function isViewMode(value: unknown): value is ViewMode {
  return value === "avatar" || value === "hud";
}

export function resolveView(override: ViewMode | null, isPhone: boolean): ViewMode {
  return override ?? (isPhone ? "avatar" : "hud");
}

// ── Last seen (for the greeting's "how long were you away") ──────────────────

export const LAST_SEEN_KEY = "jeannie.lastSeen";

/** Milliseconds since the stored timestamp, or undefined when missing / corrupt / in the future. */
export function awayMsFrom(raw: string | null, now: number): number | undefined {
  if (raw === null) return undefined;
  const seen = Number(raw);
  if (!Number.isFinite(seen) || seen <= 0 || seen > now) return undefined;
  return now - seen;
}
