"use client";

import { Fragment, useMemo, type ReactNode } from "react";
import type { SourceLink } from "@/lib/types";

// A deliberately small, safe Markdown renderer for Jeannie's replies. It builds
// React elements directly (never HTML strings), only links http(s)/mailto URLs,
// and tolerates half-finished syntax while a reply is still streaming.

type Block =
  | { type: "code"; lang: string; text: string }
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; start: number; items: string[] }
  | { type: "quote"; text: string }
  | { type: "divider" }
  | { type: "paragraph"; text: string };

const FENCE_OPEN = /^\s*```\s*([\w+#.-]*)\s*$/;
const FENCE_CLOSE = /^\s*```\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;
const DIVIDER = /^\s*(?:[—–]{1,2}|-{3,}|\*{3,}|_{3,})\s*$/;
const BULLET = /^\s*[-*+•]\s+(.*)$/;
const ORDERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;

function startsBlock(line: string): boolean {
  return (
    FENCE_OPEN.test(line) ||
    HEADING.test(line) ||
    DIVIDER.test(line) ||
    BULLET.test(line) ||
    ORDERED.test(line) ||
    QUOTE.test(line)
  );
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fence = FENCE_OPEN.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE_CLOSE.test(lines[i])) body.push(lines[i++]);
      i++; // closing fence (absent while streaming: the rest is code)
      blocks.push({ type: "code", lang: fence[1], text: body.join("\n") });
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].replace(/\s+#+\s*$/, "") });
      i++;
      continue;
    }
    if (DIVIDER.test(line)) {
      blocks.push({ type: "divider" });
      i++;
      continue;
    }
    const bullet = BULLET.exec(line);
    const ordered = bullet ? null : ORDERED.exec(line);
    if (bullet || ordered) {
      const isOrdered = Boolean(ordered);
      const marker = isOrdered ? ORDERED : BULLET;
      const items: string[] = [];
      const start = ordered ? Number(ordered[1]) : 1;
      while (i < lines.length) {
        const current = lines[i];
        const match = marker.exec(current);
        if (match) {
          items.push(isOrdered ? match[2] : match[1]);
          i++;
          continue;
        }
        // Indented continuation of the previous item.
        if (current.trim() && /^\s{2,}/.test(current) && !startsBlock(current) && items.length) {
          items[items.length - 1] += ` ${current.trim()}`;
          i++;
          continue;
        }
        // A blank line only ends the list if the next line is not another item.
        if (!current.trim() && i + 1 < lines.length && marker.test(lines[i + 1])) {
          i++;
          continue;
        }
        break;
      }
      blocks.push({ type: "list", ordered: isOrdered, start, items });
      continue;
    }
    if (QUOTE.test(line)) {
      const quoted: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) quoted.push(QUOTE.exec(lines[i++])?.[1] ?? "");
      blocks.push({ type: "quote", text: quoted.join("\n") });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && (para.length === 0 || !startsBlock(lines[i]))) para.push(lines[i++]);
    blocks.push({ type: "paragraph", text: para.join("\n") });
  }
  return blocks;
}

/** Only web and mail links survive; everything else (javascript:, data:, relative) renders as text. */
export function safeHref(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:" ? url.href : null;
  } catch {
    return null;
  }
}

const INLINE =
  /(`+)([^`]+?)\1|\*\*([^*\n]+?)\*\*|__([^_\n]+?)__|\[([^\]\n]+)\]\(([^)\s]+)\)|\[(\d{1,2})\]|(https?:\/\/[^\s<>()[\]]*[^\s<>()[\].,;:!?'"])|\*([^*\s](?:[^*\n]*?[^*\s])?)\*/g;

const linkClass =
  "text-neon-hot underline decoration-neon/50 underline-offset-2 transition-colors hover:text-white hover:decoration-neon-hot [overflow-wrap:anywhere]";

function renderInline(text: string, sources: SourceLink[] | undefined, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0;
    if (at > last) nodes.push(text.slice(last, at));
    const key = `${keyPrefix}-${index++}`;
    const [whole, , code, bold, boldAlt, linkText, linkUrl, citation, bareUrl, italic] = match;

    if (code !== undefined) {
      nodes.push(
        <code key={key} className="rounded bg-neon/10 px-1 py-px font-mono text-[0.85em] text-neon-hot">
          {code}
        </code>,
      );
    } else if (bold !== undefined || boldAlt !== undefined) {
      nodes.push(
        <strong key={key} className="font-semibold text-white">
          {renderInline(bold ?? boldAlt ?? "", sources, key)}
        </strong>,
      );
    } else if (linkText !== undefined && linkUrl !== undefined) {
      const href = safeHref(linkUrl);
      nodes.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer" className={linkClass}>
            {renderInline(linkText, sources, key)}
          </a>
        ) : (
          <Fragment key={key}>{linkText}</Fragment>
        ),
      );
    } else if (citation !== undefined) {
      const n = Number(citation);
      const source = sources?.[n - 1];
      const href = source ? safeHref(source.url) : null;
      nodes.push(
        href ? (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            title={source?.title}
            aria-label={`Source ${n}: ${source?.title ?? href}`}
            className="relative -top-[0.35em] mx-px inline-flex h-[1.15rem] min-w-[1.15rem] items-center justify-center rounded-sm border border-neon/50 bg-neon/15 px-1 font-mono text-[0.62rem] leading-none text-petal-soft transition-colors hover:bg-neon hover:text-white"
          >
            {n}
          </a>
        ) : (
          <sup key={key} className="font-mono text-[0.65rem] text-neon-hot">
            [{n}]
          </sup>
        ),
      );
    } else if (bareUrl !== undefined) {
      const href = safeHref(bareUrl);
      nodes.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer" className={linkClass}>
            {bareUrl.replace(/^https?:\/\/(www\.)?/, "")}
          </a>
        ) : (
          <Fragment key={key}>{bareUrl}</Fragment>
        ),
      );
    } else if (italic !== undefined) {
      nodes.push(
        <em key={key} className="italic text-petal">
          {renderInline(italic, sources, key)}
        </em>,
      );
    } else {
      nodes.push(whole);
    }
    last = at + whole.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** Inline text with hard line breaks preserved. */
