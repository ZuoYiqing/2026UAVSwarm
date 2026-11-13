const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const dashboard = require("../mission-dashboard.js");
const model = require("../console-model.js");

const stamp = (second) => new Date(Date.UTC(2026, 10, 13, 2, 0, second)).toISOString();
const allow = { type:"policy_decision_event", timestamp:stamp(2), request_id:"req-1",
  action_id:"act-1", node_id:"UAV-02", action_type:"takeoff", decision_code:"allow", enforced_constraints:["fixture"] };
const adapter = { type:"adapter_execution_started", timestamp:stamp(3), request_id:"req-1", node_id:"UAV-02", adapter:"mavlink" };
const result = { type:"action_result", timestamp:stamp(4), request_id:"req-1", action_id:"act-1",
  node_id:"UAV-02", action:"takeoff", status:"succeeded", completion_evidence:{completion_reached:true} };
const deny = { type:"policy_decision_event", timestamp:stamp(8), request_id:"req-2",
  node_id:"UAV-03", action_type:"takeoff", decision_code:"deny", rule_name:"fixture_rule", reason:"fixture denial" };

function harness(href = "http://127.0.0.1:5178/") {
  let elapsed = 0;
  const timers = [];
  const calls = [];
  const intervals = [];
  const listeners = {};
  const slots = new Map(["app", "stage-title", "stage-content", "stage-indicators", "slot-banner", "slot-content"]
    .map(id => [id, { innerHTML:"", dataset:{}, addEventListener:(type,fn) => { listeners[type]=fn; } }]));
  const api = {
    getConfiguredBaseUrl:() => "http://127.0.0.1:8765/api",
    health:() => { calls.push("health"); return new Promise(() => {}); },
  };
  const context = vm.createContext({
    console, URL, crypto:require("node:crypto").webcrypto,
    localStorage:{getItem:() => null,setItem() {}},
    window:{location:{href},performance:{now:()=>elapsed},SwarmConsoleModel:model,SwarmMissionDashboard:dashboard,
      SwarmRuntimeApi:api,setTimeout:(callback,ms) => timers.push({callback,ms}),addEventListener() {}},
    document:{getElementById:id => slots.get(id) || null,querySelector:()=>null,activeElement:null},
    setInterval:(callback,ms) => intervals.push({callback,ms}),
  });
  const run = code => vm.runInContext(code, context);
  run(fs.readFileSync(path.join(__dirname,"../app.js"),"utf8"));
  return { api, calls, run, timers, listeners, html:id => slots.get(id).innerHTML,
    tick:s => { elapsed=s*1000; intervals.find(timer=>timer.ms===1000).callback(); } };
}

test("audit merges envelopes, raw replay and projections without inventing adapter stages", () => {
  const projection = {...allow, type:undefined, action_id:undefined, decision_id:"generated-id"};
  const log = dashboard.timeline({
    events:[{event_id:"generated-envelope", event_type:allow.type, timestamp:allow.timestamp, payload:allow}],
    replay:[deny, result, adapter, {...allow}],
    decisions:[projection],
    lifecycle:[{action_id:"act-1",request_id:"req-1",status:"succeeded",finished_at:stamp(4)},
      {action_id:"act-pending",request_id:"req-pending",status:"executing"}],
  });
  assert.deepEqual(log.map(row=>[row.type,row.color]), [
    ["policy_decision_event","green"],["adapter_execution_started","violet"],["action_result","muted"],["policy_decision_event","red"],
  ]);
  assert.deepEqual(log[0].raw.enforced_constraints, ["fixture"]);
  assert.equal(log[3].rule, "fixture_rule");
  assert.equal(log[3].reason, "fixture denial");
  assert.deepEqual(dashboard.timeline({decisions:[projection]}).map(row=>row.type), ["policy_decision_event"]);
});

test("producer mission progress retains waypoint basis and map only uses aligned fresh poses", () => {
  const payload = {mission_id:"fixture-plan",run_id:"fixture-run",status:"running",mode:"LIVE",
    completion_basis:"verified_waypoints",completion_pct:25,area_total_km2:0.00475,area_covered_km2:0.001,
    targets_found:null,targets_total:null,vehicles:[{node_id:"UAV-01",active:true,waypoints_reached:1,waypoints_total:4}],
    coverage:{scene_id:"fixture-scene",map_version:"v1",area_id:"fixture-area",frame:"scene_ned",
      polygon:[{north_m:0,east_m:0},{north_m:0,east_m:10},{north_m:10,east_m:10},{north_m:10,east_m:0}]}};
  const pose = {frame:"scene_ned",position_m:{x:5,y:5}};
  const snapshot = {scene_id:"fixture-scene",vehicles:[
    {id:"UAV-01",connected:true,telemetry:{stale:false},spatial:{map_version:"v1",scene_pose:pose,public_position_usable:true}},
    {id:"UAV-02",connected:true,telemetry:{stale:false},spatial:{map_version:"v2",scene_pose:pose,public_position_usable:true}},
    {id:"UAV-03",connected:true,telemetry:{stale:true},spatial:{map_version:"v1",scene_pose:pose,public_position_usable:true}},
  ]};
  const progress = dashboard.missionProgress(payload);
  assert.equal(progress.completionBasis, "verified_waypoints");
  assert.equal(progress.targetsFound, null);
  assert.equal(progress.safety, null);
  assert.equal(dashboard.assignmentProgress(progress.assignments[0]), 25);
  assert.equal(dashboard.assignmentProgress({waypoints_reached:0,waypoints_total:0}), null);
  assert.equal(dashboard.missionProgress({...payload,status:"unavailable"}), null);
  const map = dashboard.missionMap(progress, snapshot);
  assert.equal(map.regions[0].coverage_status, undefined);
  assert.deepEqual(map.markers,[{id:"UAV-01",x:50,y:50}]);
  assert.equal(dashboard.missionMap(progress,{...snapshot,scene_id:"other"}).markers.length,0);
  assert.equal(dashboard.missionMap(dashboard.missionProgress({...payload,coverage:null}),snapshot),null);
});

