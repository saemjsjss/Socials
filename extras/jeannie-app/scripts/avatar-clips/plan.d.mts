// Types for plan.mjs (the build script is plain Node; the tests are TypeScript).

export const FPS: number;
export const WIDTH: number;
export const HEIGHT: number;

export interface Step {
  kind: "video" | "image";
  src: string;
  /** Frames the step is fully opaque. */
  hold: number;
  /** Source offset in frames (video only). */
  mediaStart?: number;
}

export interface Layer extends Step {
  start: number;
  end: number;
  fadeIn: number;
}

export interface Plan {
  layers: Layer[];
  total: number;
}

export function toFrames(seconds: number, fps?: number): number;
export function planSequence(steps: Step[], fadeFrames: number): Plan;
export function planLoop(options: { cutFrame: number; fadeFrames: number; src: string; still: string }): Plan;
export function compositionHtml(options: {
  id?: string;
  plan: Plan;
  backdrop: string;
  fps?: number;
  width?: number;
  height?: number;
}): string;
export function rgbToHex(rgb: [number, number, number] | number[]): string;
export function manifestEntry(
  emote: string,
  clip: { duration: number; loop: boolean; placeholder: boolean },
): { src: string; poster: string; duration: number; loop: boolean; placeholder: boolean };
