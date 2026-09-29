/**
 * 对**真实 Runtime + 真实前端**做一次端到端健康检查，并截图存档。
 *
 * 与其他 e2e 文件不同，这里**不拦截任何请求** —— 因此它检验的是真实系统，
 * 而不是夹具。用途：重启之后确认"到底恢复好了没有"。
 *
 * 检查项：
 *   1. 主控制台布局正确（侧边栏是左侧竖栏、内容区在右侧）
 *   2. 三维视图 iframe 里能看到载具（说明快照推送链路通）
 *   3. 控制台没有 JS 报错
 *   4. 两侧选择同步
 *
 * 出图：test-results/live-console.png、test-results/live-twin.png
 */
import { test, expect } from "@playwright/test";

const CONSOLE_URL = "http://127.0.0.1:5178/index.html";
const SIM_FRAME_URL = "http://127.0.0.1:5179/";

test.describe("真实系统健康检查", () => {
  test("主控制台布局 + 三维视图载具 + 无报错", async ({ page }) => {
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
    page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message.slice(0, 200)}`));

    await page.goto(CONSOLE_URL);
    await page.waitForTimeout(3000);

    // --- 1) 布局几何 ---
    const layout = await page.evaluate(() => {
      const rect = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const { x, y, width, height } = el.getBoundingClientRect();
        return { x: Math.round(x), y: Math.round(y), w: Math.round(width), h: Math.round(height) };
      };
      return { sidebar: rect(".sidebar"), content: rect(".content"), topbar: rect(".topbar") };
    });
    console.log("[layout]", JSON.stringify(layout));

    expect(layout.sidebar, "侧边栏应存在").toBeTruthy();
    expect(layout.sidebar.w, "侧边栏应是窄竖栏（约 252px），横过来就说明网格错位了")
      .toBeLessThan(400);
    expect(layout.sidebar.h, "侧边栏应是高竖栏").toBeGreaterThan(300);
    expect(layout.content.w, "内容区应占据剩余宽度").toBeGreaterThan(800);
    expect(layout.content.x, "内容区应在侧边栏右侧").toBeGreaterThan(layout.sidebar.w - 10);

    await page.screenshot({ path: "test-results/live-console.png" });

    // 先查清 .topbar 为什么有两个 —— 可能是外壳结构重复，那是真 bug
    const duplicates = await page.evaluate(() => {
      const describe = (el) => ({
        tag: el.tagName,
        id: el.id || "(无)",
        parent: el.parentElement ? `${el.parentElement.tagName}.${el.parentElement.className || "(无类名)"}` : "(无)",
      });
      return {
        topbar: [...document.querySelectorAll(".topbar")].map(describe),
        sidebar: [...document.querySelectorAll(".sidebar")].map(describe),
        content: [...document.querySelectorAll(".content")].map(describe),
        shellCount: document.querySelectorAll(".shell").length,
        appChildren: [...(document.getElementById("app")?.children ?? [])].map(describe),
      };
    });
    console.log("[重复元素检查]", JSON.stringify(duplicates));

    // 总览页的"数据活着"判据：顶部"在线节点 3 / 3"。
    // ⚠️ 不要在这里断言 tr.selectable-row —— 节点列表表格只在**三维集群态势页**，
    // 在总览页断言它会得到 0 行。实测踩到：把测试写错当成了产品故障。
    await expect.poll(
      async () => (await page.locator("#slot-topbar").innerText()).includes("在线节点"),
      { timeout: 20000, intervals: [300, 600] },
    ).toBe(true);

    // --- 3) 三维视图（节点列表表格在这一页）---
    await page.evaluate(() => setPage("twin"));
    await page.waitForSelector("#simulation-frame", { state: "attached", timeout: 30000 });

    await expect.poll(
      async () => page.locator("tr.selectable-row").count(),
      { timeout: 25000, intervals: [300, 600] },
    ).toBeGreaterThan(0);

    await page.waitForTimeout(6000);

    const contractError = await page.evaluate(() => state.simulationContractError);
    console.log("[contractError]", contractError ?? "(无)");
    expect(contractError, `快照没推给三维视图：${contractError}`).toBeFalsy();

    const frame = page.frameLocator("#simulation-frame");
    await expect.poll(
      async () => frame.locator("#vehicle-select option").count(),
      { timeout: 25000, intervals: [400, 800] },
    ).toBeGreaterThan(0);

    const childSummary = await frame.locator("#vehicle-summary").innerText().catch(() => "(无)");
    console.log("[三维视图] 载具摘要:", childSummary);

    await page.screenshot({ path: "test-results/live-twin.png" });

    // --- 4) 选择同步 ---
    const ids = await frame.locator("#vehicle-select option").evaluateAll(
      (opts) => opts.map((o) => o.value).filter(Boolean),
    );
    console.log("[可选载具]", ids.join(", "));
    expect(ids.length, "应有可选载具").toBeGreaterThan(1);

    await page.evaluate((id) => selectVehicle(id), ids[1]);
    await expect(frame.locator("#vehicle-select")).toHaveValue(ids[1], { timeout: 10000 });

    console.log("[JS 报错]", errors.length ? errors.join(" | ") : "(无)");
    expect(errors, "控制台不应有 JS 报错").toEqual([]);
  });
});
