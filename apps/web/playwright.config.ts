import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: process.env.E2E_EXTERNAL_SERVER === "1" ? undefined : {
    command: "npm run dev",
    url: "http://localhost:3000/login",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {name: "chromium", use: {...devices["Desktop Chrome"]}},
    {name: "mobile-chromium", use: {...devices["iPhone 13"], browserName: "chromium"}},
  ],
});
