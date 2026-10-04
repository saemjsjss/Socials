// POST /api/tts: Jeannie's voice as audio/mpeg. 503 tells the HUD to use browser speech.

import { z } from "zod";
import { requireAccess } from "@/lib/auth";
import { synthesizeSpeech, TtsInputError, TtsUnavailableError } from "@/lib/agents/tts-engine";
import { TTS_ENGINE_HEADER } from "@/lib/types";
import { errorResponse } from "@/lib/utils";

export const runtime = "nodejs"; // Edge TTS needs the `ws` package
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const TtsRequestSchema = z.object({
  text: z.string().trim().min(1, "text is empty").max(2000, "text exceeds 2000 characters"),
  lang: z.enum(["en", "ko"]).optional(),
});

export async function POST(req: Request): Promise<Response> {
  const denied = requireAccess(req);
  if (denied) return denied;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }

  const parsed = TtsRequestSchema.safeParse(body);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
    return errorResponse(400, "invalid_request", `${where}${issue?.message ?? "Invalid request body."}`);
  }

  try {
    const result = await synthesizeSpeech({ ...parsed.data, signal: req.signal });
    return new Response(result.audio, {
      status: 200,
      headers: {
        "content-type": result.contentType,
        "content-length": String(result.audio.byteLength),
        "cache-control": "no-store",
        [TTS_ENGINE_HEADER]: result.engine,
      },
    });
  } catch (error) {
    if (error instanceof TtsInputError) {
      return errorResponse(400, "nothing_to_speak", error.message);
    }
    if (error instanceof TtsUnavailableError) {
      console.warn(`[tts] ${error.message}`);
      return errorResponse(503, "tts_unavailable", error.message);
    }
    console.error("[tts] unexpected failure", error instanceof Error ? error.name : typeof error);
    return errorResponse(503, "tts_unavailable", "Voice synthesis failed. Use the browser voice.");
  }
}
