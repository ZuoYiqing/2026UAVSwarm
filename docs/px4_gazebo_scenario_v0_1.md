# PX4 / Gazebo Scenario v0.1

## 1. Scope and design judgment

PX4 / Gazebo Scenario v0.1 defines a **single-vehicle simulation scenario metadata contract**. The goal is not to create a complex city or a multi-agent planner; it is to provide one stable scene description that Gazebo, `uav_runtime`, the frontend console, and future Agent planning code can all reference.

This phase stays single-vehicle because PX4 SITL, telemetry, smoke-takeoff, and runtime validation are already proven for one `gz_x500`. Adding multi-vehicle orchestration before the shared metadata contract would mix scenario semantics with networking, session sharing, and fleet scheduling problems.

Non-goals in this phase:

- No multi-vehicle simulation.
- No multi-Agent planning.
- No real aircraft.
- No strike, drop, release, or dangerous payload actions.
- No frontend page changes.
- No HTTP API changes.
- No Policy Gate bypass.

## 2. Scene metadata contract

The canonical metadata lives at:

```text
scenarios/simple_recon_v0_1/scene.json
```

`scene.json` is a shared contract, not a Gazebo-only artifact. It describes:

- `scene_id`, `name`, and coordinate `frame`.
- Geographic `origin` for local-frame anchoring.
- `home` position.
- one or more `vehicles` with stable `node_id` values.
- `targets` for reconnaissance objectives.
- `obstacles` such as simple buildings.
- `no_fly_zones` for future policy/safety overlays.
- `mission_areas` for frontend/Agent mission context.
- `map_assets` pointers for the optional Gazebo world and a future frontend map export.

The current scenario uses `frame: local_ned`, and `map_assets` records that the Gazebo world and future frontend map may be separate exported formats from the same source metadata. Gazebo owns physics/collision/visual simulation; the frontend owns command-and-control display overlays. The current scenario uses `frame: local_ned`. PX4 telemetry uses `LOCAL_POSITION_NED`, where `x_m` and `y_m` are local meters and `z` is positive-down. The scene metadata keeps its local meter positions explicit; frontend rendering can map these values into its own ENU, Three.js, or map coordinate convention later.

Important altitude convention:

- PX4 telemetry altitude remains derived from NED as `altitude_m = max(0.0, -z_down_m)`.
- `scene.json` obstacle and marker `z_m` fields are scene geometry positions in meters, not flight altitude authorization.
- No-fly-zone `min_alt_m` and `max_alt_m` are metadata for later policy/display use and are not enforced in this phase.

## 3. Gazebo world file

A minimal optional world is provided at:

```text
scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf
```

It includes:

- ground plane.
- sun.
- `building-001` as a box marker.
- `target-001-marker` as a low green cylinder.
- `nfz-001-marker` as a red cylinder visual marker.

The x500 vehicle is still spawned by PX4. The world file does not modify PX4 default model logic and does not replace the known-good `make px4_sitl gz_x500` path.

Gazebo GUI visualization is useful for human observation, but it is not required for the telemetry data chain: Gazebo server, PX4, MAVLink telemetry, and `uav_runtime` validation can remain healthy even when WSLg GUI display has issues.

Default proven launch remains:

```bash
cd ~/PX4-Autopilot
make px4_sitl gz_x500
```

Optional world launch is intentionally documented as a manual/TODO path because PX4 world selection depends on the local PX4/Gazebo setup:

1. Copy or symlink `scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf` into a PX4/Gazebo resource path.
2. Start PX4 SITL with the equivalent local world-selection mechanism supported by the checked-out PX4 version.
3. Confirm that PX4 still spawns `gz_x500` and the scene markers are visible if GUI display is available; otherwise confirm PX4 and telemetry readiness from CLI outputs.

TODO: once the local PX4 world-selection command is finalized, document the exact command alongside the proven default `gz_x500` startup.

## 4. Scene validator

Validate the scene metadata with:

```bash
python scripts/validate_scene.py scenarios/simple_recon_v0_1/scene.json --pretty
```

Expected summary fields:

- `scene_id`
- `vehicle_count`
- `target_count`
- `obstacle_count`
- `no_fly_zone_count`
- `mission_area_count`
- `validation_result`

The validator checks required fields, unique IDs, and finite non-negative radii/sizes/heights where applicable. It rejects `NaN` and `Infinity` so invalid numeric values cannot leak into RuntimeSnapshot or frontend displays.

## 5. Telemetry / frontend / Agent alignment

Do not force scene fields into `PX4TelemetrySnapshot`. The intended composition for future RuntimeSnapshot is:

```text
TelemetryLatest
+ SceneMetadata
+ ActionResultView
+ EventEnvelope
=> RuntimeSnapshot
```

Initial alignment rules:

- `node_id`: the scenario uses `UAV-01`, matching the single PX4 x500 node used in telemetry and frontend examples.
- `scene_id`: `simple_recon_v0_1` should be carried by future snapshot or mission context metadata.
- `map_assets.gazebo_world` and `map_assets.frontend_map_hint` allow Gazebo and frontend maps to share source metadata while using different output formats.
- `local_position.x_m` / `local_position.y_m` / `altitude_m` can be rendered against the `scene.json` local coordinate frame.
- No-fly zones and mission areas are display/planning metadata in v0.1; they do not authorize or block actions by themselves.
- Future Agent planning may reference targets and mission areas, but all executable actions must still pass Capability Registry, Policy Gate, and Runtime execution checks.

## 6. Manual validation steps

1. Start default PX4/Gazebo GUI:

```bash
cd ~/PX4-Autopilot
make px4_sitl gz_x500
```

2. Confirm backend readiness:

```bash
python -m uav_runtime.console.cli check-backend \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --connect-timeout-ms 5000 \
  --pretty
```

3. Validate scenario metadata:

```bash
python scripts/validate_scene.py scenarios/simple_recon_v0_1/scene.json --pretty
```

4. Optionally inspect the world file in a local Gazebo/PX4 resource path without changing PX4 core models.

## 7. Next phase suggestions

- Add a read-only scenario listing API after the HTTP console contract stabilizes.
- Add RuntimeSnapshot composition that joins `TelemetryLatest` with `SceneMetadata` for `UAV-01`.
- Document the exact PX4 command for launching `simple_recon_v0_1.sdf` once verified locally.
- Add optional frontend overlay support for target, obstacle, no-fly-zone, and mission-area markers.
