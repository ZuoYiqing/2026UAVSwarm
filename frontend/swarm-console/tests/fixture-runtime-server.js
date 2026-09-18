const http = require("node:http");

const port = Number(process.env.FIXTURE_RUNTIME_PORT || 8876);
const actions = [];
const captures = [];
let testScenario = "normal";
const altitudes = new Map();

const registry = [1, 2, 3].map((systemId) => ({
  node_id: `UAV-0${systemId}`,
  backend: "px4_sitl",
  backend_mode: "sitl",
  endpoint: `udpin:127.0.0.1:${14539 + systemId}`,
  system_id: systemId,
  component_id: 1,
  enabled: true,
  connected: true,
  stale: false,
}));

function write(response, status, payload) {
  response.writeHead(status, {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json",
  });
  response.end(JSON.stringify(payload));
}

function telemetryNodes() {
  return registry.map((vehicle, index) => ({
    node_id: vehicle.node_id,
    system_id: vehicle.system_id,
    component_id: vehicle.component_id,
    connected: testScenario !== "stale",
    stale: testScenario === "stale",
    armed: (altitudes.get(vehicle.node_id) || 0) > 0,
    flight_mode: (altitudes.get(vehicle.node_id) || 0) > 0 ? "AUTO.LOITER" : "STANDBY",
    age_ms: 35 + index,
    last_seen: "2026-09-06T10:00:03Z",
    local_position: { altitude_m: altitudes.get(vehicle.node_id) || 0, z_down_m: -(altitudes.get(vehicle.node_id) || 0) },
    battery: { percent: 80 - index * 5 },
  }));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {});
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

const server = http.createServer(async (request, response) => {
  if (request.method === "OPTIONS") return write(response, 204, {});
  const url = new URL(request.url, `http://127.0.0.1:${port}`);
  const path = url.pathname;
  if (path === "/api/test/scenario" && request.method === "POST") {
    testScenario = (await readBody(request)).scenario || "normal";
    return write(response, 200, { scenario: testScenario });
  }
  if (path === "/api/test/complete" && request.method === "POST") {
    const body = await readBody(request);
    const action = actions.find((item) => item.node_id === body.node_id && item.status === "executing");
    if (!action) return write(response, 404, { error: "no_test_action" });
    action.status = body.status || "succeeded";
    action.completion_evidence = { completion_reached: action.status === "succeeded",
      status: action.status, telemetry_state: "fresh", target_altitude_m: action.altitude_m,
      stable_duration_ms: 1000, last_sample_timestamp: new Date().toISOString(),
      ...(action.action_type === "land" ? { armed: false, landed_state_name: "on_ground" } : {}) };
    if (action.status === "succeeded") altitudes.set(action.node_id, action.action_type === "land" ? 0 : action.altitude_m || 3);
    return write(response, 200, action);
  }
  if (path === "/api/health") return write(response, 200, { status: "ok", service: "fixture_runtime", version: "test" });
  if (path === "/api/vehicles") return write(response, 200, { source: "fixture", vehicles: registry });
  if (path === "/api/telemetry/latest") return write(response, 200, { status: "ok", backend: "px4_sitl", backend_mode: "sitl", nodes: telemetryNodes() });
  if (path === "/api/vehicle-snapshot") return write(response, 200, {
    version: "1.0", frame: "NED",
    timestamp: "2026-09-06T10:00:03Z",
    scene_id: "simple_recon_v0_1",
    map_version: "simple_recon_v0_1-map-1",
    source: { id: "fixture_runtime", kind: "simulation", label: "FIXTURE ONLY" },
    vehicles: telemetryNodes().map((node) => ({
      id: node.node_id,
      connected: node.connected,
      pose: { frame: "NED", position_m: { x: 0, y: 0, z: node.local_position.z_down_m } },
      telemetry: { armed: node.armed, mode: node.flight_mode, stale: node.stale, age_ms: node.age_ms },
    })),
  });
  if (path === "/api/snapshot") return write(response, 200, { active_actions: actions.filter((item) => item.status === "executing"), backend_statuses: [] });
  if (path === "/api/agent/status") return write(response, 200, { active_plans: [], planner_version: "fixture", planner_kind: "test" });
  if (path === "/api/simulation/status") return write(response, 200, { status: "ready", scene_id: "simple_recon_v0_1", map_version: "simple_recon_v0_1-map-1" });
  if (path === "/api/skills") return write(response, 200, { skills: [] });
  if (["/api/policy/decisions", "/api/actions/recent", "/api/events"].includes(path)) return write(response, 200, []);
  if (path === "/api/actions/lifecycle") return testScenario === "old"
    ? write(response, 404, {error:"not_found"}) : write(response, 200, actions);
  if (path === "/api/test/captures") return write(response, 200, captures);
  if (path.startsWith("/api/actions/") && request.method === "GET") {
    const action = actions.find((item) => item.action_id === decodeURIComponent(path.split("/").pop()));
    return action ? write(response, 200, action) : write(response, 404, { error: "action_not_found" });
  }
  if (["/api/actions/takeoff", "/api/actions/land", "/api/actions/smoke-takeoff"].includes(path) && request.method === "POST") {
    const body = await readBody(request);
    captures.push({ path, body });
    const replay = actions.find((item) => item.idempotency_key === body.idempotency_key);
    if (replay) return write(response, 202, {...replay, idempotent_replay:true});
    if (testScenario === "busy") return write(response, 409, {error:"node_busy"});
    const actionType = path.endsWith("land") ? "land" : "takeoff";
    const action = {
      contract_version: "1.1",
      action_id: `act-${body.node_id}-${actions.length + 1}`,
      request_id: body.request_id,
      trace_id: body.trace_id,
      idempotency_key: body.idempotency_key,
      node_id: body.node_id,
      system_id: body.system_id,
      component_id: body.component_id,
      action_type: actionType,
      altitude_m: body.altitude_m,
      status: testScenario === "policy" ? "policy_rejected" : "executing",
      policy_decision: { decision_code: testScenario === "policy" ? "deny" : "allow" },
      ack_evidence: [{ stage: actionType, result: 0, result_name: "MAV_RESULT_ACCEPTED", timestamp: "2026-09-06T10:00:04Z" }],
      completion_evidence: { status: "pending", completion_reached: false },
      timestamps: { requested_at: new Date().toISOString() },
    };
    if (testScenario === "policy") action.ack_evidence = [];
    actions.unshift(action);
    return write(response, 202, action);
  }
  if (path === "/api/backend/check" && request.method === "POST") {
    const body = await readBody(request);
    captures.push({ path, body });
    return write(response, 200, { resolved_node_id: body.node_id, readiness: "ready", connect_probe: { code: "backend_connected" } });
  }
  return write(response, 404, { error: "not_found", path });
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`Fixture Runtime listening on http://127.0.0.1:${port}/api\n`);
});
