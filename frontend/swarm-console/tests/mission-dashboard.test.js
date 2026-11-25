const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const dashboard = require("../mission-dashboard.js");
const model = require("../console-model.js");
const coverageGrid = require("../coverage-grid.js");
// Synthetic producer fixture preserved from 82729c9, not flight telemetry.
const s7Fixture = require("./fixtures/coverage_grid_s7_v1.json");
const inspection = require("./fixtures/equipment-inspection-lifecycle.json");

const stamp = (second) => new Date(Date.UTC(2026, 10, 13, 2, 0, second)).toISOString();
const allow = { type:"policy_decision_event", timestamp:stamp(2), request_id:"req-1",
  action_id:"act-1", node_id:"UAV-02", action_type:"takeoff", decision_code:"allow", enforced_constraints:["fixture"] };
const adapter = { type:"adapter_execution_started", timestamp:stamp(3), request_id:"req-1", node_id:"UAV-02", adapter:"mavlink" };
const result = { type:"action_result", timestamp:stamp(4), request_id:"req-1", action_id:"act-1",
  node_id:"UAV-02", action:"takeoff", status:"succeeded", completion_evidence:{completion_reached:true} };
const deny = { type:"policy_decision_event", timestamp:stamp(8), request_id:"req-2",
  node_id:"UAV-03", action_type:"takeoff", decision_code:"deny", rule_name:"fixture_rule", reason:"fixture denial" };

function progressWithGrid(coverage = s7Fixture.coverage) {
  return {
    mission_id: "s7-fixture-plan", status: "running", mode: "LIVE",
    scene_id: coverage.scene_id, map_version: coverage.map_version,
    completion_basis: "verified_waypoints", completion_pct: 75,
    waypoints_reached: 3, waypoints_total: 4,
    area_covered_km2: coverage.area_covered_km2, area_total_km2: coverage.area_total_km2,
    coverage,
  };
}

