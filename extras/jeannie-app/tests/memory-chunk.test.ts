import { describe, expect, it } from "vitest";
import { chunkJsonl, chunkMarkdown, documentTitle, findSecrets, memoryKindFor, searchTerms } from "@/lib/memory/chunk";

const PROFILE = `# Who I Am — Saemur Rahman

*A personal + work profile.*

## Myself
- **Name:** Saemur Rahman
- **Lives in:** Dhaka

## My work

### 1. Manager — Hangeul
- **HGLC — Hangeul Global Learning Center** *(Office 2)* — 10th Floor, Green Landmark, Kalabagan.

\`\`\`
# not a heading inside a code fence
\`\`\`

#### Details stay inside their section
- 21-PC lab
`;

describe("memoryKindFor / documentTitle", () => {
  it("accepts markdown, text and JSON Lines only", () => {
    expect(memoryKindFor("profile.md")).toBe("markdown");
    expect(memoryKindFor("NOTES.MARKDOWN")).toBe("markdown");
    expect(memoryKindFor("a.txt")).toBe("markdown");
    expect(memoryKindFor("saemur-knowledge.jsonl")).toBe("jsonl");
    expect(memoryKindFor("x.pdf")).toBeNull();
    expect(memoryKindFor("x.json")).toBeNull();
  });

  it("titles a document by its first H1, else by its file name", () => {
    expect(documentTitle("profile.md", PROFILE, "markdown")).toBe("Who I Am — Saemur Rahman");
    expect(documentTitle("notes/todo.md", "no heading", "markdown")).toBe("todo");
    expect(documentTitle("k.jsonl", "{}", "jsonl")).toBe("k");
  });
});

describe("chunkMarkdown", () => {
  it("makes one chunk per section with its heading path", () => {
    const chunks = chunkMarkdown(PROFILE);
    expect(chunks.map((c) => c.heading)).toEqual([
      "Who I Am — Saemur Rahman",
      "Who I Am — Saemur Rahman › Myself",
      "Who I Am — Saemur Rahman › My work › 1. Manager — Hangeul",
    ]);
    const work = chunks[2].content;
    expect(work).toContain("Green Landmark");
    expect(work).toContain("# not a heading inside a code fence");
    expect(work).toContain("#### Details stay inside their section");
    expect(chunks.map((c) => c.ord)).toEqual([0, 1, 2]);
  });

  it("splits long sections near the size cap and keeps every word", () => {
    const paragraph = "한글 센터는 칼라바간에 있습니다. ".repeat(40).trim();
    const body = `## Long\n\n${Array.from({ length: 6 }, () => paragraph).join("\n\n")}`;
    const chunks = chunkMarkdown(body, 1_500);
    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) {
      expect(chunk.content.length).toBeLessThanOrEqual(1_500);
      expect(chunk.heading).toBe("Long");
    }
    const words = (s: string) => s.split(/\s+/).filter(Boolean).length;
    expect(chunks.reduce((n, c) => n + words(c.content), 0)).toBe(words(body) - 2); // minus "##" and "Long"
  });

  it("hard-splits a single line longer than the cap", () => {
    const chunks = chunkMarkdown("x".repeat(3_200), 1_500);
    expect(chunks.map((c) => c.content.length)).toEqual([1_500, 1_500, 200]);
  });

  it("drops YAML front matter and empty sections", () => {
    expect(chunkMarkdown("---\ntitle: x\n---\n# A\n\n## B\ntext")).toEqual([{ ord: 0, heading: "A › B", content: "text" }]);
  });
});

describe("chunkJsonl", () => {
  const record = {
    id: "org-005-hglc-overview",
    type: "organization",
    title: "HGLC - Hangeul Global Learning Center (Office 2)",
    text: "HGLC (Hangeul Global Learning Center) is Office 2 at Green Landmark, Kalabagan.",
    tags: ["hglc", "office-2", "kalabagan", 7],
    entity: "HGLC",
    updated: "2026-09-28",
  };

  it("maps each record to one chunk and reports bad lines by number", () => {
    const text = [
      JSON.stringify(record),
      "",
      "{not json",
      JSON.stringify({ id: "x" }),
      JSON.stringify({ text: "no id" }),
      JSON.stringify(record),
      "[1,2]",
      JSON.stringify({ id: "note-1", text: "Short note." }),
    ].join("\n");
    const { chunks, issues } = chunkJsonl(text);
    expect(chunks).toEqual([
      {
        ord: 0,
        heading: record.title,
        content: record.text,
        record_id: record.id,
        type: "organization",
        entity: "HGLC",
        tags: ["hglc", "office-2", "kalabagan"],
      },
      { ord: 1, heading: "note-1", content: "Short note.", record_id: "note-1", type: undefined, entity: undefined, tags: [] },
    ]);
    expect(issues).toEqual([
      { line: 3, message: "not valid JSON" },
      { line: 4, message: 'missing "text"' },
      { line: 5, message: 'missing "id"' },
      { line: 6, message: 'duplicate id "org-005-hglc-overview"' },
      { line: 7, message: "not a JSON object" },
    ]);
  });
});

describe("findSecrets", () => {
  it.each([
    ["DeepSeek-style key", "key sk-0000000000000000000000fakekey00"],
    ["ElevenLabs-style key", "sk_000000000000000000000000000000000000000fakekey0"],
    ["Supabase secret", "sb_secret_abcdefghijklmnopqrstu"],
    ["JWT", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abcdefghijklmnopqrstuv"],
    ["GitHub token", "ghp_abcdefghijklmnopqrstuvwxyz0123"],
    ["private key", "-----BEGIN RSA PRIVATE KEY-----"],
    ["passport number", "Passport no: A01234567"],
    ["NID", "NID 19971234567890123"],
  ])("flags a %s", (_label, text) => {
    expect(findSecrets(text).length).toBeGreaterThan(0);
  });

  it("lets the profile's safe facts through", () => {
    expect(findSecrets(PROFILE)).toEqual([]);
    expect(findSecrets("| Passport | valid to 08 Apr 2035 |\nLicense valid to 30 Jun 2027. Office 1209.")).toEqual([]);
  });
});

describe("searchTerms", () => {
  it("drops stopwords and punctuation", () => {
    expect(searchTerms("Where is HGLC located?")).toEqual(["hglc", "located"]);
    expect(searchTerms("Who is my CEO?")).toEqual(["ceo"]);
    expect(searchTerms("What's A S M Traders' license?")).toEqual(["traders", "license"]);
  });

  it("splits scripts and strips Korean particles", () => {
    expect(searchTerms("HGLC는 어디에 있어?")).toEqual(["hglc"]);
    expect(searchTerms("한글센터에서 수업은 언제야")).toEqual(["한글센터", "수업"]);
    expect(searchTerms("칼라바간의 사무실")).toEqual(["칼라바간", "사무실"]);
  });

  it("keeps hyphenated tags as separate prefix terms and caps the count", () => {
    expect(searchTerms("office-2 hangeul.com.bd")).toEqual(["office", "hangeul", "com", "bd"]);
    expect(searchTerms(Array.from({ length: 30 }, (_, i) => `term${i}`).join(" "))).toHaveLength(12);
    expect(searchTerms("?? !!")).toEqual([]);
  });
});
