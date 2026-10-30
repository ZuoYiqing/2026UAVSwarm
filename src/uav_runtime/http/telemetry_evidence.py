"""Simulation health projection from existing owners; no MAVLink I/O or scene truth."""
from __future__ import annotations

import copy
import math
import time

from uav_runtime.platform.contract import stamp, timestamp

PATH = "/api/simulation/runtime-telemetry"
VALID_MS = 5000
LIMITS = (("heartbeat", "heartbeat_fresh", 2500), ("position", "telemetry_fresh", 1500))


def local_evidence(registry, run_id, *, clock=None):
    clock = clock or time.time
    rows = []
    for handle in registry.list_vehicles():
        read = getattr(handle.session, "telemetry_health_evidence", None)
        row = read() if callable(read) else {}
        row.update({"node_id": handle.config.node_id, "endpoint": handle.config.endpoint})
        identity = (row.get("system_id"), row.get("component_id")) == (handle.config.system_id, handle.config.component_id)
        for _, flag, _ in LIMITS:
            row[flag] = row.get(flag) is True and identity
        if not identity:
            row["reason"] = "sample_identity_unavailable"
        rows.append(row)
    return {"contract_version": "1.0", "scene_id": registry.scene_id, "run_id": run_id,
            "source_timestamp": stamp(clock()), "valid_for_ms": VALID_MS, "vehicles": rows,
            "source": "runtime_session_rx", "execution_authorized": False, "flight_command_sent": False}


def remote_evidence(view, *, scene_id, run_id, clock=None):
    """Validate/age optional companion evidence; a fresh view never refreshes samples."""
    clock = clock or time.time
    unavailable = {"node_id": "UAV-02", "system_id": None, "component_id": None,
                   "endpoint": "udpin:127.0.0.1:14541", "heartbeat_timestamp": None,
                   "position_timestamp": None, "last_seen": None, "heartbeat_fresh": False,
                   "telemetry_fresh": False, "reason": "platform_telemetry_unavailable"}
    evidence = view.get("runtime_telemetry")
    try:
        if (view.get("fresh") is not True or view.get("run_id") != run_id
                or not isinstance(evidence, dict) or evidence.get("contract_version") != "1.0"
                or evidence.get("scene_id") != scene_id or evidence.get("run_id") != run_id
                or evidence.get("execution_authorized") is not False or evidence.get("flight_command_sent") is not False
                or type(evidence.get("valid_for_ms")) is not int or not 0 < evidence["valid_for_ms"] <= VALID_MS):
            return unavailable
        age = (clock() - timestamp(evidence.get("source_timestamp"))) * 1000
        if not -100 <= age <= evidence["valid_for_ms"]:
            return unavailable
        rows = evidence["vehicles"]
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return unavailable
        row = copy.deepcopy(rows[0])
        if (row.get("node_id") != "UAV-02" or row.get("endpoint") != unavailable["endpoint"]
                or row.get("source") != "px4_session_rx"
                or (row.get("system_id"), row.get("component_id")) not in {(2, 1), (None, None)}):
            return unavailable
        for prefix, flag, limit in LIMITS:
            if type(row.get(flag)) is not bool:
                return unavailable
            sample = row.get(prefix + "_timestamp")
            sample_age = None if sample is None else (clock() - timestamp(sample)) * 1000
            row[flag] = (row[flag] and (row.get("system_id"), row.get("component_id")) == (2, 1)
                         and sample_age is not None and math.isfinite(sample_age) and -100 <= sample_age <= limit)
            # Preserve monotonic producer age too; wall-clock rollback must not rejuvenate a sample.
            producer_age = row.get(prefix + "_age_ms")
            if type(producer_age) not in (int, float) or not math.isfinite(producer_age) or producer_age < 0:
                row[flag] = False
            else:
                producer_age += max(0, view.get("age_ms") or 0)
                row[flag] = row[flag] and producer_age <= limit
                sample_age = max(sample_age or 0, producer_age)
            row[prefix + "_age_ms"] = sample_age
        row["reason"] = "ok" if row["heartbeat_fresh"] and row["telemetry_fresh"] else "platform_telemetry_stale"
        return row
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable
