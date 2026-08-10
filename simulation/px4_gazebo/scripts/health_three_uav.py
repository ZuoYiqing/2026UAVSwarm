#!/usr/bin/env python3
"""Report process, model and MAVLink heartbeat readiness for all configured UAVs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from harness import DEFAULT_MANIFEST_PATH, HarnessError, collect_health, load_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        payload = collect_health(load_manifest(args.config), timeout_s=args.timeout)
    except HarnessError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2
    print(
        json.dumps(
            payload,
            indent=2 if args.pretty else None,
            ensure_ascii=False,
        )
    )
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
