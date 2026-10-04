import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  asOfLine,
  checkProse,
  factsForModel,
  needsSearchRewrite,
  planFor,
  proseNumbersOk,
  renderAnswer,
  runPlan,
  type RunOptions,
} from "@/lib/hangeul/answer";
import { businessDay } from "@/lib/hangeul/days";
import { readersFromRecords } from "@/lib/hangeul/memory-readers";
import { HangeulReadError, type HangeulReaders, type HgHit, type HgRecord, type Plan } from "@/lib/hangeul/types";
import { AFTER_MIDNIGHT, NOW, rec, records, runs, STUDENT_ONE, TZ } from "./hangeul-fixtures";

const options = (now = NOW, extra: Partial<RunOptions> = {}): RunOptions => ({ now, timeZone: TZ, ...extra });
const readers = (extra: Parameters<typeof readersFromRecords>[0] | null = null) =>
  readersFromRecords(extra ?? { records: records(), runs: runs() });

async function answer(question: string, now = NOW, r: HangeulReaders = readers(), extra: Partial<RunOptions> = {}) {
  const plan = planFor(question, { today: businessDay(now, TZ), now, timeZone: TZ });
  const result = await runPlan(plan, r, options(now, extra));
  return { plan, result, en: renderAnswer(result, "en", { now, timeZone: TZ }), ko: renderAnswer(result, "ko", { now, timeZone: TZ }) };
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("consultancies closed today (the owner's question)", () => {
  it("gives the performance tile, per consultant, and today's requests by status, as of the full picture", async () => {
    const { result, en } = await answer("how many consultancies were closed today?");
    expect(result.unavailable).toBeUndefined();
    expect(en).toContain(
      "Consultancies done today (30 Sep): 20 — TEST CONSULTANT C 8, TEST CONSULTANT B 4, TEST CONSULTANT A 3, TEST CONSULTANT D 2, TEST CONSULTANT E 2, TEST CONSULTANT F 1.",
    );
    expect(en).toContain("• Consultancies done: 20");
    expect(en).toContain("• Files opened: 5");
    expect(en).toContain("• Top performer: TEST CONSULTANT A (score 3.5, consultancies 3)");
    expect(en).toContain("• TEST CONSULTANT C: Consultancies 8, Files opened 1");
    expect(en).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    // Rows add up to the tile, so no mismatch note.
    expect(en).not.toContain("add up to");
    expect(en.trim().split("\n").at(-1)).toBe("As of 17:35 (full picture)");
    expect(result.asOf.consultant_performance).toEqual({ at: "2026-09-30T11:35:40+00:00", job: "full_picture", source: "run" });
  });

  it("after midnight, says today's figures are not available yet and never shows yesterday's as today's", async () => {
    const { en } = await answer("how many consultancies were closed today?", AFTER_MIDNIGHT);
    expect(en).toContain("Consultancies done today (1 Oct): not available yet.");
    expect(en).toContain("The latest day on file is 2026-09-30 – 2026-09-30");
    expect(en).toContain("Requests received today (1 Oct): not available yet.");
    expect(en).not.toMatch(/Consultancies done[^\n]*: 20/);
    expect(en).not.toContain("• Consultancies done");
  });

  it("answers a past day from its own window, dated by the last run of that day", async () => {
    const { result, en } = await answer("how many consultancies were done yesterday?");
    expect(en).toContain("Consultancies done yesterday (29 Sep): 15");
    // That day's requests only (the fixtures hold 30 Sep's too): by the day received, with their current status.
    expect(en).toContain("Requests received yesterday (29 Sep): 4 (Consulted 2, File Opened 1, No Answer 1).");
    expect(result.asOf.consultant_performance).toMatchObject({ job: "full_picture", at: "2026-09-29T17:35:00+00:00" });
    // One job at two times: each time says what it dates.
    expect(asOfLine(result, "en", { now: NOW, timeZone: TZ })).toBe(
      "As of 29 Sep 23:35 (consultant performance, full picture) · consultation requests 17:35 (full picture)",
    );
  });

  it("leads with 'not available yet' for the tile, and never takes a window from another day", async () => {
    // A mis-scoped summary (its first_day is not today) is not today's window.
    const data = records().map((r) => (r.key === "today|2026-09-30|summary" ? { ...r, data: { ...r.data, first_day: "2026-09-29" } } : r));
    const { result, en } = await answer("how many consultancies were closed today?", NOW, readers({ records: data, runs: runs() }));
    expect(result.headline[0].en).toBe("Consultancies done today (30 Sep): not available yet.");
    expect(en).not.toContain("• Consultancies done");
  });

  it("notes when the leaderboard rows do not add up to the tile", async () => {
    const data = records().map((r) =>
      r.key === "today|2026-09-30|TEST CONSULTANT F" ? { ...r, data: { ...r.data, consultancies: "2" } } : r,
    );
    const { en } = await answer("how many consultancies were closed today?", NOW, readers({ records: data, runs: runs() }));
    expect(en).toContain("The leaderboard rows add up to 21; the portal's tile says 20.");
  });

  it("renders in Korean and bilingually", async () => {
    const { result, ko } = await answer("오늘 상담 몇 건 끝났어?");
    expect(ko).toContain("오늘(9월 30일) 상담 완료: 20");
    expect(ko).toContain("• 상담 완료: 20");
    expect(ko).toContain("기준: 17:35 (전체 점검)");
    const both = renderAnswer(result, "bilingual", { now: NOW, timeZone: TZ });
    expect(both.split("\n\n—\n\n")).toHaveLength(2);
  });

  it("a tile the portal left blank reads 'not given on the portal' in each language, headline included", async () => {
    const data = records().map((r) => {
      if (r.key !== "today|2026-09-30|summary") return r;
      const tiles = { ...(r.data.tiles as Record<string, string>) };
      delete tiles["Consultancies done"];
      return { ...r, data: { ...r.data, tiles, blank_on_portal: ["tiles.Consultancies done"] } };
    });
    const { en, ko } = await answer("how many consultancies were closed today?", NOW, readers({ records: data, runs: runs() }));
    expect(en).toContain("Consultancies done today (30 Sep): not given on the portal — TEST CONSULTANT C 8");
    expect(ko).toContain("오늘(9월 30일) 상담 완료: 포털에 입력되지 않음 — TEST CONSULTANT C 8");
    expect(ko).toContain("• 상담 완료: 포털에 입력되지 않음");
    expect(ko).not.toContain("not given");
  });

  it("today's count holds today's requests only, not a neighbouring day's", async () => {
    const { en } = await answer("how many consultancies were closed today?");
    expect(en).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    const inquiries = await answer("How many inquiries came in yesterday?");
    expect(inquiries.en).toContain("Requests received yesterday (29 Sep): 4 (Consulted 2, File Opened 1, No Answer 1).");
    expect(inquiries.en).not.toContain("TEST REQUESTER 1:");
    expect(inquiries.en).toContain("• TEST REQUESTER 800: Status Consulted");
  });

  it("a range of days says the portal has no figure for it, lists the day windows on file and the requests day by day", async () => {
    const { result, en, ko } = await answer("how many consultancies were closed this week?");
    expect(result.plan).toEqual({ intent: "consultancies_closed_today", day: "2026-09-24", to: "2026-09-30" });
    expect(en).toContain("Consultancies done 24 Sep – 30 Sep: not on the portal. Its Consultant Performance page shows only today and this month.");
    expect(en).toContain("• 29 Sep: Consultancies done 15, Files opened 5");
    expect(en).toContain("• 30 Sep: Consultancies done 20, Files opened 5");
    expect(en).toContain("Requests received 24 Sep – 30 Sep: 14.");
    expect(en).toContain("• 29 Sep: 4");
    expect(en).toContain("• 30 Sep: 10");
    // Never today's single-day figure labelled as the week's.
    expect(en).not.toMatch(/Consultancies done[^\n]*: 20\b/);
    expect(ko).toContain("9월 24일 ~ 9월 30일 상담 완료: 포털에 없는 수치예요.");
    const perf = await answer("consultant performance this week");
    expect(perf.en).toContain("Consultant performance 24 Sep – 30 Sep: not on the portal.");
    expect(perf.en).not.toContain("on the leaderboard");
  });
});

describe("performance", () => {
  it("today's leaderboard in rank order and this month's tiles", async () => {
    const today = await answer("consultant performance today");
    expect(today.en).toContain("Consultant performance today (30 Sep) (2026-09-30 – 2026-09-30): 6 consultants on the leaderboard.");
    const lines = today.en.split("\n").filter((l) => l.startsWith("• TEST CONSULTANT"));
    expect(lines[0]).toBe(
      "• TEST CONSULTANT A ★: Rank 1, Score 3.5, Consultancies 3, Files opened 2, Conversion 50%, Points 1.5, Docs ready 0",
    );
    const month = await answer("consultant performance this month");
    expect(month.en).toContain("Consultant performance, Sep 2026");
    expect(month.en).toContain("• Consultancies done: 731");
  });
});

describe("verified on a day", () => {
  it("counts the day's verifications exactly, with the total and who verified", async () => {
    const { en } = await answer("How many payments were verified on 12 Sep?");
    expect(en).toContain("Payments verified 12 Sep: 3.");
    expect(en).toContain("• Total verified: 39,500.00 BDT");
    expect(en).toContain("• TEST STAFF X: 2");
    expect(en).toContain("• TEST STUDENT FOUR (HNG-2026-926): Amount 12,000.00 BDT, Method Cash, Verified by TEST STAFF X, When 12 Sep, 10:05");
  });

  it("says 0 for an empty day of a kind the bot reads, dated by its run", async () => {
    const { en } = await answer("How many payments were verified on 13 Sep?");
    expect(en).toContain("Payments verified 13 Sep: 0.");
    expect(en).toContain("As of 17:35 (full picture)");
  });
});

describe("not available yet (never 0 for an unread kind)", () => {
  it("a kind no run has read and no row holds is not available yet", async () => {
    const noVerifications = readers({ records: records().filter((r) => r.kind !== "verification"), runs: [] });
    const { en } = await answer("How many payments were verified on 12 Sep?", NOW, noVerifications);
    expect(en).toContain("Payments verified 12 Sep: not available yet.");
    expect(en).not.toMatch(/: 0\b/);
  });

  it("a kind read with no rows is 0, as of that run", async () => {
    const { en } = await answer("any window applications under review?");
    expect(en).toContain("Window applications under review: 0.");
    expect(en).toContain("As of 17:35 (full picture)");
  });

  it("no brief yet: says so first, then shows the dashboard instead", async () => {
    const { en, result } = await answer("Hangeul daily report");
    expect(en.startsWith("Daily brief: not available yet.\nHangeul BOT sends its brief at 18:05.\nFrom the portal's dashboard instead:\n\nAt a glance:")).toBe(
      true,
    );
    expect(en).toContain("• Applied this month: 113");
    expect(en).toContain("• Missing documents — students: 161");
    // The missing brief is dated by nothing: the portal sync (which made other reports) never dates it.
    expect(result.asOf.report).toBeUndefined();
    expect(en.trim().split("\n").at(-1)).toBe("As of 17:35 (full picture)");
  });

  it("the latest brief, with its day, when there is one", async () => {
    const brief = rec("report", "brief|2026-09-29", {
      scope: "brief",
      day: "2026-09-29",
      read_at: "2026-09-29T12:05:00+00:00",
      data: { report: "brief", when: "2026-09-29", facts: { lines: ["3 payments verified today.", "No passport alerts."], pending_payments: { count: 1 } } },
    });
    const { en, result } = await answer("Hangeul daily report", NOW, readers({ records: [...records(), brief], runs: runs() }));
    expect(en).toContain("Daily brief of 29 Sep 2026:");
    expect(en).toContain("• 3 payments verified today.");
    expect(en).toContain("• Pending payments: 1");
    expect(en).toContain("Today's brief is not available yet; Hangeul BOT sends it at 18:05.");
    expect(result.asOf.report).toEqual({ at: "2026-09-29T12:05:00+00:00", job: "daily_brief", source: "read_at" });
  });
});

describe("as of: a day is dated by the runs that read that day", () => {
  // 12 Sep's requests: only the backfill (29 Sep 22:05) has read them; the full picture reads yesterday and today.
  const twelfth = [
    rec("consultation", "500", { scope: "2026-09-12", day: "2026-09-12", read_at: "2026-09-29T15:30:00+00:00", data: { status: "Consulted" } }),
    rec("consultation", "501", { scope: "2026-09-12", day: "2026-09-12", read_at: "2026-09-29T15:30:00+00:00", data: { status: "New" } }),
    rec("consultation_day", "2026-09-12", { day: "2026-09-12", read_at: "2026-09-29T15:30:00+00:00", data: { day: "2026-09-12", counts: { All: 2 } } }),
  ];
  // A Telegram command at 17:50 that published one day (which one, the run does not say) and the pending list.
  const command = {
    job: "command",
    started_at: "2026-09-30T11:50:00+00:00",
    finished_at: "2026-09-30T11:50:00+00:00",
    status: "ok" as const,
    byKind: { consultation: [1, 0, 0], consultation_day: [0, 0, 1], pending_payment: [0, 0, 1] },
    failedReads: [],
  };
  // The backfill read every day's requests up to its own.
  const withBackfill = () =>
    runs().map((r) => (r.job === "backfill" ? { ...r, byKind: { ...r.byKind, consultation: [2, 0, 0], consultation_day: [1, 0, 0] } } : r));
  const withTwelfth = (list = withBackfill()) => readers({ records: [...records(), ...twelfth], runs: list });

  it("an older day by the backfill that read it, not by the newest full picture", async () => {
    const { en, result } = await answer("how many inquiries on 12 Sep?", NOW, withTwelfth());
    expect(en).toContain("Requests received 12 Sep: 2 (Consulted 1, New 1).");
    expect(result.asOf.consultation).toEqual({ at: "2026-09-29T16:05:00+00:00", job: "backfill", source: "run" });
    expect(en.trim().split("\n").at(-1)).toBe("As of 29 Sep 22:05 (backfill)");
  });

  it("yesterday by today's full picture (it reads yesterday too), today by the newest run of today", async () => {
    const yesterday = await answer("How many inquiries came in yesterday?", NOW, withTwelfth());
    expect(yesterday.result.asOf.consultation).toMatchObject({ job: "full_picture", at: "2026-09-30T11:35:40+00:00" });
    const today = await answer("How many inquiries came in today?", NOW, withTwelfth([...withBackfill(), command]));
    // A command of the same day may date today's requests; it never dates another day's.
    expect(today.result.asOf.consultation).toMatchObject({ job: "command", at: "2026-09-30T11:50:00+00:00" });
    const older = await answer("how many inquiries on 12 Sep?", NOW, withTwelfth([...withBackfill(), command]));
    expect(older.result.asOf.consultation).toMatchObject({ job: "backfill" });
  });

  it("a command never dates a whole kind", async () => {
    const { result } = await answer("Any pending payments?", NOW, withTwelfth([...withBackfill(), command]));
    expect(result.asOf.pending_payment).toMatchObject({ job: "full_picture", at: "2026-09-30T11:35:40+00:00" });
  });

  it("a range is as fresh as its least recently read day", async () => {
    const { en, result } = await answer("how many inquiries in the last 30 days?", NOW, withTwelfth());
    expect(en).toContain("Requests received 1 Sep – 30 Sep: 16.");
    expect(result.asOf.consultation).toMatchObject({ job: "backfill", at: "2026-09-29T16:05:00+00:00" });
  });

  it("falls back to the rows' own read_at when no run read that day", async () => {
    const onlyToday = withBackfill().filter((r) => r.job !== "backfill");
    const { result } = await answer("how many inquiries on 12 Sep?", NOW, withTwelfth(onlyToday));
    expect(result.asOf.consultation).toEqual({ at: "2026-09-29T15:30:00+00:00", job: null, source: "read_at" });
  });
});

describe("passport alerts", () => {
  it("a range counts the scans checked in it", async () => {
    const { en, result } = await answer("any passport alerts in the last 2 days?");
    expect(result.plan).toEqual({ intent: "passport_alerts", from: "2026-09-29", to: "2026-09-30" });
    expect(en).toContain("Passport scans checked 29 Sep – 30 Sep: 2, 1 with a problem, 1 alert sent.");
  });

  it("names the students of the newest problem scans (the rows shown), however many there are", async () => {
    const alerts: HgRecord[] = [];
    const students: HgRecord[] = [];
    for (let uid = 1; uid <= 70; uid++) {
      // Newer with every uid; the keys' text order ("1|", "10|", ... "7|", "70|", "8|") is not the time order.
      const checked = `2026-09-${String(10 + Math.floor(uid / 10)).padStart(2, "0")} ${String(uid % 10).padStart(2, "0")}:00`;
      alerts.push(rec("passport_alert", `${uid}|passport_${uid}.jpg`, { student_uid: uid, day: checked.slice(0, 10), data: { uid: String(uid), status: "DISCREPANCY", checked, sent: false } }));
      students.push(rec("student", String(uid), { student_uid: uid, student_name: `TEST STUDENT U${uid}`, data: {} }));
    }
    const { en } = await answer("any passport problems?", NOW, readers({ records: [...alerts, ...students], runs: runs() }));
    const rows = en.split("\n").filter((l) => l.startsWith("• ") && l.includes("Status DISCREPANCY"));
    expect(rows).toHaveLength(40);
    for (const row of rows) expect(row).toMatch(/^• TEST STUDENT U\d+: /);
    // The newest scan (uid 70, 17 Sep 00:00) leads the table.
    expect(rows[0]).toContain("TEST STUDENT U70:");
  });
});

describe("student card", () => {
  it("finds HNG-2026-12 as HNG-2026-012 and says a blank portal field is not given", async () => {
    const { en, ko, result } = await answer("Who is HNG-2026-12?");
    expect(en).toContain("TEST STUDENT ONE (HNG-2026-012, portal uid 101): Documents Verified.");
    expect(en).toContain("• Passport: A00000001");
    expect(en).toContain("• IELTS/TOEFL: not given on the portal");
    expect(ko).toContain("• IELTS/TOEFL: 포털에 입력되지 않음");
    expect(en).toContain("• Progress: 22%, Verified");
    expect(en).toContain("• Document check: REVIEW, checked 2026-09-29 14:02");
    expect(result.sources).toContainEqual({ kind: "student", key: "101" });
    // The doc check is dated by its own check time; the student by its run.
    // The student kind's newest run is the passport watcher's; the progress only the backfill has read.
    expect(asOfLine(result, "en", { now: NOW, timeZone: TZ })).toBe("As of 17:57 (passport watcher) · backfill 29 Sep 22:05 · document checks 29 Sep 14:02");
  });

  it("lists candidates for an ambiguous name and says when nobody matches", async () => {
    const many = await answer("find student TEST");
    expect(many.en).toContain("3 students match TEST:");
    const none = await answer("find student Zed Quill");
    expect(none.en).toContain("No student matches Zed Quill.");
  });
});

describe("other plans", () => {
  it("passport alerts today", async () => {
    const { en } = await answer("Any passport alerts today?");
    expect(en).toContain("Passport scans checked today (30 Sep): 2, 1 with a problem, 1 alert sent.");
    expect(en).toContain("• TEST STUDENT TWO (HNG-2026-913): Status DISCREPANCY, Checked 2026-09-30 11:00, Alert sent 2026-09-30 11:01");
  });

  it("missing information for a student, from the latest missing report and the blank portal fields", async () => {
    const { en } = await answer("What's the missing information for student HNG-2026-12?");
    expect(en).toContain("TEST STUDENT ONE: 2 missing in the report of 30 Sep: SSC GPA, HSC GPA.");
    expect(en).toContain("• Not given on the portal: IELTS/TOEFL");
  });

  it("a student's document check", async () => {
    const { en } = await answer("Show the documents of HNG-2026-12");
    expect(en).toContain("Document check of TEST STUDENT ONE (A00000001): REVIEW, checked 2026-09-29 14:02.");
    expect(en).toContain("• 08 Bank Solvency & Statement: Verdict FLAG, Detail Statement older than 3 months.");
  });

  it("requests received on a day, one row each", async () => {
    const { en } = await answer("How many inquiries came in today?");
    expect(en).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    expect(en).toContain("• TEST REQUESTER 1: Status Consulted, Consultant TEST CONSULTANT A");
  });

  it("calendar items for a named university, and none for one the agency's calendar does not have", async () => {
    const found = await answer("application deadlines for Test University");
    expect(found.en).toContain("Calendar items for Test University 30 Sep – 29 Nov: 1.");
    expect(found.en).toContain("• TEST UNIVERSITY application period: Kind Application period, Where Online, Dates 21 Sep – 2 Oct");
    const none = await answer("application deadlines for Harvard");
    expect(none.en).toContain("No item on the agency's calendar mentions Harvard 30 Sep – 29 Nov.");
    expect(none.en).not.toContain("TEST UNIVERSITY");
    expect(none.en).toContain("As of 17:35 (full picture)");
  });

  it("pending payments, calendar and dashboard", async () => {
    expect((await answer("Any pending payments?")).en).toContain("Pending payments: 1.");
    expect((await answer("any deadlines this week?")).en).toContain("• TEST UNIVERSITY application period: Kind Application period, Where Online, Dates 21 Sep – 2 Oct");
    expect((await answer("How many students do we have?")).en).toContain("• Applied this month: 113");
    expect((await answer("How many students applied today?")).en).toContain("Students who applied today (30 Sep): 2.");
  });

  it("changes since a time, by kind", async () => {
    const changes = [
      { seq: 1, kind: "consultation", key: "900", op: "upsert" as const, changed_at: "2026-09-30T05:00:00+00:00" },
      { seq: 2, kind: "consultation", key: "901", op: "upsert" as const, changed_at: "2026-09-30T06:00:00+00:00" },
      { seq: 3, kind: "notification", key: "abc", op: "delete" as const, changed_at: "2026-09-30T07:00:00+00:00" },
      { seq: 4, kind: "student", key: "101", op: "upsert" as const, changed_at: "2026-09-29T10:00:00+00:00" },
    ];
    const r = readersFromRecords({ records: records(), runs: runs(), changes });
    const { en, ko } = await answer("What changed since this morning?", NOW, r);
    expect(en).toContain("Changes since 00:00: 2 records new or updated, 1 removed.");
    expect(en).toContain("• consultation requests: New or updated 2, Removed 0, Last change 12:00");
    expect(ko).toContain("• 상담 신청: 추가·변경 2");
    expect(en).toContain("(change log, live)");
  });

  it("data status lists the latest run of each job", async () => {
    const { en } = await answer("Is the Hangeul portal up?");
    expect(en).toContain("• portal sync: Finished 17:58, Status ok");
    expect(en).toContain("• full picture: Finished 17:35, Status ok");
  });
});

describe("semantic search", () => {
  const hit = (kind: string, key: string, similarity: number, extra: Partial<HgHit> = {}): HgHit => ({
    kind,
    key,
    ord: 0,
    content: `Document bank_statement.pdf of TEST STUDENT ONE (A00000001), page 1:\nOpening balance 50,000 BDT`,
    similarity,
    data: { file: "bank_statement.pdf", page: 1 },
    day: null,
    read_at: "2026-09-29T08:00:00+00:00",
    student_uid: 101,
    student_hng_id: "HNG-2026-012",
    student_name: "TEST STUDENT ONE",
    ...extra,
  });

  it("fails closed when the question cannot be embedded", async () => {
    const { en } = await answer("What does Karim's bank statement say about the opening balance?");
    expect(en).toContain("Search is not available yet: the question could not be embedded.");
  });

  it("embeds, searches the student's chunks and shows the matched page text", async () => {
    const match = vi.fn(async () => [hit("doc_page_text", "A00000001|bank_statement.pdf|p1", 0.91), hit("student", "999", 0.8)]);
    const embed = vi.fn(async (texts: readonly string[]) => texts.map(() => new Array(384).fill(0.01)));
    const r = readersFromRecords({ records: records(), runs: runs(), match, embed });
    const { en } = await answer("What does HNG-2026-12's bank statement say about the opening balance?", NOW, r);
    expect(embed).toHaveBeenCalledWith(["What does HNG-2026-12's bank statement say about the opening balance?"]);
    expect(match).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ studentUid: 101 }));
    expect(en).toContain("document page text: TEST STUDENT ONE");
    expect(en).toContain("• Opening balance 50,000 BDT");
    // The far hit (0.80 against 0.91) is left out.
    expect(en).not.toContain("999");
  });

  it("re-reads the device's own hits from current rows", async () => {
    const { en, result } = await answer("what about the bank statement of the student?", NOW, readers(), {
      hits: [{ kind: "doc_verdict", key: "A00000001|08 Bank Solvency & Statement" }],
    });
    expect(result.plan.intent).toBe("semantic");
    expect(en).toContain("document verdicts: TEST STUDENT ONE");
    expect(en).toContain("• verdict: FLAG");
  });

  it("rewrites Korean or Bangla questions into an English query before searching", async () => {
    expect(needsSearchRewrite("통장 잔고가 얼마야?")).toBe(true);
    expect(needsSearchRewrite("ব্যাংক স্টেটমেন্ট")).toBe(true);
    expect(needsSearchRewrite("bank statement")).toBe(false);
    const embed = vi.fn(async (texts: readonly string[]) => texts.map(() => new Array(384).fill(0.01)));
    const match = vi.fn(async () => [hit("doc_page_text", "A00000001|bank_statement.pdf|p1", 0.9)]);
    const rewrite = vi.fn(async () => "bank statement opening balance");
    const plan: Plan = { intent: "semantic", question: "한글 자료에서 통장 잔고 알려줘" };
    const result = await runPlan(plan, readersFromRecords({ records: records(), runs: runs(), match, embed }), options(NOW, { rewrite, embedding: new Array(384).fill(0.5) }));
    expect(rewrite).toHaveBeenCalledWith("한글 자료에서 통장 잔고 알려줘");
    // The device vector is of the Korean wording, so the English query is embedded again.
    expect(embed).toHaveBeenCalledWith(["bank statement opening balance"]);
    expect(result.headline[0].en).toContain("bank statement opening balance");
  });
});

