"""技能注册与查询容器。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import Skill


@dataclass(slots=True)
class SkillRegistry:
    skills: dict[str, Skill] = field(default_factory=dict)

    def register(self, skill: Skill) -> None:
        self.skills[skill.metadata.name] = skill

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)
