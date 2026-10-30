"""The simulation topology must preserve the existing three-aircraft mapping."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SIM_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(SIM_DIR))

import harness  # noqa: E402
import onboard_topology  # noqa: E402


def _inputs() -> tuple[dict, dict]:
    topology = json.loads(onboard_topology.DEFAULT_TOPOLOGY.read_text(encoding="utf-8"))
    manifest = harness.load_manifest(harness.resolve_repo_path(onboard_topology.SIMULATION_MANIFEST))
    return topology, manifest


def test_uav02_is_only_onboard_receiver_and_endpoints_are_unchanged() -> None:
    topology, manifest = _inputs()
    result = onboard_topology.validate_topology(topology, manifest)
    assert [(row["node_id"], row["owner"], row["endpoint"]) for row in result["bindings"]] == [
        ("UAV-01", "ground_runtime", "udpin:127.0.0.1:14540"),
        ("UAV-02", "onboard_agent", "udpin:127.0.0.1:14541"),
        ("UAV-03", "ground_runtime", "udpin:127.0.0.1:14542"),
    ]


@pytest.mark.parametrize("mutation,reason", [
    (lambda t: t["command_owner"].update({"UAV-01": "onboard_agent"}), "command_owner_mismatch"),
    (lambda t: t["fault_domain"].update({"link": "onboard_agent_to_px4"}), "fault_scope_mismatch"),
    (lambda t: t["fault_domain"].update({"preserved_links": ["onboard_agent_to_camera"]}),
     "px4_or_sensor_link_not_preserved"),
    (lambda t: t["onboard_inputs"].update({"camera_image_topic": "/world/pose/info"}),
     "onboard_sensor_input_mismatch"),
    (lambda t: t["evaluation_only"].remove("gazebo_world_pose"), "oracle_boundary_mismatch"),
])
def test_unsafe_topology_is_rejected(mutation, reason: str) -> None:
    topology, manifest = _inputs()
    unsafe = copy.deepcopy(topology)
    mutation(unsafe)
    with pytest.raises(onboard_topology.TopologyError, match=reason):
        onboard_topology.validate_topology(unsafe, manifest)
