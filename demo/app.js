const SCENE_ORDER = ["ALLOW", "DENY", "REQUIRE_CONFIRM", "SITL_WIRING"];
const AUTO_DWELL_MS = 7200;

const LABELS = {
  scene: "场景（Scene）",
  mission: "任务（Mission）",
  action: "动作（Action）",
  adapter: "适配器（Adapter）",
  backend: "后端（Backend）",
  status: "系统状态（Status）",
};

const STATUS_TEXT = {
  READY: "就绪（READY）",
  BLOCKED: "已阻断（BLOCKED）",
  WAIT_CONFIRM: "等待确认（WAIT_CONFIRM）",
  SITL_PENDING: "仿真后端待接入（SITL_PENDING）",
};

const ACTION_TEXT = {
  takeoff: "起飞（takeoff）",
  goto: "航点移动（goto）",
};

const SCOPE_TEXT = {
  self_only: "本机范围（self_only）",
};

const DECISION_TEXT = {
  allow: "允许执行（allow）",
  deny: "拒绝执行（deny）",
  REQUIRE_CONFIRM: "需要确认（REQUIRE_CONFIRM）",
};

const REASON_TEXT = {
  "(null)": "无阻断原因（null）",
  REASON_CODE_RISK_LEVEL_EXCEEDED: "风险等级超限（REASON_CODE_RISK_LEVEL_EXCEEDED）",
  REASON_CODE_CONFIRMATION_REQUIRED: "需要人工确认（REASON_CODE_CONFIRMATION_REQUIRED）",
};

const ADAPTER_TEXT = {
  fake: "虚拟适配器（fake）",
  mavlink: "MAVLink适配器（mavlink）",
  "(skipped)": "未执行（skipped）",
  "(pending)": "待执行（pending）",
};

const MODE_TEXT = {
  stub: "桩模式（stub）",
  "sitl(stub)": "仿真桩模式（sitl/stub）",
  sitl: "仿真模式（sitl）",
  "n/a": "不适用（n/a）",
};

const RESULT_CODE_TEXT = {
  exec_ok: "执行成功（exec_ok）",
  REASON_CODE_RISK_LEVEL_EXCEEDED: "风险等级超限（REASON_CODE_RISK_LEVEL_EXCEEDED）",
  REASON_CODE_CONFIRMATION_REQUIRED: "需要人工确认（REASON_CODE_CONFIRMATION_REQUIRED）",
  smoke_not_connected: "后端未连接（smoke_not_connected）",
};

const RESULT_STATUS_TEXT = {
  accepted: "已接受（accepted）",
  rejected: "已拒绝（rejected）",
  blocked: "已阻断（blocked）",
  waiting_confirmation: "等待确认（waiting_confirmation）",
};

const EVENT_NAME_TEXT = {
  mission_request: "任务请求（mission_request）",
  action_request: "动作请求（action_request）",
  policy_decision_event: "策略裁决事件（policy_decision_event）",
  action_result: "执行结果（action_result）",
  replay: "回放审计（replay）",
};

const BASE_DRONES = [
  { id: "UAV-01", x: 18, y: 70, color: "#61d4ff" },
  { id: "UAV-02", x: 27, y: 58, color: "#79a2ff" },
  { id: "UAV-03", x: 39, y: 66, color: "#5ee6b1" },
  { id: "UAV-04", x: 52, y: 54, color: "#ffd26c" },
  { id: "UAV-05", x: 66, y: 63, color: "#d7a1ff" },
];

const COMMON = {
  groundStation: { x: 8, y: 86 },
  targetPoint: { x: 82, y: 22 },
  noFlyZone: { x: 72, y: 42, r: 13 },
};

