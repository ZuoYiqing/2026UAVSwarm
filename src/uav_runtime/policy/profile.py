"""本轮最后修补点：把 contract 要求的 profile 扩展字段沉到 PolicyProfile 数据结构，保持 skeleton 默认值。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PolicyProfile:
    name: str
    allowed_skill_groups: list[str] = field(default_factory=list)
    denied_skill_groups: list[str] = field(default_factory=list)
    max_risk_when_link_lost: int = 1
    require_confirm_for_risk_ge: int = 3
    allow_without_confirm: bool = False
    max_concurrent_actions: int = 1

    # contract-aligned skeleton fields
    confirm_rules: list[dict[str, Any]] = field(default_factory=list)
    degradation_behavior: dict[str, Any] = field(default_factory=dict)
    fallback_behavior: dict[str, Any] = field(default_factory=dict)
    recovery_behavior: dict[str, Any] = field(default_factory=dict)
    runtime_constraints: dict[str, Any] = field(default_factory=dict)


def build_policy_profile(name: str = "standard") -> PolicyProfile:
    """Build a minimal Policy Profile v0.2 profile by name."""
    normalized = (name or "standard").strip().lower()
    if normalized == "conservative":
        return PolicyProfile(
            name="conservative",
            allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
            max_risk_when_link_lost=1,
            require_confirm_for_risk_ge=2,
            allow_without_confirm=False,
            runtime_constraints={"max_risk_allow": 3, "degraded_high_risk": "deny"},
            fallback_behavior={"lost_link_profile": "conservative", "lost_link_fallback_only": True},
        )
    if normalized == "aggressive":
        return PolicyProfile(
            name="aggressive",
            allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
            max_risk_when_link_lost=1,
            require_confirm_for_risk_ge=4,
            allow_without_confirm=False,
            runtime_constraints={"max_risk_allow": 5, "degraded_high_risk": "require_confirm"},
            fallback_behavior={"lost_link_profile": "aggressive", "lost_link_fallback_only": True},
        )
    if normalized == "lost_link":
        return PolicyProfile(
            name="lost_link",
            allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
            max_risk_when_link_lost=1,
            require_confirm_for_risk_ge=2,
            allow_without_confirm=False,
            runtime_constraints={"max_risk_allow": 2, "degraded_high_risk": "require_confirm"},
            fallback_behavior={"lost_link_profile": "lost_link", "lost_link_fallback_only": True},
        )
    return PolicyProfile(
        name="standard",
        allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
        max_risk_when_link_lost=1,
        require_confirm_for_risk_ge=3,
        allow_without_confirm=False,
        runtime_constraints={"max_risk_allow": 4, "degraded_high_risk": "require_confirm"},
        fallback_behavior={"lost_link_profile": "standard", "lost_link_fallback_only": True},
    )
