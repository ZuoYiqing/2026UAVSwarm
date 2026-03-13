from __future__ import annotations

from typing import Any, Dict

from swarm_ai_platform.adapters.base import DroneAdapter, Telemetry


class ROS2Adapter(DroneAdapter):
    """ROS2 adapter stub.

    Typical integration patterns:
    - run as a ROS2 node (rclpy/rclcpp)
    - subscribe to telemetry topics (e.g., /mavros/local_position/pose)
    - publish command topics (e.g., /mavros/setpoint_raw/local)

    In production you would also configure DDS QoS for reliability/bandwidth.

    This demo leaves it unimplemented to keep runtime dependencies low.
    """

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        ...

    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    def send_command(self, cmd: Dict[str, Any]) -> None:
        raise NotImplementedError
