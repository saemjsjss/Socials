import { z } from "zod";
import { runOrchestrator } from "@/lib/agents/orchestrator";
import { hasValidAccessKey, isTrustedRequest, requireAccess } from "@/lib/auth";
import { EMBEDDING_DIMENSIONS, readEmbedding } from "@/lib/hangeul/vectors";
import { CHAT_HEADERS } from "@/lib/types";
import { dataUrlByteLength, encodeHeaderJson, errorResponse, isImageDataUrl } from "@/lib/utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

const MAX_MESSAGES = 50;
const MAX_MESSAGE_CHARS = 20_000;
// Base64 adds a third, and Vercel caps request bodies at ~4.5 MB.
const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
const MAX_SOURCES = 5;

const imageSchema = z
  .string()
  .refine(isImageDataUrl, "must be a base64 image data URL (png, jpeg, webp or gif)")
  .refine((value) => dataUrlByteLength(value) <= MAX_IMAGE_BYTES, "image is larger than 3 MB");

const messageSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string().max(MAX_MESSAGE_CHARS, `message is longer than ${MAX_MESSAGE_CHARS} characters`),
  image: imageSchema.nullish(),
});

// What the PWA computed on the device for a Hangeul question (spec §6): its vector and its own hits.
const hangeulSchema = z.object({
  embedding: z.union([z.array(z.number().finite()).length(EMBEDDING_DIMENSIONS), z.string().max(4_096)]).optional(),
  hits: z
    .array(z.object({ kind: z.string().min(1).max(40), key: z.string().min(1).max(512) }))
    .max(24, "at most 24 hits")
    .optional(),
});

const bodySchema = z
  .object({
    messages: z.array(messageSchema).min(1, "messages is empty").max(MAX_MESSAGES, `more than ${MAX_MESSAGES} messages`),
    image: imageSchema.nullish(),
    lang: z.enum(["auto", "en", "ko", "bilingual"]).optional(),
    hangeul: hangeulSchema.optional(),
  })
  .superRefine((body, ctx) => {
    const last = body.messages.at(-1);
    if (!last || last.role !== "user") {
      ctx.addIssue({ code: "custom", path: ["messages"], message: "the last message must come from the user" });
    } else if (!last.content.trim() && !last.image && !body.image) {
      ctx.addIssue({ code: "custom", path: ["messages"], message: "the last message is empty" });
    }
  });

export async function POST(req: Request): Promise<Response> {
  const denied = requireAccess(req);
  if (denied) return denied;

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }

  const parsed = bodySchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
    return errorResponse(400, "invalid_request", `${where}${issue?.message ?? "invalid request body"}`);
  }

  const { messages, image, lang, hangeul } = parsed.data;
  if (hangeul?.embedding !== undefined && readEmbedding(hangeul.embedding) === null) {
    return errorResponse(400, "invalid_request", "hangeul.embedding: expected 384 numbers or their base64 float32 form");
  }
  try {
    const result = await runOrchestrator(
      { messages, image: image ?? null, lang },
      {
        trusted: isTrustedRequest(req),
        // Student records need the access key itself (like every /api/hangeul route): never the cron bearer.
        hangeulAccess: hasValidAccessKey(req),
        signal: req.signal,
        hangeulDevice: hangeul
          ? { embedding: hangeul.embedding !== undefined ? readEmbedding(hangeul.embedding) : null, hits: hangeul.hits ?? null }
          : null,
      },
    );
    const headers = new Headers({
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      [CHAT_HEADERS.agent]: result.agent,
      [CHAT_HEADERS.lang]: result.lang,
      [CHAT_HEADERS.provider]: result.provider,
      // Header values must be ASCII; "부장님" travels URI-encoded.
      [CHAT_HEADERS.honorific]: encodeURIComponent(result.honorific),
    });
    if (result.sources.length > 0) {
      headers.set(CHAT_HEADERS.sources, encodeHeaderJson(result.sources.slice(0, MAX_SOURCES)));
    }
    return new Response(result.stream, { status: 200, headers });
  } catch (error) {
    console.error(`[chat] orchestrator failed: ${error instanceof Error ? error.name : "Error"}`);
    return errorResponse(500, "internal_error", "Jeannie hit an internal error. Please try again.");
  }
}
