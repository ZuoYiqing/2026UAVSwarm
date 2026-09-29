import { defineConfig } from "@playwright/test";

/**
 * 闆嗘垚楠岃瘉涓撶敤閰嶇疆锛氫富鎺у埗鍙?+ 涓夌淮瑙嗗浘涓や釜鏈嶅姟閮界敱娴嬭瘯鑷繁鎷夎捣銆? *
 * 涓庝富閰嶇疆鍒嗗紑锛屽洜涓轰富閰嶇疆鐨?webServer 鍙捣 5189 鐨勪笁缁磋鍥撅紝
 * 鑰岃繖閲岀殑閲嶇偣鏄?鐪熷疄涓绘帶鍒跺彴閲岀殑 iframe 鏄惁琚噸澶嶅姞杞?锛? * 闇€瑕?5178 閭ｄ竴渚х殑鐪熷疄椤甸潰鍚屾椂鍦ㄥ満銆? */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /(console-integration|selection-sync|live-health|stale-probe)\.spec\.js$/,
  timeout: 90000,
  workers: 1,
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL || (process.platform === "win32" ? "msedge" : "chromium"),
    viewport: { width: 1440, height: 960 },
  },
  webServer: [
    {
      // 涓绘帶鍒跺彴闈欐€佺珯锛堢湡瀹?app.js / index.html锛夛紝绔彛涓庣敓浜т竴鑷?      command: "python -m http.server 5178 --directory ..",
      url: "http://127.0.0.1:5178/index.html",
      reuseExistingServer: true,
      timeout: 60000,
      cwd: ".",
    },
    {
      // 涓夌淮瑙嗗浘锛歩frame 鎸囧悜鐨勭湡瀹炲瓙搴旂敤锛岀鍙ｄ笌鐢熶骇涓€鑷淬€?      // 鍥犳鏈祴璇曡窇鐨勫氨鏄?*鐪熷疄鐨勮法鍩熸嫇鎵?*锛?178 鐖?/ 5179 瀛愶級銆?      command: "npm run dev -- --port 5179 --strictPort",
      url: "http://127.0.0.1:5179",
      reuseExistingServer: true,
      timeout: 90000,
      cwd: ".",
    },
  ],
});
