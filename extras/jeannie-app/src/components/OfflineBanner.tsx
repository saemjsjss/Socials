"use client";

import { WifiOff } from "lucide-react";
import { OFFLINE_LINE } from "@/lib/client/reachability";

interface OfflineBannerProps {
  offline: boolean;
  /** "avatar" on the phone's light avatar screen, "hud" on the dark HUD. */
  variant: "hud" | "avatar";
}

/**
 * "Offline: Jeannie needs a connection" (spec D10). The live region is always
 * mounted so a screen reader announces the line when it appears; there are no
 * offline answers, the input is disabled instead.
 */
export function OfflineBanner({ offline, variant }: OfflineBannerProps) {
  return (
    <div role="status" aria-live="polite" className="offline-banner-region">
      {offline ? (
        <p className="offline-banner" data-variant={variant}>
          <WifiOff aria-hidden="true" className="h-4 w-4 shrink-0" />
          <span className="min-w-0">
            <span className="block">{OFFLINE_LINE.en}</span>
            <span className="block text-[0.72rem] opacity-80" lang="ko">
              {OFFLINE_LINE.ko}
            </span>
          </span>
        </p>
      ) : null}
    </div>
  );
}
