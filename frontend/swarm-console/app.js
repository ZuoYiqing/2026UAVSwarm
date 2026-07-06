const navItems = [
  ["overview", "总览驾驶舱", "OV"],
  ["planning", "任务规划", "PL"],
  ["twin", "三维集群态势", "3D"],
  ["vehicle", "单机详情", "UA"],
  ["runtime", "Agent Runtime", "AR"],
  ["policy", "Policy Gate", "PG"],
  ["skills", "Skills 能力库", "SK"],
  ["backend", "Adapter / Backend", "AB"],
  ["simulation", "仿真中心", "SM"],
  ["assets", "硬件资产", "HW"],
  ["replay", "Audit / Replay", "RP"],
  ["model", "模型与知识", "MK"],
  ["settings", "系统设置", "ST"],
];

const state = {
  page: "overview",
  backendConnected: true,
  currentAction: "TAKEOFF",
  altitude: 18,
  maxAltitude: 20.4,
  lastZ: -19.8,
  thresholdReached: true,
  missionCount: 3,
  successRate: 96.3,
  policyBlocks: 18,
  linkIssues: 2,
  activeTrace: "trc_8f3a2c91",
  selectedUav: "UAV-01",
  replayIndex: 4,
  simRunning: true,
  toast: [],
};

const events = [
  ["14:30:55", "SYSTEM", "Backend 切换完成：AUTO -> MISSION", "cyan"],
  ["14:31:20", "TIMEOUT", "UAV-05 心跳超时，持续 15s", "red"],
  ["14:31:44", "LINK_WARNING", "UAV-09 链路质量下降，RSSI -112 dBm", "amber"],
  ["14:31:58", "ACTION_RESULT", "UAV-01 执行 TakePhoto 成功", "green"],
  ["14:32:12", "POLICY_DECISION_EVENT", "Policy 拦截 ACTION_REQUEST，决策 DENY", "violet"],
  ["14:32:15", "ACTION_REQUEST", "UAV-03 请求执行 TakePhoto", "cyan"],
];

function pushEvent(type, message, color = "cyan") {
  const now = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  events.unshift([now, type, message, color]);
  if (events.length > 8) {
    events.pop();
  }
}

function notify(title, body, color = "cyan") {
  state.toast.unshift({ title, body, color, id: Date.now() });
  state.toast = state.toast.slice(0, 3);
  window.setTimeout(() => {
    state.toast = state.toast.filter((item) => Date.now() - item.id < 4200);
    render();
  }, 4200);
}

const vehicles = [
  ["UAV-01", "在线", "巡检-北区", "78%", "强", "1.2 km"],
  ["UAV-02", "在线", "巡检-北区", "64%", "强", "1.6 km"],
  ["UAV-03", "在线", "拍照-园区", "81%", "强", "1.8 km"],
  ["UAV-04", "在线", "归巢-西区", "52%", "中", "2.3 km"],
  ["UAV-05", "告警", "续航-南区", "18%", "弱", "2.6 km"],
  ["UAV-06", "在线", "中继-西区", "69%", "强", "1.9 km"],
  ["UAV-07", "在线", "扫描-园区", "73%", "强", "2.0 km"],
  ["UAV-09", "告警", "侦察-南区", "12%", "弱", "2.9 km"],
];

const capabilities = [
  ["起飞", "takeoff", "中风险", "PX4 MAVLink", "98.7%"],
  ["前往航点", "goto", "中风险", "PX4 MAVLink", "97.2%"],
  ["悬停", "hover", "低风险", "fake / mavlink", "99.1%"],
  ["降落", "land", "中风险", "PX4 MAVLink", "98.3%"],
  ["返航", "return_home", "低风险", "PX4 MAVLink", "96.4%"],
  ["拍照", "camera_capture", "低风险", "payload", "99.0%"],
  ["云台角度", "gimbal_set_angle", "中风险", "payload", "97.9%"],
  ["喊话播放", "speaker_play_message", "中风险", "payload", "94.6%"],
];

const app = document.getElementById("app");

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function badge(text, color = "cyan") {
  return `<span class="badge ${color}">${esc(text)}</span>`;
}

function metric(title, value, detail, color = "cyan") {
  return `<section class="metric">
    <label>${esc(title)}</label>
    <b class="${color}">${esc(value)}</b>
    <div class="delta ${color}">${esc(detail)}</div>
  </section>`;
}

function panel(title, body, extra = "") {
  return `<section class="panel ${extra}">
    <div class="panel-title"><h2>${title}</h2></div>
    ${body}
  </section>`;
}

function toastStack() {
  if (!state.toast.length) return "";
  return `<div class="toast-stack">${state.toast.map((item) => `
    <div class="toast">
      <b class="${item.color}">${esc(item.title)}</b>
      <div class="small">${esc(item.body)}</div>
    </div>`).join("")}</div>`;
}

function spark(color = "#36c7f4") {
  const points = "0,38 18,30 36,35 54,20 72,26 90,14 108,19 126,8 144,13 162,6 180,11";
  return `<svg class="sparkline" viewBox="0 0 180 48" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" />
  </svg>`;
}

