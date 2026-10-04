"use client";

// The device copy of the Hangeul data (ticket 7) in the HUD: opens IndexedDB,
// runs the first sync (asking first on mobile data), then the change log on
// open, on focus and every 5 minutes while the HUD is open; runs the embed-model
// check once; and prepares each Hangeul question (answer on the device, or send
// the device's search hits to the server). The logic lives in pure modules
// under src/lib/client/hg-local/; this hook only schedules it. Every tab of the
// origin shares the one database: the tabs sync one at a time (Web Locks), and
// "Delete local copy" holds in all of them (device.ts).

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, fetchHangeulChanges, fetchHangeulRuns, fetchHangeulSnapshot, isAbortError } from "@/lib/client/api";
import { prepareHangeul, type DeviceCopy, type Prepared } from "@/lib/client/hg-local/ask";
import { checkEmbedModel, pickCheckSamples } from "@/lib/client/hg-local/check";
import {
  EMPTY_META,
  indexedDbAvailable,
  openIndexedDbStore,
  requestPersistentStorage,
  type HgLocalMeta,
  type HgLocalStore,
  type ModelCheckResult,
} from "@/lib/client/hg-local/db";
import {
  DEVICE_PREF_KEY,
  deleteDeviceCopy,
  followRemoteDelete,
  isDevicePreference,
  openDeviceChannel,
  readDevicePreference,
  syncAllowed,
  type DeviceChannel,
  type DevicePreference,
} from "@/lib/client/hg-local/device";
import { createWorkerEmbedder, EMBED_TIMEOUT_MS, workerSupported, type Embedder } from "@/lib/client/hg-local/embedder";
import { buildIndex, type VectorIndex } from "@/lib/client/hg-local/search";
import { firstSyncNeedsConsent, HgSyncError, syncOnce, type ConnectionHint, type HgTransport, type SyncProgress } from "@/lib/client/hg-local/sync";
import type { ResolvedLang } from "@/lib/types";
import { usePersistentState } from "./usePersistentState";

export const SYNC_INTERVAL_MS = 5 * 60_000;
/** A focus right after a sync does not start another. */
const FOCUS_THROTTLE_MS = 30_000;
/** Warm the model and the vector index this long after the first sync of a page load. */
const WARM_DELAY_MS = 2_000;

export type HgLocalPhase =
  | "unsupported" // no IndexedDB (or storage blocked)
  | "off" // "Delete local copy": nothing syncs until the owner asks again
  | "waiting" // not started yet
  | "consent" // the first sync waits for a yes on mobile data
  | "syncing" // the first sync is running
  | "ready" // the copy is complete
  | "blocked" // the server refuses (no key, not configured)
  | "error"; // the last sync failed (a complete copy is still used while fresh)

export type HgModelState = "unchecked" | "loading" | "ok" | "mismatch" | "unavailable";

export interface HgLocalState {
  phase: HgLocalPhase;
  /** The first sync finished. */
  complete: boolean;
  /** First-sync progress (null otherwise). */
  progress: SyncProgress | null;
  records: number;
  chunks: number;
  syncedAt: string | null;
  /** Why syncing failed or is blocked (plain text, no data). */
  error: string | null;
  model: HgModelState;
  /** Model download progress (0-100) while it loads. */
  modelProgress: number | null;
}

export interface HangeulLocal {
  state: HgLocalState;
  /** Yes to the first sync on mobile data (this page load only). */
  allowMobileData: () => void;
  /** "Re-sync everything": delete the copy and download it again (the panel confirms first). */
  resync: () => Promise<void>;
  /**
   * "Delete local copy": the only way to remove the data from a device; nothing
   * syncs, in any tab of this origin, until enable(). Rejects when the copy
   * could not be deleted (it then stays on, with its real counts).
   */
  deleteCopy: () => Promise<void>;
  /** Sync to this device again after a delete. */
  enable: () => void;
  /** A Hangeul question: answer on the device, or the hints for the server; null when it is not one. */
  prepare: (question: string, lang: ResolvedLang) => Promise<Prepared | null>;
}

