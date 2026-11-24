"""Check the offline navigation example against the scene and world sources."""

import json
import math
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest

from simulation.px4_gazebo.patrol import PositionNED, _point_conflict_reason, _segment_samples


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "docs/simulation/fixtures/simple_recon_v0_1_target_001_navigation_v1.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def scene_xyz(position):
    return position["north_m"], position["east_m"], position["down_m"]


def legacy_xyz(position):
    return position["x_m"], position["y_m"], position["z_m"]


def unrotated_pose(element):
    pose = tuple(map(float, element.findtext("pose", "0 0 0 0 0 0").split()))
    assert pose[3:] == (0, 0, 0)
    east, north, up = pose[:3]
    return north, east, -up


@pytest.fixture
def navigation():
    fixture = load_json(FIXTURE)
    scene = load_json(ROOT / fixture["sources"]["scene"])
    world = ElementTree.parse(ROOT / fixture["sources"]["world"]).getroot().find("world")
    assert world is not None
    return fixture, scene, world


def test_geometry_and_identity_match_scene_world_and_manifests(navigation):
    fixture, scene, world = navigation
    identity = fixture["scene_identity"]
    assert identity["scene_id"] == scene["scene_id"] == world.attrib["name"]
    assert identity["map_version"] == scene["map_version"]
    assert identity["frame"] == scene["public_frame"] == "scene_ned"
    assert identity["units"] == "m"
    origin = world.find("spherical_coordinates")
    assert origin.findtext("world_frame_orientation") == "ENU"
    assert identity["origin"] == scene["origin"] == {
        "lat_deg": float(origin.findtext("latitude_deg")),
        "lon_deg": float(origin.findtext("longitude_deg")),
        "alt_m": float(origin.findtext("elevation")),
    }
    models = {model.attrib["name"]: model for model in world.findall("model")}
    ground = fixture["ground"]
    ground_model = models[ground["object_id"]]
    plane = ground_model.find("link/collision/geometry/plane")
    assert plane.findtext("normal").split() == ["0", "0", "1"]
    assert unrotated_pose(ground_model) == (0, 0, ground["surface_down_m"])
    assert tuple(map(float, plane.findtext("size").split())) == (
        ground["size_east_m"], ground["size_north_m"],
    )

    target = fixture["target"]
    declared_target = next(item for item in scene["targets"] if item["target_id"] == target["object_id"])
    marker = models[target["gazebo_model"]]
    marker_cylinder = marker.find("link/visual/geometry/cylinder")
    north, east, down = unrotated_pose(marker)
    reference_down = down + float(marker_cylinder.findtext("length")) / 2
    assert scene_xyz(target["reference"]) == legacy_xyz(declared_target["position"]) == (north, east, reference_down)
    assert target["radius_m"] == declared_target["radius_m"] == float(marker_cylinder.findtext("radius"))
    assert target["collision"] is False and marker.find(".//collision") is None

    for box in fixture["obstacles"]:
        declared = next(item for item in scene["obstacles"] if item["obstacle_id"] == box["object_id"])
        model = models[box["object_id"]]
        size = model.findtext("link/collision/geometry/box/size")
        east, north, up = map(float, size.split())
        assert scene_xyz(box["center"]) == legacy_xyz(declared["position"]) == unrotated_pose(model)
        assert scene_xyz(box["size"]) == tuple(declared["size_m"][axis] for axis in ("x", "y", "z")) == (north, east, up)
        assert box["collision"] is True

    for zone in fixture["no_fly_zones"]:
        declared = next(item for item in scene["no_fly_zones"] if item["zone_id"] == zone["object_id"])
        model = models[zone["gazebo_model"]]
        cylinder = model.find("link/visual/geometry/cylinder")
        north, east, down = unrotated_pose(model)
        half_height = float(cylinder.findtext("length")) / 2
        assert scene_xyz(zone["center"]) == legacy_xyz(declared["center"]) == (north, east, down + half_height)
        assert zone["radius_m"] == declared["radius_m"] == float(cylinder.findtext("radius"))
        assert zone["down_min_m"] == -declared["max_alt_m"] == down - half_height
        assert zone["down_max_m"] == -declared["min_alt_m"] == down + half_height
        assert zone["collision"] is False and model.find(".//collision") is None

    scene_spawns = {v["node_id"]: legacy_xyz(v["initial_pose"]) for v in scene["vehicles"]}
    fixture_spawns = {v["node_id"]: scene_xyz(v["position"]) for v in fixture["spawns"]}
    assert scene_spawns == fixture_spawns
    for source in ("default_manifest", "camera_manifest"):
        manifest = load_json(ROOT / fixture["sources"][source])
        assert manifest["scene_id"] == identity["scene_id"] and manifest["map_version"] == identity["map_version"]
        assert {v["node_id"]: legacy_xyz(v["spawn_ned"]) for v in manifest["vehicles"]} == fixture_spawns
    for spawn in fixture["spawns"]:
        pad = models[spawn["pad_id"]]
        north, east, down = unrotated_pose(pad)
        thickness = float(pad.findtext("link/visual/geometry/cylinder/length"))
        assert scene_xyz(spawn["position"]) == (north, east, down + thickness / 2)
        assert pad.find(".//collision") is None


