"""Action / Capability Registry v0.1.

The registry is metadata-only. It does not execute actions, replace Policy Gate,
or dispatch adapters. It provides a shared reference for policy/profile rules,
fallback taxonomy, adapter mapping consistency, and future hardware capability
inventory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ActionDomain = Literal["flight", "payload", "system", "coordination"]
LinkStateName = Literal["healthy", "degraded", "lost"]


@dataclass(frozen=True, slots=True)
class ActionCapability:
    """Metadata row for one action_type.

    This is deliberately descriptive, not executable:
    - Policy Gate may reference the same concepts but is not replaced by this dataclass.
    - Adapter mapping may be checked against supported_adapters but is not dispatched from here.
    - Hardware inventory can use this as a checklist for what needs real interfaces.
    """

    action_type: str
    domain: ActionDomain
    skill_group: str
    risk_level: int
    supported_adapters: tuple[str, ...]
    fallback_allowed: bool
    allowed_link_states: tuple[LinkStateName, ...]
    requires_confirmation_by_default: bool = False
    dangerous: bool = False
    policy_default: str = "allow"
    notes: str = ""


_REGISTRY: dict[str, ActionCapability] = {
    # flight/control actions -------------------------------------------------
    # These entries describe current skeleton knowledge, not proven real flight capability.
    "takeoff": ActionCapability(
        action_type="takeoff",
        domain="flight",
        skill_group="flight_core",
        risk_level=2,
        supported_adapters=("mavlink",),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
        notes="MAVLink mapping skeleton only; no real takeoff command in current stage.",
    ),
    "goto": ActionCapability(
        action_type="goto",
        domain="flight",
        skill_group="flight_core",
        risk_level=3,
        supported_adapters=("mavlink",),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
        notes="New target navigation is not a lost-link fallback action.",
    ),
    "hover": ActionCapability(
        action_type="hover",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=("fake", "mavlink"),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
    ),
    "land": ActionCapability(
        action_type="land",
        domain="flight",
        skill_group="flight_core",
        risk_level=2,
        supported_adapters=("mavlink",),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
    ),
    "return_home": ActionCapability(
        action_type="return_home",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=("mavlink",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "hold_position": ActionCapability(
        action_type="hold_position",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=("fake",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "land_safe": ActionCapability(
        action_type="land_safe",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=(),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
        notes="Policy capability placeholder; not mapped to a real adapter yet.",
    ),
    "reduce_speed": ActionCapability(
        action_type="reduce_speed",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=(),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "maintain_heading": ActionCapability(
        action_type="maintain_heading",
        domain="flight",
        skill_group="flight_core",
        risk_level=1,
        supported_adapters=(),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    # payload/device and system-health actions ------------------------------
    # These are limited to non-destructive devices.  Real hardware support must be proven
    # later through the hardware capability mapping template and bench tests.
    "camera_capture": ActionCapability(
        action_type="camera_capture",
        domain="payload",
        skill_group="payload",
        risk_level=1,
        supported_adapters=("payload",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "gimbal_set_angle": ActionCapability(
        action_type="gimbal_set_angle",
        domain="payload",
        skill_group="payload",
        risk_level=2,
        supported_adapters=("payload",),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
    ),
    "speaker_play_message": ActionCapability(
        action_type="speaker_play_message",
        domain="payload",
        skill_group="payload",
        risk_level=2,
        supported_adapters=("payload",),
        fallback_allowed=False,
        allowed_link_states=("healthy", "degraded"),
        requires_confirmation_by_default=True,
        notes="Degraded can require confirmation; lost-link default is deny.",
    ),
    "light_set_state": ActionCapability(
        action_type="light_set_state",
        domain="payload",
        skill_group="payload",
        risk_level=1,
        supported_adapters=("payload",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "sensor_read": ActionCapability(
        action_type="sensor_read",
        domain="system",
        skill_group="payload",
        risk_level=1,
        supported_adapters=("payload",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "health_query": ActionCapability(
        action_type="health_query",
        domain="system",
        skill_group="payload",
        risk_level=1,
        supported_adapters=("payload",),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    "report_status": ActionCapability(
        action_type="report_status",
        domain="system",
        skill_group="generic",
        risk_level=1,
        supported_adapters=(),
        fallback_allowed=True,
        allowed_link_states=("healthy", "degraded", "lost"),
    ),
    # unsafe / explicitly denied actions ------------------------------------
    # Keep these visible as forbidden metadata so reviewers can see the boundary.
    # They must not appear in payload_mapping.py or mavlink_mapping.py supported actions.
    "payload_release": ActionCapability(
        action_type="payload_release",
        domain="payload",
        skill_group="payload",
        risk_level=10,
        supported_adapters=(),
        fallback_allowed=False,
        allowed_link_states=(),
        dangerous=True,
        policy_default="deny",
        notes="Explicitly unsafe placeholder; never mapped to adapters.",
    ),
    "drop": ActionCapability(
        action_type="drop",
        domain="payload",
        skill_group="payload",
        risk_level=10,
        supported_adapters=(),
        fallback_allowed=False,
        allowed_link_states=(),
        dangerous=True,
        policy_default="deny",
    ),
    "deploy": ActionCapability(
        action_type="deploy",
        domain="payload",
        skill_group="payload",
        risk_level=10,
        supported_adapters=(),
        fallback_allowed=False,
        allowed_link_states=(),
        dangerous=True,
        policy_default="deny",
    ),
    "strike": ActionCapability(
        action_type="strike",
        domain="payload",
        skill_group="payload",
        risk_level=10,
        supported_adapters=(),
        fallback_allowed=False,
        allowed_link_states=(),
        dangerous=True,
        policy_default="deny",
    ),
    "attack": ActionCapability(
        action_type="attack",
        domain="payload",
        skill_group="payload",
        risk_level=10,
        supported_adapters=(),
        fallback_allowed=False,
        allowed_link_states=(),
        dangerous=True,
        policy_default="deny",
    ),
}

ACTION_CAPABILITY_REGISTRY: dict[str, ActionCapability] = dict(_REGISTRY)


def get_action_capability(action_type: str) -> ActionCapability | None:
    """Return action capability metadata by action type."""
    return ACTION_CAPABILITY_REGISTRY.get(action_type)


def list_action_capabilities() -> tuple[ActionCapability, ...]:
    """Return all registered capabilities in action_type order."""
    return tuple(ACTION_CAPABILITY_REGISTRY[name] for name in sorted(ACTION_CAPABILITY_REGISTRY))


def action_capability_to_manifest(capability: ActionCapability) -> dict[str, Any]:
    """Return a JSON-ready manifest row for an action capability."""
    # dataclasses.asdict keeps tuples as tuples; convert tuple fields to lists so CLI JSON
    # output is easy for non-Python readers and hardware inventory spreadsheets.
    row = asdict(capability)
    row["supported_adapters"] = list(capability.supported_adapters)
    row["allowed_link_states"] = list(capability.allowed_link_states)
    return row


def capability_manifest(
    *,
    domain: ActionDomain | None = None,
    adapter: str | None = None,
    fallback_only: bool = False,
    include_dangerous: bool = False,
) -> list[dict[str, Any]]:
    """Return filtered, JSON-ready capability manifest rows.

    The manifest is visibility-only: it does not execute actions, dispatch adapters,
    or replace Policy Gate decisions. Dangerous actions are hidden by default and
    only shown when explicitly requested.
    """
    rows: list[dict[str, Any]] = []
    for capability in list_action_capabilities():
        # Safety default: manifest hides dangerous actions unless a reviewer explicitly asks
        # to audit forbidden capabilities via --include-dangerous.
        if capability.dangerous and not include_dangerous:
            continue
        if domain is not None and capability.domain != domain:
            continue
        if adapter is not None and adapter not in capability.supported_adapters:
            continue
        if fallback_only and not capability.fallback_allowed:
            continue
        rows.append(action_capability_to_manifest(capability))
    return rows


def fallback_action_types() -> frozenset[str]:
    """Return registry-derived lost-link fallback action types."""
    return frozenset(
        cap.action_type
        for cap in ACTION_CAPABILITY_REGISTRY.values()
        if cap.fallback_allowed and "lost" in cap.allowed_link_states and not cap.dangerous
    )


def unsafe_action_types() -> frozenset[str]:
    """Return registry-derived unsafe action types."""
    return frozenset(cap.action_type for cap in ACTION_CAPABILITY_REGISTRY.values() if cap.dangerous)
