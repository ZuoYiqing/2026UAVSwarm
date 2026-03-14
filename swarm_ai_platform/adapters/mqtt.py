from __future__ import annotations

import json
from typing import Any, Dict, Optional

from swarm_ai_platform.adapters.base import DroneAdapter, Telemetry


class MQTTAdapter(DroneAdapter):
    """MQTT adapter stub.

    Useful for IoT-class devices or bridging to edge nodes.
    - telemetry: publish to topic `telemetry/<node_id>`
    - commands: subscribe `cmd/<node_id>`

    Implementation left to integrator.
    """

    def __init__(self, broker: str, node_id: str):
        self.broker = broker
        self.node_id = node_id
        self._client = None

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        self._client = None

    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    def send_command(self, cmd: Dict[str, Any]) -> None:
        raise NotImplementedError
