# PX4 Runtime Takeoff Action Integration Plan

## 1) Goal

The next stage is to turn the validated SITL-only pymavlink takeoff smoke into the smallest safe runtime action path:

```text
uav_runtime action takeoff
-> Policy Gate
-> PX4 adapter/backend
-> MAVLink ARM/TAKEOFF
-> action_result
-> audit/replay
```

This is still a PX4 SITL integration plan. It is not a real-aircraft plan.

---

## 2) Minimal Action Scope

In scope for the first runtime integration:

| Action | Scope |
| --- | --- |
| `takeoff` | SITL-only ARM + TAKEOFF + altitude observation |
| `land` | SITL-only LAND command and ACK/result capture |

Out of scope:

- waypoint missions;
- multi-vehicle takeoff;
- real UAVs;
- QGroundControl integration;
- GUI changes;
- payload control;
- dangerous payload / release / strike / drop / deploy actions;
- complex mission planning.

---

## 3) Required Safety Boundaries

The runtime implementation must preserve these gates:

1. **SITL-only command execution**
   - Real MAVLink ARM/TAKEOFF/LAND may only be enabled when `backend_mode=sitl`.
   - Default real-hardware backend behavior must remain disabled / unsupported.

2. **Policy Gate remains mandatory**
   - `takeoff` must pass Policy Gate before the PX4 backend sends any command.
   - No backend path may bypass policy decisions.

3. **Explicit action support**
   - `takeoff` and `land` must be the only real command actions in the first integration.
   - Unsupported actions must continue returning stable unsupported / placeholder results.

4. **No unsafe payload expansion**
   - This plan does not open payload release, strike, attack, drop, deploy, or weaponized behavior.

---

## 4) Backend Session Requirements

The validated smoke showed that PX4 can temporarily reject ARM when no continuous GCS heartbeat is present.
Therefore the runtime/backend design should:

- maintain a GCS/companion heartbeat thread or session while connected to PX4;
- reuse a backend session instead of creating a fresh short-lived connection for every command;
- expose heartbeat/session status in action result details;
- close or clean up the session deterministically when runtime shuts down or the test ends.

---

## 5) Command and Observation Requirements

The first implementation should capture enough evidence for audit/replay:

| Item | Requirement |
| --- | --- |
| Endpoint | Record `transport_endpoint`, e.g. `udpin:127.0.0.1:14540` |
| Command sequence | Record ARM / TAKEOFF / LAND commands sent |
| ACK | Record MAVLink ACK result for each command |
| Altitude observation | Record whether `LOCAL_POSITION_NED` was observed |
| Max altitude | Record `max_altitude_m` |
| Threshold | Record whether the smoke threshold was reached |
| Final result | Return stable `action_result` fields |

The action result should include enough detail to diagnose failures such as:

- heartbeat missing;
- ARM rejected;
- TAKEOFF rejected;
- no local position stream;
- altitude threshold not reached;
- LAND rejected or timed out.

---

## 6) Configurability

Keep the first implementation small but configurable:

| Setting | Purpose |
| --- | --- |
| `command_ack_timeout_ms` | Timeout for ARM / TAKEOFF / LAND ACK wait |
| `local_position_timeout_ms` | Timeout for `LOCAL_POSITION_NED` observation |
| `takeoff_altitude_m` | Requested takeoff altitude |
| `takeoff_threshold_m` | Minimum altitude rise needed for smoke pass |
| `heartbeat_period_s` | GCS heartbeat interval |
| `connect_timeout_ms` | Existing backend heartbeat/probe timeout |

Defaults should remain conservative and SITL-focused.

---

## 7) Suggested Minimal Implementation Order

1. Add PX4 backend session object that can maintain GCS heartbeat.
2. Add SITL-only real command path for `land` first or as a cleanup helper.
3. Add SITL-only real command path for `takeoff`:
   - wait heartbeat;
   - start/ensure GCS heartbeat;
   - request local position stream;
   - ARM;
   - TAKEOFF;
   - observe altitude threshold;
   - LAND cleanup if required.
4. Return structured `action_result` with ACKs and altitude evidence.
5. Write audit events with endpoint, commands, ACKs, altitude observation, and final result.
6. Add integration tests using mocks/stubs for command ACK handling, without requiring real PX4 in CI.
7. Keep manual PX4 SITL smoke runbook as the real-environment acceptance test.

---

## 8) Non-goals

- No real UAV control.
- No multi-vehicle scheduling.
- No waypoint mission execution.
- No QGroundControl dependency.
- No GUI.
- No protocol contract change unless a later design explicitly requires it.
- No policy bypass.
- No dangerous payload or weaponized capability.


---

## 9) v0.1 Implementation Entry Point

The initial runtime entry point is the SITL-only CLI command:

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

The command performs Policy Gate evaluation before the PX4 backend sends ARM / TAKEOFF / LAND.
It remains SITL-only and is documented in `docs/px4_runtime_takeoff_action_v0_1.md`.
