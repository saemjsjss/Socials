import { describe, expect, it } from "vitest";
import { CLIP_NAMES, CLIP_VERSION, DEFAULT_CLIPS, ESSENTIAL_CLIPS, clipNameFor, mergeClipManifest } from "@/lib/avatar/clips";
import { emotePickerEnabled } from "@/lib/avatar/debug";
import { EMOTES } from "@/lib/emote";
import { CLIP_VERSION as INGEST_CLIP_VERSION, KLING_NAMES, ingestPlan } from "../scripts/avatar-clips/kling.mjs";
import { oneShotDeadlineMs } from "@/hooks/useAvatarDirector";
import klingClips from "../assets/avatar/kling/clips.json";
import {
  IDLE_SEQUENCE,
  INITIAL_DIRECTOR,
  baseStateOf,
  cueOf,
  directorReducer,
  shouldDeferCue,
  type ClipCue,
  type DirectorEvent,
  type DirectorState,
} from "@/lib/avatar/director";
import {
  CHECK_IN_LINES,
  CHECK_IN_MS,
  holdIdle,
  idleStep,
  pickCheckIn,
  resetIdle,
} from "@/lib/avatar/idle";
import { awayMsFrom, isViewMode, resolveView } from "@/lib/avatar/view-mode";
import manifest from "../public/avatar/manifest.json";

const run = (events: DirectorEvent[], from: DirectorState = INITIAL_DIRECTOR) => events.reduce(directorReducer, from);

