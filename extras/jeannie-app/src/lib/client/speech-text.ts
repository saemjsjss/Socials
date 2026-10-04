// What Jeannie reads aloud. The terminal shows the whole reply, but the voice
// gets a short spoken version: no URLs, no numbered source or result lists, no
// data dumps (Hangeul fact and table bullets, "as of" lines, timestamps), and at
// most SPEECH_MAX_CHARS characters cut at a sentence boundary.

import type { AgentId, ResolvedLang } from "@/lib/types";
import { detectLanguage, stripMarkdownForSpeech } from "@/lib/utils";

/**
 * What a Hangeul reply says out loud. The voice goes to /api/tts, whose engines
 * are ElevenLabs and Microsoft Edge TTS: third parties the spec's accepted risks
 * (D11) do not name. A Hangeul headline holds student names, HNG ids and portal
 * uids, or every consultant's name, so the reply is not read aloud; this line
 * is, and the figures stay on the screen.
 */
export const HANGEUL_SPOKEN_LINE = {
  en: "The answer is on your screen.",
  ko: "답을 화면에 띄워 드렸어요.",
} as const;

/** The text to speak for a finished reply of `agent`: a Hangeul reply becomes HANGEUL_SPOKEN_LINE in its language. */
export function spokenText(text: string, agent: AgentId | null | undefined, lang: ResolvedLang | null): string {
  if (agent !== "hangeul") return text;
  if (lang === "bilingual") return `${HANGEUL_SPOKEN_LINE.en}\n—\n${HANGEUL_SPOKEN_LINE.ko}`;
  return lang === "ko" ? HANGEUL_SPOKEN_LINE.ko : HANGEUL_SPOKEN_LINE.en;
}

export type SpeechLang = "en" | "ko";

export interface SpeechSegment {
  text: string;
  lang: SpeechLang;
}

/** Longest stretch of a reply read aloud, across all of its segments. */
export const SPEECH_MAX_CHARS = 600;

// The "—" line between the English and Korean halves of a bilingual reply. [ \t], not \s:
// a `\s*` here would run across newlines and go quadratic on a long run of blank lines.
const BILINGUAL_SEPARATOR = /^[ \t]*(?:[—–]{1,2}|-{3,})[ \t]*$/m;
// Only the start of a reply is ever spoken; this bounds the work on a huge one.
const MAX_SCANNED_CHARS = 8_000;
// "Sources:", "출처:", "Sources / 출처:": everything after it is a link list.
const SOURCES_LABEL = /^\s*[*_]*(?:sources|references|출처|참고\s*자료)(?:\s*\/\s*(?:sources|출처))?\s*[:：]?[*_]*\s*$/i;
// "[1] Title — snippet — https://…": one entry of a search briefing or source list.
const LISTED_SOURCE = /^\s*(?:[-*•]\s*)?\[\d{1,2}\]\s/;
// Metadata lines of the search briefing and the Hangeul answers ("As of 23:35 (full picture)", "기준: 23:35").
const DATA_LINE =
  /^\s*(?:(?:no\s+)?live web results for\b|(?:generated|checked|latency)\s*:|(?:생성|확인)\s*시각\s*:|응답\s*시간\s*:|as of \d|기준\s*:)/i;
// "• Consultancies done: 20", "• Consulted: 6": a code-built fact or table row of a Hangeul answer.
const METRIC_BULLET = /^\s*•\s*[^:：\n]{1,60}[:：]/;
// A heading-like label on its own line ("Highlights:", "주요 사항:").
const SHORT_LABEL = /^\s*[^\s:：]+(?:\s+[^\s:：]+){0,2}\s*[:：]\s*$/;
const URLS = /\b(?:https?:\/\/|www\.)\S+/gi;
const INLINE_CITATION = /\s*\[\d{1,2}\]/g;
// "(SUPABASE_URL, SUPABASE_SECRET_KEY)": configuration names are for the screen.
const ENV_NAME_GROUP = /\s*\(\s*[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?:\s*,\s*[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)*\s*\)/g;
const ENV_NAME = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g;

/** "Daily brief: not available yet" → "Daily brief: not available yet."; text already ending a sentence or clause is left alone. */
function asSentence(line: string): string {
  return /[.!?。！？…,;、，][)\]"'”’」]*$/.test(line) ? line : `${line}.`;
}

