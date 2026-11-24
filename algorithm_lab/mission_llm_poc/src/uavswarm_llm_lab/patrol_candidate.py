"""Deterministic, fixture-only patrol candidate generation. No Runtime or transport calls."""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from itertools import permutations
from pathlib import Path

from .contracts import ContractError, digest, parse_json, resource_text
from .semantic_validator import context_errors, eligibility_reasons, validate_proposal


BASELINE = "6a680fe"
FIXTURE_FILE = "benchmarks/patrol_candidate_fixture_v0_1.json"
FIXTURE_SHA256 = "90a0a451f3e6883d11d0d130f00c18a460c7eabbdf936abb793c9b6861120bf2"
REQUEST_KEYS = {"objective", "scene_id", "map_version", "fixture_evidence_id"}
PATROL = re.compile(r"(?:请)?巡检([^。.!！?？\r\n]+)[。.]?")


def _load_fixture() -> dict:
    fixture = parse_json(resource_text(FIXTURE_FILE))
    if digest(fixture) != FIXTURE_SHA256 or fixture.get("scope") != "fake_adapter_only":
        raise ContractError("FIXTURE_CONTENT_MISMATCH")
    return fixture


def _reject(reason: str, *, status: str = "rejected", **details) -> dict:
    return {"kind": "uavswarm-offline-patrol-candidate", "status": status, "reason_code": reason,
            "scope": "fake_adapter_only", "execution_authorized": False,
            "runtime_submission_allowed": False, "model_executed": False,
            "context": None, "proposal": None, "detail": details}


def _match_targets(text: str, fixture: dict):
    match = PATROL.fullmatch(text.strip(" \t"))
    if not match:
        return [], _reject("PATROL_WORDING_UNSUPPORTED", status="clarify",
                           question="请按「巡检」+明确的模拟设备名描述本例任务。")
    result = []
    for label in re.split(r"[、]|和", match[1]):
        label = label.strip()
        options = [item for item in fixture["targets"] if label in item["labels"]]
        if len(options) != 1:
            reason = "TARGET_AMBIGUOUS" if options else "TARGET_NOT_IN_FIXTURE"
            return [], _reject(reason, status="clarify", label=label,
                               candidate_labels=[item["labels"][0] for item in options],
                               question="请指定模拟冷却泵或模拟仪表柜；暂不产生部分计划。")
        if any(item["region_id"] == options[0]["region_id"] for item in result):
            return [], _reject("DUPLICATE_TARGET", status="clarify", label=label)
        result.append(options[0])
    return result, None


def _context(request: dict, fixture: dict, targets: list, motion: bool) -> dict:
    mission = "fx-" + digest({"request": request, "fixture_content_sha256": FIXTURE_SHA256})[:24]
    identity = {field: fixture[field] for field in ("scene_id", "map_version")}
    actions = ["GOTO"] if motion else ["GOTO", "OBSERVE"]
    nodes = fixture["fleet"]
    if motion:
        spec = fixture["motion_only"]
        nodes = [{**node, "position_m": spec["start_position_m"]} for node in nodes if node["node_id"] == spec["node_id"]]
    fleet = [{
        "node_id": node["node_id"], "connected": node["connected"], "stale": node["stale"],
        "battery_pct": node["battery_pct"], "capabilities": list(actions), "current_assignment": None,
        "spatial": {"frame": "scene_ned", **identity, "public_position_usable": True,
                    "sample_age_ms": 0, "position_m": deepcopy(node["position_m"])},
    } for node in nodes]
    return {
        "schema_version": "0.1", "source": "synthetic_benchmark", "mission_id": mission,
        "snapshot_id": "fx-snap-" + FIXTURE_SHA256[:18], "objective": request["objective"],
        **identity, "coordinate_frame": "scene_ned", "snapshot_age_ms": 0,
        "snapshot_valid_for_ms": 120000,
        "constraints": {"min_battery_pct": 30, "max_sample_age_ms": 1000, "min_vehicles": len(targets),
                        "allow_partial": False, "min_altitude_m": 3, "max_altitude_m": 8},
        "fleet": fleet, "waypoints": [deepcopy(w) for target in targets for w in target["waypoints"]],
        "tasks": [{"task_id": "TASK-" + target["region_id"], "region_id": target["region_id"],
                   "required_actions": list(actions), "waypoint_ids": [w["waypoint_id"] for w in target["waypoints"]]}
                  for target in targets],
        "policy_denials": [],
    }