describe("avatar director", () => {
  it("loops idle by default", () => {
    expect(cueOf(INITIAL_DIRECTOR)).toEqual({ emote: "idle", key: "idle", loop: true, focus: false });
  });

  it("derives the base state: listening beats talking", () => {
    expect(baseStateOf({ listening: true, speaking: true })).toBe("listening");
    expect(baseStateOf({ listening: false, speaking: true })).toBe("talking");
    expect(baseStateOf({ listening: false, speaking: false })).toBe("idle");
  });

  it("plays a one-shot once, then hands back to the base state", () => {
    const playing = run([{ type: "emote", emote: "greeting" }]);
    expect(cueOf(playing)).toMatchObject({ emote: "greeting", loop: false });
    // Idle's base is the idle sequence.
    expect(cueOf(run([{ type: "ended", seq: playing.seq }], playing))).toMatchObject({ emote: "spin", loop: false });
    const talking = run([{ type: "base", base: "talking" }, { type: "emote", emote: "nod" }]);
    expect(cueOf(run([{ type: "ended", seq: talking.seq }], talking))).toMatchObject({ emote: "talking", loop: true });
  });

  it("hands a finished one-shot to talking while speech plays", () => {
    const state = run([
      { type: "emote", emote: "nod" },
      { type: "base", base: "talking" },
    ]);
    expect(cueOf(state).emote).toBe("nod");
    expect(cueOf(run([{ type: "ended", seq: state.seq }], state))).toMatchObject({ emote: "talking", loop: true });
  });

  it("queues one emote behind a playing one-shot, newest wins", () => {
    const state = run([
      { type: "emote", emote: "greeting" },
      { type: "emote", emote: "concern" },
      { type: "emote", emote: "air_kiss" },
    ]);
    expect(state.playing).toBe("greeting");
    expect(state.queued).toBe("air_kiss");
    const next = run([{ type: "ended", seq: state.seq }], state);
    expect(next.playing).toBe("air_kiss");
    expect(next.queued).toBeNull();
    expect(cueOf(next).key).not.toBe(cueOf(state).key);
  });

  it("restarts the clip for a repeat of the same emote", () => {
    const first = run([
      { type: "base", base: "talking" },
      { type: "emote", emote: "nod" },
    ]);
    const second = run(
      [
        { type: "ended", seq: first.seq },
        { type: "emote", emote: "nod" },
      ],
      first,
    );
    expect(cueOf(second).key).not.toBe(cueOf(first).key);
  });

  it("ignores a stale ended event", () => {
    const first = run([{ type: "emote", emote: "nod" }]);
    const second = run(
      [
        { type: "ended", seq: first.seq },
        { type: "emote", emote: "sadness" },
      ],
      first,
    );
    expect(run([{ type: "ended", seq: first.seq }], second)).toBe(second);
  });

  it("listening cuts the one-shot and keeps the idle loop running under a focus", () => {
    const state = run([
      { type: "emote", emote: "greeting" },
      { type: "base", base: "listening" },
    ]);
    expect(state.playing).toBeNull();
    expect(cueOf(state)).toEqual({ emote: "listening", key: "idle", loop: true, focus: true });
  });

  it("holds emotes that arrive while listening until the mic is released", () => {
    const listening = run([
      { type: "base", base: "listening" },
      { type: "emote", emote: "concern" },
    ]);
    expect(listening.playing).toBeNull();
    expect(run([{ type: "base", base: "idle" }], listening).playing).toBe("concern");
  });

  it("idle sequence: plays spin, playful, shyness, heartbeat, sway back-to-back after the greeting", () => {
    let state = run([{ type: "emote", emote: "greeting" }]);
    const order: string[] = [];
    for (let i = 0; i < IDLE_SEQUENCE.length + 1; i++) {
      state = run([{ type: "ended", seq: state.seq }], state);
      order.push(cueOf(state).emote);
      expect(cueOf(state).loop).toBe(false);
    }
    expect(order).toEqual(["spin", "playful", "shyness", "heartbeat", "sway", "spin"]);
  });

  it("idle sequence gives way to talking at once and resumes at the next step", () => {
    const greeted = run([{ type: "emote", emote: "greeting" }]);
    const spinning = run([{ type: "ended", seq: greeted.seq }], greeted);
    const talking = run([{ type: "base", base: "talking" }], spinning);
    expect(cueOf(talking)).toMatchObject({ emote: "talking", loop: true });
    expect(cueOf(run([{ type: "base", base: "idle" }], talking)).emote).toBe("playful");
  });

  it("idle sequence gives way to the mic", () => {
    const greeted = run([{ type: "emote", emote: "greeting" }]);
    const spinning = run([{ type: "ended", seq: greeted.seq }], greeted);
    expect(cueOf(run([{ type: "base", base: "listening" }], spinning))).toMatchObject({ emote: "listening", key: "idle" });
  });

  it("a reply emote waits for the idle-sequence step, then the sequence carries on", () => {
    const greeted = run([{ type: "emote", emote: "greeting" }]);
    const spinning = run([{ type: "ended", seq: greeted.seq }, { type: "emote", emote: "love" }], greeted);
    expect(spinning.playing).toBe("spin");
    const love = run([{ type: "ended", seq: spinning.seq }], spinning);
    expect(love).toMatchObject({ playing: "love", ambient: false });
    expect(run([{ type: "ended", seq: love.seq }], love).playing).toBe("playful");
  });

  it("a reply emote with speech cuts the idle-sequence step at once", () => {
    const greeted = run([{ type: "emote", emote: "greeting" }]);
    const state = run(
      [{ type: "ended", seq: greeted.seq }, { type: "emote", emote: "love" }, { type: "base", base: "talking" }],
      greeted,
    );
    expect(state).toMatchObject({ base: "talking", playing: "love", queued: null, ambient: false });
  });
});

