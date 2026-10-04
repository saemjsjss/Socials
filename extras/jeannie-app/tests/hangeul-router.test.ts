import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routeQuery, runOrchestratorToText } from "@/lib/agents/orchestrator";
import { classify, daySpan, isHangeulContextQuery, isHangeulStatusQuery, normalizeHngId, studentFrom } from "@/lib/hangeul/router";

const TODAY = "2026-09-30";
const CTX = { today: TODAY, now: new Date("2026-09-30T12:00:00Z"), timeZone: "Asia/Dhaka" };
const plan = (text: string) => classify(text, CTX);

beforeEach(() => {
  for (const name of ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "LLM_PROVIDER", "MOCK_MODE"]) vi.stubEnv(name, "");
  for (const name of ["SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"]) vi.stubEnv(name, "");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the owner's question", () => {
  it.each([
    "how many consultancies were closed today?",
    "How many consultancies were done today?",
    "How many consultancies today",
    "오늘 상담 몇 건 끝났어?",
  ])("%j → consultancies_closed_today for today, routed to the Hangeul agent", (text) => {
    expect(plan(text)).toEqual({ intent: "consultancies_closed_today", day: TODAY });
    expect(routeQuery({ text, hasImage: false }).agent).toBe("hangeul");
  });

  it("names another day when one is asked for", () => {
    expect(plan("how many consultancies were done yesterday?")).toEqual({ intent: "consultancies_closed_today", day: "2026-09-29" });
    expect(plan("how many consultancies this month?")).toEqual({ intent: "performance", period: "month", day: TODAY });
    // Last month is last month's window, not this month's.
    expect(plan("how many consultancies last month?")).toEqual({ intent: "performance", period: "month", day: "2026-08-31" });
    expect(plan("how many consultancies were done in August?")).toEqual({ intent: "performance", period: "month", day: "2026-08-31" });
  });

  it("a range of days is a range (the answer says the portal has no figure for it), never today's figures", () => {
    const week = { intent: "consultancies_closed_today", day: "2026-09-24", to: TODAY };
    expect(plan("how many consultancies were closed this week?")).toEqual(week);
    expect(plan("how many consultancies were closed in the last 7 days?")).toEqual(week);
    expect(plan("how many consultancies were closed last week?")).toEqual({ intent: "consultancies_closed_today", day: "2026-09-17", to: "2026-09-23" });
    expect(plan("consultant performance this week")).toEqual({ intent: "performance", period: "today", day: "2026-09-24", to: TODAY });
    expect(plan("any passport alerts this week?")).toEqual({ intent: "passport_alerts", from: "2026-09-24", to: TODAY });
    expect(plan("any passport alerts yesterday?")).toEqual({ intent: "passport_alerts", day: "2026-09-29" });
  });
});

describe("the owner's performance phrasings (Hangeul BOT's own, pack 05)", () => {
  const today = { intent: "performance", period: "today", day: TODAY };
  const month = { intent: "performance", period: "month", day: TODAY };
  it.each([
    ["this month's performance", month],
    ["This month's performance?", month],
    ["monthly performance", month],
    ["performence this month", month],
    ["this months performence", month],
    ["how did the consultants do this month?", month],
    ["who is the top performer this month", month],
    ["today's performance", today],
    ["what's today's performance?", today],
    ["performance today", today],
    ["perfomance today", today],
    ["performances today", today],
    // The rest of the bot's _PERFORMANCE_WORDS misspellings.
    ["performace today", today],
    ["perfromance this month", month],
    ["preformance today", today],
    ["perfomence this month", month],
    ["how did the team do today", today],
    ["how's the team doing?", today],
    ["performance", today],
    ["show me the performance", today],
    ["leaderboard", today],
    ["team activity", today],
    ["staff stats today", today],
    ["last month's performance", { intent: "performance", period: "month", day: "2026-08-31" }],
    ["consultant performance yesterday", { intent: "performance", period: "today", day: "2026-09-29" }],
  ])("%j → %j", (text, expected) => {
    expect(plan(text)).toEqual(expected);
    expect(isHangeulContextQuery(text)).toBe(true);
    expect(routeQuery({ text, hasImage: false }).agent).toBe("hangeul");
  });

  it.each([
    "performance of the stock market this month",
    "how is the team performance in the premier league this month",
    "server performance today",
    "today's performance of the website",
    "this month's performance review for my employee",
    "how is everyone doing?",
    "how did the team do at the hackathon",
    "team stats for the NBA",
    "outperform",
    "performing arts",
  ])("%j is someone else's performance", (text) => {
    expect(isHangeulContextQuery(text)).toBe(false);
    expect(plan(text)).toBeNull();
  });

  it("a subject that is someone else's stays ours when the agency's own word anchors it", () => {
    // FOREIGN ("football") would keep the leaderboard out; the word "consultancy" alone keeps it in.
    expect(plan("show the consultancy leaderboard like a football table")).toEqual(today);
    expect(plan("show the leaderboard like a football table")).toBeNull();
  });
});