def test_city_collision_boxes_are_outside_the_local_scope(navigation):
    fixture, scene, world = navigation
    scope = fixture["scope"]
    bounds = scope["centerline_bounds"]
    area = next(item for item in scene["coverage_areas"] if item["area_id"] == scope["coverage_area_id"])
    assert {
        (p["north_m"], p["east_m"]) for p in area["polygon"]
    } == {
        (n, e) for n in (bounds["north_min_m"], bounds["north_max_m"])
        for e in (bounds["east_min_m"], bounds["east_max_m"])
    }
    export = load_json(ROOT / fixture["sources"]["city_geometry"])
    exported = {item["object_id"]: item for item in export["obstacles"]}
    city = world.find("model[@name='city-block-4-3']")
    assert unrotated_pose(city) == (0, 0, 0)
    assert set(exported) == {link.attrib["name"] for link in city.findall("link")}
    for link in city.findall("link"):
        box = exported[link.attrib["name"]]
        north, east, down = unrotated_pose(link)
        size_east, size_north, height = map(float, link.findtext("collision/geometry/box/size").split())
        assert (box["center_north_m"], box["center_east_m"]) == (north, east)
        assert (box["size_north_m"], box["size_east_m"], box["height_m"]) == (size_north, size_east, height)
        assert (box["base_down_m"], box["top_down_m"]) == (down + height / 2, down - height / 2)
        assert north - size_north / 2 > bounds["north_max_m"] + fixture["reference_navigation"]["static_check_margin_m"]
    assert scope["complete_physical_map"] is False
    assert {
        model.attrib["name"] for model in world.findall("model")
        if model.find(".//collision") is not None
    } == {fixture["ground"]["object_id"], "city-block-4-3", *(box["object_id"] for box in fixture["obstacles"])}
    assert {item["obstacle_id"] for item in scene["obstacles"]} == {box["object_id"] for box in fixture["obstacles"]}
    assert {item["zone_id"] for item in scene["no_fly_zones"]} == {z["object_id"] for z in fixture["no_fly_zones"]}


def test_reference_route_clearance_and_blocked_shortcuts(navigation):
    fixture, scene, _ = navigation
    route = fixture["reference_navigation"]
    spawns = {v["node_id"]: PositionNED(*scene_xyz(v["position"])) for v in fixture["spawns"]}
    spawn = spawns.pop(route["node_id"])
    takeoff = PositionNED(spawn.x_m, spawn.y_m, spawn.z_m - route["takeoff_height_m"])
    waypoints = [PositionNED(*scene_xyz(point)) for point in route["waypoints"]]
    goal = waypoints[route["target_waypoint_index"]]
    assert route["target_id"] == fixture["target"]["object_id"]
    assert (goal.x_m, goal.y_m) == scene_xyz(fixture["target"]["reference"])[:2]
    assert all(point.z_m == takeoff.z_m for point in waypoints)
    assert route["arrival_tolerance_m"] <= fixture["target"]["radius_m"]
    assert route["arrival_tolerance_m"] <= route["static_check_margin_m"]

    # Any point on a segment is within half the sample spacing of a tested point.
    # Inflate boxes and cylinders by that amount in addition to the example margin.
    spacing = 0.25
    margin = route["static_check_margin_m"] + spacing / 2
    expanded_scene = deepcopy(scene)
    for box in expanded_scene["obstacles"]:
        for axis in ("x", "y", "z"):
            box["size_m"][axis] += 2 * margin
    for zone in expanded_scene["no_fly_zones"]:
        zone["radius_m"] += margin
        zone["min_alt_m"] -= margin
        zone["max_alt_m"] += margin
    bounds = fixture["scope"]["centerline_bounds"]
    vertices = [spawn, takeoff, *waypoints]
    for start, end in zip(vertices, vertices[1:]):
        for point in [start, *_segment_samples(start, end, step_m=spacing)]:
            assert bounds["north_min_m"] <= point.x_m <= bounds["north_max_m"]
            assert bounds["east_min_m"] <= point.y_m <= bounds["east_max_m"]
            assert _point_conflict_reason(point, expanded_scene) is None
            assert all(math.dist((point.x_m, point.y_m), (p.x_m, p.y_m)) > margin for p in spawns.values())

    assert _point_conflict_reason(takeoff, scene) is None and _point_conflict_reason(goal, scene) is None
    shortcut = _segment_samples(takeoff, goal, step_m=spacing)
    assert "no_fly_zone:nfz-001" in {_point_conflict_reason(point, scene) for point in shortcut}
    over_building = _segment_samples(PositionNED(0, 0, -6), PositionNED(30, 0, -6), step_m=spacing)
    assert "obstacle:building-001" in {_point_conflict_reason(point, scene) for point in over_building}
