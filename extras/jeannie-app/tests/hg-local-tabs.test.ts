// Ticket 7, "Delete local copy" with two tabs of Jeannie open on one origin
// (the installed PWA and a Chrome tab share one IndexedDB database). Synthetic
// data only (tests/hangeul-fixtures.ts): two handles on one in-memory IndexedDB
// (tests/idb-shim.ts), a shared fake localStorage, and Node's BroadcastChannel.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { syncBlock, syncPanelView } from "@/components/HangeulSyncPanel";
import type { HgLocalState } from "@/hooks/useHangeulLocal";
import { createMemoryStore, openIndexedDbStore, type HgLocalStore } from "@/lib/client/hg-local/db";
import {
  DEVICE_CHANNEL,
  DEVICE_PREF_KEY,
  deleteDeviceCopy,
  followRemoteDelete,
  openDeviceChannel,
  readDevicePreference,
  syncAllowed,
  type DevicePreference,
} from "@/lib/client/hg-local/device";
import { syncOnce, type HgTransport, type SnapshotPage } from "@/lib/client/hg-local/sync";
import type { HgRecord } from "@/lib/hangeul/types";
import { encodeVector } from "@/lib/hangeul/vectors";
import { records, runs } from "./hangeul-fixtures";
import { unit } from "./hangeul-postgrest";
import { fakeIndexedDb, FakeKeyRange } from "./idb-shim";

beforeEach(() => vi.stubGlobal("IDBKeyRange", FakeKeyRange));
afterEach(() => vi.unstubAllGlobals());

/** localStorage as usePersistentState writes it (JSON), shared by the tabs of one origin. */
function sharedStorage() {
  const items = new Map<string, string>();
  return {
    getItem: (key: string) => items.get(key) ?? null,
    setPref: (pref: DevicePreference) => items.set(DEVICE_PREF_KEY, JSON.stringify(pref)),
  };
}

/** A fake snapshot in pages of `size`; `hold` pauses the page at that cursor until released. */
function feed(all: HgRecord[], size = 5) {
  const state = { snapshots: 0, hold: null as string | null, release: null as (() => void) | null, held: null as Promise<void> | null };
  const page = (start: number): SnapshotPage => {
    const part = all.slice(start, start + size);
    return {
      max_seq: 10,
      records: structuredClone(part),
      chunks: part.map((r, i) => ({ kind: r.kind, key: r.key, ord: 0, embedding: encodeVector(unit(start + i)), embed_model: "m" })),
      next: start + size < all.length ? String(start + size) : null,
    };
  };
  const transport: HgTransport = {
    snapshot: async (cursor) => {
      state.snapshots++;
      if (cursor !== null && cursor === state.hold) {
        await new Promise<void>((resolve) => {
          state.release = resolve;
        });
      }
      return page(cursor ? Number(cursor) : 0);
    },
    changes: async (since) => ({ changes: [], next_seq: since, more: false }),
    runs: async () => runs(),
  };
  return { state, transport };
}

async function twoTabs() {
  const idb = fakeIndexedDb();
  return { a: await openIndexedDbStore(idb.indexedDB), b: await openIndexedDbStore(idb.indexedDB) };
}

const isAbort = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

describe("Delete local copy holds in every tab", () => {
  it("a second tab whose own choice is still 'auto' never downloads the copy again", async () => {
    const { a, b } = await twoTabs();
    const storage = sharedStorage();
    const all = records();
    const f = feed(all);

    await syncOnce(a, f.transport);
    expect((await a.counts()).records).toBe(all.length);
    const snapshotsBefore = f.state.snapshots;

    // Tab A: Delete local copy.
    const turnOff = vi.fn(() => storage.setPref("off"));
    const counts = await deleteDeviceCopy(a, { stop: async () => undefined, turnOff });
    expect(counts).toEqual({ records: 0, chunks: 0 });
    expect(turnOff).toHaveBeenCalledTimes(1);

    // Tab B: its 5-minute timer fires with its in-memory choice still "auto".
    const allowed = () => syncAllowed("auto", readDevicePreference(storage));
    const error = await syncOnce(b, f.transport, { allowed }).catch((e: unknown) => e);
    expect(isAbort(error)).toBe(true);
    expect(f.state.snapshots).toBe(snapshotsBefore);
    expect(await b.counts()).toEqual({ records: 0, chunks: 0 });
    expect(await a.counts()).toEqual({ records: 0, chunks: 0 });
  });

  it("a first sync that was running in the other tab stops before its next write", async () => {
    const { a, b } = await twoTabs();
    const storage = sharedStorage();
    storage.setPref("auto");
    const all = records();
    const f = feed(all, 5);
    f.state.hold = "10"; // tab B pauses on its third page

    const allowed = () => syncAllowed("auto", readDevicePreference(storage));
    const running = syncOnce(b, f.transport, { allowed }).catch((e: unknown) => e);
    await vi.waitFor(() => expect(f.state.release).not.toBeNull());
    expect((await a.counts()).records).toBe(10);

    await deleteDeviceCopy(a, { stop: async () => undefined, turnOff: () => storage.setPref("off") });
    f.state.release?.();
    expect(isAbort(await running)).toBe(true);
    expect(await a.counts()).toEqual({ records: 0, chunks: 0 });
    expect((await a.meta()).complete).toBe(false);
  });

  it("the other tab clears once more when told: a page it wrote after the first clear goes too", async () => {
    const { a, b } = await twoTabs();
    const all = records();
    await syncOnce(a, feed(all).transport);
    await a.clear();
    // Tab B's write landed after tab A's clear, before the message reached it.
    await b.write({ ops: [{ op: "upsert", record: all[0], chunks: [] }], meta: {} });
    expect((await a.counts()).records).toBe(1);

    const stop = vi.fn(async () => undefined);
    expect(await followRemoteDelete(b, stop)).toEqual({ records: 0, chunks: 0 });
    expect(stop).toHaveBeenCalledTimes(1);
    expect(await a.counts()).toEqual({ records: 0, chunks: 0 });
  });

  it("stops this tab's sync before clearing, and turns the copy off only after the clear worked", async () => {
    const order: string[] = [];
    const store = createMemoryStore();
    const clear = store.clear.bind(store);
    const recording: HgLocalStore = {
      ...store,
      clear: async () => {
        order.push("clear");
        await clear();
      },
    };
    await deleteDeviceCopy(recording, { stop: async () => void order.push("stop"), turnOff: () => void order.push("off") });
    expect(order).toEqual(["stop", "clear", "off"]);
  });

  it("a clear that fails throws before anything says the copy is gone", async () => {
    const failing: HgLocalStore = {
      ...createMemoryStore(),
      clear: async () => Promise.reject(new DOMException("blocked", "UnknownError")),
    };
    const turnOff = vi.fn();
    await expect(deleteDeviceCopy(failing, { stop: async () => undefined, turnOff })).rejects.toThrow("blocked");
    expect(turnOff).not.toHaveBeenCalled();
  });
});

