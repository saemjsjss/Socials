// A small in-memory IndexedDB for the tests (the repo has no fake-indexeddb,
// and ticket 7 allows one new dependency only): just what
// src/lib/client/hg-local/db.ts uses. Keys compare as the IndexedDB spec says
// (number < string < array; arrays element by element, a prefix first), which
// is what the device copy's [kind, key] and [kind, key, ord] ranges rely on.
// Operations run in request order; success events and the transaction's
// complete event arrive asynchronously, as in a browser.

type Key = number | string | Key[];

function typeRank(k: Key): number {
  if (typeof k === "number") return 1;
  if (typeof k === "string") return 3;
  if (Array.isArray(k)) return 5;
  throw new DataError("not a valid key");
}

class DataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataError";
  }
}

export function compareKeys(a: Key, b: Key): number {
  const ta = typeRank(a);
  const tb = typeRank(b);
  if (ta !== tb) return ta < tb ? -1 : 1;
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const c = compareKeys(a[i], b[i]);
      if (c !== 0) return c;
    }
    return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
  }
  return a === b ? 0 : (a as number | string) < (b as number | string) ? -1 : 1;
}

export class FakeKeyRange {
  constructor(
    readonly lower: Key | undefined,
    readonly upper: Key | undefined,
    readonly lowerOpen = false,
    readonly upperOpen = false,
  ) {}

  static bound(lower: Key, upper: Key, lowerOpen = false, upperOpen = false): FakeKeyRange {
    if (compareKeys(lower, upper) > 0) throw new DataError("lower is greater than upper");
    return new FakeKeyRange(lower, upper, lowerOpen, upperOpen);
  }

  static only(key: Key): FakeKeyRange {
    return new FakeKeyRange(key, key);
  }

  includes(key: Key): boolean {
    if (this.lower !== undefined) {
      const c = compareKeys(key, this.lower);
      if (c < 0 || (c === 0 && this.lowerOpen)) return false;
    }
    if (this.upper !== undefined) {
      const c = compareKeys(key, this.upper);
      if (c > 0 || (c === 0 && this.upperOpen)) return false;
    }
    return true;
  }
}

class FakeRequest<T = unknown> {
  result: T | undefined;
  error: Error | null = null;
  onsuccess: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onupgradeneeded: (() => void) | null = null;
}

interface Row {
  key: Key;
  value: unknown;
}

class StoreData {
  rows: Row[] = [];
  constructor(readonly keyPath: string | string[] | null) {}

  keyOf(value: unknown, explicit?: Key): Key {
    if (this.keyPath === null) {
      if (explicit === undefined) throw new DataError("an out-of-line store needs a key");
      return explicit;
    }
    const v = value as Record<string, Key>;
    return Array.isArray(this.keyPath) ? this.keyPath.map((p) => v[p]) : v[this.keyPath];
  }

  find(key: Key): number {
    return this.rows.findIndex((r) => compareKeys(r.key, key) === 0);
  }

  put(value: unknown, explicit?: Key): Key {
    const key = this.keyOf(value, explicit);
    typeRank(key);
    const row = { key, value: structuredClone(value) };
    const at = this.find(key);
    if (at >= 0) this.rows[at] = row;
    else {
      this.rows.push(row);
      this.rows.sort((a, b) => compareKeys(a.key, b.key));
    }
    return key;
  }

  select(query?: Key | FakeKeyRange): Row[] {
    if (query === undefined) return this.rows;
    const range = query instanceof FakeKeyRange ? query : FakeKeyRange.only(query);
    return this.rows.filter((r) => range.includes(r.key));
  }
}

class FakeTransaction {
  oncomplete: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  error: Error | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly stores: Map<string, StoreData>,
    private readonly names: string[],
    private readonly mode: IDBTransactionMode,
  ) {
    this.schedule();
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.oncomplete?.(), 0);
  }

  request<T>(run: () => T): FakeRequest<T> {
    const req = new FakeRequest<T>();
    try {
      req.result = run();
      queueMicrotask(() => req.onsuccess?.());
    } catch (error) {
      req.error = error as Error;
      this.error = req.error;
      queueMicrotask(() => {
        req.onerror?.();
        this.onerror?.();
      });
    }
    this.schedule();
    return req;
  }

  objectStore(name: string) {
    if (!this.names.includes(name)) throw new Error(`store ${name} is not in this transaction`);
    const data = this.stores.get(name);
    if (!data) throw new Error(`no store ${name}`);
    const writable = () => {
      if (this.mode !== "readwrite") throw new Error("read-only transaction");
    };
    return {
      put: (value: unknown, key?: Key) =>
        this.request(() => {
          writable();
          return data.put(value, key);
        }),
      delete: (query: Key | FakeKeyRange) =>
        this.request(() => {
          writable();
          const doomed = new Set(data.select(query));
          data.rows = data.rows.filter((r) => !doomed.has(r));
          return undefined;
        }),
      get: (key: Key) => this.request(() => structuredClone(data.select(key)[0]?.value)),
      getAll: (query?: Key | FakeKeyRange) => this.request(() => data.select(query).map((r) => structuredClone(r.value))),
      getAllKeys: () => this.request(() => data.rows.map((r) => r.key)),
      count: () => this.request(() => data.rows.length),
      clear: () =>
        this.request(() => {
          writable();
          data.rows = [];
          return undefined;
        }),
    };
  }
}

class FakeDatabase {
  readonly stores = new Map<string, StoreData>();
  onversionchange: (() => void) | null = null;
  closed = false;
  constructor(public version: number) {}

  get objectStoreNames() {
    return { contains: (name: string) => this.stores.has(name) };
  }

  createObjectStore(name: string, options: { keyPath?: string | string[] } = {}) {
    this.stores.set(name, new StoreData(options.keyPath ?? null));
  }

  transaction(names: string | string[], mode: IDBTransactionMode = "readonly") {
    if (this.closed) throw new Error("database closed");
    return new FakeTransaction(this.stores, Array.isArray(names) ? names : [names], mode);
  }

  close() {
    this.closed = true;
  }
}

/** A fresh IndexedDB (IDBFactory-like) and IDBKeyRange, to stub as globals. */
export function fakeIndexedDb() {
  const databases = new Map<string, FakeDatabase>();
  const factory = {
    open(name: string, version = 1) {
      const req = new FakeRequest<FakeDatabase>();
      setTimeout(() => {
        let db = databases.get(name);
        const upgrade = !db || db.version < version;
        if (!db) {
          db = new FakeDatabase(version);
          databases.set(name, db);
        }
        db.closed = false;
        db.version = Math.max(db.version, version);
        req.result = db;
        if (upgrade) req.onupgradeneeded?.();
        req.onsuccess?.();
      }, 0);
      return req;
    },
    deleteDatabase(name: string) {
      databases.delete(name);
      const req = new FakeRequest();
      setTimeout(() => req.onsuccess?.(), 0);
      return req;
    },
  };
  return { indexedDB: factory as unknown as IDBFactory, IDBKeyRange: FakeKeyRange, databases };
}
