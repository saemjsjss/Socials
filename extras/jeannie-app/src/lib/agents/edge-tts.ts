// Microsoft Edge "Read Aloud" neural TTS client (Node.js runtime only: uses `ws`).
//
// Protocol ported from the reference implementation edge-tts 7.2.8
// (https://github.com/rany2/edge-tts: constants.py, drm.py, communicate.py).
// One WebSocket per text chunk: send `speech.config`, then the SSML, collect
// binary `Path:audio` frames until `Path:turn.end`. The service returns
// 48 kbps CBR MP3 frames, so chunk outputs concatenate into one valid stream.

import { createHash, randomBytes, randomUUID } from "node:crypto";
import type { Agent } from "node:http";
import WebSocket from "ws";

export const TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
export const CHROMIUM_FULL_VERSION = "143.0.3650.75";
const CHROMIUM_MAJOR_VERSION = CHROMIUM_FULL_VERSION.split(".")[0];
export const SEC_MS_GEC_VERSION = `1-${CHROMIUM_FULL_VERSION}`;
export const EDGE_TTS_ENDPOINT = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1";
export const EDGE_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3";

/** Jeannie's register: calm and slightly lower than the stock voice. */
export const JEANNIE_PROSODY = { rate: "+0%", volume: "+0%", pitch: "-2Hz" } as const;

/** Per-chunk budget in UTF-8 bytes of escaped SSML text (the service rejects very large turns). */
export const EDGE_MAX_CHUNK_BYTES = 3000;
export const EDGE_TIMEOUT_MS = 25_000;

const WIN_EPOCH_SECONDS = 11_644_473_600;
const FULL_VOICE_PREFIX = "Microsoft Server Speech Text to Speech Voice";

const WSS_HEADERS = {
  Pragma: "no-cache",
  "Cache-Control": "no-cache",
  Origin: "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
  "User-Agent":
    `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ` +
    `Chrome/${CHROMIUM_MAJOR_VERSION}.0.0.0 Safari/537.36 Edg/${CHROMIUM_MAJOR_VERSION}.0.0.0`,
  "Accept-Encoding": "gzip, deflate, br, zstd",
  "Accept-Language": "en-US,en;q=0.9",
} as const;

export type EdgeTtsErrorCode =
  | "invalid_input" // bad voice or prosody (configuration)
  | "empty_text" // nothing left to send once control characters are removed
  | "forbidden" // HTTP 403 on the handshake (token/clock problem)
  | "handshake_failed" // any other non-101 handshake response
  | "socket" // network error or socket closed before turn.end
  | "protocol" // malformed frame from the service
  | "no_audio" // turn ended without any audio: the voice cannot speak this text
  | "timeout"
  | "aborted";

export class EdgeTtsError extends Error {
  readonly code: EdgeTtsErrorCode;
  readonly status?: number;
  /** Raw `Date` header of a rejected handshake, used for clock-skew correction. */
  readonly serverDate?: string;

  constructor(code: EdgeTtsErrorCode, message: string, extra: { status?: number; serverDate?: string } = {}) {
    super(message);
    this.name = "EdgeTtsError";
    this.code = code;
    this.status = extra.status;
    this.serverDate = extra.serverDate;
  }
}

export interface EdgeTtsOptions {
  text: string;
  /** Short name (`en-US-JennyNeural`) or full service name. */
  voice: string;
  /** `[+-]N%`, default `+0%`. */
  rate?: string;
  /** `[+-]NHz`, default `-2Hz`. */
  pitch?: string;
  /** `[+-]N%`, default `+0%`. */
  volume?: string;
  signal?: AbortSignal;
  /** Budget for the whole synthesis (all chunks), default 25 s. */
  timeoutMs?: number;
  /** Custom agent, e.g. an HTTPS CONNECT tunnel when egress goes through a proxy. */
  agent?: Agent;
  /** Service URL override (tests, relays). Query parameters are appended. */
  endpoint?: string;
}

// ---------------------------------------------------------------- DRM / clock skew

// Mirrors DRM.clock_skew_seconds in the reference: process-wide, corrected on 403.
let clockSkewMs = 0;

