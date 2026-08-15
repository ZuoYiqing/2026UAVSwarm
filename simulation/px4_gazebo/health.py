#!/usr/bin/env python3
"""Machine-readable PX4/Gazebo health evidence for the three-UAV harness."""
from __future__ import annotations

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

try:
    from . import harness
except ImportError:  # Direct script execution adds this directory to sys.path.
    import harness  # type: ignore


DEFAULT_STABILITY_WINDOW_S = 10.0
HEARTBEAT_MAX_AGE_S = 2.5
TELEMETRY_MAX_AGE_S = 1.5


def _message_type(message: Any) -> str:
    getter = getattr(message, "get_type", None)
    return str(getter()) if callable(getter) else ""


def _source_ids(message: Any) -> tuple[int | None, int | None]:
    system_getter = getattr(message, "get_srcSystem", None)
    component_getter = getattr(message, "get_srcComponent", None)
    system_id = system_getter() if callable(system_getter) else None
    component_id = component_getter() if callable(component_getter) else None
    return (
        None if system_id is None else int(system_id),
        None if component_id is None else int(component_id),
    )


def probe_mavlink_stream(
    endpoint: str,
    timeout_s: float,
    stability_window_s: float,
) -> dict[str, Any]:
    """Observe one endpoint without sending flight-control commands."""
    try:
        from pymavlink import mavutil  # type: ignore
    except ImportError:
        return {
            "heartbeat_fresh": False,
            "telemetry_fresh": False,
            "reason": "pymavlink_missing",
            "evidence": {},
        }

    connection = None
    started = time.monotonic()
    first_heartbeat_at: float | None = None
    last_heartbeat_at: float | None = None
    last_telemetry_at: float | None = None
    last_seen: str | None = None
    heartbeat_count = 0
    telemetry_count = 0
    source_ids: set[tuple[int | None, int | None]] = set()
    error: str | None = None
    try:
        connection = mavutil.mavlink_connection(
            endpoint,
            timeout=max(float(timeout_s), 0.1),
        )
        connect_deadline = started + max(float(timeout_s), 0.1)
        final_deadline: float | None = None
        while True:
            now = time.monotonic()
            deadline = final_deadline if final_deadline is not None else connect_deadline
            if now >= deadline:
                break
            message = connection.recv_match(
                type=None,
                blocking=True,
                timeout=max(min(deadline - now, 0.5), 0.01),
            )
            if message is None:
                continue
            now = time.monotonic()
            message_type = _message_type(message)
            system_id, component_id = _source_ids(message)
            if message_type == "HEARTBEAT":
                source_ids.add((system_id, component_id))
                heartbeat_count += 1
                first_heartbeat_at = (
                    now if first_heartbeat_at is None else first_heartbeat_at
                )
                last_heartbeat_at = now
                last_seen = harness.utc_now()
                if final_deadline is None:
                    final_deadline = (
                        first_heartbeat_at
                        + max(float(stability_window_s), 0.0)
                        + HEARTBEAT_MAX_AGE_S
                    )
            elif message_type == "LOCAL_POSITION_NED":
                source_ids.add((system_id, component_id))
                telemetry_count += 1
                last_telemetry_at = now
                last_seen = harness.utc_now()

            if first_heartbeat_at is None or last_heartbeat_at is None:
                continue
            heartbeat_span_s = last_heartbeat_at - first_heartbeat_at
            heartbeat_age_s = now - last_heartbeat_at
            telemetry_age_s = (
                None if last_telemetry_at is None else now - last_telemetry_at
            )
            if (
                heartbeat_span_s >= max(float(stability_window_s), 0.0)
                and heartbeat_age_s <= HEARTBEAT_MAX_AGE_S
                and telemetry_count >= 2
                and telemetry_age_s is not None
                and telemetry_age_s <= TELEMETRY_MAX_AGE_S
            ):
                break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()

    finished = time.monotonic()
    heartbeat_span_s = (
        0.0
        if first_heartbeat_at is None or last_heartbeat_at is None
        else max(0.0, last_heartbeat_at - first_heartbeat_at)
    )
    heartbeat_age_s = (
        None
        if last_heartbeat_at is None
        else max(0.0, finished - last_heartbeat_at)
    )
    telemetry_age_s = (
        None
        if last_telemetry_at is None
        else max(0.0, finished - last_telemetry_at)
    )
    heartbeat_fresh = bool(
        error is None
        and heartbeat_count >= 2
        and heartbeat_span_s >= max(float(stability_window_s), 0.0)
        and heartbeat_age_s is not None
        and heartbeat_age_s <= HEARTBEAT_MAX_AGE_S
    )
    telemetry_fresh = bool(
        error is None
        and telemetry_count >= 2
        and telemetry_age_s is not None
        and telemetry_age_s <= TELEMETRY_MAX_AGE_S
    )
    reason = "ok"
    if error:
        reason = "endpoint_in_use" if "address already in use" in error.lower() else "mavlink_probe_failed"
    elif not heartbeat_fresh:
        reason = "heartbeat_stale"
    elif not telemetry_fresh:
        reason = "telemetry_stale"
    return {
        "heartbeat_fresh": heartbeat_fresh,
        "telemetry_fresh": telemetry_fresh,
        "observed_system_ids": sorted(
            system_id for system_id, _ in source_ids if system_id is not None
        ),
        "observed_component_ids": sorted(
            component_id for _, component_id in source_ids if component_id is not None
        ),
        "last_seen": last_seen,
        "reason": reason,
        "evidence": {
            "heartbeat_count": heartbeat_count,
            "heartbeat_span_s": round(heartbeat_span_s, 3),
            "last_heartbeat_age_s": (
                None if heartbeat_age_s is None else round(heartbeat_age_s, 3)
            ),
            "local_position_ned_count": telemetry_count,
            "last_telemetry_age_s": (
                None if telemetry_age_s is None else round(telemetry_age_s, 3)
            ),
            "probe_duration_s": round(finished - started, 3),
            "error": error,
        },
    }


