const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../console-model.js");

test("action evidence never carries altitude across actions on the same node", () => {
  const first = model.normalizeActionRecord({ node_id: "UAV-02", action_id: "a", status: "succeeded",
    result: { max_altitude_m: 8, last_z: -8, threshold_reached: true } });
  const next = model.normalizeActionRecord({ node_id: "UAV-02", action_id: "b", status: "executing" });
  assert.equal(model.actionTelemetry(first).maxAltitudeAction, 8);
  assert.deepEqual(model.actionTelemetry(next), { maxAltitudeAction: null, lastZ: null, thresholdReached: null });
});

test("polling preserves request metadata and cannot regress terminal state", () => {
  const first = model.normalizeActionRecord({ node_id: "UAV-02", action_id: "a", status: "executing", smoke: true }, { altitude_m: 8 });
  const terminal = model.mergeActionRecords([first], [{ node_id: "UAV-02", action_id: "a", status: "succeeded" }]);
  assert.equal(terminal[0].request_parameters.altitude_m, 8);
  assert.equal(terminal[0].smoke, true);
  const delayed = model.mergeActionRecords(terminal, [{ node_id: "UAV-02", action_id: "a", status: "executing" }]);
  assert.equal(delayed[0].status, "succeeded");
});

test("shared trace cannot associate another action and negative ACK is not accepted", () => {
  assert.equal(model.eventMatchesAction({ node_id: "UAV-02", action_id: "other", trace_id: "trace" },
    { node_id: "UAV-02", action_id: "a", trace_id: "trace" }), false);
  assert.equal(model.ackAccepted({ result_name: "NOT_ACCEPTED" }), false);
});

function loadRuntimeApi() {
  const previousWindow = global.window;
  const storage = new Map();
  global.window = {
    setTimeout,
    clearTimeout,
    localStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    },
  };
  global.localStorage = global.window.localStorage;
  delete require.cache[require.resolve("../runtime-api.js")];
  require("../runtime-api.js");
  const api = global.window.SwarmRuntimeApi;
  global.window = previousWindow;
  delete global.localStorage;
  return api;
}

const registry = {
  vehicles: [
    {
      node_id: "UAV-01",
      backend: "px4_sitl",
      backend_mode: "sitl",
      endpoint: "udpin:127.0.0.1:14540",
      system_id: 1,
      component_id: 1,
      enabled: true,
      connected: true,
      stale: false,
    },
    {
      node_id: "UAV-02",
      backend: "px4_sitl",
      backend_mode: "sitl",
      endpoint: "udpin:127.0.0.1:14541",
      system_id: 2,
      component_id: 1,
      enabled: true,
      connected: false,
      stale: true,
    },
  ],
};

test("mergeFleet keeps offline registry nodes and overlays telemetry", () => {
  const fleet = model.mergeFleet(
    registry,
    {
      backend: "mixed",
      nodes: [{
        node_id: "UAV-01",
        connected: true,
        stale: false,
        flight_mode: "AUTO.LOITER",
        local_position: { altitude_m: 2.5, z_down_m: -2.5 },
        battery: { percent: 78 },
      }],
    },
    { vehicles: [] }
  );

  assert.equal(fleet.length, 2);
  assert.equal(fleet[0].flightMode, "AUTO.LOITER");
  assert.equal(fleet[0].altitudeM, 2.5);
  assert.equal(fleet[1].connected, false);
});

test("buildRuntimeRequest routes to the selected identity", () => {
  const vehicle = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[0];
  vehicle.connected = true;
  vehicle.stale = false;
  const request = model.buildRuntimeRequest(vehicle, 12.34);

  assert.equal(request.node_id, "UAV-01");
  assert.equal(request.system_id, 1);
  assert.equal(request.component_id, 1);
  assert.equal(request.transport_endpoint, "udpin:127.0.0.1:14540");
  assert.equal(request.altitude_m, 12.3);
});

test("actions are blocked for offline or identity-less vehicles", () => {
  const offline = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[1];
  assert.equal(model.canExecute(offline, "live").allowed, false);
  assert.throws(() => model.buildRuntimeRequest(offline, 3), /离线或已过期/);

  const missingIdentity = { ...offline, connected: true, stale: false, systemId: null };
  assert.match(model.canExecute(missingIdentity, "live").reason, /identity/);
});

test("API offline blocks an otherwise ready vehicle", () => {
  const vehicle = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[0];
  vehicle.connected = true;
  vehicle.stale = false;
  assert.equal(model.canExecute(vehicle, "offline").allowed, false);
});

