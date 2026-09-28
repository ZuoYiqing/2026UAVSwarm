/**
 * 找一个适合做"楼中间飞行"演示的街区。
 *
 * 约束：
 *   - 原点街区 (-280..260, -300..210) 是保留的测试园区，不能加楼（会盖住起降点）。
 *   - terrainHeight > 5 的地方是山地，也不该放楼。
 *   - 离原点越近越好，方便从测试园区直接飞过去。
 */
import { createCityLayout, CITY, terrainHeight } from "../src/city-layout.js";

const { blocks } = createCityLayout();

console.log("=== 全部街区（按到原点距离排序，取最近 12 个）===");
const sorted = [...blocks].sort((a, b) => Math.hypot(a.x, a.y) - Math.hypot(b.x, b.y));
console.log("  街区             中心(东,北)      尺寸(宽×深)      到原点   公园");
for (const b of sorted.slice(0, 12)) {
  console.log(
    `  ${b.id.padEnd(14)} (${String(b.x).padStart(6)}, ${String(b.y).padStart(6)})  ` +
      `${b.width.toFixed(0).padStart(4)} × ${b.depth.toFixed(0).padStart(4)} m  ` +
      `${Math.hypot(b.x, b.y).toFixed(0).padStart(6)} m   ${b.park ? "是" : ""}`,
  );
}

console.log("\n=== 地形检查（terrainHeight > 5 视为山地）===");
for (const b of sorted.slice(0, 8)) {
  const h = terrainHeight(b.x, b.y);
  console.log(`  ${b.id.padEnd(14)} terrainHeight = ${h.toFixed(1)} m  ${h > 5 ? "*** 山地，不适合" : "平地"}`);
}

console.log("\n=== 起点（原点）到最近街区的距离 ===");
const nearest = sorted[0];
console.log(`  ${nearest.id}: 中心 (${nearest.x}, ${nearest.y})，距原点 ${Math.hypot(nearest.x, nearest.y).toFixed(0)} m`);
console.log(`  该街区内会生成 ${3 * 3}-${4 * 4} 栋楼（取决于尺寸阈值）`);

console.log("\n=== 街道宽度（决定楼与楼之间的通道有多宽）===");
const gapX = [];
for (let i = 1; i < CITY.roadsX.length; i++) gapX.push(CITY.roadsX[i] - CITY.roadsX[i - 1]);
console.log(`  roadsX 相邻间距: ${gapX.join(", ")} m`);
console.log(`  街区宽度 320 m 左右，减去 34 m 道路退距后是街区本体`);
console.log(`  街区内每栋楼宽约为 街区宽/3 × 0.48~0.66，所以楼与楼之间约 30~60 m 通道`);