def _assign(context: dict) -> list | None:
    tasks, fleet = context["tasks"], context["fleet"]
    positions = {w["waypoint_id"]: w["position_m"] for w in context["waypoints"]}
    # Fixture-only 2-D ranking; not a flight-length or energy estimate.
    def rank(nodes):
        total = 0
        for node, task in zip(nodes, tasks):
            entry = positions[task["waypoint_ids"][0]]
            at = node["spatial"]["position_m"]
            total += sum((entry[axis] - at[axis]) ** 2 for axis in ("north_m", "east_m"))
        return total, tuple(node["node_id"] for node in nodes)

    eligible = (nodes for nodes in permutations(fleet, len(tasks))
                if all(not eligibility_reasons(context, node, task) for node, task in zip(nodes, tasks)))
    best = min(eligible, key=rank, default=None)
    if best is None:
        return None
    return [{"task_id": task["task_id"], "node_id": node["node_id"], "actions": list(task["required_actions"]),
             "waypoint_ids": list(task["waypoint_ids"]), "reason_code": "ASSIGNED",
             "explanation": "夹具内适任并通过入口平面距离、节点 ID 排序；不构成状态、能源或航线安全证明。"}
            for task, node in zip(tasks, best)]


def build_candidate(request: dict) -> dict:
    if not isinstance(request, dict) or (set(request) - REQUEST_KEYS):
        return _reject("REQUEST_SHAPE_UNSUPPORTED")
    if not isinstance(request.get("objective"), str) or not 1 <= len(request["objective"]) <= 160:
        return _reject("OBJECTIVE_REQUIRED")
    if any(not isinstance(request.get(key), str) or not request[key].strip() for key in ("scene_id", "map_version")):
        return _reject("SCENE_IDENTITY_REQUIRED")
    try:
        fixture = _load_fixture()
    except (ContractError, OSError, UnicodeError):
        return _reject("FIXTURE_EVIDENCE_INVALID")
    if any(request[key] != fixture[key] for key in ("scene_id", "map_version")):
        return _reject("SCENE_IDENTITY_MISMATCH")
    if request.get("fixture_evidence_id") != fixture["fixture_id"]:
        return _reject("FIXTURE_EVIDENCE_REQUIRED")
    text = request["objective"]
    motion = text == fixture["motion_only"]["objective"]
    if motion:
        targets = [fixture["motion_only"]]
    else:
        targets, failure = _match_targets(text, fixture)
        if failure:
            return failure
    context = _context(request, fixture, targets, motion)
    errors = context_errors(context)
    if errors:
        return _reject("CANDIDATE_CONTEXT_INVALID", validation_errors=errors)
    assignments = _assign(context)
    if assignments is None:
        return _reject("NO_ELIGIBLE_FIXTURE_ASSIGNMENT")
    proposal = {key: context[key] for key in ("schema_version", "mission_id", "snapshot_id",
                                             "scene_id", "map_version", "coordinate_frame")}
    proposal.update(
        execution_authorized=False, status="proposed", reason_code="MISSION_PROPOSED",
        explanation="原话经过固定目录核对；所有状态和航点为测试夹具，不构成运行或飞行许可。",
        assignments=assignments, unassigned_tasks=[],
        warnings=["FAKE_ADAPTER_ONLY", "NOT_SCENE_CLEARANCE", "NOT_AN_EXECUTION_REQUEST"],
    )
    errors = validate_proposal(context, proposal)
    if errors:
        return _reject("CANDIDATE_PROPOSAL_INVALID", validation_errors=errors)
    purpose = "fake_motion_only" if motion else "fake_equipment_inspection"
    return {
        "kind": "uavswarm-offline-patrol-candidate", "status": "candidate", "reason_code": "FIXTURE_CANDIDATE_ONLY",
        "scope": "fake_adapter_only", "purpose": purpose, "candidate_id": context["mission_id"],
        "execution_authorized": False, "runtime_submission_allowed": False, "model_executed": False,
        "fixture_evidence": {"id": fixture["fixture_id"], "content_sha256": FIXTURE_SHA256,
                             "kind": "synthetic_fixture",
                             "source_reference": fixture["motion_only"]["source_reference"] if motion else FIXTURE_FILE,
                             "actual_scene_geometry_certified": False},
        "completion_expectation": {
            "mode": "synthetic_arrival_only" if motion else "capture_evidence_required",
            "simulated_start_assumption": fixture["motion_only"]["assumption"] if motion else None,
            "inspection_completed": False, "observation_evidence": None,
        },
        "context": context, "proposal": proposal,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--input", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    requests = parse_json(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(requests, list) or not 1 <= len(requests) <= 20:
        cli.error("Input must be an array of 1–20 requests")
    if args.output.exists() or not args.output.parent.is_dir():
        cli.error("Output must be a new file in an existing directory")
    report = {"baseline": BASELINE, "scope": "fake_adapter_only", "execution_authorized": False,
              "cases": [{"input": request, "result": build_candidate(request)} for request in requests]}
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps([row["result"]["reason_code"] for row in report["cases"]]))


if __name__ == "__main__":
    main()
