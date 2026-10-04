// GET /api/session?awayMs=<ms>: Jeannie's opening line for a new session. A
// short Korean greeting written by the model for the operator's local time of
// day, how long they were away and something from memory, addressed as 부장님
// or 자기야; the template greeting when no model answers within ~4 s.

import { buildSessionGreeting, parseAwayMs } from "@/lib/agents/greeting";
import { isTrustedRequest, requireAccess } from "@/lib/auth";
import { jsonResponse } from "@/lib/utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const denied = requireAccess(req);
  if (denied) return denied;
  const awayMs = parseAwayMs(new URL(req.url).searchParams.get("awayMs"));
  const body = await buildSessionGreeting({ awayMs, trusted: isTrustedRequest(req), signal: req.signal });
  return jsonResponse(body);
}