describe("avatar clips", () => {
  it("listening reuses the idle clip; every other emote has its own, in the table and the manifest", () => {
    expect(clipNameFor("listening")).toBe("idle");
    expect(clipNameFor("love")).toBe("love");
    const clipEmotes = EMOTES.filter((e) => e !== "listening");
    expect([...CLIP_NAMES].sort()).toEqual([...clipEmotes].sort());
    for (const name of CLIP_NAMES) {
      expect(DEFAULT_CLIPS[name].src).toMatch(new RegExp(`^/avatar/${name}\\.mp4(\\?v=${CLIP_VERSION})?$`));
      expect(manifest).toHaveProperty(name);
    }
    expect(Object.keys(manifest).sort()).toEqual([...clipEmotes].sort());
  });

  it("versions the Kling clip URLs so a stale service-worker cache is bypassed", () => {
    expect(INGEST_CLIP_VERSION).toBe(CLIP_VERSION);
    for (const [name, entry] of Object.entries(manifest)) {
      const kling = (entry as { source?: string }).source === "kling";
      expect({ name, versioned: entry.src.endsWith(`?v=${CLIP_VERSION}`) }).toEqual({ name, versioned: kling });
    }
  });

  it("loops idle and talking; the essential clips cover every state before a reply", () => {
    const loops = CLIP_NAMES.filter((e) => DEFAULT_CLIPS[e].loop).sort();
    expect(loops).toEqual(["idle", "talking"]);
    expect([...ESSENTIAL_CLIPS].sort()).toEqual(["greeting", "idle", "talking"]);
  });

  it("gives a one-shot time to wait out one idle cycle before its safety timeout", () => {
    expect(oneShotDeadlineMs(DEFAULT_CLIPS, "spin")).toBe(
      Math.round((DEFAULT_CLIPS.spin.duration + DEFAULT_CLIPS.idle.duration) * 1000 + 5000),
    );
  });

  it("the static table agrees with the pipeline manifest on files and looping", () => {
    // Durations move whenever the pipeline re-cuts a clip; the manifest overrides them at runtime.
    const merged = mergeClipManifest(DEFAULT_CLIPS, manifest);
    for (const [name, clip] of Object.entries(merged)) {
      const base = DEFAULT_CLIPS[name as keyof typeof DEFAULT_CLIPS];
      expect({ name, src: clip.src, poster: clip.poster, loop: clip.loop }).toEqual({
        name,
        src: base.src,
        poster: base.poster,
        loop: base.loop,
      });
    }
  });

  it("merges valid manifest entries and ignores junk", () => {
    const merged = mergeClipManifest(DEFAULT_CLIPS, {
      nod: { src: "/avatar/nod.mp4", poster: "/avatar/nod.jpg", duration: 2.5, loop: false, placeholder: false },
      talking: { src: "https://evil.example/x.mp4", poster: "", duration: 1, loop: true },
      unknown: { src: "/x.mp4", poster: "/x.jpg", duration: 1, loop: true },
      idle: { src: "/avatar/idle.mp4", poster: "/avatar/idle.jpg", duration: -1, loop: true },
    });
    expect(merged.nod).toMatchObject({ duration: 2.5, placeholder: false });
    expect(merged.talking).toEqual(DEFAULT_CLIPS.talking);
    expect(merged.idle).toEqual(DEFAULT_CLIPS.idle);
    expect(mergeClipManifest(DEFAULT_CLIPS, null)).toBe(DEFAULT_CLIPS);
  });

  it("ships the talking clip's mouth rests, ascending and inside the clip", () => {
    const rests = mergeClipManifest(DEFAULT_CLIPS, manifest).talking.rests ?? [];
    expect(rests.length).toBeGreaterThan(10);
    expect(rests[0]).toBe(0);
    for (let i = 1; i < rests.length; i++) {
      expect(rests[i]).toBeGreaterThan(rests[i - 1]!);
      // A pause never waits much longer than a second for her mouth to close.
      expect(rests[i]! - rests[i - 1]!).toBeLessThanOrEqual(1);
    }
    expect(rests.at(-1)).toBeLessThan(manifest.talking.duration);
  });

  it("keeps valid rests and drops junk ones", () => {
    const talking = { src: "/avatar/talking.mp4", poster: "/avatar/talking.jpg", duration: 2, loop: true };
    expect(mergeClipManifest(DEFAULT_CLIPS, { talking: { ...talking, rests: [0, 0.5, 1.5] } }).talking.rests).toEqual([
      0, 0.5, 1.5,
    ]);
    for (const rests of [[0.5, 0.2], [0, 3], [0, Number.NaN], "0,1", [-1]]) {
      expect(mergeClipManifest(DEFAULT_CLIPS, { talking: { ...talking, rests } }).talking.rests).toBeUndefined();
    }
  });
});

describe("seamless cuts", () => {
  const idle: ClipCue = { emote: "idle", key: "idle", loop: true, focus: false };
  const listening: ClipCue = { emote: "listening", key: "idle", loop: true, focus: true };
  const talking: ClipCue = { emote: "talking", key: "talking", loop: true, focus: false };
  const love: ClipCue = { emote: "love", key: "love#1", loop: false, focus: false };

  it("a one-shot over idle waits for idle's loop point", () => {
    expect(shouldDeferCue(idle, love)).toBe(true);
    expect(shouldDeferCue(idle, { ...love, emote: "sway", key: "sway#2" })).toBe(true);
  });

  it("voice, mic and one-shots over talking cut at once", () => {
    expect(shouldDeferCue(talking, love)).toBe(false);
    expect(shouldDeferCue(idle, talking)).toBe(false);
    expect(shouldDeferCue(love, idle)).toBe(false);
    expect(shouldDeferCue(null, love)).toBe(false);
  });

  it("pressing the mic never switches clips: listening keeps idle's key", () => {
    expect(cueOf(run([{ type: "base", base: "listening" }])).key).toBe(idle.key);
    expect(shouldDeferCue(listening, love)).toBe(true);
  });
});