function renderLines(text: string, sources: SourceLink[] | undefined, keyPrefix: string): ReactNode[] {
  return text.split("\n").flatMap((line, i) => {
    const content = renderInline(line, sources, `${keyPrefix}-l${i}`);
    return i === 0 ? content : [<br key={`${keyPrefix}-br${i}`} />, ...content];
  });
}

interface MarkdownProps {
  text: string;
  sources?: SourceLink[];
  /** Appended inside the last block (e.g. the streaming cursor). */
  tail?: ReactNode;
}

export function Markdown({ text, sources, tail }: MarkdownProps) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  if (blocks.length === 0) return tail ? <p>{tail}</p> : null;

  return (
    <div className="space-y-2.5 break-words text-[0.9rem] leading-relaxed [overflow-wrap:anywhere]">
      {blocks.map((block, index) => {
        const key = `b${index}`;
        const end = index === blocks.length - 1 ? tail : null;
        switch (block.type) {
          case "code":
            return (
              <div key={key} className="overflow-hidden rounded border border-neon/25 bg-black/50">
                {block.lang ? (
                  <div className="border-b border-neon/20 px-3 py-1 font-mono text-[0.6rem] uppercase tracking-[0.2em] text-petal/80">
                    {block.lang}
                  </div>
                ) : null}
                <pre className="overflow-x-auto px-3 py-2 font-mono text-[0.78rem] leading-relaxed text-petal-soft [overflow-wrap:normal]">
                  <code>{block.text}</code>
                  {end}
                </pre>
              </div>
            );
          case "heading":
            return (
              <p
                key={key}
                className={
                  block.level <= 2
                    ? "pt-1 font-display text-[0.78rem] font-semibold uppercase tracking-[0.18em] text-neon-hot"
                    : "pt-1 font-semibold text-white"
                }
              >
                {renderInline(block.text, sources, key)}
                {end}
              </p>
            );
          case "divider":
            return (
              <div key={key} role="separator" className="flex items-center gap-2 py-1">
                <span className="hud-divider flex-1" />
                <span className="h-1.5 w-1.5 rotate-45 bg-neon-hot shadow-glow-sm" />
                <span className="hud-divider flex-1" />
                {end}
              </div>
            );
          case "quote":
            return (
              <blockquote key={key} className="border-l-2 border-neon/60 bg-neon/5 py-1 pl-3 text-petal-soft/90">
                {renderLines(block.text, sources, key)}
                {end}
              </blockquote>
            );
          case "list": {
            const ListTag = block.ordered ? "ol" : "ul";
            return (
              <ListTag key={key} className="space-y-1.5" start={block.ordered ? block.start : undefined}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-${itemIndex}`} className="flex gap-2">
                    <span
                      aria-hidden="true"
                      className={
                        block.ordered
                          ? "min-w-[1.4rem] shrink-0 pt-px font-mono text-[0.75rem] text-neon-hot"
                          : "mt-[0.55em] h-1.5 w-1.5 shrink-0 rotate-45 bg-neon shadow-glow-sm"
                      }
                    >
                      {block.ordered ? `${String(block.start + itemIndex).padStart(2, "0")}` : null}
                    </span>
                    <span className="min-w-0 flex-1">
                      {renderInline(item, sources, `${key}-${itemIndex}`)}
                      {itemIndex === block.items.length - 1 ? end : null}
                    </span>
                  </li>
                ))}
              </ListTag>
            );
          }
          default:
            return (
              <p key={key}>
                {renderLines(block.text, sources, key)}
                {end}
              </p>
            );
        }
      })}
    </div>
  );
}
