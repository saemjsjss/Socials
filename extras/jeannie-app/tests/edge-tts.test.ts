import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import { WebSocketServer, type WebSocket } from "ws";
import {
  buildEdgeTtsUrl,
  buildSpeechConfigMessage,
  buildSsml,
  buildSsmlMessage,
  dateToString,
  EdgeTtsError,
  escapeXml,
  expandVoiceName,
  generateSecMsGec,
  getClockSkewMs,
  parseBinaryFrame,
  parseTextFrame,
  removeIncompatibleCharacters,
  resetClockSkew,
  SEC_MS_GEC_VERSION,
  splitTextByBytes,
  synthesizeEdgeTts,
  TRUSTED_CLIENT_TOKEN,
} from "@/lib/agents/edge-tts";

const utf8Bytes = (text: string) => Buffer.byteLength(text, "utf8");

function binaryFrame(headers: string, payload: Uint8Array = new Uint8Array()): Buffer {
  const head = Buffer.from(headers, "utf8");
  const out = Buffer.alloc(2 + head.length + payload.length);
  out.writeUInt16BE(head.length, 0);
  head.copy(out, 2);
  Buffer.from(payload).copy(out, 2 + head.length);
  return out;
}

describe("SSML", () => {
  it("escapes XML special characters", () => {
    expect(escapeXml(`Tom & Jerry <b>"hi"</b> it's`)).toBe(
      "Tom &amp; Jerry &lt;b&gt;&quot;hi&quot;&lt;/b&gt; it&apos;s",
    );
    expect(escapeXml("안녕하세요")).toBe("안녕하세요");
  });

  it("expands short voice names like the reference client", () => {
    expect(expandVoiceName("en-US-JennyNeural")).toBe(
      "Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)",
    );
    expect(expandVoiceName("ko-KR-SunHiNeural")).toBe(
      "Microsoft Server Speech Text to Speech Voice (ko-KR, SunHiNeural)",
    );
    expect(expandVoiceName("zh-CN-liaoning-XiaobeiNeural")).toBe(
      "Microsoft Server Speech Text to Speech Voice (zh-CN-liaoning, XiaobeiNeural)",
    );
    const full = "Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)";
    expect(expandVoiceName(full)).toBe(full);
    expect(() => expandVoiceName("Jenny")).toThrow(EdgeTtsError);
  });

  it("builds SSML with Jeannie's default prosody (slightly lower pitch)", () => {
    expect(buildSsml({ text: "Hello", voice: "en-US-JennyNeural" })).toBe(
      "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
        "<voice name='Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)'>" +
        "<prosody pitch='-2Hz' rate='+0%' volume='+0%'>Hello</prosody></voice></speak>",
    );
  });

  it("escapes the text and applies custom prosody", () => {
    const ssml = buildSsml({
      text: "A < B & 'C'",
      voice: "ko-KR-SunHiNeural",
      rate: "-5%",
      pitch: "+0Hz",
      volume: "+10%",
    });
    expect(ssml).toContain("<prosody pitch='+0Hz' rate='-5%' volume='+10%'>A &lt; B &amp; &apos;C&apos;</prosody>");
    expect(ssml).toContain("(ko-KR, SunHiNeural)");
  });

  it("rejects malformed prosody values", () => {
    expect(() => buildSsml({ text: "x", voice: "en-US-JennyNeural", rate: "fast" })).toThrow(/rate/);
    expect(() => buildSsml({ text: "x", voice: "en-US-JennyNeural", pitch: "-2%" })).toThrow(/pitch/);
    expect(() => buildSsml({ text: "x", voice: "en-US-JennyNeural", volume: "10%" })).toThrow(/volume/);
  });

  it("replaces control characters the service rejects", () => {
    expect(removeIncompatibleCharacters("a\u000Bb\u0000c\td\ne\rf")).toBe("a b c\td\ne\rf");
  });
});

