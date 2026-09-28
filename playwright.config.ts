import { defineConfig } from "@playwright/test";

const browserChannel =
  process.env.PLAYWRIGHT_BROWSER_CHANNEL ??
  (process.platform === "win32" ? "msedge" : undefined);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:18761",
    browserName: "chromium",
    channel: browserChannel,
    trace: "retain-on-failure",
  },
});
