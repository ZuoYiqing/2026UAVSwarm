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
  ["observation", "观察复核", "OR"],
  ["clarification", "澄清待办", "CL"],
  ["assets", "硬件资产", "HW"],
  ["replay", "Audit / Replay", "RP"],
  ["model", "模型与知识", "MK"],
  ["settings", "系统设置", "ST"],
];

const ACTION_STORAGE_KEY = "swarm-console.pending-actions.v1";
const dashboard = window.SwarmMissionDashboard;
const missionPhases = new Map([["running", "执行中"], ["completed", "已完成"], ["failed", "失败"], ["blocked", "受阻"]]);
const fixtureReceiptNames = new Map([
  ["running", "Runtime 已受理"], ["completed", "执行已完成"], ["failed", "执行失败"],
  ["blocked", "执行受阻"], ["declined", "审批已拒绝"],
]);
// The browser Runtime API provides no plan-write transport. Tests inject this adapter in memory.
const missionFixture = window.SwarmRuntimeApi?.missionFixture;
const FIXTURE_PLAN_PREVIEW_TTL_MS = 60_000;
let fixturePreviewFrame = null;
const pageParams = new URL(window.location?.href || "http://127.0.0.1:5178/").searchParams;
const stageMode = pageParams.get("mode") === "stage";
const builtInDemo = stageMode && pageParams.get("source") !== "live";
const liveStages = [
  { view: "map", title: "任务地图", detail: "任务区、覆盖记录与载具位置。" },
  { view: "kpi", title: "任务状态", detail: "遥测接收新鲜度、任务进度与安全状态。" },
  { view: "timeline", title: "审计事件", detail: "查看近期策略裁决和动作结果。" },
  { view: "twin", title: "三维态势", detail: "由 Runtime 快照驱动的三维视图。" },
];
const liveStageSeconds = 18;
const stagePlayback = { elapsed: 0, startedAt: builtInDemo ? performanceNow() : null };
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
  linkIssues: null,
  selectedUav: null,
  apiBaseUrl: window.SwarmRuntimeApi?.getConfiguredBaseUrl?.() || "http://127.0.0.1:8765/api",
  apiStatus: "checking",
  apiLastError: null,
  runtimeHealth: null,
  lastProbeAt: null,
  dataStatus: "checking",
  lastBackendResult: null,
  lastActionResult: null,
  templatePlan: { objective: "", inFlight: false, slowHint: "", reply: null, error: null },
  fixturePlan: {},
  semanticPreview: {},
  semanticPreviewDetailsOpen: false,
  semanticLive: { objective: "", inFlight: false, result: {}, health: null, healthInFlight: false, healthError: null },
  semanticLiveDetailsOpen: false,
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
  auditEvents: null,
  replayEvents: null,
  auditStatus: "waiting",
  runtimeSnapshotCurrent: false,
  auditInFlight: false,
  decisionsLoaded: false,
  lifecycleLoaded: false,
  mission: null,
  missionStatus: "waiting",
  links: new Map(),
  linkTrends: new Map(),
  missionTrend: "",
  demoRuntime: null,
  demoWriteInFlight: false,
  demoWriteStatus: "",
  stageFrame: null,
  stageMarkup: "",
  timelineKey: null,
  policyFilters: { node: "", decision: "" },
  policySeen: new Set(),
  policyBannerReady: false,
  policyBanner: null,
  stateSyncInFlight: false,
  simulationReady: false,
  simulationContractError: null,
  simulationAlignment: "unknown",
  simulationUrl: "http://127.0.0.1:5179/",
  toast: [],
};

function performanceNow() {
  return window.performance?.now() ?? Date.now();
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
  if (stageMode) return { allowed: false, reason: "演示大屏仅供观看" };
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
    state.links.clear();
    state.linkTrends.clear();
    if (state.mission) state.missionStatus = "stale";
    state.missionTrend = "";
    state.demoRuntime = null;
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
  if (state.auditInFlight || builtInDemo) return;
  const source = state.apiBaseUrl;
  state.auditInFlight = true;
  try {
    const api = window.SwarmRuntimeApi;
    const [eventRead, replayRead] = await Promise.allSettled([api.events(50), api.replayLast?.(20)]);
    if (state.apiBaseUrl !== source) return;
    const payload = eventRead.status === "fulfilled" && Array.isArray(eventRead.value) ? eventRead.value : null;
    const replay = replayRead.status === "fulfilled" && Array.isArray(replayRead.value) ? replayRead.value : null;
    if (payload) state.auditEvents = payload;
    if (replay) state.replayEvents = replay;
    state.auditStatus = payload && replay ? "live" : payload || replay ? "partial" : "unavailable";
    const audit = payload || replay;
    if (!audit) {
      if (options.notifyFailure) notify("审计暂不可用", "等待 Runtime 事件或回放接口响应", "amber");
      return;
    }
    state.runtimeEvents = audit.slice().reverse().slice(0, 30);
    updatePolicyBanner();
  } catch (error) {
    state.auditStatus = "unavailable";
    if (options.notifyFailure) notify("审计暂不可用", error.message, "amber");
  } finally {
    state.auditInFlight = false;
  }
}

async function probeRuntime(options = {}) {
  if (builtInDemo) return;
  const source = state.apiBaseUrl;
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
    if (state.apiBaseUrl !== source) return;
    applyApiSuccess("health", healthPayload);
    await Promise.all([
      syncRuntimeState({ notifyFailure: false }),
      syncRuntimeEvents({ notifyFailure: false }),
    ]);
    if (options.notifyUser) {
      notify("Runtime API 已连接", state.apiBaseUrl, "green");
    }
  } catch (error) {
    if (state.apiBaseUrl !== source) return;
    applyApiFailure("health", error, options.notifyUser === true);
  }
  renderRuntimeUpdate();
}

