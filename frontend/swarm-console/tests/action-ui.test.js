const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const model = require("../console-model.js");

function harness(saved = []) {
  const storage = new Map([["swarm-console.pending-actions.v1", JSON.stringify(saved)]]);
  const app = { innerHTML: "", addEventListener() {} };
  const listeners = {};
  const api = { getConfiguredBaseUrl: () => "http://127.0.0.1:8876/api",
    health: () => new Promise(() => {}) };
  const context = vm.createContext({
    console, URL, crypto: require("node:crypto").webcrypto,
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    document: { getElementById: (id) => id === "app" ? app : null,
      querySelector: () => null, activeElement: null },
    window: { SwarmRuntimeApi: api, SwarmConsoleModel: model,
      location: { href: "http://127.0.0.1:5178/" },
      setTimeout() {}, addEventListener: (name, handler) => { listeners[name] = handler; } },
    setInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app.js"), "utf8"), context);
  vm.runInContext(`
    syncRuntimeEvents = async () => {};
    syncRuntimeState = async () => {};
    state.apiStatus = "live";
    state.lifecycleSupported = true;
    state.fleet = [1,2,3].map(n => ({id: 'UAV-0'+n, nodeId:'UAV-0'+n,
      systemId:n, componentId:1, backend:'px4_sitl', backendMode:'sitl',
      endpoint:'udpin:127.0.0.1:'+ (14539+n), enabled:true, connected:true, stale:false}));
    state.selectedUav = 'UAV-02';
  `, context);
  return { api, context, app, storage, listeners, run: (code) => vm.runInContext(code, context) };
}

const pending = { node_id: "UAV-02", action_type: "takeoff", api_base_url: "http://127.0.0.1:8876/api",
  body: { node_id: "UAV-02", request_id: "req2", trace_id: "trace2", idempotency_key: "idem2" } };

test("Runtime busy terminal response releases only its own pending request", async () => {
  const h = harness([pending]);
  h.api.takeoff = async (body) => { throw Object.assign(new Error("node_busy"), {
    kind: "http", status: 409, payload: { ...body, action_id: "act2", status: "failed",
      failure_reason: "node_busy", details: { active_action_id: "other" } },
  }); };
  await h.run("executePendingAction(state.pendingActions[0])");
  assert.equal(h.run("state.pendingActions.length"), 0);
  assert.equal(h.run("selectedAction().failure_reason"), "node_busy");
  assert.equal(h.run("selectedAction().action_id"), "act2");
});

test("HTTP failure with a conflicting identity stays unknown without rejecting the task", async () => {
  const h = harness([pending]);
  h.api.takeoff = async () => { throw Object.assign(new Error("conflict"), {
    kind: "http", status: 409, payload: { node_id: "UAV-02", action_id: "other", request_id: "other-request" },
  }); };
  await h.run("executePendingAction(state.pendingActions[0])");
  assert.equal(h.run("state.pendingActions.length"), 1);
  assert.match(h.run("selectedAction().client_status"), /身份不匹配/);
});

test("parent validates the shared vehicle contract and forwards original samples only", async () => {
  const h = harness();
  const contract = await import("../simulation-3d/src/vehicle-contract.js");
  const sent = [];
  const frame = { contentWindow: { postMessage: (...args) => sent.push(args) } };
  h.context.document.getElementById = (id) => id === "simulation-frame" ? frame : h.app;
  h.context.sharedContract = contract;
  h.run(`vehicleContractModule = Promise.resolve(sharedContract); state.simulationReady = true;
    state.vehicleSnapshot = { version:'1.0', timestamp:'2026-09-06T10:00:03Z', full_state:true,
      frame:{type:'NED'}, source:{id:'fixture',kind:'simulation'}, vehicles:[
        {id:'UAV-02',pose:{position_m:{x:1,y:2,z:-3}}}] }`);
  await h.run("postVehicleSnapshot()");
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1], "http://127.0.0.1:5179");
  assert.equal(sent[0][0].payload, h.run("state.vehicleSnapshot"));
  assert.equal(sent[0][0].payload.vehicles[0].pose.position_m.z, -3);
  assert.equal(sent[0][0].payload.timestamp, "2026-09-06T10:00:03Z");
  h.run("state.vehicleSnapshot.version='9.0'");
  await h.run("postVehicleSnapshot()");
  assert.equal(sent.length, 1);
  assert.match(h.run("state.simulationContractError"), /未发送/);
});

test("empty action page renders with usable selectors", () => {
  const h = harness();
  const html = h.run("backendPage()");
  assert.match(html, /正式起飞/);
  assert.match(html, /待遥测确认/);
  assert.doesNotMatch(html, /undefined/);
});

