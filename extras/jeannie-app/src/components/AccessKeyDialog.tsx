"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Eye, EyeOff, KeyRound, X } from "lucide-react";
import { useDialogFocus } from "@/hooks/useDialogFocus";
import { isValidAccessKey } from "@/lib/client/api";

export type AccessKeyReason = "required" | "rejected" | "manage";

interface AccessKeyDialogProps {
  open: boolean;
  reason: AccessKeyReason;
  hasStoredKey: boolean;
  onSubmit: (key: string) => void;
  onForget: () => void;
  onClose: () => void;
}

const COPY: Record<AccessKeyReason, { title: string; body: string }> = {
  required: {
    title: "Access key required",
    body: "This Jeannie deployment is locked. Enter the access key to continue; it stays in this browser only.",
  },
  rejected: {
    title: "Access key rejected",
    body: "That key was not accepted. Check it and try again.",
  },
  manage: {
    title: "Access key",
    body: "The key is sent as a header with every request from this browser and stored locally.",
  },
};

export function AccessKeyDialog({ open, reason, hasStoredKey, onSubmit, onForget, onClose }: AccessKeyDialogProps) {
  const [value, setValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus(open, onClose, inputRef);

  useEffect(() => {
    if (open) {
      setValue("");
      setReveal(false);
      setInvalid(false);
    }
  }, [open]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!value.trim()) return;
    // Keys are plain ASCII; a Korean IME or smart quotes would make every request fail.
    if (!isValidAccessKey(value)) {
      setInvalid(true);
      inputRef.current?.focus();
      return;
    }
    onSubmit(value.trim());
  };

  const copy = COPY[reason];

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="access-key"
          className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-4 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="access-key-title"
            aria-describedby={invalid ? "access-key-desc access-key-error" : "access-key-desc"}
            tabIndex={-1}
            className="hud-panel w-full max-w-md"
            initial={{ scale: 0.95, y: 10 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.95, y: 10 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <form onSubmit={submit} className="space-y-4 p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full border border-neon/60 bg-neon/15 shadow-glow-sm">
                    <KeyRound aria-hidden="true" className="h-5 w-5 text-neon-hot" />
                  </span>
                  <div>
                    <h2
                      id="access-key-title"
                      className="font-display text-sm font-semibold tracking-[0.18em] text-white text-glow-soft"
                    >
                      {copy.title.toUpperCase()}
                    </h2>
                    <p className="hud-label normal-case tracking-[0.08em]">접근 키</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="hud-btn border-transparent bg-transparent"
                >
                  <X aria-hidden="true" className="h-4 w-4" />
                </button>
              </div>

              <p id="access-key-desc" className="text-[0.86rem] leading-relaxed text-petal-soft/85">
                {copy.body}
              </p>

              <div className="relative">
                <label htmlFor="access-key-input" className="hud-label mb-1.5 block">
                  Key
                </label>
                <input
                  id="access-key-input"
                  ref={inputRef}
                  type={reveal ? "text" : "password"}
                  value={value}
                  onChange={(event) => {
                    setValue(event.target.value);
                    setInvalid(false);
                  }}
                  autoComplete="current-password"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  aria-invalid={reason === "rejected" || invalid}
                  aria-errormessage={invalid ? "access-key-error" : undefined}
                  placeholder={hasStoredKey ? "Enter a new key" : "Paste your Jeannie access key"}
                  // 16px on phones: iOS Safari zooms into any smaller focused field.
                  className="hud-input min-h-[44px] px-3 pr-12 font-mono text-base sm:text-sm"
                />
                <button
                  type="button"
                  onClick={() => setReveal((r) => !r)}
                  aria-label={reveal ? "Hide key" : "Show key"}
                  className="hud-btn absolute bottom-0.5 right-0.5 border-transparent bg-transparent"
                >
                  {reveal ? (
                    <EyeOff aria-hidden="true" className="h-4 w-4" />
                  ) : (
                    <Eye aria-hidden="true" className="h-4 w-4" />
                  )}
                </button>
              </div>
              {invalid ? (
                <p id="access-key-error" role="alert" className="-mt-2 font-mono text-[0.72rem] text-neon-hot">
                  Keys use plain letters, digits and symbols (ASCII) only. · 영문, 숫자, 기호만 쓸 수 있어요.
                </p>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-2">
                {hasStoredKey ? (
                  <button
                    type="button"
                    onClick={onForget}
                    className="hud-btn px-3 font-mono text-[0.68rem] tracking-[0.14em]"
                  >
                    FORGET KEY
                  </button>
                ) : (
                  <span />
                )}
                <button
                  type="submit"
                  disabled={!value.trim()}
                  className="hud-btn hud-btn-primary px-4 font-mono text-[0.72rem] tracking-[0.18em]"
                >
                  UNLOCK
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
