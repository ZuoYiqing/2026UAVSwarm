from uav_runtime.sim.evaluator import run_episode


def test_run_episode_counts_messages() -> None:
    rep = run_episode(10, 10, 2, steps=5, drop_rate=0.2)
    assert rep.sent == 10
    assert rep.delivered + rep.dropped == rep.sent
