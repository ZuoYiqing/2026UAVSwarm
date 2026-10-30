"""Bounded, immutable task authorizations for the first companion profile."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any


class PlatformError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def stamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def timestamp(value: Any) -> float:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError
        return dt.timestamp()
    except (TypeError, ValueError, AttributeError, OverflowError):
        raise PlatformError("invalid_timestamp") from None


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identifier(value: Any) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 100
            or any(not (c.isascii() and (c.isalnum() or c in "-_.")) for c in value)):
        raise PlatformError("invalid_identifier")
    return value


def number(value: Any, lower: float, upper: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not lower < value <= upper):
        raise PlatformError("parameter_out_of_bounds")
    return float(value)


def validate_task(body: Any, node_id: str, now: float) -> dict[str, Any]:
    keys = {"contract_version", "node_id", "task_id", "task_version", "request_id", "trace_id", "authorization", "steps"}
    if not isinstance(body, dict) or set(body) != keys:
        raise PlatformError("invalid_task_fields")
    if body["contract_version"] != "1.0" or type(body["task_version"]) is not int or body["task_version"] != 1:
        raise PlatformError("unsupported_task_version")
    if body["node_id"] != node_id:
        raise PlatformError("node_mismatch", 409)
    for key in ("task_id", "request_id", "trace_id"):
        identifier(body[key])
    auth = body["authorization"]
    if not isinstance(auth, dict) or set(auth) != {"operator_id", "expires_at", "offline_policy", "max_altitude_m", "max_hold_s"}:
        raise PlatformError("invalid_authorization")
    identifier(auth["operator_id"])
    if auth["offline_policy"] != "continue_authorized":
        raise PlatformError("unsupported_offline_policy")
    if not now < timestamp(auth["expires_at"]) <= now + 3600:
        raise PlatformError("authorization_expired_or_too_long", 409)
    max_alt = number(auth["max_altitude_m"], 0, 3)
    max_hold = number(auth["max_hold_s"], 0, 10)
    steps = body["steps"]
    if not isinstance(steps, list) or len(steps) != 3:
        raise PlatformError("unsupported_task_sequence")
    ids = set()
    for step, action in zip(steps, ("takeoff", "hold_position", "land")):
        if not isinstance(step, dict) or set(step) != {"step_id", "action", "params"} or step["action"] != action:
            raise PlatformError("unsupported_task_sequence")
        sid = identifier(step["step_id"])
        if sid in ids:
            raise PlatformError("duplicate_step_id")
        ids.add(sid)
        params = step["params"]
        allowed = {"takeoff": {"altitude_m"}, "hold_position": {"hold_s"}, "land": set()}[action]
        if not isinstance(params, dict) or set(params) != allowed:
            raise PlatformError("invalid_step_parameters")
        if action == "takeoff":
            number(params["altitude_m"], 0.5, max_alt)
        if action == "hold_position":
            number(params["hold_s"], 0, max_hold)
    return json.loads(canonical(body))
