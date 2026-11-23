import test from "node:test";
import assert from "node:assert/strict";
import { Cartesian3, EntityCollection, PolylineDashMaterialProperty } from "cesium";
import { createParentMessageHandler } from "../src/parent-bridge.js";
import { PlanPreviewLayer } from "../src/plan-preview-layer.js";
import { QINGLAN_SCENE, RECON_SCENE } from "../src/scene-alignment.js";
import { planPreview } from "./fixtures/plan-preview.js";

const now = 1000;
const expires = now + 60_000;
const origin = "http://127.0.0.1:5178";
function setup({ enabled = true, topLevel = false } = {}) {
  const entities = new EntityCollection();
  const layer = new PlanPreviewLayer(entities, (east, north, up) => new Cartesian3(east, north, up));
  layer.setScene(RECON_SCENE);
  const measured = entities.add({ properties: { semantic: "telemetry_trail" }, position: new Cartesian3(9, 3, 2) });
  const parentWindow = {};
  const handle = createParentMessageHandler({
    parentWindow, selfWindow: topLevel ? parentWindow : {}, allowedOrigins: new Set([origin, "http://localhost:5178"]),
    expectedOrigin: origin, onSnapshot: () => assert.fail("preview is not telemetry"),
    onMode: () => assert.fail("preview is not a mode switch"),
    onError: error => { throw error; },
    onPlanPreview: enabled ? payload => layer.apply(payload, now) : undefined,
  });
  const post = (payload, overrides) => handle({
    source: parentWindow, origin, data: { type: "uav-swarm/plan-preview", payload }, ...overrides,
  });
  const previewEntities = () => entities.values.filter(entity => entity.properties.semantic.getValue() === "plan_preview");
  return { layer, post, entities, previewEntities, measured };
}

test("plan preview uses a dashed line with ordered NED waypoints; turnback points retain their step IDs", () => {
  const { post, layer, previewEntities } = setup();
  assert.equal(post(planPreview(expires)), true);
  assert.deepEqual(layer.summary, { planId: "fake-target-001-patrol-v1", expiresAtMs: expires, waypointCount: 5 });
  const [line, ...points] = previewEntities();
  assert.ok(line.polyline.material instanceof PolylineDashMaterialProperty);
  const dashBits = line.polyline.material.dashPattern.getValue().toString(2).padStart(16, "0");
  assert.match(dashBits, /0+1+0+/);
  assert.equal(dashBits, [...dashBits].reverse().join(""));
  assert.deepEqual(line.polyline.positions.getValue().map(p => [p.x, p.y, p.z]),
    [[25, 0, 6], [25, 30, 6], [15, 30, 6], [25, 30, 6], [25, 0, 6]]);
  assert.deepEqual(points.map(p => p.properties.step_id.getValue()), ["goto-0", "goto-1", "goto-2", "goto-3", "goto-4"]);
  assert.ok(points.every(p => p.properties.node_id.getValue() === "UAV-02"));
});

test("waypoints for a different vehicle are not joined to the first vehicle's line", () => {
  const { post, previewEntities } = setup();
  const preview = planPreview(expires);
  preview.waypoints.splice(1, 0, { ...preview.waypoints[0], step_id: "second-node", node_id: "UAV-01" });
  assert.equal(post(preview), true);
  assert.equal(previewEntities().filter(p => p.polyline).length, 1);
  assert.equal(previewEntities().find(p => p.polyline).polyline.positions.getValue().length, 5);
  assert.equal(previewEntities().filter(p => p.properties.node_id.getValue() === "UAV-01").length, 1);
});

test("only the opted-in current frame accepts the actual parent at the expected origin", () => {
  const { post, layer } = setup();
  assert.equal(post(planPreview(expires), { source: {} }), false);
  assert.equal(post(planPreview(expires), { origin: "http://untrusted.invalid" }), false);
  assert.equal(post(planPreview(expires), { origin: "http://localhost:5178" }), false);
  assert.equal(layer.summary, null);
  assert.equal(post(planPreview(expires)), true);
  assert.equal(post(null, { source: {} }), false);
  assert.equal(layer.summary.waypointCount, 5);
  assert.equal(setup({ enabled: false }).post(planPreview(expires)), false);
  assert.equal(setup({ topLevel: true }).post(planPreview(expires)), false);
});

test("null and rejected plans clear only the preview and never fall back to the old plan", () => {
  for (const change of [
    { version: "2.0" }, { scene_id: "foreign" }, { map_version: "foreign" },
    { frame: "vehicle_local_ned" }, { expires_at_ms: now }, { expires_at_ms: String(expires) },
    { waypoints: [] }, { waypoints: [null] },
    { waypoints: [planPreview(expires).waypoints[0], planPreview(expires).waypoints[0]] },
    { waypoints: [{ ...planPreview(expires).waypoints[0], east_m: Number.NaN }] },
    null,
  ]) {
    const { post, layer, entities, measured } = setup();
    assert.equal(post(planPreview(expires)), true);
    assert.equal(post(change === null ? null : { ...planPreview(expires), ...change }), change === null);
    assert.equal(layer.summary, null);
    assert.deepEqual(entities.values, [measured]);
  }
});

test("expiry and scene transition remove the overlay without changing the telemetry entity", () => {
  const { post, layer, entities, measured } = setup();
  post(planPreview(expires));
  layer.expire(expires - 1);
  assert.equal(layer.summary.expiresAtMs, expires);
  layer.expire(expires);
  assert.deepEqual(entities.values, [measured]);
  assert.equal(layer.apply(planPreview(expires), expires), false);

  post(planPreview(expires));
  layer.setScene(QINGLAN_SCENE);
  assert.deepEqual(entities.values, [measured]);
  assert.equal(post(planPreview(expires)), false);
  layer.setScene(RECON_SCENE);
  assert.equal(layer.summary, null);
});
