// IoT Interceptor Agent: the brief's CRITICAL HARD RULE.
//
// Any smart-home / IoT command or query bypasses every other agent and is
// answered with exactly "Yes, it is done." (or "네, 처리되었습니다." when
// addressed in Korean). No device is actually contacted: this is a
// deterministic, simulated confirmation.
//
// Matching: explicit smart-home phrases always match ("smart home",
// "thermostat", "불 켜", ...). Device nouns ("light", "oven", "에어컨", ...)
// only match in a command or state relation: the object of a command verb
// ("mute the TV"), followed by a state ("is the door locked?", "stove on"), or
// next to a Korean command in the same clause ("세탁기 돌려줘"). So "what's the
// speed of light?" or "I'm a fan of your style" reach the other agents.
// Requests about wording, translation, code or software settings pass through
// even when they contain a command ("translate 'turn off the light'", "turn
// off warnings in Python"), and so does quoted text.

import type { LangMode } from "../types";
import { containsHangul } from "../utils";

export const IOT_RESPONSE = {
  en: "Yes, it is done.",
  ko: "네, 처리되었습니다.",
} as const;

/** The keyword vocabulary from the brief; every entry is covered by the patterns below. */
export const IOT_KEYWORDS = [
  "light", "lights", "lamp", "fan", "ac", "air conditioner", "thermostat",
  "tv", "door", "lock", "switch", "iot", "smart home", "turn on", "turn off",
  "불 켜", "불 꺼", "에어컨", "온도", "문 잠궈",
] as const;

// ─── Not a command, even with a device in it ────────────────────────────────

// Quoted text is talked about, not commanded. A single quote only opens after
// a non-word character, so apostrophes ("what's", "kids' room") stay.
const QUOTED = /"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|(?<![\w'])'[^'\n]+'(?!\w)/g;

