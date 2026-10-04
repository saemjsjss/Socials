// Multimodal Vision & Korean/English Localization Agent helpers: turn the HUD's
// chat history into model messages, with the image (document, screenshot or
// camera frame) only on the latest user turn.

import type { ModelMessage, UserModelMessage } from "ai";
import type { ChatMessage, ResolvedLang } from "../types";

export const IMAGE_PLACEHOLDER = "[image attached earlier]";

export const DEFAULT_VISION_INSTRUCTION: Record<ResolvedLang, string> = {
  en: "Analyse this image.",
  ko: "이 이미지를 분석해 주세요.",
  bilingual: "Analyse this image. / 이 이미지를 분석해 주세요.",
};

/** `data:image/png;base64,...` → `image/png` (JPEG when the header is unusual). */
export function imageMediaType(dataUrl: string): string {
  const match = /^data:(image\/[a-z0-9.+-]+);base64,/i.exec(dataUrl);
  return match ? match[1].toLowerCase() : "image/jpeg";
}

/** The latest user turn with its image: text part (default instruction when empty) + image file part. */
export function buildVisionUserMessage(text: string, image: string, lang: ResolvedLang): UserModelMessage {
  return {
    role: "user",
    content: [
      { type: "text", text: text.trim() || DEFAULT_VISION_INSTRUCTION[lang] },
      // `file` parts with an image media type replace the deprecated `image` part in AI SDK v7.
      { type: "file", mediaType: imageMediaType(image), data: image },
    ],
  };
}

/** Older turns keep their text; their images become a placeholder so they are not re-sent. */
export function withoutImage(message: ChatMessage): ModelMessage {
  const content = message.content.trim();
  if (message.role === "assistant") return { role: "assistant", content };
  if (!message.image) return { role: "user", content };
  return { role: "user", content: content ? `${content}\n${IMAGE_PLACEHOLDER}` : IMAGE_PLACEHOLDER };
}

/**
 * History → model messages. Only the final user message may carry an image,
 * and only when `latestImage` is given (vision route); every other image is
 * replaced by a placeholder.
 */
export function toModelMessages(
  history: ChatMessage[],
  options: { latestImage?: string | null; lang: ResolvedLang },
): ModelMessage[] {
  const messages = history.map(withoutImage);
  const lastIndex = history.length - 1;
  const last = history[lastIndex];
  if (options.latestImage && last?.role === "user") {
    messages[lastIndex] = buildVisionUserMessage(last.content, options.latestImage, options.lang);
  }
  return messages;
}
