"""Strict, local-only v1.0 candidate contract for one authorized UAV-02 step."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any


VERSION = "1.0"
PRODUCER_VERSION = "platform_candidate_lab/0.1.0"
MAX_JSON_BYTES = 65_536
MAX_AGE_SECONDS = 3.0
MAX_FUTURE_SECONDS = 0.5
DECISIONS = {"execute_authorized_step", "abort_to_land"}
ACTIONS = {"takeoff", "hold_position", "land"}


class ContractError(ValueError):
    """Invalid or ambiguous data at the algorithm boundary."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError("NONFINITE_JSON_NUMBER")


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractError("INVALID_JSON_VALUE") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_json(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        if len(raw) > MAX_JSON_BYTES:
            raise ContractError("JSON_TOO_LARGE")
        try:
            raw = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ContractError("INVALID_UTF8") from exc
    elif not isinstance(raw, str):
        raise ContractError("JSON_TEXT_REQUIRED")
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ContractError("JSON_TOO_LARGE")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        canonical_json(value)
        return value
    except (ValueError, RecursionError, TypeError) as exc:
        raise ContractError("INVALID_JSON") from exc


def _object(value: Any, required: set[str], name: str,
            optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise ContractError(f"{name}_FIELDS_INVALID")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.strip():
        raise ContractError(f"{name}_INVALID")
    return value


def _number(value: Any, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ContractError(f"{name}_INVALID")
    return float(value)


def utc_time(value: Any, name: str) -> datetime:
    if (not isinstance(value, str) or len(value) > 40
            or not (value.endswith("Z") or value.endswith("+00:00"))):
        raise ContractError(f"{name}_NOT_UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ContractError(f"{name}_INVALID") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError(f"{name}_NOT_UTC")
    return parsed


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _params(action: str, params: Any, authorization: dict[str, Any]) -> None:
    if action == "land":
        _object(params, set(), "LAND_PARAMS")
    elif action == "takeoff":
        p = _object(params, {"altitude_m"}, "TAKEOFF_PARAMS",
                    {"altitude_tolerance_m", "stable_duration_ms"})
        altitude = _number(p["altitude_m"], "TAKEOFF_ALTITUDE", 0.1, 1000)
        if altitude > authorization["max_altitude_m"]:
            raise ContractError("TAKEOFF_EXCEEDS_AUTHORIZATION")
        if "altitude_tolerance_m" in p:
            _number(p["altitude_tolerance_m"], "TAKEOFF_TOLERANCE", 0.01, 100)
        if "stable_duration_ms" in p:
            _number(p["stable_duration_ms"], "STABLE_DURATION", 1, 60000)
    elif action == "hold_position":
        p = _object(params, {"hold_s"}, "HOLD_PARAMS", {"tolerance_m", "timeout_s"})
        duration = _number(p["hold_s"], "HOLD_DURATION", 0.1, 3600)
        if duration > authorization["max_hold_s"]:
            raise ContractError("HOLD_EXCEEDS_AUTHORIZATION")
        if "tolerance_m" in p:
            _number(p["tolerance_m"], "HOLD_TOLERANCE", 0.01, 100)
        if "timeout_s" in p:
            _number(p["timeout_s"], "HOLD_TIMEOUT", 0.1, 3600)


def validate_request(value: Any) -> dict[str, Any]:
    root = _object(value, {
        "contract_version", "node_id", "task_id", "task_version", "execution_id",
        "step_id", "request_id", "trace_id", "snapshot_id", "decision_timeout_ms",
        "ground_link", "authorization", "next_step", "observation", "allowed_options",
    }, "REQUEST")
    if root["contract_version"] != VERSION or root["node_id"] != "UAV-02":
        raise ContractError("VERSION_OR_NODE_UNSUPPORTED")
    for name in ("task_id", "execution_id", "step_id", "request_id", "trace_id", "snapshot_id"):
        _identifier(root[name], name.upper())
    if root["snapshot_id"] != root["request_id"]:
        raise ContractError("SNAPSHOT_REQUEST_MISMATCH")
    if type(root["task_version"]) is not int or not 1 <= root["task_version"] <= 1_000_000:
        raise ContractError("TASK_VERSION_INVALID")
    if type(root["decision_timeout_ms"]) is not int or not 1 <= root["decision_timeout_ms"] <= 10_000:
        raise ContractError("DECISION_TIMEOUT_INVALID")
    link = _object(root["ground_link"], {"state"}, "GROUND_LINK",
                   {"last_received_at", "age_ms"})
    if link["state"] not in {"healthy", "lost"}:
        raise ContractError("GROUND_LINK_STATE_INVALID")
    if "last_received_at" in link and link["last_received_at"] is not None:
        utc_time(link["last_received_at"], "GROUND_LINK_TIMESTAMP")
    if "age_ms" in link and link["age_ms"] is not None:
        _number(link["age_ms"], "GROUND_LINK_AGE", 0, 86_400_000)
    auth = _object(root["authorization"],
                   {"expires_at", "max_altitude_m", "max_hold_s", "offline_policy"},
                   "AUTHORIZATION", {"operator_id"})
    if "operator_id" in auth:
        _identifier(auth["operator_id"], "OPERATOR_ID")
    utc_time(auth["expires_at"], "AUTHORIZATION_EXPIRY")
    _number(auth["max_altitude_m"], "MAX_ALTITUDE", 0.1, 1000)
    _number(auth["max_hold_s"], "MAX_HOLD", 0.1, 3600)
    if auth["offline_policy"] != "continue_authorized":
        raise ContractError("OFFLINE_POLICY_UNSUPPORTED")
    step = _object(root["next_step"], {"step_id", "action", "params"}, "NEXT_STEP")
    if step["step_id"] != root["step_id"] or step["action"] not in ACTIONS:
        raise ContractError("NEXT_STEP_INVALID")
    _params(step["action"], step["params"], auth)
    obs = _object(root["observation"],
                  {"source", "sample_timestamp", "stale", "local_position"},
                  "OBSERVATION", {"armed", "landed_state", "landed_fresh",
                                  "battery", "velocity_mps"})
    if obs["source"] not in {"px4_telemetry", "fake"} or type(obs["stale"]) is not bool:
        raise ContractError("OBSERVATION_SOURCE_OR_STALE_INVALID")
    utc_time(obs["sample_timestamp"], "OBSERVATION_TIMESTAMP")
    position = _object(obs["local_position"], set(), "LOCAL_POSITION",
                       {"x_m", "y_m", "z_down_m", "altitude_m",
                        "vx_m_s", "vy_m_s", "vz_m_s"})
    for name, number in position.items():
        if number is not None:
            _number(number, name.upper(), -100_000, 100_000)
    if "armed" in obs and obs["armed"] is not None and type(obs["armed"]) is not bool:
        raise ContractError("ARMED_INVALID")
    if ("landed_fresh" in obs and obs["landed_fresh"] is not None
            and type(obs["landed_fresh"]) is not bool):
        raise ContractError("LANDED_FRESH_INVALID")
    if "landed_state" in obs and obs["landed_state"] is not None:
        state = obs["landed_state"]
        if type(state) is int:
            _number(state, "LANDED_STATE", 0, 10)
        else:
            _identifier(state, "LANDED_STATE")
    if "battery" in obs and obs["battery"] is not None:
        battery = obs["battery"]
        if isinstance(battery, dict):
            _object(battery, set(), "BATTERY",
                    {"voltage_v", "current_a", "battery_remaining",
                     "onboard_control_sensors_present",
                     "onboard_control_sensors_enabled",
                     "onboard_control_sensors_health"})
            for name, number in battery.items():
                if number is not None:
                    _number(number, name.upper(), -100_000, 4_294_967_295)
        else:
            _number(battery, "BATTERY", 0, 100)
    if "velocity_mps" in obs and obs["velocity_mps"] is not None:
        _number(obs["velocity_mps"], "VELOCITY", 0, 1000)
    options = root["allowed_options"]
    if not isinstance(options, list) or len(options) != 2:
        raise ContractError("ALLOWED_OPTIONS_INVALID")
    seen: set[str] = set()
    for option in options:
        item = _object(option, {"option_id", "action_type", "params"}, "OPTION")
        if item["option_id"] not in DECISIONS or item["option_id"] in seen:
            raise ContractError("OPTION_ID_INVALID")
        seen.add(item["option_id"])
        if item["option_id"] == "execute_authorized_step":
            if item["action_type"] != step["action"] or item["params"] != step["params"]:
                raise ContractError("OPTION_STEP_MISMATCH")
        elif item["action_type"] != "land" or item["params"] != {}:
            raise ContractError("ABORT_OPTION_INVALID")
    if seen != DECISIONS:
        raise ContractError("ALLOWED_OPTIONS_INCOMPLETE")
    canonical_json(root)
    if len(canonical_json(root).encode("utf-8")) > MAX_JSON_BYTES:
        raise ContractError("REQUEST_TOO_LARGE")
    return root


def model_reply(raw: str) -> str:
    value = _object(parse_json(raw), {"option_id"}, "MODEL_REPLY")
    if value["option_id"] not in DECISIONS:
        raise ContractError("MODEL_OPTION_UNAUTHORIZED")
    return value["option_id"]
