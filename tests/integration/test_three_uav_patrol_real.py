"""Opt-in real PX4/Gazebo patrol acceptance test.

This test flies all three simulated vehicles. It is skipped unless the operator
explicitly enables it after starting the harness and stopping Runtime.
"""
from __future__ import annotations

import os

import pytest

from simulation.px4_gazebo.scripts import patrol_three_uav


@pytest.mark.requires_px4_multi
def test_real_three_uav_patrol_acceptance() -> None:
    if os.environ.get("UAV_SIM_RUN_REAL_PATROL") != "1":
        pytest.skip("BLOCKED_WAITING_FOR_EXPLICIT_REAL_PATROL_OPT_IN")

    assert patrol_three_uav.main(["--pretty"]) == 0