describe("the spec's §9 questions", () => {
  it("Who is HNG-2026-12? → the student card (the portal zero-pads to three digits)", () => {
    expect(plan("Who is HNG-2026-12?")).toEqual({ intent: "student_card", student: { hngId: "HNG-2026-012" } });
    expect(routeQuery({ text: "Who is HNG-2026-12?", hasImage: false }).agent).toBe("hangeul");
    expect(normalizeHngId("2026", "7")).toBe("HNG-2026-007");
    expect(normalizeHngId("2026", "0012")).toBe("HNG-2026-012");
    expect(normalizeHngId("2026", "964")).toBe("HNG-2026-964");
  });

  it("How many payments were verified on 12 Sep?", () => {
    expect(plan("How many payments were verified on 12 Sep?")).toEqual({ intent: "verified_on_day", from: "2026-09-12", to: "2026-09-12" });
  });

  it("Any passport alerts today?", () => {
    expect(plan("Any passport alerts today?")).toEqual({ intent: "passport_alerts", day: TODAY });
    expect(plan("any passport issues?")).toEqual({ intent: "passport_alerts" });
  });

  it("What does <name>'s bank statement say about the opening balance? → a search of that student's pages", () => {
    expect(plan("What does Karim Uddin's bank statement say about the opening balance?")).toMatchObject({
      intent: "semantic",
      student: { name: "Karim Uddin" },
      kinds: expect.arrayContaining(["doc_page_text"]),
    });
    expect(plan("What's Karim's bank statement opening balance?")).toMatchObject({ intent: "semantic", student: { name: "Karim" } });
  });

  it("What changed since this morning? → the change log since 00:00 Dhaka", () => {
    expect(plan("What changed since this morning?")).toEqual({ intent: "changes_since", since: "2026-09-29T18:00:00.000Z", sinceLabel: "00:00" });
    expect(plan("anything new since 9:30?")).toEqual({ intent: "changes_since", since: "2026-09-30T03:30:00.000Z", sinceLabel: "09:30" });
    expect(plan("any changes in the last 3 hours")).toMatchObject({ intent: "changes_since", since: "2026-09-30T09:00:00.000Z" });
    expect(plan("anything changed in the last 3 hours?")).toMatchObject({ intent: "changes_since" });
    expect(plan("any updates since yesterday?")).toMatchObject({ intent: "changes_since", sinceLabel: "2026-09-29 00:00" });
    expect(plan("what changed since 9am on the portal?")).toMatchObject({ intent: "changes_since", sinceLabel: "09:00" });
  });
});

