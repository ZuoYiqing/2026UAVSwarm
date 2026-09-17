export const QINGLAN_SCENE = Object.freeze({
  scene_id: "qinglan_city_v1", map_version: "qinglan-city-1",
  scene_origin: { kind: "synthetic_enu_anchor", north_m: 0, east_m: 0, down_m: 0 },
  anchor: { longitude: 116.3913, latitude: 39.9075, altitude: 0 },
  altitude_reference: "scene_origin_z_down", physical_status: "visual_only",
});

// This is a local coordinate reference view, not a claim of surveyed geography.
export const RECON_SCENE = Object.freeze({
  scene_id: "simple_recon_v0_1", map_version: "simple_recon_v0_1-map-1",
  scene_origin: { kind: "gazebo_world_ned", north_m: 0, east_m: 0, down_m: 0 },
  anchor: { longitude: 8.5461639, latitude: 47.3979709, altitude: 0 },
  altitude_reference: "scene_origin_z_down", physical_status: "reference_only",
});

const finite = value => typeof value === "number" && Number.isFinite(value);
const timestamp = value => typeof value === "string" ? Date.parse(value) : NaN;

export function alignmentReason(vehicle, snapshot, scene, nowMs, staleAfterMs) {
  const s = vehicle.spatial;
  const c = snapshot.coordinateContract;
  if (!scene?.scene_id) return "当前地图仅展示";
  if (!s || s.contract_version !== "1.0") return "缺少 spatial 1.0 公共坐标契约";
  if (snapshot.sceneId !== scene.scene_id || s.scene_id !== scene.scene_id) return "scene_id 不匹配";
  if (s.map_version !== scene.map_version) return "map_version 不匹配";
  if (!c || c.version !== "1.0" || c.transform_owner !== "runtime" || c.calibration_producer !== "simulation") return "公共变换所有权未确认";
  if (c.public_frame !== "scene_ned" || s.public_frame !== "scene_ned" || s.scene_pose?.frame !== "scene_ned") return "公共 frame 未确认";
  if (c.units !== "m" || s.units !== "m" || c.z_convention !== "positive_down" || s.z_convention !== "positive_down") return "单位或坐标轴不匹配";
  if (s.altitude_reference !== scene.altitude_reference || c.altitude_reference !== scene.altitude_reference) return "高程参考不匹配";
  const origin = s.scene_origin;
  if (!origin || origin.kind !== scene.scene_origin.kind || ["north_m", "east_m", "down_m"].some(k => !finite(origin[k]) || Math.abs(origin[k] - scene.scene_origin[k]) > 1e-6)) return "origin 不匹配";
  if (s.axis_alignment !== "ned_aligned") return "axis_alignment 未确认或不受支持";
  // No yaw-derived rotation, implicit rebase, or consumer-side spawn translation.
  if (s.frame_transform || c.frame_transform) return "frame transform 尚未约定";
  if (s.attitude_convention !== "roll_pitch_yaw_deg_ned_frd") return "姿态约定未确认";
  if (s.origin_continuity !== "verified" || !s.local_origin_id || !s.calibration_version) return "原点连续性未验证";
  if (s.calibration_status !== "calibrated" || s.public_position_usable !== true) return "公共位置不可用或标定过期";
  const calibrationTime = timestamp(s.calibration_source_timestamp);
  const sampleTime = timestamp(s.sample_timestamp);
  if (!finite(calibrationTime) || !finite(sampleTime) || calibrationTime > nowMs + 5000 || sampleTime > nowMs + 5000) return "标定或样本时间无效";
  if (!finite(s.calibration_age_ms) || s.calibration_age_ms < 0 || !finite(s.calibration_valid_for_ms) || s.calibration_valid_for_ms <= 0) return "标定有效期缺失";
  if (Math.max(s.calibration_age_ms, nowMs - calibrationTime) > s.calibration_valid_for_ms) return "标定已过期";
  if (!finite(s.sample_age_ms) || s.sample_age_ms < 0) return "样本 age 无效";
  const p = s.scene_pose.position_m;
  if (!p || ![p.x, p.y, p.z].every(finite)) return "公共位置不是有限数值";
  return "";
}

export function projectPublicVehicle(vehicle, snapshot, scene, nowMs, staleAfterMs = 3000) {
  const reason = alignmentReason(vehicle, snapshot, scene, nowMs, staleAfterMs);
  const s = vehicle.spatial;
  if (reason) return { ...vehicle, position: null, positionUsable: false,
    alignment: { aligned: false, reason }, telemetry: { ...vehicle.telemetry, stale: true } };
  const p = s.scene_pose.position_m;
  const ageMs = Math.max(s.sample_age_ms, nowMs - timestamp(s.sample_timestamp), nowMs - snapshot.timestampMs, vehicle.telemetry.ageMs || 0);
  const attitude = s.scene_pose.attitude_deg;
  const attitudeKnown = attitude && [attitude.roll, attitude.pitch, attitude.yaw].every(finite);
  return {
    ...vehicle,
    position: { frame: "ENU", eastM: p.y, northM: p.x, upM: -p.z, sourceFrame: "scene_ned" },
    attitude: attitudeKnown ? { rollDeg: attitude.roll, pitchDeg: attitude.pitch, yawDeg: attitude.yaw } : { rollDeg: 0, pitchDeg: 0, yawDeg: 0 },
    attitudeKnown: Boolean(attitudeKnown), positionUsable: true,
    publicValidUntilMs: Math.min(timestamp(s.calibration_source_timestamp) + s.calibration_valid_for_ms, nowMs + s.calibration_valid_for_ms - s.calibration_age_ms),
    alignment: { aligned: true, reason: "" },
    telemetry: { ...vehicle.telemetry, stale: vehicle.telemetry.stale || s.stale === true || ageMs > staleAfterMs, ageMs },
  };
}
