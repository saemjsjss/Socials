import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { maxDuration, POST as webhook } from "@/app/api/telegram/webhook/route";
import { resetSearchState } from "@/lib/agents/search-agent";
import {
  downloadFileAsDataUrl,
  handleTelegramUpdate,
  MAX_UPDATE_TEXT,
  notifyAdmin,
  sendMessage,
  splitMessage,
  TELEGRAM_CHUNK_SIZE,
  UPDATE_DEADLINE_MS,
} from "@/lib/telegram";

const TOKEN = "123456:SECRET-bot-token";
const ADMIN = 42;
const STRANGER = 7;
const FAILED = "Something went wrong on my side. Please try again.";
const LOCKED = "private until TELEGRAM_ADMIN_CHAT_ID is set";

interface ApiCall {
  method: string;
  payload: Record<string, unknown>;
}

/** Rejects like fetch does once the request's signal aborts. */
function hangUntilAborted(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((_resolve, reject) => {
    const fail = () => reject(signal?.reason ?? new DOMException("aborted", "AbortError"));
    if (signal?.aborted) fail();
    else signal?.addEventListener("abort", fail, { once: true });
  });
}

const sseChunk = (content: string) =>
  `data: ${JSON.stringify({ id: "c1", object: "chat.completion.chunk", created: 1, model: "gpt-4o", choices: [{ index: 0, delta: { role: "assistant", content }, finish_reason: null }] })}\n\n`;

/** OpenAI streaming answer: `first` right away, then either the rest or silence until the signal aborts. */
function openAiStream(first: string, signal: AbortSignal | null | undefined, finish: boolean): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(sseChunk(first)));
      if (finish) {
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
        return;
      }
      const fail = () => controller.error(signal?.reason ?? new DOMException("aborted", "AbortError"));
      if (signal?.aborted) fail();
      else signal?.addEventListener("abort", fail, { once: true });
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

interface FakeOptions {
  fileSize?: number;
  filePath?: string;
  fileBytes?: number;
  /** getFile never answers until the request is aborted. */
  getFileHangs?: boolean;
  /** getFile answers ok: false. */
  getFileFails?: boolean;
  /** OpenAI chat completions: "hang" never answers, "partial" streams one chunk then stalls, "answer" completes. */
  openai?: "hang" | "partial" | "answer";
}

