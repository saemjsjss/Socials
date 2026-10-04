// Ticket 6 (spec D10): an unreachable API turns into the offline banner and
// disabled controls, and nothing is sent while offline. The wiring is tested
// without a browser: api.ts with a stubbed fetch, the send guard, the composer
// rule and the probe loop as pure helpers, and the controls rendered to static
// markup with react-dom/server (no effects run, so the first render is what a
// user sees).
import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatComposer } from "@/components/ChatComposer";
import { IoTControlGrid, sendToggle } from "@/components/IoTControlGrid";
import { OfflineBanner } from "@/components/OfflineBanner";
import { TacticalMetrics } from "@/components/TacticalMetrics";
import type { SpeechRecognitionState } from "@/hooks/useSpeechRecognition";
import { ApiRequestError, fetchSystemStatus, onReachability } from "@/lib/client/api";
import { canSendMessage, OFFLINE_LINE, probeDelay, sendUnlessOffline, startProbeLoop } from "@/lib/client/reachability";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Every reachability report during `run`. */
async function reportsDuring(run: () => Promise<unknown>): Promise<boolean[]> {
  const seen: boolean[] = [];
  const unsubscribe = onReachability((reachable) => seen.push(reachable));
  try {
    await run().catch(() => undefined);
  } finally {
    unsubscribe();
  }
  return seen;
}

describe("api.ts reports whether the server was reached", () => {
  it("a fetch that throws (no network) reports unreachable, as a network_error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const error = await fetchSystemStatus().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).code).toBe("network_error");
    expect(await reportsDuring(() => fetchSystemStatus())).toEqual([false]);
  });

  it("any HTTP answer, even a 502, reports reachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "Upstream.", code: "bad_gateway" }), { status: 502 })));
    const error = await fetchSystemStatus().catch((e: unknown) => e);
    expect((error as ApiRequestError).status).toBe(502);
    expect(await reportsDuring(() => fetchSystemStatus())).toEqual([true]);
  });

  it("a 200 reports reachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
    expect(await reportsDuring(() => fetchSystemStatus())).toEqual([true]);
  });

  it("a timeout reports nothing (a long answer can time out on a working connection)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new DOMException("The operation timed out.", "TimeoutError"))));
    const error = await fetchSystemStatus().catch((e: unknown) => e);
    expect((error as ApiRequestError).code).toBe("timeout");
    expect(await reportsDuring(() => fetchSystemStatus())).toEqual([]);
  });

  it("a request the user stopped reports nothing", async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new DOMException("Aborted", "AbortError"))));
    expect(await reportsDuring(() => fetchSystemStatus(controller.signal))).toEqual([]);
  });

  it("an unsubscribed listener hears nothing more", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const seen: boolean[] = [];
    const unsubscribe = onReachability((reachable) => seen.push(reachable));
    unsubscribe();
    await fetchSystemStatus().catch(() => undefined);
    expect(seen).toEqual([]);
  });
});

describe("the HUD's one send", () => {
  it("sends nothing while offline and says so (false)", () => {
    const chat = vi.fn<(text: string, image?: string | null) => boolean>(() => true);
    let offline = true;
    const send = sendUnlessOffline(() => offline, chat);
    expect(send("Turn on the fan", null)).toBe(false);
    expect(chat).not.toHaveBeenCalled();
    offline = false;
    expect(send("Turn on the fan", null)).toBe(true);
    expect(chat).toHaveBeenCalledWith("Turn on the fan", null);
  });

  it("passes on the chat's own refusal (busy)", () => {
    const send = sendUnlessOffline(() => false, (text: string) => text.length === 0);
    expect(send("hello")).toBe(false);
  });

  it("the composer can send text or an image, never while disabled (offline) or preparing an image", () => {
    const base = { draft: "hello", hasAttachment: false, preparing: false, disabled: false };
    expect(canSendMessage(base)).toBe(true);
    expect(canSendMessage({ ...base, disabled: true })).toBe(false);
    expect(canSendMessage({ ...base, preparing: true })).toBe(false);
    expect(canSendMessage({ ...base, draft: "   " })).toBe(false);
    expect(canSendMessage({ ...base, draft: "", hasAttachment: true })).toBe(true);
    expect(canSendMessage({ ...base, draft: "", hasAttachment: true, disabled: true })).toBe(false);
  });
});

