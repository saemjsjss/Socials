// GET /api/hangeul/snapshot?cursor= : one page of the full Hangeul dump for a
// device's first sync (spec §5, §6). Records and chunks, vectors as base64
// little-endian float32; `max_seq` is where the device's /changes start.
// Pages are cut to ~3 MB (Vercel's response cap is 4.5 MB); follow `next`
// until it is null.

import { hangeulFailure, hangeulGate } from "@/lib/hangeul/http";
import { readSnapshotPage } from "@/lib/hangeul/store";
import { EMBEDDING_DIMENSIONS } from "@/lib/hangeul/vectors";
import { jsonResponse } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function GET(req: Request): Promise<Response> {
  const denied = hangeulGate(req);
  if (denied) return denied;
  const cursor = new URL(req.url).searchParams.get("cursor") || null;
  try {
    const page = await readSnapshotPage(cursor, { signal: req.signal });
    return jsonResponse({ ...page, vector: { encoding: "base64-float32le", dimensions: EMBEDDING_DIMENSIONS } });
  } catch (error) {
    return hangeulFailure(error, "snapshot");
  }
}
