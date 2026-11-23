import json
from pathlib import Path
from xml.etree import ElementTree

import pytest


SCENARIO = Path(__file__).resolve().parents[2] / "scenarios/simple_recon_v0_1"


def test_catalog_geometry_covers_the_versioned_scene():
    catalog = json.loads((SCENARIO / "entity_catalog.json").read_text(encoding="utf-8"))
    scene = json.loads((SCENARIO / "scene.json").read_text(encoding="utf-8"))
    world = ElementTree.parse(SCENARIO / scene["map_assets"]["gazebo_world"]).find("world")
    assert (catalog["scene_id"], catalog["map_version"], catalog["frame"], catalog["origin"]) == (
        scene["scene_id"], scene["map_version"], scene["public_frame"], scene["origin"],
    )
    ids = [entry["entity_id"] for entry in catalog["catalog"]]
    geometry = catalog["geometry_by_entity_id"]
    assert len(ids) == len(set(ids)) == len(geometry) == 27
    assert set(ids) == geometry.keys()
    for entry in catalog["catalog"]:
        assert set(entry) == {"entity_id", "label", "aliases", "exclusive_group"}

    cluster = world.find("model[@name='city-block-4-3']")
    building_links = {"building-001": world.find("model[@name='building-001']")}
    building_links.update({link.attrib["name"]: link for link in cluster.findall("link")})
    assert {key for key, row in geometry.items() if row["kind"] == "building"} == building_links.keys()
    assert set(geometry["city-block-4-3"]["member_ids"]) == building_links.keys() - {"building-001"}
    for entity_id, link in building_links.items():
        e, n, up, roll, pitch, yaw = map(float, link.findtext("pose").split())
        assert roll == pitch == yaw == 0
        box = geometry[entity_id]["geometry"]
        assert box["center"] == {"north_m": n, "east_m": e, "down_m": -up}
        collision = link.find(".//collision/geometry/box")
        east, north, height = map(float, collision.findtext("size").split())
        assert box["size_m"] == {"north": north, "east": east, "vertical": height}
        if entity_id != "building-001":
            extents = geometry["city-block-4-3"]["geometry"]["horizontal_bounds"]
            assert extents["north_min_m"] <= n - north / 2 <= n + north / 2 <= extents["north_max_m"]
            assert extents["east_min_m"] <= e - east / 2 <= e + east / 2 <= extents["east_max_m"]

    for collection, key, kind in (
        ("targets", "target_id", "visual_target_marker"), ("mission_areas", "area_id", "mission_area"),
        ("coverage_areas", "area_id", "coverage_area"), ("no_fly_zones", "zone_id", "no_fly_zone"),
    ):
        assert {object_id for object_id, row in geometry.items() if row["kind"] == kind} == {
            row[key] for row in scene[collection]
        }
    coverage = geometry[scene["coverage_areas"][0]["area_id"]]["geometry"]
    assert coverage["vertices"] == scene["coverage_areas"][0]["polygon"]
    for vehicle in scene["vehicles"]:
        pad = geometry[f"landing-pad-{vehicle['node_id']}"]["geometry"]
        spawn = vehicle["initial_pose"]
        assert pad["base_center"] == {"north_m": spawn["x_m"], "east_m": spawn["y_m"], "down_m": spawn["z_m"]}
        assert pad["radius_m"] == pytest.approx(1.5)

    slots = catalog["demo_slot_ids"]
    candidate_ids = {*slots["distinct_inspection_candidates"], *slots["same_name_candidates"],
                     *slots["exclusive_candidates"], slots["reference_only_candidate"]}
    assert len(candidate_ids) == 7 and candidate_ids <= geometry.keys()
    assert all(geometry[key]["source"] == "gazebo_visual" for key in candidate_ids - {"building-001", "target-001"})
    a, b = (geometry[key]["geometry"]["position"] for key in slots["same_name_candidates"])
    assert a != b
    west, east = (geometry[key]["geometry"]["horizontal_bounds"] for key in slots["exclusive_candidates"])
    assert west["east_max_m"] < east["east_min_m"]
    task = geometry["recon-area-001"]["geometry"]
    marker = geometry["target-001"]["geometry"]
    assert task["center"] == marker["base_center"]
    assert task["radius_m"] == 8 and marker["radius_m"] == 3


def test_display_slots_are_sdf_visuals_at_the_declared_poses_and_sizes():
    catalog = json.loads((SCENARIO / "entity_catalog.json").read_text(encoding="utf-8"))
    world = ElementTree.parse(SCENARIO / "worlds/simple_recon_v0_1.sdf").find("world")
    display_rows = {key: row for key, row in catalog["geometry_by_entity_id"].items() if "display" in row}
    assert set(display_rows) == {
        "demo-area-001", "demo-sector-001", "demo-sector-002", "demo-anchor-001", "demo-anchor-002",
    }
    for key, row in display_rows.items():
        geom, display = row["geometry"], row["display"]
        model = world.find(f"model[@name='{row['gazebo_model']}']")
        assert model is not None and model.findtext("static") == "true"
        assert model.find(".//collision") is None
        e, n, up, roll, pitch, yaw = map(float, model.findtext("pose").split())
        point = geom.get("center") or geom["position"]
        assert (e, n, up, roll, pitch, yaw) == (point["east_m"], point["north_m"], -point["down_m"], 0, 0, 0)
        visuals = {visual.attrib["name"]: visual for visual in model.findall("link/visual")}
        if display["kind"] == "ground_outline":
            assert visuals.keys() == {"north", "south", "east", "west"}
            bounds = geom["horizontal_bounds"]
            edges = []
            for visual in visuals.values():
                east, north, height, *_ = map(float, visual.findtext("pose").split())
                width, depth, thickness = map(float, visual.findtext("geometry/box/size").split())
                assert height + thickness / 2 == pytest.approx(display["height_m"])
                edges.append((e + east - width / 2, e + east + width / 2, n + north - depth / 2, n + north + depth / 2))
            assert min(edge[0] for edge in edges) == pytest.approx(bounds["east_min_m"])
            assert max(edge[1] for edge in edges) == pytest.approx(bounds["east_max_m"])
            assert min(edge[2] for edge in edges) == pytest.approx(bounds["north_min_m"])
            assert max(edge[3] for edge in edges) == pytest.approx(bounds["north_max_m"])
        else:
            assert display["kind"] == "numbered_post" and display["number"] == key[-3:]
            column = visuals["post"].find("geometry/cylinder")
            assert float(column.findtext("length")) == display["height_m"]
            assert float(column.findtext("radius")) == display["radius_m"]
            digits = {"0": "abcdef", "1": "bc", "2": "abdeg"}
            assert {name for name in visuals if name.startswith("number-")} == {
                f"number-{i}-{segment}" for i, digit in enumerate(display["number"]) for segment in digits[digit]
            }

    display = {key: row["display"] for key, row in display_rows.items()}
    assert display["demo-sector-001"]["color"] == display["demo-sector-002"]["color"]
    assert display["demo-anchor-001"]["color"] != display["demo-anchor-002"]["color"]
