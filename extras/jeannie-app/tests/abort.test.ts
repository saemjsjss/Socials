import { afterEach, describe, expect, it } from "vitest";
import { installAbortSignalAny, ownSignal } from "@/lib/abort";

const native = AbortSignal.any;

afterEach(() => {
  Object.defineProperty(AbortSignal, "any", { value: native, configurable: true, writable: true });
});

describe("installAbortSignalAny", () => {
  it("adds a working AbortSignal.any where the runtime lacks it", () => {
    Object.defineProperty(AbortSignal, "any", { value: undefined, configurable: true, writable: true });
    installAbortSignalAny();
    expect(AbortSignal.any).not.toBe(native);

    const a = new AbortController();
    const b = new AbortController();
    const combined = AbortSignal.any([a.signal, b.signal]);
    expect(combined.aborted).toBe(false);
    b.abort("second");
    expect(combined.aborted).toBe(true);
    expect(combined.reason).toBe("second");
    a.abort("late"); // no effect once aborted
    expect(combined.reason).toBe("second");

    const already = new AbortController();
    already.abort("early");
    expect(AbortSignal.any([new AbortController().signal, already.signal]).reason).toBe("early");
  });

  it("keeps a native implementation", () => {
    installAbortSignalAny();
    expect(AbortSignal.any).toBe(native);
  });
});

describe("ownSignal", () => {
  it("follows the parent with a signal of its own", () => {
    expect(ownSignal(null)).toBeUndefined();
    const parent = new AbortController();
    const own = ownSignal(parent.signal)!;
    expect(own).not.toBe(parent.signal);
    parent.abort("stop");
    expect(own.aborted).toBe(true);
    expect(own.reason).toBe("stop");

    const done = new AbortController();
    done.abort("x");
    expect(ownSignal(done.signal)!.aborted).toBe(true);
  });

  it("never throws on a hostile signal", () => {
    const hostile = {
      aborted: false,
      addEventListener() {
        throw new TypeError("host signal");
      },
    } as unknown as AbortSignal;
    expect(ownSignal(hostile)?.aborted).toBe(false);
  });
});