function harness(href = "http://127.0.0.1:5178/", apiOverrides = {}) {
  let elapsed = 0;
  const timers = [];
  const calls = [];
  const intervals = [];
  const listeners = {};
  const slots = new Map(["app", "stage-title", "stage-content", "stage-indicators", "slot-banner", "slot-content",
    "mission-fixture-candidate", "mission-fixture-progress"]
    .map(id => [id, { innerHTML:"", dataset:{}, addEventListener:(type,fn) => { listeners[type]=fn; } }]));
  const api = {
    getConfiguredBaseUrl:() => "http://127.0.0.1:8765/api",
    health:() => { calls.push("health"); return new Promise(() => {}); },
    ...apiOverrides,
  };
  const context = vm.createContext({
    console, URL, crypto:require("node:crypto").webcrypto,
    localStorage:{getItem:() => null,setItem() {}},
    window:{location:{href},performance:{now:()=>elapsed},SwarmConsoleModel:model,SwarmMissionDashboard:dashboard,
      SwarmRuntimeApi:api,
      setTimeout(callback, ms) {
        const timer = { callback, ms };
        timers.push(timer);
        return timer;
      },
      clearTimeout(timer) {
        const index = timers.indexOf(timer);
        if (index >= 0) timers.splice(index, 1);
      },
      addEventListener:(type, fn) => { listeners[type] = fn; }},
    document:{getElementById:id => slots.get(id) || null,querySelector:()=>null,activeElement:null},
    setInterval:(callback,ms) => intervals.push({callback,ms}),
  });
  const run = code => vm.runInContext(code, context);
  run(fs.readFileSync(path.join(__dirname,"../app.js"),"utf8"));
  return { api, calls, run, timers, listeners, slots, html:id => slots.get(id).innerHTML,
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

test("the LIVE task map separates verified waypoint completion from covered area", () => {
  const h = harness("http://127.0.0.1:5178/?mode=stage&source=live");
  const progress = {
    mission_id: "fixture-plan", status: "running", completion_basis: "verified_waypoints",
    completion_pct: 75, waypoints_reached: 3, waypoints_total: 4,
    area_covered_km2: 0.001, area_total_km2: 0.00475,
    coverage: { frame: "scene_ned", polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
  };
  h.run(`state.apiStatus="live"; state.missionStatus="live"; state.mission=dashboard.missionProgress(${JSON.stringify(progress)}); renderStage();`);
  const map = h.html("stage-content");
  assert.match(map, /航点完成度<\/span><b>75%<\/b>\s*<small>3 \/ 4 个航点/);
  assert.match(map, /面积覆盖率<\/span><b>21\.05%<\/b>\s*<small>0\.001000 \/ 0\.004750 km²/);
  assert.match(map, /class="mission-region unknown"/);

  for (const [covered, total, label] of [[0, 0.00475, "0%"], [null, 0.00475, "—"],
    [0.001, 0, "—"], [0.005, 0.00475, "—"]]) {
    const sample = {...progress, area_covered_km2: covered, area_total_km2: total};
    h.run(`state.mission=dashboard.missionProgress(${JSON.stringify(sample)}); renderStage();`);
    assert.ok(h.html("stage-content").includes(`面积覆盖率</span><b>${label}</b>`));
    assert.match(h.html("stage-content"), /航点完成度<\/span><b>75%/);
  }
});

test("the S7 producer fixture draws along north and east within the published boundary", () => {
  const projection = dashboard.missionMap(dashboard.missionProgress(progressWithGrid()), null).coverageGrid;
  assert.equal(projection.cells.length, 7);
  assert.equal(projection.size, 20);
  const calls = [];
  const ctx = Object.fromEntries(["save", "restore", "clearRect", "beginPath", "moveTo", "lineTo",
    "closePath", "clip", "fillRect"].map(name => [name, (...args) => calls.push([name, ...args])]));
  coverageGrid.draw({width:1600, height:1000, getContext:()=>ctx}, projection);
  const clipped = calls.findIndex(([name]) => name === "clip");
  const rectangles = calls.filter(([name]) => name === "fillRect");
  assert.ok(clipped > 0 && clipped < calls.findIndex(([name]) => name === "fillRect"));
  assert.equal(rectangles.length, 7);
  assert.ok(rectangles[1][1] > rectangles[0][1], "advancing east moves right");
  assert.ok(rectangles[2][2] < rectangles[0][2], "advancing north moves up");
  assert.ok(rectangles[1][1] + rectangles[1][3] > projection.polygon[2].x * 16,
    "the east-most display cell extends past the polygon and is clipped");
  assert.equal(calls.at(-1)[0], "restore");
});

test("the LIVE map distinguishes mapped coverage, observed zero and unavailable distribution", () => {
  const h = harness("http://127.0.0.1:5178/?mode=stage&source=live");
  h.run('state.apiStatus="live"; state.missionStatus="live";');
  const renderMap = coverage => {
    h.run(`state.mission=dashboard.missionProgress(${JSON.stringify(progressWithGrid(coverage))}); renderStage();`);
    return h.html("stage-content");
  };
  const valid = s7Fixture.coverage;
  const map = renderMap(valid);
  assert.match(map, /mission-coverage-grid/);
  assert.match(map, /7 个格有覆盖记录，格内可能仅部分覆盖/);
  assert.match(map, /航点完成度<\/span><b>75%/);
  assert.match(map, /面积覆盖率<\/span><b>15\.12%/);

  const zero = renderMap({...valid, area_covered_km2:0, grid:{...valid.grid, covered_cells:[]}});
  assert.match(zero, /已有观测，当前没有覆盖记录/);
  assert.match(zero, /面积覆盖率<\/span><b>0%/);

  for (const grid of [undefined, null,
    {...valid.grid, frame:"scene_enu"}, {...valid.grid, map_version:"foreign-version"},
    {...valid.grid, rows:300, columns:300}, {...valid.grid, covered_cells:[[0,0,718],[0,0,718]]},
    {...valid.grid, covered_cells:[[5,0,718]]}, {...valid.grid, covered_cells:[]}]) {
    const fallback = renderMap({...valid, grid});
    assert.match(fallback, /覆盖分布未知/);
    assert.doesNotMatch(fallback, /mission-coverage-grid/);
    assert.match(fallback, /面积覆盖率<\/span><b>15\.12%/);
  }
  const snapshotMiss = dashboard.missionProgress({...progressWithGrid(), scene_id:"other-scene"});
  assert.equal(snapshotMiss.coverageGrid, null);
});

test("the three offline chapters retain the map and policy evidence and never call Runtime", async () => {
  const h = harness("http://127.0.0.1:5178/?mode=stage");
  assert.match(h.html("app"), /stage-shell/);
  assert.doesNotMatch(h.html("app"), /slot-sidebar/);
  assert.match(h.html("stage-indicators"), /DEMO · 内置演习/);
  assert.match(h.html("stage-content"), /UAV-01.*西区/s);
  assert.match(h.html("stage-content"), /内置演习进度/);
  assert.doesNotMatch(h.html("stage-content"), /航点完成度/);
  h.tick(21);
  assert.match(h.html("stage-content"), /链路质量.*42.*▼/s);
  h.tick(27);
  assert.match(h.html("stage-content"), /mission-kpi red[\s\S]*链路质量[\s\S]*18/);
  assert.match(h.html("stage-title"), /链路降级与接续.*2 \/ 3/s);
  for (const event of [/适配器/, /动作结果/, /拒绝/, /中区任务转交/]) assert.match(h.html("stage-content"), event);
  assert.match(h.html("stage-content"), /任务地图/);
  assert.doesNotMatch(h.html("stage-content"), /<iframe/);
  h.tick(41);
  assert.match(h.html("stage-content"), /链路质量.*89/s);
  h.tick(60);
  assert.match(h.html("stage-content"), /部分覆盖/);
  assert.match(h.html("stage-content"), /恢复/);
  assert.match(h.html("stage-title"), /恢复与结果.*3 \/ 3/s);
  h.run("seekStage(1)");
  h.tick(80);
  assert.match(h.html("stage-title"), /2 \/ 3/);
  assert.match(h.html("stage-content"), /中区任务转交/);
  assert.doesNotMatch(h.html("stage-content"), /链路读数恢复到 89/);
  h.run("toggleStagePlayback(true)");
  assert.match(h.html("stage-title"), /1 \/ 3/);
  h.run("runOperationalTakeoff(); runSmokeTakeoff(); runLand();");
  await h.run("Promise.all([changeDemoLink('inject'),checkBackend(),generateRequest()])");
  assert.deepEqual(h.calls,[]);
});

test("the live stage holds a selected view unless the presenter starts rotation", () => {
  const h = harness("http://127.0.0.1:5178/?mode=stage&source=live");
  h.tick(60);
  assert.match(h.html("stage-title"), /任务地图.*1 \/ 4/s);
  h.run("seekStage(3)");
  h.tick(120);
  assert.match(h.html("stage-title"), /三维态势.*4 \/ 4/s);
  assert.match(h.html("stage-content"), /5179\/.*inert/);
  h.run("toggleStagePlayback()");
  h.tick(139);
  assert.match(h.html("stage-title"), /任务地图.*1 \/ 4/s);
  assert.doesNotMatch(h.html("stage-content"), /<iframe/);
});

test("fresh shared poses are shown without inventing task geometry or assignments", () => {
  const h = harness();
  const snapshot = { scene_id: "fixture-scene", source: {kind:"simulation", label:"PX4 SITL / Runtime"},
    vehicles: ["UAV-01", "UAV-02", "UAV-03"].map((id, index) => ({
      id, connected: true, telemetry: { stale: index === 2 },
      spatial: { map_version: "fixture-v1", public_position_usable: true,
        scene_pose: {frame: "scene_ned", position_m: {x:0, y:index * 10}} },
    })) };
  h.run(`state.apiStatus="live"; state.dataStatus="live";
    state.vehicleSnapshot=${JSON.stringify(snapshot)};
    state.fleet=state.vehicleSnapshot.vehicles.map(v => ({id:v.id, connected:true, stale:v.telemetry.stale}));`);
  assert.match(h.run("overviewPage()"), /LIVE · PX4 SITL 遥测/);
  assert.doesNotMatch(h.run("overviewPage()"), /Runtime 演示注入未启用|区域覆盖、链路健康与自主处置/);
  let html = h.run("missionMapPanel()");
  assert.match(html, /载具位置俯视图/);
  assert.equal((html.match(/class="mission-map-node"/g) ?? []).length, 2);
  assert.match(html, /UAV-01<\/b><span>未收到任务分工/);
  assert.doesNotMatch(html, /<canvas|class="mission-region|<progress/);
  h.run('state.vehicleSnapshot.vehicles[1].spatial.map_version = "fixture-v2"');
  assert.doesNotMatch(h.run("missionMapPanel()"), /class="mission-map-node"/);
  h.run('state.dataStatus="stale"');
  html = h.run("missionMapPanel()");
  assert.match(html, /尚未收到任务执行数据/);
});

test("older fake action audit rows use their recorded time and remain labeled as DEMO", () => {
  const h = harness();
  const legacy = { type: "action_result", adapter: "fake", message: "simulated success",
    request_id: "legacy-record", timestamps: { result_time: stamp(9) } };
  const entry = dashboard.timeline({replay:[legacy]})[0];
  assert.equal(entry.timestamp, stamp(9));
  h.run(`state.replayEvents=${JSON.stringify([legacy])}`);
  const html = h.run("timelinePanel()");
  assert.match(html, /未记录载具或动作/);
  assert.match(html, /DEMO · simulated success/);
  assert.doesNotMatch(html, /时间未知/);
});

test("template preview submits the operator's text and renders only returned policy and risk evidence", async () => {
  const h = harness();
  const requests = [];
  const objective = "检查园区设备并保存照片。";
  h.api.planMission = async body => {
    requests.push(JSON.parse(JSON.stringify(body)));
    return {
      result: "awaiting_confirmation",
      ...(body.mission_type ? {
        contract_version: "1.0", intent_source: "explicit", plan_source: "template",
        fallback_reason: null, execution_authorized: false,
      } : {}),
      plan: {plan_id: "test-plan", steps: [
        {action_type:"takeoff", risk_level:2, policy_precheck:{decision_code:"require_confirm",primary_reason_code:"operator_required"}},
        {action_type:"camera_capture", status:"dry_run_only", policy_precheck:null},
      ]},
    };
  };
  h.run('setPage("planning")');
  await h.run("generateRequest()");
  assert.match(h.run("templatePlanPreview()"), /请先填写任务目标/);
  assert.doesNotMatch(h.run("templatePlanPreview()"), /Runtime 返回 JSON/);
  h.run(`setTemplatePlanObjective(${JSON.stringify(objective)})`);
  await h.run("Promise.all([generateRequest(), generateRequest()])");
  assert.deepEqual(requests, [{objective}]);
  const plan = h.run("planningPage()");
  assert.match(plan, /起飞<\/td>\s*<td>需确认<\/td>\s*<td>operator_required<\/td>\s*<td>2<\/td>/);
  assert.match(plan, /采集照片<\/td>\s*<td>未预检<\/td>\s*<td>未上报原因<\/td>\s*<td>未上报<\/td>/);
  assert.match(plan, /Runtime 返回 JSON/);
  assert.doesNotMatch(plan, /42 \/ 100|18 条策略|<iframe/);

  assert.match(plan, /意图识别<\/dt><dd>未知/);
  assert.match(plan, /执行授权<\/dt><dd>未上报/);
  await h.run('generateRequest("inspection_snapshot")');
  assert.deepEqual(requests[1], {objective, mission_type:"inspection_snapshot"});
  assert.match(h.run("templatePlanPreview()"), /显式指定模板 <code>explicit<\/code>/);

  h.api.planMission = async () => { throw Object.assign(new Error("模板接口故障"), {kind:"http"}); };
  await h.run("generateRequest()");
  assert.match(h.run("templatePlanPreview()"), /模板接口故障/);
  assert.doesNotMatch(h.run("templatePlanPreview()"), /test-plan|operator_required/);
  h.run('setTemplatePlanObjective("重新填写")');
  assert.doesNotMatch(h.run("planningPage()"), /模板接口故障/);
});

test("preview shows slow feedback with the configured limit, then unlocks retry after a timeout", async () => {
  const h = harness();
  const button = { textContent: "", disabled: false };
  h.slots.set("template-plan-submit", button);
  h.slots.set("template-plan-preview", { innerHTML: "" });
  let slow;
  let rejectRequest;
  let calls = 0;
  h.api.planMission = (_body, { onSlow }) => {
    calls += 1;
    slow = onSlow;
    return new Promise((_resolve, reject) => { rejectRequest = reject; });
  };

  h.run('setPage("planning"); setTemplatePlanObjective("巡检东北视觉标记");');
  const first = h.run("generateRequest()");
  assert.equal(button.textContent, "识别中…");
  assert.equal(button.disabled, true);
  assert.doesNotMatch(h.html("template-plan-preview"), /继续等待/);

  slow(30_000);
  assert.equal(button.textContent, "继续等待…");
  assert.match(h.html("template-plan-preview"), /Runtime 响应较慢，继续等待（最多 30 秒）/);
  assert.equal(button.disabled, true);
  await h.run("generateRequest()");
  assert.equal(calls, 1);

  rejectRequest(Object.assign(new Error("transport timeout"), { kind: "timeout" }));
  await first;
  assert.match(h.html("template-plan-preview"), /Runtime 响应超时/);
  assert.doesNotMatch(h.html("template-plan-preview"), /继续等待/);
  assert.equal(button.textContent, "预览任务");
  assert.equal(button.disabled, false);

  h.api.planMission = async () => ({ result: "ready", plan: { plan_id: "retry-preview", steps: [] } });
  await h.run("generateRequest()");
  assert.match(h.html("template-plan-preview"), /retry-preview/);
  assert.doesNotMatch(h.html("template-plan-preview"), /响应超时|继续等待/);
});

// 前端消费端契约用例。真实场景输入另由 Runtime 路由和浏览器联验。
test("scene intent previews show the reported sources and keep preview, reference and exclusion roles distinct", async () => {
  const h = harness();
  h.api.planMission = async () => ({
    contract_version: "1.0", intent_source: "rules", plan_source: "template",
    fallback_reason: null, execution_authorized: false, result: "ready",
    intent_resolution: { status: "resolved", mission_type: "inspection_snapshot" },
    plan: {
      steps: [{ action_type: "camera_capture", status: "dry_run_only" }],
      preview_binding: { steps_are_outline: true,
        catalog: { scene_id: "simple_recon_v0_1", map_version: "test-map", catalog_id: "test-catalog" },
        bindings: {
          targets: [],
          preview_only_targets: [{ entity_id:"demo-area-001", evidence:"西北区域" }],
          reference_only: [{ entity_id:"building-001", evidence:"中央建筑" }],
          excluded_targets: [{ entity_id:"building-001", evidence:"中央建筑" }],
          only_listed_targets: true, status_scope: null,
        },
      },
    },
  });
  h.run('setPage("planning"); setTemplatePlanObjective("巡检西北区域");');
  await h.run("generateRequest()");
  const html = h.run("templatePlanPreview()");
  assert.match(html, /契约版本<\/dt><dd>1\.0/);
  assert.match(html, /离线规则识别 <code>rules<\/code>/);
  assert.match(html, /模板生成 <code>template<\/code>/);
  assert.match(html, /执行授权<\/dt><dd>未授权执行 <code>false<\/code>/);
  assert.match(html, /降级原因<\/dt><dd>无/);
  assert.match(html, /Runtime 模板大纲/);
  assert.match(html, /场景巡检目标<\/dt><dd>无/);
  assert.match(html, /演习目标<\/dt><dd><ul><li>西北区域 <code>demo-area-001<\/code>.*仅预览，不可执行/);
  for (const role of ["定位参照", "排除目标"]) {
    assert.ok(html.includes(`${role}</dt><dd><ul><li>中央建筑 <code>building-001</code>`));
  }
  assert.match(html, /仅列明目标<\/dt><dd>是/);
  assert.match(html, /状态范围<\/dt><dd>无/);
  assert.doesNotMatch(html, /<iframe|<canvas|本地模型识别/);
});

test("clarification and unsupported replies replace the previous plan with Runtime's question and reason", async () => {
  const h = harness();
  h.run('setPage("planning"); setTemplatePlanObjective("巡检东北视觉标记");');
  const oldPlan = { plan_id:"old-preview", steps:[{action_type:"camera_capture"}] };
  h.api.planMission = async () => ({ result:"ready", plan:oldPlan });
  await h.run("generateRequest()");
  assert.match(h.run("templatePlanPreview()"), /old-preview/);

  let respond;
  const requests = [];
  h.api.planMission = body => {
    requests.push(body.objective);
    return new Promise(resolve => { respond = resolve; });
  };
  const pending = h.run("generateRequest()");
  assert.doesNotMatch(h.run("templatePlanPreview()"), /old-preview|template-plan-steps/);
  const noPlan = (status, reason_code, question) => ({
    contract_version:"1.0", intent_source:"rules", plan_source:"none",
    fallback_reason:null, execution_authorized:false, result:"blocked", plan:null,
    intent_resolution:{ status, reason_code, question },
  });

  respond(noPlan("needs_clarification", "TARGET_AMBIGUOUS", "西侧参考点还是东侧参考点？"));
  await pending;
  let html = h.run("templatePlanPreview()");
  assert.match(html, /需要澄清/);
  assert.match(html, /西侧参考点还是东侧参考点？/);
  assert.match(html, /无计划 <code>none<\/code>/);
  assert.doesNotMatch(html, /template-plan-steps|old-preview|策略预检/);

  h.run('setTemplatePlanObjective("巡检中央建筑")');
  const reference = h.run("generateRequest()");
  respond(noPlan("needs_clarification", "TARGET_REFERENCE_ONLY", "所选对象仅可作参照。"));
  await reference;
  html = h.run("templatePlanPreview()");
  assert.match(html, /TARGET_REFERENCE_ONLY/);
  assert.match(html, /可用于定位，也可从本轮目标中排除/);
  assert.doesNotMatch(html, /template-plan-steps|old-preview|策略预检/);

  h.run('setTemplatePlanObjective("西南和东南都巡检")');
  const unsupported = h.run("generateRequest()");
  respond(noPlan("unsupported", "UNSUPPORTED_OBJECTIVE", "请明确任务目标。"));
  await unsupported;
  html = h.run("templatePlanPreview()");
  assert.match(html, /当前输入不受支持/);
  assert.match(html, /UNSUPPORTED_OBJECTIVE/);
  assert.doesNotMatch(html, /template-plan-steps|old-preview|策略预检/);
  assert.deepEqual(requests, ["巡检东北视觉标记", "巡检中央建筑", "西南和东南都巡检"]);
});

test("planner shows the adopted model answer and rejected retry evidence without changing intent provenance", async () => {
  const h = harness();
  const reply = {
    contract_version: "1.0", intent_source: "local_model", plan_source: "template",
    execution_authorized: false, fallback_reason: null, result: "ready",
    plan: { steps: [{ action_type: "camera_capture" }], preview_binding: { steps_are_outline: true } },
  };
  h.api.planMission = async () => reply;
  h.run('setPage("planning"); setTemplatePlanObjective("巡检东北视觉标记");');
  await h.run("generateRequest()");
  assert.doesNotMatch(h.run("templatePlanPreview()"), /模型原答/);

  reply.model_diagnostics = {
    adopted: true, not_adopted_reason: null,
    attempts: [
      { adopted: false, raw_text: "<b>模型返回了非 JSON 内容</b>", not_adopted_reason: "MODEL_JSON_INVALID" },
      { adopted: true, raw_text: '{"t":[2],"r":[],"x":[],"only":false}', not_adopted_reason: null },
    ],
  };
  await h.run("generateRequest()");
  const html = h.run("templatePlanPreview()");
  assert.match(html, /本地模型识别 <code>local_model<\/code>/);
  assert.match(html, /Runtime 模板大纲/);
  assert.match(html, /<details class="template-model-answer" open><summary>模型原答 · 已采用/);
  assert.match(html, /第 1 次 · 未采用/);
  assert.match(html, /未采用原因.*MODEL_JSON_INVALID/);
  assert.match(html, /&lt;b&gt;模型返回了非 JSON 内容&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>模型返回了非 JSON 内容<\/b>/);
  assert.match(html, /第 2 次 · 已采用/);
  assert.match(html, /&quot;t&quot;:\[2\]/);
});

test("planner shows fallback diagnostics with the offline rules source and handles unavailable text", async () => {
  const h = harness();
  const reply = {
    contract_version: "1.0", intent_source: "rules", plan_source: "template", execution_authorized: false,
    fallback_reason: "model_invalid_output", result: "ready",
    plan: { steps: [{ action_type: "camera_capture" }], preview_binding: { steps_are_outline: true } },
    model_diagnostics: {
      adopted: false, not_adopted_reason: "MODEL_INDEX_INVALID",
      attempts: [{ adopted: false, raw_text: '{"t":[99],"r":[],"x":[],"only":false}',
        not_adopted_reason: "MODEL_INDEX_INVALID", truncated: true }],
    },
  };
  h.api.planMission = async () => reply;
  h.run('setPage("planning"); setTemplatePlanObjective("巡检东北视觉标记");');
  await h.run("generateRequest()");
  const html = h.run("templatePlanPreview()");
  const answer = html.match(/<details class="template-model-answer" open>([\s\S]*?)<\/details>/)?.[1] || "";
  assert.match(html, /离线规则识别 <code>rules<\/code>/);
  assert.match(html, /降级原因<\/dt><dd>model_invalid_output/);
  assert.match(answer, /模型原答 · 未采用/);
  assert.match(answer, /目录编号列表不符合要求.*MODEL_INDEX_INVALID/);
  assert.match(answer, /&quot;t&quot;:\[99\]/);
  assert.match(answer, /原答已由 Runtime 截断/);

  reply.plan_source = "none";
  reply.plan = null;
  reply.result = "blocked";
  reply.fallback_reason = "model_unavailable";
  reply.model_diagnostics = { adopted: false, not_adopted_reason: "MODEL_TIMEOUT",
    attempts: [{ adopted: false, raw_text: null, not_adopted_reason: "MODEL_TIMEOUT" }] };
  await h.run("generateRequest()");
  assert.match(h.run("templatePlanPreview()"), /本次未提供原答文本/);
  assert.match(h.run("templatePlanPreview()"), /模型响应超时 <code>MODEL_TIMEOUT<\/code>/);
  assert.doesNotMatch(h.run("templatePlanPreview()"), /template-plan-steps/);
});

test("planner renders the runtime order across preview and real targets only when reported", () => {
  const h = harness();
  const real = { entity_id: "target-001", evidence: "东北视觉标记" };
  const preview = { entity_id: "demo-area-001", evidence: "西北区域" };
  const render = bindings => h.run(`templatePlanBinding({bindings:${JSON.stringify(bindings)}}, "inspection_snapshot")`);

  const mixed = { targets: [real], preview_only_targets: [preview] };
  assert.doesNotMatch(render(mixed), /核对顺序/);
  assert.match(render({ targets: [real], preview_only_targets: [], target_order_basis: null }),
    /核对顺序<\/dt><dd>无顺序要求/);
  assert.match(render({ ...mixed, target_order_basis: "explicit_sequence", target_order: [real.entity_id, preview.entity_id] }),
    /核对顺序<\/dt><dd>东北视觉标记 → 西北区域（仅预览）.*原话明确先后/);
  assert.match(render({ ...mixed, target_order_basis: "mention_order", target_order: [preview.entity_id, real.entity_id] }),
    /核对顺序<\/dt><dd>西北区域（仅预览） → 东北视觉标记.*按提及顺序/);
  assert.match(render({ ...mixed, target_order_basis: "mention_order" }), /核对顺序<\/dt><dd>顺序未上报/);
  assert.match(render({ ...mixed, target_order_basis: "mention_order", target_order: [real.entity_id, real.entity_id] }),
    /核对顺序<\/dt><dd>顺序未上报/);
  const sameRole = [real, { entity_id: "target-002", evidence: "南侧标记" }];
  assert.match(render({ targets: sameRole, preview_only_targets: [], target_order_basis: "mention_order" }),
    /核对顺序<\/dt><dd>东北视觉标记 → 南侧标记.*按提及顺序/);
});

const inspectionObjective = "检查场景里的 target-001 设备标记并记录航点到达。";

function inspectionConsole() {
  const { completed_run: completed } = inspection;
  let progress = completed.before;
  let respond;
  const approvals = [];
  const validateCandidate = async ({ objective }) => objective === inspectionObjective
    ? { result: "validated", plan: inspection.plan }
    : { result: "clarify", failure_reason: "请明确巡检样例的设备标记" };
  const h = harness(undefined, {
    snapshot: async () => ({ active_actions: [], mission_progress: completed.progress }),
    telemetryLatest: async () => ({ nodes: [] }),
    vehicleSnapshot: async () => ({ vehicles: [] }),
    agentStatus: async () => ({}),
    simulationStatus: async () => ({}),
    vehicles: async () => ({ vehicles: [] }),
    skills: async () => ({}),
    policyDecisions: async () => [],
    recentActions: async () => [],
    actionLifecycle: async () => [],
    missionProgress: async () => {
      if (progress instanceof Error) throw progress;
      return progress;
    },
    missionFixture: {
      validateCandidate,
      execute: body => {
        approvals.push(JSON.parse(JSON.stringify(body)));
        return new Promise(resolve => { respond = resolve; });
      },
    },
  });
  h.run(`setPage("planning"); setTemplatePlanObjective(${JSON.stringify(inspectionObjective)});`);
  return {
    ...h, approvals, validateCandidate,
    respond: receipt => respond(receipt),
    read: async next => {
      progress = next;
      await h.run("syncRuntimeState()");
      h.run("renderRuntimeUpdate()");
    },
  };
}

test("the preview sends only validated fixture waypoints to the current twin and clears without an execution", async () => {
  const h = inspectionConsole();
  const sent = [];
  const frame = { contentWindow: { postMessage: (message, origin) => sent.push({ message, origin }) } };
  const hello = { origin: "http://127.0.0.1:5179", source: frame.contentWindow, data: {
    type: "uav-swarm/simulation-ready", payload: { contractVersion: "1.0", integration: "parent-snapshot" },
  } };
  const time = Date.parse(stamp(0));
  h.run(`Date.now = () => ${time}`);
  await h.run("validateFixtureCandidate()");
  assert.equal(sent.length, 0);
  h.run('setPage("twin")');
  assert.match(h.run("simulationFrame()"), /planPreview=fixture/);
  h.slots.set("simulation-frame", frame);
  h.listeners.message({ ...hello, source: {} });
  h.listeners.message({ ...hello, origin: "http://127.0.0.1:5188" });
  assert.equal(sent.length, 0);
  h.listeners.message(hello);
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0])), {
    origin: "http://127.0.0.1:5179",
    message: { type: "uav-swarm/plan-preview", payload: {
      version: "1.0", plan_id: inspection.plan.plan_id, scene_id: inspection.plan.scene_id,
      map_version: inspection.plan.map_version, frame: "scene_ned", expires_at_ms: time + 60_000,
      waypoints: inspection.plan.steps.filter(step => step.action_type === "goto").map(step => ({
        step_id: step.step_id, node_id: step.node_id,
        north_m: step.params.north_m, east_m: step.params.east_m, down_m: step.params.down_m,
      })),
    } },
  });
  h.run(`Date.now = () => ${time + 10_000}`);
  h.listeners.message(hello);
  assert.deepEqual(sent[0], sent[1]);

  h.run(`Date.now = () => ${time + 60_000}`);
  h.timers.find(timer => timer.ms === 60_000).callback();
  assert.equal(sent.at(-1).message.payload, null);
  assert.equal(h.run("state.fixturePlan.plan.plan_id"), inspection.plan.plan_id);
  assert.equal(h.approvals.length, 0);
  assert.doesNotMatch(harness().run('setPage("twin"); simulationFrame()'), /planPreview=fixture/);
});

