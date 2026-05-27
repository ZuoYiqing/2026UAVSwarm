"""MissionContext 最小模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MissionContext:
    mission_id: str
    status: str = "created"
    active_tasks: list[str] = field(default_factory=list)
