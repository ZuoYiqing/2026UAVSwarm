"""Deterministic tests for the manifest-driven three-UAV simulation harness."""
from __future__ import annotations

import copy
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HARNESS_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(HARNESS_DIR))

import harness


MANIFEST_PATH = HARNESS_DIR / "config" / "three_uav_sitl.json"
SCENE_PATH = Path("scenarios/simple_recon_v0_1/scene.json")
WORLD_PATH = Path("scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf")


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _scene() -> dict[str, object]:
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


def test_manifest_has_stable_three_vehicle_mapping() -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    rows = harness.mapping_rows(manifest)

    assert [row["node_id"] for row in rows] == ["UAV-01", "UAV-02", "UAV-03"]
    assert [row["px4_instance"] for row in rows] == [0, 1, 2]
    assert [row["system_id"] for row in rows] == [1, 2, 3]
    assert [row["gazebo_model_name"] for row in rows] == [
        "x500_0",
        "x500_1",
        "x500_2",
    ]
    assert [row["command_endpoint"] for row in rows] == [
        "udpin:127.0.0.1:14540",
        "udpin:127.0.0.1:14541",
        "udpin:127.0.0.1:14542",
    ]


def test_ned_to_gazebo_conversion_includes_yaw() -> None:
    pose = harness.ned_to_gazebo_pose(
        {"x_m": 12, "y_m": -4, "z_m": -3, "yaw_deg": 0}
    )

    assert pose.x_m == -4
    assert pose.y_m == 12
    assert pose.z_m == 3
    assert pose.yaw_rad == pytest.approx(math.pi / 2)

    east_facing = harness.ned_to_gazebo_pose(
        {"x_m": 0, "y_m": 0, "z_m": 0, "yaw_deg": 90}
    )
    assert east_facing.yaw_rad == pytest.approx(0)


def test_manifest_rejects_implicit_or_duplicate_identity() -> None:
    manifest = _manifest()
    manifest["vehicles"][1]["system_id"] = 1  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="must be unique: system_id"):
        harness.validate_manifest(manifest, scene=_scene())  # type: ignore[arg-type]


def test_manifest_rejects_endpoint_not_matching_px4_instance() -> None:
    manifest = _manifest()
    manifest["vehicles"][2]["command_endpoint"] = "udpin:127.0.0.1:14549"  # type: ignore[index]
    manifest["vehicles"][2]["telemetry_endpoint"] = "udpin:127.0.0.1:14549"  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="endpoint port must be 14542"):
        harness.validate_manifest(manifest, scene=_scene())  # type: ignore[arg-type]


def test_manifest_and_scene_spawns_must_match() -> None:
    manifest = _manifest()
    scene = copy.deepcopy(_scene())
    scene["vehicles"][1]["initial_pose"]["y_m"] = 9  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="spawn differs"):
        harness.validate_manifest(manifest, scene=scene)  # type: ignore[arg-type]


def test_health_requires_expected_unique_sysids_processes_and_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "processes": [
                    {"node_id": vehicle["node_id"], "pid": index + 100}
                    for index, vehicle in enumerate(manifest["vehicles"])
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(harness, "STATE_PATH", state_path)
    endpoint_to_sysid = {
        vehicle["telemetry_endpoint"]: vehicle["system_id"]
        for vehicle in manifest["vehicles"]
    }

    def heartbeat_probe(endpoint: str, timeout_s: float) -> dict[str, object]:
        del timeout_s
        return {
            "heartbeat_received": True,
            "observed_system_id": endpoint_to_sysid[endpoint],
            "last_heartbeat_age_s": 0.01,
            "error": None,
        }

    payload = harness.collect_health(
        manifest,
        timeout_s=0.1,
        heartbeat_probe=heartbeat_probe,
        process_probe=lambda pid: pid in {100, 101, 102},
        model_probe=lambda: {"x500_0", "x500_1", "x500_2"},
    )

    assert payload["ready"] is True
    assert payload["unique_system_ids"] is True
    assert all(row["readiness"] for row in payload["vehicles"])


def test_world_contains_aligned_pads_but_no_static_x500() -> None:
    root = ET.parse(WORLD_PATH).getroot()
    names = {
        model.attrib["name"]
        for model in root.findall("./world/model")
    }

    assert {
        "landing-pad-UAV-01",
        "landing-pad-UAV-02",
        "landing-pad-UAV-03",
        "building-001",
        "target-001-marker",
        "nfz-001-marker",
    }.issubset(names)
    assert not any(name.startswith("x500") for name in names)
