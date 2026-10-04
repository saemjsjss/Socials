// Hangeul context: the shapes Hangeul BOT publishes to Supabase (migration
// 20260929030000_hangeul_context.sql, bot src/cloud/records.py) and the shapes
// the answer code builds from them. Dependency-free and isomorphic: the server,
// the Edge chat route and the PWA's IndexedDB copy all share it.

/** Every kind the bot publishes, in the bot's own order (records.CLOUD_KINDS). The snapshot pages kinds in this order. */
export const HG_KINDS = [
  "student",
  "student_export",
  "student_profile",
  "student_progress",
  "student_documents",
  "verification",
  "consultation",
  "consultation_day",
  "consultation_totals",
  "pending_payment",
  "window_application",
  "dashboard_fact",
  "calendar_item",
  "passport_audit",
  "passport_alert",
  "passport_issue",
  "doc_verdict",
  "doc_check",
  "field_check",
  "field_correction",
  "doc_page_text",
  "report",
  "report_section",
  "brief_fact",
  "notification",
  "consultant_performance",
] as const;

export type HgKind = (typeof HG_KINDS)[number];

export function isHgKind(value: unknown): value is HgKind {
  return typeof value === "string" && (HG_KINDS as readonly string[]).includes(value);
}

/** One row of hg_records: the latest state of one entity. Timestamps are ISO strings (UTC from PostgREST). */
export interface HgRecord {
  kind: string;
  key: string;
  scope: string;
  student_uid: number | null;
  student_hng_id: string | null;
  student_name: string | null;
  passport_no: string | null;
  /** Business day (Asia/Dhaka), "YYYY-MM-DD". */
  day: string | null;
  data: Record<string, unknown>;
  content: string;
  content_hash?: string;
  source?: string;
  /** When the bot read it, i.e. the read that last CHANGED the row (same-hash reads leave it alone). */
  read_at: string;
  run_id?: string | null;
  updated_at?: string;
}

/** One embedded chunk of a record (gte-small, 384-d, L2-normalised). */
export interface HgChunk {
  kind: string;
  key: string;
  ord: number;
  content: string;
  embedding: Float32Array | number[];
  embed_model: string;
}

export type HgRunStatus = "ok" | "partial" | "failed";

/** One hg_runs row, trimmed to what the "as of" line needs. */
export interface HgRun {
  job: string;
  started_at: string;
  finished_at: string | null;
  status: HgRunStatus | null;
  /** counts.by_kind: {kind: [upserted, deleted, unchanged]}; a kind is present only when its read succeeded. */
  byKind: Record<string, number[]>;
  failedReads: string[];
}

/** One hg_match hit (a chunk plus its record's columns). */
export interface HgHit {
  kind: string;
  key: string;
  ord: number;
  content: string;
  similarity: number;
  data: Record<string, unknown>;
  day: string | null;
  read_at: string;
  student_uid: number | null;
  student_hng_id: string | null;
  student_name: string | null;
}

/** One hg_changes row (light form: no data). */
export interface HgChange {
  seq: number;
  kind: string;
  key: string;
  op: "upsert" | "delete";
  changed_at: string;
}

// ─── Readers: what the answer code needs, implemented by the server store and by the device copy ──

/**
 * Filter for `records(kind, filter)`. Every given condition must hold (AND).
 * `from`/`to` are inclusive bounds on `day`; `dataEq` compares `String(data[field])`.
 */
export interface RecordFilter {
  key?: string;
  keys?: readonly string[];
  keySuffix?: string;
  scope?: string;
  scopePrefix?: string;
  day?: string;
  from?: string;
  to?: string;
  studentUid?: number;
  studentHngId?: string;
  passportNo?: string;
  dataEq?: Readonly<Record<string, string>>;
  /** "key" (default) or newest day first. */
  order?: "key" | "day.desc";
  limit?: number;
}

export interface StudentQuery {
  hngId?: string;
  uid?: number;
  passport?: string;
  name?: string;
}

export interface MatchOptions {
  count?: number;
  kinds?: readonly string[];
  from?: string;
  to?: string;
  studentUid?: number;
}

/**
 * Read access to the published data. Every method throws a HangeulReadError-like
 * error (`name === "HangeulReadError"`, plain `message`) when the data cannot be
 * read; none ever returns an empty list for a failed read.
 */
