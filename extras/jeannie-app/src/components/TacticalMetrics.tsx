"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Activity, Cpu, FileText, House, RefreshCw, Send } from "lucide-react";
import type { ChatTelemetry } from "@/hooks/useJeannieChat";
import { formatClock, formatDuration, useNow } from "@/hooks/useNow";
import { ApiRequestError, fetchHangeulData, isAbortError } from "@/lib/client/api";
import { OFFLINE_LINE } from "@/lib/client/reachability";
import type { HangeulDataStatus, HangeulRunSummary, LangMode, ResolvedLang, SystemStatus, TtsEngine } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgentBadge } from "./ChatMessageView";
import { HudPanel } from "./HudPanel";
import { IoTControlGrid } from "./IoTControlGrid";

type Led = "on" | "warn" | "idle" | "off";

const LED_CLASS: Record<Led, string> = { on: "led-on", warn: "led-warn", idle: "led-idle", off: "" };

const PROVIDER_LABEL: Record<string, string> = { deepseek: "DeepSeek", tavily: "Tavily", google: "Google", duckduckgo: "DDG" };
const ENGINE_SHORT: Record<TtsEngine, string> = { elevenlabs: "11LABS", edge: "EDGE", browser: "BROWSER" };
const VOICE_ROW_LABEL: Record<TtsEngine, string> = { elevenlabs: "11Labs", edge: "Edge", browser: "Browser" };
const LANG_SHORT: Record<ResolvedLang, string> = { en: "EN", ko: "KO", bilingual: "EN+KO" };

function StatusRow({
  label,
  ko,
  value,
  led,
  title,
}: {
  label: string;
  ko: string;
  value: string;
  led: Led;
  title?: string;
}) {
  return (
    <li className="flex min-h-[23px] items-center gap-2.5 py-[2px]">
      <span className={cn("led", LED_CLASS[led])} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block font-mono text-[0.62rem] tracking-[0.16em] text-petal-soft/70">
          {label} <span className="tracking-normal text-petal-soft/45">{ko}</span>
        </span>
      </span>
      <span className="max-w-[60%] truncate text-right font-mono text-[0.7rem] text-petal-soft" title={title ?? value}>
        {value}
      </span>
    </li>
  );
}

