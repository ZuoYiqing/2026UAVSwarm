const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../console-model.js");

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
  assert.equal(api.smokeTakeoffTimeoutMs({ auto_land: true }), 70_000);
  assert.equal(api.landTimeoutMs({ command_timeout_ms: 10_000 }), 15_000);
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
