// /api/memory: Jeannie's long-term memory in Supabase.
//   GET              → { documents: MemoryDocument[] }
//   POST             → store one file; JSON {name, content, pinned?} or multipart (file, pinned)
//   PATCH  ?id=      → JSON {pinned}
//   DELETE ?id=      → remove a document and its chunks
// The notes are personal, so every method needs JEANNIE_ACCESS_KEY to be set
// and presented; an open deployment cannot read or change memory.

import { z } from "zod";
import { hasValidAccessKey } from "@/lib/auth";
import { getEnv } from "@/lib/env";
import { MAX_FILE_BYTES } from "@/lib/memory/chunk";
import { deleteDocument, listDocuments, MemoryInputError, setPinned, upsertDocument } from "@/lib/memory/store";
import { MemoryError } from "@/lib/memory/supabase";
import { errorResponse, jsonResponse } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

const uploadSchema = z.object({
  name: z.string().trim().min(1, "name is empty").max(200, "name is longer than 200 characters"),
  content: z.string().max(MAX_FILE_BYTES, "file is larger than 1 MB"),
  pinned: z.boolean().optional(),
});

const pinSchema = z.object({ pinned: z.boolean() });

function gate(req: Request): Response | null {
  const env = getEnv();
  if (!env.accessKey) {
    return errorResponse(403, "access_key_not_configured", "Set JEANNIE_ACCESS_KEY to use memory: it holds personal notes.");
  }
  if (!hasValidAccessKey(req)) {
    return errorResponse(401, "access_key_required", "Access key required. Enter your Jeannie access key.");
  }
  if (!env.memory.enabled) {
    return errorResponse(503, "memory_not_configured", "Memory is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.");
  }
  return null;
}

function failure(error: unknown, action: string): Response {
  if (error instanceof MemoryInputError) {
    return jsonResponse({ error: error.message, code: "invalid_file", issues: error.issues.slice(0, 20) }, 400);
  }
  const reason = error instanceof MemoryError ? error.message : error instanceof Error ? error.name : "error";
  console.error(`[memory] ${action} failed: ${reason}`);
  // PGRST202 / 42P01: the functions or tables do not exist yet.
  if (/PGRST20[25]|42P01|42883/.test(reason)) {
    return errorResponse(503, "memory_not_migrated", "Memory tables are missing. Apply supabase/migrations to your Supabase project.");
  }
  return errorResponse(502, "memory_unavailable", "Supabase memory did not respond. Try again in a moment.");
}

function documentId(req: Request): string | null {
  return new URL(req.url).searchParams.get("id");
}

async function readUpload(req: Request): Promise<{ name: string; content: string; pinned?: boolean } | Response> {
  const declared = Number(req.headers.get("content-length") ?? "0");
  // JSON escaping and multipart framing add overhead on top of the 1 MB file cap.
  if (declared > MAX_FILE_BYTES * 2 + 16_384) return errorResponse(413, "too_large", "File is larger than 1 MB.");

  if ((req.headers.get("content-type") ?? "").toLowerCase().startsWith("multipart/form-data")) {
    let form: FormData;
    try {
      form = await req.formData();
    } catch {
      return errorResponse(400, "invalid_form", "Could not read the uploaded form.");
    }
    const file = form.get("file");
    if (!(file instanceof File)) return errorResponse(400, "invalid_request", "file: missing");
    if (file.size > MAX_FILE_BYTES) return errorResponse(413, "too_large", "File is larger than 1 MB.");
    const pinned = form.get("pinned");
    return { name: file.name, content: await file.text(), pinned: pinned === "true" || pinned === "1" };
  }

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }
  const parsed = uploadSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
    const status = issue?.path[0] === "content" && issue.code === "too_big" ? 413 : 400;
    return errorResponse(status, status === 413 ? "too_large" : "invalid_request", `${where}${issue?.message ?? "invalid request body"}`);
  }
  return parsed.data;
}

export async function GET(req: Request): Promise<Response> {
  const denied = gate(req);
  if (denied) return denied;
  try {
    return jsonResponse({ documents: await listDocuments() });
  } catch (error) {
    return failure(error, "list");
  }
}

export async function POST(req: Request): Promise<Response> {
  const denied = gate(req);
  if (denied) return denied;
  const upload = await readUpload(req);
  if (upload instanceof Response) return upload;
  if (new TextEncoder().encode(upload.content).byteLength > MAX_FILE_BYTES) {
    return errorResponse(413, "too_large", "File is larger than 1 MB.");
  }
  try {
    const result = await upsertDocument(upload);
    return jsonResponse({ document: result }, 201);
  } catch (error) {
    return failure(error, "upload");
  }
}

export async function PATCH(req: Request): Promise<Response> {
  const denied = gate(req);
  if (denied) return denied;
  const id = documentId(req);
  if (!id) return errorResponse(400, "invalid_request", "id: missing");
  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }
  const parsed = pinSchema.safeParse(raw);
  if (!parsed.success) return errorResponse(400, "invalid_request", "pinned: expected true or false");
  try {
    const found = await setPinned(id, parsed.data.pinned);
    return found ? jsonResponse({ ok: true }) : errorResponse(404, "not_found", "No such document.");
  } catch (error) {
    return failure(error, "pin");
  }
}

export async function DELETE(req: Request): Promise<Response> {
  const denied = gate(req);
  if (denied) return denied;
  const id = documentId(req);
  if (!id) return errorResponse(400, "invalid_request", "id: missing");
  try {
    const found = await deleteDocument(id);
    return found ? jsonResponse({ ok: true }) : errorResponse(404, "not_found", "No such document.");
  } catch (error) {
    return failure(error, "delete");
  }
}
