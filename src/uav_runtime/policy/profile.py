"""PolicyProfile 模型（风险、skill group、确认、收缩、并发等字段）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PolicyProfile:
    name: str
    allowed_skill_groups: list[str] = field(default_factory=list)
    denied_skill_groups: list[str] = field(default_factory=list)
    max_risk_when_link_lost: int = 1
    require_confirm_for_risk_ge: int = 3
    allow_without_confirm: bool = False
    max_concurrent_actions: int = 1