describe("every plan", () => {
  it.each([
    ["Hangeul daily report", { intent: "report", report: "brief" }],
    ["send me the daily brief", { intent: "report", report: "brief" }],
    ["show me the missing report", { intent: "report", report: "missing" }],
    ["document check report", { intent: "report", report: "document_check" }],
    ["consultant performance today", { intent: "performance", period: "today", day: TODAY }],
    ["consultant performance this month", { intent: "performance", period: "month", day: TODAY }],
    ["who is the top performer this month?", { intent: "performance", period: "month", day: TODAY }],
    ["how many files opened today?", { intent: "performance", period: "today", day: TODAY }],
    ["How many inquiries came in yesterday?", { intent: "inquiries_on_day", day: "2026-09-29" }],
    ["how many inquiries are still no answer today?", { intent: "inquiries_on_day", day: TODAY, status: "No Answer" }],
    ["Any pending payments?", { intent: "pending_payments" }],
    ["any window applications under review?", { intent: "window_review" }],
    ["which students failed the document check?", { intent: "doc_verdicts", verdict: "FAIL" }],
    ["run the cross-check", { intent: "doc_verdicts" }],
    ["any deadlines this week?", { intent: "calendar_window", from: TODAY, to: "2026-10-06" }],
    ["What's the missing information for student HNG-2026-12?", { intent: "missing_for_student", student: { hngId: "HNG-2026-012" } }],
    ["Show the documents of HNG-2026-913", { intent: "doc_verdicts", student: { hngId: "HNG-2026-913" } }],
    ["How many students do we have?", { intent: "dashboard" }],
    ["How many students applied today?", { intent: "students_applied", from: TODAY, to: TODAY }],
    ["Is the Hangeul portal up?", { intent: "data_status" }],
    ["when was the hangeul data last updated?", { intent: "data_status" }],
    // The same loose cues, when the agency is meant.
    ["what's our conversion today?", { intent: "performance", period: "today", day: TODAY }],
    ["conversion rate of the consultants this month", { intent: "performance", period: "month", day: TODAY }],
    ["how many consultations today?", { intent: "consultancies_closed_today", day: TODAY }],
    ["anything verified today?", { intent: "verified_on_day", from: TODAY, to: TODAY }],
    ["any passport problems?", { intent: "passport_alerts" }],
    ["top performers of our consultants today", { intent: "performance", period: "today", day: TODAY }],
    ["How many students are there?", { intent: "dashboard" }],
    ["application deadlines for Gachon University", { intent: "calendar_window", from: TODAY, to: "2026-11-29", where: "Gachon University" }],
    ["upcoming deadlines for MIT applications", { intent: "calendar_window", from: TODAY, to: "2026-11-29", where: "MIT" }],
    ["any deadlines for us this week?", { intent: "calendar_window", from: TODAY, to: "2026-10-06" }],
  ])("%j → %j", (text, expected) => {
    expect(plan(text)).toEqual(expected);
    expect(isHangeulContextQuery(text)).toBe(true);
  });

  it("a Hangeul question that fits no structured plan is a semantic search", () => {
    expect(plan("What's our attendance rate this week?")).toMatchObject({ intent: "semantic" });
  });
});

describe("days", () => {
  it.each([
    ["on 12 Sep", "2026-09-12"],
    ["on Sep 12th", "2026-09-12"],
    ["on 12 September 2025", "2025-09-12"],
    ["on 2026-09-12", "2026-09-12"],
    ["9월 12일", "2026-09-12"],
    ["yesterday", "2026-09-29"],
    ["today", TODAY],
    // A day more than a month ahead with no year is last year's.
    ["on 28 Dec", "2025-12-28"],
  ])("%j → %s", (text, day) => {
    expect(daySpan(text, TODAY)).toMatchObject({ from: day, to: day, single: true });
  });

  it("reads ranges and ignores words that only look like months", () => {
    expect(daySpan("this month", TODAY)).toEqual({ from: "2026-09-01", to: TODAY, single: false });
    expect(daySpan("last month", TODAY)).toEqual({ from: "2026-08-01", to: "2026-08-31", single: false });
    expect(daySpan("I have 10 decks of cards", TODAY)).toBeNull();
    expect(daySpan("3 mayors met", TODAY)).toBeNull();
  });
});

