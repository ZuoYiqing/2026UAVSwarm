import test from "node:test";
import assert from "node:assert/strict";

import {
  VEHICLE_CONTRACT_VERSION,
  normalizeVehicleSnapshot,
} from "../src/vehicle-contract.js";

function baseSnapshot(vehicle) {
  return {
    version: VEHICLE_CONTRACT_VERSION,
    timestamp_ms: 1_754_000_000_000,
    full_state: true,
    frame: { type: "ENU" },
    source: {
      id: "gazebo-sitl",
      kind: "simulation",
      label: "Gazebo SITL",
    },
    vehicles: [vehicle],
  };
}

test("normalizes an ENU vehicle and inherits snapshot source", () => {
  const snapshot = normalizeVehicleSnapshot(
    baseSnapshot({
      id: "MR-01",
      type: "quadrotor",
      pose: {
        position_m: { x: 12, y: -4, z: 30 },
        attitude_deg: { roll: 1, pitch: 2, yaw: 90 },
      },
      telemetry: { mode: "OFFBOARD", battery_percent: 82 },
    }),
  );

  assert.equal(snapshot.vehicles[0].vehicleType, "multirotor");
  assert.deepEqual(snapshot.vehicles[0].position, {
    frame: "ENU",
    eastM: 12,
    northM: -4,
    upM: 30,
    sourceFrame: "ENU",
  });
  assert.equal(snapshot.vehicles[0].source.id, "gazebo-sitl");
});

test("converts NED position to ENU", () => {
  const snapshot = normalizeVehicleSnapshot({
    ...baseSnapshot({
      id: "FW-01",
      vehicle_type: "fixed-wing",
      pose: {
        frame: "NED",
        position_m: { x: 100, y: 20, z: -50 },
      },
    }),
    frame: { type: "NED" },
  });

  assert.equal(snapshot.vehicles[0].vehicleType, "fixed_wing");
  assert.deepEqual(snapshot.vehicles[0].position, {
    frame: "ENU",
    eastM: 20,
    northM: 100,
    upM: 50,
    sourceFrame: "NED",
  });
});

test("keeps WGS84 coordinates", () => {
  const snapshot = normalizeVehicleSnapshot({
    ...baseSnapshot({
      id: "PHYSICAL-01",
      vehicle_type: "vtol",
      pose: {
        frame: "WGS84",
        position: {
          longitude_deg: 116.3913,
          latitude_deg: 39.9075,
          altitude_m: 110,
        },
      },
    }),
    frame: { type: "WGS84" },
  });

  assert.deepEqual(snapshot.vehicles[0].position, {
    frame: "WGS84",
    longitudeDeg: 116.3913,
    latitudeDeg: 39.9075,
    altitudeM: 110,
  });
});

test("rejects duplicate vehicle ids", () => {
  const vehicle = {
    id: "DUPLICATE",
    pose: { position_m: { x: 0, y: 0, z: 0 } },
  };

  assert.throws(
    () =>
      normalizeVehicleSnapshot({
        ...baseSnapshot(vehicle),
        vehicles: [vehicle, vehicle],
      }),
    /Duplicate vehicle id/,
  );
});

test("an omitted vehicle is removable when the snapshot is full state", () => {
  const snapshot = normalizeVehicleSnapshot({
    ...baseSnapshot({
      id: "UGV-01",
      vehicle_type: "rover",
      pose: { position_m: { x: 0, y: 0, z: 0 } },
    }),
    vehicles: [],
  });

  assert.equal(snapshot.fullState, true);
  assert.deepEqual(snapshot.vehicles, []);
});
