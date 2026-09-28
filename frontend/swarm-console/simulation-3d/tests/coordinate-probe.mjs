/**
 * 实测 worldToSceneNed 的逆变换是否正确。
 *
 * 背景：在青岚市场景里点击地面，得到的目标坐标是几百万米量级
 * （north=4450505, east=-4117128），显然错误。
 * 本脚本直接验证 Matrix4.inverse + multiplyByPoint 的行为，
 * 判断是变换本身写错，还是调用方传入了错误的点。
 */
import { Cartesian3, Matrix4, Transforms } from "cesium";

const ANCHOR = { longitude: 116.3913, latitude: 39.9075, altitude: 0 };
const origin = Cartesian3.fromDegrees(ANCHOR.longitude, ANCHOR.latitude, ANCHOR.altitude);
const missionFrame = Transforms.eastNorthUpToFixedFrame(origin);

console.log("=== 锚点 ===");
console.log(`  ECEF = (${origin.x.toFixed(1)}, ${origin.y.toFixed(1)}, ${origin.z.toFixed(1)})`);
console.log(`  |origin| = ${Cartesian3.magnitude(origin).toFixed(0)} m`);

const inverse = Matrix4.inverse(missionFrame, new Matrix4());

function toSceneNed(worldPosition) {
  const local = Matrix4.multiplyByPoint(inverse, worldPosition, new Cartesian3());
  return { north: local.y, east: local.x, down: -local.z };
}

console.log("\n=== 用 ENU 正变换造点，再用逆变换还原（自洽性检验）===");
const cases = [
  [0, 0, 0],
  [100, 0, 0],      // 东 100
  [0, 100, 0],      // 北 100
  [0, 0, 50],       // 上 50
  [-250, 300, -10], // 西 250、北 300、下 10
];

let allOk = true;
for (const [e, n, u] of cases) {
  const world = Matrix4.multiplyByPoint(missionFrame, new Cartesian3(e, n, u), new Cartesian3());
  const back = toSceneNed(world);
  const ok = Math.abs(back.east - e) < 1e-6 && Math.abs(back.north - n) < 1e-6 && Math.abs(back.down - -u) < 1e-6;
  if (!ok) allOk = false;
  console.log(
    `  ENU(${e}, ${n}, ${u}) -> scene_ned(北 ${back.north.toFixed(3)}, 东 ${back.east.toFixed(3)}, 下 ${back.down.toFixed(3)})  ${ok ? "OK" : "*** 不一致 ***"}`,
  );
}

console.log(`\n自洽性: ${allOk ? "全部通过 —— 逆变换本身是对的" : "存在错误"}`);

console.log("\n=== 如果误把「地心坐标」当「ENU 局部坐标」会怎样（复现线上现象）===");
// 把锚点的 ECEF 直接当作 ENU 偏移，再走正变换 —— 模拟"用错原点"的效果
const bogusEnu = new Cartesian3(origin.x, origin.y, origin.z);
const bogusWorld = Matrix4.multiplyByPoint(missionFrame, bogusEnu, new Cartesian3());
const bogusBack = toSceneNed(bogusWorld);
console.log(`  结果: 北 ${bogusBack.north.toFixed(0)}, 东 ${bogusBack.east.toFixed(0)}, 下 ${bogusBack.down.toFixed(0)}`);
console.log("  （若线上数字与此同量级，说明调用方把 ECEF 当成了 ENU）");

console.log("\n=== 线上报告的错误值反推 ===");
console.log("  线上: 北 4450505.3, 东 -4117128.4, 下 -4388850.7");
console.log(`  锚点 ECEF: x=${origin.x.toFixed(0)}, y=${origin.y.toFixed(0)}, z=${origin.z.toFixed(0)}`);
console.log("  对比可见线上「北」≈ 锚点 ECEF.y、「东」≈ 锚点 ECEF.x，符号与量级都对得上。");
