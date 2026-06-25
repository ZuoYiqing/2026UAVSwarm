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
from typing import Any, Tuple

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
        # pymavlink is optional.  Readiness must degrade cleanly when it is missing,
        # because default pytest/CI should not require PX4 or MAVLink dependencies.
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

    def _probe_via_pymavlink(self) -> Tuple[bool, str]:
        """Best-effort connect probe (no control command).

        Returns:
            (ok, reason)
        """
        try:
            # Import inside the probe so importing the package never requires pymavlink.
            from pymavlink import mavutil  # type: ignore

            # This is intentionally a heartbeat-only probe.  Do not add arm/set_mode/
            # command_long/takeoff here; those belong to later SITL smoke stages.
            conn = mavutil.mavlink_connection(
                self.config.transport_endpoint,
                timeout=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1),
            )
            hb = conn.wait_heartbeat(timeout=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1))
            if hb is None:
                return False, "heartbeat_timeout"
            return True, "backend_connected"
        except TimeoutError:
            return False, "heartbeat_timeout"
        except OSError:
            return False, "connection_failed"
        except Exception:
            return False, "probe_exception"

    def readiness_diagnostic(self) -> dict[str, Any]:
        # readiness is derived only from connect_probe.code.  The frozen rule is:
        # backend_connected -> ready; every other code -> not_ready.
        probe = self.connect_probe()
        code = str(probe.get("code", "backend_probe_failed"))
        reason = str(probe.get("reason", "unknown"))
        status = str(probe.get("status", self.session.status()))
        dep_ok = self._is_pymavlink_available()
        endpoint = str(self.config.transport_endpoint or "").strip()
        endpoint_configured = bool(endpoint)
        ready = code == "backend_connected"
        return {
            "backend": "px4_sitl",
            "dependency": {"name": "pymavlink", "present": dep_ok},
            "backend_enabled": bool(self.config.backend_enabled),
            "backend_mode": self.config.backend_mode,
            "transport_endpoint": endpoint,
            "transport_endpoint_configured": endpoint_configured,
            "connect_timeout_ms": self.config.connect_timeout_ms,
            "connect_probe": {"code": code, "reason": reason, "status": status},
            "readiness": "ready" if ready else "not_ready",
        }

    def connect_probe(self) -> dict[str, Any]:
        # Order matters for operator diagnostics:
        # 1. backend disabled/not SITL -> sitl_not_configured
        # 2. missing endpoint -> backend_not_configured
        # 3. missing optional dependency -> dependency_missing
        # 4. endpoint + dependency present but heartbeat fails -> backend_probe_failed
        status = self.session.status()
        if status == "not_configured":
            return {
                "ok": False,
                "code": "sitl_not_configured",
                "reason": "sitl_backend_disabled",
                "status": status,
            }
        if not str(self.config.transport_endpoint or "").strip():
            return {
                "ok": False,
                "code": "backend_not_configured",
                "reason": "transport_endpoint_missing",
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
            ok, reason = self._probe_via_pymavlink()
            if ok:
                return {
                    "ok": True,
                    "code": "backend_connected",
                    "reason": "backend_connected",
                    "status": "connected",
                }
            return {
                "ok": False,
                "code": "backend_probe_failed",
                "reason": reason,
                "status": status,
            }
        return {
            "ok": True,
            "code": "backend_connected",
            "reason": "backend_connected",
            "status": status,
        }

    def execute_mapped_action(self, action: str, mapping: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        # Execution remains placeholder-only.  Even if backend_connected is true,
        # this method does not send a real MAVLink control command.
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
