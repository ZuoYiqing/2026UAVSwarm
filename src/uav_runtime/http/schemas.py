"""Small JSON schema helpers for the local Runtime HTTP Bridge.

The bridge intentionally uses plain dictionaries/dataclasses instead of a large
web framework contract so tests and local development can run without extra
runtime dependencies.  These helpers normalize browser JSON into the existing
uav_runtime config objects without exposing shell commands.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class BackendRequest:
    node_id: str | None = None
    system_id: int | None = None
    backend: str = "px4_sitl"
    backend_mode: str = "sitl"
    backend_enabled: bool = False
    transport_endpoint: str = ""
    connect_timeout_ms: int = 3000
    command_timeout_ms: int = 10000
    observe_timeout_ms: int = 25000
    timeout_ms: int = 3000
    retry_count: int = 0

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BackendRequest":
        return cls(
            node_id=str(payload["node_id"]) if payload.get("node_id") else None,
            system_id=_int(payload.get("system_id"), 0) or None,
            backend=str(payload.get("backend", "px4_sitl") or "px4_sitl"),
            backend_mode=str(payload.get("backend_mode", "sitl") or "sitl"),
            backend_enabled=_bool(payload.get("backend_enabled"), False),
            # Preserve udpin: endpoints exactly.  PX4 SITL onboard MAVLink expects
            # pymavlink to listen on udpin:127.0.0.1:14540; do not rewrite to udp://.
            transport_endpoint=str(payload.get("transport_endpoint", "") or ""),
            connect_timeout_ms=_int(payload.get("connect_timeout_ms"), 3000),
            command_timeout_ms=_int(payload.get("command_timeout_ms"), 10000),
            observe_timeout_ms=_int(payload.get("observe_timeout_ms"), 25000),
            timeout_ms=_int(payload.get("timeout_ms"), 3000),
            retry_count=_int(payload.get("retry_count"), 0),
        )

    def to_mavlink_config(self) -> MavlinkBackendConfig:
        return MavlinkBackendConfig(
            backend_mode=self.backend_mode,
            backend_enabled=self.backend_enabled,
            transport_endpoint=self.transport_endpoint,
            target_system=self.system_id,
            connect_timeout_ms=self.connect_timeout_ms,
            command_timeout_ms=self.command_timeout_ms,
            observe_timeout_ms=self.observe_timeout_ms,
            timeout_ms=self.timeout_ms,
            retry_count=self.retry_count,
        )


@dataclass(slots=True)
class SmokeTakeoffRequest(BackendRequest):
    altitude_m: float = 3.0
    threshold_ratio: float = 0.70
    auto_land: bool = True

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "SmokeTakeoffRequest":
        base = BackendRequest.from_json(payload)
        return cls(
            **asdict(base),
            altitude_m=_float(payload.get("altitude_m"), 3.0),
            threshold_ratio=_float(payload.get("threshold_ratio"), 0.70),
            auto_land=_bool(payload.get("auto_land"), True),
        )


@dataclass(slots=True)
class LandRequest(BackendRequest):
    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "LandRequest":
        base = BackendRequest.from_json(payload)
        return cls(**asdict(base))


@dataclass(slots=True)
class PlanMissionRequest:
    mission_type: str
    source: str = "ground_station"
    profile: str = "standard"
    dry_run: bool = True
    objective: str = ""

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PlanMissionRequest":
        return cls(
            mission_type=str(payload.get("mission_type", "") or ""),
            source=str(payload.get("source", "ground_station") or "ground_station"),
            profile=str(payload.get("profile", "standard") or "standard"),
            dry_run=_bool(payload.get("dry_run"), True),
            objective=str(payload.get("objective", "") or ""),
        )