function scene3d(size = "full") {
  return `<div class="three-scene ${size}">
    <div class="scene-label">
      ${badge("Cesium 3D Tiles 接入位", "cyan")}
      ${badge("任务区 MISSION-ALPHA", "green")}
      ${badge("限高 120m", "amber")}
    </div>
    <div class="scene-plane"></div>
    <div class="building b1"></div><div class="building b2"></div><div class="building b3"></div><div class="building b4"></div><div class="building b5"></div>
    <div class="zone red"></div><div class="zone amber"></div><div class="zone green"></div>
    <svg class="scene-svg" viewBox="0 0 1000 600">
      <path class="path cyan" d="M250 178 C380 240 424 306 505 290 C604 270 633 202 705 196" />
      <path class="path green" d="M508 296 C492 382 554 455 648 412 C734 370 780 428 842 386" />
      <path class="path amber" d="M503 306 C416 356 376 418 293 395 C230 377 183 432 164 492" />
      <path class="path cyan" d="M503 298 C384 284 310 220 208 246" />
    </svg>
    <div class="alt-column a1" data-alt="60m"></div>
    <div class="alt-column a2" data-alt="120m"></div>
    <div class="alt-column a3" data-alt="42m"></div>
    <div class="cluster-node"><span>CLUSTER-01</span></div>
    <div class="uav u1"><span>UAV-07</span></div>
    <div class="uav u2"><span>UAV-03</span></div>
    <div class="uav u3"><span>UAV-02</span></div>
    <div class="uav u4"><span>UAV-05</span></div>
    <div class="uav u5"><span>UAV-09</span></div>
    <div class="uav u6"><span>UAV-06</span></div>
  </div>`;
}

function eventList() {
  return `<div class="event-list">${events.map((e) => `
    <div class="event">
      <div class="time">${e[0]}</div>
      <div><strong class="${e[3]}">${e[1]}</strong><span class="small">${e[2]}</span></div>
    </div>`).join("")}</div>`;
}

function vehicleTable() {
  return `<table class="table">
    <thead><tr><th>ID</th><th>状态</th><th>任务</th><th>电量</th><th>链路</th><th>距离</th></tr></thead>
    <tbody>${vehicles.map((v) => `
      <tr><td>${v[0]}</td><td>${badge(v[1], v[1] === "告警" ? "red" : "green")}</td><td>${v[2]}</td><td>${v[3]}</td><td>${v[4]}</td><td>${v[5]}</td></tr>
    `).join("")}</tbody>
  </table>`;
}

function overviewPage() {
  return `<div class="page">
    ${pageTitle("总览驾驶舱", "三维态势 · Runtime 执行链路 · 策略安全 · 审计回放")}
    <div class="metrics">
      ${metric("在线节点数", "37 / 48", "较昨日 +5", "cyan")}
      ${metric("当前任务数", state.missionCount, `运行中 ${state.missionCount} / 计划 5`, "blue")}
      ${metric("执行成功率", `${state.successRate.toFixed(1)}%`, "近 24h +2.1%", "green")}
      ${metric("Policy 拦截次数", state.policyBlocks, "近 24h +3", "violet")}
      ${metric("链路异常数", state.linkIssues, "近 24h -1", "amber")}
      ${metric("Backend 模式", "MISSION", "主用", "cyan")}
    </div>
    <div class="main-overview">
      ${panel("三维任务态势预览", scene3d(), "h-fill")}
      ${panel("最近动作记录 / 事件流", `<p class="small">点击 Check Backend、Smoke Test、Land、策略预检、故障注入后会写入这里。</p>${eventList()}`, "h-fill scroll")}
    </div>
    ${runtimeChain(true)}
  </div>`;
}

function pageTitle(title, subtitle, actions = "") {
  return `<div class="page-title">
    <h1>${esc(title)}</h1>
    <p>${esc(subtitle)}</p>
    <div class="page-actions">${actions}</div>
  </div>`;
}

function runtimeChain(compact = false) {
  const cards = [
    ["任务输入", "3", "NEW"],
    ["Agent Runtime", "37", "ACTIVE"],
    ["Policy Gate", "18", "TODAY"],
    ["Skill Router", "145", "ROUTED"],
    ["Adapter Gateway", "6", "ADAPTERS"],
    ["MAVLink / Hardware", "37", "NODES"],
    ["Action Result", "96.3%", "SUCCESS"],
    ["Audit / Replay", "ON", "TRACE"],
  ];
  return panel("Agent Runtime 执行链路（实时）", `<div class="runtime-chain">${cards.map((c, i) => `
    <div class="chain-card">
      <h3>${c[0]}</h3>
      <b class="${i === 2 ? "violet" : i > 5 ? "green" : "cyan"}">${c[1]}</b>
      <span class="small">${c[2]}</span>
    </div>`).join("")}</div>`, compact ? "" : "h-fill");
}

function twinPage() {
  return `<div class="page">
    ${pageTitle("三维集群态势", "Cesium 3D Tiles · 倾斜摄影接入位 · 多机任务态势")}
    <div class="two-main" style="grid-template-columns:1.42fr .58fr">
      ${panel("三维 Mission Twin", scene3d(), "h-fill")}
      <div class="grid" style="grid-template-rows:auto 1fr">
        <div class="metrics" style="grid-template-columns:repeat(3,1fr)">
          ${metric("在线节点", "37/48", "77%", "cyan")}
          ${metric("执行成功率", "96.3%", "近 24h", "green")}
          ${metric("策略生效数", "18", "今日", "violet")}
        </div>
        ${panel("节点列表", vehicleTable(), "scroll")}
      </div>
    </div>
    <div class="split-2" style="grid-template-columns:1.15fr .85fr">
      ${vehicleDiagramPanel()}
      ${panel("遥测与告警", `<div class="cols-4">
        ${telemetryCard("电量", "78%", "#36c7f4")}
        ${telemetryCard("电压", "22.8V", "#42d883")}
        ${telemetryCard("温度", "42°C", "#ff5e5e")}
        ${telemetryCard("RSSI", "-58 dBm", "#42d883")}
      </div>`, "")}
    </div>
  </div>`;
}

