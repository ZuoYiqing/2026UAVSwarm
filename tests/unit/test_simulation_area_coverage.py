import json
from pathlib import Path

import pytest

from simulation.px4_gazebo.area_coverage import AreaCoverage


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
    scene = json.loads(Path("scenarios/simple_recon_v0_1/scene.json").read_text(encoding="utf-8"))
    coverage = AreaCoverage(scene, "three-uav-patrol-coverage-v1", footprint_radius_m=10)
    assert coverage.report()["area_total_km2"] == pytest.approx(0.00475)
    with pytest.raises(ValueError, match="finite numbers"):
        coverage.observe(north_m=float("nan"), east_m=0)
    assert coverage.report()["sample_count"] == 0
