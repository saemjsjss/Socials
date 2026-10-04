"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, isAbortError, requestSpeech } from "@/lib/client/api";
import { speechSegments, type SpeechLang, type SpeechSegment } from "@/lib/client/speech-text";
import type { ResolvedLang, TtsEngine } from "@/lib/types";

// Jeannie's voice: server TTS (ElevenLabs / Edge neural) played through a shared
// AudioContext + AnalyserNode so the orb and spectrum react to the real signal,
// falling back to the browser's speechSynthesis with a synthetic level.

const SERVER_BACKOFF_MS = 60_000; // after a 503/404/network failure, go straight to the browser voice for a while
const BROWSER_CHUNK_CHARS = 220; // Chrome cuts long utterances off after ~15 s

type AudioContextCtor = typeof AudioContext;

function audioContextCtor(): AudioContextCtor | null {
  const w = window as unknown as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

function sentenceChunks(text: string, max: number): string[] {
  const sentences = text.match(/[^.!?。？！]+[.!?。？！]*\s*/g) ?? [text];
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    if ((current + sentence).length > max && current) {
      chunks.push(current.trim());
      current = "";
    }
    current += sentence;
    while (current.length > max) {
      chunks.push(current.slice(0, max));
      current = current.slice(max);
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

const PREFERRED_VOICE = /natural|neural|google|jenny|aria|samantha|sunhi|yuna|heami|female/i;

function pickVoice(voices: SpeechSynthesisVoice[], lang: SpeechLang): SpeechSynthesisVoice | null {
  const exact = lang === "ko" ? "ko-kr" : "en-us";
  const normalized = (v: SpeechSynthesisVoice) => v.lang.replace("_", "-").toLowerCase();
  const candidates = voices.filter((v) => normalized(v).startsWith(lang));
  const score = (v: SpeechSynthesisVoice) =>
    (normalized(v) === exact ? 4 : 0) + (PREFERRED_VOICE.test(v.name) ? 2 : 0) + (v.localService ? 0 : 1);
  return candidates.sort((a, b) => score(b) - score(a))[0] ?? null;
}

let silentWavUrl: string | null = null;

/** A 12 ms silent WAV, played inside the first user gesture to unlock later async playback (iOS). */
function silentWav(): string {
  if (silentWavUrl) return silentWavUrl;
  const samples = 100;
  const bytes = new Uint8Array(44 + samples);
  const view = new DataView(bytes.buffer);
  const ascii = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, 8000, true);
  view.setUint32(28, 8000, true);
  view.setUint16(32, 1, true);
  view.setUint16(34, 8, true);
  ascii(36, "data");
  view.setUint32(40, samples, true);
  bytes.fill(128, 44);
  silentWavUrl = `data:audio/wav;base64,${btoa(String.fromCharCode(...bytes))}`;
  return silentWavUrl;
}

/**
 * Resolves when playback is over: "ended" (or failed), "aborted" by stop(), or
 * "interrupted" when something outside the app paused it (OS media controls,
 * headphones unplugged, a phone call). Only "ended" plays on to the next segment.
 */
function waitForEnd(element: HTMLAudioElement, signal: AbortSignal): Promise<"ended" | "aborted" | "interrupted"> {
  return new Promise((resolve) => {
    const finish = (outcome: "ended" | "aborted" | "interrupted") => {
      element.removeEventListener("ended", onEnded);
      element.removeEventListener("error", onEnded);
      element.removeEventListener("pause", onPause);
      element.removeEventListener("emptied", onPause);
      signal.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onEnded = () => finish("ended");
    const onAbort = () => finish("aborted");
    // A natural end also fires "pause" first, with `ended` already true.
    const onPause = () => {
      if (signal.aborted) finish("aborted");
      else if (!element.ended) finish("interrupted");
    };
    element.addEventListener("ended", onEnded);
    element.addEventListener("error", onEnded);
    element.addEventListener("pause", onPause);
    element.addEventListener("emptied", onPause);
    signal.addEventListener("abort", onAbort);
    if (signal.aborted) finish("aborted");
  });
}

/** How one segment went on the server voice: played, hand over to the browser voice, or stop reading. */
type ServerOutcome = "played" | "fallback" | "halt";

export interface SpeechOutput {
  /** Audio is audibly playing. */
  speaking: boolean;
  /** A voice request is in flight (before the first sound). */
  preparing: boolean;
  engine: TtsEngine | null;
  /** Shared analyser; only meaningful while `routed` is true. */
  analyser: AnalyserNode | null;
  /** The current playback runs through `analyser` (real FFT available). */
  routed: boolean;
  /** Smoothed output level 0..1, read every animation frame. */
  getLevel: () => number;
  speak: (text: string, lang: ResolvedLang | null) => void;
  stop: () => void;
}

interface SpeechOutputOptions {
  /** False when /api/status reports no server voice engine: skip straight to the browser voice. */
  serverVoice?: boolean;
}

export function useSpeechOutput({ serverVoice = true }: SpeechOutputOptions = {}): SpeechOutput {
  const [speaking, setSpeaking] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [engine, setEngine] = useState<TtsEngine | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const [routed, setRouted] = useState(false);

  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sharedAudioRef = useRef<HTMLAudioElement | null>(null);
  const sharedRoutedRef = useRef(false);
  const primedRef = useRef(false);
  const primingRef = useRef(false);
  const synthPrimedRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const serverDownUntilRef = useRef(0);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  const serverVoiceRef = useRef(serverVoice);

  const levelRef = useRef(0);
  const activeRef = useRef(false);
  const sourceRef = useRef<() => number>(() => 0);
  const loopRef = useRef(0);
  const boundaryRef = useRef(0);

  const getLevel = useCallback(() => levelRef.current, []);

  const runLevelLoop = useCallback(() => {
    if (loopRef.current) return;
    const tick = () => {
      const target = activeRef.current ? sourceRef.current() : 0;
      const prev = levelRef.current;
      levelRef.current = prev + (target - prev) * (target > prev ? 0.45 : 0.12);
      if (!activeRef.current && levelRef.current < 0.003) {
        levelRef.current = 0;
        loopRef.current = 0;
        return;
      }
      loopRef.current = requestAnimationFrame(tick);
    };
    loopRef.current = requestAnimationFrame(tick);
  }, []);

  const sharedAudio = useCallback((): HTMLAudioElement => {
    if (!sharedAudioRef.current) {
      const audio = new Audio();
      audio.preload = "auto";
      sharedAudioRef.current = audio;
    }
    return sharedAudioRef.current;
  }, []);

  /**
   * Creates/resumes the AudioContext and primes playback inside a user gesture.
   * It runs on every gesture until the priming actually succeeds: a touch
   * pointerdown is not an activation, and play() rejects there.
   */
  const unlock = useCallback(() => {
    // Outside an activating event this would only be refused (and Chrome warns about
    // the AudioContext); the pointerup / click of the same tap comes right after.
    if (typeof navigator !== "undefined" && navigator.userActivation && !navigator.userActivation.isActive) return;
    const Ctor = audioContextCtor();
    if (!ctxRef.current && Ctor) {
      try {
        ctxRef.current = new Ctor();
      } catch {
        ctxRef.current = null;
      }
    }
    const ctx = ctxRef.current;
    // "suspended", or iOS's "interrupted" after a call or another app took the audio.
    if (ctx && ctx.state !== "running" && ctx.state !== "closed") void ctx.resume().catch(() => undefined);

    // iOS only lets speechSynthesis talk after a first utterance inside a gesture.
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synthPrimedRef.current && synth && typeof SpeechSynthesisUtterance !== "undefined" && !synth.speaking && !synth.pending) {
      synthPrimedRef.current = true;
      try {
        synth.speak(new SpeechSynthesisUtterance(""));
      } catch {
        synthPrimedRef.current = false;
      }
    }

    const audio = sharedAudio();
    // Never swap the source of a reply that is playing or about to play.
    if (primedRef.current || primingRef.current || currentAudioRef.current === audio || !audio.paused) return;
    primingRef.current = true;
    audio.src = silentWav();
    audio.play().then(
      () => {
        primedRef.current = true;
        primingRef.current = false;
        if (currentAudioRef.current !== audio) audio.pause();
      },
      () => {
        primingRef.current = false; // retried on the next gesture
      },
    );
  }, [sharedAudio]);

  /** The element to play through: the analyser-routed one when the context is running, else a plain one. */
  const playbackElement = useCallback(async (): Promise<{ element: HTMLAudioElement; routed: boolean }> => {
    const ctx = ctxRef.current;
    if (ctx && ctx.state !== "running") await ctx.resume().catch(() => undefined);
    if (!ctx || ctx.state !== "running") {
      // A MediaElementSource on a suspended context would be silent, so bypass Web Audio entirely.
      return {
        element: sharedAudioRef.current && !sharedRoutedRef.current ? sharedAudioRef.current : new Audio(),
        routed: false,
      };
    }
    const element = sharedAudio();
    if (!sharedRoutedRef.current) {
      try {
        const node = ctx.createAnalyser();
        node.fftSize = 1024;
        node.smoothingTimeConstant = 0.78;
        const source = ctx.createMediaElementSource(element);
        source.connect(node);
        node.connect(ctx.destination);
        analyserRef.current = node;
        sharedRoutedRef.current = true;
        setAnalyser(node);
      } catch {
        return { element: new Audio(), routed: false };
      }
    }
    return { element, routed: true };
  }, [sharedAudio]);

  const analyserLevel = useCallback((): (() => number) => {
    const node = analyserRef.current;
    if (!node) return () => 0;
    const data = new Uint8Array(node.fftSize);
    return () => {
      node.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      return Math.min(1, Math.sqrt(sum / data.length) * 3.4);
    };
  }, []);

  const syntheticLevel = useCallback((): (() => number) => {
    return () => {
      const t = performance.now() / 1000;
      const burst = Math.exp(-(t - boundaryRef.current) * 5) * 0.35;
      const wobble = 0.18 * Math.sin(t * 9.1) * Math.sin(t * 3.7);
      return Math.min(1, Math.max(0.08, 0.34 + wobble + Math.random() * 0.12 + burst));
    };
  }, []);

  const beginPlayback = useCallback(
    (nextEngine: TtsEngine, source: () => number, isRouted: boolean) => {
      sourceRef.current = source;
      activeRef.current = true;
      setEngine(nextEngine);
      setRouted(isRouted);
      setPreparing(false);
      setSpeaking(true);
      runLevelLoop();
    },
    [runLevelLoop],
  );

  const endPlayback = useCallback(() => {
    activeRef.current = false;
  }, []);

  /** Server voice for one segment. */
  const playServer = useCallback(
    async (segment: SpeechSegment, signal: AbortSignal, generation: number): Promise<ServerOutcome> => {
      let audio: Blob;
      let serverEngine: TtsEngine;
      try {
        ({ audio, engine: serverEngine } = await requestSpeech({ text: segment.text, lang: segment.lang }, signal));
      } catch (error) {
        if (isAbortError(error)) return "played";
        // 400 (e.g. nothing_to_speak): nothing worth saying in this segment; skip it, no fallback.
        if (error instanceof ApiRequestError && error.status === 400) return "played";
        if (error instanceof ApiRequestError && (error.status === 503 || error.status === 404 || error.status === 0)) {
          serverDownUntilRef.current = Date.now() + SERVER_BACKOFF_MS;
        }
        return "fallback";
      }
      if (generation !== generationRef.current) return "played";

      const { element, routed: isRouted } = await playbackElement();
      if (generation !== generationRef.current) return "played";
      const url = URL.createObjectURL(audio);
      currentAudioRef.current = element;
      try {
        element.src = url;
        beginPlayback(serverEngine, isRouted ? analyserLevel() : syntheticLevel(), isRouted);
        await element.play();
        if (element === sharedAudioRef.current) primedRef.current = true;
        // Paused from outside the app: stop reading instead of hanging in SPEAKING,
        // and don't carry on with the next segment through the speakers.
        return (await waitForEnd(element, signal)) === "interrupted" ? "halt" : "played";
      } catch {
        return signal.aborted ? "played" : "fallback"; // autoplay refusal or decode error → browser voice
      } finally {
        endPlayback();
        URL.revokeObjectURL(url);
        if (currentAudioRef.current === element) currentAudioRef.current = null;
      }
    },
    [analyserLevel, beginPlayback, endPlayback, playbackElement, syntheticLevel],
  );

  const playBrowser = useCallback(
    async (segment: SpeechSegment, generation: number): Promise<void> => {
      const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
      if (!synth || typeof SpeechSynthesisUtterance === "undefined") return;
      if (voicesRef.current.length === 0) voicesRef.current = synth.getVoices();
      const voice = pickVoice(voicesRef.current, segment.lang);

      for (const chunk of sentenceChunks(segment.text, BROWSER_CHUNK_CHARS)) {
        if (generation !== generationRef.current) return;
        await new Promise<void>((resolve) => {
          const utterance = new SpeechSynthesisUtterance(chunk);
          utterance.lang = segment.lang === "ko" ? "ko-KR" : "en-US";
          if (voice) utterance.voice = voice;
          utterance.rate = 1.03;
          utterance.pitch = 1.05;
          // Some engines never fire `end`; don't let the queue hang forever.
          const guard = setTimeout(finish, 4000 + chunk.length * 110);
          function finish() {
            clearTimeout(guard);
            endPlayback();
            resolve();
          }
          utterance.onstart = () => beginPlayback("browser", syntheticLevel(), false);
          utterance.onboundary = () => {
            boundaryRef.current = performance.now() / 1000;
          };
          utterance.onend = finish;
          utterance.onerror = finish;
          synth.speak(utterance);
        });
      }
    },
    [beginPlayback, endPlayback, syntheticLevel],
  );

  const stop = useCallback(() => {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    const element = currentAudioRef.current;
    if (element) {
      element.pause();
      currentAudioRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel();
    activeRef.current = false;
    setSpeaking(false);
    setPreparing(false);
    setRouted(false);
  }, []);

  const speak = useCallback(
    (text: string, lang: ResolvedLang | null) => {
      stop();
      const segments = speechSegments(text, lang);
      if (segments.length === 0) return;
      const generation = generationRef.current;
      const controller = new AbortController();
      abortRef.current = controller;
      setPreparing(true);

      void (async () => {
        try {
          for (const segment of segments) {
            if (generation !== generationRef.current) return;
            const useServer = serverVoiceRef.current && Date.now() >= serverDownUntilRef.current;
            const outcome = useServer ? await playServer(segment, controller.signal, generation) : "fallback";
            if (generation !== generationRef.current || outcome === "halt") return;
            if (outcome === "fallback") await playBrowser(segment, generation);
          }
        } finally {
          if (generation === generationRef.current) {
            activeRef.current = false;
            abortRef.current = null;
            setSpeaking(false);
            setPreparing(false);
            setRouted(false);
          }
        }
      })();
    },
    [playBrowser, playServer, stop],
  );

  useEffect(() => {
    serverVoiceRef.current = serverVoice;
  }, [serverVoice]);

  // Unlock audio on user gestures; cheap once unlocked. Touch activation comes on
  // pointerup / touchend / click (not pointerdown), so listen to all of them.
  useEffect(() => {
    const onGesture = () => unlock();
    const events = ["pointerdown", "pointerup", "touchend", "click", "keydown"] as const;
    for (const type of events) window.addEventListener(type, onGesture, true);
    return () => {
      for (const type of events) window.removeEventListener(type, onGesture, true);
    };
  }, [unlock]);

  useEffect(() => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    const load = () => {
      voicesRef.current = synth.getVoices();
    };
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => synth.removeEventListener?.("voiceschanged", load);
  }, []);

  useEffect(
    () => () => {
      generationRef.current += 1;
      abortRef.current?.abort();
      currentAudioRef.current?.pause();
      window.speechSynthesis?.cancel();
      cancelAnimationFrame(loopRef.current);
      void ctxRef.current?.close().catch(() => undefined);
    },
    [],
  );

  return { speaking, preparing, engine, analyser, routed, getLevel, speak, stop };
}