_SIM_BLOCK_RE = re.compile(r"\bsim\s*\{(?P<body>.*?)\}", re.DOTALL)
_SEC_RE = re.compile(r"\bsec:\s*(-?\d+)")
_NSEC_RE = re.compile(r"\bnsec:\s*(-?\d+)")


def parse_gazebo_clock_samples(output: str) -> list[float]:
    """Extract Gazebo Clock.sim values from protobuf text output."""
    samples: list[float] = []
    for match in _SIM_BLOCK_RE.finditer(output):
        body = match.group("body")
        sec = _SEC_RE.search(body)
        nsec = _NSEC_RE.search(body)
        if sec is None:
            continue
        samples.append(
            int(sec.group(1))
            + (int(nsec.group(1)) if nsec is not None else 0) / 1_000_000_000
        )
    return samples


def probe_gazebo_clock(world_name: str, timeout_s: float) -> dict[str, Any]:
    topic = f"/world/{world_name}/clock"
    try:
        result = subprocess.run(
            ["gz", "topic", "-e", "-t", topic, "-n", "2"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(float(timeout_s), 0.1),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "clock_advancing": False,
            "reason": "gazebo_clock_probe_failed",
            "evidence": {"topic": topic, "error": f"{type(exc).__name__}: {exc}"},
        }
    samples = parse_gazebo_clock_samples(result.stdout)
    advancing = len(samples) >= 2 and samples[-1] > samples[0]
    return {
        "clock_advancing": advancing,
        "reason": "ok" if advancing else "gazebo_clock_stalled",
        "evidence": {
            "topic": topic,
            "returncode": result.returncode,
            "samples_s": samples,
            "stderr": result.stderr.strip() or None,
        },
    }


def _failed_probe(reason: str, exc: Exception) -> dict[str, Any]:
    return {
        "heartbeat_fresh": False,
        "telemetry_fresh": False,
        "observed_system_ids": [],
        "observed_component_ids": [],
        "last_seen": None,
        "reason": reason,
        "evidence": {"error": f"{type(exc).__name__}: {exc}"},
    }


def collect_health(
    manifest: dict[str, Any],
    *,
    timeout_s: float,
    stability_window_s: float = DEFAULT_STABILITY_WINDOW_S,
    mavlink_probe: Callable[[str, float, float], dict[str, Any]] = probe_mavlink_stream,
    clock_probe: Callable[[str, float], dict[str, Any]] = probe_gazebo_clock,
    model_probe: Callable[[], set[str]] = harness.gazebo_models,
    world_probe: Callable[[], list[str]] = harness._running_gazebo_worlds,
    identity_reader: Callable[[int], harness.ProcessIdentityReadResult] | None = None,
) -> dict[str, Any]:
    """Collect fail-closed simulator, process and MAVLink readiness evidence."""
    state = harness.read_state() or {}
    processes = list(state.get("processes", []))
    decisions = harness._validate_processes(
        processes,
        run_id=str(state.get("run_id", "")),
        identity_reader=identity_reader,
    )
    identity_by_node = {
        str(row.node_id): row for row in decisions if row.node_id is not None
    }

    models = model_probe()
    worlds = world_probe()
    expected_world = str(manifest["world_name"])
    try:
        clock = clock_probe(expected_world, timeout_s)
    except Exception as exc:
        clock = {
            "clock_advancing": False,
            "reason": "gazebo_clock_probe_failed",
            "evidence": {"error": f"{type(exc).__name__}: {exc}"},
        }

    vehicles = list(manifest["vehicles"])
    probe_rows: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(vehicles)) as executor:
        futures = {
            str(vehicle["node_id"]): executor.submit(
                mavlink_probe,
                str(vehicle["command_endpoint"]),
                timeout_s,
                stability_window_s,
            )
            for vehicle in vehicles
        }
        for node_id, future in futures.items():
            try:
                probe_rows[node_id] = future.result()
            except Exception as exc:
                probe_rows[node_id] = _failed_probe("mavlink_probe_failed", exc)

    rows: list[dict[str, Any]] = []
    observed_system_ids: list[int] = []
    for vehicle in vehicles:
        node_id = str(vehicle["node_id"])
        expected_system_id = int(vehicle["system_id"])
        expected_component_id = int(vehicle.get("component_id", 1))
        probe = probe_rows[node_id]
        system_ids = [int(value) for value in probe.get("observed_system_ids", [])]
        component_ids = [
            int(value) for value in probe.get("observed_component_ids", [])
        ]
        observed_system_ids.extend(system_ids)
        identity = identity_by_node.get(node_id)
        process_identity_valid = bool(
            identity is not None and identity.code == harness.IDENTITY_MATCH
        )
        model_name = str(vehicle["gazebo_model_name"])
        reasons: list[str] = []
        if not process_identity_valid:
            reasons.append(identity.code if identity is not None else harness.STALE_STATE)
        if model_name not in models:
            reasons.append("gazebo_model_missing")
        if not probe.get("heartbeat_fresh"):
            reasons.append(str(probe.get("reason") or "heartbeat_stale"))
        if system_ids != [expected_system_id]:
            reasons.append("system_id_mismatch")
        if component_ids != [expected_component_id]:
            reasons.append("component_id_mismatch")
        if not probe.get("telemetry_fresh"):
            reasons.append("telemetry_stale")
        ready = not reasons
        rows.append(
            {
                "node_id": node_id,
                "system_id": expected_system_id,
                "component_id": expected_component_id,
                "endpoint": vehicle["command_endpoint"],
                "heartbeat_fresh": bool(probe.get("heartbeat_fresh")),
                "telemetry_fresh": bool(probe.get("telemetry_fresh")),
                "process_identity_valid": process_identity_valid,
                "last_seen": probe.get("last_seen"),
                "reason": "ok" if ready else ",".join(dict.fromkeys(reasons)),
                "evidence": {
                    "expected_system_id": expected_system_id,
                    "observed_system_ids": system_ids,
                    "expected_component_id": expected_component_id,
                    "observed_component_ids": component_ids,
                    "gazebo_model_name": model_name,
                    "model_present": model_name in models,
                    "process": identity.to_dict() if identity is not None else None,
                    "mavlink": probe.get("evidence", {}),
                },
                "readiness": ready,
            }
        )

    expected_models = {str(vehicle["gazebo_model_name"]) for vehicle in vehicles}
    world_correct = expected_world in worlds
    unique_system_ids = (
        len(observed_system_ids) == len(vehicles)
        and len(set(observed_system_ids)) == len(vehicles)
    )
    clock_advancing = bool(clock.get("clock_advancing"))
    ready = bool(
        world_correct
        and expected_models.issubset(models)
        and clock_advancing
        and unique_system_ids
        and all(row["readiness"] for row in rows)
    )
    top_reasons: list[str] = []
    if not world_correct:
        top_reasons.append("world_mismatch")
    if not expected_models.issubset(models):
        top_reasons.append("gazebo_models_missing")
    if not clock_advancing:
        top_reasons.append(str(clock.get("reason") or "gazebo_clock_stalled"))
    if not unique_system_ids:
        top_reasons.append("system_ids_not_unique")
    if any(not row["readiness"] for row in rows):
        top_reasons.append("vehicle_not_ready")
    return {
        "contract_version": "1.0",
        "simulator": "gazebo",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "server_running": world_correct,
        "clock_advancing": clock_advancing,
        "world": expected_world,
        "models": sorted(models),
        "scene_id": manifest["scene_id"],
        "unique_system_ids": unique_system_ids,
        "checked_at": harness.utc_now(),
        "reason": "ok" if ready else ",".join(dict.fromkeys(top_reasons)),
        "evidence": {
            "observed_worlds": worlds,
            "world_correct": world_correct,
            "expected_models": sorted(expected_models),
            "clock": clock.get("evidence", {}),
            "stability_window_s": stability_window_s,
            "run_id": state.get("run_id"),
        },
        "vehicles": rows,
    }
