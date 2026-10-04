// Types for kling.mjs (the ingest script is plain Node; the tests are TypeScript).

export const KLING_NAMES: Record<string, string>;
export const CLIP_VERSION: string;

export function ingestPlan(clipsJson: {
  clips: { id: string; file: string | null; verdict: string }[];
}): { name: string; file: string; loop: boolean }[];
