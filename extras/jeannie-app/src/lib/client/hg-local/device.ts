// Whether this browser keeps the device copy at all, for every tab of the
// origin (ticket 7, "Delete local copy"). The copy is one IndexedDB database
// shared by all tabs (an installed PWA and a Chrome tab, say), so turning it
// off must hold in all of them:
//
// - the choice is persisted ("jeannie.hg.device", JSON, as usePersistentState
//   writes it) and re-read before a sync starts and before each of its writes
//   (syncOnce's `allowed`), so a tab whose in-memory choice is stale never
//   downloads the copy again;
// - a BroadcastChannel tells the other tabs at once: they stop their sync and
//   clear the store once more (a page they were writing may have landed after
//   this tab's clear).
//
// Pure apart from the injected storage and channel, so it is tested in Node.

import type { HgLocalStore } from "./db";

export const DEVICE_PREF_KEY = "jeannie.hg.device";
export const DEVICE_CHANNEL = "jeannie-hg-device";

/** "auto": the copy syncs; "off": deleted, nothing syncs until the owner turns it on again. */
export type DevicePreference = "auto" | "off";

export const isDevicePreference = (value: unknown): value is DevicePreference => value === "auto" || value === "off";

type StorageLike = Pick<Storage, "getItem">;

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The persisted choice, or null when none is stored or storage is blocked (the tab's own choice then stands). */
export function readDevicePreference(storage: StorageLike | null = browserStorage()): DevicePreference | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(DEVICE_PREF_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDevicePreference(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** A sync may run (and keep writing) only while neither this tab nor the persisted choice says "off". */
export function syncAllowed(own: DevicePreference, stored: DevicePreference | null): boolean {
  return own !== "off" && stored !== "off";
}

interface ChannelLike {
  postMessage(message: unknown): void;
  close(): void;
  onmessage: ((event: MessageEvent) => void) | null;
}

export interface DeviceChannel {
  /** Tells the other tabs (never this one) that the copy was deleted, or turned on again. */
  announce(pref: DevicePreference): void;
  close(): void;
}

function browserChannel(name: string): ChannelLike | null {
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(name);
}

/** The other tabs' announcements; a no-op channel where the browser has no BroadcastChannel. */
export function openDeviceChannel(
  onRemote: (pref: DevicePreference) => void,
  create: (name: string) => ChannelLike | null = browserChannel,
): DeviceChannel {
  let channel: ChannelLike | null = null;
  try {
    channel = create(DEVICE_CHANNEL);
  } catch {
    channel = null;
  }
  if (channel) {
    channel.onmessage = (event) => {
      const data = event.data as { type?: unknown; pref?: unknown } | null;
      if (data && data.type === "hg-device" && isDevicePreference(data.pref)) onRemote(data.pref);
    };
  }
  return {
    announce(pref) {
      try {
        channel?.postMessage({ type: "hg-device", pref });
      } catch {
        // A closed channel: the other tabs still read the persisted choice before their next write.
      }
    },
    close() {
      channel?.close();
      channel = null;
    },
  };
}

/**
 * "Delete local copy": stop this tab's sync, clear the store, and only then
 * turn the copy off (persist "off" and tell the other tabs). A clear that
 * fails throws before anything says the copy is gone. Returns the store's
 * real counts afterwards.
 */
export async function deleteDeviceCopy(
  store: HgLocalStore,
  steps: { stop: () => Promise<void>; turnOff: () => void },
): Promise<{ records: number; chunks: number }> {
  await steps.stop();
  await store.clear();
  steps.turnOff();
  return store.counts();
}

/**
 * Another tab deleted the copy: stop this tab's sync (and wait for it), then
 * clear again, so nothing this tab wrote after the other tab's clear stays.
 */
export async function followRemoteDelete(store: HgLocalStore, stop: () => Promise<void>): Promise<{ records: number; chunks: number }> {
  await stop();
  await store.clear();
  return store.counts();
}
