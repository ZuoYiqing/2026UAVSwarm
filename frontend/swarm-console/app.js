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

const ACTION_STORAGE_KEY = "swarm-console.pending-actions.v1";
let vehicleContractModule;

const state = {
  page: "overview",
  backendConnected: false,
  currentAction: "IDLE",
  targetAltitude: 3,
  altitude: null,
  maxAltitude: null,
  lastZ: null,
  thresholdReached: null,
  missionCount: null,
  policyBlocks: null,
  linkIssues: null,
  activeTrace: null,
  selectedUav: null,
  replayIndex: 0,
  apiBaseUrl: window.SwarmRuntimeApi?.getConfiguredBaseUrl?.() || "http://127.0.0.1:8765/api",
  apiStatus: "checking",
  apiLastError: null,
  runtimeHealth: null,
  lastProbeAt: null,
  runtimeEventsLoaded: false,
  dataStatus: "checking",
  lastBackendResult: null,
  lastActionResult: null,
  lastPlanResult: null,
  runtimeSnapshot: null,
  telemetry: null,
  vehicleSnapshot: null,
  agentStatus: null,
  simulationStatus: null,
  registryPayload: null,
  skillsPayload: null,
  policyDecisions: [],
  recentActions: [],
  lifecycleRecords: [],
  actionRecords: [],
  lifecycleSupported: null,
  pendingActions: loadPendingActions(),
  actionRequestsInFlight: new Set(),
  fleet: [],
  nodeStats: {},
  runtimeEvents: [],
  stateSyncInFlight: false,
  simulationReady: false,
  simulationContractError: null,
  simulationAlignment: "unknown",
  simulationUrl: "http://127.0.0.1:5179/",
  toast: [],
};

const events = [];

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

function showStatusHelp() {
  notify(
    "状态来源",
    "LIVE 表示 Runtime API 可达；STALE 表示保留最后快照；PX4 就绪按所选载具遥测判断。",
    "cyan"
  );
}

function currentRuntimeRequest(options = {}) {
  return window.SwarmConsoleModel.buildRuntimeRequest(
    selectedVehicle(),
    state.targetAltitude,
    options
  );
}

function loadPendingActions() {
  try {
    const rows = JSON.parse(localStorage.getItem(ACTION_STORAGE_KEY) || "[]");
    return Array.isArray(rows) ? rows.filter((item) => item?.body?.idempotency_key
      && item.body.node_id === item.node_id && typeof item.api_base_url === "string") : [];
  } catch (_error) {
    return [];
  }
}

function persistPendingActions() {
  localStorage.setItem(ACTION_STORAGE_KEY, JSON.stringify(state.pendingActions));
}

function selectedVehicle() {
  return window.SwarmConsoleModel.findVehicle(state.fleet, state.selectedUav);
}

function selectedNodeStats() {
  if (!state.selectedUav) return {};
  return state.nodeStats[state.selectedUav] || {};
}

function selectedAction() {
  const pending = state.pendingActions.filter((item) => item.node_id === state.selectedUav
    && item.api_base_url === state.apiBaseUrl).at(-1);
  if (pending) {
    const record = state.actionRecords.find((item) => item.request_id === pending.body.request_id);
    return { ...(record || pending.body), action_type: pending.action_type,
      status: record?.status || "unknown", action_id: pending.action_id,
      client_status: pending.client_status || "请求发送中", client_pending: true,
      error_payload: pending.error_payload, smoke: pending.smoke };
  }
  return window.SwarmConsoleModel.latestActionForNode(
    state.actionRecords,
    state.selectedUav
  );
}

function actionPermission(actionType) {
  return window.SwarmConsoleModel.actionPermission(
    selectedVehicle(),
    state.apiStatus,
    [...state.actionRecords, ...state.pendingActions.filter((item) => item.api_base_url === state.apiBaseUrl)
      .map((item) => ({ ...item, client_pending: true }))],
    actionType
  );
}

function updateSelectedTelemetry() {
  const vehicle = selectedVehicle();
  if (!vehicle) {
    state.altitude = null;
    state.maxAltitude = null;
    state.lastZ = null;
    state.thresholdReached = null;
    state.currentAction = "IDLE";
    return;
  }
  const stats = window.SwarmConsoleModel.actionTelemetry(selectedAction());
  state.altitude = vehicle.altitudeM;
  state.maxAltitude = stats.maxAltitudeAction;
  state.lastZ = vehicle.zDownM;
  state.thresholdReached = stats.thresholdReached ?? null;
  const action = selectedAction();
  state.currentAction = action?.status
    ? `${action.action_type.toUpperCase()} / ${action.status.toUpperCase()}`
    : vehicle.activeAction || "IDLE";
}

function applyApiSuccess(source, payload) {
  state.apiStatus = "live";
  state.apiLastError = null;
  state.lastProbeAt = new Date().toISOString();
  if (source === "health") {
    state.runtimeHealth = payload;
  }
  if (source === "backend") {
    state.lastBackendResult = payload;
  } else if (source === "action") {
    applyActionResult(payload);
  } else if (source === "plan") {
    state.lastPlanResult = payload;
  }
}

function applyApiFailure(source, error, notifyFailure = true) {
  // An HTTP error still proves the bridge is reachable; network and timeout
  // failures mean the browser cannot currently reach the Runtime API.
  state.apiStatus = error.kind === "http" ? "live" : "offline";
  state.apiLastError = `${source}: ${error.message}`;
  if (source === "health" || state.apiStatus === "offline") {
    state.backendConnected = false;
  }
  if (state.apiStatus === "offline") {
    state.dataStatus = state.dataStatus === "live" ? "stale" : "unavailable";
    state.fleet = window.SwarmConsoleModel.markFleetStale(state.fleet);
    state.vehicleSnapshot = window.SwarmConsoleModel.markVehicleSnapshotStale(state.vehicleSnapshot);
    postVehicleSnapshot();
  }
  if (notifyFailure) {
    const title = state.apiStatus === "live" ? "Runtime API 返回错误" : "Runtime API 未连接";
    notify(title, state.apiLastError, state.apiStatus === "live" ? "red" : "amber");
  }
}

function applyActionResult(payload, fallback = {}) {
  const action = window.SwarmConsoleModel.normalizeActionRecord(payload, fallback);
  const nodeId = action.node_id;
  if (!nodeId) return;
  state.actionRecords = window.SwarmConsoleModel.mergeActionRecords(
    state.actionRecords,
    [action]
  );
  state.lastActionResult = action;
  if (nodeId === state.selectedUav) updateSelectedTelemetry();
}

async function callRuntime(source, call, fallback, options = {}) {
  try {
    const payload = await call();
    applyApiSuccess(source, payload);
    return payload;
  } catch (error) {
    applyApiFailure(source, error, options.notifyFailure !== false);
    return fallback(error);
  }
}

function runtimeApiStatus() {
  return {
    checking: { label: "连接中", color: "cyan" },
    live: { label: "LIVE", color: "green" },
    offline: { label: "OFFLINE", color: "amber" },
  }[state.apiStatus] || { label: "UNKNOWN", color: "amber" };
}

function dataSourceStatus() {
  return {
    checking: { label: "同步中", color: "cyan" },
    live: { label: "LIVE", color: "green" },
    stale: { label: "STALE", color: "amber" },
    unavailable: { label: "无数据", color: "red" },
  }[state.dataStatus] || { label: "UNKNOWN", color: "amber" };
}

function backendStatus(vehicle = selectedVehicle()) {
  if (state.apiStatus === "checking") {
    return { label: "探测中", color: "cyan" };
  }
  if (state.apiStatus !== "live") {
    return { label: "未知", color: "amber" };
  }
  const selectedReady = vehicle
    ? vehicle.enabled && vehicle.connected && !vehicle.stale
    : state.backendConnected;
  return selectedReady
    ? { label: "READY", color: "green" }
    : { label: "NOT READY", color: "red" };
}

function eventColor(severity, eventType) {
  if (severity === "error" || severity === "critical") return "red";
  if (severity === "warning") return "amber";
  if (String(eventType).includes("policy")) return "violet";
  if (String(eventType).includes("action")) return "green";
  return "cyan";
}

function eventTime(timestamp) {
  if (!timestamp) return "--:--:--";
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime())
    ? String(timestamp).slice(11, 19)
    : parsed.toLocaleTimeString("zh-CN", { hour12: false });
}

async function syncRuntimeEvents(options = {}) {
  try {
    const payload = await window.SwarmRuntimeApi.events(options.count || 30);
    if (!Array.isArray(payload)) {
      throw new Error("事件接口返回的不是数组");
    }
    const normalized = payload
      .slice()
      .reverse()
      .slice(0, 30)
      .map((event) => [
        eventTime(event.timestamp),
        event.event_type || "RUNTIME_EVENT",
        event.summary || `${event.event_type || "runtime"} event`,
        eventColor(event.severity, event.event_type),
      ]);
    events.splice(0, events.length, ...normalized);
    state.runtimeEvents = payload.slice().reverse().slice(0, 30);
    state.runtimeEventsLoaded = true;
    state.apiStatus = "live";
    state.apiLastError = null;
  } catch (error) {
    applyApiFailure("events", error, options.notifyFailure === true);
  }
}

