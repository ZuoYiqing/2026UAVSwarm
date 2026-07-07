# Runtime Console Contract v0.1

## 1. Purpose and design judgment

The swarm-console frontend has grown beyond a command-result viewer: it now has overview, planning, 3D situational awareness, vehicle detail, Agent Runtime, Policy Gate, Skills, Adapter/Backend, simulation, hardware assets, and Audit/Replay pages. The backend already has Capability Registry, Policy Gate, Mission Runtime, Agent Planner, PX4 SITL smoke actions, Audit/Replay, telemetry normalization, and a local HTTP bridge. Runtime Console Contract v0.1 defines the stable data language between those backend capabilities and the console.

This contract is needed now because each page otherwise invents its own JSON shape, making the UI brittle and forcing every backend feature to couple directly to a specific widget. A stable contract lets the backend evolve internally while the frontend consumes consistent view models.

Runtime internal objects are not the same as frontend View Models:

- Runtime objects preserve execution truth: policy decisions, action requests, backend sessions, adapter results, audit records, MAVLink telemetry, and planner IR.
- View Models are presentation-safe summaries: they can combine multiple runtime records, derive UI-friendly labels, and include clearly marked default/mock values while preserving stable field semantics.

In v0.1, some fields may be `derived`, `default`, or `mock` because the backend does not yet produce every dashboard metric. The field names and meanings must still be stable so frontend code does not need to change when a field moves from mock to real data.

`EventEnvelope` is the base of Audit, Replay, and Timeline because those surfaces need one chronological message standard across policy, planner, adapter, backend, telemetry, health, faults, and operator approval. Snapshot, telemetry, skill, plan, and action_result view models also need a shared standard so the console can correlate what happened, where it happened, which mission/node was involved, and which trace/session links events together.

Runtime Console Contract v0.1 does not require WebSocket. The first implementation should expose latest snapshot APIs because they are easier to test, easier to replay, and safer for local development. WebSocket/SSE can be added later after the message standard is stable.

## 2. Compatibility with current frontend prototype

The frontend prototype is expected to use `http://127.0.0.1:8765/api` as the Runtime API base URL. The current bridge already exposes these interfaces:

- `GET /api/health`
- `POST /api/backend/check`
- `POST /api/actions/smoke-takeoff`
- `POST /api/actions/land`
- `POST /api/planner/plan-mission`
- `GET /api/replay?n=20`
- `GET /api/capabilities`

Runtime Console Contract v0.1 keeps those existing routes stable and adds view-model-oriented read APIs:

- `GET /api/snapshot`
- `GET /api/runtime/pipeline`
- `GET /api/telemetry/latest`
- `GET /api/skills`
- `GET /api/actions/recent?n=20`
- `GET /api/policy/decisions?n=20`
- `GET /api/events?n=50`

The current routes remain command/planning primitives. The new routes are console display contracts built from runtime state, audit/replay events, capability metadata, telemetry snapshots, and safe defaults.

## 3. Source metadata convention

Any field that may be derived, mocked, or defaulted should carry source semantics either at the object level or the field group level:

```json
{
  "source": "runtime|audit|telemetry|capability_registry|policy|planner|derived|mock|default",
  "stale": false,
  "updated_at": "2026-07-07T00:00:00Z"
}
```

This prevents the console from presenting mock/default values as operational truth.

## 4. EventEnvelope

`EventEnvelope` is the unified message record for Audit, Replay, Timeline, and later streaming.

```json
{
  "event_id": "evt_01HX...",
  "trace_id": "trc_8f3a2c91",
  "mission_id": "mission-demo",
  "session_id": "sess_7b1e9a2c",
  "parent_event_id": null,
  "event_type": "policy_decision_event",
  "severity": "info",
  "source": "policy_gate",
  "node_id": "UAV-01",
  "timestamp": "2026-07-07T00:00:00Z",
  "summary": "Policy allowed takeoff",
  "payload": {}
}
```

### Fields

| Field | Meaning |
| --- | --- |
| `event_id` | Unique event identifier. |
| `trace_id` | Correlation ID across plan/action/policy/adapter/audit. |
| `mission_id` | Mission or smoke-run identifier when available. |
| `session_id` | Runtime or agent session identifier when available. |
| `parent_event_id` | Optional parent for step/result chains. |
| `event_type` | Stable event classification. |
| `severity` | One of `debug`, `info`, `warning`, `error`, `critical`. |
| `source` | Producing subsystem: runtime, planner, policy, adapter, backend, telemetry, operator, replay. |
| `node_id` | Vehicle/node identifier when applicable. |
| `timestamp` | UTC ISO-8601 timestamp. |
| `summary` | Human-readable one-line description. |
| `payload` | Event-specific structured payload. |

### Suggested event_type values

- `mission_request`
- `agent_plan_created`
- `agent_plan_validated`
- `agent_plan_approved`
- `agent_plan_execution_started`
- `agent_plan_step_started`
- `policy_decision_event`
- `adapter_execution_started`
- `adapter_execution_result`
- `backend_probe_result`
- `action_request`
- `action_result`
- `telemetry_sample`
- `health_status`
- `fault_event`
- `link_warning`
- `operator_confirm_required`
- `operator_approval_event`
- `replay_marker`

