import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioReviewView } from "./audio-review-view";
import { SettingsView } from "./management-views";

function envelope(data: unknown) {
  return { data, provenance: [], query: {}, pagination: {}, warnings: [], generated_at_utc: "2026-01-01T00:00:00Z" };
}

function jsonResponse(data: unknown, status = 200) {
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

describe("persistence-backed user actions", () => {
  it("posts a corrected preferred transcript while keeping the machine candidate visible", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith("/segments/segment-1")) return jsonResponse({
        id: "segment-1",
        recording_id: "recording-1",
        start_sec: 1,
        end_sec: 5,
        segment_type: "VOICE",
        reviewed: false,
        transcripts: [{ id: "machine-1", transcript_type: "MACHINE", text: "two eight one", language: "en", is_preferred: true, confidence: 0.7, word_timestamps: [] }],
        entities: [{ id: "entity-1", entity_type: "NUMBER_GROUP", raw_value: "two eight one", normalized_value: "281" }],
      });
      if (url.endsWith("/segments/segment-1/media")) return jsonResponse({ processed_url: null, waveform_url: null, spectrogram_url: null });
      if (url.endsWith("/recordings/recording-1/media")) return jsonResponse({ original_url: "https://signed.invalid/original", processed_url: null, preview_url: null });
      if (url.endsWith("/segments/segment-1/transcripts") && init?.method === "POST") return jsonResponse({ id: "corrected-1" }, 201);
      throw new Error(`unexpected request: ${url}`);
    }));
    renderQuery(<AudioReviewView segmentId="segment-1"/>);
    expect(await screen.findByText("two eight one")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("transcript-editor"), { target: { value: "281 corrected" } });
    fireEvent.click(screen.getByTestId("save-transcript"));
    await waitFor(() => expect(requests.some(request => request.url.endsWith("/transcripts") && request.init?.method === "POST")).toBe(true));
    const post = requests.find(request => request.url.endsWith("/transcripts") && request.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ text: "281 corrected", language: "en", mark_preferred: true });
    expect(screen.getByText("two eight one")).toBeInTheDocument();
  });

  it("stores settings as a new revision instead of mutating a client-only value", async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (init?.method === "POST") return jsonResponse({ id: "revision-1", key: "display.timezone", value: { value: "Asia/Seoul" } }, 201);
      return jsonResponse([]);
    }));
    renderQuery(<SettingsView/>);
    fireEvent.change(screen.getByPlaceholderText("display.timezone"), { target: { value: "display.timezone" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Value" }), { target: { value: "Asia/Seoul" } });
    fireEvent.click(screen.getByText("Save new revision"));
    expect(await screen.findByText("Revision stored.")).toBeInTheDocument();
    const post = requests.find(request => request.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ key: "display.timezone", value: { value: "Asia/Seoul" } });
  });
});
