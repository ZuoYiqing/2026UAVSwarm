import test from "node:test";
import assert from "node:assert/strict";
import { Cartesian3 } from "cesium";

import {
  RuntimeVehicleSnapshotPoller,
  VehicleSnapshotState,
} from "../src/vehicle-snapshot-state.js";
import { normalizeVehicleSnapshot } from "../src/vehicle-contract.js";
import { VehicleLayer } from "../src/vehicle-layer.js";

function vehicle(id, x = 0, type = "multirotor") {
  return {
    id,
    display_name: id,
    vehicle_type: type,
    connected: true,
    pose: {
      frame: "ENU",
      position_m: { x, y: 0, z: type === "ugv" ? 1 : 30 },
      attitude_deg: { roll: 0, pitch: 0, yaw: 0 },
    },
    telemetry: { mode: "AUTO", battery_percent: 80 },
  };
}

function snapshot(timestampMs, vehicles) {
  return {
    version: "1.0",
    timestamp_ms: timestampMs,
    full_state: true,
    source: {
      id: "runtime-fusion",
      kind: "simulation",
      label: "Runtime",
    },
    frame: { type: "ENU" },
    vehicles,
  };
}

function withStatus(rawVehicle, { connected = true, stale = false, ageMs = 0 } = {}) {
  return {
    ...rawVehicle,
    connected,
    telemetry: {
      ...rawVehicle.telemetry,
      stale,
      age_ms: ageMs,
    },
  };
}

function installCanvasStub() {
  const context = new Proxy(
    {},
    {
      get: (target, property) => target[property] || (() => {}),
      set: (target, property, value) => {
        target[property] = value;
        return true;
      },
    },
  );
  globalThis.document = {
    createElement: () => ({
      getContext: () => context,
      toDataURL: () => "data:image/png;base64,marker",
    }),
  };
}

function createViewerStub() {
  const entities = new Map();
  return {
    entities: {
      add(options) {
        entities.set(options.id, options);
        return options;
      },
      remove(entity) {
        return entities.delete(entity.id);
      },
    },
  };
}

test("full snapshots report dynamic additions, updates, and removals", () => {
  const state = new VehicleSnapshotState({ now: () => 1_000 });
  const first = state.ingest(snapshot(100, [vehicle("MR-01"), vehicle("UGV-01", 2, "ugv")]));
  assert.deepEqual(first.diff, {
    added: ["MR-01", "UGV-01"],
    updated: [],
    removed: [],
  });

  const second = state.ingest(snapshot(200, [vehicle("MR-01", 8), vehicle("FW-01", 4, "fixed_wing")]));
  assert.deepEqual(second.diff, {
    added: ["FW-01"],
    updated: ["MR-01"],
    removed: ["UGV-01"],
  });
  assert.equal(state.vehicles.size, 2);
  assert.equal(state.getVehicle("MR-01").position.eastM, 8);
  assert.equal(state.getVehicle("UGV-01"), undefined);
});

test("stale state freezes the last accepted vehicle position", () => {
  const state = new VehicleSnapshotState({ staleAfterMs: 3_000, now: () => 1_000 });
  state.ingest(snapshot(100, [vehicle("MR-01", 12)]), { receivedAtMs: 1_000 });

  assert.equal(state.statusAt(3_999).stale, false);
  assert.equal(state.statusAt(4_001).stale, true);
  assert.equal(state.statusAt(4_001).connection, "stale");
  assert.equal(state.getVehicle("MR-01").position.eastM, 12);
});

test("stale vehicle updates status but preserves its last trusted pose", () => {
  const state = new VehicleSnapshotState();
  const freshA = vehicle("MR-01", 10);
  freshA.pose.attitude_deg.yaw = 15;
  state.ingest(snapshot(100, [freshA]));

  const staleB = vehicle("MR-01", 80);
  staleB.pose.attitude_deg.yaw = 120;
  state.ingest(snapshot(600, [withStatus(staleB, { stale: true, ageMs: 2_500 })]));

  assert.equal(state.getVehicle("MR-01").position.eastM, 10);
  assert.equal(state.getVehicle("MR-01").attitude.yawDeg, 15);
  assert.equal(state.getVehicle("MR-01").telemetry.stale, true);
  assert.equal(state.getVehicle("MR-01").telemetry.ageMs, 2_500);

  const freshC = vehicle("MR-01", 120);
  freshC.pose.attitude_deg.yaw = 35;
  state.ingest(snapshot(1_200, [freshC]));
  assert.equal(state.getVehicle("MR-01").position.eastM, 120);
  assert.equal(state.getVehicle("MR-01").attitude.yawDeg, 35);
  assert.equal(state.getVehicle("MR-01").telemetry.stale, false);
});

