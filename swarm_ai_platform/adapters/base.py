from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Telemetry:
    x_km: float
    y_km: float
    altitude_m: float
    heading_deg: float
    speed_m_s: float
    extra: Dict[str, Any]


class DroneAdapter:
    """Abstract adapter for heterogeneous drones.

    This demo repo does NOT implement real drone control.
    You should implement the methods with the vendor SDK / standard protocols under legal/compliant use.
    """

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    def send_command(self, cmd: Dict[str, Any]) -> None:
        """Send a high-level command represented by your protocol_json."""
        raise NotImplementedError
