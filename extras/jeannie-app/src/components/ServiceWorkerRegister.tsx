"use client";

import { useEffect } from "react";

/** Registers the hand-written service worker (public/sw.js). Production only: in dev it would cache HMR chunks. */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((error: unknown) => {
      console.warn("Service worker registration failed", error);
    });
  }, []);

  return null;
}