describe("the persisted choice and the channel", () => {
  it("reads the JSON usePersistentState writes, and nothing else", () => {
    const storage = sharedStorage();
    expect(readDevicePreference(storage)).toBeNull();
    storage.setPref("off");
    expect(readDevicePreference(storage)).toBe("off");
    expect(readDevicePreference({ getItem: () => "off" })).toBeNull(); // not JSON
    expect(readDevicePreference({ getItem: () => '"maybe"' })).toBeNull();
    expect(
      readDevicePreference({
        getItem: () => {
          throw new DOMException("denied", "SecurityError");
        },
      }),
    ).toBeNull();
    expect(readDevicePreference(null)).toBeNull();
  });

  it("a sync is allowed only while neither this tab nor storage says off", () => {
    expect(syncAllowed("auto", null)).toBe(true);
    expect(syncAllowed("auto", "auto")).toBe(true);
    expect(syncAllowed("auto", "off")).toBe(false);
    expect(syncAllowed("off", "auto")).toBe(false);
  });

  it("tells the other tabs, never itself", async () => {
    const heardA: DevicePreference[] = [];
    const heardB: DevicePreference[] = [];
    const a = openDeviceChannel((pref) => heardA.push(pref));
    const b = openDeviceChannel((pref) => heardB.push(pref));
    // Someone else's message on the same channel name is ignored.
    const stranger = new BroadcastChannel(DEVICE_CHANNEL);
    try {
      a.announce("off");
      stranger.postMessage({ type: "other", pref: "off" });
      await vi.waitFor(() => expect(heardB).toEqual(["off"]));
      a.announce("auto");
      await vi.waitFor(() => expect(heardB).toEqual(["off", "auto"]));
      expect(heardA).toEqual([]);
    } finally {
      a.close();
      b.close();
      stranger.close();
    }
  });

  it("works as a no-op where the browser has no BroadcastChannel", () => {
    const channel = openDeviceChannel(() => undefined, () => null);
    expect(() => channel.announce("off")).not.toThrow();
    channel.close();
  });
});

describe("the Hangeul Sync panel", () => {
  const state = (changes: Partial<HgLocalState>): HgLocalState => ({
    phase: "ready",
    complete: true,
    progress: null,
    records: 0,
    chunks: 0,
    syncedAt: null,
    error: null,
    model: "unchecked",
    modelProgress: null,
    ...changes,
  });

  it("says NOT ON THIS DEVICE only when nothing is stored", () => {
    const empty = syncPanelView(state({ phase: "off", complete: false }), null, null, false);
    expect(empty.headline).toBe("NOT ON THIS DEVICE");
    expect(empty.canDelete).toBe(false);
  });

  it("with syncing off but records still stored, says so and keeps Delete enabled", () => {
    const left = syncPanelView(state({ phase: "off", complete: false, records: 3, chunks: 3 }), null, null, false);
    expect(left.headline).toBe("SYNC OFF · 3 STILL HERE");
    expect(left.detail).toContain("3 records are still on this device");
    expect(left.canDelete).toBe(true);
  });

  it("names a block as the Hangeul Data panel does: checking, not linked, locked", () => {
    const view = (block: ReturnType<typeof syncBlock>) => syncPanelView(state({}), block, null, false);
    const checking = syncBlock({ statusLoaded: false, configured: false, keyRequired: false, hasAccessKey: false });
    expect(checking).toEqual({ kind: "checking", text: "Checking the server…" });
    expect(view(checking).headline).toBe("CHECKING…");

    const notLinked = syncBlock({ statusLoaded: true, configured: false, keyRequired: true, hasAccessKey: true });
    expect(notLinked?.kind).toBe("not_linked");
    expect(view(notLinked).headline).toBe("NOT LINKED");
    expect(view(notLinked).detail).toBe("Not linked: set SUPABASE_URL and SUPABASE_SECRET_KEY.");

    const noServerKey = syncBlock({ statusLoaded: true, configured: true, keyRequired: false, hasAccessKey: false });
    expect(noServerKey?.kind).toBe("locked");
    expect(view(noServerKey).headline).toBe("LOCKED");
    const noKeyHere = syncBlock({ statusLoaded: true, configured: true, keyRequired: true, hasAccessKey: false });
    expect(view(noKeyHere)).toMatchObject({ headline: "LOCKED", detail: "Locked: access key required.", canResync: false });

    expect(syncBlock({ statusLoaded: true, configured: true, keyRequired: true, hasAccessKey: true })).toBeNull();
  });
});
