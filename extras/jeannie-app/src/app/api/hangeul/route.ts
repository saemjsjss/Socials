// GET /api/hangeul : the state of the Hangeul data (what the HUD panel shows):
// how many records Hangeul BOT has published, its latest runs, and the latest
// brief report record (keys and times only, no student data). Jeannie never
// talks to the portal; the bot reads it and publishes to Supabase.

import { hangeulFailure, hangeulGate } from "@/lib/hangeul/http";
import { readDataStatus } from "@/lib/hangeul/store";
import { jsonResponse } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const denied = hangeulGate(req);
  if (denied) return denied;
  try {
    return jsonResponse(await readDataStatus({ signal: req.signal }));
  } catch (error) {
    return hangeulFailure(error, "status");
  }
}
