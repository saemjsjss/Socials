// Optional shared-secret gate for the API routes. Runs on Edge and Node.js.

import { getEnv } from "./env";
import { ACCESS_KEY_HEADER } from "./types";
import { errorResponse, timingSafeEqual } from "./utils";

function bearer(req: Request): string | null {
  const header = req.headers.get("authorization");
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1].trim() : null;
}

/** Key presented by the caller, from `x-jeannie-key` or `Authorization: Bearer`. */
export function presentedKey(req: Request): string | null {
  return req.headers.get(ACCESS_KEY_HEADER)?.trim() || bearer(req);
}

/** True when the request carries the configured JEANNIE_ACCESS_KEY. */
export function hasValidAccessKey(req: Request): boolean {
  const { accessKey } = getEnv();
  if (!accessKey) return false;
  const key = presentedKey(req);
  return key !== null && timingSafeEqual(key, accessKey);
}

/** True when the request is Vercel Cron (`Authorization: Bearer $CRON_SECRET`). */
export function isCronRequest(req: Request): boolean {
  const { cronSecret } = getEnv();
  if (!cronSecret) return false;
  const key = bearer(req);
  return key !== null && timingSafeEqual(key, cronSecret);
}

/**
 * Gate for public API routes. Returns a 401 Response to send back, or null to
 * continue. With no JEANNIE_ACCESS_KEY configured the API is open.
 */
export function requireAccess(req: Request): Response | null {
  const { accessKey } = getEnv();
  if (!accessKey) return null;
  if (hasValidAccessKey(req)) return null;
  return errorResponse(401, "access_key_required", "Access key required. Enter your Jeannie access key.");
}

/**
 * Whether a caller may see privileged data (memory). Only callers that proved a
 * configured secret qualify; an open API (no access key configured) is never
 * trusted. The Hangeul data (full student records) needs more: the access key
 * itself (`hasValidAccessKey`), never the cron bearer.
 */
export function isTrustedRequest(req: Request): boolean {
  return hasValidAccessKey(req) || isCronRequest(req);
}
