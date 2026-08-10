"""Payload/device action mapping skeleton for non-destructive devices.

This module intentionally does not import or connect to real payload hardware.
It only defines deterministic action metadata for future adapter implementations.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_PAYLOAD_ACTIONS: dict[str, dict[str, Any]] = {
    "camera_capture": {
        "device_type": "camera",
        "placeholder_action": "capture_image",
        "required_params": [],
        "optional_params": ["camera_id", "mode", "resolution"],
        "safe_non_destructive": True,
    },
    "gimbal_set_angle": {
        "device_type": "gimbal",
        "placeholder_action": "set_angle",
        "required_params": ["pitch_deg", "yaw_deg"],
        "optional_params": ["roll_deg", "gimbal_id"],
        "safe_non_destructive": True,
    },
    "speaker_play_message": {
        "device_type": "speaker",
        "placeholder_action": "play_message",
        "required_params": ["message"],
        "optional_params": ["speaker_id", "volume"],
        "safe_non_destructive": True,
    },
    "light_set_state": {
        "device_type": "light",
        "placeholder_action": "set_state",
        "required_params": ["state"],
        "optional_params": ["light_id", "intensity"],
        "safe_non_destructive": True,
    },
    "sensor_read": {
        "device_type": "sensor",
        "placeholder_action": "read_value",
        "required_params": [],
        "optional_params": ["sensor_id", "sensor_type"],
        "safe_non_destructive": True,
    },
    "health_query": {
        "device_type": "health_monitor",
        "placeholder_action": "query_status",
        "required_params": [],
        "optional_params": ["device_id", "include_metrics"],
        "safe_non_destructive": True,
    },
}


def resolve_payload_mapping(command_name: str) -> dict[str, Any] | None:
    """Resolve non-destructive payload/device mapping metadata."""
    if not command_name:
        return None
    return SUPPORTED_PAYLOAD_ACTIONS.get(command_name)