test("the fixture binds an explicitly approved candidate to the Runtime run and reported progress fields", async () => {
  const h = inspectionConsole();
  const { completed_run: completed, failed_run: failed, plan } = inspection;
  await h.read(completed.before);
  assert.match(h.run("overviewPage()"), /Runtime 尚无任务执行/);
  assert.doesNotMatch(h.run("overviewPage()"), /<progress|mission-coverage-grid/);
  await h.run("validateFixtureCandidate()");
  assert.match(h.html("mission-fixture-candidate"), /测试桩 · 设备巡检导航.*fake-target-001-patrol-v1.*UAV-02.*N\/E\/D.*人工确认与执行/s);
  assert.equal(h.approvals.length, 0);
  await h.run('confirmFixtureExecution("   ")');
  assert.match(h.html("mission-fixture-candidate"), /请填写操作员 ID 后再确认/);
  assert.equal(h.approvals.length, 0);

  const submission = h.run('confirmFixtureExecution(" fake-acceptance-operator ")');
  await h.run('confirmFixtureExecution("fake-acceptance-operator")');
  assert.deepEqual(h.approvals, [{ plan, operator_id: "fake-acceptance-operator", decision: "approve" }]);
  assert.match(h.html("mission-fixture-candidate"), /等待执行回执/);
  await h.read(completed.starting);
  assert.match(h.run("missionMapPanel()"), /0 \/ 5 个航点.*等待覆盖证据/s);
  assert.doesNotMatch(h.run("missionMapPanel()"), /mission-coverage-grid/);
  await h.read(completed.first_arrival);
  const map = h.run("missionMapPanel()");
  assert.match(map, /1 \/ 5 个航点/);
  assert.match(map, /mission-coverage-grid/);
  assert.ok(map.includes(completed.first_arrival.coverage_pct.toFixed(2) + "%"));
  assert.ok(map.includes(completed.receipt.run_id));
  assert.match(h.run("overviewPage()"), /测试桩 · 设备巡检导航/);

  await h.read(completed.before_land);
  assert.match(h.run("missionMapPanel()"), /· 执行中.*100%.*5 \/ 5 个航点/s);
  await h.read(completed.progress);
  h.respond(completed.receipt);
  await submission;
  assert.match(h.html("mission-fixture-candidate"), /执行已完成/);
  assert.ok(h.html("mission-fixture-progress").includes(completed.receipt.run_id));
  assert.match(h.html("mission-fixture-progress"), /已完成 · 已验证航点 5 \/ 5/);
  await h.read(failed.progress);
  assert.match(h.run("fixtureProgressContent()"), /等待 Runtime 上报本次任务进度/);
  assert.match(h.run("missionMapPanel()"), /· 失败.*1 \/ 5 个航点/s);
});