export function getClockSkewMs(): number {
  return clockSkewMs;
}

export function resetClockSkew(): void {
  clockSkewMs = 0;
}

/**
 * Sec-MS-GEC token: uppercase hex SHA-256 of (Windows file time in 100 ns ticks,
 * rounded down to 5 minutes) + trusted client token. Same result as drm.py.
 */
export function generateSecMsGec(nowMs: number): string {
  const winSeconds = Math.floor(nowMs / 1000) + WIN_EPOCH_SECONDS;
  const rounded = winSeconds - (((winSeconds % 300) + 300) % 300);
  // ~1.3e17 exceeds Number.MAX_SAFE_INTEGER, so do the tick conversion in BigInt.
  const ticks = BigInt(rounded) * 10_000_000n;
  return createHash("sha256")
    .update(`${ticks}${TRUSTED_CLIENT_TOKEN}`, "ascii")
    .digest("hex")
    .toUpperCase();
}

function applyServerDate(serverDate: string | undefined): boolean {
  if (!serverDate) return false;
  const serverMs = Date.parse(serverDate);
  if (Number.isNaN(serverMs)) return false;
  clockSkewMs += serverMs - (Date.now() + clockSkewMs);
  return true;
}

function connectionId(): string {
  return randomUUID().replace(/-/g, "");
}

export function buildEdgeTtsUrl(nowMs: number, endpoint: string = EDGE_TTS_ENDPOINT): string {
  const params = new URLSearchParams({
    TrustedClientToken: TRUSTED_CLIENT_TOKEN,
    ConnectionId: connectionId(),
    "Sec-MS-GEC": generateSecMsGec(nowMs),
    "Sec-MS-GEC-Version": SEC_MS_GEC_VERSION,
  });
  return `${endpoint}?${params.toString()}`;
}

// ---------------------------------------------------------------- SSML + messages

const XML_ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&apos;",
};

export function escapeXml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => XML_ENTITIES[ch]);
}

/** The service rejects some control characters (vertical tab is common in OCR text). */
export function removeIncompatibleCharacters(text: string): string {
  return text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ");
}

/**
 * `en-US-JennyNeural` → `Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)`;
 * `zh-CN-liaoning-XiaobeiNeural` keeps the sub-region with the locale. Full names pass through.
 */
export function expandVoiceName(voice: string): string {
  const trimmed = voice.trim();
  const match = /^([a-z]{2,})-([A-Z]{2,})-(.+Neural)$/.exec(trimmed);
  let full = trimmed;
  if (match) {
    let region = match[2];
    let name = match[3];
    const dash = name.indexOf("-");
    if (dash !== -1) {
      region = `${region}-${name.slice(0, dash)}`;
      name = name.slice(dash + 1);
    }
    full = `${FULL_VOICE_PREFIX} (${match[1]}-${region}, ${name})`;
  }
  if (!/^Microsoft Server Speech Text to Speech Voice \(.+,.+\)$/.test(full)) {
    throw new EdgeTtsError("invalid_input", `Invalid Edge TTS voice "${voice}".`);
  }
  return full;
}

function checkProsody(name: string, value: string, pattern: RegExp): string {
  if (!pattern.test(value)) throw new EdgeTtsError("invalid_input", `Invalid ${name} "${value}".`);
  return value;
}

