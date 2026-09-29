/**
 * 校验生成/合并后的 Gazebo 世界是否合法、楼是否贴地、是否有碰撞体。
 *
 * 用法：
 *   node tools/validate-city-world.mjs <world.sdf> [--expect-block block-4-3]
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const path = args[0];
if (!path) {
  console.error("用法: node tools/validate-city-world.mjs <world.sdf>");
  process.exit(2);
}
const file = resolve(path);
if (!existsSync(file)) {
  console.error(`文件不存在: ${file}`);
  process.exit(1);
}
const text = readFileSync(file, "utf8");

let ok = true;
const check = (label, pass, detail = "") => {
  if (!pass) ok = false;
  console.log(`  ${pass ? "✅" : "❌"} ${label}${detail ? `  (${detail})` : ""}`);
};

console.log(`=== 校验 ${file} ===`);

// XML 良构性的轻量检查：标签配对。完整的 XML 解析在 Node 里需要额外依赖，
// 而 Gazebo 自己会做严格解析，这里只做"明显损坏"的兜底。
const opens = (text.match(/<model\b/g) || []).length;
const closes = (text.match(/<\/model>/g) || []).length;
check("model 标签配对", opens === closes, `open=${opens} close=${closes}`);

const worldCount = (text.match(/<world\b/g) || []).length;
check("恰好一个 <world>", worldCount === 1, `count=${worldCount}`);

check("以 </sdf> 收尾", text.trimEnd().endsWith("</sdf>"));

// 生成区段的标记与内容
const begin = text.indexOf("<!-- BEGIN GENERATED city-world");
const end = text.indexOf("<!-- END GENERATED city-world");
check("存在生成区段标记", begin >= 0 && end > begin,
  begin < 0 ? "未找到（尚未合并？）" : `span=${end - begin} 字符`);

if (begin >= 0 && end > begin) {
  const section = text.slice(begin, end);
  const links = (section.match(/<link name="link-block-/g) || []).length;
  check("生成区段内含建筑 link", links > 0, `${links} 个`);
  // 用带 '>' 的精确模式：区段的注释文字里也提到了 <collision>，
  // 只匹配 "<collision" 会把注释一起数进去（实测多出 1，导致误报）。
  const collisions = (section.match(/<collision\s+name="/g) || []).length;
  const visuals = (section.match(/<visual\s+name="/g) || []).length;
  check("每栋楼都有碰撞体（否则会穿模）", collisions === links,
    `collision=${collisions} link=${links}`);
  check("collision 与 visual 数量一致", collisions === visuals,
    `collision=${collisions} visual=${visuals}`);

  // 每栋楼是否底面贴地：pose 的 z 应等于 size 的 z/2
  const linkRe = /<link name="(link-block-[^"]+)">\s*<pose>([-\d.]+) ([-\d.]+) ([-\d.]+)[^<]*<\/pose>[\s\S]*?<box><size>([-\d.]+) ([-\d.]+) ([-\d.]+)<\/size>/g;
  let m, count = 0, floating = [];
  while ((m = linkRe.exec(section)) !== null) {
    count += 1;
    const pz = Number(m[4]);
    const h = Number(m[7]);
    if (Math.abs(pz - h / 2) > 0.02) floating.push(`${m[1]} pose_z=${pz} 应为 ${(h / 2).toFixed(3)}`);
  }
  check("能解析出楼的位置与尺寸", count === links, `解析 ${count} / link ${links}`);
  check("所有楼底面贴地", floating.length === 0,
    floating.length ? floating.slice(0, 3).join("; ") : "");
}

// 关键：合并不能破坏原有的模型
for (const name of ["ground_plane", "building-001", "landing-pad-UAV-01",
                    "landing-pad-UAV-02", "landing-pad-UAV-03"]) {
  check(`原有 model 仍在: ${name}`, text.includes(`<model name="${name}">`));
}

console.log();
console.log(ok ? "结论：世界文件校验通过 ✅" : "结论：存在问题 ❌");
process.exit(ok ? 0 : 1);
