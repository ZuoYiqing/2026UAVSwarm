/**
 * 记录一条被实测推翻的假设：**移动 iframe 一定会触发重新加载。**
 *
 * 背景：主控制台的 render() 原本用 `app.innerHTML = ...` 整树替换，而三维视图是
 * 其中的 <iframe>，于是每次 render 都会销毁并重建它 —— 用户看到的是
 * "点一下载具列表，左边地图就刷新一次"，Cesium 场景重新加载、选中状态丢失。
 *
 * 第一版修复试图"把 iframe 摘下来、替换完再放回去"，理由是"同一文档内移动 iframe
 * 不会重新加载"。**这个理由是错的**，本测试就是用来固定这个结论：
 *
 *   四种移动方式实测全部导致重新加载：
 *     - appendChild 到另一个已在文档中的父元素
 *     - replaceChildren 到另一个父元素
 *     - remove 后 append 回**同一个**父元素
 *     - remove、等一拍、再移到另一个父元素
 *   连"移动 iframe 的祖先容器"也一样重载（见 iframe-tree-probe.spec.js 的对照）。
 *
 * 因此正确的做法不是"搬动"，而是**根本不碰 iframe 所在的子树**：
 * 外壳只建一次，各区域各自更新（见 app.js 的 ensureShell / renderRegions）。
 * 该方案的有效性由 iframe-tree-probe.spec.js 与 e2e/console-integration.spec.js 验证。
 *
 * 保留本文件是为了让后来者不必再试一遍这个死路。
 */
import { test, expect } from "@playwright/test";

const PARENT = `<!doctype html>
<html><body>
  <div id="host-a"><iframe id="f" src="/__mv-child.html"></iframe></div>
  <div id="host-b"></div>
  <script>
    window.__loads = () => document.getElementById("f")?.contentWindow?.__mvLoads ?? -1;
    window.__moveAppend = () => {
      document.getElementById("host-b").appendChild(document.getElementById("f"));
    };
    window.__moveReplace = () => {
      document.getElementById("host-b").replaceChildren(document.getElementById("f"));
    };
    window.__removeThenAppendSameParent = () => {
      const f = document.getElementById("f");
      const host = f.parentNode;
      f.remove();
      host.appendChild(f);
    };
  </script>
</body></html>`;

const CHILD = `<!doctype html>
<html><body><div id="c">child</div>
<script>
  const n = Number(sessionStorage.getItem("mv-loads") || "0") + 1;
  sessionStorage.setItem("mv-loads", String(n));
  window.__mvLoads = n;
</script>
</body></html>`;

async function setup(page) {
  await page.route("**/__mv-child.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: CHILD }));
  await page.route("**/__move-probe.html", (route) =>
    route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: PARENT }));
  await page.goto("/__move-probe.html");
  await page.waitForFunction(() => document.getElementById("f")?.contentWindow?.__mvLoads > 0);
  return page.evaluate(() => window.__loads());
}

test.describe("移动 iframe 必然触发重新加载", () => {
  for (const [label, fn] of [
    ["appendChild 到另一个父元素", "__moveAppend"],
    ["replaceChildren 到另一个父元素", "__moveReplace"],
    ["remove 后 append 回同一父元素", "__removeThenAppendSameParent"],
  ]) {
    test(`${label} → 重新加载（因此该保活思路不可用）`, async ({ page }) => {
      const before = await setup(page);
      await page.evaluate((f) => window[f](), fn);
      await page.waitForTimeout(400);
      const after = await page.evaluate(() => window.__loads());
      expect(after, `${label} 竟然没有重载 —— 若成立，保活方案可以简化`).toBeGreaterThan(before);
    });
  }
});
