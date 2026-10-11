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

Completion contract `1.1` separates ordinary scene-ground completion from a
named-site task goal. Ordinary LAND does **not** require a `validated` pad.
LAND remains an available controlled-recovery command without ground evidence.
Success requires an accepted LAND command and fresh post-command evidence:
`EXTENDED_SYS_STATE.ON_GROUND`, disarmed HEARTBEAT, and at least three consecutive
local-position samples transformed once into `scene_ned`, inside the declared
ground-reference bounds and within 0.3 m of its down value for at least 0.5 s.
The maximum position sample gap/age is 0.5 s; armed/landed state age is at most
2 s. An outlier, rearm, missing/stale state, or origin reset invalidates the
window. Samples received during the ACK wait remain eligible; old cache does not.

`completion_evidence.physical_landed_disarmed` is separate from
`completion_reached`. A roof can satisfy the first and fail the second with
`scene_ground_not_reached`. Missing reference yields `ground_reference_unavailable`
and `completion_state: unknown` if physical completion is observed; missing
physical evidence times out. Changed/stale ground or calibration evidence at
completion yields `ground_reference_changed_or_stale`. This proves consistency
with the stated scene plane, not perception of safe bearing capacity, slope, or
obstacles in an unknown environment. No path implements in-air forced disarm.

The internal backend can additionally check an explicitly supplied site XY
goal; HTTP ordinary LAND supplies no site. `site_completion.state: not_requested`
does not mean a named-site mission was completed. A disconnected session is
rejected before sending LAND regardless of ground evidence.

After sending LAND, Runtime requests the landed-state stream as best-effort
completion instrumentation. A stream-setup exception is retained as evidence but
does not suppress or delay the LAND command. The action still cannot succeed
unless fresh landed and disarmed samples arrive.

### `POST /api/actions/return-home`

Runtime requests this node's actual `HOME_POSITION` (MAV_CMD_REQUEST_MESSAGE 242)
through its sole receiver. It uses MAVLink `x/y`, not non-existent `local_x/y`,
scene pad coordinates, or an assumed local zero. Fresh, time-aligned
`GLOBAL_POSITION_INT` and `LOCAL_POSITION_NED` must independently corroborate
the HOME XY within 2 m (sample alignment <=250 ms, age <=2 s). A zero HOME is
accepted only when that cross-check agrees. Cached HOME from before the request,
missing/unverified HOME, or a changed origin is not usable; no RTL is sent in
those cases (`home_position_unavailable`, `home_position_unverified`,
`home_reference_changed`). No pad evidence or scene calibration is required for
this local HOME goal. Horizontal `home_tolerance_m` defaults to 0.75 m.
The measured cross-check discrepancy consumes that tolerance; discrepancy at or
above it rejects RTL with `home_position_uncertainty_exceeds_tolerance`.
This is a telemetry-relative check, not a sensor accuracy certification.
Before sending RTL the same dispatcher must receive fresh replies to
`PARAM_REQUEST_READ(RTL_TYPE)` and `MISSION_REQUEST_LIST(mission_type=RALLY)`.
Only actual `RTL_TYPE=0` and zero rally points are supported by this HOME-only
action. Missing replies fail `rtl_destination_unverified`; any other type or
nonzero rally count fails `rtl_home_configuration_unsupported`, without sending
RTL. Evidence is retained as `rtl_destination_evidence`; no parameters or mission
items are written. This bounded configuration avoids confusing HOME with the
closest rally or mission landing destination. New HOME/configuration queries
still use the already-owned MAVLink receiver.
`stable_duration_ms` defaults to 1000 ms (range 300–10000 ms); at least three
fresh post-command position samples must remain within tolerance for this
duration. `min_progress_m` is only diagnostic. Changing to AUTO_RTL or reducing
the distance by 5 m never completes return-home by itself. A timed observation
with progress but no arrival yields `return_home_in_progress`, not success.
The completion goal is `px4_home_horizontal_arrival`, not landing, disarm,
obstacle clearance, or precision pad occupancy. The configured PX4 RTL
configuration-read support/behavior must be verified in real acceptance. Rally
and mission landing return configurations are intentionally not supported by
this HOME-only route. Observation expiry
is terminal `timed_out`, with progress retained only as diagnostic evidence.