/** Fake Telegram (plus DuckDuckGo and OpenAI) backend; records Bot API calls. */
function fakeTelegram(options: FakeOptions = {}) {
  const calls: ApiCall[] = [];
  const other: string[] = [];
  const openaiRequests: { body: string; signal: AbortSignal | null | undefined }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input);
    const api = /^https:\/\/api\.telegram\.org\/bot([^/]+)\/(\w+)$/.exec(url);
    if (api) {
      expect(api[1]).toBe(TOKEN);
      const payload = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      calls.push({ method: api[2], payload });
      if (api[2] === "getFile") {
        if (options.getFileHangs) return hangUntilAborted(init?.signal);
        if (options.getFileFails) return Response.json({ ok: false, description: "file is too big" }, { status: 400 });
        return Response.json({ ok: true, result: { file_path: options.filePath ?? "photos/file_9.jpg", file_size: options.fileSize ?? 2048 } });
      }
      return Response.json({ ok: true, result: api[2] === "sendMessage" ? { message_id: calls.length } : true });
    }
    if (url.startsWith(`https://api.telegram.org/file/bot${TOKEN}/`)) {
      return new Response(new Uint8Array(options.fileBytes ?? 16).fill(0xff), { status: 200 });
    }
    other.push(url);
    if (url.startsWith("https://api.openai.com/")) {
      openaiRequests.push({ body: String(init?.body ?? ""), signal: init?.signal });
      if (options.openai === "hang") return hangUntilAborted(init?.signal);
      return openAiStream("Once upon a time", init?.signal, options.openai !== "partial");
    }
    if (url.startsWith("https://api.duckduckgo.com/")) {
      return new Response(
        JSON.stringify({ Heading: "Seoul", AbstractText: "Capital of Korea.", AbstractURL: "https://en.wikipedia.org/wiki/Seoul", RelatedTopics: [] }),
        { status: 202 },
      );
    }
    return new Response("{}", { status: 500 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const sent = () => calls.filter((c) => c.method === "sendMessage").map((c) => c.payload);
  return { calls, other, sent, fetchMock, openaiRequests };
}

function textUpdate(chatId: number, text: string, extra: Record<string, unknown> = {}) {
  return {
    update_id: 1,
    message: { message_id: 10, chat: { id: chatId, type: "private" }, from: { id: chatId, is_bot: false }, text, ...extra },
  };
}

beforeEach(() => {
  resetSearchState();
  vi.stubEnv("TELEGRAM_BOT_TOKEN", TOKEN);
  vi.stubEnv("TELEGRAM_ADMIN_CHAT_ID", String(ADMIN));
  vi.stubEnv("TELEGRAM_WEBHOOK_SECRET", "");
  for (const name of ["OPENAI_API_KEY", "OLLAMA_BASE_URL", "LLM_PROVIDER", "TAVILY_API_KEY", "GOOGLE_CSE_API_KEY", "GOOGLE_CSE_ID"]) {
    vi.stubEnv(name, "");
  }
  for (const name of ["MOCK_MODE", "JEANNIE_ACCESS_KEY"]) vi.stubEnv(name, "");
  for (const name of ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "NEXT_PUBLIC_SUPABASE_URL"]) {
    vi.stubEnv(name, "");
  }
  // Unset, not blank: @ai-sdk/openai reads a blank OPENAI_BASE_URL itself and rejects it.
  for (const name of ["OPENAI_BASE_URL", "DEFAULT_MODEL", "VERCEL"]) vi.stubEnv(name, undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("splitMessage", () => {
  it("keeps short text whole and splits long text at line breaks under the limit", () => {
    expect(splitMessage("hello")).toEqual(["hello"]);
    const paragraph = `${"word ".repeat(700).trim()}\n`;
    const chunks = splitMessage(paragraph.repeat(4));
    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) expect(chunk.length).toBeLessThanOrEqual(TELEGRAM_CHUNK_SIZE);
    const same = chunks.join(" ").replace(/\s+/g, " ") === paragraph.repeat(4).replace(/\s+/g, " ").trim();
    expect(same).toBe(true);
  });

  it("hard-splits text without spaces and never breaks a surrogate pair", () => {
    const text = `${"a".repeat(TELEGRAM_CHUNK_SIZE - 1)}😀${"b".repeat(10)}`;
    const chunks = splitMessage(text);
    expect(chunks[0]).toBe("a".repeat(TELEGRAM_CHUNK_SIZE - 1));
    expect(chunks[1].startsWith("😀")).toBe(true);
  });
});

describe("Bot API client", () => {
  it("sends plain text (no parse_mode) in 4000-character chunks", async () => {
    const tg = fakeTelegram();
    expect(await sendMessage(ADMIN, "x".repeat(9000))).toBe(true);
    const sent = tg.sent();
    expect(sent).toHaveLength(3);
    for (const payload of sent) {
      expect(payload.chat_id).toBe(ADMIN);
      expect(payload).not.toHaveProperty("parse_mode");
      expect(String(payload.text).length).toBeLessThanOrEqual(4000);
    }
  });

  it("notifyAdmin is false without an admin chat and true when delivered", async () => {
    const tg = fakeTelegram();
    expect(await notifyAdmin("daily report")).toBe(true);
    expect(tg.sent()[0]).toMatchObject({ chat_id: String(ADMIN), text: "daily report" });

    vi.stubEnv("TELEGRAM_ADMIN_CHAT_ID", "");
    expect(await notifyAdmin("daily report")).toBe(false);
  });

  it("downloads images as data URLs and rejects files over 4 MB", async () => {
    fakeTelegram();
    expect(await downloadFileAsDataUrl("file-1")).toMatch(/^data:image\/jpeg;base64,\/\/\/\//);

    fakeTelegram({ fileSize: 5 * 1024 * 1024 });
    expect(await downloadFileAsDataUrl("file-2")).toBeNull();

    fakeTelegram({ fileSize: 0, fileBytes: 4 * 1024 * 1024 + 1 });
    expect(await downloadFileAsDataUrl("file-3")).toBeNull();

    fakeTelegram({ filePath: "documents/file.pdf" });
    expect(await downloadFileAsDataUrl("file-4")).toBeNull();
  });
});

describe("handleTelegramUpdate", () => {
  it("answers IoT commands with exactly the fixed sentence", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "Turn on the kitchen lights"));
    await handleTelegramUpdate(textUpdate(ADMIN, "거실 불 꺼줘"));
    expect(tg.sent().map((p) => p.text)).toEqual(["Yes, it is done.", "네, 처리되었습니다."]);
    expect(tg.other).toEqual([]);
  });

  it("keeps a private instance private but still answers /whoami", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(STRANGER, "Tell me a joke"));
    await handleTelegramUpdate(textUpdate(STRANGER, "/whoami"));
    const [privateReply, whoami] = tg.sent().map((p) => String(p.text));
    expect(privateReply).toContain("This Jeannie instance is private.");
    expect(whoami).toContain(`Your chat id is ${STRANGER}.`);
    expect(tg.calls.every((c) => c.payload.chat_id === STRANGER)).toBe(true);
  });

  it("stays locked until TELEGRAM_ADMIN_CHAT_ID is set: only /start, /help and /whoami are answered", async () => {
    vi.stubEnv("TELEGRAM_ADMIN_CHAT_ID", "your_chat_id"); // the .env.example placeholder counts as unset
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.example");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test");
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(STRANGER, "/whoami@JeannieBot"));
    await handleTelegramUpdate(textUpdate(STRANGER, "/start"));
    await handleTelegramUpdate(textUpdate(STRANGER, "/help"));
    const [whoami, start, help] = tg.sent().map((p) => String(p.text));
    expect(whoami).toContain(`TELEGRAM_ADMIN_CHAT_ID=${STRANGER}`);
    expect(start).toContain("I'm Jeannie");
    expect(help).toContain("/report");

    const locked = [
      textUpdate(STRANGER, "write me a poem about the sea"),
      textUpdate(STRANGER, "switch off the fan"),
      textUpdate(STRANGER, "/report"),
      textUpdate(STRANGER, "/status"),
      textUpdate(STRANGER, "/search Seoul"),
      textUpdate(STRANGER, "", { text: undefined, caption: "What is this?", photo: [{ file_id: "p", width: 90, height: 90, file_size: 1000 }] }),
    ];
    for (const update of locked) await handleTelegramUpdate(update);
    const replies = tg.sent().slice(3).map((p) => String(p.text));
    expect(replies).toHaveLength(locked.length);
    for (const reply of replies) {
      expect(reply).toContain(LOCKED);
      expect(reply).toContain("TELEGRAM_ADMIN_CHAT_ID를 설정하기 전까지");
    }
    // No model, search, portal or file download was reached.
    expect(tg.other).toEqual([]);
    expect(tg.calls.some((c) => c.method === "getFile")).toBe(false);
  });

  it("handles /start, /help, /status (no secrets) and unknown commands", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-live-secret");
    vi.stubEnv("JEANNIE_ACCESS_KEY", "access-secret");
    const tg = fakeTelegram();
    for (const text of ["/start", "/help", "/status", "/frobnicate"]) await handleTelegramUpdate(textUpdate(ADMIN, text));
    const [start, help, status, unknown] = tg.sent().map((p) => String(p.text));
    expect(start).toMatch(/^(?:좋은 (?:아침|오후|저녁)입니다|늦은 시간까지 수고 많으십니다), (?:부장님|자기야)\. /);
    expect(start).toContain("I'm Jeannie");
    expect(start).toContain("안녕하세요");
    expect(help).toContain("/report");
    expect(status).toContain("Language model: openai");
    expect(status).toContain("Admin chat: this chat");
    for (const secret of [TOKEN, "sk-live-secret", "access-secret"]) expect(status).not.toContain(secret);
    expect(unknown).toContain("/help");
  });

  it("/report reads the Hangeul data for the admin chat only, and never shows demo data", async () => {
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.example");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test");
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "/report"));
    expect(tg.other.length).toBeGreaterThan(0);
    expect(tg.other.every((url) => url.startsWith("https://proj.supabase.example/rest/v1/"))).toBe(true);
    // The fake Supabase answers 500, so the admin gets the plain reason, not a figure.
    const text = String(tg.sent()[0].text);
    expect(text).toContain("I couldn't read the Hangeul data just now (Hangeul data unreachable (HTTP 500))");
    expect(text).not.toMatch(/demo|mock/i);

    const stranger = fakeTelegram();
    await handleTelegramUpdate(textUpdate(STRANGER, "/report"));
    expect(stranger.other).toEqual([]);
    expect(String(stranger.sent()[0].text)).toContain("This Jeannie instance is private.");
  });

  it("/report says when the Hangeul data is not configured", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "/report"));
    expect(String(tg.sent()[0].text)).toContain("The Hangeul data is not configured");
    expect(tg.other).toEqual([]);
  });

  it("/status says whether the Hangeul data is connected", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "/status"));
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.example");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test");
    await handleTelegramUpdate(textUpdate(ADMIN, "/status"));
    const [off, on] = tg.sent().map((p) => String(p.text));
    expect(off).toContain("• Hangeul data: not configured\n");
    expect(on).toContain("• Hangeul data: Supabase connected\n");
    expect(on).not.toContain("sb_secret_test");
    expect(tg.other).toEqual([]);
  });

  it("/search returns numbered results and asks for a query when empty", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "/search Seoul"));
    await handleTelegramUpdate(textUpdate(ADMIN, "/search"));
    const [results, usage] = tg.sent().map((p) => String(p.text));
    expect(results).toContain("[1] Seoul — Capital of Korea. — https://en.wikipedia.org/wiki/Seoul");
    expect(usage).toContain("Usage: /search");
  });

  it("routes other text through the orchestrator and appends sources", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(textUpdate(ADMIN, "latest news about Seoul"));
    const reply = String(tg.sent()[0].text);
    expect(reply).toContain("Here's what the live web says");
    expect(reply).toContain("https://en.wikipedia.org/wiki/Seoul");
    expect(tg.calls.some((c) => c.method === "sendChatAction")).toBe(true);
  });

  it("sends the largest photo to the vision agent", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", {
        text: undefined,
        caption: "What does this say?",
        photo: [
          { file_id: "small", width: 90, height: 90, file_size: 1000 },
          { file_id: "large", width: 1280, height: 960, file_size: 200_000 },
          { file_id: "medium", width: 320, height: 240, file_size: 20_000 },
        ],
      }),
    );
    expect(tg.calls.find((c) => c.method === "getFile")?.payload.file_id).toBe("large");
    // No LLM configured, so the vision agent explains how to enable it.
    expect(String(tg.sent()[0].text)).toMatch(/vision-capable model/);
  });

  it("answers an IoT caption on an image with the fixed sentence before any lookup or download", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", {
        text: undefined,
        caption: "Turn off the lights",
        document: { file_id: "doc", mime_type: "image/png", file_size: 6_000_000 },
      }),
    );
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", { text: undefined, caption: "Turn off the lights", photo: [{ file_id: "p", width: 90, height: 90, file_size: 1000 }] }),
    );
    const failing = fakeTelegram({ getFileFails: true });
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", { text: undefined, caption: "불 꺼줘", photo: [{ file_id: "p", width: 90, height: 90, file_size: 1000 }] }),
    );
    expect(tg.sent().map((p) => p.text)).toEqual(["Yes, it is done.", "Yes, it is done."]);
    expect(failing.sent().map((p) => p.text)).toEqual(["네, 처리되었습니다."]);
    for (const fake of [tg, failing]) {
      expect(fake.calls.map((c) => c.method)).toEqual(fake === tg ? ["sendMessage", "sendMessage"] : ["sendMessage"]);
      expect(fake.other).toEqual([]);
    }
  });

  it("caps text at Telegram's 4,096-character limit before anything reads it", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    const tg = fakeTelegram({ openai: "answer" });
    const kept = `Write a haiku about ${"a".repeat(MAX_UPDATE_TEXT - 20)}`;
    expect(kept).toHaveLength(MAX_UPDATE_TEXT);
    await handleTelegramUpdate(textUpdate(ADMIN, `${kept}${"Q".repeat(50_000)}`));
    expect(tg.openaiRequests).toHaveLength(1);
    expect(tg.openaiRequests[0].body).toContain(kept);
    expect(tg.openaiRequests[0].body).not.toContain("QQQQ");
    expect(tg.sent().map((p) => p.text)).toEqual(["Once upon a time"]);
  });

  it("answers a 20,000-character whitespace attack in the admin chat quickly", async () => {
    const tg = fakeTelegram();
    const started = performance.now();
    await handleTelegramUpdate(textUpdate(ADMIN, `hangeul portal up${"\n".repeat(20_000)}.`));
    expect(performance.now() - started).toBeLessThan(500);
    expect(String(tg.sent()[0].text)).toContain("The Hangeul data isn't connected");
  });

  it("rejects photos over 4 MB without downloading", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", { text: undefined, photo: [{ file_id: "huge", width: 5000, height: 5000, file_size: 6_000_000 }] }),
    );
    expect(tg.calls.some((c) => c.method === "getFile")).toBe(false);
    expect(String(tg.sent()[0].text)).toContain("larger than 4 MB");
  });

  it("keeps the per-update deadline under the webhook's maxDuration", () => {
    expect(UPDATE_DEADLINE_MS).toBeGreaterThanOrEqual(45_000);
    expect(UPDATE_DEADLINE_MS).toBeLessThanOrEqual(maxDuration * 1000 - 10_000);
  });

  it("sends the failure text once when the model does not answer before the deadline", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    const tg = fakeTelegram({ openai: "hang" });
    const started = performance.now();
    await handleTelegramUpdate(textUpdate(ADMIN, "Write me a long bedtime story about a fox"), { deadline: AbortSignal.timeout(100) });
    expect(performance.now() - started).toBeLessThan(3_000);
    expect(tg.sent().map((p) => p.text)).toEqual([expect.stringContaining(FAILED)]);
    // The deadline reached the model request itself.
    expect(tg.openaiRequests.length).toBeGreaterThan(0);
    expect(tg.openaiRequests.every((r) => r.signal?.aborted)).toBe(true);
  });

  it("keeps a partial answer and says it was cut off at the deadline", async () => {
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    const tg = fakeTelegram({ openai: "partial" });
    await handleTelegramUpdate(textUpdate(ADMIN, "Write me a long bedtime story about a fox"), { deadline: AbortSignal.timeout(150) });
    const replies = tg.sent().map((p) => String(p.text));
    expect(replies).toHaveLength(1);
    expect(replies[0]).toMatch(/^Once upon a time\n\n\(Cut off: that took too long/);
    expect(replies[0]).not.toContain(FAILED);
  });

  it("aborts a stalled image download at the deadline and sends the failure text once", async () => {
    const tg = fakeTelegram({ getFileHangs: true });
    await handleTelegramUpdate(
      textUpdate(ADMIN, "", { text: undefined, caption: "What does this say?", photo: [{ file_id: "p", width: 90, height: 90, file_size: 1000 }] }),
      { deadline: AbortSignal.timeout(100) },
    );
    expect(tg.calls.some((c) => c.method === "getFile")).toBe(true);
    expect(tg.sent().map((p) => p.text)).toEqual([expect.stringContaining(FAILED)]);
  });

  it("ignores non-message updates and bot authors", async () => {
    const tg = fakeTelegram();
    await handleTelegramUpdate({ update_id: 5, edited_message: textUpdate(ADMIN, "turn on the tv").message });
    await handleTelegramUpdate({ update_id: 6, callback_query: { id: "x" } });
    await handleTelegramUpdate(textUpdate(ADMIN, "hi", { from: { id: 99, is_bot: true } }));
    await handleTelegramUpdate(null);
    expect(tg.fetchMock).not.toHaveBeenCalled();
  });
});

