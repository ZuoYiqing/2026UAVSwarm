# Runtime → Simulation telemetry health evidence v1.0

## Scope and ownership

Runtime owns this producer, RX/sample clocks, route and exporter. Simulation
owns health.py, managed process/run identity, Gazebo clock/models evidence and
the integrated-health consumer. Integration supplies the same verified run_id
to both Runtime processes and manages the evidence exporter. Console/Cesium
continue consuming existing snapshots; no frontend route/conversion is needed.

This closes a missing producer contract, not flight acceptance. Telemetry
health alone cannot establish Gazebo readiness, landed/disarmed, safe surface,
task completion or execution permission. No ports, configuration, sysids,
thresholds, ground_reference lifetime or model input changes.

## Implemented interface

`GET /api/simulation/runtime-telemetry`, no query/body, returns HTTP 200 with
the envelope in `fixtures/runtime_telemetry_evidence_v1.json`. This fixture is
**synthetic at a controlled 1970 clock**, not live evidence.

Ground takes additive `--run-id <active Simulation harness run_id>`:

```text
python -m uav_runtime.http.server --exclude-node UAV-02 --platform-url http://127.0.0.1:8767 --platform-token-file <token-file> --run-id <active-run-id>
```

Platform retains its existing `--execution-mode sitl --run-id`. Both processes
must use the same integrated Runtime version and active run label. This label
is a deployment assertion, **not proof of PX4/Gazebo process identity**;
Simulation independently verifies its managed processes. Missing ground run_id
returns 503 `runtime_run_id_required`; any query, including a run_id override,
returns 400 `invalid_query`. Old routes/CLI defaults remain compatible without
run_id, but cannot provide this new evidence until explicitly configured.

The ground bridge remains local-only under its existing security model;
internal platform view remains bearer-authenticated. GET performs no connection,
stream request, ARM, other command or new MAVLink receiver operation.

## Fields and source

| Field | Source / meaning |
| --- | --- |
| contract_version | `1.0`, separate from UI `version/nodes` |
| scene_id / run_id | Registry scene / explicit process startup label |
| source_timestamp | UTC envelope assembly time, not sample time |
| valid_for_ms | 5000, does not extend individual sample lifetime |
| vehicles | Owned nodes plus cached UAV-02 when gateway configured |
| node_id / endpoint | Authoritative node routing configuration |
| system_id / component_id | Matched RX source identity; null if unobserved |
| heartbeat_timestamp | That session's HEARTBEAT UTC receive time |
| position_timestamp | Independent LOCAL_POSITION_NED UTC receive time |
| heartbeat_age_ms / position_age_ms | Independent monotonic RX age, conservatively aged through cache |
| heartbeat_sequence / position_sequence | Per-session, not fleet-wide, RX sequences |
| heartbeat_fresh / telemetry_fresh | Strict booleans: connected RX owner, source identity and age |
| last_seen | Latest of the two sample times; does not replace either |
| execution_authorized / flight_command_sent | Both false; not flight authorization |

HEARTBEAT limit is 2500 ms; position limit is 1500 ms, matching Simulation.
Missing IDs, stopped RX, disconnect, identity/RX error, nonfinite positions or
reset-invalidated samples cannot yield both flags true. New heartbeat/battery/
HTTP responses cannot renew old position. Simulation independently checks UTC
sample ages, manifest identity, run/scene and envelope age. No ground truth enters
this producer, and no wall clock replaces the RX monotonic age.

Additive internal `/api/platform/view.runtime_telemetry` carries UAV-02's
single-node evidence through its existing owner. Fake mode has null evidence.
Ground validates run/scene/source/node/endpoint/version and ages samples using
both UTC and monotonic cache elapsed time. Absent/invalid/stale/failed platform
view retains UAV-02 with false flags and unknown identity/sample values. Older
views still render but cannot satisfy telemetry health. Four UI projections
remain unchanged; the diagnostic envelope is not included in public
`platform_view` metadata.

## Atomic file handoff

Simulation's `--mode integrated --runtime-telemetry <file>` or
`runtime_telemetry_provider` consumes this envelope, **not** UI
`GET /api/telemetry/latest`. Export with:

```text
PYTHONPATH=src python scripts/export_runtime_telemetry.py --url http://127.0.0.1:8765 --scene-id simple_recon_v0_1 --run-id <active-run-id> --output <ignored-runtime-dir>/runtime-telemetry.json --interval 0.5
```

Without interval it writes once. With 0.5 it repeatedly performs only GET,
validates binding/exact three-node set, atomically replaces the file and preserves
every producer timestamp/false flag. HTTP/binding/write failure leaves the old
file unchanged; its age increases until rejected. No stale file is re-stamped.
Explicit 127.0.0.1 HTTP only; no inherited proxy/redirect.

Use Simulation's provider/file re-read **after** its Gazebo sampling window.
One-shot samples may expire during multi-second Gazebo probes. This cadence is
dynamic telemetry sampling, not health re-publication to bypass static geometry
validation. Short health TTL and version-bound ground_reference stay separate.
The exporter is opt-in, owned by the deployment window; no automatic service or
Simulation launcher change is included. Stop only the exporter started for the
window. Missing evidence remains unknown, never ready.

## Verification / remaining acceptance

2026-10-30 targeted producer/session/platform-view run: **82 passed, 0 failed**.
Tests use dispatcher fixtures, synthetic clocks and temporary loopback HTTP,
never real PX4/model. They cover independent node/sample ages, repeated GET and
old samples, identity/RX/reset/nonfinite cases, platform link loss/binding,
unchanged projections, actual Simulation consumer compatibility and atomic export
without timestamp renewal. Full regression is recorded after completion.

Final verification on this source (2026-10-30):

- Windows Python 3.11 targeted command:
  `python -B -m pytest -q -p no:cacheprovider tests/unit/test_runtime_telemetry_evidence.py tests/unit/test_platform_view.py tests/unit/test_mavlink_backend_session.py --basetemp .tmp_runtime_health_evidence4`
  → **82 passed, 0 failed**, 4.32 s (32 new producer/export tests).
- Ubuntu 22.04 / Python 3.10 offline environment, `PYTHONNOUSERSITE=1
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -rs -p
  no:cacheprovider --basetemp <external-owned-test-dir>`:
  **1027 passed, 12 skipped, 0 failed**, 141.20 s. Skips: 5 real multi-PX4,
  1 opt-in real patrol, 6 Node/converter-dependency cases.
- Fixed integration `0f21683` cross-line test with only this Runtime source
  overridden: `python -B -m pytest -q -p no:cacheprovider -o
  pythonpath=D:/2026UAVSwarm-worktrees/runtime-action-lifecycle/src
  tests/integration/test_uav02_onboard_autonomy.py` → **10 passed**, 4.46 s.
  This is a source-overlay fixture check, not a committed combination/live run.
- AST syntax parsing: 10 changed Python files passed. `git diff --check` passed.

Initial targeted failures were fixture UTC spelling, missing fake-thread join,
route-clock mocking, and old view dispatch mocks lacking the new optional GET.
They were corrected before the passing targeted/full runs, not counted as passes.

Simulation also consumed the fixture in its own worktree at controlled time:
3/3 node probes reason=ok (reported by Simulation, not a LIVE pass). Actual
multi-process PX4/Gazebo/model and console/Cesium acceptance remains pending a
managed, resource-admitted window. Do not mark the PR Ready from these results.
