"""Replay the proposed capture evidence checks without a simulator or HTTP."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from simulation.px4_gazebo.harness import WORLD_SHA256_SCHEME, canonical_world_bytes


ROOT = Path(__file__).resolve().parents[2]


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


def replay_fixture(capture_case, sample, payload):
    request = capture_case["capture_request"]
    limits = capture_case["proposal_limits"]
    manifest = read_json("simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json")
    arrival = capture_case["arrival"]
    vehicle = next(v for v in manifest["vehicles"] if v["node_id"] == arrival["node_id"])
    topic_base = f"/world/{manifest['world_name']}/model/{vehicle['gazebo_model_name']}/link/camera_link/sensor/camera"
    arrival_status = "arrived" if arrival["arrival_observed"] is True else "unverified"
    result = {"arrival": arrival_status, "capture": "fixture_valid", "observation": "undetermined"}
    if any(sample[key] != request[key] for key in ("request_id", "gazebo_run_id", "gazebo_model_entity_id")):
        result["capture"] = "capture_context_mismatch"
    elif (sample["image_topic"] != f"{topic_base}/image"
          or sample["camera_info_topic"] != f"{topic_base}/camera_info"):
        result["capture"] = "image_source_mismatch"
    elif (sample["image_sim_stamp_ns"] <= request["after_sim_stamp_ns"]
          or sample["received_monotonic_ns"] < request["requested_monotonic_ns"]
          or not 0 <= sample["checked_monotonic_ns"] - sample["received_monotonic_ns"] <= limits["max_receive_age_wall_ns"]):
        result["capture"] = "frame_stale"
    elif (abs(sample["image_sim_stamp_ns"] - sample["pose_sim_stamp_ns"]) > limits["max_pose_skew_sim_ns"]
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
