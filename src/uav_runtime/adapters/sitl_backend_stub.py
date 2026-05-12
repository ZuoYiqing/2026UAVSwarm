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
            "connect_timeout_ms": self.config.connect_timeout_ms,
            "timeout_ms": self.config.timeout_ms,
            "retry_count": self.config.retry_count,
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
        if status == "not_connected" and not self.config.transport_endpoint:
            return {
                "ok": False,
                "code": "backend_probe_failed",
                "reason": "transport_endpoint_missing",
                "status": status,
            }
        if status == "not_connected":
            return {
                "ok": False,
                "code": "smoke_not_connected",
                "reason": "backend_not_connected",
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
        status = str(probe.get("status", self.session.status()))
        code = str(probe.get("code", "smoke_not_connected"))
        reason = str(probe.get("reason", self.session.availability_description()))
        message_map = {
            "backend_probe_failed": "mavlink_sitl_backend_probe_failed",
            "sitl_not_configured": "mavlink_sitl_not_configured",
            "smoke_not_connected": "mavlink_sitl_smoke_not_connected",
            "backend_connected": "mavlink_sitl_backend_connected",
        }
        detail_map = {
            "backend_probe_failed": "probe_failed",
            "sitl_not_configured": "not_configured",
            "smoke_not_connected": "not_connected",
            "backend_connected": "connected",
        }
        evidence_map = {
            "backend_probe_failed": "sitl://mavlink/probe_failed",
            "sitl_not_configured": "sitl://mavlink/not_configured",
            "smoke_not_connected": "sitl://mavlink/not_connected",
            "backend_connected": "sitl://mavlink/connected",
        }
        return {
            "accepted": False,
            "code": code,
            "message": message_map.get(code, "mavlink_sitl_smoke_not_connected"),
            "detail": detail_map.get(code, "not_connected"),
            "evidence_ref": evidence_map.get(code, "sitl://mavlink/not_connected"),
            "execution_trace": {
                "backend_impl": self.name,
                "backend_status": status,
                "action": action,
                "mapped_action": mapping.get("mavlink_action", ""),
                "param_hints": mapping.get("param_hints", []),
                "args_keys": sorted(args.keys()),
                "transport_endpoint": self.config.transport_endpoint,
                "connect_timeout_ms": self.config.connect_timeout_ms,
                "timeout_ms": self.config.timeout_ms,
                "retry_count": self.config.retry_count,
                "reason": reason,
                "probe_code": code,
            },
        }
