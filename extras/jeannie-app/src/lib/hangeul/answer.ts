// Code-built Hangeul answers (spec D11): a question becomes a query plan
// (router.ts), the plan reads rows through a HangeulReaders (the server store,
// or the device's IndexedDB copy), and every figure and table is computed here
// from those rows. The language model only writes up to two sentences around
// them, and those sentences must pass the number check below.
//
// Rules this file keeps (the pack's R1/R5): a kind that was never published
// is "not available yet", never 0; a portal field left as N/A or PENDING
// (data.blank_on_portal) is "not given on the portal"; every answer ends with
// an "as of" line dated by the bot's runs (a record's read_at only moves when
// its content changes). ISOMORPHIC: no Node APIs and no "ai" import, so the
// PWA renders structured plans straight from IndexedDB with this same code.

import { addDays, businessDay, clock, dayOf, firstOfMonth, koDay, longDay, monthName, shortDay } from "./days";
import { classify, isHangeulContextQuery, isHangeulStatusQuery, normalizeQuery, type RouterContext } from "./router";
import {
  HG_KINDS,
  isHangeulReadError,
  type AnswerResult,
  type AnswerSource,
  type AsOf,
  type Bi,
  type Fact,
  type HangeulReaders,
  type HgHit,
  type HgKind,
  type HgRecord,
  type HgRun,
  type Plan,
  type RecordFilter,
  type ReportName,
  type StudentQuery,
  type Table,
} from "./types";

export { classify, isHangeulContextQuery, isHangeulStatusQuery, normalizeQuery };
export type { RouterContext };

export type AnswerLang = "en" | "ko" | "bilingual";

export interface RunOptions {
  now: Date;
  /** The business time zone (JEANNIE_TIMEZONE, Asia/Dhaka). */
  timeZone: string;
  /** The question's embedding computed on the device (384 numbers), for the semantic plan. */
  embedding?: readonly number[] | null;
  /** The device's own search hits: the answer re-reads these records instead of calling hg_match. */
  hits?: readonly AnswerSource[] | null;
  /** Korean/Bangla question → English search query (the stored text is English). Semantic plan only. */
  rewrite?: (question: string) => Promise<string | null>;
}

const bi = (en: string, ko: string): Bi => ({ en, ko });
const same = (text: string): Bi => ({ en: text, ko: text });

const NOT_GIVEN = bi("not given on the portal", "포털에 입력되지 않음");
const MAX_TABLE_ROWS = 40;

// ─── Labels ─────────────────────────────────────────────────────────────────

const JOB_LABEL: Record<string, Bi> = {
  full_picture: bi("full picture", "전체 점검"),
  portal_sync: bi("portal sync", "포털 동기화"),
  passport_watcher: bi("passport watcher", "여권 감시"),
  backfill: bi("backfill", "초기 적재"),
  daily_brief: bi("brief", "브리핑"),
  missing_report: bi("missing report", "누락 보고서"),
  issue_refresh: bi("issue refresh", "발급일 갱신"),
  stage_report: bi("stage report", "단계 보고서"),
  command: bi("command", "명령"),
  change_log: bi("change log, live", "변경 기록, 실시간"),
  // Report records are dated by when the report was made.
  document_check_report: bi("document check report", "서류 검사 보고서"),
  field_check_report: bi("field check report", "항목 검사 보고서"),
  inquiries_report: bi("inquiries report", "문의 보고서"),
};

const KIND_LABEL: Record<string, Bi> = {
  student: bi("students", "학생"),
  student_export: bi("student export rows", "학생 내보내기"),
  student_profile: bi("student profiles", "학생 프로필"),
  student_progress: bi("student progress", "학생 진행 상황"),
  student_documents: bi("verified documents", "검증된 서류"),
  verification: bi("payment verifications", "결제 확인"),
  consultation: bi("consultation requests", "상담 신청"),
  consultation_day: bi("consultation day counts", "일별 상담 신청 수"),
  consultation_totals: bi("consultation totals", "상담 신청 합계"),
  pending_payment: bi("pending payments", "미납"),
  window_application: bi("window applications", "윈도우 지원"),
  dashboard_fact: bi("dashboard figures", "대시보드 수치"),
  calendar_item: bi("calendar items", "일정"),
  passport_audit: bi("passport audits", "여권 검사"),
  passport_alert: bi("passport checks", "여권 확인"),
  passport_issue: bi("passport issue dates", "여권 발급일"),
  doc_verdict: bi("document verdicts", "서류 판정"),
  doc_check: bi("document checks", "서류 검사"),
  field_check: bi("field checks", "항목 검사"),
  field_correction: bi("field corrections", "항목 수정"),
  doc_page_text: bi("document page text", "서류 본문"),
  report: bi("reports", "보고서"),
  report_section: bi("report sections", "보고서 항목"),
  brief_fact: bi("brief facts", "브리핑 항목"),
  notification: bi("notifications", "알림"),
  consultant_performance: bi("consultant performance", "상담사 실적"),
};

function kindLabel(kind: string): Bi {
  return KIND_LABEL[kind] ?? same(kind.replace(/_/g, " "));
}

const TILE_KO: Record<string, string> = {
  "Consultancies done": "상담 완료",
  "Files opened": "파일 오픈",
  "Conversion (file open)": "전환율(파일 오픈)",
  "Docs ready": "서류 준비 완료",
};

const STATUS_KO: Record<string, string> = {
  New: "신규",
  Consulted: "상담 완료",
  "No Answer": "무응답",
  "File Opened": "파일 오픈",
  "Wrong Number": "잘못된 번호",
};

// ─── Small value helpers ────────────────────────────────────────────────────

