"""Semantic binding to physical entities; no flight path or invented waypoint."""
import unittest

from uavswarm_llm_lab.scene_binding import bind_scene_reference


def fixture():
    def building(name, north, east, height):
        return {"object_id": name, "kind": "building", "frame": "scene_ned",
                "center_north_m": north, "center_east_m": east,
                "size_north_m": 40.0, "size_east_m": 70.0, "height_m": height,
                "physics_status": "imported_with_collision", "source": "world.sdf"}

    return {
        "status": "exported_from_physics_pending_review",
        "scene_identity": {"scene_id": "simple_recon_v0_1",
                           "map_version": "simple_recon_v0_1-map-1",
                           "public_frame": "scene_ned"},
        "coverage": {"complete_physical_map": False},
        "obstacle_cluster": {"summary_id": "city-block-4-3", "object_count": 3,
                             "center_north_m": 350.0, "center_east_m": -10.0,
                             "extent_north_m": [268.0, 432.0],
                             "extent_east_m": [-199.75, 179.75], "source": "world.sdf",
                             "bearing_from_origin": "北"},
        "obstacles": [building("B-1", 350.0, -73.25, 41.0),
                      building("B-2", 350.0, 53.25, 52.0),
                      building("B-3", 432.0, 179.75, 52.0)],
    }


class SceneBindingTest(unittest.TestCase):
    def test_north_cluster_east_side_uses_coordinates_not_bearing_as_exact(self):
        result = bind_scene_reference("飞到北边那片楼群的东侧", fixture())
        self.assertEqual(result["status"], "grounded_requires_planning")
        self.assertEqual(result["reason_code"], "ROUTE_PLANNING_REQUIRED")
        binding = result["bindings"][0]
        self.assertEqual(binding["target_id"], "city-block-4-3")
        self.assertEqual(binding["relation"], "east_side")
        self.assertEqual(binding["reference_geometry"]["center_east_m"], -10.0)
        self.assertEqual(binding["matched_text"], "楼群的东侧")
        self.assertIsNone(result["proposal"])
        self.assertFalse(result["execution_ready"])

    def test_circumnavigate_requires_route_planner(self):
        result = bind_scene_reference("绕楼群一圈", fixture())
        self.assertEqual(result["bindings"][0]["relation"], "circumnavigate")
        self.assertIsNone(result["proposal"])

    def test_tallest_tie_requires_clarification(self):
        result = bind_scene_reference("到最高的那栋楼旁边", fixture())
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason_code"], "AMBIGUOUS_HIGHEST_BUILDING")
        self.assertEqual({item["target_id"] for item in result["candidates"]},
                         {"B-2", "B-3"})
        self.assertEqual(result["bindings"], [])

    def test_explicit_id_grounded_but_not_flight_waypoint(self):
        result = bind_scene_reference("到 B-2 旁边", fixture())
        self.assertEqual(result["bindings"][0]["target_id"], "B-2")
        self.assertEqual(result["bindings"][0]["reference_geometry"]["height_m"], 52.0)
        self.assertIsNone(result["proposal"])

    def test_unknown_and_wrong_direction_require_clarification(self):
        self.assertEqual(bind_scene_reference("到山谷东侧", fixture())["reason_code"],
                         "SCENE_REFERENCE_UNRESOLVED")
        self.assertEqual(bind_scene_reference("飞到楼群西侧", fixture())["reason_code"],
                         "SPATIAL_RELATION_UNSUPPORTED")
        self.assertEqual(bind_scene_reference("到南边楼群", fixture())["reason_code"],
                         "DIRECTION_REFERENCE_MISMATCH")
        wrong_bearing = fixture()
        wrong_bearing["obstacle_cluster"]["center_east_m"] = -150.0
        self.assertEqual(bind_scene_reference("到北边楼群", wrong_bearing)["reason_code"],
                         "DIRECTION_REFERENCE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
