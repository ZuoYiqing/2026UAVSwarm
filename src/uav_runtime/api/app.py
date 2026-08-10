from __future__ import annotations

from uav_runtime.api.models import PlanRequest, SimRequest
from uav_runtime.core.mission import Mission
from uav_runtime.core.scene import Scene
from uav_runtime.services.health_service import health
from uav_runtime.services.plan_service import plan_mission
from uav_runtime.services.sim_service import run_sim


def get_health() -> dict:
    return health()


def post_plan(req: PlanRequest) -> dict:
    mission = Mission(req.mission_name, req.goals)
    scene = Scene(req.area, req.agents, [])
    return plan_mission(mission, scene)


def post_sim(req: SimRequest) -> dict:
    mission = Mission(req.mission_name, req.goals)
    scene = Scene(req.area, req.agents, [])
    return run_sim(mission, scene, steps=req.steps)
