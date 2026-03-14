"""PolicyContext 与运行动作上下文模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

from uav_runtime.protocol.enums import AuthorityScope, CommandSource, LinkState


@dataclass(slots=True)
class PolicyContext:
    source: CommandSource
    scope: AuthorityScope
    link_state: LinkState
    active_profile: str = "default"
    flags: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeActionContext:
    task_id: str
    action: str
    risk_level: int
    require_confirm: bool = False
