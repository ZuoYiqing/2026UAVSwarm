"""MAVLink adapter skeleton: contract-compatible placeholder without real MAVLink/PX4 integration."""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.mavlink_mapping import resolve_mapping


class MavlinkAdapter:
    """Future MAVLink adapter stub.

    This adapter intentionally does not connect to PX4/SITL yet.
    It only provides deterministic contract-compatible raw results.
    """

    name = "mavlink"

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        cmd = command if isinstance(command, dict) else {}
        action = str(cmd.get("command", "") or "")
        args = cmd.get("arguments") if isinstance(cmd.get("arguments"), dict) else {}

        mapping = resolve_mapping(action)
        if mapping is None:
            return {
                "accepted": False,
                "code": "exec_unsupported",
                "message": "mavlink_stub_unsupported_command",
                "detail": "unsupported",
                "adapter": self.name,
                "evidence_ref": "stub://mavlink/unsupported",
                "execution_trace": {
                    "mode": "mavlink_stub",
                    "action": action,
                    "connected": False,
                    "supported": False,
                    "reason": "mapping_not_defined",
                },
            }

        return {
            "accepted": False,
            "code": "exec_unavailable",
            "message": "mavlink_stub_unavailable",
            "detail": "unavailable",
            "adapter": self.name,
            "evidence_ref": "stub://mavlink/unavailable",
            "execution_trace": {
                "mode": "mavlink_stub",
                "action": action,
                "mapped_action": mapping["mavlink_action"],
                "param_hints": mapping["param_hints"],
                "args_keys": sorted(args.keys()),
                "placeholder": bool(mapping.get("placeholder", True)),
                "connected": False,
                "reason": "no_real_backend",
            },
        }
