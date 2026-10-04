"use client";

import type { LangMode } from "@/lib/types";
import { cn } from "@/lib/utils";

const OPTIONS: { value: LangMode; label: string; title: string }[] = [
  { value: "auto", label: "AUTO", title: "Auto-detect language" },
  { value: "en", label: "EN", title: "English replies" },
  { value: "ko", label: "한", title: "Korean replies (한국어)" },
  { value: "bilingual", label: "EN+한", title: "Bilingual replies (English, then Korean)" },
];

export function isLangMode(value: unknown): value is LangMode {
  return value === "auto" || value === "en" || value === "ko" || value === "bilingual";
}

interface LanguageToggleProps {
  value: LangMode;
  onChange: (value: LangMode) => void;
  className?: string;
}

/** Segmented control for the reply language (radio-group semantics, arrow-key navigation). */
export function LanguageToggle({ value, onChange, className }: LanguageToggleProps) {
  const move = (delta: number) => {
    const index = OPTIONS.findIndex((o) => o.value === value);
    const next = OPTIONS[(index + delta + OPTIONS.length) % OPTIONS.length];
    onChange(next.value);
    requestAnimationFrame(() => document.getElementById(`lang-opt-${next.value}`)?.focus());
  };

  return (
    <div
      role="radiogroup"
      aria-label="Reply language"
      className={cn("inline-flex rounded-md border border-neon/35 bg-void/60 p-0.5", className)}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          event.preventDefault();
          move(1);
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          event.preventDefault();
          move(-1);
        }
      }}
    >
      {OPTIONS.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            id={`lang-opt-${option.value}`}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            title={option.title}
            aria-label={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "min-h-[40px] min-w-[40px] rounded px-2 font-mono text-[0.7rem] font-semibold tracking-[0.12em] transition-all",
              selected
                ? "bg-neon text-white shadow-glow-sm"
                : "text-petal-soft/70 hover:bg-neon/15 hover:text-petal-soft",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
