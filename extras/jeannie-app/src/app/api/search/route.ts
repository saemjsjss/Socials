import { z } from "zod";
import { webSearch } from "@/lib/agents/search-agent";
import { requireAccess } from "@/lib/auth";
import { errorResponse, jsonResponse } from "@/lib/utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

const querySchema = z.string().trim().min(1, "query is empty").max(500, "query is longer than 500 characters");
const maxResultsSchema = z.coerce.number().int().min(1).max(10);

const postSchema = z.object({
  query: querySchema,
  maxResults: maxResultsSchema.optional(),
});

function badRequest(error: z.ZodError): Response {
  const issue = error.issues[0];
  const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
  return errorResponse(400, "invalid_request", `${where}${issue?.message ?? "invalid request"}`);
}

export async function GET(req: Request): Promise<Response> {
  const denied = requireAccess(req);
  if (denied) return denied;

  const params = new URL(req.url).searchParams;
  const parsed = postSchema.safeParse({
    query: params.get("q") ?? "",
    maxResults: params.get("maxResults") ?? undefined,
  });
  if (!parsed.success) return badRequest(parsed.error);

  return search(parsed.data.query, parsed.data.maxResults, req);
}

export async function POST(req: Request): Promise<Response> {
  const denied = requireAccess(req);
  if (denied) return denied;

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return errorResponse(400, "invalid_json", "Request body must be JSON.");
  }
  const parsed = postSchema.safeParse(raw);
  if (!parsed.success) return badRequest(parsed.error);

  return search(parsed.data.query, parsed.data.maxResults, req);
}

async function search(query: string, maxResults: number | undefined, req: Request): Promise<Response> {
  try {
    return jsonResponse(await webSearch(query, { maxResults, signal: req.signal }));
  } catch (error) {
    const name = error instanceof Error ? error.name : typeof error;
    console.error(`[jeannie] /api/search failed: ${name}`);
    return errorResponse(500, "search_failed", `Live search failed (${name}).`);
  }
}
