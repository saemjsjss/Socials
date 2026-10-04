// Pure helpers for Jeannie's memory: turning uploaded markdown / JSON Lines
// into searchable chunks, refusing files that carry secrets, and reducing a
// question to search terms. No I/O, so every rule here is unit-tested.
// Runs on Edge and Node.js.

export type MemoryKind = "markdown" | "jsonl";

export interface MemoryChunk {
  ord: number;
  heading: string;
  content: string;
  /** Stable id of a JSONL record (`org-005-hglc-overview`). */
  record_id?: string;
  type?: string;
  entity?: string;
  tags?: string[];
}

export const MAX_CHUNK_CHARS = 1_500;
export const MAX_FILE_BYTES = 1024 * 1024;
const MAX_TAGS = 20;

export function memoryKindFor(name: string): MemoryKind | null {
  const lower = name.toLowerCase();
  if (/\.(?:md|markdown|mdx|txt)$/.test(lower)) return "markdown";
  if (/\.(?:jsonl|ndjson)$/.test(lower)) return "jsonl";
  return null;
}

/** First `# Title` of a markdown file, else the file name without its extension. */
export function documentTitle(name: string, content: string, kind: MemoryKind): string {
  if (kind === "markdown") {
    const h1 = /^#\s+(.+?)\s*#*\s*$/m.exec(stripFrontMatter(content));
    if (h1) return h1[1].trim().slice(0, 200);
  }
  const base = name.split(/[\\/]/).pop() ?? name;
  return base.replace(/\.[^.]+$/, "").slice(0, 200) || "Untitled";
}

function stripFrontMatter(markdown: string): string {
  return markdown.replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n/, "");
}

/** Splits `text` at paragraph, then line, then hard boundaries so no piece exceeds `max`. */
function splitToSize(text: string, max: number): string[] {
  if (text.length <= max) return [text];
  const pieces: string[] = [];
  let current = "";
  const push = () => {
    if (current.trim()) pieces.push(current.trim());
    current = "";
  };
  for (const paragraph of text.split(/\n{2,}/)) {
    const candidate = current ? `${current}\n\n${paragraph}` : paragraph;
    if (candidate.length <= max) {
      current = candidate;
      continue;
    }
    push();
    if (paragraph.length <= max) {
      current = paragraph;
      continue;
    }
    for (const line of paragraph.split("\n")) {
      const next = current ? `${current}\n${line}` : line;
      if (next.length <= max) {
        current = next;
        continue;
      }
      push();
      for (let i = 0; i < line.length; i += max) {
        const slice = line.slice(i, i + max);
        if (slice.length === max) pieces.push(slice);
        else current = slice;
      }
    }
  }
  push();
  return pieces;
}

/**
 * Markdown → chunks, one per `#`–`###` section (deeper headings stay inside
 * their section). Each chunk keeps its heading path ("My work › HGLC"), so it
 * reads on its own after retrieval. Long sections are split near MAX_CHUNK_CHARS.
 */
