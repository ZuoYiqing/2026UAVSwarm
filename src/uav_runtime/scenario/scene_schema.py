"""Scene metadata loader and validator for PX4/Gazebo scenario contracts.

The scene schema is shared metadata for runtime, frontend, and agent planning.
It is not a Gazebo-only world file and it does not authorize any vehicle action.
PX4 telemetry remains LOCAL_POSITION_NED; scene coordinates use a local meter
frame that can be mapped into frontend coordinates later.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class SceneValidationError(ValueError):
    """Raised when a scene metadata file violates the v0.1 contract."""


@dataclass(slots=True)
class SceneSummary:
    """Serializable summary emitted by validation CLI and tests."""

    scene_id: str
    name: str
    frame: str
    vehicle_count: int
    target_count: int
    obstacle_count: int
    no_fly_zone_count: int
    mission_area_count: int
    validation_result: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_scene(path: str | Path) -> dict[str, Any]:
    """Load scene JSON without binding it to Gazebo-specific implementation."""
    scene_path = Path(path)
    with scene_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SceneValidationError("scene root must be a JSON object")
    return data


def validate_scene(scene: dict[str, Any]) -> SceneSummary:
    """Validate the shared scene contract, including multi-vehicle spawns.

    v0.1 intentionally validates metadata shape and safe numeric bounds only.
    It does not generate missions, bypass Policy Gate, or control PX4/Gazebo.
    """
    for key in ("scene_id", "name", "frame", "origin", "home", "vehicles", "targets", "obstacles", "no_fly_zones", "mission_areas", "map_assets"):
        if key not in scene:
            raise SceneValidationError(f"missing required field: {key}")

    # v0.1 downstream spawn, altitude, and safety geometry are defined in NED.
    # Reject ENU metadata until every consumer has an explicit frame conversion.
    if scene["frame"] != "local_ned":
        raise SceneValidationError("frame must be local_ned in v0.1")

    vehicles = _expect_list(scene, "vehicles")
    targets = _expect_list(scene, "targets")
    obstacles = _expect_list(scene, "obstacles")
    no_fly_zones = _expect_list(scene, "no_fly_zones")
    mission_areas = _expect_list(scene, "mission_areas")
    if not vehicles:
        raise SceneValidationError("vehicles must contain at least one vehicle")

    _unique_ids(vehicles, "node_id")
    _unique_ids(targets, "target_id")
    _unique_ids(obstacles, "obstacle_id")
    _unique_ids(no_fly_zones, "zone_id")
    _unique_ids(mission_areas, "area_id")

    _validate_origin(scene["origin"])
    _validate_xyz(scene["home"], context="home")
    _validate_map_assets(scene["map_assets"])
    minimum_spawn_separation_m = _non_negative_number(
        scene.get("minimum_spawn_separation_m", 0),
        context="minimum_spawn_separation_m",
    )
    for vehicle in vehicles:
        _validate_xyz(vehicle.get("initial_pose", {}), context=f"vehicle {vehicle.get('node_id')} initial_pose")
        _finite_number(vehicle.get("initial_pose", {}).get("yaw_deg", 0), context="vehicle yaw_deg")
    for target in targets:
        _validate_xyz(target.get("position", {}), context=f"target {target.get('target_id')} position")
        _non_negative_number(target.get("radius_m"), context=f"target {target.get('target_id')} radius_m")
    for obstacle in obstacles:
        _validate_xyz(obstacle.get("position", {}), context=f"obstacle {obstacle.get('obstacle_id')} position")
        size = obstacle.get("size_m", {})
        for axis in ("x", "y", "z"):
            _non_negative_number(size.get(axis), context=f"obstacle {obstacle.get('obstacle_id')} size_m.{axis}")
    for zone in no_fly_zones:
        _validate_xyz(zone.get("center", {}), context=f"zone {zone.get('zone_id')} center")
        _non_negative_number(zone.get("radius_m"), context=f"zone {zone.get('zone_id')} radius_m")
        min_alt = _non_negative_number(zone.get("min_alt_m"), context=f"zone {zone.get('zone_id')} min_alt_m")
        max_alt = _non_negative_number(zone.get("max_alt_m"), context=f"zone {zone.get('zone_id')} max_alt_m")
        if max_alt < min_alt:
            raise SceneValidationError(f"zone {zone.get('zone_id')} max_alt_m must be >= min_alt_m")
    for area in mission_areas:
        _validate_xyz(area.get("center", {}), context=f"area {area.get('area_id')} center")
        _non_negative_number(area.get("radius_m"), context=f"area {area.get('area_id')} radius_m")

    _validate_vehicle_spawns(
        vehicles,
        obstacles=obstacles,
        targets=targets,
        no_fly_zones=no_fly_zones,
        minimum_separation_m=minimum_spawn_separation_m,
    )

    return SceneSummary(
        scene_id=str(scene["scene_id"]),
        name=str(scene["name"]),
        frame=str(scene["frame"]),
        vehicle_count=len(vehicles),
        target_count=len(targets),
        obstacle_count=len(obstacles),
        no_fly_zone_count=len(no_fly_zones),
        mission_area_count=len(mission_areas),
    )


def load_and_validate_scene(path: str | Path) -> tuple[dict[str, Any], SceneSummary]:
    scene = load_scene(path)
    return scene, validate_scene(scene)


def _expect_list(scene: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = scene.get(key)
    if not isinstance(value, list):
        raise SceneValidationError(f"{key} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise SceneValidationError(f"{key} entries must be objects")
    return value


def _unique_ids(items: list[dict[str, Any]], key: str) -> None:
    seen: set[str] = set()
    for item in items:
        if key not in item:
            raise SceneValidationError(f"missing required id field: {key}")
        item_id = str(item[key])
        if item_id in seen:
            raise SceneValidationError(f"duplicate {key}: {item_id}")
        seen.add(item_id)


def _validate_origin(origin: Any) -> None:
    if not isinstance(origin, dict):
        raise SceneValidationError("origin must be an object")
    _finite_number(origin.get("lat_deg"), context="origin.lat_deg")
    _finite_number(origin.get("lon_deg"), context="origin.lon_deg")
    _finite_number(origin.get("alt_m"), context="origin.alt_m")


def _validate_xyz(value: Any, *, context: str) -> None:
    if not isinstance(value, dict):
        raise SceneValidationError(f"{context} must be an object")
    for key in ("x_m", "y_m", "z_m"):
        _finite_number(value.get(key), context=f"{context}.{key}")


def _validate_vehicle_spawns(
    vehicles: list[dict[str, Any]],
    *,
    obstacles: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    no_fly_zones: list[dict[str, Any]],
    minimum_separation_m: float,
) -> None:
    """Reject unsafe initial overlap without adding transport details to the scene."""
    for index, vehicle in enumerate(vehicles):
        node_id = str(vehicle["node_id"])
        pose = vehicle["initial_pose"]
        x_m = float(pose["x_m"])
        y_m = float(pose["y_m"])
        z_m = float(pose["z_m"])

        for other in vehicles[index + 1 :]:
            other_pose = other["initial_pose"]
            distance_m = math.dist(
                (x_m, y_m, z_m),
                (
                    float(other_pose["x_m"]),
                    float(other_pose["y_m"]),
                    float(other_pose["z_m"]),
                ),
            )
            if distance_m < minimum_separation_m:
                raise SceneValidationError(
                    f"vehicle spawn separation below minimum: {node_id} and "
                    f"{other['node_id']} are {distance_m:.3f}m apart"
                )

        for obstacle in obstacles:
            center = obstacle["position"]
            size = obstacle["size_m"]
            inside = all(
                abs(value - float(center[key])) <= float(size[axis]) / 2.0
                for value, key, axis in (
                    (x_m, "x_m", "x"),
                    (y_m, "y_m", "y"),
                    (z_m, "z_m", "z"),
                )
            )
            if inside:
                raise SceneValidationError(
                    f"vehicle {node_id} initial_pose overlaps obstacle {obstacle['obstacle_id']}"
                )

        for target in targets:
            center = target["position"]
            if math.dist((x_m, y_m), (float(center["x_m"]), float(center["y_m"]))) < float(target["radius_m"]):
                raise SceneValidationError(
                    f"vehicle {node_id} initial_pose overlaps target {target['target_id']}"
                )

        altitude_m = max(0.0, -z_m)
        for zone in no_fly_zones:
            center = zone["center"]
            horizontal_distance_m = math.dist(
                (x_m, y_m),
                (float(center["x_m"]), float(center["y_m"])),
            )
            inside_altitude = float(zone["min_alt_m"]) <= altitude_m <= float(zone["max_alt_m"])
            if horizontal_distance_m < float(zone["radius_m"]) and inside_altitude:
                raise SceneValidationError(
                    f"vehicle {node_id} initial_pose overlaps no-fly zone {zone['zone_id']}"
                )


def _finite_number(value: Any, *, context: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SceneValidationError(f"{context} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise SceneValidationError(f"{context} must be finite")
    return parsed


def _non_negative_number(value: Any, *, context: str) -> float:
    parsed = _finite_number(value, context=context)
    if parsed < 0:
        raise SceneValidationError(f"{context} must be non-negative")
    return parsed


def _validate_map_assets(map_assets: Any) -> None:
    if not isinstance(map_assets, dict):
        raise SceneValidationError("map_assets must be an object")
    gazebo_world = map_assets.get("gazebo_world")
    if not isinstance(gazebo_world, str) or not gazebo_world:
        raise SceneValidationError("map_assets.gazebo_world must be a non-empty string")
    frontend_map_hint = map_assets.get("frontend_map_hint")
    if frontend_map_hint is not None and not isinstance(frontend_map_hint, str):
        raise SceneValidationError("map_assets.frontend_map_hint must be a string when present")