async function probeRuntime(options = {}) {
  state.apiStatus = "checking";
  state.apiLastError = null;
  state.backendConnected = false;
  renderRuntimeUpdate();

  if (!window.SwarmRuntimeApi) {
    const error = new Error("runtime-api.js 未加载");
    error.kind = "network";
    applyApiFailure("health", error, options.notifyUser === true);
    render();
    return;
  }

  try {
    const healthPayload = await window.SwarmRuntimeApi.health();
    applyApiSuccess("health", healthPayload);
    await Promise.all([
      syncRuntimeState({ notifyFailure: false }),
      syncRuntimeEvents({ notifyFailure: false }),
    ]);
    if (options.notifyUser) {
      notify("Runtime API 已连接", state.apiBaseUrl, "green");
    }
  } catch (error) {
    applyApiFailure("health", error, options.notifyUser === true);
  }
  renderRuntimeUpdate();
}

async function syncRuntimeState(options = {}) {
  if (state.stateSyncInFlight || !window.SwarmRuntimeApi) return;
  state.stateSyncInFlight = true;
  try {
    const calls = {
    runtimeSnapshot: window.SwarmRuntimeApi.snapshot(),
    telemetry: window.SwarmRuntimeApi.telemetryLatest(),
    vehicleSnapshot: window.SwarmRuntimeApi.vehicleSnapshot(),
    agentStatus: window.SwarmRuntimeApi.agentStatus(),
    simulationStatus: window.SwarmRuntimeApi.simulationStatus(),
    registryPayload: window.SwarmRuntimeApi.vehicles(),
    skillsPayload: window.SwarmRuntimeApi.skills(),
    policyDecisions: window.SwarmRuntimeApi.policyDecisions(20),
    recentActions: window.SwarmRuntimeApi.recentActions(20),
    lifecycleRecords: window.SwarmRuntimeApi.actionLifecycle(30),
  };
    const keys = Object.keys(calls);
    const results = await Promise.allSettled(Object.values(calls));
    const resultsByKey = Object.fromEntries(keys.map((key, index) => [key, results[index]]));
    let successCount = 0;
    let firstError = null;
    results.forEach((result, index) => {
    if (result.status === "fulfilled") {
      state[keys[index]] = result.value;
      successCount += 1;
    } else if (!firstError) {
      firstError = result.reason;
    }
    });

    if (successCount > 0) {
    state.apiStatus = "live";
    state.apiLastError = successCount === keys.length ? null : `${keys.length - successCount} 个状态接口不可用`;
    const criticalStateFailed = ["telemetry", "vehicleSnapshot", "registryPayload"]
      .some((key) => resultsByKey[key]?.status !== "fulfilled");
    if (criticalStateFailed) {
      state.fleet = window.SwarmConsoleModel.markFleetStale(state.fleet);
      state.vehicleSnapshot = window.SwarmConsoleModel.markVehicleSnapshotStale(
        state.vehicleSnapshot
      );
      state.backendConnected = false;
      state.dataStatus = "stale";
      updateSelectedTelemetry();
      postVehicleSnapshot();
      return;
    }
    state.fleet = window.SwarmConsoleModel.mergeFleet(
      state.registryPayload,
      state.telemetry,
      state.vehicleSnapshot
    );
    if (resultsByKey.lifecycleRecords?.status === "fulfilled" && Array.isArray(state.lifecycleRecords)) {
      state.lifecycleSupported = true;
      state.actionRecords = window.SwarmConsoleModel.mergeActionRecords(
        state.actionRecords,
        state.lifecycleRecords
      );
    } else {
      state.lifecycleSupported = false;
    }
    if (!state.fleet.some((vehicle) => vehicle.id === state.selectedUav)) {
      state.selectedUav = state.fleet[0]?.id || null;
    }
    for (const vehicle of state.fleet) {
      const stats = state.nodeStats[vehicle.id] || {};
      if (vehicle.connected && !vehicle.stale && typeof vehicle.altitudeM === "number") {
        stats.maxAltitudeTelemetry = Math.max(
          stats.maxAltitudeTelemetry ?? vehicle.altitudeM,
          vehicle.altitudeM
        );
      }
      state.nodeStats[vehicle.id] = stats;
    }
    state.backendConnected = window.SwarmConsoleModel.isFleetReady(state.fleet);
    state.missionCount = state.agentStatus?.active_plans?.length ?? null;
    const decisions = state.runtimeSnapshot?.policy_summary?.recent_decisions || [];
    state.policyBlocks = decisions.filter((item) => String(item.decision_code || item.decision || "").toUpperCase() === "DENY").length;
    state.linkIssues = state.fleet.filter((vehicle) => vehicle.enabled && (!vehicle.connected || vehicle.stale)).length;
    state.dataStatus = state.telemetry?.status === "ok"
      ? "live"
      : state.telemetry?.status === "stale"
        ? "stale"
        : "unavailable";
    updateSelectedTelemetry();
    postVehicleSnapshot();
    await recoverPendingActions();
    updateSelectedTelemetry();
    } else if (firstError) {
      applyApiFailure("snapshot", firstError, options.notifyFailure === true);
    }
  } catch (error) {
    applyApiFailure("snapshot-contract", error, options.notifyFailure === true);
  } finally {
    state.stateSyncInFlight = false;
  }
}

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
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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

