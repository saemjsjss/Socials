import { MockLanguageModelV4 } from "ai/test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildSessionGreeting, cleanGreeting, describeAway, greetingPrompt, parseAwayMs, partOfDay } from "@/lib/agents/greeting";

const EVENING = new Date("2026-09-29T13:05:00Z"); // 19:05 in Dhaka

function textModel(text: string | (() => Promise<never>)) {
  return new MockLanguageModelV4({
    doGenerate: async () => {
      if (typeof text === "function") return text();
      return {
        content: [{ type: "text", text }],
        finishReason: { unified: "stop", raw: "stop" },
        usage: {
          inputTokens: { total: 1, noCache: 1, cacheRead: 0, cacheWrite: 0 },
          outputTokens: { total: 1, text: 1, reasoning: 0 },
        },
        warnings: [],
      };
    },
  });
}

beforeEach(() => {
  vi.stubEnv("MOCK_MODE", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("greeting helpers", () => {
  it("names the part of day", () => {
    expect([6, 13, 19, 23, 3].map(partOfDay)).toEqual(["아침", "오후", "저녁", "늦은 밤", "늦은 밤"]);
  });

  it("describes time away only past an hour", () => {
    expect(describeAway(undefined)).toBeNull();
    expect(describeAway(Number.NaN)).toBeNull();
    expect(describeAway(59 * 60_000)).toBeNull();
    expect(describeAway(3 * 3_600_000)).toBe("약 3시간");
    expect(describeAway(2 * 86_400_000)).toBe("2일");
    expect(describeAway(21 * 86_400_000)).toBe("약 3주");
    expect(describeAway(90 * 86_400_000)).toBe("약 3개월");
  });

  it("parses awayMs strictly", () => {
    expect(parseAwayMs("7200000")).toBe(7_200_000);
    expect(parseAwayMs(null)).toBeNull();
    expect(parseAwayMs("-5")).toBeNull();
    expect(parseAwayMs("1e9")).toBeNull();
    expect(parseAwayMs("abc")).toBeNull();
  });

  it("builds the prompt from the facts", () => {
    const prompt = greetingPrompt({ localTime: "19:05", hour: 19, timeZone: "Asia/Dhaka", honorific: "자기야", away: "2일", memory: "Your memory: launch on Friday." });
    expect(prompt).toContain("19:05 (저녁) in Asia/Dhaka");
    expect(prompt).toContain("away for 2일");
    expect(prompt).toContain("Address the user as 자기야");
    expect(prompt).toContain("launch on Friday");
    expect(greetingPrompt({ localTime: "10:00", hour: 10, timeZone: "Asia/Dhaka", honorific: "부장님", away: null, memory: "" })).toContain(
      "do not mention being away",
    );
  });

  it("cleans the model's line and rejects unusable ones", () => {
    expect(cleanGreeting('[emote:greeting] "좋은 저녁이에요, 자기야."\n')).toBe("좋은 저녁이에요, 자기야.");
    expect(cleanGreeting("**좋은 아침이에요**, 부장님.")).toBe("좋은 아침이에요, 부장님.");
    expect(cleanGreeting("Good evening!")).toBeNull();
    expect(cleanGreeting("")).toBeNull();
    expect(cleanGreeting("가".repeat(300))).toBeNull();
  });
});

describe("buildSessionGreeting", () => {
  it("returns the model's greeting with recalled memory for trusted callers", async () => {
    const model = textModel("좋은 저녁이에요, 자기야. 금요일 출시 준비는 잘 되고 있어요?");
    const recall = vi.fn(async () => "Your memory: product launch on Friday.");
    const result = await buildSessionGreeting({ now: EVENING, timeZone: "Asia/Dhaka", awayMs: 3 * 3_600_000, trusted: true, model, recall });
    expect(result).toEqual({
      greeting: "좋은 저녁이에요, 자기야. 금요일 출시 준비는 잘 되고 있어요?",
      honorific: "자기야",
      localTime: "19:05",
      timeZone: "Asia/Dhaka",
      source: "ai",
    });
    const prompt = JSON.stringify(model.doGenerateCalls[0]!.prompt);
    expect(prompt).toContain("product launch on Friday");
    expect(prompt).toContain("약 3시간");
    expect(prompt).not.toContain("[emote:");
  });

  it("skips memory for untrusted callers", async () => {
    const recall = vi.fn(async () => "secret");
    await buildSessionGreeting({ now: EVENING, timeZone: "Asia/Dhaka", trusted: false, model: textModel("안녕하세요, 자기야."), recall });
    expect(recall).not.toHaveBeenCalled();
  });

  it("fails open when recall throws", async () => {
    const recall = vi.fn(async () => Promise.reject(new Error("supabase down")));
    const result = await buildSessionGreeting({ now: EVENING, timeZone: "Asia/Dhaka", trusted: true, model: textModel("안녕하세요, 자기야."), recall });
    expect(result.source).toBe("ai");
  });

  it("falls back to the template on a model error or timeout", async () => {
    const failing = textModel(() => Promise.reject(new Error("boom")));
    const failed = await buildSessionGreeting({ now: EVENING, timeZone: "Asia/Dhaka", trusted: false, model: failing, rng: () => 0 });
    expect(failed).toMatchObject({ source: "template", honorific: "자기야", localTime: "19:05" });
    expect(failed.greeting.startsWith("좋은 저녁입니다, 자기야. ")).toBe(true);

    const slow = new MockLanguageModelV4({
      doGenerate: ({ abortSignal }) =>
        new Promise((_, reject) => abortSignal?.addEventListener("abort", () => reject(new Error("aborted")))),
    });
    const late = await buildSessionGreeting({ now: EVENING, timeZone: "Asia/Dhaka", trusted: false, model: slow, timeoutMs: 50 });
    expect(late.source).toBe("template");
  });
});
