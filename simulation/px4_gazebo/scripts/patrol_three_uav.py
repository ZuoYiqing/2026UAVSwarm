#!/usr/bin/env python3
"""Run the deterministic standalone three-UAV patrol acceptance validator."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
HARNESS_DIR = SCRIPT_DIR.parent
REPO_ROOT = HARNESS_DIR.parent.parent
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(REPO_ROOT / "src"))

import harness  # noqa: E402
import health as health_service  # noqa: E402
import patrol  # noqa: E402
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig  # noqa: E402
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession  # noqa: E402


def _session(vehicle: dict[str, Any]) -> MavlinkBackendSession:
    return MavlinkBackendSession.from_config(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint=str(vehicle["command_endpoint"]),
            target_system=int(vehicle["system_id"]),
            target_component=int(vehicle.get("component_id", 1)),
            connect_timeout_ms=5000,
            command_timeout_ms=10000,
            observe_timeout_ms=45000,
        )
    )


def _write_report(payload: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    output_path = output_dir / f"three_uav_patrol_{timestamp}.json"
    payload["result_path"] = str(output_path)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=harness.DEFAULT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--patrol",
        type=Path,
        default=patrol.DEFAULT_PATROL_PATH,
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=harness.RUNTIME_ROOT / "validation",
    )
    parser.add_argument("--health-timeout", type=float, default=5.0)
    parser.add_argument(
        "--health-stability-window",
        type=float,
        default=health_service.DEFAULT_STABILITY_WINDOW_S,
    )
    parser.add_argument("--command-timeout", type=float, default=10.0)
    parser.add_argument("--landing-timeout", type=float, default=45.0)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_at = harness.utc_now()
    payload: dict[str, Any]
    try:
        manifest = harness.load_manifest(args.config)
        scene = harness.load_json(harness.resolve_repo_path(str(manifest["scene_path"])))
        plan = patrol.load_patrol_plan(
            args.patrol,
            manifest=manifest,
            scene=scene,
        )

        # The standalone validator must own all three UDP listeners. Runtime or
        # any other receiver must be stopped before this point.
        patrol.require_standalone_endpoints(manifest)
        health = health_service.collect_health(
            manifest,
            timeout_s=args.health_timeout,
            stability_window_s=args.health_stability_window,
        )
        if not health["ready"]:
            raise patrol.PatrolError("three_uav_health_not_ready")
        patrol.require_standalone_endpoints(manifest)

        controllers = [
            patrol.MavlinkPatrolController(vehicle, _session(vehicle))
            for vehicle in manifest["vehicles"]
        ]
        payload = patrol.run_patrol(
            plan,
            controllers,
            command_timeout_s=args.command_timeout,
            landing_timeout_s=args.landing_timeout,
        )
        payload["health"] = health
        payload["manifest_path"] = str(args.config.resolve())
        payload["patrol_path"] = str(args.patrol.resolve())
        payload["started_at"] = started_at
    except Exception as exc:
        payload = {
            "status": "ERROR",
            "scope": "SITL_STANDALONE_ACCEPTANCE",
            "started_at": started_at,
            "completed_at": harness.utc_now(),
            "reason": (
                "endpoint_in_use"
                if "endpoint_in_use" in str(exc)
                else "validation_error"
            ),
            "error": f"{type(exc).__name__}: {exc}",
        }

    _write_report(payload, args.report_dir)
    print(
        json.dumps(
            payload,
            indent=2 if args.pretty else None,
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
