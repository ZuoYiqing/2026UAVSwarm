"""Bind a small set of scene references to supplied physical affordances.

Coordinates here identify objects. They are never navigation waypoints.
"""
from __future__ import annotations

import math

from .contracts import ContractError, digest


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_affordances(affordances: dict) -> tuple[dict, list[dict]]:
    if not isinstance(affordances, dict):
        raise ContractError("SCENE_AFFORDANCES_INVALID: expected object")
    identity = affordances.get("scene_identity")
    cluster = affordances.get("obstacle_cluster")
    obstacles = affordances.get("obstacles")
    if not isinstance(identity, dict) or not isinstance(cluster, dict) or not isinstance(obstacles, list):
        raise ContractError("SCENE_AFFORDANCES_INVALID: missing identity, cluster or obstacles")
    if identity.get("public_frame") != "scene_ned":
        raise ContractError("SCENE_FRAME_UNSUPPORTED")
    if not identity.get("scene_id") or not identity.get("map_version"):
        raise ContractError("SCENE_IDENTITY_MISSING")
    if affordances.get("status") not in {"exported_from_physics_pending_review", "reviewed"}:
        raise ContractError("SCENE_AFFORDANCES_STATUS_UNSUPPORTED")
    if (not obstacles or not cluster.get("summary_id") or
            not isinstance(cluster.get("source"), str) or not cluster["source"] or
            cluster.get("object_count") != len(obstacles)):
        raise ContractError("SCENE_CLUSTER_INCOMPLETE")
    for field in ("center_north_m", "center_east_m"):
        if not _finite(cluster.get(field)):
            raise ContractError("SCENE_CLUSTER_COORDINATE_INVALID:" + field)
    for field in ("extent_north_m", "extent_east_m"):
        extent = cluster.get(field)
        if (not isinstance(extent, list) or len(extent) != 2 or
                not all(_finite(value) for value in extent) or extent[0] > extent[1]):
            raise ContractError("SCENE_CLUSTER_EXTENT_INVALID:" + field)
    ids = set()
    for item in obstacles:
        if not isinstance(item, dict) or not item.get("object_id") or item["object_id"] in ids:
            raise ContractError("SCENE_OBSTACLE_ID_INVALID")
        ids.add(item["object_id"])
        if item.get("kind") != "building" or item.get("frame") != "scene_ned":
            raise ContractError("SCENE_OBSTACLE_TYPE_UNSUPPORTED:" + item["object_id"])
        if item.get("physics_status") != "imported_with_collision":
            raise ContractError("SCENE_OBSTACLE_NOT_PHYSICAL:" + item["object_id"])
        if not isinstance(item.get("source"), str) or not item["source"]:
            raise ContractError("SCENE_OBSTACLE_SOURCE_MISSING:" + item["object_id"])
        for field in ("center_north_m", "center_east_m", "height_m", "size_north_m", "size_east_m"):
            if not _finite(item.get(field)):
                raise ContractError("SCENE_OBSTACLE_COORDINATE_INVALID:" + item["object_id"])
        if any(item[field] <= 0 for field in ("height_m", "size_north_m", "size_east_m")):
            raise ContractError("SCENE_OBSTACLE_SIZE_INVALID:" + item["object_id"])
    if not isinstance(affordances.get("coverage"), dict):
        raise ContractError("SCENE_COVERAGE_MISSING")
    return cluster, obstacles


def _base(objective: str, affordances: dict) -> dict:
    identity = affordances["scene_identity"]
    return {
        "authority": "objective",
        "objective": objective,
        "scene_id": identity["scene_id"],
        "map_version": identity["map_version"],
        "coordinate_frame": "scene_ned",
        "affordances_hash": digest(affordances),
        "affordances_status": affordances["status"],
        "execution_ready": False,
        "proposal": None,
        "bindings": [],
        "candidates": [],
        "warnings": [
            "Object coordinates are reference geometry, not approved flight waypoints.",
            "No route, obstacle clearance, timing, energy or payload feasibility was checked.",
        ],
    }


