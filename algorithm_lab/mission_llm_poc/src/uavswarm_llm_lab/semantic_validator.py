"""Deterministic proposal checks; not Policy Gate or a flight-safety proof."""
from __future__ import annotations

import math

from .contracts import schema_errors


def context_errors(context: dict, elapsed_ms: float = 0) -> list[str]:
    errors = schema_errors(context, "context")
    if errors:
        return ["INPUT_SCHEMA: " + error for error in errors]
    if not math.isfinite(elapsed_ms) or elapsed_ms < 0:
        return ["INVALID_ELAPSED_TIME"]
    if context["snapshot_age_ms"] + elapsed_ms >= context["snapshot_valid_for_ms"]:
        errors.append("SNAPSHOT_EXPIRED")
    limits = context["constraints"]
    if limits["min_altitude_m"] > limits["max_altitude_m"]:
        errors.append("ALTITUDE_RANGE_INVALID")
    for collection, key in (("fleet", "node_id"), ("tasks", "task_id"),
                            ("waypoints", "waypoint_id")):
        ids = [item[key] for item in context[collection]]
        if len(ids) != len(set(ids)):
            errors.append("DUPLICATE_" + key.upper())
    waypoints = {item["waypoint_id"]: item for item in context["waypoints"]}
    for waypoint in waypoints.values():
        altitude = -waypoint["position_m"]["down_m"]
        if not limits["min_altitude_m"] <= altitude <= limits["max_altitude_m"]:
            errors.append("WAYPOINT_ALTITUDE_OUT_OF_RANGE:" + waypoint["waypoint_id"])
    for task in context["tasks"]:
        if any(w not in waypoints for w in task["waypoint_ids"]):
            errors.append("UNKNOWN_TASK_WAYPOINT:" + task["task_id"])
        if ("GOTO" in task["required_actions"]) != bool(task["waypoint_ids"]):
            errors.append("GOTO_WAYPOINT_MISMATCH:" + task["task_id"])
    node_ids = {node["node_id"] for node in context["fleet"]}
    for denial in context["policy_denials"]:
        if denial["node_id"] != "*" and denial["node_id"] not in node_ids:
            errors.append("UNKNOWN_POLICY_NODE:" + denial["node_id"])
    return sorted(set(errors))


def eligibility_reasons(context: dict, node: dict, task: dict,
                        elapsed_ms: float = 0) -> list[str]:
    reasons = []
    limits = context["constraints"]
    if not node["connected"]:
        reasons.append("NODE_OFFLINE")
    if node["stale"]:
        reasons.append("TELEMETRY_STALE")
    if node["battery_pct"] is None:
        reasons.append("BATTERY_UNKNOWN")
    elif node["battery_pct"] < limits["min_battery_pct"]:
        reasons.append("BATTERY_LOW")
    if node["current_assignment"] is not None:
        reasons.append("NODE_BUSY")
    spatial = node["spatial"]
    if (not spatial["public_position_usable"] or spatial["frame"] != "scene_ned"
            or spatial["position_m"] is None
            or spatial["scene_id"] != context["scene_id"]
            or spatial["map_version"] != context["map_version"]):
        reasons.append("SPATIAL_UNAVAILABLE")
    if spatial["sample_age_ms"] + elapsed_ms > limits["max_sample_age_ms"]:
        reasons.append("TELEMETRY_STALE")
    if not set(task["required_actions"]).issubset(node["capabilities"]):
        reasons.append("CAPABILITY_MISSING")
    if any(d["node_id"] in {"*", node["node_id"]}
           and d["action"] in task["required_actions"]
           for d in context["policy_denials"]):
        reasons.append("POLICY_DENIED")
    return sorted(set(reasons))


def validate_proposal(context: dict, proposal: dict,
                      elapsed_ms: float = 0) -> list[str]:
    errors = context_errors(context, elapsed_ms)
    if errors:
        return errors
    shape = schema_errors(proposal, "proposal")
    if shape:
        return ["OUTPUT_SCHEMA: " + error for error in shape]
    for key in ("mission_id", "snapshot_id", "scene_id", "map_version",
                "coordinate_frame"):
        if proposal[key] != context[key]:
            errors.append("CONTEXT_MISMATCH:" + key)
    tasks = {t["task_id"]: t for t in context["tasks"]}
    fleet = {n["node_id"]: n for n in context["fleet"]}
    seen = []
    assigned_nodes = set()
    for assignment in proposal["assignments"]:
        task_id, node_id = assignment["task_id"], assignment["node_id"]
        seen.append(task_id)
        assigned_nodes.add(node_id)
        if task_id not in tasks:
            errors.append("UNKNOWN_TASK:" + task_id)
        if node_id not in fleet:
            errors.append("UNKNOWN_NODE:" + node_id)
        if task_id not in tasks or node_id not in fleet:
            continue
        task = tasks[task_id]
        if assignment["actions"] != task["required_actions"]:
            errors.append("ACTION_SEQUENCE_MISMATCH:" + task_id)
        if assignment["waypoint_ids"] != task["waypoint_ids"]:
            errors.append("WAYPOINT_SEQUENCE_MISMATCH:" + task_id)
        errors.extend(reason + ":" + node_id + ":" + task_id for reason in
                      eligibility_reasons(context, fleet[node_id], task, elapsed_ms))
    for item in proposal["unassigned_tasks"]:
        seen.append(item["task_id"])
        if item["task_id"] not in tasks:
            errors.append("UNKNOWN_TASK:" + item["task_id"])
        if item["reason_code"] in {"ASSIGNED", "MISSION_PROPOSED", "PARTIAL_MISSION"}:
            errors.append("INVALID_REJECTION_REASON:" + item["task_id"])
    if len(seen) != len(set(seen)):
        errors.append("DUPLICATE_TASK")
    if set(tasks) - set(seen):
        errors.append("MISSING_TASK")
    assigned, unassigned = proposal["assignments"], proposal["unassigned_tasks"]
    status = proposal["status"]
    if status == "proposed":
        if not assigned or unassigned:
            errors.append("INVALID_PROPOSED_STATUS")
        if proposal["reason_code"] != "MISSION_PROPOSED":
            errors.append("STATUS_REASON_MISMATCH")
    elif status == "degraded":
        if not assigned or not unassigned or not context["constraints"]["allow_partial"]:
            errors.append("PARTIAL_MISSION_NOT_ALLOWED")
        if proposal["reason_code"] != "PARTIAL_MISSION":
            errors.append("STATUS_REASON_MISMATCH")
    else:
        if assigned or len(unassigned) != len(tasks):
            errors.append("INVALID_REJECTED_STATUS")
        if proposal["reason_code"] not in {"REQUEST_REJECTED", "INSUFFICIENT_FLEET",
                                          "NO_ELIGIBLE_VEHICLE", "POLICY_DENIED"}:
            errors.append("STATUS_REASON_MISMATCH")
    if status != "rejected" and len(assigned_nodes) < context["constraints"]["min_vehicles"]:
        errors.append("INSUFFICIENT_FLEET")
    return sorted(set(errors))
