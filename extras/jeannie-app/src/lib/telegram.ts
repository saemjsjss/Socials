// Telegram bridge: a small Bot API client plus the webhook update handler.
// Plain-text replies only (no parse_mode), so model output can never break
// Telegram's markup parser. Replies arrive with an emote tag for the avatar
// (see emote.ts), which is stripped here. The bot token lives in request URLs,
// so errors are logged by method name and status only.

import { APPROVAL_MARKER, isApprovalReply } from "./agents/audit-flow";
import { sessionGreeting } from "./agents/etiquette";
import { checkIoTQuery } from "./agents/iot-interceptor";
import { runOrchestratorToText } from "./agents/orchestrator";
import { formatSearchBriefing, webSearch, withTimeout } from "./agents/search-agent";
import { stripEmotes } from "./emote";
import { configuredSearchProviders, configuredTtsEngines, getEnv } from "./env";
import { answerHangeul } from "./hangeul/respond";
import { createHangeulStore } from "./hangeul/store";
import { getPendingAudit, logAuditDecision, savePendingAudit } from "./memory/store";
import type { ChatMessage, LangMode, SourceLink } from "./types";
import { truncate } from "./utils";

const TELEGRAM_API = "https://api.telegram.org";
const REQUEST_TIMEOUT_MS = 10_000;
const DOWNLOAD_TIMEOUT_MS = 15_000;
export const TELEGRAM_CHUNK_SIZE = 4000; // Telegram's hard limit is 4096 characters
export const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
/** Longest text or caption read from an update, Telegram's own message limit. */
export const MAX_UPDATE_TEXT = 4096;
/**
 * End-to-end budget for one update. The webhook runs under maxDuration 60, so
 * this leaves time to send the reply (or the failure line) before Vercel kills
 * the function, returns 504 and makes Telegram redeliver the update.
 */
export const UPDATE_DEADLINE_MS = 50_000;

// ─── Bot API types (only the fields we read) ────────────────────────────────

interface TelegramUser {
  id: number;
  is_bot?: boolean;
  language_code?: string;
}

interface TelegramChat {
  id: number;
  type: string;
}

interface TelegramPhotoSize {
  file_id: string;
  width: number;
  height: number;
  file_size?: number;
}

interface TelegramDocument {
  file_id: string;
  mime_type?: string;
  file_size?: number;
}

export interface TelegramMessage {
  message_id: number;
  chat: TelegramChat;
  from?: TelegramUser;
  text?: string;
  caption?: string;
  photo?: TelegramPhotoSize[];
  document?: TelegramDocument;
}

export interface TelegramUpdate {
  update_id: number;
  message?: TelegramMessage;
}

type ChatId = number | string;

// ─── Client ─────────────────────────────────────────────────────────────────

function errorName(error: unknown): string {
  return error instanceof Error ? error.name : "Error";
}