export interface HangeulLocalOptions {
  /** The server serves the data to this browser: Hangeul configured, access key set and presented. */
  enabled: boolean;
  online: boolean;
  /** A phone: asks before the first sync when the connection type is unknown. */
  phone: boolean;
  timeZone: string;
}

const transport: HgTransport = { snapshot: fetchHangeulSnapshot, changes: fetchHangeulChanges, runs: fetchHangeulRuns };

const SYNC_LOCK = "jeannie-hg-sync";

/**
 * One sync at a time across the tabs of this origin (Web Locks, where the
 * browser has them): a second tab waits, then finds the copy complete and
 * only reads the change log, instead of downloading it a second time.
 */
function oneSyncAtATime(signal: AbortSignal, run: () => Promise<void>): Promise<void> {
  const locks = typeof navigator === "undefined" ? undefined : (navigator as Partial<Pick<Navigator, "locks">>).locks;
  if (!locks || typeof locks.request !== "function") return run();
  return locks.request(SYNC_LOCK, { signal }, () => run()).then(() => undefined);
}

const INITIAL: HgLocalState = {
  phase: "waiting",
  complete: false,
  progress: null,
  records: 0,
  chunks: 0,
  syncedAt: null,
  error: null,
  model: "unchecked",
  modelProgress: null,
};

function connection(): (ConnectionHint & Partial<EventTarget>) | null {
  if (typeof navigator === "undefined") return null;
  return (navigator as Navigator & { connection?: ConnectionHint & Partial<EventTarget> }).connection ?? null;
}

function modelState(check: ModelCheckResult | null): HgModelState {
  return check ? check.status : "unchecked";
}

function failure(error: unknown): { blocked: boolean; text: string } {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) return { blocked: true, text: "Locked: access key required." };
    if (error.status === 403) return { blocked: true, text: "Set JEANNIE_ACCESS_KEY on the server: the data holds student records." };
    if (error.status === 503) return { blocked: true, text: "Hangeul data is not configured on the server." };
    if (error.status === 404) return { blocked: true, text: "This deployment has no device sync yet." };
    return { blocked: false, text: error.message };
  }
  if (error instanceof HgSyncError) return { blocked: false, text: `Sync stopped: ${error.message}.` };
  if (error instanceof DOMException && error.name === "QuotaExceededError") return { blocked: false, text: "Not enough storage on this device for the copy." };
  return { blocked: false, text: "The device copy could not be written." };
}

