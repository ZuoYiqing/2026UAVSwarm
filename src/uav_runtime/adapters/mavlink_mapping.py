"""Future MAVLink action mapping skeleton (design-phase placeholder).

This module intentionally does not import any real MAVLink/PX4 library.
It only defines deterministic command->future-action mapping metadata.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_MAVLINK_ACTIONS: dict[str, dict[str, Any]] = {
    "takeoff": {
        "mavlink_action": "NAV_TAKEOFF",
        "param_hints": ["altitude_m"],
        "placeholder": True,
    },
    "goto": {
        "mavlink_action": "NAV_WAYPOINT",
        "param_hints": ["x", "y", "z", "lat", "lon", "alt_m"],
        "placeholder": True,
    },
    "hover": {
        "mavlink_action": "NAV_LOITER_TIME",
        "param_hints": ["duration_s"],
        "placeholder": True,
    },
    "land": {
        "mavlink_action": "NAV_LAND",
        "param_hints": [],
        "placeholder": True,
    },
    "return_home": {
        "mavlink_action": "NAV_RTL",
        "param_hints": [],
        "placeholder": True,
    },
}


def resolve_mapping(command_name: str) -> dict[str, Any] | None:
    """Resolve future MAVLink mapping metadata for a canonical command name."""
    if not command_name:
        return None
    return SUPPORTED_MAVLINK_ACTIONS.get(command_name)
