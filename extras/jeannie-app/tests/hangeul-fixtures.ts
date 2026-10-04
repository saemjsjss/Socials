// Synthetic Hangeul data for the tests (no real names, passports or phones):
// the shapes Hangeul BOT publishes (src/cloud/records.py), for 30 Sep 2026.
import type { HgRecord, HgRun } from "@/lib/hangeul/types";

export const TZ = "Asia/Dhaka";
/** 30 Sep 2026, 18:00 in Dhaka. */
export const NOW = new Date("2026-09-30T12:00:00Z");
/** 1 Oct 2026, 00:10 in Dhaka: the new day has no performance window yet. */
export const AFTER_MIDNIGHT = new Date("2026-09-30T18:10:00Z");

export function rec(kind: string, key: string, fields: Partial<HgRecord> = {}): HgRecord {
  return {
    kind,
    key,
    scope: "all",
    student_uid: null,
    student_hng_id: null,
    student_name: null,
    passport_no: null,
    day: null,
    data: {},
    content: `${kind} ${key}`,
    read_at: "2026-09-30T09:52:00+00:00",
    ...fields,
  };
}

const CONSULTANTS = [
  ["TEST CONSULTANT A", "1", "3.5", "3", "2", true],
  ["TEST CONSULTANT B", "2", "3.0", "4", "2", false],
  ["TEST CONSULTANT C", "3", "2.5", "8", "1", false],
  ["TEST CONSULTANT D", "4", "1.0", "2", "0", false],
  ["TEST CONSULTANT E", "5", "1.0", "2", "0", false],
  ["TEST CONSULTANT F", "6", "0.5", "1", "0", false],
] as const;

function performanceWindow(period: "today" | "month", first: string, last: string, done: string, rows: readonly (typeof CONSULTANTS)[number][]): HgRecord[] {
  const scope = `${period}|${first}`;
  const base = { period, period_label: period === "today" ? "Today" : "This Month", range: `${first} – ${last}`, first_day: first, last_day: last };
  return [
    rec("consultant_performance", `${scope}|summary`, {
      scope,
      day: last,
      data: {
        ...base,
        tiles: { "Consultancies done": done, "Files opened": "5", "Conversion (file open)": "25%", "Docs ready": "1" },
        top: { label: "Top performer", name: rows[0][0], score: rows[0][2], consultancies: rows[0][3], files_opened: rows[0][4], conversion: "67%", metrics: [] },
        count: rows.length,
        sort_note: "Sorted by score, highest first",
      },
    }),
    ...rows.map(([name, rank, score, consultancies, files, top]) =>
      rec("consultant_performance", `${scope}|${name}`, {
        scope,
        day: last,
        data: { ...base, name, rank, score, consultancies, files_opened: files, conversion: "50%", points: "1.5", docs_ready: "0", top },
      }),
    ),
  ];
}

const DAY_LABEL: Record<string, string> = { "2026-09-29": "29 Sep 2026", "2026-09-30": "30 Sep 2026" };

/** One day's consultation requests, keys from `base` (portal ids are unique across days). */
function consultations(day: string, statuses: string[], base = 900, fields: Partial<HgRecord> = {}): HgRecord[] {
  // 30 Sep's requesters are TEST REQUESTER 1-10; another day's are named by their id.
  const who = (i: number) => `TEST REQUESTER ${base === 900 ? i + 1 : base + i}`;
  return statuses.map((status, i) =>
    rec("consultation", `${base + i}`, {
      scope: day,
      day,
      student_name: who(i),
      data: {
        id: `${base + i}`,
        name: who(i),
        status,
        consultant: "TEST CONSULTANT A",
        handled_by: "TEST CONSULTANT B",
        received: `${DAY_LABEL[day]} 1${i}:00`,
        received_date: DAY_LABEL[day],
      },
      ...fields,
    }),
  );
}

/** 29 Sep, the day before NOW: 4 requests, read by the 29 Sep 23:35 full picture. */
export const YESTERDAY_REQUESTS = { day: "2026-09-29", statuses: ["Consulted", "No Answer", "Consulted", "File Opened"], read_at: "2026-09-29T15:00:00+00:00" };

