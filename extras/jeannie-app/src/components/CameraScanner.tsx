"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Aperture, CameraOff, LoaderCircle, ScanLine, SwitchCamera, X } from "lucide-react";
import { useDialogFocus } from "@/hooks/useDialogFocus";
import { encodeJpeg } from "@/lib/client/image";
import { cn } from "@/lib/utils";

type Facing = "environment" | "user";
type CameraIssue = "insecure" | "unsupported" | "denied" | "missing" | "busy" | "unknown";

const ISSUE_TEXT: Record<CameraIssue, { title: string; body: string }> = {
  insecure: {
    title: "Secure connection required",
    body: "Browsers only allow camera access over HTTPS or on localhost. Open Jeannie over HTTPS to scan.",
  },
  unsupported: {
    title: "Camera not supported",
    body: "This browser does not expose a camera API. Use image upload instead.",
  },
  denied: {
    title: "Camera permission denied",
    body: "Allow camera access for this site in your browser settings, then try again. 카메라 권한을 허용해 주세요.",
  },
  missing: {
    title: "No camera found",
    body: "No video input device is available. Connect a camera or attach an image instead.",
  },
  busy: { title: "Camera is busy", body: "Another app is using the camera. Close it and try again." },
  unknown: {
    title: "Camera unavailable",
    body: "The camera could not be started. Try again or attach an image instead.",
  },
};

function classify(error: unknown): CameraIssue {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return "missing";
  if (name === "NotReadableError" || name === "TrackStartError") return "busy";
  return "unknown";
}

interface CameraScannerProps {
  open: boolean;
  onClose: () => void;
  /** JPEG data URL, max 1280 px. */
  onCapture: (dataUrl: string) => void;
}

