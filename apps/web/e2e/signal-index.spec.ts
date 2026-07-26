import { expect, test } from "@playwright/test";

test("login screen and browser-agent semantics", async ({page}) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", {name: "Signal Index"})).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveValue("owner@local.test");
  await expect(page.getByRole("button", {name: "Sign in"})).toBeVisible();
});

test("responsive navigation, search, review, graph and offline inbox", async ({page, context}) => {
  await page.goto("/dashboard");
  await expect(page.getByTestId("main-content")).toBeVisible();
  await page.getByTestId("command-trigger").click();
  await expect(page.getByRole("dialog", {name: "Command palette"})).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/sessions");
  await expect(page.getByTestId("session-search")).toBeVisible();
  await page.goto("/segments/demo");
  await expect(page.getByTestId("audio-review")).toBeVisible();
  await page.goto("/graph");
  await expect(page.getByTestId("relation-graph")).toBeVisible();
  await page.goto("/inbox");
  await context.setOffline(true);
  await expect(page.getByTestId("inbox-form")).toBeVisible();
  await page.locator('input[name="frequency_hz"]').fill("4625000");
  await page.locator('textarea[name="note"]').fill("Offline E2E note");
  await page.getByRole("button", {name: "Save to inbox"}).click();
  await expect(page.getByRole("status")).toContainText("Saved");
  await context.setOffline(false);
});

test("full upload, processing, correction, hypothesis and evidence flow", async ({page}) => {
  test.skip(process.env.E2E_REAL_STACK !== "1", "requires the full API, worker and storage stack");
  await page.goto("/login");
  await page.getByLabel("Email").fill(process.env.FIRST_USER_EMAIL ?? "owner@local.test");
  await page.getByLabel("Password").fill(process.env.FIRST_USER_PASSWORD ?? "change-this-password");
  await page.getByRole("button", {name: "Sign in"}).click();
  await page.waitForURL("**/dashboard");
  await page.goto("/inbox");
  const sample = Buffer.alloc(44 + 16_000 * 2);
  sample.write("RIFF", 0);
  sample.writeUInt32LE(sample.length - 8, 4);
  sample.write("WAVEfmt ", 8);
  sample.writeUInt32LE(16, 16);
  sample.writeUInt16LE(1, 20);
  sample.writeUInt16LE(1, 22);
  sample.writeUInt32LE(16_000, 24);
  sample.writeUInt32LE(32_000, 28);
  sample.writeUInt16LE(2, 32);
  sample.writeUInt16LE(16, 34);
  sample.write("data", 36);
  sample.writeUInt32LE(sample.length - 44, 40);
  await page.locator('input[name="file"]').setInputFiles({
    name: "e2e.wav",
    mimeType: "audio/wav",
    buffer: sample,
  });
  await page.locator('input[name="frequency_hz"]').fill("4625000");
  await page.getByRole("button", {name: "Save to inbox"}).click();
  await expect(page.getByRole("status")).toContainText("Saved");
  const apiBase = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
  const csrfCookie = (await page.context().cookies()).find(cookie => cookie.name === "signal_csrf");
  expect(csrfCookie).toBeTruthy();
  let sessionId = "";
  await expect.poll(async () => {
    const response = await page.request.post(`${apiBase}/search/sessions`, {
      headers: {"x-csrf-token": csrfCookie!.value},
      data: {frequency_min_hz: 4625000, frequency_max_hz: 4625000, limit: 10},
    });
    if (!response.ok()) return 0;
    const body = await response.json();
    sessionId = body.data[0]?.id ?? "";
    return body.data.length;
  }, {timeout: 300_000, intervals: [2000, 5000]}).toBeGreaterThan(0);
  const detail = await page.request.get(`${apiBase}/sessions/${sessionId}`);
  expect(detail.ok()).toBeTruthy();
  const session = (await detail.json()).data;
  expect(session.segment_ids.length).toBeGreaterThan(0);
  const correction = await page.request.post(
    `${apiBase}/segments/${session.segment_ids[0]}/transcripts`,
    {
      headers: {"x-csrf-token": csrfCookie!.value},
      data: {text: "E2E corrected transcript", language: "en", mark_preferred: true},
    },
  );
  expect(correction.ok()).toBeTruthy();
  const hypothesis = await page.request.post(`${apiBase}/hypotheses`, {
    headers: {"x-csrf-token": csrfCookie!.value},
    data: {
      title: "E2E evidence hypothesis",
      statement: "This is an end-to-end test hypothesis.",
      related_session_ids: [sessionId],
      created_by: "USER",
    },
  });
  expect(hypothesis.ok()).toBeTruthy();
  const evidence = await page.request.get(`${apiBase}/export/evidence-bundle?session_id=${sessionId}`);
  expect(evidence.ok()).toBeTruthy();
  expect((await evidence.body()).subarray(0, 2).toString()).toBe("PK");
});
