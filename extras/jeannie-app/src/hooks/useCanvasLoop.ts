"use client";

import { useEffect, useRef } from "react";

export interface CanvasFrame {
  ctx: CanvasRenderingContext2D;
  /** CSS pixels; the context is already scaled for devicePixelRatio. */
  width: number;
  height: number;
  /** Seconds since the loop started. */
  time: number;
  /** Seconds since the previous frame (clamped). */
  dt: number;
}

/**
 * Shared canvas plumbing for the HUD visualizers: devicePixelRatio-aware sizing
 * via ResizeObserver, a requestAnimationFrame loop that pauses while the tab is
 * hidden or the canvas is off-screen, and a single-frame mode (animate=false)
 * that repaints only on resize or when `redrawKey` changes (reduced motion).
 */
export function useCanvasLoop(draw: (frame: CanvasFrame) => void, animate: boolean, redrawKey?: unknown) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  const repaintRef = useRef<() => void>(() => {});

  useEffect(() => {
    drawRef.current = draw;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    let running = false;
    let pageVisible = document.visibilityState === "visible";
    let onScreen = true;
    const start = performance.now();
    let last = start;

    const paint = (now: number) => {
      if (width === 0 || height === 0) return;
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawRef.current({ ctx, width, height, time: (now - start) / 1000, dt });
    };

    const loop = (now: number) => {
      paint(now);
      raf = requestAnimationFrame(loop);
    };

    const sync = () => {
      const shouldRun = animate && pageVisible && onScreen;
      if (shouldRun && !running) {
        running = true;
        last = performance.now();
        raf = requestAnimationFrame(loop);
      } else if (!shouldRun && running) {
        running = false;
        cancelAnimationFrame(raf);
      }
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(0, Math.round(rect.width));
      height = Math.max(0, Math.round(rect.height));
      const pw = Math.max(1, Math.round(width * dpr));
      const ph = Math.max(1, Math.round(height * dpr));
      if (canvas.width !== pw || canvas.height !== ph) {
        canvas.width = pw;
        canvas.height = ph;
      }
      if (!running) paint(performance.now());
    };

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);

    const intersection =
      typeof IntersectionObserver === "function"
        ? new IntersectionObserver((entries) => {
            onScreen = entries.some((entry) => entry.isIntersecting);
            sync();
          })
        : null;
    intersection?.observe(canvas);

    const onVisibility = () => {
      pageVisible = document.visibilityState === "visible";
      sync();
    };
    document.addEventListener("visibilitychange", onVisibility);

    repaintRef.current = () => {
      if (!running) paint(performance.now());
    };

    resize();
    sync();

    return () => {
      cancelAnimationFrame(raf);
      running = false;
      resizeObserver.disconnect();
      intersection?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      repaintRef.current = () => {};
    };
  }, [animate]);

  useEffect(() => {
    repaintRef.current();
  }, [redrawKey]);

  return canvasRef;
}
