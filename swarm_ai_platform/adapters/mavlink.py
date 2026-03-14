from __future__ import annotations

from typing import Any, Dict, Optional

from swarm_ai_platform.adapters.base import DroneAdapter, Telemetry


class MAVLinkAdapter(DroneAdapter):
    """MAVLink adapter stub.

    Intended for PX4/ArduPilot based drones.

    Implementation notes (for your engineering backlog):
    - use pymavlink to connect (UDP/TCP/serial)
    - map your internal protocol_json commands to MAVLink messages (COMMAND_LONG, SET_POSITION_TARGET_* etc.)
    - publish telemetry back into your canonical message bus

    This demo intentionally leaves it unimplemented.
    """

    def __init__(self, connection_str: str) -> None:
        self.connection_str = connection_str
        self._mav = None

    def connect(self) -> None:
        raise NotImplementedError("Implement with pymavlink in your deployment.")

    def disconnect(self) -> None:
        self._mav = None

    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    def send_command(self, cmd: Dict[str, Any]) -> None:
        raise NotImplementedError
