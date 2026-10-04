// GET /api/hangeul/runs : Hangeul BOT's recent finished runs (job, times,
// status, counts.by_kind, failed page reads), plus the newest run of every kind
// none of them read (the backfill-only kinds). A device syncs these with its
// copy (ticket 7), so an answer built from IndexedDB carries the same "as of"
// line as the server's: a record's read_at only moves when its content changes,
// so the time a kind was last confirmed comes from the runs. No student data.

import { hangeulFailure, hangeulGate } from "@/lib/hangeul/http";
import { readRuns } from "@/lib/hangeul/store";
import { HG_KINDS } from "@/lib/hangeul/types";
import { jsonResponse } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const denied = hangeulGate(req);
  if (denied) return denied;
  try {
    return jsonResponse({ runs: await readRuns(HG_KINDS, { signal: req.signal }) });
  } catch (error) {
    return hangeulFailure(error, "runs");
  }
}
