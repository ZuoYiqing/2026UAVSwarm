"""技能执行器骨架（预留 policy hook / timeout / rollback）。"""
from __future__ import annotations

from .registry import SkillRegistry


class SkillExecutor:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def execute(self, skill_name: str, params: dict) -> dict:
        skill = self.registry.get(skill_name)
        if skill is None:
            return {"ok": False, "error": "skill_not_found"}
        # TODO: policy hook
        # TODO: timeout handling
        # TODO: rollback hook
        return {"ok": True, "result": skill.execute(params)}
