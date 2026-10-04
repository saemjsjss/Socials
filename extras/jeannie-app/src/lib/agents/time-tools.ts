// Time tools: the current time in a city or IANA zone, and converting a wall
// time between zones. Pure Intl arithmetic (no network, no date library) so it
// runs on Edge and Node.js and is unit-tested with a fixed clock.

import { tool } from "ai";
import { z } from "zod";
import { getEnv } from "../env";

/** Common cities (English and Korean names) → IANA zone. Anything else must be an IANA name. */
export const CITY_TIME_ZONES: Readonly<Record<string, string>> = {
  dhaka: "Asia/Dhaka",
  다카: "Asia/Dhaka",
  bangladesh: "Asia/Dhaka",
  seoul: "Asia/Seoul",
  서울: "Asia/Seoul",
  busan: "Asia/Seoul",
  부산: "Asia/Seoul",
  korea: "Asia/Seoul",
  한국: "Asia/Seoul",
  tokyo: "Asia/Tokyo",
  도쿄: "Asia/Tokyo",
  japan: "Asia/Tokyo",
  일본: "Asia/Tokyo",
  london: "Europe/London",
  런던: "Europe/London",
  "new york": "America/New_York",
  nyc: "America/New_York",
  뉴욕: "America/New_York",
  dubai: "Asia/Dubai",
  두바이: "Asia/Dubai",
  singapore: "Asia/Singapore",
  싱가포르: "Asia/Singapore",
  sydney: "Australia/Sydney",
  시드니: "Australia/Sydney",
  "los angeles": "America/Los_Angeles",
  la: "America/Los_Angeles",
  로스앤젤레스: "America/Los_Angeles",
  "san francisco": "America/Los_Angeles",
  paris: "Europe/Paris",
  파리: "Europe/Paris",
  berlin: "Europe/Berlin",
  beijing: "Asia/Shanghai",
  shanghai: "Asia/Shanghai",
  베이징: "Asia/Shanghai",
  "hong kong": "Asia/Hong_Kong",
  delhi: "Asia/Kolkata",
  "new delhi": "Asia/Kolkata",
  mumbai: "Asia/Kolkata",
  kolkata: "Asia/Kolkata",
  bangkok: "Asia/Bangkok",
  jakarta: "Asia/Jakarta",
  toronto: "America/Toronto",
  chicago: "America/Chicago",
  utc: "UTC",
  gmt: "UTC",
};

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** "Seoul", "서울", "asia/seoul", "Asia/Seoul" → "Asia/Seoul"; null when unknown. */
export function resolveTimeZone(input: string): string | null {
  const key = input.trim().toLowerCase().replace(/\s+/g, " ");
  if (!key) return null;
  const city = CITY_TIME_ZONES[key];
  if (city) return city;
  try {
    // Intl accepts IANA names case-insensitively and reports the canonical spelling.
    return new Intl.DateTimeFormat("en-US", { timeZone: input.trim() }).resolvedOptions().timeZone;
  } catch {
    return null;
  }
}

interface WallClock {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function wallClock(date: Date, timeZone: string): WallClock {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? "0");
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour") % 24, minute: get("minute") };
}

/** Minutes `timeZone` is ahead of UTC at `date` (Dhaka: 360). */
export function utcOffsetMinutes(date: Date, timeZone: string): number {
  const w = wallClock(date, timeZone);
  const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute);
  const floored = Math.floor(date.getTime() / 60_000) * 60_000;
  return Math.round((asUtc - floored) / 60_000);
}