const SCENARIOS = {
  ALLOW: {
    btn: "正常放行（ALLOW）",
    title: "正常放行（ALLOW）",
    status: "READY",
    missionAction: { mission_id: "mission-alpha", action_type: "takeoff", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "allow", primary_reason_code: "(null)", effective_scope: "self_only", policy_trace_id: "pt-allow-001" },
    result: { adapter: "fake", backend_mode: "stub", code: "exec_ok", status: "accepted", replay: "策略裁决事件与执行结果已记录" },
    summary: {
      policy: "策略判定通过，指令满足当前风险与作用域约束。",
      result: "执行面正常返回 accepted，控制面闭环贯通。",
      replay: "本次决策与执行结果已记录，可回放审计。",
    },
    mapHint: "目标激活，航迹高亮，无人机进入执行态。",
    targetState: "active",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i + 1) * 4, y: d.y - (i % 2 ? 16 : 10), state: "takeoff" })),
    paths: [
      { from: [18, 70], to: [28, 56], cls: "path allow" },
      { from: [27, 58], to: [39, 45], cls: "path allow" },
      { from: [39, 66], to: [51, 52], cls: "path allow" },
      { from: [52, 54], to: [67, 38], cls: "path allow" },
    ],
    timeline: [
      ["00:00", "mission_request", "任务 mission-alpha 已提交", "neutral"],
      ["00:01", "action_request", "起飞动作请求（flight_core）", "neutral"],
      ["00:02", "policy_decision_event", "裁决结果：允许，范围：本机", "ok"],
      ["00:03", "action_result", "执行已接受，返回码：exec_ok", "ok"],
      ["00:04", "replay", "事件已记录，可回放、可审计", "replay"],
    ],
  },
  DENY: {
    btn: "高风险拒绝（DENY）",
    title: "高风险拒绝（DENY）",
    status: "BLOCKED",
    missionAction: { mission_id: "mission-bravo", action_type: "goto", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "deny", primary_reason_code: "REASON_CODE_RISK_LEVEL_EXCEEDED", effective_scope: "self_only", policy_trace_id: "pt-deny-001" },
    result: { adapter: "(skipped)", backend_mode: "n/a", code: "REASON_CODE_RISK_LEVEL_EXCEEDED", status: "blocked", replay: "拒绝链路完整留痕" },
    summary: {
      policy: "风险超限，策略层阻断执行。",
      result: "Adapter 未执行，避免进入危险动作。",
      replay: "拒绝链路完整留痕，可用于复盘。",
    },
    mapHint: "风险区告警，目标锁定，无人机保持当前位置。",
    targetState: "locked",
    drones: BASE_DRONES.map((d) => ({ ...d, state: "hold" })),
    paths: [{ from: [39, 66], to: [82, 22], cls: "path denied" }],
    timeline: [
      ["00:00", "mission_request", "任务 mission-bravo 已提交", "neutral"],
      ["00:01", "action_request", "航点移动请求（goto）", "neutral"],
      ["00:02", "policy_decision_event", "裁决结果：拒绝，原因：风险等级超限", "deny"],
      ["00:03", "action_result", "执行阻断，Adapter 未执行", "deny"],
      ["00:04", "replay", "拒绝链路可回放审计", "replay"],
    ],
  },
  REQUIRE_CONFIRM: {
    btn: "等待确认（REQUIRE_CONFIRM）",
    title: "等待确认（REQUIRE_CONFIRM）",
    status: "WAIT_CONFIRM",
    missionAction: { mission_id: "mission-charlie", action_type: "goto", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "REQUIRE_CONFIRM", primary_reason_code: "REASON_CODE_CONFIRMATION_REQUIRED", effective_scope: "self_only", policy_trace_id: "pt-confirm-001" },
    result: { adapter: "(pending)", backend_mode: "sitl(stub)", code: "REASON_CODE_CONFIRMATION_REQUIRED", status: "waiting_confirmation", replay: "等待确认状态已记录" },
    summary: {
      policy: "命中人工确认规则，系统暂停等待确认。",
      result: "执行层暂停，等待确认指令。",
      replay: "等待确认状态已记录，可追踪。",
    },
    mapHint: "任务暂停，等待人工确认。",
    targetState: "pending",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i % 2 ? 3 : -2), y: d.y + (i % 2 ? -4 : 2), state: "confirm" })),
    paths: [
      { from: [27, 58], to: [56, 36], cls: "path pending" },
      { from: [39, 66], to: [63, 30], cls: "path pending" },
    ],
    timeline: [
      ["00:00", "mission_request", "任务 mission-charlie 已提交", "neutral"],
      ["00:01", "action_request", "航点移动请求（需确认）", "neutral"],
      ["00:02", "policy_decision_event", "裁决结果：需要确认", "warn"],
      ["00:03", "action_result", "等待人工确认后继续", "warn"],
      ["00:04", "replay", "确认流程可回放审计", "replay"],
    ],
  },
  SITL_WIRING: {
    btn: "接入位预留（SITL_WIRING）",
    title: "接入位预留（SITL_WIRING）",
    status: "SITL_PENDING",
    missionAction: { mission_id: "mission-delta", action_type: "takeoff", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "allow", primary_reason_code: "(null)", effective_scope: "self_only", policy_trace_id: "pt-sitl-001" },
    result: { adapter: "mavlink", backend_mode: "sitl", code: "smoke_not_connected", status: "rejected", replay: "SITL wiring 状态可追踪" },
    summary: {
      policy: "策略层已放行，控制路径进入MAVLink/SITL预留后端。",
      result: "执行路径已到 backend 接入位，当前真实后端未连接。",
      replay: "SITL wiring 状态可追踪，可用于后续真实接入验证。",
    },
    mapHint: "SITL后端路径已预留，真实后端尚未连接。",
    targetState: "sitl",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i % 2 ? 1 : -1), y: d.y - (i % 2 ? 2 : 1), state: "sitl" })),
    paths: [{ from: [18, 70], to: [30, 50], cls: "path sitl" }],
    timeline: [
      ["00:00", "mission_request", "任务 mission-delta 已提交", "neutral"],
      ["00:01", "action_request", "MAVLink/SITL 路径已进入", "neutral"],
      ["00:02", "policy_decision_event", "策略裁决通过，进入执行路径", "ok"],
      ["00:03", "action_result", "真实后端尚未连接（smoke_not_connected）", "sitl"],
      ["00:04", "replay", "后端接入位已预留，可回放审计", "replay"],
    ],
  },
};

