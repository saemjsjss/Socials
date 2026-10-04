import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { LangMode, ResolvedLang } from "./types";

/** Tailwind-aware className combiner. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// Hangul Jamo, Compatibility Jamo and Syllables.
const HANGUL_CHAR = /[ᄀ-ᇿ㄰-㆏가-힯]/;
const HANGUL_GLOBAL = /[ᄀ-ᇿ㄰-㆏가-힯]/g;
const LATIN_GLOBAL = /[A-Za-z]/g;
const LATIN_WORDS = /[A-Za-z]+(?:'[A-Za-z]+)?/g;

export function containsHangul(text: string): boolean {
  return HANGUL_CHAR.test(text);
}

// Latin words with none of these are names or terms inside a Korean sentence
// ("React useEffect 설명해줘", "iPhone 15 Pro Max 가격 알려줘").
const ENGLISH_FUNCTION_WORDS = new Set(
  (
    "a an the is are was were be been am do does did what how why who which where when can could would should " +
    "will to of in on at for with from by about and or but if that this it i me my you your we our they their " +
    "he she his her please not have has there"
  ).split(" "),
);

// English that asks about Korean words stays English ("what does 사랑 mean?").
const ABOUT_KOREAN_WORDS =
  /\b(?:say|says|said|mean|means|meaning|word|words|phrase|translate|translation|pronounce|pronunciation|spell|spelling|called)\b|\bin\s+korean\b/i;

// Sentence-final Korean endings: 해줘, 알려줘, 뭐야, 있어요, 사용법, ...
const KOREAN_PREDICATE_END = /(?:요|죠|다|까|니|냐|야|지|줘|자|래|게|봐|해|네|나|어|아|법|기|음|함|임|걸|데)$/;

/** Last word with letters, trailing punctuation and emoji removed. */
function lastWord(text: string): string {
  const words = text.split(/\s+/).filter((w) => /[A-Za-z가-힯]/.test(w));
  return (words.at(-1) ?? "").replace(/[^A-Za-z0-9가-힯]+$/, "");
}

/**
 * Dominant language of a message. Latin words without English grammar are
 * terms inside a Korean sentence. Otherwise a Korean predicate at the end wins
 * when Korean is a fair share of the words, and the letter ratio decides the
 * rest (a Hangul syllable carries about as much as 2-3 Latin letters).
 */
