"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, fetchSystemStatus, isAbortError } from "@/lib/client/api";
import type { SystemStatus } from "@/lib/types";

export interface SystemStatusState {
  status: SystemStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/** GET /api/status on mount (and on demand). Failures leave `status` null with a readable error. */
export function useSystemStatus(): SystemStatusState {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    fetchSystemStatus(controller.signal)
      .then((next) => {
        setStatus(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setError(err instanceof ApiRequestError ? err.message : "Status feed unavailable.");
      })
      .finally(() => {
        if (controllerRef.current === controller) setLoading(false);
      });
  }, []);

  useEffect(() => {
    refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  return { status, loading, error, refresh };
}