test("backend probe request may target an offline registered vehicle", () => {
  const vehicle = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[1];
  const request = model.buildRuntimeRequest(vehicle, 3, { requireConnected: false });
  assert.equal(request.node_id, "UAV-02");
  assert.equal(request.transport_endpoint, "udpin:127.0.0.1:14541");
});

test("three discovered identities route actions independently", () => {
  const threeRegistry = {
    vehicles: [1, 2, 3].map((systemId) => ({
      node_id: `UAV-0${systemId}`,
      backend: "px4_sitl",
      backend_mode: "sitl",
      endpoint: `udp:${systemId}`,
      system_id: systemId,
      component_id: 1,
      enabled: true,
      connected: true,
      stale: false,
    })),
  };
  const fleet = model.mergeFleet(threeRegistry, { nodes: [] }, { vehicles: [] });

  assert.deepEqual(fleet.map((vehicle) => vehicle.id), ["UAV-01", "UAV-02", "UAV-03"]);
  assert.deepEqual(
    fleet.map((vehicle) => model.buildRuntimeRequest(vehicle, 3)),
    [1, 2, 3].map((systemId) => ({
      backend: "px4_sitl",
      backend_mode: "sitl",
      backend_enabled: true,
      node_id: `UAV-0${systemId}`,
      system_id: systemId,
      component_id: 1,
      transport_endpoint: `udp:${systemId}`,
      altitude_m: 3,
      connect_timeout_ms: 5000,
      command_timeout_ms: 10000,
      observe_timeout_ms: 25000,
      threshold_ratio: 0.7,
      auto_land: false,
    }))
  );
  assert.equal(model.isFleetReady(fleet), true);

  fleet[1].connected = false;
  fleet[1].stale = true;
  assert.equal(model.isFleetReady(fleet), false);
  assert.equal(model.canExecute(fleet[0], "live").allowed, true);
  assert.equal(model.canExecute(fleet[1], "live").allowed, false);
});

test("flight action timeouts cover backend command and observation windows", () => {
  const api = loadRuntimeApi();
  assert.equal(
    api.smokeTakeoffTimeoutMs({
      command_timeout_ms: 10_000,
      observe_timeout_ms: 25_000,
      auto_land: false,
    }),
    60_000
  );
  assert.equal(api.takeoffTimeoutMs({ command_timeout_ms: 10_000, observe_timeout_ms: 25_000 }), 60_000);
  assert.equal(api.smokeTakeoffTimeoutMs({ auto_land: true }), 70_000);
  assert.equal(api.landTimeoutMs({ command_timeout_ms: 10_000, observe_timeout_ms: 25_000 }), 40_000);
});

test("critical state failure marks console and Cesium snapshots stale", () => {
  const fleet = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] });
  fleet[0].connected = true;
  fleet[0].stale = false;
  const staleFleet = model.markFleetStale(fleet);
  const staleSnapshot = model.markVehicleSnapshotStale({
    vehicles: [{ id: "UAV-01", connected: true, telemetry: { stale: false } }],
  });

  assert.equal(staleFleet[0].connected, false);
  assert.equal(staleFleet[0].stale, true);
  assert.equal(staleSnapshot.vehicles[0].connected, false);
  assert.equal(staleSnapshot.vehicles[0].telemetry.stale, true);
});

test("operational requests carry stable identity and omit smoke semantics", () => {
  const vehicle = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[0];
  vehicle.connected = true;
  vehicle.stale = false;
  const identifiers = {
    request_id: "req-uav01-1",
    trace_id: "trace-uav01-1",
    idempotency_key: "idem-uav01-1",
  };
  const takeoff = model.buildOperationalActionRequest(vehicle, "takeoff", 8, identifiers);
  const land = model.buildOperationalActionRequest(vehicle, "land", 8, identifiers);

  assert.equal(takeoff.node_id, "UAV-01");
  assert.equal(takeoff.altitude_m, 8);
  assert.equal(takeoff.altitude_tolerance_m, 0.3);
  assert.equal(takeoff.stable_duration_ms, 1000);
  assert.equal(takeoff.command_source, "ground_station");
  assert.equal("auto_land" in takeoff, false);
  assert.equal("threshold_ratio" in takeoff, false);
  assert.equal("altitude_m" in land, false);
});