export function detectLanguage(text: string): "en" | "ko" {
  const hangul = text.match(HANGUL_GLOBAL)?.length ?? 0;
  if (hangul === 0) return "en";
  const latinWords = text.match(LATIN_WORDS) ?? [];
  if (!latinWords.some((word) => ENGLISH_FUNCTION_WORDS.has(word.toLowerCase().replace(/'.*$/, "")))) return "ko";
  if (ABOUT_KOREAN_WORDS.test(text)) return "en";
  const last = lastWord(text);
  const hangulWords = text.split(/\s+/).filter(containsHangul).length;
  if (/[가-힯]$/.test(last) && KOREAN_PREDICATE_END.test(last) && hangulWords * 2 >= latinWords.length) return "ko";
  const latin = text.match(LATIN_GLOBAL)?.length ?? 0;
  return hangul * 2 >= latin ? "ko" : "en";
}

/** Asking for both languages in the message itself switches to bilingual. */
const BILINGUAL_REQUEST =
  /\b(?:bilingual(?:ly)?|in\s+both\s+(?:languages|english\s+and\s+korean|korean\s+and\s+english)|in\s+(?:english\s+and\s+korean|korean\s+and\s+english))\b|영어(?:와|랑|하고)\s*한국어|한국어(?:와|랑|하고)\s*영어|두\s*언어|(?<![가-힯])(?:한\s*\/\s*영|영\s*\/\s*한|한영|영한)(?:(?![가-힯])|(?=으로|로|병기|둘|모두))/i;

// "Answer in Korean" asks for the answer language. Looser wording ("explain
// ... in Korean") does too, unless the message is about wording: "explain how
// to say thank you in Korean" wants an English explanation.
const ANSWER_IN = String.raw`\b(?:answer|reply|respond|talk|speak|tell|write\s+(?:it|this|that|the\s+answer)|explain(?:\s+(?:it|this|that))?)(?:\s+(?:to\s+)?(?:me|back))?\s+in\s+`;
const ANSWER_IN_KOREAN = new RegExp(String.raw`${ANSWER_IN}korean\b|(?:한국어|한글)로\s*(?:대답|답|말|설명|써|알려|얘기|이야기)`, "i");
const ANSWER_IN_ENGLISH = new RegExp(String.raw`${ANSWER_IN}english\b|(?:영어|영문)로\s*(?:대답|답|말|설명|써|알려|얘기|이야기)`, "i");
const LOOSELY_IN_KOREAN = /\bin\s+korean,?\s+please\b|\bexplain\b[^.?!\n]{0,60}?\bin\s+korean\b/i;
const LOOSELY_IN_ENGLISH = /\bin\s+english,?\s+please\b|\bexplain\b[^.?!\n]{0,60}?\bin\s+english\b/i;
const WORDING_QUESTION =
  /\bhow\s+(?:do|would|can|should)\s+(?:i|you|we)\s+say\b|\bhow\s+to\s+say\b|\b(?:word|phrase|mean|means|pronounce|spell|translate)\b/i;

/** The answer language the message asks for in its own words, if any. */
export function requestedLanguage(text: string): ResolvedLang | null {
  if (BILINGUAL_REQUEST.test(text)) return "bilingual";
  if (ANSWER_IN_KOREAN.test(text)) return "ko";
  if (ANSWER_IN_ENGLISH.test(text)) return "en";
  if (WORDING_QUESTION.test(text)) return null;
  if (LOOSELY_IN_KOREAN.test(text)) return "ko";
  if (LOOSELY_IN_ENGLISH.test(text)) return "en";
  return null;
}

/** Text that says something in a language (not empty, emoji, digits or a bare URL). */
function hasWords(text: string): boolean {
  return /[A-Za-z]/.test(text.replace(/https?:\/\/\S+/g, " ")) || containsHangul(text);
}

/**
 * The answer language. An explicit HUD mode wins, then a request in the
 * message ("answer in Korean", "한영으로"), then detection. A turn without
 * words (image only) takes the language of the latest earlier user turn that
 * has words (`previous` is oldest first), else English.
 */
export function resolveLanguage(mode: LangMode | undefined, text: string, previous: readonly string[] = []): ResolvedLang {
  if (mode === "en" || mode === "ko" || mode === "bilingual") return mode;
  const source = hasWords(text) ? text : ([...previous].reverse().find(hasWords) ?? "");
  return requestedLanguage(source) ?? detectLanguage(source);
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * HTTP header values must be ASCII, but source titles can be Korean. Encode as
 * base64(UTF-8 JSON). Works in the browser, Edge and Node.js runtimes.
 */
export function encodeHeaderJson(value: unknown): string {
  return bytesToBase64(new TextEncoder().encode(JSON.stringify(value)));
}

export function decodeHeaderJson<T>(value: string | null | undefined): T | null {
  if (!value) return null;
  try {
    return JSON.parse(new TextDecoder().decode(base64ToBytes(value))) as T;
  } catch {
    return null;
  }
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/** Constant-time string comparison (no Node crypto needed, so it runs on Edge). */
export function timingSafeEqual(a: string, b: string): boolean {
  const ea = new TextEncoder().encode(a);
  const eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  const len = Math.max(ea.length, eb.length);
  for (let i = 0; i < len; i++) diff |= (ea[i] ?? 0) ^ (eb[i] ?? 0);
  return diff === 0;
}

/** Text safe to hand to a speech engine: no markdown, code, or bare URLs. */
export function stripMarkdownForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\][]*\]\([^()]*\)/g, " ")
    .replace(/\[([^\][]+)\]\([^()]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/[*_~>|#]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** JSON Response helper used by every API route. */
export function jsonResponse(body: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

export function errorResponse(status: number, code: string, error: string): Response {
  return jsonResponse({ error, code }, status);
}

/** Rough data-URL size check (bytes of the decoded payload). */
export function dataUrlByteLength(dataUrl: string): number {
  const comma = dataUrl.indexOf(",");
  const payload = comma === -1 ? dataUrl : dataUrl.slice(comma + 1);
  return Math.floor((payload.length * 3) / 4);
}

export function isImageDataUrl(value: unknown): value is string {
  return typeof value === "string" && /^data:image\/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$/.test(value);
}
