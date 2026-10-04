"use client";

import { useEffect, useMemo, useRef } from "react";
import { useReducedMotion } from "framer-motion";
import { useCanvasLoop, type CanvasFrame } from "@/hooks/useCanvasLoop";
import { cn } from "@/lib/utils";

export type OrbState = "standby" | "listening" | "analyzing" | "speaking";

interface HologramOrbProps {
  state: OrbState;
  /** Audio level 0..1 (voice output or input activity). */
  level: number;
  className?: string;
}

/** How each state drives the reactor. Values are eased toward, never jumped to. */
interface Profile {
  speed: number; // ring rotation multiplier
  energy: number; // overall brightness
  sweep: number; // radar sweep visibility
  ripple: number; // expanding "listening" ripples
  wave: number; // soundwave ring deformation
}

const PROFILES: Record<OrbState, Profile> = {
  standby: { speed: 0.3, energy: 0.55, sweep: 0, ripple: 0, wave: 0.12 },
  listening: { speed: 0.75, energy: 0.82, sweep: 0, ripple: 1, wave: 0.55 },
  analyzing: { speed: 2.3, energy: 0.92, sweep: 1, ripple: 0, wave: 0.3 },
  speaking: { speed: 1.05, energy: 1, sweep: 0, ripple: 0.3, wave: 1 },
};

const TAU = Math.PI * 2;
const PINK = "255, 0, 127";
const DEEP = "255, 20, 147";
const HOT = "255, 105, 180";
const SOFT = "251, 207, 232";
const rgba = (rgb: string, alpha: number) => `rgba(${rgb}, ${Math.max(0, Math.min(1, alpha)).toFixed(3)})`;

interface Particle {
  radius: number;
  angle: number;
  speed: number;
  size: number;
  phase: number;
}

function makeParticles(count: number): Particle[] {
  let seed = 1337; // deterministic layout: the orb looks the same on every load
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  return Array.from({ length: count }, () => ({
    radius: 0.34 + rand() * 0.64,
    angle: rand() * TAU,
    speed: (0.12 + rand() * 0.55) * (rand() > 0.35 ? 1 : -1),
    size: 0.5 + rand() * 1.5,
    phase: rand() * TAU,
  }));
}

interface AnimState extends Profile {
  level: number;
  rot: number;
}

function strokeCircle(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.stroke();
}