test("LIVE overview and stage reject contradictory area evidence and retain verified waypoints", () => {
  const report = inspection.completed_run.first_arrival;
  const { coverage } = report;
  const coveredRate = report.coverage_pct.toFixed(2) + "%";
  const conflicts = {
    foreignReport: { ...report, map_version: "foreign-map" },
    foreignArea: { ...report, area_id: "another-area" },
    topLevelArea: { ...report, area_covered_km2: report.area_covered_km2 * 2 },
    topLevelRate: { ...report, coverage_pct: 99 },
    reportRate: { ...report, coverage: { ...coverage, completion_pct: 99 } },
    foreignGrid: { ...report, coverage: { ...coverage, grid: { ...coverage.grid, map_version: "foreign-map" } } },
    inconsistentCells: { ...report, coverage: { ...coverage, grid: { ...coverage.grid, covered_cells: [] } } },
  };
  const summaryOnly = {
    ...report, coverage_pct: null, coverage: { ...coverage, completion_pct: null, grid: null },
  };
  const observedZero = {
    ...report, area_covered_km2: 0, coverage_pct: 0,
    coverage: { ...coverage, area_covered_km2: 0, completion_pct: 0, grid: { ...coverage.grid, covered_cells: [] } },
  };

  for (const href of ["http://127.0.0.1:5178/", "http://127.0.0.1:5178/?mode=stage&source=live"]) {
    const h = harness(href);
    const render = value => {
      h.run(`state.apiStatus="live"; updateMissionDashboard({ missionProgress: { status: "fulfilled", value: ${JSON.stringify(value)} } });`);
      if (!href.includes("mode=stage")) return h.run("overviewPage()");
      h.run("renderStage()");
      return h.html("stage-content");
    };

    const matching = render(report);
    assert.ok(matching.includes(`面积覆盖率</span><b>${coveredRate}</b>`));
    assert.match(matching, /mission-coverage-grid/);
    const noGrid = render(summaryOnly);
    assert.ok(noGrid.includes(`面积覆盖率</span><b>${coveredRate}</b>`));
    assert.doesNotMatch(noGrid, /mission-coverage-grid/);
    const validZero = render(observedZero);
    assert.ok(validZero.includes("面积覆盖率</span><b>0%</b>"));
    assert.match(validZero, /已有观测，当前没有覆盖记录/);

    for (const [issue, conflicting] of Object.entries(conflicts)) {
      const html = render(conflicting);
      assert.ok(html.includes("面积覆盖率</span><b>—</b>"), `${issue} on ${href}`);
      assert.match(html, /1 \/ 5 个航点/);
      assert.doesNotMatch(html, /mission-coverage-grid/);
      assert.equal(h.run("state.mission.areaCovered"), null);
      assert.equal(h.run("state.mission.areaTotal"), null);
    }
  }
});

