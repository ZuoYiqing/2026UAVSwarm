from __future__ import annotations

from uav_runtime.core.mission import Mission
from uav_runtime.core.scene import Scene
from uav_runtime.services.health_service import health
from uav_runtime.services.plan_service import plan_mission
from uav_runtime.services.sim_service import run_sim


def cmd_health() -> dict:
    return health()


def cmd_plan() -> dict:
    mission = Mission(name="demo", goals=["search"])
    scene = Scene(area=(100, 100), agents=3, obstacles=[])
    return plan_mission(mission, scene)


def cmd_sim() -> dict:
    mission = Mission(name="demo", goals=["search"])
    scene = Scene(area=(40, 40), agents=2, obstacles=[])
    return run_sim(mission, scene, steps=25)