async function syncRuntimeState(options = {}) {
  if (builtInDemo || state.stateSyncInFlight || !window.SwarmRuntimeApi) return;
  const source = state.apiBaseUrl;
  state.stateSyncInFlight = true;
  try {
    const api = window.SwarmRuntimeApi;
    const calls = {
      runtimeSnapshot: api.snapshot(),
      telemetry: api.telemetryLatest(),
      vehicleSnapshot: api.vehicleSnapshot(),
      agentStatus: api.agentStatus(),
      simulationStatus: api.simulationStatus(),
      registryPayload: api.vehicles(),
      skillsPayload: api.skills(),
      policyDecisions: api.policyDecisions(20),
      recentActions: api.recentActions(20),
      lifecycleRecords: api.actionLifecycle(20),
      missionProgress: api.missionProgress?.(),
      demoRuntime: stageMode ? undefined : api.demoState?.(),
    };
    const optional = new Set(["missionProgress", "demoRuntime"]);
    const keys = Object.keys(calls);
    const results = await Promise.allSettled(Object.values(calls));
    if (state.apiBaseUrl !== source) return;
    const resultsByKey = Object.fromEntries(keys.map((key, index) => [key, results[index]]));
    const required = keys.filter(key => !optional.has(key));
    const failed = required.filter(key => resultsByKey[key].status === "rejected");
    for (const key of required) {
      if (resultsByKey[key].status === "fulfilled") state[key] = resultsByKey[key].value;
    }
    updateMissionDashboard(resultsByKey);
    state.decisionsLoaded = Array.isArray(resultsByKey.policyDecisions?.value);
    state.lifecycleLoaded = Array.isArray(resultsByKey.lifecycleRecords?.value);
    state.runtimeSnapshotCurrent = Array.isArray(resultsByKey.runtimeSnapshot?.value?.active_actions);
    if (failed.length === required.length) {
      state.links.clear();
      state.linkTrends.clear();
      applyApiFailure("snapshot", resultsByKey[failed[0]].reason, options.notifyFailure === true);
      return;
    }

    state.apiStatus = "live";
    state.apiLastError = failed.length ? `${failed.length} 个状态接口不可用` : null;
    const criticalStateFailed = [["telemetry", "nodes"], ["vehicleSnapshot", "vehicles"], ["registryPayload", "vehicles"]]
      .some(([key, field]) => !Array.isArray(resultsByKey[key]?.value?.[field]));
    updatePolicyBanner();
    if (criticalStateFailed) {
      state.links.clear();
      state.linkTrends.clear();
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
    updateMissionLinks();
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
    state.linkIssues = state.fleet.filter((vehicle) => vehicle.enabled && (!vehicle.connected || vehicle.stale)).length;
    state.dataStatus = state.telemetry?.status === "ok"
      ? "live"
      : state.telemetry?.status === "stale"
        ? "stale"
        : "unavailable";
    updateSelectedTelemetry();
    postVehicleSnapshot();
    if (!stageMode) await recoverPendingActions();
    updateSelectedTelemetry();
  } catch (error) {
    applyApiFailure("snapshot-contract", error, options.notifyFailure === true);
  } finally {
    state.stateSyncInFlight = false;
  }
}

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

function metric(title, value, detail, color = "cyan", metricKey = "") {
  // metricKey 用于同页局部更新时的定点定位（见 updatePageInPlace）。
  // 没有它的指标只能在整块重建时更新，而整块重建会连带重建三维视图的 iframe。
  const keyAttr = metricKey ? ` data-metric="${esc(metricKey)}"` : "";
  return `<section class="metric">
    <label>${esc(title)}</label>
    <b class="${color}"${keyAttr}>${esc(value)}</b>
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

function vehicleTable() {
  // 空状态与表格**同时**存在，由 CSS/JS 控制显隐，而不是二选一渲染。
  //
  // 为什么不能二选一：首次渲染时数据往往还没到，若那时只渲染空状态、不建
  // #vehicle-table-body 锚点，之后数据到达时局部更新找不到锚点就什么都不做，
  // 表格永远不会出现（实测踩到：fleet 已有 3 台，界面停在"尚未提供载具"）。
  //
  // 但**只保留锚点还不够**：空状态 div 若由首屏决定是否渲染，数据到达后它不会被
  // 移除 —— 于是出现"表格已有 3 行、下面还写着'尚未提供载具'"（实测截图确认）。
  // 因此空状态固定渲染，显隐交给 updatePageInPlace()。
  return `<table class="table" id="vehicle-table">
    <thead><tr><th>节点</th><th>状态</th><th>Identity</th><th>模式</th><th>高度</th><th>电量</th></tr></thead>
    <tbody id="vehicle-table-body">${vehicleTableRows()}</tbody>
  </table>
  <div class="empty-state" id="vehicle-table-empty" ${state.fleet.length ? "hidden" : ""}>Runtime 尚未提供已注册载具</div>`;
}

/** 只生成表格行，供同页局部更新使用（不重建整个表格）。 */
function vehicleTableRows() {
  return state.fleet.map((vehicle) => `
      <tr class="selectable-row ${vehicle.id === state.selectedUav ? "selected" : ""}" data-vehicle-id="${esc(vehicle.id)}">
        <td><b>${esc(vehicle.displayName)}</b></td>
        <td>${badge(vehicle.connected ? "在线" : vehicle.stale ? "过期" : "离线", vehicle.connected ? "green" : vehicle.stale ? "amber" : "red")}</td>
        <td>${esc(`${vehicle.systemId ?? "-"}/${vehicle.componentId ?? "-"}`)}</td>
        <td>${esc(vehicle.activeAction || vehicle.flightMode || "--")}</td>
        <td>${esc(formatNumber(vehicle.altitudeM, 1, " m"))}</td>
        <td>${esc(formatNumber(vehicle.batteryPercent, 0, "%"))}</td>
      </tr>
    `).join("");
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
  let source = builtInDemo ? new URL("?mode=demo", state.simulationUrl).href : state.simulationUrl;
  if (fixturePlanPreviewPage()) {
    const url = new URL(source, window.location.href);
    url.searchParams.set("planPreview", "fixture");
    source = url.href;
  }
  return `<div class="simulation-frame-wrap">
    <iframe id="simulation-frame" class="simulation-frame" src="${esc(source)}" title="Cesium 三维集群态势"${stageMode ? ' inert tabindex="-1"' : ""}></iframe>
    <div class="simulation-frame-note ${alignment.color}">${esc(
      state.simulationContractError
        || (state.simulationReady ? (builtInDemo ? "DEMO · Cesium 内置场景" : `Runtime 快照由主控制台统一推送；${alignment.label}`) : "等待 5179 三维服务响应")
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

function fixturePlanPreviewPage() {
  return Boolean(missionFixture) && !stageMode && state.page === "twin";
}

function currentFixturePlanPreview() {
  const preview = state.fixturePlan.preview;
  return preview && Date.now() < preview.expires_at_ms ? preview : null;
}

function syncFixturePlanPreview() {
  if (!fixturePlanPreviewPage()) return;
  const payload = currentFixturePlanPreview();
  const control = document.getElementById("fixture-plan-preview-clear");
  if (control) control.disabled = payload === null;
  const frame = document.getElementById("simulation-frame");
  const origin = simulationOrigin();
  if (frame !== fixturePreviewFrame || !frame?.contentWindow || !state.simulationReady || !origin) return;
  frame.contentWindow.postMessage({ type: "uav-swarm/plan-preview", payload }, origin);
}

function clearFixturePlanPreview() {
  const draft = state.fixturePlan;
  if (!draft.preview) return;
  window.clearTimeout(draft.previewTimer);
  draft.previewTimer = null;
  draft.preview = null;
  syncFixturePlanPreview();
}

function setFixturePlanDraft(draft = {}) {
  if (state.fixturePlan.previewTimer != null) window.clearTimeout(state.fixturePlan.previewTimer);
  state.fixturePlan = draft;
  syncFixturePlanPreview();
}

async function postVehicleSnapshot() {
  if (builtInDemo) return;
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

/**
 * 把"当前选中载具"推给三维视图。
 *
 * 两侧本来是各自独立的：主控制台有它的节点列表选中项，三维视图有它自己的
 * 选中项。用户在任一侧切换，另一侧不会跟随——表现为"右边选了 UAV-02，
 * 左边还停在前一台"。
 *
 * 用与快照同一条 postMessage 通道，不引入新的通信机制。
 */
function syncSelectionToSimulation(nodeId) {
  const frame = document.getElementById("simulation-frame");
  const origin = simulationOrigin();
  if (!frame?.contentWindow || !origin) return;
  frame.contentWindow.postMessage(
    { type: "uav-swarm/select-vehicle", payload: { nodeId: nodeId || null } },
    origin,
  );
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

/**
 * 选中载具（主控制台内的唯一入口）。
 *
 * @param {string} nodeId
 * @param {object} [options]
 * @param {boolean} [options.fromSimulation=false]
 *   为 true 表示这次选中是三维视图推过来的，**不再回推**，否则两侧会互相触发
 *   形成环路。用显式参数而不是"当前是否在处理消息"之类的全局标志：后者容易
 *   因为消息时序（推送在途时刚好有一次本地操作）而失效。
 */
function selectVehicle(nodeId, { fromSimulation = false } = {}) {
  if (!state.fleet.some((vehicle) => vehicle.id === nodeId)) return;
  if (state.selectedUav === nodeId) return;
  state.selectedUav = nodeId;
  updateSelectedTelemetry();
  // updateSelectedTelemetry() 只更新状态；显示也必须立即跟随请求目标。
  // 复用 renderRegions()/updatePageInPlace()：twin 局部更新保留 iframe，
  // 其它页面重绘 endpoint、MAVLink identity 和所选节点的动作证据。
  render();
  if (!fromSimulation) syncSelectionToSimulation(nodeId);
}

function updateMissionDashboard(reads) {
  if (!dashboard) return;
  const progressRead = reads.missionProgress;
  const payload = progressRead?.status === "fulfilled" ? progressRead.value : undefined;
  const progress = dashboard.runtimeMissionProgress(payload);
  const previous = state.mission;
  if (progress) {
    if (previous?.id !== progress.id || previous?.runId !== progress.runId || state.missionStatus !== "live") {
      state.missionTrend = "";
    } else if (previous.completion !== progress.completion) {
      state.missionTrend = dashboard.trend(previous.completion, progress.completion);
    }
    state.missionStatus = "live";
  } else {
    state.missionTrend = "";
    if (progressRead?.status === "rejected") {
      state.missionStatus = "error";
    } else if (payload?.contract_version === "1.0" && payload.source === "runtime_plan_executor" && payload.mode === "LIVE"
      && payload.status === "unavailable"
      && payload.reason === "no_runtime_plan_execution") {
      state.missionStatus = "empty";
    } else {
      state.missionStatus = payload === undefined ? "waiting" : "invalid";
    }
  }
  state.mission = progress;
  const demo = reads.demoRuntime;
  const demoState = demo?.status === "fulfilled" ? demo.value : null;
  state.demoRuntime = demoState?.enabled === true && demoState.mode === "DEMO"
    && demoState.execution_authorized === false && demoState.flight_command_sent === false ? demoState : null;
}

function updateMissionLinks() {
  if (!dashboard) return;
  const next = dashboard.linkScores(state.vehicleSnapshot, state.telemetry, state.fleet);
  for (const [id, value] of next) {
    const previous = state.links.get(id);
    if (previous !== value) state.linkTrends.set(id, dashboard.trend(previous, value));
  }
  for (const id of state.links.keys()) if (!next.has(id)) state.linkTrends.delete(id);
  state.links = next;
}

function missionTimeline() {
  if (builtInDemo) return state.stageFrame?.timeline || [];
  return dashboard?.timeline({
    events: state.auditEvents, replay: state.replayEvents,
    decisions: state.policyDecisions, lifecycle: state.lifecycleRecords,
  }) || [];
}

function decisionIdentity(entry) {
  if (entry.timestamp && entry.raw.request_id) {
    return JSON.stringify([entry.timestamp, entry.raw.request_id, entry.node, entry.action, entry.decision]);
  }
  return entry.raw.decision_id || entry.key;
}

function updatePolicyBanner() {
  const entries = missionTimeline().filter(entry => entry.type === "policy_decision_event");
  let latest = null;
  for (const entry of entries) {
    const id = decisionIdentity(entry);
    if (state.policyBannerReady && !state.policySeen.has(id)) {
      if (!latest || entry.color === "red" || latest.color !== "red") latest = entry;
    }
    state.policySeen.add(id);
  }
  // Initial live history is a baseline. Built-in DEMO starts with an empty timeline.
  if (state.auditEvents || state.replayEvents || state.decisionsLoaded || builtInDemo) state.policyBannerReady = true;
  if (!latest) return;
  const notice = { entry: latest, compact: false };
  state.policyBanner = notice;
  renderPolicyBanner();
  window.setTimeout(() => {
    if (state.policyBanner !== notice) return;
    notice.compact = true;
    renderPolicyBanner();
  }, 2000);
}

function isDemoEvent(entry) {
  return String(entry.raw.data_mode ?? entry.raw.execution_mode ?? entry.raw.mode ?? entry.raw.source ?? "").toLowerCase() === "demo"
    || entry.raw.demo === true || entry.raw.simulated === true || entry.type.startsWith("demo_")
    || entry.raw.backend_mode === "fake" || entry.raw.adapter === "fake";
}

function renderPolicyBanner() {
  const slot = document.getElementById("slot-banner");
  if (!slot) return;
  const notice = state.policyBanner;
  const renderKey = notice ? notice.entry.key + ":" + notice.compact : "";
  if (slot.dataset?.notice === renderKey) return;
  if (slot.dataset) slot.dataset.notice = renderKey;
  if (!notice) {
    slot.innerHTML = "";
    return;
  }
  const { entry, compact } = notice;
  const fromDemo = builtInDemo || isDemoEvent(entry);
  const subject = [fromDemo ? "DEMO" : "", entry.node, entry.quality !== null ? "链路 " + entry.quality : "",
    entry.action, entry.decision.toUpperCase()].filter(Boolean).join(" · ");
  const label = `${esc(subject)}${!compact && (entry.rule || entry.reason)
    ? `<small>${esc([entry.rule, entry.reason].filter(Boolean).join(" · "))}</small>` : ""}`;
  slot.innerHTML = `<div class="policy-banner ${entry.color} ${compact ? "is-compact" : ""}" role="status">
    ${stageMode ? `<span class="policy-banner-main">${label}</span>`
      : `<button class="policy-banner-main" data-policy-open title="查看这条策略裁决">${label}</button>`}
    <button class="policy-banner-close" data-policy-dismiss aria-label="关闭策略提示">×</button>
  </div>`;
}

function sourceLabel() {
  if (builtInDemo) return { text: "DEMO · 内置演习", color: "amber" };
  if (missionFixture) return { text: "测试桩 · 设备巡检导航", color: "amber" };
  const snapshot = state.vehicleSnapshot;
  const hasOverride = Array.isArray(snapshot?.vehicles)
    && snapshot.vehicles.some(row => String(row?.link_quality_mode).toUpperCase() === "DEMO");
  const isFixture = /fixture|demo|fake/i.test(String(state.runtimeHealth?.service || ""))
    || /fixture|demo|fake/i.test(String(snapshot?.source?.kind || "")) || /fixture|demo|fake/i.test(String(snapshot?.source?.id || ""));
  if (hasOverride || state.demoRuntime?.overrides?.length) {
    return { text: "DEMO · Runtime 链路注入", color: "amber" };
  }
  if (state.demoRuntime?.held_out?.length) return { text: "DEMO · Runtime 演习", color: "amber" };
  if (state.mission?.mode === "DEMO") return { text: "DEMO · Runtime 任务演习", color: "amber" };
  if (isFixture) return { text: "DEMO · 测试数据", color: "amber" };
  const fresh = state.apiStatus === "live" && state.dataStatus === "live";
  const telemetrySource = snapshot?.source?.kind === "simulation"
    ? (/\bSITL\b/i.test(snapshot.source.label ?? "") ? "PX4 SITL 遥测" : "仿真遥测") : "Runtime 遥测";
  return { text: fresh ? `LIVE · ${telemetrySource}` : "LIVE · 等待新鲜遥测", color: fresh ? "green" : "amber" };
}

function currentMission() {
  if (builtInDemo) return state.stageFrame?.progress;
  return state.apiStatus === "live" && state.missionStatus === "live" ? state.mission : null;
}

function missionReadLabel() {
  if (state.missionStatus === "stale") return "最后上报 · 当前进度未知";
  if (state.apiStatus === "offline" || state.missionStatus === "error") return "Runtime 任务进度读取失败";
  if (state.missionStatus === "empty") return "Runtime 尚无任务执行";
  if (state.missionStatus === "invalid") return "Runtime 任务进度证据不完整";
  return "尚未收到任务执行数据";
}

function missionIndicators(compact = false) {
  const frame = state.stageFrame;
  const mission = currentMission();
  const links = builtInDemo ? frame?.links : state.links;
  const degraded = !builtInDemo && state.apiStatus !== "live";
  const overrides = builtInDemo ? [] : dashboard?.rows(state.vehicleSnapshot?.vehicles)
    .filter(row => row.link_quality_mode === "DEMO" && links.has(row.id)) || [];
  const override = overrides.find(row => row.id === state.selectedUav) || overrides[0];
  const quality = !degraded && links?.size ? override ? links.get(override.id) : Math.min(...links.values()) : null;
  const node = quality === null ? null : override?.id ?? [...links].find(([, value]) => value === quality)?.[0];
  const measured = dashboard?.pct(override?.link_quality_measured) ?? null;
  const linkArrow = builtInDemo ? frame?.linkTrend : state.linkTrends.get(node);
  const completion = mission?.completion ?? null;
  const completionLabel = mission?.completionBasis === "verified_waypoints" ? "航点完成度" : "任务完成度";
  const missionArrow = builtInDemo ? frame?.progressTrend : state.missionTrend;
  const safety = typeof mission?.safety === "string" ? mission.safety : null;
  const color = quality === null ? "muted" : quality < 40 ? "red" : quality < 80 ? "amber" : "green";
  const areaDigits = mission?.areaTotal < 0.01 ? 6 : 3;
  const area = mission?.areaCovered != null
    ? `${formatNumber(mission.areaCovered, areaDigits)} / ${formatNumber(mission.areaTotal, areaDigits)} km²` : "等待覆盖证据";
  const targets = mission?.targetsFound !== null && mission?.targetsFound !== undefined
    ? `${mission.targetsFound} / ${mission.targetsTotal ?? "—"}` : "等待目标证据";
  if (compact) return `<div class="stage-kpi-strip">
    <span>链路质量 <b class="${color}">${quality === null ? "—" : esc(quality + " " + (linkArrow || ""))}</b></span>
    <span>${completionLabel} <b>${completion === null ? "—" : esc(`${completion}% ${missionArrow || ""}`)}</b></span>
    <span>剩余安全裕度 <b>${esc(safety || "未知")}</b></span>
  </div>`;
  return `<div class="mission-kpis" aria-label="任务状态指标">
    <section class="mission-kpi ${color}">
      <h2>链路质量</h2><strong>${quality === null ? "—" : formatNumber(quality, Number.isInteger(quality) ? 0 : 1)}
        <span class="kpi-trend" aria-hidden="true">${esc(linkArrow || "")}</span></strong>
      <p>${node ? `${builtInDemo ? "演习最低读数" : override ? "DEMO 注入" : "最低已上报"} · ${esc(node)} / 100
        ${measured === null ? "" : ` · 实测 ${measured}`}
        ${links.size < (builtInDemo ? frame.fleet : state.fleet).filter(v => v.enabled !== false).length ? " · 部分节点缺数据" : ""}` : "等待链路质量数据"}</p>
      ${quality !== null && !builtInDemo ? '<p>遥测接收新鲜度评分</p>' : ""}
    </section>
    <section class="mission-kpi cyan">
      <h2>${completionLabel}</h2><strong>${completion === null ? "—" : formatNumber(completion, Number.isInteger(completion) ? 0 : 1) + "%"}
        <span class="kpi-trend" aria-hidden="true">${esc(completion === null ? "" : missionArrow || "")}</span></strong>
      ${completion === null ? "" : `<progress max="100" value="${completion}" aria-label="${completionLabel}"></progress>`}
      <p>${mission ? esc(mission.title) : missionReadLabel()}
        ${mission?.completionBasis === "verified_waypoints" ? " · 已验证航点" : ""}</p>
    </section>
    <section class="mission-kpi ${safety === "正常" || safety === "normal" ? "green" : safety ? "amber" : "muted"}">
      <h2>剩余安全裕度</h2><strong class="kpi-word">${esc(safety || "未知")}
        ${builtInDemo && frame?.safetyTrend ? `<span class="kpi-trend" aria-hidden="true">${frame.safetyTrend}</span>` : ""}</strong>
      <p>${safety ? (builtInDemo ? "演习脚本" : "任务层上报") : "等待安全证据"}</p>
    </section>
    <div class="mission-evidence"><span>覆盖面积 <b>${esc(area)}</b></span><span>目标发现 <b>${esc(targets)}</b></span>
      ${mission?.vehiclesActive == null ? "" : `<span>任务中载具 <b>${mission.vehiclesActive}</b></span>`}
      ${mission?.degraded === true ? badge("降级任务", "amber") : ""}
      ${!builtInDemo && mission ? `<span>执行状态 <b>${esc(missionPhases.get(mission.status) || "未知")}</b></span>` : ""}
      ${mission?.timestamp ? `<span>${builtInDemo ? "演习时刻" : "采样"} <b>${esc(eventTime(mission.timestamp))}</b></span>` : ""}
    </div>
  </div>`;
}

function missionMapMetrics(mission) {
  const verifiedWaypoints = mission?.completionBasis === "verified_waypoints";
  const completion = verifiedWaypoints || builtInDemo ? mission?.completion ?? null : null;
  const reached = mission?.waypointsReached;
  const total = mission?.waypointsTotal;
  const hasWaypointCount = reached != null && total > 0 && reached <= total;
  const coverage = mission?.coveragePercent ?? null;
  const areaDigits = mission?.areaTotal < 0.01 ? 6 : 3;
  const waypointDetail = hasWaypointCount ? `${reached} / ${total} 个航点` : builtInDemo ? "内置演习进度" : "已验证到达";
  const percent = value => value === null ? "—" : formatNumber(value, Number.isInteger(value) ? 0 : 2, "%");
  return `<div class="mission-map-metrics">
    <div><span>${builtInDemo && !verifiedWaypoints ? "任务完成度" : "航点完成度"}</span><b>${percent(completion)}</b>
      <small>${completion === null ? "等待已验证航点" : waypointDetail}</small></div>
    <div><span>面积覆盖率</span><b>${percent(coverage)}</b>
      <small>${coverage === null ? "等待覆盖证据" : `${formatNumber(mission.areaCovered, areaDigits)} / ${formatNumber(mission.areaTotal, areaDigits)} km²`}</small></div>
  </div>`;
}

function missionMapPanel() {
  const frame = state.stageFrame;
  const mission = currentMission();
  const fleet = builtInDemo ? frame?.fleet || [] : state.fleet;
  const snapshot = builtInDemo ? frame?.vehicleSnapshot
    : state.apiStatus === "live" && state.dataStatus === "live" ? state.vehicleSnapshot : null;
  const map = dashboard?.missionMap(mission, snapshot);
  const positionMap = map ? null : dashboard?.fleetMap(snapshot);
  const assignments = mission?.assignments || [];
  const ids = new Set([...fleet.map(v => v.id), ...assignments.map(a => a.node_id || a.vehicle_id).filter(Boolean)]);
  const roster = [...ids].map(id => {
    const assignment = assignments.find(a => (a.node_id || a.vehicle_id) === id);
    const vehicle = fleet.find(v => v.id === id);
    const pct = dashboard?.assignmentProgress(assignment) ?? null;
    const region = assignment?.region_label || assignment?.region_id || assignment?.task_name
      || (assignment?.waypoints_total > 0 ? `航点 ${assignment.waypoints_reached ?? "—"} / ${assignment.waypoints_total}` : "未收到任务分工");
    const telemetry = vehicle?.stale ? "遥测过期" : state.dataStatus === "live" && vehicle
      ? (vehicle.connected ? "遥测在线" : "遥测离线") : "等待遥测";
    const phase = assignment?.status || (assignment?.active === true ? "任务中" : assignment?.active === false ? "未在任务中" : telemetry);
    return `<div class="mission-roster-row">
      <b>${esc(id)}</b><span>${esc(region)}</span>
      <span>${pct === null ? "—" : formatNumber(pct, Number.isInteger(pct) ? 0 : 1, "%")}${pct === null ? "" : `<progress aria-label="${esc(id)} 进度" max="100" value="${pct}"></progress>`}</span>
      <small>${esc(phase)}</small>
    </div>`;
  }).join("");
  const grid = map?.coverageGrid;
  const coverage = region => {
    if (grid && grid.areaId === region.area_id) return "uncovered";
    return builtInDemo && ["covered", "uncovered"].includes(region.coverage_status) ? region.coverage_status : "unknown";
  };
  const markerHtml = (map ?? positionMap)?.markers.map(marker => `<span class="mission-map-node" style="left:${marker.x}%;top:${marker.y}%">${esc(marker.id)}</span>`).join("") || "";
  const geometry = map ? `<div class="mission-map">
    <span class="mission-compass" aria-hidden="true">↑ 北</span>
    ${map.regions.map(region => `<div class="mission-region ${coverage(region)}" title="${esc(region.label || region.area_id || "任务区域")}"
      style="clip-path:polygon(${region.projected.map(point => point.x + "% " + point.y + "%").join(",")})"></div>`).join("")}
    ${grid ? '<canvas class="mission-coverage-grid" width="1600" height="1000" aria-hidden="true"></canvas>' : ""}
    ${markerHtml}
    ${markerHtml ? "" : `<span class="mission-map-caption">等待同场景的可用载具位置</span>`}
  </div>
  <div class="mission-legend">${grid
    ? `<span class="grid-covered">有覆盖记录的格</span><span class="uncovered">无覆盖记录</span>${map.regions.some(region => region.area_id !== grid.areaId) ? '<span class="unknown">覆盖分布未知</span>' : ""}`
    : builtInDemo ? '<span class="covered">已覆盖</span><span class="uncovered">未覆盖</span><span class="unknown">覆盖未知</span>'
      : '<span class="unknown">覆盖分布未知</span>'}</div>`
    : positionMap
      ? `<div class="mission-map mission-position-map" aria-label="载具位置俯视图">
          <span class="mission-compass" aria-hidden="true">↑ 北</span>${markerHtml}
          <span class="mission-map-caption">载具位置 · ${esc(positionMap.scene)} · 场景坐标</span></div>
        <p class="small mission-grid-note">任务区域与覆盖分布待 Runtime 上报</p>`
      : `<div class="mission-wait"><b>${mission ? "暂无任务区域边界" : missionReadLabel()}</b>
          <span>${state.dataStatus === "live" ? "遥测在线，俯视图仍需可用的共享坐标或任务区边界。" : "等待 Runtime 上报任务区域或载具共享坐标。"}</span></div>`;
  const phaseLabel = missionPhases.get(mission?.status);
  const titleDetail = mission ? `${mission.title}${phaseLabel ? " · " + phaseLabel : ""}` : "任务区域与载具位置";
  return `<section class="panel mission-map-panel"><div class="panel-title"><h2>任务地图</h2><span class="small">${esc(titleDetail)}</span></div>
    ${mission?.runId && !builtInDemo ? `<p class="small">Runtime 运行 ID <b>${esc(mission.runId)}</b></p>` : ""}
    ${missionMapMetrics(mission)}
    ${geometry}
    ${grid ? `<p class="small mission-grid-note">${grid.size} m 网格 · ${grid.cells.length
      ? `${grid.cells.length} 个格有覆盖记录，格内可能仅部分覆盖` : "已有观测，当前没有覆盖记录"}</p>` : ""}
    <div class="mission-roster">
      <div class="mission-roster-row mission-roster-head"><span>载具</span><span>任务分工</span><span>进度</span><span>状态</span></div>
      ${roster || '<p class="small">尚未收到载具或任务分工</p>'}</div>
  </section>`;
}

function drawMissionCoverage() {
  const canvas = document.querySelector(".mission-coverage-grid");
  if (!canvas) return;
  const map = dashboard?.missionMap(state.mission, null);
  window.SwarmCoverageGrid?.draw(canvas, map?.coverageGrid);
}

function missionMetricsBar() {
  const frame = state.stageFrame;
  const fleet = builtInDemo ? frame?.fleet || [] : state.fleet;
  const api = runtimeApiStatus();
  const source = sourceLabel();
  const timeline = missionTimeline();
  const auditReady = builtInDemo || state.apiStatus === "live" && (state.decisionsLoaded || state.auditStatus !== "unavailable" && state.auditStatus !== "waiting");
  const denials = auditReady ? timeline.filter(entry => entry.decision === "deny").length : "—";
  const active = builtInDemo ? frame?.actionCount : state.apiStatus === "live" && state.runtimeSnapshotCurrent
    ? state.runtimeSnapshot?.active_actions?.length : null;
  const online = builtInDemo || (state.apiStatus === "live" && ["live", "stale"].includes(state.dataStatus))
    ? fleet.filter(vehicle => vehicle.connected && !vehicle.stale).length + " / " + fleet.length : "—";
  return `<div class="mission-status-strip">
    <span>在线节点 <b>${esc(online)}</b></span><span>执行中动作 <b>${active ?? "—"}</b></span>
    <span>最近拒绝 <b>${denials}</b></span><span>Runtime API <b class="${builtInDemo ? "amber" : api.color}">${builtInDemo ? "离线演习" : api.label}</b></span>
    <span>数据源 <b class="${source.color}">${esc(source.text)}</b></span>
  </div>`;
}

function timelinePanel({ full = false } = {}) {
  const entries = missionTimeline();
  const important = entries.filter(entry => entry.label !== "记录" || entry.type.startsWith("mission_"));
  const ordered = [...(full ? entries : important)].sort((a, b) =>
    (Date.parse(b.timestamp) || -Infinity) - (Date.parse(a.timestamp) || -Infinity));
  const displayed = full ? ordered : ordered.slice(0, 10);
  const selected = entries.find(entry => entry.key === state.timelineKey);
  const historical = !builtInDemo && (state.apiStatus !== "live" || state.auditStatus !== "live"
    || !state.decisionsLoaded || !state.lifecycleLoaded);
  const eventRows = displayed.map(entry => {
    const subject = [entry.node, entry.action].filter(Boolean).join(" · ");
    const summary = entry.summary || "未记录说明";
    const title = subject || (builtInDemo ? summary : entry.label === "记录" ? entry.type : "未记录载具或动作");
    const details = title !== summary ? `<small>${!builtInDemo && isDemoEvent(entry) ? "DEMO · " : ""}${esc(summary)}</small>` : "";
    return `<li><button class="mission-event ${entry.color}" data-timeline-key="${esc(entry.key)}"
      aria-pressed="${entry.key === state.timelineKey}"><time title="${esc(entry.timestamp ?? "未记录时间")}">${entry.timestamp ? esc(eventTime(entry.timestamp)) : "时间未知"}</time>
      <b>${esc(entry.label)}</b><span><strong>${esc(title)}</strong>${details}</span></button></li>`;
  }).join("");
  return `<section class="panel mission-timeline"><div class="panel-title"><h2>${builtInDemo ? "演习事件" : "策略与动作记录"}</h2>
    <span class="small">${historical && entries.length ? "部分或最后上报 · " : ""}${builtInDemo ? "脚本记录" : full ? "最近审计窗口" : "最近关键事件"}</span></div>
    <div class="timeline-legend"><span class="green">允许</span><span class="red">拒绝</span><span class="amber">降级 / 告警</span><span class="blue">恢复</span><span>结果</span></div>
    <ol class="mission-events">${eventRows}</ol>
    ${displayed.length ? "" : '<div class="empty-state">等待策略、适配器与结果事件</div>'}
    ${selected ? `<div class="timeline-detail"><div class="panel-title"><h2>事件原文</h2><span class="small">${builtInDemo ? "内置 DEMO" : esc(selected.source)}</span></div>
      <pre class="json">${esc(JSON.stringify(selected.raw, null, 2))}</pre></div>` : ""}
  </section>`;
}

function demoControls() {
  if (stageMode) return "";
  const node = selectedVehicle();
  if (!state.demoRuntime || !node || node.enabled === false || state.apiStatus !== "live") {
    return state.demoWriteStatus ? `<p class="small" role="status">${esc(state.demoWriteStatus)}</p>` : "";
  }
  const assignments = dashboard.rows(state.demoRuntime.assignments);
  const held = Array.isArray(state.demoRuntime.held_out) ? state.demoRuntime.held_out : [];
  return `<div class="mission-demo-controls">
    <label class="small">Runtime DEMO · 目标载具
      <select data-demo-target ${state.demoWriteInFlight ? "disabled" : ""}>${state.fleet.filter(v => v.enabled !== false).map(v =>
        `<option value="${esc(v.id)}" ${v.id === node.id ? "selected" : ""}>${esc(v.id)}</option>`).join("")}</select>
    </label>
    <button class="button warn" data-demo-operation="inject" ${state.demoWriteInFlight ? "disabled" : ""}>注入链路降级</button>
    <button class="button" data-demo-operation="clear" ${state.demoWriteInFlight ? "disabled" : ""}>恢复链路</button>
    <span class="small" role="status">${esc(state.demoWriteStatus)}</span>
    ${assignments.length ? `<div class="demo-assignments small"><b>DEMO 任务分配</b> ${assignments.map(item =>
      esc(item.work_id + " → " + (item.node_id || "等待分配"))).join(" · ")}
      ${held.length ? `<span> 暂停参与 · ${esc(held.join("、"))}</span>` : ""}</div>` : ""}</div>`;
}

async function changeDemoLink(operation) {
  const node = selectedVehicle();
  if (stageMode || state.apiStatus !== "live" || !state.demoRuntime || !node || node.enabled === false || state.demoWriteInFlight
    || !["inject", "clear"].includes(operation)) return;
  const source = state.apiBaseUrl;
  const api = window.SwarmRuntimeApi;
  state.demoWriteInFlight = true;
  state.demoWriteStatus = "等待 Runtime 确认";
  render();
  try {
    const response = operation === "inject"
      ? await api.demoInject({node_id:node.id,kind:"link_degraded",value:18,duration_s:60})
      : await api.demoClear({node_id:node.id});
    if (state.apiBaseUrl !== source) return;
    state.demoWriteStatus = response?.mode === "DEMO" && response?.flight_command_sent === false
      ? (response.changed === false ? "演习状态未变更" : "Runtime 已确认演习状态")
      : "Runtime 响应缺少演习确认";
    await Promise.all([syncRuntimeState(), syncRuntimeEvents()]);
  } catch (error) {
    if (state.apiBaseUrl === source) state.demoWriteStatus = "演示请求未确认 · " + error.message;
  } finally {
    state.demoWriteInFlight = false;
    renderRuntimeUpdate();
  }
}

function stageNavigation() {
  const views = builtInDemo ? dashboard.demoChapters : liveStages;
  return `<nav class="stage-navigation" aria-label="${builtInDemo ? "演习章节" : "实时大屏视图"}">
    ${views.map(({ title }, index) => `<button class="button" type="button" id="stage-view-${index}" data-stage-view="${index}" aria-pressed="false">${esc(title)}</button>`).join("")}
    <button class="button stage-play" type="button" id="stage-play" data-stage-play>${builtInDemo ? "暂停" : "自动轮播"}</button>
    ${builtInDemo ? '<button class="button" type="button" data-stage-restart>从头播放</button>' : ""}
  </nav>`;
}

function stageElapsed() {
  const runningSeconds = stagePlayback.startedAt === null ? 0 : (performanceNow() - stagePlayback.startedAt) / 1000;
  return stagePlayback.elapsed + runningSeconds;
}

function seekStage(index) {
  const views = builtInDemo ? dashboard.demoChapters : liveStages;
  if (!Number.isInteger(index) || !views[index]) return;
  // Manual chapter selection shows the evidence collected by the end of that chapter.
  stagePlayback.elapsed = builtInDemo ? (index + 1) * dashboard.demoChapterSeconds - 0.01 : index * liveStageSeconds;
  stagePlayback.startedAt = null;
  state.timelineKey = null;
  renderStage();
}

function toggleStagePlayback(restart = false) {
  if (restart || builtInDemo && stagePlayback.elapsed >= dashboard.demoDuration) {
    stagePlayback.elapsed = 0;
    stagePlayback.startedAt = performanceNow();
    state.timelineKey = null;
  } else if (stagePlayback.startedAt === null) {
    stagePlayback.startedAt = performanceNow();
  } else {
    stagePlayback.elapsed = stageElapsed();
    stagePlayback.startedAt = null;
  }
  renderStage();
}

function stageContent(view) {
  if (view === "demo") return `${missionIndicators()}<div class="mission-workspace">${missionMapPanel()}${timelinePanel({ full: true })}</div>`;
  if (view === "map") return missionMapPanel();
  if (view === "timeline") return timelinePanel({ full: true });
  if (view === "kpi") return missionIndicators();
  return `<section class="panel stage-three"><div class="panel-title"><h2>三维态势</h2>
    <span class="small">LIVE · Runtime 快照</span></div>${simulationFrame()}</section>`;
}

function renderStage() {
  const elapsed = stageElapsed();
  if (builtInDemo) {
    state.stageFrame = dashboard.demoFrame(elapsed);
    if (elapsed >= dashboard.demoDuration) {
      stagePlayback.elapsed = dashboard.demoDuration;
      stagePlayback.startedAt = null;
    }
  }
  const index = builtInDemo ? state.stageFrame.chapterIndex : Math.floor(elapsed / liveStageSeconds) % liveStages.length;
  const count = builtInDemo ? dashboard.demoChapters.length : liveStages.length;
  const { view = "demo", title: heading, detail } = builtInDemo ? state.stageFrame.chapter : liveStages[index];
  const title = document.getElementById("stage-title");
  const indicators = document.getElementById("stage-indicators");
  const body = document.getElementById("stage-content");
  if (!body) return;
  if (title) title.innerHTML = `<div class="stage-heading"><div><h1>${esc(heading)}</h1><p>${esc(detail)}</p></div><span>${index + 1} / ${count}</span></div>`;
  if (indicators) indicators.innerHTML = missionMetricsBar() + (builtInDemo || view === "kpi" ? "" : missionIndicators(true));
  for (let slot = 0; slot < count; slot++) {
    document.getElementById(`stage-view-${slot}`)?.setAttribute("aria-pressed", String(slot === index));
  }
  const playButton = document.getElementById("stage-play");
  if (playButton) {
    const isPlaying = stagePlayback.startedAt !== null;
    playButton.textContent = builtInDemo ? (isPlaying ? "暂停" : elapsed >= dashboard.demoDuration ? "重新播放" : "继续播放")
      : (isPlaying ? "暂停轮播" : "自动轮播");
  }
  if (view !== "twin" || state.renderedPage !== view) {
    if (view === "twin") state.simulationReady = false;
    const markup = stageContent(view);
    if (markup !== state.stageMarkup) {
      body.innerHTML = markup;
      state.stageMarkup = markup;
    }
    state.renderedPage = view;
  }
  if (view === "map") drawMissionCoverage();
  if (!builtInDemo) updatePolicyBanner();
}

function policyAuditPanel() {
  const decisions = missionTimeline().filter(entry => entry.type === "policy_decision_event").reverse();
  const nodes = [...new Set(decisions.map(entry => entry.node).filter(Boolean))].sort();
  const filters = state.policyFilters;
  if (filters.node && !nodes.includes(filters.node)) nodes.push(filters.node);
  const selected = decisions.find(entry => entry.key === state.timelineKey);
  const displayed = decisions.filter(entry => (!filters.node || filters.node === entry.node)
    && (!filters.decision || filters.decision === entry.decision));
  const option = (value, label, current) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;
  return `<section class="panel policy-audit"><div class="panel-title"><h2>策略裁决溯源</h2>
    <span class="small">${state.apiStatus !== "live" || state.auditStatus !== "live" ? "部分或最后上报" : "Runtime 审计"}</span></div>
    <div class="policy-filters"><label>载具 <select data-policy-filter="node">${option("", "全部", filters.node)}
      ${nodes.map(node => option(node, node, filters.node)).join("")}</select></label>
    <label>判定 <select data-policy-filter="decision">${option("", "全部", filters.decision)}
      ${["allow","deny","require_confirm","defer","preempt"].map(code => option(code, code.toUpperCase(), filters.decision)).join("")}</select></label></div>
    ${displayed.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>时间</th><th>载具</th><th>动作</th><th>判定</th><th>规则 / 理由</th><th>事件</th></tr></thead>
      <tbody>${displayed.map(entry => `<tr><td>${esc(eventTime(entry.timestamp))}</td><td>${esc(entry.node || "—")}</td>
      <td>${esc(entry.action || "—")}</td><td>${badge(entry.decision.toUpperCase() || "UNKNOWN", entry.color)} ${isDemoEvent(entry) ? badge("DEMO", "amber") : ""}</td>
      <td>${esc(entry.rule || entry.reason || "未上报")}</td><td><button class="button" data-timeline-key="${esc(entry.key)}" aria-pressed="${entry.key === state.timelineKey}">完整 JSON</button></td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty-state">等待数据或当前筛选无记录</div>'}
    ${selected ? `<pre class="json">${esc(JSON.stringify(selected.raw, null, 2))}</pre>` : ""}
  </section>`;
}

function overviewPage() {
  return `<div class="page mission-overview">
    ${pageTitle("总览驾驶舱", "", `
      <a class="button stage-link" href="?mode=stage&amp;source=live">实时大屏</a>
      <a class="button stage-link" href="?mode=stage">离线演习</a>`)}
    ${missionMetricsBar()}
    ${missionIndicators()}
    <div class="mission-workspace">${missionMapPanel()}
      <div class="grid">${panel("载具状态", vehicleTable(), "scroll")}${timelinePanel()}</div></div>
    ${demoControls()}
  </div>`;
}

function pageTitle(title, subtitle, actions = "") {
  return `<div class="page-title">
    <h1>${esc(title)}</h1>
    ${subtitle ? `<p>${esc(subtitle)}</p>` : ""}
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

const semanticPreviewFiles = [
  ["01-clarification.preview.json", "加载并列澄清"],
  ["02-clarified.preview.json", "加载明确实体后的绑定"],
];
const modelReplayFiles = [
  ["higher-12.preview.json", "32 米：模型选对，核实通过"],
  ["higher-2.preview.json", "22 米：模型选错，待澄清"],
  ["higher-27.preview.json", "47 米：目录范围内无匹配，待澄清"],
];

const semanticLiveExamples = [
  [12, "32 米题"],
  [2, "22 米题"],
  [27, "47 米题"],
];

function semanticLivePanel() {
  const live = state.semanticLive;
  return panel("本地试推理", `
    <p class="small">当前仅支持导出目录中北侧首排东半幅的限定楼栋题。</p>
    <div class="field"><label for="semantic-live-example">输入示例</label>
      <select id="semantic-live-example" data-semantic-live-example${live.inFlight ? " disabled" : ""}>
        <option value="">选择题目，只填入原话</option>
        ${semanticLiveExamples.map(([difference, label]) => `<option value="${difference}">${label}</option>`).join("")}
      </select></div>
    <div class="field"><label for="semantic-live-objective">原话（最多 160 字）</label>
      <textarea id="semantic-live-objective" rows="2" maxlength="160" data-semantic-live-objective${live.inFlight ? " disabled" : ""}>${esc(live.objective)}</textarea></div>
    <div class="semantic-preview-controls">
      <button type="button" class="button primary" id="semantic-live-submit" data-semantic-infer${live.inFlight ? " disabled" : ""}>${live.inFlight ? "推理中…" : "本地试推理"}</button>
      <button type="button" class="button" id="semantic-lab-check" data-semantic-health${live.healthInFlight ? " disabled" : ""}>检查 Lab</button>
    </div>
    <p class="small" id="semantic-lab-health" role="status">${semanticLabHealth()}</p>
    <div id="semantic-live-result" aria-live="polite">${semanticLiveResult()}</div>`, "semantic-preview semantic-live");
}

function semanticLabHealth() {
  const live = state.semanticLive;
  if (live.healthInFlight) return "正在检查 Lab · 模型状态未检查";
  if (live.healthError) return esc(live.healthError);
  return live.health ? "Lab 可接收请求 · 模型状态未检查" : "Lab 尚未检查 · 模型状态未检查";
}

function semanticLiveResult() {
  const preview = state.semanticLive.result;
  if (!preview.mode) return '<p class="small">提交后显示本次模型原答、算法结论和 Lab 耗时。</p>';
  return semanticPreviewResult(preview);
}

function renderSemanticLive() {
  const result = document.getElementById("semantic-live-result");
  if (result) result.innerHTML = semanticLiveResult();
  const health = document.getElementById("semantic-lab-health");
  if (health) health.innerHTML = semanticLabHealth();
  const live = state.semanticLive;
  const submit = document.getElementById("semantic-live-submit");
  if (submit) {
    submit.disabled = live.inFlight;
    submit.textContent = live.inFlight ? "推理中…" : "本地试推理";
  }
  const check = document.getElementById("semantic-lab-check");
  if (check) check.disabled = live.healthInFlight;
  for (const id of ["semantic-live-example", "semantic-live-objective"]) {
    const input = document.getElementById(id);
    if (input) input.disabled = live.inFlight;
  }
}

function setSemanticLiveObjective(value) {
  if (value === state.semanticLive.objective) return;
  state.semanticLive.objective = value;
  state.semanticLive.result = {};
  const input = document.getElementById("semantic-live-objective");
  if (input && input.value !== value) input.value = value;
  renderSemanticLive();
}

async function checkSemanticLab() {
  if (stageMode || state.semanticLive.healthInFlight) return;
  const live = state.semanticLive;
  live.healthInFlight = true;
  live.health = null;
  live.healthError = null;
  renderSemanticLive();
  try {
    live.health = await window.SwarmSemanticLab.health();
  } catch (error) {
    live.healthError = `${error.reasonCode || "LAB_UNREACHABLE"} · ${error.message}`;
  } finally {
    live.healthInFlight = false;
    renderSemanticLive();
  }
}

async function inferSemanticPreview() {
  if (stageMode || state.semanticLive.inFlight) return;
  const live = state.semanticLive;
  const result = { mode: "live", label: "本次请求", objective: live.objective, loading: true };
  live.result = result;
  live.inFlight = true;
  renderSemanticLive();
  try {
    Object.assign(result, await window.SwarmSemanticLab.infer(result.objective));
  } catch (error) {
    result.error = `${error.httpStatus ? `HTTP ${error.httpStatus} · ` : ""}${error.reasonCode || "LAB_RESPONSE_INVALID"} · ${error.message}`;
  } finally {
    result.loading = false;
    live.inFlight = false;
    renderSemanticLive();
  }
}

function semanticPreviewPanel() {
  return panel("离线算法证据 · 只读预览", `
    <div class="semantic-preview-controls">
      ${semanticPreviewFiles.map(([file, label]) => `<button type="button" class="button" data-semantic-sample="${file}">${label}</button>`).join("")}
      <div class="field"><label for="semantic-model-replay">模型实测回放（不触发推理）</label>
        <select id="semantic-model-replay" data-semantic-model-sample>
          <option value="">选择实测记录</option>
          ${modelReplayFiles.map(([file, label]) => `<option value="${file}">${label}</option>`).join("")}
        </select></div>
      <div class="field"><label for="semantic-preview-file">导入本地预览 JSON</label>
        <input id="semantic-preview-file" type="file" accept=".json,application/json" data-semantic-file></div>
    </div>
    <div id="semantic-preview-result" aria-live="polite">${semanticPreviewResult()}</div>`, "semantic-preview");
}

function semanticPreviewResult(preview = state.semanticPreview) {
  const { record, label, error, scopeText, mode, objective, elapsedMs, evidenceText } = preview;
  const modes = { live: "本地实时推理", replay: "录制证据回放", import: "本地文件导入" };
  const origin = mode ? `<p>${badge(modes[mode], "amber")}${Number.isFinite(elapsedMs) ? ` <span class="small">Lab 耗时 ${elapsedMs} ms</span>` : ""}</p>` : "";
  if (error) return `${origin}<p class="inline-error">${esc(label)}：${esc(error)}</p>${objective ? `<p>本次原话 ${esc(objective)}</p>` : ""}`;
  if (!record) return `${origin}<p class="small">${preview.loading ? "正在等待本次模型响应…" : label ? `正在读取 ${esc(label)}…` : "选择一份离线导出以查看绑定依据。"}</p>`;

  const { source } = record;
  const statuses = { bound: ["已绑定", "cyan"], clarify: ["待澄清", "amber"], unknown: ["未知", "amber"] };
  const items = record.status === "bound" ? record.bindings : record.candidates;
  const modelAlias = typeof record.scope?.model_alias === "string" ? record.scope.model_alias : null;
  const modelRaw = typeof record.scope?.model_response === "string" ? record.scope.model_response : null;
  const ruleHint = record.reason_code === "MODEL_CHOICE_EVIDENCE_MATCH"
    ? "模型选项与目录规则一致：按所需高度核对唯一匹配，绑定目录对象，不下发任务。"
    : record.reason_code === "MODEL_CHOICE_REQUIRES_REVIEW"
      ? "模型选项与目录规则不一致，没有绑定；下方对象只是候选。" : null;
  return `${origin}<p>${badge(...statuses[record.status])} <span class="small">${esc(record.reason_code)}</span></p>
    <p class="small">${source.model_executed
      ? (mode === "live" ? "本次模型响应" : mode === "import" ? "导入模型记录（文件标注）" : "模型实测回放（文件标注）") + (modelAlias ? " · " + esc(modelAlias) : "") : "离线规则验证 · 模型未运行"}</p>
    <p class="small">${esc(record.scene_id)} / ${esc(record.map_version)} · schema ${esc(record.schema_version)}</p>
    <p><span class="small">原话</span> ${esc(record.objective)}</p>
    ${source.model_executed && modelRaw ? `<p><span class="small">模型原始回复</span> <code>${esc(modelRaw)}</code></p>` : ""}
    ${source.kind === "local_model_scene_selection" ? '<p class="small">核对规则：20 米加上原话中的差值。只查导出目录的北侧首排东半幅；唯一匹配才可绑定，并列须澄清，没有匹配不能选楼。不会替模型改答案。</p>' : ""}
    ${ruleHint ? `<p class="small">${ruleHint}</p>` : ""}
    ${record.status === "clarify" ? `<p class="amber">${esc(record.clarification_question)}</p>` : ""}
    ${record.status === "unknown" ? '<p class="small">当前证据不足以绑定实体。</p>' : ""}
    ${items.length ? `<ul class="semantic-preview-entities">${items.map(item => `<li>
      <b>${esc(item.entity_id)}</b> <span class="small">${esc(item.entity_kind)}${Number.isFinite(item.height_m) ? ` · ${item.height_m} m` : ""}</span>
      ${item.evidence ? `<div>原文依据 ${esc(item.evidence)}</div>` : ""}
      ${item.source_reference ? `<div class="small">${esc(item.source_reference)}</div>` : ""}
    </li>`).join("")}</ul>` : ""}
    <details ${mode === "live" ? "data-semantic-live-details" : "data-semantic-details"}${(mode === "live" ? state.semanticLiveDetailsOpen : state.semanticPreviewDetailsOpen) ? " open" : ""}>
      <summary>来源与限定条件</summary>
      <div class="semantic-preview-provenance">
        <dl class="semantic-preview-source">
          <dt>来源类型</dt><dd>${esc(source.kind)}</dd>
          <dt>${mode === "live" ? "请求来源" : "导入文件"}</dt><dd>${esc(label)}</dd>
          <dt>原始证据</dt><dd>${esc(source.evidence_file)}</dd>
          <dt>原证据 SHA-256（${mode === "live" ? "已核对" : "导出记录"}）</dt><dd><code>${esc(source.evidence_sha256)}</code></dd>
          <dt>场景目录</dt><dd>${esc(source.catalog_file)}</dd>
          <dt>目录内容 SHA-256（导出记录）</dt><dd><code>${esc(source.catalog_content_sha256)}</code></dd>
          <dt>目录审核状态</dt><dd>${source.catalog_review_status === "exported_from_physics_pending_review" ? "物理导出待审核 · " : ""}${esc(source.catalog_review_status)}</dd>
        </dl>
        ${evidenceText ? `<p>本次原始证据</p><pre class="json">${esc(evidenceText)}</pre>` : ""}
        ${scopeText !== null ? `<p>限定范围</p><pre class="json">${esc(scopeText)}</pre>` : ""}
        ${record.limitations.length ? `<ul>${record.limitations.map(limit => `<li>${esc(limit)}</li>`).join("")}</ul>` : ""}
      </div>
    </details>`;
}

function renderSemanticPreviewResult() {
  const slot = document.getElementById("semantic-preview-result");
  if (slot) slot.innerHTML = semanticPreviewResult();
}

async function loadSemanticPreview(read, label, fileSize = 0, mode = "import") {
  const model = window.SwarmSemanticPreview;
  const preview = { label, mode };
  state.semanticPreview = preview;
  renderSemanticPreviewResult();
  try {
    Object.assign(preview, fileSize > model.maxFileBytes ? { error: "证据文件超过 512 KiB。" } : model.parse(await read()));
  } catch {
    preview.error = "无法读取证据文件。";
  }
  if (state.semanticPreview === preview) renderSemanticPreviewResult();
}

function loadSemanticSample(file) {
  if (stageMode || ![...semanticPreviewFiles, ...modelReplayFiles].some(([name]) => name === file)) return;
  return loadSemanticPreview(async () => {
    const response = await fetch("./evidence/semantic-preview/" + file);
    if (!response.ok) throw new Error("Evidence file unavailable");
    return response.text();
  }, file, 0, "replay");
}

function twinPage() {
  const summary = fleetSummary();
  const previewControl = fixturePlanPreviewPage()
    ? `<button class="button" id="fixture-plan-preview-clear" type="button" onclick="clearFixturePlanPreview()"${currentFixturePlanPreview() ? "" : " disabled"}>撤销计划预览</button>`
    : "";
  return `<div class="page twin-page">
    ${pageTitle("三维集群态势", "Cesium · Runtime vehicle snapshot · 多机任务态势", `${previewControl}<a class="button" href="${esc(state.simulationUrl)}" target="_blank" rel="noreferrer">独立打开</a>`)}
    <div class="twin-main">
      ${panel(`三维 Mission Twin ${badge(state.simulationReady ? "CONNECTED" : "WAITING", state.simulationReady ? "green" : "amber")}`, simulationFrame(), "twin-panel")}
      <div class="grid twin-nodes">
        ${semanticLivePanel()}
        ${semanticPreviewPanel()}
        <div class="metrics">
          ${metric("在线节点", `${summary.online}/${summary.total}`, "Runtime", "cyan", "online")}
          ${metric("已武装", summary.armed, "Telemetry", "green", "armed")}
          ${metric("离线 / 过期", state.linkIssues ?? "--", "Fleet", "amber", "issues")}
        </div>
        ${panel("节点列表", vehicleTable(), "scroll")}
      </div>
    </div>
    <div class="twin-details">
      ${vehicleDiagramPanel()}
      ${panel("所选节点遥测", `<div class="twin-telemetry" id="selected-telemetry">${telemetrySummary()}</div>`)}
    </div>
  </div>`;
}

function templatePlanButtonLabel() {
  const { inFlight, slowHint } = state.templatePlan;
  if (!inFlight) return "预览任务";
  return slowHint ? "继续等待…" : "识别中…";
}

function planningPage() {
  const { objective, inFlight } = state.templatePlan;
  const inputsDisabled = inFlight || state.fixturePlan.executing ? " disabled" : "";
  return `<div class="page semantic-planning-page">
    ${pageTitle("任务规划", "", '<button class="button" onclick="setPage(\'twin\')">查看三维集群态势</button>')}
    <div class="planning-workspace">
      <div class="grid">
        ${panel("任务输入", `<div class="field"><label for="template-plan-objective">任务目标</label>
          <textarea rows="4" id="template-plan-objective" data-template-plan-objective placeholder="输入或粘贴任务书"${inputsDisabled}>${esc(objective)}</textarea></div>
          <div class="planning-actions">
            <button class="button" id="template-plan-example" type="button" onclick="useTemplatePlanExample()"${inputsDisabled}>填入巡检示例</button>
            <button class="button primary" id="template-plan-submit" type="button" onclick="generateRequest()"${inputsDisabled}>${templatePlanButtonLabel()}</button>
          </div>
          <p class="small">Runtime 根据当前场景目录识别目标，返回只读预览或追问。</p>`)}
        ${panel("载具状态", vehicleTable(), "scroll")}
      </div>
      <div class="grid">
        <div id="template-plan-preview" class="grid" aria-live="polite">${templatePlanPreview()}</div>
        ${panel("可校验计划候选", missionFixture ? `
          <div id="mission-fixture-candidate" aria-live="polite">${fixtureCandidateContent()}</div>
          <div id="mission-fixture-progress" aria-live="polite">${fixtureProgressContent()}</div>`
          : '<p class="small">等待算法提供校验过的载具分工、航点和场景版本。收到后才可进入人工确认与执行。</p>')}
      </div>
    </div>
    <div class="planning-algorithm">${semanticLivePanel()}${semanticPreviewPanel()}</div>
  </div>`;
}

const templateActionNames = new Map([["takeoff", "起飞"], ["report_status", "报告状态"], ["camera_capture", "采集照片"], ["land", "降落"]]);
const templateResultNames = new Map([["ready", "预览就绪"], ["awaiting_confirmation", "需确认"], ["blocked", "预览受阻"]]);
const templateDecisionNames = new Map([["allow", "预检允许"], ["deny", "预检拒绝"], ["require_confirm", "需确认"]]);
const previewIntentSources = new Map([
  ["explicit", "显式指定模板"], ["rules", "离线规则识别"], ["local_model", "本地模型识别"], ["none", "未识别"],
]);
const previewPlanSources = new Map([["template", "模板生成"], ["algorithm", "算法生成"], ["none", "无计划"]]);

function previewFields(rows) {
  return `<dl class="plan-preview-fields">${rows.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${value}</dd>`).join("")}</dl>`;
}

function templatePlanProvenance(reply) {
  const source = (names, value) => value == null ? "未知" : `${names.get(value) || "未知"} <code>${esc(value)}</code>`;
  const authorization = reply.execution_authorized === false
    ? "未授权执行 <code>false</code>"
    : reply.execution_authorized === true ? "契约异常 <code>true</code>" : "未上报";
  return previewFields([
    ["契约版本", esc(reply.contract_version ?? "未上报")],
    ["意图识别", source(previewIntentSources, reply.intent_source)],
    ["计划来源", source(previewPlanSources, reply.plan_source)],
    ["降级原因", esc(reply.fallback_reason === null ? "无" : reply.fallback_reason ?? "未上报")],
    ["执行授权", authorization],
  ]);
}

function templatePlanBinding({ catalog, bindings }, missionType) {
  const list = (items, note = "") => {
    if (!Array.isArray(items)) return "未上报";
    if (!items.length) return "无";
    if (items.some(item => typeof item?.entity_id !== "string" || !item.entity_id)) return "绑定信息异常";
    return `<ul>${items.map(({ entity_id, evidence }) => `<li>${esc(evidence || entity_id)} <code>${esc(entity_id)}</code>${note}</li>`).join("")}</ul>`;
  };
  return previewFields([
    ["任务类型", `<code>${esc(missionType ?? "未上报")}</code>`],
    ["场景 / 地图 / 目录", [catalog?.scene_id, catalog?.map_version, catalog?.catalog_id].map(id => esc(id ?? "未上报")).join(" / ")],
    ["场景巡检目标", list(bindings?.targets)],
    ["演习目标", list(bindings?.preview_only_targets, ' <span class="amber">仅预览，不可执行</span>')],
    ["定位参照", list(bindings?.reference_only)],
    ["排除目标", list(bindings?.excluded_targets)],
    ["仅列明目标", bindings?.only_listed_targets === true ? "是" : bindings?.only_listed_targets === false ? "否" : "未上报"],
    ["状态范围", esc(bindings?.status_scope === null ? "无" : bindings?.status_scope ?? "未上报")],
  ]);
}

const modelRejectionLabels = new Map([
  ["MODEL_JSON_INVALID", "模型回答不是合法的 JSON"],
  ["MODEL_FIELDS_INVALID", "模型回答的字段不符合要求"],
  ["MODEL_INDEX_INVALID", "目录编号列表不符合要求"],
  ["MODEL_DUPLICATE_SELECTION", "重复选择了同一目录对象"],
  ["TARGET_REFERENCE_ONLY", "把仅供定位的参照对象选成了目标"],
  ["CONFLICTING_TARGETS", "选中的目标互斥"],
  ["MODEL_ROLE_CONFLICT", "所选目标与参照或排除约束冲突"],
  ["MODEL_ABSTAINED", "模型没有选出巡检目标"],
  ["MODEL_TIMEOUT", "模型响应超时"],
  ["MODEL_UNAVAILABLE", "模型服务不可用"],
  ["MODEL_BUSY", "模型正在处理其他请求"],
  ["MODEL_THREAD_UNAVAILABLE", "模型请求无法启动"],
  ["MODEL_INPUT_TOO_LARGE", "模型输入超过大小上限"],
  ["MODEL_INPUT_INVALID", "模型输入格式无效"],
  ["MODEL_RESPONSE_TOO_LARGE", "模型回包超过大小上限"],
  ["MODEL_ENVELOPE_INVALID", "模型服务回包格式无效"],
  ["MODEL_TEXT_MISSING", "模型回包缺少文本"],
  ["MODEL_ID_MISMATCH", "回包中的模型标识与配置不符"],
  ["MODEL_RESPONSE_INCOMPLETE", "模型回答未完整返回"],
  ["MODEL_TOOL_CALL_REFUSED", "模型回包包含工具调用"],
]);

function templateModelAnswer(diagnostics) {
  if (!Array.isArray(diagnostics?.attempts)) return "";
  const attempts = diagnostics.attempts.filter(attempt => typeof attempt?.adopted === "boolean"
    && (attempt.raw_text === null || typeof attempt.raw_text === "string"));
  if (!attempts.length) return "";

  const adoption = diagnostics.adopted === true ? "已采用" : diagnostics.adopted === false ? "未采用" : "采纳状态未知";
  const answers = attempts.map((attempt, index) => {
    const status = attempt.adopted ? "已采用" : "未采用";
    const reason = attempt.not_adopted_reason;
    const reasonText = typeof reason === "string" && reason
      ? `${esc(modelRejectionLabels.get(reason) || "Runtime 上报原因")} <code>${esc(reason)}</code>`
      : "未上报";
    const raw = attempt.redacted === true ? '<p class="small">原答已由 Runtime 脱敏</p>'
      : attempt.raw_text === null ? '<p class="small">本次未提供原答文本</p>'
      : attempt.raw_text === "" ? '<p class="small">模型返回了空文本</p>'
      : `<pre class="json">${esc(attempt.raw_text)}</pre>`;
    return `${attempts.length > 1 ? `<p class="small"><b>第 ${index + 1} 次 · ${status}</b></p>` : ""}
      ${attempt.adopted ? "" : `<p class="small">未采用原因 ${reasonText}</p>`}
      ${raw}
      ${attempt.truncated === true ? '<p class="small">原答已由 Runtime 截断</p>' : ""}`;
  }).join("");
  return `<details class="template-model-answer"><summary>模型原答 · ${adoption}</summary>${answers}</details>`;
}

function templatePlanPreview() {
  const { inFlight, slowHint, reply, error } = state.templatePlan;
  if (!reply) {
    const content = error
      ? `<p class="inline-error">${esc(error)}</p>`
      : `<p class="small">${inFlight ? esc(slowHint || "等待 Runtime 识别任务…") : "填写任务目标后可生成只读预览。"}</p>`;
    return panel("Runtime 任务预览", content);
  }
  const provenance = templatePlanProvenance(reply);
  const modelAnswer = templateModelAnswer(reply.model_diagnostics);
  const intent = reply.intent_resolution;
  if (intent && (intent.status !== "resolved" || intent.reason_code === "TARGET_REFERENCE_ONLY")) {
    const title = intent.status === "needs_clarification" ? "需要澄清"
      : intent.status === "unsupported" ? "当前输入不受支持" : "识别状态未知";
    const question = intent.question ?? (intent.status === "needs_clarification" ? "Runtime 未返回追问" : "");
    const referenceNote = intent.reason_code === "TARGET_REFERENCE_ONLY"
      ? '<p class="small">所选参照对象可用于定位，也可从本轮目标中排除。</p>' : "";
    return panel(title, `${question ? `<p>${esc(question)}</p>` : ""}
      ${referenceNote}
      ${intent.reason_code ? `<p class="small"><code>${esc(intent.reason_code)}</code></p>` : ""}
      ${provenance}${modelAnswer}`);
  }

  const plan = reply.plan_source === "none" || reply.execution_authorized === true ? null : reply.plan;
  const outcome = `<p>${badge(templateResultNames.get(reply.result) || "结果未识别", plan ? "cyan" : "amber")}
    ${reply.failure_reason ? `<span class="small">${esc(reply.failure_reason)}</span>` : ""}</p>`;
  if (!plan) return panel("Runtime 任务预览", `${provenance}${outcome}<p class="small">本次没有可显示的计划。</p>${modelAnswer}`);

  const binding = plan.preview_binding;
  const outline = binding?.steps_are_outline === true;
  const steps = Array.isArray(plan.steps) ? plan.steps.filter(step => step && typeof step.action_type === "string") : [];
  const stepList = steps.map(step => {
    const node = step.node_id ? (outline ? `模板节点 ${step.node_id}` : step.node_id) : "未指定载具";
    return `<li><b>${esc(templateActionNames.get(step.action_type) || step.action_type)}</b>
      <small>${esc(node)}${step.status === "dry_run_only" ? " · 仅预览" : ""}</small></li>`;
  }).join("");
  const precheck = steps.map(step => {
    const decision = step.policy_precheck?.decision_code;
    const decisionLabel = templateDecisionNames.get(decision);
    const risk = Number.isInteger(step.risk_level) && step.risk_level >= 0 ? step.risk_level : "未上报";
    return `<tr><td>${esc(templateActionNames.get(step.action_type) || step.action_type)}</td>
      <td>${esc(decisionLabel || decision || "未预检")}</td>
      <td>${esc(step.policy_precheck?.primary_reason_code || "未上报原因")}</td>
      <td>${risk}</td></tr>`;
  }).join("");

  return `${panel(outline ? "Runtime 模板大纲" : "Runtime 任务预览", `${provenance}${outcome}
      ${binding ? templatePlanBinding(binding, intent?.mission_type ?? plan.mission_type) : ""}
      ${outline ? '<p class="small">以下为模板通用步骤。目标和约束见上方绑定。</p>' : ""}
      ${stepList ? `<ol class="template-plan-steps">${stepList}</ol>` : '<p class="small">Runtime 未返回计划步骤</p>'}
      ${modelAnswer}
      <details><summary>Runtime 返回 JSON</summary><pre class="json">${esc(JSON.stringify(reply, null, 2))}</pre></details>`)}
    ${precheck ? panel("逐步策略预检与风险", `<div class="planning-table"><table class="table">
      <thead><tr><th>步骤</th><th>预检结论</th><th>依据</th><th>动作风险级别</th></tr><tbody>${precheck}</tbody></table></div>
      <p class="small">风险级别来自 Runtime 动作能力登记。现场条件由 Runtime 在执行时重新核验。</p>`) : ""}`;
}

function renderTemplatePlan() {
  const slot = document.getElementById("template-plan-preview");
  if (slot) slot.innerHTML = templatePlanPreview();
  const { inFlight } = state.templatePlan;
  for (const id of ["template-plan-objective", "template-plan-example", "template-plan-submit"]) {
    const control = document.getElementById(id);
    if (!control) continue;
    control.disabled = Boolean(inFlight || state.fixturePlan.executing);
    if (id === "template-plan-submit") control.textContent = templatePlanButtonLabel();
  }
}

function setTemplatePlanObjective(value) {
  const draft = state.templatePlan;
  if (draft.inFlight || state.fixturePlan.executing || draft.objective === value) return;
  draft.objective = value;
  setFixturePlanDraft();
  renderFixtureCandidate();
  const input = document.getElementById("template-plan-objective");
  if (input && input.value !== value) input.value = value;
  if (draft.reply || draft.error) {
    draft.reply = null;
    draft.error = null;
    renderTemplatePlan();
  }
}

function useTemplatePlanExample() {
  setTemplatePlanObjective("巡检东北视觉标记");
}

function fixtureCandidateContent() {
  const { plan, validating, executing, submitted, operatorId, receipt, error } = state.fixturePlan;
  const actions = plan?.steps.map(step => {
    const { north_m, east_m, down_m } = step.params ?? {};
    const waypoint = step.action_type === "goto" ? ` · N/E/D ${north_m} / ${east_m} / ${down_m} m` : "";
    return `<li><b>${esc(step.node_id)}</b> · ${esc(step.action_type + waypoint)}</li>`;
  }).join("");
  return `<p class="small">测试桩 · 设备巡检导航</p>
    <button class="button" type="button" onclick="validateFixtureCandidate()"${validating || submitted ? " disabled" : ""}>
      ${validating ? "校验中…" : "校验任务候选"}
    </button>
    ${plan ? `<p class="small">${esc(plan.plan_id)} · ${esc(plan.scene_id)} / ${esc(plan.map_version)}</p>
      <ol class="template-plan-steps">${actions}</ol>
      <h3>人工确认与执行</h3>
      <div class="field"><label for="mission-fixture-operator">操作员 ID</label>
        <input id="mission-fixture-operator" value="${esc(operatorId || "")}"${submitted ? " disabled" : ""}></div>
      <button class="button primary" type="button" onclick="confirmFixtureExecution(document.getElementById('mission-fixture-operator').value)"${submitted ? " disabled" : ""}>
        ${executing ? "等待执行回执…" : "确认并执行（测试桩）"}
      </button>` : ""}
    ${receipt ? `<p>${esc(fixtureReceiptNames.get(receipt.result))}${receipt.failure_reason ? " · " + esc(receipt.failure_reason) : ""}
      ${receipt.aborted_at_step ? " · 中止步骤 " + esc(receipt.aborted_at_step) : ""}</p>` : ""}
    ${error ? `<p class="inline-error">${esc(error)}</p>` : ""}`;
}

function fixtureProgressContent() {
  const { plan, receipt } = state.fixturePlan;
  if (!receipt) return "";
  if (typeof receipt.run_id !== "string" || !receipt.run_id.trim()) {
    return '<p class="small">回执未提供运行 ID，无法关联本次任务进度。</p>';
  }
  const mission = currentMission();
  if (mission?.id !== plan.plan_id || mission.runId !== receipt.run_id
    || mission.sceneId !== plan.scene_id || mission.mapVersion !== plan.map_version) {
    return '<p class="small">等待 Runtime 上报本次任务进度。</p>';
  }
  const waypoints = mission.waypointsTotal > 0
    ? ` · 已验证航点 ${mission.waypointsReached} / ${mission.waypointsTotal}` : "";
  return `<p class="small">Runtime 上报 · ${esc(mission.runId)} · ${esc(missionPhases.get(mission.status))}${waypoints}</p>`;
}

function renderFixtureProgress() {
  const slot = document.getElementById("mission-fixture-progress");
  if (!slot) return;
  const html = fixtureProgressContent();
  if (slot.innerHTML !== html) slot.innerHTML = html;
}

function renderFixtureCandidate() {
  const slot = document.getElementById("mission-fixture-candidate");
  if (slot) slot.innerHTML = fixtureCandidateContent();
  renderFixtureProgress();
}

function validFixtureCandidate(plan) {
  if (typeof plan?.plan_id !== "string" || !plan.plan_id.trim()
    || plan.execution_authorized === true
    || plan.scene_id !== "simple_recon_v0_1" || plan.map_version !== "simple_recon_v0_1-map-1"
    || !Array.isArray(plan.steps) || !plan.steps.length) return false;
  const ids = new Set();
  for (const step of plan.steps) {
    if (typeof step?.step_id !== "string" || !step.step_id.trim() || ids.has(step.step_id)
      || typeof step.node_id !== "string" || !step.node_id.trim()
      || !["takeoff", "goto", "land"].includes(step.action_type)
      || (step.status != null && !["pending", "ready"].includes(step.status))) return false;
    if (step.action_type === "goto" && !["north_m", "east_m", "down_m"].every(key => Number.isFinite(step.params?.[key]))) return false;
    ids.add(step.step_id);
  }
  return plan.steps.some(step => step.action_type === "goto");
}

async function validateFixtureCandidate() {
  if (!missionFixture || stageMode || state.page !== "planning" || state.fixturePlan.validating || state.fixturePlan.submitted) return;
  const objective = state.templatePlan.objective.trim();
  const draft = { validating: Boolean(objective) };
  setFixturePlanDraft(draft);
  if (!objective) draft.error = "请先填写任务目标";
  renderFixtureCandidate();
  if (!objective) return;
  try {
    const candidate = await missionFixture.validateCandidate({ objective });
    if (state.fixturePlan !== draft) return;
    if (candidate?.result === "validated" && validFixtureCandidate(candidate.plan)) {
      const plan = JSON.parse(JSON.stringify(candidate.plan));
      draft.plan = plan;
      draft.preview = {
        version: "1.0", plan_id: plan.plan_id, scene_id: plan.scene_id, map_version: plan.map_version,
        frame: "scene_ned", expires_at_ms: Date.now() + FIXTURE_PLAN_PREVIEW_TTL_MS,
        waypoints: plan.steps.filter(step => step.action_type === "goto").map(({ step_id, node_id, params }) => ({
          step_id, node_id, north_m: params.north_m, east_m: params.east_m, down_m: params.down_m,
        })),
      };
      draft.previewTimer = window.setTimeout(() => {
        if (state.fixturePlan === draft) clearFixturePlanPreview();
      }, FIXTURE_PLAN_PREVIEW_TTL_MS);
      syncFixturePlanPreview();
    } else {
      draft.error = candidate?.failure_reason || "缺少已校验的载具、航点或场景版本";
    }
  } catch (error) {
    draft.error = `候选校验失败 · ${error.message}`;
  } finally {
    draft.validating = false;
    if (state.fixturePlan === draft) renderFixtureCandidate();
  }
}

async function confirmFixtureExecution(operatorId) {
  const draft = state.fixturePlan;
  if (!missionFixture || stageMode || state.page !== "planning" || !draft.plan || draft.submitted) return;
  if (typeof operatorId !== "string" || !operatorId.trim()) {
    draft.error = "请填写操作员 ID 后再确认";
    renderFixtureCandidate();
    return;
  }
  draft.submitted = true;
  draft.executing = true;
  draft.operatorId = operatorId.trim();
  draft.error = null;
  renderFixtureCandidate();
  renderTemplatePlan();
  try {
    const receipt = await missionFixture.execute({ plan: draft.plan, operator_id: draft.operatorId, decision: "approve" });
    if (receipt?.plan?.plan_id !== draft.plan.plan_id
      || !fixtureReceiptNames.has(receipt.result)) throw new Error("执行回执无法识别");
    draft.receipt = receipt;
  } catch (error) {
    draft.error = `执行状态未知，请先核对 Runtime · ${error.message}`;
  } finally {
    draft.executing = false;
    renderFixtureCandidate();
    renderTemplatePlan();
  }
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
  return `
    ${telemetryCard("max_altitude_m", formatNumber(state.maxAltitude), "#36c7f4")}
    ${telemetryCard("last_z", formatNumber(state.lastZ), "#42d883")}
    ${telemetryCard("threshold_reached", state.thresholdReached === null ? "--" : String(state.thresholdReached), "#f5b84c")}
    ${telemetryCard("current status", state.currentAction, "#9a7cff")}
  `;
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
  return `<div class="page mission-overview">
    ${pageTitle("Policy Gate", "策略裁决、触发规则与原始证据")}
    ${policyAuditPanel()}
  </div>`;
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
      : "HOLD 后端已实现并完成实测；主控台暂未接入保持操作，当前状态见实时遥测";
  return `<div class="page action-page">
    ${pageTitle("飞行控制与 Runtime", "指定节点 · Policy · MAVLink ACK · 遥测完成证据")}
    <div class="grid api-toolbar">
      ${panel("Runtime API 与传输端点", `<div class="form-grid"><div class="field"><label for="runtime-api-url">Runtime API Base URL</label><input id="runtime-api-url" value="${esc(state.apiBaseUrl)}"></div><div class="field"><label>所选 MAVLink Endpoint</label><input value="${esc(vehicle?.endpoint || "--")}" readonly></div><div class="field"><label>Telemetry REST</label><input value="${esc(state.apiBaseUrl)}/telemetry/latest" readonly></div></div><div style="margin-top:8px"><button class="button" onclick="saveApiBaseUrl(document.getElementById('runtime-api-url').value)">连接此 API</button> ${badge(`Runtime API ${api.label}`, api.color)} ${badge(`PX4 ${backend.label}`, backend.color)} ${state.apiLastError ? `<span class="small">${esc(state.apiLastError)}</span>` : ""}</div>`)}
      <button class="button primary" onclick="probeRuntime({notifyUser:true})">刷新全部状态</button>
    </div>
    <div class="split-2 h-fill" style="grid-template-columns:1.12fr .88fr">
      <div class="grid backend-action-column scroll">
        ${panel("指定节点动作", `<div class="form-grid"><div class="field"><label for="action-node">目标载具</label><select id="action-node" onchange="selectVehicle(this.value)">${state.fleet.map((item) => `<option value="${esc(item.id)}" ${item.id === state.selectedUav ? "selected" : ""}>${esc(item.id)} · SYS ${item.systemId ?? "-"}</option>`).join("")}</select></div><div class="field"><label for="action-altitude">目标相对高度 altitude_m</label><input id="action-altitude" type="number" min="1" max="120" step="0.5" value="${state.targetAltitude.toFixed(1)}" onchange="setTargetAltitude(this.value)"></div><div class="field"><label>MAVLink Identity</label><input value="${esc(`${vehicle?.systemId ?? "-"}/${vehicle?.componentId ?? "-"}`)}" readonly></div></div><div class="action-buttons"><button class="button" onclick="checkBackend()" ${!vehicle || state.apiStatus !== "live" ? "disabled" : ""}>Check Backend</button><button class="button primary" data-action="takeoff" onclick="runOperationalTakeoff()" ${!lifecycleReady || !takeoffPermission.allowed ? "disabled" : ""}>正式起飞</button><button class="button" data-action="smoke" onclick="runSmokeTakeoff()" ${!lifecycleReady || !takeoffPermission.allowed ? "disabled" : ""}>Smoke Test</button><button class="button warn" data-action="land" onclick="runLand()" ${!lifecycleReady || !landPermission.allowed ? "disabled" : ""}>受控降落</button></div><div class="control-notes">${badge(lifecycleReady ? "LIFECYCLE 1.1" : "正式动作接口暂不支持", lifecycleReady ? "green" : "amber")}<span class="small">TAKEOFF：${esc(takeoffPermission.reason)}</span><span class="small">LAND：${esc(landPermission.reason)}</span><span class="small">保持：${esc(holdState)}</span><span class="small">Smoke 为独立阈值测试；本控制台不请求自动降落。</span></div>`)}
        ${panel("动作界面规划", '<p class="small">前往航点、保持位置与返航的主控台入口规划中。</p>')}
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
  if (stageMode) return null;
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
  if (options.notifyUser !== false) {
    notify("Backend Check", `${nodeId} 返回 ${code}`, state.backendConnected ? "green" : "amber");
  }
  await syncRuntimeState({ notifyFailure: false });
  render();
  return payload;
}

function saveApiBaseUrl(value) {
  if (stageMode) return;
  if (state.actionRequestsInFlight.size || state.pendingActions.length || state.demoWriteInFlight || state.templatePlan.inFlight || state.fixturePlan.executing) {
    notify("地址未更改", "仍有请求在执行或等待核实，请先确认原 Runtime 的动作状态", "amber");
    render();
    return;
  }
  state.apiBaseUrl = window.SwarmRuntimeApi.setConfiguredBaseUrl(value);
  state.apiStatus = "checking";
  state.runtimeHealth = null;
  state.lastBackendResult = null;
  state.templatePlan.reply = null;
  state.templatePlan.error = null;
  setFixturePlanDraft();
  state.backendConnected = false;
  state.actionRecords = [];
  state.lifecycleRecords = [];
  state.lifecycleSupported = null;
  state.fleet = [];
  state.nodeStats = {};
  state.vehicleSnapshot = null;
  state.dataStatus = "checking";
  state.runtimeSnapshot = null;
  state.telemetry = null;
  state.registryPayload = null;
  state.runtimeEvents = [];
  state.auditEvents = null;
  state.replayEvents = null;
  state.auditStatus = "waiting";
  state.runtimeSnapshotCurrent = false;
  state.policyDecisions = [];
  state.decisionsLoaded = false;
  state.lifecycleLoaded = false;
  state.policySeen.clear();
  state.policyBannerReady = false;
  state.policyBanner = null;
  state.timelineKey = null;
  state.policyFilters = { node: "", decision: "" };
  state.mission = null;
  state.missionStatus = "waiting";
  state.missionTrend = "";
  state.links.clear();
  state.linkTrends.clear();
  state.demoRuntime = null;
  state.demoWriteStatus = "";
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
  return `<div class="page mission-overview">
    ${pageTitle("Audit / Replay", "审计事件与原始执行证据", '<button class="button" onclick="replayPlay()">刷新审计</button>')}
    ${timelinePanel({ full: true })}
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

async function generateRequest(missionType) {
  const draft = state.templatePlan;
  if (stageMode || state.page !== "planning" || draft.inFlight || state.fixturePlan.executing) return;
  draft.reply = null;
  if (!draft.objective.trim()) {
    draft.error = "请先填写任务目标";
    renderTemplatePlan();
    return;
  }
  // Runtime 对省略的模板键走规则识别，任务预览路由始终只读。
  const request = { objective: draft.objective };
  if (typeof missionType === "string" && missionType) request.mission_type = missionType;
  draft.inFlight = true;
  draft.error = null;
  renderTemplatePlan();
  try {
    draft.reply = await callRuntime("plan", () => window.SwarmRuntimeApi.planMission(request, {
      onSlow(maxWaitMs) {
        draft.slowHint = `Runtime 响应较慢，继续等待（最多 ${maxWaitMs / 1000} 秒）`;
        renderTemplatePlan();
      },
    }), error => {
      draft.error = error.kind === "timeout" ? "Runtime 响应超时" : error.message;
      return null;
    }, { notifyFailure: false });
  } finally {
    draft.inFlight = false;
    draft.slowHint = "";
    renderTemplatePlan();
    render();
  }
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
  if (stageMode) return;
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

async function replayPlay() {
  await syncRuntimeEvents({ notifyFailure: true });
  render();
}

/**
 * 观察复核（L2）页面。
 *
 * 这一页做的事：把**人工对图像的判定**记成一条可校验、可追溯的记录。
 *
 * 为什么它必须存在：采集到图像（L1，CAPTURE）与判定"是否观察到目标"（L2）是两件事。
 * 三方已对齐：CAPTURE 的 pass **不能**把 OBSERVE、巡检步骤或原任务标记为完成。
 * 在没有 L2 的情况下把巡检报成完成，就是本仓库反复防的那类假成功。
 *
 * 三条由 `SwarmConsoleModel.validateObservationReview` 强制的规则：
 *   1. 不得编造数值置信度（confidence 必须显式 null）
 *   2. reviewer 必须是 `human:` 前缀 —— 本阶段只接受人工复核
 *   3. `not_observed` / `undetermined` 必须给出依据
 */
function observationPage() {
  const reviewModel = reviewModelApi();
  const draft = state.reviewDraft || {};
  const result = state.reviewResult || null;

  const field = (id, label, value, opts = {}) => {
    const type = opts.type || "text";
    const ph = opts.placeholder ? ` placeholder="${esc(opts.placeholder)}"` : "";
    return `<div class="field"><label for="${id}">${esc(label)}</label>`
      + `<input id="${id}" type="${type}" value="${esc(value ?? "")}"${ph}`
      + ` oninput="setReviewDraft('${opts.key}', this.value)"></div>`;
  };

  const body = `
    <div class="design-preview-notice">
      <b>本阶段不能当验收证据</b>
      <span>${esc("CAPTURE（采集）端点尚未实现，因此 capture_id 与图像哈希都靠人工录入——校验器只能保证格式与哈希自洽，不能证明它们来自真实采集。等 CAPTURE 接通、capture_id 由 Runtime 签发后，这一点才会成立。")}</span>
    </div>
    <div class="design-preview-notice">
      <b>为什么要有 L2</b>
      <span>${esc("采集到图像不等于观察到目标。CAPTURE 的 pass 不能把巡检报成完成；那正是本项目反复防的假成功。本页只记录人工判定，不自动产生结论。")}</span>
    </div>
    ${panel("新建复核记录", `
      <div class="form-grid">
        ${field("review-task", "任务 ID (task_id)", draft.taskId, { key: "taskId", placeholder: "TASK-1" })}
        ${field("review-target", "目标 ID (target_id)", draft.targetId, { key: "targetId", placeholder: "target-001" })}
        ${field("review-capture", "采集 ID (capture_id)", draft.captureId, { key: "captureId", placeholder: "cap-…" })}
        ${field("review-criterion", "判据版本 (criterion_version)", draft.criterionVersion, { key: "criterionVersion", placeholder: "l2-criterion-v0.1" })}
        ${field("review-reviewer", "复核人 (reviewer)", draft.reviewer, { key: "reviewer", placeholder: "human:<你的标识>" })}
        ${field("review-vehicle", "载具 (vehicle_id)", draft.vehicleId, { key: "vehicleId", placeholder: "UAV-01" })}
        ${field("review-camera", "相机 (camera_id)", draft.cameraId, { key: "cameraId", placeholder: "front_rgb" })}
        ${field("review-captured-at", "采集时刻 (captured_at)", draft.capturedAt, { key: "capturedAt", placeholder: "2026-10-05T11:59:30Z" })}
        ${field("review-width", "宽 (width)", draft.width, { key: "width", placeholder: "1280" })}
        ${field("review-height", "高 (height)", draft.height, { key: "height", placeholder: "960" })}
        ${field("review-encoding", "像素格式 (encoding)", draft.encoding, { key: "encoding", placeholder: "RGB8" })}
        ${field("review-image-ref", "图像引用 (image.ref)", draft.imageRef, { key: "imageRef", placeholder: "sha256:<64 位小写十六进制>" })}
      </div>
      <div class="field"><label for="review-outcome">结论 (outcome)</label>
        <select id="review-outcome" onchange="setReviewDraft('outcome', this.value)">
          ${Object.keys(reviewModel.REVIEW_OUTCOMES).map((key) => {
            const labels = { observed: "observed —— 按判据看到了目标", not_observed: "not_observed —— 未按判据看到（不证明目标不存在）", undetermined: "undetermined —— 判不了" };
            return `<option value="${esc(key)}" ${draft.outcome === key ? "selected" : ""}>${esc(labels[key] || key)}</option>`;
          }).join("")}
        </select>
      </div>
      <div class="field"><label for="review-note">判断依据（文字说明）</label>
        <input id="review-note" value="${esc(draft.note ?? "")}" placeholder="目标位于画面中央偏右 / 画面模糊无法判定" oninput="setReviewDraft('note', this.value)"></div>
      <div class="action-buttons">
        <button class="button primary" onclick="submitObservationReview()">校验并生成记录</button>
        <button class="button" onclick="clearObservationReview()">清空</button>
      </div>
      <div class="control-notes">
        <span class="small">结论为 <b>not_observed</b> 或 <b>undetermined</b> 时，必须填写文字说明——没有依据的否定与「检测器没报」无法区分。</span>
        <span class="small">不提供"置信度"输入框：人工结论不伪造数值置信度。</span>
      </div>
    `)}
    ${panel("校验结果", reviewResultView(result))}
    ${panel("记录 JSON（可复制保存；格式与 Python 侧一致）",
      result && result.ok
        ? `<pre class="json scroll">${esc(JSON.stringify(result.record, null, 2))}</pre>`
        : `<div class="empty-state">校验通过后在此显示记录 JSON</div>`)}
    ${panel("导入并校验已有记录",
      `<div class="field"><label for="review-import">粘贴记录 JSON</label>
        <input id="review-import" placeholder='{"review_version":"0.1", …}' oninput="setReviewImport(this.value)"></div>
       <div class="action-buttons"><button class="button" onclick="validateImportedObservationReview()">校验这份记录</button></div>
       ${state.reviewImportResult ? reviewResultView(state.reviewImportResult) : `<div class="empty-state">尚未校验</div>`}`)}
  `;

  return `<div class="page">
    ${pageTitle("观察复核 (L2)", "对采集图像的人工判定记录。CAPTURE pass 只代表采集完成，不代表观察到目标。")}
    ${body}
  </div>`;
}

/** 取复核模型；页面在 Node 测试环境里也要能渲染。 */
function reviewModelApi() {
  return (typeof window !== "undefined" && window.SwarmConsoleModel)
    || (typeof SwarmConsoleModel !== "undefined" ? SwarmConsoleModel : null)
    || {};
}

function reviewResultView(result) {
  if (!result) return `<div class="empty-state">尚未校验</div>`;
  if (result.ok) {
    return `<div>${badge("校验通过", "green")} <span class="small">review_id ${esc(result.record.review_id)}，confidence 为 null，linked_task_completion 为 not_asserted。</span></div>`;
  }
  return `<div class="inline-error">${result.violations.length} 处不合法，已拒绝（不部分采纳）：</div>
    <table class="table"><thead><tr><th>代码</th><th>字段</th><th>说明</th><th>实际值</th></tr></thead><tbody>
    ${result.violations.map((v) => `<tr>
      <td>${esc(v.code)}</td><td>${esc(v.field || "--")}</td>
      <td>${esc(v.hint || "")}</td>
      <td class="small">${esc(v.value === undefined || v.value === null ? "--" : JSON.stringify(v.value))}</td>
    </tr>`).join("")}</tbody></table>`;
}

function setReviewDraft(key, value) {
  state.reviewDraft = { ...(state.reviewDraft || {}), [key]: value };
  // 不整页重渲染：输入框正在被编辑，重渲染会丢光标。
}

function clearObservationReview() {
  state.reviewDraft = {};
  state.reviewResult = null;
  state.reviewImportResult = null;
  render();
}

function setReviewImport(value) {
  state.reviewImportRaw = value;
}

/** 从草稿构造 image 对象。缺字段就让校验器去报，不在这里提前替它判断。 */
function reviewImageFromDraft(draft) {
  return {
    ref: draft.imageRef,
    sha256: String(draft.imageRef || "").replace(/^sha256:/, ""),
    width: Number(draft.width),
    height: Number(draft.height),
    encoding: draft.encoding || "RGB8",
    captured_at: draft.capturedAt,
    vehicle_id: draft.vehicleId,
    camera_id: draft.cameraId || "front_rgb",
  };
}

function submitObservationReview() {
  const model = reviewModelApi();
  const draft = state.reviewDraft || {};
  if (typeof model.buildObservationReview !== "function") {
    notify("复核模型不可用", "SwarmConsoleModel.buildObservationReview 缺失。", "amber");
    return;
  }
  const result = model.buildObservationReview({
    taskId: draft.taskId,
    targetId: draft.targetId,
    captureId: draft.captureId,
    image: reviewImageFromDraft(draft),
    criterionVersion: draft.criterionVersion,
    reviewer: draft.reviewer,
    reviewedAt: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    outcome: draft.outcome || "observed",
    note: draft.note,
  });
  state.reviewResult = result;
  if (result.ok) {
    notify("记录已生成", "校验通过。请复制 JSON 保存，或用 scripts/observe_review.py 写入。", "green");
  } else {
    notify("记录不合法", `${result.violations.length} 处问题，未生成记录。`, "amber");
  }
  render();
}

function validateImportedObservationReview() {
  const model = reviewModelApi();
  const raw = state.reviewImportRaw;
  if (!raw || !raw.trim()) {
    state.reviewImportResult = { ok: false, violations: [{ code: "empty_input", field: "review-import", hint: "请先粘贴记录 JSON。" }] };
    render();
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    state.reviewImportResult = { ok: false, violations: [{ code: "invalid_json", field: "review-import", hint: String(error.message || error) }] };
    render();
    return;
  }
  state.reviewImportResult = model.validateObservationReview(parsed);
  render();
}

/**
 * 澄清待办页面。
 *
 * 算法侧遇到目标歧义时**不猜**，而是返回澄清请求要求操作者补全。交接说明写明：
 *
 *   > `resolution=resubmit_objective_without_tasks`。调用方应在现有控制台把问题
 *   > 呈现给操作者。
 *
 * 这一页就是那个"呈现"。两种真实形状：
 *   · `EXTERNAL_TASKS_FORBIDDEN` —— 请求里带了 `tasks`，需要**去掉 tasks 重新提交**
 *   · `AMBIGUOUS_HIGHEST_BUILDING` 等 —— 目标歧义，需要**从候选里指定实体**
 *
 * ⚠️ 这一页最容易做错的地方：让操作者"改一下再提交"，却没告诉他**改了哪里**。
 * 那会变成"提交→被拒→再提交"的循环。所以每个澄清都显式给出：
 *   问题是什么 / 为什么被拒 / 下一步该改哪个字段。
 */
function clarificationPage() {
  const model = reviewModelApi();
  const parsed = state.clarificationParsed || null;
  const resubmitResult = state.clarificationResubmitResult || null;

  const body = `
    <div class="design-preview-notice">
      <b>算法侧不会猜</b>
      <span>${esc("遇到目标歧义或请求形态不合格时，算法侧返回澄清请求而不是猜一个答案。猜错等于飞错目标，所以这里要求人来定。")}</span>
    </div>
    ${panel("粘贴算法侧返回的澄清请求",
      `<div class="field"><label for="clarify-raw">澄清请求 JSON（或整份响应）</label>
        <input id="clarify-raw" placeholder='{"status":"clarification_required", …}' oninput="setClarificationRaw(this.value)"></div>
       <div class="action-buttons"><button class="button primary" onclick="parseClarification()">解析</button>
         <button class="button" onclick="useClarificationSample('ambiguous')">填入示例：目标歧义</button>
         <button class="button" onclick="useClarificationSample('tasks')">填入示例：请求带了 tasks</button>
       </div>`)}
    ${panel("澄清内容", clarificationView(parsed))}
    ${panel("修正后重新提交",
      `${clarificationMissionHint(parsed)}
       <div class="field"><label for="clarify-mission">任务 ID mission_id</label>
        <input id="clarify-mission" value="${esc(state.clarifyMissionId ?? "")}" oninput="setClarifyMissionId(this.value)"></div>
       <div class="field"><label for="clarify-objective">任务目标 objective</label>
        <input id="clarify-objective" value="${esc(state.clarifyObjective ?? "")}" oninput="setClarifyObjective(this.value)"></div>
       <div class="action-buttons"><button class="button primary" onclick="buildClarificationResubmit()">生成重提交请求</button></div>
       <div class="control-notes">
         <span class="small"><b>重提交不带 tasks</b>：算法侧要求任务清单由目标派生。带上 tasks 会再次被拒，所以这里根本不给输入口。</span>
         <span class="small"><b>句子里必须出现实体 ID</b>：算法侧按显式标签匹配。写"就是那栋高的"仍然会是歧义。</span>
       </div>`)}
    ${panel("重提交请求 JSON",
      resubmitResult && resubmitResult.ok
        ? `<pre class="json scroll">${esc(JSON.stringify(resubmitResult.request, null, 2))}</pre>`
        : `<div class="empty-state">生成后在此显示</div>`)}
    ${resubmitResult && !resubmitResult.ok ? reviewResultView(resubmitResult) : ""}
  `;

  return `<div class="page">
    ${pageTitle("澄清待办", "算法侧遇到歧义时返回的问题，以及修正后重新提交的请求。")}
    ${body}
  </div>`;
}

function clarificationView(parsed) {
  if (!parsed) return `<div class="empty-state">尚未解析</div>`;
  if (!parsed.ok) return reviewResultView(parsed);

  const c = parsed.clarification;
  const kindLabel = c.kind === "external_tasks_forbidden"
    ? "请求形态不合格（带了 tasks）"
    : "目标歧义";
  const nextStep = c.kind === "external_tasks_forbidden"
    ? "去掉 tasks，只保留 objective 与 mission_id 后重新提交。"
    : "从下列候选里指定一个目标实体，把它的 ID 写进 objective 后重新提交。";

  const candidateRows = c.candidates.length
    ? `<table class="table"><thead><tr><th>目标实体</th><th>高度 (m)</th><th>中心 N (m)</th><th>中心 E (m)</th><th>选择</th></tr></thead><tbody>
      ${c.candidates.map((cand) => `<tr>
        <td>${esc(cand.targetId)}</td>
        <td>${esc(cand.heightM ?? "--")}</td>
        <td>${esc(cand.centerNorthM ?? "--")}</td>
        <td>${esc(cand.centerEastM ?? "--")}</td>
        <td><button class="button" onclick="selectClarificationCandidate('${esc(cand.targetId)}')">选它</button></td>
      </tr>`).join("")}</tbody></table>`
    : `<div class="empty-state">没有候选可指定</div>`;

  return `<div>
    ${badge(kindLabel, c.kind === "external_tasks_forbidden" ? "amber" : "cyan")}
    ${c.reasonCode ? badge(c.reasonCode, "amber") : ""}
    ${parsed.violations.length ? `<div class="inline-error">${esc(parsed.violations.map((v) => v.hint).join(" "))}</div>` : ""}
    <table class="table">
      <tr><th>问题</th><td>${esc(c.question ?? "（算法侧未给出问题文本，请据 reason_code 判断）")}</td></tr>
      ${c.matchedText ? `<tr><th>匹配到的说法</th><td>${esc(c.matchedText)}</td></tr>` : ""}
      ${c.conflictingFields.length ? `<tr><th>冲突字段</th><td>${esc(c.conflictingFields.join("、"))}</td></tr>` : ""}
      ${c.audience ? `<tr><th>应答者</th><td>${esc(c.audience)}</td></tr>` : ""}
      ${c.missionId ? `<tr><th>任务</th><td>${esc(c.missionId)}</td></tr>` : ""}
      <tr><th>下一步</th><td>${esc(nextStep)}</td></tr>
    </table>
    ${panel("候选目标", candidateRows, "nested")}</div>`;
}

function setClarificationRaw(value) { state.clarificationRaw = value; }
function setClarifyObjective(value) { state.clarifyObjective = value; }
function setClarifyMissionId(value) { state.clarifyMissionId = value; }

function useClarificationSample(which) {
  const samples = {
    ambiguous: {
      // 贴近 scene_binding 的真实返回：带 objective 与 scene 身份，且**没有** mission_id。
      authority: "objective",
      objective: "到最高的那栋楼旁边",
      scene_id: "simple_recon_v0_1",
      map_version: "simple_recon_v0_1-map-1",
      coordinate_frame: "scene_ned",
      status: "clarification_required", accepted: false,
      reason_code: "AMBIGUOUS_HIGHEST_BUILDING", matched_text: "最高的那栋楼",
      candidates: [
        { target_id: "link-block-4-3-2-1", height_m: 52.0, center_north_m: 350.0, center_east_m: 53.2 },
        { target_id: "link-block-4-3-3-2", height_m: 52.0, center_north_m: 432.0, center_east_m: 179.8 },
      ],
      clarification_question: "最高建筑并列；请指定目标建筑 ID。",
    },
    tasks: {
      reason_code: "EXTERNAL_TASKS_FORBIDDEN",
      clarification_request: {
        audience: "originating_operator", mission_id: "mission-1",
        conflicting_fields: ["objective", "tasks"],
        question: "请确认原始任务目标并重新提交；任务清单将由目标派生。",
        resolution: "resubmit_objective_without_tasks",
      },
    },
  };
  state.clarificationRaw = JSON.stringify(samples[which], null, 2);
  state.clarificationParsed = null;
  state.clarificationResubmitResult = null;
  render();
}

function parseClarification() {
  const model = reviewModelApi();
  const raw = state.clarificationRaw;
  if (!raw || !raw.trim()) {
    state.clarificationParsed = { ok: false, violations: [{ code: "empty_input", field: "clarify-raw", hint: "请先粘贴澄清请求 JSON。" }] };
    render();
    return;
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (error) {
    state.clarificationParsed = { ok: false, violations: [{ code: "invalid_json", field: "clarify-raw", hint: String(error.message || error) }] };
    render();
    return;
  }
  const parsed = model.normalizeClarification(payload);
  state.clarificationParsed = parsed;
  if (parsed.ok) {
    // mission_id：澄清自带就预填，**不自带就显式置空**。
    // 置空而不是留着 undefined —— 否则输入框渲染出 "undefined"，
    // 而"没有值"与"值是个叫 undefined 的字符串"在界面上看起来一样。
    state.clarifyMissionId = parsed.clarification.missionId || "";
    // objective：`scene_binding` 的返回里带原始那句话，预填它。
    // 不预填的话操作者得重新手打一遍，而句子里往往正是需要保留的上下文
    // （"最高的那栋楼旁边"）—— 手打一遍很容易丢掉它，然后又被拒一次。
    state.clarifyObjective = parsed.clarification.objective || "";
    state.clarifyOriginalObjective = state.clarifyObjective;
    notify("已解析澄清请求", parsed.clarification.question || parsed.clarification.reasonCode || "", "cyan");
  } else {
    notify("这不是澄清请求", "普通拒绝不应被当成需要回答的问题。", "amber");
  }
  render();
}

function selectClarificationCandidate(targetId) {
  const model = reviewModelApi();
  const parsed = state.clarificationParsed;
  if (!parsed || !parsed.ok) return;
  // 把候选 ID 拼进 objective。**句子里必须出现实体 ID** ——
  // 算法侧按显式标签匹配，写"就是那栋高的"仍然会是歧义。
  state.clarifyObjective = model.composeClarifiedObjective({
    originalObjective: state.clarifyObjective || "",
    selectedTargetId: targetId,
  });
  notify("已选定目标实体", `${targetId} 已写入 objective。`, "green");
  render();
}

function buildClarificationResubmit() {
  const model = reviewModelApi();
  const parsed = state.clarificationParsed;
  const result = model.buildClarificationResubmission({
    missionId: state.clarifyMissionId,
    objective: state.clarifyObjective,
    resolution: parsed && parsed.ok ? parsed.clarification.resolution : undefined,
  });
  state.clarificationResubmitResult = result;
  notify(result.ok ? "已生成重提交请求" : "无法生成",
    result.ok ? "只含 mission_id 与 objective，不含 tasks。" : `${result.violations.length} 处问题。`,
    result.ok ? "green" : "amber");
  render();
}

/**
 * 澄清请求不带 `mission_id` 时的提示。
 *
 * 为什么需要：`scene_binding` 的返回里**没有** `mission_id`（它的 `_base` 只给
 * authority / objective / scene_id / map_version / …）。于是操作者填完 objective、
 * 点"生成"，只会看到一句 `mission_id_required` —— **却不知道这个值该从哪来**。
 *
 * 修法不是自动编一个 id（那会让重提交关联到一个不存在的任务），
 * 而是**把这件事说明白**。
 */
function clarificationMissionHint(parsed) {
  if (!parsed || !parsed.ok) return "";
  if (parsed.clarification.missionId) return "";
  return `<div class="design-preview-notice">
    <b>需要你填 mission_id</b>
    <span>${esc("这条澄清请求里没有 mission_id —— 场景绑定（scene_binding）的返回本来就不带它。请从你最初提交的任务里取，界面不会替你编一个：编出来的 id 会让重提交关联到一个不存在的任务。")}</span>
  </div>`;
}

function assetsPage() {
  return placeholderPage("硬件资产", "飞控、通信、载荷与传感器台账", "等待硬件资产数据接口。");
}
function modelPage() {
  return placeholderPage("模型与知识", "模型配置、知识库与数据集管理", "等待模型与知识库配置接口。");
}
function settingsPage() {
  return placeholderPage("系统设置", "权限、日志与设备配置", "Runtime 地址可在 Adapter / Backend 配置。",
    '<button class="button" onclick="setPage(\'backend\')">前往 Adapter / Backend</button>');
}

function placeholderPage(title, subtitle, text, action = "") {
  return `<div class="page">
    ${pageTitle(title, subtitle)}
    ${panel("规划中", `<div class="empty-state">${esc(text)} ${action}</div>`)}
  </div>`;
}

/**
 * 重新渲染界面。
 *
 * ⚠️ 这里**不能**对 #app 做整树 innerHTML 替换。
 *
 * 三维视图是页面里的一个 <iframe>。整树替换会销毁并重建这个 iframe，
 * 后果是 Cesium 场景重新加载、选中状态丢失、相机复位——用户看到的是
 * "点一下载具列表，左边地图就刷新一次"。而 renderRuntimeUpdate() 在非 twin
 * 页面每 2 秒就会走到这里，所以那个看似只影响点击的问题实际上一直在发生。
 *
 * 关于"把 iframe 摘下来再放回去"的保活写法（曾被尝试）：
 * 用 Playwright 实测过四种移动方式——appendChild / replaceChildren /
 * remove+append 回同一父元素 / remove 后再移到别的父元素——**全部触发重新加载**；
 * 连"移动 iframe 的祖先容器"也一样重载。所以任何"搬动"的思路都不成立。
 * 实测有效的唯一做法是：**根本不碰 iframe 所在的子树**，分块更新其余区域。
 *
 * 因此结构是：外壳只建一次，各区域各有独立容器，render() 只更新容器内部。
 * 三维视图所在的 #simulation-frame-wrap 不在任何一次更新范围内。
 */
function render() {
  ensureShell();
  if (stageMode && dashboard) renderStage();
  else {
    renderRegions();
    if (state.page === "overview") drawMissionCoverage();
  }
  renderPolicyBanner();
}

/** 只建立一次外壳与各区域容器。 */
function ensureShell() {
  // ⚠️ 这里刻意用可选链读 dataset。
  //
  // 控制台的单元测试不挂载真实 DOM：它们用一个极简对象替换 #app
  // （见 tests/action-ui.test.js：`const app = { innerHTML: "", addEventListener() {} }`），
  // 该对象没有 dataset 属性。直接写 `.dataset.shellMounted` 会抛 TypeError，
  // 一次性打挂 12 个既有测试 —— 这是实测踩到的，并用 stash 对比基线确认过。
  const host = document.getElementById("app");
  if (!host) return;
  if (host.dataset?.shellMounted === "1") return;
  if (stageMode && dashboard) {
    host.innerHTML = `<main class="stage-shell${builtInDemo ? " stage-demo" : ""}">
      <header class="stage-bar">
        <b>2026UAVSwarm</b>
        <div id="stage-indicators"></div>
        <a class="button stage-link" href="./">返回主控台</a>
      </header>
      ${stageNavigation()}
      <div id="stage-title"></div><div id="stage-content"></div>
      <div id="slot-banner"></div>
    </main>`;
    if (host.dataset) host.dataset.shellMounted = "1";
    return;
  }

  // ⚠️ 外壳结构必须与 CSS 的网格定义严格对应，否则整页布局会错位。
  //
  // `.shell` 是 CSS Grid（styles.css:46）：
  //     grid-template-columns: 252px minmax(0, 1fr);
  //     grid-template-rows: auto 1fr;
  // 且**只有 `.topbar` 有显式定位**（grid-column: 1 / -1），
  // `.sidebar` 与 `.content` 都靠**自动落格**：第 1 个位置被 topbar 占掉整行后，
  // sidebar 落 [第2行第1列]、content 落 [第2行第2列]。
  //
  // 因此直接子元素的**数量与顺序**都不能变。曾经把 sidebar 和 content 各包一层
  // 无类名的 #slot-* 容器，结果自动落格全乱：sidebar 被拉成横跨整行的 64px 条，
  // content 被挤成 224px 窄列，整页无法使用（实测截图确认）。
  //
  // 现在的做法：**语义元素仍是网格项**（保持原版顺序与数量），slot 作为它们内部的
  // 容器。末尾那个 .toast-stack 是 position:fixed，不参与网格流，保持它在最后。
  host.innerHTML = `<div class="shell">
    <header class="topbar" id="slot-topbar"></header>
    <aside class="sidebar" id="slot-sidebar"></aside>
    <main class="content"><div id="slot-content"></div></main>
    <div id="slot-toast"></div><div id="slot-banner"></div>
  </div>`;
  if (host.dataset) host.dataset.shellMounted = "1";
  state.renderedPage = null;
}

/**
 * 更新各区域内容。
 *
 * 关键约束：**只要当前页是 twin，#slot-content 就不能整体替换** ——
 * 三维视图的 iframe 在它内部，整块替换等于销毁重建。
 *
 * 但同一页面内的状态更新（选中载具、遥测刷新、动作结果）又必须反映到界面上。
 * 因此按"结构是否变化"分流：
 *   - 页面切换（结构变）→ 重建 #slot-content，iframe 随之重建（可接受：确实换页了）
 *   - 同页更新（结构不变）→ 只更新各区域的局部节点，不碰 iframe
 *
 * twin 页的局部更新范围是"节点列表 / 遥测 / 指标"这些面板，
 * 三维面板自身不需要重绘（它的内容由 iframe 自己管，父页面只推快照）。
 */
function renderRegions() {
  const topbarSlot = document.getElementById("slot-topbar");
  const sidebarSlot = document.getElementById("slot-sidebar");
  const contentSlot = document.getElementById("slot-content");
  const toastSlot = document.getElementById("slot-toast");

  if (topbarSlot) topbarSlot.innerHTML = topbar();
  if (sidebarSlot) sidebarSlot.innerHTML = sidebar();

  const pageChanged = state.renderedPage !== state.page;

  // ⚠️ 这里**不能**因为"表格是空的"就重建 #slot-content。
  //
  // 曾经这样"自愈"过，结果是灾难性的：重建 #slot-content 会连三维视图的 iframe
  // 一起销毁重建，而该条件在数据到位后持续成立（空表 + 有 fleet），于是每次
  // render 都重载一次地图。实测表现为 readyCount 不断增长。
  //
  // 空表的问题改由 updatePageInPlace() 原地填充解决 —— 它可以只更新 <tbody>，
  // 完全不触碰 iframe。
  if (contentSlot && (pageChanged || !contentSlot.firstElementChild)) {
    contentSlot.innerHTML = route();
    state.renderedPage = state.page;
    // 首屏之后立刻做一次局部刷新：切页时数据可能还没到，首屏会渲染成空状态。
    updatePageInPlace();
  } else if (contentSlot) {
    updatePageInPlace();
  }

  if (toastSlot) toastSlot.innerHTML = toastStack();
}

/**
 * 同页局部更新：只替换会被状态影响的面板内容，不动三维视图所在容器。
 *
 * twin 页保留 iframe；任务规划页保留输入框和证据控件。
 * 其它页面仍走整体重建。
 */
function updatePageInPlace() {
  if (state.page === "planning" && document.getElementById("semantic-preview-result")) {
    // 后台探活不能重建当前的下拉列表或文件选择框。
    updateVehicleTableInPlace();
    renderFixtureProgress();
    return;
  }
  if (state.page !== "twin") {
    const contentSlot = document.getElementById("slot-content");
    if (contentSlot) contentSlot.innerHTML = route();
    return;
  }
  const frameWrap = document.querySelector(".simulation-frame-wrap");
  if (!frameWrap) {
    // 结构不符合预期（例如首次从别的页面切过来）→ 退化为整体重建
    const contentSlot = document.getElementById("slot-content");
    if (contentSlot) contentSlot.innerHTML = route();
    state.renderedPage = state.page;
    return;
  }

  updateVehicleTableInPlace();
  const telemetry = document.getElementById("selected-telemetry");
  if (telemetry) telemetry.innerHTML = telemetrySummary();
  const summary = fleetSummary();
  document.querySelectorAll("[data-metric='online']").forEach((node) => {
    node.textContent = `${summary.online}/${summary.total}`;
  });
  document.querySelectorAll("[data-metric='armed']").forEach((node) => {
    node.textContent = String(summary.armed);
  });
  document.querySelectorAll("[data-metric='issues']").forEach((node) => {
    node.textContent = String(state.linkIssues ?? "--");
  });
}

function updateVehicleTableInPlace() {
  const table = document.getElementById("vehicle-table-body");
  if (table) table.innerHTML = vehicleTableRows();
  const emptyNote = document.getElementById("vehicle-table-empty");
  if (emptyNote) emptyNote.hidden = state.fleet.length > 0;
}

function topbar() {
  const api = runtimeApiStatus();
  const dataSource = dataSourceStatus();
  const source = sourceLabel();
  const summary = fleetSummary();
  const now = new Date();
  const fleetState = state.apiStatus === "checking"
    ? "检查中"
    : summary.total > 0 && summary.online === summary.total
      ? "HEALTHY"
      : summary.online > 0 ? "DEGRADED" : "OFFLINE";
  // 只返回 topbar 的**内容**，不返回 <header> 本身。
  //
  // <header class="topbar" id="slot-topbar"> 由 ensureShell() 建一次，且它必须是
  // .shell 的直接子元素（CSS 靠自动落格把它放在第 1 行通栏）。
  // 这里若再返回一层 <header>，就会出现 header 套 header 的冗余结构。
  if (state.page === "overview") return `
    <div class="brand"><div class="mark"></div><div class="brand-title">2026UAVSwarm Console</div></div>
    <div class="top-actions">
      <button class="icon-btn" title="状态说明" onclick="showStatusHelp()">?</button>
      <button class="icon-btn" title="刷新 Runtime" onclick="probeRuntime({notifyUser:true})">R</button>
    </div>`;
  return `
    <div class="brand"><div class="mark"></div><div class="brand-title">2026UAVSwarm Console</div></div>
    ${badge(source.text, source.color)}
    <div class="top-pill profile-pill">Ground Profile</div>
    <div class="top-pill">Fleet Telemetry<strong class="${state.backendConnected ? "green" : "amber"}">${fleetState}</strong></div>
    <div class="top-pill">在线节点<strong>${summary.online} / ${summary.total}</strong></div>
    <div class="top-pill">目标载具<strong>${esc(state.selectedUav || "--")}</strong></div>
    <div class="top-pill">当前 Action<strong>${esc(state.currentAction)}</strong></div>
    <div class="top-pill">Runtime API<strong class="${api.color}">${api.label}</strong></div>
    <div class="top-pill">遥测状态<strong class="${dataSource.color}">${dataSource.label}</strong></div>
    <div class="top-actions">
      <button class="icon-btn" title="三维态势" onclick="setPage('twin')">3D</button><button class="icon-btn" title="状态说明" onclick="showStatusHelp()">?</button><button class="icon-btn" title="刷新 Runtime" onclick="probeRuntime({notifyUser:true})">R</button>
      <div class="operator"><div class="avatar"></div><div><div>Operator_01</div><div class="small">管理员</div></div></div>
      <div class="small top-time">${esc(now.toLocaleDateString("zh-CN"))}<br>UTC+8</div>
    </div>`;
}

function sidebar() {
  // 同 topbar()：只返回导航内容。<aside class="sidebar" id="slot-sidebar">
  // 由 ensureShell() 建一次，并作为 .shell 的直接子元素参与网格自动落格。
  return `<nav class="nav">
    ${navItems.map(([id, label, icon]) => {
      const planned = ["assets", "model", "settings"].includes(id);
      return `<button title="${label}${planned ? " · 规划中" : ""}" class="${state.page === id ? "active " : ""}${planned ? "nav-planned" : ""}" onclick="setPage('${id}')"><span class="nav-icon">${icon}</span><span>${label}</span><span>${planned ? '<small class="nav-plan-tag">规划中</small>' : "›"}</span></button>`;
    }).join("")}
  </nav>`;
}

function setPage(page) {
  if (stageMode) return;
  if (page !== state.page) fixturePreviewFrame = null;
  state.page = page;
  if (page === "twin" && state.renderedPage !== "twin") state.simulationReady = false;
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
    observation: observationPage,
    clarification: clarificationPage,
    assets: assetsPage,
    replay: replayPage,
    model: modelPage,
    settings: settingsPage,
  };
  return (pages[state.page] || overviewPage)();
}

render();
if (!builtInDemo) probeRuntime();

app.addEventListener("click", (event) => {
  if (stageMode && dashboard) {
    const view = event.target.closest("[data-stage-view]");
    if (view) return seekStage(Number(view.dataset.stageView));
    if (event.target.closest("[data-stage-restart]")) return toggleStagePlayback(true);
    if (event.target.closest("[data-stage-play]")) return toggleStagePlayback();
  }
  const decision = event.target.closest("[data-policy-open]");
  if (decision && state.policyBanner) {
    state.timelineKey = state.policyBanner.entry.key;
    if (stageMode) renderStage();
    else setPage("policy");
    return;
  }
  if (event.target.closest("[data-policy-dismiss]")) {
    state.policyBanner = null;
    renderPolicyBanner();
    return;
  }
  const timeline = event.target.closest("[data-timeline-key]");
  if (timeline) {
    state.timelineKey = state.timelineKey === timeline.dataset.timelineKey ? null : timeline.dataset.timelineKey;
    if (stageMode && stagePlayback.startedAt !== null) return toggleStagePlayback();
    render();
    return;
  }
  const demo = event.target.closest("[data-demo-operation]");
  if (demo) {
    changeDemoLink(demo.dataset.demoOperation);
    return;
  }
  if (stageMode) return;
  if (event.target.closest("[data-semantic-infer]")) return inferSemanticPreview();
  if (event.target.closest("[data-semantic-health]")) return checkSemanticLab();
  const sample = event.target.closest("[data-semantic-sample]");
  if (sample) return loadSemanticSample(sample.dataset.semanticSample);
  const target = event.target.closest("[data-vehicle-id]");
  if (target) selectVehicle(target.dataset.vehicleId);
});

app.addEventListener("input", (event) => {
  if (event.target.hasAttribute?.("data-template-plan-objective")) setTemplatePlanObjective(event.target.value);
  if (event.target.hasAttribute?.("data-semantic-live-objective")) setSemanticLiveObjective(event.target.value);
});

app.addEventListener("toggle", (event) => {
  if (event.target.hasAttribute?.("data-semantic-live-details")) state.semanticLiveDetailsOpen = event.target.open;
  if (event.target.hasAttribute?.("data-semantic-details")) state.semanticPreviewDetailsOpen = event.target.open;
}, true);

app.addEventListener("change", (event) => {
  if (event.target.hasAttribute?.("data-semantic-live-example")) {
    const difference = Number(event.target.value);
    event.target.value = "";
    if (semanticLiveExamples.some(([value]) => value === difference)) {
      setSemanticLiveObjective(`请登记已导出目录里，北侧首排东半幅比20米高${difference}米的那栋楼。`);
    }
    return;
  }
  if (event.target.hasAttribute?.("data-semantic-model-sample")) {
    const file = event.target.value;
    event.target.value = "";
    return loadSemanticSample(file);
  }
  if (event.target.hasAttribute?.("data-semantic-file")) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) return loadSemanticPreview(() => file.text(), file.name, file.size);
    return;
  }
  if (event.target.hasAttribute?.("data-demo-target")) {
    selectVehicle(event.target.value);
    return;
  }
  const filter = event.target.dataset?.policyFilter;
  if (filter !== "node" && filter !== "decision") return;
  state.policyFilters[filter] = event.target.value;
  render();
});

function renderRuntimeUpdate() {
  if (stageMode && dashboard) {
    renderStage();
    return;
  }
  if (state.page === "twin") {
    postVehicleSnapshot();
    // 还要做一次**原地**更新。
    //
    // 原先这里只有 postVehicleSnapshot() 就 return 了，于是 twin 页的 DOM 从首次
    // 渲染后就再没更新过。后果之一是：切页时数据尚未到达，节点列表渲染成空状态，
    // 之后即便 fleet 已有数据，表格也永远空着（实测：fleet 3 台、表格 0 行）。
    //
    // 之所以不改成调 render()：render() 在 twin 页会重建 #slot-content，把三维视图的
    // iframe 一起销毁重建。updatePageInPlace() 只更新 <tbody> 与遥测面板，不碰 iframe。
    updatePageInPlace();
    return;
  }
  if (document.activeElement?.matches("input, textarea, select, [data-timeline-key]")) return;
  render();
}

window.addEventListener("message", (event) => {
  const frame = document.getElementById("simulation-frame");
  if (!frame?.contentWindow || event.source !== frame.contentWindow) return;
  if (event.origin !== simulationOrigin()) return;

  // 三维视图内改选了载具（点选实体或下拉框）→ 跟随更新主控制台的选中项。
  // 用 fromSimulation:true 避免回推形成环路。
  if (event.data?.type === "uav-swarm/selection-changed") {
    const nodeId = event.data.payload?.nodeId;
    if (typeof nodeId === "string" && nodeId) {
      selectVehicle(nodeId, { fromSimulation: true });
    }
    return;
  }

  if (event.data?.type !== "uav-swarm/simulation-ready") return;
  if (!window.SwarmConsoleModel.validateSimulationReadyMessage(event.data)) {
    state.simulationReady = false;
    state.simulationContractError = "三维消息契约不兼容，要求 parent-snapshot 1.0";
    renderRuntimeUpdate();
    return;
  }
  state.simulationReady = true;
  state.simulationContractError = null;
  if (fixturePlanPreviewPage()) {
    fixturePreviewFrame = frame;
    syncFixturePlanPreview();
  }
  const note = document.querySelector(".simulation-frame-note");
  if (note) note.textContent = builtInDemo ? "DEMO · Cesium 内置场景"
    : `Runtime 快照由主控制台统一推送；${simulationAlignmentStatus().label}`;
  const headingBadge = document.querySelector(".twin-panel .badge");
  if (headingBadge) {
    headingBadge.textContent = "CONNECTED";
    headingBadge.className = "badge green";
  }
  postVehicleSnapshot();
});

setInterval(async () => {
  if (builtInDemo) return;
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
  if (builtInDemo) return;
  if (state.apiStatus !== "live") return;
  await syncRuntimeEvents({ notifyFailure: false });
  renderRuntimeUpdate();
}, 5000);

if (stageMode && dashboard) setInterval(() => {
  if (stagePlayback.startedAt !== null) renderStage();
}, 1000);
