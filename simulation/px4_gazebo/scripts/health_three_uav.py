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
from health import DEFAULT_STABILITY_WINDOW_S, HEALTH_MODES, collect_health
from patrol import PatrolError, require_standalone_endpoints
from evidence import atomic_json
from runtime_evidence import publish


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--mode",
        choices=sorted(HEALTH_MODES),
        default="standalone",
        help="standalone probes MAVLink; integrated consumes Runtime telemetry",
    )
    parser.add_argument(
        "--runtime-telemetry",
        type=Path,
        help="Versioned Runtime telemetry envelope; missing data yields system unknown",
    )
    parser.add_argument(
        "--stability-window",
        type=float,
        default=DEFAULT_STABILITY_WINDOW_S,
        help="Seconds of continuous fresh heartbeat evidence required per UAV",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--runtime-output", type=Path, help="Export the Runtime 1.0 evidence object separately")
    parser.add_argument("--publish-runtime", help="Explicit loopback API base, e.g. http://127.0.0.1:8765/api")
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
        runtime_telemetry = None
        if args.mode == "integrated":
            if args.runtime_telemetry is not None:
                runtime_telemetry = json.loads(args.runtime_telemetry.read_text(encoding="utf-8"))
                if not isinstance(runtime_telemetry, dict):
                    raise HarnessError("Runtime telemetry root must be a JSON object")
        else:
            require_standalone_endpoints(manifest)
        payload = collect_health(
            manifest,
            timeout_s=args.timeout,
            stability_window_s=args.stability_window,
            mode=args.mode,
            runtime_telemetry=runtime_telemetry,
            runtime_telemetry_provider=(
                (lambda: json.loads(args.runtime_telemetry.read_text(encoding="utf-8")))
                if args.mode == "integrated" and args.runtime_telemetry is not None else None
            ),
        )
        if args.mode == "standalone":
            require_standalone_endpoints(manifest)
    except (HarnessError, PatrolError, OSError, json.JSONDecodeError) as exc:
        payload = {
            "contract_version": "1.0",
            "mode": args.mode,
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
    if "runtime_evidence" in payload:
        if args.runtime_output:
            atomic_json(args.runtime_output, payload["runtime_evidence"])
        if args.publish_runtime:
            try:
                payload["publication"] = publish(args.publish_runtime, payload["runtime_evidence"])
            except Exception as exc:
                payload["publication"] = {"error": f"{type(exc).__name__}:{exc}"}
                exit_code = 2
    atomic_json(args.output, payload)
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
