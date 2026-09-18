"""Measured NED translations bound to a PX4 origin and Gazebo model instance.

Vehicle heading never rotates earth-fixed NED axes. Only NED-aligned
translations are supported. Raw measurements remain in acceptance reports.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

try:
    from . import harness
    from .evidence import proto_time
    from .gazebo_evidence import capture_poses
except ImportError:
    import harness
    from evidence import proto_time
    from gazebo_evidence import capture_poses


ORIGIN_FIELDS = ("ref_timestamp", "ref_lat", "ref_lon", "ref_alt", "xy_reset_counter", "z_reset_counter")
AXES = ("x_m", "y_m", "z_m")


def aligned_translation(value: dict[str, Any]) -> tuple[float, float, float]:
    rotation = float(value.get("frame_rotation_deg", 0.0))
    if not math.isfinite(rotation) or rotation != 0:
        raise ValueError("unsupported_frame_rotation")
    result = tuple(float(value[axis]) for axis in AXES)
    if not all(math.isfinite(number) for number in result):
        raise ValueError("nonfinite_translation")
    return result


def parse_origin(output: str) -> dict[str, Any]:
    values = {}
    for key in ORIGIN_FIELDS + ("xy_valid", "z_valid", "xy_global", "z_global"):
        match = re.search(rf"^\s*{key}:\s*(\S+)", output, re.MULTILINE)
        if not match:
            raise ValueError(f"origin_field_missing:{key}")
        raw = match.group(1)
        values[key] = raw == "True" if key.endswith(("valid", "global")) else float(raw)
    if not all(values[k] for k in ("xy_valid", "z_valid", "xy_global", "z_global")):
        raise ValueError("px4_origin_not_valid")
    if not all(math.isfinite(values[k]) for k in ORIGIN_FIELDS) or values["ref_timestamp"] <= 0:
        raise ValueError("px4_origin_not_finite")
    return values


def read_origin_context(vehicle: dict[str, Any], *, include_sample: bool = False) -> dict[str, Any]:
    """SITL daemon listener is read-only and opens no MAVLink receiver."""
    state = harness.read_state() or {}
    row = next((p for p in state.get("processes", []) if p.get("node_id") == vehicle["node_id"]), None)
    if row is None:
        raise ValueError("calibration_process_missing")
    decision = harness.validate_process_identity(row, run_id=str(state.get("run_id", "")))
    if decision.code != harness.IDENTITY_MATCH:
        raise ValueError(f"calibration_{decision.code}")
    binary = Path(row["process_identity"]["executable"]).with_name("px4-listener")
    result = subprocess.run([str(binary), "--instance", str(vehicle["px4_instance"]),
                             "vehicle_local_position", "-n", "1"],
                            capture_output=True, text=True, timeout=3, check=False)
    if result.returncode:
        raise ValueError("px4_origin_probe_failed")
    context = {"run_id": state["run_id"], "process_identity": row["process_identity"],
               "origin": parse_origin(result.stdout)}
    if include_sample:
        values = {}
        for field in ("timestamp_sample", "x", "y", "z"):
            match = re.search(rf"^\s*{field}:\s*([-+0-9.eE]+)", result.stdout, re.MULTILINE)
            if not match:
                raise ValueError(f"local_sample_field_missing:{field}")
            values[field] = float(match.group(1))
        return {"context": context, "sample": {"time_boot_ms": values["timestamp_sample"] / 1000,
                "x_m": values["x"], "y_m": values["y"], "z_m": values["z"]}}
    return context


def pair_samples(poses: list[dict[str, Any]], local_samples: list[dict[str, Any]],
                 model_name: str, *, maximum_skew_s: float = 0.05) -> list[dict[str, Any]]:
    world_samples = []
    for message in poses:
        stamp = proto_time(message.get("header", {}).get("stamp", {}))
        model = next((p for p in message.get("pose", []) if p.get("name") == model_name), None)
        if model:
            p = model.get("position", {})
            world_samples.append((stamp, model["id"], (float(p.get("y", 0)), float(p.get("x", 0)), -float(p.get("z", 0)))))
    if not world_samples:
        raise ValueError("gazebo_model_pose_missing")
    world_samples.sort()
    stamps = [row[0] for row in world_samples]
    pairs = []
    previous = -1.0
    for sample in local_samples:
        stamp = float(sample["time_boot_ms"]) / 1000
        if stamp <= previous:
            raise ValueError("px4_sample_clock_reset_or_duplicate")
        previous = stamp
        index = bisect.bisect_left(stamps, stamp)
        candidates = world_samples[max(0, index - 1):index + 1]
        nearest = min(candidates, key=lambda row: abs(row[0] - stamp))
        skew = abs(nearest[0] - stamp)
        if skew > maximum_skew_s:
            continue
        local = [float(sample[axis]) for axis in AXES]
        if not all(math.isfinite(v) for v in (*local, *nearest[2])):
            raise ValueError("nonfinite_calibration_sample")
        pairs.append({"sim_time_s": stamp, "skew_s": skew, "model_id": nearest[1],
                      "scene_position": {"frame": "scene_ned", **dict(zip(AXES, nearest[2]))},
                      "vehicle_local_position": {"frame": "vehicle_local_ned", **dict(zip(AXES, local))}})
    return pairs


def build_calibration(vehicle: dict[str, Any], manifest: dict[str, Any], pairs: list[dict[str, Any]],
                      before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    aligned_translation(vehicle["spawn_ned"])
    if before != after:
        raise ValueError("calibration_origin_or_process_reset")
    if len(pairs) < 10 or pairs[-1]["sim_time_s"] - pairs[0]["sim_time_s"] < 1.0:
        raise ValueError("calibration_insufficient_samples")
    if len({p["model_id"] for p in pairs}) != 1:
        raise ValueError("calibration_model_respawned")
    offsets = [[p["scene_position"][axis] - p["vehicle_local_position"][axis] for axis in AXES] for p in pairs]
    translation = [statistics.mean(row[i] for row in offsets) for i in range(3)]
    residuals = [math.dist(row, translation) for row in offsets]
    if max(residuals) > 0.5:
        raise ValueError("calibration_residual_exceeded")
    spans = {axis: max(p["scene_position"][axis] for p in pairs) - min(p["scene_position"][axis] for p in pairs) for axis in AXES}
    identity = {**before, "model_id": pairs[0]["model_id"]}
    origin_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    sampled_at = harness.utc_now()
    return {
        "contract_version": "1.0", "transform_version": "ned-translation-1",
        "scene_id": manifest["scene_id"], "map_version": manifest.get("map_version", f"{manifest['scene_id']}-map-1"),
        "node_id": vehicle["node_id"], "status": "calibrated", "valid": True,
        "calibration_version": f"{origin_id}:{sampled_at}", "local_origin_id": origin_id,
        "origin_continuity": "verified", "axis_alignment": "ned_aligned",
        "scene_origin": {"kind": "gazebo_world_ned", "north_m": 0.0, "east_m": 0.0, "down_m": 0.0},
        "altitude_reference": "scene_origin_z_down", "source_timestamp": sampled_at, "valid_for_ms": 5000,
        "translation_scene_ned_m": dict(zip(("north", "east", "down"), translation)),
        "evidence_source": "gazebo_pose_and_px4_local_position", "context": identity,
        "evidence": {"sample_count": len(pairs), "span_s": pairs[-1]["sim_time_s"] - pairs[0]["sim_time_s"],
                     "maximum_skew_s": max(p["skew_s"] for p in pairs),
                     "maximum_residual_m": max(residuals), "rms_residual_m": math.sqrt(statistics.mean(v * v for v in residuals)),
                     "measured_displacement_m": spans,
                     "physical_axes_exercised": {axis: span >= 1 for axis, span in spans.items()},
                     "axis_basis": "PX4_LOCAL_POSITION_NED_and_Gazebo_ENU_definitions",
                     "spawn_offset_error_m": dict(zip(AXES, [translation[i] - float(vehicle["spawn_ned"][axis]) for i, axis in enumerate(AXES)])),
                     "pairs": pairs},
    }


def capture_session_calibration(vehicle: dict[str, Any], session: Any,
                                manifest: dict[str, Any], *, duration_s: float = 3.0) -> dict[str, Any]:
    """Use the caller's existing standalone session, never a second receiver."""
    before = read_origin_context(vehicle)
    samples: list[dict[str, Any]] = []
    lock = threading.Lock()

    def observe(message: Any) -> None:
        if (message.get_type() == "LOCAL_POSITION_NED"
                and message.get_srcSystem() == int(vehicle["system_id"])
                and message.get_srcComponent() == int(vehicle["component_id"])):
            with lock:
                samples.append({"time_boot_ms": message.time_boot_ms,
                                "x_m": message.x, "y_m": message.y, "z_m": message.z})

    subscription = session.subscribe(observe)
    try:
        poses = capture_poses(str(manifest["world_name"]), duration_s)
        after = read_origin_context(vehicle)
        with lock:
            pairs = pair_samples(poses, list(samples), str(vehicle["gazebo_model_name"]))
        return build_calibration(vehicle, manifest, pairs, before, after)
    finally:
        session.unsubscribe(subscription)


