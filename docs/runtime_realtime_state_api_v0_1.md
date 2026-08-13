# Runtime Read-only Realtime State API v0.1

## Purpose

This API turns the local HTTP bridge into a non-blocking status source for the
console and Cesium page. It does not make the browser a MAVLink, Gazebo
Transport, or DDS client, and read-only routes never send ARM, TAKEOFF, LAND, or
message-interval commands.

## State ownership

`RuntimeStateStore` is a process-local, thread-safe cache of:

- the latest normalized PX4 telemetry and receipt time;
- backend readiness from explicit `/api/backend/check` probes;
- the latest deterministic Template Planner result and lifecycle updates;
- recent in-process events, policy decisions, and action results.

HTTP GET handlers only copy and serialize this state. They do not connect to PX4
or scan audit logs to infer active plan state.

Each Registry `VehicleHandle` owns one background receive loop and the
manifest-selected endpoint (`14540/14541/14542`). `Px4TelemetryCollector` is a
passive subscriber to that loop; ACK waits and altitude observation consume the
same dispatcher's mailbox/cache. Independent processes must not bind and consume
the same UDP listen port. Set this environment variable when launching the
server:

```bash
UAV_RUNTIME_TELEMETRY_ENABLED=true
python -m uav_runtime.http.server
```

Runtime loads the endpoint mapping from
`simulation/px4_gazebo/config/three_uav_sitl.json`; there is no separate
telemetry endpoint override in the shared-session contract.

## Read-only routes

### `GET /api/telemetry/latest`

Source: latest `Px4TelemetrySnapshot` published by the managed collector.

It returns freshness (`fresh`, `age_ms`, `stale_after_ms`), PX4 connection state,
NED local position, positive altitude derived from negative NED down, attitude,
velocity, battery, global position, and last command ACK. Non-finite numeric data
is serialized as `null`. Before data exists it returns HTTP 200 with
`status: unavailable`, an empty `nodes` array, and a reason.

### `GET /api/snapshot`

Source: `RuntimeStateStore` composition of cached telemetry, explicit backend
probe state, stored plan state, in-process events/policy/actions, and static
truthful capability flags.

Unavailable fields remain `null`, empty, or `supported: false`. The API does not
invent fleet size, queue depth, success rate, latency, or session metrics.

### `GET /api/vehicle-snapshot`

Source: a deterministic projection of cached telemetry into the Cesium vehicle
snapshot contract. `full_state: true` means the response is a complete set. The
single SITL vehicle uses stable ID `UAV-01`; the structure remains an array for
future multi-vehicle support. No `agent` object is emitted because current plans
are not bound to a specific vehicle execution identity.

The NED frame uses PX4 local origin semantics. The frontend may transform NED for
rendering, but must not reinterpret `z` as positive-up. When a managed WGS84/local
origin contract is added, it can be published explicitly rather than guessed.

### `GET /api/agent/status`

Source: plans saved directly after `TemplateAgentPlanner.plan()` plus explicit
lifecycle updates written to the store. Current truth is:

- planner: deterministic `template_agent_planner` v0.1;
- LLM disabled;
- real execution disabled;
- supported controller modes: `dry_run` and `fake`;
- no fabricated token, cache, queue, session, or latency metrics.

### `GET /api/simulation/status`

Source: independent Gazebo evidence only. Runtime currently has no Gazebo clock,
world/model service, process probe, or Gazebo bridge heartbeat, so this route
returns `status: unknown`, `evidence: []`, and
`reason: gazebo_probe_not_implemented`. PX4 heartbeat is exposed separately as
`px4_sitl_connected`; it never changes Gazebo status to `running`.

## Example unavailable telemetry

```json
{
  "version": "1.0",
  "timestamp": "2026-07-29T03:00:00.125Z",
  "status": "unavailable",
  "fresh": false,
  "age_ms": null,
  "stale_after_ms": 2000,
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "endpoint": "udpin:127.0.0.1:14030",
  "nodes": [],
  "reason": "telemetry_not_started",
  "source": "runtime_state_store"
}
```

## Example vehicle snapshot

```json
{
  "version": "1.0",
  "timestamp": "2026-07-29T03:00:00.125Z",
  "full_state": true,
  "source": {"id": "runtime-fusion", "kind": "simulation", "label": "PX4 SITL / Runtime"},
  "frame": {"type": "NED"},
  "vehicles": []
}
```

An empty array is intentional when telemetry is unavailable; it is not replaced
with sample or random vehicle data.
