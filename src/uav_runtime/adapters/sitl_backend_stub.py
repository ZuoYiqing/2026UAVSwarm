"""SITL backend stub (non-real backend).

This backend never opens real connections and only provides deterministic
placeholder semantics for smoke wiring.
"""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession


class SitlBackendStub:
    """Non-real backend placeholder for SITL wiring.

    Future real backend implementations should replace this class behind the
    same `MavlinkBackend` interface.
    """

    name = "sitl_backend_stub"

    def __init__(self, config: MavlinkBackendConfig, session: MavlinkBackendSession) -> None:
        self.config = config
        self.session = session

    def status(self) -> str:
        return self.session.status()

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "mode": self.config.backend_mode,
            "enabled": bool(self.config.backend_enabled),
            "status": self.session.status(),
            "transport_endpoint": self.config.transport_endpoint,
            "timeout_ms": self.config.timeout_ms,
            "retry_count": self.config.retry_count,
        }

    def execute_mapped_action(self, action: str, mapping: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        status = self.session.status()
        reason = self.session.availability_description()
        return {
            "accepted": False,
            "code": "smoke_not_connected" if status == "not_connected" else "sitl_not_configured",
            "message": "mavlink_sitl_smoke_not_connected" if status == "not_connected" else "mavlink_sitl_not_configured",
            "detail": "not_connected" if status == "not_connected" else "not_configured",
            "evidence_ref": "sitl://mavlink/not_connected" if status == "not_connected" else "sitl://mavlink/not_configured",
            "execution_trace": {
                "backend_impl": self.name,
                "backend_status": status,
                "action": action,
                "mapped_action": mapping.get("mavlink_action", ""),
                "param_hints": mapping.get("param_hints", []),
                "args_keys": sorted(args.keys()),
                "transport_endpoint": self.config.transport_endpoint,
                "timeout_ms": self.config.timeout_ms,
                "retry_count": self.config.retry_count,
                "reason": reason,
            },
        }
