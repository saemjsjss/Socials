"use client";

import { useEffect, useReducer } from "react";
import { fetchSystemStatus, onReachability } from "@/lib/client/api";
import { INITIAL_REACHABILITY, isOffline, reduceReachability, startProbeLoop, type Reachability } from "@/lib/client/reachability";

export interface OnlineStatus extends Reachability {
  /** Show the offline banner and disable the input (spec D10). */
  offline: boolean;
}

/**
 * navigator.onLine plus the online/offline events, plus API reachability: a
 * request that never reached the server (ApiRequestError status 0,
 * network_error) marks the API unreachable, and GET /api/status is re-probed
 * with a growing delay until it answers.
 */
export function useOnlineStatus(): OnlineStatus {
  const [state, dispatch] = useReducer(reduceReachability, INITIAL_REACHABILITY);

  useEffect(() => {
    dispatch({ type: "browser", online: navigator.onLine !== false });
    const online = () => dispatch({ type: "browser", online: true });
    const offline = () => dispatch({ type: "browser", online: false });
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    const unsubscribe = onReachability((reachable) => dispatch({ type: "api", reachable }));
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
      unsubscribe();
    };
  }, []);

  // While the browser says online but the API did not answer, re-probe /api/status.
  // A successful probe reports reachability itself (every request does).
  const probing = state.browserOnline && !state.apiReachable;
  useEffect(() => {
    if (!probing) return;
    const controller = new AbortController();
    const stop = startProbeLoop(() => fetchSystemStatus(controller.signal));
    return () => {
      controller.abort();
      stop();
    };
  }, [probing]);

  return { ...state, offline: isOffline(state) };
}
