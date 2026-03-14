"""StopStream 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("stop_stream", "0.1", "payload", 1)

def execute(params: dict) -> dict:
    return {"skill": "stop_stream", "params": params}
