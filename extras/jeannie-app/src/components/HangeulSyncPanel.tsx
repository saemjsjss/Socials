"use client";

import { useState } from "react";
import { DatabaseZap, Download, RefreshCw, Trash } from "lucide-react";
import type { HangeulLocal, HgLocalState } from "@/hooks/useHangeulLocal";
import { cn } from "@/lib/utils";
import { HudPanel } from "./HudPanel";

/** What the first sync downloads (the live dump, spec §6), and the search model once. */
export const FIRST_SYNC_SIZE = "about 60 MB";
export const MODEL_SIZE = "about 35 MB";

/**
 * Why the server does not serve the data to this browser, named as the Hangeul
 * Data panel and the status row name it: still asking /api/status, not linked
 * to Supabase, or locked (no access key on the server or in this browser).
 */
export interface SyncBlock {
  kind: "checking" | "not_linked" | "locked";
  text: string;
}

const BLOCK_HEADLINE: Record<SyncBlock["kind"], string> = { checking: "CHECKING…", not_linked: "NOT LINKED", locked: "LOCKED" };

/** The block for the server's status (null while it is unknown), or null when the data is served here. */
export function syncBlock(input: {
  statusLoaded: boolean;
  configured: boolean;
  keyRequired: boolean;
  hasAccessKey: boolean;
}): SyncBlock | null {
  if (!input.statusLoaded) return { kind: "checking", text: "Checking the server…" };
  if (!input.configured) return { kind: "not_linked", text: "Not linked: set SUPABASE_URL and SUPABASE_SECRET_KEY." };
  if (!input.keyRequired) return { kind: "locked", text: "Locked: set JEANNIE_ACCESS_KEY on the server (the data holds student records)." };
  if (!input.hasAccessKey) return { kind: "locked", text: "Locked: access key required." };
  return null;
}

interface HangeulSyncPanelProps {
  local: HangeulLocal;
  /** Why the server does not serve the data to this browser (see syncBlock), or null. */
  blocked: SyncBlock | null;
  /** Records in Supabase (from /api/status with the key), for the first sync's progress. */
  total: number | null;
  onNotice: (text: string) => void;
}

function clock(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return date.toDateString() === new Date().toDateString() ? time : `${date.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${time}`;
}

function searchLine(state: HgLocalState): string {
  switch (state.model) {
    case "ok":
      return "search on this device";
    case "loading":
      return state.modelProgress !== null ? `loading the search model ${state.modelProgress}%` : "checking the search model";
    case "mismatch":
      return "search on the server (model check failed)";
    case "unavailable":
      return "search on the server (model not loaded)";
    default:
      return "search on the server";
  }
}

export function percent(records: number, total: number | null): number | null {
  if (!total || total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((records / total) * 100)));
}

export interface SyncPanelView {
  led: string;
  headline: string;
  detail: string;
  /** First-sync progress, 0-100 (null when unknown or not syncing). */
  pct: number | null;
  canResync: boolean;
  /** Anything is on this device (its real counts), whatever the preference says. */
  canDelete: boolean;
}

/**
 * What the panel shows. "NOT ON THIS DEVICE" rests on the store's real
 * counts, never on the preference alone: with syncing off but records still
 * stored (a delete that failed, or a write that landed from another tab), it
 * says so and Delete stays enabled.
 */
export function syncPanelView(state: HgLocalState, blocked: SyncBlock | null, total: number | null, busy: boolean): SyncPanelView {
  const pct = state.progress ? percent(state.progress.records, total) : null;
  const stored = state.records > 0 || state.chunks > 0;
  let led = "";
  let headline: string;
  let detail: string;
  if (blocked) {
    headline = BLOCK_HEADLINE[blocked.kind];
    detail = blocked.text;
  } else {
    switch (state.phase) {
      case "unsupported":
        headline = "NOT AVAILABLE";
        detail = state.error ?? "This browser cannot keep a device copy; answers come from the server.";
        break;
      case "off":
        if (stored) {
          led = "led-warn";
          headline = `SYNC OFF · ${state.records.toLocaleString("en-US")} STILL HERE`;
          detail = `Syncing is off, but ${state.records.toLocaleString("en-US")} records are still on this device. Delete local copy removes them.`;
        } else {
          headline = "NOT ON THIS DEVICE";
          detail = "Deleted from this device. Answers come from the server.";
        }
        break;
      case "consent":
        led = "led-warn";
        headline = "WAITING FOR A YES";
        detail = `Mobile data: the first sync downloads ${FIRST_SYNC_SIZE}, plus the search model (${MODEL_SIZE}).`;
        break;
      case "syncing":
        led = "led-on";
        headline = `SYNCING${pct !== null ? ` · ${pct}%` : ""}`;
        detail = state.progress
          ? `${state.progress.records.toLocaleString("en-US")}${total ? ` of ${total.toLocaleString("en-US")}` : ""} records · page ${state.progress.pages}`
          : "Starting the first sync…";
        break;
      case "blocked":
      case "error":
        led = "led-warn";
        headline = state.complete ? `ON DEVICE · ${state.records.toLocaleString("en-US")}` : "SYNC FAILED";
        detail = `${state.error ?? "The last sync failed."}${state.complete ? ` Copy from ${clock(state.syncedAt)}.` : ""}`;
        break;
      case "ready":
        led = "led-on";
        headline = `ON DEVICE · ${state.records.toLocaleString("en-US")}`;
        detail = `Synced ${clock(state.syncedAt)} · ${searchLine(state)}${state.error ? ` · ${state.error}` : ""}`;
        break;
      default:
        headline = "NOT SYNCED YET";
        detail = "The first sync starts when the access key is loaded.";
    }
  }
  return {
    led,
    headline,
    detail,
    pct,
    canResync: !blocked && state.phase !== "unsupported" && !busy,
    canDelete: state.phase !== "unsupported" && !busy && (stored || state.complete || state.phase === "syncing"),
  };
}