/** The lines of one reply (or one half of a bilingual reply) worth saying out loud. */
function speakableLines(text: string): string {
  const kept: string[] = [];
  for (const raw of text.split("\n")) {
    // Collapsed first, so no pattern below ever scans a long whitespace run.
    const line = raw.replace(/\s+/g, " ");
    if (SOURCES_LABEL.test(line)) break;
    if (LISTED_SOURCE.test(line) || DATA_LINE.test(line) || METRIC_BULLET.test(line) || SHORT_LABEL.test(line)) continue;
    const spoken = line
      .replace(/!\[[^\][]*\]\([^()]*\)/g, " ")
      .replace(/\[([^\][]+)\]\([^()]*\)/g, "$1")
      .replace(URLS, " ")
      .replace(INLINE_CITATION, "")
      .replace(ENV_NAME_GROUP, "")
      .replace(ENV_NAME, (name) => name.replace(/_/g, " "))
      .trim();
    // Each line ends as a sentence, so the voice pauses after a title or a list item
    // and a line that introduced a dropped list doesn't trail off on its colon.
    if (spoken) kept.push(asSentence(spoken.replace(/[:：]$/, ".")));
  }
  return stripMarkdownForSpeech(kept.join("\n")).trim();
}

/** Cuts `text` to at most `max` characters, at the last sentence end when there is a reasonable one. */
export function clipAtSentence(text: string, max: number): string {
  if (text.length <= max) return text;
  let sentenceEnd = -1;
  for (let i = Math.min(max, text.length) - 1; i >= 0; i--) {
    if (/[.!?。！？]/.test(text[i]) && (i + 1 === text.length || /\s/.test(text[i + 1]))) {
      sentenceEnd = i;
      break;
    }
  }
  if (sentenceEnd >= max * 0.4) return text.slice(0, sentenceEnd + 1);
  // One very long sentence: stop at a word boundary instead.
  const head = text.slice(0, max - 1);
  const space = head.lastIndexOf(" ");
  return `${(space > max * 0.5 ? head.slice(0, space) : head).replace(/[\s,;:、，]+$/, "")}…`;
}

/** Splits `total` characters fairly: short segments keep all of theirs, long ones share the rest. */
function allocate(lengths: number[], total: number): number[] {
  const budgets = new Array<number>(lengths.length).fill(0);
  const order = lengths.map((length, index) => ({ length, index })).sort((a, b) => a.length - b.length);
  let remaining = total;
  order.forEach(({ length, index }, k) => {
    budgets[index] = Math.min(length, Math.floor(remaining / (order.length - k)));
    remaining -= budgets[index];
  });
  return budgets;
}

/**
 * The spoken version of a reply, as segments to synthesise in order. Bilingual
 * replies are split at their separator line so each half gets its own voice.
 */
export function speechSegments(text: string, lang: ResolvedLang | null, maxChars = SPEECH_MAX_CHARS): SpeechSegment[] {
  const halves = lang === "en" || lang === "ko" ? [text] : text.split(BILINGUAL_SEPARATOR);
  const parts = halves.map((half) => speakableLines(half.slice(0, MAX_SCANNED_CHARS))).filter((part) => part.length > 0);
  const budgets = allocate(
    parts.map((part) => part.length),
    maxChars,
  );
  return parts.map((part, index) => ({
    text: clipAtSentence(part, budgets[index]),
    lang: lang === "en" || lang === "ko" ? lang : detectLanguage(part),
  }));
}
