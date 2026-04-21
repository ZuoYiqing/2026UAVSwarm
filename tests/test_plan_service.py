from uav_runtime.services.plan_service import plan_mission


def test_plan_service_returns_tasks_and_messages(demo_mission, demo_scene) -> None:
    out = plan_mission(demo_mission, demo_scene)
    assert "tasks" in out
    assert "messages" in out
    assert len(out["tasks"]) == len(out["messages"])
