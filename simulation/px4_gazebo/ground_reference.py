"""Conservative ground-plane evidence for the simple reconnaissance world."""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from typing import Any

try:
    from . import harness
except ImportError:  # Direct script execution adds this directory to sys.path.
    import harness  # type: ignore


SUPPORTED_SCENE = "simple_recon_v0_1"
SUPPORTED_MAP = "simple_recon_v0_1-map-1"
SUPPORTED_WORLD = "simple_recon_v0_1"


def _zero_pose(element: ET.Element) -> bool:
    pose = element.find("pose")
    if pose is None:
        return True
    if pose.attrib:
        return False
    raw = pose.text
    if raw is None:
        return False
    try:
        values = [float(value) for value in raw.split()]
    except ValueError:
        return False
    return len(values) == 6 and all(math.isfinite(value) and abs(value) < 1e-9 for value in values)


def _only_named(parent: ET.Element, tag: str, name: str) -> ET.Element:
    matches = [row for row in parent.findall(tag) if row.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"ground_reference_{tag}_missing_or_duplicate")
    return matches[0]


def _positive_pair(raw: str | None) -> tuple[float, float]:
    try:
        values = [float(value) for value in (raw or "").split()]
    except ValueError as exc:
        raise ValueError("ground_reference_plane_size_invalid") from exc
    if len(values) != 2 or not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("ground_reference_plane_size_invalid")
    return values[0], values[1]


def from_managed_world(manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Describe only the known flat collision plane bound to this harness run.

    This is geometry evidence, not landing permission or live contact evidence.
    A missing startup digest (older runs) or changed world file fails closed.
    """
    if (manifest.get("scene_id"), manifest.get("map_version"), manifest.get("world_name")) != (
        SUPPORTED_SCENE, SUPPORTED_MAP, SUPPORTED_WORLD
    ):
        raise ValueError("ground_reference_scene_unsupported")
    world_path = harness.resolve_repo_path(str(manifest["world_path"])).resolve()
    scene_path = harness.resolve_repo_path(str(manifest["scene_path"]))
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    if (scene.get("scene_id"), scene.get("map_version"), scene.get("public_frame")) != (
        SUPPORTED_SCENE, SUPPORTED_MAP, "scene_ned"
    ):
        raise ValueError("ground_reference_scene_mismatch")
    if state.get("world_name") != SUPPORTED_WORLD or state.get("world_path") != str(world_path):
        raise ValueError("ground_reference_run_world_mismatch")
    world_bytes = world_path.read_bytes()
    digest = hashlib.sha256(world_bytes).hexdigest()
    if state.get("world_sha256") != digest:
        raise ValueError("ground_reference_run_world_hash_mismatch")

    try:
        root = ET.fromstring(world_bytes)
    except ET.ParseError as exc:
        raise ValueError("ground_reference_world_xml_invalid") from exc
    world = _only_named(root, "world", SUPPORTED_WORLD)
    model = _only_named(world, "model", "ground_plane")
    if model.findtext("static") != "true":
        raise ValueError("ground_reference_not_static")
    link = _only_named(model, "link", "link")
    collision = _only_named(link, "collision", "collision")
    if not all(_zero_pose(row) for row in (model, link, collision)):
        raise ValueError("ground_reference_pose_unsupported")
    if len(link.findall("collision")) != 1:
        raise ValueError("ground_reference_collision_ambiguous")
    plane = collision.find("geometry/plane")
    if plane is None or plane.findtext("normal") != "0 0 1":
        raise ValueError("ground_reference_plane_unsupported")
    east_size_m, north_size_m = _positive_pair(plane.findtext("size"))
    return {
        "contract_version": "1.0",
        "scene_id": SUPPORTED_SCENE,
        "map_version": SUPPORTED_MAP,
        "world_sha256": digest,
        "frame": "scene_ned",
        "kind": "horizontal_plane",
        "ground_down_m": 0.0,
        "source": "world_collision_geometry",
        "surface_id": "ground_plane",
        "xy_bounds_m": {
            "north_min_m": -north_size_m / 2,
            "north_max_m": north_size_m / 2,
            "east_min_m": -east_size_m / 2,
            "east_max_m": east_size_m / 2,
        },
    }
