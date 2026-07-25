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
    window.addEventListener("online", sync);
    sync();
    return () => window.removeEventListener("online", sync);
  }, []);
  return null;
}