describe("protocol messages", () => {
  const date = new Date(Date.UTC(2026, 8, 27, 8, 5, 9));

  it("formats timestamps like JavaScript Date.toString() in UTC", () => {
    expect(dateToString(date)).toBe("Sun Sep 27 2026 08:05:09 GMT+0000 (Coordinated Universal Time)");
    expect(dateToString(new Date(Date.UTC(2026, 0, 3, 23, 59, 1)))).toBe(
      "Sat Jan 03 2026 23:59:01 GMT+0000 (Coordinated Universal Time)",
    );
  });

  it("builds speech.config with MP3 output and boundaries disabled", () => {
    const message = buildSpeechConfigMessage(date);
    const { headers, body } = parseTextFrame(message);
    expect(headers).toEqual({
      "X-Timestamp": "Sun Sep 27 2026 08:05:09 GMT+0000 (Coordinated Universal Time)",
      "Content-Type": "application/json; charset=utf-8",
      Path: "speech.config",
    });
    expect(JSON.parse(body)).toEqual({
      context: {
        synthesis: {
          audio: {
            metadataoptions: { sentenceBoundaryEnabled: "false", wordBoundaryEnabled: "false" },
            outputFormat: "audio-24khz-48kbitrate-mono-mp3",
          },
        },
      },
    });
  });

  it("builds the ssml message with the trailing-Z timestamp quirk", () => {
    expect(buildSsmlMessage("abc123", "<speak/>", date)).toBe(
      "X-RequestId:abc123\r\nContent-Type:application/ssml+xml\r\n" +
        "X-Timestamp:Sun Sep 27 2026 08:05:09 GMT+0000 (Coordinated Universal Time)Z\r\n" +
        "Path:ssml\r\n\r\n<speak/>",
    );
  });

  it("builds the WSS URL with token, connection id and Sec-MS-GEC", () => {
    const now = 1_790_000_123_456;
    const url = new URL(buildEdgeTtsUrl(now));
    expect(url.origin + url.pathname).toBe(
      "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1",
    );
    expect(url.searchParams.get("TrustedClientToken")).toBe(TRUSTED_CLIENT_TOKEN);
    expect(url.searchParams.get("ConnectionId")).toMatch(/^[0-9a-f]{32}$/);
    expect(url.searchParams.get("Sec-MS-GEC")).toBe(generateSecMsGec(now));
    expect(url.searchParams.get("Sec-MS-GEC-Version")).toBe(SEC_MS_GEC_VERSION);
    expect(SEC_MS_GEC_VERSION).toMatch(/^1-\d+\.\d+\.\d+\.\d+$/);
  });
});

describe("generateSecMsGec", () => {
  // Expected values computed with the reference algorithm (edge_tts/drm.py) in python3 hashlib.
  it("matches the Python reference for fixed timestamps", () => {
    const window = "8FD81A00C2EAEDB004963D5A0BD37C00DAF969A0A8FB3B08C469C9BEF94498F2";
    expect(generateSecMsGec(1_790_000_123_456)).toBe(window);
    expect(generateSecMsGec(1_790_000_100_000)).toBe(window); // window start
    expect(generateSecMsGec(1_790_000_399_999)).toBe(window); // window end
    expect(generateSecMsGec(1_790_000_400_000)).toBe(
      "86E3273C389E59197FFD4FFFC8B8B8B37AE81B7AC9D8931EDC637E707E3EE153",
    );
    expect(generateSecMsGec(1_790_000_099_999)).toBe(
      "CA99F0B37F2EAC6F5D719AE4BA7C98978842B3F335D9F42979070A8DB149F0A5",
    );
    expect(generateSecMsGec(1_700_000_000_000)).toBe(
      "42301B335578FEFDAE2637DED1ABD614505D432559EC08032B82048483726AFF",
    );
    expect(generateSecMsGec(0)).toBe("7ECB79D14E3AA576D2D79E6D487A1388156D91E614B1BE11C64226A29BC8DD8C");
  });
});

