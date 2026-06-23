"""本轮最后修补点：把 contract 要求的上下文字段沉到 PolicyContext 数据结构，移除 orchestrator 的临时占位依赖。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uav_runtime.protocol.enums import AuthorityScope, CommandSource, LinkState


@dataclass(slots=True)
class PolicyContext:
    source: CommandSource
    scope: AuthorityScope
    link_state: LinkState

    # contract-aligned skeleton fields
    mission_id: str = ""
    current_phase: str = ""
    active_controller_source: str = ""
    active_delegations: list[str] = field(default_factory=list)
    running_actions: list[str] = field(default_factory=list)
    pending_takeovers: list[str] = field(default_factory=list)
    runtime_limits: dict[str, Any] = field(default_factory=dict)

    # existing fields
    active_profile: str = "default"
    flags: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeActionContext:
    task_id: str
    action: str
    risk_level: int
    require_confirm: bool = False