export function CameraScanner({ open, onClose, onCapture }: CameraScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const captureRef = useRef<HTMLButtonElement>(null);
  const [facing, setFacing] = useState<Facing>("environment");
  const [issue, setIssue] = useState<CameraIssue | null>(null);
  const [starting, setStarting] = useState(false);
  const [canSwitch, setCanSwitch] = useState(false);
  const [flash, setFlash] = useState(false);
  const dialogRef = useDialogFocus(open, onClose, captureRef);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    const start = async () => {
      setIssue(null);
      if (!window.isSecureContext) return setIssue("insecure");
      if (!navigator.mediaDevices?.getUserMedia) return setIssue("unsupported");
      setStarting(true);
      try {
        stopTracks();
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
        }
        const devices = await navigator.mediaDevices.enumerateDevices().catch(() => []);
        if (!cancelled) setCanSwitch(devices.filter((d) => d.kind === "videoinput").length > 1);
      } catch (error) {
        if (!cancelled) setIssue(classify(error));
      } finally {
        if (!cancelled) setStarting(false);
      }
    };
    void start();

    return () => {
      cancelled = true;
      stopTracks();
    };
  }, [open, facing, stopTracks]);

  // Release the camera if the tab is hidden while scanning.
  useEffect(() => {
    if (!open) return;
    const onVisibility = () => {
      if (document.visibilityState === "hidden") onClose();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [open, onClose]);

  const capture = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) return;
    try {
      const { dataUrl } = encodeJpeg(video, video.videoWidth, video.videoHeight, { mirror: facing === "user" });
      setFlash(true);
      window.setTimeout(() => {
        setFlash(false);
        onCapture(dataUrl);
        onClose();
      }, 180);
    } catch {
      setIssue("unknown");
    }
  };

  const issueText = issue ? ISSUE_TEXT[issue] : null;

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="camera-scanner"
          className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-3 backdrop-blur-md sm:p-6"
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
            aria-labelledby="camera-scanner-title"
            tabIndex={-1}
            className="hud-panel flex max-h-full w-full max-w-2xl flex-col overflow-hidden"
            initial={{ scale: 0.96, y: 12 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.96, y: 12 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center justify-between gap-2 border-b border-neon/25 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <ScanLine aria-hidden="true" className="h-4 w-4 text-neon-hot" />
                <h2 id="camera-scanner-title" className="hud-title truncate">
                  Optical Scanner
                </h2>
                <span className="hud-label hidden normal-case tracking-[0.08em] sm:inline">카메라 스캐너</span>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close camera scanner"
                className="hud-btn border-transparent bg-transparent"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </header>

            <div className="relative aspect-[4/3] max-h-[70vh] w-full overflow-hidden bg-black">
              <video
                ref={videoRef}
                playsInline
                muted
                autoPlay
                aria-label="Live camera preview"
                className={cn("h-full w-full object-cover", facing === "user" && "-scale-x-100", issue && "hidden")}
              />

              {!issue ? (
                <div className="pointer-events-none absolute inset-0" aria-hidden="true">
                  {/* Vignette keeps the overlay legible on bright scenes. */}
                  <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_50%,rgba(10,5,10,0.6)_100%)]" />
                  <div className="absolute inset-0 bg-neon/[0.04] mix-blend-screen" />
                  {/* Reticle: corner brackets + centre crosshair + sweeping scan line */}
                  <div className="absolute inset-[8%]">
                    {[
                      "left-0 top-0 border-l-2 border-t-2",
                      "right-0 top-0 border-r-2 border-t-2",
                      "bottom-0 left-0 border-b-2 border-l-2",
                      "bottom-0 right-0 border-b-2 border-r-2",
                    ].map((corner) => (
                      <span
                        key={corner}
                        className={cn(
                          "absolute h-10 w-10 border-neon-hot drop-shadow-[0_0_6px_rgba(255,0,127,0.9)]",
                          corner,
                        )}
                      />
                    ))}
                    <span className="scan-line" />
                    <span className="absolute left-1/2 top-1/2 h-8 w-8 -translate-x-1/2 -translate-y-1/2 rounded-full border border-neon-hot/70" />
                    <span className="absolute left-1/2 top-1/2 h-px w-16 -translate-x-1/2 bg-neon-hot/60" />
                    <span className="absolute left-1/2 top-1/2 h-16 w-px -translate-y-1/2 bg-neon-hot/60" />
                  </div>
                  <p className="absolute left-3 top-3 font-mono text-[0.62rem] tracking-[0.2em] text-neon-hot text-glow-soft">
                    {starting ? "INITIALISING OPTICS…" : "TARGET ACQUISITION"}
                  </p>
                  <p className="absolute bottom-3 right-3 font-mono text-[0.62rem] tracking-[0.2em] text-petal-soft/80">
                    {facing === "environment" ? "REAR CAM" : "FRONT CAM"}
                  </p>
                </div>
              ) : null}

              {starting && !issue ? (
                <div className="absolute inset-0 flex items-center justify-center">
                  <LoaderCircle aria-label="Starting camera" className="h-8 w-8 animate-spin text-neon-hot" />
                </div>
              ) : null}

              {issueText ? (
                <div
                  role="alert"
                  className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center"
                >
                  <CameraOff
                    aria-hidden="true"
                    className="h-10 w-10 text-neon-hot drop-shadow-[0_0_10px_rgba(255,0,127,0.8)]"
                  />
                  <p className="font-display text-sm tracking-[0.16em] text-white">{issueText.title}</p>
                  <p className="max-w-sm text-[0.85rem] leading-relaxed text-petal-soft/80">{issueText.body}</p>
                </div>
              ) : null}

              {flash ? <div className="absolute inset-0 bg-white/80" aria-hidden="true" /> : null}
            </div>

            <footer className="flex items-center justify-between gap-2 border-t border-neon/25 px-3 py-2.5">
              <button
                type="button"
                onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
                disabled={!canSwitch || Boolean(issue)}
                aria-label="Switch between front and back camera"
                title="Switch camera"
                className="hud-btn px-3"
              >
                <SwitchCamera aria-hidden="true" className="h-4 w-4" />
                <span className="hidden font-mono text-[0.66rem] tracking-[0.14em] sm:inline">FLIP</span>
              </button>
              <button
                ref={captureRef}
                type="button"
                onClick={capture}
                disabled={Boolean(issue) || starting}
                className="hud-btn hud-btn-primary min-h-[48px] px-5 font-mono text-[0.74rem] tracking-[0.2em]"
              >
                <Aperture aria-hidden="true" className="h-5 w-5" />
                CAPTURE
              </button>
              <button
                type="button"
                onClick={onClose}
                className="hud-btn px-3 font-mono text-[0.66rem] tracking-[0.14em]"
              >
                CANCEL
              </button>
            </footer>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
