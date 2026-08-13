#!/usr/bin/env python3
"""Run the SITL-only three-UAV command isolation validation."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
HARNESS_DIR = SCRIPT_DIR.parent
REPO_ROOT = HARNESS_DIR.parent.parent
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness import (
    DEFAULT_MANIFEST_PATH,
    HarnessError,
    RUNTIME_ROOT,
    collect_health,
    load_manifest,
    utc_now,
)
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig


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
            observe_timeout_ms=25000,
        )
    )


def _accepted(ack: dict[str, Any]) -> bool:
    return not bool(ack.get("timeout")) and int(ack.get("result", -1)) == 0


def _observe_passive_state(
    vehicle: dict[str, Any],
    *,
    timeout_s: float,
) -> dict[str, Any]:
    session = _session(vehicle)
    armed: bool | None = None
    max_altitude_m = 0.0
    samples = 0
    condition = threading.Condition()

    def observe(message: Any) -> None:
        nonlocal armed, max_altitude_m, samples
        message_type = message.get_type()
        with condition:
            if message_type == "HEARTBEAT":
                armed = bool(
                    int(getattr(message, "base_mode", 0)) & armed_flag
                )
            elif message_type == "LOCAL_POSITION_NED":
                samples += 1
                max_altitude_m = max(
                    max_altitude_m,
                    max(0.0, -float(getattr(message, "z", 0.0))),
                )
            condition.notify_all()

    token: int | None = None
    try:
        session.connect(timeout_s=min(timeout_s, 5.0))
        if session.target_system != int(vehicle["system_id"]):
            raise HarnessError(
                f"{vehicle['node_id']} heartbeat sysid {session.target_system} "
                f"does not match expected {vehicle['system_id']}"
            )
        session.start_gcs_heartbeat()
        armed_flag = session._mavlink_const("MAV_MODE_FLAG_SAFETY_ARMED", 128)
        token = session.subscribe(observe)
        stream_ack = session.request_local_position_stream(
            rate_hz=10.0,
            timeout_s=2.0,
        )
        deadline = time.monotonic() + timeout_s
        with condition:
            while time.monotonic() < deadline:
                condition.wait(timeout=min(0.5, deadline - time.monotonic()))
        return {
            "node_id": vehicle["node_id"],
            "system_id": session.target_system,
            "stream_ack": stream_ack,
            "armed": armed,
            "sample_count": samples,
            "max_altitude_m": round(max_altitude_m, 3),
            "isolated": (
                _accepted(stream_ack)
                and armed is False
                and samples > 0
                and max_altitude_m <= 0.5
            ),
        }
    finally:
        if token is not None:
            session.unsubscribe(token)
        session.close()


def _wait_for_landing(
    session: MavlinkBackendSession,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    final_altitude_m: float | None = None
    low_samples = 0
    samples = 0
    condition = threading.Condition()

    def observe(message: Any) -> None:
        nonlocal final_altitude_m, low_samples, samples
        if message.get_type() != "LOCAL_POSITION_NED":
            return
        with condition:
            samples += 1
            final_altitude_m = max(0.0, -float(getattr(message, "z", 0.0)))
            low_samples = low_samples + 1 if final_altitude_m <= 0.3 else 0
            condition.notify_all()

    token = session.subscribe(observe)
    try:
        with condition:
            while time.monotonic() < deadline and low_samples < 3:
                condition.wait(timeout=min(0.5, deadline - time.monotonic()))
    finally:
        session.unsubscribe(token)
    return {
        "observed": samples > 0,
        "sample_count": samples,
        "final_altitude_m": (
            round(final_altitude_m, 3) if final_altitude_m is not None else None
        ),
        "landed": low_samples >= 3,
    }


def _validate_active_vehicle(
    active: dict[str, Any],
    passive: list[dict[str, Any]],
    *,
    altitude_m: float,
    command_timeout_s: float,
    observe_timeout_s: float,
) -> dict[str, Any]:
    session = _session(active)
    result: dict[str, Any] = {
        "node_id": active["node_id"],
        "expected_system_id": active["system_id"],
        "started_at": utc_now(),
        "takeoff_observed": False,
        "land_command_accepted": False,
        "landed_observed": False,
    }
    try:
        session.connect(timeout_s=5.0)
        result["observed_system_id"] = session.target_system
        if session.target_system != int(active["system_id"]):
            raise HarnessError(
                f"{active['node_id']} connected to sysid {session.target_system}, "
                f"expected {active['system_id']}"
            )
        session.start_gcs_heartbeat()
        result["stream_ack"] = session.request_local_position_stream(
            rate_hz=10.0,
            timeout_s=command_timeout_s,
        )
        result["arm_ack"] = session.arm(timeout_s=command_timeout_s)
        if not _accepted(result["arm_ack"]):
            raise HarnessError(f"{active['node_id']} ARM was not accepted")
        result["takeoff_ack"] = session.takeoff(
            altitude_m=altitude_m,
            timeout_s=command_timeout_s,
        )
        if not _accepted(result["takeoff_ack"]):
            raise HarnessError(f"{active['node_id']} TAKEOFF was not accepted")
        result["takeoff_observation"] = session.observe_local_position_altitude(
            timeout_s=observe_timeout_s,
            threshold_altitude_m=altitude_m * 0.70,
        )
        if not result["takeoff_observation"]["threshold_reached"]:
            raise HarnessError(
                f"{active['node_id']} did not reach the altitude threshold"
            )
        result["takeoff_observed"] = True

        with ThreadPoolExecutor(max_workers=len(passive)) as executor:
            futures = [
                executor.submit(
                    _observe_passive_state,
                    vehicle,
                    timeout_s=3.0,
                )
                for vehicle in passive
            ]
            result["passive_isolation"] = [future.result() for future in futures]
        if not all(row["isolated"] for row in result["passive_isolation"]):
            raise HarnessError(
                f"{active['node_id']} isolation check failed for passive vehicles"
            )

        result["land_ack"] = session.land(timeout_s=command_timeout_s)
        if not _accepted(result["land_ack"]):
            raise HarnessError(f"{active['node_id']} LAND was not accepted")
        result["land_command_accepted"] = True
        result["landing_observation"] = _wait_for_landing(
            session,
            timeout_s=observe_timeout_s,
        )
        if not result["landing_observation"]["landed"]:
            raise HarnessError(f"{active['node_id']} landing was not observed")
        result["landed_observed"] = True
        result["status"] = "PASS"
        return result
    except Exception as exc:
        result["status"] = "FAIL"
        result["error"] = f"{type(exc).__name__}: {exc}"
        takeoff_accepted = _accepted(result.get("takeoff_ack", {}))
        if session.connected and (result["takeoff_observed"] or takeoff_accepted) and not result["landed_observed"]:
            try:
                result["recovery_land_ack"] = session.land(
                    timeout_s=command_timeout_s
                )
                result["recovery_landing_observation"] = _wait_for_landing(
                    session,
                    timeout_s=observe_timeout_s,
                )
                result["landed_observed"] = bool(
                    result["recovery_landing_observation"]["landed"]
                )
            except Exception as recovery_exc:
                result["recovery_error"] = (
                    f"{type(recovery_exc).__name__}: {recovery_exc}"
                )
        return result
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--altitude-m", type=float, default=2.0)
    parser.add_argument("--command-timeout", type=float, default=5.0)
    parser.add_argument("--observe-timeout", type=float, default=25.0)
    args = parser.parse_args()
    if not 1.0 <= args.altitude_m <= 5.0:
        parser.error("--altitude-m must be between 1.0 and 5.0 for this smoke")

    try:
        manifest = load_manifest(args.config)
        health = collect_health(manifest, timeout_s=5.0)
    except HarnessError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2))
        return 2
    if not health["ready"]:
        print(
            json.dumps(
                {
                    "status": "NOT_READY",
                    "reason": "three-UAV health check failed",
                    "health": health,
                },
                indent=2,
            )
        )
        return 2

    rows = []
    vehicles = list(manifest["vehicles"])
    for active in vehicles:
        passive = [
            vehicle
            for vehicle in vehicles
            if vehicle["node_id"] != active["node_id"]
        ]
        row = _validate_active_vehicle(
            active,
            passive,
            altitude_m=args.altitude_m,
            command_timeout_s=args.command_timeout,
            observe_timeout_s=args.observe_timeout,
        )
        rows.append(row)
        if row["status"] != "PASS":
            break

    payload = {
        "status": "PASS" if len(rows) == len(vehicles) and all(
            row["status"] == "PASS" for row in rows
        ) else "FAIL",
        "scope": "SITL_ONLY",
        "scene_id": manifest["scene_id"],
        "started_with_health": health,
        "vehicles": rows,
        "completed_at": utc_now(),
    }
    output_dir = RUNTIME_ROOT / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    output_path = output_dir / f"three_uav_validation_{timestamp}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["result_path"] = str(output_path)
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