test("Cesium entity and trail freeze at A during stale B then resume at fresh C", () => {
  installCanvasStub();
  const layer = new VehicleLayer(
    createViewerStub(),
    (position) => new Cartesian3(6_378_137 + position.eastM, position.northM, position.upM),
  );
  const apply = (timestampMs, rawVehicle) =>
    layer.applySnapshot(normalizeVehicleSnapshot(snapshot(timestampMs, [rawVehicle])));

  const freshA = vehicle("MR-01", 10);
  freshA.pose.attitude_deg.yaw = 15;
  apply(100, freshA);
  const record = layer.getRecords()[0];
  const trustedPosition = record.worldPosition;
  const trustedOrientation = record.entity.orientation;
  const initialTrailLength = record.trailPositions.length;

  const staleB = vehicle("MR-01", 80);
  staleB.pose.attitude_deg.yaw = 120;
  apply(600, withStatus(staleB, { connected: false, stale: true, ageMs: 2_500 }));

  assert.equal(record.worldPosition, trustedPosition);
  assert.equal(record.entity.position, trustedPosition);
  assert.equal(record.entity.orientation, trustedOrientation);
  assert.equal(record.trailPositions.length, initialTrailLength);
  assert.equal(record.vehicle.telemetry.ageMs, 2_500);
  assert.equal(layer.isRecordStale(record), true);

  const freshC = vehicle("MR-01", 120);
  freshC.pose.attitude_deg.yaw = 35;
  apply(1_200, freshC);

  assert.equal(record.worldPosition.x, 6_378_257);
  assert.equal(record.entity.position, record.worldPosition);
  assert.notEqual(record.entity.orientation, trustedOrientation);
  assert.equal(record.trailPositions.length, initialTrailLength + 1);
  assert.equal(layer.isRecordStale(record), false);
});

test("a newly discovered stale vehicle is placed once and remains removable", () => {
  installCanvasStub();
  const layer = new VehicleLayer(
    createViewerStub(),
    (position) => new Cartesian3(6_378_137 + position.eastM, position.northM, position.upM),
  );
  const apply = (timestampMs, vehicles) =>
    layer.applySnapshot(normalizeVehicleSnapshot(snapshot(timestampMs, vehicles)));

  apply(100, [withStatus(vehicle("MR-STALE", 40), { stale: true, ageMs: 4_000 })]);
  const record = layer.getRecords()[0];
  assert.equal(record.worldPosition.x, 6_378_177);
  assert.equal(record.trailPositions.length, 1);

  apply(700, [withStatus(vehicle("MR-STALE", 90), { stale: true, ageMs: 4_600 })]);
  assert.equal(record.worldPosition.x, 6_378_177);
  assert.equal(record.trailPositions.length, 1);
  assert.equal(record.vehicle.telemetry.ageMs, 4_600);

  apply(1_300, []);
  assert.equal(layer.getRecords().length, 0);
});

test("out-of-order snapshots are rejected without rolling positions back", () => {
  const state = new VehicleSnapshotState();
  state.ingest(snapshot(200, [vehicle("MR-01", 20)]));
  const result = state.ingest(snapshot(100, [vehicle("MR-01", 5)]));

  assert.equal(result.accepted, false);
  assert.equal(result.reason, "out-of-order");
  assert.equal(state.getVehicle("MR-01").position.eastM, 20);
});

test("the same snapshot timestamp is de-duplicated", () => {
  const state = new VehicleSnapshotState();
  state.ingest(snapshot(200, [vehicle("MR-01", 20)]));
  const result = state.ingest(snapshot(200, [vehicle("MR-01", 40)]));

  assert.equal(result.accepted, false);
  assert.equal(result.reason, "duplicate");
  assert.equal(state.getVehicle("MR-01").position.eastM, 20);
});

test("invalid snapshot data is rejected and preserves the last valid fleet", () => {
  const state = new VehicleSnapshotState();
  state.ingest(snapshot(100, [vehicle("MR-01", 3)]));
  const invalid = snapshot(200, [{ id: "BROKEN", vehicle_type: "multirotor" }]);

  assert.throws(() => state.ingest(invalid), /requires pose/);
  assert.equal(state.vehicles.size, 1);
  assert.equal(state.getVehicle("MR-01").position.eastM, 3);
});

