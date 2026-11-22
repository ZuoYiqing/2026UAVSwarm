"""Check one synthetic capture-to-review binding, not perform vision or Runtime actions."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from uav_runtime.observation.review_record import build_review, record_sha256, validate_review


BASELINE = "2d01ffc889d70e64f74391a5dce6f8eadd77ce38"
CAPTURE_SOURCE = {
    "commit": "6952513e8ee8482d7cf48e364603b2893909dbfe",
    "path": "docs/simulation/fixtures/simple_recon_v0_1_target_001_capture_v1.json",
    "content_sha256": "caf93b5f03e94187c469a608c2cdb2e334f8fb564ba86982a0cca59731e129c5",
}
REVIEW_FIXTURE = Path(__file__).resolve().parents[1] / "examples/target_001_valid_capture_undetermined_v0_1.json"
CRITERION = "target-001-green-disk-pixels-v0.1"
EXPECTED = {"capture": "fixture_valid", "observation": "undetermined",
            "advance_observe_step": False, "linked_task_completion": "not_asserted"}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def canonical_digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def verify(capture: dict, fixture: dict) -> dict:
    require(canonical_digest(capture) == CAPTURE_SOURCE["content_sha256"], "CAPTURE_FIXTURE_DIGEST_MISMATCH")
    require(capture["source_baseline"] == fixture["baseline"] == BASELINE
            and capture["evidence_origin"] == fixture["evidence_origin"] == "synthetic_test_fixture"
            and fixture["scope"] == "fake_adapter_only" and fixture["execution_authorized"] is False
            and fixture["capture_source"] == CAPTURE_SOURCE,
            "FIXTURE_SCOPE_MISMATCH")
    arrival, request, sample = capture["arrival"], capture["capture_request"], capture["sample"]
    limits = capture["proposal_limits"]
    require(arrival["arrival_observed"] is True and arrival["runtime_run_id"] != request["gazebo_run_id"]
            and all(request[field] == sample[field]
                    for field in ("request_id", "gazebo_run_id", "gazebo_model_entity_id")),
            "CAPTURE_SOURCE_MISMATCH")
    binding = {
        **{field: capture[field] for field in ("scene_id", "map_version", "target_id")},
        **{field: arrival[field] for field in ("plan_id", "runtime_run_id", "node_id")},
        "arrival_step_id": arrival["step_id"],
        "proposed_observe_step_id": "observe-01",
        "capture_request_id": request["request_id"],
        "gazebo_run_id": request["gazebo_run_id"],
        "image_sim_stamp_ns": sample["image_sim_stamp_ns"],
        "capture_id_origin": "derived_fixture_only",
        "iso_time_origin": "synthetic_epoch_2000_plus_simulation_offset",
    }
    require(fixture["binding"] == binding, "RUNTIME_CAPTURE_BINDING_MISMATCH")
    age = sample["checked_monotonic_ns"] - sample["received_monotonic_ns"]
    pose_skew = abs(sample["image_sim_stamp_ns"] - sample["pose_sim_stamp_ns"])
    info_skew = abs(sample["image_sim_stamp_ns"] - sample["camera_info_sim_stamp_ns"])
    require(sample["image_sim_stamp_ns"] > request["after_sim_stamp_ns"]
            and sample["received_monotonic_ns"] >= request["requested_monotonic_ns"]
            and 0 <= age <= limits["max_receive_age_wall_ns"]
            and pose_skew <= limits["max_pose_skew_sim_ns"]
            and info_skew <= limits["max_camera_info_skew_sim_ns"],
            "CAPTURE_FIXTURE_OUTSIDE_PROPOSED_TIME_BOUNDS")

    # Reconstruct the provided bytes verbatim; this is not a detector or a new image.
    width, height = sample["width"], sample["height"]
    rows = [bytes(rgb) * width for rgb in sample["synthetic_rows_rgb"]]
    require(rows and height % len(rows) == 0 and sample["encoding"] == "RGB8"
            and sample["row_stride_bytes"] == width * 3 and all(len(row) == width * 3 for row in rows),
            "IMAGE_LAYOUT_MISMATCH")
    payload = b"".join(rows) * (height // len(rows))
    sha = hashlib.sha256(payload).hexdigest()
    require(len(payload) == sample["row_stride_bytes"] * height
            and sha == sample["payload_sha256"] and sample["image_ref"] == "sha256:" + sha,
            "IMAGE_INTEGRITY_MISMATCH")
    capture_key = {"plan_id": arrival["plan_id"], "runtime_run_id": arrival["runtime_run_id"],
                   "request_id": request["request_id"], "image_ref": sample["image_ref"]}
    capture_id = "cap-" + canonical_digest(capture_key)[:16]
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    fixture_time = epoch + timedelta(microseconds=sample["image_sim_stamp_ns"] // 1000)
    image = {
        "ref": sample["image_ref"], "sha256": sha, "width": width, "height": height, "encoding": sample["encoding"],
        "captured_at": fixture_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "vehicle_id": arrival["node_id"], "camera_id": sample["image_topic"].removesuffix("/image"),
    }
    review = validate_review(fixture["review"])
    require(review["outcome"] == "undetermined" and review["confidence"] is None
            and review["linked_task_completion"] == "not_asserted" and fixture["expected"] == EXPECTED,
            "REVIEW_OUTCOME_MISMATCH")
    require(review["image"] == image and review["capture_id"] == capture_id, "REVIEW_FRAME_MISMATCH")
    rebuilt = build_review(
        task_id="TASK-target-001", target_id=capture["target_id"], capture_id=capture_id, image=image,
        criterion_version=CRITERION, reviewer="human:fixture-reviewer",
        reviewed_at="2000-01-01T00:00:31.000Z", created_at="2000-01-01T00:00:31.000Z",
        outcome="undetermined", note=review["note"],
    )
    require(review == rebuilt, "REVIEW_RECORD_MISMATCH")
    return {
        "baseline": BASELINE, "scope": "fake_adapter_only", "evidence_origin": "synthetic_test_fixture",
        "capture_source": CAPTURE_SOURCE, "binding": binding, "capture_id": capture_id,
        "image_sha256": sha, "payload_bytes": len(payload), "sample_receive_age_ms": age / 1_000_000,
        "pose_skew_ms": pose_skew / 1_000_000, "review_id": review["review_id"],
        "review_content_sha256": record_sha256(review), "criterion_version": CRITERION,
        "decision_origin": "declared_fixture_not_live_review", "runtime_lifecycle_tested": False,
        "execution_authorized": False, "expected": EXPECTED,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-fixture", type=Path, required=True)
    parser.add_argument("--review-fixture", type=Path, default=REVIEW_FIXTURE)
    parser.add_argument("--output", type=Path, help="Optional new local proof file")
    args = parser.parse_args()
    capture = json.loads(args.capture_fixture.read_text(encoding="utf-8-sig"))
    fixture = json.loads(args.review_fixture.read_text(encoding="utf-8-sig"))
    proof = verify(capture, fixture)
    body = json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    print(body, end="")


if __name__ == "__main__":
    main()
