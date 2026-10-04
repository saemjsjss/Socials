// Emote protocol shared by the server persona and the avatar player.
//
// Every reply opens with one tag such as `[emote:concern]`. The avatar plays
// that clip; the tag is stripped before the text is shown, spoken or sent to
// Telegram. Replies without a tag fall back to "talking".

/** Emotes the model may choose for a reply. */
export const REPLY_EMOTES = [
  "greeting",
  "air_kiss",
  "nod",
  "supportive",
  "concern",
  "sadness",
  "love",
  "heartbeat",
  "shyness",
  "curiosity",
  "excitement",
  "playful",
  "stress",
  "frustration",
  "peek",
  "spin",
] as const;

export type ReplyEmote = (typeof REPLY_EMOTES)[number];

/** Every clip the avatar can show: the app drives idle / listening / talking and the idle sequence (sway is idle-only). */
export const EMOTES = ["idle", "listening", "talking", "sway", ...REPLY_EMOTES] as const;

export type Emote = (typeof EMOTES)[number];

/** Emotes that play once over the base loop: reply emotes plus app-driven one-shots (sway). */
export type OneShotEmote = Exclude<Emote, "idle" | "listening" | "talking">;

export function isEmote(value: unknown): value is Emote {
  return typeof value === "string" && (EMOTES as readonly string[]).includes(value);
}

export function isReplyEmote(value: unknown): value is ReplyEmote {
  return typeof value === "string" && (REPLY_EMOTES as readonly string[]).includes(value);
}

// Tolerant of what models actually write: `[emote: nod]`, `[Emote:air-kiss]`, `[emote:air kiss]`.
const LEADING_TAG = /^\s*\[\s*emote\s*:\s*([a-z_ -]*?)\s*\]\s*/i;
// A whole tag anywhere, or an unterminated one at the very end (still streaming in).
const ANY_TAG = /\[\s*emote\s*:[^\]\n]{0,24}(?:\]|$)\s*/gi;

/** Names the model may still write for an emote that was renamed. */
const EMOTE_ALIASES: Record<string, string> = { excited: "playful" };

const normalizeName = (name: string) => {
  const normalized = name.trim().toLowerCase().replace(/[\s-]+/g, "_");
  return EMOTE_ALIASES[normalized] ?? normalized;
};

/**
 * Split a (possibly still streaming) reply into its emote and display text.
 * `pending` is true while the text could still be the start of a tag, so the
 * caller can hold back rendering the first few characters. Pass `final` once
 * the text is complete: nothing is held back then.
 */
export function parseEmote(
  text: string,
  options: { final?: boolean } = {},
): { emote: ReplyEmote | null; text: string; pending: boolean } {
  const match = LEADING_TAG.exec(text);
  if (match) {
    const name = normalizeName(match[1]!);
    return {
      emote: isReplyEmote(name) ? name : null,
      text: text.slice(match[0].length).replace(ANY_TAG, ""),
      pending: false,
    };
  }
  const head = text.trimStart();
  const compact = head.replace(/\s+/g, "").slice(0, 7).toLowerCase();
  const pending = !options.final && head.length < 32 && "[emote:".startsWith(compact) && !head.includes("]");
  return { emote: null, text: pending ? "" : text.replace(ANY_TAG, ""), pending };
}

/** Remove every emote tag from finished text (for TTS, Telegram, memory). */
export function stripEmotes(text: string): string {
  return parseEmote(text, { final: true }).text;
}

/** System-prompt line teaching the model the protocol. */
export const EMOTE_DIRECTIVE = `Begin every reply with exactly one emote tag chosen from: ${REPLY_EMOTES.map((e) => `[emote:${e}]`).join(", ")}.
Pick the one that matches your feeling:
- greeting when welcoming the user; air_kiss for affection or a warm goodbye.
- nod when agreeing, confirming or acknowledging (the default for ordinary replies); supportive when encouraging the user or reassuring them about a worry.
- concern when the user is stressed, tired, unwell or facing a problem; sadness for bad news or when you missed the user.
- love for deep affection or gratitude; heartbeat when the user flatters you or makes your heart flutter; shyness when complimented or teased.
- curiosity when asking a question or finding something intriguing; excitement for good news or the user's success; playful for light-hearted, teasing happiness.
- stress when a deadline, a heavy workload or something going wrong is under discussion; frustration only on the user's behalf, when something is unfair to them, never at the user.
- peek and spin only in light, fun moments, rarely.
The tag is invisible to the user; never mention it and never use it anywhere else in the reply.`;