test("parent snapshots take authority and suppress later runtime polling results", () => {
  const state = new VehicleSnapshotState();
  state.ingest(snapshot(100, [vehicle("MR-01", 1)]), { transport: "runtime" });
  state.ingest(snapshot(200, [vehicle("MR-01", 2)]), { transport: "parent" });
  const suppressed = state.ingest(snapshot(300, [vehicle("MR-01", 3)]), { transport: "runtime" });

  assert.equal(state.transport, "parent");
  assert.equal(suppressed.reason, "transport-suppressed");
  assert.equal(state.getVehicle("MR-01").position.eastM, 2);
});

test("runtime poller is idempotent and never overlaps requests", async () => {
  let fetchCount = 0;
  let releaseFetch;
  const deferred = new Promise((resolve) => {
    releaseFetch = resolve;
  });
  const poller = new RuntimeVehicleSnapshotPoller({
    fetchSnapshot: async () => {
      fetchCount += 1;
      await deferred;
      return snapshot(100, []);
    },
    onSnapshot: async () => {},
    onError: async () => {},
    setTimer: () => 1,
    clearTimer: () => {},
  });

  assert.equal(poller.start(), true);
  assert.equal(poller.start(), false);
  const first = poller.pollOnce();
  const overlapping = await poller.pollOnce();
  assert.deepEqual(overlapping, { polled: false, reason: "in-flight" });
  assert.equal(fetchCount, 1);
  releaseFetch();
  assert.deepEqual(await first, { polled: true, ok: true });
  poller.stop();
});

test("runtime poller default timers can start and stop without losing their host binding", async () => {
  let calls = 0;
  const poller = new RuntimeVehicleSnapshotPoller({
    fetchSnapshot: async () => snapshot(100 + calls, []),
    onSnapshot: async () => {
      calls += 1;
    },
    onError: async () => {},
    intervalMs: 50,
  });

  poller.start();
  await new Promise((resolve) => setTimeout(resolve, 10));
  poller.stop();
  assert.equal(calls, 1);
});

test("stop and immediate restart cannot leave two polling schedules", async () => {
  const scheduled = [];
  let releaseFirst;
  let fetchCount = 0;
  const firstFetch = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  const poller = new RuntimeVehicleSnapshotPoller({
    fetchSnapshot: async () => {
      fetchCount += 1;
      if (fetchCount === 1) {
        await firstFetch;
      }
      return snapshot(100 + fetchCount, []);
    },
    onSnapshot: async () => {},
    onError: async () => {},
    setTimer: (callback) => {
      scheduled.push(callback);
      return scheduled.length;
    },
    clearTimer: () => {},
  });

  poller.start();
  const oldTick = scheduled[0]();
  poller.stop();
  poller.start();
  releaseFirst();
  await oldTick;
  assert.equal(scheduled.length, 2);

  await scheduled[1]();
  assert.equal(scheduled.length, 3);
  poller.stop();
});

test("three Runtime vehicles update Cesium positions and TAKEOFF height", () => {
  const state = new VehicleSnapshotState();
  const nedVehicle = (id, northM, eastM, altitudeM, armed = false) => ({
    id,
    display_name: id,
    vehicle_type: "multirotor",
    connected: true,
    pose: {
      frame: "NED",
      position_m: { x: northM, y: eastM, z: -altitudeM },
      attitude_deg: { roll: 0, pitch: 0, yaw: 0 },
    },
    telemetry: { armed, mode: armed ? "AUTO.TAKEOFF" : "AUTO.LAND" },
  });

  state.ingest(snapshot(100, [
    nedVehicle("UAV-01", 1, 10, 0),
    nedVehicle("UAV-02", 2, 20, 0),
    nedVehicle("UAV-03", 3, 30, 0),
  ]));
  state.ingest(snapshot(200, [
    nedVehicle("UAV-01", 1.5, 11, 0),
    nedVehicle("UAV-02", 2.5, 21, 4.2, true),
    nedVehicle("UAV-03", 3.5, 31, 0),
  ]));

  assert.deepEqual([...state.vehicles.keys()], ["UAV-01", "UAV-02", "UAV-03"]);
  assert.deepEqual(
    ["UAV-01", "UAV-02", "UAV-03"].map((id) => state.getVehicle(id).position.eastM),
    [11, 21, 31]
  );
  assert.equal(state.getVehicle("UAV-02").position.sourceFrame, "NED");
  assert.equal(state.getVehicle("UAV-02").position.upM, 4.2);
  assert.equal(state.getVehicle("UAV-02").telemetry.armed, true);
});
