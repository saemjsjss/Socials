import { describe, expect, it } from "vitest";
import {
  containsHangul,
  dataUrlByteLength,
  decodeHeaderJson,
  detectLanguage,
  encodeHeaderJson,
  isImageDataUrl,
  resolveLanguage,
  stripMarkdownForSpeech,
  timingSafeEqual,
  truncate,
} from "@/lib/utils";

describe("language detection", () => {
  it("detects Korean and English", () => {
    expect(detectLanguage("안녕하세요, 오늘 일정 알려줘")).toBe("ko");
    expect(detectLanguage("What's on my calendar today?")).toBe("en");
    expect(detectLanguage("")).toBe("en");
  });

  it("weighs mixed text by content", () => {
    expect(detectLanguage("Jennie 노래 추천해줘")).toBe("ko");
    expect(detectLanguage("Can you explain the word 사랑 in a long English sentence?")).toBe("en");
  });

  it.each([
    "React useEffect 설명해줘",
    "JavaScript Promise 설명해줘",
    "Next.js App Router 사용법",
    "iPhone 15 Pro Max 가격 알려줘",
    "Samsung Galaxy S24 Ultra 리뷰 보여줘",
    "The Great Gatsby 줄거리 알려줘",
    "Call on Me 가사 알려줘",
  ])("reads Korean with English terms as Korean: %j", (text) => {
    expect(detectLanguage(text)).toBe("ko");
    expect(resolveLanguage("auto", text)).toBe("ko");
  });

  it.each([
    "Can you explain the word 사랑 in a long English sentence?",
    "How do you say hello in Korean? 안녕하세요",
    "What does 사랑해요 여보 mean?",
    "Thank you is 감사합니다 in Korean.",
    "I love this song: 봄날",
  ])("reads English that mentions Korean as English: %j", (text) => {
    expect(detectLanguage(text)).toBe("en");
  });

  it("containsHangul sees jamo and syllables", () => {
    expect(containsHangul("ㅋㅋ")).toBe(true);
    expect(containsHangul("hello")).toBe(false);
  });

  it("resolves HUD language modes", () => {
    expect(resolveLanguage("en", "안녕")).toBe("en");
    expect(resolveLanguage("ko", "hello")).toBe("ko");
    expect(resolveLanguage("bilingual", "hello")).toBe("bilingual");
    expect(resolveLanguage("auto", "안녕하세요")).toBe("ko");
    expect(resolveLanguage(undefined, "hello")).toBe("en");
    expect(resolveLanguage("auto", "Answer bilingually: what is kimchi?")).toBe("bilingual");
    expect(resolveLanguage("auto", "영어와 한국어로 설명해줘")).toBe("bilingual");
  });

  it.each([
    ["Explain photosynthesis in English and Korean", "bilingual"],
    ["Explain photosynthesis in both English and Korean", "bilingual"],
    ["광합성 한영으로 설명해줘", "bilingual"],
    ["한/영 병기로 요약해줘", "bilingual"],
    ["Answer in Korean: what is photosynthesis?", "ko"],
    ["Please reply in Korean. What is kimchi?", "ko"],
    ["Explain black holes in Korean", "ko"],
    ["영어로 대답해줘: 광합성이 뭐야?", "en"],
    ["영어로 설명해줘 광합성", "en"],
    ["Respond in English: 김치가 뭐야?", "en"],
    ["Tell me how to say thank you in Korean", "en"],
    ["Explain how to say thank you in Korean", "en"],
    ["한영사전 추천해줘", "ko"],
    ["광합성 영어로 뭐야?", "ko"],
  ])("honours a language request in auto mode: %j → %s", (text, lang) => {
    expect(resolveLanguage("auto", text)).toBe(lang);
    expect(resolveLanguage(undefined, text)).toBe(lang);
  });

  it("lets an explicit HUD mode win over a request in the message", () => {
    expect(resolveLanguage("en", "Answer in Korean: what is kimchi?")).toBe("en");
    expect(resolveLanguage("ko", "Explain photosynthesis in English and Korean")).toBe("ko");
    expect(resolveLanguage("bilingual", "영어로 대답해줘")).toBe("bilingual");
  });

  it("takes the latest earlier turn with words for an empty or image-only turn", () => {
    expect(resolveLanguage("auto", "", ["Hello", "사진 보낼게요"])).toBe("ko");
    expect(resolveLanguage("auto", "📷", ["사진 보낼게요", "  "])).toBe("ko");
    expect(resolveLanguage("auto", "https://example.com/cat.png", ["고양이 사진이야"])).toBe("ko");
    expect(resolveLanguage("auto", "", ["사진 보낼게요", "Here it comes"])).toBe("en");
    expect(resolveLanguage("auto", "")).toBe("en");
    expect(resolveLanguage("auto", "안녕", ["Hello"])).toBe("ko");
  });
});

describe("header JSON encoding", () => {
  it("round-trips non-ASCII values as ASCII", () => {
    const value = [{ title: "서울 날씨 · Seoul weather", url: "https://example.com/?q=서울" }];
    const encoded = encodeHeaderJson(value);
    expect(encoded).toMatch(/^[A-Za-z0-9+/=]+$/);
    expect(decodeHeaderJson(encoded)).toEqual(value);
  });

  it("returns null for missing or garbage input", () => {
    expect(decodeHeaderJson(null)).toBeNull();
    expect(decodeHeaderJson("%%%")).toBeNull();
  });
});

describe("helpers", () => {
  it("truncate adds an ellipsis only when needed", () => {
    expect(truncate("short", 10)).toBe("short");
    expect(truncate("a long sentence here", 8)).toBe("a long…");
  });

  it("timingSafeEqual compares exactly", () => {
    expect(timingSafeEqual("secret", "secret")).toBe(true);
    expect(timingSafeEqual("secret", "secreT")).toBe(false);
    expect(timingSafeEqual("secret", "secret2")).toBe(false);
    expect(timingSafeEqual("", "")).toBe(true);
  });

  it("stripMarkdownForSpeech removes markup and URLs", () => {
    const md = "## Briefing\n- **Seoul**: 21°C [source](https://x.com)\n```js\ncode()\n```\nSee https://example.com";
    expect(stripMarkdownForSpeech(md)).toBe("Briefing Seoul: 21°C source See");
  });

  it("validates image data URLs", () => {
    expect(isImageDataUrl("data:image/png;base64,iVBORw0KGgo=")).toBe(true);
    expect(isImageDataUrl("data:text/html;base64,PGgxPg==")).toBe(false);
    expect(isImageDataUrl("https://example.com/cat.png")).toBe(false);
    expect(dataUrlByteLength("data:image/png;base64,AAAA")).toBe(3);
  });
});