describe("the /api/status re-probe loop", () => {
  function fakeTimers() {
    const pending: { run: () => void; ms: number; id: number }[] = [];
    let next = 1;
    return {
      pending,
      timers: {
        set: (run: () => void, ms: number) => {
          const id = next++;
          pending.push({ run, ms, id });
          return id;
        },
        clear: (handle: unknown) => {
          const i = pending.findIndex((p) => p.id === handle);
          if (i >= 0) pending.splice(i, 1);
        },
      },
      /** Fire the oldest timer and let the probe settle. */
      async fire() {
        const timer = pending.shift();
        if (!timer) throw new Error("no timer pending");
        timer.run();
        await new Promise((resolve) => setTimeout(resolve, 0));
        return timer.ms;
      },
    };
  }

  it("probes after 2 s, 4 s, 8 s ... while it fails, and stops once one answers", async () => {
    const t = fakeTimers();
    const results = [false, false, false, true];
    const probe = vi.fn(async () => {
      if (!results.shift()) throw new ApiRequestError(0, "network_error", "Uplink unreachable.");
    });
    startProbeLoop(probe, t.timers);
    const delays = [await t.fire(), await t.fire(), await t.fire(), await t.fire()];
    expect(delays).toEqual([probeDelay(0), probeDelay(1), probeDelay(2), probeDelay(3)]);
    expect(delays).toEqual([2_000, 4_000, 8_000, 16_000]);
    expect(probe).toHaveBeenCalledTimes(4);
    expect(t.pending).toEqual([]);
  });

  it("stop() cancels the next probe, and a probe that fails after stop() schedules none", async () => {
    const t = fakeTimers();
    let fail: (error: Error) => void = () => undefined;
    const probe = vi.fn(() => new Promise<void>((_, reject) => (fail = reject)));
    const stop = startProbeLoop(probe, t.timers);
    t.pending[0].run();
    stop();
    fail(new Error("down"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(t.pending).toEqual([]);

    const again = fakeTimers();
    const stopAgain = startProbeLoop(probe, again.timers);
    expect(again.pending).toHaveLength(1);
    stopAgain();
    expect(again.pending).toEqual([]);
  });
});

// ── The controls, as rendered ────────────────────────────────────────────────

const html = (element: ReactElement) => renderToStaticMarkup(element);

/** The opening tag of every <button> in the markup. */
function buttons(markup: string): string[] {
  return markup.match(/<button\b[^>]*>/g) ?? [];
}

const recognition: SpeechRecognitionState = {
  supported: true,
  listening: false,
  interim: "",
  error: null,
  activityRef: { current: 0 },
  start: () => undefined,
  stop: () => undefined,
};

describe("offline banner", () => {
  it("shows the line in both languages while offline, inside an always-mounted live region", () => {
    const off = html(createElement(OfflineBanner, { offline: true, variant: "hud" }));
    expect(off).toContain('role="status"');
    expect(off).toContain(OFFLINE_LINE.en);
    expect(off).toContain(OFFLINE_LINE.ko);
    const on = html(createElement(OfflineBanner, { offline: false, variant: "hud" }));
    expect(on).toContain('role="status"');
    expect(on).not.toContain(OFFLINE_LINE.en);
  });
});

describe("composer while offline", () => {
  const props = {
    phase: "idle" as const,
    speaking: false,
    lang: "auto" as const,
    onLangChange: () => undefined,
    voiceOn: true,
    onVoiceToggle: () => undefined,
    attachment: null,
    onAttach: () => undefined,
    onOpenCamera: () => undefined,
    onSend: () => true,
    onStop: () => undefined,
    onNotice: () => undefined,
    recognition,
  };

  it("disables the text box and the mic, with the offline line as the placeholder", () => {
    const markup = html(createElement(ChatComposer, { ...props, disabled: true, disabledText: OFFLINE_LINE.en }));
    expect(markup).toMatch(/<textarea[^>]*disabled=""/);
    expect(markup).toContain(`placeholder="${OFFLINE_LINE.en}"`);
    // The mic is the hold-to-talk button; offline, its label is the offline line.
    const mic = buttons(markup).find((b) => b.includes("touch-hold"));
    expect(mic, "the mic button").toBeDefined();
    expect(mic).toContain('disabled=""');
    expect(mic).toContain(`aria-label="${OFFLINE_LINE.en}"`);
  });

  it("leaves them enabled online", () => {
    const markup = html(createElement(ChatComposer, { ...props, disabled: false }));
    expect(markup).not.toMatch(/<textarea[^>]*disabled=""/);
    expect(buttons(markup).find((b) => b.includes("touch-hold"))).not.toContain('disabled=""');
  });
});

describe("smart-home tiles while offline", () => {
  it("disables every tile and both thermostat buttons, with the offline line as their title", () => {
    const markup = html(createElement(IoTControlGrid, { lang: "en", onCommand: () => false, offline: true, offlineText: OFFLINE_LINE.en }));
    const all = buttons(markup);
    expect(all).toHaveLength(7); // five tiles, thermostat - and +
    for (const button of all) {
      expect(button).toContain('disabled=""');
      expect(button).toContain(`title="${OFFLINE_LINE.en}"`);
    }
  });

  it("leaves the tiles enabled online", () => {
    const markup = html(createElement(IoTControlGrid, { lang: "en", onCommand: () => true }));
    const tiles = buttons(markup).filter((b) => b.includes("aria-pressed"));
    expect(tiles).toHaveLength(5);
    for (const tile of tiles) expect(tile).not.toContain('disabled=""');
  });

  it("a tile flips only when its command went out", () => {
    const on = { lights: true, fan: false };
    const command = (next: boolean) => (next ? "Turn on the fan" : "Turn off the fan");
    const unsent = sendToggle(on, "fan", command, () => false);
    expect(unsent).toBe(on);
    const sent: string[] = [];
    const flipped = sendToggle(on, "fan", command, (text) => {
      sent.push(text);
      return true;
    });
    expect(flipped).toEqual({ lights: true, fan: true });
    expect(sent).toEqual(["Turn on the fan"]);
    // A caller that returns nothing (void) counts as sent.
    expect(sendToggle(on, "lights", () => "Turn off the living room lights", () => undefined)).toEqual({ lights: false, fan: false });
  });
});

describe("DAILY REPORT while offline", () => {
  const props = {
    status: null,
    statusLoading: false,
    statusError: null,
    onRetryStatus: () => undefined,
    hasAccessKey: true,
    lang: "en" as const,
    onCommand: () => true,
    telemetry: { lastLatencyMs: null, lastTtfbMs: null, activeAgent: null, provider: null },
    messageCount: 0,
    voiceEngine: null,
    replyLang: null,
    sessionStart: null,
  };
  const report = (markup: string) => buttons(markup).find((b) => b.includes('aria-label="Ask Jeannie for the Hangeul daily brief"'));

  it("is disabled offline, with the offline line as its title, and so are the tiles", () => {
    const markup = html(createElement(TacticalMetrics, { ...props, offline: true }));
    expect(report(markup)).toContain('disabled=""');
    expect(report(markup)).toContain(`title="${OFFLINE_LINE.en}"`);
    for (const tile of buttons(markup).filter((b) => b.includes("aria-pressed"))) expect(tile).toContain('disabled=""');
  });

  it("is enabled online", () => {
    const markup = html(createElement(TacticalMetrics, { ...props, offline: false }));
    expect(report(markup)).toBeDefined();
    expect(report(markup)).not.toContain('disabled=""');
  });
});
