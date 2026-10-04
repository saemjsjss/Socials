"use client";

import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";
import { useCanvasLoop, type CanvasFrame } from "@/hooks/useCanvasLoop";
import { cn } from "@/lib/utils";

interface VoiceVisualizerProps {
  /** Real FFT source; when absent the bars are synthesised from `level`. */
  analyser?: AnalyserNode | null;
  level: number;
  active: boolean;
  className?: string;
}

const MAX_BARS = 96;

/** Value-noise in 0..1, smooth in both bar index and time. */
function noise(i: number, t: number): number {
  return (
    0.5 + 0.25 * Math.sin(i * 0.9 + t * 7.3) + 0.15 * Math.sin(i * 2.3 - t * 11.1) + 0.1 * Math.sin(i * 5.1 + t * 17.9)
  );
}

/**
 * Mirrored spectrum analyser: low frequencies in the middle, fanning out to both
 * sides, bars reflected above and below a glowing baseline.
 */
export function VoiceVisualizer({ analyser, level, active, className }: VoiceVisualizerProps) {
  const reduced = useReducedMotion() ?? false;
  const propsRef = useRef({ analyser, level, active });
  const valuesRef = useRef(new Float32Array(MAX_BARS));
  const peaksRef = useRef(new Float32Array(MAX_BARS));
  const freqRef = useRef<Uint8Array<ArrayBuffer> | null>(null);

  useEffect(() => {
    propsRef.current = { analyser, level, active };
  }, [analyser, level, active]);

  const canvasRef = useCanvasLoop(
    ({ ctx, width, height, time, dt }: CanvasFrame) => {
      const { analyser: node, level: lvl, active: on } = propsRef.current;
      ctx.clearRect(0, 0, width, height);
      const mid = height / 2;
      const half = Math.max(8, Math.min(MAX_BARS / 2, Math.floor(width / 14)));
      const bars = half * 2;
      const slot = width / bars;
      const barWidth = Math.max(1.5, slot * 0.56);
      const values = valuesRef.current;
      const peaks = peaksRef.current;

      // Targets per half (index 0 = centre = lowest frequency).
      let freq: Uint8Array<ArrayBuffer> | null = null;
      if (node && on) {
        if (!freqRef.current || freqRef.current.length !== node.frequencyBinCount) {
          freqRef.current = new Uint8Array(node.frequencyBinCount);
        }
        freq = freqRef.current;
        node.getByteFrequencyData(freq);
      }
      const usable = freq ? Math.floor(freq.length * 0.55) : 0; // speech lives below ~12 kHz

      for (let i = 0; i < half; i++) {
        let target = 0;
        if (on && freq) {
          // Log-spaced bins so the voice band spreads across the bars.
          const lo = Math.floor(Math.pow(usable, i / half));
          const hi = Math.max(lo + 1, Math.floor(Math.pow(usable, (i + 1) / half)));
          let sum = 0;
          for (let b = lo; b < hi && b < freq.length; b++) sum += freq[b];
          target = Math.pow(sum / (hi - lo) / 255, 1.35);
        } else if (on) {
          const envelope = 1 - (i / half) * 0.7;
          target = Math.min(1, lvl * 1.15 * envelope * noise(i, reduced ? 0 : time));
        }
        const prev = values[i];
        values[i] = prev + (target - prev) * (target > prev ? 0.55 : Math.min(1, dt * 7));
        peaks[i] = Math.max(values[i], peaks[i] - dt * 0.5);
      }

      // Baseline glow.
      const line = ctx.createLinearGradient(0, 0, width, 0);
      line.addColorStop(0, "rgba(255, 0, 127, 0)");
      line.addColorStop(0.5, `rgba(255, 105, 180, ${on ? 0.7 : 0.45})`);
      line.addColorStop(1, "rgba(255, 0, 127, 0)");

      const maxH = mid - 3;
      const barFill = ctx.createLinearGradient(0, mid - maxH, 0, mid + maxH);
      barFill.addColorStop(0, "rgba(255, 0, 127, 0.15)");
      barFill.addColorStop(0.35, "rgba(255, 20, 147, 0.85)");
      barFill.addColorStop(0.5, "rgba(255, 214, 236, 1)");
      barFill.addColorStop(0.65, "rgba(255, 20, 147, 0.85)");
      barFill.addColorStop(1, "rgba(255, 0, 127, 0.15)");

      ctx.save();
      ctx.globalCompositeOperation = "lighter";

      const anyEnergy = values.subarray(0, half).some((v) => v > 0.01);
      if (anyEnergy) {
        ctx.fillStyle = barFill;
        for (let i = 0; i < half; i++) {
          const h = Math.max(1, values[i] * maxH);
          for (const side of [-1, 1]) {
            const slotIndex = side < 0 ? half - 1 - i : half + i;
            const x = slotIndex * slot + (slot - barWidth) / 2;
            ctx.beginPath();
            if (typeof ctx.roundRect === "function")
              ctx.roundRect(x, mid - h, barWidth, h * 2, Math.min(barWidth / 2, 3));
            else ctx.rect(x, mid - h, barWidth, h * 2);
            ctx.fill();
            // Peak caps.
            const py = peaks[i] * maxH;
            if (py > 2) {
              ctx.fillStyle = "rgba(251, 207, 232, 0.8)";
              ctx.fillRect(x, mid - py - 2, barWidth, 1.5);
              ctx.fillRect(x, mid + py + 0.5, barWidth, 1.5);
              ctx.fillStyle = barFill;
            }
          }
        }
      }

      // Idle / baseline: a calm travelling ripple.
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      const ripple = on ? 0.6 : 1.6;
      for (let x = 0; x <= width; x += 3) {
        const u = x / width;
        const taper = Math.sin(u * Math.PI);
        const y = mid + Math.sin(u * 22 - (reduced ? 0 : time) * 2.4) * ripple * taper;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      if (!on && !reduced) {
        // A short scanning streak drifting along the idle line.
        const x = ((time * 0.16) % 1) * width;
        const streak = ctx.createLinearGradient(x - 50, 0, x + 50, 0);
        streak.addColorStop(0, "rgba(255, 105, 180, 0)");
        streak.addColorStop(0.5, "rgba(255, 214, 236, 0.9)");
        streak.addColorStop(1, "rgba(255, 105, 180, 0)");
        ctx.fillStyle = streak;
        ctx.fillRect(x - 50, mid - 1, 100, 2);
      }
      ctx.restore();
    },
    !reduced,
    reduced ? `${active}-${level > 0.05}` : undefined,
  );

  return <canvas ref={canvasRef} aria-hidden="true" className={cn("block h-full w-full", className)} />;
}