const STATUS_CLASS = {
  READY: "ok",
  BLOCKED: "deny",
  WAIT_CONFIRM: "warn",
  SITL_PENDING: "sitl",
};

const state = {
  sceneKey: "ALLOW",
  autoPlay: false,
  stepIndex: 0,
  clock: new Date(),
  stepTimer: null,
  autoTimer: null,
};

const root = document.getElementById("root");

const explain = (value, map) => map[value] || value;
const esc = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

function kv(label, value, strong = false) {
  return `<div class="kv"><span>${esc(label)}</span><span class="value${strong ? " strong" : ""}">${esc(value)}</span></div>`;
}

function render() {
  const scene = SCENARIOS[state.sceneKey];
  const badgeClass = STATUS_CLASS[scene.status] || "warn";

  const pathsHtml = scene.paths
    .map(
      (path, idx) => `<svg data-path="${idx}" class="path-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
        <line class="${path.cls}" x1="${path.from[0]}" y1="${path.from[1]}" x2="${path.to[0]}" y2="${path.to[1]}" />
      </svg>`
    )
    .join("");

  const dronesHtml = scene.drones
    .map(
      (drone) => `<div class="drone ${drone.state}" style="left:${drone.x}%;top:${drone.y}%;background:${drone.color}">
        <span>${esc(drone.id)}</span>
      </div>`
    )
    .join("");

  const timelineHtml = scene.timeline
    .map((entry, idx) => {
      const active = idx <= state.stepIndex ? " active" : "";
      const cursor = idx === state.stepIndex ? " cursor" : "";
      return `<div class="line${active}${cursor} ${entry[3]}">
        <span class="dot"></span>
        <span class="ts">${esc(entry[0])}</span>
        <span class="ev">${esc(EVENT_NAME_TEXT[entry[1]])}</span>
        <span class="desc">${esc(entry[2])}</span>
      </div>`;
    })
    .join("");

  root.innerHTML = `
    <div class="app">
      <header class="topbar panel">
        <div class="brand">
          <h1>2026UAVSwarm Demo Shell</h1>
          <p>控制面闭环已打通 · 策略裁决与执行面解耦</p>
        </div>
        <div class="top-metrics">
          <span class="metric"><label>${LABELS.scene}</label><b>${esc(scene.title)}</b></span>
          <span class="metric"><label>${LABELS.mission}</label><b>${esc(scene.missionAction.mission_id)}</b></span>
          <span class="metric"><label>${LABELS.action}</label><b>${esc(explain(scene.missionAction.action_type, ACTION_TEXT))}</b></span>
          <span class="metric"><label>${LABELS.adapter}</label><b>${esc(explain(scene.result.adapter, ADAPTER_TEXT))}</b></span>
          <span class="metric"><label>${LABELS.backend}</label><b>${esc(explain(scene.result.backend_mode, MODE_TEXT))}</b></span>
          <span class="status ${badgeClass}">${esc(STATUS_TEXT[scene.status])}</span>
          <span class="lamp"></span>
          <span class="metric clock"><label>演示时间（Time）</label><b>${esc(state.clock.toLocaleTimeString())}</b></span>
        </div>
      </header>

      <main class="main">
        <section class="panel map-panel">
          <div class="panel-title">
            <h2>2D Fleet Situation / 集群态势</h2>
            <div class="hint">${esc(scene.mapHint)}</div>
          </div>

          <div class="tag-row">
            <span class="tag">控制面闭环已打通</span>
            <span class="tag">策略裁决与执行面解耦</span>
            ${state.sceneKey === "SITL_WIRING" ? '<span class="tag sitl">SITL backend path prepared</span>' : ""}
          </div>

          <div class="map">
            <div class="ground-station" style="left:${COMMON.groundStation.x}%;top:${COMMON.groundStation.y}%">地面站</div>
            <div class="target ${scene.targetState}" style="left:${COMMON.targetPoint.x}%;top:${COMMON.targetPoint.y}%">${scene.targetState === "locked" ? "目标锁定" : "目标点"}</div>
            <div class="zone ${state.sceneKey === "DENY" ? "danger active" : "danger"}" style="left:${COMMON.noFlyZone.x}%;top:${COMMON.noFlyZone.y}%;width:${COMMON.noFlyZone.r * 2}%;height:${COMMON.noFlyZone.r * 2}%">禁飞区</div>
            ${pathsHtml}
            ${dronesHtml}
            ${state.sceneKey === "REQUIRE_CONFIRM" ? '<div class="confirm-banner">任务暂停，等待人工确认</div>' : ""}
            ${state.sceneKey === "SITL_WIRING" ? '<div class="sitl-banner">SITL后端路径已预留，真实后端尚未连接</div>' : ""}
          </div>
        </section>

        <aside class="panel side">
          <div class="controls-row" id="scene-buttons"></div>
          <div class="controls-row">
            <button id="auto-toggle" class="${state.autoPlay ? "active glow" : ""}">${state.autoPlay ? "停止自动演示" : "自动演示（Auto Demo / Play All）"}</button>
            <button id="restart-btn">重置演示（Restart）</button>
          </div>

          <section class="card">
            <h3>任务 / 动作（Mission / Action）</h3>
            ${kv("任务编号（mission_id）", scene.missionAction.mission_id)}
            ${kv("动作类型（action_type）", explain(scene.missionAction.action_type, ACTION_TEXT), true)}
            ${kv("优先级提示（priority_hint）", scene.missionAction.priority_hint)}
            ${kv("请求范围（requested_scope）", explain(scene.missionAction.requested_scope, SCOPE_TEXT))}
          </section>

          <section class="card">
            <h3>策略决策（Policy Decision）</h3>
            ${kv("裁决结果（decision_code）", explain(scene.policy.decision_code, DECISION_TEXT), true)}
            ${kv("主要原因（primary_reason_code）", explain(scene.policy.primary_reason_code, REASON_TEXT))}
            ${kv("生效范围（effective_scope）", explain(scene.policy.effective_scope, SCOPE_TEXT))}
            ${kv("策略追踪号（policy_trace_id）", scene.policy.policy_trace_id)}
            <p class="summary">${esc(scene.summary.policy)}</p>
          </section>

          <section class="card">
            <h3>执行结果（Adapter / Backend / Result）</h3>
            ${kv("执行适配器（adapter）", explain(scene.result.adapter, ADAPTER_TEXT), true)}
            ${kv("后端模式（backend_mode）", explain(scene.result.backend_mode, MODE_TEXT))}
            ${kv("结果代码（result.code）", explain(scene.result.code, RESULT_CODE_TEXT), true)}
            ${kv("执行状态（result.status）", explain(scene.result.status, RESULT_STATUS_TEXT))}
            <p class="summary">${esc(scene.summary.result)}</p>
          </section>

          <section class="card">
            <h3>回放审计（Replay & Audit）</h3>
            <p>${esc(scene.result.replay)}</p>
            <p class="summary">${esc(scene.summary.replay)}</p>
          </section>
        </aside>
      </main>

      <section class="panel timeline-wrap">
        <h2>事件时间线（Event Timeline）</h2>
        ${timelineHtml}
      </section>

      <footer class="footer">演示模式（Demo Mode）· 当前未连接真实 PX4/MAVLink/SITL</footer>
    </div>
  `;

  const buttonsWrap = document.getElementById("scene-buttons");
  buttonsWrap.innerHTML = SCENE_ORDER
    .map((key) => `<button data-scene="${key}" class="${state.sceneKey === key ? "active" : ""}">${esc(SCENARIOS[key].btn)}</button>`)
    .join("");

  buttonsWrap.querySelectorAll("button[data-scene]").forEach((btn) => {
    btn.addEventListener("click", () => setScene(btn.dataset.scene));
  });

  document.getElementById("auto-toggle").addEventListener("click", () => {
    state.autoPlay = !state.autoPlay;
    syncAutoTimer();
    render();
  });

  document.getElementById("restart-btn").addEventListener("click", () => setScene("ALLOW"));
}

function setScene(sceneKey) {
  state.sceneKey = sceneKey;
  state.stepIndex = 0;
  syncStepTimer();
  render();
}

function syncStepTimer() {
  clearInterval(state.stepTimer);
  state.stepTimer = setInterval(() => {
    const total = SCENARIOS[state.sceneKey].timeline.length;
    state.stepIndex = Math.min(state.stepIndex + 1, total - 1);
    render();
  }, 1200);
}

function syncAutoTimer() {
  clearInterval(state.autoTimer);
  if (!state.autoPlay) {
    return;
  }
  state.autoTimer = setInterval(() => {
    const idx = SCENE_ORDER.indexOf(state.sceneKey);
    setScene(SCENE_ORDER[(idx + 1) % SCENE_ORDER.length]);
  }, AUTO_DWELL_MS);
}

setInterval(() => {
  state.clock = new Date();
  const clockNode = document.querySelector(".metric.clock b");
  if (clockNode) {
    clockNode.textContent = state.clock.toLocaleTimeString();
  }
}, 1000);

syncStepTimer();
render();
