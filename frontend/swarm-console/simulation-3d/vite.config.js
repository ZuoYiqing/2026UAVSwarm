import { defineConfig } from "vite";
import { viteStaticCopy } from "vite-plugin-static-copy";

const cesiumSource = "node_modules/cesium/Build/Cesium";
const cesiumBaseUrl = "cesium-static";

/**
 * 不参与应用构建、也不需要热更新的目录。
 *
 * 为什么必须排除这些：Playwright 运行时会在这两个目录里创建临时目录与文件
 * （例如 `e2e/.live-health.spec.js.<pid>.<uuid>.tmpdir/`），而 Vite 的监听器
 * 会去 watch 它们，撞上 Windows 的文件锁后抛
 * `EBUSY: resource busy or locked` —— **整个 Vite 进程崩掉**
 * （watch 的错误是未捕获的 error 事件，不是可以忽略的警告）。
 * 5179 一挂，所有依赖三维视图的集成测试就全线失败。
 *
 * 实测踩到过：跑一次集成测试 → Vite 退出 → 后续检查全挂。
 * 两边各自的行为都正常，冲突只在"谁去监听谁的临时文件"，因此在这里划开。
 */
const IGNORED = ["**/e2e/**", "**/test-results/**", "**/playwright-report/**"];

export default defineConfig({
  base: "./",
  define: {
    CESIUM_BASE_URL: JSON.stringify(`./${cesiumBaseUrl}`),
  },
  plugins: [
    viteStaticCopy({
      targets: [
        { src: `${cesiumSource}/ThirdParty`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Workers`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Assets`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Widgets`, dest: cesiumBaseUrl },
      ],
    }),
  ],
  server: {
    host: "127.0.0.1",
    port: 5179,
    strictPort: true,
    // 见上方 IGNORED 的说明：不监听测试产物，避免 EBUSY 打挂 Vite。
    watch: { ignored: IGNORED },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  // 预览模式另有一套监听配置，一并排除。
  preview: {
    watch: { ignored: IGNORED },
  },
});
