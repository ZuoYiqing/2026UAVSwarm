from uav_runtime.core.planner import RulePlanner


def test_rule_planner_generates_one_task_per_agent(demo_mission, demo_scene) -> None:
    planner = RulePlanner()
    plan = planner.make_plan(demo_mission, demo_scene)
    assert len(plan.tasks) == demo_scene.agents
    assert all(t["action"] == "patrol" for t in plan.tasks)


def test_rule_planner_hold_mode() -> None:
    from uav_runtime.core.mission import Mission
    from uav_runtime.core.scene import Scene

    plan = RulePlanner().make_plan(Mission("x", ["observe"]), Scene((10, 10), 1, []))
    assert plan.tasks[0]["action"] == "hold"
