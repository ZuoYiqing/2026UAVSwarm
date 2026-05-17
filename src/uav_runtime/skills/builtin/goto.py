"""Goto 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("goto", "0.1", "flight_core", 2)

def execute(params: dict) -> dict:
    return {"skill": "goto", "params": params}
