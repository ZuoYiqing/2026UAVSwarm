# PX4 Runtime Action v0.1

## 1) Scope

PX4 runtime action v0.1 adds a SITL-only runtime smoke command for the already validated PX4 SITL takeoff path.
It converts the temporary pymavlink smoke procedure into a controlled `uav_runtime` CLI path:

```text
smoke-takeoff
-> Policy Gate
-> PX4 SITL backend/session
-> MAVLink GCS heartbeat
-> ARM
-> TAKEOFF
-> altitude observation
-> optional LAND
-> action_result JSON
-> audit/replay JSONL event
```

This is not a complete mission planner and not real-aircraft support.

---

## 2) CLI

Manual SITL verification command:

```bash
python -m uav_runtime.console.cli smoke-takeoff \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --altitude-m 3 \
  --connect-timeout-ms 5000 \
  --command-timeout-ms 10000 \
  --observe-timeout-ms 25000 \
  --auto-land \
  --pretty
```

PX4 must already be running:

```bash
HEADLESS=1 make px4_sitl gz_x500
```

Correct endpoint remains `udpin:127.0.0.1:14540`.

---

## 3) Safety Boundaries

- Real MAVLink ARM / TAKEOFF / LAND is restricted to `backend_mode=sitl`.
- `--backend-enabled` must be set for SITL command execution.
- The command still goes through Policy Gate before any backend command is sent.
- No policy/protocol contract change is introduced by this CLI smoke path.
- No real UAV, waypoint, multi-vehicle, GUI, QGroundControl, payload, release, drop, deploy, strike, or attack behavior is enabled.
- PX4 safety checks are not disabled or bypassed.

---

## 4) Session / Heartbeat Design

The PX4 session keeps a pymavlink connection for the smoke action and starts a GCS heartbeat loop before ARM.
This is required because the manual smoke found ARM can return `TEMPORARILY_REJECTED` without a continuous GCS heartbeat.

Session responsibilities:

- wait PX4 heartbeat;
- start GCS heartbeat loop;
- stop GCS heartbeat loop on completion or failure;
- request `LOCAL_POSITION_NED` with `MAV_CMD_SET_MESSAGE_INTERVAL`;
- send ARM / TAKEOFF / LAND command_long messages;
- wait `COMMAND_ACK`;
- observe `LOCAL_POSITION_NED` altitude;
- clean up the heartbeat thread.

---

## 5) action_result Fields

`smoke-takeoff` returns JSON with at least:

- `action`;
- `backend`;
- `backend_mode`;
- `endpoint`;
- `policy_decision`;
- `heartbeat_connected`;
- `gcs_heartbeat_started`;
- `local_position_stream_requested`;
- `arm_ack`;
- `takeoff_ack`;
- `land_ack`;
- `target_altitude_m`;
- `max_altitude_m`;
- `threshold_ratio`;
- `threshold_altitude_m`;
- `threshold_reached`;
- `auto_land`;
- `result`;
- `failure_reason` when failed.

ACK objects include:

- `command`;
- `command_name` when known;
- `result`;
- `result_name`;
- `timeout`.

---

## 6) Audit / Replay

The CLI writes:

1. the normal `policy_decision_event` from RuntimeOrchestrator;
2. a `px4_sitl_smoke_takeoff` event containing:
   - timestamp;
   - endpoint;
   - backend and backend_mode;
   - policy decision;
   - MAVLink commands sent;
   - ACK objects;
   - altitude observation summary;
   - max altitude;
   - threshold result;
   - final result and failure reason.

Existing replay reads JSONL events generically, so this event can be inspected without adding GUI work.

---

## 7) Non-goals

- No real UAV.
- No multi-vehicle orchestration.
- No waypoint mission upload.
- No return_home / hold_position implementation.
- No QGroundControl dependency.
- No payload/device control expansion.
- No dangerous payload, release, strike, drop, or deploy action.
- No policy bypass.
