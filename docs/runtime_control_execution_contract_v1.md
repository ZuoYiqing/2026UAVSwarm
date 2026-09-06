# Runtime Control Execution Contract v1

This contract is the implemented handoff from Agent Runtime to the main console,
the 3D client, and Simulation. The executable examples live in
`docs/fixtures/runtime_control_contract_v1.json`.

## Ownership and boundaries

- Runtime owns request validation, node routing, Policy Gate evaluation,
  idempotency, action lifecycle, MAVLink ACK correlation, telemetry completion
  criteria, and the public vehicle view-model.
- Simulation owns Gazebo world/model/clock evidence and the physical calibration
  from each PX4 local origin into `scene_ned`.
- The main console and 3D client consume Runtime state. They do not infer success
  from timers, cache an independent authoritative action state, open a MAVLink
  receiver, or add spawn offsets a second time.
- `POST /api/planner/plan-mission` remains plan-only. It does not execute a plan.
- Runtime does not start, stop, or infer the health of Gazebo.

The HTTP bridge is intended for the local loopback deployment. Policy and
`command_source` provide execution authorization semantics, but this version does
not add user authentication or a network-facing identity provider. Do not expose
the bridge to an untrusted network.

## Node and transport routing

The checked-in manifest is unchanged and remains authoritative:

| node_id | target system | target component | Runtime endpoint |
| --- | ---: | ---: | --- |
| `UAV-01` | 1 | 1 | `udpin:127.0.0.1:14540` |
| `UAV-02` | 2 | 1 | `udpin:127.0.0.1:14541` |
| `UAV-03` | 3 | 1 | `udpin:127.0.0.1:14542` |

Each registered vehicle owns one long-lived `MavlinkBackendSession`. Its receive
loop dispatches HEARTBEAT, command ACK, local position, and landed-state messages.
Actions do not close that session or stop its GCS heartbeat. No read or action
route creates a competing receiver.

## Operational actions

### `POST /api/actions/takeoff`

Use `operational_takeoff_request` from the fixture. Required routing and safety
fields include `node_id`, `backend_enabled: true`, and the endpoint matching the
registered node. Stable client identifiers are strongly recommended:

- `request_id` identifies the HTTP/command request.
- `trace_id` joins Policy, adapter, ACK, telemetry completion, and audit events.
- `idempotency_key` prevents a browser refresh or retry from executing again.
- `command_source` is `ground_station` or `agent`; both use the same execution
  path and Policy Gate.

Success requires all of the following: Policy allow, per-node admission, accepted
stream/arm/takeoff command stages, and fresh `LOCAL_POSITION_NED` samples after
the TAKEOFF command cursor within `altitude_m +/- altitude_tolerance_m` for
`stable_duration_ms`. At least two in-tolerance samples are required when the
stability duration is at least 100 ms. Tolerance must be smaller than the target
altitude so a ground-level sample cannot satisfy the completion band. Samples
cached before the TAKEOFF send are never
completion evidence; samples received while waiting for its ACK are retained.

### `POST /api/actions/land`

Use `land_request` from the fixture. LAND may preempt an active non-LAND action on
the same node. The old action is terminal `failed` with code
`action_preempted_by_land`; its cancellation event is signalled, and a late result
cannot overwrite that terminal result. A second LAND remains a normal busy
conflict rather than creating two commands.

LAND success requires an accepted LAND command plus fresh post-command
`EXTENDED_SYS_STATE` reporting `ON_GROUND` and a fresh HEARTBEAT reporting
disarmed. ACK acceptance alone is not success. Missing landed/armed evidence is
reported as `unknown`, `incomplete`, or `stale` in completion evidence and ends as
`timed_out` when the observation deadline expires. No path implements
"stop task" as an in-air forced disarm.

After sending LAND, Runtime requests the landed-state stream as best-effort
completion instrumentation. A stream-setup exception is retained as evidence but
does not suppress or delay the LAND command. The action still cannot succeed
unless fresh landed and disarmed samples arrive.

### Compatibility smoke route

`POST /api/actions/smoke-takeoff` remains compatible and may auto-land. Its loose
height threshold is an integration smoke signal, not the operational takeoff
completion contract. New console controls must use the operational routes.

## Action lifecycle and errors

Query one action with `GET /api/actions/{action_id}` or recent server-owned
lifecycle records with `GET /api/actions/lifecycle?n=20`.

Lifecycle contract version `1.1` has these states:

| State | Meaning |
| --- | --- |
| `requested` | Runtime created the idempotent action record. |
| `policy_rejected` | Policy denied execution; the adapter was not called. |
| `accepted` | Policy allowed and Runtime is attempting per-node admission. |
| `executing` | The node-specific adapter call is active. |
| `succeeded` | Telemetry completion criteria, not only ACK, passed. |
| `failed` | Execution, validation after admission, cancellation, or adapter failure. |
| `timed_out` | Required fresh completion evidence did not arrive by the deadline. |

`ack_evidence` contains command/stage, MAVLink result, receive timestamp, node,
action, request, and trace identifiers. `completion_evidence` contains the actual
telemetry criteria and source/sample timestamps. The response and stored record
retain `node_id`, `system_id`, `component_id`, `action_id`, `request_id`, and
`trace_id`.

Relevant HTTP/error behavior:

