from uav_runtime.services.sim_service import run_sim


def test_sim_service_basic(demo_mission, demo_scene) -> None:
    out = run_sim(demo_mission, demo_scene, steps=8)
    assert out["steps"] == 8
    assert out["sent"] == demo_scene.agents * 8