def translation_from_calibration(calibration: dict[str, Any]) -> dict[str, float]:
    if calibration.get("axis_alignment") != "ned_aligned" or calibration.get("valid") is not True:
        raise ValueError("calibration_invalid")
    translation = calibration["translation_scene_ned_m"]
    return dict(zip(AXES, [translation[k] for k in ("north", "east", "down")]))


def check_context(calibration: dict[str, Any], context: dict[str, Any], *, model_id: int | None = None) -> None:
    expected = {key: value for key, value in calibration["context"].items() if key != "model_id"}
    if expected != context or (model_id is not None and model_id != calibration["context"]["model_id"]):
        raise ValueError("calibration_origin_process_or_model_changed")


def capture_readonly_calibrations(manifest: dict[str, Any], *, duration_s: float = 3.0) -> list[dict[str, Any]]:
    """Integrated sampler: PX4 uORB listener plus Gazebo, zero MAVLink sockets."""
    vehicles = manifest["vehicles"]
    before = {v["node_id"]: read_origin_context(v) for v in vehicles}
    samples: dict[str, list[dict[str, Any]]] = {v["node_id"]: [] for v in vehicles}
    with ThreadPoolExecutor(max_workers=len(vehicles) + 1) as executor:
        future = executor.submit(capture_poses, manifest["world_name"], duration_s)
        deadline = time.monotonic() + duration_s + 2
        while not future.done() and time.monotonic() < deadline:
            pending = [(vehicle, executor.submit(read_origin_context, vehicle, include_sample=True))
                       for vehicle in vehicles]
            for vehicle, sample_future in pending:
                evidence = sample_future.result()
                node_id = vehicle["node_id"]
                if before[node_id] != evidence["context"]:
                    raise ValueError("calibration_origin_or_process_reset")
                values = samples[node_id]
                if not values or evidence["sample"]["time_boot_ms"] > values[-1]["time_boot_ms"]:
                    values.append(evidence["sample"])
            time.sleep(.05)
        poses = future.result()
    results = []
    for vehicle in vehicles:
        node_id = vehicle["node_id"]
        pairs = pair_samples(poses, samples[node_id], vehicle["gazebo_model_name"])
        result = build_calibration(vehicle, manifest, pairs, before[node_id], read_origin_context(vehicle))
        result["evidence_source"] = "gazebo_pose_and_px4_uorb_vehicle_local_position"
        results.append(result)
    return results


