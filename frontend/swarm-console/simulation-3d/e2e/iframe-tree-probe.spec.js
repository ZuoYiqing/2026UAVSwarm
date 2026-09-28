/**
 * 验证：如果**不重建 iframe 所在的子树**（只重建兄弟子树），iframe 是否保持不重载。
 *
 * 前面两个探针证明：
 *   - 移动 iframe 本身（任何方式）→ 重载
 *   - 移动 iframe 的祖先容器 → 同样重载
 *
 * 因此"把 iframe 拿出来再放回去"这条路整体是死的。剩下的方向是：
 * **让整树替换根本不碰 iframe 所在的子树** —— 即分块更新，而不是 app.innerHTML 一把梭。
 *
 * 本探针验证该思路，并给出两种具体做法的对照：
 *   C1: 只更新 #app 之外的兄弟容器（sidebar/topbar 各自独立的容器）
 *   C2: 整树里 iframe 的父容器用独立容器承载，只更新其它容器
 */
import { test, expect } from "@playwright/test";

const PARENT = `<!doctype html>
<html><body>
  <div id="app"></div>
  <script>
    // 建立分块结构：topbar / sidebar / content 各自独立容器；
    // content 内部再分 simulation-frame-wrap 与其它内容。
    function mount() {
      document.getElementById("app").innerHTML =
        '<div class="shell">'
        + '<div id="slot-topbar"></div>'
        + '<div id="slot-sidebar"></div>'
        + '<main class="content">'
        +   '<div id="simulation-frame-wrap" class="simulation-frame-wrap"></div>'
        +   '<div id="slot-content-rest"></div>'
        + '</main>'
        + '</div>';
      const f = document.createElement("iframe");
      f.id = "simulation-frame";
      f.src = "/__tree-child.html";
      document.getElementById("simulation-frame-wrap").appendChild(f);
    }

    // C1：整树替换（对照组）—— 会重载
    function renderFullReplace() {
      document.getElementById("app").innerHTML =
        '<div class="shell">'
        + '<div id="slot-topbar"></div>'
        + '<div id="slot-sidebar"></div>'
        + '<main class="content">'
        +   '<div id="simulation-frame-wrap" class="simulation-frame-wrap"></div>'
        +   '<div id="slot-content-rest"></div>'
        + '</main>'
        + '</div>';
      const f = document.createElement("iframe");
      f.id = "simulation-frame";
      f.src = "/__tree-child.html";
      document.getElementById("simulation-frame-wrap").appendChild(f);
    }

    // C2：分块更新 —— 只改各容器的内部，完全不动 iframe 所在容器
    let n = 0;
    function renderScoped() {
      n += 1;
      document.getElementById("slot-topbar").innerHTML = '<header>top ' + n + '</header>';
      document.getElementById("slot-sidebar").innerHTML = '<aside>side ' + n + '</aside>';
      document.getElementById("slot-content-rest").innerHTML = '<div>rest ' + n + '</div>';
      // simulation-frame-wrap 一字未动
    }

    window.__mount = mount;
    window.__renderFullReplace = renderFullReplace;
    window.__renderScoped = renderScoped;
    window.__loads = () => document.getElementById("simulation-frame")?.contentWindow?.__treeLoads ?? -1;
  </script>
</body></html>`;

const CHILD = `<!doctype html>
<html><body><div id="c">child</div>
<script>
  const n = Number(sessionStorage.getItem("tree-loads") || "0") + 1;
  sessionStorage.setItem("tree-loads", String(n));
  window.__treeLoads = n;
</script>
</body></html>`;

async function setup(page) {
  await page.route("**/__tree-child.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: CHILD }));
  await page.route("**/__tree-probe.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: PARENT }));
  await page.goto("/__tree-probe.html");
  await page.evaluate(() => window.__mount());
  await page.waitForFunction(() => window.__loads() > 0);
  return page.evaluate(() => window.__loads());
}

test.describe("分块更新方案", () => {
  test("C2：分块更新 10 次后 iframe 未重载", async ({ page }) => {
    const before = await setup(page);
    for (let i = 0; i < 10; i += 1) {
      await page.evaluate(() => window.__renderScoped());
    }
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => window.__loads());
    const stillInPlace = await page.evaluate(() =>
      document.getElementById("simulation-frame")?.parentElement?.id === "simulation-frame-wrap");

    console.log(`[tree] 分块更新: before=${before} after=${after} 原位=${stillInPlace}`);
    expect(after, "分块更新不应导致 iframe 重载").toBe(before);
    expect(stillInPlace).toBe(true);
  });

  test("对照：整树替换会重载", async ({ page }) => {
    const before = await setup(page);
    await page.evaluate(() => window.__renderFullReplace());
    await page.waitForTimeout(400);
    const after = await page.evaluate(() => window.__loads());
    console.log(`[tree] 整树替换: before=${before} after=${after}`);
    expect(after).toBeGreaterThan(before);
  });
});
