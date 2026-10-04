import { afterEach, describe, expect, it, vi } from "vitest";
import { checkPublicUrl, decodeEntities, htmlToText, MAX_READ_CHARS, parseJinaText, readUrl } from "@/lib/agents/read-url";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("checkPublicUrl", () => {
  it.each(["https://example.com/a?b=1", "http://news.example.co.kr/", "https://example.com:443/", "http://8.8.8.8/", "http://192.0.78.9/", "https://[2606:4700::1111]/"])(
    "allows %s",
    (url) => {
      expect(checkPublicUrl(url)).toHaveProperty("url");
    },
  );

  it.each([
    ["ftp://example.com/", /http and https/],
    ["file:///etc/passwd", /http and https/],
    ["javascript:alert(1)", /http and https/],
    ["https://user:pass@example.com/", /credentials/],
    ["https://example.com:8080/", /standard ports/],
    ["http://localhost/", /Local/],
    ["http://api.localhost/", /Local/],
    ["http://printer.local/", /Local/],
    ["http://intranet/", /Local/],
    ["http://127.0.0.1/", /Private/],
    ["http://2130706433/", /Private/], // 127.0.0.1 as a decimal
    ["http://0x7f.1/", /Private/],
    ["http://10.1.2.3/", /Private/],
    ["http://172.20.0.1/", /Private/],
    ["http://192.168.1.1/", /Private/],
    ["http://169.254.169.254/latest/meta-data", /Private/],
    ["http://100.64.0.1/", /Private/],
    ["http://0.0.0.0/", /Private/],
    ["http://[::1]/", /Private/],
    ["http://[::ffff:127.0.0.1]/", /Private/],
    ["http://[fd00::1]/", /Private/],
    ["http://[fe80::1]/", /Private/],
    ["http://[::ffff:a9fe:a9fe]/", /Private/], // 169.254.169.254, hex form
    ["http://[64:ff9b::a9fe:a9fe]/", /Private/], // NAT64
    ["http://[2002:7f00:1::]/", /Private/], // 6to4
    ["http://[fec0::1]/", /Private/],
    ["http://192.0.0.8/", /Private/],
    ["http://localhost./", /Local/],
    ["not a url", /valid URL/],
  ])("refuses %s", (url, reason) => {
    const result = checkPublicUrl(url);
    expect(result).toHaveProperty("error");
    expect((result as { error: string }).error).toMatch(reason);
  });
});

describe("HTML to text", () => {
  it("keeps the title and readable body, drops scripts, styles and navigation", () => {
    const html = `<!doctype html><html><head><title>Seoul &amp; Busan</title><style>p{}</style></head>
      <body><nav>Home | About</nav><script>alert(1)</script>
      <h1>Travel</h1><p>Seoul is the&nbsp;capital.<br>Busan is by the sea.</p>
      <ul><li>Food</li><li>K&#8209;pop &#x2764;</li></ul><footer>© 2026</footer></body></html>`;
    const { title, text } = htmlToText(html);
    expect(title).toBe("Seoul & Busan");
    expect(text).toBe("Travel\n\nSeoul is the capital.\nBusan is by the sea.\n\n• Food\n• K‑pop ❤");
  });

  it("decodes entities and leaves unknown ones", () => {
    expect(decodeEntities("&lt;b&gt; &quot;hi&quot; &#39;x&#39; &bogus; &#0;")).toBe("<b> \"hi\" 'x' &bogus; &#0;");
  });

  it("parses Jina Reader's plain-text format", () => {
    expect(parseJinaText("Title: Hello\n\nURL Source: https://example.com\n\nMarkdown Content:\n# Hi\nBody")).toEqual({
      title: "Hello",
      text: "# Hi\nBody",
    });
    expect(parseJinaText("just text")).toEqual({ title: null, text: "just text" });
  });
});

describe("readUrl", () => {
  it("uses Jina Reader first", async () => {
    const fetchMock = vi.fn(async () => new Response("Title: Example\n\nMarkdown Content:\nHello world"));
    vi.stubGlobal("fetch", fetchMock);
    const result = await readUrl("https://example.com/page");
    expect(result).toEqual({ url: "https://example.com/page", title: "Example", text: "Hello world", truncated: false, via: "jina" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://r.jina.ai/https://example.com/page");
    expect(new Headers(init.headers).get("accept")).toBe("text/plain");
  });

  it("falls back to its own fetch and HTML stripping when Jina fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).startsWith("https://r.jina.ai/")
        ? new Response("rate limited", { status: 429 })
        : new Response("<html><title>Direct</title><body><p>From the page</p></body></html>", {
            headers: { "content-type": "text/html; charset=utf-8" },
          }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await readUrl("https://example.com/")).toEqual({
      url: "https://example.com/",
      title: "Direct",
      text: "From the page",
      truncated: false,
      via: "direct",
    });
  });

  it("checks every redirect hop of its own fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).startsWith("https://r.jina.ai/")
          ? new Response("", { status: 500 })
          : new Response(null, { status: 302, headers: { location: "http://169.254.169.254/latest" } }),
      ),
    );
    const result = await readUrl("https://example.com/");
    expect(result).toEqual({ url: "https://example.com/", error: expect.stringMatching(/Redirected to a blocked address/) });
  });

  it("caps the text at 12k characters", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(`Markdown Content:\n${"a".repeat(MAX_READ_CHARS + 500)}`)));
    const result = await readUrl("https://example.com/");
    expect(result).toMatchObject({ truncated: true });
    expect((result as { text: string }).text).toHaveLength(MAX_READ_CHARS + 1); // plus the ellipsis
  });

  it("refuses blocked URLs without any network call, and never throws", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await readUrl("http://localhost:3000/api")).toHaveProperty("error");
    expect(fetchMock).not.toHaveBeenCalled();

    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network down"))));
    expect(await readUrl("https://example.com/")).toEqual({ url: "https://example.com/", error: "Could not fetch the page." });
  });

  it("rejects binary content types", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).startsWith("https://r.jina.ai/")
          ? new Response("", { status: 500 })
          : new Response("PK", { headers: { "content-type": "application/zip" } }),
      ),
    );
    expect(await readUrl("https://example.com/file.zip")).toEqual({
      url: "https://example.com/file.zip",
      error: "Unsupported content type (application/zip).",
    });
  });
});
