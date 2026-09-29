import { defineConfig } from "@playwright/test";

/**
 * 集成验证专用配置：主控制台 + 三维视图两个服务都由测试自己拉起。
 *
 * 与主配置分开，因为主配置的 webServer 只起 5189 的三维视图，
 * 而这里的重点是"真实主控制台里的 iframe 是否被重复加载"，
 * 需要 5178 那一侧的真实页面同时在场。
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /(console-integration|selection-sync|console-dom-probe)\.spec\.js$/,
  timeout: 90000,
  workers: 1,
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL || (process.platform === "win32" ? "msedge" : "chromium"),
    viewport: { width: 1440, height: 960 },
  },
  webServer: [
    {
      // 主控制台静态站（真实 app.js / index.html），端口与生产一致
      command: "python -m http.server 5178 --directory ..",
      url: "http://127.0.0.1:5178/index.html",
      reuseExistingServer: true,
      timeout: 60000,
      cwd: ".",
    },
    {
      // 三维视图：iframe 指向的真实子应用，端口与生产一致。
      // 因此本测试跑的就是**真实的跨域拓扑**（5178 父 / 5179 子）。
      command: "npm run dev -- --port 5179 --strictPort",
      url: "http://127.0.0.1:5179",
      reuseExistingServer: true,
      timeout: 90000,
      cwd: ".",
    },
  ],
});
