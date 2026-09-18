import { test, expect } from "@playwright/test";
import { PNG } from "pngjs";

function snapshot(vehicles = []) {
  return {
    version: "1.0",
    timestamp_ms: Date.now(),
    full_state: true,
    frame: { type: "ENU" },
    source: { id: "browser-test", kind: "simulation", label: "TEST FEED" },
    vehicles,
  };
}

async function verifyCanvas(page, testInfo, name) {
  await expect(page.locator(".cesium-widget canvas")).toBeVisible();
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  const shot = await page.screenshot({
    path: testInfo.outputPath(`${name}.png`),
  });
  const png = PNG.sync.read(shot);
  const colors = new Set();
  // Sample actual rendered pixels away from panels and toolbars.
  for (let y = Math.floor(png.height * 0.33); y < png.height * 0.78; y += 5) {
    for (let x = Math.floor(png.width * 0.34); x < png.width * 0.75; x += 5) {
      const k = (y * png.width + x) * 4;
      colors.add(
        `${png.data[k] >> 3},${png.data[k + 1] >> 3},${png.data[k + 2] >> 3}`,
      );
    }
  }
  expect(colors.size).toBeGreaterThan(30);
  await testInfo.attach(name, { body: shot, contentType: "image/png" });
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/vehicle-snapshot", (route) =>
    route.fulfill({ json: snapshot() }),
  );
});

test("city views, layers and explicit demo rendering", async ({
  page,
}, testInfo) => {
  const errors = [];
  const externalRequests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (
      /^https?:/.test(request.url()) &&
      new URL(request.url()).hostname !== "127.0.0.1"
    )
      externalRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator("#scene-status")).toContainText("READY");
  await expect(page.locator("#vehicle-summary")).toContainText("0 个节点");
  await expect(page.locator("#city-statistics")).toContainText("栋建筑");
  await page.waitForFunction(() => performance.now() > 5000);
  await verifyCanvas(page, testInfo, "city-desktop");
  for (const id of ["downtown", "river", "hills", "campus"]) {
    await page.locator(`[data-view="${id}"]`).click();
    await expect(page.locator(`[data-view="${id}"]`)).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await verifyCanvas(page, testInfo, id);
  }
  await page.locator(".map-layers summary").click();
  await page.locator('[data-city-layer="buildings"]').uncheck();
  await expect(page.locator('[data-city-layer="buildings"]')).not.toBeChecked();
  await page.locator('[data-city-layer="buildings"]').check();
  await page.locator("#shadows-toggle").check();
  await verifyCanvas(page, testInfo, "campus-shadows");
  await page.locator("#shadows-toggle").uncheck();
  await page.getByRole("button", { name: "DEMO", exact: true }).click();
  await expect(page.locator("#vehicle-summary")).toContainText("5 个节点");
  await page.locator("#vehicle-select").selectOption("FW-01");
  await expect(page.locator("#selected-vehicle-type")).toHaveText("固定翼");
  const altitude = await page.locator("#telemetry-alt").textContent();
  await expect
    .poll(() => page.locator("#telemetry-alt").textContent())
    .not.toBe(altitude);
  await page.getByRole("button", { name: "LIVE", exact: true }).click();
  await expect(page.locator("#vehicle-summary")).toContainText("0 个节点");
  await page.locator("#scene-select").selectOption("campus");
  await expect(page.locator("#scene-status")).toContainText("任务园区");
  await page.locator("#scene-select").selectOption("city");
  await expect(page.locator("#map-location")).toContainText("城市总览");
  expect(errors).toEqual([]);
  expect(externalRequests).toEqual([]);
});

