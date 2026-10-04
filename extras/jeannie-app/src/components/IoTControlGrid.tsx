"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  AirVent,
  DoorClosed,
  DoorOpen,
  Fan,
  Lightbulb,
  Minus,
  Plus,
  Thermometer,
  Tv,
  type LucideIcon,
} from "lucide-react";
import type { LangMode } from "@/lib/types";
import { cn } from "@/lib/utils";

// Simulated smart-home tiles. Each tap sends the matching natural-language
// command through the normal chat flow, where the IoT Interceptor confirms it
// ("Yes, it is done." / "네, 처리되었습니다."), and flips the tile once it was
// sent. Offline (spec D10) the tiles and the thermostat are disabled.

type ToggleId = "lights" | "door" | "ac" | "fan" | "tv";

interface ToggleDevice {
  id: ToggleId;
  name: string;
  ko: string;
  icon: LucideIcon;
  offIcon?: LucideIcon;
  onLabel: string;
  offLabel: string;
  command: (on: boolean, korean: boolean) => string;
}

const TOGGLES: ToggleDevice[] = [
  {
    id: "lights",
    name: "Living Room Lights",
    ko: "거실 조명",
    icon: Lightbulb,
    onLabel: "ON",
    offLabel: "OFF",
    command: (on, ko) =>
      ko
        ? on
          ? "거실 불 켜줘"
          : "거실 불 꺼줘"
        : on
          ? "Turn on the living room lights"
          : "Turn off the living room lights",
  },
  {
    id: "door",
    name: "Front Door Lock",
    ko: "현관 도어락",
    icon: DoorClosed,
    offIcon: DoorOpen,
    onLabel: "LOCKED",
    offLabel: "OPEN",
    command: (on, ko) =>
      ko ? (on ? "현관문 잠가줘" : "현관문 잠금 해제해줘") : on ? "Lock the front door" : "Unlock the front door",
  },
  {
    id: "ac",
    name: "Air Conditioner",
    ko: "에어컨",
    icon: AirVent,
    onLabel: "COOL",
    offLabel: "OFF",
    command: (on, ko) =>
      ko ? (on ? "에어컨 켜줘" : "에어컨 꺼줘") : on ? "Turn on the air conditioner" : "Turn off the air conditioner",
  },
  {
    id: "fan",
    name: "Fan",
    ko: "선풍기",
    icon: Fan,
    onLabel: "ON",
    offLabel: "OFF",
    command: (on, ko) => (ko ? (on ? "선풍기 켜줘" : "선풍기 꺼줘") : on ? "Turn on the fan" : "Turn off the fan"),
  },
  {
    id: "tv",
    name: "TV",
    ko: "텔레비전",
    icon: Tv,
    onLabel: "ON",
    offLabel: "OFF",
    command: (on, ko) => (ko ? (on ? "TV 켜줘" : "TV 꺼줘") : on ? "Turn on the TV" : "Turn off the TV"),
  },
];

export function thermostatCommand(celsius: number, korean: boolean): string {
  return korean ? `온도를 ${celsius}도로 맞춰줘` : `Set the thermostat to ${celsius}°C`;
}

/**
 * The tiles show what was sent: a tile flips only when its command went out.
 * `send` returns false when nothing was sent (offline); the same state object
 * then comes back, so the tile keeps its state.
 */
export function sendToggle<T extends string>(
  on: Readonly<Record<T, boolean>>,
  id: T,
  command: (next: boolean) => string,
  send: (command: string) => boolean | void,
): Readonly<Record<T, boolean>> {
  const next = !on[id];
  return send(command(next)) === false ? on : { ...on, [id]: next };
}

const MIN_TEMP = 16;
const MAX_TEMP = 30;
const THERMOSTAT_DEBOUNCE_MS = 700;

interface IoTControlGridProps {
  lang: LangMode;
  /** Sends the command through the chat; false when it was not sent (offline), so the tile does not flip. */
  onCommand: (command: string) => boolean | void;
  /** Offline (spec D10): nothing can be sent, so every tile and the thermostat are disabled. */
  offline?: boolean;
  /** Why the controls are disabled (the offline line), as their tooltip. */
  offlineText?: string;
}

const tileBase =
  "relative flex min-h-[70px] min-w-0 flex-col justify-between gap-1 overflow-hidden rounded-md border p-2 text-left transition-colors";

