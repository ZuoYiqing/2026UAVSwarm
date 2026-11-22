"""Replay checks on a pinned synthetic PNG and its visual annotation, not a detector or a review issuer."""
from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from check_target_001_review_fixture import BASELINE, CAPTURE_SOURCE, CRITERION, REVIEW_FIXTURE, canonical_digest, require


VISIBLE = {
    "commit": "940a9d93a74e1fa98d312a39969f8e220212d107",
    "fixture": "docs/simulation/fixtures/simple_recon_v0_1_target_001_visible_v1.json",
    "fixture_content_sha256": "fab98d5a13b60c2035a47b6370d1f30e4acb4f40c0180a785777de3aa61228a9",
}
IMAGE_PATH = "docs/simulation/fixtures/target_001_visible_synthetic.png"
ANNOTATION = Path(__file__).resolve().parents[1] / "examples/target_001_visible_pixel_annotation_v0_1.json"
OPERATIONS = {"observation_without_review": "undetermined", "linked_task_completion": "not_asserted",
              "advance_observe_step": False, "changes_closeout": False}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify(capture: dict, visible: dict, png: bytes, record: dict) -> dict:
    require(record["scope"] == "fake_adapter_only" and record["execution_authorized"] is False
            and record["evidence_origin"] == visible["evidence_origin"] == "synthetic_test_fixture"
            and visible["execution_authorized"] is False and record["source_baseline"] == BASELINE
            and record["visual_source"] == VISIBLE, "ANNOTATION_SCOPE_MISMATCH")
    require(canonical_digest(capture) == CAPTURE_SOURCE["content_sha256"]
            and canonical_digest(visible) == VISIBLE["fixture_content_sha256"]
            and visible["capture_base"] == {k: CAPTURE_SOURCE[k] for k in ("commit", "path")},
            "SOURCE_FIXTURE_MISMATCH")
    require(record["review_record"] is None and record["operation_expectation"] == OPERATIONS,
            "SIGNED_REVIEW_OR_OPERATION_OUTCOME_FORBIDDEN")
    annotation = record["annotation"]
    require(annotation["criterion_version"] == CRITERION and annotation["confidence"] is None
            and annotation["expected_outcome_for_synthetic_pixel_review"] == "observed"
            and annotation["note"].strip(), "PIXEL_ANNOTATION_INVALID")

    overrides = visible["overrides"]
    arrival = {**capture["arrival"], **overrides["arrival"]}
    request = {**capture["capture_request"], **overrides["capture_request"]}
    sample = {**capture["sample"], **overrides["sample"]}
    require(all(request[key] == sample[key] for key in ("request_id", "gazebo_run_id", "gazebo_model_entity_id")),
            "CAPTURE_BINDING_MISMATCH")
    capture_id = "cap-" + canonical_digest({
        "plan_id": arrival["plan_id"], "runtime_run_id": arrival["runtime_run_id"],
        "request_id": request["request_id"], "image_ref": sample["image_ref"],
    })[:16]
    binding = {
        **{key: capture[key] for key in ("scene_id", "map_version", "target_id")},
        **{key: arrival[key] for key in ("plan_id", "runtime_run_id", "node_id")},
        "gazebo_run_id": request["gazebo_run_id"], "capture_request_id": request["request_id"],
        "capture_id": capture_id,
    }
    previous = read_json(REVIEW_FIXTURE)
    require(record["binding"] == binding
            and capture_id != previous["review"]["capture_id"]
            and sample["image_ref"] != previous["review"]["image"]["ref"]
            and arrival["runtime_run_id"] != previous["binding"]["runtime_run_id"],
            "BINDING_MISMATCH_OR_REUSED_FIXTURE_ID")

    declared = visible["image"]
    png_hash = hashlib.sha256(png).hexdigest()
    require(png_hash == declared["png_sha256"], "PNG_DIGEST_MISMATCH")
    with Image.open(BytesIO(png)) as frame:
        require(frame.format == "PNG" and frame.mode == "RGB"
                and frame.size == (declared["width"], declared["height"]), "PNG_LAYOUT_MISMATCH")
        width, height = frame.size
        raw = frame.tobytes()
        raw_hash = hashlib.sha256(raw).hexdigest()
        require(len(raw) == declared["raw_bytes"] and raw_hash == sample["payload_sha256"]
                and sample["image_ref"] == "sha256:" + raw_hash, "RGB8_DIGEST_MISMATCH")
        # Check the two declared colors of this exact synthetic fixture; never infer anything in a live image.
        colors = visible["reference_pixels"]
        marker, background = tuple(colors["marker_rgb"]), tuple(colors["background_rgb"])
        require({color for _, color in frame.getcolors(maxcolors=3) or []} == {marker, background},
                "SYNTHETIC_PALETTE_MISMATCH")
        pixels = [(index % width, index // width) for index, color in enumerate(frame.getdata()) if color == marker]
    xs, ys = zip(*pixels)
    region = {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1}
    require(region == annotation["region"] == colors["region"] and min(region["w"], region["h"]) >= 16
            and region["x"] > 0 and region["y"] > 0
            and region["x"] + region["w"] < width and region["y"] + region["h"] < height,
            "PIXEL_REGION_MISMATCH")
    image = {"png_path": IMAGE_PATH, "png_sha256": png_hash, "rgb8_sha256": raw_hash,
             "width": width, "height": height, "encoding": "RGB8"}
    require(record["image"] == image and declared["png_path"] == IMAGE_PATH, "IMAGE_REFERENCE_MISMATCH")
    return {"scope": "fake_adapter_only", "visual_source": VISIBLE, "binding": binding, "image": image,
            "pixel_region": region, "marked_pixel_count": len(pixels), "criterion_version": CRITERION,
            "synthetic_pixel_expectation": "observed", "signed_review": False,
            "operation_expectation": OPERATIONS, "execution_authorized": False}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--simulation-root", type=Path, required=True)
    cli.add_argument("--output", type=Path, help="Optional new local proof JSON")
    args = cli.parse_args()
    root = args.simulation_root
    proof = verify(read_json(root / CAPTURE_SOURCE["path"]), read_json(root / VISIBLE["fixture"]),
                   (root / IMAGE_PATH).read_bytes(), read_json(ANNOTATION))
    body = json.dumps(proof, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    print(body, end="")


if __name__ == "__main__":
    main()
