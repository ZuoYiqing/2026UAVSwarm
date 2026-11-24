// Run after npm run build. All requests are intercepted; no HTTP server is needed.
import assert from "node:assert/strict";
import { resolve, sep } from "node:path";
import { chromium } from "playwright";
import { PNG } from "pngjs";

const dist = resolve(process.env.UAVSWARM_TWIN_DIST || "dist");
const origin = "http://127.0.0.1:58983";
const markerPixels = [
  { id: "002", x: 783, y: 506, rgb: [255, 164, 47] },
  { id: "001", x: 675, y: 467, rgb: [41, 171, 226] },
  { id: "northwest outline", x: 713, y: 376, rgb: [22, 216, 231] },
  { id: "southwest outline", x: 639, y: 488, rgb: [188, 119, 245] },
  { id: "southeast outline", x: 749, y: 527, rgb: [188, 119, 245] },
];
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: "block" });
  const page = await context.newPage();
  const writes = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await context.route("**/*", route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!["GET", "HEAD"].includes(request.method())) {
      writes.push(request.method() + " " + url.pathname);
      return route.abort();
    }
    if (url.origin !== origin) return route.abort();
    if (url.pathname.startsWith("/api/")) return route.fulfill({ status: 503, json: { reason: "isolated_review" } });
    const file = resolve(dist, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
    if (!file.startsWith(dist + sep)) return route.abort();
    return route.fulfill({ path: file });
  });

  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.SwarmSimulationBridge?.getState().sceneId === "recon");
  const canvas = page.locator("#cesium-container canvas").first();
  let visible;
  for (let i = 0; i < 12; i += 1) {
    const png = PNG.sync.read(await canvas.screenshot());
    visible = markerPixels.filter(({ x, y, rgb }) => {
      const offset = (y * png.width + x) * 4;
      return rgb.every((channel, k) => Math.abs(png.data[offset + k] - channel) <= 5);
    }).map(marker => marker.id);
    if (visible.length === markerPixels.length) break;
  }
  assert.deepEqual(visible, markerPixels.map(marker => marker.id), "default WebGL view must retain all five markers");

  await page.locator("#goto-armed").check();
  const target = page.locator("#goto-target");
  for (const { id, x, y } of markerPixels) {
    await page.mouse.click(850, 550);
    await target.waitFor({ state: "visible", timeout: 3000 });
    const lastGroundPick = await page.evaluate(() => window.__uavLastPick);
    assert.deepEqual(lastGroundPick.windowPx, { x: 850, y: 550 });
    await page.mouse.click(x, y);
    assert.equal(await target.isVisible(), false, `${id} staged a target: ${await target.textContent()}`);
    assert.equal(await page.locator("#action-result").getAttribute("data-state"), "error");
    assert.deepEqual(await page.evaluate(() => window.__uavLastPick), lastGroundPick);
    console.log(`${id} at (${x}, ${y}): visible, no target staged, previous target cleared`);
  }
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("Ordinary ground pick preserved; five preview-only clicks rejected; zero write requests.");
} finally {
  await browser.close();
}
