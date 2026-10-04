// Pure timing and markup helpers for the avatar clip pipeline (no I/O, unit tested).
//
// Every clip is a stack of layers (video or still) played in order. Each layer after the
// first fades in over `fadeFrames` on top of the one before, so the whole pipeline is
// expressed as a list of steps in frames. Frame-exact maths matters here: the loop seam
// and the "start and end on the idle first frame" rule are checked by SSIM afterwards.

export const FPS = 24;
export const WIDTH = 720;
export const HEIGHT = 1280;

/** Seconds -> nearest whole frame. */
export function toFrames(seconds, fps = FPS) {
  return Math.round(seconds * fps);
}

/**
 * Lay out a crossfaded sequence.
 *
 * `steps` are `{ hold, ...anything }` where `hold` is the number of frames the step is fully
 * opaque. Step 0 is opaque from frame 0; every later step starts at `start` and reaches full
 * opacity `fadeFrames - 1` frames later (alpha (k+1)/fadeFrames on its k-th frame), so its
 * first opaque frame is also the first frame the step below it can be dropped.
 *
 * Returns the steps with `start`/`end` (frames, end exclusive), `fadeIn` (frames, 0 for the
 * first step) and the total frame count.
 */
export function planSequence(steps, fadeFrames) {
  if (steps.length === 0) throw new Error("planSequence: no steps");
  if (!Number.isInteger(fadeFrames) || fadeFrames < 1) throw new Error("planSequence: fadeFrames must be a positive integer");
  const laid = [];
  let start = 0;
  steps.forEach((step, i) => {
    if (!Number.isInteger(step.hold) || step.hold < 1) throw new Error(`planSequence: step ${i} needs a positive integer hold`);
    const fadeIn = i === 0 ? 0 : fadeFrames;
    laid.push({ ...step, start, fadeIn });
    start += (i === 0 ? 0 : fadeFrames - 1) + step.hold;
  });
  const total = start;
  // A layer stays until the one above it is fully opaque.
  laid.forEach((layer, i) => {
    const next = laid[i + 1];
    layer.end = next ? next.start + fadeFrames - 1 : total;
  });
  return { layers: laid, total };
}

/**
 * Seamless loop that starts on source frame 0 (the neutral pose the other clips share):
 * play [0, cut) and dissolve the last `fadeFrames` into a still of frame 0 (`still`). The
 * still never reaches full opacity, so the final frame is not a duplicate of the first
 * and the restart continues the dissolve instead of pausing on it.
 */
export function planLoop({ cutFrame, fadeFrames, src, still }) {
  if (cutFrame < fadeFrames * 3) throw new Error("planLoop: cut is too short for the fade");
  const plan = planSequence(
    [
      { kind: "video", src, mediaStart: 0, hold: cutFrame - fadeFrames + 1 },
      { kind: "image", src: still, hold: 1 },
    ],
    fadeFrames,
  );
  const total = plan.total - 1;
  return { layers: plan.layers.map((layer) => ({ ...layer, end: Math.min(layer.end, total) })), total };
}

const floor6 = (x) => Math.floor(x * 1e6 + 1e-6) / 1e6;
const ceil6 = (x) => Math.ceil(x * 1e6 - 1e-6) / 1e6;

/**
 * HyperFrames composition for a planned sequence. Clip starts round down and durations up
 * to the microsecond, so a layer is always live on the frame it is meant to appear.
 */
export function compositionHtml({ id = "main", plan, backdrop, fps = FPS, width = WIDTH, height = HEIGHT }) {
  const sec = (frames) => frames / fps;
  const duration = ceil6(sec(plan.total));
  const layers = plan.layers.map((layer, i) => {
    const lid = `${id}-l${i}`;
    const start = floor6(sec(layer.start));
    const span = ceil6(sec(layer.end - layer.start));
    const timing = `data-start="${start}" data-duration="${span}" data-track-index="${i}"`;
    const media =
      layer.kind === "video"
        ? `<video id="${lid}-v" src="${layer.src}" ${timing} data-media-start="${floor6(sec(layer.mediaStart ?? 0))}" muted playsinline></video>`
        : `<img id="${lid}-i" class="clip" src="${layer.src}" alt="" ${timing} />`;
    return `    <div class="layer" id="${lid}">${media}</div>`;
  });
  // Opacity ramps live on the wrapper divs, never on the timed media (HyperFrames owns clip visibility).
  const tweens = plan.layers
    .slice(1)
    .map((layer, j) => {
      const at = floor6(sec(layer.start - 1));
      return `  tl.fromTo("#${id}-l${j + 1}", { opacity: 0 }, { opacity: 1, duration: ${sec(layer.fadeIn)}, ease: "none" }, ${at});`;
    })
    .join("\n");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=${width}, height=${height}" />
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    body { margin: 0; background: ${backdrop}; }
    #root { position: relative; width: 100%; height: 100%; overflow: hidden; background: ${backdrop}; }
    .layer { position: absolute; inset: 0; }
    .layer video, .layer img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
  </style>
</head>
<body>
  <div id="root" data-composition-id="${id}" data-start="0" data-width="${width}" data-height="${height}" data-duration="${duration}" data-fps="${fps}">
${layers.join("\n")}
  </div>
  <script>
  const tl = gsap.timeline({ paused: true });
${plan.layers
  .slice(1)
  .map((_, j) => `  tl.set("#${id}-l${j + 1}", { opacity: 0 }, 0);`)
  .join("\n")}
${tweens}
  window.__timelines["${id}"] = tl;
  </script>
</body>
</html>
`;
}

/** "#rrggbb" from 0-255 channels. */
export function rgbToHex([r, g, b]) {
  return `#${[r, g, b].map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join("")}`;
}

/** public/avatar/manifest.json entry for one emote. */
export function manifestEntry(emote, { duration, loop, placeholder }) {
  return {
    src: `/avatar/${emote}.mp4`,
    poster: `/avatar/${emote}.jpg`,
    duration: Math.round(duration * 1000) / 1000,
    loop,
    placeholder,
  };
}
