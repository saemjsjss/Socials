"use client";

import { useEffect, useState } from "react";
import type { AvatarDirector } from "@/hooks/useAvatarDirector";
import { emotePickerEnabled } from "@/lib/avatar/debug";
import { REPLY_EMOTES } from "@/lib/emote";

// QA picker (preview deployments only): plays any emote on tap so every clip can be
// checked on a real phone before a release goes live.

interface EmotePickerProps {
  director: AvatarDirector;
  /** Plays talking against a scripted voice (on / off) to check the mouth rests. */
  onVoiceTest: () => void;
  voiceTestRunning: boolean;
}

export function EmotePicker({ director, onVoiceTest, voiceTestRunning }: EmotePickerProps) {
  const [enabled, setEnabled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setEnabled(emotePickerEnabled(process.env.NEXT_PUBLIC_DEPLOY_ENV, window.location.search));
  }, []);

  if (!enabled) return null;

  return (
    <div className="emote-picker" data-testid="emote-picker">
      <button type="button" className="emote-picker-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? "Close" : "Emotes (QA)"}
      </button>
      {open ? (
        <div className="emote-picker-list">
          {REPLY_EMOTES.map((emote) => (
            <button key={emote} type="button" data-emote={emote} onClick={() => director.play(emote)}>
              {emote}
            </button>
          ))}
          <button type="button" data-voice-test="" onClick={onVoiceTest} disabled={voiceTestRunning}>
            {voiceTestRunning ? "voice test…" : "voice test"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
