/**
 * 选择同步的端到端验证（真实 5178 主控制台 + 真实 5179 三维视图，跨域）。
 *
 * 之前我判定这条"自动化测不了"，理由是跨域下父页面读不了子页面的 document。
 * 那只说明**自建探针**不行 —— Playwright 的 frameLocator 与 page.frame() 走
 * 浏览器调试协议，可以真实读取子框架内部的 DOM。本文件证明这条能自动测。
 *
 * 夹具来源很重要：这里用 `tests/fixtures/real-runtime-snapshot.json`
 * —— 从真实 Runtime 抓下来的一份快照（见 _ops/capture-runtime-fixture.py）。
 * **不要手写夹具**：共享消费契约要求的字段（source / frame /
 * coordinate_contract / spatial.*）比看上去多，手写的必然缺项，而缺项的表现是
 * postVehicleSnapshot() 静默不发送、三维视图显示"0 个节点"、选择同步无从发生
 * —— 看起来像同步坏了，实际是夹具不完整。实测在这上面浪费了两轮。
 */
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONSOLE_URL = "http://127.0.0.1:5178/index.html";
const SIM_FRAME_URL = "http://127.0.0.1:5179/";

/** 读取真实快照，并把时间相关字段改成"刚刚采样"，避免被判过期。 */
function realSnapshot() {
  const raw = JSON.parse(
    readFileSync(resolve(HERE, "../tests/fixtures/real-runtime-snapshot.json"), "utf8"),
  );
  const now = new Date().toISOString();
  raw.timestamp = now;
  for (const vehicle of raw.vehicles ?? []) {
    vehicle.connected = true;
    vehicle.telemetry = { ...(vehicle.telemetry ?? {}), stale: false, age_ms: 5 };
    if (vehicle.spatial) {
      vehicle.spatial = {
        ...vehicle.spatial,
        stale: false,
        calibration_status: "calibrated",
        public_position_usable: true,
        sample_age_ms: 5,
        calibration_age_ms: 5,
        calibration_valid_for_ms: 60000,
        sample_timestamp: now,
        calibration_source_timestamp: now,
        source_timestamp: now,
      };
    }
  }
  return raw;
}

/** 从同一份快照派生注册表与遥测，保证三者一致。 */
function derivedEndpoints(snapshot) {
  const registry = {
    version: "1.0",
    source: snapshot.source,
    scene_id: snapshot.scene_id,
    vehicles: (snapshot.vehicles ?? []).map((v) => ({
      node_id: v.id,
      display_name: v.display_name ?? v.id,
      connected: true,
      stale: false,
      enabled: true,
      system_id: 1,
      component_id: 1,
      backend: "px4_sitl",
      scene_id: snapshot.scene_id,
    })),
  };
  const telemetry = {
    version: "1.0",
    status: "ok",
    nodes: (snapshot.vehicles ?? []).map((v) => ({
      node_id: v.id,
      connected: true,
      stale: false,
      armed: Boolean(v.telemetry?.armed),
      flight_mode: v.telemetry?.mode ?? "LOITER",
      local_position: {
        x_m: v.pose?.position_m?.x ?? 0,
        y_m: v.pose?.position_m?.y ?? 0,
        z_down_m: v.pose?.position_m?.z ?? 0,
      },
      battery: { remaining_percent: v.telemetry?.battery_percent ?? 100 },
    })),
  };
  return { registry, telemetry };
}

/**
 * 在子框架内部把载具下拉框切到指定值，并派发真实的 change 事件。
 *
 * 三个踩过的坑，记在这里免得重犯：
 *  1. 不能用 selectOption()：它要求元素"可交互"（可见 + 可接收指针事件），
 *     而该下拉框位于遥测面板里，默认视图下不满足，会一直等到超时（实测 90 秒）。
 *  2. 不能用 page.evaluate + frame.contentDocument：父（5178）与子（5179）
 *     跨域，contentDocument 是 null。
 *  3. 不能用 frameLocator().evaluate()：frameLocator 返回 Locator，没有
 *     evaluate 方法（实测 TypeError）。要用 page.frame() 拿真正的 Frame。
 *
 * 仍然走真实代码路径：派发的是真 change 事件，会进入 main.js 的监听器，
 * 后续 postMessage 上报与父页面处理都是真实现。只是跳过了动作性检查。
 */
