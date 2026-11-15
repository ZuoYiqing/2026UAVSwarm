"""Validate the simulation-side ownership and fault boundary for UAV-02.

This is a deployment plan, not a Runtime route or an agent implementation.
The sole MAVLink receiver and application transport are supplied by Runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from . import harness
except ImportError:  # Direct script execution.
    import harness  # type: ignore


DEFAULT_TOPOLOGY = Path(__file__).resolve().parent / "config/uav02_onboard_topology_v0_1.json"
SIMULATION_MANIFEST = "simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json"
OWNERS = {"UAV-01": "ground_runtime", "UAV-02": "onboard_agent", "UAV-03": "ground_runtime"}
PRESERVED_LINKS = {"onboard_agent_to_px4", "onboard_agent_to_camera"}
EVALUATION_ONLY = {
    "gazebo_world_pose", "gazebo_target_ground_truth", "gazebo_derived_scene_calibration"
}


class TopologyError(ValueError):
    pass


def validate_topology(topology: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Return bindings derived from the existing SITL manifest; never remap ports."""
    if topology.get("version") != "0.1":
        raise TopologyError("topology_version_unsupported")
    if set(topology) != {
        "version", "simulation_manifest", "scene_id", "map_version",
        "command_owner", "fault_domain", "onboard_inputs", "evaluation_only",
    }:
        raise TopologyError("topology_fields_invalid")
    if topology.get("simulation_manifest") != SIMULATION_MANIFEST:
        raise TopologyError("simulation_manifest_mismatch")
    if (topology.get("scene_id"), topology.get("map_version")) != (
        manifest["scene_id"], manifest["map_version"]
    ):
        raise TopologyError("scene_or_map_version_mismatch")
    if topology.get("command_owner") != OWNERS:
        raise TopologyError("command_owner_mismatch")
    fault = topology.get("fault_domain")
    if not isinstance(fault, dict) or fault.get("node_id") != "UAV-02":
        raise TopologyError("fault_target_mismatch")
    if set(fault) != {"node_id", "link", "preserved_links"}:
        raise TopologyError("fault_fields_invalid")
    if fault.get("link") != "ground_runtime_to_onboard_agent":
        raise TopologyError("fault_scope_mismatch")
    preserved = fault.get("preserved_links")
    if (not isinstance(preserved, list) or len(preserved) != len(PRESERVED_LINKS)
            or not all(isinstance(item, str) for item in preserved)
            or set(preserved) != PRESERVED_LINKS):
        raise TopologyError("px4_or_sensor_link_not_preserved")
    if set(topology.get("evaluation_only") or []) != EVALUATION_ONLY:
        raise TopologyError("oracle_boundary_mismatch")

    vehicles = {row["node_id"]: row for row in manifest["vehicles"]}
    if len(vehicles) != len(manifest["vehicles"]) or set(vehicles) != set(OWNERS):
        raise TopologyError("vehicle_set_mismatch")
    if any(int(vehicles[node]["system_id"]) != number for node, number in
           (("UAV-01", 1), ("UAV-02", 2), ("UAV-03", 3))):
        raise TopologyError("system_id_mismatch")
    endpoints = [vehicles[node]["command_endpoint"] for node in OWNERS]
    if endpoints != [f"udpin:127.0.0.1:{port}" for port in (14540, 14541, 14542)]:
        raise TopologyError("endpoint_mismatch")
    if any(int(vehicles[node]["component_id"]) != 1 for node in OWNERS):
        raise TopologyError("component_id_mismatch")
    target = vehicles["UAV-02"]
    world = manifest["world_name"]
    model = target["gazebo_model_name"]
    if model != "x500_mono_cam_1":
        raise TopologyError("camera_model_mismatch")
    topic_root = f"/world/{world}/model/{model}/link/camera_link/sensor/camera"
    if topology.get("onboard_inputs") != {
        "px4_telemetry": "owned_mavlink_session",
        "camera_image_topic": f"{topic_root}/image",
        "camera_info_topic": f"{topic_root}/camera_info",
    }:
        raise TopologyError("onboard_sensor_input_mismatch")
    return {
        "version": topology["version"],
        "scene_id": manifest["scene_id"],
        "map_version": manifest["map_version"],
        "fault_domain": fault["link"],
        "bindings": [
            {
                "node_id": node,
                "owner": OWNERS[node],
                "system_id": vehicles[node]["system_id"],
                "component_id": vehicles[node]["component_id"],
                "endpoint": vehicles[node]["command_endpoint"],
                "gazebo_model": vehicles[node]["gazebo_model_name"],
            }
            for node in OWNERS
        ],
    }


def load_topology(path: Path = DEFAULT_TOPOLOGY) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TopologyError("topology_root_invalid")
    manifest = harness.load_manifest(harness.resolve_repo_path(SIMULATION_MANIFEST))
    return validate_topology(raw, manifest)