export function IoTControlGrid({ lang, onCommand, offline = false, offlineText }: IoTControlGridProps) {
  const [on, setOn] = useState<Record<ToggleId, boolean>>({
    lights: true,
    door: true,
    ac: false,
    fan: false,
    tv: false,
  });
  const [temp, setTemp] = useState(22);
  const tempTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** The last thermostat setting that was sent: shown again when a debounced send finds the HUD offline. */
  const sentTemp = useRef(22);
  const korean = lang === "ko";

  useEffect(
    () => () => {
      if (tempTimer.current) clearTimeout(tempTimer.current);
    },
    [],
  );

  const toggle = (device: ToggleDevice) => {
    if (offline) return;
    const next = sendToggle(on, device.id, (value) => device.command(value, korean), onCommand);
    if (next !== on) setOn(next);
  };

  // Rapid +/- taps settle into a single command.
  const nudge = (delta: number) => {
    if (offline) return;
    const next = Math.min(MAX_TEMP, Math.max(MIN_TEMP, temp + delta));
    if (next === temp) return;
    setTemp(next);
    if (tempTimer.current) clearTimeout(tempTimer.current);
    tempTimer.current = setTimeout(() => {
      if (onCommand(thermostatCommand(next, korean)) === false) setTemp(sentTemp.current);
      else sentTemp.current = next;
    }, THERMOSTAT_DEBOUNCE_MS);
  };

  const renderToggle = (device: ToggleDevice, span: string) => {
    const active = on[device.id];
    const Icon = !active && device.offIcon ? device.offIcon : device.icon;
    return (
      <motion.button
        key={device.id}
        type="button"
        whileTap={offline ? undefined : { scale: 0.97 }}
        onClick={() => toggle(device)}
        disabled={offline}
        title={offline ? offlineText : undefined}
        aria-pressed={active}
        aria-label={`${device.name}: ${active ? device.onLabel : device.offLabel}. Tap to ${active ? "switch off" : "switch on"}.`}
        className={cn(
          tileBase,
          span,
          active
            ? "border-neon/80 bg-gradient-to-br from-neon/25 to-neon/5 shadow-[0_0_18px_rgba(255,0,127,0.35),inset_0_0_14px_rgba(255,0,127,0.2)]"
            : "border-neon/20 bg-void/50 hover:border-neon/50 hover:bg-neon/5",
          offline && "cursor-not-allowed opacity-50",
        )}
      >
        <span className="flex items-center justify-between gap-1">
          <Icon
            aria-hidden="true"
            className={cn(
              "h-5 w-5 shrink-0 transition-colors",
              active ? "text-white drop-shadow-[0_0_6px_rgba(255,0,127,0.9)]" : "text-petal-soft/60",
              active && device.id === "fan" && "animate-spin [animation-duration:1.6s]",
            )}
          />
          <span
            className={cn(
              "font-mono text-[0.58rem] tracking-[0.12em]",
              active ? "text-neon-hot text-glow-soft" : "text-petal-soft/50",
            )}
          >
            {active ? device.onLabel : device.offLabel}
          </span>
        </span>
        <span className="min-w-0">
          <span className="line-clamp-2 block text-[0.72rem] font-medium leading-tight text-petal-soft">
            {device.name}
          </span>
          <span className="block truncate text-[0.64rem] text-petal-soft/60">{device.ko}</span>
        </span>
      </motion.button>
    );
  };

  return (
    <div className="space-y-2">
      <div
        role="group"
        aria-label={`Thermostat, ${temp} degrees Celsius`}
        className="flex items-center justify-between gap-2 rounded-md border border-neon/60 bg-gradient-to-r from-neon/15 via-neon/5 to-transparent p-1.5 pl-2.5"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Thermometer
            aria-hidden="true"
            className="h-5 w-5 shrink-0 text-neon-hot drop-shadow-[0_0_6px_rgba(255,0,127,0.7)]"
          />
          <span className="min-w-0 leading-tight">
            <span className="block truncate text-[0.72rem] font-medium text-petal-soft">Thermostat</span>
            <span className="block truncate text-[0.64rem] text-petal-soft/60">온도 조절기</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => nudge(-1)}
            disabled={offline || temp <= MIN_TEMP}
            title={offline ? offlineText : undefined}
            aria-label="Lower thermostat by one degree"
            className="hud-btn h-10 w-10 min-w-0 p-0"
          >
            <Minus aria-hidden="true" className="h-4 w-4" />
          </button>
          <output
            aria-live="polite"
            className="w-[3.4rem] text-center font-display text-base font-semibold tabular-nums text-white text-glow"
          >
            {temp}°C
          </output>
          <button
            type="button"
            onClick={() => nudge(1)}
            disabled={offline || temp >= MAX_TEMP}
            title={offline ? offlineText : undefined}
            aria-label="Raise thermostat by one degree"
            className="hud-btn h-10 w-10 min-w-0 p-0"
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
          </button>
        </span>
      </div>
      {/* Six-column track: three tiles on the first row, two wider ones on the second. */}
      <div className="grid grid-cols-6 gap-2">
        {TOGGLES.map((device, index) => renderToggle(device, index < 3 ? "col-span-2" : "col-span-3"))}
      </div>
    </div>
  );
}
