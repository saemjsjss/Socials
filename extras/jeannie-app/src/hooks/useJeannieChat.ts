"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, isAbortError, openChatStream, readAccessKey } from "@/lib/client/api";
import { parseEmote, type ReplyEmote } from "@/lib/emote";
import type { AgentId, ChatMessage, HangeulDeviceHints, LangMode, LlmProvider, ResolvedLang, SourceLink } from "@/lib/types";

export type HudMessageStatus = "streaming" | "done" | "stopped" | "error";

export interface HudMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: number;
  status: HudMessageStatus;
  image?: string | null;
  agent?: AgentId | null;
  lang?: ResolvedLang | null;
  provider?: LlmProvider | null;
  sources?: SourceLink[];
  latencyMs?: number;
  /** The reply's leading emote tag; `content` never contains it. */
  emote?: ReplyEmote | null;
  /** Shown in the HUD only, never sent back to the model (the opening greeting). */
  local?: boolean;
}

/** idle → waiting (request sent, no bytes yet) → streaming (text arriving) → idle. */
export type ChatPhase = "idle" | "waiting" | "streaming";

export interface ChatTelemetry {
  lastLatencyMs: number | null;
  lastTtfbMs: number | null;
  activeAgent: AgentId | null;
  provider: LlmProvider | null;
}

export interface CompletedReply {
  /** Display text, emote tag removed (safe to speak). */
  text: string;
  lang: ResolvedLang | null;
  agent: AgentId | null;
}

interface ChatOptions {
  lang: LangMode;
  /** Runs before every request (e.g. stop speaking). */
  onBeforeSend?: () => void;
  onReplyComplete?: (reply: CompletedReply) => void;
  /** Once per reply, as soon as its leading emote tag has streamed in (never for untagged replies). */
  onEmote?: (emote: ReplyEmote) => void;
  /** 401 access_key_required. `rejected` = a stored key was sent and refused. */
  onAccessKeyRequired?: (rejected: boolean) => void;
  /**
   * Hangeul questions and the device copy (ticket 7): an answer built on the
   * device (shown at once, no request), or hints for the server (the device's
   * question vector and search hits). Null for any other question.
   */
  prepareHangeul?: (input: { question: string; lang: LangMode; previous: string[] }) => Promise<HangeulAssist | null>;
}

export interface HangeulAssist {
  answer?: { text: string; lang: ResolvedLang };
  hints?: HangeulDeviceHints;
}

/** A device answer or hint that takes longer than this is skipped: the server answers instead. */
const PREPARE_TIMEOUT_MS = 6_000;

async function withDeadline<T>(work: Promise<T>, ms: number): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  try {
    return await Promise.race([work.catch(() => null), deadline]);
  } finally {
    clearTimeout(timer);
  }
}

// Contract limits are 50 messages / 20k chars; stay comfortably inside them.
const HISTORY_LIMIT = 24;
const MAX_CHARS = 20_000;

