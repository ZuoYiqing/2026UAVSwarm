# PX4 / Gazebo Visual Observation Runbook

## 1) Purpose and Boundary

This runbook explains how to visually observe local PX4 SITL + Gazebo Harmonic `gz_x500` behavior.
It is only for local simulation observability and validation method alignment.

Non-goals:

- no frontend page;
- no Agent / GPT control;
- no multi-vehicle simulation;
- no real UAV;
- no payload / drop / release / strike / attack capability;
- no policy or protocol change.

---

## 2) Headless vs GUI

### Headless

```bash
HEADLESS=1 make px4_sitl gz_x500
```

This starts PX4 SITL and Gazebo simulation backend without showing the Gazebo graphical window.
It is useful for CI-like local runs, SSH sessions, and command-line smoke validation.

### GUI

```bash
make px4_sitl gz_x500
```

This attempts to start Gazebo with its graphical interface. If WSLg / desktop display is available, the Gazebo GUI should open and show the `x500` model in the simulation world.

If the GUI does not appear, check:

- `DISPLAY`;
- `WAYLAND_DISPLAY`;
- WSLg availability / Windows graphics integration;
- whether another Gazebo process is already running;
- GPU / Mesa / Gazebo Harmonic installation state.

---

## 3) Starting Gazebo GUI

Stop the current PX4 instance from `pxh>`:

```text
pxh> logger stop
pxh> shutdown
```

Start GUI mode:

```bash
cd ~/PX4-Autopilot
make px4_sitl gz_x500
```

Start headless mode again when GUI is not needed:

```bash
HEADLESS=1 make px4_sitl gz_x500
```

---

## 4) How to Tell the Vehicle Actually Took Off

Use more than one signal when possible:

1. **Gazebo GUI**
   - The `x500` model should visibly leave the ground.
   - You can observe the vehicle height changing in the 3D world.

2. **runtime action_result**
   - Check `arm_ack`, `takeoff_ack`, and `land_ack` for accepted ACKs.
   - Check `max_altitude_m`, `threshold_altitude_m`, `threshold_reached`, and `result`.

3. **MAVLink telemetry**
   - Use `scripts/px4_sitl_observe.py` to observe `LOCAL_POSITION_NED`.
   - PX4 NED `z` is positive down; altitude is `max(0.0, -z)`.

Do not rely on `COMMAND_ACK` alone. ACK means PX4 accepted a command; it does not prove the action completed.

---

## 5) Optional QGroundControl Observation Path

QGroundControl provides a ground-station view:

- map icon;
- attitude;
- mode;
- armed state;
- altitude;
- telemetry status.

Gazebo provides the physical simulation-world view.
QGC is not required for this stage, but it can become a useful later observation tool.

In WSL / Windows setups, QGC connection to port `14550` may require extra network configuration. For now, QGC is documented as optional and is not a validation dependency.
