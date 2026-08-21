# PX4 / Gazebo Three-UAV Harness

This directory owns the repeatable local three-UAV SITL process harness. PX4
and Gazebo remain external engines under `~/PX4-Autopilot`; Runtime policy,
Agent planning and frontend code are outside this directory.

## Layout

```text
simulation/px4_gazebo/
|-- config/three_uav_sitl.json
|-- harness.py
|-- health.py
|-- patrol.py
`-- scripts/
    |-- start_three_uav.sh
    |-- stop_three_uav.sh
    |-- health_three_uav.py
    |-- patrol_three_uav.py
    `-- validate_three_uav.py
```

The reusable acceptance route and criteria live with the scenario at
`scenarios/simple_recon_v0_1/missions/three_uav_patrol_v0_1.json`; the
standalone controller remains under this simulation directory.

The JSON manifest is the single implementation binding source for `node_id`,
PX4 instance, MAVLink system ID, Gazebo model, endpoint, spawn and runtime
directory. Scene semantics remain in `scenarios/simple_recon_v0_1/scene.json`.

## Quick Start in WSL

```bash
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
python3 simulation/px4_gazebo/scripts/health_three_uav.py --pretty
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
python3 simulation/px4_gazebo/scripts/patrol_three_uav.py --pretty
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

`validate_three_uav.py` is the retained per-node ARM/TAKEOFF/LAND isolation
regression. `patrol_three_uav.py` is an acceptance-only three-aircraft patrol:
it requires exclusive ownership of all three Runtime/PX4 MAVLink endpoints,
flies three fixed NED corridors, checks each waypoint and inter-vehicle
separation, lands/disarms every aircraft, and writes JSON evidence. Stop
Runtime before either standalone validator; integrated actions remain owned by
Runtime and Policy Gate.

Patrol geometry, obstacle checks, no-fly checks and separation use the shared
`scene_ned` frame. Each public waypoint is transformed into the target
aircraft's `vehicle_local_ned` frame before `SET_POSITION_TARGET_LOCAL_NED` is
sent. Raw PX4 `LOCAL_POSITION_NED` is transformed back into `scene_ned` before
any cross-vehicle calculation. Spawn translation and yaw rotation are both
part of this transform.

Health has two explicit modes. `--mode standalone` directly probes MAVLink and
requires Runtime to be stopped. `--mode integrated --runtime-telemetry <json>`
never opens ports 14540-14542; it combines Gazebo/process evidence with the
node telemetry status supplied by Runtime.

Use `--gui` instead of `--headless` when WSLg and Gazebo GUI are available.
Override the external PX4 checkout without editing the manifest:

```bash
PX4_AUTOPILOT_DIR=/path/to/PX4-Autopilot \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
```

Runtime logs, PID files and validation JSON are written under
`.runtime/px4_gazebo/` and are intentionally ignored by Git.

Detailed operation and troubleshooting:
[PX4_GAZEBO_3UAV_RUNBOOK_ZH-CN.md](../../docs/simulation/PX4_GAZEBO_3UAV_RUNBOOK_ZH-CN.md).
