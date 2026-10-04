// Business days and clock times for the Hangeul answers. The agency's day is
// Asia/Dhaka (JEANNIE_TIMEZONE), while PostgREST returns UTC and the server
// runs in UTC, so every "today" is worked out here. Isomorphic (Intl only).

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

function parts(date: Date, timeZone: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date)) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return out;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function isIsoDay(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const m = ISO_DAY.exec(value);
  if (!m) return false;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.getUTCFullYear() === Number(m[1]) && d.getUTCMonth() === Number(m[2]) - 1 && d.getUTCDate() === Number(m[3]);
}

/** The business day ("YYYY-MM-DD") that `date` falls on in `timeZone`. */
export function businessDay(date: Date, timeZone: string): string {
  const p = parts(date, timeZone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

/** The business day of an ISO timestamp; null when it is not a time. */
export function dayOf(iso: string | null | undefined, timeZone: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : businessDay(date, timeZone);
}

export function addDays(day: string, n: number): string {
  const m = ISO_DAY.exec(day);
  if (!m) return day;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + n));
  return d.toISOString().slice(0, 10);
}

export function firstOfMonth(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

/** Last day of the month before `day`'s month, and its first day. */
export function previousMonth(day: string): { from: string; to: string } {
  const to = addDays(firstOfMonth(day), -1);
  return { from: firstOfMonth(to), to };
}

/** "30 Sep" (with the year when it is not `thisYear`). */
export function shortDay(day: string, thisYear?: string): string {
  const m = ISO_DAY.exec(day);
  if (!m) return day;
  const base = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
  return thisYear && thisYear !== m[1] ? `${base} ${m[1]}` : base;
}

/** "30 Sep 2026" (the portal's own way of writing a day). */
export function longDay(day: string): string {
  const m = ISO_DAY.exec(day);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : day;
}

/** "Sep 2026" for any day of that month. */
export function monthName(day: string): string {
  const m = ISO_DAY.exec(day);
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : day;
}

/** "9월 30일" (with the year when it is not `thisYear`). */
export function koDay(day: string, thisYear?: string): string {
  const m = ISO_DAY.exec(day);
  if (!m) return day;
  const base = `${Number(m[2])}월 ${Number(m[3])}일`;
  return thisYear && thisYear !== m[1] ? `${m[1]}년 ${base}` : base;
}

/** "HH:MM" of an ISO time in `timeZone`; "" when it is not a time. */
export function clock(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const p = parts(date, timeZone);
  return `${pad(p.hour % 24)}:${pad(p.minute)}`;
}

/** The UTC instant of `hh:mm` local time on business day `day` in `timeZone`, as ISO. */
export function zonedTime(day: string, timeZone: string, hour = 0, minute = 0): string {
  const m = ISO_DAY.exec(day);
  if (!m) return "";
  const wall = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), hour, minute);
  let guess = wall;
  // Two rounds settle any offset change at the boundary (Asia/Dhaka has none).
  for (let i = 0; i < 2; i++) {
    const p = parts(new Date(guess), timeZone);
    const seen = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
    guess += wall - seen;
  }
  return new Date(guess).toISOString();
}
