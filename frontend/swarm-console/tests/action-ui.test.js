const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const model = require("../console-model.js");

function harness(saved = [], { polling = false } = {}) {
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
    ${polling ? "" : "syncRuntimeEvents = async () => {}; syncRuntimeState = async () => {};"}
    state.apiStatus = "live";
    state.dataStatus = "live";
    state.observationStale = false;
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

// 仅用于单元回归的现有 GET 契约，不连接 PX4，也不定义平台代理路由。
function installStateFixture(h) {
  const reads = [];
  const sampleTime = "2026-10-22T03:00:00Z";
  const payloads = {
    health: { status: "ok", service: "fixture_only" },
    snapshot: { active_actions: [] },
    telemetryLatest: { status: "ok", nodes: [{node_id:"UAV-02", connected:true,
      stale:false, last_seen:sampleTime, flight_mode:"AUTO.LOITER"}] },
    vehicleSnapshot: { version:"1.0", timestamp:sampleTime, frame:"NED", source:{id:"fixture_only",kind:"simulation"},
      vehicles:[{id:"UAV-02",connected:true,telemetry:{stale:false},pose:{position_m:{x:0,y:0,z:-3}}}] },
    vehicles: { vehicles:[{node_id:"UAV-02",enabled:true,connected:true,stale:false,
      system_id:2,component_id:1,endpoint:"udpin:127.0.0.1:14541"}] },
    agentStatus: { active_plans:[{plan_id:"fixture-plan"}] },
    simulationStatus: {}, skills: [], policyDecisions: [], recentActions: [],
    actionLifecycle: [], events: [],
  };
  for (const [name, payload] of Object.entries(payloads)) {
    h.api[name] = async () => { reads.push(name); return structuredClone(payload); };
  }
  return { reads, payloads, sampleTime };
}

test("HTTP loss preserves platform connectivity, task evidence and last trusted receive time", () => {
  const h = harness();
  h.run(`state.lastObservationAt='2026-10-22T03:00:01Z';
    state.actionRecords=[{node_id:'UAV-02',action_type:'takeoff',status:'executing'}];
    state.agentStatus={active_plans:[{plan_id:'fixture-plan',status:'executing'}]};
    state.vehicleSnapshot={vehicles:[{id:'UAV-02',connected:true,telemetry:{stale:false}}]};
    updateSelectedTelemetry()`);
  const snapshot = h.run("state.vehicleSnapshot");
  const records = h.run("state.actionRecords");
  h.run("applyApiFailure('snapshot', {kind:'network',message:'fixture link lost'}, false)");
  h.run("applyApiFailure('snapshot', {kind:'timeout',message:'fixture still lost'}, false)");
  assert.equal(h.run("state.apiStatus"), "offline");
  assert.equal(h.run("state.dataStatus"), "stale");
  assert.equal(h.run("selectedVehicle().connected"), true);
  assert.equal(h.run("selectedVehicle().stale"), false);
  assert.equal(h.run("selectedVehicle().observationStale"), true);
  assert.equal(h.run("selectedAction().status"), "executing");
  assert.equal(h.run("state.agentStatus.active_plans[0].status"), "executing");
  assert.equal(h.run("state.actionRecords"), records);
  assert.equal(h.run("state.vehicleSnapshot"), snapshot);
  assert.equal(h.run("state.lastObservationAt"), "2026-10-22T03:00:01Z");
  assert.match(h.run("observationNotice()"), /当前未知/);
  assert.match(h.run("backendPage()"), /connected \/ stale（平台最后上报）<\/dt><dd>true \/ false/);
  assert.match(h.run("vehicleTableRows()"), /STALE · 当前未知/);
  assert.doesNotMatch(h.run("topbar()"), /HEALTHY/);

  // 健康接口恢复不能把旧观测或动作结论冒充为已同步。
  h.run("applyApiSuccess('health', {status:'ok'})");
  assert.equal(h.run("state.apiStatus"), "live");
  assert.equal(h.run("state.observationStale"), true);
  assert.equal(h.run("actionPermission('takeoff').allowed"), false);
  assert.equal(h.run("actionPermission('land').allowed"), false);
  assert.equal(h.run("backendStatus().label"), "未知");
  assert.equal(h.run("state.lastObservationAt"), "2026-10-22T03:00:01Z");
});

test("partial GET recovery and HTTP 200 contract errors retain the last complete observation", async () => {
  const h = harness([], {polling:true});
  const fixture = installStateFixture(h);
  await h.run("syncRuntimeState()");
  const snapshot = h.run("state.vehicleSnapshot");
  const received = h.run("state.lastObservationAt");
  assert.equal(h.run("selectedVehicle().lastSeen"), fixture.sampleTime);
  assert.equal(h.run("state.observationStale"), false);

  h.api.telemetryLatest = async () => { throw Object.assign(new Error("fixture timeout"), {kind:"timeout"}); };
  fixture.payloads.vehicleSnapshot.vehicles[0].connected = false;
  await h.run("syncRuntimeState()");
  await h.run("syncRuntimeEvents()");
  assert.equal(h.run("state.apiStatus"), "live");
  assert.equal(h.run("state.observationStale"), true);
  assert.equal(h.run("selectedVehicle().connected"), true);
  assert.equal(h.run("state.vehicleSnapshot"), snapshot);
  assert.equal(h.run("state.lastObservationAt"), received);
  assert.equal(h.run("actionPermission('takeoff').allowed"), false);

  h.api.telemetryLatest = async () => ({status:"ok"}); // HTTP 200，契约仍不完整。
  await h.run("syncRuntimeState()");
  assert.equal(h.run("state.apiStatus"), "live");
  assert.equal(h.run("state.vehicleSnapshot"), snapshot);
  assert.equal(h.run("state.lastObservationAt"), received);
  assert.match(h.run("state.apiLastError"), /关键状态接口缺少/);
});

test("reconnect reconciles existing pending actions through GET only, never replays POST", async () => {
  const h = harness([{...pending,action_id:"fixture-action"}], {polling:true});
  const fixture = installStateFixture(h);
  const record = {...pending.body,action_type:"takeoff",action_id:"fixture-action",status:"executing"};
  fixture.payloads.actionLifecycle.push(record);
  const posts = [];
  for (const name of ["takeoff", "land", "smokeTakeoff", "planMission"]) {
    h.api[name] = async () => { posts.push(name); throw new Error("must not POST"); };
  }
  await h.run("syncRuntimeState()");
  assert.equal(h.run("state.pendingActions.length"), 1);
  h.run("applyApiFailure('snapshot', {kind:'network',message:'fixture lost'}, false)");
  fixture.payloads.actionLifecycle.length = 0;
  h.api.actionStatus = async (id) => {
    fixture.reads.push(`actionStatus:${id}`);
    return {...record,status:"succeeded",completion_evidence:{completion_reached:true}};
  };
  await h.run("probeRuntime()");
  await h.run("probeRuntime()");
  assert.equal(h.run("state.observationStale"), false);
  assert.equal(h.run("selectedVehicle().connected"), true);
  assert.equal(h.run("selectedVehicle().observationStale"), undefined);
  assert.equal(h.run("state.pendingActions.length"), 0);
  assert.equal(h.run("selectedAction().status"), "succeeded");
  assert.equal(fixture.reads.filter((name) => name.startsWith("actionStatus:")).length, 1);
  assert.deepEqual(posts, []);
});

test("cold start stays unknown and editing an input does not hide observation loss", () => {
  const h = harness();
  h.run("state.fleet=[]; state.lastObservationAt=null; state.vehicleSnapshot=null");
  h.run("applyApiFailure('health', {kind:'network',message:'fixture lost'}, false)");
  assert.equal(h.run("state.dataStatus"), "unavailable");
  assert.match(h.run("observationNotice()"), /接收：unknown/);
  const notice = {textContent:""};
  const topbar = {innerHTML:""};
  h.context.document.getElementById = (id) => ({app:h.app,"slot-topbar":topbar,"observation-notice":notice}[id] || null);
  h.context.document.activeElement = {matches:() => true};
  h.run("renderRuntimeUpdate()");
  assert.match(notice.textContent, /HTTP（浏览器→网关）：OFFLINE/);
  assert.match(topbar.innerHTML, /UNKNOWN/);
  assert.doesNotMatch(topbar.innerHTML, /HEALTHY/);
});

test("stale Cesium view preserves platform connectivity, sample time and original snapshot", async () => {
  const h = harness();
  h.context.sharedContract = await import("../simulation-3d/src/vehicle-contract.js");
  const sent = [];
  const frame = {contentWindow:{postMessage:(message) => sent.push(message)}};
  h.context.document.getElementById = (id) => id === "simulation-frame" ? frame : null;
  h.run(`vehicleContractModule=Promise.resolve(sharedContract); state.simulationReady=true;
    state.observationStale=true;
    state.vehicleSnapshot={version:'1.0',timestamp:'2026-10-22T03:00:00Z',frame:'NED',source:{id:'fixture_only',kind:'simulation'},
      vehicles:[{id:'UAV-02',connected:true,telemetry:{stale:false},pose:{position_m:{x:0,y:0,z:-3}}}]}`);
  const original = h.run("state.vehicleSnapshot");
  await h.run("postVehicleSnapshot()");
  assert.equal(sent.length, 1, h.run("state.simulationContractError"));
  assert.notEqual(sent[0].payload, original);
  assert.equal(sent[0].payload.vehicles[0].connected, true);
  assert.equal(sent[0].payload.vehicles[0].telemetry.stale, true);
  assert.equal(sent[0].payload.timestamp, original.timestamp);
  assert.deepEqual(sent[0].payload.vehicles[0].pose, original.vehicles[0].pose);
  assert.equal(original.vehicles[0].telemetry.stale, false);
});

test("switching Runtime source clears the previous observation and task cache", () => {
  const h = harness();
  h.api.setConfiguredBaseUrl = (value) => value;
  h.run(`state.lastObservationAt='2026-10-22T03:00:01Z';
    state.agentStatus={active_plans:[{plan_id:'old-fixture'}]};
    saveApiBaseUrl('http://127.0.0.1:9999/api')`);
  assert.equal(h.run("state.lastObservationAt"), null);
  assert.equal(h.run("state.observationStale"), true);
  assert.equal(h.run("state.agentStatus"), null);
  assert.equal(h.run("state.fleet.length"), 0);
});

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

test("selecting a vehicle immediately refreshes backend identity and ACK evidence", () => {
  const h = harness();
  // 沿用无 dataset 的极简 DOM 桩，检查 render 写入的内容而非直接调用页面函数。
  const content = { innerHTML: "", addEventListener() {} };
  h.context.document.getElementById = (id) => id === "app" ? h.app
    : id === "slot-content" ? content : null;
  h.run(`state.page = 'backend'; state.selectedUav = 'UAV-01';
    state.actionRecords = [1,2].map(n => ({node_id:'UAV-0'+n,
      action_id:'fixture-action-'+n, action_type:'takeoff', status:'succeeded',
      ack_evidence:[{stage:'fixture-ack-UAV-0'+n, result:0}]}));
    updateSelectedTelemetry(); render()`);
  assert.match(content.innerHTML, /<dt>node_id<\/dt><dd>UAV-01<\/dd>/);
  assert.match(content.innerHTML, /udpin:127\.0\.0\.1:14540/);
  assert.match(content.innerHTML, /<label>MAVLink Identity<\/label><input value="1\/1"/);
  assert.match(content.innerHTML, /fixture-ack-UAV-01/);

  h.run("selectVehicle('UAV-02')");
  assert.match(content.innerHTML, /<dt>node_id<\/dt><dd>UAV-02<\/dd>/);
  assert.match(content.innerHTML, /udpin:127\.0\.0\.1:14541/);
  assert.match(content.innerHTML, /<label>MAVLink Identity<\/label><input value="2\/1"/);
  assert.match(content.innerHTML, /fixture-action-2/);
  assert.match(content.innerHTML, /fixture-ack-UAV-02/);
  assert.doesNotMatch(content.innerHTML, /14540|fixture-action-1|fixture-ack-UAV-01/);

  // 来自三维视图的选择也立即刷新当前非 twin 页，不回推选择消息。
  h.run("selectVehicle('UAV-01', {fromSimulation:true})");
  assert.match(content.innerHTML, /<dt>node_id<\/dt><dd>UAV-01<\/dd>/);
  assert.match(content.innerHTML, /fixture-ack-UAV-01/);
  assert.doesNotMatch(content.innerHTML, /14541|fixture-action-2|fixture-ack-UAV-02/);
});

test("selecting a vehicle refreshes vehicle detail identity and telemetry state", () => {
  const h = harness();
  const content = { innerHTML: "", addEventListener() {} };
  h.context.document.getElementById = (id) => id === "app" ? h.app
    : id === "slot-content" ? content : null;
  h.run(`state.page='vehicle'; state.selectedUav='UAV-01';
    state.fleet[0].zDownM=-3; state.fleet[1].zDownM=-7;
    state.actionRecords=[{node_id:'UAV-02',action_type:'land',status:'executing'}];
    updateSelectedTelemetry(); render()`);
  assert.match(content.innerHTML, /单机详情 \/ UAV-01/);
  h.run("selectVehicle('UAV-02')");
  assert.match(content.innerHTML, /单机详情 \/ UAV-02/);
  assert.match(content.innerHTML, /MAVLink Identity<\/div><h2[^>]*>2\/1<\/h2>/);
  assert.match(content.innerHTML, /LAND \/ EXECUTING/);
  assert.equal(h.run("state.lastZ"), -7);
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
