"""Replay the proposed capture evidence checks without a simulator or HTTP."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from simulation.px4_gazebo.harness import WORLD_SHA256_SCHEME, canonical_world_bytes


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REQUEST_TIMEOUT_WALL_NS = 1_000_000_000
POSE_SOURCE_PATH = "docs/simulation/fixtures/simple_recon_v0_1_target_001_pose_sources_v1.json"
_USE_FIXTURE_POSE_SOURCE = object()


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


@pytest.fixture
def capture_case():
    return read_json("docs/simulation/fixtures/simple_recon_v0_1_target_001_capture_v1.json")


def test_capture_context_matches_navigation_fixture_and_world(capture_case):
    navigation = read_json("docs/simulation/fixtures/simple_recon_v0_1_target_001_navigation_v1.json")
    identity = navigation["scene_identity"]
    assert (capture_case["scene_id"], capture_case["map_version"]) == (identity["scene_id"], identity["map_version"])
    assert capture_case["target_id"] == navigation["target"]["object_id"]
    world = ROOT / navigation["sources"]["world"]
    assert capture_case["world_sha256_scheme"] == WORLD_SHA256_SCHEME
    assert capture_case["world_sha256"] == hashlib.sha256(canonical_world_bytes(world.read_bytes())).hexdigest()

    plan = read_json("docs/fixtures/runtime_plan_progress_fake_target_001_v1.json")["plan_request_used_in_test"]["plan"]
    arrival = capture_case["arrival"]
    assert (plan["plan_id"], plan["scene_id"], plan["map_version"]) == (
        arrival["plan_id"], capture_case["scene_id"], capture_case["map_version"],
    )
    step = next(step for step in plan["steps"] if step["step_id"] == arrival["step_id"])
    assert step["action_type"] == "goto" and step["node_id"] == arrival["node_id"]
    assert arrival["position_scene_ned_m"] == {axis: step["params"][axis] for axis in ("north_m", "east_m", "down_m")}
    assert arrival["runtime_run_id"] != capture_case["capture_request"]["gazebo_run_id"]

    east, north, up = capture_case["sample"]["body_pose_enu"]["position_m"]
    assert arrival["position_scene_ned_m"] == {"north_m": north, "east_m": east, "down_m": -up}
    assert math.hypot(*capture_case["sample"]["body_pose_enu"]["orientation_xyzw"]) == pytest.approx(1)


def _finite_vector(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return False
    try:
        return all(type(component) in (int, float) and math.isfinite(component) for component in value)
    except OverflowError:
        return False


def _valid_body_pose(pose):
    if not isinstance(pose, dict) or not _finite_vector(pose.get("position_m"), 3):
        return False
    orientation = pose.get("orientation_xyzw")
    return _finite_vector(orientation, 4) and math.isclose(
        math.hypot(*orientation), 1.0, rel_tol=0, abs_tol=1e-3,
    )


def replay_fixture(capture_case, sample, payload, *, pose_source=_USE_FIXTURE_POSE_SOURCE):
    request = capture_case["capture_request"]
    limits = capture_case["proposal_limits"]
    manifest = read_json("simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json")
    arrival = capture_case["arrival"]
    vehicle = next(v for v in manifest["vehicles"] if v["node_id"] == arrival["node_id"])
    topic_base = f"/world/{manifest['world_name']}/model/{vehicle['gazebo_model_name']}/link/camera_link/sensor/camera"
    arrival_status = "arrived" if arrival["arrival_observed"] is True else "unverified"
    result = {"arrival": arrival_status, "capture": "fixture_valid", "observation": "undetermined"}
    pose = sample.get("body_pose_enu")
    pose_stamp = sample.get("pose_sim_stamp_ns")
    requested = request["requested_monotonic_ns"]
    received = sample["received_monotonic_ns"]
    checked = sample["checked_monotonic_ns"]
    if pose_source is _USE_FIXTURE_POSE_SOURCE:
        sources = read_json(POSE_SOURCE_PATH)["sources_by_capture_request_id"]
        pose_source = sources.get(request["request_id"])
    pose_source_keys = ("gazebo_run_id", "gazebo_model_entity_id")
    if any(sample[key] != request[key] for key in ("request_id", "gazebo_run_id", "gazebo_model_entity_id")):
        result["capture"] = "capture_context_mismatch"
    elif (sample["image_topic"] != f"{topic_base}/image"
          or sample["camera_info_topic"] != f"{topic_base}/camera_info"):
        result["capture"] = "image_source_mismatch"
    elif (sample["image_sim_stamp_ns"] <= request["after_sim_stamp_ns"]
          or received < requested
          or not 0 <= checked - received <= limits["max_receive_age_wall_ns"]):
        result["capture"] = "frame_stale"
    elif checked - requested >= FIXTURE_REQUEST_TIMEOUT_WALL_NS:
        result["capture"] = "capture_request_timeout"
    elif pose is None or pose_stamp is None:
        result["capture"] = "capture_pose_missing"
    elif not _valid_body_pose(pose) or type(pose_stamp) is not int or pose_stamp < 0:
        result["capture"] = "capture_pose_invalid"
    elif not isinstance(pose_source, dict) or any(pose_source.get(key) is None for key in pose_source_keys):
        result["capture"] = "capture_pose_source_missing"
    elif any(pose_source[key] != request[key] for key in pose_source_keys):
        result["capture"] = "capture_pose_source_mismatch"
    elif (abs(sample["image_sim_stamp_ns"] - pose_stamp) > limits["max_pose_skew_sim_ns"]
          or abs(sample["image_sim_stamp_ns"] - sample["camera_info_sim_stamp_ns"]) > limits["max_camera_info_skew_sim_ns"]):
        result["capture"] = "capture_samples_unaligned"
    elif sample["camera_frame"] != "camera_link" or not (
        len(sample["intrinsics_k"]) == 9
        and all(math.isfinite(value) for value in sample["intrinsics_k"])
        and min(sample["intrinsics_k"][0], sample["intrinsics_k"][4]) > 0
    ):
        result["capture"] = "camera_info_invalid"
    elif (sample["encoding"], sample["width"], sample["height"], sample["row_stride_bytes"], len(payload)) != (
        "RGB8", 1280, 960, 3840, 3686400,
    ):
        result["capture"] = "image_layout_mismatch"
    else:
        digest = hashlib.sha256(payload).hexdigest()
        if digest != sample["payload_sha256"] or f"sha256:{digest}" != sample["image_ref"]:
            result["capture"] = "image_integrity_mismatch"
    return result


@pytest.fixture
def fake_payload(capture_case):
    sample = capture_case["sample"]
    rows = [bytes(rgb) * sample["width"] for rgb in sample["synthetic_rows_rgb"]]
    return b"".join(rows) * (sample["height"] // len(rows))


def test_valid_fake_capture_keeps_observation_undetermined(capture_case, fake_payload):
    assert capture_case["evidence_origin"] == "synthetic_test_fixture"
    assert capture_case["arrival"]["arrival_observed"] is True
    assert replay_fixture(capture_case, capture_case["sample"], fake_payload) == capture_case["positive_expected"]


def test_correct_image_bytes_from_wrong_vehicle_are_rejected(capture_case, fake_payload):
    negative = capture_case["negative_case"]
    sample = {**capture_case["sample"], **negative["override_sample"]}
    assert replay_fixture(capture_case, sample, fake_payload) == negative["expected"]


@pytest.mark.parametrize(
    ("override_sample", "reason"),
    [
        ({"gazebo_run_id": "fixture-previous-run"}, "capture_context_mismatch"),
        ({"image_sim_stamp_ns": 30000000000}, "frame_stale"),
        ({"checked_monotonic_ns": 2000000000}, "frame_stale"),
        ({"body_pose_enu": {"position_m": [100, 100, 50], "orientation_xyzw": [0, 0, 0, 0]}}, "capture_pose_invalid"),
        ({"body_pose_enu": {"position_m": [25, 30, 6], "orientation_xyzw": [0, 0, 1, 1]}}, "capture_pose_invalid"),
        ({"body_pose_enu": {"position_m": [25, float("nan"), 6], "orientation_xyzw": [0, 0, 1, 0]}}, "capture_pose_invalid"),
        ({"pose_sim_stamp_ns": 29700000000}, "capture_samples_unaligned"),
        ({"intrinsics_k": [0] * 9}, "camera_info_invalid"),
        ({"payload_sha256": "0" * 64}, "image_integrity_mismatch"),
    ],
)
def test_invalid_capture_never_changes_arrival_or_observation(capture_case, fake_payload, override_sample, reason):
    sample = {**capture_case["sample"], **override_sample}
    assert replay_fixture(capture_case, sample, fake_payload) == {
        "arrival": "arrived", "capture": reason, "observation": "undetermined",
    }


@pytest.mark.parametrize("missing_key", ["body_pose_enu", "pose_sim_stamp_ns"])
def test_missing_body_pose_or_stamp_rejects_an_otherwise_valid_capture(capture_case, fake_payload, missing_key):
    sample = dict(capture_case["sample"])
    del sample[missing_key]
    assert replay_fixture(capture_case, sample, fake_payload) == {
        "arrival": "arrived", "capture": "capture_pose_missing", "observation": "undetermined",
    }


@pytest.mark.parametrize(
    ("pose_source", "expected"),
    [
        (None, "capture_pose_source_missing"),
        ({"gazebo_run_id": "fixture-gazebo-run-1"}, "capture_pose_source_missing"),
        ({"gazebo_run_id": "fixture-gazebo-run-1", "gazebo_model_entity_id": 201}, "capture_pose_source_mismatch"),
        ({"gazebo_run_id": "fixture-prior-run", "gazebo_model_entity_id": 202}, "capture_pose_source_mismatch"),
    ],
)
def test_same_image_and_pose_timestamp_cannot_hide_wrong_pose_source(capture_case, fake_payload, pose_source, expected):
    assert replay_fixture(capture_case, capture_case["sample"], fake_payload, pose_source=pose_source) == {
        "arrival": "arrived", "capture": expected, "observation": "undetermined",
    }


@pytest.mark.parametrize(
    ("received_offset_ns", "checked_offset_ns", "expected"),
    [
        (-50_000_000, -1, "fixture_valid"),
        (-50_000_000, 0, "capture_request_timeout"),
        (599_000_000_000, 599_050_000_000, "capture_request_timeout"),
    ],
)
def test_request_deadline_is_independent_of_fresh_receipt(
    capture_case, fake_payload, received_offset_ns, checked_offset_ns, expected,
):
    deadline = capture_case["capture_request"]["requested_monotonic_ns"] + FIXTURE_REQUEST_TIMEOUT_WALL_NS
    sample = {
        **capture_case["sample"],
        "received_monotonic_ns": deadline + received_offset_ns,
        "checked_monotonic_ns": deadline + checked_offset_ns,
    }
    receive_age = sample["checked_monotonic_ns"] - sample["received_monotonic_ns"]
    assert 0 <= receive_age <= capture_case["proposal_limits"]["max_receive_age_wall_ns"]
    assert replay_fixture(capture_case, sample, fake_payload) == {
        "arrival": "arrived", "capture": expected, "observation": "undetermined",
    }