/** SSML for one chunk. `text` is raw; it is escaped here. */
export function buildSsml(options: {
  text: string;
  voice: string;
  rate?: string;
  pitch?: string;
  volume?: string;
}): string {
  const voice = expandVoiceName(options.voice);
  const rate = checkProsody("rate", options.rate ?? JEANNIE_PROSODY.rate, /^[+-]\d+%$/);
  const volume = checkProsody("volume", options.volume ?? JEANNIE_PROSODY.volume, /^[+-]\d+%$/);
  const pitch = checkProsody("pitch", options.pitch ?? JEANNIE_PROSODY.pitch, /^[+-]\d+Hz$/);
  // xml:lang stays en-US like the reference client; the <voice> element sets the spoken language.
  return (
    "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
    `<voice name='${voice}'>` +
    `<prosody pitch='${pitch}' rate='${rate}' volume='${volume}'>` +
    escapeXml(options.text) +
    "</prosody></voice></speak>"
  );
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad2 = (n: number) => String(n).padStart(2, "0");

/** JavaScript `Date.toString()` style in UTC, as Edge sends it. */
export function dateToString(date: Date = new Date()): string {
  return (
    `${DAYS[date.getUTCDay()]} ${MONTHS[date.getUTCMonth()]} ${pad2(date.getUTCDate())} ${date.getUTCFullYear()} ` +
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())} ` +
    "GMT+0000 (Coordinated Universal Time)"
  );
}

export function buildSpeechConfigMessage(date: Date = new Date()): string {
  return (
    `X-Timestamp:${dateToString(date)}\r\n` +
    "Content-Type:application/json; charset=utf-8\r\n" +
    "Path:speech.config\r\n\r\n" +
    '{"context":{"synthesis":{"audio":{"metadataoptions":{' +
    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},' +
    `"outputFormat":"${EDGE_OUTPUT_FORMAT}"}}}}\r\n`
  );
}

export function buildSsmlMessage(requestId: string, ssml: string, date: Date = new Date()): string {
  return (
    `X-RequestId:${requestId}\r\n` +
    "Content-Type:application/ssml+xml\r\n" +
    // The trailing "Z" after a non-ISO date is what Edge itself sends.
    `X-Timestamp:${dateToString(date)}Z\r\n` +
    "Path:ssml\r\n\r\n" +
    ssml
  );
}

// ---------------------------------------------------------------- frame parsing

function parseHeaderBlock(block: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of block.split("\r\n")) {
    const colon = line.indexOf(":");
    if (colon <= 0) continue;
    headers[line.slice(0, colon)] = line.slice(colon + 1).trim();
  }
  return headers;
}

/** Text frames: `Header:value\r\n...\r\n\r\nbody`. */
export function parseTextFrame(message: string): { headers: Record<string, string>; body: string } {
  const split = message.indexOf("\r\n\r\n");
  if (split === -1) return { headers: parseHeaderBlock(message), body: "" };
  return { headers: parseHeaderBlock(message.slice(0, split)), body: message.slice(split + 4) };
}

/** Binary frames: 2-byte big-endian header length, the header block, then the payload. */
export function parseBinaryFrame(data: Uint8Array): { headers: Record<string, string>; audio: Uint8Array } {
  if (data.length < 2) {
    throw new EdgeTtsError("protocol", "Binary frame is missing its header length.");
  }
  const headerLength = (data[0] << 8) | data[1];
  if (2 + headerLength > data.length) {
    throw new EdgeTtsError("protocol", "Binary frame header length exceeds the frame size.");
  }
  const headers = parseHeaderBlock(new TextDecoder().decode(data.subarray(2, 2 + headerLength)));
  return { headers, audio: data.subarray(2 + headerLength) };
}

// ---------------------------------------------------------------- text chunking

function isHighSurrogate(code: number): boolean {
  return code >= 0xd800 && code <= 0xdbff;
}

// UTF-8 size of one code point, counting XML specials at their escaped size so a
// chunk's escaped SSML text also fits the budget.
function escapedByteLength(codePoint: number): number {
  switch (codePoint) {
    case 0x26: // &amp;
      return 5;
    case 0x3c: // &lt;
    case 0x3e: // &gt;
      return 4;
    case 0x22: // &quot;
    case 0x27: // &apos;
      return 6;
  }
  if (codePoint < 0x80) return 1;
  if (codePoint < 0x800) return 2;
  if (codePoint < 0x10000) return 3;
  return 4;
}

const SENTENCE_END = /[.!?。！？…]["'”’)\]]*$/;

/**
 * Split text into chunks whose escaped UTF-8 size is at most `maxBytes`,
 * preferring sentence ends, then whitespace, then a code-point boundary.
 * Chunks are trimmed; empty chunks are dropped.
 */
export function splitTextByBytes(text: string, maxBytes: number = EDGE_MAX_CHUNK_BYTES): string[] {
  // 6 = the largest single code-point cost (&quot;), so every pass makes progress.
  if (!Number.isFinite(maxBytes) || maxBytes < 6) throw new RangeError("maxBytes must be at least 6.");
  const chunks: string[] = [];
  let rest = text.trim();

  while (rest.length > 0) {
    // Longest prefix (in UTF-16 units, on a code-point boundary) that fits.
    let bytes = 0;
    let limit = 0;
    while (limit < rest.length) {
      const wide = isHighSurrogate(rest.charCodeAt(limit)) && limit + 1 < rest.length;
      const cost = escapedByteLength(rest.codePointAt(limit) ?? 0);
      if (bytes + cost > maxBytes) break;
      bytes += cost;
      limit += wide ? 2 : 1;
    }
    if (limit >= rest.length) {
      chunks.push(rest);
      break;
    }

    let cut = -1;
    let sentenceCut = -1;
    let spaceCut = -1;
    for (let i = limit; i > 0; i--) {
      if (!/\s/.test(rest[i])) continue;
      if (spaceCut === -1) spaceCut = i;
      if (SENTENCE_END.test(rest.slice(Math.max(0, i - 4), i))) {
        sentenceCut = i;
        break;
      }
    }
    // A sentence end in the back half keeps chunks natural without making them tiny.
    if (sentenceCut > limit / 2) cut = sentenceCut;
    else if (spaceCut > 0) cut = spaceCut;
    else cut = limit;

    const chunk = rest.slice(0, cut).trim();
    if (chunk) chunks.push(chunk);
    rest = rest.slice(cut).trimStart();
  }
  return chunks;
}

// ---------------------------------------------------------------- socket

function rawDataToBytes(data: WebSocket.RawData): Uint8Array {
  if (Array.isArray(data)) return new Uint8Array(Buffer.concat(data));
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
}

function rawDataToText(data: WebSocket.RawData): string {
  return new TextDecoder().decode(rawDataToBytes(data));
}

function abortReason(timeoutSignal: AbortSignal, timeoutMs: number): EdgeTtsError {
  return timeoutSignal.aborted
    ? new EdgeTtsError("timeout", `Edge TTS timed out after ${timeoutMs} ms.`)
    : new EdgeTtsError("aborted", "Edge TTS request was aborted.");
}

function closeQuietly(ws: WebSocket): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.close(1000);
    // Do not wait up to ws's 30 s close timeout for the server's close frame.
    const timer = setTimeout(() => ws.terminate(), 2000);
    timer.unref?.();
    ws.once("close", () => clearTimeout(timer));
  } else if (ws.readyState === WebSocket.CONNECTING) {
    ws.terminate();
  }
}

interface SocketRun {
  ssml: string;
  endpoint: string;
  agent?: Agent;
  signal: AbortSignal;
  onAbort: () => EdgeTtsError;
}

function synthesizeChunk(run: SocketRun): Promise<Uint8Array[]> {
  return new Promise((resolve, reject) => {
    if (run.signal.aborted) {
      reject(run.onAbort());
      return;
    }

    const ws = new WebSocket(buildEdgeTtsUrl(Date.now() + clockSkewMs, run.endpoint), {
      headers: { ...WSS_HEADERS, Cookie: `muid=${randomBytes(16).toString("hex").toUpperCase()};` },
      agent: run.agent,
      perMessageDeflate: true,
    });
    const audio: Uint8Array[] = [];
    let settled = false;

    const finish = (error?: EdgeTtsError) => {
      if (settled) return;
      settled = true;
      run.signal.removeEventListener("abort", abort);
      closeQuietly(ws);
      if (error) reject(error);
      else resolve(audio);
    };
    const abort = () => finish(run.onAbort());
    run.signal.addEventListener("abort", abort, { once: true });

    ws.on("unexpected-response", (_req, res) => {
      const status = res.statusCode ?? 0;
      const date = res.headers.date;
      res.resume();
      finish(
        new EdgeTtsError(
          status === 403 ? "forbidden" : "handshake_failed",
          `Edge TTS handshake rejected with HTTP ${status}.`,
          { status, serverDate: typeof date === "string" ? date : undefined },
        ),
      );
    });

    ws.on("open", () => {
      const now = new Date();
      ws.send(buildSpeechConfigMessage(now));
      ws.send(buildSsmlMessage(connectionId(), run.ssml, now));
    });

    ws.on("message", (data, isBinary) => {
      if (settled) return;
      if (!isBinary) {
        const { headers } = parseTextFrame(rawDataToText(data));
        // turn.start, response and audio.metadata carry nothing we need. A silent
        // chunk (only punctuation) is fine; synthesizeEdgeTts checks the total.
        if (headers.Path === "turn.end") finish();
        return;
      }
      try {
        const frame = parseBinaryFrame(rawDataToBytes(data));
        if (frame.headers.Path !== "audio") {
          throw new EdgeTtsError("protocol", "Binary frame without Path:audio.");
        }
        // The stream ends with an empty audio frame that has no Content-Type.
        if (frame.audio.length === 0) return;
        const type = frame.headers["Content-Type"];
        if (type !== "audio/mpeg") {
          throw new EdgeTtsError("protocol", `Unexpected audio Content-Type "${type ?? "none"}".`);
        }
        audio.push(new Uint8Array(frame.audio)); // copy: the frame buffer may be pooled
      } catch (error) {
        finish(error instanceof EdgeTtsError ? error : new EdgeTtsError("protocol", "Malformed binary frame."));
      }
    });

    // Kept attached after settling: ws emits "error" when a pending handshake is terminated.
    ws.on("error", (error) => finish(new EdgeTtsError("socket", `Edge TTS socket error: ${error.message}`)));
    ws.on("close", (code, reason) => {
      const detail = reason.length > 0 ? `: ${reason.toString()}` : "";
      finish(new EdgeTtsError("socket", `Edge TTS socket closed before turn.end (code ${code}${detail}).`));
    });
  });
}

function concatBytes(parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const total = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.byteLength;
  }
  return out;
}

/**
 * Synthesize `text` with a Microsoft Edge neural voice. Returns MP3 bytes
 * (24 kHz mono, 48 kbps). Long text is split and synthesized chunk by chunk.
 * Throws EdgeTtsError.
 */
export async function synthesizeEdgeTts(options: EdgeTtsOptions): Promise<Uint8Array<ArrayBuffer>> {
  const timeoutMs = options.timeoutMs ?? EDGE_TIMEOUT_MS;
  const text = removeIncompatibleCharacters(options.text).replace(/\s+/g, " ").trim();
  if (!text) throw new EdgeTtsError("empty_text", "Nothing to synthesize.");

  const chunks = splitTextByBytes(text, EDGE_MAX_CHUNK_BYTES);
  // Validate voice and prosody before opening any socket.
  const ssmls = chunks.map((chunk) =>
    buildSsml({ text: chunk, voice: options.voice, rate: options.rate, pitch: options.pitch, volume: options.volume }),
  );

  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const signal = options.signal ? AbortSignal.any([options.signal, timeoutSignal]) : timeoutSignal;
  const onAbort = () => abortReason(timeoutSignal, timeoutMs);
  const endpoint = options.endpoint ?? EDGE_TTS_ENDPOINT;

  const parts: Uint8Array[] = [];
  for (const ssml of ssmls) {
    const run: SocketRun = { ssml, endpoint, agent: options.agent, signal, onAbort };
    try {
      parts.push(...(await synthesizeChunk(run)));
    } catch (error) {
      // 403 usually means our clock is off: correct the skew from the server's Date and retry once.
      if (!(error instanceof EdgeTtsError) || error.code !== "forbidden" || !applyServerDate(error.serverDate)) {
        throw error;
      }
      parts.push(...(await synthesizeChunk(run)));
    }
  }

  const audio = concatBytes(parts);
  if (audio.byteLength === 0) throw new EdgeTtsError("no_audio", "Edge TTS returned no audio.");
  return audio;
}
