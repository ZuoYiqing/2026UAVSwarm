#!/usr/bin/env python3
"""Measure three local origins without taking ownership of MAVLink endpoints."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import capture_readonly_calibrations
from evidence import atomic_json
from harness import DEFAULT_MANIFEST_PATH, RUNTIME_ROOT, load_manifest, utc_now
from runtime_evidence import publish


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=RUNTIME_ROOT / "calibration/latest.json")
    parser.add_argument("--publish-runtime", help="Existing loopback API base; only calibration evidence is posted")
    args = parser.parse_args(argv)
    if not 2 <= args.duration <= 10:
        parser.error("duration must be between 2 and 10 seconds")
    try:
        calibrations = capture_readonly_calibrations(load_manifest(args.config), duration_s=args.duration)
        publications = [publish(args.publish_runtime, row, kind="calibration") for row in calibrations] if args.publish_runtime else []
        payload = {"status": "PASS", "mode": "read_only_no_mavlink", "checked_at": utc_now(),
                   "calibrations": calibrations, "publications": publications}
    except Exception as exc:
        payload = {"status": "FAIL", "checked_at": utc_now(), "error": f"{type(exc).__name__}:{exc}"}
    atomic_json(args.output, payload)
    print(json.dumps({k:v for k,v in payload.items() if k != "calibrations"}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
