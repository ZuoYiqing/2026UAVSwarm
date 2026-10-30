# Single-platform task execution v1.0

Simulation health handoff now has a dedicated read-only producer and optional
platform-view extension. Ground additionally supplies `--run-id` when using
`GET /api/simulation/runtime-telemetry`; existing task routes are unchanged.
See `runtime_telemetry_health_contract_v1.md` for the exact source clocks,
fixture and atomic file exporter. This does not constitute LIVE acceptance.

UAV-02's companion is a separate long-lived process with a SQLite task/event
store and one MAVLink receiver. An HTTP request accepts an immutable bounded
task; its worker executes independently of ground/browser connections. This
profile supports exactly TAKEOFF, HOLD_POSITION, LAND in that order, height at
most 3 m and hold at most 10 s. GOTO, perception, arbitrary tools and DISARM
are outside this profile. Existing action endpoints retain their contracts.

## Deployment and ownership

Run every process from the same integrated source version, with its `src` on
PYTHONPATH. Keep generated stores, credentials, audit files and model artifacts
outside Git. Create an unpredictable local token of at least 32 characters;
restrict its file permissions. The token authorizes the local ground process,
not an Internet-facing identity provider. All new listeners/clients use explicit
127.0.0.1. No proxy inheritance, redirects or cloud fallback is supported.

```text
python -m uav_runtime.platform.server --node-id UAV-02 --port 8766 --store-dir <agent-store> --token-file <token-file> --execution-mode fake
python -m uav_runtime.http.server --exclude-node UAV-02 --platform-url http://127.0.0.1:8767 --platform-token-file <token-file>
```

Simulation owns proxy 8767 -> agent 8766. `--candidate-url
http://127.0.0.1:8872/candidate` adds the Algorithm-owned local candidate service.
For actual simulation use `--execution-mode sitl --vehicle-config <manifest>
--run-id <active-harness-run-id>`. SITL is explicit; fake never opens MAVLink.
Agent binds only UAV-02's 14541; ground excludes UAV-02 and retains 14540/14542.
The registry selection reuses per-node configuration; no endpoint/sysid/compid
is renumbered. Starting the unmodified legacy three-node server concurrently
would violate ownership and is not a supported topology.

This profile fixes the SITL companion to UAV-02. Companion and ground processes
also hold kernel-exclusive TCP port reservations corresponding to their MAVLink
UDP endpoint numbers. These are ownership locks, not additional listeners or
MAVLink receivers, and work across different store directories. All cooperating
Runtime launchers must use this version; unmanaged external receivers still
require Simulation's preflight checks.

`GET /api/platform/status` returns `platform_observation` from the owned PX4
session, `execution_mode`, `run_id` supplied by the deployment manager and
`safe_to_stop`. Only no active task plus fresh disarmed/on-ground evidence makes
safe_to_stop true. Simulation must independently bind run_id/process identity;
an echoed CLI value alone is not identity verification. Fake evidence has
source=fake and cannot justify SITL process termination. SIGINT refuses a SITL
stop lacking safe_to_stop; an OS kill can still interrupt execution and is not
a safe flight-stop mechanism.

## HTTP and task persistence

The checked-in `docs/fixtures/platform_autonomy_v1.json` is a tested example,
not live authorization. Replace its expires_at (UTC ISO8601, max one hour from
acceptance) and identifiers before a new task. Every platform request requires
`Authorization: Bearer <token>`. The ground gateway supplies this header and
proxies the same `/api/platform/*` paths, so browser code need not know tokens.
The ground bridge keeps its existing local-origin CORS boundaries.
Its platform POST facade additionally rejects non-whitelisted Origin values
and requires application/json. Origin-less local CLI clients may submit JSON;
the loopback ground bridge is a trusted-local-process boundary.

POST /api/platform/tasks returns 202 `{task, idempotent_replay:false}` after a
durable transaction. GET /api/platform/tasks/{task_id} returns `{task}`. Identical
submissions return 200 with the same execution_id, even after expiry/loss or
restart. Reusing a task/request identity with changed content is 409. An active
or recovery_required task blocks new tasks on that node. The store is bound to
node_id and execution mode and has a cross-process exclusive ownership lock.

The task has task_id/task_version, execution_id, request_id, trace_id, immutable
authorization, steps, status, current_step, step_outcomes and failure_reason.
Statuses: accepted, executing, succeeded, failed, cancelled, recovery_required.
The durable step_started event precedes adapter execution. A process restart
marks unfinished tasks recovery_required; it never blindly replays a possibly
executed action. This provides deduplication and conservative recovery, not
distributed exactly-once delivery. Reconciliation is explicit:
POST /api/platform/tasks/{task_id}/reconcile with `{operator_id,execution_id}`
requires matching uncertain execution and fresh local landed/disarmed evidence;
the old task becomes failed, never retroactively succeeded.

## Local authority, loss and recovery