test("the planning fixture refuses ambiguous, unsupported and cross-map candidates before approval", async () => {
  const h = inspectionConsole();
  h.run('setTemplatePlanObjective("巡检模拟设备")');
  await h.run("validateFixtureCandidate()");
  assert.match(h.html("mission-fixture-candidate"), /请明确巡检样例的设备标记/);
  assert.doesNotMatch(h.html("mission-fixture-candidate"), /确认并执行/);

  h.run(`setTemplatePlanObjective(${JSON.stringify(inspectionObjective)})`);
  for (const plan of [
    { ...inspection.plan, map_version: "another-map" },
    { ...inspection.plan, execution_authorized: true },
    { ...inspection.plan, steps: [...inspection.plan.steps, { step_id: "observe", action_type: "observe", node_id: "UAV-02" }] },
    { ...inspection.plan, steps: inspection.plan.steps.map(step => ({ ...step, status: "dry_run_only" })) },
  ]) {
    h.api.missionFixture.validateCandidate = async () => ({ result: "validated", plan });
    await h.run("validateFixtureCandidate()");
    assert.match(h.html("mission-fixture-candidate"), /缺少已校验的载具、航点或场景版本/);
    await h.run('confirmFixtureExecution("fake-acceptance-operator")');
  }
  assert.equal(h.approvals.length, 0);
  h.api.missionFixture.validateCandidate = h.validateCandidate;
  await h.run("validateFixtureCandidate()");
  h.run('setTemplatePlanObjective("修改后的任务")');
  await h.run('confirmFixtureExecution("fake-acceptance-operator")');
  assert.equal(h.approvals.length, 0);
  const regularConsole = harness();
  assert.match(regularConsole.run("planningPage()"), /等待算法提供校验过的载具分工/);
  assert.doesNotMatch(regularConsole.run("planningPage()"), /确认并执行/);
});

