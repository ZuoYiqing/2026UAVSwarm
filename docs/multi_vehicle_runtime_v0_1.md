# Multi-Vehicle Runtime Foundation v0.1

## Scope and identity

`node_id` is the Runtime-wide identity used by HTTP, Agent, Policy, Audit and
frontend projections. MAVLink `system_id` and UDP endpoints are deployment
attributes and must never replace it. The registry owns this mapping:

```text
node_id -> VehicleConfig -> independent MAVLink session/command lock
        -> PX4TelemetrySnapshot -> VehicleRuntimeState -> HTTP projections
```

This release establishes isolation and deterministic assignment only. It does
not implement formation control, route planning, obstacle avoidance, LLM/RL
coordination, WebSocket/SSE, databases, payload control or real-aircraft use.

## Configuration and lifecycle

`config/vehicles.sitl.json` is the deployment fact source. UAV-01 retains the
validated single-node endpoints. UAV-02/03 are deliberately disabled with empty
endpoints until the PX4 owner supplies real values; the Runtime does not guess
ports. Each enabled node receives its own `MavlinkBackendSession`, telemetry
collector, command lock, target IDs, timestamps and fault state. A heartbeat
timeout marks only that node `stale/offline`; it preserves the last pose. Only
explicit `unregister_vehicle` removes an ID from a subsequent full snapshot.

Command and telemetry receive sockets must not compete for one UDP listener.
Configure `endpoint` for commands and `telemetry_endpoint` for the managed
collector as independent PX4 outputs. Registry start/stop owns collectors; HTTP
GET handlers only read cached state.

Legacy requests without `node_id` use a node only when `default_node_id` is
explicitly configured. Responses identify `node_selection=default`. Without a
default, the Runtime returns `400 ambiguous_node_request`; it never selects the
first array entry.

## HTTP contracts

### `GET /api/vehicles`

Returns registered configuration identity and connection/freshness state. A
disabled or offline node remains visible. Example fields include `scene_id`,
`node_id`, `backend`, `endpoint`, `system_id`, `connected`, `stale`, and latest
heartbeat/telemetry timestamps.

```json
{
  "version": "1.0",
  "scene_id": "simple_recon_v0_1",
  "vehicles": [{"node_id": "UAV-01", "system_id": 1, "connected": false, "stale": true}],
  "source": "vehicle_registry"
}
```

### `GET /api/telemetry/latest?node_id=UAV-01`

Returns only the requested node. Unknown IDs return `404 unknown_node`. Missing
telemetry returns a stable unavailable response. Positions are explicitly NED:
PX4 z is positive-down, and display altitude remains
`max(0.0, -z_down_m)`. Fleet polling without `node_id` returns all cached nodes.

```json
{
  "version": "1.0",
  "status": "unavailable",
  "fresh": false,
  "nodes": [],
  "reason": "telemetry_not_started",
  "source": "vehicle_registry"
}
```

### `GET /api/vehicle-snapshot`

This is a read-only projection of registry state, not the state owner or an
execution authorization. It uses `version=1.0`, `full_state=true`,
`source.kind=simulation`, `frame.type=NED`, stable node IDs and the configured
`scene_id`. Offline/stale vehicles with prior telemetry remain in the feed;
unregistered vehicles disappear. Polling at 5–10 Hz is supported; streaming is
future work. The Runtime does not modify the Cesium contract.

Registered nodes without telemetry still appear with a stable ID,
`connected=false`, stale freshness and no invented pose. This is essential for
`full_state=true`: absence means removed, while stale means temporarily offline.

```json
{
  "version": "1.0",
  "full_state": true,
  "source": {"id": "runtime-fusion", "kind": "simulation", "label": "PX4 SITL / Runtime"},
  "scene_id": "simple_recon_v0_1",
  "frame": {"type": "NED"},
  "vehicles": [
    {"id": "UAV-01", "vehicle_type": "multirotor", "connected": true},
    {"id": "UAV-02", "vehicle_type": "multirotor", "connected": false},
    {"id": "UAV-03", "vehicle_type": "multirotor", "connected": false}
  ]
}
```