function planningPage() {
  return `<div class="page">
    ${pageTitle("任务规划", "自然语言生成任务 · 结构化编排 · 策略预检 · 仿真预演", `
      <button class="button primary" onclick="generateRequest()">生成请求</button><button class="button" onclick="policyPrecheck()">策略预检</button><button class="button" onclick="simulationPreview()">仿真预演</button><button class="button success" onclick="dispatchMission()">下发任务</button>
    `)}
    <div class="three-main">
      <div class="grid">
        ${panel("1 任务输入（自然语言）", `<div class="field"><textarea rows="8">在东区工业园执行巡检任务，重点检查 3 号仓库和周边围墙，识别异常人员与车辆。发现火点后立即上报并拍照取证，优先保证人员安全。</textarea></div>
          <div class="mini-tabs" style="margin-top:10px"><span class="chip">园区巡检</span><span class="chip">边界巡逻</span><span class="chip">应急搜救</span><span class="chip">消防侦察</span></div>`)}
        ${panel("地图预览", scene3d("small"), "")}
      </div>
      <div class="grid" style="grid-template-rows:1.05fr .95fr">
        ${panel("2 任务编排（结构化任务图）", flowGraph(), "")}
        ${panel("3 请求预览（JSON）", `<pre class="json">${esc(JSON.stringify(sampleActionRequest(), null, 2))}</pre>`, "scroll")}
      </div>
      <div class="grid">
        ${panel("4 策略预检（Policy Gate）", `<div class="donut"><div class="donut-inner"><b class="green">通过</b><span class="small">18 条策略</span></div></div>
          ${checkList(["飞行安全策略", "空域合规策略", "数据安全策略", "设备健康策略"])}`)}
        ${panel("5 风险评估", `<h2 class="amber">中等风险 42 / 100</h2>${checkList(["夜间飞行：需确认照明条件", "人员密集区：建议提高告警阈值", "电量窗口：建议预留 15% 余量"])}`)}
        ${panel("6 目标节点选择", vehicleTable(), "scroll")}
      </div>
    </div>
  </div>`;
}

function flowGraph() {
  const nodes = [
    ["开始", 6, 42, "green"], ["起飞 TakeOff", 22, 25, ""], ["航线巡检 Patrol", 42, 25, ""],
    ["异常识别 Detect", 66, 19, "violet"], ["热源定位", 67, 49, "violet"], ["拍照取证", 83, 49, "violet"],
    ["返航 RTL", 47, 72, ""], ["结束", 13, 76, "green"],
  ];
  return `<div class="flow-canvas">
    <svg class="scene-svg" viewBox="0 0 1000 420">
      <path class="path cyan" d="M140 190 L260 150 L460 150 L650 130 L720 220 L840 220" />
      <path class="path green" d="M690 250 L520 325 L210 335" />
    </svg>
    ${nodes.map((n) => `<div class="node ${n[3]}" style="left:${n[1]}%;top:${n[2]}%">${n[0]}</div>`).join("")}
  </div>`;
}

function checkList(items) {
  return `<div class="event-list">${items.map((item) => `<div class="event" style="grid-template-columns:24px 1fr"><div class="green">OK</div><div>${esc(item)}</div></div>`).join("")}</div>`;
}

function sampleActionRequest() {
  return {
    action_request: {
      mission_id: "M-20260705-001",
      action_type: "takeoff",
      skill_group: "flight_core",
      target_set: ["UAV-01", "UAV-02", "UAV-03"],
      requested_scope: "self_only",
      risk_hint: 2,
      params: { altitude_m: 20, area: "east_industrial_park" },
    },
  };
}

function vehiclePage() {
  return `<div class="page">
    ${pageTitle("单机详情 / UAV-01", "飞控状态 · MAVLink · 载荷模块 · 遥测曲线")}
    <div class="split-2" style="grid-template-columns:1fr 1fr">
      ${panel("局部三维态势", scene3d(), "h-fill")}
      ${panel("集群节点", vehicleTable(), "scroll")}
    </div>
    <div class="split-2" style="grid-template-columns:1.05fr .95fr">
      ${vehicleDiagramPanel()}
      <div class="grid">
        <div class="cols-4">
          ${statusTile("运行状态", "飞行中", "空速 12.6 m/s · 高度 152m AGL", "green")}
          ${statusTile("权限", "本机授权", "Operator_01 · L2", "green")}
          ${statusTile("自主状态", "自治运行", "L3 · Planner-Agent", "cyan")}
          ${statusTile("链路状态", "链路强", "5G / Mesh · RSSI -58 dBm", "green")}
        </div>
        <div class="cols-4">
          ${telemetryCard("max_altitude_m", state.maxAltitude.toFixed(1), "#36c7f4")}
          ${telemetryCard("last_z", state.lastZ.toFixed(1), "#42d883")}
          ${telemetryCard("threshold_reached", String(state.thresholdReached), "#f5b84c")}
          ${telemetryCard("current status", `AUTO.${state.currentAction}`, "#9a7cff")}
        </div>
      </div>
    </div>
  </div>`;
}

function vehicleDiagramPanel() {
  return panel("单机模块健康", `<div class="vehicle-diagram">
    <div class="drone-arm a"></div><div class="drone-arm b"></div><div class="drone-body"></div>
    <div class="rotor r1"></div><div class="rotor r2"></div><div class="rotor r3"></div><div class="rotor r4"></div>
    <div class="module-tile m1"><b>飞控</b><br><span class="green">正常</span><br><span class="small">温度 42°C</span></div>
    <div class="module-tile m2"><b>伴随计算板</b><br><span class="green">正常</span><br><span class="small">负载 48%</span></div>
    <div class="module-tile m3"><b>相机 / 云台</b><br><span class="green">正常</span><br><span class="small">存储 64%</span></div>
    <div class="module-tile m4"><b>电源系统</b><br><span class="green">正常</span><br><span class="small">电量 78%</span></div>
  </div>`);
}

function telemetryCard(title, value, color) {
  return `<section class="panel"><div class="small">${esc(title)}</div><h2 style="margin:8px 0;color:${color}">${esc(value)}</h2>${spark(color)}</section>`;
}