describe("frame parsing", () => {
  it("parses a binary audio frame", () => {
    const payload = new Uint8Array([0xff, 0xf3, 0x64, 0xc4, 0x00]);
    const frame = binaryFrame(
      "X-RequestId:abc\r\nContent-Type:audio/mpeg\r\nX-StreamId:XYZ\r\nPath:audio\r\n",
      payload,
    );
    const parsed = parseBinaryFrame(new Uint8Array(frame));
    expect(parsed.headers).toEqual({
      "X-RequestId": "abc",
      "Content-Type": "audio/mpeg",
      "X-StreamId": "XYZ",
      Path: "audio",
    });
    expect(Array.from(parsed.audio)).toEqual(Array.from(payload));
  });

  it("parses the empty end-of-stream audio frame", () => {
    const parsed = parseBinaryFrame(new Uint8Array(binaryFrame("X-RequestId:abc\r\nPath:audio\r\n")));
    expect(parsed.headers.Path).toBe("audio");
    expect(parsed.headers["Content-Type"]).toBeUndefined();
    expect(parsed.audio.length).toBe(0);
  });

  it("rejects truncated frames", () => {
    expect(() => parseBinaryFrame(new Uint8Array([0x00]))).toThrow(EdgeTtsError);
    expect(() => parseBinaryFrame(new Uint8Array([0x00, 0x10, 0x41]))).toThrow(/header length/);
  });

  it("parses text frames", () => {
    const { headers, body } = parseTextFrame(
      "X-RequestId:abc\r\nContent-Type:application/json; charset=utf-8\r\nPath:turn.end\r\n\r\n{}",
    );
    expect(headers.Path).toBe("turn.end");
    expect(headers["Content-Type"]).toBe("application/json; charset=utf-8");
    expect(body).toBe("{}");
  });
});

describe("splitTextByBytes", () => {
  const englishSentence = "Jeannie keeps every system calm, precise and online through the night. ";
  const koreanSentence = "지니는 밤새도록 모든 시스템을 차분하고 정확하게 지켜요. ";

  it("returns one chunk for short text and nothing for blank text", () => {
    expect(splitTextByBytes("  Hello there.  ")).toEqual(["Hello there."]);
    expect(splitTextByBytes("   ")).toEqual([]);
  });

  it("splits English on sentence boundaries within the byte budget", () => {
    const text = englishSentence.repeat(100).trim(); // ~7 KB
    const chunks = splitTextByBytes(text, 3000);
    expect(chunks.length).toBeGreaterThanOrEqual(3);
    for (const chunk of chunks) {
      expect(utf8Bytes(escapeXml(chunk))).toBeLessThanOrEqual(3000);
      expect(chunk.endsWith(".")).toBe(true);
    }
    expect(chunks.join(" ")).toBe(text);
  });

  it("splits Korean (3 bytes per syllable) without breaking characters", () => {
    const text = koreanSentence.repeat(80).trim(); // ~7.4 KB of UTF-8
    const chunks = splitTextByBytes(text, 3000);
    expect(chunks.length).toBeGreaterThanOrEqual(3);
    for (const chunk of chunks) {
      expect(utf8Bytes(chunk)).toBeLessThanOrEqual(3000);
      expect(chunk).not.toContain("�");
      expect(chunk.endsWith("요.")).toBe(true);
    }
    expect(chunks.join(" ")).toBe(text);
  });

  it("falls back to whitespace, then code points, when there is no sentence end", () => {
    const words = "안녕 ".repeat(1500).trim();
    for (const chunk of splitTextByBytes(words, 3000)) {
      expect(utf8Bytes(chunk)).toBeLessThanOrEqual(3000);
      expect(chunk.startsWith("안녕")).toBe(true);
      expect(chunk.endsWith("안녕")).toBe(true);
    }

    const solid = "가".repeat(2500);
    expect(splitTextByBytes(solid, 3000).map((c) => c.length)).toEqual([1000, 1000, 500]);
  });

  it("never splits surrogate pairs and counts XML escapes", () => {
    expect(splitTextByBytes("😀😀😀", 6)).toEqual(["😀", "😀", "😀"]);
    expect(splitTextByBytes("&&&&&", 12)).toEqual(["&&", "&&", "&"]);
    expect(() => splitTextByBytes("abc", 5)).toThrow(RangeError);
  });
});

// ---------------------------------------------------------------- socket flow against a local fake service

interface FakeServiceOptions {
  /** Reply to the first N handshakes with HTTP 403 and this Date header. */
  reject403?: { times: number; date: string };
  /** Per-connection behaviour once the SSML arrives. */
  onSsml?: (socket: WebSocket, ssml: string, index: number) => void;
}

interface FakeService {
  endpoint: string;
  handshakes: IncomingMessage[];
  messages: string[][];
  close: () => Promise<void>;
}

const AUDIO_HEADERS = "X-RequestId:r\r\nContent-Type:audio/mpeg\r\nX-StreamId:S\r\nPath:audio\r\n";
const TURN_END = "X-RequestId:r\r\nContent-Type:application/json; charset=utf-8\r\nPath:turn.end\r\n\r\n{}";

