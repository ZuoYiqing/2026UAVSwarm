"""BroadcastMessage 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("broadcast_message", "0.1", "coordination", 1)

def execute(params: dict) -> dict:
    return {"skill": "broadcast_message", "params": params}
