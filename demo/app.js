import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);

const SCENE_ORDER = ["ALLOW", "DENY", "REQUIRE_CONFIRM", "SITL_WIRING"];
const AUTO_DWELL_MS = 7200;

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
    title: "ALLOW · 正常放行",
    status: "READY",
    badge: "ok",
    missionAction: { mission_id: "mission-alpha", action_type: "takeoff", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "allow", primary_reason_code: "(null)", effective_scope: "self_only", policy_trace_id: "pt-allow-001" },
    result: { adapter: "fake", backend_mode: "stub", code: "exec_ok", status: "accepted", replay: "policy_decision_event + action_result persisted" },
    summary: {
      policy: "策略放行：指令满足当前风险与作用域约束。",
      result: "执行面正常返回 accepted，控制面闭环贯通。",
      replay: "Replay 可回放本次决策与结果链路（可审计）。",
    },
    mapHint: "Target activated, trajectory highlighted, UAVs moving upward.",
    targetState: "active",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i + 1) * 4, y: d.y - (i % 2 ? 16 : 10), state: "takeoff" })),
    paths: [
      { from: [18, 70], to: [28, 56], cls: "path allow" },
      { from: [27, 58], to: [39, 45], cls: "path allow" },
      { from: [39, 66], to: [51, 52], cls: "path allow" },
      { from: [52, 54], to: [67, 38], cls: "path allow" },
    ],
    timeline: [
      ["00:00", "mission_request", "mission-alpha submitted", "neutral"],
      ["00:01", "action_request", "takeoff (flight_core)", "neutral"],
      ["00:02", "policy_decision_event", "decision=allow, scope=self_only", "ok"],
      ["00:03", "action_result", "accepted, code=exec_ok", "ok"],
      ["00:04", "replay", "events replayable & auditable", "replay"],
    ],
  },
  DENY: {
    title: "DENY · 高风险拒绝",
    status: "BLOCKED",
    badge: "deny",
    missionAction: { mission_id: "mission-bravo", action_type: "goto", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "deny", primary_reason_code: "REASON_CODE_RISK_LEVEL_EXCEEDED", effective_scope: "self_only", policy_trace_id: "pt-deny-001" },
    result: { adapter: "(skipped)", backend_mode: "n/a", code: "REASON_CODE_RISK_LEVEL_EXCEEDED", status: "blocked", replay: "deny path persisted" },
    summary: {
      policy: "策略拒绝：风险超阈值，阻断执行。",
      result: "Adapter 未执行，避免进入危险动作。",
      replay: "拒绝链路完整留痕，可用于复盘。",
    },
    mapHint: "Risk zone warning; target locked; UAVs hold position.",
    targetState: "locked",
    drones: BASE_DRONES.map((d) => ({ ...d, state: "hold" })),
    paths: [{ from: [39, 66], to: [82, 22], cls: "path denied" }],
    timeline: [
      ["00:00", "mission_request", "mission-bravo submitted", "neutral"],
      ["00:01", "action_request", "goto target-zone", "neutral"],
      ["00:02", "policy_decision_event", "decision=deny, reason=risk_exceeded", "deny"],
      ["00:03", "action_result", "blocked", "deny"],
      ["00:04", "replay", "deny decision replayable", "replay"],
    ],
  },
  REQUIRE_CONFIRM: {
    title: "REQUIRE_CONFIRM · 等待确认",
    status: "WAIT_CONFIRM",
    badge: "warn",
    missionAction: { mission_id: "mission-charlie", action_type: "goto", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "REQUIRE_CONFIRM", primary_reason_code: "REASON_CODE_CONFIRMATION_REQUIRED", effective_scope: "self_only", policy_trace_id: "pt-confirm-001" },
    result: { adapter: "(pending)", backend_mode: "sitl(stub)", code: "REASON_CODE_CONFIRMATION_REQUIRED", status: "waiting_confirmation", replay: "pending state persisted" },
    summary: {
      policy: "策略要求确认：命中人工确认规则。",
      result: "执行层暂停，等待确认指令。",
      replay: "确认前后状态可回放审计。",
    },
    mapHint: "Fleet paused with confirmation markers.",
    targetState: "pending",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i % 2 ? 3 : -2), y: d.y + (i % 2 ? -4 : 2), state: "confirm" })),
    paths: [
      { from: [27, 58], to: [56, 36], cls: "path pending" },
      { from: [39, 66], to: [63, 30], cls: "path pending" },
    ],
    timeline: [
      ["00:00", "mission_request", "mission-charlie submitted", "neutral"],
      ["00:01", "action_request", "goto + require_confirm", "neutral"],
      ["00:02", "policy_decision_event", "decision=REQUIRE_CONFIRM", "warn"],
      ["00:03", "action_result", "waiting_confirmation", "warn"],
      ["00:04", "replay", "confirm workflow replayable", "replay"],
    ],
  },
  SITL_WIRING: {
    title: "SITL_WIRING · 接入位已预留",
    status: "SITL_PENDING",
    badge: "sitl",
    missionAction: { mission_id: "mission-delta", action_type: "takeoff", requested_scope: "self_only", priority_hint: 50 },
    policy: { decision_code: "allow", primary_reason_code: "(null)", effective_scope: "self_only", policy_trace_id: "pt-sitl-001" },
    result: { adapter: "mavlink", backend_mode: "sitl", code: "smoke_not_connected", status: "rejected", replay: "backend seam verified" },
    summary: {
      policy: "策略层已放行，控制面闭环正常。",
      result: "执行路径已到 backend 接入位，当前真实后端未连接。",
      replay: "SITL wiring 状态可追踪，可用于后续真实接入验证。",
    },
    mapHint: "Dashed backend path shown: prepared but not connected.",
    targetState: "sitl",
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i % 2 ? 1 : -1), y: d.y - (i % 2 ? 2 : 1), state: "sitl" })),
    paths: [{ from: [18, 70], to: [30, 50], cls: "path sitl" }],
    timeline: [
      ["00:00", "mission_request", "mission-delta submitted", "neutral"],
      ["00:01", "action_request", "takeoff via adapter=mavlink", "neutral"],
      ["00:02", "policy_decision_event", "decision=allow", "ok"],
      ["00:03", "action_result", "code=smoke_not_connected", "sitl"],
      ["00:04", "replay", "SITL backend path prepared", "replay"],
    ],
  },
};