export function chunkMarkdown(markdown: string, maxChars = MAX_CHUNK_CHARS): MemoryChunk[] {
  const lines = stripFrontMatter(markdown).replace(/\r\n?/g, "\n").split("\n");
  const path: string[] = [];
  const sections: { heading: string; body: string[] }[] = [{ heading: "", body: [] }];
  let inFence = false;

  for (const line of lines) {
    if (/^\s*(?:```|~~~)/.test(line)) inFence = !inFence;
    const match = inFence ? null : /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (match) {
      const level = match[1].length;
      path.length = level - 1;
      path[level - 1] = match[2].trim();
      sections.push({ heading: path.filter(Boolean).join(" › "), body: [] });
    } else {
      sections.at(-1)!.body.push(line);
    }
  }

  const chunks: MemoryChunk[] = [];
  for (const section of sections) {
    const body = section.body.join("\n").trim();
    if (!body) continue;
    for (const piece of splitToSize(body, maxChars)) {
      chunks.push({ ord: chunks.length, heading: section.heading, content: piece });
    }
  }
  return chunks;
}

export interface JsonlIssue {
  line: number;
  message: string;
}

function optionalString(value: unknown, max: number): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim().slice(0, max) : undefined;
}

/**
 * JSON Lines knowledge records (`{id, type, title, text, tags, entity, updated}`)
 * → one chunk per record; `text` is never split further. Bad lines are
 * reported by line number instead of failing the whole file.
 */
export function chunkJsonl(jsonl: string): { chunks: MemoryChunk[]; issues: JsonlIssue[] } {
  const chunks: MemoryChunk[] = [];
  const issues: JsonlIssue[] = [];
  const seen = new Set<string>();

  jsonl.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    if (!raw.trim()) return;
    let record: unknown;
    try {
      record = JSON.parse(raw);
    } catch {
      issues.push({ line, message: "not valid JSON" });
      return;
    }
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      issues.push({ line, message: "not a JSON object" });
      return;
    }
    const r = record as Record<string, unknown>;
    const id = optionalString(r.id, 200);
    const text = optionalString(r.text, 20_000);
    if (!id) return void issues.push({ line, message: "missing \"id\"" });
    if (!text) return void issues.push({ line, message: "missing \"text\"" });
    if (seen.has(id)) return void issues.push({ line, message: `duplicate id "${id}"` });
    seen.add(id);

    const tags = Array.isArray(r.tags)
      ? r.tags.filter((t): t is string => typeof t === "string" && t.trim() !== "").map((t) => t.trim().slice(0, 60)).slice(0, MAX_TAGS)
      : [];
    chunks.push({
      ord: chunks.length,
      heading: optionalString(r.title, 300) ?? id,
      content: text,
      record_id: id,
      type: optionalString(r.type, 60),
      entity: optionalString(r.entity, 120),
      tags,
    });
  });
  return { chunks, issues };
}

// ─── Secret guard ───────────────────────────────────────────────────────────

const SECRET_PATTERNS: { label: string; pattern: RegExp }[] = [
  { label: "API key (sk-…/sk_…)", pattern: /\bsk[-_](?:live_|test_|proj-|ant-)?[A-Za-z0-9_-]{20,}/ },
  { label: "Supabase secret key", pattern: /\bsb_secret_[A-Za-z0-9_-]{16,}/ },
  { label: "JSON Web Token", pattern: /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/ },
  { label: "GitHub token", pattern: /\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}/ },
  { label: "AWS access key", pattern: /\bAKIA[0-9A-Z]{16}\b/ },
  { label: "Slack token", pattern: /\bxox[abprs]-[A-Za-z0-9-]{10,}/ },
  { label: "Telegram bot token", pattern: /\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b/ },
  { label: "private key", pattern: /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/ },
  {
    label: "ID number (passport/NID/TIN)",
    pattern: /\b(?:passport|NID|national\s+id|TIN|birth\s*reg(?:istration)?)(?:\s*(?:no\.?|number|#))?\s*[:：#-]?\s*[A-Z]{0,2}\d{7,17}\b/i,
  },
];

/** Labels of the secrets found in `text` (empty when it is safe to store). */
export function findSecrets(text: string): string[] {
  return SECRET_PATTERNS.filter(({ pattern }) => pattern.test(text)).map(({ label }) => label);
}

// ─── Search terms ───────────────────────────────────────────────────────────

const STOPWORDS = new Set(
  (
    "a an the is are was were be been am do does did of to in on at by for with from about as into and or but not " +
    "what whats what's where who whom whose which when why how this that these those it its i me my mine we our " +
    "you your he him his she her they them their there here can could would should will shall may might must " +
    "please tell know show give let lets let's get got any some all much many more most jeannie hey hi hello " +
    "뭐 뭐야 뭐예요 무엇 어디 어디야 누구 누구야 언제 왜 어떻게 얼마 몇 좀 제 내 저 나 우리 그 이 저기 알려줘 알려 주세요 말해줘 있어 있어요 있나요 인가요 이야 예요 이에요"
  ).split(/\s+/),
);

// Longest first, so "에서" is stripped before "서" could be.
const KOREAN_PARTICLES = [
  "으로부터", "에게서", "한테서", "이라고", "까지는", "에서는", "에게는", "으로는",
  "에서", "에게", "한테", "으로", "부터", "까지", "처럼", "보다", "이랑", "하고", "이나", "라고", "이야", "이에요", "예요", "인가요", "인가",
  "은", "는", "이", "가", "을", "를", "에", "의", "로", "와", "과", "도", "만", "랑", "야", "요",
];

function stripParticle(word: string): string {
  for (const particle of KOREAN_PARTICLES) {
    if (word.length > particle.length + 1 && word.endsWith(particle)) return word.slice(0, -particle.length);
  }
  return word;
}

/**
 * A question → up to 12 search terms: lowercased, punctuation removed, mixed
 * scripts split ("HGLC는" → "hglc"), Korean particles stripped, stopwords
 * dropped. The database matches each term as a prefix, ranked by how many hit.
 */
export function searchTerms(query: string, max = 12): string[] {
  const terms: string[] = [];
  const split = query
    .toLowerCase()
    .replace(/['’]s\b/g, "")
    // A space wherever Hangul meets another script: "hglc는" → "hglc 는".
    .replace(/(?<=\p{Script=Hangul})(?=[^\p{Script=Hangul}])|(?<=[^\p{Script=Hangul}])(?=\p{Script=Hangul})/gu, " ");
  const words = split.match(/[\p{L}\p{N}]+/gu) ?? [];
  for (const raw of words) {
    const hangul = /\p{Script=Hangul}/u.test(raw);
    const clean = hangul ? stripParticle(raw) : raw;
    if (!hangul && clean.length < 2) continue;
    if (STOPWORDS.has(clean) || STOPWORDS.has(raw) || KOREAN_PARTICLES.includes(raw)) continue;
    if (!terms.includes(clean)) terms.push(clean);
    if (terms.length >= max) break;
  }
  return terms;
}
