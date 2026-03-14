"""Hover 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("hover", "0.1", "flight_core", 1)

def execute(params: dict) -> dict:
    return {"skill": "hover", "params": params}
