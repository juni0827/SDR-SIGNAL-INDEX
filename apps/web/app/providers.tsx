"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { ServiceWorkerRegistration } from "./service-worker-registration";

function RealtimeSync() {
  const client = useQueryClient();
  useEffect(() => {
    let polling: ReturnType<typeof setInterval> | undefined;
    const source = new EventSource(`${API_BASE}/realtime/events`, { withCredentials: true });
    const refresh = () => {
      void client.invalidateQueries();
    };
    for (const type of ["processing_progress","capture_progress","worker_status","new_session","transcript_completion","failed_job","receiver_status"]) {
      source.addEventListener(type, refresh);
    }
    source.onerror = () => {
      if (!polling) polling = setInterval(refresh, 10_000);
    };
    source.onopen = () => {
      if (polling) clearInterval(polling);
      polling = undefined;
    };
    return () => {
      source.close();
      if (polling) clearInterval(polling);
    };
  }, [client]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  }));
  return (
    <QueryClientProvider client={client}>
      {children}
      <RealtimeSync />
      <ServiceWorkerRegistration />
    </QueryClientProvider>
  );
}
