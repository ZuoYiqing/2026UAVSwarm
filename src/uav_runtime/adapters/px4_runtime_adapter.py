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
            if arguments.get("completion_mode") == "operational_stable_altitude":
                raw = self.backend.execute_takeoff_action(
                    altitude_m=float(arguments.get("altitude_m", 3.0)),
                    altitude_tolerance_m=float(arguments.get("altitude_tolerance_m", 0.3)),
                    stable_duration_ms=int(arguments.get("stable_duration_ms", 1000)),
                    command_timeout_ms=arguments.get("command_timeout_ms"),
                    observe_timeout_ms=arguments.get("observe_timeout_ms"),
                    cancel_event=arguments.get("_cancel_event"),
                )
            else:
                raw = self.backend.execute_takeoff_smoke(
                    altitude_m=float(arguments.get("altitude_m", 3.0)),
                    auto_land=bool(arguments.get("auto_land", True)),
                    command_timeout_ms=arguments.get("command_timeout_ms"),
                    observe_timeout_ms=arguments.get("observe_timeout_ms"),
                    threshold_ratio=float(arguments.get("threshold_ratio", 0.70)),
                    cancel_event=arguments.get("_cancel_event"),
                )
        elif action == "land":
            raw = self.backend.execute_land_action(
                command_timeout_ms=arguments.get("command_timeout_ms"),
                observe_timeout_ms=arguments.get("observe_timeout_ms"),
                landing_site=arguments.get("landing_site"),
                translation_scene_ned_m=arguments.get("translation_scene_ned_m"),
                cancel_event=arguments.get("_cancel_event"),
            )
        elif action == "goto":
            raw = self.backend.execute_goto_action(
                scene_north_m=float(arguments.get("scene_north_m", 0.0)),
                scene_east_m=float(arguments.get("scene_east_m", 0.0)),
                scene_down_m=float(arguments.get("scene_down_m", -3.0)),
                translation_scene_ned_m=dict(arguments.get("translation_scene_ned_m") or {}),
                altitude_tolerance_m=float(arguments.get("altitude_tolerance_m", 1.0)),
                hold_s=float(arguments.get("hold_s", 1.0)),
                command_timeout_ms=arguments.get("command_timeout_ms"),
                observe_timeout_ms=arguments.get("observe_timeout_ms"),
                cancel_event=arguments.get("_cancel_event"),
            )
        elif action in ("hold_position", "hold"):
            # HOLD 不需要坐标，也就不需要标定平移量 —— 它的语义是"待在现在这里"。
            raw = self.backend.execute_hold_position_action(
                tolerance_m=float(arguments.get("tolerance_m", 2.0)),
                hold_s=float(arguments.get("hold_s", 3.0)),
                timeout_s=(
                    float(arguments["timeout_s"]) if arguments.get("timeout_s") is not None
                    else (
                        float(arguments["observe_timeout_ms"]) / 1000.0
                        if arguments.get("observe_timeout_ms") is not None else None
                    )
                ),
                cancel_event=arguments.get("_cancel_event"),
            )
        elif action == "return_home":
            raw = self.backend.execute_return_home_action(
                timeout_s=(
                    float(arguments["timeout_s"]) if arguments.get("timeout_s") is not None
                    else (
                        float(arguments["observe_timeout_ms"]) / 1000.0
                        if arguments.get("observe_timeout_ms") is not None else None
                    )
                ),
                min_progress_m=float(arguments.get("min_progress_m", 5.0)),
                home_local_north_m=float(arguments["home_local_north_m"]),
                home_local_east_m=float(arguments["home_local_east_m"]),
                home_tolerance_m=float(arguments["home_tolerance_m"]),
                stable_duration_s=float(arguments["stable_duration_s"]),
                landing_site_id=str(arguments["landing_site_id"]),
                cancel_event=arguments.get("_cancel_event"),
            )
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
