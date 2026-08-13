# PX4 / Gazebo Telemetry Bridge v0.1

## Scope

Telemetry Bridge v0.1 is the uav_runtime observability layer for PX4 / Gazebo SITL. It is not an isolated simulation script and it is not a control path. Its purpose is to normalize PX4 MAVLink telemetry into runtime data structures that can later feed Runtime Console Contract view models, HTTP APIs, Audit/Replay, and frontend pages.

This phase does not change frontend pages, add WebSocket, add a database, introduce Agent/GPT control, implement multi-vehicle control, connect real aircraft, require QGroundControl, upload waypoint missions, implement return_home/hold_position, control payloads, or bypass Policy Gate.

## Runtime layering

Telemetry bridge code is split into layers:

1. `mavlink_backend_session.py` remains the connection/session layer for MAVLink connection, heartbeat, command ack, and smoke-takeoff session behavior.
2. `px4_telemetry.py` is the PX4 telemetry normalization layer. It parses `HEARTBEAT`, `LOCAL_POSITION_NED`, `ATTITUDE`, `GLOBAL_POSITION_INT`, `SYS_STATUS`, `BATTERY_STATUS`, `VFR_HUD`, and `COMMAND_ACK` into `PX4TelemetrySnapshot`.
3. Console-facing view models such as `TelemetryLatest`, `NodeStateView`, and a runtime snapshot fragment are derived from `PX4TelemetrySnapshot`. They are not MAVLink-native data and are not execution authorization.

`PX4TelemetrySnapshot` intentionally stays frontend-neutral. UI labels, cards, graph layout, and page-specific state belong in console view models or HTTP contract DTOs, not in the PX4 telemetry schema.

## Telemetry schema

The normalized snapshot contains:

- connection metadata: `timestamp`, `backend`, `backend_mode`, `endpoint`, `connected`, `system_id`, `component_id`;
- vehicle state: `vehicle_type`, `autopilot`, `armed`, `flight_mode`, `custom_mode`, `system_status`;
- `local_position`: `x_m`, `y_m`, `z_down_m`, `altitude_m`, `vx_m_s`, `vy_m_s`, `vz_m_s`;
- `attitude`: roll/pitch/yaw in radians and degrees;
- optional `global_position`: latitude, longitude, relative altitude, heading;
- optional battery/sys status: voltage, current, battery remaining, onboard sensor present/enabled/health bitmasks;
- optional `last_command_ack`: command, command name, result, result name, timeout;
- `source_message_counts` for `HEARTBEAT`, `LOCAL_POSITION_NED`, `ATTITUDE`, `GLOBAL_POSITION_INT`, `SYS_STATUS`, `BATTERY_STATUS`, `VFR_HUD`, and `COMMAND_ACK`.

PX4 publishes `LOCAL_POSITION_NED` in NED coordinates, so `z` is positive down. During takeoff `z_down_m` becomes negative, and runtime altitude is:

```text
altitude_m = max(0.0, -float(z_down_m))
```

Never treat `z_down_m` as positive altitude. For example, `z_down_m=-2.12` means `altitude_m=2.12`, while `z_down_m=1.0` still means `altitude_m=0.0` for above-origin display.

## Runtime Console Contract alignment

Telemetry bridge output is designed to support:

- `TelemetryLatest` for telemetry cards and single-aircraft detail;
- `NodeStateView` for 3D situation and vehicle detail pages;
- `RuntimeSnapshot` fragments for overview/status dashboards;
- `ActionResultView` observations when an action needs altitude or command evidence;
- `EventEnvelope` records for Audit / Replay / Timeline.

Future HTTP routes should expose standard view models instead of asking the frontend to read CLI output files directly:

- `GET /api/telemetry/latest`
- `GET /api/snapshot`
- `GET /api/events?n=50`

The observe CLI is a validation tool, not the final data channel for the frontend.

## EventEnvelope / Audit / Replay alignment

Telemetry summary and sample events should be compatible with the Runtime Console Contract event-envelope idea:

