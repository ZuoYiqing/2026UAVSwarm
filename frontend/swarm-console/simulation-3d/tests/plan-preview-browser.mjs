// Run after npm run build. Intercept every request; no service or Runtime is needed.
import assert from "node:assert/strict";
import { resolve, sep } from "node:path";
import { chromium } from "playwright";
import { PNG } from "pngjs";
import { planPreview } from "./fixtures/plan-preview.js";
import { publicSnapshot } from "./fixtures/public-snapshot.js";

const parentOrigin = "http://127.0.0.1:5178";
const childOrigin = "http://127.0.0.1:5179";
const dist = resolve("dist");
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
const testCases = [
  { name: "plan-first", viewport: { width: 1366, height: 900 } },
  { name: "telemetry-first", viewport: { width: 390, height: 844 } },
];

function isPreviewLinePixel(png, i) {
  const [r, g, b] = png.data.subarray(i, i + 3);
  if (r < 140 || r > 186 || g < 64 || g > 93 || b > 39) return false;
  const x = (i / 4) % png.width, y = Math.floor(i / 4 / png.width);
  if (x < 7 || y < 7 || x + 7 >= png.width || y + 7 >= png.height) return false;
  // Exclude the dark rims around the white centers of the waypoint markers.
  for (let dy = -7; dy <= 7; dy += 1) {
    for (let dx = -7; dx <= 7; dx += 1) {
      const index = i + (dy * png.width + dx) * 4;
      if (png.data[index] > 235 && png.data[index + 1] > 235 && png.data[index + 2] > 235) return false;
    }
  }
  return true;
}

