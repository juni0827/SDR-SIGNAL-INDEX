"use client";

import { useEffect } from "react";
import { syncMutations } from "@/lib/offline";

export function ServiceWorkerRegistration() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch((error: unknown) => {
        console.error("service_worker_registration_failed", error);
      });
    }
    const sync = () => void syncMutations().catch((error: unknown) => {
      console.error("offline_sync_failed", error);
    });
    const message = (event: MessageEvent<{type?: string}>) => {
      if (event.data?.type === "SYNC_REQUIRED") sync();
    };
    navigator.serviceWorker?.addEventListener("message", message);
    window.addEventListener("online", sync);
    sync();
    return () => {
      window.removeEventListener("online", sync);
      navigator.serviceWorker?.removeEventListener("message", message);
    };
  }, []);
  return null;
}