```json
{
  "event_type": "telemetry_sample",
  "trace_id": "trc-...",
  "session_id": "sess-...",
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "endpoint": "udpin:127.0.0.1:14540",
  "timestamp": "2026-07-07T00:00:00Z",
  "summary": "PX4 telemetry sample",
  "payload": {}
}
```

v0.1 does not require a full replay UI, but telemetry summary/sample data should not be written as uncorrelated JSON that cannot later be joined with action results, backend probes, or policy events.

## Parameter boundaries

`observe-telemetry` is PX4 SITL only:

- `--backend` must be `px4_sitl`.
- `--backend-mode` must be `sitl`.
- `--backend-enabled` must be set, otherwise the command returns a structured rejection.
- `--transport-endpoint` is preserved exactly and should use `udpin:...`; do not rewrite it to `udp://...`.
- `--duration-s` must be between `1` and `3600`.
- `--rate-hz` must be between `0.2` and `50`.
- NaN / Infinity telemetry values are sanitized before becoming view-model values.
- Output directories are created when writing JSON/JSONL/CSV files.
- The command must not open real hardware mode.

## Start PX4 with Gazebo GUI

```bash
cd ~/PX4-Autopilot
make px4_sitl gz_x500
```

Gazebo GUI should show the x500 model. Headless PX4 can also publish telemetry, but GUI is useful for visually confirming takeoff and landing.

## Confirm backend connectivity

```bash
python -m uav_runtime.console.cli check-backend \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --connect-timeout-ms 5000 \
  --pretty
```

Expected readiness remains `backend_connected` / `ready` when PX4 is publishing the onboard MAVLink endpoint.

## Single-process telemetry observation

Use this mode when no other process is consuming `udpin:127.0.0.1:14540`.

```bash
python -m uav_runtime.console.cli observe-telemetry \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --duration-s 10 \
  --rate-hz 5 \
  --pretty
```

Optional file outputs:

```bash
python -m uav_runtime.console.cli observe-telemetry \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --duration-s 30 \
  --rate-hz 5 \
  --output-json ~/px4_offline_bundle/uav_runtime/sitl_validation/telemetry_summary.json \
  --output-jsonl ~/px4_offline_bundle/uav_runtime/sitl_validation/telemetry_samples.jsonl \
  --output-csv ~/px4_offline_bundle/uav_runtime/sitl_validation/telemetry_samples.csv \
  --pretty
```

## Parallel observation during smoke-takeoff

Do not force two independent processes to listen on the same UDP endpoint. The runtime smoke-takeoff flow already uses:

```text
udpin:127.0.0.1:14540
```

Standalone telemetry observation uses the authoritative offboard endpoint only
when Runtime and other listeners are stopped:

```bash
python -m uav_runtime.console.cli observe-telemetry \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --duration-s 30 \
  --rate-hz 5 \
  --pretty
```

Inside Runtime, telemetry is now a subscriber to the Registry-owned shared
session. Do not run this standalone command concurrently with Runtime on the
same `udpin` endpoint.

## How to verify telemetry correctness

During a takeoff smoke run:

- `connected` should be `true` after HEARTBEAT.
- `source_message_counts.LOCAL_POSITION_NED` should increase if the local position stream is available.
- `z_down_m` should become negative as the vehicle climbs.
- `altitude_m` should rise because it is computed as `max(0.0, -z_down_m)`.
- `max_altitude_m` in the summary should exceed `2.1` for a 3 m smoke with `threshold_ratio=0.7`.
- `attitude.roll_deg`, `attitude.pitch_deg`, and `attitude.yaw_deg` should have numeric values after `ATTITUDE` messages arrive.
- `last_command_ack` should contain command/result metadata if COMMAND_ACK is observed.

## Non-goals

Telemetry Bridge v0.1 does not implement frontend screens, WebSocket streaming, databases, Agent/GPT control, LLM prompts, multi-vehicle routing, waypoint missions, real aircraft control, QGroundControl requirements, payload control, dangerous actions, or Policy Gate bypasses.
