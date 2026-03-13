from __future__ import annotations

from typing import Any, Dict

from swarm_ai_platform.adapters.base import DroneAdapter, Telemetry


class VendorSDKAdapter(DroneAdapter):
    """Vendor SDK adapter placeholder.

    Example mapping ideas:
    - DJI: Mobile SDK / Onboard SDK / Payload SDK / Cloud API
    - Other vendors: proprietary gRPC/WebSocket/serial protocols

    Strategy:
    1) Keep your platform's canonical protocol_json as the "control plane".
    2) For each vendor, implement an adapter that:
       - translates command JSON -> vendor SDK calls
       - translates vendor telemetry -> canonical status messages
    3) Put all safety constraints (geofence, speed/alt limit,权限) in THIS layer,
       not inside LLM outputs.

    This demo does not implement vendor SDK bindings.
    """

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        ...

    def get_telemetry(self) -> Telemetry:
        raise NotImplementedError

    def send_command(self, cmd: Dict[str, Any]) -> None:
        raise NotImplementedError
