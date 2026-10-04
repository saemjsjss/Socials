import { describe, expect, it } from "vitest";
import { EMOTE_DIRECTIVE, REPLY_EMOTES, parseEmote, stripEmotes } from "@/lib/emote";

describe("parseEmote", () => {
  it("splits the leading tag from the text", () => {
    expect(parseEmote("[emote:concern] 괜찮아요, 부장님?")).toEqual({ emote: "concern", text: "괜찮아요, 부장님?", pending: false });
    expect(parseEmote("  [EMOTE:Nod]\nYes.")).toMatchObject({ emote: "nod", text: "Yes." });
  });

  it("accepts the spellings models actually write", () => {
    expect(parseEmote("[emote: nod] hi")).toMatchObject({ emote: "nod", text: "hi" });
    expect(parseEmote("[emote:air-kiss] hi")).toMatchObject({ emote: "air_kiss", text: "hi" });
    expect(parseEmote("[ emote : air kiss ] hi")).toMatchObject({ emote: "air_kiss", text: "hi" });
  });

  it("drops an unknown tag without playing it", () => {
    expect(parseEmote("[emote:happy] hi")).toEqual({ emote: null, text: "hi", pending: false });
  });

  it("holds back text that could still become a tag while streaming", () => {
    for (const partial of ["", "[", "[emo", "[emote:", "[emote:conc", " [emote: air"]) {
      expect(parseEmote(partial)).toMatchObject({ pending: true, text: "" });
    }
    expect(parseEmote("Hello")).toMatchObject({ pending: false, text: "Hello" });
    expect(parseEmote("[1] first")).toMatchObject({ pending: false, text: "[1] first" });
  });

  it("releases held-back text once the reply is final", () => {
    expect(parseEmote("[", { final: true })).toMatchObject({ pending: false, text: "[" });
  });

  it("strips tags repeated later in the reply (tool-loop steps)", () => {
    expect(parseEmote("[emote:nod] Let me check.\n\n[emote:nod] 서울은 맑아요.").text).toBe("Let me check.\n\n서울은 맑아요.");
    expect(parseEmote("[emote:nod] 네 [emote:conc").text).toBe("네 ");
  });
});

describe("stripEmotes", () => {
  it("never leaves tag fragments in finished text", () => {
    expect(stripEmotes("[emote:sadness] 아쉬워요.")).toBe("아쉬워요.");
    expect(stripEmotes("[emote: air-kiss] 잘 자요, 자기야.")).toBe("잘 자요, 자기야.");
    expect(stripEmotes("plain")).toBe("plain");
    expect(stripEmotes("[")).toBe("[");
  });
});

it("teaches every reply emote", () => {
  for (const emote of REPLY_EMOTES) expect(EMOTE_DIRECTIVE).toContain(`[emote:${emote}]`);
});

it("gives every reply emote a rule for when to use it", () => {
  const rules = EMOTE_DIRECTIVE.split("\n").slice(1).join("\n");
  for (const emote of REPLY_EMOTES) expect(rules).toMatch(new RegExp(`\\b${emote}\\b`));
});

describe("the Kling emote set", () => {
  it("parses every reply emote and strips its tag", () => {
    for (const emote of REPLY_EMOTES) {
      expect(parseEmote(`[emote:${emote}] 네.`)).toEqual({ emote, text: "네.", pending: false });
      expect(stripEmotes(`[emote:${emote}] 네.`)).toBe("네.");
    }
  });

  it("reads the old excited tag as playful", () => {
    expect(REPLY_EMOTES).toContain("playful");
    expect(REPLY_EMOTES).not.toContain("excited");
    expect(parseEmote("[emote:excited] 좋아요!")).toEqual({ emote: "playful", text: "좋아요!", pending: false });
    expect(stripEmotes("[emote:excited] 좋아요!")).toBe("좋아요!");
  });

  it("never lets the model drive the app-only clips", () => {
    for (const name of ["idle", "listening", "talking", "sway"]) {
      expect(REPLY_EMOTES).not.toContain(name);
      expect(parseEmote(`[emote:${name}] hi`)).toEqual({ emote: null, text: "hi", pending: false });
    }
  });
});
