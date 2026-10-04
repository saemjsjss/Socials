"use client";

import { useState } from "react";
import type { HangeulLocal } from "@/hooks/useHangeulLocal";
import { FIRST_SYNC_SIZE, MODEL_SIZE, percent } from "./HangeulSyncPanel";

interface HangeulSyncNoticeProps {
  local: HangeulLocal;
  total: number | null;
}

/**
 * The phone's avatar screen has no panels: the first sync's two moments show
 * here instead. On mobile data it asks before downloading; while it runs, a
 * progress line. Nothing otherwise.
 */
export function HangeulSyncNotice({ local, total }: HangeulSyncNoticeProps) {
  const [dismissed, setDismissed] = useState(false);
  const { state } = local;
  if (state.phase === "consent" && !dismissed) {
    return (
      <div className="hg-sync-notice" role="dialog" aria-label="Download the Hangeul data">
        <p>
          Download the Hangeul data to this phone? It is {FIRST_SYNC_SIZE} (plus {MODEL_SIZE} for search), and you seem to be on mobile
          data.
        </p>
        <p className="mt-0.5 text-[0.78rem] opacity-80" lang="ko">
          모바일 데이터로 한글 데이터를 내려받을까요?
        </p>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" onClick={() => setDismissed(true)}>
            Later
          </button>
          <button type="button" data-primary="true" onClick={local.allowMobileData}>
            Download
          </button>
        </div>
      </div>
    );
  }
  if (state.phase === "syncing" && state.progress) {
    const pct = percent(state.progress.records, total);
    return (
      <div className="hg-sync-notice" role="status" aria-live="polite">
        <p>
          Syncing the Hangeul data{pct !== null ? `: ${pct}%` : `: ${state.progress.records.toLocaleString("en-US")} records`}
        </p>
        {pct !== null ? (
          <div className="hg-sync-bar" aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </div>
        ) : null}
      </div>
    );
  }
  return null;
}
