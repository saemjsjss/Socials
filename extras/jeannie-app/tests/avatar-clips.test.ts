import { describe, expect, it } from "vitest";
import { compositionHtml, manifestEntry, planLoop, planSequence, rgbToHex, toFrames } from "../scripts/avatar-clips/plan.mjs";

describe("planSequence", () => {
  it("lays steps out so each fades in over the one below", () => {
    const plan = planSequence(
      [
        { kind: "video", src: "idle.mp4", hold: 10 },
        { kind: "image", src: "a.png", hold: 5 },
        { kind: "image", src: "b.png", hold: 3 },
      ],
      6,
    );
    expect(plan.layers.map((l) => [l.start, l.end, l.fadeIn])).toEqual([
      [0, 15, 0], // under a until a is opaque (10 + 5)
      [10, 25, 6], // a opaque 15..19, b starts at 20 and is opaque at 25
      [20, 28, 6],
    ]);
    expect(plan.total).toBe(28);
  });

  it("rejects bad input", () => {
    expect(() => planSequence([], 6)).toThrow();
    expect(() => planSequence([{ kind: "image", src: "a", hold: 0 }], 6)).toThrow();
    expect(() => planSequence([{ kind: "image", src: "a", hold: 1 }], 0)).toThrow();
  });
});

describe("planLoop", () => {
  it("plays [0, cut) and dissolves the tail into the still without ever reaching it", () => {
    const plan = planLoop({ cutFrame: 120, fadeFrames: 12, src: "idle.mp4", still: "first.png" });
    expect(plan.total).toBe(120);
    const [video, still] = plan.layers;
    expect(video).toMatchObject({ kind: "video", mediaStart: 0, start: 0, end: 120 });
    // Alpha (k+1)/12 at frame 109 + k: the last frame (119) is 11/12 and frame 0 completes the ramp.
    expect(still).toMatchObject({ kind: "image", src: "first.png", start: 109, end: 120, fadeIn: 12 });
    // The video never needs a source frame past the cut.
    expect(video.mediaStart! + video.end).toBeLessThanOrEqual(120);
  });

  it("refuses a cut shorter than the fade allows", () => {
    expect(() => planLoop({ cutFrame: 20, fadeFrames: 12, src: "a", still: "b" })).toThrow();
  });
});

describe("compositionHtml", () => {
  const html = compositionHtml({
    id: "air-kiss",
    backdrop: "#dfcaca",
    plan: planSequence(
      [
        { kind: "video", src: "idle.mp4", mediaStart: 0, hold: 10 },
        { kind: "image", src: "cell2.png", hold: 7 },
      ],
      6,
    ),
  });

  it("declares a 720x1280 24 fps root with the frame-exact duration", () => {
    expect(html).toContain('data-composition-id="air-kiss"');
    expect(html).toContain('data-width="720" data-height="1280"');
    expect(html).toContain('data-duration="0.916667"'); // 22 frames, rounded up
    expect(html).toContain('data-fps="24"');
    expect(html).toContain('window.__timelines["air-kiss"]');
  });

  it("times media on the layers and fades the wrappers, starting one frame early", () => {
    expect(html).toContain('<video id="air-kiss-l0-v" src="idle.mp4" data-start="0"');
    expect(html).toContain('data-media-start="0" muted playsinline');
    expect(html).toContain('<img id="air-kiss-l1-i" class="clip" src="cell2.png" alt="" data-start="0.416666"');
    expect(html).toContain('tl.fromTo("#air-kiss-l1", { opacity: 0 }, { opacity: 1, duration: 0.25, ease: "none" }, 0.375);');
    expect(html).not.toContain("crossorigin");
  });
});

describe("helpers", () => {
  it("converts seconds to frames", () => {
    expect(toFrames(0.25)).toBe(6);
    expect(toFrames(4.875)).toBe(117);
    expect(toFrames(1, 30)).toBe(30);
  });

  it("formats and clamps hex colours", () => {
    expect(rgbToHex([223, 202, 202])).toBe("#dfcaca");
    expect(rgbToHex([300, -4, 15.6])).toBe("#ff0010");
  });

  it("builds manifest entries", () => {
    expect(manifestEntry("air_kiss", { duration: 3.5000001, loop: false, placeholder: true })).toEqual({
      src: "/avatar/air_kiss.mp4",
      poster: "/avatar/air_kiss.jpg",
      duration: 3.5,
      loop: false,
      placeholder: true,
    });
  });
});
