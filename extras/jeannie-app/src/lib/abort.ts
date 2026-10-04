// AbortSignal helpers for the Edge runtime. Next's local Edge sandbox has no
// AbortSignal.any, and Vercel's Edge runtime rejects request signals created by
// the host inside AbortSignal.any. The AI SDK combines the caller's signal with
// its own timeouts through AbortSignal.any, so the chat route needs both fixes.

/** Minimal AbortSignal.any: aborts with the first source's reason. */
function anySignal(signals: Iterable<AbortSignal>): AbortSignal {
  const controller = new AbortController();
  const sources = Array.from(signals);
  const cleanups: (() => void)[] = [];
  const abort = (source: AbortSignal) => {
    for (const cleanup of cleanups) cleanup();
    controller.abort(source.reason);
  };
  for (const source of sources) {
    if (source.aborted) {
      abort(source);
      return controller.signal;
    }
  }
  for (const source of sources) {
    const onAbort = () => abort(source);
    source.addEventListener("abort", onAbort, { once: true });
    cleanups.push(() => source.removeEventListener("abort", onAbort));
  }
  return controller.signal;
}

/** Installs AbortSignal.any where the runtime lacks it. Idempotent. */
export function installAbortSignalAny(): void {
  if (typeof AbortSignal === "undefined" || typeof AbortSignal.any === "function") return;
  Object.defineProperty(AbortSignal, "any", { value: anySignal, configurable: true, writable: true });
}

installAbortSignalAny();

/**
 * A signal owned by this code that follows `parent`, so libraries can pass it
 * to AbortSignal.any even when `parent` is a host request signal. Never throws.
 */
export function ownSignal(parent?: AbortSignal | null): AbortSignal | undefined {
  if (!parent) return undefined;
  const controller = new AbortController();
  try {
    if (parent.aborted) controller.abort(parent.reason);
    else parent.addEventListener("abort", () => controller.abort(parent.reason), { once: true });
  } catch {
    // An unreadable host signal: the SDK's own timeouts still apply.
  }
  return controller.signal;
}
