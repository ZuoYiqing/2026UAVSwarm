import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // console-integration.spec.js 由 playwright.integration.config.js 单独运行。
  //
  // 它验证的是"主控制台（5178）里的 iframe 不被重复加载"，需要 5178 与 5179
  // 两个服务同时在场（真实跨域拓扑）。本配置的 webServer 只起 5189 一个
  // 三维视图服务，因此在这里它无法成立 —— 混跑时它会因拿不到 5178 而失败，
  // 表现为"单独跑通过、全量跑失败"。
  testIgnore: /console-integration\.spec\.js$/,
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
