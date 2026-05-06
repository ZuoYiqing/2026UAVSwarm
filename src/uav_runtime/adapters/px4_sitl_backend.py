"""PX4 SITL backend placeholder for future real integration.

This module intentionally does NOT import real MAVLink/PX4 dependencies.
It exists to reserve the replacement slot for the first real backend.

v1 target (future):
- one backend implementation (`px4_sitl_backend`)
- one action first (`takeoff`)
- one transport path first (single endpoint)
- validate minimal end-to-end path only
"""
from __future__ import annotations

import importlib.util
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession


class Px4SitlBackend:
    """Future real PX4 SITL backend placeholder.

    Role now:
    - Conform to `MavlinkBackend` protocol
    - Return deterministic placeholder semantics

    Role later:
    - Replace placeholder execution with real SITL transport execution
      while keeping adapter contract unchanged.
    """

    name = "px4_sitl_backend"

    def __init__(self, config: MavlinkBackendConfig, session: MavlinkBackendSession) -> None:
        self.config = config
        self.session = session

    def status(self) -> str:
        return self.session.status()

    @staticmethod
    def _is_pymavlink_available() -> bool:
        return importlib.util.find_spec("pymavlink") is not None

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "mode": self.config.backend_mode,
            "enabled": bool(self.config.backend_enabled),
            "status": self.session.status(),
            "transport_endpoint": self.config.transport_endpoint,
            "connect_timeout_ms": self.config.connect_timeout_ms,
            "timeout_ms": self.config.timeout_ms,
            "retry_count": self.config.retry_count,
            "integration_stage": "placeholder",
            "planned_first_action": "takeoff",
            "planned_transport": "single_endpoint",
        }

    def connect_probe(self) -> dict[str, Any]:
        status = self.session.status()
        if status == "not_configured":
            return {
                "ok": False,
                "code": "sitl_not_configured",
                "reason": "sitl_backend_disabled",
                "status": status,
            }
        if not self._is_pymavlink_available():
            return {
                "ok": False,
                "code": "dependency_missing",
                "reason": "pymavlink_not_installed",
                "status": status,
            }
        if status == "not_connected":
            return {
                "ok": False,
                "code": "backend_probe_failed",
                "reason": "px4_sitl_backend_not_implemented",
                "status": status,
            }
        return {
            "ok": True,
            "code": "backend_connected",
            "reason": "backend_connected",
            "status": status,
        }

    def execute_mapped_action(self, action: str, mapping: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        probe = self.connect_probe()
        code = str(probe.get("code", "backend_probe_failed"))
        status = str(probe.get("status", self.session.status()))

        # Placeholder semantics only: never pretend success in current phase.
        return {
            "accepted": False,
            "code": code,
            "message": "px4_sitl_backend_placeholder",
            "detail": str(probe.get("reason", "not_implemented")),
            "evidence_ref": f"sitl://px4/{code}",
            "execution_trace": {
                "backend_impl": self.name,
                "backend_status": status,
                "probe_code": code,
                "probe_reason": str(probe.get("reason", "")),
                "action": action,
                "mapped_action": mapping.get("mavlink_action", ""),
                "args_keys": sorted(args.keys()),
                "transport_endpoint": self.config.transport_endpoint,
                "connect_timeout_ms": self.config.connect_timeout_ms,
                "timeout_ms": self.config.timeout_ms,
                "retry_count": self.config.retry_count,
                "integration_stage": "placeholder",
            },
        }