## 5. RuntimeSnapshot

`RuntimeSnapshot` supports overview dashboard, 3D situation summary, and status bar.

```json
{
  "snapshot_id": "snap_01HX...",
  "timestamp": "2026-07-07T00:00:00Z",
  "runtime_status": {},
  "fleet_summary": {},
  "nodes": [],
  "missions": [],
  "recent_events": []
}
```

### runtime_status

```json
{
  "mode": "local_dev",
  "profile": "standard",
  "api_status": "ok",
  "backend_mode": "sitl",
  "active_backend": "px4_sitl",
  "policy_profile": "standard",
  "simulation_status": "ready"
}
```

### fleet_summary

```json
{
  "online_nodes": 1,
  "total_nodes": 1,
  "active_missions": 0,
  "policy_blocks_24h": 0,
  "link_warnings": 0,
  "success_rate_24h": 1.0
}
```

### Field sources

- `api_status`: real value from `GET /api/health`.
- `backend_mode`, `active_backend`: real value from backend/action requests or defaults.
- `simulation_status`: derived from backend check / telemetry / smoke result.
- `fleet_summary`: initially derived/default from replay, telemetry, and action result history.
- `nodes`: from `TelemetryLatest` plus defaults.
- `recent_events`: from `EventEnvelope` values converted from audit/replay.

## 6. NodeState

`NodeState` supports 3D situation, vehicle detail, and telemetry cards.

```json
{
  "node_id": "UAV-01",
  "node_type": "quadrotor",
  "status": "online",
  "backend": "px4_sitl",
  "current_task": "idle",
  "battery_percent": null,
  "link_quality": "unknown",
  "rssi_dbm": null,
  "position": {
    "lat": null,
    "lon": null,
    "alt_m": 0.0,
    "agl_m": 0.0
  },
  "attitude": {
    "roll_deg": 0.0,
    "pitch_deg": 0.0,
    "yaw_deg": 0.0
  },
  "velocity": {
    "ground_speed_mps": 0.0,
    "vertical_speed_mps": 0.0
  },
  "health": {
    "score": 1.0,
    "battery": "unknown",
    "gps": "unknown",
    "motor": "unknown",
    "camera": "unknown",
    "link": "unknown"
  },
  "capabilities": [],
  "last_seen": "2026-07-07T00:00:00Z"
}
```

Position/attitude/velocity should be derived from PX4 telemetry where available. PX4 `LOCAL_POSITION_NED.z` must be exposed as positive altitude only after conversion to `alt_m` / `agl_m`; raw positive-down values belong in lower-level telemetry payloads, not the general `NodeState.position` view.

## 7. SkillManifest

`SkillManifest` supports the Skills capability library. It is a console-safe projection of Capability Registry metadata, not an execution grant.

```json
{
  "skill_id": "skill_takeoff",
  "action_type": "takeoff",
  "display_name": "Takeoff",
  "description": "Arm and climb in SITL/runtime-controlled flow",
  "domain": "flight",
  "skill_group": "flight_core",
  "risk_level": 2,
  "enabled": true,
  "supported_backends": ["px4_sitl"],
  "supported_adapters": ["mavlink", "fake"],
  "input_schema": {},
  "output_schema": {},
  "usage": {
    "total_calls": 0,
    "success_rate": null,
    "avg_duration_s": null,
    "last_used_at": null
  },
  "safety": {
    "requires_policy_check": true,
    "requires_operator_confirm": false,
    "dangerous": false,
    "sitl_only": true
  }
}
```

Dangerous actions should be hidden by default or displayed as forbidden metadata only; they must not become executable because they appear in the Skills UI.

## 8. MissionPlanView

`MissionPlanView` supports the planning page. It is derived from `MissionPlan` / `PlanResult`, but includes UI fields for graph layout and summary estimates.

```json
{
  "plan_id": "plan_01HX...",
  "mission_type": "inspection_snapshot",
  "status": "validated",
  "steps": [],
  "graph": {},
  "summary": {
    "estimated_duration_min": null,
    "estimated_distance_km": null,
    "estimated_energy_percent": null,
    "risk_level": 2,
    "requires_operator_confirm": false
  }
}
```

### step

```json
{
  "step_id": "step_1",
  "action_type": "takeoff",
  "display_name": "Takeoff",
  "status": "ready",
  "expected_adapter": "mavlink",
  "policy_precheck": {},
  "estimated_duration_s": null,
  "estimated_energy_percent": null,
  "graph": {}
}
```

Estimates can be default/derived in v0.1. Policy precheck is only planning-time guidance; execution-time Runtime / Policy Gate authorization is still required.

## 9. ActionResultView

`ActionResultView` supports Adapter/Backend, recent actions, and Audit details.

