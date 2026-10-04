// Real synthesis against speech.platform.bing.com. Opt-in:
//   LIVE_EDGE_TTS=1 npx vitest run tests/edge-tts.live.test.ts
// Optional: LIVE_EDGE_TTS_OUT=<dir> saves tts-sample-{en,ko,mixed}.mp3 there.
// Optional: LIVE_EDGE_TTS_VIA_PROXY=1 tunnels through HTTPS_PROXY (egress-restricted CI);
// the synthesizeSpeech cases then skip, because the route has no proxy agent.
// By default it connects directly, exactly like the production route.

import { writeFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import { join } from "node:path";
import type { Duplex } from "node:stream";
import tls from "node:tls";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { synthesizeEdgeTts } from "@/lib/agents/edge-tts";
import { DEFAULT_EDGE_VOICE_MIXED, synthesizeSpeech, TtsInputError } from "@/lib/agents/tts-engine";

type ConnectCallback = (error: Error | null, socket?: Duplex) => void;

/**
 * `ws` ignores HTTPS_PROXY. When egress goes through an HTTP CONNECT proxy
 * (CI sandboxes), tunnel the WebSocket's TLS connection through it.
 */
class ConnectTunnelAgent extends https.Agent {
  constructor(private readonly proxy: URL) {
    super({ keepAlive: false });
  }

  // Node's Agent accepts an async createConnection that reports through the callback.
  createConnection(options: tls.ConnectionOptions & { host?: string; port?: number }, callback: ConnectCallback) {
    const target = `${options.host}:${options.port ?? 443}`;
    const request = http.request({
      host: this.proxy.hostname,
      port: Number(this.proxy.port || 80),
      method: "CONNECT",
      path: target,
      headers: { host: target },
    });
    request.once("connect", (response, socket) => {
      if (response.statusCode !== 200) {
        socket.destroy();
        callback(new Error(`Proxy CONNECT failed with HTTP ${response.statusCode}`));
        return;
      }
      callback(null, tls.connect({ socket, servername: options.servername ?? options.host, ALPNProtocols: ["http/1.1"] }));
    });
    request.once("error", (error) => callback(error));
    request.end();
    return undefined;
  }
}

function proxyAgent(): https.Agent | undefined {
  if (!process.env.LIVE_EDGE_TTS_VIA_PROXY) return undefined;
  const proxy = process.env.HTTPS_PROXY ?? process.env.https_proxy;
  if (!proxy) throw new Error("LIVE_EDGE_TTS_VIA_PROXY is set but HTTPS_PROXY is not.");
  return new ConnectTunnelAgent(new URL(proxy));
}

function looksLikeMp3(bytes: Uint8Array): boolean {
  const id3 = bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33; // "ID3"
  const frameSync = bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0;
  return id3 || frameSync;
}

// The service streams 48 kbps CBR MP3, so 6000 bytes are one second of speech.
const BYTES_PER_SECOND = 6000;
const MIXED_TEXT = "Thank you is 감사합니다 in Korean.";
const ENGLISH_PART = "Thank you is in Korean.";

function save(name: string, bytes: Uint8Array) {
  const dir = process.env.LIVE_EDGE_TTS_OUT;
  if (dir) writeFileSync(join(dir, name), bytes);
}

describe.skipIf(!process.env.LIVE_EDGE_TTS)("Edge TTS (live)", () => {
  const agent = proxyAgent();

  it("speaks English with JennyNeural", async () => {
    const audio = await synthesizeEdgeTts({
      text: "Good evening. All systems are online, and I'm standing by for your next command.",
      voice: "en-US-JennyNeural",
      agent,
    });
    expect(audio.byteLength).toBeGreaterThan(2048);
    expect(looksLikeMp3(audio)).toBe(true);
    save("tts-sample-en.mp3", audio);
  }, 30_000);

  it("speaks Korean with SunHiNeural", async () => {
    const audio = await synthesizeEdgeTts({
      text: "안녕하세요. 모든 시스템이 정상적으로 작동하고 있어요. 다음 명령을 기다리고 있을게요.",
      voice: "ko-KR-SunHiNeural",
      agent,
    });
    expect(audio.byteLength).toBeGreaterThan(2048);
    expect(looksLikeMp3(audio)).toBe(true);
    save("tts-sample-ko.mp3", audio);
  }, 30_000);

  // English-only voices (JennyNeural) render MIXED_TEXT exactly as long as ENGLISH_PART:
  // the Korean word is dropped. The mixed voice must add real speech for it.
  it("speaks the Korean word inside an English sentence with the mixed voice", async () => {
    const mixed = await synthesizeEdgeTts({ text: MIXED_TEXT, voice: DEFAULT_EDGE_VOICE_MIXED, agent });
    const englishOnly = await synthesizeEdgeTts({ text: ENGLISH_PART, voice: DEFAULT_EDGE_VOICE_MIXED, agent });
    expect(looksLikeMp3(mixed)).toBe(true);
    expect(mixed.byteLength - englishOnly.byteLength).toBeGreaterThan(0.5 * BYTES_PER_SECOND);
    save("tts-sample-mixed.mp3", mixed);
  }, 30_000);
});

describe.skipIf(!process.env.LIVE_EDGE_TTS || process.env.LIVE_EDGE_TTS_VIA_PROXY)("synthesizeSpeech on Edge (live)", () => {
  beforeEach(() => {
    for (const name of ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "EDGE_TTS_VOICE_EN", "EDGE_TTS_VOICE_KO", "EDGE_TTS_VOICE_MIXED"]) {
      vi.stubEnv(name, "");
    }
    vi.stubEnv("EDGE_TTS_ENABLED", "true");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("keeps Korean words in an English reply (lang en)", async () => {
    const mixed = await synthesizeSpeech({ text: MIXED_TEXT, lang: "en" });
    const englishOnly = await synthesizeSpeech({ text: ENGLISH_PART, lang: "en" });
    expect(mixed.engine).toBe("edge");
    expect(mixed.audio.byteLength - englishOnly.audio.byteLength).toBeGreaterThan(0.5 * BYTES_PER_SECOND);
  }, 30_000);

  it("speaks Korean-only text sent with lang en instead of failing", async () => {
    const result = await synthesizeSpeech({ text: "감사합니다.", lang: "en" });
    expect(result.audio.byteLength).toBeGreaterThan(2048);
  }, 30_000);

  it("rejects text the voice cannot say as nothing to speak", async () => {
    await expect(synthesizeSpeech({ text: "..." })).rejects.toBeInstanceOf(TtsInputError);
    // Letters, so it reaches the service, which ends the turn without audio.
    await expect(synthesizeSpeech({ text: "ㅋㅋㅋ" })).rejects.toBeInstanceOf(TtsInputError);
  }, 30_000);
});
