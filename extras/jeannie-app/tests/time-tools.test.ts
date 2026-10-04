import { describe, expect, it } from "vitest";
import { routeQuery } from "@/lib/agents/orchestrator";
import { convertTime, currentTime, isClockQuery, resolveTimeZone, utcOffsetMinutes, zonedTime } from "@/lib/agents/time-tools";

const NOW = new Date("2026-09-29T14:15:00Z"); // 20:15 in Dhaka, 23:15 in Seoul

describe("resolveTimeZone", () => {
  it.each([
    ["Dhaka", "Asia/Dhaka"],
    ["  new   york ", "America/New_York"],
    ["서울", "Asia/Seoul"],
    ["Los Angeles", "America/Los_Angeles"],
    ["Asia/Tokyo", "Asia/Tokyo"],
    ["europe/london", "Europe/London"],
    ["UTC", "UTC"],
  ])("%j → %s", (input, zone) => {
    expect(resolveTimeZone(input)).toBe(zone);
  });

  it.each(["Mars/Olympus", "", "Atlantis"])("rejects %j", (input) => {
    expect(resolveTimeZone(input)).toBeNull();
  });
});

describe("currentTime", () => {
  it("defaults to the home zone", () => {
    expect(currentTime(undefined, { now: NOW, homeZone: "Asia/Dhaka" })).toEqual({
      query: "Asia/Dhaka",
      timeZone: "Asia/Dhaka",
      date: "2026-09-29",
      time: "20:15",
      weekday: "Tuesday",
      utcOffset: "+06:00",
    });
  });

  it("reads a city, crossing midnight", () => {
    expect(currentTime("Sydney", { now: NOW, homeZone: "Asia/Dhaka" })).toMatchObject({
      timeZone: "Australia/Sydney",
      date: "2026-09-30",
      time: "00:15",
      weekday: "Wednesday",
      utcOffset: "+10:00",
    });
    expect(currentTime("New York", { now: NOW, homeZone: "Asia/Dhaka" })).toMatchObject({ time: "10:15", utcOffset: "-04:00" });
  });

  it("explains an unknown zone", () => {
    expect(currentTime("Gotham", { now: NOW, homeZone: "Asia/Dhaka" })).toEqual({ error: expect.stringContaining("Gotham") });
  });
});

describe("convertTime", () => {
  it("converts an HH:mm wall time on today's date in the source zone", () => {
    expect(convertTime({ time: "15:30", from: "Dhaka", to: "Seoul" }, { now: NOW })).toEqual({
      from: { timeZone: "Asia/Dhaka", date: "2026-09-29", time: "15:30", weekday: "Tuesday", utcOffset: "+06:00" },
      to: { timeZone: "Asia/Seoul", date: "2026-09-29", time: "18:30", weekday: "Tuesday", utcOffset: "+09:00" },
      dayShift: 0,
    });
  });

  it("reports the day shift and accepts am/pm and an explicit date", () => {
    const result = convertTime({ time: "9pm", date: "2026-12-31", from: "Asia/Seoul", to: "London" });
    expect(result).toMatchObject({ to: { date: "2026-12-31", time: "12:00", utcOffset: "+00:00" }, dayShift: 0 });
    const late = convertTime({ time: "23:00", date: "2026-09-29", from: "Dhaka", to: "Tokyo" });
    expect(late).toMatchObject({ to: { date: "2026-09-30", time: "02:00" }, dayShift: 1 });
  });

  it("takes a local ISO time in the source zone, or an absolute instant", () => {
    expect(convertTime({ time: "2026-07-01T09:00", from: "London", to: "UTC" })).toMatchObject({ to: { time: "08:00" } }); // BST
    expect(convertTime({ time: "2026-07-01T09:00Z", from: "UTC", to: "Dhaka" })).toMatchObject({ to: { time: "15:00" } });
  });

  it("handles daylight saving on both sides", () => {
    // New York is UTC-5 in January, UTC-4 in July.
    expect(convertTime({ time: "12:00", date: "2026-01-15", from: "New York", to: "UTC" })).toMatchObject({ to: { time: "17:00" } });
    expect(convertTime({ time: "12:00", date: "2026-07-15", from: "New York", to: "UTC" })).toMatchObject({ to: { time: "16:00" } });
  });

  it("rejects bad input with a readable error", () => {
    expect(convertTime({ time: "25:00", from: "Dhaka", to: "Seoul" })).toHaveProperty("error");
    expect(convertTime({ time: "noonish", from: "Dhaka", to: "Seoul" })).toHaveProperty("error");
    expect(convertTime({ time: "10:00", date: "2026-02-30", from: "Dhaka", to: "Seoul" })).toHaveProperty("error");
    expect(convertTime({ time: "10:00", from: "Nowhere", to: "Seoul" })).toEqual({ error: expect.stringContaining("Nowhere") });
  });
});

describe("zone helpers", () => {
  it("computes offsets", () => {
    expect(utcOffsetMinutes(NOW, "Asia/Dhaka")).toBe(360);
    expect(utcOffsetMinutes(NOW, "Asia/Kolkata")).toBe(330);
    expect(zonedTime(NOW, "Asia/Kolkata").utcOffset).toBe("+05:30");
  });
});

describe("clock questions", () => {
  it.each([
    "What time is it in Seoul?",
    "what's the time in London",
    "current time in Tokyo",
    "time difference between Dhaka and Seoul",
    "convert 3pm Dhaka time to Seoul",
    "지금 서울 몇 시야?",
    "현재 몇 시예요?",
    "한국이랑 시차가 얼마나 돼?",
  ])("routes %j to the core agent's time tools", (text) => {
    expect(isClockQuery(text)).toBe(true);
    expect(routeQuery({ text, hasImage: false }).agent).toBe("core");
  });

  it.each(["What time does the game start tonight?", "몇 시에 시작해?", "convert 5 dollars to won", "Tell me about Seoul"])(
    "leaves %j alone",
    (text) => {
      expect(isClockQuery(text)).toBe(false);
    },
  );
});