function SystemStatusPanel({
  status,
  loading,
  error,
  onRetry,
  hasAccessKey,
}: {
  status: SystemStatus | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  hasAccessKey: boolean;
}) {
  const retry = (
    <button
      type="button"
      onClick={onRetry}
      aria-label="Refresh system status"
      title="Refresh"
      className="hud-btn -my-1 border-transparent bg-transparent lg:h-8 lg:min-h-0 lg:w-8 lg:min-w-0"
    >
      <RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
    </button>
  );

  let body;
  if (status) {
    const llmOnline = status.llm.provider !== "none";
    const serverVoice = status.voice.engines.some((e) => e !== "browser");
    body = (
      <ul className="divide-y divide-neon/10">
        <StatusRow
          label="NEURAL CORE"
          ko="코어"
          value={llmOnline ? `${status.llm.provider.toUpperCase()} · ${status.llm.model ?? "default"}` : "OFFLINE MODE"}
          title={
            llmOnline
              ? status.llm.visionProvider !== "none"
                ? `Vision: ${status.llm.visionProvider} · ${status.llm.visionModel ?? "default"}`
                : "Vision: off (no vision-capable model connected)"
              : "No LLM configured"
          }
          led={llmOnline ? "on" : "warn"}
        />
        <StatusRow
          label="LIVE SEARCH"
          ko="검색"
          value={status.search.providers.map((p) => PROVIDER_LABEL[p] ?? p).join(" · ") || "NONE"}
          led={status.search.providers.length > 1 ? "on" : status.search.providers.length ? "idle" : "off"}
        />
        <StatusRow
          label="VOICE"
          ko="음성"
          value={status.voice.engines.map((e) => VOICE_ROW_LABEL[e]).join(" · ")}
          led={serverVoice ? "on" : "idle"}
        />
        <StatusRow
          label="MEMORY"
          ko="기억"
          value={status.memory.configured ? "SUPABASE" : "NOT LINKED"}
          led={status.memory.configured ? "on" : "off"}
        />
        <StatusRow
          label="TELEGRAM"
          ko="텔레그램"
          value={status.telegram.configured ? "LINKED" : "NOT LINKED"}
          led={status.telegram.configured ? "on" : "off"}
        />
        <StatusRow
          label="HANGEUL"
          ko="한글"
          value={
            !status.hangeul.configured
              ? "NOT LINKED"
              : status.hangeul.records !== null
                ? `DATA · ${status.hangeul.records.toLocaleString("en-US")}`
                : "DATA LINKED"
          }
          title={
            status.hangeul.lastRuns?.length
              ? `Latest runs: ${status.hangeul.lastRuns.map((r) => `${jobName(r.job)} ${clockOf(r.finishedAt)} (${r.status ?? "?"})`).join(", ")}`
              : status.hangeul.configured
                ? "Hangeul BOT's data in Supabase"
                : "Set SUPABASE_URL and SUPABASE_SECRET_KEY"
          }
          led={status.hangeul.configured ? "on" : "off"}
        />
        <StatusRow
          label="ACCESS"
          ko="보안"
          value={status.accessKeyRequired ? (hasAccessKey ? "KEY LOADED" : "KEY REQUIRED") : "OPEN"}
          led={status.accessKeyRequired ? (hasAccessKey ? "on" : "warn") : "idle"}
        />
      </ul>
    );
  } else if (loading) {
    body = (
      <ul className="space-y-2.5 py-1" aria-label="Loading system status">
        {Array.from({ length: 5 }, (_, i) => (
          <li key={i} className="flex items-center gap-2.5">
            <span className="led" aria-hidden="true" />
            <span
              className="h-2 flex-1 animate-pulse rounded-sm bg-neon/15"
              style={{ animationDelay: `${i * 120}ms` }}
            />
          </li>
        ))}
      </ul>
    );
  } else {
    body = (
      <div className="space-y-2 py-1">
        <p className="flex items-center gap-2 font-mono text-[0.7rem] tracking-[0.14em] text-neon-hot">
          <span className="led led-warn" aria-hidden="true" />
          STATUS FEED OFFLINE
        </p>
        <p className="text-[0.78rem] leading-relaxed text-petal-soft/75">{error ?? "No response from /api/status."}</p>
      </div>
    );
  }

  return (
    <HudPanel title="System Status" subtitle="시스템" icon={<Cpu />} actions={retry} delay={0.05}>
      {body}
    </HudPanel>
  );
}

function Readout({ label, value, wide }: { label: string; value: ReactNode; wide?: boolean }) {
  return (
    <div className={cn("min-w-0 rounded border border-neon/15 bg-void/40 px-2 py-[3px]", wide && "col-span-2")}>
      <dt className="truncate font-mono text-[0.56rem] uppercase tracking-[0.14em] text-petal-soft/60">{label}</dt>
      <dd className="mt-0.5 truncate font-mono text-[0.8rem] tabular-nums text-white">{value}</dd>
    </div>
  );
}

