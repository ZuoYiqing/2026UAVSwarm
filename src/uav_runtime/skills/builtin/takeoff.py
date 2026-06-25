"""Takeoff 语义技能 stub。"""
from __future__ import annotations

from uav_runtime.skills.base import SkillMetadata

metadata = SkillMetadata("takeoff", "0.1", "flight_core", 2)

def execute(params: dict) -> dict:
    return {"skill": "takeoff", "params": params}