describe("students named in a question", () => {
  it.each([
    ["find student Rahim Uddin", { name: "Rahim Uddin" }],
    ["tell me about the student called karim", { name: "karim" }],
    ["student RAHIM UDDIN", { name: "RAHIM UDDIN" }],
    ["Show me Karim's documents", { name: "Karim" }],
    ["passport A00000001", { passport: "A00000001" }],
    ["uid 425", { uid: 425 }],
    ["what's the stage of student Karim?", { name: "Karim" }],
    ["open the student called Karim", { name: "Karim" }],
  ])("%j → %j", (text, student) => {
    expect(studentFrom(text)).toEqual(student);
  });

  it.each([
    "What are the student visa requirements for Korea?",
    "my friend's passport expired",
    "What's the country's visa policy?",
    "My booking reference is EK1234567",
    // What students have, not a student's name.
    "What are the Student Visa Requirements for Korea?",
    "check student visa requirements for Korea",
    "what about student visas?",
    "tell me about student life in Seoul",
    "tell me about student accommodation in Busan",
    "info about student loans",
    "find student discounts for trains",
    "How is the Student Union at Seoul National?",
  ])("%j names no student", (text) => {
    expect(studentFrom(text)).toBeNull();
    expect(isHangeulContextQuery(text)).toBe(false);
  });
});

describe("consultancy counts are the agency's", () => {
  it.each([
    "total consultancy fees",
    "what's the consultancy fee for a Korean university?",
    "number of consultancies in Dhaka",
    "how many consultancies are there in Bangladesh?",
    "how many consultations did the doctor do today",
  ])("%j is not a count of the agency's consultancies", (text) => {
    expect(isHangeulContextQuery(text)).toBe(false);
    expect(plan(text)).toBeNull();
  });

  it.each([
    "how many consultations did we do today",
    "how many consultancies did we do in Dhaka today?",
    "how many consultations were done today",
  ])("%j still is", (text) => {
    expect(plan(text)).toEqual({ intent: "consultancies_closed_today", day: TODAY });
  });
});