function drawReactor(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: number,
  s: AnimState,
  particles: Particle[],
  monoFont: string,
) {
  const cx = width / 2;
  const cy = height / 2;
  const R = (Math.min(width, height) / 2) * 0.94;
  if (R < 8) return;
  const { energy: e, level: lvl, rot } = s;
  const pulse = 0.5 + 0.5 * Math.sin(time * (1.3 + s.speed * 0.7));

  ctx.clearRect(0, 0, width, height);

  // Ambient halo.
  const halo = ctx.createRadialGradient(cx, cy, R * 0.08, cx, cy, R);
  halo.addColorStop(0, rgba(PINK, 0.26 * e + lvl * 0.22));
  halo.addColorStop(0.42, rgba(DEEP, 0.08 * e + lvl * 0.08));
  halo.addColorStop(1, rgba(PINK, 0));
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(cx, cy, R, 0, TAU);
  ctx.fill();

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.lineCap = "round";

  // Radar sweep while analyzing.
  if (s.sweep > 0.01) {
    const lead = rot * 2.1;
    const span = 1.2;
    const slices = 30;
    for (let i = 0; i < slices; i++) {
      const a = lead - (i / slices) * span;
      ctx.fillStyle = rgba(PINK, 0.24 * s.sweep * (1 - i / slices) ** 1.5);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, R * 0.93, a - span / slices, a);
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = rgba(SOFT, 0.85 * s.sweep);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(lead) * R * 0.3, cy + Math.sin(lead) * R * 0.3);
    ctx.lineTo(cx + Math.cos(lead) * R * 0.93, cy + Math.sin(lead) * R * 0.93);
    ctx.stroke();
  }

  // Expanding ripples while listening.
  if (s.ripple > 0.01) {
    for (let i = 0; i < 3; i++) {
      const p = (time * 0.5 + i / 3) % 1;
      ctx.strokeStyle = rgba(HOT, (1 - p) ** 1.5 * 0.5 * s.ripple);
      ctx.lineWidth = 1.4 + (1 - p) * 1.4;
      strokeCircle(ctx, cx, cy, R * (0.3 + p * 0.68));
    }
  }

  // Outer frame: thin ring, four rotating bracket arcs, cardinal notches and bearings.
  ctx.lineWidth = 1;
  ctx.strokeStyle = rgba(PINK, 0.26 + 0.12 * e);
  strokeCircle(ctx, cx, cy, R * 0.95);
  ctx.lineWidth = Math.max(1.5, R * 0.012);
  for (let k = 0; k < 4; k++) {
    const a = rot * 0.12 + (k * TAU) / 4 + Math.PI / 4;
    ctx.strokeStyle = rgba(HOT, 0.55 + 0.35 * e);
    ctx.beginPath();
    ctx.arc(cx, cy, R * 0.985, a - 0.2, a + 0.2);
    ctx.stroke();
  }
  const fontSize = Math.max(8, Math.round(R * 0.042));
  ctx.font = `500 ${fontSize}px ${monoFont}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ["000", "090", "180", "270"].forEach((label, k) => {
    const a = (k * TAU) / 4 - Math.PI / 2;
    const x = cx + Math.cos(a) * R * 0.9;
    const y = cy + Math.sin(a) * R * 0.9;
    ctx.fillStyle = rgba(SOFT, 0.5 + 0.2 * e);
    ctx.fillText(label, x, y);
    ctx.fillStyle = rgba(HOT, 0.8);
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * R * 0.95, cy + Math.sin(a) * R * 0.95, Math.max(1.5, R * 0.008), 0, TAU);
    ctx.fill();
  });

  // Tick ring with a travelling highlight.
  const ticks = 120;
  const tickOuter = R * 0.845;
  ctx.lineWidth = 1;
  for (let i = 0; i < ticks; i++) {
    const a = (i / ticks) * TAU - rot * 0.22;
    const long = i % 10 === 0;
    const mid = i % 5 === 0;
    const len = long ? R * 0.055 : mid ? R * 0.034 : R * 0.018;
    const highlight = Math.max(0, Math.cos(a - rot * 1.1)) ** 10;
    ctx.strokeStyle = rgba(long ? HOT : PINK, 0.18 + 0.2 * e + highlight * 0.65);
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * tickOuter, cy + Math.sin(a) * tickOuter);
    ctx.lineTo(cx + Math.cos(a) * (tickOuter - len), cy + Math.sin(a) * (tickOuter - len));
    ctx.stroke();
  }

  // Soundwave ring: deforms with the audio level.
  const waveBase = R * 0.72;
  const amp = R * (0.008 + s.wave * (0.016 + lvl * 0.13));
  const points = 180;
  for (let pass = 0; pass < 2; pass++) {
    const phase = pass * 1.7;
    ctx.beginPath();
    for (let i = 0; i <= points; i++) {
      const th = (i / points) * TAU;
      const envelope = 0.55 + 0.45 * Math.sin(th * 3 + time * 0.9 + phase);
      const offset =
        Math.sin(th * 6 + time * 3.1 + phase) * 0.5 +
        Math.sin(th * 11 - time * 4.4 + phase) * 0.3 +
        Math.sin(th * 19 + time * 7.3) * 0.2;
      const r = waveBase + offset * amp * envelope;
      const x = cx + Math.cos(th) * r;
      const y = cy + Math.sin(th) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = pass === 0 ? rgba(HOT, 0.5 + 0.35 * e + lvl * 0.2) : rgba(DEEP, 0.28 + lvl * 0.3);
    ctx.lineWidth = pass === 0 ? 1.6 : 1;
    ctx.stroke();
  }

  // Segmented ring (three long arcs) plus a counter-rotating dashed ring.
  ctx.lineWidth = Math.max(2, R * 0.02);
  for (let k = 0; k < 3; k++) {
    const a = rot * 0.9 + (k * TAU) / 3;
    ctx.strokeStyle = rgba(PINK, 0.5 + 0.35 * e);
    ctx.beginPath();
    ctx.arc(cx, cy, R * 0.6, a, a + TAU / 3 - 0.32);
    ctx.stroke();
    ctx.fillStyle = rgba(SOFT, 0.85);
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * R * 0.6, cy + Math.sin(a) * R * 0.6, Math.max(1.5, R * 0.011), 0, TAU);
    ctx.fill();
  }
  ctx.lineWidth = 1;
  ctx.setLineDash([Math.max(2, R * 0.012), Math.max(4, R * 0.028)]);
  ctx.lineDashOffset = -rot * R * 0.35;
  ctx.strokeStyle = rgba(HOT, 0.45 + 0.2 * e);
  strokeCircle(ctx, cx, cy, R * 0.645);
  ctx.setLineDash([2, 6]);
  ctx.lineDashOffset = rot * R * 0.5;
  ctx.strokeStyle = rgba(SOFT, 0.3 + 0.2 * e);
  strokeCircle(ctx, cx, cy, R * 0.5);
  ctx.setLineDash([]);

  // Coil ring: ten arc-reactor segments with a chasing light.
  const coils = 10;
  const r1 = R * 0.355;
  const r2 = R * 0.44;
  for (let k = 0; k < coils; k++) {
    const a0 = (k / coils) * TAU - rot * 0.5;
    const a1 = a0 + (TAU / coils) * 0.72;
    const chase = Math.max(0, Math.cos(a0 - rot * 2.4)) ** 4;
    const b = 0.22 + 0.55 * chase + lvl * 0.35;
    ctx.fillStyle = rgba(PINK, (0.14 + 0.4 * b) * e);
    ctx.strokeStyle = rgba(HOT, (0.3 + 0.55 * b) * e);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, r2, a0, a1);
    ctx.arc(cx, cy, r1, a1, a0, true);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  // Core.
  const coreR = R * (0.25 + 0.025 * pulse * e + lvl * 0.07);
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 1.45);
  core.addColorStop(0, "rgba(255, 255, 255, 0.95)");
  core.addColorStop(0.16, rgba("255, 214, 236", 0.92));
  core.addColorStop(0.36, rgba(HOT, 0.82 * e + 0.1));
  core.addColorStop(0.6, rgba(DEEP, 0.55 * e));
  core.addColorStop(0.8, rgba(PINK, 0.22 * e));
  core.addColorStop(1, rgba(PINK, 0));
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR * 1.45, 0, TAU);
  ctx.fill();

  ctx.strokeStyle = rgba("255, 255, 255", 0.28 + 0.2 * pulse);
  ctx.lineWidth = 1;
  strokeCircle(ctx, cx, cy, R * 0.205);
  // Inner hexagon.
  ctx.strokeStyle = rgba("255, 255, 255", 0.32);
  ctx.beginPath();
  for (let k = 0; k <= 6; k++) {
    const a = (k / 6) * TAU - rot * 0.35;
    const x = cx + Math.cos(a) * R * 0.14;
    const y = cy + Math.sin(a) * R * 0.14;
    if (k === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Orbiting particles with short trails.
  for (const p of particles) {
    const a = p.angle + rot * p.speed * 1.4;
    const r = R * p.radius * (1 + 0.015 * Math.sin(time * 2 + p.phase));
    const twinkle = 0.5 + 0.5 * Math.sin(time * 2.6 + p.phase);
    const alpha = (0.25 + 0.6 * twinkle) * e;
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    ctx.fillStyle = rgba(twinkle > 0.8 ? SOFT : HOT, alpha);
    ctx.beginPath();
    ctx.arc(x, y, p.size * (1 + lvl * 0.8), 0, TAU);
    ctx.fill();
    ctx.strokeStyle = rgba(PINK, alpha * 0.35);
    ctx.lineWidth = p.size * 0.8;
    ctx.beginPath();
    const trail = 0.1 * Math.sign(p.speed) * Math.min(2, s.speed + 0.3);
    ctx.arc(cx, cy, r, trail > 0 ? a - trail : a, trail > 0 ? a : a - trail);
    ctx.stroke();
  }

  ctx.restore();
}

/** Canvas arc-reactor hologram. Purely decorative; state is announced elsewhere. */
export function HologramOrb({ state, level, className }: HologramOrbProps) {
  const reduced = useReducedMotion() ?? false;
  const particles = useMemo(() => makeParticles(46), []);
  const targetRef = useRef({ state, level });
  const animRef = useRef<AnimState>({ ...PROFILES[state], level: 0, rot: 0.6 });
  const fontRef = useRef("ui-monospace, monospace");

  useEffect(() => {
    targetRef.current = { state, level };
  }, [state, level]);

  const canvasRef = useCanvasLoop(
    ({ ctx, width, height, time, dt }: CanvasFrame) => {
      const target = PROFILES[targetRef.current.state];
      const s = animRef.current;
      if (reduced) {
        Object.assign(s, target, { level: 0 });
      } else {
        const k = 1 - Math.exp(-dt * 3);
        s.speed += (target.speed - s.speed) * k;
        s.energy += (target.energy - s.energy) * k;
        s.sweep += (target.sweep - s.sweep) * k;
        s.ripple += (target.ripple - s.ripple) * k;
        s.wave += (target.wave - s.wave) * k;
        const lk = 1 - Math.exp(-dt * 14);
        s.level += (targetRef.current.level - s.level) * lk;
        s.rot += dt * s.speed;
      }
      drawReactor(ctx, width, height, reduced ? 0.8 : time, s, particles, fontRef.current);
    },
    !reduced,
    reduced ? state : undefined,
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const family = getComputedStyle(canvas).getPropertyValue("--font-mono").trim();
    if (family) fontRef.current = `${family}, ui-monospace, monospace`;
  }, [canvasRef]);

  return <canvas ref={canvasRef} aria-hidden="true" className={cn("block h-full w-full", className)} />;
}