describe("Kling ingest", () => {
  it("ships only accepted clips, under their app names", () => {
    const plan = ingestPlan(klingClips);
    const names = plan.map((p) => p.name).sort();
    expect(names).toEqual(
      [
        "concern",
        "curiosity",
        "excitement",
        "frustration",
        "heartbeat",
        "idle",
        "love",
        "peek",
        "playful",
        "sadness",
        "shyness",
        "spin",
        "stress",
        "supportive",
        "sway",
        "talking",
      ].sort(),
    );
    for (const name of names) expect(EMOTES).toContain(name);
    expect(plan.find((p) => p.name === "talking")?.file).toBe("23_speaking.mp4");
    expect(plan.find((p) => p.name === "playful")?.file).toBe("07_sway_2.mp4");
  });

  it("never ingests rejected, missing or unmapped clips", () => {
    const plan = ingestPlan({
      clips: [
        { id: "air_kiss", file: "18_air_kiss__rejected.mp4", verdict: "reject" },
        { id: "love", file: null, verdict: "accept" },
        { id: "entry", file: "02_entry.mp4", verdict: "accept" },
        { id: "peek", file: "04_peek.mp4", verdict: "accept" },
      ],
    });
    expect(plan).toEqual([{ name: "peek", file: "04_peek.mp4", loop: false }]);
    expect(KLING_NAMES).not.toHaveProperty("entry");
  });
});

describe("emote picker (QA)", () => {
  it("shows on previews, locally only on request, never on production", () => {
    expect(emotePickerEnabled("preview", "")).toBe(true);
    expect(emotePickerEnabled("local", "?debug=emotes")).toBe(true);
    expect(emotePickerEnabled("local", "")).toBe(false);
    expect(emotePickerEnabled("production", "?debug=emotes")).toBe(false);
    expect(emotePickerEnabled(undefined, "?debug=emotes")).toBe(false);
  });
});

describe("idle watch", () => {
  const t0 = 1_000_000;

  it("checks in once after ~3 min, until the user interacts", () => {
    let state = resetIdle(t0);
    expect(idleStep(state, t0 + CHECK_IN_MS - 1).action).toBeNull();
    const checkIn = idleStep(state, t0 + CHECK_IN_MS);
    expect(checkIn.action).toBe("check-in");
    state = checkIn.state;
    // Her own speech holds the silence but does not re-arm the check-in.
    state = holdIdle(state, t0 + CHECK_IN_MS + 5_000);
    expect(idleStep(state, t0 + CHECK_IN_MS * 3).action).toBeNull();
    // The user interacts: armed again.
    state = resetIdle(t0 + CHECK_IN_MS * 3);
    expect(idleStep(state, t0 + CHECK_IN_MS * 4).action).toBe("check-in");
  });

  it("picks a Korean check-in line", () => {
    expect(CHECK_IN_LINES).toContain(pickCheckIn(() => 0));
    expect(CHECK_IN_LINES).toContain(pickCheckIn(() => 0.999999));
    expect(pickCheckIn(() => 0.99)).toMatch(/부장님|자기야/);
  });
});

describe("view mode", () => {
  it("defaults to the avatar on phones, the HUD elsewhere, unless overridden", () => {
    expect(resolveView(null, true)).toBe("avatar");
    expect(resolveView(null, false)).toBe("hud");
    expect(resolveView("hud", true)).toBe("hud");
    expect(resolveView("avatar", false)).toBe("avatar");
    expect(isViewMode("avatar")).toBe(true);
    expect(isViewMode("desktop")).toBe(false);
  });

  it("computes how long the user was away", () => {
    expect(awayMsFrom(null, 5000)).toBeUndefined();
    expect(awayMsFrom("garbage", 5000)).toBeUndefined();
    expect(awayMsFrom("9000", 5000)).toBeUndefined();
    expect(awayMsFrom("1000", 5000)).toBe(4000);
  });
});