async function callApi<T>(
  method: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<{ ok: true; result: T } | { ok: false }> {
  const token = getEnv().telegram.botToken;
  if (!token) return { ok: false };
  try {
    const res = await fetch(`${TELEGRAM_API}/bot${token}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: withTimeout(REQUEST_TIMEOUT_MS, signal),
    });
    const data = (await res.json().catch(() => null)) as { ok?: boolean; result?: T; description?: string } | null;
    if (!res.ok || !data?.ok) {
      const detail = typeof data?.description === "string" ? ` (${truncate(data.description, 120)})` : "";
      console.error(`[telegram] ${method} failed: HTTP ${res.status}${detail}`);
      return { ok: false };
    }
    return { ok: true, result: data.result as T };
  } catch (error) {
    console.error(`[telegram] ${method} failed: ${errorName(error)}`);
    return { ok: false };
  }
}

/** Splits text into ≤ `size` chunks, preferring paragraph, line, then word boundaries. */
export function splitMessage(text: string, size = TELEGRAM_CHUNK_SIZE): string[] {
  const chunks: string[] = [];
  let rest = text;
  while (rest.length > size) {
    const window = rest.slice(0, size);
    let cut = window.lastIndexOf("\n\n");
    if (cut < size / 2) cut = window.lastIndexOf("\n");
    if (cut < size / 2) cut = window.lastIndexOf(" ");
    if (cut < size / 2) cut = size;
    // Never split a UTF-16 surrogate pair (emoji, rare CJK).
    const code = rest.charCodeAt(cut - 1);
    if (code >= 0xd800 && code <= 0xdbff) cut -= 1;
    chunks.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).replace(/^\s+/, "");
  }
  if (rest.trim()) chunks.push(rest.trimEnd());
  return chunks.filter((c) => c.length > 0);
}

/** Sends plain text, chunked at 4000 characters. True when every chunk was delivered. */
export async function sendMessage(chatId: ChatId, text: string): Promise<boolean> {
  const chunks = splitMessage(text);
  if (chunks.length === 0) return false;
  for (const chunk of chunks) {
    const sent = await callApi("sendMessage", {
      chat_id: chatId,
      text: chunk,
      link_preview_options: { is_disabled: true },
    });
    if (!sent.ok) return false;
  }
  return true;
}

export async function sendChatAction(chatId: ChatId, action: "typing" = "typing"): Promise<boolean> {
  return (await callApi("sendChatAction", { chat_id: chatId, action })).ok;
}

const EXTENSION_MIME: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  gif: "image/gif",
};

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** Downloads a Telegram image as a data URL; null when missing, not an image, larger than 4 MB, or aborted. */
export async function downloadFileAsDataUrl(fileId: string, signal?: AbortSignal): Promise<string | null> {
  const token = getEnv().telegram.botToken;
  if (!token) return null;
  const file = await callApi<{ file_path?: string; file_size?: number }>("getFile", { file_id: fileId }, signal);
  if (!file.ok || !file.result.file_path) return null;
  if ((file.result.file_size ?? 0) > MAX_IMAGE_BYTES) return null;

  const extension = file.result.file_path.split(".").pop()?.toLowerCase() ?? "";
  const mime = EXTENSION_MIME[extension];
  if (!mime) return null;

  try {
    const res = await fetch(`${TELEGRAM_API}/file/bot${token}/${file.result.file_path}`, {
      signal: withTimeout(DOWNLOAD_TIMEOUT_MS, signal),
    });
    if (!res.ok || Number(res.headers.get("content-length") ?? 0) > MAX_IMAGE_BYTES) {
      await res.body?.cancel().catch(() => undefined);
      return null;
    }
    const bytes = new Uint8Array(await res.arrayBuffer());
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_IMAGE_BYTES) return null;
    return `data:${mime};base64,${bytesToBase64(bytes)}`;
  } catch (error) {
    console.error(`[telegram] file download failed: ${errorName(error)}`);
    return null;
  }
}

/** Pushes a message to TELEGRAM_ADMIN_CHAT_ID. False when not configured or delivery failed. */
export async function notifyAdmin(text: string): Promise<boolean> {
  const { botToken, adminChatId } = getEnv().telegram;
  if (!botToken || !adminChatId) return false;
  return sendMessage(adminChatId, text);
}

// ─── Update handling ────────────────────────────────────────────────────────

type ReplyLang = "en" | "ko";

const bilingual = (en: string, ko: string) => `${en}\n—\n${ko}`;
const pick = (lang: ReplyLang, en: string, ko: string) => (lang === "ko" ? ko : en);

const TEXT = {
  private: bilingual("This Jeannie instance is private.", "이 Jeannie는 비공개로 운영되고 있어요."),
  locked: bilingual(
    "This Jeannie instance stays private until TELEGRAM_ADMIN_CHAT_ID is set. Send /whoami to get the id to put there.",
    "TELEGRAM_ADMIN_CHAT_ID를 설정하기 전까지 이 Jeannie는 비공개예요. /whoami 로 설정할 ID를 확인하세요.",
  ),
  start: bilingual(
    "Hi, I'm Jeannie, your bilingual AI operator. Send me a message or a photo and I'll handle it. Type /help for commands.",
    "안녕하세요, 저는 Jeannie예요. 메시지나 사진을 보내 주시면 바로 처리할게요. 명령어는 /help 로 확인하세요.",
  ),
  help: bilingual(
    [
      "Commands:",
      "/report - Hangeul daily brief (Hangeul BOT's data)",
      "/search <query> - live web search",
      "/status - Jeannie's systems",
      "/whoami - this chat's id",
      "Or just send a message or a photo.",
    ].join("\n"),
    [
      "명령어:",
      "/report - 한글 일일 브리핑 (Hangeul BOT 자료)",
      "/search <검색어> - 실시간 웹 검색",
      "/status - 시스템 상태",
      "/whoami - 이 채팅의 ID",
      "메시지나 사진을 그냥 보내셔도 돼요.",
    ].join("\n"),
  ),
  failed: bilingual("Something went wrong on my side. Please try again.", "처리 중 문제가 생겼어요. 다시 시도해 주세요."),
  cutOff: bilingual("(Cut off: that took too long. Please try again.)", "(시간이 너무 오래 걸려 여기서 멈췄어요. 다시 시도해 주세요.)"),
};

function parseCommand(text: string): { name: string; args: string } | null {
  const match = /^\/([a-z0-9_]+)(?:@[a-z0-9_]+)?(?:\s+([\s\S]*))?$/i.exec(text.trim());
  return match ? { name: match[1].toLowerCase(), args: (match[2] ?? "").trim() } : null;
}

function whoamiText(chatId: number, isAdmin: boolean, adminConfigured: boolean): string {
  const en = isAdmin
    ? `Your chat id is ${chatId}. This chat is Jeannie's admin chat.`
    : `Your chat id is ${chatId}.${adminConfigured ? "" : ` Set TELEGRAM_ADMIN_CHAT_ID=${chatId} to make this Jeannie's admin chat.`}`;
  const ko = isAdmin
    ? `이 채팅의 ID는 ${chatId}이며, Jeannie의 관리자 채팅이에요.`
    : `이 채팅의 ID는 ${chatId}예요.${adminConfigured ? "" : ` TELEGRAM_ADMIN_CHAT_ID=${chatId} 로 설정하면 관리자 채팅이 돼요.`}`;
  return bilingual(en, ko);
}

/** The daily brief from the Hangeul data, code-built only (no model): the admin chat's /report. */
async function hangeulReportText(lang: ReplyLang, deadline: AbortSignal): Promise<string> {
  const env = getEnv();
  if (!env.hangeul.enabled) {
    return pick(lang, "The Hangeul data is not configured (SUPABASE_URL, SUPABASE_SECRET_KEY).", "한글 자료가 설정되어 있지 않아요 (SUPABASE_URL, SUPABASE_SECRET_KEY).");
  }
  const answer = await answerHangeul({
    question: "Hangeul daily report",
    lang,
    readers: createHangeulStore({ signal: deadline }),
    now: new Date(),
    timeZone: env.timeZone,
    model: null,
    signal: deadline,
  });
  return stripEmotes(answer.text);
}

function statusText(isAdmin: boolean): string {
  const env = getEnv();
  const vision = env.llm.visionProvider === "none" ? "vision off" : `vision ${env.llm.visionProvider} ${env.llm.visionModel}`;
  const llm = env.llm.provider === "none" ? "offline (no model configured)" : `${env.llm.provider} (${env.llm.model}; ${vision})`;
  const lines = [
    `${env.appName} status`,
    `• Language model: ${llm}`,
    `• Live search: ${configuredSearchProviders(env).join(" → ")}`,
    `• Voice: ${configuredTtsEngines(env).join(", ")}`,
    `• Memory: ${env.memory.enabled ? "Supabase connected" : "not configured"}`,
    `• Hangeul data: ${env.hangeul.enabled ? "Supabase connected" : "not configured"}`,
    `• Admin chat: ${env.telegram.adminChatId ? (isAdmin ? "this chat" : "configured") : "not set (use /whoami)"}`,
    `• Access key: ${env.accessKey ? "required" : "not required"}`,
  ];
  return lines.join("\n");
}

function sourcesSuffix(sources: SourceLink[], text: string): string {
  if (sources.length === 0 || sources.some((s) => text.includes(s.url))) return "";
  return `\n\n${sources.map((s, i) => `[${i + 1}] ${s.title} — ${s.url}`).join("\n")}`;
}

/** Largest photo size under the 4 MB limit (Telegram lists sizes smallest first). */
function pickPhoto(photos: TelegramPhotoSize[]): TelegramPhotoSize | null {
  const fitting = photos.filter((p) => (p.file_size ?? 0) <= MAX_IMAGE_BYTES);
  return fitting.sort((a, b) => b.width * b.height - a.width * a.height)[0] ?? null;
}

function imageFileId(message: TelegramMessage): { fileId: string | null; tooLarge: boolean } | null {
  if (message.photo?.length) {
    const photo = pickPhoto(message.photo);
    return { fileId: photo?.file_id ?? null, tooLarge: !photo };
  }
  const doc = message.document;
  if (doc && /^image\/(png|jpe?g|webp|gif)$/i.test(doc.mime_type ?? "")) {
    const tooLarge = (doc.file_size ?? 0) > MAX_IMAGE_BYTES;
    return { fileId: tooLarge ? null : doc.file_id, tooLarge };
  }
  return null;
}

function isMessage(value: unknown): value is TelegramMessage {
  if (typeof value !== "object" || value === null) return false;
  const chat = (value as { chat?: unknown }).chat;
  return typeof chat === "object" && chat !== null && typeof (chat as { id?: unknown }).id === "number";
}

/** Text or caption, capped at Telegram's own limit before anything else reads it. */
function messageBody(message: TelegramMessage): string {
  const raw = typeof message.text === "string" ? message.text : typeof message.caption === "string" ? message.caption : "";
  return raw.slice(0, MAX_UPDATE_TEXT).trim();
}

async function answerWithOrchestrator(
  chatId: number,
  content: string,
  image: string | null,
  lang: LangMode,
  trusted: boolean,
  deadline: AbortSignal,
): Promise<void> {
  void sendChatAction(chatId);
  // Telegram sends one message at a time, so an audit awaiting approval is kept
  // in Supabase and replayed as the previous turn when the reply is "승인" / "cancel".
  const chatKey = `telegram:${chatId}`;
  const pending = !image && isApprovalReply(content) ? await getPendingAudit(chatKey) : null;
  const messages: ChatMessage[] = pending
    ? [{ role: "assistant", content: pending }, { role: "user", content }]
    : [{ role: "user", content }];
  const reply = await runOrchestratorToText(
    { messages, image, lang },
    {
      trusted,
      signal: deadline,
      onAuditDecision: (decision, items) => void logAuditDecision(chatKey, decision, items),
    },
  );
  // The emote tag drives the web avatar only; Telegram and the stored audit get plain text.
  const result = { ...reply, text: stripEmotes(reply.text) };
  if (!deadline.aborted) {
    // Any other reply ends the wait, like the HUD, where approval must follow the audit directly.
    await savePendingAudit(chatKey, result.agent === "audit" && result.text.includes(APPROVAL_MARKER) ? result.text : null);
  }
  if (deadline.aborted) {
    // On abort the orchestrator returns whatever streamed so far, possibly nothing.
    const partial = result.text.trim();
    await sendMessage(chatId, partial ? `${partial}\n\n${TEXT.cutOff}` : TEXT.failed);
    return;
  }
  // IoT answers must stay exactly the fixed sentence, so only add sources when there are any.
  await sendMessage(chatId, result.text + sourcesSuffix(result.sources, result.text));
}

async function handleMessage(message: TelegramMessage, deadline: AbortSignal): Promise<void> {
  const chatId = message.chat.id;
  const { adminChatId } = getEnv().telegram;
  const isAdmin = Boolean(adminChatId) && String(chatId) === adminChatId;
  const lang: ReplyLang = message.from?.language_code?.toLowerCase().startsWith("ko") ? "ko" : "en";
  const body = messageBody(message);
  const command = parseCommand(body);

  if (command?.name === "whoami") {
    await sendMessage(chatId, whoamiText(chatId, isAdmin, Boolean(adminChatId)));
    return;
  }
  if (!adminChatId) {
    // Until an admin chat is set nothing that spends model, search or portal calls is reachable,
    // so a bot found by its username cannot run up the owner's bills.
    if (command?.name === "start" || command?.name === "help") {
      await sendMessage(chatId, command.name === "start" ? TEXT.start : TEXT.help);
    } else {
      await sendMessage(chatId, TEXT.locked);
    }
    return;
  }
  if (!isAdmin) {
    await sendMessage(chatId, TEXT.private);
    return;
  }

  if (command) {
    switch (command.name) {
      case "start":
        await sendMessage(chatId, `${sessionGreeting({ timeZone: getEnv().timeZone }).greeting}\n\n${TEXT.start}`);
        return;
      case "help":
        await sendMessage(chatId, TEXT.help);
        return;
      case "status":
        await sendMessage(chatId, statusText(isAdmin));
        return;
      case "report": {
        // Only the admin chat reaches here (every other chat was refused above).
        void sendChatAction(chatId);
        const text = await hangeulReportText(lang, deadline);
        await sendMessage(chatId, deadline.aborted ? TEXT.failed : text);
        return;
      }
      case "search": {
        if (!command.args) {
          await sendMessage(chatId, pick(lang, "Usage: /search <query>", "사용법: /search <검색어>"));
          return;
        }
        void sendChatAction(chatId);
        const res = await webSearch(command.args, { maxResults: 5, signal: deadline });
        await sendMessage(chatId, deadline.aborted ? TEXT.failed : formatSearchBriefing(res));
        return;
      }
      default:
        await sendMessage(chatId, pick(lang, "Unknown command. Try /help.", "알 수 없는 명령어예요. /help 를 입력해 보세요."));
        return;
    }
  }

  // Hard rule: an IoT command gets exactly the fixed sentence, also as a photo caption,
  // so it is answered before any image lookup, download or failure message.
  const iot = body ? checkIoTQuery(body, "auto") : null;
  if (iot) {
    await sendMessage(chatId, iot);
    return;
  }

  const image = imageFileId(message);
  if (image) {
    if (!image.fileId) {
      await sendMessage(chatId, pick(lang, "That image is larger than 4 MB. Please send a smaller one.", "이미지가 4MB를 넘어요. 더 작은 이미지를 보내 주세요."));
      return;
    }
    void sendChatAction(chatId);
    const dataUrl = await downloadFileAsDataUrl(image.fileId, deadline);
    if (!dataUrl) {
      const failure = pick(lang, "I couldn't download that image. Please try again.", "이미지를 받지 못했어요. 다시 보내 주세요.");
      await sendMessage(chatId, deadline.aborted ? TEXT.failed : failure);
      return;
    }
    await answerWithOrchestrator(chatId, body, dataUrl, body ? "auto" : lang, isAdmin, deadline);
    return;
  }

  if (body) await answerWithOrchestrator(chatId, body, null, "auto", isAdmin, deadline);
}

export interface UpdateOptions {
  /** Overrides the per-update deadline (tests). */
  deadline?: AbortSignal;
}

/**
 * Handles one webhook update. Only `message` updates from people are answered;
 * everything else (edits, callbacks, bot messages, stickers) is ignored. The
 * caller must have verified the webhook secret: admin trust comes from chat.id.
 */
export async function handleTelegramUpdate(update: unknown, options: UpdateOptions = {}): Promise<void> {
  if (typeof update !== "object" || update === null) return;
  const message = (update as { message?: unknown }).message;
  if (!isMessage(message) || message.from?.is_bot) return;

  const deadline = options.deadline ?? AbortSignal.timeout(UPDATE_DEADLINE_MS);
  try {
    await handleMessage(message, deadline);
  } catch (error) {
    console.error(`[telegram] update handling failed: ${errorName(error)}`);
    await sendMessage(message.chat.id, TEXT.failed);
  }
}
