from __future__ import annotations

from typing import Any, Dict, List

from jsonschema import Draft202012Validator


def mission_schema() -> Dict[str, Any]:
    """JSON Schema for mission_json (demo version)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": True,
        "required": ["mission_id", "objective", "area", "time_limit_s", "constraints"],
        "properties": {
            "mission_id": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1},
            "area": {
                "type": "object",
                "additionalProperties": True,
                "required": ["type", "x_min_km", "x_max_km", "y_min_km", "y_max_km"],
                "properties": {
                    "type": {"type": "string", "enum": ["rectangle"]},
                    "x_min_km": {"type": "number"},
                    "x_max_km": {"type": "number"},
                    "y_min_km": {"type": "number"},
                    "y_max_km": {"type": "number"},
                },
            },
            "time_limit_s": {"type": "integer", "minimum": 1},
            "constraints": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "max_total_bandwidth_bps": {"type": "integer", "minimum": 1},
                    "max_uav_count": {"type": "integer", "minimum": 1},
                    "lost_contact_timeout_s": {"type": "integer", "minimum": 1},
                },
            },
            "phases": {"type": "array", "items": {"type": "string"}},
        },
    }


def scene_schema() -> Dict[str, Any]:
    """JSON Schema for scene_json (demo version)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": True,
        "required": ["nodes", "links"],
        "properties": {
            "nodes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["id", "type", "role"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "type": {"type": "string", "minLength": 1},
                        "role": {"type": "string", "minLength": 1},
                        "position": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "x_km": {"type": "number"},
                                "y_km": {"type": "number"},
                            },
                        },
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["src", "dst", "type", "bandwidth_bps"],
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                        "type": {"type": "string"},
                        "bandwidth_bps": {"type": "integer", "minimum": 1},
                        "latency_ms": {"type": "integer", "minimum": 0},
                        "loss_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                },
            },
        },
    }


def decision_schema() -> Dict[str, Any]:
    """JSON Schema for decision_json (rule-level, not per-timestep actions)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": True,
        "required": ["global_policy", "cluster_head_policy", "member_policy"],
        "properties": {
            "global_policy": {
                "type": "object",
                "additionalProperties": True,
                "required": ["controller", "rules"],
                "properties": {
                    "controller": {"type": "string"},
                    "rules": {"type": "array", "items": {"type": "string"}},
                },
            },
            "cluster_head_policy": {
                "type": "object",
                "additionalProperties": True,
                "required": ["node_id", "rules"],
                "properties": {
                    "node_id": {"type": "string"},
                    "rules": {"type": "array", "items": {"type": "string"}},
                },
            },
            "member_policy": {
                "type": "object",
                "additionalProperties": True,
                "required": ["nodes", "rules"],
                "properties": {
                    "nodes": {"type": "array", "items": {"type": "string"}},
                    "rules": {"type": "array", "items": {"type": "string"}},
                },
            },
            "message_usage_hint": {
                "type": "object",
                "additionalProperties": True,
            },
        },
    }


def protocol_schema() -> Dict[str, Any]:
    """JSON Schema for protocol_json."""
    field_def = {
        "type": "object",
        "additionalProperties": True,
        "required": ["name", "type", "length"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "type": {"type": "string", "minLength": 1},
            "length": {"type": "integer", "minimum": 0},
            "range": {"type": "string"},
            "desc": {"type": "string"},
        },
    }

    msg_def = {
        "type": "object",
        "additionalProperties": True,
        "required": ["name", "msg_id", "direction", "fields"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "msg_id": {"type": "integer", "minimum": 0},
            "direction": {"type": "string", "minLength": 1},
            "trigger": {"type": "string"},
            "period_s": {"type": "number", "minimum": 0},
            "fields": {"type": "array", "items": field_def},
            "comment": {"type": "string"},
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": True,
        "required": ["version", "header_fields", "messages"],
        "properties": {
            "version": {"type": "string"},
            "header_fields": {"type": "array", "items": field_def},
            "messages": {"type": "array", "items": msg_def},
        },
    }


def validate_json(obj: Any, schema: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation errors (empty means valid)."""
    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(obj), key=lambda e: e.path)
    out: List[str] = []
    for e in errors:
        path = "/".join([str(p) for p in e.path])
        prefix = f"{path}: " if path else ""
        out.append(prefix + e.message)
    return out


def assert_valid(obj: Any, schema: Dict[str, Any], *, name: str = "json") -> None:
    errs = validate_json(obj, schema)
    if errs:
        joined = "\n".join([f"- {m}" for m in errs])
        raise ValueError(f"{name} schema validation failed:\n{joined}")
