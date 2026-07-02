# PX4 SITL backend_connected Validation Log

## 1) Purpose and Boundary

This document records the completed local PX4 SITL `backend_connected` readiness validation.
It is a readiness/probe record only:

- no `takeoff`;
- no `arm`;
- no `set_mode`;
- no `command_long`;
- no multi-vehicle setup;
- no QGroundControl dependency;
- no policy/protocol/adapter contract change.

`backend_connected` means the `px4_sitl_backend` could complete the minimum pymavlink connection / heartbeat probe. It does **not** mean any flight-control action has been executed.

---

## 2) Environment

| Item | Value |
| --- | --- |
| Host environment | WSL Ubuntu 22.04.4 |
| PX4 commit | `171f0f38cffa95f28d5e159f7aaf7599756f9e0e` |
| Gazebo | `8.14.0` |
| PX4 model / target | `gz_x500` |
| Runtime dependency | `pymavlink` installed and able to receive heartbeat |

---

## 3) PX4 SITL Startup Command

Run PX4 SITL independently from the `uav_runtime` process:

```bash
HEADLESS=1 make px4_sitl gz_x500
```

Expected PX4 state for this readiness validation:

- PX4 reaches the `pxh>` prompt;
- Gazebo Harmonic launches the `gz_x500` simulation;
- MAVLink endpoints are printed in the PX4 startup log.

---

## 4) PX4 MAVLink Ports Observed

Observed PX4 MAVLink lines:

| MAVLink instance | PX4 local UDP port | Remote port | Notes |
| --- | ---: | ---: | --- |
| Normal | `18570` | `14550` | Common GCS-facing stream |
| Onboard | `14580` | `14540` | Runtime/pymavlink should listen on `14540` |
| Onboard | `14280` | `14030` | Additional onboard-style stream |
| Gimbal | `13030` | `13280` | Gimbal-related stream |

Important endpoint interpretation:

- PX4 prints `udp port 14580 remote port 14540` for the Onboard stream.
- In this setup, PX4 sends MAVLink traffic to remote port `14540`.
- The external pymavlink client should therefore bind/listen on `14540`.
- The verified pymavlink connection string is `udpin:127.0.0.1:14540` or `udpin:0.0.0.0:14540`.

---

## 5) Raw pymavlink Test

Verified raw pymavlink heartbeat probe:

```text
udpin:127.0.0.1:14540 -> OK heartbeat
```

This confirms that the endpoint semantics are listener-style `udpin`, not the previously attempted `udp://` URL-style endpoint.

---

## 6) uav_runtime check-backend Command

Verified command:

```bash
python -m uav_runtime.console.cli check-backend \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --connect-timeout-ms 5000 \
  --pretty
```

Verified alternate listener endpoint:

```bash
python -m uav_runtime.console.cli check-backend \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:0.0.0.0:14540 \
  --connect-timeout-ms 5000 \
  --pretty
```

Observed result:

```text
connect_probe.code = backend_connected
readiness = ready
```

Minimum acceptance criteria satisfied:

- `code=backend_connected`;
- `readiness=ready`;
- `dependency.present=true`;
- `transport_endpoint_configured=true`.

---

## 7) Known Non-working Endpoint from This Validation

Known non-working endpoint in this WSL + PX4 SITL + Gazebo Harmonic validation:

```text
udp://127.0.0.1:14540 -> backend_probe_failed / connection_failed
```

Reason:

- `udp://127.0.0.1:14540` is not the endpoint form that matched the observed PX4 Onboard MAVLink stream in this validation.
- PX4 printed `udp port 14580 remote port 14540`, meaning PX4 is sending to remote port `14540`.
- The external pymavlink process must listen on that port, so the verified endpoint is `udpin:127.0.0.1:14540`.

---

## 8) Final Validation Status

| Check | Status |
| --- | --- |
| PX4 SITL starts with `HEADLESS=1 make px4_sitl gz_x500` | passed |
| PX4 reaches `pxh>` | passed |
| Raw pymavlink receives heartbeat from `udpin:127.0.0.1:14540` | passed |
| `uav_runtime check-backend` returns `backend_connected` | passed |
| `readiness=ready` | passed |
| Real takeoff / arm / set_mode / command_long | not in scope |

