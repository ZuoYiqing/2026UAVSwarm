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
