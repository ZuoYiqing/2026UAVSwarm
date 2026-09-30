/**
 * 验证默认场景修复：三维视图打开后应当能显示载具。
 *
 * 背景：`#scene-select` 原先默认选中 `city`（青岚市，scene_id=qinglan_city_v1），
 * 而 Runtime 提供的数据始终是 `simple_recon_v0_1`，于是每次对齐都因 scene_id
 * 不匹配而失败、载具被丢弃，表现为"界面上看不到飞机"。
 *
 * 为什么用夹具而不是真实 Runtime：这个检查要能在仿真没起时也跑得动
 * （修复的验证不该依赖整套仿真在线）。夹具取自真实 Runtime
 * （tests/fixtures/real-runtime-snapshot.json），只是把时间字段改成"刚刚采样"。
 * 它带着真实的 scene_id，因此**足以验证默认场景是否与数据匹配**。
 *
 * 同时检查一个关键点：对齐失败时必须有**可见提示**，而不是静默丢弃 ——
 * 静默丢弃正是这个 bug 一直难以发现的原因。
 */
import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

for (const stream of [process.stdout, process.stderr]) {
  try { stream.reconfigure?.({ encoding: "utf-8" }); } catch { /* 忽略 */ }
}

const HERE = dirname(fileURLToPath(import.meta.url));
const CONSOLE_URL = "http://127.0.0.1:5178/index.html";
const EXPECTED_SCENE = "simple_recon_v0_1";

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

test.describe("默认场景与数据匹配", () => {
  let snapshot;

  test.beforeEach(async ({ page }) => {
    snapshot = realSnapshot();
    const registry = {
      version: "1.0", source: snapshot.source, scene_id: snapshot.scene_id,
      vehicles: (snapshot.vehicles ?? []).map((v) => ({
        node_id: v.id, display_name: v.display_name ?? v.id, connected: true,
        stale: false, enabled: true, system_id: 1, component_id: 1,
        backend: "px4_sitl", scene_id: snapshot.scene_id,
      })),
    };
    const telemetry = {
      version: "1.0", status: "ok",
      nodes: (snapshot.vehicles ?? []).map((v) => ({
        node_id: v.id, connected: true, stale: false,
        armed: Boolean(v.telemetry?.armed), flight_mode: v.telemetry?.mode ?? "LOITER",
        local_position: {
          x_m: v.pose?.position_m?.x ?? 0, y_m: v.pose?.position_m?.y ?? 0,
          z_down_m: v.pose?.position_m?.z ?? 0,
        },
        battery: { remaining_percent: v.telemetry?.battery_percent ?? 100 },
      })),
    };

    await page.route("http://127.0.0.1:8765/api/**", async (route) => {
      const url = route.request().url();
      const json = (body) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (url.includes("/vehicle-snapshot")) return json(snapshot);
      if (url.includes("/vehicles")) return json(registry);
      if (url.includes("/telemetry/latest")) return json(telemetry);
      if (url.includes("/health")) return json({ status: "ok" });
      if (url.includes("/simulation/status")) {
        return json({ status: "ready", scene_id: snapshot.scene_id,
                      map_version: snapshot.vehicles?.[0]?.spatial?.map_version ?? "" });
      }
      if (/\/api\/(events|actions\/recent|actions\/lifecycle|policy\/decisions)/.test(url)) {
        return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      }
      return json({});
    });
  });

  test("三维视图默认场景与 Runtime 数据匹配，载具可见且对齐成功", async ({ page }) => {
    await page.goto(CONSOLE_URL);
    await page.evaluate(() => setPage("twin"));
    await page.waitForSelector("#simulation-frame", { state: "attached", timeout: 30000 });

    const frame = page.frameLocator("#simulation-frame");
    await expect.poll(
      async () => frame.locator("#vehicle-select option").count(),
      { timeout: 30000, intervals: [300, 600] },
    ).toBeGreaterThan(0);

    // 1) 默认选中的场景必须是 recon（而不是 city）
    const sceneSelect = frame.locator("#scene-select");
    await expect.poll(async () => sceneSelect.inputValue(), { timeout: 15000 })
      .toBe("recon");

    // 2) 子框架内部的场景身份必须等于数据来源的场景身份
    const state = await page.frame({ url: "http://127.0.0.1:5179/" }).evaluate(
      () => window.SwarmSimulationBridge.getState(),
    );
    console.log("[子框架状态]", JSON.stringify({
      sceneId: state.sceneId, connection: state.connection,
      vehicleCount: state.vehicleCount,
      alignment: (state.alignment ?? []).map((a) => `${a.id}:aligned=${a.aligned}:${a.reason}`),
    }, null, 2));

    // 2b) 对齐列表里不得有任何 aligned=false 的项。
    //
    // 这是最贴近根因的断言：默认场景与数据不匹配时，alignmentReason() 会返回
    // "scene_id 不匹配"，于是载具位置被丢弃、connection 变成 stale。
    // 直接查这个列表，比间接看摘要文字更准。
    const failedAlignment = (state.alignment ?? []).filter((a) => a.aligned === false);
    expect(
      failedAlignment,
      `存在对齐失败的载具：${JSON.stringify(failedAlignment)}`,
    ).toEqual([]);
    expect(state.connection, "对齐成功后连接状态不应为 stale").not.toBe("stale");

    // 3) 载具摘要不应再出现 "N STALE"
    const summary = await frame.locator("#vehicle-summary").innerText();
    console.log("[载具摘要]", summary);
    expect(summary, "载具不应被判为 STALE").not.toMatch(/STALE/);

    // 3b) 节点列表有行时，空状态提示必须隐藏。
    //
    // 空状态由首屏渲染决定是否可见，而首屏通常还没数据；若局部更新不同步它，
    // 就会出现"表格已有 3 行、下面还写着'Runtime 尚未提供已注册载具'"。
    // 实测踩到过，这里守住。
    const tableState = await page.evaluate(() => ({
      rows: document.querySelectorAll("tr.selectable-row").length,
      emptyVisible: (() => {
        const el = document.getElementById("vehicle-table-empty");
        if (!el) return null;
        return !el.hidden;
      })(),
    }));
    console.log("[节点列表]", JSON.stringify(tableState));
    expect(tableState.rows, "应有节点行").toBeGreaterThan(0);
    expect(
      tableState.emptyVisible,
      "有节点行时空状态提示不该显示（表格已填好、下面还写着'尚未提供载具'）",
    ).toBe(false);

    // 4) 对齐状态必须成功（关键断言：这是修复的核心）
    const aligned = await page.evaluate(() => {
      const el = document.querySelector("#scene-alignment");
      return el ? el.textContent : "(无该元素)";
    }).catch(() => "(读取失败)");
    console.log("[主控制台对齐状态]", aligned);

    await page.screenshot({ path: "test-results/default-scene-fix-twin.png" });

    // 子框架里也应显示对齐成功而非"不匹配"
    const childAlignment = await frame.locator("#scene-alignment").innerText().catch(() => "");
    console.log("[子框架对齐状态]", childAlignment);
    expect(childAlignment, `子框架对齐应成功，实际：${childAlignment}`)
      .not.toContain("不匹配");
  });
});