function telemetrySummary() {
  return `<div class="cols-4">
    ${telemetryCard("max_altitude_m", state.maxAltitude.toFixed(1), "#36c7f4")}
    ${telemetryCard("last_z", state.lastZ.toFixed(1), "#42d883")}
    ${telemetryCard("threshold_reached", String(state.thresholdReached), "#f5b84c")}
    ${telemetryCard("current status", `AUTO.${state.currentAction}`, "#9a7cff")}
  </div>`;
}

function statusTile(title, value, detail, color) {
  return `<section class="panel"><div class="small">${esc(title)}</div><h2 class="${color}" style="margin:8px 0">${esc(value)}</h2><div class="small">${esc(detail)}</div></section>`;
}

function runtimePage() {
  return `<div class="page">
    ${pageTitle("Agent Runtime", "任务队列 · 上下文构建 · Planner · Policy · Adapter · Audit")}
    <div class="metrics">
      ${metric("当前 Trace ID", state.activeTrace, "开始时间 14:31:58", "violet")}
      ${metric("活跃会话数", "18 / 36", "在线率 50%", "cyan")}
      ${metric("队列任务总数", "142", "等待中 27", "amber")}
      ${metric("最近执行成功率", "96.3%", "近 24h", "green")}
      ${metric("端到端 P95 延迟", "1.23s", "-0.21s", "green")}
      ${metric("系统负载", "42%", "CPU", "cyan")}
    </div>
    ${runtimeChain()}
    <div class="split-2 h-fill" style="grid-template-columns:1fr .52fr">
      <div class="split-3">
        ${panel("会话状态", `<table class="table"><tr><td>会话 ID</td><td>sess_7b1e9a2c</td></tr><tr><td>状态</td><td>${badge("运行中", "green")}</td></tr><tr><td>触发源</td><td>ACTION_REQUEST</td></tr><tr><td>TTL</td><td>02:13</td></tr></table>`)}
        ${panel("上下文存储", `<div class="donut"><div class="donut-inner"><b>92.4%</b><span class="small">命中率</span></div></div>`)}
        ${panel("执行延迟 P95", `<table class="table"><tr><td>Context</td><td>186ms</td></tr><tr><td>Planner</td><td>1.02s</td></tr><tr><td>Policy Gate</td><td>38ms</td></tr><tr><td>Adapter</td><td>412ms</td></tr></table>`)}
      </div>
      ${panel("当前选中执行详情", `<pre class="json">${esc(JSON.stringify({
        trace_id: state.activeTrace,
        session_id: "sess_7b1e9a2c",
        type: "ACTION_REQUEST",
        task: "UAV-03 执行 TakePhoto",
        planner_output: "PLAN_TAKEPHOTO_V2",
        adapter: "Planner-Agent",
        status: "SUCCESS",
      }, null, 2))}</pre><button class="button primary">查看完整 Payload</button>`, "scroll")}
    </div>
  </div>`;
}