let sequence = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(sequence++).toString(36)}`;

function defaultImagePrompt(lang: LangMode): string {
  return lang === "ko" ? "이 이미지를 분석해 주세요." : "Analyze this image.";
}

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 0) return error.message;
    return `${error.message} [${error.status}${error.code.startsWith("http_") ? "" : ` · ${error.code}`}]`;
  }
  return "Unexpected failure while talking to Jeannie.";
}

export function useJeannieChat(options: ChatOptions) {
  const [messages, setMessages] = useState<HudMessage[]>([]);
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [telemetry, setTelemetry] = useState<ChatTelemetry>({
    lastLatencyMs: null,
    lastTtfbMs: null,
    activeAgent: null,
    provider: null,
  });

  // Mirrors of state for use inside async flows without stale closures.
  const messagesRef = useRef<HudMessage[]>([]);
  const optionsRef = useRef(options);
  const controllerRef = useRef<AbortController | null>(null);
  const pendingRetryRef = useRef<string | null>(null);

  useEffect(() => {
    optionsRef.current = options;
  });

  const commit = useCallback((update: (prev: HudMessage[]) => HudMessage[]) => {
    messagesRef.current = update(messagesRef.current);
    setMessages(messagesRef.current);
  }, []);

  const patch = useCallback(
    (id: string, changes: Partial<HudMessage>) =>
      commit((prev) => prev.map((m) => (m.id === id ? { ...m, ...changes } : m))),
    [commit],
  );

  const addSystemLine = useCallback(
    (content: string) =>
      commit((prev) => [
        ...prev,
        { id: nextId("sys"), role: "system", content, createdAt: Date.now(), status: "error" },
      ]),
    [commit],
  );

  const buildHistory = useCallback((userId: string): ChatMessage[] => {
    const all = messagesRef.current;
    const end = all.findIndex((m) => m.id === userId);
    const upTo = end === -1 ? all : all.slice(0, end + 1);
    const conversational = upTo.filter(
      (m) => m.role !== "system" && !m.local && m.status !== "error" && m.content.trim().length > 0,
    );
    return conversational.slice(-HISTORY_LIMIT).map((m, index, list): ChatMessage => {
      const isNewest = index === list.length - 1;
      const role = m.role === "user" ? "user" : "assistant";
      // Give the model its own tags back so it keeps to the protocol.
      const tagged = role === "assistant" && m.emote ? `[emote:${m.emote}] ${m.content}` : m.content;
      const content = tagged.slice(0, MAX_CHARS);
      // Only the newest user turn carries its image; older turns are text-only.
      return isNewest && m.image ? { role, content, image: m.image } : { role, content };
    });
  }, []);

  const run = useCallback(
    async (userId: string) => {
      const history = buildHistory(userId);
      if (history.length === 0 || history[history.length - 1].role !== "user") return;

      const controller = new AbortController();
      controllerRef.current = controller;
      const assistantId = nextId("jeannie");
      commit((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "", createdAt: Date.now(), status: "streaming" },
      ]);
      setPhase("waiting");
      setTelemetry((prev) => ({ ...prev, activeAgent: null }));

      const started = performance.now();
      let text = "";
      let frame = 0;
      let emoteSeen = false;
      // The raw stream opens with an emote tag; only the text after it is shown.
      const display = (final = false) => parseEmote(text, { final });
      const flush = () => {
        frame = 0;
        patch(assistantId, { content: display().text });
      };

      try {
        const newest = history[history.length - 1];
        let hints: HangeulDeviceHints | undefined;
        const prepare = optionsRef.current.prepareHangeul;
        if (prepare && !newest.image) {
          const previous = history.slice(0, -1).flatMap((m) => (m.role === "user" ? [m.content] : []));
          const assist = await withDeadline(prepare({ question: newest.content, lang: optionsRef.current.lang, previous }), PREPARE_TIMEOUT_MS);
          if (controller.signal.aborted) throw new DOMException("Aborted by user", "AbortError");
          if (assist?.answer) {
            // Built on the device from the synced copy: shown at once, with its own "as of" line.
            const latency = Math.round(performance.now() - started);
            patch(assistantId, {
              content: assist.answer.text,
              agent: "hangeul",
              lang: assist.answer.lang,
              provider: "none",
              status: "done",
              latencyMs: latency,
            });
            setTelemetry((prev) => ({ ...prev, activeAgent: "hangeul", provider: "none", lastLatencyMs: latency, lastTtfbMs: latency }));
            optionsRef.current.onReplyComplete?.({ text: assist.answer.text, lang: assist.answer.lang, agent: "hangeul" });
            return;
          }
          hints = assist?.hints;
        }
        const { meta, chunks } = await openChatStream(
          { messages: history, lang: optionsRef.current.lang, ...(hints ? { hangeul: hints } : {}) },
          controller.signal,
        );
        patch(assistantId, { agent: meta.agent, lang: meta.lang, provider: meta.provider, sources: meta.sources });
        setTelemetry((prev) => ({ ...prev, activeAgent: meta.agent, provider: meta.provider }));

        let ttfb: number | null = null;
        for await (const chunk of chunks) {
          if (ttfb === null) {
            ttfb = Math.round(performance.now() - started);
            setPhase("streaming");
            setTelemetry((prev) => ({ ...prev, lastTtfbMs: ttfb }));
          }
          text += chunk;
          if (!emoteSeen) {
            const parsed = display();
            if (!parsed.pending) {
              emoteSeen = true;
              if (parsed.emote) {
                patch(assistantId, { emote: parsed.emote });
                optionsRef.current.onEmote?.(parsed.emote);
              }
            }
          }
          // Coalesce token bursts into one render per frame.
          if (!frame) frame = requestAnimationFrame(flush);
        }
        cancelAnimationFrame(frame);

        const latency = Math.round(performance.now() - started);
        setTelemetry((prev) => ({ ...prev, lastLatencyMs: latency, lastTtfbMs: ttfb ?? latency }));
        const { text: shown, emote } = display(true);
        if (!shown.trim()) {
          commit((prev) => prev.filter((m) => m.id !== assistantId));
          addSystemLine("Jeannie returned an empty transmission. Try again.");
          return;
        }
        patch(assistantId, { content: shown, emote, status: "done", latencyMs: latency });
        optionsRef.current.onReplyComplete?.({ text: shown, lang: meta.lang, agent: meta.agent });
      } catch (error) {
        cancelAnimationFrame(frame);
        const shown = display(true).text;
        if (isAbortError(error)) {
          if (shown) patch(assistantId, { content: shown, status: "stopped" });
          else commit((prev) => prev.filter((m) => m.id !== assistantId));
          return;
        }
        if (shown) patch(assistantId, { content: shown, status: "stopped" });
        else commit((prev) => prev.filter((m) => m.id !== assistantId));

        if (error instanceof ApiRequestError && error.needsAccessKey) {
          pendingRetryRef.current = userId;
          optionsRef.current.onAccessKeyRequired?.(readAccessKey() !== null);
          return;
        }
        addSystemLine(describeError(error));
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
          setPhase("idle");
        }
      }
    },
    [addSystemLine, buildHistory, commit, patch],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  /** Sends a user turn. Interrupts a reply still streaming. Returns false when there is nothing to send. */
  const send = useCallback(
    (text: string, image?: string | null): boolean => {
      const trimmed = text.trim();
      if (!trimmed && !image) return false;
      controllerRef.current?.abort();
      pendingRetryRef.current = null;
      optionsRef.current.onBeforeSend?.();

      const userMessage: HudMessage = {
        id: nextId("op"),
        role: "user",
        content: trimmed || defaultImagePrompt(optionsRef.current.lang),
        createdAt: Date.now(),
        status: "done",
        image: image ?? null,
      };
      commit((prev) => [...prev, userMessage]);
      void run(userMessage.id);
      return true;
    },
    [commit, run],
  );

  /** Re-sends the request that was refused for lack of an access key. */
  const retryPending = useCallback(() => {
    const pending = pendingRetryRef.current;
    pendingRetryRef.current = null;
    if (pending) void run(pending);
  }, [run]);

  const dropPending = useCallback(() => {
    if (!pendingRetryRef.current) return;
    pendingRetryRef.current = null;
    addSystemLine("Access key required. Use the lock control to enter it, then resend.");
  }, [addSystemLine]);

  const clear = useCallback(() => {
    controllerRef.current?.abort();
    pendingRetryRef.current = null;
    commit(() => []);
  }, [commit]);

  /** Jeannie's opening line, shown once at the top of an empty session. Returns false when the chat already started. */
  const greet = useCallback(
    (content: string): boolean => {
      if (messagesRef.current.length > 0) return false;
      commit(() => [
        { id: nextId("greet"), role: "assistant", content, createdAt: Date.now(), status: "done", lang: "ko", local: true },
      ]);
      return true;
    },
    [commit],
  );

  /** A line she says on her own (the idle check-in): shown like a reply, never sent back to the model. */
  const announce = useCallback(
    (content: string, lang: ResolvedLang = "ko") =>
      commit((prev) => [
        ...prev,
        { id: nextId("say"), role: "assistant", content, createdAt: Date.now(), status: "done", lang, local: true },
      ]),
    [commit],
  );

  useEffect(() => () => controllerRef.current?.abort(), []);

  return {
    messages,
    phase,
    telemetry,
    send,
    stop,
    retryPending,
    dropPending,
    clear,
    greet,
    announce,
    notify: addSystemLine,
  };
}

export type JeannieChat = ReturnType<typeof useJeannieChat>;
