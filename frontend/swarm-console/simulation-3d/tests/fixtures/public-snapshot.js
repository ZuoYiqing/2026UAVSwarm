import { RECON_SCENE } from "../../src/scene-alignment.js";

// Simulated evidence only; no PX4/Gazebo measurements are represented here.
export function publicSnapshot({ time = Date.now(), scene = RECON_SCENE, positions = [[0,0,0],[0,8,0],[0,-8,0]] } = {}) {
  const timestamp = new Date(time).toISOString();
  return {
    version: "1.0", timestamp_ms: time, full_state: true, scene_id: scene.scene_id,
    source: { id: "contract-fixture", kind: "simulation", label: "FIXTURE ONLY" }, frame: { type: "NED" },
    coordinate_contract: { version: "1.0", public_frame: "scene_ned", local_frame: "vehicle_local_ned", units: "m", z_convention: "positive_down", altitude_reference: scene.altitude_reference, transform_owner: "runtime", calibration_producer: "simulation" },
    vehicles: positions.map(([x,y,z],i) => ({
      id: `UAV-0${i+1}`, vehicle_type: "multirotor", connected: true,
      pose: { frame: "NED", position_m: { x: 0, y: 0, z: 0 } }, pose_source: "runtime_scene_calibration",
      telemetry: { stale: false, age_ms: 0, mode: "HOLD", ground_speed_mps: 0 },
      spatial: { contract_version: "1.0", scene_id: scene.scene_id, map_version: scene.map_version,
        public_frame: "scene_ned", local_frame: "vehicle_local_ned", units: "m", z_convention: "positive_down",
        scene_origin: structuredClone(scene.scene_origin), altitude_reference: scene.altitude_reference,
        attitude_convention: "roll_pitch_yaw_deg_ned_frd", axis_alignment: "ned_aligned",
        calibration_status: "calibrated", public_position_usable: true, origin_continuity: "verified",
        local_origin_id: `fixture-origin-${i+1}`, calibration_version: `fixture-cal-${i+1}`,
        source_timestamp: timestamp, sample_timestamp: timestamp, calibration_source_timestamp: timestamp,
        sample_age_ms: 0, calibration_age_ms: 0, calibration_valid_for_ms: 5000, stale: false,
        scene_pose: { frame: "scene_ned", position_m: {x,y,z}, attitude_deg: { roll: 0, pitch: 0, yaw: i*90 } },
        raw_vehicle_local_pose: { frame: "vehicle_local_ned", position_m: { x: 0, y: 0, z: 0 } },
      },
    })),
  };
}
