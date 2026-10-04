// GET /api/hangeul/changes?since=<seq>&limit=<1-1000> : the change log after a
// device's cursor (spec D13, D14), with each upsert's current record and
// chunks (base64 vectors). A delete carries only kind, key, op and changed_at.
// Call again with since=next_seq while `more` is true.

import { hangeulFailure, hangeulGate } from "@/lib/hangeul/http";
import { readChangesSince } from "@/lib/hangeul/store";
import { EMBEDDING_DIMENSIONS } from "@/lib/hangeul/vectors";
import { errorResponse, jsonResponse } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const DEFAULT_LIMIT = 200;

function integer(value: string | null, fallback: number): number | null {
  if (value === null || value === "") return fallback;
  return /^\d{1,15}$/.test(value) ? Number(value) : null;
}

export async function GET(req: Request): Promise<Response> {
  const denied = hangeulGate(req);
  if (denied) return denied;
  const params = new URL(req.url).searchParams;
  if (params.get("since") === null) return errorResponse(400, "invalid_request", "since: missing (the device's last seq, 0 for none)");
  const since = integer(params.get("since"), 0);
  if (since === null) return errorResponse(400, "invalid_request", "since: expected a whole number");
  const limit = integer(params.get("limit"), DEFAULT_LIMIT);
  if (limit === null || limit < 1 || limit > 1_000) return errorResponse(400, "invalid_request", "limit: expected 1 to 1000");
  try {
    const page = await readChangesSince(since, limit, { signal: req.signal });
    return jsonResponse({ ...page, vector: { encoding: "base64-float32le", dimensions: EMBEDDING_DIMENSIONS } });
  } catch (error) {
    return hangeulFailure(error, "changes");
  }
}
