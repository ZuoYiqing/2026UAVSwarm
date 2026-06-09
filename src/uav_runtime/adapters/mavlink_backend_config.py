"""MAVLink backend config placeholder (adapter-internal/deployment wiring level)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MavlinkBackendConfig:
    backend_mode: str = "stub"  # supported: stub / sitl
    backend_enabled: bool = False
    transport_endpoint: str = ""
    connect_timeout_ms: int = 3000
    timeout_ms: int = 3000
    retry_count: int = 0
