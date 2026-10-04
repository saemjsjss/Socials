import { getEnv } from "@/lib/env";
import { handleTelegramUpdate } from "@/lib/telegram";
import { errorResponse, jsonResponse, timingSafeEqual } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const SECRET_HEADER = "x-telegram-bot-api-secret-token";

export async function POST(req: Request): Promise<Response> {
  const { webhookSecret, botToken } = getEnv().telegram;
  if (!botToken) return errorResponse(503, "telegram_not_configured", "TELEGRAM_BOT_TOKEN is not configured.");
  // Fail closed: without the secret anyone could post forged updates, including
  // ones that claim to come from the admin chat (admin trust is chat.id).
  if (!webhookSecret) {
    return errorResponse(
      503,
      "telegram_webhook_secret_required",
      "TELEGRAM_WEBHOOK_SECRET is not configured, so webhook updates are refused.",
    );
  }
  if (!timingSafeEqual(req.headers.get(SECRET_HEADER) ?? "", webhookSecret)) {
    return errorResponse(401, "invalid_webhook_secret", "Invalid Telegram webhook secret.");
  }

  let update: unknown;
  try {
    update = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }

  try {
    await handleTelegramUpdate(update);
  } catch (error) {
    // Still 200: a non-2xx makes Telegram redeliver the same update indefinitely.
    console.error(`[telegram] webhook handling failed: ${error instanceof Error ? error.name : "Error"}`);
  }
  return jsonResponse({ ok: true });
}
