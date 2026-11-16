"""Deterministic evidence checks; no perception model or vehicle control."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class ContractError(ValueError):
    pass


VERSION = "landing_assessment_proposal_v0.1"
ALGORITHM = "scene_ground_evidence_baseline/0.1.0"


def _object(value: Any, fields: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError(f"{name}_FIELDS_INVALID")
    return value


def _id(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.strip():
        raise ContractError(f"{name}_INVALID")


def _number(value: Any, name: str, *, minimum: float = -1e12, maximum: float = 1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{name}_NONFINITE_OR_NONNUMERIC")
    if not minimum <= value <= maximum:
        raise ContractError(f"{name}_OUT_OF_RANGE")
    return float(value)


def _position(value: Any) -> None:
    if value is None:
        return
    _object(value, {"north_m", "east_m", "down_m"}, "POSITION")
    for axis in ("north_m", "east_m", "down_m"):
        _number(value[axis], axis, minimum=-100000, maximum=100000)


def validate(request: Any) -> dict:
    root = _object(request, {"contract_version", "assessment_id", "correlation", "goal", "observation"}, "REQUEST")
    if root["contract_version"] != VERSION:
        raise ContractError("CONTRACT_VERSION_UNSUPPORTED")
    _id(root["assessment_id"], "ASSESSMENT_ID")
    corr = _object(root["correlation"], {"mission_id", "request_id", "action_id", "trace_id"}, "CORRELATION")
    for name in corr:
        _id(corr[name], name.upper(), nullable=True)
    goal = _object(root["goal"], {"kind", "scene_id", "map_version", "ground_reference",
                                  "vertical_tolerance_m", "min_samples", "min_stable_s"}, "GOAL")
    if goal["kind"] not in {"scene_ground_contact", "unknown_surface"}:
        raise ContractError("GOAL_KIND_UNSUPPORTED")
    for name in ("scene_id", "map_version"):
        _id(goal[name], name.upper())
    _number(goal["vertical_tolerance_m"], "VERTICAL_TOLERANCE", minimum=0.001, maximum=1)
    if type(goal["min_samples"]) is not int or not 2 <= goal["min_samples"] <= 64:
        raise ContractError("MIN_SAMPLES_INVALID")
    _number(goal["min_stable_s"], "MIN_STABLE", minimum=0.01, maximum=10)
    reference = goal["ground_reference"]
    if reference is not None:
        _object(reference, {"scene_id", "map_version", "source_kind", "source_ref", "ground_down_m"},
                "GROUND_REFERENCE")
        for name in ("scene_id", "map_version", "source_kind", "source_ref"):
            _id(reference[name], "GROUND_REFERENCE_" + name.upper())
        _number(reference["ground_down_m"], "GROUND_DOWN", minimum=-10000, maximum=10000)
    if goal["kind"] == "unknown_surface" and reference is not None:
        raise ContractError("UNKNOWN_SURFACE_REFERENCE_FORBIDDEN")
    obs = _object(root["observation"], {"node_id", "source_kind", "source_ref", "timebase",
                                         "evaluated_at_s", "max_sample_age_s", "calibration", "samples",
                                         "surface_observation"}, "OBSERVATION")
    for name in ("node_id", "source_kind", "source_ref"):
        _id(obs[name], "OBSERVATION_" + name.upper())
    if obs["source_kind"] not in {"synthetic_replay", "normalized_runtime_snapshot"}:
        raise ContractError("SOURCE_KIND_UNSUPPORTED")
    if obs["timebase"] not in {"unix_s", "simulation_s", "px4_boot_s"}:
        raise ContractError("TIMEBASE_UNSUPPORTED")
    _number(obs["evaluated_at_s"], "EVALUATED_AT", minimum=0)
    _number(obs["max_sample_age_s"], "MAX_SAMPLE_AGE", minimum=0.001, maximum=10)
    if obs["calibration"] is not None:
        cal = _object(obs["calibration"], {"version", "frame", "scene_id", "map_version", "source_ref"},
                      "CALIBRATION")
        if cal["frame"] != "scene_ned":
            raise ContractError("CALIBRATION_FRAME_UNSUPPORTED")
        for name in ("version", "scene_id", "map_version", "source_ref"):
            _id(cal[name], "CALIBRATION_" + name.upper())
    samples = obs["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 64:
        raise ContractError("SAMPLES_INVALID")
    ids = set()
    for sample in samples:
        _object(sample, {"sample_id", "t_s", "position_scene_ned_m", "landed", "armed", "source_ref"},
                "SAMPLE")
        for name in ("sample_id", "source_ref"):
            _id(sample[name], "SAMPLE_" + name.upper())
        if sample["sample_id"] in ids:
            raise ContractError("DUPLICATE_SAMPLE_ID")
        ids.add(sample["sample_id"])
        _number(sample["t_s"], "SAMPLE_TIME", minimum=0)
        _position(sample["position_scene_ned_m"])
        if type(sample["landed"]) is not bool or type(sample["armed"]) is not bool:
            raise ContractError("CONTACT_STATE_INVALID")
    surface = _object(obs["surface_observation"], {"kind", "image_ref", "range_down_m", "source_ref"},
                      "SURFACE_OBSERVATION")
    if surface["kind"] not in {"absent", "range_only", "rgb_capture"}:
        raise ContractError("SURFACE_OBSERVATION_KIND_UNSUPPORTED")
    for name in ("image_ref", "source_ref"):
        _id(surface[name], name.upper(), nullable=True)
    if surface["range_down_m"] is not None:
        _number(surface["range_down_m"], "RANGE_DOWN", minimum=0, maximum=10000)
    if surface["kind"] == "absent" and any(surface[k] is not None for k in ("image_ref", "range_down_m", "source_ref")):
        raise ContractError("ABSENT_SURFACE_WITH_DATA")
    if surface["kind"] == "range_only" and (surface["range_down_m"] is None or surface["source_ref"] is None):
        raise ContractError("RANGE_SOURCE_REQUIRED")
    if surface["kind"] == "rgb_capture" and (surface["image_ref"] is None or surface["source_ref"] is None):
        raise ContractError("IMAGE_SOURCE_REQUIRED")
    return root


def assess(request: Any) -> dict:
    """Evaluate only a stated scene-ground contact criterion; never authorize action."""
    request = validate(request)
    goal, obs = request["goal"], request["observation"]
    raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    status, reasons = "unknown", []
    samples = obs["samples"]
    times = [s["t_s"] for s in samples]
    if any(b <= a for a, b in zip(times, times[1:])):
        reasons = ["SAMPLE_TIME_NOT_INCREASING"]
    elif any(not 0 <= obs["evaluated_at_s"] - t <= obs["max_sample_age_s"] for t in times):
        reasons = ["SAMPLE_STALE_OR_FUTURE"]
    elif len(samples) < goal["min_samples"] or times[-1] - times[0] < goal["min_stable_s"]:
        reasons = ["STABLE_WINDOW_INSUFFICIENT"]
    elif goal["kind"] == "unknown_surface":
        reasons = ["SURFACE_SUPPORT_UNOBSERVED"]
    elif goal["ground_reference"] is None:
        reasons = ["GROUND_REFERENCE_UNAVAILABLE"]
    elif obs["calibration"] is None:
        reasons = ["CALIBRATION_UNAVAILABLE"]
    elif (goal["scene_id"] != goal["ground_reference"]["scene_id"]
          or goal["map_version"] != goal["ground_reference"]["map_version"]
          or goal["scene_id"] != obs["calibration"]["scene_id"]
          or goal["map_version"] != obs["calibration"]["map_version"]):
        reasons = ["SCENE_BINDING_MISMATCH"]
    elif any(s["position_scene_ned_m"] is None for s in samples):
        reasons = ["SCENE_POSITION_UNAVAILABLE"]
    else:
        mismatches = []
        if any(abs(s["position_scene_ned_m"]["down_m"] - goal["ground_reference"]["ground_down_m"])
               > goal["vertical_tolerance_m"] for s in samples):
            mismatches.append("GROUND_HEIGHT_MISMATCH")
        if any(not s["landed"] or s["armed"] for s in samples):
            mismatches.append("CONTACT_STATE_NOT_MET")
        status = "criteria_not_met" if mismatches else "criteria_met"
        reasons = mismatches or ["SCENE_GROUND_CONTACT_EVIDENCE_MET"]
    return {
        "contract_version": VERSION, "assessment_id": request["assessment_id"],
        "correlation": request["correlation"], "node_id": obs["node_id"],
        "goal_kind": goal["kind"], "status": status, "reason_codes": reasons,
        "evidence_refs": [obs["source_ref"], *[s["source_ref"] for s in samples]],
        "source_kind": obs["source_kind"], "timebase": obs["timebase"],
        "evaluated_at_s": obs["evaluated_at_s"],
        "algorithm": ALGORITHM, "input_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "confidence": None, "surface_safety": "unknown", "execution_authorized": False,
        "task_completed": False,
    }