export function useHangeulLocal({ enabled, online, phone, timeZone }: HangeulLocalOptions): HangeulLocal {
  const [pref, setPref] = usePersistentState<DevicePreference>(DEVICE_PREF_KEY, "auto", isDevicePreference);
  const [state, setState] = useState<HgLocalState>(INITIAL);
  const [storeReady, setStoreReady] = useState(false);
  const patch = useCallback((changes: Partial<HgLocalState>) => setState((prev) => ({ ...prev, ...changes })), []);

  const storeRef = useRef<HgLocalStore | null>(null);
  const metaRef = useRef<HgLocalMeta>(EMPTY_META);
  /** Bumped whenever a sync changed records or chunks: an index built before is stale. */
  const versionRef = useRef(0);
  const indexRef = useRef<{ index: VectorIndex | null; version: number; building: Promise<VectorIndex | null> | null }>({
    index: null,
    version: -1,
    building: null,
  });
  const embedderRef = useRef<Embedder | null>(null);
  const syncRef = useRef<Promise<void> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const consentRef = useRef(false);
  const lastStartRef = useRef(0);
  const checkingRef = useRef(false);
  const warmedRef = useRef(false);
  /** "Delete local copy" is running in this tab: no sync may start meanwhile. */
  const deletingRef = useRef(false);
  const channelRef = useRef<DeviceChannel | null>(null);
  const live = useRef({ enabled, online, phone, pref });
  useEffect(() => {
    live.current = { enabled, online, phone, pref };
  });

  // Open the database once.
  useEffect(() => {
    if (!indexedDbAvailable()) {
      patch({ phase: "unsupported" });
      return;
    }
    let cancelled = false;
    openIndexedDbStore()
      .then(async (store) => {
        const [meta, counts] = await Promise.all([store.meta(), store.counts()]);
        if (cancelled) return;
        storeRef.current = store;
        metaRef.current = meta;
        patch({
          phase: meta.complete ? "ready" : "waiting",
          complete: meta.complete,
          records: counts.records,
          chunks: counts.chunks,
          syncedAt: meta.synced_at,
          model: modelState(meta.model_check),
        });
        setStoreReady(true);
      })
      .catch(() => {
        if (!cancelled) patch({ phase: "unsupported", error: "This browser's storage is not available (private mode?)." });
      });
    return () => {
      cancelled = true;
    };
  }, [patch]);

  const embedder = useCallback((): Embedder | null => {
    if (!workerSupported()) return null;
    embedderRef.current ??= createWorkerEmbedder((progress) => patch({ modelProgress: Math.round(progress) }));
    return embedderRef.current;
  }, [patch]);

  const ensureIndex = useCallback(async (): Promise<VectorIndex | null> => {
    const store = storeRef.current;
    if (!store) return null;
    const slot = indexRef.current;
    if (slot.index && slot.version === versionRef.current) return slot.index;
    if (!slot.building) {
      const version = versionRef.current;
      slot.building = store
        .chunks()
        .then((chunks) => {
          const index = buildIndex(chunks);
          if (indexRef.current === slot) {
            slot.index = index;
            slot.version = version;
          }
          return index;
        })
        .catch(() => null)
        .finally(() => {
          slot.building = null;
        });
    }
    return slot.building;
  }, []);

  const runModelCheck = useCallback(async () => {
    const store = storeRef.current;
    const e = embedder();
    if (!store || !e || checkingRef.current) return;
    checkingRef.current = true;
    patch({ model: "loading", modelProgress: null });
    try {
      const samples = await pickCheckSamples(store, await store.chunks());
      const result = await checkEmbedModel(samples, (texts) => e.embed(texts));
      await store.write({ ops: [], meta: { model_check: result } });
      metaRef.current = { ...metaRef.current, model_check: result };
      patch({ model: result.status, modelProgress: null });
    } catch {
      patch({ model: "unavailable", modelProgress: null });
    } finally {
      checkingRef.current = false;
    }
  }, [embedder, patch]);

  const warm = useCallback(() => {
    if (warmedRef.current) return;
    warmedRef.current = true;
    setTimeout(() => {
      void ensureIndex();
      void embedder()
        ?.load()
        .catch(() => undefined);
    }, WARM_DELAY_MS);
  }, [embedder, ensureIndex]);

  const stopSync = useCallback(async () => {
    abortRef.current?.abort();
    await syncRef.current?.catch(() => undefined);
  }, []);

  const forget = useCallback(() => {
    metaRef.current = { ...EMPTY_META };
    versionRef.current++;
    indexRef.current = { index: null, version: -1, building: null };
    warmedRef.current = false;
  }, []);

  /**
   * Another tab changed the shared copy (device.ts): "off" stops this tab's
   * sync and clears once more; "auto" (turned on again, or re-synced from
   * scratch there) re-reads the store, so this tab never answers from a copy
   * it believes complete while it is being downloaded again.
   */
  const followRemote = useCallback(
    async (next: DevicePreference) => {
      live.current = { ...live.current, pref: next };
      setPref(next);
      const store = storeRef.current;
      if (!store) return;
      try {
        if (next === "off") {
          embedderRef.current?.dispose();
          embedderRef.current = null;
          const counts = await followRemoteDelete(store, stopSync);
          forget();
          patch({ ...INITIAL, phase: "off", records: counts.records, chunks: counts.chunks });
          return;
        }
        await stopSync();
        const [meta, counts] = await Promise.all([store.meta(), store.counts()]);
        forget();
        metaRef.current = meta;
        patch({
          phase: meta.complete ? "ready" : "waiting",
          complete: meta.complete,
          progress: null,
          records: counts.records,
          chunks: counts.chunks,
          syncedAt: meta.synced_at,
          error: null,
          model: modelState(meta.model_check),
        });
      } catch {
        // The store could not be read or cleared here: the next sync or reload reads it again.
      }
    },
    [forget, patch, setPref, stopSync],
  );

  const sync = useCallback((): Promise<void> => {
    if (syncRef.current) return syncRef.current;
    const store = storeRef.current;
    const l = live.current;
    if (!store || deletingRef.current || !l.enabled || !l.online || l.pref === "off") return Promise.resolve();
    // Deleted in another tab whose message never came: follow it, never download the copy again.
    if (readDevicePreference() === "off") {
      void followRemote("off");
      return Promise.resolve();
    }
    const controller = new AbortController();
    abortRef.current = controller;
    lastStartRef.current = Date.now();
    const allowed = () => !deletingRef.current && syncAllowed(live.current.pref, readDevicePreference());
    const run: Promise<void> = oneSyncAtATime(controller.signal, async () => {
      if (controller.signal.aborted || !allowed()) return;
      const before = await store.meta();
      const mayDownload = consentRef.current || !firstSyncNeedsConsent(connection(), live.current.phone);
      if (!before.complete && !mayDownload) {
        patch({ phase: "consent" });
        return;
      }
      if (!before.complete) {
        patch({ phase: "syncing", progress: { phase: "snapshot", pages: 0, records: 0, chunks: 0 }, error: null });
        void requestPersistentStorage();
      }
      try {
        const outcome = await syncOnce(store, transport, {
          signal: controller.signal,
          allowed,
          onProgress: (progress) => {
            if (progress.phase === "snapshot") patch({ progress });
          },
        });
        const [meta, counts] = await Promise.all([store.meta(), store.counts()]);
        metaRef.current = meta;
        if (outcome.firstSync || outcome.upserts > 0 || outcome.deletes > 0) versionRef.current++;
        patch({
          phase: "ready",
          complete: meta.complete,
          progress: null,
          records: counts.records,
          chunks: counts.chunks,
          syncedAt: meta.synced_at,
          error: outcome.behind ? "Catching up with the change log." : null,
          model: checkingRef.current ? "loading" : modelState(meta.model_check),
        });
        const check = meta.model_check?.status;
        if (check === "ok") warm();
        // The model downloads once (~34 MB): on the first sync, or later on a connection that needs no consent.
        else if (check !== "mismatch" && (consentRef.current || !firstSyncNeedsConsent(connection(), live.current.phone))) void runModelCheck();
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) {
          // Stopped because another tab deleted the copy: clear what this sync wrote after that tab's clear.
          if (live.current.pref !== "off" && readDevicePreference() === "off") void followRemote("off");
          return;
        }
        const meta = await store.meta().catch(() => metaRef.current);
        metaRef.current = meta;
        const f = failure(error);
        patch({ phase: f.blocked ? "blocked" : "error", complete: meta.complete, progress: null, error: f.text });
      }
    })
      // Cancelled while waiting for another tab's sync to finish.
      .catch((error: unknown) => {
        if (!isAbortError(error)) throw error;
      })
      .finally(() => {
        if (syncRef.current === run) syncRef.current = null;
        if (abortRef.current === controller) abortRef.current = null;
      });
    syncRef.current = run;
    return run;
  }, [followRemote, patch, runModelCheck, warm]);

  // On open (and whenever syncing becomes possible), on focus, every 5 minutes, and when the connection changes.
  useEffect(() => {
    if (storeReady && enabled && online && pref === "auto") void sync();
  }, [storeReady, enabled, online, pref, sync]);

  useEffect(() => {
    if (!storeReady) return;
    const onFocus = () => {
      if (document.visibilityState === "visible" && Date.now() - lastStartRef.current > FOCUS_THROTTLE_MS) void sync();
    };
    const onConnection = () => void sync();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    const conn = connection();
    conn?.addEventListener?.("change", onConnection);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void sync();
    }, SYNC_INTERVAL_MS);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
      conn?.removeEventListener?.("change", onConnection);
      clearInterval(timer);
    };
  }, [storeReady, sync]);

  useEffect(() => () => embedderRef.current?.dispose(), []);

  // Another tab deleted the copy, re-synced it from scratch or turned it on again.
  useEffect(() => {
    const channel = openDeviceChannel((next) => void followRemote(next));
    channelRef.current = channel;
    return () => {
      channel.close();
      if (channelRef.current === channel) channelRef.current = null;
    };
  }, [followRemote]);

  const allowMobileData = useCallback(() => {
    consentRef.current = true;
    void sync();
  }, [sync]);

  const resync = useCallback(async () => {
    await stopSync();
    const store = storeRef.current;
    if (!store) return;
    await store.clear();
    forget();
    consentRef.current = true;
    setPref("auto");
    live.current = { ...live.current, pref: "auto" };
    // The other tabs re-read the store: the copy they had is being downloaded again.
    channelRef.current?.announce("auto");
    patch({ ...INITIAL, phase: "waiting" });
    await sync();
  }, [forget, patch, setPref, stopSync, sync]);

  /**
   * "Delete local copy" (device.ts): stop this tab's sync, clear the store, and
   * only then turn the copy off here, in storage and in the other tabs. A
   * clear that fails keeps the copy on (with its real counts) and throws, so
   * the panel says so instead of "deleted".
   */
  const deleteCopy = useCallback(async () => {
    const store = storeRef.current;
    if (!store) return;
    deletingRef.current = true;
    try {
      const counts = await deleteDeviceCopy(store, {
        stop: async () => {
          await stopSync();
          embedderRef.current?.dispose();
          embedderRef.current = null;
        },
        turnOff: () => {
          setPref("off");
          live.current = { ...live.current, pref: "off" };
          channelRef.current?.announce("off");
        },
      });
      forget();
      patch({ ...INITIAL, phase: "off", records: counts.records, chunks: counts.chunks });
    } catch (error) {
      const counts = await store.counts().catch(() => null);
      patch({ error: "The copy on this device could not be deleted.", ...(counts ?? {}) });
      throw error;
    } finally {
      deletingRef.current = false;
    }
  }, [forget, patch, setPref, stopSync]);

  const enable = useCallback(() => {
    consentRef.current = true;
    setPref("auto");
    live.current = { ...live.current, pref: "auto" };
    channelRef.current?.announce("auto");
    patch({ phase: "waiting", error: null });
    void sync();
  }, [patch, setPref, sync]);

  const prepare = useCallback(
    async (question: string, lang: ResolvedLang): Promise<Prepared | null> => {
      const store = storeRef.current;
      const l = live.current;
      const meta = metaRef.current;
      let copy: DeviceCopy | null = null;
      if (store && l.enabled && l.pref !== "off") {
        const e = meta.model_check?.status === "ok" ? embedder() : null;
        // Not loaded yet (a fresh page): this question goes to the server; the next one can use the device.
        if (e && !e.ready) void e.load().catch(() => undefined);
        copy = {
          store,
          meta,
          index: ensureIndex,
          embed: e?.ready ? async (text) => (await e.embed([text], EMBED_TIMEOUT_MS))[0] : null,
        };
      }
      return prepareHangeul({ question, lang, now: new Date(), timeZone, copy });
    },
    [embedder, ensureIndex, timeZone],
  );

  return {
    state: pref === "off" && state.phase !== "unsupported" ? { ...state, phase: "off" } : state,
    allowMobileData,
    resync,
    deleteCopy,
    enable,
    prepare,
  };
}
