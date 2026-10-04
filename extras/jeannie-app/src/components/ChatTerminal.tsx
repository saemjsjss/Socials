"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown, Eraser, FileText, Languages, Lightbulb, Newspaper, Terminal, type LucideIcon } from "lucide-react";
import type { ChatPhase, HudMessage } from "@/hooks/useJeannieChat";
import type { SpeechRecognitionState } from "@/hooks/useSpeechRecognition";
import { OFFLINE_LINE } from "@/lib/client/reachability";
import type { LangMode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChatComposer, type Attachment } from "./ChatComposer";
import { ChatMessageView } from "./ChatMessageView";

export type { Attachment } from "./ChatComposer";

interface Suggestion {
  label: string;
  prompt: string;
  icon: LucideIcon;
}

const SUGGESTIONS: Suggestion[] = [
  { label: "Dim the living room lights", prompt: "Dim the living room lights to 40%", icon: Lightbulb },
  { label: "Live AI news", prompt: "What are today's top AI news headlines?", icon: Newspaper },
  { label: "Hangeul daily report", prompt: "Hangeul daily report", icon: FileText },
  { label: "오늘 서울 날씨 어때?", prompt: "오늘 서울 날씨 어때?", icon: Languages },
];

interface ChatTerminalProps {
  messages: HudMessage[];
  phase: ChatPhase;
  /** Jeannie is reading a reply aloud. */
  speaking: boolean;
  lang: LangMode;
  onLangChange: (lang: LangMode) => void;
  voiceOn: boolean;
  onVoiceToggle: () => void;
  attachment: Attachment | null;
  onAttach: (attachment: Attachment | null) => void;
  onOpenCamera: () => void;
  onSend: (text: string, image: string | null) => boolean;
  onStop: () => void;
  onClear: () => void;
  onNotice: (message: string) => void;
  recognition: SpeechRecognitionState;
  /** No connection (spec D10): the composer and the quick commands are disabled. */
  offline?: boolean;
  className?: string;
}

const STICK_THRESHOLD_PX = 96;

const PHASE_LABEL: Record<ChatPhase, string> = {
  idle: "LINK READY",
  waiting: "ROUTING",
  streaming: "RECEIVING",
};

function EmptyState({ onPick, disabled }: { onPick: (prompt: string) => void; disabled: boolean }) {
  return (
    <div className="flex min-h-full flex-col justify-center gap-5 px-1 py-2">
      <div className="space-y-2">
        <p className="font-display text-[0.7rem] tracking-[0.3em] text-neon-hot text-glow-soft">JEANNIE ONLINE</p>
        <p className="text-[0.95rem] leading-relaxed text-petal-soft">
          All systems nominal. Ask me anything, show me something through the camera, or give a smart-home command.
        </p>
        <p className="text-[0.85rem] leading-relaxed text-petal-soft/70">
          모든 시스템 정상. 한국어로도 편하게 말씀하세요.
        </p>
      </div>
      <div>
        <p className="hud-label mb-2">Quick commands · 빠른 명령</p>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s, index) => (
            <motion.button
              key={s.prompt}
              type="button"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35 + index * 0.07 }}
              onClick={() => onPick(s.prompt)}
              disabled={disabled}
              className="hud-chip disabled:cursor-not-allowed disabled:opacity-50"
            >
              <s.icon aria-hidden="true" className="h-3.5 w-3.5 text-neon-hot" />
              {s.label}
            </motion.button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The comms terminal: message log with smart auto-scroll plus the composer. */