test("DEMO plays its complete zero-operation story and keeps all writes disabled", async () => {
  const h = harness("http://127.0.0.1:5178/?mode=stage");
  assert.match(h.html("app"), /stage-shell/);
  assert.doesNotMatch(h.html("app"), /slot-sidebar/);
  assert.match(h.html("stage-indicators"), /DEMO · 内置演习/);
  assert.match(h.html("stage-content"), /UAV-01.*西区/s);
  h.tick(19);
  assert.match(h.html("stage-content"), /链路质量.*42.*▼/s);
  h.tick(25);
  assert.match(h.html("stage-content"), /mission-kpi red[\s\S]*链路质量[\s\S]*18/);
  h.tick(43);
  assert.match(h.html("stage-content"), /适配器.*动作结果.*拒绝/s);
  assert.match(h.html("slot-banner"), /DENY.*link_rejoin_threshold/s);
  h.timers.filter(timer=>timer.ms===2000).at(-1).callback();
  assert.match(h.html("slot-banner"), /is-compact/);
  h.tick(55);
  assert.match(h.html("stage-content"), /5179\/\?mode=demo.*inert/);
  h.tick(97);
  assert.match(h.html("stage-content"), /链路质量.*89/s);
  h.tick(180);
  assert.match(h.html("stage-content"), /部分覆盖/);
  assert.match(h.html("stage-content"), /恢复/);
  assert.match(h.html("stage-title"), /10 \/ 10/);
  h.run("runOperationalTakeoff(); runSmokeTakeoff(); runLand();");
  await h.run("Promise.all([changeDemoLink('inject'),checkBackend(),generateRequest()])");
  assert.deepEqual(h.calls,[]);
});

test("live demo writes require an explicitly enabled safe Runtime rehearsal and keep audit evidence labeled", async () => {
  const h = harness();
  const body = [];
  h.api.demoInject = async data => { body.push(data); return {mode:"DEMO",flight_command_sent:false,changed:true}; };
  h.api.demoClear = async data => { body.push(data); return {mode:"DEMO",flight_command_sent:false,changed:true}; };
  h.run(`syncRuntimeState=async()=>{};syncRuntimeEvents=async()=>{};
    state.apiStatus="live"; state.fleet=[{id:"UAV-02",enabled:true,connected:true}]; state.selectedUav="UAV-02";`);
  await h.run("changeDemoLink('inject')");
  assert.equal(body.length,0);
  h.run(`updateMissionDashboard({demoRuntime:{status:"fulfilled",value:{
    enabled:true,mode:"DEMO",flight_command_sent:false,execution_authorized:false}}});`);
  await h.run("Promise.all([changeDemoLink('inject'),changeDemoLink('inject')])");
  await h.run("changeDemoLink('clear')");
  assert.deepEqual(body.map(row=>JSON.parse(JSON.stringify(row))), [
    {node_id:"UAV-02",kind:"link_degraded",value:18,duration_s:60},{node_id:"UAV-02"},
  ]);
  h.run(`state.fleet.push({id:"UAV-01",enabled:true,connected:false});
    state.vehicleSnapshot={vehicles:[{id:"UAV-01",link_quality_mode:"LIVE",link_quality:0},
      {id:"UAV-02",link_quality_mode:"DEMO",link_quality:18,link_quality_measured:0}]};
    state.telemetry={nodes:[]}; updateMissionLinks();`);
  assert.match(h.run("overviewPage()"), /DEMO · Runtime 链路注入/);
  assert.match(h.run("missionIndicators()"), /mission-kpi red/);
  assert.match(h.run("missionIndicators()"), /链路质量.*18.*DEMO 注入 · UAV-02 \/ 100.*实测 0/s);
  assert.match(h.run("missionIndicators()"), /等待安全证据/);
  h.run(`state.apiStatus="offline"; state.mission={id:"fixture",title:"Fixture",completion:30};`);
  assert.match(h.run("missionIndicators()"), /最后上报 · 当前进度未知/);
  assert.doesNotMatch(h.run("missionIndicators()"), /mission-kpi red/);
});

test("clearing an override remains distinct from a confirmed link recovery", () => {
  const events = dashboard.timeline({replay:[
    {type:"demo_clear",mode:"DEMO",timestamp:stamp(10),link_quality:0},
    {type:"demo_recovered",mode:"DEMO",timestamp:stamp(20),link_quality:89},
  ]});
  assert.deepEqual(events.map(row=>row.label), ["撤销注入","恢复"]);
});

test("policy filters and full event JSON persist across navigation, while unavailable modules are explicit", () => {
  const h = harness();
  h.run(`state.replayEvents=${JSON.stringify([allow,deny])};
    state.policyFilters={node:"UAV-03",decision:"deny"};
    state.timelineKey=missionTimeline().find(row=>row.decision==="deny").key;
    setPage("policy"); setPage("overview"); setPage("policy");`);
  const html = h.html("slot-content");
  assert.match(html, /<option value="UAV-03" selected>/);
  assert.match(html, /<option value="deny" selected>/);
  assert.match(html, /fixture_rule[\s\S]*fixture denial/);
  assert.doesNotMatch(html, /enforced_constraints/);
  assert.equal((h.run("sidebar()").match(/onclick="setPage\(/g)||[]).length, 15);
  assert.match(h.run("assetsPage()"), /规划中.*等待硬件资产数据/s);
  assert.match(h.run("planningPage()"), /下发任务 · 规划中/);
});
