import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FrequenciesView } from "./catalog-views";

function envelope(data: unknown) {
  return { data, provenance: [], query: {}, pagination: {}, warnings: [], generated_at_utc: "2026-01-01T00:00:00Z" };
}

function response(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(envelope(data)), { status: 200, headers: { "content-type": "application/json" } }));
}

function renderQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><FrequenciesView/></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("indexed activity spectrum", () => {
  it("renders a real canvas waterfall from the spectrum endpoint rather than activity bars", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      setTransform: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), strokeRect: vi.fn(), setLineDash: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 900, height: 480 } as DOMRect);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/spectrum?")) return response({
        kind: "INDEXED_ACTIVITY_WATERFALL", raw_fft_available: false,
        start_at_utc: "2026-01-01T00:00:00Z", end_at_utc: "2026-01-02T00:00:00Z",
        frequency_min_hz: 2_000_000, frequency_max_hz: 30_000_000,
        time_bins: 96, frequency_bins: 96, time_bin_sec: 900, frequency_bin_hz: 291667,
        cells: [{ time_bin: 2, frequency_bin: 8, session_count: 3, active_duration_sec: 45, mean_confidence: 0.8 }],
        sessions: [{ id: "session-1", title: "Synthetic session", primary_frequency_hz: 4_625_000, start_at_utc: "2026-01-01T00:30:00Z", end_at_utc: "2026-01-01T00:31:00Z", confidence: 0.8, callsigns: ["ALPHA"], number_groups: ["281"], receiver_ids: [], category: "NUMBERS", status: "UNREVIEWED" }],
        markers: [{ id: "frequency-1", frequency_hz: 4_625_000, label: "Synthetic marker", category: "NUMBERS", mode: "USB", watchlisted: true, favorite: false }],
      });
      if (url.endsWith("/receivers?limit=500")) return response([]);
      throw new Error(`unexpected request: ${url}`);
    }));
    renderQuery();
    expect(await screen.findByText("Activity waterfall")).toBeInTheDocument();
    expect(screen.getByTestId("spectrum-waterfall")).toBeInTheDocument();
    expect(screen.getByText("Synthetic marker")).toBeInTheDocument();
    expect(screen.getByText(/not a live receiver FFT or IQ waterfall/i)).toBeInTheDocument();
  });
});
