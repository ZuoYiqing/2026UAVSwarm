import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

const BASE_DRONES = [
  { id: "UAV-01", x: 20, y: 72, color: "#6ee7ff" },
  { id: "UAV-02", x: 30, y: 54, color: "#7aa2ff" },
  { id: "UAV-03", x: 46, y: 66, color: "#31d0aa" },
  { id: "UAV-04", x: 60, y: 45, color: "#ffcd57" },
  { id: "UAV-05", x: 72, y: 62, color: "#d5a3ff" },
];

const SCENARIOS = {
  ALLOW: {
    title: "Scenario A · ALLOW",
    badge: "ok",
    command: "submit-action takeoff --adapter fake",
    policy: {
      decision_code: "allow",
      primary_reason_code: null,
      effective_scope: "self_only",
      policy_trace_id: "pt-allow-001",
    },
    result: {
      status: "accepted",
      code: "exec_ok",
      adapter: "fake",
      backend_mode: "stub",
      replay: "policy_decision_event + action_result persisted",
    },
    drones: BASE_DRONES.map((d, i) => ({ ...d, y: d.y - (i % 2 ? 7 : 11), state: "hover" })),
    timeline: [
      ["00:00", "action_request", "takeoff, mission=demo-allow"],
      ["00:01", "policy_decision_event", "decision_code=allow, scope=self_only"],
      ["00:02", "adapter(fake)", "exec_ok"],
      ["00:03", "action_result", "status=accepted"],
      ["00:04", "replay", "last 2 events loaded"],
    ],
  },
  DENY: {
    title: "Scenario B · DENY",
    badge: "deny",
    command: "submit-action goto --risk-hint 5 --demo-link-state lost",
    policy: {
      decision_code: "deny",
      primary_reason_code: "REASON_CODE_RISK_LEVEL_EXCEEDED",
      effective_scope: "self_only",
      policy_trace_id: "pt-deny-001",
    },
    result: {
      status: "blocked",
      code: "REASON_CODE_RISK_LEVEL_EXCEEDED",
      adapter: "(not executed)",
      backend_mode: "n/a",
      replay: "only policy_decision_event + blocked result",
    },
    drones: BASE_DRONES.map((d) => ({ ...d, state: "denied" })),
    timeline: [
      ["00:00", "action_request", "goto, risk_hint=5"],
      ["00:01", "policy_decision_event", "decision_code=deny"],
      ["00:02", "adapter", "skipped (policy blocked)"],
      ["00:03", "action_result", "status=blocked"],
      ["00:04", "replay", "deny path verified"],
    ],
  },
  CONFIRM: {
    title: "Scenario C · REQUIRE_CONFIRM",
    badge: "warn",
    command: "submit-action goto --require-confirm",
    policy: {
      decision_code: "REQUIRE_CONFIRM",
      primary_reason_code: "REASON_CODE_CONFIRMATION_REQUIRED",
      effective_scope: "self_only",
      policy_trace_id: "pt-confirm-001",
    },
    result: {
      status: "waiting_confirmation",
      code: "REASON_CODE_CONFIRMATION_REQUIRED",
      adapter: "(pending confirm)",
      backend_mode: "sitl(stub)",
      replay: "decision + waiting state persisted",
    },
    drones: BASE_DRONES.map((d, i) => ({ ...d, x: d.x + (i % 2 ? 2 : -2), state: "hover" })),
    timeline: [
      ["00:00", "action_request", "goto + require_confirm"],
      ["00:01", "policy_decision_event", "decision_code=REQUIRE_CONFIRM"],
      ["00:02", "adapter", "pending, not executed"],
      ["00:03", "action_result", "status=waiting_confirmation"],
      ["00:04", "replay", "confirm flow visible"],
    ],
  },
};

function App() {
  const [sceneKey, setSceneKey] = useState("ALLOW");
  const scene = useMemo(() => SCENARIOS[sceneKey], [sceneKey]);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>UAV Runtime Demo Shell</h1>
          <div className="sub">Mission/Action → Policy → Adapter → Result → Replay (visual mock for leadership demo)</div>
        </div>
        <span className={`badge ${scene.badge}`}>{scene.title}</span>
      </header>

      <main className="main">
        <section className="panel map-wrap">
          <p className="map-title">Left · 2D Fleet Situation</p>
          <div className="map">
            {scene.drones.map((d) => (
              <div
                key={d.id}
                className={`drone ${d.state}`}
                data-id={d.id}
                style={{ left: `${d.x}%`, top: `${d.y}%`, background: d.color }}
              />
            ))}
          </div>
        </section>

        <aside className="panel right">
          <div className="card">
            <h3>Scenario Switch</h3>
            <div className="controls">
              {Object.keys(SCENARIOS).map((k) => (
                <button key={k} className={k === sceneKey ? "active" : ""} onClick={() => setSceneKey(k)}>
                  {SCENARIOS[k].title.split("·")[1].trim()}
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Command Input (Mock)</h3>
            <pre>{scene.command}</pre>
          </div>

          <div className="card">
            <h3>Policy Decision Event</h3>
            <pre>{JSON.stringify(scene.policy, null, 2)}</pre>
          </div>

          <div className="card">
            <h3>Action Result / Replay Summary</h3>
            <pre>{JSON.stringify(scene.result, null, 2)}</pre>
          </div>
        </aside>
      </main>

      <section className="panel timeline">
        <h3>Bottom · Event Timeline</h3>
        {scene.timeline.map((row, idx) => (
          <div key={idx} className="line">
            <div>{row[0]}</div>
            <div className="k">{row[1]}</div>
            <div>{row[2]}</div>
          </div>
        ))}
      </section>

      <div className="footer">Demo shell only · no real PX4/MAVLink backend in this mode</div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