describe("failures", () => {
  it("a read that fails is the plain reason, never a figure", async () => {
    const broken: HangeulReaders = {
      records: async () => {
        throw new HangeulReadError("Hangeul data unreachable (timeout)");
      },
      runs: async () => runs(),
      findStudents: async () => [],
    };
    const { en, ko, result } = await answer("how many consultancies were closed today?", NOW, broken);
    expect(result.unavailable).toBe("Hangeul data unreachable (timeout)");
    expect(en).toBe("I couldn't read the Hangeul data just now (Hangeul data unreachable (timeout)). I won't guess the figures.");
    expect(ko).toContain("수치를 추측하지는 않을게요");
  });
});

describe("the prose number check", () => {
  const facts = "Consultancies done today (30 Sep): 20.\n• Files opened: 5\n• Conversion (file open): 25%\n• Total verified: 39,500.00 BDT\nAs of 17:35 (full picture)";

  it("keeps sentences whose numbers are all in the facts", () => {
    expect(proseNumbersOk("Twenty is great: 20 done and 5 files opened by 17:35.", facts)).toBe(true);
    expect(proseNumbersOk("That is 25% conversion and 39500 BDT verified.", facts)).toBe(true);
    expect(proseNumbersOk("We did 21 today.", facts)).toBe(false);
  });

  it("drops a sentence with a number not in the facts", () => {
    const { text, dropped } = checkProse("Busy day, 부장님: 20 consultancies done. That's 45% better than last week!", facts);
    expect(text).toBe("Busy day, 부장님: 20 consultancies done.");
    expect(dropped).toEqual(["That's 45% better than last week!"]);
  });

  it("a time or a date in the answer never lets a bare count through (the as-of line's 02:35, '1 Oct')", () => {
    // The owner's question, answered at the start of 1 Oct.
    const rendered = [
      "Consultancies done today (1 Oct): 0.",
      "Requests received today (1 Oct): 0.",
      "",
      "• Consultancies done: 0",
      "• Files opened: 0",
      "• Conversion (file open): 0%",
      "• Docs ready: 0",
      "",
      "As of 02:35 (full picture)",
    ].join("\n");
    expect(checkProse("Your team closed 35 consultancies today.", rendered).text).toBe("");
    expect(checkProse("Your team closed 2 consultancies today.", rendered).text).toBe("");
    expect(checkProse("Your team closed 1 consultancy today.", rendered).text).toBe("");
    expect(checkProse("Your team closed 20 consultancies today.", rendered).text).toBe("");
    // The same time, the same date and the real counts still pass.
    expect(checkProse("Nothing closed yet: 0 so far, as of 02:35.", rendered).text).toBe("Nothing closed yet: 0 so far, as of 02:35.");
    expect(checkProse("As of 2:35 am on 1 October, 0 done.", rendered).text).toBe("As of 2:35 am on 1 October, 0 done.");
    expect(checkProse("By 03:35 nothing was done.", rendered).text).toBe("");
    expect(checkProse("Nothing on 2 Oct.", rendered).text).toBe("");
    // Korean: "10월 1일" is a date, not the counts 10 and 1.
    const ko = "오늘(10월 1일) 상담 완료: 0.\n\n기준: 02:35 (전체 점검)";
    expect(checkProse("오늘 1건 끝났어요.", ko).text).toBe("");
    expect(checkProse("10월 1일 기준 0건이에요.", ko).text).toBe("10월 1일 기준 0건이에요.");
    // An id's digits are not counts either.
    expect(proseNumbersOk("1 passport was flagged.", "• Passport: A00000001")).toBe(false);
    expect(proseNumbersOk("A00000001 was flagged.", "• Passport: A00000001")).toBe(true);
    expect(proseNumbersOk("HNG-2026-012 is verified.", "TEST STUDENT ONE (HNG-2026-012, portal uid 101)")).toBe(true);
    expect(proseNumbersOk("12 students are verified.", "TEST STUDENT ONE (HNG-2026-012, portal uid 101)")).toBe(false);
  });

  it("keeps at most two sentences and drops everything when every sentence fails", () => {
    expect(checkProse("One. Two. Three.", facts).text).toBe("One. Two.");
    expect(checkProse("We made 99 sales.", facts).text).toBe("");
  });

  it("gives the model the facts with their values", async () => {
    const { result } = await answer("how many consultancies were closed today?");
    const context = factsForModel(result, { now: NOW, timeZone: TZ });
    expect(context).toMatchObject({ intent: "consultancies_closed_today", as_of: "As of 17:35 (full picture)" });
    expect(JSON.stringify(context)).toContain("TEST CONSULTANT C");
  });
});

it("fixtures stay synthetic", () => {
  const all: HgRecord[] = [...records(), STUDENT_ONE];
  for (const r of all) expect(JSON.stringify(r)).not.toMatch(/@|\+880/);
});
