import { describe, expect, it } from "vitest";
import { formatSearchBriefing } from "@/lib/agents/search-agent";
import { planFor, renderAnswer, runPlan } from "@/lib/hangeul/answer";
import { readersFromRecords } from "@/lib/hangeul/memory-readers";
import { NOW, records, runs, TZ } from "./hangeul-fixtures";
import { clipAtSentence, HANGEUL_SPOKEN_LINE, SPEECH_MAX_CHARS, speechSegments, spokenText } from "@/lib/client/speech-text";
import type { SearchResponse } from "@/lib/types";

const spoken = (text: string, lang: Parameters<typeof speechSegments>[1] = "en") =>
  speechSegments(text, lang)
    .map((s) => s.text)
    .join(" ");

const results: SearchResponse = {
  query: "latest news on the Mars mission today",
  provider: "duckduckgo",
  results: [
    { title: "Mars: News & Features - NASA Science", url: "https://science.nasa.gov/mars/stories/", snippet: "Get the latest news releases.", source: "duckduckgo" },
    { title: "Mars news - CBS News", url: "https://www.cbsnews.com/tag/mars/", snippet: "NASA's latest mission to Mars.", source: "duckduckgo" },
  ],
};

describe("speechSegments: what is read aloud", () => {
  it("reads short replies unchanged", () => {
    expect(speechSegments("Yes, it is done.", "en")).toEqual([{ text: "Yes, it is done.", lang: "en" }]);
    expect(speechSegments("네, 처리되었습니다.", "ko")).toEqual([{ text: "네, 처리되었습니다.", lang: "ko" }]);
  });

  it("never reads the raw results of an offline search", () => {
    const dump = `Here's what the live web says (no language model is connected, so these are the raw results):\n\n${formatSearchBriefing(results)}`;
    const text = spoken(dump);
    expect(text).toBe("Here's what the live web says (no language model is connected, so these are the raw results).");
    expect(text).not.toMatch(/https?:|www\.|\[\d\]|NASA|DuckDuckGo/);
  });

  it("drops the sources footer and inline citations of an answer", () => {
    const answer =
      "NASA's Perseverance rover found new rock samples this week [1]. The next launch window opens in 2026 [2].\n\nSources:\n[1] NASA — https://science.nasa.gov/mars/\n[2] CBS — https://www.cbsnews.com/tag/mars/";
    expect(spoken(answer)).toBe("NASA's Perseverance rover found new rock samples this week. The next launch window opens in 2026.");
    const bilingual = "Seoul is sunny today [1].\n—\n오늘 서울은 맑아요 [1].\n\nSources / 출처:\n[1] KMA — https://www.weather.go.kr/";
    expect(speechSegments(bilingual, "bilingual")).toEqual([
      { text: "Seoul is sunny today.", lang: "en" },
      { text: "오늘 서울은 맑아요.", lang: "ko" },
    ]);
    expect(spoken("Answer here.\n\n**Sources:**\n1. [NASA](https://nasa.gov)")).toBe("Answer here.");
  });

  it("removes URLs anywhere in the text", () => {
    expect(spoken("See https://example.com/a?b=c and www.example.org for more.")).toBe("See and for more.");
    expect(spoken("Read [the guide](https://example.com/guide) first.")).toBe("Read the guide first.");
  });

  async function hangeulAnswer(question: string, lang: "en" | "ko" | "bilingual") {
    const plan = planFor(question, { today: "2026-09-30", now: NOW, timeZone: TZ });
    const result = await runPlan(plan, readersFromRecords({ records: records(), runs: runs() }), { now: NOW, timeZone: TZ });
    return renderAnswer(result, lang, { now: NOW, timeZone: TZ });
  }

  it("reads a Hangeul answer as its headline and notes, not the fact and table bullets or the as-of line", async () => {
    const en = spoken(await hangeulAnswer("how many consultancies were closed today?", "en"));
    expect(en).toMatch(/^Consultancies done today \(30 Sep\): 20 — TEST CONSULTANT C 8/);
    expect(en).toContain("Requests received today (30 Sep): 10 (Consulted 6, New 4).");
    expect(en).not.toMatch(/Files opened: 5|By consultant|As of|•/);

    const ko = spoken(await hangeulAnswer("오늘 상담 몇 건 끝났어?", "ko"), "ko");
    expect(ko).toMatch(/^오늘\(9월 30일\) 상담 완료: 20/);
    expect(ko).not.toMatch(/기준:|•/);

    const both = speechSegments(await hangeulAnswer("how many consultancies were closed today?", "bilingual"), "bilingual");
    expect(both.map((s) => s.lang)).toEqual(["en", "ko"]);
  });

  it("a Hangeul reply is never sent to the voice engines: a fixed line is spoken, no student name or id", async () => {
    // The student card's headline would be "TEST STUDENT ONE (HNG-2026-012, portal uid 101): Documents Verified."
    const card = await hangeulAnswer("Who is HNG-2026-12?", "en");
    expect(card).toContain("TEST STUDENT ONE (HNG-2026-012, portal uid 101)");
    for (const lang of ["en", "ko", "bilingual"] as const) {
      const text = await hangeulAnswer("Who is HNG-2026-12?", lang);
      const said = speechSegments(spokenText(text, "hangeul", lang), lang).map((s) => s.text).join(" ");
      for (const secret of ["TEST STUDENT", "HNG-2026", "101", "A00000001", "01700000001", "TEST CONSULTANT"]) expect(said).not.toContain(secret);
    }
    expect(speechSegments(spokenText(card, "hangeul", "en"), "en")).toEqual([{ text: HANGEUL_SPOKEN_LINE.en, lang: "en" }]);
    expect(speechSegments(spokenText(card, "hangeul", "ko"), "ko")).toEqual([{ text: HANGEUL_SPOKEN_LINE.ko, lang: "ko" }]);
    expect(speechSegments(spokenText(card, "hangeul", "bilingual"), "bilingual").map((s) => s.text)).toEqual([HANGEUL_SPOKEN_LINE.en, HANGEUL_SPOKEN_LINE.ko]);
    // The owner's question: every consultant's name is in its headline.
    const owner = await hangeulAnswer("how many consultancies were closed today?", "en");
    expect(spokenText(owner, "hangeul", "en")).not.toContain("TEST CONSULTANT");
    // Every other agent's reply is spoken as before.
    expect(spokenText("Seoul is sunny today.", "search", "en")).toBe("Seoul is sunny today.");
    expect(spokenText("Yes, it is done.", null, "en")).toBe("Yes, it is done.");
  });

  it("reads a Hangeul data-status answer without its run table", async () => {
    const text = spoken(await hangeulAnswer("Is the Hangeul portal up?", "en"));
    expect(text).toMatch(/^Hangeul BOT reads the portal/);
    expect(text).not.toMatch(/Finished|portal sync:|17:58/);
  });

  it("ends every spoken line as a sentence, once", () => {
    expect(spoken("Status report (demo)\n- first item\n- second item.\n(Already done.)")).toBe(
      "Status report (demo). first item. second item. (Already done.)",
    );
  });

  it("says configuration names as words and skips lists of them", () => {
    expect(spoken("Set OPENAI_API_KEY and I'll be online.")).toBe("Set OPENAI API KEY and I'll be online.");
    expect(spoken("The Hangeul data isn't connected (SUPABASE_URL, SUPABASE_SECRET_KEY), so ask again later.")).toBe(
      "The Hangeul data isn't connected, so ask again later.",
    );
  });

  it(`caps a long answer at ${SPEECH_MAX_CHARS} characters on a sentence boundary`, () => {
    const sentence = "Photosynthesis turns light, water and carbon dioxide into sugar and oxygen. ";
    const segments = speechSegments(sentence.repeat(30), "en");
    expect(segments).toHaveLength(1);
    expect(segments[0].text.length).toBeLessThanOrEqual(SPEECH_MAX_CHARS);
    expect(segments[0].text.length).toBeGreaterThan(SPEECH_MAX_CHARS * 0.8);
    expect(segments[0].text.endsWith("oxygen.")).toBe(true);

    const ko = "광합성은 빛과 물과 이산화탄소를 이용해 포도당과 산소를 만드는 과정이에요. ".repeat(30);
    const koText = speechSegments(ko, "ko")[0].text;
    expect(koText.length).toBeLessThanOrEqual(SPEECH_MAX_CHARS);
    expect(koText.endsWith("과정이에요.")).toBe(true);
  });

  it("shares the cap between the halves of a bilingual answer", () => {
    const en = "The weather in Seoul is clear with a light breeze this afternoon. ".repeat(20).trim();
    const ko = "오늘 오후 서울 날씨는 맑고 바람이 약하게 불어요. ".repeat(20).trim();
    const segments = speechSegments(`${en}\n—\n${ko}`, "bilingual");
    expect(segments.map((s) => s.lang)).toEqual(["en", "ko"]);
    const total = segments.reduce((n, s) => n + s.text.length, 0);
    expect(total).toBeLessThanOrEqual(SPEECH_MAX_CHARS);
    for (const s of segments) expect(s.text.length).toBeGreaterThan(SPEECH_MAX_CHARS * 0.3);

    // A short half keeps all of its text; the long half gets the rest.
    const shortKo = speechSegments(`${en}\n—\n좋아요.`, "bilingual");
    expect(shortKo[1].text).toBe("좋아요.");
    expect(shortKo[0].text.length).toBeGreaterThan(SPEECH_MAX_CHARS * 0.8);
  });

  it("stays fast on hostile whitespace", () => {
    const started = performance.now();
    speechSegments(`a${" ".repeat(20_000)}(b${"\t".repeat(20_000)}[1]`, "en");
    speechSegments("\n".repeat(20_000), null);
    speechSegments(`${"[".repeat(20_000)}x`, "en");
    speechSegments(`${"-\n".repeat(10_000)}`, null);
    expect(performance.now() - started).toBeLessThan(200);
  });
});

describe("clipAtSentence", () => {
  it("keeps text within the limit untouched", () => {
    expect(clipAtSentence("Short. Text.", 50)).toBe("Short. Text.");
  });

  it("does not cut inside a number", () => {
    expect(clipAtSentence("Growth was 3.5 percent in total across all the regions we tracked", 30)).toBe(
      "Growth was 3.5 percent in…",
    );
  });

  it("falls back to a word boundary for one long sentence", () => {
    const clipped = clipAtSentence("word ".repeat(200), 100);
    expect(clipped.length).toBeLessThanOrEqual(100);
    expect(clipped.endsWith("word…")).toBe(true);
  });
});
