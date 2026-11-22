import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Cartesian3, EntityCollection } from "cesium";
import dashboard from "../../mission-dashboard.js";
import { RECON_SCENE } from "../src/scene-alignment.js";
import { VehicleLayer } from "../src/vehicle-layer.js";
import { VehicleSnapshotState } from "../src/vehicle-snapshot-state.js";
import { publicSnapshot } from "./fixtures/public-snapshot.js";

const json = path => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const { context, proposal } = json("./fixtures/equipment-inspection-observer.json");
const { mission_progress_unavailable: noRun } = json("../../../../docs/fixtures/runtime_demo_readiness_v1.json");
const { coverage } = json("../../tests/fixtures/coverage_grid_s7_v1.json");
const epoch = Date.parse("2026-11-22T00:00:00Z");
const subject = proposal.assignments[0].node_id;
const routeNed = proposal.assignments[0].waypoint_ids.map(id => {
  const { north_m, east_m, down_m } = context.waypoints.find(w => w.waypoint_id === id).position_m;
  return [north_m, east_m, down_m];
});

// Stub icon painting only. Entities, their position/polyline properties and the LIVE consumer are real.
const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
before(() => {
  const ctx = Object.fromEntries("translate beginPath moveTo lineTo stroke arc fill fillRect closePath".split(" ").map(k => [k, () => {}]));
  globalThis.document = { createElement(tag) {
    assert.equal(tag, "canvas");
    return { getContext: () => ctx, toDataURL: () => "data:image/png;base64," };
  } };
});
after(() => {
  if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
  else delete globalThis.document;
});

function observer(t) {
  let now = epoch;
  t.mock.method(Date, "now", () => now);
  const state = new VehicleSnapshotState({ scene: RECON_SCENE });
  state.activateLive("parent");
  const entities = new EntityCollection();
  // Keep coordinates in ENU metres to inspect the points before the common Cesium world transform.
  const layer = new VehicleLayer({ entities }, p => new Cartesian3(p.eastM, p.northM, p.upM));
  function frame(offset, ned, mutate = () => {}) {
    now = epoch + offset;
    const raw = publicSnapshot({ time: now, positions: [[0, 0, 0], ned, [0, -8, 0]] });
    mutate(raw, raw.vehicles[1]);
    const result = state.ingest(raw, { transport: "parent" });
    assert.equal(result.accepted, true);
    layer.applySnapshot(result.snapshot);
    return raw;
  }
  const xyz = p => p && [p.x, p.y, p.z === 0 ? 0 : p.z];
  const marker = () => entities.getById("vehicle:" + subject);
  function trail(id = subject) {
    const line = entities.getById("vehicle-route:" + id);
    assert.equal(line.properties.semantic.getValue(), "telemetry_trail");
    return line.polyline.positions.getValue().map(xyz);
  }
  return { entities, state, frame, marker, trail, position: () => xyz(marker().position?.getValue()) };
}

test("proposed geometry is not a full vehicle snapshot or a Runtime execution", t => {
  const view = observer(t);
  for (const payload of [context, proposal]) {
    assert.equal(payload.scene_id, RECON_SCENE.scene_id);
    assert.equal(payload.map_version, RECON_SCENE.map_version);
    assert.equal(payload.coordinate_frame, "scene_ned");
    assert.throws(() => view.state.ingest(payload, { transport: "parent" }));
  }
  assert.equal(proposal.execution_authorized, false);
  assert.equal(view.state.lastSnapshot, null);
  assert.equal(view.entities.values.length, 0);
  assert.equal(noRun.reason, "no_runtime_plan_execution");
  assert.equal(dashboard.missionProgress(noRun), null);
  assert.equal(dashboard.missionMap(null, null), null);
});

test("only public samples reach the measured polyline: A, stale waypoint B, fresh off-route C", t => {
  const view = observer(t);
  view.frame(0, [0, 8, 0]);
  view.frame(1000, routeNed[0], (_, v) => { v.telemetry.stale = true; });
  assert.deepEqual(view.position(), [8, 0, 0]);
  assert.deepEqual(view.trail(), [[8, 0, 0]]);
  assert.match(view.marker().label.text.getValue(), /STALE/);
  view.frame(2000, [3, 9, -2]);
  assert.deepEqual(view.position(), [9, 3, 2]);
  assert.deepEqual(view.trail(), [[8, 0, 0], [9, 3, 2]]);
  assert.deepEqual(view.trail("UAV-01"), [[0, 0, 0]]);
  assert.deepEqual(view.trail("UAV-03"), [[-8, 0, 0]]);
  assert.equal(view.marker().label.text.getValue(), subject);
});