```json
{
  "action_id": "act_01HX...",
  "trace_id": "trc_8f3a2c91",
  "request_id": "req_01HX...",
  "mission_id": "mission-px4-smoke-takeoff",
  "node_id": "UAV-01",
  "action_type": "takeoff",
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "adapter": "mavlink",
  "status": "completed",
  "result": "pass",
  "started_at": "2026-07-07T00:00:00Z",
  "finished_at": "2026-07-07T00:00:05Z",
  "duration_ms": 5000,
  "policy_decision": {},
  "command_results": [],
  "observations": {},
  "cleanup": {},
  "failure_reason": null
}
```

### command_result

```json
{
  "command": "MAV_CMD_NAV_TAKEOFF",
  "accepted": true,
  "result": 0,
  "result_name": "MAV_RESULT_ACCEPTED",
  "timeout": false
}
```

ACK accepted means the command was accepted by PX4; it does not prove physical completion. Completion evidence belongs in `observations`, such as max altitude and threshold reached.

## 10. TelemetryLatest

`TelemetryLatest` supports telemetry cards without requiring streaming.

```json
{
  "timestamp": "2026-07-07T00:00:00Z",
  "backend": "px4_sitl",
  "nodes": [
    {
      "node_id": "UAV-01",
      "battery_percent": null,
      "altitude_m": 0.0,
      "ground_speed_mps": 0.0,
      "rssi_dbm": null,
      "temperature_c": null,
      "attitude": {
        "roll_deg": 0.0,
        "pitch_deg": 0.0,
        "yaw_deg": 0.0
      }
    }
  ]
}
```

Telemetry may be sourced from the PX4 telemetry bridge, recent action observations, or a default value if no sample has arrived. The response must identify the source so the UI can label stale/default data.

## 11. Recommended HTTP API v0.1 route plan

| Route | Purpose | Initial source |
| --- | --- | --- |
| `GET /api/snapshot` | Overview, 3D summary, status bar | derived/default from health, replay, telemetry, capabilities |
| `GET /api/runtime/pipeline` | Agent Runtime pipeline cards | derived from audit/replay and plan lifecycle events |
| `GET /api/telemetry/latest` | Telemetry display | real PX4 telemetry when collector exists; otherwise derived/default |
| `GET /api/skills` | Skills library | real Capability Registry projection plus derived usage metrics |
| `GET /api/actions/recent?n=20` | Recent action list | real audit/replay action events |
| `GET /api/policy/decisions?n=20` | Policy Gate page | real audit/replay policy events |
| `GET /api/events?n=50` | Unified event timeline | real audit/replay converted to EventEnvelope |
| `GET /api/capabilities` | Existing capability inventory | real Capability Registry |
| `POST /api/planner/plan-mission` | Existing plan-only command | real Template Agent Planner |
| `POST /api/backend/check` | Existing backend readiness | real PX4 SITL backend check |
| `POST /api/actions/smoke-takeoff` | Existing SITL smoke action | real Runtime/Policy/PX4 SITL only |
| `POST /api/actions/land` | Existing SITL land action | real Runtime/Policy/PX4 SITL only |

Routes that can start derived/mock/default in v0.1: `/api/snapshot`, `/api/runtime/pipeline`, `/api/telemetry/latest`, `/api/skills` usage metrics. Routes that must remain real runtime-backed: backend check, smoke-takeoff, land, plan-mission, capabilities, replay-derived actions/events/policy decisions.

## 12. Security boundary

- Frontend display data is not execution authorization.
- Every real action must still go through Runtime / Policy Gate.
- HTTP API must not accept arbitrary shell commands.
- `smoke-takeoff` and `land` remain SITL-only.
- Dangerous actions are hidden by default or marked as forbidden metadata.
- Telemetry and snapshot routes may expose derived/mock/default values, but the source must be visible.
- No real aircraft integration in v0.1.
- No public deployment in v0.1.
- No WebSocket, database, authentication system, GUI rewrite, or runtime core rewrite in v0.1.

## 13. Later implementation guidance

Recommended code structure:

- `src/uav_runtime/http/contracts.py` or `src/uav_runtime/console_api/contracts.py`
- `to_event_envelope(...)`
- `to_runtime_snapshot_view(...)`
- `to_node_state_view(...)`
- `to_skill_manifest_view(...)`
- `to_mission_plan_view(...)`
- `to_action_result_view(...)`
- `to_telemetry_latest_view(...)`

DTOs should be separated from runtime internal objects. Runtime objects should remain authoritative for execution and audit; DTOs should be safe projections for the console.

Each View Model should have a docstring that explains:

- which frontend page consumes it;
- which runtime source fields are authoritative;
- which fields are derived/mock/default in v0.1;
- whether the view is display-only or can trigger follow-up actions;
- which security boundary prevents UI display from becoming execution authorization.

Conversion function comments should explain field source and safety semantics, not restate the code line by line.

## 14. Non-goals

- No WebSocket in this phase.
- No database in this phase.
- No authentication system in this phase.
- No real aircraft in this phase.
- No real multi-vehicle control in this phase.
- No GUI rewrite in this phase.
- No frontend changes in this phase.
- No major runtime core rewrite in this phase.