async function selectInFrame(page, frameUrl, vehicleId) {
  const frame = page.frame({ url: frameUrl });
  if (!frame) throw new Error(`找不到子框架: ${frameUrl}`);
  await frame.evaluate((id) => {
    const select = document.getElementById("vehicle-select");
    select.value = id;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, vehicleId);
}

test.describe("主控制台 <-> 三维视图 选择同步", () => {
  let snapshot;

  test.beforeEach(async ({ page }) => {
    snapshot = realSnapshot();
    const { registry, telemetry } = derivedEndpoints(snapshot);

    await page.route("http://127.0.0.1:8765/api/**", async (route) => {
      const url = route.request().url();
      const json = (body) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (url.includes("/vehicle-snapshot")) return json(snapshot);
      if (url.includes("/vehicles")) return json(registry);
      if (url.includes("/telemetry/latest")) return json(telemetry);
      if (url.includes("/health")) return json({ status: "ok" });
      if (url.includes("/simulation/status")) {
        return json({
          status: "ready",
          scene_id: snapshot.scene_id,
          map_version: snapshot.vehicles?.[0]?.spatial?.map_version ?? "",
        });
      }
      // /events、/actions/*、/policy/decisions 在真实 Runtime 返回数组；
      // 给 {} 会被判为契约不符并把 apiStatus 置为 offline（实测踩到）。
      if (/\/api\/(events|actions\/recent|actions\/lifecycle|policy\/decisions)/.test(url)) {
        return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      }
      return json({});
    });
  });

  /** 打开 twin 页，等到两侧都出现载具。 */
  async function openTwinWithVehicles(page) {
    await page.goto(CONSOLE_URL);
    await page.evaluate(() => setPage("twin"));
    await page.waitForSelector("#simulation-frame", { state: "attached", timeout: 30000 });

    await expect.poll(
      async () => page.locator("tr.selectable-row").count(),
      { timeout: 30000, intervals: [250, 500] },
    ).toBeGreaterThan(0);

    // 若快照没被推给子框架，这个字段会给出原因 —— 直接断言它为空，
    // 免得后续的"0 个节点"看起来像同步 bug
    const contractError = await page.evaluate(() => state.simulationContractError);
    expect(contractError, `父页面没能把快照推给三维视图：${contractError}`).toBeFalsy();

    const frame = page.frameLocator("#simulation-frame");
    await expect.poll(
      async () => frame.locator("#vehicle-select option").count(),
      { timeout: 30000, intervals: [250, 500] },
    ).toBeGreaterThan(0);

    return frame;
  }

  test("框架一：主控制台改选 → 三维视图跟随", async ({ page }) => {
    const frame = await openTwinWithVehicles(page);
    const ids = snapshot.vehicles.map((v) => v.id);

    await page.evaluate((id) => selectVehicle(id), ids[1]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[1], { timeout: 10000 });

    // 再换一台，确认不是"只同步了第一次"
    await page.evaluate((id) => selectVehicle(id), ids[2]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[2], { timeout: 10000 });
  });

  test("框架二：三维视图改选 → 主控制台跟随", async ({ page }) => {
    await openTwinWithVehicles(page);
    const ids = snapshot.vehicles.map((v) => v.id);

    await selectInFrame(page, SIM_FRAME_URL, ids[1]);
    await expect.poll(
      async () => page.evaluate(() => state.selectedUav),
      { timeout: 10000, intervals: [200, 400] },
    ).toBe(ids[1]);
  });

  test("不成环：两侧来回选择后状态稳定且一致", async ({ page }) => {
    const frame = await openTwinWithVehicles(page);
    const ids = snapshot.vehicles.map((v) => v.id);

    // 父 → 子
    await page.evaluate((id) => selectVehicle(id), ids[2]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[2], { timeout: 10000 });

    // 子 → 父
    await selectInFrame(page, SIM_FRAME_URL, ids[0]);
    await expect.poll(
      async () => page.evaluate(() => state.selectedUav),
      { timeout: 10000, intervals: [200, 400] },
    ).toBe(ids[0]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[0], { timeout: 10000 });

    // 静置一段时间：成环会让两侧反复互相覆盖，表现为值来回跳动
    await page.waitForTimeout(1500);
    expect(await page.evaluate(() => state.selectedUav)).toBe(ids[0]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[0]);
  });
});
