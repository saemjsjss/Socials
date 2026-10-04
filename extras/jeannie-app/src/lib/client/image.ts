// Client-side image preparation: every attachment (upload or camera frame) is
// re-encoded as a JPEG no larger than 1280 px on its long edge, which keeps the
// data URL far below the chat route's 3 MB limit.

import { dataUrlByteLength } from "@/lib/utils";

export const MAX_IMAGE_EDGE = 1280;
export const JPEG_QUALITY = 0.85;
// The chat route accepts 3 MB decoded; re-encode harder in the rare case a noisy frame gets close.
const SAFE_BYTES = 2_400_000;

export interface PreparedImage {
  dataUrl: string;
  width: number;
  height: number;
  name: string;
}

function fitWithin(width: number, height: number, max = MAX_IMAGE_EDGE): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** Draws any image-like source onto a canvas and returns a JPEG data URL. */
export function encodeJpeg(
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  options: { mirror?: boolean } = {},
): { dataUrl: string; width: number; height: number } {
  const { width, height } = fitWithin(sourceWidth, sourceHeight);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not available in this browser.");
  // JPEG has no alpha: paint white first so transparent PNGs (logos, screenshots) stay legible.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  if (options.mirror) {
    ctx.translate(width, 0);
    ctx.scale(-1, 1);
  }
  ctx.drawImage(source, 0, 0, width, height);
  let dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  for (const quality of [0.7, 0.55]) {
    if (dataUrlByteLength(dataUrl) <= SAFE_BYTES) break;
    dataUrl = canvas.toDataURL("image/jpeg", quality);
  }
  return { dataUrl, width, height };
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("This image format could not be decoded."));
    img.src = url;
  });
}

/** Downscales a user-picked file. Rejects non-images and undecodable formats (e.g. HEIC on desktop). */
export async function prepareImageFile(file: File): Promise<PreparedImage> {
  if (!file.type.startsWith("image/")) throw new Error("Only image files can be attached.");
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url);
    const encoded = encodeJpeg(img, img.naturalWidth, img.naturalHeight);
    return { ...encoded, name: file.name || "image.jpg" };
  } finally {
    URL.revokeObjectURL(url);
  }
}
