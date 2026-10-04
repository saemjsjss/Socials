import { describe, expect, it } from "vitest";
import {
  ENCOURAGEMENTS,
  greetingHonorific,
  honorificDirective,
  isPersonalMessage,
  koreanGreetingForHour,
  localClock,
  pickHonorific,
  pickWeighted,
  sessionGreeting,
} from "@/lib/agents/etiquette";

describe("pickWeighted", () => {
  it("lays the options out on a cumulative scale", () => {
    const options = [
      { value: "a", weight: 0.6 },
      { value: "b", weight: 0.1 },
      { value: "c", weight: 0.3 },
    ];
    expect(pickWeighted(options, () => 0)).toBe("a");
    expect(pickWeighted(options, () => 0.5999)).toBe("a");
    expect(pickWeighted(options, () => 0.6)).toBe("b");
    expect(pickWeighted(options, () => 0.6999)).toBe("b");
    expect(pickWeighted(options, () => 0.7)).toBe("c");
    expect(pickWeighted(options, () => 0.9999999)).toBe("c");
  });

  it("normalizes weights that do not sum to 1 and skips zero weights", () => {
    const options = [
      { value: "x", weight: 3 },
      { value: "never", weight: 0 },
      { value: "y", weight: 1 },
    ];
    expect(pickWeighted(options, () => 0.74)).toBe("x");
    expect(pickWeighted(options, () => 0.75)).toBe("y");
    expect(pickWeighted(options, () => 1)).toBe("y"); // out-of-range draw is clamped
  });

  it("rejects empty, negative and all-zero weights", () => {
    expect(() => pickWeighted([])).toThrow(RangeError);
    expect(() => pickWeighted([{ value: 1, weight: -1 }])).toThrow(RangeError);
    expect(() => pickWeighted([{ value: 1, weight: 0 }])).toThrow(RangeError);
    expect(() => pickWeighted([{ value: 1, weight: Number.NaN }])).toThrow(RangeError);
  });
});

describe("honorifics", () => {
  it.each([
    "Draft the Q3 budget memo",
    "What's on the agenda for the board meeting?",
    "계약서 검토해 줘",
    "Explain binary search in Python",
  ])("uses 부장님 for work: %j", (text) => {
    expect(pickHonorific({ text, agent: "core" })).toBe("부장님");
  });

  it.each([
    "I'm so tired today",
    "I missed you, Jeannie",
    "good night!",
    "오늘 너무 피곤해",
    "보고 싶었어",
    "자기야 뭐 해?",
    "기분이 좀 우울해",
  ])("uses 자기야 for personal moments: %j", (text) => {
    expect(isPersonalMessage(text)).toBe(true);
    expect(pickHonorific({ text, agent: "core" })).toBe("자기야");
  });

  it("keeps specialist agents on 부장님 whatever the wording", () => {
    for (const agent of ["audit", "hangeul", "search", "vision", "iot"] as const) {
      expect(pickHonorific({ text: "I'm tired, check the portal", agent })).toBe("부장님");
    }
    expect(pickHonorific({ text: "I'm tired" })).toBe("자기야");
  });

  it("greets with 부장님 in office hours and 자기야 outside them", () => {
    expect(greetingHonorific(8)).toBe("자기야");
    expect(greetingHonorific(9)).toBe("부장님");
    expect(greetingHonorific(17)).toBe("부장님");
    expect(greetingHonorific(18)).toBe("자기야");
    expect(greetingHonorific(0)).toBe("자기야");
  });

  it("tells the model to use exactly that title, and when each applies", () => {
    expect(honorificDirective("부장님")).toContain('"부장님"');
    expect(honorificDirective("부장님")).toMatch(/work or business/);
    expect(honorificDirective("자기야")).toContain('"네, 자기야."');
    expect(honorificDirective("자기야")).toMatch(/affectionate, personal/);
    expect(honorificDirective("자기야")).toMatch(/use only "자기야" and no other title/);
  });
});

describe("Korean session greeting", () => {
  it.each([
    [5, "좋은 아침입니다"],
    [11, "좋은 아침입니다"],
    [12, "좋은 오후입니다"],
    [17, "좋은 오후입니다"],
    [18, "좋은 저녁입니다"],
    [21, "좋은 저녁입니다"],
    [22, "늦은 시간까지 수고 많으십니다"],
    [0, "늦은 시간까지 수고 많으십니다"],
    [4, "늦은 시간까지 수고 많으십니다"],
  ])("hour %i → %s", (hour, expected) => {
    expect(koreanGreetingForHour(hour)).toBe(expected);
  });

  it("reads the hour in the operator's time zone", () => {
    const utc0230 = new Date("2026-09-28T02:30:00Z");
    expect(localClock(utc0230, "Asia/Dhaka")).toEqual({ hour: 8, time: "08:30" }); // UTC+6
    expect(localClock(utc0230, "Asia/Seoul")).toEqual({ hour: 11, time: "11:30" }); // UTC+9
    expect(localClock(utc0230, "UTC")).toEqual({ hour: 2, time: "02:30" });
    expect(localClock(new Date("2026-09-28T18:00:00Z"), "Asia/Dhaka").hour).toBe(0); // midnight, not 24
  });

  it("builds greeting, honorific and encouragement", () => {
    const evening = new Date("2026-09-28T13:05:00Z"); // 19:05 in Dhaka
    const result = sessionGreeting({ now: evening, timeZone: "Asia/Dhaka", honorific: "부장님", rng: () => 0 });
    expect(result).toEqual({
      greeting: `좋은 저녁입니다, 부장님. ${ENCOURAGEMENTS[0]}`,
      honorific: "부장님",
      localTime: "19:05",
      timeZone: "Asia/Dhaka",
    });
  });

  it("picks the title from the local hour when none is given", () => {
    const morning = new Date("2026-09-28T01:00:00Z"); // 07:00 in Dhaka
    const result = sessionGreeting({ now: morning, timeZone: "Asia/Dhaka", rng: () => 0.95 });
    expect(result.honorific).toBe("자기야");
    expect(result.greeting.startsWith("좋은 아침입니다, 자기야. ")).toBe(true);
    expect(ENCOURAGEMENTS).toContain(result.greeting.split("자기야. ")[1]);
    const noon = new Date("2026-09-28T06:00:00Z"); // 12:00 in Dhaka
    expect(sessionGreeting({ now: noon, timeZone: "Asia/Dhaka" }).honorific).toBe("부장님");
  });
});
