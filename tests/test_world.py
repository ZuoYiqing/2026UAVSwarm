from uav_runtime.sim.world import World


def test_world_tick_moves_agents() -> None:
    w = World.create(10, 10, 2)
    prev = [(a.x, a.y) for a in w.agents]
    w.tick()
    now = [(a.x, a.y) for a in w.agents]
    assert prev != now


def test_world_coverage_ratio_range() -> None:
    w = World.create(8, 8, 2)
    ratio = w.coverage_ratio()
    assert 0.0 < ratio <= 1.0
