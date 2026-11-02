import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "test-results",
  use: { baseURL: process.env.UI_URL ?? "http://localhost:15173", viewport: { width: 1360, height: 860 }, locale: "en-GB", screenshot: "off" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
