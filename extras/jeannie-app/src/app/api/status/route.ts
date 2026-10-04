import { hasValidAccessKey } from "@/lib/auth";
import { configuredSearchProviders, configuredTtsEngines, getEnv } from "@/lib/env";
import { countRecords, lastRunPerJob, readRuns } from "@/lib/hangeul/store";
import type { SystemStatus } from "@/lib/types";
import { jsonResponse } from "@/lib/utils";

export const runtime = "edge";
export const dynamic = "force-dynamic";

/** The Hangeul volume must never hold up the HUD's first call. */
const HANGEUL_STATUS_TIMEOUT_MS = 1_500;

// Deliberately open (no access key): the HUD calls this first to learn whether
// it must ask for a key. Only booleans and model names leave the server; the
// Hangeul record count and last runs are added only for a caller with the key.
export async function GET(req: Request): Promise<Response> {
  const env = getEnv();
  const online = env.llm.provider !== "none";
  const status: SystemStatus = {
    app: env.appName,
    voiceName: env.voiceName,
    accessKeyRequired: Boolean(env.accessKey),
    llm: {
      provider: env.llm.provider,
      model: online ? env.llm.model : null,
      visionProvider: env.llm.visionProvider,
      visionModel: env.llm.visionProvider !== "none" ? env.llm.visionModel : null,
    },
    memory: { configured: env.memory.enabled },
    search: { providers: configuredSearchProviders(env) },
    voice: { engines: configuredTtsEngines(env) },
    telegram: { configured: Boolean(env.telegram.botToken) },
    hangeul: { configured: env.hangeul.enabled, records: null, lastRuns: null },
    timeZone: env.timeZone,
    time: new Date().toISOString(),
  };
  if (env.hangeul.enabled && hasValidAccessKey(req)) {
    const options = { signal: req.signal, timeoutMs: HANGEUL_STATUS_TIMEOUT_MS };
    const [records, runs] = await Promise.all([
      countRecords(options).catch(() => null),
      readRuns([], options).catch(() => null),
    ]);
    status.hangeul.records = records;
    status.hangeul.lastRuns = runs ? lastRunPerJob(runs) : null;
  }
  return jsonResponse(status);
}