function formatNumber(value, digits = 1, suffix = "") {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(digits)}${suffix}`
    : "--";
}

function fleetSummary() {
  const total = state.fleet.length;
  const online = state.fleet.filter((vehicle) => vehicle.connected && !vehicle.stale).length;
  const armed = state.fleet.filter((vehicle) => vehicle.armed === true).length;
  return { total, online, armed };
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
  if (!events.length) {
    return `<div class="empty-state">暂无 Runtime 事件</div>`;
  }
  return `<div class="event-list">${events.map((e) => `
    <div class="event">
      <div class="time">${e[0]}</div>
      <div><strong class="${e[3]}">${e[1]}</strong><span class="small">${e[2]}</span></div>
    </div>`).join("")}</div>`;
}

function vehicleTable() {
  if (!state.fleet.length) {
    return `<div class="empty-state">Runtime 尚未提供已注册载具</div>`;
  }
  return `<table class="table">
    <thead><tr><th>节点</th><th>状态</th><th>Identity</th><th>模式</th><th>高度</th><th>电量</th></tr></thead>
    <tbody>${state.fleet.map((vehicle) => `
      <tr class="selectable-row ${vehicle.id === state.selectedUav ? "selected" : ""}" data-vehicle-id="${esc(vehicle.id)}">
        <td><b>${esc(vehicle.displayName)}</b></td>
        <td>${badge(vehicle.connected ? "在线" : vehicle.stale ? "过期" : "离线", vehicle.connected ? "green" : vehicle.stale ? "amber" : "red")}</td>
        <td>${esc(`${vehicle.systemId ?? "-"}/${vehicle.componentId ?? "-"}`)}</td>
        <td>${esc(vehicle.activeAction || vehicle.flightMode || "--")}</td>
        <td>${esc(formatNumber(vehicle.altitudeM, 1, " m"))}</td>
        <td>${esc(formatNumber(vehicle.batteryPercent, 0, "%"))}</td>
      </tr>
    `).join("")}</tbody>
  </table>`;
}

function fleetPreview() {
  if (!state.fleet.length) return `<div class="empty-state fleet-empty">等待 vehicle snapshot</div>`;
  return `<div class="fleet-preview">
    <div class="fleet-grid"></div>
    ${state.fleet.map((vehicle, index) => {
      const column = index % 3;
      const row = Math.floor(index / 3);
      const left = 18 + column * 32;
      const top = 24 + row * 34;
      const color = vehicle.connected ? "green" : vehicle.stale ? "amber" : "red";
      return `<button class="fleet-node ${color} ${vehicle.id === state.selectedUav ? "selected" : ""}" style="left:${left}%;top:${top}%" data-vehicle-id="${esc(vehicle.id)}">
        <span>${esc(vehicle.id)}</span><small>${esc(formatNumber(vehicle.altitudeM, 1, "m"))}</small>
      </button>`;
    }).join("")}
    <div class="fleet-preview-meta">${badge(`源 ${state.vehicleSnapshot?.source?.label || "Runtime"}`, "cyan")} ${badge(`场景 ${state.vehicleSnapshot?.scene_id || "--"}`, "green")}</div>
  </div>`;
}

function simulationFrame() {
  const alignment = simulationAlignmentStatus();
  return `<div class="simulation-frame-wrap">
    <iframe id="simulation-frame" class="simulation-frame" src="${esc(state.simulationUrl)}" title="Cesium 三维集群态势"></iframe>
    <div class="simulation-frame-note ${alignment.color}">${esc(
      state.simulationContractError
        || (state.simulationReady ? `Runtime 快照由主控制台统一推送；${alignment.label}` : "等待 5179 三维服务响应")
    )}</div>
  </div>`;
}

function simulationOrigin() {
  try {
    return new URL(state.simulationUrl, window.location.href).origin;
  } catch (_error) {
    return null;
  }
}

async function postVehicleSnapshot() {
  const frame = document.getElementById("simulation-frame");
  const origin = simulationOrigin();
  if (!frame?.contentWindow || !origin || !state.vehicleSnapshot || !state.simulationReady) return;
  try {
    vehicleContractModule ||= import("./simulation-3d/src/vehicle-contract.js");
    const contract = await vehicleContractModule;
    if (document.getElementById("simulation-frame") !== frame) return;
    const snapshot = state.vehicleSnapshot;
    // Validate with the shared consumer contract, but forward the original
    // Runtime object. Never use the normalizer's coordinate conversion here.
    contract.normalizeVehicleSnapshot(snapshot);
    state.simulationContractError = null;
    frame.contentWindow.postMessage(window.SwarmConsoleModel.createVehicleSnapshotMessage(snapshot), origin);
    const note = document.querySelector(".simulation-frame-note");
    if (note) note.textContent = `Runtime 快照统一推送；${simulationAlignmentStatus().label}`;
  } catch (error) {
    state.simulationContractError = `三维快照未发送：${error.message}`;
    const note = document.querySelector(".simulation-frame-note");
    if (note) note.textContent = state.simulationContractError;
  }
}

function simulationAlignmentStatus() {
  const spatial = state.vehicleSnapshot?.vehicles?.find((vehicle) => vehicle.spatial)?.spatial || {};
  const runtimeScene = state.vehicleSnapshot?.scene_id || spatial.scene_id || null;
  const runtimeMap = state.vehicleSnapshot?.map_version || spatial.map_version || null;
  const simulationScene = state.simulationStatus?.scene_id || null;
  const simulationMap = state.simulationStatus?.map_version || null;
  if (!runtimeScene || !runtimeMap || !simulationScene || !simulationMap) {
    state.simulationAlignment = "unknown";
    return { label: "场景对齐未知", color: "amber" };
  }
  const aligned = runtimeScene === simulationScene && runtimeMap === simulationMap;
  state.simulationAlignment = aligned ? "map_unverified" : "mismatch";
  return aligned
    ? { label: `${runtimeScene} / ${runtimeMap}：Runtime/Simulation 标识一致，Cesium 地图待确认`, color: "amber" }
    : { label: `未对齐：Runtime ${runtimeScene}/${runtimeMap}，Simulation ${simulationScene}/${simulationMap}`, color: "red" };
}

function selectVehicle(nodeId) {
  if (!state.fleet.some((vehicle) => vehicle.id === nodeId)) return;
  state.selectedUav = nodeId;
  updateSelectedTelemetry();
  render();
}

function overviewPage() {
  const summary = fleetSummary();
  const activeActions = state.runtimeSnapshot?.active_actions?.length ?? 0;
  const mode = selectedVehicle()?.backendMode?.toUpperCase() || "--";
  return `<div class="page">
    ${pageTitle("总览驾驶舱", "三维态势 · Runtime 执行链路 · 策略安全 · 审计回放")}
    <div class="metrics">
      ${metric("在线节点数", `${summary.online} / ${summary.total}`, `已武装 ${summary.armed}`, "cyan")}
      ${metric("活跃计划", state.missionCount ?? "--", "Agent Runtime 快照", "blue")}
      ${metric("执行中动作", activeActions, "当前 Runtime", "green")}
      ${metric("最近拒绝", state.policyBlocks ?? "--", "最近策略窗口", "violet")}
      ${metric("离线 / 过期", state.linkIssues ?? "--", "已启用节点", "amber")}
      ${metric("Backend 模式", mode, state.selectedUav || "未选择", "cyan")}
    </div>
    <div class="main-overview">
      ${panel("实时集群状态预览", fleetPreview(), "h-fill")}
      ${panel("最近动作记录 / 事件流", eventList(), "h-fill scroll")}
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
  const summary = fleetSummary();
  const activePlans = state.agentStatus?.active_plans?.length ?? 0;
  const decisions = state.runtimeSnapshot?.policy_summary?.recent_decisions?.length ?? 0;
  const activeActions = state.runtimeSnapshot?.active_actions?.length ?? 0;
  const cards = [
    ["任务输入", activePlans, "ACTIVE PLANS"],
    ["Agent Runtime", state.agentStatus?.planner_version || "--", state.agentStatus?.planner_kind || "UNAVAILABLE"],
    ["Policy Gate", decisions, "RECENT"],
    ["Skill Router", "--", "NOT EXPOSED"],
    ["Adapter Gateway", state.apiStatus === "live" ? "ON" : "OFF", "HTTP BRIDGE"],
    ["MAVLink / PX4", `${summary.online}/${summary.total}`, "ONLINE"],
    ["Active Action", activeActions, "RUNNING"],
    ["Audit / Replay", state.runtimeEvents.length, "RECENT"],
  ];
  return panel("Agent Runtime 执行链路（实时）", `<div class="runtime-chain">${cards.map((c, i) => `
    <div class="chain-card">
      <h3>${c[0]}</h3>
      <b class="${i === 2 ? "violet" : i > 5 ? "green" : "cyan"}">${c[1]}</b>
      <span class="small">${c[2]}</span>
    </div>`).join("")}</div>`, compact ? "" : "h-fill");
}

function twinPage() {
  const summary = fleetSummary();
  return `<div class="page">
    ${pageTitle("三维集群态势", "Cesium · Runtime vehicle snapshot · 多机任务态势", `<a class="button" href="${esc(state.simulationUrl)}" target="_blank" rel="noreferrer">独立打开</a>`)}
    <div class="two-main" style="grid-template-columns:1.42fr .58fr">
      ${panel(`三维 Mission Twin ${badge(state.simulationReady ? "CONNECTED" : "WAITING", state.simulationReady ? "green" : "amber")}`, simulationFrame(), "h-fill twin-panel")}
      <div class="grid" style="grid-template-rows:auto 1fr">
        <div class="metrics" style="grid-template-columns:repeat(3,1fr)">
          ${metric("在线节点", `${summary.online}/${summary.total}`, "Runtime", "cyan")}
          ${metric("已武装", summary.armed, "Telemetry", "green")}
          ${metric("离线 / 过期", state.linkIssues ?? "--", "Fleet", "amber")}
        </div>
        ${panel("节点列表", vehicleTable(), "scroll")}
      </div>
    </div>
    <div class="split-2" style="grid-template-columns:1.15fr .85fr">
      ${vehicleDiagramPanel()}
      ${panel("所选节点遥测", telemetrySummary())}
    </div>
  </div>`;
}

