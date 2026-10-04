#!/usr/bin/env python3
"""Sample each managed Gazebo camera without opening a MAVLink endpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from harness import load_manifest, read_state


def _stamp(message: object) -> float:
    stamp = message.header.stamp
    return float(stamp.sec) + float(stamp.nsec) / 1_000_000_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--minimum-frames", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from gz.msgs10.camera_info_pb2 import CameraInfo
    from gz.msgs10.image_pb2 import Image
    from gz.transport13 import Node

    manifest = load_manifest(args.config)
    state = read_state() or {}
    node = Node()
    world = manifest["world_name"]
    discovered = set(node.topic_list())
    rows: dict[str, dict] = {}
    lock = threading.Lock()

    for vehicle in manifest["vehicles"]:
        node_id = vehicle["node_id"]
        model = vehicle["gazebo_model_name"]
        base = f"/world/{world}/model/{model}/link/camera_link/sensor/camera"
        image_topic = f"{base}/image"
        info_topic = f"{base}/camera_info"
        rows[node_id] = {
            "model": model,
            "image_topic": image_topic,
            "camera_info_topic": info_topic,
            "topics_present": image_topic in discovered and info_topic in discovered,
            "first_frame": None,
            "last_frame": None,
            "sample_count": 0,
            "timestamps_increasing": True,
            "camera_info": None,
        }

        def on_image(message: Image, *, owner: str = node_id) -> None:
            frame = {
                "sim_timestamp_s": _stamp(message),
                "width": message.width,
                "height": message.height,
                "step": message.step,
                "pixel_format_type": message.pixel_format_type,
                "data_bytes": len(message.data),
                "sha256": hashlib.sha256(message.data).hexdigest(),
            }
            with lock:
                row = rows[owner]
                if row["first_frame"] is None:
                    row["first_frame"] = frame
                    frame["nonzero_pixels_present"] = any(message.data)
                elif frame["sim_timestamp_s"] <= row["last_frame"]["sim_timestamp_s"]:
                    row["timestamps_increasing"] = False
                row["last_frame"] = frame
                row["sample_count"] += 1

        def on_info(message: CameraInfo, *, owner: str = node_id) -> None:
            sample = {
                "sim_timestamp_s": _stamp(message),
                "width": message.width,
                "height": message.height,
                "intrinsics": list(message.intrinsics.k),
            }
            with lock:
                rows[owner]["camera_info"] = sample

        node.subscribe(Image, image_topic, on_image)
        node.subscribe(CameraInfo, info_topic, on_info)

    time.sleep(args.duration)
    for row in rows.values():
        first = row["first_frame"]
        last = row["last_frame"]
        row["sim_span_s"] = last["sim_timestamp_s"] - first["sim_timestamp_s"] if first and last else 0.0
        row["sim_fps"] = (row["sample_count"] - 1) / row["sim_span_s"] if row["sim_span_s"] > 0 else 0.0
        row["image_valid"] = bool(
            row["topics_present"]
            and row["camera_info"]
            and row["sample_count"] >= args.minimum_frames
            and row["timestamps_increasing"]
            and first["nonzero_pixels_present"]
            and all(frame["width"] == 1280 and frame["height"] == 960
                    and frame["step"] == 3840 and frame["data_bytes"] == 3686400
                    and frame["pixel_format_type"] == 3
                    for frame in (first, last))
        )
    all_topics = [row["image_topic"] for row in rows.values()]
    first_hashes = [row["first_frame"]["sha256"] for row in rows.values() if row["first_frame"]]
    streams_observed = bool(
        len(set(all_topics)) == len(rows)
        and len(first_hashes) == len(rows)
        and len(set(first_hashes)) == len(rows)
        and all(row["image_valid"] for row in rows.values())
    )
    payload = {
        "camera_stream_status": "observed" if streams_observed else "invalid",
        "system_readiness": "not_assessed",
        "run_id": state.get("run_id"),
        "manifest_path": str(args.config.resolve()),
        "world": world,
        "sample_wall_s": args.duration,
        "distinct_image_topics": len(set(all_topics)) == len(rows),
        "distinct_first_frame_hashes": len(first_hashes) == len(rows) and len(set(first_hashes)) == len(rows),
        "vehicles": rows,
    }
    encoded = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if streams_observed else 1


if __name__ == "__main__":
    raise SystemExit(main())