HTTP completion does not stop autonomous RTL/LAND. The per-node autonomous
guard blocks subsequent non-LAND actions until a fresh **post-command** safe
HOLD/POSCTL/ALTCTL mode or landed/disarmed pair proves execution ended. LAND can
preempt it. Old HOLD heartbeats and stale evidence cannot release it. The
additive `vehicles[].control` contract `1.1` in `/api/vehicle-snapshot` exposes
`active_action_id`, `autonomous_action_id`, `autonomous_execution_may_continue`,
and its evidence; `/api/vehicles` exposes matching registry fields. Nullable IDs
are omitted by the existing vehicle-view serialization when empty. Action query
and idempotent replay retain the terminal observation result, not a fictitious
stop confirmation.

### Optional named-site evidence v1.0 (reserved, not an ordinary action gate)

This change reserves an internal, node-specific evidence shape separate from
the dynamic coordinate calibration: `scene_id`, `map_version`, `world_sha256`,
`node_id`, `object_id`, `center_scene_ned_m`, horizontal/vertical tolerances,
`ground_down_m`, `collision_surface`, `source_timestamp`,
`status`, and `validation`. A render-only pad and a fresh EKF translation do not
prove a safe landing surface. The current scene's pad visual has no collision;
the physical support is `ground_plane`. Simulation has proposed a conservative
0.75 m center tolerance but has **not** validated it with an integrated flight.

Landing-site geometry does not expire by elapsed time: it is tied to
`scene_id`/`map_version`/world identity. Landing capability must be tied to the
software version in a future trusted validation record, not a TTL.
`source_timestamp` is provenance only; `valid_for_ms` is not accepted for this
static site record. Runtime still decides whether a site may be used for an
action from live telemetry, dynamic calibration, Policy, and matching versioned
evidence. Calibration and Simulation-health TTLs below remain unchanged.

There is currently **no trusted landing-site publisher** in the Runtime HTTP
bridge. In particular, an unauthenticated caller's `status: validated` or
claimed run ID cannot grant flight authority. The store rejects such evidence
with `trusted_landing_site_producer_unavailable`; no public landing-site write
route is exposed. This reserved capability is no longer a prerequisite for
ordinary LAND or actual HOME arrival. A future **named-site task** must define
its evidence producer and explicit task goal independently. Static site records
remain version-keyed rather than expiring by time. Do not promote this candidate
fixture or ordinary calibration into a safe-surface declaration.

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

Simulation PR #92 adds optional `ground_reference` `1.0` and matching
`world_sha256` to `runtime_evidence`. Runtime requires the outer source timestamp
and TTL, world ready/advancing clock, selected-node model ready, matching
scene/map/world identity, and calibration `context.run_id` matching health.
`ground_reference` contains `frame: scene_ned`, `kind: horizontal_plane`,
`ground_down_m`, `xy_bounds_m`, `surface_id`, and
`source: world_collision_geometry`. It is a known-scene geometry reference,
not a perception model or trusted pad certificate. Source time is checked too;
reposting an old file does not rejuvenate it. Local boot/reset-counter changes
immediately invalidate accepted calibration; republication must postdate reset.
Silent origin resets with no observable reset signal remain a real-verification
gap and require the Simulation calibration monitor. Ground health must be
republished while observing a flight (producer TTL 5000 ms); a one-shot expired
publication cannot complete LAND.

Simulation owns the world-hash scheme. Its cross-checkout reference uses SHA-256
of LF-normalized SDF content (`world_sha256_scheme: sha256-lf-v1`); the harness
separately records and checks the startup file's raw-byte `world_file_sha256`.
Runtime treats `world_sha256` as an opaque
version binding and compares producer fields, never silently normalizes an
incoming hash. A matching normalized hash does not excuse a changed running
file. This is not a proof of dynamically modified Gazebo geometry.

Executable additive examples are in
`docs/fixtures/runtime_ground_completion_v1_1.json`. Old fixtures keep their
existing field shapes. No endpoint, sysid, port, or config manifest changes.