Ground sends POST /api/platform/link/heartbeat once per second. Only successful
receipt updates the platform's three-second monotonic link lease. Browser
closure does not imply ground loss. GET and event queries do not refresh it.
New tasks and new TAKEOFF require healthy ground link. Local PX4 and model
communication remain available when Simulation cuts only ground-to-agent HTTP.

The full accepted authorization is persisted. Every step passes a local Policy
Gate using actual link state and then the existing Runtime action/adapter path.
The platform profile explicitly opts into preauthorized controlled LAND during
lost link; ordinary profiles retain fallback-only restrictions. HOLD/LAND can
continue after ground loss; stale local observations prevent TAKEOFF/HOLD.
Expiry forbids further non-recovery steps; controlled LAND remains the task's
preauthorized recovery. No exception authorizes DISARM or a new target.

Cancel is cooperative: POST /api/platform/tasks/{task_id}/cancel sets a durable
request. It does not mean the aircraft stopped. The worker checks before each
step; an already-running bounded action completes/returns before recovery LAND.
HOLD is bounded at 10 s but command/observation waits can be longer. Immediate
emergency preemption is not provided by this task endpoint. A failed/ambiguous
LAND is not blindly retried: task remains recovery_required and guard evidence
must be inspected. Recovery LAND success never changes a failed/cancelled task
into succeeded. ACK alone cannot complete a step.

## Model boundary

At each step Algorithm receives only platform-local PX4 observations and the
accepted authorization/next step. Request v1.0 carries identity fields including
execution_id, step_id, snapshot_id, UTC sample timestamp, ground_link and two
allowed option IDs: execute_authorized_step and abort_to_land. Output echoes
identity, status=candidate, execution_authorized=false, decision and evidence
(model identity/version, input/output hashes, timestamp, reason). It cannot
change parameters. Missing, malformed, mismatched or late candidates are
recorded as model_unavailable and use the already-authorized deterministic
sequence; runtime authorization/freshness checks still run afterwards. A
two-second daemon request budget prevents stalled inference from blocking
control. Late replies are discarded; one still-pending model call prevents
new model calls, not local deterministic processing.

Without --candidate-url the service makes no model-capability claim. A shared
ground inference server cannot prove independent platform autonomy. The first
profile only proves the chosen virtual platform boundary; real board resources,
network topology and process isolation require separate acceptance.

The model never receives scene calibration or Gazebo ground-truth poses. The
existing LAND action still uses its previously reviewed scene-ground completion
monitor and fails closed without evidence. That simulation acceptance monitor
is not a general onboard surface sensor. Its calibration TTL remains unchanged.
Independent onboard positioning and ground perception are not completed here.

## Events, snapshots and compatibility

GET /api/platform/events?after_seq=N&store_id=S returns events in persistent
monotonic seq order, next_seq, checkpoint_seq, history_gap=false and has_more.
There is no automatic truncation in v1; page limit is 100. Wrong store_id or a
cursor ahead of the store returns 409. Callers must scope cursors by store_id,
not wall clock or boot_id. Events retain node/task/execution/request/trace IDs.
GET /api/platform/events/stream with the same query provides SSE (`id: seq`,
`event: platform_event`). Reconnect with the last committed cursor and dedupe
event IDs. Snapshot event_seq and task are read under one store lock; follow
the snapshot checkpoint with events after that seq. SSE loss never cancels tasks.
Event pages also have a 48 KiB payload budget. Diagnostic event data above
32 KiB is explicitly replaced by payload_omitted, original byte count and hash;
step results remain in the task record. Model evidence above 8 KiB is rejected.
The ground facade caps full task/status replies at 8 MiB and model replies at
64 KiB. Events never silently disappear due to a bounded recent-window query.

The ground gateway returns 503 platform_link_unavailable/unknown on link failure.
It never rewrites a platform task as failed. Frontends retain last-confirmed
platform state and mark its observation stale. They must not automatically
resubmit POST requests on reconnect. Existing /api/events and legacy action views
remain unchanged; platform state is an additive namespace. The follow-up public
snapshot fusion preserves existing shapes and includes the remotely owned node.

The authenticated `GET /api/platform/view` publishes platform-owned, calibrated
read-only projections. Ground polls this independently of its heartbeat and
merges a freshness-bounded cache into the existing snapshot/telemetry/vehicle
feeds; it never opens UAV-02's transport or adds its origin offset again.
Missing/stale views retain the node and last pose, mark public position unusable,
and never rewrite task terminal state. Fake views cannot become PX4 evidence.
Ground UAV-02 preflight forwards read-only HOME/RTL diagnostics to the owner and
rechecks local 01/03 isolation; it remains non-authorizing. Exact fields, TTLs,
errors, fixture and compatibility: `platform_view_contract_v1.md`.

Runtime owns this contract/fixture and src/uav_runtime changes. Algorithm owns
candidate service/model artifacts; Simulation owns process topology, sensors,
fault injection and independent physics evidence; Console owns display/recovery;
Integration owns combined fake and exclusive SITL acceptance. No test fixture
or process-ready result may be labeled real flight PASS.
