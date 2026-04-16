"""MAVLink adapter skeleton: contract-compatible placeholder without real MAVLink/PX4 integration."""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_mapping import resolve_mapping


class MavlinkAdapter:
    """Future MAVLink adapter stub.

    This adapter intentionally does not connect to PX4/SITL yet.
    It only provides deterministic contract-compatible raw results.
    """

    name = "mavlink"

    def __init__(self, config: MavlinkBackendConfig | None = None) -> None:
        self.config = config or MavlinkBackendConfig()

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
        if mode == "sitl" and not self.config.backend_enabled:
            return {
                "accepted": False,
                "code": "sitl_not_configured",
                "message": "mavlink_sitl_not_configured",
                "detail": "not_configured",
                "adapter": self.name,
                "evidence_ref": "sitl://mavlink/not_configured",
                "execution_trace": {
                    "mode": "mavlink_sitl",
                    "action": action,
                    "mapped_action": mapping["mavlink_action"],
                    "param_hints": mapping["param_hints"],
                    "args_keys": sorted(args.keys()),
                    "backend_mode": mode,
                    "backend_enabled": False,
                    "transport_endpoint": self.config.transport_endpoint,
                    "timeout_ms": self.config.timeout_ms,
                    "retry_count": self.config.retry_count,
                    "reason": "sitl_backend_disabled",
                },
            }

        return {
            "accepted": False,
            "code": "exec_unavailable",
            "message": "mavlink_stub_unavailable",
            "detail": "unavailable",
            "adapter": self.name,
            "evidence_ref": f"{mode}://mavlink/unavailable",
            "execution_trace": {
                "mode": f"mavlink_{mode}",
                "action": action,
                "mapped_action": mapping["mavlink_action"],
                "param_hints": mapping["param_hints"],
                "args_keys": sorted(args.keys()),
                "placeholder": bool(mapping.get("placeholder", True)),
                "backend_mode": mode,
                "backend_enabled": bool(self.config.backend_enabled),
                "transport_endpoint": self.config.transport_endpoint,
                "timeout_ms": self.config.timeout_ms,
                "retry_count": self.config.retry_count,
                "reason": "no_real_backend",
            },
        }