Simulation `ready` requires fresh evidence, an advancing clock, a ready world,
and ready model evidence covering enabled nodes. Fresh but incomplete evidence
is `degraded`; missing or expired evidence is `unknown`. PX4 heartbeat is reported
separately and never promotes Gazebo to ready. In integrated mode Simulation does
not bind ports 14540-14542. `evidence_fresh`, `evidence_age_ms`, and
`evidence_valid_for_ms` expose the TTL decision even after evidence expires.

## Read-only acceptance preflight

`GET /api/preflight?node_id=UAV-02` is implemented as diagnostic contract `1.0`.
Exactly one explicit `node_id` is required; endpoint/system/timeout overrides
and duplicate/empty node parameters return HTTP 400. Unknown nodes return 404.

The handler reuses **already connected Registry-owned sessions**. It never
starts or reconnects a vehicle, opens a temporary probe, creates an action, or
calls ARM, TAKEOFF, LAND, RTL mode switching, parameter/mission writes or flight
setpoints. HOME uses REQUEST_MESSAGE (512/242); RTL evidence uses PARAM_REQUEST_READ,
MISSION_REQUEST_LIST(RALLY=2) and the zero-count MISSION_ACK protocol reply.
These diagnostic MAVLink reads are not flight commands. GCS heartbeat continues.

The report returns `preflight_id`, `timestamp`, `node_id`, per-node `nodes`,
`home_evidence`, `rtl_destination_evidence`, `ground_context`, `reason_codes`,
`status` (`ready`/`not_ready`), `execution_authorized: false`, and
`flight_command_sent: false`. HTTP 200 means a diagnostic report, not passed
flight acceptance. `ready` requires all registered nodes' fresh disarmed evidence,
one RX owner and GCS heartbeat, no busy/autonomous lease, selected-node fresh
ON_GROUND, current ground/calibration context, verified HOME cross-check error
strictly below the default 0.75 m tolerance, and supported HOME-only RTL config.
Locks are acquired nonblocking; a busy/offline/stale node is not queried.
Queries use fixed two-second per-wait budgets; HOME's ACK and evidence waits can
total four seconds, plus the two-second RTL query. Isolation and ground context
are rechecked afterwards. No lock or readiness ticket persists in this report.

Failures remain `not_ready` with reasons such as
`persistent_session_unavailable:UAV-02`, `fresh_disarmed_evidence_unavailable:UAV-01`,
`node_busy:UAV-02`, `fresh_landed_evidence_unavailable`,
`ground_reference_unavailable`, `ground_reference_changed_or_stale`,
`home_position_unverified`, `home_position_uncertainty_exceeds_tolerance`,
`rtl_destination_unverified`, `rtl_home_configuration_unsupported`,
`home_or_rtl_not_checked`, or `preflight_query_exception` (with `error_class`).
Ground/config source evidence and timestamps remain separate from report time.

This point-in-time diagnostic is **not Policy admission**, a landing-surface
safety certificate, nor a promise of future completion. Ordinary controlled
LAND does not depend on preflight being ready. Operators must not arm to make
an unavailable HOME query pass. Existing action routes retain all their gates.
The executable response projection is in
`docs/fixtures/runtime_preflight_v1.json`; it is offline, not live evidence.

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

## Spatial execution status

`GOTO`, `HOLD`, and `RETURN_HOME` have operational routes through Runtime,
Policy, node admission, and the persistent session. `RETURN_HOME` uses actual
verified PX4 HOME; ordinary LAND uses the explicit plane goal described above.
`POST /api/planner/plan-mission` remains plan-only; this does not imply an
autonomous multi-waypoint executor.

## Verification boundary

The producer and fixture tests validate routing, replay/conflict behavior, Policy
rejection, ACK-versus-completion semantics, stale/timeout behavior, LAND
preemption, persistent session use, coordinate translation, snapshot
compatibility, and simulation evidence expiry without opening real PX4 ports.
Real UAV-02 takeoff/hold/land plus UAV-01/UAV-03 isolation remains a separate
joint PX4/Gazebo/console/3D acceptance and must not be inferred from unit tests.

Algorithm PR #91 supplies an **offline proposal** assessment baseline, not a
Runtime producer. `criteria_met` is never execution authorization or task
success. Confidence is null; surface safety remains unknown. Raw observations,
assessment/version/input hash, and independently verified labels must be stored
separately; Runtime's historic `succeeded` is not ground truth for training.