export interface HangeulReaders {
  records(kind: HgKind, filter?: RecordFilter): Promise<HgRecord[]>;
  /** Finished runs (status ok or partial), newest first; enough to date every kind asked for. */
  runs(kinds: readonly string[]): Promise<HgRun[]>;
  /** Student records (kind "student") matching the query, best match first. */
  findStudents(query: StudentQuery): Promise<HgRecord[]>;
  /** Change-log rows after an ISO time, oldest first (server only; the device keeps no log). */
  changes?(sinceIso: string, limit?: number): Promise<HgChange[]>;
  /** Vector search (server: hg_match). */
  match?(embedding: readonly number[], options?: MatchOptions): Promise<HgHit[]>;
  /** Embeds question texts (server: the hg-embed Edge Function). */
  embed?(texts: readonly string[]): Promise<number[][]>;
}

export type HangeulReadCode = "not_configured" | "not_migrated" | "unreachable" | "invalid" | "cancelled";

/** A read failed. `message` is a plain reason safe to show; it never holds data, keys or URLs. */
export class HangeulReadError extends Error {
  readonly code: HangeulReadCode;

  constructor(message: string, code: HangeulReadCode = "unreachable") {
    super(message);
    this.name = "HangeulReadError";
    this.code = code;
  }
}

export function isHangeulReadError(error: unknown): error is Error {
  return error instanceof Error && error.name === "HangeulReadError";
}

// ─── Plans ──────────────────────────────────────────────────────────────────

export type ReportName = "brief" | "missing" | "stage" | "document_check" | "field_check" | "inquiries";

/** What a question asks for, as the router understood it. Days are ISO "YYYY-MM-DD" in the business time zone. */
export type Plan =
  | { intent: "student_card"; student: StudentQuery }
  | { intent: "verified_on_day"; from: string; to: string }
  | { intent: "inquiries_on_day"; day: string; to?: string; status?: string }
  | { intent: "pending_payments" }
  | { intent: "window_review" }
  | { intent: "doc_verdicts"; student?: StudentQuery; verdict?: string }
  /** `day` for one day, `from`/`to` for a range (scans checked in it), neither for every scan on file. */
  | { intent: "passport_alerts"; day?: string; from?: string; to?: string; student?: StudentQuery }
  /** `where`: the university or place named ("deadlines for Gachon"); only items that mention it count. */
  | { intent: "calendar_window"; from: string; to: string; where?: string }
  | { intent: "missing_for_student"; student: StudentQuery }
  | { intent: "changes_since"; since: string; sinceLabel: string }
  | { intent: "report"; report: ReportName; day?: string }
  /**
   * `to` (period "today" only): a range of days from `day`, which the portal's page does not show (it has Today and
   * This Month); the answer says so and lists the day windows on file in it.
   */
  | { intent: "performance"; period: "today" | "month"; day: string; to?: string }
  /** `to`: a range of days from `day` (see `performance`), with the requests received day by day. */
  | { intent: "consultancies_closed_today"; day: string; to?: string }
  | { intent: "students_applied"; from: string; to: string }
  | { intent: "dashboard" }
  | { intent: "data_status" }
  | { intent: "semantic"; question: string; kinds?: readonly string[]; from?: string; to?: string; student?: StudentQuery };

export type PlanIntent = Plan["intent"];

/** Plans a device cannot answer from its own copy: they need the server (/api/hangeul/ask). */
export const SERVER_ONLY_INTENTS: ReadonlySet<PlanIntent> = new Set(["changes_since", "data_status"]);

// ─── Results ────────────────────────────────────────────────────────────────

/** A text in both answer languages. */
export interface Bi {
  en: string;
  ko: string;
}

/** One code-built figure: shown verbatim, and the only numbers the prose may use. */
export interface Fact {
  label: Bi;
  value: string;
}

/** A code-built table. `rows[i][0]` names the row; the other cells follow `columns`. */
export interface Table {
  title: Bi;
  columns: Bi[];
  rows: string[][];
  /** The same rows with Korean cell text, when some cells are words the code wrote (kind names). */
  rowsKo?: string[][];
}

/** When the data behind one kind was last confirmed. */
export interface AsOf {
  /** ISO time. */
  at: string;
  /** The job whose run confirmed it ("full_picture"), or null when dated by the rows' own read_at. */
  job: string | null;
  source: "run" | "read_at";
}

export interface AnswerSource {
  kind: string;
  key: string;
}

export interface AnswerResult {
  plan: Plan;
  /** One or more headline sentences (spoken). */
  headline: Bi[];
  facts: Fact[];
  tables: Table[];
  /** Plain notes shown after the tables ("not given on the portal", "not available yet"...). */
  notes: Bi[];
  /** Per kind the answer read. A kind never published is absent. */
  asOf: Record<string, AsOf>;
  /** The records the answer was built from (for the device, and for the PWA's "open" links). */
  sources: AnswerSource[];
  /** Set when the data could not be read at all: the answer is only this reason. */
  unavailable?: string;
}
