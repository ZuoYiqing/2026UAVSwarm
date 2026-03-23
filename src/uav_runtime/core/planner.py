from __future__ import annotations

from dataclasses import dataclass

from .mission import Mission
from .scene import Scene


@dataclass(slots=True)
class Plan:
    mission: str
    tasks: list[dict]


class RulePlanner:
    def make_plan(self, mission: Mission, scene: Scene) -> Plan:
        mission.validate()
        scene.validate()
        tasks: list[dict] = []
        for idx in range(scene.agents):
            tasks.append(
                {
                    "agent": f"uav-{idx+1}",
                    "action": "patrol" if "search" in mission.goals else "hold",
                    "params": {"sector": idx},
                }
            )
        return Plan(mission=mission.name, tasks=tasks)
