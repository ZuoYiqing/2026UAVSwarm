#!/usr/bin/env python3
"""Observe PX4 SITL telemetry without sending flight commands.

This script is intentionally read-only: it waits for heartbeat, listens to
telemetry messages, summarizes LOCAL_POSITION_NED altitude, and optionally writes
JSON/CSV files. It does not send ARM, TAKEOFF, LAND, mode changes, or payload
commands.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any


def ned_z_to_altitude_m(z: float) -> float:
    """PX4 LOCAL_POSITION_NED.z is positive down; altitude is max(0, -z)."""
    return max(0.0, -float(z))


def empty_summary(endpoint: str, duration_s: float) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "heartbeat_received": False,
        "sample_count": 0,
        "first_z": None,
        "last_z": None,
        "min_z": None,
        "max_z": None,
        "max_altitude_m": 0.0,
        "duration_s": float(duration_s),
        "first_timestamp": None,
        "last_timestamp": None,
        "heartbeat_count": 0,
        "attitude_count": 0,
        "global_position_int_count": 0,
    }


def update_local_position_summary(summary: dict[str, Any], *, z: float, timestamp: float) -> None:
    z_value = float(z)
    altitude_m = ned_z_to_altitude_m(z_value)
    count = int(summary.get("sample_count") or 0)
    summary["sample_count"] = count + 1
    summary["first_z"] = z_value if summary.get("first_z") is None else summary["first_z"]
    summary["last_z"] = z_value
    summary["min_z"] = z_value if summary.get("min_z") is None else min(float(summary["min_z"]), z_value)
    summary["max_z"] = z_value if summary.get("max_z") is None else max(float(summary["max_z"]), z_value)
    summary["max_altitude_m"] = round(max(float(summary.get("max_altitude_m") or 0.0), altitude_m), 3)
    summary["first_timestamp"] = timestamp if summary.get("first_timestamp") is None else summary["first_timestamp"]
    summary["last_timestamp"] = timestamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observe PX4 SITL telemetry without sending commands")
    parser.add_argument("--endpoint", default="udpin:127.0.0.1:14540")
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--include-attitude", action="store_true")
    parser.add_argument("--include-global-position", action="store_true")
    parser.add_argument("--heartbeat-timeout-s", type=float, default=5.0)
    return parser


def observe(args: argparse.Namespace) -> dict[str, Any]:
    from pymavlink import mavutil  # type: ignore

    summary = empty_summary(args.endpoint, args.duration_s)
    samples: list[dict[str, Any]] = []
    conn = mavutil.mavlink_connection(args.endpoint, timeout=max(float(args.heartbeat_timeout_s), 0.1))
    hb = conn.wait_heartbeat(timeout=max(float(args.heartbeat_timeout_s), 0.1))
    summary["heartbeat_received"] = hb is not None

    deadline = time.time() + max(float(args.duration_s), 0.1)
    message_types = ["HEARTBEAT", "LOCAL_POSITION_NED"]
    if args.include_attitude:
        message_types.append("ATTITUDE")
    if args.include_global_position:
        message_types.append("GLOBAL_POSITION_INT")

    while time.time() < deadline:
        msg = conn.recv_match(type=message_types, blocking=True, timeout=0.5)
        if msg is None:
            continue
        now = time.time()
        msg_type = msg.get_type() if hasattr(msg, "get_type") else type(msg).__name__
        if msg_type == "HEARTBEAT":
            summary["heartbeat_count"] = int(summary.get("heartbeat_count") or 0) + 1
            continue
        if msg_type == "ATTITUDE":
            summary["attitude_count"] = int(summary.get("attitude_count") or 0) + 1
            continue
        if msg_type == "GLOBAL_POSITION_INT":
            summary["global_position_int_count"] = int(summary.get("global_position_int_count") or 0) + 1
            continue
        if msg_type == "LOCAL_POSITION_NED":
            z = float(getattr(msg, "z", 0.0))
            altitude_m = ned_z_to_altitude_m(z)
            update_local_position_summary(summary, z=z, timestamp=now)
            samples.append({"timestamp": now, "z": z, "altitude_m": altitude_m})

    if args.output_json:
        out = Path(args.output_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if args.output_csv:
        out = Path(args.output_csv).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["timestamp", "z", "altitude_m"])
            writer.writeheader()
            writer.writerows(samples)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = observe(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
