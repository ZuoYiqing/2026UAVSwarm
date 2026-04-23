"""Skill 协议与 SkillMetadata 抽象。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class SkillMetadata:
    name: str
    version: str
    skill_group: str
    risk_level: int


class Skill(Protocol):
    metadata: SkillMetadata

    def execute(self, params: dict) -> dict:
        ...
