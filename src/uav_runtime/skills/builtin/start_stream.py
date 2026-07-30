"""StartStream 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("start_stream", "0.1", "payload", 2)

def execute(params: dict) -> dict:
    return {"skill": "start_stream", "params": params}