function policyPage() {
  const rows = [
    ["14:32:15", "ALLOW", "UAV-03", "TAKE_PHOTO", "LOW", "OPERATOR"],
    ["14:32:12", "DENY", "UAV-01", "ENTER_NO_FLY_ZONE", "HIGH", "SYSTEM"],
    ["14:31:58", "REQUIRE_CONFIRM", "UAV-07", "FOLLOW_TARGET", "MEDIUM", "DELEGATED"],
    ["14:31:45", "PREEMPT", "UAV-02", "LAND", "LOW", "OPERATOR"],
    ["14:31:28", "DEFER", "UAV-05", "SWARM_RECONFIGURE", "MEDIUM", "SYSTEM"],
  ];
  return `<div class="page">
    ${pageTitle("Policy Gate", "Safe · Deterministic · Explainable Decisions", `<button class="button primary">策略配置中心</button><button class="button">Policy Simulator</button>`)}
    <div class="metrics">
      ${metric("总决策数(24h)", "18,762", "+8.6%", "cyan")}
      ${metric("ALLOW 允许", "14,251", "76.0%", "green")}
      ${metric("DENY 拒绝", "2,163", "11.5%", "red")}
      ${metric("REQUIRE_CONFIRM", "1,248", "6.6%", "amber")}
      ${metric("PREEMPT", "812", "4.3%", "violet")}
      ${metric("DEFER", "288", "1.5%", "blue")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.12fr .88fr">
      ${panel("决策监控 / Decision Monitor", `<table class="table"><thead><tr><th>时间</th><th>决策</th><th>节点</th><th>Action</th><th>Risk</th><th>Authority</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${r[0]}</td><td>${badge(r[1], decisionColor(r[1]))}</td><td>${r[2]}</td><td>${r[3]}</td><td>${badge(r[4], r[4] === "HIGH" ? "red" : r[4] === "MEDIUM" ? "amber" : "green")}</td><td>${r[5]}</td></tr>`).join("")}</tbody></table>`, "scroll")}
      <div class="grid">
        ${panel("决策对比 / Decision Comparison", `<div class="split-2"><pre class="json">${esc(JSON.stringify({ requested_scope: "self_only", action: "TAKE_PHOTO", altitude_m: 120 }, null, 2))}</pre><pre class="json">${esc(JSON.stringify({ effective_scope: "self_only", decision_code: "ALLOW", mitigations: ["ALTITUDE_LIMIT", "GEO_FENCE_PASS"] }, null, 2))}</pre></div>`)}
        ${panel("约束与交接", `${checkList(["GEO_FENCE_PASS", "MAX_ALTITUDE <= 120m", "PAYLOAD_ALLOWED(CAM-01)", "LINK_STABILITY_OK"])}`)}
        ${panel("决策说明", `<pre class="json">${esc(JSON.stringify({
          reason_code: "ALTITUDE_ABOVE_THRESHOLD",
          error_code: null,
          policy_trace_id: "ptr_8f3c1a7e5c2b",
          audit_tags: ["mission:M-0045", "node:UAV-03", "backend:MISSION"],
        }, null, 2))}</pre>`)}
      </div>
    </div>
  </div>`;
}

function decisionColor(code) {
  return { ALLOW: "green", DENY: "red", REQUIRE_CONFIRM: "amber", PREEMPT: "violet", DEFER: "cyan" }[code] || "cyan";
}

function backendPage() {
  return `<div class="page">
    ${pageTitle("Adapter 与 Backend 管理", "PX4 SITL · MAVLink · Fake Adapter · Hardware Backend")}
    <div class="grid" style="grid-template-columns:.92fr 1.18fr auto">
      ${panel("Backend 模式", `<div class="mini-tabs"><span class="chip">FAKE</span><span class="chip active">SITL(PX4)</span><span class="chip">HARDWARE</span></div>`)}
      ${panel("传输与端点配置", `<div class="form-grid"><div class="field"><label>gRPC Endpoint</label><input value="grpc://10.42.0.12:50051"></div><div class="field"><label>MAVLink Endpoint</label><input value="udpin:127.0.0.1:14540"></div><div class="field"><label>WS / Telemetry</label><input value="ws://10.42.0.12:8765"></div></div>`)}
      <button class="button primary" onclick="checkBackend()">Check Backend</button>
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.12fr .88fr">
      <div class="grid">
        ${panel("Adapter 连接拓扑", adapterTopology())}
        <div class="cols-4">
          ${statusTile("exec_unavailable", "12", "24h -2", "red")}
          ${statusTile("smoke_not_connected", "9", "24h +3", "violet")}
          ${statusTile("backend_probe_failed", "5", "24h -1", "red")}
          ${statusTile("ack_failed", "4", "24h", "amber")}
        </div>
      </div>
      <div class="grid">
        ${panel("Backend 健康与探测", `<table class="table"><tr><th>Backend</th><th>状态</th><th>Probe</th><th>延迟</th></tr><tr><td>Fake Backend</td><td>${badge("RUNNING", "green")}</td><td>OK</td><td>1ms</td></tr><tr><td>px4_sitl_backend</td><td>${badge(state.backendConnected ? "RUNNING" : "FAILED", state.backendConnected ? "green" : "red")}</td><td>${state.backendConnected ? "OK" : "FAILED"}</td><td>6ms</td></tr><tr><td>hardware_backend</td><td>${badge("STANDBY", "amber")}</td><td>N/A</td><td>-</td></tr></table>`)}
        ${panel("Action 控制", `<div class="form-grid"><div class="field"><label>目标 Backend</label><select><option>px4_sitl_backend</option></select></div><div class="field"><label>altitude_m</label><input value="${state.altitude.toFixed(1)}"></div><div class="field"><label>超时(s)</label><input value="10"></div></div><button class="button primary" style="margin-top:10px" onclick="runSmokeTakeoff()">Smoke Takeoff</button> <button class="button warn" onclick="runLand()">Land</button> ${badge(state.thresholdReached ? "SUCCESS" : "RUNNING", state.thresholdReached ? "green" : "amber")}`)}
        ${panel("Telemetry 显示", telemetrySummary())}
        ${panel("Action Result JSON", `<pre class="json">${esc(JSON.stringify({
          backend: "px4_sitl_backend",
          action_type: state.currentAction,
          status: "SUCCESS",
          arm_ack: true,
          takeoff_ack: true,
          land_ack: false,
          result: { altitude: state.altitude, max_altitude_m: state.maxAltitude, last_z: state.lastZ, threshold_reached: state.thresholdReached, mode: `AUTO.${state.currentAction}` },
        }, null, 2))}</pre>`, "scroll")}
        ${panel("最近动作记录", eventList(), "scroll")}
      </div>
    </div>
  </div>`;
}

function adapterTopology() {
  const adapters = ["Fake Adapter", "MAVLink Adapter", "Payload Adapter", "Perception Adapter", "GPIO/UART Adapter"];
  return `<div class="cols-4" style="grid-template-columns:repeat(5,1fr)">${adapters.map((a) => `<div class="chain-card"><h3>${a}</h3>${badge("RUNNING", "green")}<br><span class="small">v1.${Math.floor(Math.random()*5)}.0 · CPU 4%</span></div>`).join("")}</div>
  <div class="runtime-chain" style="grid-template-columns:repeat(3,1fr);margin-top:12px">
    <div class="chain-card"><h3>fake_backend</h3>${badge("RUNNING", "green")}</div>
    <div class="chain-card"><h3>px4_sitl_backend</h3>${badge("RUNNING", "green")}</div>
    <div class="chain-card"><h3>hardware_backend</h3>${badge("STANDBY", "amber")}</div>
  </div>`;
}

function checkBackend() {
  state.backendConnected = true;
  pushEvent("BACKEND_CHECK", "px4_sitl_backend 探测成功：backend_connected", "green");
  notify("Backend Connected", "endpoint udpin:127.0.0.1:14540 返回 backend_connected", "green");
  render();
}

function replayPage() {
  const replayRows = [
    ["14:30:00.125", "MISSION_REQUEST", "Planner-Agent", "MISSION 创建请求", "MSG-000001"],
    ["14:30:00.532", "ACTION_REQUEST", "Planner-Agent", "UAV-03 请求执行 TakePhoto", "MSG-000002"],
    ["14:30:00.912", "POLICY_DECISION_EVENT", "Policy Gate", "策略决策：ALLOW", "MSG-000003"],
    ["14:30:01.301", "ADAPTER_EXECUTION", "Adapter-Gateway", "分发到 UAV-03 适配器", "MSG-000004"],
    ["14:30:01.842", "ACTION_RESULT", "UAV-03", "执行成功：TakePhoto", "MSG-000006"],
    ["14:30:05.412", "FAULT", "UAV-05", "电量低于阈值告警 LOW_BATTERY", "MSG-000015"],
  ];
  return `<div class="page">
    ${pageTitle("Audit / Replay", "任务审计与回放 · 事件溯源 · 三维态势复盘", `<button class="button">导出报告</button><button class="button">下载日志</button><button class="button primary">分享链接</button>`)}
    <div class="grid" style="grid-template-columns:repeat(5,1fr)">
      ${metric("事件总数", "128", "mission-20260705", "cyan")}
      ${metric("成功", "120", "93.8%", "green")}
      ${metric("失败", "3", "2.3%", "red")}
      ${metric("超时", "2", "1.6%", "amber")}
      ${metric("涉及节点", "12", "UAV / GCS", "violet")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.22fr .78fr">
      ${panel("事件时间线（按时间排序）", `<table class="table"><thead><tr><th>时间</th><th>类型</th><th>节点</th><th>事件 / 消息</th><th>消息 ID</th></tr></thead><tbody>${replayRows.map((r) => `<tr><td>${r[0]}</td><td>${badge(r[1], eventColor(r[1]))}</td><td>${r[2]}</td><td>${r[3]}</td><td>${r[4]}</td></tr>`).join("")}</tbody></table>`, "scroll")}
      <div class="grid">
        ${panel("事件详情", `<pre class="json">${esc(JSON.stringify({
          event_type: "ADAPTER_EXECUTION",
          message_id: "MSG-000005",
          node: "UAV-03",
          action: "TakePhoto",
          status: "SUCCESS",
          payload: { preset: "1920x1080", storage: "/data/images/20260705/" },
        }, null, 2))}</pre>`, "scroll")}
        ${panel("回放控制器", `<div class="mini-tabs"><button class="button" onclick="replayStep(-1)">上一帧</button><button class="button primary" onclick="replayPlay()">播放</button><button class="button" onclick="replayStep(1)">下一帧</button><span class="chip active">1x</span><span class="chip">2x</span><span class="chip">4x</span></div><div class="progress" style="margin:14px 0"><span style="width:${Math.min(96, 18 + state.replayIndex * 9)}%"></span></div>${scene3d("small")}`)}
      </div>
    </div>
  </div>`;
}

function eventColor(type) {
  if (type.includes("FAULT")) return "red";
  if (type.includes("POLICY")) return "violet";
  if (type.includes("RESULT")) return "green";
  if (type.includes("ADAPTER")) return "cyan";
  return "amber";
}

function skillsPage() {
  return `<div class="page">
    ${pageTitle("Skills 能力库", "能力注册 · 风险分级 · Adapter 支持 · Schema 治理")}
    <div class="metrics">
      ${metric("技能总数", "128", "本周新增 12", "cyan")}
      ${metric("已启用", "96", "75%", "green")}
      ${metric("高风险技能", "14", "+10.9%", "amber")}
      ${metric("覆盖 Backend", "5", "PX4 / Payload / Fake", "cyan")}
      ${metric("平均成功率", "96.1%", "+1.8%", "green")}
      ${metric("今日调用次数", "8,742", "+12.3%", "amber")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1fr .52fr">
      ${panel("能力卡片", `<div class="cap-grid">${capabilities.map((c) => `<div class="cap-card"><h3>${c[0]}</h3><div class="small">${c[1]}</div><div class="meta">${badge("已启用", "green")}${badge(c[2], c[2].includes("高") ? "red" : c[2].includes("中") ? "amber" : "green")}${badge(c[3], "cyan")}</div><div style="margin-top:14px"><span class="small">近7天成功率</span><b class="green" style="display:block;font-size:22px">${c[4]}</b></div></div>`).join("")}</div>`, "scroll")}
      ${panel("起飞 takeoff 详情", `<div class="mini-tabs"><span class="chip active">概览</span><span class="chip">接口定义</span><span class="chip">使用统计</span><span class="chip">版本历史</span></div><pre class="json" style="margin-top:10px">${esc(JSON.stringify({
        skill_id: "takeoff",
        category: "flight_control",
        risk_level: 2,
        supported_backend: ["PX4", "MAVLink"],
        input_schema: { altitude_m: "number", heading: "number", frame: "AMSL|AGL" },
        output_schema: { success: "boolean", achieved_altitude: "number", duration: "number" },
      }, null, 2))}</pre><button class="button primary">执行测试</button> <button class="button">在任务中使用</button>`, "scroll")}
    </div>
  </div>`;
}

function simulationPage() {
  return `<div class="page">
    ${pageTitle("仿真中心", "PX4 SITL · Gazebo · 高逼真数字孪生 · Smoke Test", `<button class="button primary" onclick="runScenario()">运行场景</button><button class="button" onclick="injectFault()">故障注入</button>`)}
    <div class="split-2 h-fill" style="grid-template-columns:.92fr 1.08fr">
      <div class="grid">
        ${panel("仿真环境", `<div class="cap-grid" style="grid-template-columns:repeat(2,1fr)">
          ${simCard("Fake Simulation", "轻量级逻辑仿真", "运行中", "green")}
          ${simCard("PX4 SITL + Gazebo", "飞控闭环验证", "已就绪", "green")}
          ${simCard("RflySim", "多机稳定仿真", "已就绪", "green")}
          ${simCard("ProSim / UE", "高保真渲染仿真", "已联调", "cyan")}
        </div>`)}
        ${panel("仿真任务", `<table class="table"><tr><th>任务名</th><th>环境</th><th>状态</th><th>节点</th><th>操作</th></tr><tr><td>Sim_Task_001</td><td>PX4 SITL</td><td>${badge("运行中", "green")}</td><td>8 UAV / 1 GCS</td><td>详情</td></tr><tr><td>Sim_Task_002</td><td>ProSim / UE</td><td>${badge("已完成", "green")}</td><td>4 UAV / 1 GCS</td><td>回放</td></tr><tr><td>Sim_Task_003</td><td>Fake</td><td>${badge("失败", "red")}</td><td>10 UAV</td><td>详情</td></tr></table>`)}
      </div>
      <div class="grid" style="grid-template-rows:1fr auto">
        ${panel("高逼真仿真预览", scene3d(), "h-fill")}
        ${panel("Smoke Test 状态", `<div class="split-2"><div><div class="donut"><div class="donut-inner"><b>92%</b><span class="small">通过率</span></div></div></div><pre class="json">${esc(JSON.stringify({
          max_altitude_m: state.maxAltitude,
          last_z: state.lastZ,
          threshold_reached: state.thresholdReached,
          arm_ack: true,
          takeoff_ack: true,
          land_ack: false,
          backend: "px4_sitl_backend",
        }, null, 2))}</pre></div>`)}
      </div>
    </div>
  </div>`;
}

function simCard(name, detail, status, color) {
  return `<div class="cap-card"><h3>${esc(name)}</h3><div class="small">${esc(detail)}</div><div style="height:76px;margin:10px 0;border:1px solid var(--line-soft);border-radius:7px;background:linear-gradient(135deg,rgba(54,199,244,.16),rgba(66,216,131,.08)),rgba(5,14,18,.8)"></div>${badge(status, color)} <button class="button" style="float:right">进入</button></div>`;
}

function generateRequest() {
  state.activeTrace = `trc_${Math.random().toString(16).slice(2, 10)}`;
  pushEvent("MISSION_REQUEST", `生成任务请求 ${state.activeTrace}`, "cyan");
  notify("已生成 ActionRequest", "任务输入已转换为结构化 mission_request / action_request。", "cyan");
  render();
}

function policyPrecheck() {
  state.policyBlocks += 1;
  pushEvent("POLICY_DECISION_EVENT", "策略预检通过：18 条约束命中，0 条阻断", "green");
  notify("策略预检通过", "GEO_FENCE_PASS / MAX_ALTITUDE / LINK_STABILITY 均通过。", "green");
  render();
}

function simulationPreview() {
  state.page = "simulation";
  pushEvent("SIMULATION_PREVIEW", "仿真预演已启动：PX4 SITL + Gazebo", "cyan");
  notify("仿真预演启动", "已切换到仿真中心，使用 PX4 SITL 配置。", "cyan");
  render();
}

function dispatchMission() {
  state.missionCount += 1;
  state.currentAction = "MISSION_DISPATCH";
  pushEvent("MISSION_DISPATCH", "任务已下发：Planner-Agent -> Policy Gate -> Adapter Gateway", "green");
  notify("任务已下发", "这是前端原型态，后续会接 Python runtime API。", "green");
  render();
}

function runSmokeTakeoff() {
  state.currentAction = "TAKEOFF";
  state.simRunning = true;
  state.thresholdReached = false;
  state.altitude = 0;
  state.lastZ = 0;
  pushEvent("ACTION_REQUEST", "smoke-takeoff 请求已创建，等待 Policy Gate 放行", "cyan");
  notify("Smoke Takeoff", "原型已开始模拟高度爬升；真实版本会调用 smoke-takeoff API。", "cyan");
  render();
}

function runLand() {
  state.currentAction = "LAND";
  state.altitude = Math.max(0, state.altitude - 4);
  state.lastZ = -state.altitude;
  pushEvent("ACTION_REQUEST", "LAND 请求已创建，等待 ACK", "amber");
  notify("Land", "模拟 LAND 指令已发出。真实版本会显示 land_ack。", "amber");
  render();
}

function runScenario() {
  state.simRunning = true;
  state.currentAction = "SIM_SCENARIO";
  pushEvent("SIMULATION", "场景运行：链路正常、低风、PX4 SITL ready", "green");
  notify("仿真场景运行中", "三维态势、Telemetry 与 Replay 进度开始模拟更新。", "green");
  render();
}

function injectFault() {
  state.linkIssues += 1;
  state.successRate = Math.max(90, state.successRate - 0.4);
  pushEvent("FAULT", "故障注入：UAV-05 LOW_BATTERY / link degraded", "red");
  notify("故障已注入", "UAV-05 触发低电量与链路降级告警。", "red");
  render();
}

function replayStep(delta) {
  state.replayIndex = Math.max(0, Math.min(10, state.replayIndex + delta));
  notify("Replay Step", `当前回放帧：${state.replayIndex}`, "cyan");
  render();
}

function replayPlay() {
  state.replayIndex = (state.replayIndex + 1) % 11;
  pushEvent("REPLAY", `回放跳转到事件帧 ${state.replayIndex}`, "cyan");
  notify("Replay Playing", "审计事件时间轴已推进一帧。", "cyan");
  render();
}

function assetsPage() {
  return placeholderPage("硬件资产", "飞控、伴随计算板、通信链路、云台、相机、载荷、传感器、电源模块的资产台账与接入状态。", hardwareTable());
}

function modelPage() {
  return placeholderPage("模型与知识", "Planner、Summarizer、Validator、知识库、Replay 到 Dataset 的闭环管理。", modelContent());
}

function settingsPage() {
  return placeholderPage("系统设置", "用户角色、安全策略、接口配置、日志管理、仿真路径和设备接口配置。", settingsContent());
}

function placeholderPage(title, subtitle, body) {
  return `<div class="page">
    ${pageTitle(title, subtitle)}
    ${body}
  </div>`;
}

function hardwareTable() {
  const rows = [
    ["Pixhawk 6C", "飞控", "UART/CAN/I2C/USB", "MAVLink", "在线"],
    ["NVIDIA Jetson Orin NX", "伴随计算板", "USB3.1/PCIe/CAN", "DDS/MAVLink", "在线"],
    ["SiK Radio 915", "通信链路", "UART", "MAVLink", "在线"],
    ["Gremsy H16", "云台", "UART/CAN", "MAVLink", "在线"],
    ["Sony A7R IV", "相机", "USB3.0", "Sony SDK", "在线"],
    ["Livox Avia", "传感器", "Ethernet", "Livox SDK", "在线"],
  ];
  return `<div class="metrics">
    ${metric("资产总数", "168", "在线 132", "cyan")}
    ${metric("开放接口设备", "126", "占比 75%", "green")}
    ${metric("已接入系统", "118", "占比 70%", "green")}
    ${metric("健康状态", "良好", "异常 5", "green")}
  </div>
  ${panel("资产清单", `<table class="table"><thead><tr><th>资产名称</th><th>类型</th><th>接口类型</th><th>控制协议</th><th>状态</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td><td>${badge(r[4], "green")}</td></tr>`).join("")}</tbody></table>`, "h-fill scroll")}`;
}

function modelContent() {
  return `<div class="split-2 h-fill">
    ${panel("模型配置", `<div class="cols-4">${["Planner", "Summarizer", "Validator", "Reranker"].map((m) => `<div class="cap-card"><h3>${m}</h3>${badge("运行中", "green")}<p class="small">任务规划、摘要生成、校验与重排。</p></div>`).join("")}</div>`)}
    ${panel("Replay -> Dataset 管道", `<div class="runtime-chain" style="grid-template-columns:repeat(5,1fr)">${["事件回放", "数据提取", "标注增强", "数据集生成", "模型优化"].map((m) => `<div class="chain-card"><h3>${m}</h3>${badge("READY", "cyan")}</div>`).join("")}</div><div class="donut"><div class="donut-inner"><b>96.3%</b><span class="small">最近评估</span></div></div>`)}
  </div>`;
}

function settingsContent() {
  return `<div class="split-2 h-fill">
    ${panel("用户与角色", `<table class="table"><tr><th>用户名</th><th>角色</th><th>权限范围</th><th>状态</th></tr><tr><td>Operator_01</td><td>管理员</td><td>全局</td><td>${badge("在线", "green")}</td></tr><tr><td>Planner_02</td><td>任务规划员</td><td>任务域</td><td>${badge("在线", "green")}</td></tr><tr><td>Viewer_05</td><td>观察员</td><td>只读</td><td>${badge("在线", "green")}</td></tr></table>`)}
    ${panel("接口与日志配置", `<div class="form-grid"><div class="field"><label>Backend 服务地址</label><input value="ws://backend.mission.local:8443"></div><div class="field"><label>Policy Gate 地址</label><input value="ws://policy-gate.mission.local:8443"></div><div class="field"><label>模型服务地址</label><input value="https://model.mission.local:8000"></div></div><div class="split-2" style="margin-top:10px"><div><div class="card-title"><h3>安全策略</h3></div>${checkList(["访问控制 RBAC", "策略签名验证", "通信加密 TLS", "操作审计"])}</div><div><div class="card-title"><h3>设备接口</h3></div><table class="table"><tr><td>MAVLink</td><td>UDP</td><td>14550</td><td>${badge("启用", "green")}</td></tr><tr><td>ROS 2</td><td>DDS</td><td>9090</td><td>${badge("启用", "green")}</td></tr></table></div></div>`)}
  </div>`;
}

function render() {
  app.innerHTML = `<div class="shell">
    ${topbar()}
    ${sidebar()}
    <main class="content">${route()}</main>
    ${toastStack()}
  </div>`;
}

function topbar() {
  return `<header class="topbar">
    <div class="brand"><div class="mark"></div><div class="brand-title">2026UAVSwarm Console</div></div>
    <div class="top-pill">Ground Profile</div>
    <div class="top-pill ok">系统运行<strong>${state.backendConnected ? "正常" : "降级"}</strong></div>
    <div class="top-pill">在线节点<strong>37 / 48</strong></div>
    <div class="top-pill">Backend 模式<strong>MISSION</strong></div>
    <div class="top-pill">当前 Action<strong>${state.currentAction}</strong></div>
    <div class="top-actions">
      <button class="icon-btn">N</button><button class="icon-btn">?</button><button class="icon-btn">L</button>
      <div class="operator"><div class="avatar"></div><div><div>Operator_01</div><div class="small">管理员</div></div></div>
      <div class="small">2026-07-05<br>UTC+8</div>
    </div>
  </header>`;
}

function sidebar() {
  return `<aside class="sidebar"><nav class="nav">
    ${navItems.map(([id, label, icon]) => `<button class="${state.page === id ? "active" : ""}" onclick="setPage('${id}')"><span class="nav-icon">${icon}</span><span>${label}</span><span>›</span></button>`).join("")}
  </nav></aside>`;
}

function setPage(page) {
  state.page = page;
  render();
}

function route() {
  const pages = {
    overview: overviewPage,
    planning: planningPage,
    twin: twinPage,
    vehicle: vehiclePage,
    runtime: runtimePage,
    policy: policyPage,
    skills: skillsPage,
    backend: backendPage,
    simulation: simulationPage,
    assets: assetsPage,
    replay: replayPage,
    model: modelPage,
    settings: settingsPage,
  };
  return (pages[state.page] || overviewPage)();
}

render();

setInterval(() => {
  if (!state.simRunning) {
    return;
  }
  if (state.currentAction === "TAKEOFF" || state.currentAction === "SIM_SCENARIO") {
    state.altitude = Math.min(24, state.altitude + 0.8);
    state.maxAltitude = Math.max(state.maxAltitude, state.altitude);
    state.lastZ = -state.altitude;
    state.thresholdReached = state.altitude >= 2.4;
  } else if (state.currentAction === "LAND") {
    state.altitude = Math.max(0, state.altitude - 0.9);
    state.lastZ = -state.altitude;
  }
  if (state.page === "vehicle" || state.page === "backend" || state.page === "simulation") {
    render();
  }
}, 1600);