function speakNormally(socket: WebSocket, _ssml: string, index: number) {
  socket.send("X-RequestId:r\r\nContent-Type:application/json; charset=utf-8\r\nPath:turn.start\r\n\r\n{}");
  socket.send(binaryFrame(AUDIO_HEADERS, new Uint8Array([0xff, 0xf3, index, 1])));
  socket.send(binaryFrame(AUDIO_HEADERS, new Uint8Array([0xff, 0xf3, index, 2])));
  socket.send(binaryFrame("X-RequestId:r\r\nX-StreamId:S\r\nPath:audio\r\n"));
  socket.send(TURN_END);
}

const services: FakeService[] = [];

async function startFakeService(options: FakeServiceOptions = {}): Promise<FakeService> {
  const server: Server = createServer();
  const wss = new WebSocketServer({ noServer: true });
  const handshakes: IncomingMessage[] = [];
  const messages: string[][] = [];
  let rejected = 0;
  let accepted = 0;

  server.on("upgrade", (req, socket, head) => {
    handshakes.push(req);
    if (options.reject403 && rejected < options.reject403.times) {
      rejected++;
      socket.end(
        `HTTP/1.1 403 Forbidden\r\nDate: ${options.reject403.date}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n`,
      );
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      const index = accepted++;
      const log: string[] = [];
      messages.push(log);
      ws.on("message", (data) => {
        const text = data.toString();
        log.push(text);
        if (text.includes("Path:ssml")) (options.onSsml ?? speakNormally)(ws, text, index);
      });
    });
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  const service: FakeService = {
    endpoint: `ws://127.0.0.1:${port}/consumer/speech/synthesize/readaloud/edge/v1`,
    handshakes,
    messages,
    close: async () => {
      for (const client of wss.clients) client.terminate();
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
  services.push(service);
  return service;
}

describe("synthesizeEdgeTts (local fake service)", () => {
  afterEach(async () => {
    await Promise.all(services.splice(0).map((s) => s.close()));
    resetClockSkew();
  });

  it("sends config + SSML with Edge headers and returns the concatenated audio", async () => {
    const service = await startFakeService();
    const audio = await synthesizeEdgeTts({
      text: "Hello <operator> & welcome.",
      voice: "en-US-JennyNeural",
      endpoint: service.endpoint,
    });
    expect(Array.from(audio)).toEqual([0xff, 0xf3, 0, 1, 0xff, 0xf3, 0, 2]);

    const [handshake] = service.handshakes;
    const url = new URL(handshake.url ?? "", "ws://localhost");
    expect(url.searchParams.get("TrustedClientToken")).toBe(TRUSTED_CLIENT_TOKEN);
    expect(url.searchParams.get("Sec-MS-GEC")).toMatch(/^[0-9A-F]{64}$/);
    expect(url.searchParams.get("Sec-MS-GEC-Version")).toBe(SEC_MS_GEC_VERSION);
    expect(handshake.headers.origin).toBe("chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold");
    expect(handshake.headers.pragma).toBe("no-cache");
    expect(handshake.headers["cache-control"]).toBe("no-cache");
    expect(handshake.headers["user-agent"]).toMatch(/Edg\/\d+\.0\.0\.0$/);
    expect(handshake.headers.cookie).toMatch(/^muid=[0-9A-F]{32};$/);

    const [config, ssml] = service.messages[0];
    expect(config).toContain("Path:speech.config");
    expect(ssml).toMatch(/^X-RequestId:[0-9a-f]{32}\r\nContent-Type:application\/ssml\+xml\r\nX-Timestamp:.+\)Z\r\nPath:ssml\r\n\r\n/);
    expect(ssml).toContain("Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)");
    expect(ssml).toContain("<prosody pitch='-2Hz' rate='+0%' volume='+0%'>Hello &lt;operator&gt; &amp; welcome.</prosody>");
  });

  it("synthesizes long text chunk by chunk, in order", async () => {
    const service = await startFakeService();
    const text = "지니는 모든 시스템을 차분하게 지켜요. ".repeat(250); // ~12 KB → several chunks
    const audio = await synthesizeEdgeTts({ text, voice: "ko-KR-SunHiNeural", endpoint: service.endpoint });
    const chunkCount = splitTextByBytes(text.replace(/\s+/g, " ").trim()).length;
    expect(chunkCount).toBeGreaterThan(1);
    expect(service.handshakes).toHaveLength(chunkCount);
    const expected = Array.from({ length: chunkCount }, (_, i) => [0xff, 0xf3, i, 1, 0xff, 0xf3, i, 2]).flat();
    expect(Array.from(audio)).toEqual(expected);
  });

  it("corrects clock skew from the Date header after a 403 and retries once", async () => {
    const serverNow = Date.now() + 3_600_000;
    const service = await startFakeService({ reject403: { times: 1, date: new Date(serverNow).toUTCString() } });
    const audio = await synthesizeEdgeTts({ text: "Retry me.", voice: "en-US-JennyNeural", endpoint: service.endpoint });
    expect(audio.byteLength).toBe(8);
    expect(service.handshakes).toHaveLength(2);
    expect(Math.abs(getClockSkewMs() - 3_600_000)).toBeLessThan(5_000);

    const tokenOf = (req: IncomingMessage) => new URL(req.url ?? "", "ws://localhost").searchParams.get("Sec-MS-GEC");
    const skewedNow = Date.now() + getClockSkewMs();
    expect([generateSecMsGec(skewedNow - 5_000), generateSecMsGec(skewedNow)]).toContain(tokenOf(service.handshakes[1]));
    expect(tokenOf(service.handshakes[1])).not.toBe(tokenOf(service.handshakes[0]));
  });

  it("gives up with a forbidden error when the retry is rejected too", async () => {
    const service = await startFakeService({ reject403: { times: 5, date: new Date().toUTCString() } });
    const error = await synthesizeEdgeTts({ text: "No.", voice: "en-US-JennyNeural", endpoint: service.endpoint }).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(EdgeTtsError);
    expect((error as EdgeTtsError).code).toBe("forbidden");
    expect((error as EdgeTtsError).status).toBe(403);
    expect(service.handshakes).toHaveLength(2);
  });

  it("times out when the service never ends the turn", async () => {
    const service = await startFakeService({ onSsml: () => undefined });
    await expect(
      synthesizeEdgeTts({ text: "Hang.", voice: "en-US-JennyNeural", endpoint: service.endpoint, timeoutMs: 200 }),
    ).rejects.toMatchObject({ code: "timeout" });
  });

  it("honours an abort signal", async () => {
    const service = await startFakeService({ onSsml: () => undefined });
    const controller = new AbortController();
    const pending = synthesizeEdgeTts({
      text: "Stop.",
      voice: "en-US-JennyNeural",
      endpoint: service.endpoint,
      signal: controller.signal,
    });
    setTimeout(() => controller.abort(), 50);
    await expect(pending).rejects.toMatchObject({ code: "aborted" });
  });

  it("fails when the socket closes before turn.end", async () => {
    const service = await startFakeService({ onSsml: (socket) => socket.close(1011, "boom") });
    await expect(
      synthesizeEdgeTts({ text: "Close.", voice: "en-US-JennyNeural", endpoint: service.endpoint }),
    ).rejects.toMatchObject({ code: "socket", message: expect.stringContaining("1011: boom") });
  });

  it("fails with no_audio when the turn ends silently", async () => {
    const service = await startFakeService({ onSsml: (socket) => socket.send(TURN_END) });
    await expect(
      synthesizeEdgeTts({ text: "Silence.", voice: "en-US-JennyNeural", endpoint: service.endpoint }),
    ).rejects.toMatchObject({ code: "no_audio" });
  });

  // invalid_input means a bad voice/prosody setting; empty_text is the caller's text, so the
  // engine can tell a configuration error from "nothing to say".
  it("rejects bad input before opening a socket", async () => {
    const service = await startFakeService();
    await expect(
      synthesizeEdgeTts({ text: "Hi.", voice: "Jenny", endpoint: service.endpoint }),
    ).rejects.toMatchObject({ code: "invalid_input" });
    await expect(
      synthesizeEdgeTts({ text: "Hi.", voice: "en-US-JennyNeural", pitch: "low", endpoint: service.endpoint }),
    ).rejects.toMatchObject({ code: "invalid_input" });
    await expect(
      synthesizeEdgeTts({ text: " \u000B\u0001 ", voice: "en-US-JennyNeural", endpoint: service.endpoint }),
    ).rejects.toMatchObject({ code: "empty_text" });
    expect(service.handshakes).toHaveLength(0);
  });
});