test("lifecycle records remain bound to their original nodes while selection changes", () => {
  const records = model.mergeActionRecords([], [
    {
      action_id: "act-uav02",
      request_id: "req-uav02",
      trace_id: "trace-uav02",
      node_id: "UAV-02",
      action_type: "takeoff",
      status: "executing",
      timestamps: { requested_at: "2026-09-06T10:00:01Z" },
    },
    {
      action_id: "act-uav03",
      request_id: "req-uav03",
      node_id: "UAV-03",
      action_type: "land",
      status: "succeeded",
      timestamps: { requested_at: "2026-09-06T10:00:02Z" },
    },
  ]);

  assert.equal(model.latestActionForNode(records, "UAV-02").action_id, "act-uav02");
  assert.equal(model.latestActionForNode(records, "UAV-03").action_id, "act-uav03");
});

test("duplicate takeoff is blocked but LAND may request Runtime preemption", () => {
  const vehicle = model.mergeFleet(registry, { nodes: [] }, { vehicles: [] })[0];
  vehicle.connected = true;
  vehicle.stale = false;
  const active = [{ node_id: "UAV-01", action_type: "takeoff", status: "executing" }];

  assert.equal(model.actionPermission(vehicle, "live", active, "takeoff").allowed, false);
  assert.equal(model.actionPermission(vehicle, "live", active, "land").allowed, true);
  assert.match(model.actionPermission(vehicle, "live", active, "land").reason, /LAND/);
  assert.equal(
    model.actionPermission(vehicle, "live", [{ ...active[0], action_type: "land" }], "land").allowed,
    false
  );
});

test("accepted MAVLink ACK is not telemetry-confirmed completion", () => {
  const action = model.normalizeActionRecord({
    action_id: "act-1",
    request_id: "req-1",
    node_id: "UAV-02",
    action_type: "takeoff",
    status: "executing",
    policy_decision: { decision_code: "allow" },
    ack_evidence: [{ stage: "takeoff", result: 0, result_name: "MAV_RESULT_ACCEPTED" }],
    completion_evidence: { completion_reached: false },
  });
  const stages = Object.fromEntries(model.actionStages(action).map((stage) => [stage.key, stage]));

  assert.equal(stages.ack.tone, "done");
  assert.equal(stages.completion.tone, "active");
  assert.match(stages.completion.label, /待遥测确认/);
  assert.equal(model.isTerminalAction(action), false);
});

test("policy rejection, timeout and old records remain explicit", () => {
  const rejected = model.normalizeActionRecord({
    node_id: "UAV-01",
    action: "takeoff",
    lifecycle_status: "policy_rejected",
    policy_decision: { decision_code: "deny" },
    failure_reason: "policy_deny",
  });
  const old = model.normalizeActionRecord({ node_id: "UAV-01", action: "land", result: "pass" });
  const succeeded = model.normalizeActionRecord({
    node_id: "UAV-01",
    action: "land",
    status: "succeeded",
    code: "px4_sitl_action_pass",
  });

  assert.equal(rejected.status, "policy_rejected");
  assert.equal(model.actionStages(rejected)[1].tone, "failed");
  assert.equal(model.isTerminalAction(rejected), true);
  assert.equal(old.status, "unknown");
  assert.equal(model.isTerminalAction(old), false);
  assert.equal(succeeded.failure_reason, null);
});

test("busy errors and action events retain correlation identifiers", () => {
  const busy = model.normalizeActionRecord({
    node_id: "UAV-02",
    action: "takeoff",
    status: "failed",
    failure_reason: "node_busy",
    request_id: "req-2",
    trace_id: "trace-2",
  });
  assert.equal(busy.failure_reason, "node_busy");
  assert.equal(model.eventMatchesAction({ payload: { trace_id: "trace-2" } }, busy), true);
  assert.equal(model.eventMatchesAction({ node_id: "UAV-03", action_type: "takeoff" }, busy), false);
});

test("vehicle snapshot bridge preserves sample time and declares one contract", () => {
  const snapshot = {
    timestamp: "2026-09-06T10:00:00Z",
    vehicles: [{
      id: "UAV-02",
      spatial: {
        scene_id: "simple_recon_v0_1",
        map_version: "map-1",
        sample_timestamp: "2026-09-06T09:59:59Z",
      },
    }],
  };
  const message = model.createVehicleSnapshotMessage(snapshot);

  assert.equal(message.version, "1.0");
  assert.equal(message.scene_id, "simple_recon_v0_1");
  assert.equal(message.source_timestamp, snapshot.timestamp);
  assert.equal(message.payload, snapshot);
  assert.equal(model.validateSimulationReadyMessage({
    type: "uav-swarm/simulation-ready",
    payload: { contractVersion: "1.0", integration: "parent-snapshot" },
  }), true);
  assert.equal(model.validateSimulationReadyMessage({
    type: "uav-swarm/simulation-ready",
    payload: { contractVersion: "2.0", integration: "parent-snapshot" },
  }), false);
});
