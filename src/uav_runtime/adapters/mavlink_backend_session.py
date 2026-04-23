"""MAVLink backend session placeholder for future SITL wiring.

This module intentionally avoids any real network/serial/MAVLink dependency.
It only models backend readiness states for smoke-wiring semantics.
"""
from __future__ import annotations

from dataclasses import dataclass

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig


@dataclass(slots=True)
class MavlinkBackendSession:
    backend_mode: str
    backend_enabled: bool
    transport_endpoint: str
    connected: bool = False

    @classmethod
    def from_config(cls, config: MavlinkBackendConfig) -> "MavlinkBackendSession":
        return cls(
            backend_mode=config.backend_mode,
            backend_enabled=bool(config.backend_enabled),
            transport_endpoint=config.transport_endpoint,
            connected=False,
        )

    def status(self) -> str:
        if self.backend_mode != "sitl":
            return "stub"
        if not self.backend_enabled:
            return "not_configured"
        if not self.connected:
            return "not_connected"
        return "connected"

    def availability_description(self) -> str:
        status = self.status()
        if status == "not_configured":
            return "sitl_backend_disabled"
        if status == "not_connected":
            return "sitl_backend_not_connected"
        if status == "connected":
            return "sitl_backend_connected"
        return "stub_mode"
