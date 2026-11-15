"""Mission-owned S7 grid through the Runtime producer, with no flight transport."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uav_runtime.agent.executor import StepOutcome
from uav_runtime.http import routes
from uav_runtime.http.mission_progress import MissionProgress
from tests.unit.test_runtime_action_lifecycle import install_registry
from tests.unit.test_runtime_ground_completion import publish_context


SCENE = Path(__file__).resolve().parents[2] / "scenarios" / "simple_recon_v0_1" / "scene.json"
PROGRESS = "/api/mission/progress"


def exercise_current_mission(request, monkeypatch, tmp_path):
    """Use real plan/progress handlers and replace only the action transport."""
    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    registry, store = install_registry(monkeypatch)
    registry.scene = scene
    calibration, _ = publish_context(store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "plan.audit.jsonl"))
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", None)
    monkeypatch.setenv("UAV_RUNTIME_COVERAGE_AREA_ID", "three-uav-patrol-coverage-v1")
    monkeypatch.setenv("UAV_RUNTIME_COVERAGE_FOOTPRINT_M", "10")
    unavailable = request("GET", PROGRESS)
    observed = []
    points = [(60, 40), (15, -20), (30, -20), (-10, 20)]

    def execute(step):
        observed.append(request("GET", PROGRESS))
        i = len(observed) - 1
        north, east = points[i]
        matched = {**calibration, "session_position_epoch": 1}
        if i == 3:
            matched["map_version"] = "foreign-map"
        return StepOutcome(ok=True, action_type="goto", node_id=step.node_id, raw={
            "result": "pass", "arrival_observed": True, "arrival_calibration": matched,
            "completion_evidence": {"start_sequence": i, "position_sample": {
                "north": north, "east": east - 8, "sequence": i + 1, "position_epoch": 1,
            }},
        })

    monkeypatch.setattr(routes, "RealActionExecutor", lambda **kwargs: SimpleNamespace(execute_step=execute))
    plan = {"plan_id": "r3-coverage-api-check", "scene_id": scene["scene_id"], "map_version": scene["map_version"],
            "steps": [{"step_id": f"wp{i}", "action_type": "goto", "node_id": "UAV-02", "params": {}}
                      for i in range(len(points))]}
    result = request("POST", "/api/plans/execute", {"plan": plan, "operator_id": "fixture-operator", "decision": "approve"})
    assert result["result"] == "completed"
    return unavailable, observed, request("GET", PROGRESS)


def test_grid_is_from_this_plan_run_and_uses_only_qualified_samples(monkeypatch, tmp_path):
    def request(method, path, body=None):
        status, payload = routes.dispatch(method, path, body=body)
        assert status == 200, payload
        return payload

    unavailable, (starting, outside, in_area, before_mismatch), finished = exercise_current_mission(
        request, monkeypatch, tmp_path)
    assert unavailable["coverage"] is None
    assert starting["coverage"]["grid"] is None and starting["coverage"]["sample_count"] == 0
    assert outside["coverage"]["grid"]["covered_cells"] == []
    assert outside["coverage"]["sample_count"] == 1
    assert in_area["coverage"]["grid"]["covered_cells"]
    assert finished["coverage"] == before_mismatch["coverage"]
    assert finished["coverage"]["sample_count"] == 3
    assert finished["waypoints_reached"] == 4 and finished["completion_pct"] == 100
    assert finished["status"] == "completed"
    for payload in (starting, outside, in_area, before_mismatch):
        assert payload["mission_id"] == finished["mission_id"]
        assert payload["run_id"] == finished["run_id"]
    grid = finished["coverage"]["grid"]
    assert grid["rows"] * grid["columns"] <= 25_000
    assert (grid["scene_id"], grid["map_version"]) == (finished["scene_id"], finished["map_version"])
    assert sum(cell[2] for cell in grid["covered_cells"]) * grid["source_cell_size_m"] ** 2 / 1e6 == pytest.approx(
        finished["area_covered_km2"])


@pytest.mark.parametrize("provider_version", ["legacy", "grid-error", "over-budget"])
def test_missing_display_grid_preserves_existing_area_report(provider_version):
    from simulation.px4_gazebo.area_coverage import AreaCoverage

    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    area = scene["coverage_areas"][0]
    if provider_version == "over-budget":
        area = deepcopy(area)
        area.update(cell_size_m=20, polygon=[{"north_m": n, "east_m": e}
                                            for n, e in [(0, 0), (3200, 0), (3200, 3200), (0, 3200)]])
        scene["coverage_areas"] = [area]
    provider = AreaCoverage(scene, area["area_id"], footprint_radius_m=10)
    provider.observe(north_m=10, east_m=10)
    baseline = provider.report()

    def grid_error(**kwargs):
        if kwargs:
            raise ValueError("optional display grid unavailable")
        return baseline

    coverage = (provider if provider_version == "over-budget" else SimpleNamespace(
        report=grid_error if provider_version == "grid-error" else lambda: baseline))
    progress = MissionProgress(None, SimpleNamespace(plan_id="grid-unavailable", steps=[]),
                               scene_id=scene["scene_id"], map_version=scene["map_version"],
                               coverage=coverage)
    payload = progress.snapshot()
    assert payload["coverage"] == {**baseline, "grid": None}
    assert payload["area_covered_km2"] == baseline["area_covered_km2"]
