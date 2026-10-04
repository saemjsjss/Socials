// Embedding vectors on the wire: base64 of little-endian float32 (384 floats =
// 1,536 bytes = 2,048 characters), about a quarter of the JSON number form.
// Isomorphic: btoa/atob and DataView exist in browsers, Web Workers, Edge and Node.

export const EMBEDDING_DIMENSIONS = 384;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** Numbers → base64 float32 (little-endian). */
export function encodeVector(values: ArrayLike<number>): string {
  const view = new DataView(new ArrayBuffer(values.length * 4));
  for (let i = 0; i < values.length; i++) view.setFloat32(i * 4, values[i], true);
  return bytesToBase64(new Uint8Array(view.buffer));
}

/** base64 float32 (little-endian) → Float32Array. Throws on text that is not whole float32s. */
export function decodeVector(base64: string): Float32Array {
  const binary = atob(base64);
  if (binary.length % 4 !== 0) throw new Error("vector is not a whole number of float32 values");
  const view = new DataView(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) view.setUint8(i, binary.charCodeAt(i));
  const out = new Float32Array(binary.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = view.getFloat32(i * 4, true);
  return out;
}

/** pgvector's text form "[0.1,-0.2,...]" (what a PostgREST select returns) → numbers. */
export function parsePgVector(value: unknown): number[] | null {
  if (Array.isArray(value)) return value.every((v) => typeof v === "number") ? (value as number[]) : null;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) && parsed.every((v) => typeof v === "number") ? (parsed as number[]) : null;
  } catch {
    return null;
  }
}

/** A question embedding from a client: 384 finite numbers, or their base64 float32 form. Null when invalid. */
export function readEmbedding(value: unknown): number[] | null {
  let numbers: ArrayLike<number> | null = null;
  if (typeof value === "string") {
    try {
      numbers = decodeVector(value);
    } catch {
      return null;
    }
  } else if (Array.isArray(value)) {
    numbers = value as number[];
  }
  if (!numbers || numbers.length !== EMBEDDING_DIMENSIONS) return null;
  const out = Array.from(numbers);
  return out.every((v) => typeof v === "number" && Number.isFinite(v)) ? out : null;
}

/** Cosine similarity of two equal-length vectors (1 for identical directions). */
export function cosine(a: ArrayLike<number>, b: ArrayLike<number>): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  return na === 0 || nb === 0 ? 0 : dot / Math.sqrt(na * nb);
}
