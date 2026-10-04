import { describe, expect, it } from "vitest";
import {
  INITIAL_GATE,
  RESUME_MS,
  SILENCE_MS,
  atRest,
  gateStep,
  nextRest,
  type GateState,
} from "@/lib/avatar/voice-gate";

/** Feeds `level` every 16 ms from `from` to `to` (ms) and returns the final state. */
function feed(state: GateState, level: number, from: number, to: number): GateState {
  for (let now = from; now <= to; now += 16) state = gateStep(state, level, now);
  return state;
}

describe("nextRest", () => {
  const rests = [0, 0.5, 1.25, 3];

  it("returns the rest at or just after the playhead", () => {
    expect(nextRest(rests, 0.5)).toBe(0.5);
    expect(nextRest(rests, 0.4995)).toBe(0.5);
    expect(nextRest(rests, 0.6)).toBe(1.25);
  });

  it("wraps round the loop after the last rest", () => {
    expect(nextRest(rests, 3.2)).toBe(0);
  });

  it("has nothing to offer without rests", () => {
    expect(nextRest([], 1)).toBeNull();
  });

  it("pauses only within a couple of frames of the rest", () => {
    expect(atRest(0.5, 0.5)).toBe(true);
    expect(atRest(0.55, 0.5)).toBe(true);
    expect(atRest(0.6, 0.5)).toBe(false);
    expect(atRest(0.4, 0.5)).toBe(false);
  });
});

describe("voice gate", () => {
  it("rests the mouth after 180 ms of silence", () => {
    let state = feed(INITIAL_GATE, 0.5, 0, 500);
    state = feed(state, 0, 516, 516 + SILENCE_MS - 20);
    expect(state.silent).toBe(false);
    state = feed(state, 0, 516 + SILENCE_MS - 4, 516 + SILENCE_MS + 20);
    expect(state.silent).toBe(true);
  });

  it("does not rest on a short dip inside a word", () => {
    let state = feed(INITIAL_GATE, 0.5, 0, 500);
    state = feed(state, 0, 516, 616);
    state = feed(state, 0.5, 632, 1000);
    state = feed(state, 0, 1016, 1116);
    expect(state.silent).toBe(false);
  });

  it("moves again 60 ms after the voice returns", () => {
    let state: GateState = { silent: true, since: null };
    state = gateStep(state, 0.5, 1000);
    state = gateStep(state, 0.5, 1000 + RESUME_MS - 1);
    expect(state.silent).toBe(true);
    state = gateStep(state, 0.5, 1000 + RESUME_MS);
    expect(state.silent).toBe(false);
  });

  it("ignores levels between the thresholds (no flicker)", () => {
    let state: GateState = { silent: true, since: null };
    state = feed(state, 0.06, 0, 1000);
    expect(state.silent).toBe(true);
    state = feed({ silent: false, since: null }, 0.06, 0, 1000);
    expect(state.silent).toBe(false);
  });
});
