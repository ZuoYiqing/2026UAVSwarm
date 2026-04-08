from __future__ import annotations

import pytest

from uav_runtime.core.mission import Mission
from uav_runtime.core.scene import Scene


@pytest.fixture
def demo_mission() -> Mission:
    return Mission(name="demo", goals=["search"])


@pytest.fixture
def demo_scene() -> Scene:
    return Scene(area=(30, 30), agents=3, obstacles=[])
