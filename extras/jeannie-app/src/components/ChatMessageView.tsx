"use client";

import { memo } from "react";
import { motion } from "framer-motion";
import {
  BrainCircuit,
  ClipboardCheck,
  ExternalLink,
  Eye,
  FileText,
  Globe,
  House,
  TriangleAlert,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { HudMessage } from "@/hooks/useJeannieChat";
import { formatClock } from "@/hooks/useNow";
import type { AgentId, SourceLink } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Markdown, safeHref } from "./Markdown";

export const AGENT_META: Record<AgentId, { label: string; ko: string; icon: LucideIcon; tone: string }> = {
  iot: { label: "IOT", ko: "스마트홈", icon: House, tone: "border-neon bg-neon/25 text-white" },
  search: { label: "SEARCH", ko: "실시간 검색", icon: Globe, tone: "border-neon-hot/70 bg-neon-hot/15 text-neon-hot" },
  vision: { label: "VISION", ko: "비전", icon: Eye, tone: "border-petal/70 bg-petal/15 text-petal-soft" },
  hangeul: {
    label: "HANGEUL",
    ko: "한글 데이터",
    icon: FileText,
    tone: "border-neon-deep/70 bg-neon-deep/15 text-petal-soft",
  },
  audit: {
    label: "AUDIT",
    ko: "실수 점검",
    icon: ClipboardCheck,
    tone: "border-neon-hot/70 bg-neon-hot/10 text-petal-soft",
  },
  core: { label: "CORE", ko: "코어", icon: BrainCircuit, tone: "border-neon/60 bg-neon/10 text-neon-hot" },
  offline: {
    label: "OFFLINE",
    ko: "오프라인",
    icon: WifiOff,
    tone: "border-petal-soft/30 bg-petal-soft/5 text-petal-soft/70",
  },
};

export function AgentBadge({ agent, className }: { agent: AgentId; className?: string }) {
  const meta = AGENT_META[agent];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-[0.6rem] font-semibold tracking-[0.16em]",
        meta.tone,
        className,
      )}
      title={`${meta.label} agent · ${meta.ko}`}
    >
      <Icon aria-hidden="true" className="h-3 w-3" />
      {meta.label}
    </span>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function SourcesList({ sources }: { sources: SourceLink[] }) {
  return (
    <div className="mt-3 border-t border-neon/20 pt-2">
      <p className="hud-label mb-1.5">Sources · 출처</p>
      <ol className="space-y-1">
        {sources.map((source, index) => {
          const href = safeHref(source.url);
          if (!href) return null;
          return (
            <li key={`${href}-${index}`}>
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex min-h-[40px] items-center gap-2 rounded px-1.5 py-1 text-[0.78rem] transition-colors hover:bg-neon/10 lg:min-h-[32px]"
              >
                <span className="shrink-0 font-mono text-[0.68rem] text-neon-hot">[{index + 1}]</span>
                <span className="min-w-0 flex-1 truncate text-petal-soft group-hover:text-white">{source.title}</span>
                <span className="hidden shrink-0 font-mono text-[0.62rem] text-petal/70 sm:inline">{hostOf(href)}</span>
                <ExternalLink aria-hidden="true" className="h-3 w-3 shrink-0 text-petal/70" />
              </a>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div
      className="flex items-center gap-2 py-1 font-mono text-[0.72rem] tracking-[0.18em] text-neon-hot"
      aria-label="Jeannie is analyzing"
    >
      <span className="flex h-3 items-end gap-[3px]" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <motion.span
            key={i}
            className="w-[3px] rounded-sm bg-neon shadow-glow-sm"
            animate={{ height: ["25%", "100%", "25%"] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.12, ease: "easeInOut" }}
          />
        ))}
      </span>
      ANALYZING · 분석 중
    </div>
  );
}

function Timestamp({ at }: { at: number }) {
  return (
    <time
      dateTime={new Date(at).toISOString()}
      className="font-mono text-[0.62rem] tracking-[0.12em] text-petal-soft/55"
    >
      {formatClock(new Date(at))}
    </time>
  );
}

const entrance = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] as const },
};

function MessageViewImpl({ message }: { message: HudMessage }) {
  if (message.role === "system") {
    return (
      <motion.div
        {...entrance}
        role="alert"
        className="flex items-start gap-2 rounded border border-dashed border-neon-hot/50 bg-neon/5 px-3 py-2 font-mono text-[0.74rem] leading-relaxed text-petal-soft"
      >
        <TriangleAlert aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-neon-hot" />
        <span className="min-w-0 break-words">
          <span className="text-neon-hot">SYS //</span> {message.content}
        </span>
      </motion.div>
    );
  }

  if (message.role === "user") {
    return (
      <motion.article {...entrance} className="flex justify-end" aria-label="Your message">
        <div className="max-w-[88%] rounded-md rounded-tr-none border border-neon/40 bg-gradient-to-br from-neon/20 to-neon/5 px-3 py-2 shadow-inner-glow">
          <header className="mb-1 flex items-center justify-end gap-2">
            <Timestamp at={message.createdAt} />
            <span className="font-display text-[0.6rem] font-semibold tracking-[0.22em] text-petal">OPERATOR</span>
          </header>
          {message.image ? (
            // Data-URL thumbnails of the operator's own capture; next/image adds nothing here.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={message.image}
              alt="Attached image"
              className="mb-2 max-h-44 w-auto max-w-full rounded border border-neon/40 object-cover"
            />
          ) : null}
          <p className="whitespace-pre-wrap break-words text-[0.9rem] leading-relaxed text-white [overflow-wrap:anywhere]">
            {message.content}
          </p>
        </div>
      </motion.article>
    );
  }

  const streaming = message.status === "streaming";
  return (
    <motion.article {...entrance} className="flex gap-2.5" aria-label="Jeannie's reply" aria-busy={streaming}>
      <span
        aria-hidden="true"
        className="mt-0.5 h-7 w-7 shrink-0 rounded-full border border-neon/60 bg-[radial-gradient(circle,#fff_0%,#FF69B4_28%,#FF1493_52%,#FF007F_70%,transparent_72%)] shadow-glow-sm"
      />
      <div className="min-w-0 flex-1">
        <header className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-display text-[0.66rem] font-semibold tracking-[0.24em] text-neon-hot text-glow-soft">
            JEANNIE
          </span>
          {message.agent ? <AgentBadge agent={message.agent} /> : null}
          <Timestamp at={message.createdAt} />
          {typeof message.latencyMs === "number" ? (
            <span className="font-mono text-[0.62rem] text-petal-soft/55">
              {(message.latencyMs / 1000).toFixed(2)}s
            </span>
          ) : null}
        </header>
        <div className="text-petal-soft">
          {message.content ? (
            <Markdown
              text={message.content}
              sources={message.sources}
              tail={streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
            />
          ) : (
            <ThinkingIndicator />
          )}
        </div>
        {message.status === "stopped" ? (
          <p className="mt-1.5 font-mono text-[0.62rem] tracking-[0.18em] text-petal/70">
            ■ TRANSMISSION HALTED · 중단됨
          </p>
        ) : null}
        {message.sources && message.sources.length > 0 && !streaming ? <SourcesList sources={message.sources} /> : null}
      </div>
    </motion.article>
  );
}

export const ChatMessageView = memo(MessageViewImpl);
