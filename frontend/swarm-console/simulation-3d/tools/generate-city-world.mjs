/**
 * 用城市布局生成与三维视图一致的 Gazebo 世界片段（SDF）。
 *
 * 为什么这样做
 * ------------
 * 三维视图的城市是前端用 `createCityLayout()` 的**确定性数据**（seededRandom(2026)）
 * 拼出来的；而 Gazebo 里只有一个 6×6×10 米的立方体假楼。两者完全是两个世界，
 * 于是"前端看着要撞墙、后端其实在空地"。
 *
 * 既然布局是确定性的，就让它成为**唯一事实来源**：同一份数据既画前端，也生成
 * Gazebo 的物理世界。这样前后端必然对齐，不需要人工同步两份几何。
 *
 * 输出的是一个可直接 `<include>` 进现有世界的 SDF model 片段，包含：
 *   - 每栋楼一个带 <collision> 的 box（有碰撞，飞机撞上会真的被挡住）
 *   - 地面参考平面（可选）
 *
 * 坐标约定（关键，必须与前端一致）
 * --------------------------------
 * 前端的 CITY.layout 用的是"任务 ENU 帧"（米）：x=东, y=北, z=上。
 * Gazebo 世界也是 ENU：x=东, y=北, z=上。
 * 而 Runtime 的 scene_ned 相对同一原点：north=y, east=x, down=-z。
 *
 * 所以布局坐标 **(x, y, z) 可以直接当作 Gazebo 世界坐标 (x, y, z)**，
 * 不需要任何换算。这正是选择这个方案的原因 —— 换算越少，越不容易错。
 *
 * 用法：
 *   node tools/generate-city-world.mjs [--block block-4-3] [--out 路径.sdf]
 *   node tools/generate-city-world.mjs --list        # 列出候选街区
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { createCityLayout, CITY, terrainHeight } from "../src/city-layout.js";

const args = process.argv.slice(2);
const getArg = (name, fallback = null) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

const { blocks, buildings } = createCityLayout();

if (args.includes("--list")) {
  console.log("候选街区（按到原点距离，排除公园与山地）：\n");
  const sorted = [...blocks].sort((a, b) => Math.hypot(a.x, a.y) - Math.hypot(b.x, b.y));
  for (const b of sorted) {
    if (b.park) continue;
    if (terrainHeight(b.x, b.y) > 5) continue;
    const n = buildingsIn(b).length;
    if (n === 0) continue;
    console.log(
      `  ${b.id.padEnd(14)} 中心(${String(b.x).padStart(6)}, ${String(b.y).padStart(6)}) ` +
        `${b.width.toFixed(0).padStart(4)}×${b.depth.toFixed(0).padStart(4)} m  ` +
        `${String(n).padStart(2)} 栋  距原点 ${Math.hypot(b.x, b.y).toFixed(0).padStart(5)} m`,
    );
  }
  process.exit(0);
}

/** 取落在指定街区范围内的建筑。 */
function buildingsIn(block) {
  const halfW = block.width / 2 + 40;
  const halfD = block.depth / 2 + 40;
  return buildings.filter(
    (b) => Math.abs(b.x - block.x) <= halfW && Math.abs(b.y - block.y) <= halfD,
  );
}

const blockId = getArg("--block", "block-4-3");
const block = blocks.find((b) => b.id === blockId);
if (!block) {
  console.error(`找不到街区 ${blockId}。用 --list 查看可选项。`);
  process.exit(1);
}

const picked = buildingsIn(block);
if (picked.length === 0) {
  console.error(`街区 ${blockId} 内没有建筑。用 --list 查看可选项。`);
  process.exit(1);
}

const out = getArg("--out", null);
const mergeInto = getArg("--merge-into", null);

const esc = (s) => String(s).replace(/[<>&]/g, "");
const heights = picked.map((b) => b.height);
const modelName = `city-${block.id}`;

// 合并标记：用它界定"由本生成器写入的区段"，使重复运行是幂等的。
// 手改这段没有意义 —— 下次运行会被覆盖，正确做法是改 city-layout.js 再重跑。
const MARK_BEGIN = `    <!-- BEGIN GENERATED city-world: ${modelName} (改 city-layout.js 后重跑生成器) -->`;
const MARK_END = `    <!-- END GENERATED city-world: ${modelName} -->`;

