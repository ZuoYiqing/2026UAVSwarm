/**
 * 反推：什么地心点会算出线上报告的那组场景坐标？
 *
 * 线上: north=4450505.3, east=-4117128.4, down=-4388850.7
 * 若能把该点还原出来，就知道点击时到底拿到了什么。
 */
import { Cartesian3, Cartographic, Math as CesiumMath, Matrix4, Transforms } from "cesium";

const ANCHOR = { longitude: 116.3913, latitude: 39.9075, altitude: 0 };
const origin = Cartesian3.fromDegrees(ANCHOR.longitude, ANCHOR.latitude, ANCHOR.altitude);
const missionFrame = Transforms.eastNorthUpToFixedFrame(origin);

const REPORTED = { north: 4450505.3, east: -4117128.4, down: -4388850.7 };

// scene_ned -> ENU:  east=ENU.x, north=ENU.y, down=-ENU.z
const enu = new Cartesian3(REPORTED.east, REPORTED.north, -REPORTED.down);
const world = Matrix4.multiplyByPoint(missionFrame, enu, new Cartesian3());

console.log("=== 由线上值反推出的地心点 ===");
console.log(`  ECEF = (${world.x.toFixed(0)}, ${world.y.toFixed(0)}, ${world.z.toFixed(0)})`);
console.log(`  距地心 = ${(Cartesian3.magnitude(world) / 1000).toFixed(0)} km  （正常地表约 6371 km）`);

const carto = Cartographic.fromCartesian(world);
console.log(`  经纬度 = ${CesiumMath.toDegrees(carto.latitude).toFixed(4)}°, ${CesiumMath.toDegrees(carto.longitude).toFixed(4)}°`);
console.log(`  高度   = ${(carto.height / 1000).toFixed(0)} km  （正常应接近 0）`);

console.log("\n=== 与锚点对比 ===");
const anchorCarto = Cartographic.fromCartesian(origin);
console.log(`  锚点 = ${CesiumMath.toDegrees(anchorCarto.latitude).toFixed(4)}°, ${CesiumMath.toDegrees(anchorCarto.longitude).toFixed(4)}°`);
console.log(`  反推点距锚点约 ${(Cartesian3.distance(world, origin) / 1000).toFixed(0)} km`);

console.log("\n=== 判断 ===");
const heightKm = carto.height / 1000;
if (Math.abs(heightKm) > 100) {
  console.log("  反推出的点高度异常 -> 传入的**不是**椭球面上的有效点。");
  console.log("  说明 pickEllipsoid 的返回值本身有问题，或中途被替换成了别的东西。");
} else {
  console.log("  反推出的点在地表附近 -> 说明变换的**输入**是合理的，问题在别处。");
}

// 另一种可能：把锚点自身当成了输入
console.log("\n=== 对照假设：若输入是「锚点本身」当作 ENU 偏移 ===");
const bogus = Matrix4.multiplyByPoint(missionFrame, origin, new Cartesian3());
const back = Matrix4.multiplyByPoint(Matrix4.inverse(missionFrame, new Matrix4()), bogus, new Cartesian3());
console.log(`  会得到 北 ${back.y.toFixed(0)}, 东 ${back.x.toFixed(0)}, 下 ${(-back.z).toFixed(0)}`);
console.log("  （这与线上值不同，可排除该假设）");
