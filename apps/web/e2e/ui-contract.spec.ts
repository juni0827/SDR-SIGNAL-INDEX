import { expect, test } from "@playwright/test";

const envelope = (data: unknown) => ({
  data,
  provenance: [],
  query: {},
  pagination: {},
  warnings: [],
  generated_at_utc: "2026-01-01T00:00:00Z",
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/analytics/summary")) return route.fulfill({ json: envelope({ session_count: 1, segment_count: 1, active_duration_sec: 4, receiver_coverage: 1, top_callsigns: [], top_number_groups: [] }) });
    if (path.endsWith("/search/sessions")) return route.fulfill({ json: envelope([{ id: "session-1", title: "Test session", primary_frequency_hz: 4_625_000, start_at_utc: "2026-01-01T00:00:00Z", callsigns: [], number_groups: [], confidence: 0.8, status: "UNREVIEWED" }]) });
    if (path.endsWith("/receivers")) return route.fulfill({ json: envelope([]) });
    if (path.endsWith("/hypotheses")) return route.fulfill({ json: envelope([]) });
    if (path.endsWith("/segments/segment-1")) return route.fulfill({ json: envelope({ id: "segment-1", recording_id: "recording-1", start_sec: 0, end_sec: 4, segment_type: "VOICE", reviewed: false, transcripts: [{ id: "transcript-1", transcript_type: "MACHINE", text: "two eight one", is_preferred: true, confidence: 0.8, word_timestamps: [] }], entities: [] }) });
    if (path.endsWith("/segments/segment-1/media")) return route.fulfill({ json: envelope({ processed_url: null, waveform_url: null, spectrogram_url: null }) });
    if (path.endsWith("/recordings/recording-1/media")) return route.fulfill({ json: envelope({ original_url: "", processed_url: null, preview_url: null }) });
    if (path.endsWith("/graph")) return route.fulfill({ json: envelope({ nodes: [], edges: [] }) });
    if (path.endsWith("/inbox")) return route.fulfill({ json: envelope([]) });
    return route.fulfill({ status: 404, json: envelope({}) });
  });
});

test("login screen and browser-agent semantics", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Signal Index" })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("responsive navigation and command palette use semantic controls", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByTestId("main-content")).toBeVisible();
  await expect(page.getByText("Test session")).toBeVisible();
  await page.getByTestId("command-trigger").click();
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/sessions");
  await expect(page.getByTestId("session-search")).toBeVisible();
});

test("audio review, graph and offline inbox remain operable on mobile", async ({ page, context }) => {
  await page.goto("/segments/segment-1");
  await expect(page.getByTestId("audio-review")).toBeVisible();
  await expect(page.getByText("two eight one")).toBeVisible();
  await page.goto("/graph");
  await expect(page.getByTestId("relation-graph")).toBeVisible();
  await page.goto("/inbox");
  await context.setOffline(true);
  await page.locator('select[name="item_type"]').selectOption("observation");
  await page.locator('input[name="frequency_hz"]').fill("4625000");
  await page.locator('textarea[name="note"]').fill("Offline E2E note");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toContainText("Queued offline");
  await context.setOffline(false);
});
