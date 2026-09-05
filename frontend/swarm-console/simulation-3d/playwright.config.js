import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5189",
    channel:
      process.env.PLAYWRIGHT_CHANNEL ||
      (process.platform === "win32" ? "msedge" : "chromium"),
    launchOptions: { args: ["--enable-webgl", "--ignore-gpu-blocklist"] },
    viewport: { width: 1440, height: 960 },
  },
  webServer: {
    command: "npm run dev -- --port 5189",
    url: "http://127.0.0.1:5189",
    reuseExistingServer: false,
    timeout: 60000,
  },
});
