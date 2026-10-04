// The gate and error mapping shared by the /api/hangeul routes. The data holds
// full student records (D2), so, like memory, every route needs
// JEANNIE_ACCESS_KEY to be set AND presented: an open deployment serves none of it.

import { hasValidAccessKey } from "../auth";
import { getEnv } from "../env";
import { errorResponse } from "../utils";
import { readError } from "./store";

export function hangeulGate(req: Request): Response | null {
  const env = getEnv();
  if (!env.accessKey) {
    return errorResponse(403, "access_key_not_configured", "Set JEANNIE_ACCESS_KEY to use the Hangeul data: it holds full student records.");
  }
  if (!hasValidAccessKey(req)) {
    return errorResponse(401, "access_key_required", "Access key required. Enter your Jeannie access key.");
  }
  if (!env.hangeul.enabled) {
    return errorResponse(503, "hangeul_not_configured", "Hangeul data is not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY.");
  }
  return null;
}

/** A failed read → 400 (bad cursor), 503 (not configured / not migrated) or 502. Logs the plain reason only. */
export function hangeulFailure(error: unknown, action: string): Response {
  const e = readError(error);
  console.error(`[hangeul] ${action} failed: ${e.message}`);
  if (e.message === "invalid snapshot cursor") return errorResponse(400, "invalid_cursor", "cursor is not one this server issued.");
  if (e.code === "not_migrated") {
    return errorResponse(503, "hangeul_not_migrated", "Hangeul tables are missing. Apply supabase/migrations to the Supabase project.");
  }
  if (e.code === "not_configured") return errorResponse(503, "hangeul_not_configured", "Hangeul data is not configured.");
  return errorResponse(502, "hangeul_unavailable", `${e.message}. Try again in a moment.`);
}
