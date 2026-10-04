// Telegram keeps a pending audit in Supabase, because each update is a single message.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OrchestratorContext, OrchestratorInput } from "@/lib/agents/orchestrator";

const store = vi.hoisted(() => ({
  pending: null as string | null,
  saved: [] as (string | null)[],
  decisions: [] as { decision: string; items: string[] }[],
}));

vi.mock("@/lib/memory/store", () => ({
  getPendingAudit: vi.fn(async () => store.pending),
  savePendingAudit: vi.fn(async (_key: string, pending: string | null) => {
    store.saved.push(pending);
  }),
  logAuditDecision: vi.fn(async (_key: string, decision: string, items: string[]) => {
    store.decisions.push({ decision, items });
  }),
  recallMemory: vi.fn(async () => ""),
}));

const orchestrated: { input: OrchestratorInput; ctx: OrchestratorContext }[] = [];
let reply = { agent: "core", text: "Hello, sir." };

vi.mock("@/lib/agents/orchestrator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/agents/orchestrator")>();
  return {
    ...actual,
    runOrchestratorToText: vi.fn(async (input: OrchestratorInput, ctx: OrchestratorContext) => {
      orchestrated.push({ input, ctx });
      if (input.messages.length === 2) ctx.onAuditDecision?.("approved", ["Fix row 4"]);
      return { ...reply, lang: "en", provider: "deepseek", honorific: "부장님", sources: [] };
    }),
  };
});

const { handleTelegramUpdate } = await import("@/lib/telegram");
const { APPROVAL_REQUEST_LINE } = await import("@/lib/agents/audit-flow");

const ADMIN = 42;
const update = (text: string) => ({
  update_id: 1,
  message: { message_id: 1, chat: { id: ADMIN, type: "private" }, from: { id: ADMIN, is_bot: false }, text },
});

beforeEach(() => {
  vi.stubEnv("TELEGRAM_BOT_TOKEN", "123:token");
  vi.stubEnv("TELEGRAM_ADMIN_CHAT_ID", String(ADMIN));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true, result: {} }))));
  store.pending = null;
  store.saved = [];
  store.decisions = [];
  orchestrated.length = 0;
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Telegram audit approval", () => {
  it("saves an audit reply as pending", async () => {
    reply = { agent: "audit", text: `■ 점검 결과 (Audit)\n1. Fix row 4\n${APPROVAL_REQUEST_LINE}` };
    await handleTelegramUpdate(update("check my mistakes: 3 x 4 = 13"));
    expect(orchestrated[0].input.messages).toEqual([{ role: "user", content: "check my mistakes: 3 x 4 = 13" }]);
    expect(store.saved).toEqual([reply.text]);
  });

  it("replays the pending audit before an approval, logs the decision and clears the state", async () => {
    store.pending = `■ 점검 결과 (Audit)\n1. Fix row 4\n${APPROVAL_REQUEST_LINE}`;
    reply = { agent: "audit", text: "Understood, sir. Proceeding with the approved recommendations." };
    await handleTelegramUpdate(update("approve"));
    expect(orchestrated[0].input.messages).toEqual([
      { role: "assistant", content: store.pending },
      { role: "user", content: "approve" },
    ]);
    expect(store.decisions).toEqual([{ decision: "approved", items: ["Fix row 4"] }]);
    expect(store.saved).toEqual([null]);
  });

  it("does not look up state for ordinary messages, and any other reply ends the wait", async () => {
    store.pending = "■ 승인 요청";
    reply = { agent: "core", text: "It's sunny, sir." };
    await handleTelegramUpdate(update("What's the weather like?"));
    expect(orchestrated[0].input.messages).toHaveLength(1);
    expect(store.saved).toEqual([null]);
  });

  it("strips the avatar's emote tag before sending and before saving the audit", async () => {
    const audit = `■ 점검 결과 (Audit)\n1. Fix row 4\n${APPROVAL_REQUEST_LINE}`;
    reply = { agent: "audit", text: `[emote:concern] ${audit}` };
    await handleTelegramUpdate(update("check my mistakes: 3 x 4 = 13"));
    expect(store.saved).toEqual([audit]);
    const calls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/sendMessage"));
    const sent = calls.map(([, init]) => (JSON.parse(String(init?.body)) as { text: string }).text);
    expect(sent).toEqual([audit]);
  });
});