function planningPage() {
  return `<div class="page">
    ${pageTitle("任务规划", "自然语言生成任务 · 结构化编排 · 策略预检 · 仿真预演", `
      <button class="button primary" onclick="generateRequest()">生成请求</button><button class="button" disabled title="Runtime 暂无独立策略预检接口">策略预检</button><button class="button" onclick="simulationPreview()">仿真预演</button><button class="button success" disabled title="正式任务执行接口尚未开放">下发任务</button>
    `)}
    ${designPreviewNotice("任务图、地图标记、风险分值和策略通过状态是交互设计稿；只有生成请求、载具列表与 Runtime 状态来自 LIVE 接口。")}
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
  const vehicle = selectedVehicle();
  return `<div class="page">
    ${pageTitle(`单机详情 / ${vehicle?.id || "未选择"}`, "飞控状态 · MAVLink identity · 实时遥测")}
    <div class="split-2" style="grid-template-columns:1fr 1fr">
      ${panel("局部三维态势", scene3d(), "h-fill")}
      ${panel("集群节点", vehicleTable(), "scroll")}
    </div>
    <div class="split-2" style="grid-template-columns:1.05fr .95fr">
      ${vehicleDiagramPanel()}
      <div class="grid">
        <div class="cols-4">
          ${statusTile("运行状态", vehicle?.connected ? "在线" : "离线", `${vehicle?.flightMode || "--"} · ${formatNumber(vehicle?.groundSpeedMps, 1, " m/s")}`, vehicle?.connected ? "green" : "red")}
          ${statusTile("MAVLink Identity", `${vehicle?.systemId ?? "--"}/${vehicle?.componentId ?? "--"}`, vehicle?.endpoint || "无端点", "cyan")}
          ${statusTile("武装状态", vehicle?.armed === true ? "ARMED" : vehicle?.armed === false ? "DISARMED" : "--", vehicle?.activeAction || "无执行中动作", vehicle?.armed ? "amber" : "green")}
          ${statusTile("遥测新鲜度", vehicle?.stale ? "STALE" : vehicle?.connected ? "FRESH" : "--", formatNumber(vehicle?.telemetryAgeMs, 0, " ms"), vehicle?.stale ? "amber" : "green")}
        </div>
        <div class="cols-4">
          ${telemetryCard("max_altitude_m", formatNumber(state.maxAltitude), "#36c7f4")}
          ${telemetryCard("last_z", formatNumber(state.lastZ), "#42d883")}
          ${telemetryCard("threshold_reached", state.thresholdReached === null ? "--" : String(state.thresholdReached), "#f5b84c")}
          ${telemetryCard("current status", state.currentAction, "#9a7cff")}
        </div>
      </div>
    </div>
  </div>`;
}

function vehicleDiagramPanel() {
  const vehicle = selectedVehicle();
  const status = vehicle?.connected ? "在线" : vehicle?.stale ? "遥测过期" : "离线";
  const statusColor = vehicle?.connected ? "green" : vehicle?.stale ? "amber" : "red";
  return panel("单机模块健康", `<div class="vehicle-diagram">
    <div class="drone-arm a"></div><div class="drone-arm b"></div><div class="drone-body"></div>
    <div class="rotor r1"></div><div class="rotor r2"></div><div class="rotor r3"></div><div class="rotor r4"></div>
    <div class="module-tile m1"><b>PX4 飞控</b><br><span class="${statusColor}">${esc(status)}</span><br><span class="small">${esc(vehicle?.flightMode || "无模式数据")}</span></div>
    <div class="module-tile m2"><b>MAVLink</b><br><span class="${statusColor}">${esc(`${vehicle?.systemId ?? "-"}/${vehicle?.componentId ?? "-"}`)}</span><br><span class="small">${esc(vehicle?.endpoint || "无端点")}</span></div>
    <div class="module-tile m3"><b>Runtime Action</b><br><span class="cyan">${esc(vehicle?.activeAction || "IDLE")}</span><br><span class="small">${esc(vehicle?.lastError || "无错误")}</span></div>
    <div class="module-tile m4"><b>电源遥测</b><br><span class="${typeof vehicle?.batteryPercent === "number" ? "green" : "amber"}">${esc(formatNumber(vehicle?.batteryPercent, 0, "%"))}</span><br><span class="small">${vehicle?.armed === true ? "ARMED" : vehicle?.armed === false ? "DISARMED" : "状态未知"}</span></div>
  </div>`);
}

function telemetryCard(title, value, color) {
  return `<section class="panel"><div class="small">${esc(title)}</div><h2 style="margin:8px 0;color:${color}">${esc(value)}</h2></section>`;
}

function telemetrySummary() {
  return `<div class="cols-4">
    ${telemetryCard("max_altitude_m", formatNumber(state.maxAltitude), "#36c7f4")}
    ${telemetryCard("last_z", formatNumber(state.lastZ), "#42d883")}
    ${telemetryCard("threshold_reached", state.thresholdReached === null ? "--" : String(state.thresholdReached), "#f5b84c")}
    ${telemetryCard("current status", state.currentAction, "#9a7cff")}
  </div>`;
}

function statusTile(title, value, detail, color) {
  return `<section class="panel"><div class="small">${esc(title)}</div><h2 class="${color}" style="margin:8px 0">${esc(value)}</h2><div class="small">${esc(detail)}</div></section>`;
}

function runtimePage() {
  const agent = state.agentStatus || {};
  const latestPlan = agent.latest_plan || null;
  const queue = state.runtimeSnapshot?.agent_runtime?.queue || {};
  const activeActions = state.runtimeSnapshot?.active_actions || [];
  const latestAction = activeActions[0] || state.recentActions[0] || null;
  return `<div class="page">
    ${pageTitle("Agent Runtime", "任务队列 · 上下文构建 · Planner · Policy · Adapter · Audit")}
    <div class="metrics">
      ${metric("最新 Plan", latestPlan?.plan_id || "--", latestPlan?.status || "无计划", "violet")}
      ${metric("活跃计划", agent.active_plans?.length ?? 0, "Runtime store", "cyan")}
      ${metric("队列深度", queue.supported ? queue.depth ?? "--" : "N/A", queue.supported ? "Runtime queue" : "后端未提供", "amber")}
      ${metric("执行中动作", activeActions.length, "active_actions", "green")}
      ${metric("Planner", agent.planner_version || "--", agent.planner_kind || "unavailable", "green")}
      ${metric("LLM / 实执行", agent.llm_enabled ? "ON" : "OFF", agent.real_execution_enabled ? "REAL" : "DRY / FAKE", "cyan")}
    </div>
    ${runtimeChain()}
    <div class="split-2 h-fill" style="grid-template-columns:1fr .52fr">
      <div class="split-3">
        ${panel("执行能力", `<table class="table"><tr><td>LLM</td><td>${badge(agent.llm_enabled ? "启用" : "禁用", agent.llm_enabled ? "green" : "amber")}</td></tr><tr><td>真实执行</td><td>${badge(agent.real_execution_enabled ? "启用" : "禁用", agent.real_execution_enabled ? "green" : "amber")}</td></tr><tr><td>支持模式</td><td>${esc((agent.supported_execution_modes || []).join(", ") || "--")}</td></tr></table>`)}
        ${panel("计划状态", `<table class="table"><tr><td>Plan ID</td><td>${esc(latestPlan?.plan_id || "--")}</td></tr><tr><td>状态</td><td>${esc(latestPlan?.status || "--")}</td></tr><tr><td>任务类型</td><td>${esc(latestPlan?.mission_type || "--")}</td></tr></table>`)}
        ${panel("数据可用性", `<table class="table"><tr><td>会话指标</td><td>${badge("未提供", "amber")}</td></tr><tr><td>延迟指标</td><td>${badge("未提供", "amber")}</td></tr><tr><td>系统负载</td><td>${badge("未提供", "amber")}</td></tr></table>`)}
      </div>
      ${panel("当前执行 / 最近结果", `<pre class="json">${esc(JSON.stringify(latestAction || { status: "no_action_data" }, null, 2))}</pre>`, "scroll")}
    </div>
  </div>`;
}

function policyPage() {
  const rows = Array.isArray(state.policyDecisions) ? state.policyDecisions : [];
  const count = (code) => rows.filter((item) => String(item.decision_code || "").toUpperCase() === code).length;
  const latest = rows[0] || null;
  return `<div class="page">
    ${pageTitle("Policy Gate", "Safe · Deterministic · Explainable Decisions")}
    <div class="metrics">
      ${metric("最近决策", rows.length, "Audit window", "cyan")}
      ${metric("ALLOW 允许", count("ALLOW"), "最近窗口", "green")}
      ${metric("DENY 拒绝", count("DENY"), "最近窗口", "red")}
      ${metric("REQUIRE_CONFIRM", count("REQUIRE_CONFIRM"), "最近窗口", "amber")}
      ${metric("PREEMPT", count("PREEMPT"), "最近窗口", "violet")}
      ${metric("DEFER", count("DEFER"), "最近窗口", "blue")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.12fr .88fr">
      ${panel("决策监控 / Decision Monitor", rows.length ? `<table class="table"><thead><tr><th>时间</th><th>决策</th><th>节点</th><th>Action</th><th>Risk</th><th>Profile</th></tr></thead><tbody>${rows.map((item) => { const code = String(item.decision_code || "UNKNOWN").toUpperCase(); const risk = String(item.risk?.level || "--").toUpperCase(); return `<tr><td>${esc(eventTime(item.timestamp))}</td><td>${badge(code, decisionColor(code))}</td><td>${esc(item.node_id || "--")}</td><td>${esc(item.action_type || "--")}</td><td>${esc(risk)}</td><td>${esc(item.effective_profile_id || "--")}</td></tr>`; }).join("")}</tbody></table>` : `<div class="empty-state">暂无 Policy 决策</div>`, "scroll")}
      <div class="grid">
        ${panel("最新决策", `<pre class="json">${esc(JSON.stringify(latest || { status: "no_policy_decisions" }, null, 2))}</pre>`)}
        ${panel("约束", latest?.constraints?.length ? checkList(latest.constraints.map((item) => item.code || item.constraint_id || JSON.stringify(item))) : `<div class="empty-state">未提供约束详情</div>`)}
        ${panel("决策说明", `<pre class="json">${esc(JSON.stringify(latest ? { explanation: latest.explanation, primary_reason_code: latest.primary_reason_code, secondary_reason_codes: latest.secondary_reason_codes, audit_tags: latest.audit_tags } : { status: "unavailable" }, null, 2))}</pre>`)}
      </div>
    </div>
  </div>`;
}

function decisionColor(code) {
  return { ALLOW: "green", DENY: "red", REQUIRE_CONFIRM: "amber", PREEMPT: "violet", DEFER: "cyan" }[code] || "cyan";
}

function known(value, suffix = "") {
  return value === null || value === undefined || value === ""
    ? "unknown"
    : `${value}${suffix}`;
}

function lifecycleColor(status) {
  return {
    succeeded: "green",
    executing: "cyan",
    accepted: "blue",
    requested: "violet",
    policy_rejected: "red",
    failed: "red",
    timed_out: "amber",
  }[status] || "amber";
}

function selectedActionEvents(action) {
  if (!action) return [];
  return state.runtimeEvents.filter((event) =>
    window.SwarmConsoleModel.eventMatchesAction(event, action)
  );
}

function actionLifecycleView(action) {
  return `<div class="action-lifecycle">${window.SwarmConsoleModel.actionStages(action).map((stage) => `
    <div class="action-stage ${stage.tone}">
      <span class="stage-dot"></span><b>${esc(stage.key.toUpperCase())}</b><small>${esc(stage.label)}</small>
    </div>`).join("")}</div>`;
}

function telemetryDetail(vehicle, action) {
  const stats = { ...selectedNodeStats(), ...window.SwarmConsoleModel.actionTelemetry(action) };
  const completion = action?.completion_evidence || {};
  const targetAltitude = completion.target_altitude_m
    ?? action?.request_parameters?.altitude_m ?? action?.altitude_m ?? action?.raw?.altitude_m ?? null;
  const ackRows = action?.ack_evidence?.length
    ? action.ack_evidence.map((ack) => `<tr><td>${esc(ack.stage || ack.command || "unknown")}</td><td>${badge(ack.result_name || known(ack.result), window.SwarmConsoleModel.ackAccepted(ack) ? "green" : "amber")}</td><td>${esc(eventTime(ack.timestamp))}</td></tr>`).join("")
    : `<tr><td colspan="3" class="small">接口暂未返回 ACK 证据</td></tr>`;
  return `<div class="telemetry-detail"><dl>
    <div><dt>node_id</dt><dd>${esc(vehicle?.id || "unknown")}</dd></div>
    <div><dt>endpoint</dt><dd>${esc(vehicle?.endpoint || "unknown")}</dd></div>
    <div><dt>connected / stale</dt><dd>${esc(`${known(vehicle?.connected)} / ${known(vehicle?.stale)}`)}</dd></div>
    <div><dt>armed</dt><dd>${esc(known(vehicle?.armed))}</dd></div>
    <div><dt>flight mode</dt><dd>${esc(vehicle?.flightMode || "unknown")}</dd></div>
    <div><dt>目标高度</dt><dd>${esc(known(targetAltitude, " m"))}</dd></div>
    <div><dt>相对高度</dt><dd>${esc(known(vehicle?.altitudeM, " m"))}</dd></div>
    <div><dt>高度参考</dt><dd>${vehicle?.altitudeM == null ? "unknown" : "PX4 local NED 原点 (-z)，非 AGL"}</dd></div>
    <div><dt>原始 z_down</dt><dd>${esc(known(vehicle?.zDownM, " m"))}</dd></div>
    <div><dt>last_z (action)</dt><dd>${esc(known(stats.lastZ, " m"))}</dd></div>
    <div><dt>max_altitude_m (action)</dt><dd>${esc(known(stats.maxAltitudeAction, " m"))}</dd></div>
    <div><dt>max observed (UI session)</dt><dd>${esc(known(stats.maxAltitudeTelemetry, " m"))}</dd></div>
    <div><dt>threshold_reached</dt><dd>${esc(known(stats.thresholdReached))}</dd></div>
    <div><dt>sample time</dt><dd>${esc(vehicle?.lastSeen || "unknown")}</dd></div>
    <div><dt>sample age</dt><dd>${esc(known(vehicle?.telemetryAgeMs, " ms"))}</dd></div>
    <div><dt>action status</dt><dd>${esc(action?.status || "unknown")}</dd></div>
  </dl><table class="table ack-table"><thead><tr><th>ACK stage</th><th>结果</th><th>时间</th></tr></thead><tbody>${ackRows}</tbody></table></div>`;
}

function backendPage() {
  const api = runtimeApiStatus();
  const vehicle = selectedVehicle();
  const backend = backendStatus(vehicle);
  const selectedProbe = state.runtimeSnapshot?.backend_statuses?.find((item) => item.node_id === vehicle?.id);
  const latestProbe = state.lastBackendResult?.resolved_node_id === vehicle?.id ? state.lastBackendResult : selectedProbe;
  const probeCode = latestProbe?.connect_probe?.code || "not_checked";
  const readiness = latestProbe?.readiness || backend.label;
  const runtimeService = state.runtimeHealth?.service || "uav_runtime_http_bridge";
  const takeoffPermission = actionPermission("takeoff");
  const landPermission = actionPermission("land");
  const lifecycleReady = state.lifecycleSupported === true;
  const liveAction = selectedAction();
  const actionEvents = selectedActionEvents(liveAction);
  const holdState = liveAction?.action_type === "takeoff"
    && liveAction.smoke !== true
    && liveAction.status === "succeeded"
    && liveAction.completion_evidence?.completion_reached === true
      ? "起飞时曾确认高度稳定；当前飞行状态见实时遥测"
      : "无独立 HOLD 接口；等待起飞稳定证据";
  return `<div class="page action-page">
    ${pageTitle("飞行控制与 Runtime", "指定节点 · Policy · MAVLink ACK · 遥测完成证据")}
    <div class="grid api-toolbar">
      ${panel("Runtime API 与传输端点", `<div class="form-grid"><div class="field"><label for="runtime-api-url">Runtime API Base URL</label><input id="runtime-api-url" value="${esc(state.apiBaseUrl)}"></div><div class="field"><label>所选 MAVLink Endpoint</label><input value="${esc(vehicle?.endpoint || "--")}" readonly></div><div class="field"><label>Telemetry REST</label><input value="${esc(state.apiBaseUrl)}/telemetry/latest" readonly></div></div><div style="margin-top:8px"><button class="button" onclick="saveApiBaseUrl(document.getElementById('runtime-api-url').value)">连接此 API</button> ${badge(`Runtime API ${api.label}`, api.color)} ${badge(`PX4 ${backend.label}`, backend.color)} ${state.apiLastError ? `<span class="small">${esc(state.apiLastError)}</span>` : ""}</div>`)}
      <button class="button primary" onclick="probeRuntime({notifyUser:true})">刷新全部状态</button>
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.12fr .88fr">
      <div class="grid backend-action-column scroll">
        ${panel("指定节点动作", `<div class="form-grid"><div class="field"><label for="action-node">目标载具</label><select id="action-node" onchange="selectVehicle(this.value)">${state.fleet.map((item) => `<option value="${esc(item.id)}" ${item.id === state.selectedUav ? "selected" : ""}>${esc(item.id)} · SYS ${item.systemId ?? "-"}</option>`).join("")}</select></div><div class="field"><label for="action-altitude">目标相对高度 altitude_m</label><input id="action-altitude" type="number" min="1" max="120" step="0.5" value="${state.targetAltitude.toFixed(1)}" onchange="setTargetAltitude(this.value)"></div><div class="field"><label>MAVLink Identity</label><input value="${esc(`${vehicle?.systemId ?? "-"}/${vehicle?.componentId ?? "-"}`)}" readonly></div></div><div class="action-buttons"><button class="button" onclick="checkBackend()" ${!vehicle || state.apiStatus !== "live" ? "disabled" : ""}>Check Backend</button><button class="button primary" data-action="takeoff" onclick="runOperationalTakeoff()" ${!lifecycleReady || !takeoffPermission.allowed ? "disabled" : ""}>正式起飞</button><button class="button" data-action="smoke" onclick="runSmokeTakeoff()" ${!lifecycleReady || !takeoffPermission.allowed ? "disabled" : ""}>Smoke Test</button><button class="button warn" data-action="land" onclick="runLand()" ${!lifecycleReady || !landPermission.allowed ? "disabled" : ""}>受控降落</button></div><div class="control-notes">${badge(lifecycleReady ? "LIFECYCLE 1.1" : "正式动作接口暂不支持", lifecycleReady ? "green" : "amber")}<span class="small">TAKEOFF：${esc(takeoffPermission.reason)}</span><span class="small">LAND：${esc(landPermission.reason)}</span><span class="small">保持：${esc(holdState)}</span><span class="small">Smoke 为独立阈值测试；本控制台不请求自动降落。</span></div>`)}
        ${panel(`动作生命周期 ${liveAction ? badge(liveAction.status.toUpperCase(), lifecycleColor(liveAction.status)) : badge("NO ACTION", "amber")}`, `${actionLifecycleView(liveAction)}<div class="action-identity"><span>node ${esc(liveAction?.node_id || "unknown")}</span><span>request ${esc(liveAction?.request_id || "unknown")}</span><span>action ${esc(liveAction?.action_id || "unknown")}</span><span>trace ${esc(liveAction?.trace_id || "unknown")}</span></div>${liveAction?.client_status ? `<div class="small">${esc(liveAction.client_status)}</div>` : ""}${liveAction?.failure_reason ? `<div class="inline-error">${esc(liveAction.failure_reason)}</div>` : ""}`)}
        ${panel(`实时遥测与动作证据 ${badge(state.dataStatus.toUpperCase(), dataSourceStatus().color)}`, telemetryDetail(vehicle, liveAction))}
        ${panel("所选节点 Action JSON", `<pre class="json">${esc(JSON.stringify(liveAction || { data_source: "unavailable", node_id: vehicle?.id || null }, null, 2))}</pre>`, "scroll action-json-panel")}
        ${panel("关联事件", actionEvents.length ? `<table class="table"><thead><tr><th>时间</th><th>类型</th><th>节点</th><th>摘要</th></tr></thead><tbody>${actionEvents.map((event) => `<tr><td>${esc(eventTime(event.timestamp))}</td><td>${badge(event.event_type || event.type || "EVENT", eventColor(event.severity, event.event_type || event.type))}</td><td>${esc(event.node_id || "unknown")}</td><td>${esc(event.summary || event.code || "unknown")}<details><summary>原始 JSON</summary><pre class="json">${esc(JSON.stringify(event, null, 2))}</pre></details></td></tr>`).join("")}</tbody></table>` : `<div class="empty-state">当前 action 暂无可关联事件</div>`, "scroll")}
        ${panel("Backend 健康与探测", `<table class="table"><tr><th>组件</th><th>状态</th><th>Probe</th><th>来源</th></tr><tr><td>${esc(runtimeService)}</td><td>${badge(api.label, api.color)}</td><td>${esc(state.runtimeHealth?.status || "not_checked")}</td><td>GET /api/health</td></tr><tr><td>px4_sitl_backend</td><td>${badge(backend.label, backend.color)}</td><td>${esc(probeCode)}</td><td>${esc(readiness)}</td></tr><tr><td>hardware_backend</td><td>${badge("未接入", "amber")}</td><td>N/A</td><td>配置占位</td></tr></table>`)}
      </div>
    </div>
  </div>`;
}

function adapterTopology() {
  const adapters = [
    ["Runtime HTTP", state.apiStatus === "live" ? "LIVE" : "OFFLINE", state.runtimeHealth?.version || "--", state.apiStatus === "live" ? "green" : "amber"],
    ["MAVLink Adapter", state.backendConnected ? "CONNECTED" : "IDLE", "px4_sitl", state.backendConnected ? "green" : "amber"],
    ["Vehicle Registry", `${state.fleet.length} NODES`, state.registryPayload?.source || "--", "cyan"],
  ];
  return `<div class="cols-4" style="grid-template-columns:repeat(3,1fr)">${adapters.map((a) => `<div class="chain-card"><h3>${esc(a[0])}</h3>${badge(a[1], a[3])}<br><span class="small">${esc(a[2])}</span></div>`).join("")}</div>`;
}

async function checkBackend(options = {}) {
  const vehicle = selectedVehicle();
  if (!vehicle) {
    notify("无法检查 Backend", "Runtime 没有已注册载具。", "amber");
    return null;
  }
  const nodeId = vehicle.id;
  const request = window.SwarmConsoleModel.buildRuntimeRequest(
    vehicle,
    state.targetAltitude,
    { requireConnected: false }
  );
  const payload = await callRuntime(
    "backend",
    () => window.SwarmRuntimeApi.checkBackend(request),
    () => ({ readiness: "unavailable", connect_probe: { code: "runtime_unreachable" } }),
    { notifyFailure: options.notifyUser !== false }
  );
  const readiness = payload.readiness || payload.status || "unavailable";
  const code = payload.connect_probe?.code || payload.code || "not_checked";
  state.backendConnected = readiness === "ready" || code === "backend_connected";
  pushEvent("BACKEND_CHECK", `px4_sitl_backend 探测：${code}`, state.backendConnected ? "green" : "red");
  if (options.notifyUser !== false) {
    notify("Backend Check", `${nodeId} 返回 ${code}`, state.backendConnected ? "green" : "amber");
  }
  await syncRuntimeState({ notifyFailure: false });
  render();
  return payload;
}

function saveApiBaseUrl(value) {
  if (state.actionRequestsInFlight.size || state.pendingActions.length) {
    notify("地址未更改", "仍有请求在执行或等待核实，请先确认原 Runtime 的动作状态", "amber");
    render();
    return;
  }
  state.apiBaseUrl = window.SwarmRuntimeApi.setConfiguredBaseUrl(value);
  state.apiStatus = "checking";
  state.runtimeHealth = null;
  state.lastBackendResult = null;
  state.backendConnected = false;
  state.actionRecords = [];
  state.lifecycleRecords = [];
  state.lifecycleSupported = null;
  state.fleet = [];
  state.nodeStats = {};
  state.vehicleSnapshot = null;
  notify("Runtime API 已更新", state.apiBaseUrl, "cyan");
  render();
  probeRuntime();
}

function setTargetAltitude(value) {
  const parsed = Number(value);
  state.targetAltitude = Number.isFinite(parsed)
    ? Math.min(120, Math.max(1, parsed))
    : 3;
  render();
}

function replayPage() {
  const replayRows = state.runtimeEvents;
  const errorCount = replayRows.filter((event) => ["error", "critical"].includes(event.severity)).length;
  const warningCount = replayRows.filter((event) => event.severity === "warning").length;
  const involvedNodes = new Set(replayRows.map((event) => event.node_id).filter(Boolean)).size;
  const selectedEvent = replayRows[state.replayIndex] || replayRows[0] || null;
  return `<div class="page">
    ${pageTitle("Audit / Replay", "任务审计与回放 · 事件溯源 · 三维态势复盘")}
    <div class="grid" style="grid-template-columns:repeat(5,1fr)">
      ${metric("最近事件", replayRows.length, "Runtime audit", "cyan")}
      ${metric("信息", replayRows.length - errorCount - warningCount, "当前窗口", "green")}
      ${metric("错误", errorCount, "error / critical", "red")}
      ${metric("警告", warningCount, "warning", "amber")}
      ${metric("涉及节点", involvedNodes, "node_id", "violet")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.22fr .78fr">
      ${panel("事件时间线（按时间排序）", replayRows.length ? `<table class="table"><thead><tr><th>时间</th><th>类型</th><th>节点</th><th>事件 / 消息</th><th>事件 ID</th></tr></thead><tbody>${replayRows.map((event) => `<tr><td>${esc(eventTime(event.timestamp))}</td><td>${badge(event.event_type || "RUNTIME_EVENT", eventColor(event.severity, event.event_type))}</td><td>${esc(event.node_id || "--")}</td><td>${esc(event.summary || "--")}</td><td>${esc(event.event_id || "--")}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-state">暂无可回放事件</div>`, "scroll")}
      <div class="grid">
        ${panel("事件详情", `<pre class="json">${esc(JSON.stringify(selectedEvent || { status: "no_runtime_events" }, null, 2))}</pre>`, "scroll")}
        ${panel("回放控制器", `<div class="mini-tabs"><button class="button" onclick="replayStep(-1)" ${replayRows.length ? "" : "disabled"}>上一条</button><button class="button primary" onclick="replayPlay()">刷新事件</button><button class="button" onclick="replayStep(1)" ${replayRows.length ? "" : "disabled"}>下一条</button></div><div class="progress" style="margin:14px 0"><span style="width:${replayRows.length ? ((state.replayIndex + 1) / replayRows.length) * 100 : 0}%"></span></div><div class="empty-state">Runtime 尚未提供可回放的三维轨迹帧</div>`)}
      </div>
    </div>
  </div>`;
}

function skillsPage() {
  const skills = state.skillsPayload?.skills || [];
  const enabledCount = skills.filter((skill) => skill.enabled).length;
  const highRiskCount = skills.filter((skill) => Number(skill.risk_level) >= 3).length;
  const backends = new Set(skills.flatMap((skill) => skill.supported_backends || []));
  const selectedSkill = skills.find((skill) => skill.action_type === "takeoff") || skills[0] || null;
  return `<div class="page">
    ${pageTitle("Skills 能力库", "能力注册 · 风险分级 · Adapter 支持 · Schema 治理")}
    <div class="metrics">
      ${metric("技能总数", skills.length, "Capability Registry", "cyan")}
      ${metric("已启用", enabledCount, "当前 manifest", "green")}
      ${metric("高风险技能", highRiskCount, "risk_level >= 3", "amber")}
      ${metric("覆盖 Backend", backends.size, [...backends].join(" / ") || "--", "cyan")}
      ${metric("成功率", "--", "后端未提供", "green")}
      ${metric("调用次数", skills.reduce((sum, skill) => sum + (skill.usage?.total_calls || 0), 0), "usage source", "amber")}
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1fr .52fr">
      ${panel("能力卡片", skills.length ? `<div class="cap-grid">${skills.map((skill) => `<div class="cap-card"><h3>${esc(skill.display_name)}</h3><div class="small">${esc(skill.action_type)}</div><div class="meta">${badge(skill.enabled ? "已启用" : "禁用", skill.enabled ? "green" : "red")}${badge(`风险 ${skill.risk_level}`, Number(skill.risk_level) >= 3 ? "red" : Number(skill.risk_level) >= 2 ? "amber" : "green")}${badge((skill.supported_adapters || []).join(" / ") || "无 Adapter", "cyan")}</div><div style="margin-top:14px"><span class="small">${esc(skill.description || "")}</span></div></div>`).join("")}</div>` : `<div class="empty-state">暂无 Skill manifest</div>`, "scroll")}
      ${panel(`${selectedSkill?.display_name || "Skill"} 详情`, `<pre class="json" style="margin-top:10px">${esc(JSON.stringify(selectedSkill || { status: "unavailable" }, null, 2))}</pre>`, "scroll")}
    </div>
  </div>`;
}

function simulationPage() {
  const px4 = backendStatus();
  const simulation = state.simulationStatus || {};
  const summary = fleetSummary();
  const latestSelectedAction = selectedAction();
  const smokeResult = latestSelectedAction
    ? {
        data_source: "runtime_api",
        max_altitude_m: state.maxAltitude,
        last_z: state.lastZ,
        threshold_reached: state.thresholdReached,
        ack_evidence: latestSelectedAction.ack_evidence,
        completion_evidence: latestSelectedAction.completion_evidence,
        status: latestSelectedAction.status,
        node_id: latestSelectedAction.node_id,
        backend: latestSelectedAction.backend || "px4_sitl_backend",
      }
    : {
        data_source: "unavailable",
        max_altitude_m: state.maxAltitude,
        last_z: state.lastZ,
        threshold_reached: state.thresholdReached,
        arm_ack: null,
        takeoff_ack: null,
        land_ack: null,
        backend: selectedVehicle()?.backend || null,
      };
  return `<div class="page">
    ${pageTitle("仿真中心", "PX4 SITL · Gazebo · Cesium 数字孪生 · Smoke Test", `<button class="button primary" onclick="runScenario()">进入三维态势</button><button class="button" onclick="probeRuntime({notifyUser:true})">刷新状态</button>`)}
    <div class="split-2 h-fill" style="grid-template-columns:.92fr 1.08fr">
      <div class="grid">
        ${panel("仿真环境", `<div class="cap-grid" style="grid-template-columns:repeat(2,1fr)">
          ${simCard("Gazebo", simulation.reason || "独立状态探测", simulation.status || "unknown", simulation.status === "running" ? "green" : "amber")}
          ${simCard("PX4 SITL + Gazebo", "飞控闭环验证", px4.label, px4.color)}
          ${simCard("PX4 节点", "Runtime Registry", `${summary.online}/${summary.total} 在线`, summary.online ? "green" : "amber")}
          ${simCard("Cesium", "vehicle snapshot 可视化", state.simulationReady ? "CONNECTED" : "独立服务", state.simulationReady ? "green" : "cyan")}
        </div>`)}
        ${panel(`仿真状态 ${badge(String(simulation.status || "unknown").toUpperCase(), simulation.status === "running" ? "green" : "amber")}`, `<table class="table"><tr><th>来源</th><th>注册</th><th>启用</th><th>连接</th><th>过期</th></tr><tr><td>${esc(simulation.source || "runtime_state_store")}</td><td>${simulation.total_registered_nodes ?? "--"}</td><td>${simulation.total_enabled_nodes ?? "--"}</td><td>${simulation.connected_nodes ?? "--"}</td><td>${simulation.stale_nodes ?? "--"}</td></tr></table>`)}
      </div>
      <div class="grid" style="grid-template-rows:1fr auto">
        ${panel("Runtime 载具预览", fleetPreview(), "h-fill")}
        ${panel(`所选节点动作证据 ${badge(latestSelectedAction?.status || "unknown", lifecycleColor(latestSelectedAction?.status))}`, `<pre class="json">${esc(JSON.stringify(smokeResult, null, 2))}</pre>`)}
      </div>
    </div>
  </div>`;
}

function simCard(name, detail, status, color) {
  return `<div class="cap-card"><h3>${esc(name)}</h3><div class="small">${esc(detail)}</div><div style="height:76px;margin:10px 0;border:1px solid var(--line-soft);border-radius:7px;background:linear-gradient(135deg,rgba(54,199,244,.16),rgba(66,216,131,.08)),rgba(5,14,18,.8)"></div>${badge(status, color)}</div>`;
}

async function generateRequest() {
  state.activeTrace = `trc_${Math.random().toString(16).slice(2, 10)}`;
  const payload = await callRuntime(
    "plan",
    () => window.SwarmRuntimeApi.planMission({
      mission_type: "inspection_snapshot",
      source: "ground_station",
      profile: "standard",
      objective: "园区巡检、拍照取证、返航降落",
      dry_run: true,
    }),
    () => ({ result: "unavailable", plan: null, failure_reason: "runtime_api_unreachable" })
  );
  pushEvent("MISSION_REQUEST", `生成任务请求 ${state.activeTrace}`, state.apiStatus === "live" ? "green" : "cyan");
  const planned = payload.result !== "unavailable";
  notify(planned ? "已生成 ActionRequest" : "任务规划失败", planned ? "已从 Runtime API 获取 plan-mission 结果。" : "Runtime API 未返回可用计划。", planned ? "green" : "red");
  state.lastPlanResult = payload;
  render();
}

function policyPrecheck() {
  notify("策略预检不可用", "当前 HTTP API 没有独立的 Policy 预检执行接口。", "amber");
}

function simulationPreview() {
  state.page = "simulation";
  notify("仿真中心", "仅切换视图，未启动或控制仿真进程。", "cyan");
  render();
}

function dispatchMission() {
  notify("任务未下发", "Agent Runtime 当前 real_execution_enabled=false。", "amber");
}

function actionIdentifiers(nodeId, actionType) {
  const randomId = typeof crypto?.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const suffix = `${nodeId.toLowerCase()}-${actionType}-${randomId}`;
  return {
    request_id: `req-console-${suffix}`,
    trace_id: `trace-console-${suffix}`,
    idempotency_key: `console-${suffix}`,
  };
}

function pendingActionContext(actionType, smoke = false) {
  const vehicle = selectedVehicle();
  const identifiers = actionIdentifiers(vehicle.id, smoke ? "smoke-takeoff" : actionType);
  const body = smoke
    ? {
        ...window.SwarmConsoleModel.buildRuntimeRequest(vehicle, state.targetAltitude),
        ...identifiers,
        command_source: "ground_station",
      }
    : window.SwarmConsoleModel.buildOperationalActionRequest(
        vehicle,
        actionType,
        state.targetAltitude,
        identifiers
      );
  return {
    node_id: vehicle.id,
    api_base_url: state.apiBaseUrl,
    action_type: actionType,
    smoke,
    body,
    action_id: null,
    created_at: new Date().toISOString(),
  };
}

function savePendingAction(context) {
  const key = context.body.idempotency_key;
  const index = state.pendingActions.findIndex((item) => item.body?.idempotency_key === key);
  if (index >= 0) state.pendingActions[index] = context;
  else state.pendingActions.push(context);
  persistPendingActions();
}

function clearPendingAction(context) {
  const key = context.body.idempotency_key;
  state.pendingActions = state.pendingActions.filter((item) => item.body?.idempotency_key !== key);
  persistPendingActions();
}

function actionCall(context) {
  if (context.smoke) return window.SwarmRuntimeApi.smokeTakeoff(context.body);
  if (context.action_type === "takeoff") return window.SwarmRuntimeApi.takeoff(context.body);
  return window.SwarmRuntimeApi.land(context.body);
}

function acceptActionResponse(payload, context) {
  const record = window.SwarmConsoleModel.normalizeActionRecord(payload, {
    ...context.body, action_type: context.action_type,
  });
  if (record.node_id !== context.node_id
      || record.request_id !== context.body.request_id
      || (context.action_id && record.action_id !== context.action_id)) {
    throw new Error("Runtime 动作响应身份不匹配");
  }
  context.action_id = record.action_id || context.action_id;
  context.client_status = record.action_id ? "tracking" : "接口暂不支持：缺少 action_id";
  applyActionResult({ ...payload, smoke: context.smoke }, { ...context.body, action_type: context.action_type });
  if (window.SwarmConsoleModel.isTerminalAction(record) && record.action_id) {
    clearPendingAction(context);
  } else {
    savePendingAction(context);
  }
  return record;
}

async function executePendingAction(context) {
  const key = context.body.idempotency_key;
  if (state.actionRequestsInFlight.has(key)) return;
  state.actionRequestsInFlight.add(key);
  try {
    const payload = await actionCall(context);
    const record = acceptActionResponse(payload, context);
    const confirmed = !context.smoke && record.status === "succeeded"
      && record.completion_evidence?.completion_reached === true;
    notify(
      confirmed ? "动作已由遥测确认" : "Runtime 动作返回",
      `${context.node_id} · ${record.status}`,
      confirmed ? "green" : lifecycleColor(record.status)
    );
  } catch (error) {
    applyApiFailure(context.action_type, error, false);
    context.client_status = `状态未知：${error.message}`;
    context.error_payload = error.payload || null;
    // HTTP failures can follow server admission. Recover by GET, never by
    // automatically replaying POST across a possible Runtime restart.
    if (error.payload?.action_id && error.payload?.node_id === context.node_id) {
      try {
        acceptActionResponse(error.payload, context);
      } catch (identityError) {
        context.client_status = `状态未知：${identityError.message}`;
        savePendingAction(context);
      }
    } else {
      savePendingAction(context);
    }
    notify("动作请求未确认", `${context.node_id} · ${error.message}`, "amber");
  } finally {
    state.actionRequestsInFlight.delete(key);
    await Promise.all([syncRuntimeEvents(), syncRuntimeState()]);
    renderRuntimeUpdate();
  }
}

async function recoverPendingActions() {
  if (state.apiStatus !== "live" || state.lifecycleSupported !== true) return;
  for (const context of [...state.pendingActions]) {
    if (context.api_base_url !== state.apiBaseUrl) continue;
    const key = context.body.idempotency_key;
    const discovered = state.lifecycleRecords.find((record) =>
      record.request_id === context.body.request_id && record.node_id === context.node_id
    );
    if (discovered) {
      acceptActionResponse(discovered, context);
      continue;
    }
    if (!context.action_id) {
      context.client_status = "原请求暂无可查询记录；不会自动重发";
      savePendingAction(context);
      continue;
    }
    if (state.actionRequestsInFlight.has(key)) continue;
    state.actionRequestsInFlight.add(key);
    try {
      acceptActionResponse(await window.SwarmRuntimeApi.actionStatus(context.action_id), context);
    } catch (error) {
      context.client_status = error.status === 404
        ? "Runtime 已无此动作记录，可能已重启；结果未知"
        : `动作查询失败：${error.message}`;
      savePendingAction(context);
    } finally {
      state.actionRequestsInFlight.delete(key);
    }
  }
}

function dispatchAction(actionType, options = {}) {
  if (state.lifecycleSupported !== true) {
    notify("动作未发送", "Runtime 生命周期接口不可用", "amber");
    return;
  }
  const permission = actionPermission(actionType);
  const label = options.smoke ? "Smoke Takeoff" : actionType.toUpperCase();
  if (!permission.allowed) {
    notify(`无法执行 ${label}`, permission.reason, "amber");
    return;
  }
  const context = pendingActionContext(actionType, options.smoke === true);
  try {
    savePendingAction(context);
  } catch (_error) {
    state.pendingActions = state.pendingActions.filter((item) => item !== context);
    notify("动作未发送", "浏览器无法保存请求身份，请检查本地存储权限", "red");
    return;
  }
  pushEvent("ACTION_REQUEST", `${context.node_id} 请求 ${label}`, "cyan");
  render();
  void executePendingAction(context);
}

function runOperationalTakeoff() {
  dispatchAction("takeoff");
}

function runSmokeTakeoff() {
  dispatchAction("takeoff", { smoke: true });
}

function runLand() {
  dispatchAction("land");
}

function runScenario() {
  state.page = "twin";
  render();
}

function injectFault() {
  notify("故障注入不可用", "当前 Runtime API 未提供仿真故障注入接口。", "amber");
}

function replayStep(delta) {
  const lastIndex = Math.max(0, state.runtimeEvents.length - 1);
  state.replayIndex = Math.max(0, Math.min(lastIndex, state.replayIndex + delta));
  notify("Replay Step", `当前事件：${state.replayIndex + 1} / ${state.runtimeEvents.length}`, "cyan");
  render();
}

async function replayPlay() {
  await syncRuntimeEvents({ notifyFailure: true });
  state.replayIndex = Math.min(state.replayIndex, Math.max(0, state.runtimeEvents.length - 1));
  notify("Replay Playing", state.apiStatus === "live" ? "已刷新 Runtime audit 记录。" : "Runtime API 未连接。", state.apiStatus === "live" ? "cyan" : "amber");
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
    ${designPreviewNotice("本页尚无完整 Runtime 数据契约，当前内容是界面设计预览，不代表设备、模型或用户真实在线状态。")}
    ${body}
  </div>`;
}

function designPreviewNotice(message) {
  return `<div class="design-preview-notice"><b>非 LIVE 数据</b><span>${esc(message)}</span></div>`;
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
  const api = runtimeApiStatus();
  const dataSource = dataSourceStatus();
  const summary = fleetSummary();
  const now = new Date();
  const fleetState = state.apiStatus === "checking"
    ? "检查中"
    : summary.total > 0 && summary.online === summary.total
      ? "HEALTHY"
      : summary.online > 0 ? "DEGRADED" : "OFFLINE";
  return `<header class="topbar">
    <div class="brand"><div class="mark"></div><div class="brand-title">2026UAVSwarm Console</div></div>
    <div class="top-pill profile-pill">Ground Profile</div>
    <div class="top-pill">Fleet Telemetry<strong class="${state.backendConnected ? "green" : "amber"}">${fleetState}</strong></div>
    <div class="top-pill">在线节点<strong>${summary.online} / ${summary.total}</strong></div>
    <div class="top-pill">目标载具<strong>${esc(state.selectedUav || "--")}</strong></div>
    <div class="top-pill">当前 Action<strong>${esc(state.currentAction)}</strong></div>
    <div class="top-pill">Runtime API<strong class="${api.color}">${api.label}</strong></div>
    <div class="top-pill">数据源<strong class="${dataSource.color}">${dataSource.label}</strong></div>
    <div class="top-actions">
      <button class="icon-btn" title="三维态势" onclick="setPage('twin')">3D</button><button class="icon-btn" title="状态说明" onclick="showStatusHelp()">?</button><button class="icon-btn" title="刷新 Runtime" onclick="probeRuntime({notifyUser:true})">R</button>
      <div class="operator"><div class="avatar"></div><div><div>Operator_01</div><div class="small">管理员</div></div></div>
      <div class="small top-time">${esc(now.toLocaleDateString("zh-CN"))}<br>UTC+8</div>
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
  if (page === "twin") state.simulationReady = false;
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
probeRuntime();

app.addEventListener("click", (event) => {
  const target = event.target.closest("[data-vehicle-id]");
  if (target) selectVehicle(target.dataset.vehicleId);
});

function renderRuntimeUpdate() {
  if (state.page === "twin") {
    postVehicleSnapshot();
    return;
  }
  if (document.activeElement?.matches("input, textarea, select")) return;
  render();
}

window.addEventListener("message", (event) => {
  const frame = document.getElementById("simulation-frame");
  if (!frame?.contentWindow || event.source !== frame.contentWindow) return;
  if (event.origin !== simulationOrigin()) return;
  if (event.data?.type !== "uav-swarm/simulation-ready") return;
  if (!window.SwarmConsoleModel.validateSimulationReadyMessage(event.data)) {
    state.simulationReady = false;
    state.simulationContractError = "三维消息契约不兼容，要求 parent-snapshot 1.0";
    renderRuntimeUpdate();
    return;
  }
  state.simulationReady = true;
  state.simulationContractError = null;
  const note = document.querySelector(".simulation-frame-note");
  if (note) note.textContent = `Runtime 快照由主控制台统一推送；${simulationAlignmentStatus().label}`;
  const headingBadge = document.querySelector(".twin-panel .badge");
  if (headingBadge) {
    headingBadge.textContent = "CONNECTED";
    headingBadge.className = "badge green";
  }
  postVehicleSnapshot();
});

setInterval(async () => {
  if (state.apiStatus === "offline") {
    if (document.activeElement?.matches("input, textarea, select")) return;
    probeRuntime();
    return;
  }
  if (state.apiStatus === "live") {
    await syncRuntimeState({ notifyFailure: false });
    renderRuntimeUpdate();
  }
}, 2000);

setInterval(async () => {
  if (state.apiStatus !== "live") return;
  await syncRuntimeEvents({ notifyFailure: false });
  renderRuntimeUpdate();
}, 5000);
