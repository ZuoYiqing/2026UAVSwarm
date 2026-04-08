"""MAVLink adapter stub (v0.1): contract-compatible placeholder without real MAVLink/PX4 integration."""
from __future__ import annotations

from typing import Any


class MavlinkAdapter:
    """Future MAVLink adapter stub.

    This adapter intentionally does not connect to PX4/SITL yet.
    It only provides deterministic contract-compatible raw results.
    """

    name = "mavlink"

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        action = ""
        if isinstance(command, dict):
            action = str(command.get("command", "") or "")

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
                "connected": False,
                "reason": "no_real_backend",
            },
        }