test("a receipt lacking run identity cannot claim progress from a matching plan id", async () => {
  const h = inspectionConsole();
  const { completed_run: completed } = inspection;
  await h.run("validateFixtureCandidate()");
  const submitted = h.run('confirmFixtureExecution("fake-acceptance-operator")');
  h.respond({ ...completed.receipt, run_id: undefined });
  await submitted;
  await h.read(completed.progress);
  assert.match(h.run("fixtureProgressContent()"), /回执未提供运行 ID/);
  assert.doesNotMatch(h.run("fixtureProgressContent()"), /5 \/ 5/);
});

test("a failed run keeps its verified partial evidence and unsuccessful reads clear current progress", async () => {
  const h = inspectionConsole();
  const { completed_run: completed, failed_run: failed } = inspection;
  await h.run("validateFixtureCandidate()");
  const submitted = h.run('confirmFixtureExecution("fake-acceptance-operator")');
  h.respond(failed.receipt);
  await submitted;
  await h.read(failed.progress);
  assert.match(h.run("fixtureCandidateContent()"), /执行失败 · arrival_timeout.*中止步骤/s);
  assert.match(h.run("fixtureProgressContent()"), /失败 · 已验证航点 1 \/ 5/);
  assert.match(h.run("missionMapPanel()"), /1 \/ 5 个航点/);

  await h.read({ ...failed.progress, coverage: { ...failed.progress.coverage, map_version: "foreign-map" } });
  assert.match(h.run("missionMapPanel()"), /1 \/ 5 个航点.*等待覆盖证据/s);
  assert.doesNotMatch(h.run("missionMapPanel()"), /mission-coverage-grid/);

  for (const [report, label] of [
    [new Error("fixture read failure"), /Runtime 任务进度读取失败/],
    [{ ...completed.progress, run_id: null }, /Runtime 任务进度证据不完整/],
    [{ ...completed.progress, mode: "DEMO" }, /Runtime 任务进度证据不完整/],
    [completed.before, /Runtime 尚无任务执行/],
  ]) {
    await h.read(report);
    const home = h.run("overviewPage()");
    assert.match(home, label);
    assert.doesNotMatch(home, /<progress|mission-coverage-grid|fake-target-001-patrol-v1/);
  }
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
  h.run(`state.mission={id:"fixture",title:"Fixture",completion:30}; state.missionStatus="live";
    applyApiFailure("health", {kind:"network", message:"offline"}, false);`);
  assert.match(h.run("missionIndicators()"), /最后上报 · 当前进度未知/);
  assert.doesNotMatch(h.run("missionIndicators()"), /mission-kpi red|30%/);
  h.run('state.apiStatus = "live"');
  assert.doesNotMatch(h.run("missionIndicators()"), /30%/);
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
  assert.match(h.run("planningPage()"), /填写任务目标后可生成只读预览/);
  assert.doesNotMatch(h.run("planningPage()"), /18 条策略|42 \/ 100|下发任务|DEMO · 界面预览/);
});