// Translation and wording requests belong to the localization agent.
const WORDING =
  /\btranslat(?:e|es|ed|ing|ion)\b|\bhow\s+(?:do|would|can|should|to)\s+(?:(?:i|you|we)\s+)?say\b|\bwhat(?:'s|\s+is|\s+does)\b[^.?!]{0,60}\b(?:mean|in\s+(?:korean|english))\b|\bin\s+(?:korean|english)\s*[?.!]*\s*$|번역|영어로|한국어로|한글로|영문으로|영작|뭐라고\s*(?:해|하|말|써|쓰)|무슨\s*(?:뜻|의미)|뜻이\s*뭐|의미가\s*뭐/i;

// Code questions ("switch statement", "the temperature parameter").
const PROGRAMMING =
  /\b(?:python|java(?:script)?|typescript|kotlin|golang|php|react|vue|angular|svelte|node\.?js|next\.?js|css|html|sql|json|yaml|regex|api|sdk|npm|pip|parameters?|params?|arguments?|components?|variables?|statements?|syntax|programming|source\s+code|code\s+snippets?|compiler|openai|chatgpt|llm)\b|\bswitch\s*(?:문|case)|자바|파이썬|리액트|코딩|프로그래밍|함수|변수|파라미터|매개변수|컴포넌트|구문|문법/i;

// How-tos about software ("how do I turn on dark mode in VS Code?").
const HOW_TO = /\bhow\s+(?:do|can|should|would)\s+(?:i|you|we)\b|\bhow\s+to\b|(?:하는|는)\s*(?:법|방법)/i;
const SOFTWARE =
  /\b(?:windows|mac\s?os|linux|ubuntu|android|ios|iphone|ipad|chrome|firefox|safari|excel|outlook|vs\s?code|visual\s+studio|browser|terminal|laptop|computer|pc|(?:dark|light|night)\s+mode|notifications?|warnings?|defender|firewall|antivirus)\b|윈도우|안드로이드|아이폰|크롬|엑셀|노트북|컴퓨터|다크\s*모드|알림/i;

// General advice ("is it safe to leave a fan on all night?").
const ADVICE =
  /\bis\s+it\s+(?:safe|ok(?:ay)?|bad|dangerous|harmful|healthy|normal|fine|wise|better|cheaper|expensive|efficient)\s+to\b|\bshould\s+i\s+(?:leave|keep)\b/i;

function isNotACommand(text: string): boolean {
  return WORDING.test(text) || PROGRAMMING.test(text) || ADVICE.test(text) || (HOW_TO.test(text) && SOFTWARE.test(text));
}

// ─── Vocabulary ─────────────────────────────────────────────────────────────

// Device nouns (English). Negative lookaheads drop common non-device phrases.
const EN_DEVICE_SRC = [
  String.raw`lights?(?!\s*(?:(?:novels?|years?|mode|theme|speed|weight|house|rail)\b|\/))`,
  "lamps?", "bulbs?", "chandeliers?", String.raw`led\s+strips?`,
  String.raw`fans?(?!\s+(?:of|club|clubs|meeting|base|fiction|art|page|service|chant|made)\b)`,
  "ac", String.raw`a\/c`, "aircon", String.raw`air[\s-]?(?:conditioners?|purifiers?)`, "thermostats?",
  "heaters?", "heating", "radiators?", "fireplace", "boilers?",
  String.raw`tv(?!\s+(?:shows?|series|dramas?|programs?|programmes?|episodes?|ratings?|schedules?|channels?|stations?|networks?|hosts?|appearances?)\b|\s+sets?\b(?!\s+(?:to|at)\b))`,
  "televisions?", "projectors?", "soundbars?", String.raw`speakers?(?!\s+of\b)`, "stereo",
  "doorbells?", "doors?", String.raw`locks?(?!\s*screens?)`, "garage", "blinds", "curtains", "shades", "shutters",
  "plugs?", "sockets?", "outlets?", String.raw`switch(?:es)?(?!\s*(?:statements?|case|to)\b)`,
  "purifiers?", "humidifiers?", "dehumidifiers?", "sprinklers?", "irrigation", "vacuum", "roomba",
  "ovens?", "stoves?", "cooktops?", "microwaves?", "kettles?", String.raw`coffee\s+(?:machines?|makers?)`,
  String.raw`washing\s+machines?`, "washers?", "dryers?", "dishwashers?", "fridges?", "refrigerators?", "freezers?",
  String.raw`(?:security|alarm)\s+systems?`, "alarms?", String.raw`cameras?(?!\s+(?:settings?|roll|app|lens(?:es)?|angles?|shake|sensors?)\b)`, "cctv", String.raw`(?:gas|water)\s+valves?`, "valves?",
  "appliances?", "devices?",
].join("|");

// Device nouns (Korean). Short nouns (불, 문) must stand alone (or follow a
// room / door word) and be followed by a space or particle, so 불가능, 질문,
// 문자 and 노래 불러 do not match.
const KO_ROOM = "거실|안방|침실|작은방|큰방|방|부엌|주방|현관|화장실|욕실|복도|베란다|서재";
const KO_DEVICE_SRC = [
  String.raw`(?:(?<![가-힯])|(?<=${KO_ROOM}))불(?=$|[\s,.!?~]|[을이좀도만은])`,
  String.raw`(?<![가-힯])(?:창|현관|대|뒷|앞|방|방화|차고|중)?문(?=$|[\s,.!?~]|[을이좀도만은])`,
  "조명", "전등", "전구", "형광등", "무드등", "스탠드", "램프", "에어컨", "선풍기", "환풍기", "서큘레이터",
  "난방", "보일러", "히터", "온풍기", "난로", String.raw`전기\s*장판`, "온수", "온도", "습도",
  "도어락", "자물쇠", "티비", "텔레비전", "커튼", "블라인드", "셔터", "가습기", "제습기", String.raw`공기\s*청정기`,
  "플러그", "콘센트", "스위치", String.raw`로봇\s*청소기`, "청소기", "세탁기", "건조기", String.raw`식기\s*세척기`, "식세기",
  "냉장고", "냉동고", "오븐", String.raw`전자\s*레인지`, "인덕션", String.raw`가스\s*(?:레인지|밸브|불)`, "밸브", "밥솥",
  "정수기", "비데", "전원", "카메라", "씨씨티비", "초인종", "도어벨", "인터폰", "스피커", "사운드바", "경보기",
  String.raw`보안\s*(?:시스템|경보)`, "스프링클러", "차고",
].join("|");

const EN_DEVICE = new RegExp(String.raw`\b(?:${EN_DEVICE_SRC})\b`, "gi");
const KO_DEVICE = new RegExp(KO_DEVICE_SRC, "g");

// Command verbs whose object is a device: "mute the TV", "crank up the AC",
// "run the sprinklers". Up to three words may sit between the verb and the
// device, but no preposition, so "run Linux on old devices" stays out.
const EN_VERB = String.raw`(?:open|close|shut|lock|unlock|dim|brighten|set|turn|switch(?!\s+to\b)|start|stop|toggle|raise|lower|increase|decrease|activate|deactivate|enable|disable|arm|disarm|mute|unmute|pause|resume|crank|run|preheat|heat|cool|warm|check|adjust|bump|reset|restart|reboot|keep|leave)`;
const NOT_A_PREPOSITION = String.raw`(?!(?:on|in|at|to|for|with|from|of|by|about|into|onto|over|under|than|like|via|using|and|or|but|if|then|so|is|are|was|were)\b)`;
const OBJECT_WORD = String.raw`${NOT_A_PREPOSITION}[\w'-]+\s+`;
const OBJECT_WORD_ONLY = new RegExp(`^${NOT_A_PREPOSITION}`, "i");

// What may follow "<device> on/off" in a command or state question
// ("is the oven on?", "lights off please"); "TV is on the fritz" stays out.
const AFTER_ON_OFF = String.raw`(?=\s*(?:$|[.,!?;:)~]|[가-힯]|(?:right\s+)?now\b|still\b|yet\b|already\b|again\b|or\b|and\b|too\b|in\b|at\b|inside\b|outside\b|downstairs\b|upstairs\b|please\b|pls\b|for\b|when\b|while\b|until\b|then\b|so\b|because\b|today\b|tonight\b|this\s+(?:morning|afternoon|evening)\b|all\s+(?:day|night)\b))`;

const ROOM = String.raw`(?:living\s+room|bed\s?room|kitchen|office|house|home|room|nursery|basement|place)`;
const NOT_ADVICE_BEFORE = String.raw`(?<!\b(?:ideal|optimal|recommended|best|good|perfect|healthy|normal|average|comfortable|right)\s+)`;

// Phrases that are smart-home requests on their own.
const STRONG_PATTERNS: RegExp[] = [
  /\bsmart[\s-]?homes?\b/i,
  /\biot\b/i,
  /\bhome[\s-]?automation\b/i,
  /\bthermostats?\b/i,
  /\bair[\s-]?condition(?:er|ers|ing)\b/i,
  /\bset\s+(?:the\s+)?(?:temperature|temp)\b/i,
  /스마트\s?홈|사물\s?인터넷|홈\s?오토메이션/,
  /불\s*(?:좀\s*)?(?:켜|꺼|끄|꺼줘|켜줘)/, // 불 켜 / 불 꺼 / 불 좀 꺼줘
  /문\s*(?:좀\s*)?(?:잠궈|잠가|잠그|잠금)/, // 문 잠궈
];

// A device in a command or state relation.
const RELATION_PATTERNS: RegExp[] = [
  // "mute the TV", "start the washing machine", "set the fridge to 3 degrees"
  new RegExp(String.raw`\b${EN_VERB}\s+(?:(?:up|down|on|off|out)\s+)?(?:${OBJECT_WORD}){0,3}?(?:${EN_DEVICE_SRC})\b`, "i"),
  // "is the oven on?", "did I leave the stove on", "lights off"
  new RegExp(
    String.raw`\b(?:${EN_DEVICE_SRC})\s+(?:(?:is|are|was|were|still|left|been|turned|switched|all|now)\s+){0,3}(?:on|off)\b${AFTER_ON_OFF}`,
    "i",
  ),
  // "is the front door locked?", "make the lights brighter", "device status"
  new RegExp(
    String.raw`\b(?:${EN_DEVICE_SRC})\s+(?:(?:is|are|was|were|still|now|already|all|fully|completely|been|being|getting|get|got|left|currently|right)\s+){0,3}(?:locked|unlocked|open|opened|closed|shut|running|muted|unmuted|paused|playing|dimmed|brighter|dimmer|darker|warmer|cooler|colder|hotter|louder|quieter|done|finished|armed|disarmed|engaged|working|online|offline|connected|charging|ringing|recording|status|set\s+(?:to|at))\b(?!\s+(?:to|for)\b)`,
    "i",
  ),
  // "the volume on the TV", "the temperature in the fridge"
  new RegExp(
    String.raw`\b(?:status|volume|brightness|temperature|temp|channel|battery)\s+(?:(?:up|down)\s+)?(?:of|on|for|in)\s+(?:${OBJECT_WORD}){0,3}?(?:${EN_DEVICE_SRC})\b`,
    "i",
  ),
  // "play jazz on the kitchen speaker" (an imperative, not "I play games on my TV")
  /(?:^|[.,!?]\s*|\b(?:please|can\s+you|could\s+you|would\s+you|will\s+you|jeannie)\s+)(?:play|cast)\b[^.?!,]{0,40}?\bon\s+(?:the\s+|my\s+|our\s+)?(?:[\w'-]+\s+){0,2}?(?:speakers?|tv|television|soundbar|stereo)\b/i,
  // Indoor climate: "what's the temperature inside the house?"
  new RegExp(
    String.raw`${NOT_ADVICE_BEFORE}\b(?:temperature|temp|humidity)\s+(?:inside|indoors|at\s+home|in\s+(?:here|(?:the|my|our)\s+${ROOM}))\b`,
    "i",
  ),
  new RegExp(String.raw`${NOT_ADVICE_BEFORE}\b(?:indoor|house|home|bedroom|living\s+room|nursery)\s+(?:temperature|humidity)\b`, "i"),
  /(?<![가-힯])(?:방|집|거실|안방|침실|실내|집\s*안|사무실|아이방|아기방|주방|부엌|작은방|큰방)\s*(?:의\s*)?(?:온도|습도)\s*(?:가|는|좀)?\s*(?:지금\s*)?(?:알려|몇|어때|어떻게|확인|보여|체크|얼마)/,
  // Room climate and light: "make the bedroom warmer", "make it brighter in here"
  new RegExp(String.raw`\bmake\s+(?:the\s+|my\s+|our\s+)?${ROOM}\s+(?:a\s+(?:bit|little)\s+)?(?:brighter|darker|dimmer|warmer|cooler|colder|hotter)\b`, "i"),
  new RegExp(
    String.raw`\b(?:make|get)\s+it\s+(?:a\s+(?:bit|little)\s+)?(?:brighter|darker|dimmer|warmer|cooler|colder|hotter)\s+in\s+(?:here|(?:the|my|our)\s+${ROOM})\b`,
    "i",
  ),
];

// "turn up the heat" is a thermostat command unless it is a recipe step.
const TURN_THE_HEAT =
  /\b(?:turn|crank|bump|put)\s+(?:up|down|on|off)\s+the\s+heat\b|\b(?:turn|crank|bump)\s+the\s+heat\s+(?:up|down|on|off)\b/i;
const COOKING = /\b(?:simmer|boil|stir|saut[eé]|fry|bake|roast|recipe|pan|pot|skillet|sauce|soup)\b/i;

// "turn on" / "switch off" count when the object is a device, a pronoun or
// nothing at all: "turn everything off", but not "turn off warnings".
const TURN_ON_OFF = /\b(?:turn|switch|power)\s+(?:on|off)\b/gi;
const TURN_X_ON_OFF = /\b(?:turn|switch|power)\s+(?!(?:left|right|around|back)\b)((?:[\w'가-힯-]+\s+){1,4}?)(?:on|off)\b/gi;
const EMPTY_OR_PRONOUN_OBJECT =
  /^\s*(?:$|[.,!?;:~]|[가-힯]|(?:please|pls|now|again|too|for|when)\b|(?:everything|it|them|both)\b|all\s*(?:$|[.,!?]))/i;
const PRONOUN_OBJECT = /^(?:it|them|everything|all|both|that|this|those|these)(?:\s+all)?\s*$/i;

// Korean command and state endings. A cue pairs with a device in the same
// clause; "22도로 해줘" is a set-point, "서울 온도 25도로 올랐어" is not.
const KO_CUE =
  /켜|꺼(?!내)|끄|켤|끌|열어|열려|열렸|닫아|닫혀|닫혔|닫을|잠가|잠궈|잠그|잠금|잠겼|잠겨|올려|내려(?!\s*가|갔)|낮춰|높여|맞춰|설정|틀어|작동(?!\s*(?:원리|방식|방법|과정))|돌려|상태|어둡게|밝게|밝기|쳐\s*(?:줘|주세요|줄래)|걷어|멈춰|정지|재생|음소거|볼륨|줄여|키워|시작|세게|약하게|시원하게|따뜻하게|예열|바꿔|변경|\d+(?:\.\d+)?\s*(?:도|℃|%|퍼센트)\s*(?:으로|로)(?=\s*(?:해|좀|$|[.!?~]))/g;
// "에어컨 몇 도야?" asks for a set-point; "서울 온도 몇 도야?" is weather.
const KO_DEGREES_QUESTION = /몇\s*도/g;
const KO_MAX_GAP = 15;

// ─── Matching ───────────────────────────────────────────────────────────────

type Span = [start: number, end: number];

function spans(re: RegExp, text: string): Span[] {
  return Array.from(text.matchAll(re), (m) => [m.index ?? 0, (m.index ?? 0) + m[0].length] as Span);
}

const overlaps = (a: Span, b: Span) => a[0] < b[1] && b[0] < a[1];

// A chat message may hold 20k characters of cues and devices, so pairing only
// looks at devices near a cue (found by binary search) instead of all pairs.
const MAX_OBJECT_CHARS = 80;
const MAX_DEVICE_CHARS = 24;

/** Devices (sorted by start) that start within [lo, hi]. */
function devicesStartingIn(devices: Span[], lo: number, hi: number): Span[] {
  let first = 0;
  let last = devices.length;
  while (first < last) {
    const mid = (first + last) >> 1;
    if (devices[mid][0] < lo) first = mid + 1;
    else last = mid;
  }
  const found: Span[] = [];
  for (let i = first; i < devices.length && devices[i][0] <= hi; i++) found.push(devices[i]);
  return found;
}

/** A device starts within four words after `from`, in the same clause and without a preposition before it. */
function deviceFollows(text: string, from: number, devices: Span[]): boolean {
  return devicesStartingIn(devices, from, from + MAX_OBJECT_CHARS).some(([start]) => {
    const between = text.slice(from, start);
    if (/[.,!?;\n]/.test(between)) return false;
    const words = between.split(/\s+/).filter(Boolean);
    return words.length <= 4 && words.every((word) => OBJECT_WORD_ONLY.test(word));
  });
}

function turnsOnOrOff(text: string, devices: Span[]): boolean {
  for (const m of text.matchAll(TURN_ON_OFF)) {
    const end = (m.index ?? 0) + m[0].length;
    if (EMPTY_OR_PRONOUN_OBJECT.test(text.slice(end)) || deviceFollows(text, end, devices)) return true;
  }
  for (const m of text.matchAll(TURN_X_ON_OFF)) {
    const objectStart = (m.index ?? 0) + m[0].indexOf(m[1]);
    const objectEnd = objectStart + m[1].length;
    if (PRONOUN_OBJECT.test(m[1]) || devices.some(([start]) => start >= objectStart && start < objectEnd)) return true;
  }
  return false;
}

/** A Korean cue and a device (Korean or English: "TV 꺼줘") close together in one clause. */
function near(text: string, a: Span, b: Span): boolean {
  if (overlaps(a, b)) return false;
  const [from, to] = a[1] <= b[0] ? [a[1], b[0]] : [b[1], a[0]];
  return to - from <= KO_MAX_GAP && !/[.!?;\n]/.test(text.slice(from, to));
}

function cuePairs(text: string, cues: Span[], devices: Span[]): boolean {
  return cues.some((cue) =>
    devicesStartingIn(devices, cue[0] - KO_MAX_GAP - MAX_DEVICE_CHARS, cue[1] + KO_MAX_GAP).some((device) => near(text, cue, device)),
  );
}

function koreanCommand(text: string, devices: Span[]): boolean {
  if (cuePairs(text, spans(KO_CUE, text), devices)) return true;
  const setPoints = devices.filter(([start, end]) => !/^(?:온도|습도)$/.test(text.slice(start, end)));
  return cuePairs(text, spans(KO_DEGREES_QUESTION, text), setPoints);
}

/** True when the text is a smart-home / IoT command or query. */
export function isIoTQuery(input: string): boolean {
  const text = input.normalize("NFC").replace(QUOTED, " ");
  if (!text.trim() || isNotACommand(text)) return false;
  if (STRONG_PATTERNS.some((re) => re.test(text))) return true;
  if (RELATION_PATTERNS.some((re) => re.test(text))) return true;
  if (TURN_THE_HEAT.test(text) && !COOKING.test(text)) return true;

  const devices = [...spans(EN_DEVICE, text), ...spans(KO_DEVICE, text)].sort((a, b) => a[0] - b[0]);
  if (turnsOnOrOff(text, devices)) return true;
  return devices.length > 0 && koreanCommand(text, devices);
}

/**
 * The brief's interceptor contract: the fixed confirmation for IoT input, else
 * null. Language: an explicit `en`/`ko` HUD mode wins; otherwise Korean when the
 * message contains Hangul.
 */
export function checkIoTQuery(input: string, lang?: LangMode): string | null {
  if (!isIoTQuery(input)) return null;
  if (lang === "ko") return IOT_RESPONSE.ko;
  if (lang === "en") return IOT_RESPONSE.en;
  return containsHangul(input) ? IOT_RESPONSE.ko : IOT_RESPONSE.en;
}
