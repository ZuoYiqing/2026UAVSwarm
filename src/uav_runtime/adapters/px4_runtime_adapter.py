"""Node-bound AdapterGateway target for the validated PX4 SITL action backend."""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend


class Px4RuntimeActionAdapter:
    """Execute an already-policy-approved command on one resolved PX4 backend.

    The adapter is constructed after ``node_id`` resolution, so its backend owns
    exactly that node's Registry session. It performs no policy decisions and
    cannot select a different vehicle.
    """

    name = "mavlink"

    def __init__(self, backend: Px4SitlBackend) -> None:
        self.backend = backend

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("command") or "")
        arguments = dict(command.get("arguments") or {})
        if action == "takeoff":
            raw = self.backend.execute_takeoff_smoke(
                altitude_m=float(arguments.get("altitude_m", 3.0)),
                auto_land=bool(arguments.get("auto_land", True)),
                command_timeout_ms=arguments.get("command_timeout_ms"),
                observe_timeout_ms=arguments.get("observe_timeout_ms"),
                threshold_ratio=float(arguments.get("threshold_ratio", 0.70)),
            )
        elif action == "land":
            raw = self.backend.execute_land_action(command_timeout_ms=arguments.get("command_timeout_ms"))
        else:
            raw = {"action": action, "result": "fail", "failure_reason": "unsupported_px4_runtime_action"}
        passed = raw.get("result") == "pass"
        return {
            "accepted": passed,
            "code": "pass" if passed else str(raw.get("failure_reason") or "action_failed"),
            "message": "px4_runtime_action_completed" if passed else "px4_runtime_action_failed",
            "detail": str(raw.get("result") or "fail"),
            "adapter": self.name,
            "raw_result": raw,
        }