class MotionEvidenceRecorder:
    """Observe an acceptance flight through existing sessions and Gazebo only."""

    def __init__(self, manifest: dict[str, Any], controllers: list[Any]):
        self.manifest = manifest
        self.controllers = {c.node_id: c for c in controllers}
        self.samples: dict[str, list[dict[str, Any]]] = {v["node_id"]: [] for v in manifest["vehicles"]}
        self.poses: list[dict[str, Any]] = []
        self.contexts: dict[str, dict[str, Any]] = {}
        self.subscriptions: list[tuple[Any, Any]] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        for vehicle in self.manifest["vehicles"]:
            node_id = vehicle["node_id"]
            controller = self.controllers[node_id]
            self.contexts[node_id] = read_origin_context(vehicle)

            def observe(message: Any, v=vehicle, node=node_id) -> None:
                if (message.get_type() == "LOCAL_POSITION_NED"
                        and message.get_srcSystem() == v["system_id"]
                        and message.get_srcComponent() == v["component_id"]):
                    with self.lock:
                        self.samples[node].append({"time_boot_ms": message.time_boot_ms,
                            "x_m": message.x, "y_m": message.y, "z_m": message.z})

            self.subscriptions.append((controller.session, controller.session.subscribe(observe)))
        self.thread = threading.Thread(target=self._observe_world, daemon=True, name="gazebo-motion-evidence")
        self.thread.start()

    def _observe_world(self) -> None:
        names = {v["gazebo_model_name"] for v in self.manifest["vehicles"]}
        last_stamp = -1.0
        try:
            while not self.stop_event.is_set():
                for message in capture_poses(self.manifest["world_name"], 2.0):
                    stamp = proto_time(message.get("header", {}).get("stamp", {}))
                    if stamp < last_stamp:
                        raise ValueError("gazebo_clock_reset")
                    if stamp - last_stamp < .05:
                        continue
                    last_stamp = stamp
                    self.poses.append({"header": message["header"],
                        "pose": [p for p in message.get("pose", []) if p.get("name") in names]})
        except Exception as exc:
            self.error = f"{type(exc).__name__}:{exc}"

    def finish(self) -> dict[str, Any]:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                self.error = "gazebo_observer_stop_timeout"
        for session, token in self.subscriptions:
            session.unsubscribe(token)
        reports = []
        for vehicle in self.manifest["vehicles"]:
            node_id = vehicle["node_id"]
            pairs = []
            try:
                pairs = pair_samples(self.poses, self.samples[node_id], vehicle["gazebo_model_name"])
                result = build_calibration(vehicle, self.manifest, pairs,
                    self.contexts[node_id], read_origin_context(vehicle))
                initial = translation_from_calibration(self.controllers[node_id].calibration)
                errors = [math.dist([p["scene_position"][a] for a in AXES],
                                   [p["vehicle_local_position"][a] + initial[a] for a in AXES]) for p in pairs]
                result["evidence"]["maximum_error_against_initial_calibration_m"] = max(errors)
                result["physical_validation_passed"] = (
                    max(errors) <= .75 and all(result["evidence"]["physical_axes_exercised"].values()))
                reports.append(result)
            except Exception as exc:
                reports.append({"node_id": node_id, "physical_validation_passed": False,
                                "error": f"{type(exc).__name__}:{exc}",
                                "evidence": {"pairs": pairs, "sample_count": len(pairs)}})
        distances = []
        stamps = []
        for message in self.poses:
            if len(message["pose"]) != len(self.controllers):
                continue
            points = [[p.get("position", {}).get(a, 0) for a in ("x", "y", "z")] for p in message["pose"]]
            distances.append(min(math.dist(points[i], points[j]) for i in range(len(points)) for j in range(i+1, len(points))))
            stamps.append(proto_time(message["header"]["stamp"]))
        maximum_gap = max((b-a for a,b in zip(stamps, stamps[1:])), default=0.0)
        return {"source": "gazebo_dynamic_pose_and_existing_mavlink_sessions",
                "status": "PASS" if not self.error and all(r["physical_validation_passed"] for r in reports)
                          and len(distances) >= 20 and maximum_gap <= 1.0 else "FAIL",
                "error": self.error, "vehicles": reports,
                "world_pose_sample_count": len(distances), "maximum_pose_gap_s": maximum_gap,
                "minimum_world_distance_m": min(distances) if distances else None}
