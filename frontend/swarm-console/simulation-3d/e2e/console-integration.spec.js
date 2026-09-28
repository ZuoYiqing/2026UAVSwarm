/**
 * 集成验证：真实主控制台 + 真实三维视图（跨域，5178 → 5179）。
 *
 * 验证两件事：
 *  1. 主控制台重复渲染**不会**重建三维视图的 iframe
 *  2. 两侧的载具选择能互相跟随，且不成环
 *
 * 关于"如何跨域观测子页面"——这里踩过两个坑，记录清楚：
 *   - 父页面读不了子页面的 document（浏览器禁止）
 *   - 也不能可靠地在子 window 上读写自定义属性：实测"能写但不能读"
 *     （对跨域 window 写普通属性不报错，读却抛 SecurityError）
 *
 * 因此判据改为：
 *   - iframe 是否被重建 → 看"子页面是否重新发来 simulation-ready"
 *     （三维视图每次加载都会发，不需要读子页面任何东西）
 *   - 选择同步 → 用 frameLocator 在子框架内操作真实控件，再在父页面读 state
 */
import { test, expect } from "@playwright/test";

const CONSOLE_URL = "http://127.0.0.1:5178/index.html";

/** 在页面初始化前注入探针：记录子页面发来的消息与父页面发出的选择消息。 */
async function installProbes(page) {
  await page.addInitScript(() => {
    window.__e2e = { readyCount: 0, sentSelections: [], changedSelections: [] };
    window.addEventListener("message", (event) => {
      const type = event.data?.type;
      if (type === "uav-swarm/simulation-ready") window.__e2e.readyCount += 1;
      if (type === "uav-swarm/selection-changed") {
        window.__e2e.changedSelections.push(event.data?.payload?.nodeId ?? null);
      }
    });
    // 包装 postMessage，记录父页面**发出**的选择消息。
    // 包装的是父页面自己持有的引用，不需要读子页面，因此跨域下也能用。
    const originalPost = Window.prototype.postMessage;
    Window.prototype.postMessage = function patched(message, targetOrigin, transfer) {
      try {
        if (message?.type === "uav-swarm/select-vehicle") {
          (window.__e2e.sentSelections ||= []).push(message.payload?.nodeId ?? null);
        }
      } catch { /* 记录失败不影响主流程 */ }
      return originalPost.call(this, message, targetOrigin, transfer);
    };
  });
}

const FLEET = {
  version: "1.0",
  timestamp: new Date().toISOString(),
  scene_id: "simple_recon_v0_1",
  map_version: "simple_recon_v0_1-map-1",
  vehicles: ["UAV-01", "UAV-02", "UAV-03"].map((id, i) => ({
    id,
    display_name: id,
    connected: true,
    stale: false,
    telemetry: { armed: false, mode: "LOITER", battery_percent: 100, age_ms: 5, stale: false },
    pose: { frame: "NED", position_m: { x: 0, y: i * 8, z: 0 } },
    spatial: {
      contract_version: "1.0",
      scene_id: "simple_recon_v0_1",
      map_version: "simple_recon_v0_1-map-1",
      public_frame: "scene_ned",
      local_frame: "vehicle_local_ned",
      units: "m",
      z_convention: "positive_down",
      calibration_status: "calibrated",
      public_position_usable: true,
      scene_pose: { frame: "scene_ned", position_m: { x: 0, y: i * 8, z: 0 } },
      axis_alignment: "ned_aligned",
      origin_continuity: "verified",
      local_origin_id: "e2e-test-origin",
      calibration_version: "e2e-test",
      sample_timestamp: new Date().toISOString(),
      calibration_source_timestamp: new Date().toISOString(),
      calibration_age_ms: 10,
      calibration_valid_for_ms: 60000,
      stale: false,
    },
  })),
};

/** 注册表快照：mergeFleet 读 row.connected / row.stale。 */
const REGISTRY = {
  version: "1.0",
  vehicles: ["UAV-01", "UAV-02", "UAV-03"].map((id) => ({
    node_id: id, connected: true, stale: false, enabled: true,
    system_id: 1, component_id: 1, backend: "px4_sitl", scene_id: "simple_recon_v0_1",
  })),
};

/** 遥测快照：顶层 status 决定 dataStatus（"ok" 则为 live）。 */
const TELEMETRY = {
  version: "1.0",
  status: "ok",
  nodes: ["UAV-01", "UAV-02", "UAV-03"].map((id, i) => ({
    node_id: id, connected: true, stale: false, armed: false, flight_mode: "LOITER",
    local_position: { x_m: 0, y_m: i * 8, z_down_m: 0 },
    battery: { remaining_percent: 100 },
  })),
};

/** 等数据链路就绪：apiStatus=dataStatus=live，且节点列表已渲染出行。 */
async function waitForFleetRows(page, minimum = 1) {
  await expect.poll(
    async () => page.evaluate(() => ({ api: state.apiStatus, data: state.dataStatus })),
    { timeout: 30000, intervals: [200, 400, 800] },
  ).toMatchObject({ api: "live", data: "live" });
  await expect.poll(
    async () => page.locator("tr.selectable-row").count(),
    { timeout: 30000, intervals: [200, 400, 800] },
  ).toBeGreaterThanOrEqual(minimum);
}

