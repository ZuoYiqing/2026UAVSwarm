# PX4 / Gazebo Three-UAV Harness

This directory owns the repeatable local three-UAV SITL process harness. PX4
and Gazebo remain external engines under `~/PX4-Autopilot`; Runtime policy,
Agent planning and frontend code are outside this directory.

## Layout

```text
simulation/px4_gazebo/
|-- config/three_uav_sitl.json
|-- harness.py
`-- scripts/
    |-- start_three_uav.sh
    |-- stop_three_uav.sh
    |-- health_three_uav.py
    `-- validate_three_uav.py
```

The JSON manifest is the single implementation binding source for `node_id`,
PX4 instance, MAVLink system ID, Gazebo model, endpoint, spawn and runtime
directory. Scene semantics remain in `scenarios/simple_recon_v0_1/scene.json`.

## Quick Start in WSL

```bash
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
python3 simulation/px4_gazebo/scripts/health_three_uav.py --pretty
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

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