/** 生成 <model> 片段（用于合并进已有世界）。 */
function buildModelLines(indent = "    ") {
  const lines = [];
  lines.push(`${indent}<model name="${esc(modelName)}">`);
  lines.push(`${indent}  <static>true</static>`);
  lines.push(`${indent}  <pose>0 0 0 0 0 0</pose>`);
  for (const b of picked) {
    const h = Number(b.height);
    const w = Number(b.width);
    const d = Number(b.depth);
    // 建筑底面贴地，所以中心高度 = h/2
    lines.push(`${indent}  <link name="link-${esc(b.id)}">`);
    lines.push(
      `${indent}    <pose>${b.x.toFixed(3)} ${b.y.toFixed(3)} ${(h / 2).toFixed(3)} 0 0 0</pose>`,
    );
    lines.push(`${indent}    <collision name="collision">`);
    lines.push(
      `${indent}      <geometry><box><size>${w.toFixed(3)} ${d.toFixed(3)} ${h.toFixed(3)}</size></box></geometry>`,
    );
    lines.push(`${indent}    </collision>`);
    lines.push(`${indent}    <visual name="visual">`);
    lines.push(
      `${indent}      <geometry><box><size>${w.toFixed(3)} ${d.toFixed(3)} ${h.toFixed(3)}</size></box></geometry>`,
    );
    // 与前端同色系，便于目视核对两边的楼是不是同一栋
    const color =
      b.style === "glass"
        ? "0.55 0.68 0.78 1"
        : b.style === "brick"
          ? "0.60 0.45 0.38 1"
          : "0.78 0.79 0.81 1";
    lines.push(`${indent}      <material><ambient>${color}</ambient><diffuse>${color}</diffuse></material>`);
    lines.push(`${indent}    </visual>`);
    lines.push(`${indent}  </link>`);
  }
  lines.push(`${indent}</model>`);
  return lines;
}

const headerLines = [
  `<!--`,
  `  由 frontend/swarm-console/simulation-3d/src/city-layout.js 生成，请勿手改。`,
  `  街区: ${esc(block.id)}  中心 ENU(${block.x}, ${block.y})  尺寸 ${block.width.toFixed(0)}×${block.depth.toFixed(0)} m`,
  `  建筑: ${picked.length} 栋  高度 ${Math.min(...heights)}~${Math.max(...heights)} m`,
  `  生成日期: ${new Date().toISOString().slice(0, 10)}`,
  ``,
  `  坐标：ENU 米，与前端 CITY.layout 完全一致（x=东, y=北, z=上）。`,
  `  每栋楼带 <collision>，飞机撞上会被真实阻挡，不会穿模。`,
  `-->`,
];

if (mergeInto) {
  // 合并模式：把 model 片段插入已有世界的 </world> 之前。
  // 幂等 —— 先删掉此前由本生成器写入的区段（按标记定位），再插入新的。
  const worldPath = resolve(mergeInto);
  if (!existsSync(worldPath)) {
    console.error(`目标世界不存在: ${worldPath}`);
    process.exit(1);
  }
  const original = readFileSync(worldPath, "utf8");
  const beginIdx = original.indexOf(MARK_BEGIN);
  const endIdx = original.indexOf(MARK_END);
  let stripped = original;
  if (beginIdx >= 0 && endIdx > beginIdx) {
    stripped = original.slice(0, beginIdx) + original.slice(endIdx + MARK_END.length + 1);
  }
  const closeIdx = stripped.lastIndexOf("</world>");
  if (closeIdx < 0) {
    console.error(`目标世界缺少 </world>，无法合并: ${worldPath}`);
    process.exit(1);
  }
  const block = [MARK_BEGIN, ...headerLines.map((l) => `    ${l}`), ...buildModelLines("    "), MARK_END, ""].join("\n");
  const merged = stripped.slice(0, closeIdx) + block + "\n" + stripped.slice(closeIdx);
  writeFileSync(worldPath, merged, "utf8");
  console.log(`已合并进 ${worldPath}`);
  console.log(`  model      : ${modelName}${beginIdx >= 0 ? "（替换了此前的同名区段）" : "（新增）"}`);
} else {
  const target = out || `/tmp/city-${blockId}.sdf`;
  const lines = [`<?xml version="1.0"?>`, ...headerLines];
  lines.push(`<sdf version="1.9">`);
  lines.push(`  <world name="city_${esc(block.id).replace(/-/g, "_")}">`);
  lines.push(...buildModelLines("    "));
  lines.push(`  </world>`);
  lines.push(`</sdf>`);
  lines.push(``);
  writeFileSync(target, lines.join("\n"), "utf8");
  console.log(`已生成 ${target}`);
}

console.log(`  街区        : ${block.id}  中心 ENU(${block.x}, ${block.y})`);
console.log(`  建筑        : ${picked.length} 栋`);
console.log(`  高度范围    : ${Math.min(...heights)} ~ ${Math.max(...heights)} m`);
console.log(`  距原点      : ${Math.hypot(block.x, block.y).toFixed(0)} m`);
console.log(`  楼间通道    : 约 30~60 m（可直接飞进去）`);
console.log();
console.log(`对照：场景 NED 下该街区中心约为 ` +
  `north=${block.y}, east=${block.x}（north=y, east=x）`);
