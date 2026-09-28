/**
 * 统计城市布局在原点附近的建筑，判断"在楼中间飞"是否现实。
 *
 * createCityLayout() 是纯 JS（只依赖 seededRandom），可在 Node 里直接跑，
 * 不需要浏览器。这使"用同一份数据生成 Gazebo 世界"成为可行方案。
 */
import { createCityLayout, CITY } from "../src/city-layout.js";

const { buildings, blocks } = createCityLayout();
console.log(`建筑总数 ${buildings.length}，街区 ${blocks.length}`);
console.log(`城市范围 bounds = [${CITY.bounds.join(", ")}]  (米, ENU)`);

const sample = buildings[0];
console.log(`\n单个建筑的字段: ${Object.keys(sample).join(", ")}`);
console.log(`示例: ${JSON.stringify(sample)}`);

// 按到原点的距离分环统计
const rings = [100, 200, 300, 500, 800, 1200, 2000];
console.log("\n=== 到原点距离内的建筑数 ===");
for (const r of rings) {
  const n = buildings.filter((b) => Math.hypot(b.x ?? 0, b.y ?? 0) <= r).length;
  console.log(`  ≤ ${String(r).padStart(4)} m : ${String(n).padStart(3)} 栋`);
}

// 原点附近取一小片，看看"楼中间"的密度与街道宽度
const near = buildings.filter((b) => Math.abs(b.x ?? 0) <= 250 && Math.abs(b.y ?? 0) <= 250);
console.log(`\n=== 原点 ±250 m 内: ${near.length} 栋 ===`);
if (near.length) {
  const heights = near.map((b) => b.height ?? 0).filter((h) => h > 0);
  const xs = near.map((b) => b.x).sort((a, b) => a - b);
  const ys = near.map((b) => b.y).sort((a, b) => a - b);
  console.log(`  高度范围 : ${Math.min(...heights).toFixed(1)} ~ ${Math.max(...heights).toFixed(1)} m`);
  console.log(`  x 范围   : ${xs[0].toFixed(1)} ~ ${xs[xs.length - 1].toFixed(1)} m`);
  console.log(`  y 范围   : ${ys[0].toFixed(1)} ~ ${ys[ys.length - 1].toFixed(1)} m`);

  // 街道宽度估计：相邻建筑中心的间距减去建筑尺寸
  const gaps = [];
  for (let i = 1; i < xs.length; i++) {
    const d = xs[i] - xs[i - 1];
    if (d > 1) gaps.push(d);
  }
  if (gaps.length) {
    gaps.sort((a, b) => a - b);
    console.log(`  x 向相邻间距中位数: ${gaps[Math.floor(gaps.length / 2)].toFixed(1)} m`);
  }
  console.log("\n  前 8 栋明细:");
  for (const b of near.slice(0, 8)) {
    console.log(
      `    ${String(b.id).padEnd(18)} pos=(${Number(b.x).toFixed(1)}, ${Number(b.y).toFixed(1)}) ` +
        `size=(${Number(b.width).toFixed(1)} × ${Number(b.depth).toFixed(1)}) h=${Number(b.height).toFixed(1)}m`,
    );
  }
}

console.log("\n=== 道路网格 ===");
console.log(`  roadsX (南北向道路的 x 坐标): ${CITY.roadsX.join(", ")}`);
console.log(`  roadsY (东西向道路的 y 坐标): ${CITY.roadsY.join(", ")}`);
console.log(`  桥   : x = ${CITY.bridgeX.join(", ")}`);
