"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, ImagePlus, LoaderCircle, Mic, SendHorizontal, Square, Volume2, VolumeX, X } from "lucide-react";
import type { ChatPhase } from "@/hooks/useJeannieChat";
import type { SpeechRecognitionState } from "@/hooks/useSpeechRecognition";
import { prepareImageFile } from "@/lib/client/image";
import { canSendMessage } from "@/lib/client/reachability";
import type { LangMode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LanguageToggle } from "./LanguageToggle";

export interface Attachment {
  dataUrl: string;
  name: string;
  source: "upload" | "camera";
}

interface ChatComposerProps {
  phase: ChatPhase;
  /** Jeannie is reading a reply aloud (or fetching its voice): STOP then silences her. */
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
  onNotice: (message: string) => void;
  recognition: SpeechRecognitionState;
  /** Offline (spec D10): the text box, mic, attachments and SEND are disabled; STOP still works. */
  disabled?: boolean;
  /** Shown as the placeholder while disabled (the offline line). */
  disabledText?: string;
}

const HOLD_TO_TALK_MS = 450;
const MAX_TEXTAREA_PX = 160;
// SEND turns into STOP in the same spot; the second click of a double-click must not abort.
const STOP_GUARD_MS = 400;

export function ChatComposer({
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
  onNotice,
  recognition,
  disabled = false,
  disabledText,
}: ChatComposerProps) {
  const [draft, setDraft] = useState("");
  const [preparing, setPreparing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pressRef = useRef<{ startedByPress: boolean; at: number }>({ startedByPress: false, at: 0 });
  const sentAtRef = useRef(0);
  const busy = phase !== "idle";
  const canSend = canSendMessage({ draft, hasAttachment: attachment !== null, preparing, disabled });
  // While she speaks, STOP silences her; typing a new message brings SEND back.
  const showStop = busy || (speaking && !canSend);

  // Auto-grow the textarea up to a cap.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
  }, [draft]);

  const submit = () => {
    // Enter while an image is still being prepared would send without it.
    if (!canSend) return;
    if (onSend(draft, attachment?.dataUrl ?? null)) {
      sentAtRef.current = performance.now();
      setDraft("");
      onAttach(null);
    }
  };

  const stop = (event: ReactMouseEvent<HTMLButtonElement>) => {
    if (event.detail > 1 || performance.now() - sentAtRef.current < STOP_GUARD_MS) return;
    onStop();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // IME-safe: Enter that confirms a Korean syllable composition must not send.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape" && (busy || speaking)) {
      event.preventDefault();
      onStop();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setPreparing(true);
    try {
      const prepared = await prepareImageFile(file);
      onAttach({ dataUrl: prepared.dataUrl, name: prepared.name, source: "upload" });
      textareaRef.current?.focus();
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "That image could not be attached.");
    } finally {
      setPreparing(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  // Mic: tap to toggle, or press-and-hold to talk and release to send.
  const micDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    if (!recognition.listening) {
      recognition.start();
      pressRef.current = { startedByPress: true, at: performance.now() };
    } else {
      pressRef.current = { startedByPress: false, at: performance.now() };
    }
  };
  const micUp = () => {
    const { startedByPress, at } = pressRef.current;
    if (startedByPress && performance.now() - at > HOLD_TO_TALK_MS) recognition.stop();
  };
  const micClick = (event: ReactMouseEvent<HTMLButtonElement>) => {
    if (event.detail === 0) {
      // Keyboard activation (Enter / Space): plain toggle.
      if (recognition.listening) recognition.stop();
      else recognition.start();
      return;
    }
    if (!pressRef.current.startedByPress) recognition.stop();
  };

  const micTitle = disabled
    ? (disabledText ?? "Voice input is disabled")
    : recognition.supported
      ? recognition.listening
        ? "Stop listening"
        : "Voice input: tap to talk, or hold and release to send"
      : "Voice input is not supported in this browser";

  return (
    <div className="border-t border-neon/25 bg-void/40 p-2.5 sm:p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <LanguageToggle value={lang} onChange={onLangChange} />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onVoiceToggle}
            aria-pressed={voiceOn}
            aria-label={voiceOn ? "Voice replies on" : "Voice replies off"}
            title={voiceOn ? "Voice replies on" : "Voice replies off"}
            data-active={voiceOn}
            className="hud-btn px-2.5 font-mono text-[0.68rem] tracking-[0.14em]"
          >
            {voiceOn ? (
              <Volume2 aria-hidden="true" className="h-4 w-4" />
            ) : (
              <VolumeX aria-hidden="true" className="h-4 w-4" />
            )}
            <span>VOICE</span>
          </button>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {attachment ? (
          <motion.div
            key="attachment"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mb-2 flex items-center gap-2 rounded-md border border-neon/40 bg-neon/10 p-1.5 pr-1">
              {/* eslint-disable-next-line @next/next/no-img-element -- local data URL preview */}
              <img
                src={attachment.dataUrl}
                alt=""
                className="h-10 w-10 shrink-0 rounded border border-neon/40 object-cover"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[0.78rem] text-petal-soft">{attachment.name}</p>
                <p className="hud-label">{attachment.source === "camera" ? "Camera frame" : "Image"} · Vision agent</p>
              </div>
              <button
                type="button"
                onClick={() => onAttach(null)}
                aria-label="Remove attachment"
                className="hud-btn border-transparent bg-transparent"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {recognition.listening || recognition.error ? (
        <p
          className={cn(
            "mb-2 flex items-center gap-2 rounded border px-2.5 py-1.5 font-mono text-[0.72rem]",
            recognition.listening
              ? "border-neon/50 bg-neon/10 text-white"
              : "border-dashed border-neon-hot/50 text-petal-soft",
          )}
          aria-live="polite"
        >
          {recognition.listening ? <span className="led led-on" aria-hidden="true" /> : null}
          <span className="min-w-0 truncate">
            {recognition.listening ? recognition.interim || "Listening… 듣는 중" : recognition.error}
          </span>
        </p>
      ) : null}

      <div className="rounded-md border border-neon/35 bg-void/70 transition-shadow focus-within:border-neon-hot focus-within:shadow-glow-sm">
        <label htmlFor="jeannie-composer" className="sr-only">
          Message Jeannie
        </label>
        <textarea
          id="jeannie-composer"
          ref={textareaRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          enterKeyHint="send"
          disabled={disabled}
          placeholder={
            disabled && disabledText ? disabledText : lang === "ko" ? "지니에게 명령하세요…" : "Command Jeannie… · 지니에게 말하기"
          }
          // 16px on phones: iOS Safari zooms into any smaller focused field.
          className="block max-h-40 min-h-[44px] w-full resize-none bg-transparent px-3 pt-2.5 text-base leading-relaxed text-white outline-none focus-visible:shadow-none focus-visible:outline-none sm:text-[0.92rem]"
        />
        <div className="flex items-center justify-between gap-2 px-1.5 pb-1.5">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onOpenCamera}
              aria-label="Open camera scanner"
              title="Camera scanner"
              disabled={disabled}
              className="hud-btn border-transparent bg-transparent"
            >
              <Camera aria-hidden="true" className="h-[18px] w-[18px]" />
            </button>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              aria-label="Attach an image"
              title="Attach image"
              disabled={preparing || disabled}
              className="hud-btn border-transparent bg-transparent"
            >
              {preparing ? (
                <LoaderCircle aria-hidden="true" className="h-[18px] w-[18px] animate-spin" />
              ) : (
                <ImagePlus aria-hidden="true" className="h-[18px] w-[18px]" />
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => void onFile(event.target.files?.[0])}
            />
            <button
              type="button"
              onPointerDown={micDown}
              onPointerUp={micUp}
              onClick={micClick}
              onContextMenu={(event) => event.preventDefault()}
              // A mic already open can still be closed.
              disabled={!recognition.supported || (disabled && !recognition.listening)}
              aria-pressed={recognition.listening}
              aria-label={micTitle}
              title={micTitle}
              data-active={recognition.listening}
              className={cn(
                "hud-btn touch-hold border-transparent bg-transparent",
                recognition.listening && "animate-pulse",
              )}
            >
              <Mic aria-hidden="true" className="h-[18px] w-[18px]" />
            </button>
          </div>
          <span className="hud-label hidden min-w-0 truncate xl:inline" aria-hidden="true">
            ↵ send · ⇧↵ newline
          </span>
          {showStop ? (
            <button
              type="button"
              onClick={stop}
              aria-label={busy ? "Stop the reply" : "Stop speaking"}
              title="Stop"
              className="hud-btn hud-btn-primary px-3"
            >
              <Square aria-hidden="true" className="h-3.5 w-3.5 fill-current" />
              <span className="font-mono text-[0.7rem] tracking-[0.16em]">STOP</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              aria-label="Send message"
              title="Send"
              className="hud-btn hud-btn-primary px-3"
            >
              <SendHorizontal aria-hidden="true" className="h-4 w-4" />
              <span className="font-mono text-[0.7rem] tracking-[0.16em]">SEND</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
