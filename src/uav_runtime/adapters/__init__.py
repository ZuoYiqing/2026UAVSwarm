"""adapters 层包声明。"""

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter

__all__ = ["FakeAdapter", "MavlinkAdapter"]