### Node-specific actions

`POST /api/backend/check`, `/api/actions/smoke-takeoff`, and
`/api/actions/land` accept `node_id`. Registry config resolves endpoint and
system ID. A conflicting browser endpoint/system ID returns `409`; unknown node
returns `404`; explicitly offline node returns `503`. Action responses and Audit
rows contain `resolved_node_id`/`node_id`. The path remains:

```text
HTTP -> Runtime -> Policy Gate -> node-specific backend/session
     -> ActionResult -> Audit
```

Operator or coordinator proposals never bypass the execution-time Policy Gate.

Example request:

```json
{"node_id": "UAV-02", "backend": "px4_sitl", "backend_mode": "sitl"}
```

Stable error forms are:

```json
{"error": "unknown_node", "node_id": "UAV-99"}
{"error": "node_offline", "node_id": "UAV-02"}
{"error": "ambiguous_node_request", "node_id": null}
{"error": "node_endpoint_conflict", "node_id": "UAV-02"}
```

Audit records `action_request`, `policy_decision_event`,
`adapter_execution_started`, `adapter_execution_result`, and `action_result`
with the same `node_id`, so a replay can identify the exact target vehicle.

## FleetCoordinator boundary

`FleetCoordinator` accepts mission, scene, vehicle state, capabilities,
constraints and policy context and returns node-explicit candidate intents. v0.1
supports `explicit_node`, `first_available` and `round_robin`. Availability
requires enabled, connected, non-stale and (when supplied) capable. It imports no
adapter/session and cannot issue MAVLink. Future algorithms can replace the
selection policy without changing the Runtime/Policy execution boundary.

## PX4/Gazebo owner handoff

After receiving three endpoint/system mappings:

1. Fill each `endpoint`, `telemetry_endpoint`, `system_id`, and set `enabled` in
   `config/vehicles.sitl.json`; do not edit Python business logic.
2. Start the HTTP Runtime and confirm three independent collectors/sessions.
3. Query `/api/vehicles` and each
   `/api/telemetry/latest?node_id=UAV-0N`.
4. Validate `/api/vehicle-snapshot` against the frontend Vehicle Snapshot 1.0
   schema.
5. Run `python -m pytest -m requires_px4_multi -q`.
6. Take off and land UAV-02 and verify UAV-01/UAV-03 altitude does not change.
7. Stop UAV-02 and verify it alone becomes stale while HTTP and other nodes stay
   healthy.

Gazebo health requires independent clock/world/model evidence. PX4 heartbeat is
not Gazebo evidence, and this foundation does not add a Gazebo probe.

Unit tests use fake sessions and deterministic telemetry because opening real
PX4 UDP ports would make tests environment-dependent and could steal command or
telemetry messages from an active simulator.

# Multi-Vehicle Runtime v0.1.1 Hardening

- Adapter exceptions are explicit `adapter_execution_exception` failures; they
  are never converted to simulated acceptance, and public output omits raw
  exception messages and tracebacks.
- HTTP execution identity comes from resolved `VehicleConfig`. The bridge only
  accepts `px4_sitl` / `sitl`, and finite altitude, threshold, timeout, retry and
  system-ID ranges are rejected before backend execution.
- Command and telemetry receive endpoints have one owner across both roles.
- Registry membership uses the registry lock; mutable telemetry, collector and
  action state use independent per-node locks; commands use per-node locks.
- Scenario data is authoritative for initial pose, while runtime config owns
  endpoint/system deployment mapping. They join strictly through `node_id`.
- Snapshot pose priority is fresh telemetry, last-known stale telemetry, then
  authoritative scenario initial pose. Offline nodes remain; unregister removes.
- PX4 fleet connectivity is aggregated independently from Gazebo health, which
  remains `unknown` without a separate Gazebo probe.
- Unit tests use fake sessions/probes. Real three-PX4 tests remain opt-in and
  blocked until endpoints are supplied.
- The authoritative frontend JSON Schema must be read directly. This branch
  records a blocked test because that main-branch artifact is absent locally;
  no substitute schema is created or relaxed.