export function ChatTerminal({
  messages,
  phase,
  speaking,
  lang,
  onLangChange,
  voiceOn,
  onVoiceToggle,
  attachment,
  onAttach,
  onOpenCamera,
  onSend,
  onStop,
  onClear,
  onNotice,
  recognition,
  offline = false,
  className,
}: ChatTerminalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  // Size of the log box as of the last resize callback (null until observed).
  const boxRef = useRef<{ width: number; height: number } | null>(null);
  const [showJump, setShowJump] = useState(false);

  const scrollToEnd = useCallback((smooth: boolean) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // A scroll fired by the box itself changing size (Chrome's scroll anchoring on
    // rotation or a breakpoint switch) arrives before the resize callback; it is not
    // the operator scrolling away, so keep the pin.
    const box = boxRef.current;
    if (box && (box.width !== el.clientWidth || box.height !== el.clientHeight)) {
      if (stickRef.current) scrollToEnd(false);
      return;
    }
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
    stickRef.current = nearBottom;
    setShowJump(!nearBottom);
  };

  // Follow the stream only while the operator hasn't scrolled up to read history.
  useLayoutEffect(() => {
    if (stickRef.current && messages.length > 0) scrollToEnd(false);
  }, [messages, scrollToEnd]);

  // Stay pinned when the log itself changes size (phone rotation, a layout
  // breakpoint): a shorter box would otherwise leave the newest lines below the fold.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      boxRef.current = { width: el.clientWidth, height: el.clientHeight };
      if (stickRef.current) scrollToEnd(false);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [scrollToEnd]);

  // A new operator message always snaps back to the bottom.
  const lastUserId = [...messages].reverse().find((m) => m.role === "user")?.id;
  useEffect(() => {
    if (!lastUserId) return;
    stickRef.current = true;
    setShowJump(false);
    scrollToEnd(true);
  }, [lastUserId, scrollToEnd]);

  const send = (text: string, image: string | null) => onSend(text, image);

  return (
    <section aria-label="Comms terminal" className={cn("hud-panel flex min-h-0 flex-col", className)}>
      <header className="flex min-h-[44px] items-center justify-between gap-2 border-b border-neon/20 px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <Terminal aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-neon-hot" />
          <h2 className="hud-title truncate">
            Comms<span className="hidden sm:inline"> Terminal</span>
          </h2>
          <span className="hud-label hidden whitespace-nowrap normal-case tracking-[0.08em] sm:inline lg:hidden xl:inline">
            통신 단말
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className="flex items-center gap-1.5 font-mono text-[0.6rem] tracking-[0.18em] text-petal-soft/75"
            aria-live="polite"
          >
            <span className={cn("led", phase === "idle" ? "led-idle" : "led-on")} aria-hidden="true" />
            {PHASE_LABEL[phase]}
          </span>
          <button
            type="button"
            onClick={onClear}
            disabled={messages.length === 0}
            aria-label="Clear conversation"
            title="Clear conversation"
            className="hud-btn border-transparent bg-transparent"
          >
            <Eraser aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-label="Conversation with Jeannie"
          className="h-full space-y-4 overflow-y-auto overscroll-contain px-3 py-4"
        >
          {messages.length === 0 ? (
            <EmptyState onPick={(prompt) => send(prompt, null)} disabled={offline} />
          ) : (
            messages.map((message) => <ChatMessageView key={message.id} message={message} />)
          )}
        </div>
        {showJump ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
            <button
              type="button"
              onClick={() => {
                stickRef.current = true;
                setShowJump(false);
                scrollToEnd(true);
              }}
              className="hud-btn hud-btn-primary pointer-events-auto px-3 font-mono text-[0.66rem] tracking-[0.16em]"
            >
              <ArrowDown aria-hidden="true" className="h-3.5 w-3.5" />
              LATEST
            </button>
          </div>
        ) : null}
      </div>

      <ChatComposer
        phase={phase}
        speaking={speaking}
        lang={lang}
        onLangChange={onLangChange}
        voiceOn={voiceOn}
        onVoiceToggle={onVoiceToggle}
        attachment={attachment}
        onAttach={onAttach}
        onOpenCamera={onOpenCamera}
        onSend={send}
        onStop={onStop}
        onNotice={onNotice}
        recognition={recognition}
        disabled={offline}
        disabledText={lang === "ko" ? OFFLINE_LINE.ko : OFFLINE_LINE.en}
      />
    </section>
  );
}
