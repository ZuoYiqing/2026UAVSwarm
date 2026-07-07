"""CaptureSnapshot 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("capture_snapshot", "0.1", "payload", 1)

def execute(params: dict) -> dict:
    return {"skill": "capture_snapshot", "params": params}
