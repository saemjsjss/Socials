// Mistake-audit flow: a small state machine on top of the conversation.
//
//   idle ──(audit query)──▶ audit reply with framed recommendations + approval request
//        ◀──(approval)───── standard execution confirmation      (awaiting_approval)
//        ◀──(rejection)──── short acknowledgement
//
// State is derived from the history rather than stored: the conversation is
// awaiting approval when the last assistant turn carries APPROVAL_MARKER. The
// HUD sends its history with every request; Telegram, which sends single
// messages, replays the pending audit reply from Supabase (see telegram.ts).
// The confirmation is a message only: no tool carries the actions out yet.
// Runs on Edge and Node.js.

import type { ChatMessage, Honorific, ResolvedLang } from "../types";

export type AuditState = "idle" | "awaiting_approval";

/** Line every audit reply ends with; its presence is what marks the pending approval. */
export const APPROVAL_MARKER = "■ 승인 요청";

export const APPROVAL_REQUEST_LINE = `${APPROVAL_MARKER}: "승인" 또는 "approve"라고 답하시면 진행하겠습니다. ("취소" / "cancel" to discard)`;

const AUDIT_QUERY =
  /\b(?:mistake|error)s?\s+(?:audit|check|review)\b|\baudit\b.*\b(?:mistakes?|errors?|work|this|my)\b|\b(?:check|review|find|spot)\b.*\b(?:my\s+)?(?:mistakes?|errors?)\b|\bwhat\s+did\s+I\s+(?:do|get)\s+wrong\b|\bwhere\s+did\s+I\s+go\s+wrong\b|실수\s*(?:점검|확인|검토|체크|찾아|있)|오류\s*(?:점검|확인|검토|체크|찾아)|잘못된\s*(?:점|부분)|틀린\s*(?:점|부분|곳)|검수/i;

/** "Audit this for mistakes", "check my errors", "실수 점검해줘", "잘못된 점 찾아줘". */
export function isMistakeAudit(text: string): boolean {
  return AUDIT_QUERY.test(text);
}

// Approval and rejection only count as short replies: "approve the budget draft and email it" is a new request.
const MAX_REPLY_CHARS = 40;
const APPROVAL =
  /^(?:(?:yes|yep|ok(?:ay)?|sure)[,!.\s]*)?(?:approved?|go\s+ahead|do\s+it|proceed|execute|confirm(?:ed)?|yes)(?:\s+(?:please|now|it|them|all))?[.!\s]*$|^(?:네|예|좋아요?|좋습니다)?[,.\s]*(?:승인(?:합니다|해요|해|할게요)?|진행(?:해(?:\s*주세요|요)?|하세요|해\s*주십시오|합시다|시켜)?|실행(?:해(?:\s*주세요|요)?|하세요)?|그렇게\s*(?:해|하세요|해\s*주세요))[.!\s]*$/i;
