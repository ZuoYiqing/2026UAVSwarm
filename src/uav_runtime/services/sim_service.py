from __future__ import annotations

from uav_runtime.core.mission import Mission
from uav_runtime.core.scene import Scene
from uav_runtime.sim.evaluator import run_episode


def run_sim(mission: Mission, scene: Scene, *, steps: int = 20) -> dict:
    mission.validate()
    scene.validate()
    report = run_episode(scene.area[0], scene.area[1], scene.agents, steps=steps, drop_rate=0.15)
    return {
        "mission": mission.name,
        "steps": report.steps,
        "coverage": report.coverage,
        "sent": report.sent,
        "delivered": report.delivered,
        "dropped": report.dropped,
    }
