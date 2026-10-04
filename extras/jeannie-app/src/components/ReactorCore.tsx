"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { AgentId, LangMode, LlmProvider, TtsEngine } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AGENT_META } from "./ChatMessageView";
import { HologramOrb, type OrbState } from "./HologramOrb";
import { VoiceVisualizer } from "./VoiceVisualizer";

const STATE_COPY: Record<OrbState, { label: string; ko: string }> = {
  standby: { label: "STANDBY", ko: "대기 중" },
  listening: { label: "LISTENING", ko: "듣는 중" },
  analyzing: { label: "ANALYZING", ko: "분석 중" },
  speaking: { label: "SPEAKING", ko: "응답 중" },
};

const LANG_LABEL: Record<LangMode, string> = { auto: "AUTO", en: "EN", ko: "한국어", bilingual: "EN + 한" };

/**
 * Polls a level getter at ~30 fps while audio is active, so only this subtree
 * re-renders with the signal (the chat log and panels stay still).
 */
function useLevel(getLevel: () => number, active: boolean): number {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!active) {
      setLevel(0);
      return;
    }
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (now - last > 33) {
        last = now;
        const next = getLevel();
        setLevel((prev) => (Math.abs(prev - next) > 0.012 ? next : prev));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, getLevel]);
  return level;
}

function Annotation({
  className,
  label,
  value,
  wideOnly,
}: {
  className: string;
  label: string;
  value: string;
  wideOnly?: boolean;
}) {
  // Lower annotations sit beside the state label, so they need a wide centre column.
  return (
    <div
      className={cn(
        "pointer-events-none absolute hidden font-mono",
        wideOnly ? "min-[1400px]:block" : "lg:block",
        className,
      )}
      aria-hidden="true"
    >
      <p className="text-[0.56rem] tracking-[0.24em] text-petal-soft/50">{label}</p>
      <p className="text-[0.7rem] tracking-[0.16em] text-neon-hot text-glow-soft">{value}</p>
    </div>
  );
}

interface ReactorCoreProps {
  state: OrbState;
  getLevel: () => number;
  analyser: AnalyserNode | null;
  activeAgent: AgentId | null;
  provider: LlmProvider | null;
  voiceEngine: TtsEngine | null;
  /** The reply is done and its voice is being synthesised. */
  preparingVoice: boolean;
  lang: LangMode;
  className?: string;
}

/** Centre stage: the hologram, its state readout and the voice spectrum. */
export function ReactorCore({
  state,
  getLevel,
  analyser,
  activeAgent,
  provider,
  voiceEngine,
  preparingVoice,
  lang,
  className,
}: ReactorCoreProps) {
  const audioActive = state === "speaking" || state === "listening";
  const level = useLevel(getLevel, audioActive);
  const copy = STATE_COPY[state];

  const detail =
    state === "analyzing"
      ? preparingVoice
        ? "SYNTHESIZING VOICE · 음성 합성"
        : activeAgent
          ? `ROUTED → ${AGENT_META[activeAgent].label} AGENT`
          : "ORCHESTRATOR ROUTING"
      : state === "speaking"
        ? `VOICE ▸ ${voiceEngine === "elevenlabs" ? "ELEVENLABS" : voiceEngine === "edge" ? "EDGE NEURAL" : "BROWSER SYNTH"}`
        : state === "listening"
          ? "VOICE CHANNEL OPEN"
          : "AWAITING COMMAND · 명령 대기";

  return (
    <section aria-label="Jeannie core" className={cn("relative flex flex-col items-center", className)}>
      <Annotation className="left-2 top-2" label="REACTOR" value="J-01 · ONLINE" />
      <Annotation className="right-2 top-2 text-right" label="LANGUAGE" value={LANG_LABEL[lang]} />
      <Annotation
        wideOnly
        className="bottom-28 left-2"
        label="ACTIVE AGENT"
        value={activeAgent ? AGENT_META[activeAgent].label : "—"}
      />
      <Annotation
        wideOnly
        className="bottom-28 right-2 text-right"
        label="NEURAL CORE"
        value={provider ? (provider === "none" ? "OFFLINE" : provider.toUpperCase()) : "—"}
      />

      <div className="relative flex min-h-0 w-full flex-1 items-center justify-center">
        <div className="relative aspect-square h-full max-h-[min(620px,100%)] max-w-full">
          <HologramOrb state={state} level={level} />
        </div>
      </div>

      <div className="flex flex-col items-center gap-1 pt-1 text-center" role="status" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          <motion.p
            key={state}
            initial={{ opacity: 0, y: 6, filter: "blur(4px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -6, filter: "blur(4px)" }}
            transition={{ duration: 0.25 }}
            className="font-display text-xl font-bold tracking-[0.42em] text-white text-glow sm:text-2xl"
          >
            {copy.label}
            <span className="sr-only"> · {copy.ko}</span>
          </motion.p>
        </AnimatePresence>
        <p aria-hidden="true" className="text-[0.8rem] tracking-[0.3em] text-petal">
          {copy.ko}
        </p>
        <p className="font-mono text-[0.62rem] tracking-[0.22em] text-petal-soft/60">{detail}</p>
      </div>

      <div className="mt-2 h-14 w-full max-w-xl sm:h-20">
        <VoiceVisualizer analyser={analyser} level={level} active={audioActive} />
      </div>
    </section>
  );
}