const STATUS_CLASS = { READY: "ok", BLOCKED: "deny", WAIT_CONFIRM: "warn", SITL_PENDING: "sitl" };

function ValueLine({ k, v, strong = false }) {
  return html`<div className="kv"><span>${k}</span><span className=${strong ? "value strong" : "value"}>${v}</span></div>`;
}

function App() {
  const [sceneKey, setSceneKey] = useState("ALLOW");
  const [autoPlay, setAutoPlay] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [clock, setClock] = useState(new Date());

  const scene = useMemo(() => SCENARIOS[sceneKey], [sceneKey]);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    setStepIndex(0);
    const timer = setInterval(() => {
      setStepIndex((v) => (v + 1 >= scene.timeline.length ? scene.timeline.length - 1 : v + 1));
    }, 1200);
    return () => clearInterval(timer);
  }, [sceneKey]);

  useEffect(() => {
    if (!autoPlay) return;
    const timer = setInterval(() => {
      setSceneKey((prev) => {
        const idx = SCENE_ORDER.indexOf(prev);
        return SCENE_ORDER[(idx + 1) % SCENE_ORDER.length];
      });
    }, AUTO_DWELL_MS);
    return () => clearInterval(timer);
  }, [autoPlay]);

  const badgeClass = STATUS_CLASS[scene.status] || "warn";

  return html`
    <div className="app">
      <header className="topbar panel">
        <div className="brand">
          <h1>2026UAVSwarm Demo Shell</h1>
          <p>Control-plane loop connected · Policy & Execution decoupled</p>
        </div>
        <div className="top-metrics">
          <span className="metric"><label>Scene</label><b>${scene.title}</b></span>
          <span className="metric"><label>Mission</label><b>${scene.missionAction.mission_id}</b></span>
          <span className="metric"><label>Action</label><b>${scene.missionAction.action_type}</b></span>
          <span className="metric"><label>Adapter</label><b>${scene.result.adapter}</b></span>
          <span className="metric"><label>Backend</label><b>${scene.result.backend_mode}</b></span>
          <span className=${`status ${badgeClass}`}>${scene.status}</span>
          <span className="lamp"></span>
          <span className="metric clock">${clock.toLocaleTimeString()}</span>
        </div>
      </header>

      <main className="main">
        <section className="panel map-panel">
          <div className="panel-title">
            <h2>2D Fleet Situation / 集群态势</h2>
            <div className="hint">${scene.mapHint}</div>
          </div>

          <div className="tag-row">
            <span className="tag">控制面闭环已打通</span>
            <span className="tag">策略裁决与执行面解耦</span>
            ${sceneKey === "SITL_WIRING" ? html`<span className="tag sitl">SITL backend path prepared</span>` : null}
          </div>

          <div className="map">
            <div className="ground-station" style=${{ left: `${COMMON.groundStation.x}%`, top: `${COMMON.groundStation.y}%` }}>GS</div>
            <div className=${`target ${scene.targetState}`} style=${{ left: `${COMMON.targetPoint.x}%`, top: `${COMMON.targetPoint.y}%` }}>
              ${scene.targetState === "locked" ? "TARGET LOCKED" : "TARGET"}
            </div>

            <div
              className=${`zone ${sceneKey === "DENY" ? "danger active" : "danger"}`}
              style=${{ left: `${COMMON.noFlyZone.x}%`, top: `${COMMON.noFlyZone.y}%`, width: `${COMMON.noFlyZone.r * 2}%`, height: `${COMMON.noFlyZone.r * 2}%` }}
            >NO-FLY</div>

            ${scene.paths.map(
              (p, idx) => html`<svg key=${idx} className="path-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
                <line className=${p.cls} x1=${p.from[0]} y1=${p.from[1]} x2=${p.to[0]} y2=${p.to[1]} />
              </svg>`
            )}

            ${scene.drones.map(
              (d) => html`<div key=${d.id} className=${`drone ${d.state}`} style=${{ left: `${d.x}%`, top: `${d.y}%`, background: d.color }}>
                <span>${d.id}</span>
              </div>`
            )}

            ${sceneKey === "REQUIRE_CONFIRM" ? html`<div className="confirm-banner">WAITING FOR OPERATOR CONFIRMATION</div>` : null}
            ${sceneKey === "SITL_WIRING"
              ? html`<div className="sitl-banner">SITL backend path prepared · real backend not connected</div>`
              : null}
          </div>
        </section>

        <aside className="panel side">
          <div className="controls-row">
            ${SCENE_ORDER.map((k) => html`<button className=${sceneKey === k ? "active" : ""} onClick=${() => setSceneKey(k)}>${k}</button>`)}
          </div>
          <div className="controls-row">
            <button className=${autoPlay ? "active glow" : ""} onClick=${() => setAutoPlay((v) => !v)}>${autoPlay ? "Stop Auto Demo" : "Auto Demo / Play All"}</button>
            <button onClick=${() => setSceneKey("ALLOW")}>Restart Demo</button>
          </div>

          <section className="card">
            <h3>Mission / Action</h3>
            <${ValueLine} k="mission_id" v=${scene.missionAction.mission_id} />
            <${ValueLine} k="action_type" v=${scene.missionAction.action_type} strong=${true} />
            <${ValueLine} k="priority_hint" v=${scene.missionAction.priority_hint} />
            <${ValueLine} k="requested_scope" v=${scene.missionAction.requested_scope} />
          </section>

          <section className="card">
            <h3>Policy Decision / 策略决策</h3>
            <${ValueLine} k="decision_code" v=${scene.policy.decision_code} strong=${true} />
            <${ValueLine} k="primary_reason_code" v=${scene.policy.primary_reason_code} />
            <${ValueLine} k="effective_scope" v=${scene.policy.effective_scope} />
            <${ValueLine} k="policy_trace_id" v=${scene.policy.policy_trace_id} />
            <p className="summary">${scene.summary.policy}</p>
          </section>

          <section className="card">
            <h3>Adapter / Backend / Result</h3>
            <${ValueLine} k="adapter" v=${scene.result.adapter} strong=${true} />
            <${ValueLine} k="backend_mode" v=${scene.result.backend_mode} />
            <${ValueLine} k="result.code" v=${scene.result.code} strong=${true} />
            <${ValueLine} k="result.status" v=${scene.result.status} />
            <p className="summary">${scene.summary.result}</p>
          </section>

          <section className="card">
            <h3>Replay & Audit / 回放审计</h3>
            <p>${scene.result.replay}</p>
            <p className="summary">${scene.summary.replay}</p>
          </section>
        </aside>
      </main>

      <section className="panel timeline-wrap">
        <h2>Event Timeline</h2>
        ${scene.timeline.map(
          (ev, idx) => html`<div className=${`line ${idx <= stepIndex ? "active" : ""} ${idx === stepIndex ? "cursor" : ""} ${ev[3]}`} key=${idx}>
            <span className="dot"></span>
            <span className="ts">${ev[0]}</span>
            <span className="ev">${ev[1]}</span>
            <span className="desc">${ev[2]}</span>
          </div>`
        )}
      </section>

      <footer className="footer">Demo mode only · no real PX4/MAVLink/SITL connection in this shell</footer>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
