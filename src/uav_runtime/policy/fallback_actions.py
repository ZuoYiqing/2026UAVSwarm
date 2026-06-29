"""Policy Profile v0.2 fallback action taxonomy.

The taxonomy is intentionally data-only and does not import adapter/backend code.
It defines non-destructive fallback/control actions that may remain available when
link state is lost or degraded.
"""
from __future__ import annotations

FLIGHT_CONTROL_FALLBACK_ACTIONS: frozenset[str] = frozenset(
    {
        "hold_position",
        "return_home",
        "land_safe",
        "reduce_speed",
        "maintain_heading",
    }
)

SYSTEM_HEALTH_FALLBACK_ACTIONS: frozenset[str] = frozenset(
    {
        "health_query",
        "sensor_read",
        "report_status",
    }
)

PAYLOAD_DEVICE_FALLBACK_ACTIONS: frozenset[str] = frozenset(
    {
        "light_set_state",
        "camera_capture",
    }
)

LOST_LINK_FALLBACK_ACTIONS: frozenset[str] = frozenset(
    FLIGHT_CONTROL_FALLBACK_ACTIONS
    | SYSTEM_HEALTH_FALLBACK_ACTIONS
    | PAYLOAD_DEVICE_FALLBACK_ACTIONS
)

DEGRADED_REQUIRE_CONFIRM_ACTIONS: frozenset[str] = frozenset(
    {
        "speaker_play_message",
    }
)

UNSAFE_PAYLOAD_ACTIONS: frozenset[str] = frozenset(
    {
        "payload_release",
        "release_payload",
        "drop",
        "drop_payload",
        "deploy",
        "deploy_payload",
        "strike",
        "attack",
    }
)

NON_FALLBACK_ACTIONS: frozenset[str] = frozenset(
    {
        "goto",
        "peer_control",
        "subcluster_control",
    }
)


def is_lost_link_fallback_action(action_type: str) -> bool:
    """Return whether an action is explicitly allowed as a lost-link fallback."""
    return action_type in LOST_LINK_FALLBACK_ACTIONS


def is_unsafe_payload_action(action_type: str) -> bool:
    """Return whether an action is explicitly unsafe and denied by policy."""
    return action_type in UNSAFE_PAYLOAD_ACTIONS
