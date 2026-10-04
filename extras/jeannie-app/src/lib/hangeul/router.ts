// Hangeul question router: whole-word rules (like the pack's ask.classify) that
// map a question to a query plan. "Hangeul"/한글 alone is also the Korean
// alphabet, and "deadline", "verified" or "pending payments" are everyday
// words, so each intent needs its domain noun next to a qualifier.
//
// Every pattern runs on normalizeQuery() output (single spaces, capped length)
// and uses only bounded windows (.{0,N}) and bounded word runs, so matching
// stays linear in the input: routing a 20,000-character message takes well
// under 50 ms. Isomorphic (no Node APIs, no "ai" import).

import { addDays, firstOfMonth, isIsoDay, previousMonth, zonedTime } from "./days";
import type { Plan, ReportName, StudentQuery } from "./types";

/** A data question is short; nothing past this is routed (it also bounds the work). */
const MAX_ROUTED_CHARS = 4_000;
/** Raw input read before normalizing: room for whitespace runs that collapse to one space. */
const MAX_RAW_CHARS = 16_000;

/** One space between words, straight apostrophes, composed Hangul, at most MAX_ROUTED_CHARS. */
export function normalizeQuery(text: string): string {
  const raw = text.length > MAX_RAW_CHARS ? text.slice(0, MAX_RAW_CHARS) : text;
  const t = raw.normalize("NFC").replace(/[‘’ʼ`]/g, "'").replace(/\s+/g, " ").trim();
  return t.length > MAX_ROUTED_CHARS ? t.slice(0, MAX_ROUTED_CHARS) : t;
}

// ─── Legacy portal cues (the old bridge's routing, kept so the same phrasings still arrive) ──

// up/down only count as a verdict ("is the portal up?"), not as part of a phrasal
// verb ("hangeul, pull up the dashboard", "is hangeul hard to pick up?").
const UP_DOWN_EN =
  "(?<!\\b(?:pick|pull|look|set|sign|show|bring|call|type|write|draw|sum|follow|catch|keep|make|give|take|put|hang|mess|hand|slow|calm|fill|mix|clean|warm|speed) )" +
  "(?:up|down)(?= ?(?:$|[?!.,;:)]|or\\b|and running\\b|right now\\b|now\\b|at the moment\\b|again\\b))";

const LEGACY_EN: RegExp[] = [
  /\b(?:admin|daily) reports?\b/i,
  /\bhangeul(?:'s)? (?:(?:daily|admin|today'?s) )?(?:reports?|briefing|summary|status|dashboard|portal|admin|academy|institute|school|system|server|site|website|backend|metrics|stats|numbers|students|enrol{1,2}ments?|attendance|payments?|operations|data)\b/i,
  /\b(?:portal|admin|dashboard)\b.{0,40}\bhangeul\b|\bhangeul\b.{0,40}\b(?:portal|admin|dashboard)\b/i,
  /\b(?:report|status|numbers|metrics|stats|data) (?:from|of|for) (?:the )?hangeul\b/i,
  new RegExp(`\\bis (?:the )?hangeul\\b.{0,30}\\b(?:${UP_DOWN_EN}|(?:online|offline)\\b)`, "i"),
  new RegExp(`\\bhangeul(?: is)? (?:${UP_DOWN_EN}|(?:offline|unreachable)\\b)`, "i"),
  /\b(?:check|ping) (?:on )?(?:the )?hangeul\b/i,
  /\bhangeul\.com\b/i,
  /\b(?:what's|what is|send|show|give|get|pull|fetch|read) (?:me |us )?(?:in )?today'?s (?:daily |admin )?report\b(?! (?:on|about) )/i,
  // "Send me the report" on its own; "show me the report on climate change" is not ours.
  /\b(?:send|show|give|get|pull|fetch) (?:me |us )?the (?:daily )?report(?: for today| today)?[.!?]*$/i,
  // The portal is the admin portal even without the word hangeul ("is the admin portal down?").
  /\b(?:admin|the|our) portal\b.{0,20}\b(?:up|down|online|offline|status|reachable)\b/i,
];

// "at/from Hangeul" and academy metrics are ours only with academy context:
// "I'm bad at hangeul" and "the attendance at the World Cup final" are not.
const LEGACY_AT_HANGEUL = /\b(?:at|from) (?:the )?hangeul\b/i;
const LEGACY_ACADEMY_WORDS =
  /\b(?:students?|pupils|enrol{1,2}(?:ed|ing|ments?)?|attendance|payments?|fees|tuition|classes|lessons|teachers?|staff|revenue|enquir(?:y|ies)|inquir(?:y|ies)|registrations?|numbers|stats|metrics)\b/i;
const LEGACY_METRICS =
  /\b(?:enrol{1,2}(?:ments?|ed)|attendance|pending payments?|unpaid (?:fees|tuition)|outstanding (?:fees|payments?|tuition)|active students|topik registrations?)\b/i;
const LEGACY_OWNER = /\b(?:our|hangeul|academy|today's|this (?:week|month)'s)\b/i;

const LEGACY_KO: RegExp[] = [
  /한글 ?(?:포털|관리자|어드민|리포트|보고서|현황|시스템|서버|사이트|대시보드|데이터)/,
  /(?:관리자|어드민) ?(?:리포트|보고서|현황|페이지)/,
  /(?:일일|데일리) ?(?:리포트|보고서|브리핑)/,
  /포털 ?(?:상태|현황|접속)/,
  /학원 ?(?:보고서|리포트|현황|상태|관리|재원생|출석|미납|수강생)/,
  /재원생/,
  // 출석률 and 미납 are also used for parliament attendance or unpaid taxes, so they need academy context.
  /(?:오늘|우리|학원|수업|이번 ?(?:주|달)).{0,12}(?:출석률|출석 ?현황)/,
  /미납 ?(?:건|학생|원생)|(?:수강료|학원비|원비) ?미납|(?:오늘|학원).{0,12}미납/,
];

function legacyCue(t: string): boolean {
  if (LEGACY_EN.some((re) => re.test(t)) || LEGACY_KO.some((re) => re.test(t))) return true;
  if (LEGACY_AT_HANGEUL.test(t) && LEGACY_ACADEMY_WORDS.test(t)) return true;
  return LEGACY_METRICS.test(t) && LEGACY_OWNER.test(t);
}

// A report request that mentions a status word ("the report on payment status",
// "수강생 출석 상태") still wants the report, not a health check.
const REPORT_WORDS =
  /\b(?:reports?|briefing|summary|metrics|stats|numbers|students|enrol{1,2}(?:ed|ments?)|attendance|payments?|enquir(?:y|ies)|registrations?)\b|보고서|리포트|현황|통계|재원생|출석|미납|수강생/i;
const SYSTEM_EN = "(?:hangeul|portal|server|site|website|system|backend|dashboard)";
const STATE_EN = `(?:(?:status|online|offline|reachable|unreachable|uptime|downtime|health|healthy|alive)\\b|${UP_DOWN_EN})`;
const STATUS_CUES: RegExp[] = [
  new RegExp(`\\b${SYSTEM_EN}\\b.{0,24}\\b${STATE_EN}`, "i"),
  new RegExp(`\\b(?:status|uptime|health|ping|reachability)\\b.{0,16}\\b${SYSTEM_EN}\\b`, "i"),
  /(?:포털|서버|사이트|시스템|홈페이지|대시보드|관리자 ?페이지|한글).{0,8}(?:상태|접속|정상|다운|작동|먹통|살아)/,
  // The data itself: "when was the Hangeul data last updated?", "is the bot's data fresh?"
  /\b(?:hangeul|the bot|bot's|data|portal)\b.{0,30}\b(?:last (?:synced|sync|run|updated|update|read)|up to date|fresh)\b/i,
  /\b(?:when|how recently) (?:was|did|were) (?:the )?(?:hangeul |portal |bot'?s? )?data\b/i,
];

/** Health-check wording about the portal or the data ("is the portal up?", "한글 포털 상태") rather than a data question. */
export function isHangeulStatusQuery(text: string): boolean {
  const t = normalizeQuery(text);
  if (REPORT_WORDS.test(t)) return false;
  return STATUS_CUES.some((re) => re.test(t));
}

// ─── Domain cues ────────────────────────────────────────────────────────────

/** Someone else's money or accounts: "pending payments on PayPal", "verified on Instagram". */
const NOT_OURS =
  /\b(?:paypal|stripe|venmo|amazon|ebay|twitter|instagram|facebook|tiktok|youtube|linkedin|gmail|netflix|spotify|uber|my (?:account|email|phone|bills?|rent|loan|card|bank|tax(?:es)?))\b|\bdo i (?:have|owe)\b/i;

/**
 * Plainly someone else's subject: markets, sport, news, software. The loose cues
 * ("conversion today", "top performers", "any updates since yesterday",
 * "how many students are there") are not ours next to one of these, unless an
 * anchor below says the agency is meant.
 */
const FOREIGN =
  /\b(?:exchange rates?|currenc(?:y|ies)|usd|eur|euros?|dollars?|pounds? sterling|yen|stocks?|stock market|shares|crypto|bitcoin|nba|nfl|fifa|ipl|football|cricket|soccer|golf|tennis|chess|the masters|tournaments?|premier league|champions league|world cup|olympics|games?|gaming|players?|excel|google docs?|spreadsheet|windows|iphone|android|news|war|election|weather|traffic|react|javascript|python)\b/i;
/** Words that only the agency's data uses: they keep a question ours even next to a FOREIGN word. */
const ANCHOR =
  /\bhangeul\b|\bportal\b|\bHNG[- ]?\d|\bconsultants?\b|\bconsultanc(?:y|ies)\b|\binquir(?:y|ies)\b|\benquir(?:y|ies)\b|\bthe bot\b|\bour (?:agency|office|students|consultants|team|staff|data)\b|한글|포털|상담/i;
/**
 * "Any updates since yesterday on the Ukraine war?", "what's new since yesterday in AI?":
 * a change question about a named topic is not about the data. Time phrases
 * ("in the last 3 hours") and the data's own nouns do not count as a topic.
 */
/** A traveller's passport, not the watcher's: "any passport problems when travelling to Japan?" */
const TRAVEL = /\b(?:travel(?:l?ing|l?ed)?|trips?|flights?|airports?|visas?|embassy|renew(?:al|ing)?|lost|stolen|expired?|immigration|customs|border)\b/i;
const CHANGE_TOPIC =
  /\b(?:on|about|in|regarding|with|for|to|of|from|at) (?:the )?(?!(?:the|last|past|morning|afternoon|evening|today|yesterday|this|that|those|these|portal|data|records?|hangeul|bot|office|agency|system|dashboard|students?|payments?|consultations?|consultancies|inquiries|passports?|documents?|docs|files?|our|us|we|it|here|there)\b)[a-z]/i;

const HNG_ID = /\bHNG[- ]?(\d{4})[- ]?(\d{1,4})\b/i;
const UID = /\b(?:portal )?uid[:#]? ?(\d{1,7})\b/i;
const PASSPORT_NO = /\b([A-Z]{1,2}\d{7,8})\b/i;
/** A passport-shaped token counts only next to a passport or student word ("EK1234567" may be a booking). */
const PASSPORT_CONTEXT = /\bpassports?\b|\bstudents?\b|\bapplicants?\b|여권|학생/i;
const NAME_WORDS = "([a-z][a-z.-]*(?: [a-z][a-z.-]*){0,3})";
// "Find student Rahim", "tell me about the student called Karim": a verb first, so "student visa rules" is not a name.
const STUDENT_NAMED = new RegExp(
  `\\b(?:find|show|open|pull up|look up|check|about|details (?:of|for)|info (?:on|about|for)|profile of|who is|lookup) (?:the |our |a )?(?:student|applicant)(?: named| called)? ${NAME_WORDS}`,
  "i",
);
const STUDENT_CALLED = new RegExp(`\\b(?:student|applicant) (?:named|called) ${NAME_WORDS}`, "i");
// The portal writes names in capitals ("student RAHIM UDDIN"); a capitalised name after "student" is one too.
const STUDENT_CAPS = /\b[Ss]tudent ([A-Z][A-Za-z.-]+(?: [A-Z][A-Za-z.-]+){0,3})\b/;
// "Karim's bank statement": the name must start a word (not the "s" of "What's").
const POSSESSIVE = new RegExp(
  `(?<![A-Za-z'])${NAME_WORDS}'s (?:bank (?:statement|solvency)|passport|nid|birth certificate|documents?|docs|files?|stage|progress|profile|photo|transcripts?|affidavit|certificates?|verdicts?|document check|ielts|ssc|hsc|hng id|payment (?:status|details))\\b`,
  "i",
);
const KO_STUDENT = /학생 ?([A-Za-z][A-Za-z.-]*(?: [A-Za-z][A-Za-z.-]*){0,3})/;

const NAME_STOP = new Set(
  (
    "what what's does do did is was are were show tell me about the a an for of find open pull get give check see look up please " +
    "can could would will you i we our my his her their this that these those who whose which where when how and or with " +
    "from to in on at by student students applicant file files document documents docs passport payment payments stage " +
    "progress status card profile details info say says said named called has have had any all today yesterday now s"
  ).split(" "),
);
const NOT_A_NAME = new Set(
  (
    "friend mom mother dad father wife husband son daughter brother sister boss world people children men women someone " +
    "somebody everyone anyone nobody it one user customer client company country city state nation school university " +
    "college bank government team agency office hangeul portal consultant consultants bot jeannie tomorrow last next " +
    "week month year " +
    // "Student visa requirements", "student life in Seoul", "student loans": what students have, not a student's name.
    "visa visas requirement requirements rule rules policy policies life lives loan loans debt union unions discount " +
    "discounts deal deals offer offers accommodation accommodations housing dorm dorms dormitory dormitories hostel " +
    "hostels residence residences card cards id ids account accounts fee fees tuition cost costs prices budget " +
    "scholarship scholarships aid finance insurance health job jobs work permit permits exchange exchanges " +
    "travel ticket tickets pass passes railcard transport council club clubs society societies association center " +
    "centre services service support counselling counseling ambassador ambassadors experience experiences culture " +
    "rankings population numbers statistics"
  ).split(" "),
);

function cleanName(raw: string): string | null {
  const words = raw.split(" ").filter(Boolean);
  let start = 0;
  while (start < words.length && NAME_STOP.has(words[start].toLowerCase())) start++;
  let end = start;
  while (end < words.length && !NAME_STOP.has(words[end].toLowerCase())) end++;
  const name = words.slice(start, end);
  if (name.length === 0 || name.some((w) => NOT_A_NAME.has(w.toLowerCase()))) return null;
  const joined = name.join(" ").replace(/[.-]+$/, "");
  return joined.replace(/[^a-z]/gi, "").length >= 3 ? joined : null;
}

/**
 * A capitalised run after "Student" is a name only when it is shaped like one:
 * in capitals as the portal writes names ("student RAHIM UDDIN"), or Title Case
 * that does not go on to a place ("What are the Student Visa Requirements for
 * Korea?", "the Student Union at Seoul National" are things, not people).
 */
function capsName(t: string): string | null {
  const m = STUDENT_CAPS.exec(t);
  if (!m) return null;
  const words = m[1].split(" ");
  const shouting = words.every((w) => w.replace(/[^A-Za-z]/g, "") === w.replace(/[^A-Za-z]/g, "").toUpperCase());
  const after = t.slice(m.index + m[0].length);
  if (!shouting && words.length > 1 && /^ (?:for|at|in|of|on|from|near|to) /i.test(after)) return null;
  return cleanName(m[1]);
}

/** HNG-2026-12 → HNG-2026-012 (the portal zero-pads to three digits). */
export function normalizeHngId(year: string, number: string): string {
  return `HNG-${year}-${number.replace(/^0+(?=\d)/, "").padStart(3, "0")}`;
}

/** The student a question names, if any: HNG id, portal uid, passport number (with context) or a name. */
export function studentFrom(t: string): StudentQuery | null {
  const hng = HNG_ID.exec(t);
  if (hng) return { hngId: normalizeHngId(hng[1], hng[2]) };
  const uid = UID.exec(t);
  if (uid) return { uid: Number(uid[1]) };
  const passport = PASSPORT_NO.exec(t);
  if (passport && PASSPORT_CONTEXT.test(t)) return { passport: passport[1].toUpperCase() };
  for (const re of [STUDENT_NAMED, STUDENT_CALLED, STUDENT_CAPS, POSSESSIVE, KO_STUDENT]) {
    let name: string | null;
    if (re === STUDENT_CAPS) name = capsName(t);
    else {
      const m = re.exec(t);
      name = m ? cleanName(m[1]) : null;
    }
    if (name) return { name };
  }
  return null;
}

/**
 * The performance words, with the owner's own spellings that Hangeul BOT
 * accepts too (ask._PERFORMANCE_WORDS: "performence", "perfomance",
 * "performances"). "Outperform" and "performing arts" are not among them.
 */
const PERF = "(?:perform[ae]nces?|perfom[ae]nces?|performaces?|perfromances?|preformances?)";
/** A time phrase that may close a short performance question ("how did the team do today?"). */
const PERF_WHEN = "(?: (?:today|yesterday|this (?:week|month)|last (?:week|month)|so far))?[?.!]*$";
/** Someone else's performance: a machine, a market, a show, an employee's review. Out unless the agency is named. */
const PERF_OTHER = new RegExp(
  `\\b(?:markets?|portfolio|funds?|index|indices|nasdaq|s&p|dow|nifty|sensex|servers?|websites?|site|apps?|laptops?|computers?|pc|gpu|cpu|phones?|cars?|engines?|battery|database|queries|code|network|wifi|internet|movies?|films?|actors?|actress|bands?|concerts?|singers?|songs?|albums?|athletes?|economy|gdp|compan(?:y|ies)|employees?|students?)\\b|\\b${PERF} (?:reviews?|appraisals?|evaluations?|bonus(?:es)?|tips|issues?|problems?|improvements?|tuning|tests?|testing|anxiety)\\b`,
  "i",
);
/**
 * A count of consultancies is the agency's, not a fee, a doctor's, or how many
 * consultancy firms a city has ("total consultancy fees", "how many consultations
 * did the doctor do today", "how many consultancies are there in Bangladesh?").
 */
const CONSULT_MONEY = /\b(?:fees?|costs?|prices?|pricing|charges?|rates?|salar(?:y|ies)|earn(?:ed|ings)?|revenue|budget)\b/i;
const MONTH_NAMES = "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?";
const CONSULT_ELSEWHERE = new RegExp(
  `\\b(?:are there|is there|exist|near me|firms?|compan(?:y|ies)|agencies|businesses|doctors?|physicians?|lawyers?|dentists?|therapists?|clinics?|hospitals?|patients?|nurses?|vets?)\\b|\\bin (?!(?:the|our|this|last|total|all|a|an|today|yesterday|${MONTH_NAMES})\\b)[a-z]{3,}`,
  "i",
);
/** The agency itself, named: keeps a consultancy count ours despite CONSULT_ELSEWHERE ("how many consultancies did we do in Dhaka today?"). */
const CONSULT_OURS = /\b(?:hangeul|portal|HNG|our|we|us|the bot|consultants?|counsell?ors?|staff|team)\b|한글|포털/i;

const DOC_WORDS =
  /\b(?:doc(?:ument)?s?|verdicts?|bank (?:statement|solvency)|birth certificate|nid|affidavit|transcripts?|certificates?|photo|ocr|page|statement|says?|mentions?|written|balance)\b|서류|문서|통장|잔고|증명서/i;
const FREE_TEXT_ASK = /\b(?:what does|what do|does (?:it|the)|say|says|said|mention|mentions|written|balance|how much)\b|뭐라고|잔고|얼마/i;

const CUES = {
  inquiries: [
    /\b(?:inquir(?:y|ies)|enquir(?:y|ies))\b.{0,40}\b(?:received|came in|come in|consulted|answered|so far)\b/i,
    /\b(?:inquiries|enquiries) (?:today|yesterday|this (?:week|month)|on \d{1,2})\b/i,
    /\b(?:how many|any|new|list|show|today'?s|yesterday'?s) (?:new )?(?:inquir(?:y|ies)|enquir(?:y|ies))\b/i,
    /\bconsultation requests?\b|\brequests? for (?:a )?consultation\b/i,
    /\b(?:new )?leads? (?:today|yesterday|received|came in)\b/i,
    /(?:상담 ?)?(?:문의|신청|요청).{0,12}(?:몇|오늘|어제|들어|접수|받|현황|목록)|(?:오늘|어제|이번 ?주).{0,12}(?:문의|상담 ?신청|상담 ?요청)/,
  ],
  consultancyDone: [
    /\bconsultanc(?:y|ies)\b.{0,40}\b(?:closed|done|completed|finished|made|conducted|held|handled|today|yesterday|so far)\b/i,
    /\b(?:how many|number of|count of|total) consultanc(?:y|ies)\b/i,
    // "Consultations" is also a doctor's: it needs a day or the agency ("how many consultations today?").
    /\b(?:how many|number of|count of|total) consultations?\b.{0,30}\b(?:today|yesterday|this (?:week|month)|so far|we|our|done|closed|completed|finished)\b/i,
    /\b(?:closed|done|completed|finished|conducted|held) (?:consultanc(?:y|ies)|consultations)\b/i,
    /\bconsultations? (?:were |was |have been |got )?(?:closed|done|completed|finished|conducted|held)\b/i,
    /\b(?:how many|number of) (?:people|clients|students|leads) (?:were |got |have been )?consulted\b/i,
    /상담.{0,12}(?:완료|끝|마감|종료|몇 ?건|했|진행)|컨설팅.{0,12}(?:완료|몇 ?건|끝)/,
  ],
  performance: [
    new RegExp(`\\b(?:consultants?'?s?|staff|team|counsell?ors?) (?:${PERF}|ranking|rankings|scores?|leaderboard)\\b`, "i"),
    new RegExp(`\\b${PERF} (?:of|for) (?:the |our |each )?(?:consultants?|staff|team|counsell?ors?)\\b`, "i"),
    new RegExp(`\\b${PERF} (?:page|board|report|today|this months?|so far|yesterday|monthly|mtd|this week|last week|last month)\\b`, "i"),
    // The owner writes the period first ("this month's performance", "this months performence", "today's performance").
    new RegExp(`\\b(?:this month'?s|this months|last month'?s|today'?s|yesterday'?s|this week'?s|last week'?s|monthly|daily|month'?s) ${PERF}\\b`, "i"),
    // The word on its own, or asked for plainly ("performance", "show me the performance").
    new RegExp(`^(?:(?:please )?(?:show|give|send|get|check) (?:me |us )?)?(?:the |our )?${PERF}(?: (?:page|board|report))?[?.!]*$`, "i"),
    // "How did the team do today?", "how did the consultants do this month?" (the bot's own phrasings).
    new RegExp(
      `\\bhow(?:'s| (?:did|does|do|has|have|is|are|was|were)) (?:the |our |my )?(?:whole )?(?:team|staff|counsell?ors?|consultants?) (?:do|done|doing|did|perform(?:ed|ing)?|go|going|gone)${PERF_WHEN}`,
      "i",
    ),
    new RegExp(`\\b(?:team|staff)(?:'s)? (?:activity|stats|statistics|scores?|results?)${PERF_WHEN}`, "i"),
    // "Top performers" and "leaderboard" are the portal's words, but also sport's and the market's (FOREIGN).
    /\bleaderboard\b|\btop performers?\b|\b(?:top|best) consultants?\b|\bbest performers?\b/i,
    // "How many files opened in Excel?" is not ours: files and docs need a day.
    /\bhow many files? (?:were |have been |got )?opened\b.{0,20}\b(?:today|yesterday|this (?:week|month)|so far)\b|\bfiles? opened (?:today|this month|yesterday|so far)\b/i,
    /\bhow many docs? (?:are |were |got )?ready\b.{0,20}\b(?:today|yesterday|this (?:week|month)|so far)\b|\bdocs? ready (?:today|this month|so far)\b/i,
    // Conversion is the file-open rate: "our conversion today", "conversion of the consultants" (not a currency's).
    /\bour conversion\b|\bconversion(?: rate)?\b.{0,30}\b(?:consultants?|file open|files? opened|leads?|inquir(?:y|ies))\b|\bconversion \(file open\)/i,
    /\bwhich consultants?\b.{0,30}\b(?:most|best|top|today|this month)\b/i,
    /\b(?:which|what) consultants? (?:did|has|had|made|closed|opened|handled)\b/i,
    /\bconsultants?\b.{0,30}\b(?:ranked|ranking|scores?|leaderboard)\b/i,
    /(?:상담사|컨설턴트|직원).{0,8}(?:실적|성과|순위|점수|랭킹)|(?:실적|성과).{0,8}(?:오늘|이번 ?달|이달)|(?:오늘|이번 ?달|이달).{0,8}(?:실적|성과)/,
  ],
  verified: [
    /\b(?:payments?|students?|fees?|amounts?|money)\b.{0,30}\bverified\b/i,
    // "Is this news verified today?" is not ours: a bare "verified" needs a payment or a student.
    /\bverified\b.{0,30}\b(?:payments?|students?|fees?)\b/i,
    /\b(?:anything|anyone|anybody|any) (?:got |been )?verified (?:today|yesterday|this (?:week|month)|so far)\b/i,
    /\bpayment verifications?\b|\bverifications?\b.{0,30}\b(?:today|yesterday|on \d{1,2}|this (?:week|month)|last month|how many|list)\b/i,
    /\bhow many (?:payment )?verifications?\b|\bwho verified\b|\bhow many (?:were |got )?verified\b/i,
    /\b(?:payments?|money|fees?) (?:were |was )?(?:received|collected|confirmed)\b.{0,30}\b(?:today|yesterday|on \d{1,2}|this (?:week|month))\b/i,
    /(?:입금|결제|납부|수납).{0,6}(?:확인|검증|인증)|검증.{0,8}(?:몇|된|완료|명|건)|(?:확인|검증)된 ?(?:결제|입금|학생)/,
  ],
  pending: [
    /\b(?:pending|unpaid|outstanding) payments?\b|\bpayments? (?:still )?(?:pending|outstanding|unpaid)\b|\bpending (?:fees|dues)\b/i,
    /미납 ?(?:건|학생|원생)|(?:수강료|학원비|원비) ?미납|(?:오늘|학원).{0,12}미납|(?:결제|입금) ?대기/,
  ],
  window: [
    /\bwindow applications?\b|\bapplications? (?:are |is |still )?under review\b|\bunder review\b.{0,20}\bapplications?\b/i,
    /윈도우 ?(?:신청|지원)|심사 ?중인? ?(?:지원|신청)/,
  ],
  passport: [
    /\bpassport (?:alerts?|scans?|watcher|discrepanc(?:y|ies)|mismatch(?:es)?|typos?|audits?)\b/i,
    /\bmrz\b|\bcheck[_ ]by[_ ]eye\b/i,
    /여권.{0,6}(?:알림|경고|문제|이상|검사|불일치|오류|점검)/,
  ],
  /** Everyday passport words ("passport problems when travelling"): ours only away from travel. */
  passportLoose: [
    /\bpassport (?:problems?|checks?|errors?|warnings?)\b/i,
    /\bpassport issues?\b(?! date)/i,
    /\b(?:alerts?|issues?|problems?|discrepanc(?:y|ies)) (?:with|in|on) (?:the |any )?passports?\b/i,
  ],
  docs: [
    /\bdoc(?:ument)?s? (?:checks?|checking|verdicts?|results?|review|verification)\b/i,
    /\bdocument check(?:ing)?\b|\bfield checks?\b|\bcross-?checks?\b/i,
    /\b(?:failed|flagged|missing|rejected|incomplete) (?:doc(?:ument)?s?|verdicts?)\b/i,
    /\bdoc(?:ument)?s? (?:that |which )?(?:failed|were flagged|got flagged|are missing)\b/i,
    /(?:서류|문서).{0,6}(?:검사|검토|판정|결과|불합격)/,
  ],
  missing: [
    /\bmissing (?:info(?:rmation)?|fields?|data|details)\b|\bincomplete (?:profiles?|students?|forms?)\b/i,
    /\bwhat(?:'s| is) missing\b/i,
    /누락|빠진 ?(?:정보|항목)|미기재|미입력/,
  ],
  calendar: [
    /\bapplication (?:periods?|windows?|deadlines?)\b|\bdhl\b/i,
    /\b(?:upcoming|next|coming|any|our|university|application|intake|portal) deadlines?\b/i,
    /\bdeadlines? (?:today|tomorrow|this week|this month|coming up|soon|next week)\b/i,
    /\b(?:on the|our|agency|portal|hangeul) calendar\b|\bcalendar (?:items?|events?|today|this week|tomorrow)\b/i,
    /\bwhat'?s due\b.{0,20}\b(?:today|tomorrow|this week)\b/i,
    /(?:지원|접수|원서|대학).{0,6}(?:마감|기간)|마감.{0,6}(?:일정|언제|다가|이번 ?주|오늘|내일)|DHL/,
  ],
  changes: [
    /\b(?:what(?:'s| has| have)? (?:changed|been updated|updated|new)|any (?:changes|updates)|anything (?:new|changed)|changes|updates)\b.{0,24}\b(?:since|in the (?:last|past)|over the (?:last|past))\b/i,
    /\bchanged since\b/i,
    /(?:아침|오늘|어제|최근|지난).{0,12}(?:바뀐|변경|달라진|새로 ?(?:들어온|생긴)|업데이트)/,
  ],
  report: [
    /\b(?:daily|today'?s|evening|hangeul) brief(?:ing)?\b/i,
    /일일 ?(?:리포트|보고서|브리핑)/,
  ],
  dashboard: [
    // "How many students are there at Harvard?" is not ours: no place may follow.
    /\bhow many students (?:do we have|are there|in total|we have|on the portal|in the system|are registered|have we got)\b(?! (?:at|in|of|on|from|across) (?!(?:the )?(?:portal|system|agency|office|total)\b))/i,
    /\b(?:at a glance|needs attention|application pipeline|admissions flow|top universities|applications by program)\b/i,
    /\b(?:hangeul|portal|agency) dashboard\b|\bdashboard (?:numbers|figures|summary)\b/i,
    /재원생|(?:우리|학원|포털|한글).{0,10}(?:학생|수강생).{0,6}(?:몇 ?명|총|전체)/,
  ],
  applied: [
    /\b(?:students?|applicants?) (?:have |has )?(?:applied|registered|signed up|joined)\b/i,
    /\b(?:new|fresh) (?:students?|applicants?|applications|registrations)\b/i,
    /\bhow many (?:new )?(?:applications|registrations)\b/i,
    /(?:신규|새) ?(?:학생|지원자|등록)|(?:등록|지원)한 ?학생/,
  ],
} as const;

/** "our"-style context that makes an everyday phrase ours ("students applied today", "applications this month"). */
const OURS_OR_WHEN =
  /\b(?:today|yesterday|this (?:week|month)|last (?:week|month)|on \d{1,2}|our|we|hangeul|portal|agency|so far)\b|오늘|어제|이번 ?(?:주|달)|지난 ?달/i;

const any = (res: readonly RegExp[], t: string) => res.some((re) => re.test(t));

// ─── Days ───────────────────────────────────────────────────────────────────

const MONTH_INDEX: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
};
// Only real month words ("10 decks" is not 10 Dec).
const MONTH_WORD =
  "(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\\.?";
const DAY_MONTH_BODY = `(\\d{1,2})(?:st|nd|rd|th)?(?: of)?[ -]${MONTH_WORD}(?:,? (\\d{4}))?(?![a-z])`;
const DAY_MONTH = new RegExp(`\\b${DAY_MONTH_BODY}`, "i");
const MONTH_DAY = new RegExp(`\\b${MONTH_WORD} (\\d{1,2})(?:st|nd|rd|th)?\\b(?:,? (\\d{4}))?`, "i");
const SINCE_DATE = new RegExp(`\\bsince (?:the )?${DAY_MONTH_BODY}`, "i");

function monthNumber(word: string): number {
  return MONTH_INDEX[word.slice(0, 3).toLowerCase()];
}
const ISO_DAY_IN_TEXT = /\b(\d{4})-(\d{2})-(\d{2})\b/;
const KO_MONTH_DAY = /(\d{1,2}) ?월 ?(\d{1,2}) ?일/;

export interface DaySpan {
  from: string;
  to: string;
  /** A single named day (today, yesterday, 12 Sep), not a range. */
  single: boolean;
  /** Forward-looking wording (tomorrow, next week, upcoming). */
  ahead?: boolean;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** A day named without a year: this year, unless that is more than a month ahead (then last year). */
function resolveDay(today: string, month: number, day: number, year?: string): string | null {
  const y = year ? Number(year) : Number(today.slice(0, 4));
  let iso = `${y}-${pad2(month)}-${pad2(day)}`;
  if (!isIsoDay(iso)) return null;
  if (!year && iso > addDays(today, 31)) iso = `${y - 1}-${pad2(month)}-${pad2(day)}`;
  return isIsoDay(iso) ? iso : null;
}

/** The day or range a question names, relative to `today` (business day). */
export function daySpan(t: string, today: string): DaySpan | null {
  const iso = ISO_DAY_IN_TEXT.exec(t);
  if (iso && isIsoDay(`${iso[1]}-${iso[2]}-${iso[3]}`)) {
    const d = `${iso[1]}-${iso[2]}-${iso[3]}`;
    return { from: d, to: d, single: true };
  }
  const dm = DAY_MONTH.exec(t);
  if (dm) {
    const d = resolveDay(today, monthNumber(dm[2]), Number(dm[1]), dm[3]);
    if (d) return { from: d, to: d, single: true };
  }
  const md = MONTH_DAY.exec(t);
  if (md) {
    const d = resolveDay(today, monthNumber(md[1]), Number(md[2]), md[3]);
    if (d) return { from: d, to: d, single: true };
  }
  const ko = KO_MONTH_DAY.exec(t);
  if (ko) {
    const d = resolveDay(today, Number(ko[1]), Number(ko[2]));
    if (d) return { from: d, to: d, single: true };
  }
  if (/\bday before yesterday\b|그저께|그제|엊그제/i.test(t)) {
    const d = addDays(today, -2);
    return { from: d, to: d, single: true };
  }
  if (/\byesterday\b|어제|어저께/i.test(t)) {
    const d = addDays(today, -1);
    return { from: d, to: d, single: true };
  }
  if (/\btomorrow\b|내일/i.test(t)) {
    const d = addDays(today, 1);
    return { from: d, to: d, single: true, ahead: true };
  }
  const lastN = /\b(?:last|past) (\d{1,3}) days\b|최근 ?(\d{1,3}) ?일/i.exec(t);
  if (lastN) {
    const n = Math.max(1, Math.min(366, Number(lastN[1] ?? lastN[2])));
    return { from: addDays(today, -(n - 1)), to: today, single: false };
  }
  if (/\bnext week\b|다음 ?주/i.test(t)) return { from: addDays(today, 1), to: addDays(today, 7), single: false, ahead: true };
  if (/\bthis week\b|이번 ?주/i.test(t)) return { from: addDays(today, -6), to: today, single: false };
  if (/\blast week\b|지난 ?주/i.test(t)) return { from: addDays(today, -13), to: addDays(today, -7), single: false };
  if (/\blast month\b|지난 ?달|저번 ?달/i.test(t)) return { ...previousMonth(today), single: false };
  if (/\bthis month\b|이번 ?달|이달/i.test(t)) return { from: firstOfMonth(today), to: today, single: false };
  if (/\btoday\b|\btonight\b|\bthis (?:morning|afternoon|evening)\b|\bso far\b|오늘|금일/i.test(t)) {
    return { from: today, to: today, single: true };
  }
  return null;
}

/** "since this morning" / "since 9:30" / "in the last 3 hours" → ISO instant, with its label. */
export function sinceFrom(t: string, today: string, now: Date, timeZone: string): { since: string; label: string } {
  const hours = /\b(?:in|over) the (?:last|past) (\d{1,3}) hours?\b|\b(\d{1,3}) hours? ago\b|최근 ?(\d{1,3}) ?시간/i.exec(t);
  if (hours) {
    const n = Number(hours[1] ?? hours[2] ?? hours[3]);
    return { since: new Date(now.getTime() - n * 3_600_000).toISOString(), label: `last ${n} h` };
  }
  if (/\b(?:in|over) the (?:last|past) hour\b|\ban hour ago\b/i.test(t)) {
    return { since: new Date(now.getTime() - 3_600_000).toISOString(), label: "last 1 h" };
  }
  const at = /\bsince (\d{1,2})(?::(\d{2}))? ?([ap])?\.?m?\.?(?![\d:])/i.exec(t);
  if (at && !DAY_MONTH.test(t)) {
    let hour = Number(at[1]);
    const minute = Number(at[2] ?? 0);
    if (at[3]?.toLowerCase() === "p" && hour < 12) hour += 12;
    if (at[3]?.toLowerCase() === "a" && hour === 12) hour = 0;
    if (hour <= 23 && minute <= 59) {
      let day = today;
      let since = zonedTime(day, timeZone, hour, minute);
      if (since > now.toISOString()) {
        day = addDays(today, -1);
        since = zonedTime(day, timeZone, hour, minute);
      }
      return { since, label: `${day === today ? "" : "yesterday "}${pad2(hour)}:${pad2(minute)}` };
    }
  }
  if (/\blast night\b|어젯밤/i.test(t)) {
    return { since: zonedTime(addDays(today, -1), timeZone, 18, 0), label: "yesterday 18:00" };
  }
  const span = daySpan(t, today);
  if (span && span.from < today) return { since: zonedTime(span.from, timeZone), label: `${span.from} 00:00` };
  return { since: zonedTime(today, timeZone), label: "00:00" };
}

// ─── Classification ─────────────────────────────────────────────────────────

export interface RouterContext {
  /** Today's business day, "YYYY-MM-DD" (Asia/Dhaka). */
  today: string;
  now: Date;
  timeZone: string;
}

type Intent =
  | "student"
  | "inquiries"
  | "consultancyDone"
  | "performance"
  | "verified"
  | "pending"
  | "window"
  | "passport"
  | "docs"
  | "missing"
  | "calendar"
  | "changes"
  | "report"
  | "dashboard"
  | "applied"
  | "status"
  | "legacy";

function namedReport(t: string): ReportName | null {
  if (/\bmissing(?:[- ]info(?:rmation)?)? reports?\b|누락 ?(?:보고서|리포트)/i.test(t)) return "missing";
  if (/\bdocument[- ]check (?:reports?|summary)\b|서류 ?검사 ?(?:보고서|리포트)/i.test(t)) return "document_check";
  if (/\bfield[- ]check (?:reports?|summary)\b/i.test(t)) return "field_check";
  if (/\bstage reports?\b|단계 ?(?:보고서|리포트)/i.test(t)) return "stage";
  if (/\b(?:inquir(?:y|ies)|enquir(?:y|ies)) reports?\b|문의 ?(?:보고서|리포트)/i.test(t)) return "inquiries";
  return null;
}

/** The intent a normalized question carries, or null when it is not a Hangeul data question. */
function detectIntent(t: string): { intent: Intent; student: StudentQuery | null } | null {
  const student = studentFrom(t);
  const legacy = legacyCue(t);
  const ours = !NOT_OURS.test(t);
  const anchored = legacy || ANCHOR.test(t);
  // The loose cues need the subject not to be plainly someone else's.
  const loose = anchored || (ours && !FOREIGN.test(t));
  if (namedReport(t)) return { intent: "report", student };
  if (student) return { intent: "student", student };
  if (any(CUES.inquiries, t)) return { intent: "inquiries", student };
  if (any(CUES.consultancyDone, t) && !CONSULT_MONEY.test(t) && (!CONSULT_ELSEWHERE.test(t) || CONSULT_OURS.test(t))) {
    return { intent: "consultancyDone", student };
  }
  if (loose && any(CUES.performance, t) && (anchored || !PERF_OTHER.test(t))) return { intent: "performance", student };
  if (any(CUES.passport, t)) return { intent: "passport", student };
  if (loose && !TRAVEL.test(t) && any(CUES.passportLoose, t)) return { intent: "passport", student };
  if (any(CUES.docs, t)) return { intent: "docs", student };
  if (ours && any(CUES.verified, t)) return { intent: "verified", student };
  if (ours && any(CUES.pending, t)) return { intent: "pending", student };
  if (any(CUES.window, t)) return { intent: "window", student };
  if (any(CUES.missing, t) && (legacy || /\bstudents?\b|학생|\breport\b/i.test(t))) return { intent: "missing", student };
  if (ours && any(CUES.calendar, t)) return { intent: "calendar", student };
  if (loose && (anchored || !CHANGE_TOPIC.test(t)) && any(CUES.changes, t) && hasSinceTime(t)) return { intent: "changes", student };
  if (any(CUES.report, t)) return { intent: "report", student };
  if (loose && any(CUES.dashboard, t)) return { intent: "dashboard", student };
  if (any(CUES.applied, t) && OURS_OR_WHEN.test(t)) return { intent: "applied", student };
  if (legacy) return { intent: isHangeulStatusQuery(t) ? "status" : "legacy", student };
  if (STATUS_CUES.slice(3).some((re) => re.test(t))) return { intent: "status", student };
  return null;
}

const SINCE_TIME =
  /\bsince (?:this morning|morning|today|yesterday|last night|midnight|noon|lunch|\d{1,2}(?::\d{2})?(?: ?[ap]\.?m\.?)?(?![\d:])|an? (?:hour|while) ago|\d{1,3} hours? ago|the last (?:sync|run|hour|check))|\b(?:in|over) the (?:last|past) (?:\d{1,3} )?hours?\b|(?:아침|오늘|어제|최근|지난)/i;

function hasSinceTime(t: string): boolean {
  return SINCE_TIME.test(t) || SINCE_DATE.test(t);
}

/** True when the question is about the agency's data (it goes to the Hangeul module). */
export function isHangeulContextQuery(text: string): boolean {
  return detectIntent(normalizeQuery(text)) !== null;
}

function verdictFrom(t: string): string | undefined {
  if (/\bfail(?:ed|s|ing)?\b|불합격|실패/i.test(t)) return "FAIL";
  if (/\bflag(?:ged|s)?\b/i.test(t)) return "FLAG";
  if (/\bmissing\b|누락/i.test(t)) return "MISSING";
  if (/\breview\b|검토/i.test(t)) return "REVIEW";
  if (/\bincomplete\b/i.test(t)) return "INCOMPLETE";
  return undefined;
}

const CONSULTATION_STATUS: [RegExp, string][] = [
  [/\bno answer\b|무응답|부재/i, "No Answer"],
  [/\bwrong number\b|잘못된 ?번호/i, "Wrong Number"],
  [/\bfile(?:s)? opened\b|파일 ?오픈/i, "File Opened"],
  [/\bconsulted\b|상담 ?완료/i, "Consulted"],
  [/\bnew (?:inquir|enquir|request)|신규/i, "New"],
];

const CALENDAR_TARGET = /\b(?:for|at|of) (?:the )?([a-z][a-z&.'-]*(?: [a-z][a-z&.'-]*){0,5})/i;
/** Words that end a named target ("Gachon applications this week" → "Gachon"). */
const TARGET_END = new Set(
  "application applications deadline deadlines intake intakes period periods window windows round this next last today tomorrow week month please open opening dhl on in from to by and or".split(" "),
);
/** A target that is the agency itself, not a university ("deadlines for us", "on our calendar"). */
const TARGET_NOT = new Set("us me our we the agency office portal hangeul students student calendar all any every upcoming".split(" "));

/** The university or place a calendar question names: "application deadlines for Gachon University" → "Gachon University". */
export function calendarTarget(t: string): string | null {
  const m = CALENDAR_TARGET.exec(t);
  if (!m) return null;
  const words: string[] = [];
  for (const w of m[1].split(" ")) {
    if (TARGET_END.has(w.toLowerCase())) break;
    words.push(w.replace(/[.'-]+$/, ""));
  }
  if (words.length === 0 || TARGET_NOT.has(words[0].toLowerCase())) return null;
  return words.join(" ");
}

const LAST_MONTH = /\blast month'?s?\b|지난 ?달|저번 ?달/i;
// "this months performence": the owner writes it without the apostrophe.
const THIS_MONTH = /\bthis months?\b|\bmonth(?:ly)?\b|\bmtd\b|이번 ?달|이달|월간/i;
// A month named without a day ("consultancies done in September"). "March" and "May" are also verbs: they need "in/for/of/during".
const NAMED_MONTH =
  /\b(january|february|april|june|july|august|september|october|november|december)\b|\b(?:in|for|of|during) (march|may)\b/i;

/** A day inside the month a question names on its own (its last day, or today for the current month), else null. */
function namedMonthDay(t: string, today: string): string | null {
  if (DAY_MONTH.test(t) || MONTH_DAY.test(t)) return null;
  const m = NAMED_MONTH.exec(t);
  if (!m) return null;
  const month = monthNumber(m[1] ?? m[2]);
  const first = resolveDay(today, month, 1);
  if (!first) return null;
  const last = addDays(firstOfMonth(addDays(first, 32)), -1);
  return last > today ? today : last;
}

function semanticKinds(t: string): string[] | undefined {
  if (DOC_WORDS.test(t)) return ["doc_page_text", "doc_verdict", "field_check", "doc_check", "student_documents"];
  if (/\bpassports?\b|여권/i.test(t)) return ["passport_alert", "passport_issue", "student", "student_export"];
  if (/\b(?:consult|inquir|enquir)/i.test(t) || /상담|문의/.test(t)) return ["consultation", "consultation_day", "consultant_performance"];
  return undefined;
}

/**
 * The query plan for a question, or null when it is not a Hangeul data question.
 * A Hangeul question that fits no structured plan becomes a `semantic` plan.
 */
export function classify(text: string, ctx: RouterContext): Plan | null {
  const t = normalizeQuery(text);
  const found = detectIntent(t);
  if (!found) return null;
  const { today } = ctx;
  const span = daySpan(t, today);
  const singleDay = span?.single ? span.from : today;
  const monthDay = found.intent === "consultancyDone" || found.intent === "performance" ? namedMonthDay(t, today) : null;

  switch (found.intent) {
    case "student": {
      const student = found.student!;
      if (any(CUES.missing, t)) return { intent: "missing_for_student", student };
      if (any(CUES.passport, t) || any(CUES.passportLoose, t)) return { intent: "passport_alerts", student };
      if (DOC_WORDS.test(t) && FREE_TEXT_ASK.test(t)) {
        return { intent: "semantic", question: text.trim(), kinds: semanticKinds(t), student };
      }
      if (DOC_WORDS.test(t) || any(CUES.docs, t)) return { intent: "doc_verdicts", student, verdict: verdictFrom(t) };
      return { intent: "student_card", student };
    }
    case "inquiries": {
      const status = CONSULTATION_STATUS.find(([re]) => re.test(t))?.[1];
      if (span && !span.single) return { intent: "inquiries_on_day", day: span.from, to: span.to, ...(status ? { status } : {}) };
      return { intent: "inquiries_on_day", day: singleDay, ...(status ? { status } : {}) };
    }
    case "consultancyDone":
      // The portal's page has Today and This Month: a month is its month window, another range is said to be missing.
      if (LAST_MONTH.test(t)) return { intent: "performance", period: "month", day: previousMonth(today).to };
      if (THIS_MONTH.test(t)) return { intent: "performance", period: "month", day: today };
      if (monthDay) return { intent: "performance", period: "month", day: monthDay };
      if (span && !span.single) return { intent: "consultancies_closed_today", day: span.from, to: span.to };
      return { intent: "consultancies_closed_today", day: singleDay };
    case "performance": {
      if (LAST_MONTH.test(t)) return { intent: "performance", period: "month", day: previousMonth(today).to };
      if (THIS_MONTH.test(t)) return { intent: "performance", period: "month", day: today };
      if (monthDay) return { intent: "performance", period: "month", day: monthDay };
      if (span && !span.single) return { intent: "performance", period: "today", day: span.from, to: span.to };
      return { intent: "performance", period: "today", day: singleDay };
    }
    case "verified":
      return { intent: "verified_on_day", from: span?.from ?? today, to: span?.to ?? today };
    case "pending":
      return { intent: "pending_payments" };
    case "window":
      return { intent: "window_review" };
    case "passport":
      if (!span) return { intent: "passport_alerts" };
      return span.single ? { intent: "passport_alerts", day: span.from } : { intent: "passport_alerts", from: span.from, to: span.to };
    case "docs":
      return { intent: "doc_verdicts", verdict: verdictFrom(t) };
    case "missing":
      return { intent: "report", report: "missing" };
    case "calendar": {
      const where = calendarTarget(t);
      const target = where ? { where } : {};
      // A named university looks further ahead: the portal's calendar shows this month and the next 45 days.
      if (!span) return { intent: "calendar_window", from: today, to: addDays(today, where ? 60 : 14), ...target };
      // "This week" / "this month" look ahead for deadlines.
      if (/\bthis week\b|이번 ?주/i.test(t)) return { intent: "calendar_window", from: today, to: addDays(today, 6), ...target };
      if (/\bthis month\b|이번 ?달|이달/i.test(t)) {
        return { intent: "calendar_window", from: today, to: addDays(firstOfMonth(addDays(firstOfMonth(today), 32)), -1), ...target };
      }
      return { intent: "calendar_window", from: span.from, to: span.to, ...target };
    }
    case "changes": {
      const { since, label } = sinceFrom(t, today, ctx.now, ctx.timeZone);
      return { intent: "changes_since", since, sinceLabel: label };
    }
    case "report": {
      const report = namedReport(t) ?? "brief";
      return span?.single && span.from !== today ? { intent: "report", report, day: span.from } : { intent: "report", report };
    }
    case "dashboard":
      return { intent: "dashboard" };
    case "applied":
      return { intent: "students_applied", from: span?.from ?? today, to: span?.to ?? today };
    case "status":
      return { intent: "data_status" };
    case "legacy":
    default: {
      if (/\b(?:reports?|briefing|summary)\b|보고서|리포트|브리핑|현황/i.test(t)) return { intent: "report", report: "brief" };
      if (/\b(?:enrol{1,2}(?:ed|ments?)|registrations?)\b/i.test(t)) {
        return { intent: "students_applied", from: span?.from ?? today, to: span?.to ?? today };
      }
      if (/\b(?:students|active students|numbers|stats|metrics)\b|재원생|수강생/i.test(t)) return { intent: "dashboard" };
      if (/\b(?:pending|unpaid|outstanding) (?:payments?|fees|tuition)\b|미납/i.test(t)) return { intent: "pending_payments" };
      return {
        intent: "semantic",
        question: text.trim(),
        kinds: semanticKinds(t),
        ...(span ? { from: span.from, to: span.to } : {}),
      };
    }
  }
}