function formatOffset(minutes: number): string {
  const sign = minutes < 0 ? "-" : "+";
  const abs = Math.abs(minutes);
  return `${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

const pad = (n: number, width = 2) => String(n).padStart(width, "0");

export interface ZonedTime {
  timeZone: string;
  /** "2026-09-29" */
  date: string;
  /** "20:15" (24-hour) */
  time: string;
  weekday: string;
  /** "+06:00" */
  utcOffset: string;
}

/** The wall-clock view of an instant in `timeZone`. */
export function zonedTime(date: Date, timeZone: string): ZonedTime {
  const w = wallClock(date, timeZone);
  return {
    timeZone,
    date: `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}`,
    time: `${pad(w.hour)}:${pad(w.minute)}`,
    weekday: WEEKDAYS[new Date(Date.UTC(w.year, w.month - 1, w.day)).getUTCDay()]!,
    utcOffset: formatOffset(utcOffsetMinutes(date, timeZone)),
  };
}

/**
 * The instant at which `timeZone` shows this wall-clock time. In a DST gap the
 * later offset wins; in an overlap the earlier instant does.
 */
export function wallTimeToInstant(wall: WallClock, timeZone: string): Date {
  const guess = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  const first = guess - utcOffsetMinutes(new Date(guess), timeZone) * 60_000;
  const second = guess - utcOffsetMinutes(new Date(first), timeZone) * 60_000;
  return new Date(Math.min(first, second));
}

export type TimeResult<T> = T | { error: string };

/** currentTime tool body. `zone` is a city or IANA name; blank means the home zone. */
export function currentTime(zone: string | undefined, options: { now?: Date; homeZone: string }): TimeResult<ZonedTime & { query: string }> {
  const query = zone?.trim() || options.homeZone;
  const timeZone = resolveTimeZone(query);
  if (!timeZone) return { error: `Unknown city or time zone "${query}". Use an IANA name such as "Asia/Seoul".` };
  return { query, ...zonedTime(options.now ?? new Date(), timeZone) };
}

const CLOCK = /^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$/i;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_LOCAL = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/;
const ISO_ABSOLUTE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/i;

function parseClock(text: string): { hour: number; minute: number } | null {
  const match = CLOCK.exec(text.trim());
  if (!match) return null;
  let hour = Number(match[1]);
  const minute = Number(match[2] ?? "0");
  const meridiem = match[3]?.toLowerCase().replace(/\./g, "");
  if (meridiem) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (meridiem === "pm" ? 12 : 0);
  }
  return hour <= 23 && minute <= 59 ? { hour, minute } : null;
}

function validDay(year: number, month: number, day: number): boolean {
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day;
}

export interface ConvertTimeInput {
  /** "15:30", "3pm", "2026-09-29T15:30" (wall time in `from`) or an ISO instant with Z/offset. */
  time: string;
  /** "YYYY-MM-DD" for an "HH:mm" time; defaults to today in `from`. */
  date?: string;
  from: string;
  to: string;
}

/** convertTime tool body. */
export function convertTime(
  input: ConvertTimeInput,
  options: { now?: Date } = {},
): TimeResult<{ from: ZonedTime; to: ZonedTime; dayShift: number }> {
  const fromZone = resolveTimeZone(input.from);
  if (!fromZone) return { error: `Unknown city or time zone "${input.from}".` };
  const toZone = resolveTimeZone(input.to);
  if (!toZone) return { error: `Unknown city or time zone "${input.to}".` };

  const time = input.time.trim();
  let instant: Date;
  if (ISO_ABSOLUTE.test(time)) {
    instant = new Date(time);
  } else {
    const local = ISO_LOCAL.exec(time);
    let wall: WallClock;
    if (local) {
      const [, y, mo, d, h, mi] = local.map(Number) as number[];
      wall = { year: y!, month: mo!, day: d!, hour: h!, minute: mi! };
    } else {
      const clock = parseClock(time);
      if (!clock) return { error: `Could not read the time "${input.time}". Use "HH:mm" (24-hour) or an ISO timestamp.` };
      let day: Pick<WallClock, "year" | "month" | "day">;
      if (input.date?.trim()) {
        const match = ISO_DATE.exec(input.date.trim());
        if (!match) return { error: `Could not read the date "${input.date}". Use "YYYY-MM-DD".` };
        day = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
      } else {
        day = wallClock(options.now ?? new Date(), fromZone);
      }
      wall = { ...day, ...clock };
    }
    if (!validDay(wall.year, wall.month, wall.day) || wall.hour > 23 || wall.minute > 59) {
      return { error: `Invalid date or time "${input.time}".` };
    }
    instant = wallTimeToInstant(wall, fromZone);
  }
  if (Number.isNaN(instant.getTime())) return { error: `Invalid date or time "${input.time}".` };

  const from = zonedTime(instant, fromZone);
  const to = zonedTime(instant, toZone);
  const dayShift = Math.round((Date.parse(`${to.date}T00:00Z`) - Date.parse(`${from.date}T00:00Z`)) / 86_400_000);
  return { from, to, dayShift };
}

// ─── Routing ────────────────────────────────────────────────────────────────

/**
 * Clock questions ("what time is it in Seoul?", "지금 서울 몇 시야?", time
 * differences and conversions) go to the core agent and its time tools, not to
 * live search. "What time does the game start?" is not one of them.
 */
const CLOCK_QUERIES = [
  /\bwhat time is it\b|\bwhat(?:'s| is) the (?:current |local )?time\b|\bcurrent (?:local )?time\b|\blocal time in\b/i,
  /\btime difference\b|\btime zones?\b|\bconvert\b[^.?!\n]*\b\d{1,2}(?::\d{2}|\s*[ap]m\b)[^.?!\n]*\bto\b/i,
  /(?:지금|현재)\s*(?:[가-힣A-Za-z]+\s*)?몇\s*시|시차|현지\s*시간|[가-힣]+\s*시간으로\s*(?:바꿔|변환|환산)/,
];

export function isClockQuery(text: string): boolean {
  return CLOCK_QUERIES.some((cue) => cue.test(text));
}

// ─── Tools ──────────────────────────────────────────────────────────────────

export function createCurrentTimeTool() {
  return tool({
    description:
      "Get the current date and time in a city or IANA time zone. Leave both fields empty for the user's home time zone.",
    inputSchema: z.object({
      timeZone: z.string().optional().describe('IANA time zone, e.g. "Asia/Seoul"'),
      city: z.string().optional().describe('City name, e.g. "Seoul", "New York"'),
    }),
    execute: async ({ timeZone, city }) => currentTime(timeZone || city, { homeZone: getEnv().timeZone }),
  });
}

export function createConvertTimeTool() {
  return tool({
    description:
      "Convert a time from one city or IANA time zone to another. Returns both wall-clock times, UTC offsets and the day shift.",
    inputSchema: z.object({
      time: z.string().min(1).describe('"HH:mm" (24-hour), "3pm", or an ISO timestamp'),
      date: z.string().optional().describe('"YYYY-MM-DD" for an "HH:mm" time; defaults to today in the source zone'),
      from: z.string().min(1).describe("Source city or IANA time zone"),
      to: z.string().min(1).describe("Target city or IANA time zone"),
    }),
    execute: async (input) => convertTime(input),
  });
}