describe("webhook route", () => {
  const post = (body: unknown, headers: Record<string, string> = {}) =>
    webhook(
      new Request("http://localhost/api/telegram/webhook", {
        method: "POST",
        headers: { "content-type": "application/json", ...headers },
        body: typeof body === "string" ? body : JSON.stringify(body),
      }),
    );

  const SECRET = { "x-telegram-bot-api-secret-token": "hook-secret" };

  it.each([
    ["locally", ""],
    ["on Vercel", "1"],
  ])("refuses every update without TELEGRAM_WEBHOOK_SECRET (%s)", async (_label, vercel) => {
    vi.stubEnv("VERCEL", vercel);
    vi.stubEnv("SUPABASE_URL", "https://proj.supabase.example");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test");
    const tg = fakeTelegram();
    // A forged update claiming to come from the admin chat.
    const attempts: Record<string, string>[] = [{}, { "x-telegram-bot-api-secret-token": "anything" }];
    for (const headers of attempts) {
      const res = await post(textUpdate(ADMIN, "/report"), headers);
      expect(res.status).toBe(503);
      expect((await res.json()).code).toBe("telegram_webhook_secret_required");
    }
    expect(tg.fetchMock).not.toHaveBeenCalled();
  });

  it("checks the secret token", async () => {
    vi.stubEnv("TELEGRAM_WEBHOOK_SECRET", "hook-secret");
    const tg = fakeTelegram();
    expect((await post(textUpdate(ADMIN, "turn on the lights"))).status).toBe(401);
    expect((await post(textUpdate(ADMIN, "turn on the lights"), { "x-telegram-bot-api-secret-token": "wrong" })).status).toBe(401);
    expect(tg.fetchMock).not.toHaveBeenCalled();

    const ok = await post(textUpdate(ADMIN, "turn on the lights"), SECRET);
    expect(ok.status).toBe(200);
    expect(await ok.json()).toEqual({ ok: true });
    expect(tg.sent()[0].text).toBe("Yes, it is done.");
  });

  it("503 without a bot token, 400 on bad JSON, 200 even when handling fails", async () => {
    vi.stubEnv("TELEGRAM_WEBHOOK_SECRET", "hook-secret");
    vi.stubEnv("TELEGRAM_BOT_TOKEN", "");
    const missing = await post(textUpdate(ADMIN, "hi"), SECRET);
    expect(missing.status).toBe(503);
    expect((await missing.json()).code).toBe("telegram_not_configured");

    vi.stubEnv("TELEGRAM_BOT_TOKEN", TOKEN);
    fakeTelegram();
    expect((await post("{not json", SECRET)).status).toBe(400);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("telegram down");
      }),
    );
    const res = await post(textUpdate(ADMIN, "turn on the lights"), SECRET);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});