function str(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/** "12,000.00 BDT" → 12000; "25%" → 25; "" → null. */
function num(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const m = /-?\d[\d,]*(?:\.\d+)?/.exec(str(value));
  if (!m) return null;
  const n = Number(m[0].replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

function fmtAmount(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function blanks(data: Record<string, unknown>): Set<string> {
  const list = data.blank_on_portal;
  return new Set(Array.isArray(list) ? list.filter((x): x is string => typeof x === "string") : []);
}

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function countBy<T>(items: readonly T[], key: (item: T) => string): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(key(item), (counts.get(key(item)) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function studentLabel(r: HgRecord): string {
  const name = r.student_name || str(r.data.student_name) || str(r.data.name) || str(r.data.student);
  const id = r.student_hng_id || str(r.data.student_id);
  return [name, id ? `(${id})` : ""].filter(Boolean).join(" ") || r.key;
}

function queryLabel(q: StudentQuery): string {
  return q.hngId ?? (q.uid !== undefined ? `uid ${q.uid}` : q.passport ?? q.name ?? "");
}

// ─── The run context ────────────────────────────────────────────────────────

class Run {
  readonly headline: Bi[] = [];
  readonly facts: Fact[] = [];
  readonly tables: Table[] = [];
  readonly notes: Bi[] = [];
  readonly sources: AnswerSource[] = [];
  readonly readTimes = new Map<string, string[]>();
  readonly overrides = new Map<string, AsOf>();
  private runList: HgRun[] = [];
  private runKinds = new Set<string>();
  readonly today: string;
  readonly thisYear: string;

  constructor(
    readonly readers: HangeulReaders,
    readonly options: RunOptions,
  ) {
    this.today = businessDay(options.now, options.timeZone);
    this.thisYear = this.today.slice(0, 4);
  }

  private runsLoaded = false;

  /** Loads the runs that date `kinds` (the first call always loads the recent runs). */
  async loadRuns(kinds: readonly string[]): Promise<void> {
    const missing = kinds.filter((k) => !this.runKinds.has(k));
    if (missing.length === 0 && this.runsLoaded) return;
    this.runsLoaded = true;
    const runs = await this.readers.runs(missing);
    for (const k of missing) this.runKinds.add(k);
    const seen = new Set(this.runList.map((r) => `${r.job}|${r.started_at}`));
    for (const run of runs) if (!seen.has(`${run.job}|${run.started_at}`)) this.runList.push(run);
    this.runList.sort((a, b) => ((a.finished_at ?? "") < (b.finished_at ?? "") ? 1 : -1));
  }

  private usable(run: HgRun): boolean {
    return run.finished_at !== null && (run.status === "ok" || run.status === "partial");
  }

  private reads(run: HgRun, kind: string): boolean {
    return this.usable(run) && Object.prototype.hasOwnProperty.call(run.byKind, kind);
  }

  /**
   * The newest finished run that dates `kind` as a whole. A `command` run does
   * not: a Telegram command publishes one scope (one day of /inquiries_*, one
   * period of /performance_*), so its time says nothing about the rest of the kind.
   */
  runFor(kind: string): HgRun | null {
    return this.runList.find((r) => r.job !== "command" && this.reads(r, kind)) ?? null;
  }

  /** Any finished run, commands included, that read `kind`: proof the kind is published at all. */
  private readBy(kind: string): HgRun | null {
    return this.runList.find((r) => this.reads(r, kind)) ?? null;
  }

  /**
   * The newest run that re-read day `day` of a day-scoped kind (consultation,
   * consultation_day): the full picture reads yesterday and today, the brief
   * and a command their own day, the backfill every day up to its own.
   */
  runForDay(kind: string, day: string): HgRun | null {
    return (
      this.runList.find((r) => {
        if (!this.reads(r, kind)) return false;
        const ranOn = dayOf(r.started_at || r.finished_at, this.options.timeZone);
        if (!ranOn) return false;
        switch (r.job) {
          case "full_picture":
            return ranOn === day || ranOn === addDays(day, 1);
          case "daily_brief":
          case "command":
            return ranOn === day;
          case "backfill":
            return ranOn >= day;
          default:
            return false;
        }
      }) ?? null
    );
  }

  /**
   * "As of" for day `day` of a day-scoped kind: the newest run that re-read that
   * day, or the rows' own read_at when that is newer (a read that changed them),
   * or null when nothing dates it.
   */
  datedDay(kind: string, day: string, rows: readonly HgRecord[]): AsOf | null {
    const run = this.runForDay(kind, day);
    const read = rows.reduce<string | null>((best, r) => (r.read_at && (!best || Date.parse(r.read_at) > Date.parse(best)) ? r.read_at : best), null);
    if (run?.finished_at && (!read || Date.parse(run.finished_at) >= Date.parse(read))) return { at: run.finished_at, job: run.job, source: "run" };
    return read ? { at: read, job: null, source: "read_at" } : null;
  }

  /** The last run on business day `day` that read `kind` (when a past day's window was last confirmed). */
  runOnDay(kind: string, day: string): HgRun | null {
    return (
      this.runList.find(
        (r) => this.usable(r) && Object.prototype.hasOwnProperty.call(r.byKind, kind) && dayOf(r.finished_at, this.options.timeZone) === day,
      ) ?? null
    );
  }

  /** The newest finished run of each job, newest first. */
  latestPerJob(): HgRun[] {
    const latest = new Map<string, HgRun>();
    for (const r of this.runList) if (this.usable(r) && !latest.has(r.job)) latest.set(r.job, r);
    return [...latest.values()];
  }

  /** Whether the bot has ever read this kind successfully (only then can "none" be said). */
  published(kind: string): boolean {
    return this.readBy(kind) !== null || (this.readTimes.get(kind)?.length ?? 0) > 0;
  }

  /** Leaves `kind` out of the "as of" line (it was looked up, but nothing of it is shown). */
  undate(kind: string): void {
    this.readTimes.delete(kind);
    this.overrides.delete(kind);
  }

  async read(kind: HgKind, filter?: RecordFilter): Promise<HgRecord[]> {
    const rows = await this.readers.records(kind, filter);
    const times = this.readTimes.get(kind) ?? [];
    for (const r of rows) if (r.read_at) times.push(r.read_at);
    this.readTimes.set(kind, times);
    return rows;
  }

  cite(records: readonly HgRecord[]): void {
    for (const r of records) {
      if (!this.sources.some((s) => s.kind === r.kind && s.key === r.key)) this.sources.push({ kind: r.kind, key: r.key });
    }
  }

  day(day: string): Bi {
    const en = shortDay(day, this.thisYear);
    const ko = koDay(day, this.thisYear);
    if (day === this.today) return bi(`today (${en})`, `오늘(${ko})`);
    if (day === addDays(this.today, -1)) return bi(`yesterday (${en})`, `어제(${ko})`);
    return bi(en, ko);
  }

  span(from: string, to: string): Bi {
    if (from === to) return this.day(from);
    return bi(`${shortDay(from, this.thisYear)} – ${shortDay(to, this.thisYear)}`, `${koDay(from, this.thisYear)} ~ ${koDay(to, this.thisYear)}`);
  }

  time(iso: string): string {
    const day = dayOf(iso, this.options.timeZone);
    const hhmm = clock(iso, this.options.timeZone);
    return day && day !== this.today ? `${shortDay(day, this.thisYear)} ${hhmm}` : hhmm;
  }

  asOf(): Record<string, AsOf> {
    const out: Record<string, AsOf> = {};
    for (const kind of this.readTimes.keys()) {
      const override = this.overrides.get(kind);
      if (override) {
        out[kind] = override;
        continue;
      }
      const run = this.runFor(kind);
      if (run?.finished_at) {
        out[kind] = { at: run.finished_at, job: run.job, source: "run" };
        continue;
      }
      const times = this.readTimes.get(kind) ?? [];
      if (times.length) out[kind] = { at: times.reduce((a, b) => (a > b ? a : b)), job: null, source: "read_at" };
    }
    for (const [kind, override] of this.overrides) if (!out[kind]) out[kind] = override;
    return out;
  }

  /** "<what>: not available yet." In the headline when it is the answer's main figure, else in the notes. */
  notAvailable(what: Bi, place: "headline" | "notes" = "headline"): void {
    (place === "headline" ? this.headline : this.notes).push(bi(`${what.en}: not available yet.`, `${what.ko}: 아직 확인할 수 없어요.`));
  }

  table(title: Bi, columns: Bi[], rows: string[][]): void {
    const shown = rows.slice(0, MAX_TABLE_ROWS);
    this.tables.push({ title, columns, rows: shown });
    if (rows.length > shown.length) {
      const more = rows.length - shown.length;
      this.notes.push(bi(`${title.en}: ${fmtInt(more)} more not shown.`, `${title.ko}: ${fmtInt(more)}건 더 있어요.`));
    }
  }

  result(plan: Plan): AnswerResult {
    return {
      plan,
      headline: this.headline,
      facts: this.facts,
      tables: this.tables,
      notes: this.notes,
      asOf: this.asOf(),
      sources: this.sources,
    };
  }
}

/** Kinds a plan reads, so their runs are fetched once up front. */
function planKinds(plan: Plan): string[] {
  switch (plan.intent) {
    case "student_card":
      return ["student", "student_progress", "doc_check"];
    case "verified_on_day":
      return ["verification"];
    case "inquiries_on_day":
      return ["consultation_day", "consultation"];
    case "pending_payments":
      return ["pending_payment"];
    case "window_review":
      return ["window_application"];
    case "doc_verdicts":
      return ["student", "doc_check", "doc_verdict", "field_check"];
    case "passport_alerts":
      return ["passport_alert", "student"];
    case "calendar_window":
      return ["calendar_item"];
    case "missing_for_student":
      return ["student", "report", "doc_verdict"];
    case "report":
      return ["report", "dashboard_fact"];
    case "performance":
      return ["consultant_performance"];
    case "consultancies_closed_today":
      return ["consultant_performance", "consultation_day", "consultation"];
    case "students_applied":
      return ["student"];
    case "dashboard":
      return ["dashboard_fact"];
    default:
      return [];
  }
}

// ─── Plans ──────────────────────────────────────────────────────────────────

async function resolveStudent(run: Run, query: StudentQuery): Promise<HgRecord | null> {
  const found = await run.readers.findStudents(query);
  const times = run.readTimes.get("student") ?? [];
  for (const r of found) times.push(r.read_at);
  run.readTimes.set("student", times);
  const label = queryLabel(query);
  if (found.length === 0) {
    run.headline.push(bi(`No student matches ${label}.`, `${label}에 해당하는 학생이 없어요.`));
    return null;
  }
  if (found.length > 1) {
    run.headline.push(bi(`${found.length} students match ${label}:`, `${label}에 해당하는 학생이 ${found.length}명이에요:`));
    run.cite(found);
    run.table(
      bi("Matching students", "해당 학생"),
      [bi("Student", "학생"), bi("HNG id", "HNG ID"), bi("Portal uid", "포털 UID"), bi("Program", "과정"), bi("Stage", "단계")],
      found.slice(0, 10).map((r) => [r.student_name ?? r.key, r.student_hng_id ?? "", String(r.student_uid ?? ""), str(r.data.program), str(r.data.status)]),
    );
    return null;
  }
  run.cite(found);
  return found[0];
}

function detail(record: HgRecord, label: string): unknown {
  return obj(record.data.details)[label];
}

async function studentCard(run: Run, plan: Extract<Plan, { intent: "student_card" }>): Promise<void> {
  const s = await resolveStudent(run, plan.student);
  if (!s) return;
  const d = s.data;
  const blank = blanks(d);
  const name = s.student_name ?? str(d.student_name);
  run.headline.push(
    bi(
      `${name} (${s.student_hng_id ?? "no HNG id"}, portal uid ${s.student_uid ?? s.key}): ${str(d.status) || "stage not shown"}.`,
      `${name} (${s.student_hng_id ?? "HNG ID 없음"}, 포털 UID ${s.student_uid ?? s.key}): ${str(d.status) || "단계 표시 없음"}.`,
    ),
  );
  const add = (label: Bi, value: unknown, blankKey?: string) => {
    if (blankKey && blank.has(blankKey)) {
      run.facts.push({ label, value: NOT_GIVEN.en });
      return;
    }
    const v = str(value);
    if (v) run.facts.push({ label, value: v });
  };
  add(bi("Program", "과정"), d.program, "program");
  add(bi("Target intake", "목표 학기"), d.target_intake, "target_intake");
  add(bi("University", "대학"), d.target_university, "target_university");
  add(bi("Stage", "단계"), d.status, "status");
  add(bi("Applied", "지원일"), d.applied_on ?? d.applied_date, "applied_on");
  add(bi("Documents", "서류"), d.docs_status, "docs_status");
  add(bi("Payment status", "결제 상태"), d.payment_status, "payment_status");
  const paid = [str(d.paid), str(d.method)].filter(Boolean).join(", ");
  add(bi("Paid", "결제액"), paid);
  const verified = [str(d.verified_by), str(d.verified_stamp)].filter(Boolean).join(", ");
  add(bi("Verified by", "확인자"), verified);
  add(bi("Passport", "여권"), detail(s, "Passport No") ?? s.passport_no, "details.Passport No");
  add(bi("Passport expiry", "여권 만료"), detail(s, "Passport Expiry"), "details.Passport Expiry");
  add(bi("Date of birth", "생년월일"), detail(s, "DOB"), "details.DOB");
  add(bi("Mobile", "휴대폰"), detail(s, "Mobile"), "details.Mobile");
  add(bi("Email", "이메일"), detail(s, "Email"), "details.Email");
  add(bi("Guardian WhatsApp", "보호자 왓츠앱"), detail(s, "Guardian WhatsApp"), "details.Guardian WhatsApp");
  add(bi("Father", "부"), detail(s, "Father"), "details.Father");
  add(bi("Mother", "모"), detail(s, "Mother"), "details.Mother");
  add(bi("District", "지역"), detail(s, "District"), "details.District");
  add(bi("Consultant", "상담사"), detail(s, "Consultant"), "details.Consultant");
  add(bi("IELTS/TOEFL", "IELTS/TOEFL"), detail(s, "IELTS/TOEFL"), "details.IELTS/TOEFL");

  const uidKey = String(s.student_uid ?? s.key);
  const [progress] = await run.read("student_progress", { key: uidKey });
  if (progress) {
    run.cite([progress]);
    const pct = str(progress.data.pct);
    run.facts.push({
      label: bi("Progress", "진행률"),
      value: [pct ? `${pct}%` : "", str(progress.data.status)].filter(Boolean).join(", "),
    });
  }
  const passport = s.passport_no ?? str(detail(s, "Passport No"));
  if (passport) {
    const [check] = await run.read("doc_check", { key: passport });
    if (check) {
      run.cite([check]);
      run.facts.push({
        label: bi("Document check", "서류 검사"),
        value: [str(check.data.verdict), str(check.data.checked) ? `checked ${str(check.data.checked).replace("T", " ").slice(0, 16)}` : ""]
          .filter(Boolean)
          .join(", "),
      });
      run.overrides.set("doc_check", { at: check.read_at, job: null, source: "read_at" });
    }
  }
  const shownBlank = new Set(["program", "target_intake", "target_university", "status", "applied_on", "docs_status", "payment_status"]);
  const otherBlank = [...blank].filter((b) => !shownBlank.has(b) && !run.facts.some((f) => b === `details.${f.label.en}`));
  const unlisted = otherBlank.filter(
    (b) => !["details.Passport No", "details.Passport Expiry", "details.DOB", "details.Mobile", "details.Email", "details.Guardian WhatsApp", "details.Father", "details.Mother", "details.District", "details.Consultant", "details.IELTS/TOEFL"].includes(b),
  );
  if (unlisted.length) {
    const fields = unlisted.map((b) => b.replace(/^details\./, "")).join(", ");
    run.notes.push(bi(`Not given on the portal: ${fields}.`, `포털에 입력되지 않은 항목: ${fields}.`));
  }
}

function amountOf(data: Record<string, unknown>): { value: number; currency: string } | null {
  const text = str(data.amount) || str(data.paid) || str(data.verified_income);
  const value = num(text);
  if (value === null) return null;
  const currency = /\b([A-Z]{3})\b/.exec(text)?.[1] ?? "";
  return { value, currency };
}

async function verifiedOnDay(run: Run, plan: Extract<Plan, { intent: "verified_on_day" }>): Promise<void> {
  const rows = await run.read("verification", plan.from === plan.to ? { day: plan.from } : { from: plan.from, to: plan.to });
  const span = run.span(plan.from, plan.to);
  if (rows.length === 0 && !run.published("verification")) {
    run.notAvailable(bi(`Payments verified ${span.en}`, `${span.ko} 결제 확인`));
    return;
  }
  run.cite(rows);
  run.headline.push(bi(`Payments verified ${span.en}: ${fmtInt(rows.length)}.`, `${span.ko} 확인된 결제: ${fmtInt(rows.length)}건.`));
  if (rows.length === 0) return;
  const totals = new Map<string, number>();
  for (const r of rows) {
    const a = amountOf(r.data);
    if (a) totals.set(a.currency, (totals.get(a.currency) ?? 0) + a.value);
  }
  for (const [currency, total] of totals) {
    run.facts.push({ label: bi("Total verified", "확인 금액 합계"), value: `${fmtAmount(total)}${currency ? ` ${currency}` : ""}` });
  }
  const byVerifier = countBy(rows, (r) => str(r.data.verified_by) || "—");
  if (byVerifier.length > 1 || byVerifier[0]?.[0] !== "—") {
    run.table(bi("By who verified", "확인자별"), [bi("Verified by", "확인자"), bi("Payments", "건수")], byVerifier.map(([k, n]) => [k, String(n)]));
  }
  if (plan.from !== plan.to) {
    const byDay = countBy(rows, (r) => r.day ?? "").sort((a, b) => (a[0] < b[0] ? -1 : 1));
    run.table(bi("By day", "일별"), [bi("Day", "날짜"), bi("Payments", "건수")], byDay.map(([d, n]) => [shortDay(d, run.thisYear), String(n)]));
  }
  const ordered = [...rows].sort((a, b) =>
    (a.day ?? "") !== (b.day ?? "") ? ((a.day ?? "") < (b.day ?? "") ? -1 : 1) : str(a.data.verified_time).localeCompare(str(b.data.verified_time)),
  );
  run.table(
    bi("Verified payments", "확인된 결제"),
    [bi("Student", "학생"), bi("Amount", "금액"), bi("Method", "방법"), bi("Verified by", "확인자"), bi("When", "시각")],
    ordered.map((r) => [studentLabel(r), str(r.data.amount) || str(r.data.paid), str(r.data.method), str(r.data.verified_by), str(r.data.verified_time)]),
  );
}

function statusLabel(status: string, lang: "en" | "ko"): string {
  if (!status) return lang === "ko" ? "(상태 없음)" : "(no status)";
  return lang === "ko" ? (STATUS_KO[status] ?? status) : status;
}

/**
 * Requests received on one day, by their CURRENT status. Returns false when the
 * day has not been read (its consultation_day record is the proof of a read).
 */
async function requestsOnDay(run: Run, day: string, status?: string, detailed = false, place: "headline" | "notes" = "headline"): Promise<boolean> {
  const rows = await run.read("consultation", { day });
  const [dayRecord] = await run.read("consultation_day", { key: day });
  const label = run.day(day);
  if (!dayRecord && rows.length === 0) {
    run.notAvailable(bi(`Requests received ${label.en}`, `${label.ko} 접수된 상담 신청`), place);
    return false;
  }
  if (dayRecord) run.cite([dayRecord]);
  run.cite(rows);
  // Dated by the last read of THIS day, not by the newest run of the kind (the full picture re-reads only yesterday and today).
  for (const kind of ["consultation", "consultation_day"] as const) {
    const dated = run.datedDay(kind, day, dayRecord ? [...rows, dayRecord] : rows);
    if (dated) run.overrides.set(kind, dated);
  }
  const picked = status ? rows.filter((r) => str(r.data.status) === status) : rows;
  const counts = countBy(rows, (r) => str(r.data.status));
  const breakdown = counts.map(([s, n]) => `${s || "no status"} ${n}`).join(", ");
  const breakdownKo = counts.map(([s, n]) => `${statusLabel(s, "ko")} ${n}`).join(", ");
  if (status) {
    run.headline.push(
      bi(
        `Requests received ${label.en} now marked ${status}: ${fmtInt(picked.length)} of ${fmtInt(rows.length)}.`,
        `${label.ko} 접수된 상담 신청 중 현재 '${statusLabel(status, "ko")}': ${fmtInt(rows.length)}건 중 ${fmtInt(picked.length)}건.`,
      ),
    );
  } else {
    run.headline.push(
      bi(
        `Requests received ${label.en}: ${fmtInt(rows.length)}${breakdown ? ` (${breakdown})` : ""}.`,
        `${label.ko} 접수된 상담 신청: ${fmtInt(rows.length)}건${breakdownKo ? ` (${breakdownKo})` : ""}.`,
      ),
    );
  }
  const portal = obj(dayRecord?.data.counts);
  const portalAll = num(portal.All);
  if (portalAll !== null && portalAll !== rows.length) {
    run.notes.push(
      bi(
        `The portal's date filter counts ${fmtInt(portalAll)} for ${label.en}; ${fmtInt(rows.length)} of them have been read.`,
        `포털 날짜 필터 기준 ${label.ko}는 ${fmtInt(portalAll)}건이고, 그중 ${fmtInt(rows.length)}건을 읽었어요.`,
      ),
    );
  }
  if (detailed && picked.length) {
    const ordered = [...picked].sort((a, b) => str(a.data.received).localeCompare(str(b.data.received)));
    run.table(
      bi("Requests", "상담 신청"),
      [bi("Requester", "신청자"), bi("Status", "상태"), bi("Consultant", "상담사"), bi("Last updated by", "최종 처리자"), bi("Received", "접수")],
      ordered.map((r) => [
        r.student_name || str(r.data.name) || r.key,
        str(r.data.status),
        str(r.data.consultant),
        str(r.data.handled_by),
        str(r.data.received),
      ]),
    );
  }
  return true;
}

async function inquiriesOnDay(run: Run, plan: Extract<Plan, { intent: "inquiries_on_day" }>): Promise<void> {
  if (!plan.to || plan.to === plan.day) {
    await requestsOnDay(run, plan.day, plan.status, true);
    return;
  }
  await requestsInRange(run, plan.day, plan.to, plan.status);
}

/** Requests received over a range of days, by day and by current status. False when no day of it has been read. */
async function requestsInRange(run: Run, from: string, to: string, status?: string, place: "headline" | "notes" = "headline"): Promise<boolean> {
  const days = await run.read("consultation_day", { from, to });
  const rows = await run.read("consultation", { from, to });
  const span = run.span(from, to);
  if (days.length === 0 && rows.length === 0) {
    run.notAvailable(bi(`Requests received ${span.en}`, `${span.ko} 접수된 상담 신청`), place);
    return false;
  }
  run.cite(days);
  const picked = status ? rows.filter((r) => str(r.data.status) === status) : rows;
  run.headline.push(
    bi(
      `Requests received ${span.en}${status ? ` now marked ${status}` : ""}: ${fmtInt(picked.length)}.`,
      `${span.ko} 접수된 상담 신청${status ? ` 중 현재 '${statusLabel(status, "ko")}'` : ""}: ${fmtInt(picked.length)}건.`,
    ),
  );
  const perDay = countBy(picked, (r) => r.day ?? "").sort((a, b) => (a[0] < b[0] ? -1 : 1));
  run.table(bi("By day", "일별"), [bi("Day", "날짜"), bi("Requests", "건수")], perDay.map(([d, n]) => [shortDay(d, run.thisYear), String(n)]));
  const byStatus = countBy(picked, (r) => str(r.data.status));
  run.table(bi("By status now", "현재 상태별"), [bi("Status", "상태"), bi("Requests", "건수")], byStatus.map(([s, n]) => [s || "(no status)", String(n)]));
  const read = new Set(days.map((d) => d.key));
  const unread: string[] = [];
  for (let d = from; d <= to && unread.length < 40; d = addDays(d, 1)) if (!read.has(d) && d <= run.today) unread.push(d);
  if (unread.length && days.length) {
    const list = unread.map((d) => shortDay(d, run.thisYear)).join(", ");
    run.notes.push(bi(`Days not read yet: ${list}.`, `아직 읽지 않은 날짜: ${list}.`));
  }
  // The range is only as fresh as its least recently read day.
  const readDays = new Set([...days.map((d) => d.key), ...rows.map((r) => r.day ?? "")].filter(Boolean));
  for (const kind of ["consultation", "consultation_day"] as const) {
    let oldest: AsOf | null = null;
    for (const d of readDays) {
      const dated = run.datedDay(kind, d, [...rows.filter((r) => r.day === d), ...days.filter((x) => x.key === d)]);
      if (dated && (!oldest || Date.parse(dated.at) < Date.parse(oldest.at))) oldest = dated;
    }
    if (oldest) run.overrides.set(kind, oldest);
  }
  return true;
}

interface Window {
  summary: HgRecord;
  rows: HgRecord[];
  first: string;
}

async function performanceWindow(run: Run, period: "today" | "month", day: string): Promise<Window | null> {
  const first = period === "month" ? firstOfMonth(day) : day;
  const scope = `${period}|${first}`;
  const recs = await run.read("consultant_performance", { scope });
  const summary = recs.find((r) => r.key === `${scope}|summary`);
  if (!summary) return null;
  // The window must be the one asked for: never another day's tiles offered as today's.
  const shownFirst = str(summary.data.first_day);
  if (shownFirst && shownFirst !== first) return null;
  run.cite(recs);
  return { summary, rows: recs.filter((r) => r !== summary && !r.key.endsWith("|summary")), first };
}

/** The newest window of a period, to say which day the data does have (never offered as today's). */
async function latestWindowDay(run: Run, period: "today" | "month"): Promise<HgRecord | null> {
  const summaries = await run.read("consultant_performance", { dataEq: { period }, keySuffix: "|summary" });
  return summaries.reduce<HgRecord | null>((best, r) => (!best || str(r.data.first_day) > str(best.data.first_day) ? r : best), null);
}

function tiles(summary: HgRecord): { label: string; value: string }[] {
  const data = summary.data;
  const blank = blanks(data);
  const t = obj(data.tiles);
  const order = ["Consultancies done", "Files opened", "Conversion (file open)", "Docs ready"];
  const labels = [...order.filter((l) => l in t || blank.has(`tiles.${l}`)), ...Object.keys(t).filter((l) => !order.includes(l))];
  return labels.map((label) => ({ label, value: blank.has(`tiles.${label}`) ? NOT_GIVEN.en : str(t[label]) }));
}

function tileFacts(run: Run, summary: HgRecord): void {
  for (const { label, value } of tiles(summary)) {
    if (value) run.facts.push({ label: bi(label, TILE_KO[label] ?? label), value });
  }
  const top = obj(summary.data.top);
  if (str(top.name)) {
    const figures = [str(top.score) && `score ${str(top.score)}`, str(top.consultancies) && `consultancies ${str(top.consultancies)}`]
      .filter(Boolean)
      .join(", ");
    run.facts.push({ label: bi("Top performer", "최우수 상담사"), value: figures ? `${str(top.name)} (${figures})` : str(top.name) });
  }
}

async function windowMissing(run: Run, period: "today" | "month", what: Bi): Promise<void> {
  run.notAvailable(what);
  const latest = await latestWindowDay(run, period);
  if (!latest) return;
  const latestDay = str(latest.data.first_day) || latest.day || "";
  const confirmed = run.runOnDay("consultant_performance", str(latest.data.last_day) || latestDay);
  const at = confirmed?.finished_at ?? latest.read_at;
  const range = str(latest.data.range) || shortDay(latestDay, run.thisYear);
  run.notes.push(
    bi(
      `The latest ${period === "today" ? "day" : "month"} on file is ${range}, last read ${run.time(at)}. Ask for that day if you want its figures.`,
      `가장 최근 자료는 ${range}이고, 마지막으로 읽은 시각은 ${run.time(at)}이에요. 필요하시면 그 날짜로 물어봐 주세요.`,
    ),
  );
}

/** "As of" for a window: today's by the newest run; a past window by the last run on its day. */
function dateWindow(run: Run, window: Window, period: "today" | "month"): void {
  const last = str(window.summary.data.last_day) || window.summary.day || window.first;
  if (period === "today" && last === run.today) return;
  if (period === "month" && last >= run.today) return;
  const confirmed = run.runOnDay("consultant_performance", last);
  run.overrides.set(
    "consultant_performance",
    confirmed?.finished_at
      ? { at: confirmed.finished_at, job: confirmed.job, source: "run" }
      : { at: window.summary.read_at, job: null, source: "read_at" },
  );
}

/**
 * A range of days (this week, the last 7 days). The portal's Consultant
 * Performance page shows only Today and This Month, so there is no figure for
 * the range: say so, and show each day's own Today window that is on file in it.
 */
async function performanceRange(run: Run, from: string, to: string, what: "consultancies" | "leaderboard"): Promise<void> {
  const span = run.span(from, to);
  run.headline.push(
    what === "consultancies"
      ? bi(
          `Consultancies done ${span.en}: not on the portal. Its Consultant Performance page shows only today and this month.`,
          `${span.ko} 상담 완료: 포털에 없는 수치예요. 상담사 실적 페이지는 오늘과 이번 달만 보여 줘요.`,
        )
      : bi(
          `Consultant performance ${span.en}: not on the portal. Its Consultant Performance page shows only today and this month.`,
          `${span.ko} 상담사 실적: 포털에 없는 수치예요. 상담사 실적 페이지는 오늘과 이번 달만 보여 줘요.`,
        ),
  );
  const summaries = (await run.read("consultant_performance", { dataEq: { period: "today" }, keySuffix: "|summary", from, to }))
    .filter((r) => {
      const first = str(r.data.first_day);
      return first >= from && first <= to && (str(r.data.last_day) || first) === first;
    })
    .sort((a, b) => str(a.data.first_day).localeCompare(str(b.data.first_day)));
  if (summaries.length === 0) {
    run.notes.push(bi(`No day of ${span.en} is on file.`, `${span.ko} 중 저장된 날짜가 없어요.`));
  } else {
    run.cite(summaries);
    const cell = (r: HgRecord, label: string) => tiles(r).find((t) => t.label === label)?.value ?? "";
    run.table(
      bi("Each day's Today window on file (as last read that day)", "날짜별 '오늘' 수치 (그날 마지막으로 읽은 값)"),
      [bi("Day", "날짜"), bi("Consultancies done", "상담 완료"), bi("Files opened", "파일 오픈"), bi("Conversion (file open)", "전환율(파일 오픈)"), bi("Docs ready", "서류 준비 완료")],
      summaries.map((r) => [shortDay(str(r.data.first_day), run.thisYear), cell(r, "Consultancies done"), cell(r, "Files opened"), cell(r, "Conversion (file open)"), cell(r, "Docs ready")]),
    );
    // Each day's figures are as fresh as that day's last read; the oldest dates the table.
    let oldest: AsOf | null = null;
    for (const r of summaries) {
      const day = str(r.data.first_day);
      const confirmed = day === run.today ? run.runFor("consultant_performance") : run.runOnDay("consultant_performance", day);
      const dated: AsOf = confirmed?.finished_at ? { at: confirmed.finished_at, job: confirmed.job, source: "run" } : { at: r.read_at, job: null, source: "read_at" };
      if (!oldest || Date.parse(dated.at) < Date.parse(oldest.at)) oldest = dated;
    }
    if (oldest) run.overrides.set("consultant_performance", oldest);
  }
  run.notes.push(bi("Ask for this month for the portal's month figures.", "이번 달 수치는 '이번 달'로 물어봐 주세요."));
}

async function consultanciesDone(run: Run, plan: Extract<Plan, { intent: "consultancies_closed_today" }>): Promise<void> {
  if (plan.to && plan.to !== plan.day) {
    await performanceRange(run, plan.day, plan.to, "consultancies");
    await requestsInRange(run, plan.day, plan.to, undefined, "notes");
    return;
  }
  const label = run.day(plan.day);
  const window = await performanceWindow(run, "today", plan.day);
  if (!window) {
    await windowMissing(run, "today", bi(`Consultancies done ${label.en}`, `${label.ko} 상담 완료`));
  } else {
    dateWindow(run, window, "today");
    const done = tiles(window.summary).find((t) => t.label === "Consultancies done")?.value ?? "";
    // A tile the portal left blank is "not given on the portal", in the reply's own language.
    const doneKo = !done || done === NOT_GIVEN.en ? NOT_GIVEN.ko : done;
    const rows = [...window.rows].sort(
      (a, b) => (num(b.data.consultancies) ?? -1) - (num(a.data.consultancies) ?? -1) || (num(a.data.rank) ?? 99) - (num(b.data.rank) ?? 99),
    );
    const perConsultant = rows
      .filter((r) => str(r.data.consultancies))
      .map((r) => `${str(r.data.name)} ${str(r.data.consultancies)}`)
      .join(", ");
    run.headline.push(
      bi(
        `Consultancies done ${label.en}: ${done || NOT_GIVEN.en}${perConsultant ? ` — ${perConsultant}` : ""}.`,
        `${label.ko} 상담 완료: ${doneKo}${perConsultant ? ` — ${perConsultant}` : ""}.`,
      ),
    );
    tileFacts(run, window.summary);
    run.table(
      bi("By consultant", "상담사별"),
      [bi("Consultant", "상담사"), bi("Consultancies", "상담 완료"), bi("Files opened", "파일 오픈")],
      rows.map((r) => [str(r.data.name), str(r.data.consultancies), str(r.data.files_opened)]),
    );
    const sum = rows.reduce((acc, r) => acc + (num(r.data.consultancies) ?? 0), 0);
    const tile = num(done);
    if (tile !== null && rows.length > 0 && sum !== tile) {
      run.notes.push(
        bi(
          `The leaderboard rows add up to ${fmtInt(sum)}; the portal's tile says ${fmtInt(tile)}.`,
          `순위표 합계는 ${fmtInt(sum)}건이고, 포털 타일은 ${fmtInt(tile)}건이에요.`,
        ),
      );
    }
  }
  const read = await requestsOnDay(run, plan.day, undefined, false, "notes");
  if (read) {
    run.notes.push(
      bi(
        `"Consultancies done" is the Consultant Performance page's tile; requests are counted by the day they were received, with their current status.`,
        `'상담 완료'는 상담사 실적 페이지의 수치이고, 상담 신청은 접수된 날짜 기준으로 현재 상태별로 셉니다.`,
      ),
    );
  }
}

async function performance(run: Run, plan: Extract<Plan, { intent: "performance" }>): Promise<void> {
  if (plan.period === "today" && plan.to && plan.to !== plan.day) {
    await performanceRange(run, plan.day, plan.to, "leaderboard");
    return;
  }
  const what =
    plan.period === "month"
      ? bi(`Consultant performance, ${monthName(plan.day)}`, `${Number(plan.day.slice(5, 7))}월 상담사 실적`)
      : bi(`Consultant performance ${run.day(plan.day).en}`, `${run.day(plan.day).ko} 상담사 실적`);
  const window = await performanceWindow(run, plan.period, plan.day);
  if (!window) {
    await windowMissing(run, plan.period, what);
    return;
  }
  dateWindow(run, window, plan.period);
  const range = str(window.summary.data.range);
  const count = num(window.summary.data.count) ?? window.rows.length;
  run.headline.push(
    bi(
      `${what.en}${range ? ` (${range})` : ""}: ${fmtInt(count)} consultant${count === 1 ? "" : "s"} on the leaderboard.`,
      `${what.ko}${range ? ` (${range})` : ""}: 순위표 상담사 ${fmtInt(count)}명.`,
    ),
  );
  tileFacts(run, window.summary);
  const rows = [...window.rows].sort((a, b) => (num(a.data.rank) ?? 99) - (num(b.data.rank) ?? 99));
  run.table(
    bi("Leaderboard", "순위표"),
    [
      bi("Consultant", "상담사"),
      bi("Rank", "순위"),
      bi("Score", "점수"),
      bi("Consultancies", "상담 완료"),
      bi("Files opened", "파일 오픈"),
      bi("Conversion", "전환율"),
      bi("Points", "포인트"),
      bi("Docs ready", "서류 준비"),
    ],
    rows.map((r) => [
      `${str(r.data.name)}${r.data.top === true ? " ★" : ""}`,
      str(r.data.rank),
      str(r.data.score),
      str(r.data.consultancies),
      str(r.data.files_opened),
      str(r.data.conversion),
      str(r.data.points),
      str(r.data.docs_ready),
    ]),
  );
}

async function pendingPayments(run: Run): Promise<void> {
  const rows = await run.read("pending_payment");
  if (rows.length === 0 && !run.published("pending_payment")) {
    run.notAvailable(bi("Pending payments", "미납"));
    return;
  }
  run.cite(rows);
  run.headline.push(bi(`Pending payments: ${fmtInt(rows.length)}.`, `미납: ${fmtInt(rows.length)}건.`));
  const badge = rows.map((r) => num(r.data.badge)).find((b) => b !== null);
  if (badge !== undefined && badge !== null) run.facts.push({ label: bi("Portal badge", "포털 배지"), value: fmtInt(badge) });
  run.table(
    bi("Pending", "미납 목록"),
    [bi("Student", "학생"), bi("Portal uid", "포털 UID"), bi("Applied", "지원일"), bi("Program", "과정"), bi("Amount", "금액")],
    rows.map((r) => [studentLabel(r), String(r.student_uid ?? r.key), str(r.data.applied_date) || (r.day ?? ""), str(r.data.program), str(r.data.paid)]),
  );
}

async function windowReview(run: Run): Promise<void> {
  const rows = await run.read("window_application");
  if (rows.length === 0 && !run.published("window_application")) {
    run.notAvailable(bi("Window applications under review", "심사 중인 윈도우 지원"));
    return;
  }
  run.cite(rows);
  run.headline.push(bi(`Window applications under review: ${fmtInt(rows.length)}.`, `심사 중인 윈도우 지원: ${fmtInt(rows.length)}건.`));
  run.table(
    bi("Under review", "심사 중"),
    [bi("Student", "학생"), bi("Window", "윈도우"), bi("Status", "상태")],
    rows.map((r) => [str(r.data.student) || r.student_name || r.key, str(r.data.window), str(r.data.status)]),
  );
}

async function docVerdicts(run: Run, plan: Extract<Plan, { intent: "doc_verdicts" }>): Promise<void> {
  if (plan.student) {
    const s = await resolveStudent(run, plan.student);
    if (!s) return;
    const passport = s.passport_no ?? str(detail(s, "Passport No"));
    const name = s.student_name ?? s.key;
    if (!passport) {
      run.headline.push(
        bi(`${name} has no passport number on the portal, so there is no document check for them.`, `${name} 학생은 포털에 여권 번호가 없어 서류 검사 기록이 없어요.`),
      );
      return;
    }
    const [check] = await run.read("doc_check", { key: passport });
    const verdicts = await run.read("doc_verdict", { scope: passport });
    const fields = await run.read("field_check", { scope: passport });
    if (!check && verdicts.length === 0) {
      run.notAvailable(bi(`Document check of ${name}`, `${name} 서류 검사`));
      return;
    }
    run.cite(check ? [check, ...verdicts] : verdicts);
    if (check) {
      run.overrides.set("doc_check", { at: check.read_at, job: null, source: "read_at" });
      const checked = str(check.data.checked).replace("T", " ").slice(0, 16);
      run.headline.push(
        bi(
          `Document check of ${name} (${passport}): ${str(check.data.verdict)}${checked ? `, checked ${checked}` : ""}.`,
          `${name} (${passport}) 서류 검사: ${str(check.data.verdict)}${checked ? `, 검사 ${checked}` : ""}.`,
        ),
      );
      const rowsText = (o: unknown) =>
        Object.entries(obj(o))
          .map(([k, v]) => `${k} ${str(v)}`)
          .join(", ");
      if (rowsText(check.data.document_rows)) run.facts.push({ label: bi("Documents", "서류"), value: rowsText(check.data.document_rows) });
      if (rowsText(check.data.field_rows)) run.facts.push({ label: bi("Fields", "항목"), value: rowsText(check.data.field_rows) });
    }
    if (verdicts.length) run.overrides.set("doc_verdict", { at: verdicts[0].read_at, job: null, source: "read_at" });
    const shown = plan.verdict ? verdicts.filter((v) => str(v.data.verdict) === plan.verdict) : verdicts;
    const rank: Record<string, number> = { FAIL: 0, MISSING: 1, FLAG: 2, PASS: 3 };
    run.table(
      bi("Documents", "서류"),
      [bi("Document", "서류"), bi("Verdict", "판정"), bi("Detail", "내용")],
      [...shown]
        .sort((a, b) => (rank[str(a.data.verdict)] ?? 4) - (rank[str(b.data.verdict)] ?? 4) || str(a.data.doc).localeCompare(str(b.data.doc)))
        .map((v) => [str(v.data.doc), str(v.data.verdict), clip(str(v.data.detail), 160)]),
    );
    const problems = fields.filter((f) => str(f.data.result) !== "MATCH");
    if (fields.length) {
      run.overrides.set("field_check", { at: fields[0].read_at, job: null, source: "read_at" });
      run.cite(problems);
      run.table(
        bi("Fields that did not match", "일치하지 않은 항목"),
        [bi("Field", "항목"), bi("Result", "결과"), bi("Portal value", "포털 값"), bi("Detail", "내용")],
        problems.map((f) => [str(f.data.field), str(f.data.result), str(f.data.portal) || NOT_GIVEN.en, clip(str(f.data.detail), 160)]),
      );
    }
    return;
  }

  const verdict = plan.verdict;
  if (verdict === "FLAG" || verdict === "MISSING") {
    const rows = await run.read("doc_verdict", { dataEq: { verdict } });
    if (rows.length === 0 && !run.published("doc_verdict")) {
      run.notAvailable(bi(`Documents marked ${verdict}`, `${verdict} 판정 서류`));
      return;
    }
    run.cite(rows);
    const byStudent = countBy(rows, (r) => `${r.student_name ?? str(r.data.student)} (${r.passport_no ?? r.scope})`);
    run.headline.push(
      bi(
        `Documents marked ${verdict}: ${fmtInt(rows.length)}, for ${fmtInt(byStudent.length)} student${byStudent.length === 1 ? "" : "s"}.`,
        `${verdict} 판정 서류: ${fmtInt(rows.length)}건, 학생 ${fmtInt(byStudent.length)}명.`,
      ),
    );
    run.table(bi("By student", "학생별"), [bi("Student", "학생"), bi("Documents", "서류 수")], byStudent.map(([k, n]) => [k, String(n)]));
    return;
  }
  const checks = await run.read("doc_check");
  if (checks.length === 0 && !run.published("doc_check")) {
    run.notAvailable(bi("Document checks", "서류 검사"));
    return;
  }
  const counts = countBy(checks, (r) => str(r.data.verdict));
  run.headline.push(
    bi(
      `Document checks on file: ${fmtInt(checks.length)} students (${counts.map(([v, n]) => `${v} ${n}`).join(", ")}).`,
      `서류 검사 기록: 학생 ${fmtInt(checks.length)}명 (${counts.map(([v, n]) => `${v} ${n}`).join(", ")}).`,
    ),
  );
  if (verdict) {
    const picked = checks.filter((r) => str(r.data.verdict) === verdict);
    run.cite(picked);
    run.table(
      bi(`Students with ${verdict}`, `${verdict} 학생`),
      [bi("Student", "학생"), bi("Passport", "여권"), bi("Program", "과정"), bi("Checked", "검사")],
      picked.map((r) => [studentLabel(r), r.passport_no ?? r.key, str(r.data.program), str(r.data.checked).replace("T", " ").slice(0, 16)]),
    );
  } else {
    run.table(bi("By verdict", "판정별"), [bi("Verdict", "판정"), bi("Students", "학생 수")], counts.map(([v, n]) => [v, String(n)]));
  }
}

/** Student records for the uids shown in a table (the caller passes only the rows it shows). */
async function namesByUid(run: Run, uids: readonly number[]): Promise<Map<number, HgRecord>> {
  const keys = [...new Set(uids.map(String))];
  const out = new Map<number, HgRecord>();
  if (keys.length === 0) return out;
  for (const r of await run.read("student", { keys })) if (r.student_uid !== null) out.set(r.student_uid, r);
  return out;
}

async function passportAlerts(run: Run, plan: Extract<Plan, { intent: "passport_alerts" }>): Promise<void> {
  let rows: HgRecord[];
  let scope: Bi;
  if (plan.student) {
    const s = await resolveStudent(run, plan.student);
    if (!s || s.student_uid === null) return;
    rows = await run.read("passport_alert", { studentUid: s.student_uid });
    scope = bi(`of ${s.student_name ?? s.key}`, `${s.student_name ?? s.key} 학생`);
  } else if (plan.day) {
    rows = await run.read("passport_alert", { day: plan.day });
    scope = bi(`checked ${run.day(plan.day).en}`, `${run.day(plan.day).ko} 확인된`);
  } else if (plan.from && plan.to) {
    rows = await run.read("passport_alert", { from: plan.from, to: plan.to });
    const span = run.span(plan.from, plan.to);
    scope = bi(`checked ${span.en}`, `${span.ko} 확인된`);
  } else {
    rows = await run.read("passport_alert");
    scope = bi("on file", "전체");
  }
  if (rows.length === 0 && !run.published("passport_alert")) {
    run.notAvailable(bi("Passport checks", "여권 확인"));
    return;
  }
  const problems = rows.filter((r) => str(r.data.status) && str(r.data.status) !== "MATCH");
  const sent = rows.filter((r) => r.data.sent === true);
  run.headline.push(
    bi(
      `Passport scans ${scope.en}: ${fmtInt(rows.length)}, ${fmtInt(problems.length)} with a problem, ${fmtInt(sent.length)} alert${sent.length === 1 ? "" : "s"} sent.`,
      `${scope.ko} 여권 스캔: ${fmtInt(rows.length)}건, 문제 ${fmtInt(problems.length)}건, 보낸 알림 ${fmtInt(sent.length)}건.`,
    ),
  );
  if (rows.length === 0) return;
  const byStatus = countBy(rows, (r) => str(r.data.status) || "—");
  run.table(bi("By status", "상태별"), [bi("Status", "상태"), bi("Scans", "건수")], byStatus.map(([s, n]) => [s, String(n)]));
  const listed = (plan.day || plan.student ? rows : problems).filter((r) => str(r.data.status) !== "MATCH" || plan.student);
  if (listed.length) {
    run.cite(listed);
    // Newest scans first; names are looked up for the rows the table shows (the newest matter most).
    const ordered = [...listed].sort((a, b) => str(b.data.checked).localeCompare(str(a.data.checked)));
    const shown = ordered.slice(0, MAX_TABLE_ROWS);
    const names = await namesByUid(run, shown.map((r) => r.student_uid).filter((u): u is number => u !== null));
    run.table(
      bi("Scans needing attention", "확인이 필요한 스캔"),
      [bi("Student", "학생"), bi("Status", "상태"), bi("Checked", "확인"), bi("Alert sent", "알림")],
      ordered.map((r) => {
        const s = r.student_uid !== null ? names.get(r.student_uid) : undefined;
        const who = s ? studentLabel(s) : `${r.student_hng_id ?? ""} uid ${r.student_uid ?? r.key.split("|")[0]}`.trim();
        return [who, str(r.data.status), str(r.data.checked), r.data.sent === true ? str(r.data.sent_at) || "yes" : "no"];
      }),
    );
  }
}

const CALENDAR_FILLER = new Set(["university", "univ", "the", "of", "and", "at"]);

/** Lower-case words of a calendar title or a named target, without "university" and the like. */
function calendarTokens(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w.length >= 2 && !CALENDAR_FILLER.has(w));
}

async function calendarWindow(run: Run, plan: Extract<Plan, { intent: "calendar_window" }>): Promise<void> {
  const all = await run.read("calendar_item");
  const span = run.span(plan.from, plan.to);
  if (all.length === 0 && !run.published("calendar_item")) {
    run.notAvailable(bi(`Calendar ${span.en}`, `${span.ko} 일정`));
    return;
  }
  const wanted = plan.where ? calendarTokens(plan.where) : [];
  const items = all
    .filter((r) => {
      const start = str(r.data.start) || str(r.data.end) || r.day || "";
      const end = str(r.data.end) || start;
      if (!(start <= plan.to && end >= plan.from)) return false;
      if (wanted.length === 0) return true;
      const have = calendarTokens(`${str(r.data.title)} ${str(r.data.where)}`);
      return wanted.every((w) => have.includes(w));
    })
    .sort((a, b) => (str(a.data.start) || a.day || "").localeCompare(str(b.data.start) || b.day || ""));
  run.cite(items);
  if (plan.where) {
    run.headline.push(
      bi(
        items.length
          ? `Calendar items for ${plan.where} ${span.en}: ${fmtInt(items.length)}.`
          : `No item on the agency's calendar mentions ${plan.where} ${span.en}.`,
        items.length ? `${span.ko} ${plan.where} 일정: ${fmtInt(items.length)}건.` : `${span.ko} 에이전시 일정에 ${plan.where} 항목이 없어요.`,
      ),
    );
    if (items.length === 0) return;
  } else {
    run.headline.push(bi(`Calendar items ${span.en}: ${fmtInt(items.length)}.`, `${span.ko} 일정: ${fmtInt(items.length)}건.`));
  }
  run.table(
    bi("Calendar", "일정"),
    [bi("Title", "제목"), bi("Kind", "종류"), bi("Where", "장소"), bi("Dates", "기간"), bi("Done", "완료")],
    items.map((r) => {
      const start = str(r.data.start);
      const end = str(r.data.end);
      const dates = start && end && start !== end ? `${shortDay(start, run.thisYear)} – ${shortDay(end, run.thisYear)}` : shortDay(end || start || r.day || "", run.thisYear);
      return [str(r.data.title) || NOT_GIVEN.en, str(r.data.kind), str(r.data.where), dates, r.data.done === true ? "done" : ""];
    }),
  );
  if (plan.to > addDays(run.today, 45)) {
    run.notes.push(
      bi("The portal's calendar shows only this month and the next 45 days.", "포털 일정은 이번 달과 앞으로 45일까지만 보여요."),
    );
  }
}

async function missingForStudent(run: Run, plan: Extract<Plan, { intent: "missing_for_student" }>): Promise<void> {
  const s = await resolveStudent(run, plan.student);
  if (!s) return;
  const name = s.student_name ?? s.key;
  const [report] = await run.read("report", { scope: "missing_report", order: "day.desc", limit: 1 });
  if (!report) {
    run.undate("report");
    run.notAvailable(bi("The missing-information report", "누락 정보 보고서"));
  } else {
    run.cite([report]);
    run.overrides.set("report", { at: report.read_at, job: "missing_report", source: "read_at" });
    const rows = Array.isArray(obj(report.data.facts).rows) ? (obj(report.data.facts).rows as unknown[]).map(obj) : [];
    const mine = rows.find(
      (r) =>
        (s.student_hng_id && str(r.student_id) === s.student_hng_id) ||
        (!str(r.student_id) && str(r.full_name).toLowerCase() === (s.student_name ?? "").toLowerCase()),
    );
    const day = shortDay(str(report.data.when) || report.day || "", run.thisYear);
    if (!mine || (num(mine.missing_count) ?? 0) === 0) {
      run.headline.push(bi(`${name}: nothing missing in the missing-information report of ${day}.`, `${name}: ${day} 누락 정보 보고서에 누락 항목이 없어요.`));
    } else {
      run.headline.push(
        bi(
          `${name}: ${str(mine.missing_count)} missing in the report of ${day}: ${str(mine.missing_fields)}.`,
          `${name}: ${day} 보고서 기준 누락 ${str(mine.missing_count)}건: ${str(mine.missing_fields)}.`,
        ),
      );
    }
  }
  const passport = s.passport_no ?? str(detail(s, "Passport No"));
  if (passport) {
    const missingDocs = await run.read("doc_verdict", { scope: passport, dataEq: { verdict: "MISSING" } });
    if (missingDocs.length) {
      run.cite(missingDocs);
      run.overrides.set("doc_verdict", { at: missingDocs[0].read_at, job: null, source: "read_at" });
      run.facts.push({ label: bi("Documents missing in the document check", "서류 검사에서 누락된 서류"), value: missingDocs.map((d) => str(d.data.doc)).join(", ") });
    }
  }
  const blank = [...blanks(s.data)].map((b) => b.replace(/^details\./, ""));
  if (blank.length) run.facts.push({ label: bi("Not given on the portal", "포털에 입력되지 않음"), value: blank.join(", ") });
}

async function changesSince(run: Run, plan: Extract<Plan, { intent: "changes_since" }>): Promise<void> {
  if (!run.readers.changes) {
    run.notes.push(bi("What changed can only be read on the server.", "변경 내역은 서버에서만 읽을 수 있어요."));
    return;
  }
  const changes = await run.readers.changes(plan.since, 20_000);
  run.overrides.set("change_log", { at: run.options.now.toISOString(), job: "change_log", source: "run" });
  const upserts = changes.filter((c) => c.op === "upsert").length;
  const deletes = changes.length - upserts;
  const label = plan.sinceLabel;
  run.headline.push(
    bi(
      `Changes since ${label}: ${fmtInt(upserts)} record${upserts === 1 ? "" : "s"} new or updated, ${fmtInt(deletes)} removed.`,
      `${label} 이후 변경: 새로 들어오거나 바뀐 기록 ${fmtInt(upserts)}건, 삭제 ${fmtInt(deletes)}건.`,
    ),
  );
  const byKind = new Map<string, { up: number; del: number; last: string }>();
  for (const c of changes) {
    const entry = byKind.get(c.kind) ?? { up: 0, del: 0, last: "" };
    if (c.op === "upsert") entry.up++;
    else entry.del++;
    if (c.changed_at > entry.last) entry.last = c.changed_at;
    byKind.set(c.kind, entry);
  }
  const rows = [...byKind.entries()].sort((a, b) => b[1].up + b[1].del - (a[1].up + a[1].del));
  const cells = (kind: string, e: { up: number; del: number; last: string }) => [String(e.up), String(e.del), run.time(e.last)];
  run.tables.push({
    title: bi("By kind", "종류별"),
    columns: [bi("Kind", "종류"), bi("New or updated", "추가·변경"), bi("Removed", "삭제"), bi("Last change", "마지막 변경")],
    rows: rows.map(([kind, e]) => [kindLabel(kind).en, ...cells(kind, e)]),
    rowsKo: rows.map(([kind, e]) => [kindLabel(kind).ko, ...cells(kind, e)]),
  });
}

const REPORT_SCOPE: Record<Exclude<ReportName, "stage">, string> = {
  brief: "brief",
  missing: "missing_report",
  document_check: "document_check",
  field_check: "field_check",
  inquiries: "inquiries_report",
};

/** The bot job that writes each report, for its "as of" label (the report's own read_at is when it was made). */
const REPORT_JOB: Record<ReportName, string> = {
  brief: "daily_brief",
  missing: "missing_report",
  stage: "stage_report",
  document_check: "document_check_report",
  field_check: "field_check_report",
  inquiries: "inquiries_report",
};

const REPORT_TITLE: Record<ReportName, Bi> = {
  brief: bi("Daily brief", "일일 브리핑"),
  missing: bi("Missing-information report", "누락 정보 보고서"),
  stage: bi("Stage report", "단계 보고서"),
  document_check: bi("Document check report", "서류 검사 보고서"),
  field_check: bi("Field check report", "항목 검사 보고서"),
  inquiries: bi("Inquiries report", "문의 보고서"),
};

function reportFacts(run: Run, report: HgRecord): void {
  const facts = obj(report.data.facts);
  const name = str(report.data.report) || report.scope;
  if (name === "brief") {
    const lines = Array.isArray(facts.lines) ? facts.lines.map(str).filter(Boolean) : [];
    if (lines.length) run.tables.push({ title: bi("Brief", "브리핑"), columns: [same("")], rows: lines.map((l) => [l]) });
    const pending = obj(facts.pending_payments);
    if (str(pending.count)) run.facts.push({ label: bi("Pending payments", "미납"), value: str(pending.count) });
    if (str(facts.window_apps_under_review)) {
      run.facts.push({ label: bi("Window applications under review", "심사 중인 윈도우 지원"), value: str(facts.window_apps_under_review) });
    }
    const notRead = Array.isArray(facts.not_read) ? facts.not_read.map(str).filter(Boolean) : [];
    if (notRead.length) run.notes.push(bi(`Not read for this brief: ${notRead.join(", ")}.`, `이 브리핑에서 읽지 못한 항목: ${notRead.join(", ")}.`));
    return;
  }
  if (name === "missing_report") {
    const rows = Array.isArray(facts.rows) ? facts.rows.map(obj) : [];
    const incomplete = rows.filter((r) => (num(r.missing_count) ?? 0) > 0);
    run.facts.push({ label: bi("Students with missing information", "누락 정보가 있는 학생"), value: fmtInt(incomplete.length) });
    const fields = new Map<string, number>();
    for (const r of incomplete) for (const f of str(r.missing_fields).split(",").map((x) => x.trim()).filter(Boolean)) fields.set(f, (fields.get(f) ?? 0) + 1);
    const top = [...fields.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    run.tables.push({ title: bi("Most often missing", "가장 많이 누락된 항목"), columns: [bi("Field", "항목"), bi("Students", "학생 수")], rows: top.map(([f, n]) => [f, String(n)]) });
    const byProgram = countBy(incomplete, (r) => str(r.program) || "—");
    run.tables.push({ title: bi("By program", "과정별"), columns: [bi("Program", "과정"), bi("Students", "학생 수")], rows: byProgram.map(([p, n]) => [p, String(n)]) });
    return;
  }
  if (name === "document_check") {
    if (str(facts.students)) run.facts.push({ label: bi("Students checked", "검사한 학생"), value: str(facts.students) });
    const verdicts = Object.entries(obj(facts.verdicts)).map(([v, n]) => [v, str(n)]);
    if (verdicts.length) run.tables.push({ title: bi("By verdict", "판정별"), columns: [bi("Verdict", "판정"), bi("Students", "학생 수")], rows: verdicts });
    return;
  }
  if (name === "field_check") {
    if (str(facts.students)) run.facts.push({ label: bi("Students checked", "검사한 학생"), value: str(facts.students) });
    if (str(facts.corrections)) run.facts.push({ label: bi("Corrections", "수정"), value: str(facts.corrections) });
    return;
  }
  if (name === "inquiries_report") {
    const counts = Object.entries(obj(facts.counts)).map(([k, v]) => [k, str(v)]);
    if (counts.length) run.tables.push({ title: bi("Requests by status", "상태별 신청"), columns: [bi("Status", "상태"), bi("Requests", "건수")], rows: counts });
    return;
  }
  if (name.startsWith("stage_report")) {
    const counts = Object.entries(obj(facts.counts)).map(([k, v]) => [k, str(v)]);
    if (counts.length) run.tables.push({ title: bi("By stage", "단계별"), columns: [bi("Stage", "단계"), bi("Students", "학생 수")], rows: counts });
    return;
  }
  const lines = report.content.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 25);
  run.tables.push({ title: bi("Report", "보고서"), columns: [same("")], rows: lines.map((l) => [l]) });
}

/** The portal dashboard's figures as tables, one per group (all groups, or only `groups`). False when there are none. */
async function dashboardFacts(run: Run, groups: readonly string[] | null): Promise<boolean> {
  const rows = await run.read("dashboard_fact");
  if (rows.length === 0) {
    if (!groups) run.notAvailable(bi("The dashboard", "대시보드"));
    return false;
  }
  const order = ["At a glance", "Direct / legacy pipeline", "Needs attention", "Application pipeline", "Applications by program", "Admissions flow", "Top universities"];
  const byGroup = new Map<string, HgRecord[]>();
  for (const r of rows) {
    const g = str(r.data.group);
    if (groups && !groups.includes(g)) continue;
    const list = byGroup.get(g);
    if (list) list.push(r);
    else byGroup.set(g, [r]);
  }
  const rank = (g: string) => (order.includes(g) ? order.indexOf(g) : order.length);
  const names = [...byGroup.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  for (const g of names) {
    const items = byGroup.get(g) ?? [];
    run.cite(items);
    run.tables.push({
      title: same(g || "Dashboard"),
      columns: [bi("Figure", "항목"), bi("Value", "값")],
      rows: items.map((r) => [str(r.data.note) ? `${str(r.data.label)} — ${str(r.data.note)}` : str(r.data.label), str(r.data.text) || str(r.data.value)]),
    });
  }
  return true;
}

async function report(run: Run, plan: Extract<Plan, { intent: "report" }>): Promise<void> {
  const title = REPORT_TITLE[plan.report];
  const filter: RecordFilter =
    plan.report === "stage" ? { scopePrefix: "stage_report:" } : { scope: REPORT_SCOPE[plan.report] };
  const found = await run.read("report", plan.day ? { ...filter, day: plan.day } : { ...filter, order: "day.desc", limit: plan.report === "stage" ? 50 : 1 });
  const latest = found.reduce<HgRecord | null>((best, r) => (!best || (r.day ?? "") > (best.day ?? "") || ((r.day ?? "") === (best.day ?? "") && r.read_at > best.read_at) ? r : best), null);
  if (!latest) {
    // No such report to date: the "as of" line names only what is shown (another report's run never dates this one).
    run.undate("report");
    run.notAvailable(plan.day ? bi(`${title.en} of ${shortDay(plan.day, run.thisYear)}`, `${koDay(plan.day, run.thisYear)} ${title.ko}`) : title);
    if (plan.report === "brief") {
      run.headline.push(bi("Hangeul BOT sends its brief at 18:05.", "Hangeul BOT은 18:05에 브리핑을 보내요."));
      if (await dashboardFacts(run, ["At a glance", "Needs attention"])) {
        run.headline.push(bi("From the portal's dashboard instead:", "대신 포털 대시보드 수치예요:"));
      }
    }
    return;
  }
  run.cite([latest]);
  run.overrides.set("report", { at: latest.read_at, job: REPORT_JOB[plan.report], source: "read_at" });
  const when = str(latest.data.when);
  const day = latest.day ?? when.slice(0, 10);
  run.headline.push(bi(`${title.en} of ${longDay(day)}:`, `${koDay(day)} ${title.ko}:`));
  reportFacts(run, latest);
  if (plan.report === "brief" && day !== run.today && !plan.day) {
    run.notes.push(bi("Today's brief is not available yet; Hangeul BOT sends it at 18:05.", "오늘 브리핑은 아직 없어요. Hangeul BOT이 18:05에 보내요."));
  }
}

async function studentsApplied(run: Run, plan: Extract<Plan, { intent: "students_applied" }>): Promise<void> {
  const rows = await run.read("student", plan.from === plan.to ? { day: plan.from } : { from: plan.from, to: plan.to });
  const span = run.span(plan.from, plan.to);
  if (rows.length === 0 && !run.published("student")) {
    run.notAvailable(bi(`Students who applied ${span.en}`, `${span.ko} 지원한 학생`));
    return;
  }
  run.cite(rows);
  run.headline.push(bi(`Students who applied ${span.en}: ${fmtInt(rows.length)}.`, `${span.ko} 지원한 학생: ${fmtInt(rows.length)}명.`));
  if (rows.length === 0) return;
  const byProgram = countBy(rows, (r) => str(r.data.program) || "—");
  run.table(bi("By program", "과정별"), [bi("Program", "과정"), bi("Students", "학생 수")], byProgram.map(([p, n]) => [p, String(n)]));
  run.table(
    bi("Students", "학생"),
    [bi("Student", "학생"), bi("Program", "과정"), bi("Intake", "학기"), bi("Stage", "단계"), bi("Applied", "지원일")],
    [...rows].sort((a, b) => str(a.data.applied_on).localeCompare(str(b.data.applied_on))).map((r) => [studentLabel(r), str(r.data.program), str(r.data.target_intake), str(r.data.status), str(r.data.applied_on)]),
  );
}

async function dataStatus(run: Run): Promise<void> {
  run.headline.push(
    bi("Hangeul BOT reads the portal and publishes what it reads; these are its latest runs.", "Hangeul BOT이 포털을 읽어 올린 자료예요. 최근 실행 기록입니다."),
  );
  const rows = run.latestPerJob();
  if (rows.length === 0) {
    run.notAvailable(bi("Runs", "실행 기록"));
    return;
  }
  run.tables.push({
    title: bi("Latest runs", "최근 실행"),
    columns: [bi("Job", "작업"), bi("Finished", "완료"), bi("Status", "상태"), bi("Kinds read", "읽은 종류")],
    rows: rows.map((r) => [(JOB_LABEL[r.job] ?? same(r.job)).en, run.time(r.finished_at ?? ""), r.status ?? "", String(Object.keys(r.byKind).length)]),
  });
  const failed = rows.flatMap((r) => r.failedReads.map((f) => `${(JOB_LABEL[r.job] ?? same(r.job)).en}: ${f}`));
  if (failed.length) run.notes.push(bi(`Reads that failed: ${failed.slice(0, 5).join("; ")}.`, `실패한 읽기: ${failed.slice(0, 5).join("; ")}.`));
}

// ─── Semantic search ────────────────────────────────────────────────────────

/** Questions in Korean or Bangla are rewritten into an English search query first (the stored text is English). */
export function needsSearchRewrite(text: string): boolean {
  return /[ᄀ-ᇿ㄰-㆏가-힯ঀ-৿]/.test(text);
}

export const SEARCH_REWRITE_SYSTEM =
  "Rewrite the user's question as one short English search query over an education agency's records (students, payments, consultation requests, document checks, passport checks, OCR text of documents). Keep every name, id and number exactly as written. Reply with the query only.";

export function cleanSearchRewrite(raw: string): string | null {
  const line = raw.split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  const query = line.replace(/^(?:search\s+query|query)\s*[:：]\s*/i, "").replace(/^["'“‘]+|["'”’]+$/g, "").trim();
  return query && query.length <= 300 ? query : null;
}

const SKIP_CARD_FIELDS = new Set(["details", "files", "applications", "blank_on_portal", "alert", "lines", "facts", "tiles", "top", "document_rows", "field_rows", "counts", "stale_columns", "extra"]);

function recordCard(run: Run, hit: { kind: string; key: string; data: Record<string, unknown>; student_name: string | null; content: string }): void {
  const title = hit.student_name ?? (str(hit.data.name) || str(hit.data.title) || str(hit.data.student) || hit.key);
  const blank = blanks(hit.data);
  const rows: string[][] = [];
  for (const [field, value] of Object.entries(hit.data)) {
    if (SKIP_CARD_FIELDS.has(field) || rows.length >= 12) continue;
    if (blank.has(field)) rows.push([field, NOT_GIVEN.en]);
    else if (typeof value !== "object" && str(value)) rows.push([field, clip(str(value), 200)]);
  }
  const label = kindLabel(hit.kind);
  run.tables.push({ title: bi(`${label.en}: ${title}`, `${label.ko}: ${title}`), columns: [bi("Field", "항목"), bi("Value", "값")], rows });
  if (hit.kind === "doc_page_text" || hit.kind === "report" || hit.kind === "notification") {
    const lines = hit.content.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 30).map((l) => [clip(l, 300)]);
    if (lines.length) run.tables.push({ title: bi("Matched text", "일치한 본문"), columns: [same("")], rows: lines });
  }
}

async function semantic(run: Run, plan: Extract<Plan, { intent: "semantic" }>): Promise<void> {
  const cards: { kind: string; key: string; data: Record<string, unknown>; student_name: string | null; content: string; read_at: string }[] = [];
  let query = plan.question;
  if (run.options.hits?.length) {
    const byKind = new Map<string, string[]>();
    for (const h of run.options.hits.slice(0, 24)) byKind.set(h.kind, [...(byKind.get(h.kind) ?? []), h.key]);
    const found: HgRecord[] = [];
    for (const [kind, keys] of byKind) {
      if (!(HG_KINDS as readonly string[]).includes(kind)) continue;
      found.push(...(await run.read(kind as HgKind, { keys })));
    }
    for (const h of run.options.hits) {
      const r = found.find((f) => f.kind === h.kind && f.key === h.key);
      if (r && !cards.some((c) => c.kind === r.kind && c.key === r.key)) cards.push(r);
    }
  } else {
    if (needsSearchRewrite(query) && run.options.rewrite) query = (await run.options.rewrite(query).catch(() => null)) ?? query;
    // A device vector is of the original wording; a rewritten query is embedded again when the server can.
    let embedding: readonly number[] | null = query === plan.question ? (run.options.embedding ?? null) : null;
    if (!embedding && run.readers.embed) {
      try {
        embedding = (await run.readers.embed([query]))[0] ?? null;
      } catch (error) {
        if (!isHangeulReadError(error)) throw error;
        embedding = run.options.embedding ?? null;
      }
    }
    if (!embedding) embedding = run.options.embedding ?? null;
    if (!embedding || !run.readers.match) {
      run.notes.push(bi("Search is not available yet: the question could not be embedded.", "아직 검색을 할 수 없어요: 질문을 벡터로 바꾸지 못했어요."));
      return;
    }
    let studentUid: number | undefined;
    if (plan.student) {
      const s = await resolveStudent(run, plan.student);
      if (!s) return;
      studentUid = s.student_uid ?? undefined;
    }
    const hits: HgHit[] = await run.readers.match(embedding, { count: 12, kinds: plan.kinds, from: plan.from, to: plan.to, studentUid });
    const top = hits[0]?.similarity ?? 0;
    for (const h of hits) {
      // gte-small scores sit close together (unrelated rows still score ~0.86): keep the ones near the best.
      if (h.similarity < top - 0.04) continue;
      if (cards.some((c) => c.kind === h.kind && c.key === h.key)) continue;
      cards.push({ kind: h.kind, key: h.key, data: h.data, student_name: h.student_name, content: h.content, read_at: h.read_at });
      const times = run.readTimes.get(h.kind) ?? [];
      times.push(h.read_at);
      run.readTimes.set(h.kind, times);
      if (cards.length >= 5) break;
    }
  }
  if (cards.length === 0) {
    run.headline.push(bi(`Nothing on file matches "${clip(query, 80)}".`, `"${clip(query, 80)}"에 맞는 기록이 없어요.`));
    return;
  }
  await run.loadRuns([...new Set(cards.map((c) => c.kind))]);
  run.headline.push(
    bi(`Closest records for "${clip(query, 80)}": ${cards.length}.`, `"${clip(query, 80)}"와 가장 가까운 기록: ${cards.length}건.`),
  );
  for (const c of cards) {
    run.sources.push({ kind: c.kind, key: c.key });
    if (["doc_page_text", "doc_verdict", "field_check", "doc_check", "passport_alert"].includes(c.kind)) {
      run.overrides.set(c.kind, { at: c.read_at, job: null, source: "read_at" });
    }
    recordCard(run, c);
  }
}

// ─── Running a plan ─────────────────────────────────────────────────────────

/** The plan for a question: the router's, else a semantic search (the orchestrator already decided it is ours). */
export function planFor(question: string, ctx: RouterContext): Plan {
  return classify(question, ctx) ?? { intent: "semantic", question: question.trim() };
}

export async function runPlan(plan: Plan, readers: HangeulReaders, options: RunOptions): Promise<AnswerResult> {
  const run = new Run(readers, options);
  try {
    await run.loadRuns(planKinds(plan));
    switch (plan.intent) {
      case "student_card":
        await studentCard(run, plan);
        break;
      case "verified_on_day":
        await verifiedOnDay(run, plan);
        break;
      case "inquiries_on_day":
        await inquiriesOnDay(run, plan);
        break;
      case "pending_payments":
        await pendingPayments(run);
        break;
      case "window_review":
        await windowReview(run);
        break;
      case "doc_verdicts":
        await docVerdicts(run, plan);
        break;
      case "passport_alerts":
        await passportAlerts(run, plan);
        break;
      case "calendar_window":
        await calendarWindow(run, plan);
        break;
      case "missing_for_student":
        await missingForStudent(run, plan);
        break;
      case "changes_since":
        await changesSince(run, plan);
        break;
      case "report":
        await report(run, plan);
        break;
      case "performance":
        await performance(run, plan);
        break;
      case "consultancies_closed_today":
        await consultanciesDone(run, plan);
        break;
      case "students_applied":
        await studentsApplied(run, plan);
        break;
      case "dashboard":
        await dashboardFacts(run, null);
        run.headline.unshift(bi("The portal's dashboard:", "포털 대시보드:"));
        break;
      case "data_status":
        await dataStatus(run);
        break;
      case "semantic":
        await semantic(run, plan);
        break;
    }
    return run.result(plan);
  } catch (error) {
    const reason = isHangeulReadError(error) ? error.message : "Hangeul data could not be read";
    if (!isHangeulReadError(error)) console.error(`[hangeul] ${plan.intent} plan failed: ${error instanceof Error ? error.name : "Error"}`);
    return { plan, headline: [], facts: [], tables: [], notes: [], asOf: {}, sources: [], unavailable: reason };
  }
}

// ─── Rendering ──────────────────────────────────────────────────────────────

export interface RenderOptions {
  now: Date;
  timeZone: string;
}

/** "As of 23:35 (full picture) · portal sync 23:58", dated by the runs; "" when nothing was dated. */
export function asOfLine(result: AnswerResult, lang: "en" | "ko", options: RenderOptions): string {
  const today = businessDay(options.now, options.timeZone);
  const groups = new Map<string, { at: string; label: Bi; kind: Bi }>();
  for (const [kind, asOf] of Object.entries(result.asOf)) {
    const label = asOf.job ? (JOB_LABEL[asOf.job] ?? same(asOf.job.replace(/_/g, " "))) : kindLabel(kind);
    const key = `${label.en}|${asOf.at}`;
    if (!groups.has(key)) groups.set(key, { at: asOf.at, label, kind: kindLabel(kind) });
  }
  if (groups.size === 0) return "";
  const when = (iso: string) => {
    const day = dayOf(iso, options.timeZone);
    const hhmm = clock(iso, options.timeZone);
    if (!day || day === today) return hhmm;
    return lang === "ko" ? `${koDay(day, today.slice(0, 4))} ${hhmm}` : `${shortDay(day, today.slice(0, 4))} ${hhmm}`;
  };
  const list = [...groups.values()];
  // One job at two times (yesterday's performance window, and today's re-read of yesterday's requests):
  // name what each time is for.
  const repeated = (g: { label: Bi }) => list.filter((x) => x.label.en === g.label.en).length > 1;
  const [first, ...rest] = list;
  const firstLabel = (l: "en" | "ko") => (repeated(first) ? `${first.kind[l]}, ${first.label[l]}` : first.label[l]);
  const restPart = (g: (typeof list)[number], l: "en" | "ko") =>
    repeated(g) ? `${g.kind[l]} ${when(g.at)} (${g.label[l]})` : `${g.label[l]} ${when(g.at)}`;
  if (lang === "ko") {
    return [`기준: ${when(first.at)} (${firstLabel("ko")})`, ...rest.map((g) => restPart(g, "ko"))].join(" · ");
  }
  return [`As of ${when(first.at)} (${firstLabel("en")})`, ...rest.map((g) => restPart(g, "en"))].join(" · ");
}

function renderTable(table: Table, lang: "en" | "ko"): string[] {
  const lines = table.title[lang] ? [`${table.title[lang]}:`] : [];
  const source = lang === "ko" && table.rowsKo ? table.rowsKo : table.rows;
  if (source.length === 0) {
    lines.push(lang === "ko" ? "• 없음" : "• none");
    return lines;
  }
  for (const raw of source) {
    const row = lang === "ko" ? raw.map((cell) => (cell === NOT_GIVEN.en ? NOT_GIVEN.ko : cell)) : raw;
    if (table.columns.length <= 1) {
      lines.push(`• ${row[0]}`);
    } else if (table.columns.length === 2) {
      lines.push(`• ${row[0]}: ${row[1] ?? ""}`);
    } else {
      const cells = table.columns
        .slice(1)
        .map((col, i) => (row[i + 1] ? `${col[lang]} ${row[i + 1]}` : ""))
        .filter(Boolean);
      lines.push(`• ${row[0]}${cells.length ? `: ${cells.join(", ")}` : ""}`);
    }
  }
  return lines;
}

function unavailableLine(reason: string, lang: "en" | "ko"): string {
  return lang === "ko"
    ? `지금은 한글 자료를 읽을 수 없어요 (${reason}). 수치를 추측하지는 않을게요.`
    : `I couldn't read the Hangeul data just now (${reason}). I won't guess the figures.`;
}

function renderIn(result: AnswerResult, lang: "en" | "ko", options: RenderOptions): string {
  if (result.unavailable) return unavailableLine(result.unavailable, lang);
  const blocks: string[] = [];
  if (result.headline.length) blocks.push(result.headline.map((h) => h[lang]).join("\n"));
  if (result.facts.length) {
    blocks.push(result.facts.map((f) => `• ${f.label[lang]}: ${f.value === NOT_GIVEN.en && lang === "ko" ? NOT_GIVEN.ko : f.value}`).join("\n"));
  }
  for (const table of result.tables) blocks.push(renderTable(table, lang).join("\n"));
  if (result.notes.length) blocks.push(result.notes.map((n) => n[lang]).join("\n"));
  const asOf = asOfLine(result, lang, options);
  if (asOf) blocks.push(asOf);
  return blocks.join("\n\n").trim();
}

/** The code-built answer text: facts and tables verbatim, then the as-of line. */
export function renderAnswer(result: AnswerResult, lang: AnswerLang, options: RenderOptions): string {
  if (lang === "bilingual") return `${renderIn(result, "en", options)}\n\n—\n\n${renderIn(result, "ko", options)}`;
  return renderIn(result, lang, options);
}

/** What the language model is given (D11: values included, PII too). */
export function factsForModel(result: AnswerResult, options: RenderOptions): Record<string, unknown> {
  return {
    intent: result.plan.intent,
    unavailable: result.unavailable ?? null,
    headline: result.headline.map((h) => h.en),
    facts: result.facts.map((f) => ({ label: f.label.en, value: f.value })),
    tables: result.tables.map((t) => ({ title: t.title.en, columns: t.columns.map((c) => c.en), rows: t.rows.slice(0, 20) })),
    notes: result.notes.map((n) => n.en),
    as_of: asOfLine(result, "en", options),
  };
}

// ─── The prose number check (the pack's claims_problem rule, simplest form) ─

// Numbers are compared as whole tokens of their kind. A clock time ("02:35", the
// as-of line's) only allows the same time, never its hours or minutes as counts;
// a date ("1 Oct", "2026-09-30", "10월 1일") only the same date; an id
// ("HNG-2026-012", "A00000001") only the same id. Everything else is a count.
const MONTHS_RE = "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?";
const NUMBER_TOKEN = new RegExp(
  [
    // An id: letters then digits ("A00000001"), or letters-digits-digits ("HNG-2026-012").
    "(?<id>\\b[A-Za-z]{1,5}(?:-\\d+)+\\b|\\b[A-Za-z]{1,3}\\d{4,}\\b)",
    "(?<iso>\\b(?<iy>\\d{4})-(?<im>\\d{2})-(?<id2>\\d{2})\\b)",
    `(?<dm>\\b(?<dmd>\\d{1,2})(?:st|nd|rd|th)?(?: of)?[ -](?<dmm>${MONTHS_RE})\\.?(?![a-z])(?:,? \\d{4}\\b)?)`,
    `(?<md>\\b(?<mdm>${MONTHS_RE})\\.? (?<mdd>\\d{1,2})(?:st|nd|rd|th)?(?!\\d)(?:,? \\d{4}\\b)?)`,
    "(?<ko>(?<kom>\\d{1,2}) ?월 ?(?<kod>\\d{1,2}) ?일)",
    "(?<time>\\b(?<th>[01]?\\d|2[0-3]):(?<tm>[0-5]\\d)(?: ?(?<ap>[ap])\\.?m\\b\\.?)?)",
    "(?<num>\\d+(?:[.,]\\d+)*)",
  ].join("|"),
  "gi",
);

const MONTH_NUM: Record<string, number> = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
const pad = (n: number) => String(n).padStart(2, "0");

/** Every number in `text` as a typed token: "t:02:35", "d:10-01", "id:HNG-2026-012", "n:20". */
function numberTokens(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(NUMBER_TOKEN)) {
    const g = m.groups ?? {};
    if (g.id) out.push(`id:${g.id.toUpperCase()}`);
    else if (g.iso) out.push(`d:${g.im}-${g.id2}`);
    else if (g.dm) out.push(`d:${pad(MONTH_NUM[g.dmm.slice(0, 3).toLowerCase()])}-${pad(Number(g.dmd))}`);
    else if (g.md) out.push(`d:${pad(MONTH_NUM[g.mdm.slice(0, 3).toLowerCase()])}-${pad(Number(g.mdd))}`);
    else if (g.ko) out.push(`d:${pad(Number(g.kom))}-${pad(Number(g.kod))}`);
    else if (g.time) {
      let hour = Number(g.th);
      const ap = g.ap?.toLowerCase();
      if (ap === "p" && hour < 12) hour += 12;
      if (ap === "a" && hour === 12) hour = 0;
      out.push(`t:${pad(hour)}:${g.tm}`);
    } else if (g.num) {
      const plain = g.num.replace(/,/g, "");
      const n = Number(plain);
      out.push(`n:${Number.isFinite(n) ? String(n) : plain}`);
    }
  }
  return out;
}

function sentencesOf(prose: string): string[] {
  return prose
    .split(/(?<=[.!?。！？])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** True when every number in `prose` appears in `factsText` as the same kind of token (count, time, date, id). */
export function proseNumbersOk(prose: string, factsText: string): boolean {
  const allowed = new Set(numberTokens(factsText));
  return numberTokens(prose).every((n) => allowed.has(n));
}

/**
 * Keeps the prose sentences whose every number appears in the facts (at most
 * two sentences); a sentence with any other number is dropped. A time or a
 * date in the facts (the as-of line's 02:35, "1 Oct") never lets a bare count
 * through: "35 consultancies" needs a 35 among the figures.
 */
export function checkProse(prose: string, factsText: string, maxSentences = 2): { text: string; dropped: string[] } {
  const allowed = new Set(numberTokens(factsText));
  const kept: string[] = [];
  const dropped: string[] = [];
  for (const sentence of sentencesOf(prose)) {
    if (numberTokens(sentence).every((n) => allowed.has(n))) kept.push(sentence);
    else dropped.push(sentence);
  }
  return { text: kept.slice(0, maxSentences).join(" "), dropped };
}