/**
 * The device copy of the Hangeul data (ticket 7): its state, and the only two
 * ways to change it: "Re-sync everything" and "Delete local copy".
 */
export function HangeulSyncPanel({ local, blocked, total, onNotice }: HangeulSyncPanelProps) {
  const { state } = local;
  const [busy, setBusy] = useState(false);
  const { led, headline, detail, pct, canResync, canDelete } = syncPanelView(state, blocked, total, busy);

  const resync = async () => {
    if (!window.confirm(`Re-sync everything? The copy on this device is deleted and downloaded again (${FIRST_SYNC_SIZE}).`)) return;
    setBusy(true);
    try {
      await local.resync();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete the Hangeul data from this device? It stays in Supabase, and Jeannie answers from the server until you sync again.")) return;
    setBusy(true);
    try {
      await local.deleteCopy();
      onNotice("Hangeul: the copy on this device was deleted. Jeannie answers Hangeul questions from the server.");
    } catch {
      onNotice("Hangeul: the copy on this device could not be deleted. Try again, or clear this site's data in the browser settings.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <HudPanel title="Hangeul Sync" subtitle="기기 사본" icon={<DatabaseZap />} delay={0.42}>
      <div className="space-y-2">
        <div className="min-w-0 space-y-0.5">
          <p className="flex items-center gap-1.5 whitespace-nowrap font-mono text-[0.66rem] tracking-[0.12em] text-petal-soft">
            <span className={cn("led", led)} aria-hidden="true" />
            {headline}
          </p>
          <p className="text-[0.7rem] leading-relaxed text-petal-soft/65">{detail}</p>
          {state.phase === "syncing" && pct !== null ? (
            <div className="h-1 overflow-hidden rounded-full bg-neon/15" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="First sync">
              <span className="block h-full bg-neon transition-[width]" style={{ width: `${pct}%` }} />
            </div>
          ) : null}
        </div>
        {!blocked && state.phase === "consent" ? (
          <button type="button" onClick={local.allowMobileData} className="hud-btn hud-btn-primary w-full px-2.5 font-mono text-[0.64rem] tracking-[0.12em]">
            <Download aria-hidden="true" className="h-3.5 w-3.5" />
            DOWNLOAD NOW
          </button>
        ) : null}
        {!blocked && state.phase === "off" ? (
          <button type="button" onClick={local.enable} className="hud-btn hud-btn-primary w-full px-2.5 font-mono text-[0.64rem] tracking-[0.12em]">
            <Download aria-hidden="true" className="h-3.5 w-3.5" />
            SYNC TO THIS DEVICE
          </button>
        ) : null}
        <div className="grid grid-cols-1 gap-1.5 md:grid-cols-2 lg:grid-cols-1">
          <button
            type="button"
            onClick={() => void resync()}
            disabled={!canResync}
            className="hud-btn min-w-0 justify-start px-2.5 font-mono text-[0.64rem] tracking-[0.08em]"
            title="Delete this device's copy and download it again"
          >
            <RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5 shrink-0", state.phase === "syncing" && "animate-spin")} />
            <span className="truncate">Re-sync everything</span>
          </button>
          <button
            type="button"
            onClick={() => void remove()}
            disabled={!canDelete}
            className="hud-btn min-w-0 justify-start px-2.5 font-mono text-[0.64rem] tracking-[0.08em]"
            title="Remove the Hangeul data from this device"
          >
            <Trash aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">Delete local copy</span>
          </button>
        </div>
      </div>
    </HudPanel>
  );
}
