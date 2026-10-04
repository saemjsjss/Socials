import { describe, expect, it } from "vitest";
import {
  APPROVAL_MARKER,
  APPROVAL_REQUEST_LINE,
  approvalRequestFooter,
  auditState,
  executionConfirmation,
  extractRecommendations,
  isApproval,
  isMistakeAudit,
  isRejection,
  pendingAudit,
  rejectionAcknowledgement,
} from "@/lib/agents/audit-flow";
import type { ChatMessage } from "@/lib/types";

const AUDIT_REPLY = `■ 점검 결과 (Audit)
Two issues found.
1. 문제 / Issue — Total is 1,200 not 1,100 · 원인 / Cause — row 4 skipped · 권장 조치 / Recommendation — **re-add row 4**
2. 문제 / Issue — Date says 2025 · 원인 / Cause — old template · 권장 조치 / Recommendation — change to 2026
${APPROVAL_REQUEST_LINE}`;

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string): ChatMessage => ({ role: "assistant", content });

describe("isMistakeAudit", () => {
  it.each([
    "Can you do a mistake audit on this invoice?",
    "check my mistakes in this email",
    "Please review this for errors",
    "Audit my work: 3 x 4 = 13",
    "what did I do wrong here?",
    "이 보고서 실수 점검해줘",
    "오류 확인 부탁해요",
    "잘못된 점 찾아줘",
    "틀린 부분 있어?",
  ])("detects %j", (text) => {
    expect(isMistakeAudit(text)).toBe(true);
  });

  it.each(["Hello Jeannie", "감사해요!", "What's the weather in Seoul?", "Turn off the lights", "error 404 means what?"])(
    "ignores %j",
    (text) => {
      expect(isMistakeAudit(text)).toBe(false);
    },
  );
});

describe("approval and rejection replies", () => {
  it.each(["승인", "승인합니다", "네, 진행해 주세요", "진행하세요", "실행해", "approve", "Approved.", "go ahead", "Yes, proceed", "ok do it", "yes"])(
    "%j approves",
    (text) => {
      expect(isApproval(text)).toBe(true);
      expect(isRejection(text)).toBe(false);
    },
  );

  it.each(["취소", "보류해 주세요", "아니요", "cancel", "No.", "hold off", "not now"])("%j rejects", (text) => {
    expect(isRejection(text)).toBe(true);
    expect(isApproval(text)).toBe(false);
  });

  it.each(["approve the budget draft and email it to the whole finance team", "승인 절차가 어떻게 되나요?", "how do I approve a PR?", ""])(
    "%j is neither (a new request)",
    (text) => {
      expect(isApproval(text)).toBe(false);
      expect(isRejection(text)).toBe(false);
    },
  );
});

describe("state derived from history", () => {
  it("awaits approval right after an audit reply", () => {
    const history = [user("audit this"), assistant(AUDIT_REPLY), user("승인")];
    expect(AUDIT_REPLY).toContain(APPROVAL_MARKER);
    expect(auditState(history)).toBe("awaiting_approval");
    expect(pendingAudit(history)).toBe(AUDIT_REPLY);
  });

  it("is idle when the last assistant turn is not an audit, or another turn came in between", () => {
    expect(auditState([user("hi"), assistant("Hello, sir."), user("승인")])).toBe("idle");
    expect(auditState([user("audit"), assistant(AUDIT_REPLY), user("wait"), assistant("Sure."), user("approve")])).toBe("idle");
    expect(auditState([user("approve")])).toBe("idle");
    expect(auditState([user("audit"), assistant(AUDIT_REPLY)])).toBe("idle"); // latest turn must be the user's
  });
});

describe("recommendations and confirmations", () => {
  it("extracts the numbered items without markdown", () => {
    expect(extractRecommendations(AUDIT_REPLY)).toEqual([
      "문제 / Issue — Total is 1,200 not 1,100 · 원인 / Cause — row 4 skipped · 권장 조치 / Recommendation — re-add row 4",
      "문제 / Issue — Date says 2025 · 원인 / Cause — old template · 권장 조치 / Recommendation — change to 2026",
    ]);
    expect(extractRecommendations("no numbered lines")).toEqual([]);
  });

  it("confirms execution with the honorific and the approved items", () => {
    const ko = executionConfirmation("ko", "부장님", ["Fix row 4"]);
    expect(ko).toBe("네, 부장님. 승인하신 권장 조치를 진행하겠습니다. 완료되면 보고드리겠습니다.\n\n승인된 항목:\n1. Fix row 4");
    const en = executionConfirmation("en", "자기야", []);
    expect(en).toBe("Understood, 자기야. Proceeding with the approved recommendations. I'll report back when they're done.");
    const both = executionConfirmation("bilingual", "자기야", ["A"]);
    expect(both).toContain("Understood, 자기야.");
    expect(both).toContain("네, 자기야.");
    expect(both).toContain("Approved items / 승인된 항목:\n1. A");
  });

  it("acknowledges a rejection", () => {
    expect(rejectionAcknowledgement("ko", "부장님")).toContain("알겠습니다, 부장님. 권장 조치는 보류하겠습니다.");
    expect(rejectionAcknowledgement("en", "자기야")).toContain("Understood, 자기야. I've put the recommendations on hold.");
  });

  it("adds the approval request only to framed audits that forgot it", () => {
    const withoutLine = AUDIT_REPLY.replace(APPROVAL_REQUEST_LINE, "").trim();
    expect(approvalRequestFooter(withoutLine)).toBe(`\n\n${APPROVAL_REQUEST_LINE}`);
    expect(approvalRequestFooter(AUDIT_REPLY)).toBe("");
    expect(approvalRequestFooter("Please paste the text you want me to check, sir.")).toBe("");
    expect(approvalRequestFooter("")).toBe("");
  });
});
