from simulation.px4_gazebo.scripts.observe_runtime_motion import summarize_motion


def test_motion_requires_climb_from_disarmed_baseline_and_horizontal_samples() -> None:
    baseline = {"armed": False, "local_ned_m": [1, 2, 0.1]}
    flight = [
        {"armed": True, "local_ned_m": [north, 2, -2.9]}
        for north in (1, 2.5, 4.5)
    ]
    motion = summarize_motion([baseline, *flight])
    assert motion["motion_observed"]
    assert motion["max_relative_climb_m"] == 3
    assert motion["horizontal_displacement_m"] == 3.5
    assert not summarize_motion(flight)["motion_observed"]
    assert not summarize_motion([baseline, flight[0], flight[-1]])["motion_observed"]
