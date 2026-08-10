"""PX4/Gazebo scenario metadata v0.1 tests."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from uav_runtime.scenario.scene_schema import SceneValidationError, load_and_validate_scene, load_scene, validate_scene

SCENE_PATH = Path("scenarios/simple_recon_v0_1/scene.json")


def _valid_scene() -> dict[str, object]:
    return load_scene(SCENE_PATH)


def test_scene_json_can_be_read_and_has_scene_id() -> None:
    scene = load_scene(SCENE_PATH)

    assert scene["scene_id"] == "simple_recon_v0_1"
    assert scene["frame"] == "local_ned"
    assert scene["map_assets"]["gazebo_world"] == "worlds/simple_recon_v0_1.sdf"


def test_scene_has_at_least_one_vehicle() -> None:
    _, summary = load_and_validate_scene(SCENE_PATH)

    assert summary.vehicle_count >= 1
    assert summary.validation_result == "pass"


def test_node_ids_are_unique() -> None:
    scene = _valid_scene()
    duplicate = copy.deepcopy(scene["vehicles"][0])  # type: ignore[index]
    scene["vehicles"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(SceneValidationError, match="duplicate node_id"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_target_ids_are_unique() -> None:
    scene = _valid_scene()
    duplicate = copy.deepcopy(scene["targets"][0])  # type: ignore[index]
    scene["targets"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(SceneValidationError, match="duplicate target_id"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_obstacle_ids_are_unique() -> None:
    scene = _valid_scene()
    duplicate = copy.deepcopy(scene["obstacles"][0])  # type: ignore[index]
    scene["obstacles"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(SceneValidationError, match="duplicate obstacle_id"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_zone_ids_are_unique() -> None:
    scene = _valid_scene()
    duplicate = copy.deepcopy(scene["no_fly_zones"][0])  # type: ignore[index]
    scene["no_fly_zones"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(SceneValidationError, match="duplicate zone_id"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_no_fly_zone_radius_must_be_non_negative() -> None:
    scene = _valid_scene()
    scene["no_fly_zones"][0]["radius_m"] = -1  # type: ignore[index]

    with pytest.raises(SceneValidationError, match="radius_m must be non-negative"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_obstacle_size_must_be_non_negative() -> None:
    scene = _valid_scene()
    scene["obstacles"][0]["size_m"]["z"] = -10  # type: ignore[index]

    with pytest.raises(SceneValidationError, match="size_m.z must be non-negative"):
        validate_scene(scene)  # type: ignore[arg-type]


def test_nan_and_infinity_are_rejected(tmp_path: Path) -> None:
    nan_scene = _valid_scene()
    nan_scene["targets"][0]["radius_m"] = float("nan")  # type: ignore[index]
    with pytest.raises(SceneValidationError, match="must be finite"):
        validate_scene(nan_scene)  # type: ignore[arg-type]

    inf_scene = _valid_scene()
    inf_scene["no_fly_zones"][0]["max_alt_m"] = float("inf")  # type: ignore[index]
    with pytest.raises(SceneValidationError, match="must be finite"):
        validate_scene(inf_scene)  # type: ignore[arg-type]

    # JSON constants can appear in hand-authored files even though they are not
    # portable strict JSON; the loader plus validator still rejects them.
    bad_json = tmp_path / "bad_scene.json"
    raw = json.dumps(_valid_scene()).replace('"radius_m": 3', '"radius_m": NaN', 1)
    bad_json.write_text(raw, encoding="utf-8")
    with pytest.raises(SceneValidationError, match="must be finite"):
        load_and_validate_scene(bad_json)


def test_validate_scene_cli_outputs_summary() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_scene.py", str(SCENE_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["scene_id"] == "simple_recon_v0_1"
    assert payload["vehicle_count"] == 3
    assert payload["target_count"] == 1
    assert payload["obstacle_count"] == 1
    assert payload["no_fly_zone_count"] == 1
    assert payload["validation_result"] == "pass"
