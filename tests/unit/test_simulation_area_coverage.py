import json
from pathlib import Path

import pytest

from simulation.px4_gazebo.area_coverage import AreaCoverage


SCENE_PATH = Path("scenarios/simple_recon_v0_1/scene.json")
AREA_ID = "three-uav-patrol-coverage-v1"


def test_coverage_clips_to_polygon_and_never_double_counts() -> None:
    scene = {
        "scene_id": "fixture",
        "map_version": "fixture-map-1",
        "coverage_areas": [{
            "area_id": "test",
            "frame": "scene_ned",
            "cell_size_m": 1,
            "polygon": [
                {"north_m": 0, "east_m": 0},
                {"north_m": 2, "east_m": 0},
                {"north_m": 2, "east_m": 1},
                {"north_m": 1, "east_m": 1},
                {"north_m": 1, "east_m": 2},
                {"north_m": 0, "east_m": 2},
            ],
        }],
    }
    coverage = AreaCoverage(scene, "test", footprint_radius_m=1)
    assert coverage.report()["area_total_km2"] == pytest.approx(0.000003)
    assert coverage.report()["area_covered_km2"] == 0
    coverage.observe(north_m=1.5, east_m=1.5)
    assert coverage.report()["area_covered_km2"] == pytest.approx(0.000002)
    coverage.observe(north_m=1.5, east_m=1.5)
    coverage.observe(north_m=300, east_m=300)
    assert coverage.report()["area_covered_km2"] == pytest.approx(0.000002)
    coverage.observe(north_m=0.5, east_m=0.5)
    assert coverage.report()["completion_pct"] == 100


def test_demo_polygon_report_requires_finite_samples() -> None:
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    coverage = AreaCoverage(scene, AREA_ID, footprint_radius_m=10)
    assert coverage.report()["area_total_km2"] == pytest.approx(0.00475)
    with pytest.raises(ValueError, match="finite numbers"):
        coverage.observe(north_m=float("nan"), east_m=0)
    assert coverage.report()["sample_count"] == 0


def test_opt_in_grid_preserves_summary_and_aggregates_observed_cells() -> None:
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    coverage = AreaCoverage(scene, AREA_ID, footprint_radius_m=1)
    assert "grid" not in coverage.report()
    assert coverage.report(grid_cell_size_m=20)["grid"] is None
    coverage.observe(north_m=-45.5, east_m=-25.5)
    assert coverage.report(grid_cell_size_m=20)["grid"]["covered_cells"] == []

    points = [(-44.5, -24.5), (-44.5, -24.5), (0.5, 1.5), (49.5, 24.5)]
    for north, east in points:
        coverage.observe(north_m=north, east_m=east)
    report = coverage.report(grid_cell_size_m=20)
    grid = report.pop("grid")
    assert coverage.report() == report
    assert grid["scene_origin"] == {"reference": "scene_json.origin", **scene["origin"]}
    assert grid["grid_origin_ned_m"] == {"north_m": -45, "east_m": -25}
    assert (grid["rows"], grid["columns"]) == (5, 3)
    assert grid["covered_cells"] == [[0, 0, 3], [2, 1, 5], [4, 2, 3]]
    assert sum(row[2] for row in grid["covered_cells"]) / 1_000_000 == pytest.approx(report["area_covered_km2"])
    grid["covered_cells"][0][2] = 999
    assert coverage.report(grid_cell_size_m=20)["grid"]["covered_cells"][0] == [0, 0, 3]
    coverage.observe(north_m=49.5, east_m=-24.5)
    assert [4, 0, 3] in coverage.report(grid_cell_size_m=20)["grid"]["covered_cells"]


@pytest.mark.parametrize("size", [0, 9.9, 50.1, float("nan"), True])
def test_grid_rejects_sizes_outside_10_to_50_metres(size: float) -> None:
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    coverage = AreaCoverage(scene, AREA_ID, footprint_radius_m=1)
    with pytest.raises(ValueError):
        coverage.report(grid_cell_size_m=size)


def test_grid_is_bounded_for_an_eight_square_kilometre_zone() -> None:
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    area = scene["coverage_areas"][0]
    area["cell_size_m"] = 10
    area["polygon"] = [{"north_m": n, "east_m": e}
                       for n, e in [(0, 0), (4000, 0), (4000, 2000), (0, 2000)]]
    coverage = AreaCoverage(scene, AREA_ID, footprint_radius_m=2500)
    coverage.observe(north_m=2000, east_m=1000)
    assert coverage.report(grid_cell_size_m=10)["grid"] is None
    assert coverage.report(grid_cell_size_m=20)["area_covered_km2"] == pytest.approx(8)
    grid = coverage.report(grid_cell_size_m=20)["grid"]
    assert len(grid["covered_cells"]) == 20_000
    assert all(row[2] == 4 for row in grid["covered_cells"])
    assert len(json.dumps(grid, separators=(",", ":")).encode()) < 250_000
    assert len(coverage.report(grid_cell_size_m=50)["grid"]["covered_cells"]) == 3200


def test_grid_is_unavailable_without_a_valid_scene_origin() -> None:
    scene = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    del scene["origin"]
    coverage = AreaCoverage(scene, AREA_ID, footprint_radius_m=1)
    coverage.observe(north_m=0, east_m=0)
    report = coverage.report(grid_cell_size_m=20)
    assert report["area_covered_km2"] > 0
    assert report["grid"] is None