| Situation | HTTP | Stable code/status |
| --- | ---: | --- |
| First request, terminal result | 200 | lifecycle terminal state |
| Idempotent replay while active | 202 | same `action_id`, `idempotent_replay: true` |
| Idempotent replay after terminal | 200 | same terminal action |
| Same key with a different fingerprint | 409 | `idempotency_conflict` |
| Node already executing a non-preemptible action | 409 | `node_busy` |
| Unknown/offline/mismatched node routing | 4xx/503 | vehicle registry code |
| Policy rejection | 200 | `status: policy_rejected`, `code: policy_<decision>` |
| Adapter exception normalized by Gateway | 200 | stored `failed`, `adapter_execution_exception` |
| Gateway/control-path exception | 500 at the HTTP server boundary | stored `failed`, `adapter_execution_exception` |
| Completion evidence deadline | 200 | `status: timed_out`, action-specific timeout code |

An adapter exception is never converted into success: the Gateway normalizes it
to an explicit failure. If the Gateway/control path itself raises, the local HTTP
server returns an internal error; before propagation Runtime marks the action
failed, releases the matching node lease, and records the stable failure code.

## Public coordinate view-model

Simulation publishes one node calibration through
`POST /api/coordinates/calibration`. Contract `1.0` requires:

- `scene_id`, `map_version`, `node_id`, and `calibration_version`;
- `local_origin_id`, `origin_continuity`, and `axis_alignment`;
- `scene_origin`, `altitude_reference`, `source_timestamp`, and `valid_for_ms`;
- finite `translation_scene_ned_m.{north,east,down}`.

The only implemented transform is an explicit NED-aligned translation:

```text
scene_ned = vehicle_local_ned + translation_scene_ned_m
```

Runtime applies it once and publishes the result in the vehicle snapshot as
`spatial.scene_pose`, with `spatial.public_position_usable: true`. Vehicle yaw is
not used as an axis rotation. If calibration is absent, stale, not NED-aligned,
or cannot verify origin continuity, Runtime omits `scene_pose`, sets public use to
false, and retains `spatial.raw_vehicle_local_pose` only as diagnostic evidence.
An EKF origin reset therefore requires a new origin ID/calibration; old evidence
must not be reused.

`spatial.sample_timestamp` identifies the cached vehicle telemetry sample;
`spatial.calibration_source_timestamp` identifies the Simulation calibration
evidence. `sample_age_ms`, `stale`, and calibration status must be checked before
using the position. `calibration_age_ms` and `calibration_valid_for_ms` expose the
calibration TTL decision directly.

The compatibility top-level `pose` and its existing `px4_telemetry` /
`last_known_telemetry` source values remain present for existing consumers; a
calibrated pose uses `runtime_scene_calibration`. New 3D and
separation/geofence logic must not infer the coordinate frame from that legacy
field. It must require `spatial.public_position_usable` and consume
`spatial.scene_pose` only.

Units are metres; NED uses `z_down`. The calibration's `altitude_reference`
describes the scene datum. Relative takeoff altitude, AGL, and WGS84 altitude are
not interchangeable with scene NED down.

## Simulation health evidence

Simulation publishes integrated evidence with `POST /api/simulation/evidence`.
Contract `1.0` includes `scene_id`, `map_version`, `source_timestamp`,
`valid_for_ms`, `clock_advancing`, world status, and per-node model status.
Runtime rejects a scene mismatch and exposes accepted evidence through
`GET /api/simulation/status`.

`ready` requires fresh evidence, an advancing clock, a ready world, and ready
model evidence covering enabled nodes. Fresh but incomplete evidence is
`degraded`; missing or expired evidence is `unknown`. PX4 heartbeat is reported
separately and never promotes Gazebo to ready. In integrated mode Simulation does
not bind ports 14540-14542. `evidence_fresh`, `evidence_age_ms`, and
`evidence_valid_for_ms` expose the TTL decision even after evidence expires.

## Compatibility and consumer handoff

- Existing telemetry, snapshot, vehicle-snapshot, agent-status, smoke, and planner
  routes remain available.
- Full offline snapshots retain registered stale nodes; they do not collapse to
  `vehicles: []` unless nodes are explicitly unregistered.
- `GET /api/telemetry/latest` and `GET /api/vehicle-snapshot` are implemented
  polling APIs backed by Runtime caches.
- No MOCK fallback is part of the operational action, telemetry, coordinate, or
  simulation-health contract. Unknown data remains unknown.
- Main console: use operational action routes, persist idempotency identifiers,
  then query the returned action ID.
- 3D client: render public LIVE position only when calibrated and usable; retain
  raw local pose only in a diagnostic display.
- Simulation: publish fixture-compatible health and calibration evidence with a
  TTL; do not create another MAVLink receiver.

## Deferred spatial execution

`GOTO`, `HOLD`, and `RETURN_HOME` are proposal-only. The route named in the
fixture is not implemented or allowlisted. A later version must keep Agent plan
generation separate from an executor that passes each command through Runtime,
Policy, node admission, the persistent session, and telemetry completion.

## Verification boundary

The producer and fixture tests validate routing, replay/conflict behavior, Policy
rejection, ACK-versus-completion semantics, stale/timeout behavior, LAND
preemption, persistent session use, coordinate translation, snapshot
compatibility, and simulation evidence expiry without opening real PX4 ports.
Real UAV-02 takeoff/hold/land plus UAV-01/UAV-03 isolation remains a separate
joint PX4/Gazebo/console/3D acceptance and must not be inferred from unit tests.
