import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CaptureView, SourcesView } from "./management-views";

function envelope(data: unknown) {
  return { data, provenance: [], query: {}, pagination: {}, warnings: [], generated_at_utc: "2026-01-01T00:00:00Z" };
}

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(envelope(data)), { status, headers: { "content-type": "application/json" } }));
}

function renderQuery(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("autonomous collection controls", () => {
  it("enables a persisted remote source instead of creating a browser-only fetch", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/sources/source-1") && !init?.method) {
        return response({ id: "source-1", name: "Public schedule", adapter_type: "rss_atom", enabled: false, config: { interval_sec: 900 }, last_fetched_at: null });
      }
      if (url.endsWith("/sources/source-1") && init?.method === "PATCH") return response({ id: "source-1", enabled: true });
      throw new Error(`unexpected request: ${url}`);
    }));
    renderQuery(<SourcesView id="source-1"/>);
    fireEvent.click(await screen.findByText("Enable background collection"));
    await waitFor(() => expect(requests.some(request => request.init?.method === "PATCH")).toBe(true));
    const patch = requests.find(request => request.init?.method === "PATCH");
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ enabled: true });
  });

  it("creates an enabled recurring capture schedule for an opted-in receiver", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/receivers?limit=500")) {
        return response([{ id: "receiver-1", name: "Permitted receiver", metadata_json: { capture_enabled: true, capture_url_template: "https://receiver.example/audio?f={frequency_hz}" } }]);
      }
      if (url.endsWith("/capture?limit=100")) return response([]);
      if (url.endsWith("/capture") && init?.method === "POST") return response({ id: "capture-1", enabled: true }, 201);
      if (url.endsWith("/automation/status")) return response({});
      throw new Error(`unexpected request: ${url}`);
    }));
    renderQuery(<CaptureView/>);
    await screen.findByText("Permitted receiver");
    fireEvent.change(screen.getByLabelText("Frequency Hz"), { target: { value: "4625000" } });
    fireEvent.click(screen.getByText("Create autonomous schedule"));
    await waitFor(() => expect(requests.some(request => request.url.endsWith("/capture") && request.init?.method === "POST")).toBe(true));
    const create = requests.find(request => request.url.endsWith("/capture") && request.init?.method === "POST");
    const payload = JSON.parse(String(create?.init?.body));
    expect(payload).toMatchObject({ receiver_id: "receiver-1", frequency_hz: 4625000, enabled: true, repetition: "*/15 * * * *" });
  });
});