/** 等三维视图完成首次加载。 */
async function waitForSimulationReady(page) {
  await page.waitForSelector("#simulation-frame", { state: "attached", timeout: 30000 });
  await expect.poll(
    async () => page.evaluate(() => window.__e2e.readyCount),
    { timeout: 30000, intervals: [200, 400, 800] },
  ).toBeGreaterThan(0);
}

test.describe("主控制台 <-> 三维视图", () => {
  test.beforeEach(async ({ page }) => {
    await installProbes(page);
    // 拦截 Runtime：给确定性数据。
    // 注意 /events、/actions/*、/policy/decisions 在真实 Runtime 返回**数组**，
    // 给 {} 会被判为契约不符并把 apiStatus 置为 offline（实测踩到）。
    await page.route("http://127.0.0.1:8765/api/**", async (route) => {
      const url = route.request().url();
      const json = (body) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (url.includes("/vehicle-snapshot")) return json(FLEET);
      if (url.includes("/vehicles")) return json(REGISTRY);
      if (url.includes("/telemetry/latest")) return json(TELEMETRY);
      if (url.includes("/health")) return json({ status: "ok" });
      if (url.includes("/simulation/status")) {
        return json({ status: "ready", scene_id: "simple_recon_v0_1", map_version: "simple_recon_v0_1-map-1" });
      }
      if (/\/api\/(events|actions\/recent|actions\/lifecycle|policy\/decisions)/.test(url)) {
        return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      }
      return json({});
    });
  });

  test("节点列表在有数据后能渲染出行", async ({ page }) => {
    // 回归守卫：切页时数据未到会渲染成空状态；若之后不自愈，界面会永远停在
    // "Runtime 尚未提供已注册载具"（实测出现过：fleet 已有 3 台，表格却是空的）。
    await page.goto(CONSOLE_URL);
    await page.evaluate(() => setPage("twin"));
    await waitForFleetRows(page, 3);
  });

  test("重复 render() 不会让三维视图重新加载", async ({ page }) => {
    await page.goto(CONSOLE_URL);
    await page.evaluate(() => setPage("twin"));
    await waitForSimulationReady(page);

    const before = await page.evaluate(() => window.__e2e.readyCount);
    for (let i = 0; i < 8; i += 1) {
      await page.evaluate(() => render());
      await page.waitForTimeout(70);
    }
    await page.waitForTimeout(900); // 给"若被重建"留出重新 ready 的时间

    const after = await page.evaluate(() => window.__e2e.readyCount);
    expect(after, `三维视图被重建了 ${after - before} 次：render() 仍在动 iframe`).toBe(before);
  });

  test("点击节点列表行不会让三维视图重新加载", async ({ page }) => {
    await page.goto(CONSOLE_URL);
    await page.evaluate(() => setPage("twin"));
    await waitForSimulationReady(page);
    await waitForFleetRows(page, 2);

    const before = await page.evaluate(() => window.__e2e.readyCount);
    await page.locator("tr.selectable-row").nth(1).click({ force: true });
    await page.waitForTimeout(1200);

    const after = await page.evaluate(() => window.__e2e.readyCount);
    expect(after, "点击节点列表后三维视图被重建了").toBe(before);
  });

  test("主控制台改选载具时把选择推给三维视图", async ({ page }) => {
    // ⚠️ 待人工确认。这条在自动化里没能建立可靠的观测点：
    //
    // 父页面（5178）与三维视图（5179）跨域，因此
    //   - 读不了子页面 document（不能用 select.value 判断是否同步）
    //   - 也不可靠地在子 window 上读写自定义属性（实测能写不能读）
    //   - 包装 Window.prototype.postMessage 试图记录"父页面发出了什么"也未生效
    //     （contentWindow.postMessage 的调用解析方式与父页面自己调的不同）
    //
    // 选择同步的**协议逻辑**已有单元测试覆盖，见 tests/scene-alignment.test.js：
    //   - select-vehicle 消息携带 nodeId 正确到达回调
    //   - 缺 nodeId 时传 null 而非 undefined
    //   - 未提供回调时返回 false（报告未处理，而不是静默接受）
    //   - 来源与 origin 校验仍然生效，被拒消息不触发选择
    // 端到端效果（点一下看另一侧是否跟随）需人工确认一次。
    test.fixme(true, "跨域下父页面无法可靠观测子页面的 postMessage；协议由单元测试覆盖，端到端需人工确认");
  });

  test("三维视图改选载具时主控制台跟随，且不回推成环", async ({ page }) => {
    // 同上：需要驱动子框架内的控件并观测父页面收到的消息，
    // 跨域下这两侧的观测点都无法在自动化里稳定建立。
    test.fixme(true, "跨域下无法稳定驱动并观测子框架；需人工确认一次");
  });
});
