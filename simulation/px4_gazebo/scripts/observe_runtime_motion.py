#!/usr/bin/env python3
"""Collect three-node SITL movement evidence from the existing Runtime API."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import atomic_json, timestamp_seconds
from harness import RUNTIME_ROOT, load_manifest, read_state, utc_now
from runtime_evidence import NoRedirect

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/three_uav_mono_cam_sitl.json"
MINIMUM_CLIMB_M = 2.0
MINIMUM_HORIZONTAL_STEP_M = 0.5
MINIMUM_HORIZONTAL_TRAVEL_M = 3.0


def _position_rows(payload: dict[str, Any], expected: dict[str, tuple[int, int]]) -> dict:
    if payload.get("backend_mode") != "sitl" or payload.get("source") != "vehicle_registry":
        raise ValueError("expected a SITL vehicle_registry snapshot")
    rows = {}
    for node in payload["nodes"]:
        node_id = node["node_id"]
        if node_id in rows or (node.get("system_id"), node.get("component_id")) != expected.get(node_id):
            raise ValueError(f"unexpected, duplicated or mismatched node {node_id}")
        rows[node_id] = node
    return rows


def summarize_motion(rows: list[dict]) -> dict:
    baseline = rows[0]["local_ned_m"] if rows and rows[0]["armed"] is False else None
    armed = [row["local_ned_m"] for row in rows if row["armed"] is True]
    climb = max((baseline[2] - point[2] for point in armed), default=0.0) if baseline else 0.0
    airborne = [point for point in armed if baseline and baseline[2] - point[2] >= MINIMUM_CLIMB_M]
    travel = max((math.dist(point[:2], airborne[0][:2]) for point in airborne), default=0.0)
    steps = sum(math.dist(left[:2], right[:2]) >= MINIMUM_HORIZONTAL_STEP_M
                for left, right in zip(airborne, airborne[1:]))
    return {
        "motion_observed": climb >= MINIMUM_CLIMB_M and travel >= MINIMUM_HORIZONTAL_TRAVEL_M and steps >= 2,
        "max_relative_climb_m": climb,
        "horizontal_displacement_m": travel,
        "horizontal_steps": steps,
        "samples": rows,
    }


def observe_motion(fetch, expected: dict[str, tuple[int, int]], *, duration_s: float, interval_s: float) -> dict:
    started_at = utc_now()
    started = time.monotonic()
    samples: dict[str, list[dict]] = {node_id: [] for node_id in expected}
    last_seen = dict.fromkeys(expected, float("-inf"))
    read_failures = 0
    last_read_error = None
    while time.monotonic() - started < duration_s:
        try:
            rows = _position_rows(fetch(), expected)
            for node_id, node in rows.items():
                position = node.get("local_position") or {}
                if (node.get("source") != "px4_telemetry" or node.get("connected") is not True
                        or node.get("stale") is not False or position.get("frame") != "NED"):
                    continue
                xyz = [position.get(axis) for axis in ("x_m", "y_m", "z_down_m")]
                if not all(type(value) in (int, float) and math.isfinite(value) for value in xyz):
                    continue
                stamp = timestamp_seconds(node["last_seen"])
                if stamp <= last_seen[node_id]:
                    continue
                last_seen[node_id] = stamp
                samples[node_id].append({"timestamp": node["last_seen"], "local_ned_m": xyz,
                                         "armed": node.get("armed"), "flight_mode": node.get("flight_mode")})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            read_failures += 1
            last_read_error = f"{type(exc).__name__}: {exc}"
        time.sleep(min(interval_s, max(0.0, duration_s - (time.monotonic() - started))))

    vehicles = {node_id: summarize_motion(rows) for node_id, rows in samples.items()}
    return {"status": "PASS" if all(row["motion_observed"] for row in vehicles.values()) else "FAIL",
            "scope": "SITL_RUNTIME_MOTION_ONLY", "started_at": started_at, "completed_at": utc_now(),
            "read_failures": read_failures, "last_read_error": last_read_error, "vehicles": vehicles}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/telemetry/latest")
    parser.add_argument("--duration", type=float, default=180)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=RUNTIME_ROOT / "validation/runtime-motion.json")
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.url)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or url.path != "/api/telemetry/latest" or url.username or url.password or url.query or url.fragment):
        parser.error("--url must be a loopback Runtime /api/telemetry/latest endpoint")
    if not 0 < args.duration <= 1800 or not 0.1 <= args.interval <= 5:
        parser.error("duration must be in (0, 1800] seconds and interval in [0.1, 5] seconds")
    manifest = load_manifest(args.config)
    state = read_state()
    if (not state or not state.get("run_id")
            or state.get("manifest_path") != str(args.config.resolve())):
        parser.error("start the managed SITL harness with the same --config before observing motion")
    run_id = state["run_id"]
    expected = {row["node_id"]: (row["system_id"], row.get("component_id", 1))
                for row in manifest["vehicles"]}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def fetch():
        with opener.open(args.url, timeout=2) as response:
            return json.load(response)

    report = observe_motion(fetch, expected, duration_s=args.duration, interval_s=args.interval)
    report["run_id"] = run_id
    final_state = read_state()
    if not final_state or final_state.get("run_id") != run_id:
        report.update(status="FAIL", reason="managed_run_changed_during_observation")
    atomic_json(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "motion_observed": {node_id: row["motion_observed"]
                                          for node_id, row in report["vehicles"].items()}}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
