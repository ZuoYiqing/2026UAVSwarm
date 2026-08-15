#!/usr/bin/env python3
"""Report process, model and MAVLink heartbeat readiness for all configured UAVs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from harness import DEFAULT_MANIFEST_PATH, RUNTIME_ROOT, HarnessError, load_manifest
from health import DEFAULT_STABILITY_WINDOW_S, collect_health
from patrol import PatrolError, require_standalone_endpoints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--stability-window",
        type=float,
        default=DEFAULT_STABILITY_WINDOW_S,
        help="Seconds of continuous fresh heartbeat evidence required per UAV",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=RUNTIME_ROOT / "health" / "latest.json",
        help="Path for the latest machine-readable health evidence",
    )
    args = parser.parse_args(argv)
    exit_code = 0
    try:
        manifest = load_manifest(args.config)
        require_standalone_endpoints(manifest)
        payload = collect_health(
            manifest,
            timeout_s=args.timeout,
            stability_window_s=args.stability_window,
        )
        require_standalone_endpoints(manifest)
    except (HarnessError, PatrolError) as exc:
        payload = {
            "contract_version": "1.0",
            "status": "error",
            "ready": False,
            "reason": (
                "endpoint_in_use"
                if "endpoint_in_use" in str(exc)
                else "health_error"
            ),
            "error": str(exc),
        }
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            payload,
            indent=2 if args.pretty else None,
            ensure_ascii=False,
        )
    )
    if exit_code:
        return exit_code
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