function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`;
}

function TelemetryPanel({
  telemetry,
  messageCount,
  voiceEngine,
  replyLang,
  sessionStart,
}: {
  telemetry: ChatTelemetry;
  messageCount: number;
  voiceEngine: TtsEngine | null;
  replyLang: ResolvedLang | null;
  sessionStart: number | null;
}) {
  const now = useNow(1000);
  const placeholder = "--:--:--";
  return (
    <HudPanel title="Telemetry" subtitle="원격 측정" icon={<Activity />} delay={0.2}>
      <dl className="grid grid-cols-3 gap-1.5 lg:grid-cols-2 xl:grid-cols-3">
        <Readout label="Local" value={now ? formatClock(now) : placeholder} />
        <Readout label="Seoul KST" value={now ? formatClock(now, "Asia/Seoul") : placeholder} />
        <Readout
          label="Uptime"
          value={now && sessionStart ? formatDuration(now.getTime() - sessionStart) : placeholder}
        />
        <Readout label="Latency" value={formatMs(telemetry.lastLatencyMs)} />
        <Readout label="First byte" value={formatMs(telemetry.lastTtfbMs)} />
        <Readout label="Messages" value={messageCount} />
        <Readout
          label="Agent"
          value={
            telemetry.activeAgent ? <AgentBadge agent={telemetry.activeAgent} className="align-middle" /> : "STANDBY"
          }
        />
        <Readout label="Voice" value={voiceEngine ? ENGINE_SHORT[voiceEngine] : "—"} />
        <Readout label="Reply lang" value={replyLang ? LANG_SHORT[replyLang] : "—"} />
      </dl>
    </HudPanel>
  );
}

const JOB_NAME: Record<string, string> = {
  full_picture: "Full picture",
  portal_sync: "Portal sync",
  passport_watcher: "Passport watcher",
  backfill: "Backfill",
  daily_brief: "Brief",
  missing_report: "Missing report",
  issue_refresh: "Issue refresh",
  stage_report: "Stage report",
  command: "Command",
};

function jobName(job: string): string {
  return JOB_NAME[job] ?? job.replace(/_/g, " ");
}

/** "missing_report" → "Missing report", "stage_report:KLP:MARCH 2027" → "Stage report". */
function reportName(report: string): string {
  const base = report.split(":")[0].replace(/_/g, " ");
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/** "23:35" today, "30 Sep 23:35" on another day (the browser's own time zone). */
function clockOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? time : `${date.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${time}`;
}

function HangeulPanel({
  configured,
  onReport,
  statusReady,
  hasAccessKey,
  locked,
  offline = false,
}: {
  /** Whether the server has the Supabase project Hangeul BOT publishes to (null until /api/status answers). */
  configured: boolean | null;
  onReport: () => void;
  /** Offline (spec D10): DAILY REPORT cannot be sent, so it is disabled. */
  offline?: boolean;
  statusReady: boolean;
  /** The API needs a key and none is stored: skip the request that would 401. */
  locked: boolean;
  /** Re-reads the data status once a key is entered. */
  hasAccessKey: boolean;
}) {
  const [data, setData] = useState<HangeulDataStatus | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);

  useEffect(() => {
    if (!statusReady || configured === null) return;
    if (!configured) {
      setData(null);
      setDataError("Not linked: set SUPABASE_URL and SUPABASE_SECRET_KEY.");
      return;
    }
    if (locked) {
      setData(null);
      setDataError("Locked: access key required.");
      return;
    }
    const controller = new AbortController();
    fetchHangeulData(controller.signal)
      .then((next) => {
        setData(next);
        setDataError(null);
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setData(null);
        setDataError(
          error instanceof ApiRequestError && error.needsAccessKey
            ? "Locked: access key required."
            : error instanceof ApiRequestError && error.code === "access_key_not_configured"
              ? "Set JEANNIE_ACCESS_KEY: the data holds student records."
              : "Hangeul data unreachable.",
        );
      });
    return () => controller.abort();
  }, [statusReady, configured, hasAccessKey, locked]);

  const newest = data?.lastRuns.reduce<HangeulRunSummary | null>((a, r) => (!a || r.finishedAt > a.finishedAt ? r : a), null) ?? null;
  const brief = data?.latestBrief;
  // The latest brief is what DAILY REPORT shows; until the bot has sent one, name its latest report instead.
  const report = brief ?? data?.latestReport ?? null;
  const reportText = report
    ? `${brief ? "Brief" : `No brief yet · ${reportName(report.report)}`} ${clockOf(report.read_at)}`
    : "No brief yet";
  const detail = data
    ? `${reportText}${newest ? ` · ${jobName(newest.job)} ${clockOf(newest.finishedAt)}` : ""}`
    : (dataError ?? "Hangeul BOT's data in Supabase");
  const runsTitle = data?.lastRuns.map((r) => `${jobName(r.job)}: ${clockOf(r.finishedAt)} (${r.status ?? "?"})`).join("\n");
  return (
    <HudPanel title="Hangeul Data" subtitle="한글 데이터" icon={<FileText />} delay={0.3}>
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="flex items-center gap-1.5 whitespace-nowrap font-mono text-[0.66rem] tracking-[0.12em] text-petal-soft">
            <span
              className={cn("led", data ? (newest?.status === "failed" ? "led-warn" : "led-on") : dataError ? "led-warn" : "")}
              aria-hidden="true"
            />
            {data ? "DATA LINKED" : dataError ? (configured === false ? "NOT LINKED" : "NO SIGNAL") : "CHECKING…"}
            {data ? (
              <span className="rounded-sm border border-neon/30 px-1 text-[0.58rem] text-neon-hot">
                {data.records.toLocaleString("en-US")} RECORDS
              </span>
            ) : null}
          </p>
          <p className="truncate text-[0.7rem] text-petal-soft/65" title={runsTitle || dataError || undefined}>
            {detail}
          </p>
        </div>
        <button
          type="button"
          onClick={onReport}
          disabled={offline}
          title={offline ? OFFLINE_LINE.en : undefined}
          aria-label="Ask Jeannie for the Hangeul daily brief"
          className="hud-btn hud-btn-primary shrink-0 px-2.5 font-mono text-[0.64rem] tracking-[0.12em]"
        >
          <Send aria-hidden="true" className="h-3.5 w-3.5" />
          DAILY REPORT
        </button>
      </div>
    </HudPanel>
  );
}

interface TacticalMetricsProps {
  status: SystemStatus | null;
  statusLoading: boolean;
  statusError: string | null;
  onRetryStatus: () => void;
  hasAccessKey: boolean;
  lang: LangMode;
  /** Sends a command through the chat; false when it was not sent (offline). */
  onCommand: (command: string) => boolean | void;
  /** Offline (spec D10): the smart-home tiles and DAILY REPORT are disabled, like the composer. */
  offline?: boolean;
  telemetry: ChatTelemetry;
  messageCount: number;
  voiceEngine: TtsEngine | null;
  replyLang: ResolvedLang | null;
  sessionStart: number | null;
  className?: string;
  /** Extra panels at the bottom of the column (the memory panel). */
  children?: ReactNode;
}

/** Left HUD column: capabilities, smart-home tiles, telemetry and the Hangeul data. */
export function TacticalMetrics({
  status,
  statusLoading,
  statusError,
  onRetryStatus,
  hasAccessKey,
  lang,
  onCommand,
  offline = false,
  telemetry,
  messageCount,
  voiceEngine,
  replyLang,
  sessionStart,
  className,
  children,
}: TacticalMetricsProps) {
  return (
    <div className={cn("flex flex-col gap-2.5", className)}>
      <SystemStatusPanel
        status={status}
        loading={statusLoading}
        error={statusError}
        onRetry={onRetryStatus}
        hasAccessKey={hasAccessKey}
      />
      <HudPanel title="Smart Home" subtitle="스마트홈" icon={<House />} delay={0.12}>
        <IoTControlGrid lang={lang} onCommand={onCommand} offline={offline} offlineText={OFFLINE_LINE.en} />
      </HudPanel>
      <TelemetryPanel
        telemetry={telemetry}
        messageCount={messageCount}
        voiceEngine={voiceEngine}
        replyLang={replyLang}
        sessionStart={sessionStart}
      />
      <HangeulPanel
        configured={status ? status.hangeul.configured : null}
        statusReady={!statusLoading}
        hasAccessKey={hasAccessKey}
        locked={Boolean(status?.accessKeyRequired) && !hasAccessKey}
        offline={offline}
        onReport={() => onCommand("Hangeul daily report")}
      />
      {children}
    </div>
  );
}