test("plan and prediction extras cannot substitute for missing public pose", t => {
  const view = observer(t);
  view.frame(0, [0, 8, 0], (raw, v) => {
    // Deliberately untrusted extras; not a plan transport or a schema extension.
    raw.planned_route = routeNed.map(([x, y, z]) => ({ x, y, z }));
    v.predicted_position = raw.planned_route[0];
    delete v.spatial.scene_pose.position_m;
  });
  assert.equal(view.state.getVehicle(subject).positionUsable, false);
  assert.equal(view.marker().show, false);
  assert.deepEqual(view.trail(), []);
});

for (const [problem, mutate] of [
  ["scene", raw => { raw.scene_id = "unrelated-fixture-scene"; }],
  ["map version", (_, v) => { v.spatial.map_version = "unrelated-fixture-map"; }],
]) {
  test("wrong " + problem + " at a planned waypoint adds no measured point", t => {
    const view = observer(t);
    view.frame(0, routeNed[0], mutate);
    assert.equal(view.marker().show, false);
    assert.deepEqual(view.trail(), []);
    view.frame(1000, [0, 8, 0]);
    view.frame(2000, routeNed[1], mutate);
    assert.equal(view.state.getVehicle(subject).alignment.aligned, false);
    assert.deepEqual(view.position(), [8, 0, 0]);
    assert.deepEqual(view.trail(), [[8, 0, 0]]);
  });
}

test("fresh envelope and calibration do not refresh an expired position sample", t => {
  const view = observer(t);
  view.frame(0, [0, 8, 0]);
  view.frame(4000, routeNed[1], (_, v) => { v.spatial.sample_timestamp = new Date(epoch).toISOString(); });
  assert.equal(view.state.getVehicle(subject).telemetry.stale, true);
  assert.deepEqual(view.trail(), [[8, 0, 0]]);
  assert.deepEqual(view.position(), [8, 0, 0]);
});

test.todo("cold stale waypoint may seed a last-known marker, but not a flown segment on recovery", t => {
  const view = observer(t);
  view.frame(0, routeNed[0], (_, v) => { v.telemetry.stale = true; });
  assert.match(view.marker().label.text.getValue(), /STALE/);
  view.frame(1000, [3, 9, -2]);
  assert.deepEqual(view.trail(), [[9, 3, 2]]);
});

test("three visible nodes, even at both proposed waypoints, cannot fill missing progress or coverage", t => {
  const view = observer(t);
  view.frame(0, routeNed[0]);
  const raw = view.frame(1000, routeNed[1]);
  assert.equal(dashboard.fleetMap(raw).markers.length, 3);
  assert.deepEqual(view.trail(), [[18, 12, 5], [18, 20, 5]]);
  for (const missing of [null, noRun]) {
    const progress = dashboard.missionProgress(missing);
    assert.equal(progress, null);
    assert.equal(dashboard.missionMap(progress, raw), null);
  }
});

function progressStub() {
  return {
    ...noRun, mission_id: "fixture-plan", run_id: "fixture-run", status: "running", reason: null,
    scene_id: context.scene_id, map_version: context.map_version, source_timestamp: new Date(epoch).toISOString(),
    completion_basis: "verified_waypoints", waypoints_reached: 1, waypoints_total: 2, completion_pct: 50,
  };
}

test("stub progress counts and coverage have independent evidence; foreign grid is not painted", () => {
  const progress = progressStub();
  const withoutCoverage = dashboard.missionProgress(progress);
  assert.equal(withoutCoverage.completion, 50);
  assert.equal(withoutCoverage.coveragePercent, null);
  assert.equal(withoutCoverage.coverageGrid, null);
  assert.equal(dashboard.missionProgress({ ...progress, status: "stale" }), null);
  const withCoverage = { ...progress, coverage, area_covered_km2: coverage.area_covered_km2, area_total_km2: coverage.area_total_km2 };
  const model = dashboard.missionProgress(withCoverage);
  assert.equal(model.coveragePercent, coverage.area_covered_km2 / coverage.area_total_km2 * 100);
  assert.deepEqual(dashboard.missionMap(model, null).coverageGrid.cells, coverage.grid.covered_cells);
  const mismatched = dashboard.missionProgress({ ...withCoverage, map_version: "another-fixture-map" });
  assert.equal(dashboard.missionMap(mismatched, null).coverageGrid, null);
});

test.todo("a coverage report contradicting the mission map cannot certify the current area's KPI", () => {
  const mission = dashboard.missionProgress({
    ...progressStub(), map_version: "another-fixture-map",
    coverage, area_total_km2: coverage.area_total_km2, area_covered_km2: coverage.area_covered_km2,
  });
  assert.equal(mission.coverageGrid, null);
  assert.equal(mission.coveragePercent, null);
});