test("LIVE bridge preserves frozen telemetry and resumes fresh positions in the city", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#vehicle-summary")).toContainText("0 个节点");
  const started = Date.now();
  async function send(step, altitude, stale = false) {
    const payload = snapshot([
      {
        id: "LIVE-01",
        display_name: "LIVE-01",
        vehicle_type: "multirotor",
        connected: !stale,
        pose: {
          frame: "ENU",
          position_m: { x: 20, y: 40, z: altitude },
          attitude_deg: { roll: 0, pitch: 0, yaw: 0 },
        },
        telemetry: { mode: "AUTO", stale, age_ms: stale ? 6000 : 0 },
      },
    ]);
    payload.timestamp_ms = started + step;
    return page.evaluate(
      (data) => window.SwarmSimulationBridge.applyVehicleSnapshot(data),
      payload,
    );
  }
  expect((await send(1, 50)).accepted).toBe(true);
  await expect(page.locator("#telemetry-alt")).toHaveText("50.0 m");
  expect((await send(2, 200, true)).accepted).toBe(true);
  await expect(page.locator("#telemetry-alt")).toHaveText("50.0 m");
  expect((await send(3, 100)).accepted).toBe(true);
  await expect(page.locator("#telemetry-alt")).toHaveText("100.0 m");
  const state = await page.evaluate(() =>
    window.SwarmSimulationBridge.getState(),
  );
  expect(state).toMatchObject({
    sceneId: "city",
    dataMode: "live",
    transport: "bridge",
    vehicleCount: 1,
  });
  const pair = snapshot([
    {
      id: "LIVE-01",
      vehicle_type: "multirotor",
      connected: true,
      pose: { frame: "ENU", position_m: { x: 20, y: 40, z: 100 } },
    },
    {
      id: "LIVE-FW",
      vehicle_type: "fixed_wing",
      connected: true,
      color: "#ff00ff",
      pose: { frame: "ENU", position_m: { x: 100, y: 0, z: 70 } },
    },
  ]);
  pair.timestamp_ms = started + 4;
  await page.evaluate(
    (data) => window.SwarmSimulationBridge.applyVehicleSnapshot(data),
    pair,
  );
  await page.locator('[data-view="campus"]').click();
  await verifyCanvas(page, testInfo, "live-vehicles");
  const png = PNG.sync.read(
    await page.locator(".cesium-widget canvas").screenshot(),
  );
  const pixels = [];
  for (let y = 0; y < png.height; y++)
    for (let x = 0; x < png.width; x++) {
      const k = (y * png.width + x) * 4;
      if (png.data[k] > 200 && png.data[k + 1] < 70 && png.data[k + 2] > 200)
        pixels.push([x, y]);
    }
  expect(pixels.length).toBeGreaterThan(5);
  const bounds = await page.locator(".cesium-widget canvas").boundingBox();
  const center = pixels.reduce(
    (sum, p) => [sum[0] + p[0], sum[1] + p[1]],
    [0, 0],
  );
  await page.mouse.click(
    bounds.x + center[0] / pixels.length,
    bounds.y + center[1] / pixels.length,
  );
  await expect(page.locator("#selected-vehicle-id")).toHaveText("LIVE-FW");
  await expect(page.locator("#selected-vehicle-type")).toHaveText("固定翼");
  await expect(page.locator("#telemetry-alt")).toHaveText("70.0 m");
});

test("mobile map stays usable with separate scene and telemetry panels", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?mode=demo");
  await expect(page.locator("#scene-status")).toContainText("READY");
  await page.waitForFunction(() => performance.now() > 5000);
  await verifyCanvas(page, testInfo, "city-mobile");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.locator('button[data-panel="scene"]').click();
  await page.locator('[data-view="river"]').click();
  await page.locator("#vehicle-select").selectOption("UGV-01");
  await page.locator('button[data-panel="telemetry"]').click();
  await expect(page.locator(".layer-panel")).not.toBeVisible();
  await expect(page.locator("#selected-vehicle-id")).toHaveText("UGV-01");
  await expect(page.locator("#selected-vehicle-type")).toHaveText("无人车");
  await page.screenshot({ path: testInfo.outputPath("mobile-telemetry.png") });
  await page.locator('button[data-panel="telemetry"]').click();
  await page.getByRole("button", { name: "放大地图", exact: true }).click();
  await verifyCanvas(page, testInfo, "mobile-river");
});
