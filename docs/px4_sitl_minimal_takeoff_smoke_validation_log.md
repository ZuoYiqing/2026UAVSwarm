# PX4 SITL Minimal Takeoff Smoke Validation Log

## 1) Purpose and Boundary

This document records the completed **minimal takeoff smoke** validation against local PX4 SITL.
It is a controlled SITL-only smoke record produced by a temporary pymavlink script.
It is **not** the final `uav_runtime` takeoff action implementation.

Current scope:

- PX4 SITL only;
- `gz_x500` only;
- one vehicle only;
- temporary pymavlink smoke script only;
- no real UAV;
- no multi-vehicle orchestration;
- no QGroundControl requirement;
- no protocol/policy contract change;
- no dangerous payload, release, strike, drop, or deploy action.

---

## 2) Environment

| Item | Value |
| --- | --- |
| Host environment | WSL Ubuntu 22.04.4 |
| PX4 commit | `171f0f38cffa95f28d5e159f7aaf7599756f9e0e` |
| Gazebo | `8.14.0` |
| PX4 model / target | `gz_x500` |
| Runtime commit | `aca6d40` |
| MAVLink endpoint | `udpin:127.0.0.1:14540` |

---

## 3) PX4 Startup Command

PX4 SITL was started independently from `uav_runtime`:

```bash
HEADLESS=1 make px4_sitl gz_x500
```

Pre-smoke readiness requirements:

- PX4 reaches the `pxh>` prompt;
- `uav_runtime check-backend` already returns `backend_connected` / `readiness=ready` with `udpin:127.0.0.1:14540`;
- pymavlink raw heartbeat test succeeds on `udpin:127.0.0.1:14540`.

---

## 4) Smoke Script Flow

The temporary pymavlink smoke followed this minimal sequence:

1. Wait for PX4 heartbeat.
2. Start continuous GCS heartbeat thread.
3. Request `LOCAL_POSITION_NED` stream via `MAV_CMD_SET_MESSAGE_INTERVAL`.
4. Send `MAV_CMD_COMPONENT_ARM_DISARM`.
5. Send `MAV_CMD_NAV_TAKEOFF` with target altitude `3m`.
6. Observe `LOCAL_POSITION_NED` and track altitude rise.
7. Send `MAV_CMD_NAV_LAND`.
8. Record ACKs, maximum observed altitude, threshold result, and final status.

---

## 5) Command ACK and Observation Results

| Step | Result |
| --- | --- |
| `MAV_CMD_SET_MESSAGE_INTERVAL LOCAL_POSITION_NED` | accepted |
| `MAV_CMD_COMPONENT_ARM_DISARM` | ACK `result=0` |
| `MAV_CMD_NAV_TAKEOFF` | ACK `result=0` |
| `LOCAL_POSITION_NED` altitude observation | altitude rise observed |
| `max_altitude_m` | `2.13` |
| `threshold_reached` | `True` |
| `MAV_CMD_NAV_LAND` | ACK `result=0` |
| Final smoke result | `RESULT=PASS` |

Interpretation:

- `result=0` means MAVLink command accepted by PX4 in this SITL run.
- `max_altitude_m=2.13` confirms the vehicle left the ground and altitude increased enough for this minimal smoke threshold.
- `RESULT=PASS` only applies to this local SITL smoke and does not imply real-aircraft readiness.

---

## 6) Known Issue: GCS Heartbeat Required for ARM

Observed issue:

- First ARM attempt returned `TEMPORARILY_REJECTED` when no continuous GCS heartbeat was sent.
- After adding a GCS heartbeat thread, ARM returned ACK `result=0` and the smoke passed.

Implication for the next runtime integration stage:

- PX4 runtime action support must maintain a companion/GCS heartbeat while sending ARM / TAKEOFF / LAND commands.
- The backend should not rely on a one-shot command connection that does not keep heartbeat alive.
- The action result should record heartbeat/session state so failures can be diagnosed in audit/replay.

---

## 7) Validation Conclusion

Minimal takeoff smoke status: **PASS**.

This validates that local PX4 SITL + Gazebo Harmonic + pymavlink can perform the minimum command sequence required for a future runtime `takeoff` action path:

```text
heartbeat -> GCS heartbeat -> position stream -> arm -> takeoff -> observe altitude -> land
```

It does not yet validate:

- `uav_runtime submit-action takeoff` real MAVLink execution;
- Policy Gate to real PX4 command closure;
- action_result / audit integration for ARM/TAKEOFF/LAND ACKs;
- multi-vehicle behavior;
- real hardware behavior.
