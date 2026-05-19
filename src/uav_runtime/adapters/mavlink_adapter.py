"""MAVLink adapter skeleton: contract-compatible placeholder without real MAVLink/PX4 integration."""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.mavlink_backend import MavlinkBackend
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.mavlink_mapping import resolve_mapping
from uav_runtime.adapters.sitl_backend_stub import SitlBackendStub


class MavlinkAdapter:
    """Future MAVLink adapter stub.

    This adapter intentionally does not connect to PX4/SITL yet.
    It only provides deterministic contract-compatible raw results.
    """

    name = "mavlink"

    def __init__(self, config: MavlinkBackendConfig | None = None) -> None:
        self.config = config or MavlinkBackendConfig()

    def _build_sitl_backend(self, session: MavlinkBackendSession) -> MavlinkBackend:
        """Build backend implementation for SITL mode.

        v0.1/v0.2-prep keeps this as a stub backend seam only.
        """
        return SitlBackendStub(config=self.config, session=session)

    def _smoke_tags(self, action: str, mode: str) -> dict[str, Any]:
        is_takeoff = action == "takeoff"
        return {
            "smoke_action": is_takeoff,
            "smoke_path": f"{action}_{mode}_wiring_v1" if is_takeoff else None,
        }

    def _unsupported(self, action: str) -> dict[str, Any]:
        mode = self.config.backend_mode
        return {
            "accepted": False,
            "code": "exec_unsupported",
            "message": "mavlink_stub_unsupported_command",
            "detail": "unsupported",
            "adapter": self.name,
            "evidence_ref": f"{mode}://mavlink/unsupported",
            "execution_trace": {
                **self._smoke_tags(action, mode),
                "mode": f"mavlink_{mode}",
                "action": action,
                "backend_mode": mode,
                "backend_enabled": bool(self.config.backend_enabled),
                "supported": False,
                "reason": "mapping_not_defined",
            },
        }

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        cmd = command if isinstance(command, dict) else {}
        action = str(cmd.get("command", "") or "")
        args = cmd.get("arguments") if isinstance(cmd.get("arguments"), dict) else {}

        mapping = resolve_mapping(action)
        if mapping is None:
            return self._unsupported(action)

        mode = self.config.backend_mode
        session = MavlinkBackendSession.from_config(self.config)
        session_status = session.status()
        session_desc = session.availability_description()

        if mode == "sitl" and session_status == "not_configured":
            return {
                "accepted": False,
                "code": "sitl_not_configured",
                "message": "mavlink_sitl_not_configured",
                "detail": "not_configured",
                "adapter": self.name,
                "evidence_ref": "sitl://mavlink/not_configured",
                "execution_trace": {
                    **self._smoke_tags(action, "sitl"),
                    "mode": "mavlink_sitl",
                    "action": action,
                    "mapped_action": mapping["mavlink_action"],
                    "param_hints": mapping["param_hints"],
                    "args_keys": sorted(args.keys()),
                    "backend_mode": mode,
                    "backend_enabled": False,
                    "session_status": session_status,
                    "transport_endpoint": self.config.transport_endpoint,
                    "connect_timeout_ms": self.config.connect_timeout_ms,
                    "timeout_ms": self.config.timeout_ms,
                    "retry_count": self.config.retry_count,
                    "reason": session_desc,
                },
            }

        if mode == "sitl" and session_status == "not_connected":
            backend = self._build_sitl_backend(session)
            probe = backend.connect_probe()
            backend_raw = backend.execute_mapped_action(action, mapping, args)
            trace = dict(backend_raw.get("execution_trace") or {})
            trace.update(
                {
                    **self._smoke_tags(action, "sitl"),
                    "mode": "mavlink_sitl",
                    "backend_mode": mode,
                    "backend_enabled": True,
                    "session_status": session_status,
                    "delegated_backend": backend.name,
                    "probe_code": probe.get("code"),
                }
            )
            return {
                "accepted": bool(backend_raw.get("accepted", False)),
                "code": str(backend_raw.get("code", "smoke_not_connected")),
                "message": str(backend_raw.get("message", "mavlink_sitl_smoke_not_connected")),
                "detail": str(backend_raw.get("detail", "not_connected")),
                "adapter": self.name,
                "evidence_ref": backend_raw.get("evidence_ref", "sitl://mavlink/not_connected"),
                "execution_trace": trace,
            }

        return {
            "accepted": False,
            "code": "exec_unavailable",
            "message": "mavlink_stub_unavailable",
            "detail": "unavailable",
            "adapter": self.name,
            "evidence_ref": f"{mode}://mavlink/unavailable",
            "execution_trace": {
                **self._smoke_tags(action, mode),
                "mode": f"mavlink_{mode}",
                "action": action,
                "mapped_action": mapping["mavlink_action"],
                "param_hints": mapping["param_hints"],
                "args_keys": sorted(args.keys()),
                "placeholder": bool(mapping.get("placeholder", True)),
                "backend_mode": mode,
                "backend_enabled": bool(self.config.backend_enabled),
                "session_status": session_status,
                "transport_endpoint": self.config.transport_endpoint,
                "connect_timeout_ms": self.config.connect_timeout_ms,
                "timeout_ms": self.config.timeout_ms,
                "retry_count": self.config.retry_count,
                "reason": "no_real_backend",
            },
        }