try {
  for (const { name, viewport } of testCases) {
    const context = await browser.newContext({ viewport, serviceWorkers: "block" });
    const page = await context.newPage();
    await page.clock.install();
    const writes = [];
    const errors = [];
    const api = [];
    page.on("pageerror", error => errors.push(error.message));
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (!["GET", "HEAD"].includes(request.method())) {
        writes.push(request.method() + " " + url.pathname);
        return route.abort();
      }
      if (url.pathname.startsWith("/api/")) api.push(url.pathname);
      if (url.origin === parentOrigin && url.pathname === "/") {
        return route.fulfill({ contentType: "text/html", body: `
          <style>body{margin:0} iframe{width:100vw;height:100vh;border:0;display:block}</style>
          <script>
            window.readies = 0;
            addEventListener("message", event => {
              if (event.source === document.querySelector("#twin")?.contentWindow &&
                  event.origin === "${childOrigin}" && event.data?.type === "uav-swarm/simulation-ready") ++window.readies;
            });
          </script>
          <iframe id="twin" src="${childOrigin}/?planPreview=fixture"></iframe>` });
      }
      if (url.origin !== childOrigin) return route.abort();
      const asset = resolve(dist, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
      if (!asset.startsWith(dist + sep)) return route.abort();
      return route.fulfill({ path: asset });
    });
    await page.goto(parentOrigin, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.readies === 1);
    const frame = () => {
      const twin = page.frames().find(item => item.url().startsWith(childOrigin));
      assert.ok(twin);
      return twin;
    };
    const state = () => frame().evaluate(() => window.SwarmSimulationBridge.getState());
    const send = (type, payload) => page.evaluate(({ type, payload, target }) => {
      document.querySelector("#twin").contentWindow.postMessage({ type, payload }, target);
    }, { type, payload, target: childOrigin });
    const sendPlan = payload => send("uav-swarm/plan-preview", payload);
    const waitPreview = planId => frame().waitForFunction(planId => {
      const preview = window.SwarmSimulationBridge.getState().planPreview;
      return (preview?.planId ?? null) === planId;
    }, planId);
    const sendPose = async (ned, stale, length) => {
      const time = await frame().evaluate(() => Date.now());
      const snapshot = publicSnapshot({ time, positions: [[0, 0, 0], ned, [0, -8, 0]] });
      snapshot.vehicles[1].telemetry.stale = stale;
      await send("uav-swarm/vehicle-snapshot", snapshot);
      await frame().waitForFunction(({ time, length }) => {
        const bridge = window.SwarmSimulationBridge.getState();
        const vehicle = bridge.alignment.find(row => row.id === "UAV-02");
        return vehicle?.trailLength === length && bridge.source?.id === "contract-fixture"
          && Date.now() >= time;
      }, { time, length });
    };

    // Allow time for software WebGL to render even when both owners run the probe.
    const preview = planPreview(await page.evaluate(() => Date.now() + 180_000));
    if (name === "telemetry-first") await sendPose([12, 18, -5], true, 0);
    await sendPlan(preview);
    await waitPreview(preview.plan_id);
    assert.equal((await state()).planPreview.waypointCount, 5);
    const legend = () => page.frameLocator("#twin").locator("#plan-preview-status");
    assert.equal(await legend().isVisible(), true);
    assert.equal(await legend().textContent(), "\u8ba1\u5212\u9884\u89c8 \u00b7 \u6d4b\u8bd5\u6869");
    assert.equal(await page.frameLocator("#twin").locator("#goto-actions").isVisible(), false);
    if (name === "plan-first") {
      assert.equal((await state()).vehicleCount, 0);
      await sendPose([12, 18, -5], true, 0);
    }
    await page.clock.fastForward(600);
    await sendPose([3, 9, -2], false, 1);
    const measured = (await state()).alignment;
    assert.equal(measured[1].position.eastM, 9);
    assert.equal((await state()).planPreview.expiresAtMs, preview.expires_at_ms);

    const canvas = page.frameLocator("#twin").locator("#cesium-container canvas").first();
    const colors = new Set();
    let previewPixels = 0;
    // Cesium builds polylines asynchronously; the waypoint rings can be visible first.
    for (let attempt = 0; attempt < 15 && previewPixels < 12; attempt += 1) {
      const png = PNG.sync.read(await canvas.screenshot({ path: `test-results/plan-preview-${name}.png` }));
      colors.clear();
      previewPixels = 0;
      for (let i = 0; i < png.data.length; i += 4) {
        if (i % 64 === 0) colors.add(png.data.readUInt32LE(i));
        if (isPreviewLinePixel(png, i)) previewPixels += 1;
      }
    }
    assert.ok(colors.size >= 8, "Cesium must render more than a blank frame");
    assert.ok(previewPixels >= 12, `preview line pixels beyond waypoint rings: ${previewPixels}`);

    // A wrong-window clear is ignored; a trusted cross-map message removes only the plan.
    await frame().evaluate(() => window.postMessage({ type: "uav-swarm/plan-preview", payload: null }, location.origin));
    await waitPreview(preview.plan_id);
    await sendPlan({ ...preview, map_version: "other-map" });
    await waitPreview(null);
    assert.equal(await legend().isVisible(), false);
    assert.deepEqual((await state()).alignment, measured);
    await sendPlan(preview);
    await waitPreview(preview.plan_id);
    await sendPlan(null);
    await waitPreview(null);
    assert.deepEqual((await state()).alignment, measured);

    // A reload gets no retained plan unless the parent resends, and that original expiry is not renewed.
    await page.locator("#twin").evaluate((el, url) => { el.src = url; }, childOrigin + "/?planPreview=fixture&reload");
    await page.waitForFunction(() => window.readies === 2);
    await waitPreview(null);
    await sendPlan(preview);
    await waitPreview(preview.plan_id);
    assert.equal((await state()).planPreview.expiresAtMs, preview.expires_at_ms);
    await sendPose([3, 9, -2], false, 1);
    const afterReload = (await state()).alignment;
    await page.clock.fastForward(180_001);
    await waitPreview(null);
    await sendPlan(preview);
    await page.clock.fastForward(300);
    await waitPreview(null);
    assert.deepEqual((await state()).alignment, afterReload);

    // The normal iframe cannot receive a plan even from this parent.
    await page.locator("#twin").evaluate((el, url) => { el.src = url; }, childOrigin + "/");
    await page.waitForFunction(() => window.readies === 3);
    await sendPlan(planPreview(await page.evaluate(() => Date.now() + 60_000)));
    await page.clock.fastForward(300);
    await waitPreview(null);
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    assert.deepEqual(api, []);
    console.log(`${name}: 5 fixture waypoints, distinct telemetry, stale/fresh 0/1, reload and expiry checked, ${previewPixels} preview-colored canvas pixels, zero API requests`);
    await context.close();
  }
} finally {
  await browser.close();
}
