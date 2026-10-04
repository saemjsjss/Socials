"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

// Minimal Web Speech API recognition typings (not part of lib.dom).
interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: RecognitionAlternative;
}
interface RecognitionResultEvent extends Event {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
}
interface RecognitionErrorEvent extends Event {
  readonly error: string;
}
interface Recognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionResultEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onspeechstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERROR_TEXT: Record<string, string> = {
  "not-allowed": "Microphone permission denied.",
  "service-not-allowed": "Speech recognition is blocked in this browser.",
  "audio-capture": "No microphone was found.",
  network: "Speech service unreachable.",
  "no-speech": "No speech detected. Try again.",
  "language-not-supported": "This language is not supported for voice input.",
};

export type RecognitionLang = "en-US" | "ko-KR";

interface RecognitionOptions {
  lang: RecognitionLang;
  /** Called once per session with the final transcript (never empty). */
  onFinal: (transcript: string) => void;
}

export interface SpeechRecognitionState {
  supported: boolean;
  listening: boolean;
  interim: string;
  error: string | null;
  /** performance.now() seconds of the latest speech activity, for the listening level. */
  activityRef: RefObject<number>;
  start: () => void;
  stop: () => void;
}

/** Push-to-talk speech input via the Web Speech API (Chrome, Edge, Safari). */
export function useSpeechRecognition({ lang, onFinal }: RecognitionOptions): SpeechRecognitionState {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<Recognition | null>(null);
  const onFinalRef = useRef(onFinal);
  const activityRef = useRef(0);

  useEffect(() => {
    onFinalRef.current = onFinal;
  });

  useEffect(() => {
    setSupported(recognitionCtor() !== null);
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || recognitionRef.current) return;
    if (typeof window !== "undefined" && !window.isSecureContext) {
      setError("Voice input needs HTTPS (or localhost).");
      return;
    }
    let recognition: Recognition;
    try {
      recognition = new Ctor();
    } catch {
      setError("Speech recognition could not start.");
      return;
    }
    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    let finalText = "";
    recognition.onspeechstart = () => {
      activityRef.current = performance.now() / 1000;
    };
    recognition.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) finalText += transcript;
        else pending += transcript;
      }
      activityRef.current = performance.now() / 1000;
      setInterim((finalText + pending).trim());
    };
    recognition.onerror = (event) => {
      if (event.error !== "aborted") setError(ERROR_TEXT[event.error] ?? "Voice input failed.");
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setListening(false);
      setInterim("");
      const transcript = finalText.trim();
      if (transcript) onFinalRef.current(transcript);
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      setError(null);
      setInterim("");
      setListening(true);
    } catch {
      setError("Speech recognition could not start.");
    }
  }, [lang]);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  return { supported, listening, interim, error, activityRef, start, stop };
}