def bind_scene_reference(objective: str, affordances: dict) -> dict:
    """Resolve cluster/height references; refuse ambiguous buildings and flight points."""
    if not isinstance(objective, str) or not objective.strip():
        raise ContractError("OBJECTIVE_REQUIRED")
    cluster, obstacles = _check_affordances(affordances)
    result = _base(objective, affordances)
    if affordances["status"] != "reviewed":
        result["warnings"].append("Physical export is pending provider review.")
    if not affordances.get("coverage", {}).get("complete_physical_map", False):
        result["warnings"].append("Affordance coverage is incomplete.")

    explicit = [item for item in obstacles if item["object_id"] in objective]
    if len(explicit) > 1:
        result.update(status="clarification_required", accepted=False,
                      reason_code="MULTIPLE_BUILDING_REFERENCES",
                      candidates=[{"target_id": item["object_id"]} for item in explicit],
                      clarification_question="目标同时引用多栋建筑；请明确本次目标或顺序。")
        return result
    if explicit:
        target = explicit[0]
        result["bindings"].append({
            "matched_text": target["object_id"], "target_id": target["object_id"],
            "target_kind": "building",
            "relation": "nearby" if "旁边" in objective else "identified",
            "reference_geometry": {"center_north_m": target["center_north_m"],
                                   "center_east_m": target["center_east_m"],
                                   "height_m": target["height_m"]},
            "source_reference": target["source"],
        })
    elif "最高" in objective and ("楼" in objective or "建筑" in objective):
        highest = max(item["height_m"] for item in obstacles)
        candidates = [item for item in obstacles if item["height_m"] == highest]
        if len(candidates) != 1:
            result.update(status="clarification_required", accepted=False,
                          reason_code="AMBIGUOUS_HIGHEST_BUILDING",
                          matched_text="最高的那栋楼" if "最高的那栋楼" in objective else "最高",
                          candidates=[{"target_id": item["object_id"],
                                       "height_m": item["height_m"],
                                       "center_north_m": item["center_north_m"],
                                       "center_east_m": item["center_east_m"],
                                       "source_reference": item["source"]}
                                      for item in candidates],
                          clarification_question="最高建筑并列；请指定目标建筑 ID。")
            return result
        target = candidates[0]
        result["bindings"].append({
            "matched_text": "最高的那栋楼" if "最高的那栋楼" in objective else "最高",
            "target_id": target["object_id"], "target_kind": "building",
            "relation": "highest",
            "reference_geometry": {"center_north_m": target["center_north_m"],
                                   "center_east_m": target["center_east_m"],
                                   "height_m": target["height_m"]},
            "source_reference": target["source"],
        })
    elif "楼群" in objective:
        north, east = cluster["center_north_m"], cluster["center_east_m"]
        if any(direction in objective for direction in ("西侧", "南侧", "北侧", "东边", "西边")):
            result.update(status="clarification_required", accepted=False,
                          reason_code="SPATIAL_RELATION_UNSUPPORTED",
                          clarification_question="当前仅验证了楼群东侧和环绕引用；请明确目标实体与方位。")
            return result
        if "北" in objective and (north <= 0 or abs(east) >= abs(north) * 0.25):
            result.update(status="clarification_required", accepted=False,
                          reason_code="DIRECTION_REFERENCE_MISMATCH",
                          clarification_question="目标所说的北侧与楼群中心坐标不一致，请指定实体 ID。")
            return result
        if "南" in objective and north >= 0:
            result.update(status="clarification_required", accepted=False,
                          reason_code="DIRECTION_REFERENCE_MISMATCH",
                          clarification_question="清单中的楼群不在原点南侧，请指定实体 ID。")
            return result
        relation = ("circumnavigate" if "绕" in objective else
                    "east_side" if "东侧" in objective else "cluster")
        phrase = ("楼群的东侧" if "楼群的东侧" in objective else
                  "楼群" if "楼群" in objective else cluster["summary_id"])
        result["bindings"].append({
            "matched_text": phrase, "target_id": cluster["summary_id"],
            "target_kind": "building_cluster", "relation": relation,
            "reference_geometry": {"center_north_m": north,
                                   "center_east_m": east,
                                   "extent_north_m": cluster.get("extent_north_m"),
                                   "extent_east_m": cluster.get("extent_east_m")},
            "source_reference": cluster["source"],
            "coordinate_note": "Bearing was checked against north/east coordinates; east offset is retained.",
        })
    else:
        result.update(status="clarification_required", accepted=False,
                      reason_code="SCENE_REFERENCE_UNRESOLVED",
                      clarification_question="清单中没有可确定的目标；请指定楼群或建筑 ID。")
        return result

    result.update(status="grounded_requires_planning", accepted=True,
                  reason_code="ROUTE_PLANNING_REQUIRED",
                  required_next_input="Planner-approved scene_ned waypoint candidates")
    return result