export const STUDENT_ONE = rec("student", "101", {
  student_uid: 101,
  student_hng_id: "HNG-2026-012",
  student_name: "TEST STUDENT ONE",
  passport_no: "A00000001",
  day: "2026-07-28",
  data: {
    uid: "101",
    student_id: "HNG-2026-012",
    student_name: "TEST STUDENT ONE",
    program: "KOREAN LANGUAGE PROGRAM (KLP)",
    target_intake: "MARCH 2027",
    status: "Documents Verified",
    applied_on: "28 Jul 2026, 17:16",
    docs_status: "100%",
    payment_status: "Verified",
    paid: "12,000.00 BDT",
    method: "Cash",
    details: { "Passport No": "A00000001", DOB: "2001-01-01", "IELTS/TOEFL": "", Mobile: "01700000001" },
    blank_on_portal: ["details.IELTS/TOEFL"],
  },
});

export function records(): HgRecord[] {
  return [
    ...performanceWindow("today", "2026-09-30", "2026-09-30", "20", CONSULTANTS),
    ...performanceWindow("today", "2026-09-29", "2026-09-29", "15", CONSULTANTS.slice(0, 2)),
    ...performanceWindow("month", "2026-09-01", "2026-09-30", "731", CONSULTANTS.slice(0, 3)),
    ...consultations("2026-09-30", ["Consulted", "Consulted", "New", "Consulted", "New", "Consulted", "New", "Consulted", "New", "Consulted"]),
    rec("consultation_day", "2026-09-30", {
      day: "2026-09-30",
      data: { day: "2026-09-30", counts: { All: 10, New: 4, Consulted: 6, "No Answer": 0, "File Opened": 0, "Wrong Number": 0 }, listed: 10, complete: true },
    }),
    ...consultations(YESTERDAY_REQUESTS.day, YESTERDAY_REQUESTS.statuses, 800, { read_at: YESTERDAY_REQUESTS.read_at }),
    rec("consultation_day", YESTERDAY_REQUESTS.day, {
      day: YESTERDAY_REQUESTS.day,
      read_at: YESTERDAY_REQUESTS.read_at,
      data: { day: YESTERDAY_REQUESTS.day, counts: { All: 4, New: 0, Consulted: 2, "No Answer": 1, "File Opened": 1, "Wrong Number": 0 }, listed: 4, complete: true },
    }),
    ...[
      ["201", "TEST STUDENT FOUR", "HNG-2026-926", "12,000.00 BDT", "TEST STAFF X", "12 Sep, 10:05"],
      ["202", "TEST STUDENT FIVE", "HNG-2026-928", "12,000.00 BDT", "TEST STAFF Y", "12 Sep, 13:07"],
      ["203", "TEST STUDENT SIX", "HNG-2026-929", "15,500.00 BDT", "TEST STAFF X", "12 Sep, 16:40"],
    ].map(([uid, name, hng, amount, by, time]) =>
      rec("verification", uid, {
        scope: "2026-09-12",
        day: "2026-09-12",
        student_uid: Number(uid),
        student_hng_id: hng,
        student_name: name,
        data: { day: "2026-09-12", uid, name, student_id: hng, paid: amount, amount, method: "Cash", verified_by: by, verified_time: time },
      }),
    ),
    STUDENT_ONE,
    rec("student", "102", {
      student_uid: 102,
      student_hng_id: "HNG-2026-913",
      student_name: "TEST STUDENT TWO",
      passport_no: "A00000002",
      day: "2026-09-30",
      data: { uid: "102", student_id: "HNG-2026-913", student_name: "TEST STUDENT TWO", program: "BACHELOR'S DEGREE", status: "Application Received", applied_on: "30 Sep 2026, 11:00" },
    }),
    rec("student", "103", {
      student_uid: 103,
      student_name: "TEST STUDENT THREE",
      day: "2026-09-30",
      data: { uid: "103", student_id: "", student_name: "TEST STUDENT THREE", program: "EAP (ENGLISH FOR ACADEMIC PURPOSE)", status: "Application Received", applied_on: "30 Sep 2026, 12:30" },
    }),
    rec("student_progress", "101", { student_uid: 101, student_hng_id: "HNG-2026-012", student_name: "TEST STUDENT ONE", data: { pct: 22, status: "Verified" } }),
    rec("doc_check", "A00000001", {
      student_uid: 101,
      student_hng_id: "HNG-2026-012",
      student_name: "TEST STUDENT ONE",
      passport_no: "A00000001",
      day: "2026-09-29",
      read_at: "2026-09-29T08:02:00+00:00",
      data: { student: "TEST STUDENT ONE", verdict: "REVIEW", checked: "2026-09-29T14:02:00", document_rows: { PASS: 1, FLAG: 1 }, field_rows: { MATCH: 20 } },
    }),
    rec("doc_verdict", "A00000001|01 Passport", {
      scope: "A00000001",
      passport_no: "A00000001",
      student_uid: 101,
      student_name: "TEST STUDENT ONE",
      read_at: "2026-09-29T08:02:00+00:00",
      data: { doc: "01 Passport", verdict: "PASS", detail: "Readable." },
    }),
    rec("doc_verdict", "A00000001|08 Bank Solvency & Statement", {
      scope: "A00000001",
      passport_no: "A00000001",
      student_uid: 101,
      student_name: "TEST STUDENT ONE",
      read_at: "2026-09-29T08:02:00+00:00",
      data: { doc: "08 Bank Solvency & Statement", verdict: "FLAG", detail: "Statement older than 3 months." },
    }),
    rec("passport_alert", "101|passport_101_1.jpg", {
      student_uid: 101,
      student_hng_id: "HNG-2026-012",
      day: "2026-09-30",
      data: { uid: "101", file: "passport_101_1.jpg", status: "MATCH", checked: "2026-09-30 10:00", sent: false },
    }),
    rec("passport_alert", "102|passport_102_1.jpg", {
      student_uid: 102,
      student_hng_id: "HNG-2026-913",
      day: "2026-09-30",
      data: { uid: "102", file: "passport_102_1.jpg", status: "DISCREPANCY", checked: "2026-09-30 11:00", sent: true, sent_at: "2026-09-30 11:01" },
    }),
    rec("passport_alert", "103|passport_103_1.jpg", {
      student_uid: 103,
      day: "2026-09-28",
      data: { uid: "103", file: "passport_103_1.jpg", status: "MATCH", checked: "2026-09-28 09:00", sent: false },
    }),
    rec("dashboard_fact", "At a glance|Applied this month", { data: { group: "At a glance", label: "Applied this month", value: 113, text: "113" } }),
    rec("dashboard_fact", "Needs attention|Missing documents", { data: { group: "Needs attention", label: "Missing documents", value: 161, text: "161", note: "students" } }),
    rec("pending_payment", "103", { student_uid: 103, student_name: "TEST STUDENT THREE", day: "2026-09-30", data: { uid: "103", payment_status: "Pending", badge: 1, paid: "0.00 BDT", program: "EAP" } }),
    rec("calendar_item", "77", { day: "2026-10-02", data: { id: "77", title: "TEST UNIVERSITY application period", kind: "Application period", where: "Online", start: "2026-09-21", end: "2026-10-02", done: false } }),
    rec("report", "missing_report|2026-09-30", {
      scope: "missing_report",
      day: "2026-09-30",
      read_at: "2026-09-30T03:05:00+00:00",
      data: {
        report: "missing_report",
        when: "2026-09-30",
        facts: {
          rows: [
            { program: "KLP", intake: "MARCH 2027", student_id: "HNG-2026-012", full_name: "TEST STUDENT ONE", mobile: "01700000001", missing_count: 2, missing_fields: "SSC GPA, HSC GPA" },
            { program: "KLP", intake: "MARCH 2027", student_id: "HNG-2026-913", full_name: "TEST STUDENT TWO", mobile: "01700000002", missing_count: 1, missing_fields: "SSC GPA" },
          ],
        },
      },
    }),
  ];
}

const FULL_PICTURE = [
  "student",
  "consultation",
  "verification",
  "calendar_item",
  "dashboard_fact",
  "pending_payment",
  "consultation_day",
  "window_application",
  "consultation_totals",
  "consultant_performance",
];

function run(job: string, finished: string, kinds: readonly string[]): HgRun {
  return { job, started_at: finished, finished_at: finished, status: "ok", byKind: Object.fromEntries(kinds.map((k) => [k, [0, 0, 1]])), failedReads: [] };
}

export function runs(): HgRun[] {
  return [
    run("full_picture", "2026-09-30T11:35:40+00:00", FULL_PICTURE),
    run("portal_sync", "2026-09-30T11:58:10+00:00", ["report", "report_section", "doc_check", "student_export", "student_documents"]),
    run("passport_watcher", "2026-09-30T11:57:05+00:00", ["student", "passport_alert", "passport_audit"]),
    run("full_picture", "2026-09-29T17:35:00+00:00", FULL_PICTURE),
    run("backfill", "2026-09-29T16:05:00+00:00", [
      "student",
      "student_progress",
      "doc_verdict",
      "field_check",
      "doc_page_text",
      "passport_issue",
      "field_correction",
      "report",
      "consultant_performance",
    ]),
  ];
}