describe("whole-word rules keep everyday questions out", () => {
  it.each([
    // The old bridge's negatives: "hangeul" is also the Korean alphabet.
    "Teach me hangeul",
    "What is hangeul?",
    "Write a report about the history of hangeul",
    "한글로 보고서 써줘",
    "한글 배우는 법 알려줘",
    "한글날이 언제야?",
    "I'm bad at hangeul",
    "Where did hangeul come from?",
    "How do I write my name in hangeul?",
    "What was the attendance at the World Cup final?",
    "Do I have any pending payments on PayPal?",
    "Show me the report on climate change",
    "Is the Steam portal down?",
    "Is hangeul hard to pick up?",
    "Is hangeul easy to write down?",
    "What's today's report on the weather?",
    "우리 집 전기요금 미납",
    "국회의원 출석률",
    // New cues, same care: "across" is not a cross-check, "deadline" alone is not the agency's.
    "How far across is the bridge?",
    "What are the student visa requirements for Korea?",
    "Give me the latest briefing on Ukraine",
    "What's the deadline for US tax returns?",
    "What changed in React 19 since version 18?",
    "What consultant should I hire for SEO?",
    "How do I verify my email?",
    "Is my Instagram account verified today?",
    "How many students applied to Harvard?",
    "I have 10 decks of cards",
    "한국에 유학생 몇 명이야?",
    "여권 갱신 방법 알려줘",
    // The loose cues stay out when the subject is plainly someone else's (markets, sport, news, software).
    "What's the conversion rate of USD to BDT today?",
    "conversion rate euro to dollar today",
    "Any updates since yesterday on the Ukraine war?",
    "What's new since yesterday in AI?",
    "How many students are there at Harvard?",
    "Is this news verified today?",
    "verified accounts on X today",
    "How many consultations does a doctor do a day?",
    "top performers in the NBA this season",
    "best performers of the stock market today",
    "the leaderboard of the Masters",
    "How many files opened in Excel?",
    "any passport problems when travelling to Japan?",
  ])("%j is not a Hangeul data question", (text) => {
    expect(isHangeulContextQuery(text)).toBe(false);
    expect(plan(text)).toBeNull();
    expect(routeQuery({ text, hasImage: false }).agent).not.toBe("hangeul");
  });

  it.each([
    // The old bridge's positives still arrive.
    "Show me the Hangeul report",
    "hangeul status",
    "Is the Hangeul portal up?",
    "pull the admin report",
    "send me the daily report",
    "check hangeul",
    "한글 포털 상태 확인해줘",
    "한글 관리자 보고서 보여줘",
    "한글 학원 보고서",
    "어드민 현황 알려줘",
    "일일 보고서",
    "What's today's report?",
    "Send me today's report",
    "show today’s report",
    "Send me the report",
    "Is the admin portal down?",
    "Is the portal online?",
    "hangeul down now",
    "How many students enrolled at Hangeul today?",
    "Any pending payments at Hangeul?",
    "What's our attendance rate this week?",
    "How many enrollments this month at the academy?",
    "포털 상태 확인해줘",
    "오늘 출석률 어때?",
    "한글학원 재원생 몇 명이야?",
    "재원생 몇 명이야?",
    "학원 현황 알려줘",
    "학원비 미납 몇 건이야?",
  ])("%j routes to the Hangeul agent", (text) => {
    expect(isHangeulContextQuery(text)).toBe(true);
    expect(routeQuery({ text, hasImage: false }).agent).toBe("hangeul");
  });

  it("status wording is a data-status question; report wording is not", () => {
    for (const text of ["Is the Hangeul portal up?", "is hangeul up right now ?", "hangeul down now", "한글 포털 상태", "Is the admin portal down?"]) {
      expect(isHangeulStatusQuery(text)).toBe(true);
    }
    for (const text of ["Give me the Hangeul report on payment status", "Hangeul daily report: what's the enrollment status?", "학원 현황 알려줘"]) {
      expect(isHangeulStatusQuery(text)).toBe(false);
    }
  });

  it("an attached image goes to vision unless the text names the portal", () => {
    expect(routeQuery({ text: "how many consultancies were closed today?", hasImage: true }).agent).toBe("vision");
    expect(routeQuery({ text: "Summarize this daily report", hasImage: true }).agent).toBe("vision");
    expect(routeQuery({ text: "Show me the Hangeul report", hasImage: true }).agent).toBe("hangeul");
  });
});

describe("routing cost", () => {
  // Whitespace runs used to backtrack cubically: 2,000 spaces took about 4 s.
  /** `head`, then `filler` repeated to 20,000 characters. */
  const padded = (head: string, filler: string) => `${head}${filler.repeat(Math.ceil(20_000 / filler.length))}.`;
  const timed = async (run: () => unknown) => {
    const started = performance.now();
    await run();
    return performance.now() - started;
  };

  it.each([
    ["spaces", " "],
    ["newlines", "\n"],
    ["mixed whitespace", " \r\n\t"],
    ["words", "consultancy HNG-2026 today's across "],
  ])("stays linear on 20,000 characters of %s", async (_label, filler) => {
    for (const head of ["hangeul portal up", "how many consultancies were closed today?", "student Karim's bank statement"]) {
      const text = padded(head, filler);
      expect(await timed(() => isHangeulContextQuery(text))).toBeLessThan(50);
      expect(await timed(() => classify(text, CTX))).toBeLessThan(50);
      expect(await timed(() => routeQuery({ text, hasImage: false }))).toBeLessThan(50);
    }
  });

  it("answers an untrusted caller at once, without reading any data", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    let agent = "";
    let text = "";
    const took = await timed(async () => {
      ({ agent, text } = await runOrchestratorToText({ messages: [{ role: "user", content: padded("hangeul portal up", "\n") }] }, { trusted: false }));
    });
    expect(agent).toBe("hangeul");
    expect(text).toContain("access key");
    expect(took).toBeLessThan(50);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