test("double click posts once and response remains UAV-02 after selecting UAV-03", async () => {
  const h = harness();
  const bodies = [];
  let complete;
  h.api.takeoff = (body) => { bodies.push(body); return new Promise((resolve) => { complete = resolve; }); };
  h.run("runOperationalTakeoff(); runOperationalTakeoff(); selectVehicle('UAV-03')");
  assert.equal(bodies.length, 1);
  assert.equal(bodies[0].node_id, "UAV-02");
  assert.equal(bodies[0].transport_endpoint, "udpin:127.0.0.1:14541");
  complete({ ...bodies[0], action_id: "act2", action: "takeoff", status: "executing",
    ack_evidence: [{stage:"takeoff",result:0}], completion_evidence:{completion_reached:false} });
  await new Promise(setImmediate);
  assert.equal(h.run("selectedAction()"), null);
  h.run("selectVehicle('UAV-02')");
  assert.equal(h.run("selectedAction().action_id"), "act2");
  assert.match(h.run("backendPage()"), /待遥测确认/);
});

test("refresh without action ID only looks up lifecycle, never repeats POST", async () => {
  const h = harness([pending]);
  h.api.takeoff = () => { throw new Error("must not POST"); };
  await h.run("recoverPendingActions()");
  assert.equal(h.run("actionPermission('takeoff').allowed"), false);
  assert.equal(h.run("actionPermission('land').allowed"), true);
  assert.match(h.run("selectedAction().client_status"), /不会自动重发/);
});

test("Runtime restart preserves unknown outcome and blocks repeat takeoff", async () => {
  const h = harness([{ ...pending, action_id: "act2" }]);
  h.api.actionStatus = async () => { throw Object.assign(new Error("missing"), {status:404}); };
  await h.run("recoverPendingActions()");
  assert.match(h.run("selectedAction().client_status"), /可能已重启/);
  assert.equal(h.run("selectedAction().status"), "unknown");
  assert.equal(h.run("actionPermission('takeoff').allowed"), false);
});

test("refresh finds terminal record by request and releases pending UI lock", async () => {
  const h = harness([pending]);
  h.run(`state.lifecycleRecords = [{node_id:'UAV-02',request_id:'req2',action_id:'act2',
    action:'takeoff', status:'policy_rejected', policy_decision:{decision_code:'deny'}}]`);
  await h.run("recoverPendingActions()");
  assert.equal(h.run("state.pendingActions.length"), 0);
  assert.equal(h.run("selectedAction().status"), "policy_rejected");
});

test("LAND pending cannot be bypassed by another active takeoff", () => {
  const h = harness([{...pending, action_type:"land"}]);
  h.run("state.actionRecords = [{node_id:'UAV-02',action_type:'takeoff',status:'executing'}]");
  assert.equal(h.run("actionPermission('land').allowed"), false);
});

test("old lifecycle service disables operational dispatch", () => {
  const h = harness();
  let posts = 0;
  h.api.takeoff = () => { posts++; };
  h.run("state.lifecycleSupported=false; runOperationalTakeoff()");
  assert.equal(posts, 0);
  assert.match(h.run("backendPage()"), /正式动作接口暂不支持/);
});

test("stale node cannot send and identity mismatch is rejected", () => {
  const h = harness();
  h.run("state.fleet[1].stale=true");
  assert.equal(h.run("actionPermission('takeoff').allowed"), false);
  h.context.pendingFixture = pending;
  assert.throws(() => h.run("acceptActionResponse({node_id:'UAV-03',request_id:'req2',action_id:'act3'}, pendingFixture)"), /身份不匹配/);
});

test("bridge rejects wrong source window, origin and protocol", () => {
  const h = harness();
  const frameWindow = {};
  const frame = { contentWindow: frameWindow };
  h.context.document.getElementById = (id) => id === "simulation-frame" ? frame : h.app;
  const message = { type:"uav-swarm/simulation-ready",payload:{contractVersion:"1.0",integration:"parent-snapshot"} };
  h.listeners.message({source:{},origin:"http://127.0.0.1:5179",data:message});
  assert.equal(h.run("state.simulationReady"), false);
  h.listeners.message({source:frameWindow,origin:"https://wrong.example",data:message});
  assert.equal(h.run("state.simulationReady"), false);
  h.listeners.message({source:frameWindow,origin:"http://127.0.0.1:5179",data:{...message,payload:{contractVersion:"2.0"}}});
  assert.match(h.run("state.simulationContractError"), /不兼容/);
});
