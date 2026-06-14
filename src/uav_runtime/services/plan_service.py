from __future__ import annotations

from uav_runtime.core.mission import Mission
from uav_runtime.core.planner import RulePlanner
from uav_runtime.core.protocol import ProtocolSynthesizer
from uav_runtime.core.scene import Scene


def plan_mission(mission: Mission, scene: Scene) -> dict:
    planner = RulePlanner()
    plan = planner.make_plan(mission, scene)
    protocol = ProtocolSynthesizer().synthesize(plan)
    return {
        "mission": plan.mission,
        "tasks": plan.tasks,
        "messages": protocol.messages,
    }