const REJECTION =
  /^(?:no|nope|cancel|reject(?:ed)?|stop|don'?t|hold(?:\s+off)?|not\s+now)(?:\s+(?:it|that|please|them))?[.!\s]*$|^(?:아니(?:요|오)?|취소(?:해|해요|해\s*주세요|합니다)?|보류(?:해|해요|해\s*주세요|합니다)?|하지\s*마(?:세요)?|중지(?:해)?)[.!\s]*$/i;

export function isApproval(text: string): boolean {
  const t = text.trim();
  return t.length > 0 && t.length <= MAX_REPLY_CHARS && APPROVAL.test(t);
}

export function isRejection(text: string): boolean {
  const t = text.trim();
  return t.length > 0 && t.length <= MAX_REPLY_CHARS && REJECTION.test(t);
}

/** True when `text` is a short approval or rejection (Telegram replays the pending audit only then). */
export function isApprovalReply(text: string): boolean {
  return isApproval(text) || isRejection(text);
}

/** The audit reply the latest user turn answers, when it still awaits approval. */
export function pendingAudit(history: readonly ChatMessage[]): string | null {
  if (history.at(-1)?.role !== "user") return null;
  const previous = history.at(-2);
  return previous?.role === "assistant" && previous.content.includes(APPROVAL_MARKER) ? previous.content : null;
}

export function auditState(history: readonly ChatMessage[]): AuditState {
  return pendingAudit(history) === null ? "idle" : "awaiting_approval";
}

const MAX_ITEMS = 10;
const MAX_ITEM_CHARS = 160;

/** Numbered recommendation lines ("1. 문제 — …") of an audit reply, markdown stripped. */
export function extractRecommendations(auditReply: string): string[] {
  const items: string[] = [];
  for (const line of auditReply.split("\n")) {
    const match = /^\s*(?:\*\*)?(\d{1,2})[.)]\s*(?:\*\*)?\s*(.+)$/.exec(line);
    if (!match) continue;
    const text = match[2].replace(/\*\*|__|`/g, "").replace(/\s+/g, " ").trim();
    if (!text) continue;
    items.push(text.length > MAX_ITEM_CHARS ? `${text.slice(0, MAX_ITEM_CHARS - 1)}…` : text);
    if (items.length >= MAX_ITEMS) break;
  }
  return items;
}

function itemList(items: string[]): string {
  return items.map((item, i) => `${i + 1}. ${item}`).join("\n");
}

/** Standard execution confirmation after an approval. Fixed text, no LLM. */
export function executionConfirmation(lang: ResolvedLang, honorific: Honorific, items: string[]): string {
  const ko = `네, ${honorific}. 승인하신 권장 조치를 진행하겠습니다. 완료되면 보고드리겠습니다.`;
  const en = `Understood, ${honorific}. Proceeding with the approved recommendations. I'll report back when they're done.`;
  const head = lang === "ko" ? ko : lang === "bilingual" ? `${en}\n—\n${ko}` : en;
  if (items.length === 0) return head;
  const label = lang === "ko" ? "승인된 항목" : lang === "bilingual" ? "Approved items / 승인된 항목" : "Approved items";
  return `${head}\n\n${label}:\n${itemList(items)}`;
}

/** Acknowledgement after a rejection; the recommendations are discarded. */
export function rejectionAcknowledgement(lang: ResolvedLang, honorific: Honorific): string {
  const ko = `알겠습니다, ${honorific}. 권장 조치는 보류하겠습니다. 다시 필요하시면 말씀해 주세요.`;
  const en = `Understood, ${honorific}. I've put the recommendations on hold. Just say the word if you need them again.`;
  return lang === "ko" ? ko : lang === "bilingual" ? `${en}\n—\n${ko}` : en;
}

/** Header line every framed audit reply starts with. */
export const AUDIT_HEADER = "■ 점검 결과";

/**
 * Appended when the model wrote a framed audit but forgot the approval line,
 * so the flow still reaches awaiting_approval. A reply asking the user what to
 * audit has no frame and gets no approval line.
 */
export function approvalRequestFooter(answer: string): string {
  if (!answer.includes(AUDIT_HEADER) || answer.includes(APPROVAL_MARKER)) return "";
  return `\n\n${APPROVAL_REQUEST_LINE}`;
}

/** Audit directive for the system prompt: the frame the reply must follow. */
export const AUDIT_FRAME = `Role: Mistake Audit Agent. Review what the user gave you (the text, plan, figures or work in their message and the recent conversation) for mistakes: factual errors, wrong numbers, inconsistencies, risky assumptions, missing steps, unclear wording.
After the emote tag, reply in exactly this frame and nothing else:
${AUDIT_HEADER} (Audit)
A one-line overall verdict.
Then one numbered item per finding, most important first, each on its own line:
1. 문제 / Issue — <what is wrong> · 원인 / Cause — <why> · 권장 조치 / Recommendation — <the concrete fix>
${APPROVAL_REQUEST_LINE}
If you find no mistakes, say so in the verdict, give numbered recommendations only for real improvements (or none), and still end with the approval line.
Do not invent mistakes. If there is nothing to audit in the message, ask the user to paste or describe what they want checked, and do not include the approval line.`;
