"""PX4 SITL command backend using a Registry-owned persistent MAVLink session.

The dependency is still loaded lazily so offline/unit-test imports remain safe.
Operational takeoff and LAND distinguish command ACK evidence from telemetry
completion; generic mapped actions remain non-executable unless explicitly
admitted by the Runtime control path.
"""
from __future__ import annotations

import importlib.util
import math
import threading
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession


class Px4SitlBackend:
    """Execute approved PX4 SITL actions over one caller-owned session."""

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

    def _probe_via_pymavlink(self) -> tuple[bool, str, dict[str, Any]]:
        """Best-effort connect probe (no control command).

        Returns:
            (ok, reason)
        """
        connection = None
        details = {
            "expected_system_id": self.config.target_system,
            "expected_component_id": self.config.target_component,
            "observed_system_id": None,
            "observed_component_id": None,
        }
        try:
            # Import inside the probe so importing the package never requires pymavlink.
            from pymavlink import mavutil  # type: ignore

            # This is intentionally a heartbeat-only probe.  Do not add arm/set_mode/
            # command_long/takeoff here; those belong to later SITL smoke stages.
            connection = mavutil.mavlink_connection(
                self.config.transport_endpoint,
                timeout=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1),
            )
            hb = connection.wait_heartbeat(timeout=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1))
            if hb is None:
                return False, "heartbeat_timeout", details
            system_getter = getattr(hb, "get_srcSystem", None)
            component_getter = getattr(hb, "get_srcComponent", None)
            observed_system = (
                system_getter() if callable(system_getter)
                else getattr(connection, "target_system", None)
            )
            observed_component = (
                component_getter() if callable(component_getter)
                else getattr(connection, "target_component", None)
            )
            details["observed_system_id"] = None if observed_system is None else int(observed_system)
            details["observed_component_id"] = None if observed_component is None else int(observed_component)
            if self.config.target_system is not None and details["observed_system_id"] != self.config.target_system:
                return False, "target_system_mismatch", details
            if self.config.target_component is not None and details["observed_component_id"] != self.config.target_component:
                return False, "target_component_mismatch", details
            return True, "backend_connected", details
        except TimeoutError:
            return False, "heartbeat_timeout", details
        except OSError:
            return False, "connection_failed", details
        except Exception:
            return False, "probe_exception", details
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

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
            "connect_probe": dict(probe),
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
            probe_result = self._probe_via_pymavlink()
            if len(probe_result) == 2:  # Backward-compatible test/fake hook.
                ok, reason = probe_result
                identity: dict[str, Any] = {}
            else:
                ok, reason, identity = probe_result
            if ok:
                return {
                    "ok": True,
                    "code": "backend_connected",
                    "reason": "backend_connected",
                    "status": "connected",
                    **identity,
                }
            return {
                "ok": False,
                "code": "backend_probe_failed",
                "reason": reason,
                "status": status,
                **identity,
            }
        return {
            "ok": True,
            "code": "backend_connected",
            "reason": "backend_connected",
            "status": status,
            "expected_system_id": self.config.target_system,
            "expected_component_id": self.config.target_component,
            "observed_system_id": self.session.target_system,
            "observed_component_id": self.session.target_component,
        }

    def _base_action_result(self, action: str) -> dict[str, Any]:
        return {
            "action": action,
            "backend": "px4_sitl",
            "backend_mode": self.config.backend_mode,
            "endpoint": self.config.transport_endpoint,
            "heartbeat_connected": False,
            "gcs_heartbeat_started": False,
            "local_position_stream_requested": False,
            "arm_ack": None,
            "takeoff_ack": None,
            "land_ack": None,
            "ack_evidence": [],
            "completion_evidence": None,
            "completion_state": "unknown",
            "target_altitude_m": None,
            "max_altitude_m": 0.0,
            "threshold_ratio": None,
            "threshold_altitude_m": None,
            "threshold_reached": False,
            "auto_land": False,
            "result": "fail",
            "failure_reason": None,
        }

    def _preflight_rejection(self, action: str, reason: str) -> dict[str, Any]:
        result = self._base_action_result(action)
        result.update(
            {
                "accepted": False,
                "code": reason,
                "message": reason,
                "detail": reason,
                "adapter": "mavlink",
                "failure_reason": reason,
                "execution_trace": {
                    "backend_impl": self.name,
                    "backend_mode": self.config.backend_mode,
                    "backend_enabled": bool(self.config.backend_enabled),
                    "transport_endpoint": self.config.transport_endpoint,
                    "integration_stage": "px4_sitl_action_v0_1",
                },
            }
        )
        return result

    def _ensure_sitl_action_allowed(self, action: str) -> dict[str, Any] | None:
        if self.config.backend_mode != "sitl":
            return self._preflight_rejection(action, "sitl_only_required")
        if not self.config.backend_enabled:
            return self._preflight_rejection(action, "sitl_backend_disabled")
        if not str(self.config.transport_endpoint or "").strip():
            return self._preflight_rejection(action, "transport_endpoint_missing")
        if not self._is_pymavlink_available():
            return self._preflight_rejection(action, "dependency_missing")
        return None

    def _ensure_persistent_session_ready(self, action: str) -> dict[str, Any] | None:
        if self.session.status() != "connected":
            return self._preflight_rejection(
                action,
                "persistent_vehicle_session_not_connected",
            )
        if not self.session.receive_thread_alive():
            return self._preflight_rejection(
                action,
                "persistent_vehicle_rx_not_running",
            )
        if not self.session.heartbeat_thread_alive():
            return self._preflight_rejection(
                action,
                "persistent_gcs_heartbeat_not_running",
            )
        return None

    def execute_takeoff_smoke(
        self,
        *,
        altitude_m: float = 3.0,
        auto_land: bool = True,
        command_timeout_ms: int | None = None,
        observe_timeout_ms: int | None = None,
        threshold_ratio: float = 0.70,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        rejected = self._ensure_sitl_action_allowed("takeoff")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("takeoff")
        if rejected is not None:
            return rejected

        command_timeout_s = float(command_timeout_ms or self.config.command_timeout_ms) / 1000.0
        observe_timeout_s = float(observe_timeout_ms or self.config.observe_timeout_ms) / 1000.0
        target_altitude = float(altitude_m)
        threshold_altitude = round(target_altitude * float(threshold_ratio), 2)
        result = self._base_action_result("takeoff")
        result.update(
            {
                "target_altitude_m": target_altitude,
                "threshold_ratio": float(threshold_ratio),
                "threshold_altitude_m": threshold_altitude,
                "auto_land": bool(auto_land),
            }
        )

        try:
            result["heartbeat_connected"] = True
            result["gcs_heartbeat_started"] = True

            interval_ack = self.session.request_local_position_stream(rate_hz=10.0, timeout_s=command_timeout_s)
            result["local_position_stream_ack"] = interval_ack
            result["ack_evidence"].append({"stage": "local_position_stream", **interval_ack})
            result["local_position_stream_requested"] = not bool(interval_ack.get("timeout")) and int(interval_ack.get("result") if interval_ack.get("result") is not None else -1) == 0

            arm_ack = self.session.arm(timeout_s=command_timeout_s)
            result["arm_ack"] = arm_ack
            result["ack_evidence"].append({"stage": "arm", **arm_ack})
            if bool(arm_ack.get("timeout")) or int(arm_ack.get("result") if arm_ack.get("result") is not None else -1) != 0:
                result["failure_reason"] = "arm_rejected_or_timeout"
                return self._finish_smoke_result(result)
            if cancel_event is not None and cancel_event.is_set():
                result["failure_reason"] = "action_preempted_by_land"
                result["completion_state"] = "cancelled"
                return self._finish_smoke_result(result)

            takeoff_ack = self.session.takeoff(altitude_m=target_altitude, timeout_s=command_timeout_s)
            result["takeoff_ack"] = takeoff_ack
            result["ack_evidence"].append({"stage": "takeoff", **takeoff_ack})
            if bool(takeoff_ack.get("timeout")) or int(takeoff_ack.get("result") if takeoff_ack.get("result") is not None else -1) != 0:
                result["failure_reason"] = "takeoff_rejected_or_timeout"
                return self._finish_smoke_result(result)

            observation = self.session.observe_local_position_altitude(
                timeout_s=observe_timeout_s,
                threshold_altitude_m=threshold_altitude,
                after_sequence=int(takeoff_ack["local_position_cursor"]),
                cancel_event=cancel_event,
            )
            result["altitude_observation"] = observation
            result["completion_evidence"] = observation
            result["completion_state"] = "succeeded" if observation.get("threshold_reached") else "timed_out"
            result["max_altitude_m"] = float(observation.get("max_altitude_m", 0.0) or 0.0)
            result["threshold_reached"] = bool(observation.get("threshold_reached")) or result["max_altitude_m"] >= threshold_altitude
            if observation.get("cancelled"):
                result["failure_reason"] = "action_preempted_by_land"
                result["completion_state"] = "cancelled"
            elif not result["threshold_reached"]:
                result["failure_reason"] = "altitude_threshold_not_reached"

            if auto_land and not observation.get("cancelled"):
                result["land_ack"] = self.session.land(timeout_s=command_timeout_s)
                result["ack_evidence"].append({"stage": "land", **result["land_ack"]})

            if result["threshold_reached"] and not observation.get("cancelled"):
                result["result"] = "pass"
            return self._finish_smoke_result(result)
        except TimeoutError:
            result["failure_reason"] = "heartbeat_timeout"
            return self._finish_smoke_result(result)
        except OSError:
            result["failure_reason"] = "connection_failed"
            return self._finish_smoke_result(result)
        except Exception as exc:
            result["failure_reason"] = f"px4_action_exception:{type(exc).__name__}"
            return self._finish_smoke_result(result)

    def execute_takeoff_action(
        self,
        *,
        altitude_m: float = 3.0,
        altitude_tolerance_m: float = 0.3,
        stable_duration_ms: int = 1000,
        command_timeout_ms: int | None = None,
        observe_timeout_ms: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Operational takeoff: ACK admission plus fresh, stable altitude evidence."""
        rejected = self._ensure_sitl_action_allowed("takeoff")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("takeoff")
        if rejected is not None:
            return rejected
        command_timeout_s = float(command_timeout_ms or self.config.command_timeout_ms) / 1000.0
        observe_timeout_s = float(observe_timeout_ms or self.config.observe_timeout_ms) / 1000.0
        result = self._base_action_result("takeoff")
        result.update({
            "target_altitude_m": float(altitude_m),
            "altitude_tolerance_m": float(altitude_tolerance_m),
            "stable_duration_ms": int(stable_duration_ms),
            "auto_land": False,
            "completion_mode": "operational_stable_altitude",
        })
        try:
            result["heartbeat_connected"] = True
            result["gcs_heartbeat_started"] = True
            interval_ack = self.session.request_local_position_stream(
                rate_hz=10.0,
                timeout_s=command_timeout_s,
            )
            result["local_position_stream_ack"] = interval_ack
            result["ack_evidence"].append({"stage": "local_position_stream", **interval_ack})
            result["local_position_stream_requested"] = self._ack_accepted(interval_ack)
            if not result["local_position_stream_requested"]:
                result["failure_reason"] = "local_position_stream_rejected_or_timeout"
                result["completion_state"] = "timed_out" if interval_ack.get("timeout") else "failed"
                return self._finish_smoke_result(result)
            if cancel_event is not None and cancel_event.is_set():
                result["failure_reason"] = "action_preempted_by_land"
                result["completion_state"] = "cancelled"
                return self._finish_smoke_result(result)
            arm_ack = self.session.arm(timeout_s=command_timeout_s)
            result["arm_ack"] = arm_ack
            result["ack_evidence"].append({"stage": "arm", **arm_ack})
            if not self._ack_accepted(arm_ack):
                result["failure_reason"] = "arm_rejected_or_timeout"
                result["completion_state"] = "timed_out" if arm_ack.get("timeout") else "failed"
                return self._finish_smoke_result(result)
            if cancel_event is not None and cancel_event.is_set():
                result["failure_reason"] = "action_preempted_by_land"
                result["completion_state"] = "cancelled"
                return self._finish_smoke_result(result)
            takeoff_ack = self.session.takeoff(
                altitude_m=float(altitude_m),
                timeout_s=command_timeout_s,
            )
            result["takeoff_ack"] = takeoff_ack
            result["ack_evidence"].append({"stage": "takeoff", **takeoff_ack})
            if not self._ack_accepted(takeoff_ack):
                result["failure_reason"] = "takeoff_rejected_or_timeout"
                result["completion_state"] = "timed_out" if takeoff_ack.get("timeout") else "failed"
                return self._finish_smoke_result(result)
            observation = self.session.observe_takeoff_completion(
                timeout_s=observe_timeout_s,
                target_altitude_m=float(altitude_m),
                tolerance_m=float(altitude_tolerance_m),
                stable_duration_s=float(stable_duration_ms) / 1000.0,
                after_sequence=int(takeoff_ack["observation_cursor"]),
                cancel_event=cancel_event,
            )
            result["completion_evidence"] = observation
            result["altitude_observation"] = observation
            result["completion_state"] = str(observation.get("status") or "unknown")
            result["max_altitude_m"] = float(observation.get("max_altitude_m") or 0.0)
            result["threshold_reached"] = bool(observation.get("completion_reached"))
            if observation.get("cancelled"):
                result["failure_reason"] = "action_preempted_by_land"
            elif observation.get("completion_reached"):
                result["result"] = "pass"
            else:
                result["failure_reason"] = "takeoff_completion_timeout"
                self._classify_completion_timeout(result, "takeoff")
            return self._finish_smoke_result(result)
        except Exception as exc:
            result["failure_reason"] = f"px4_action_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            return self._finish_smoke_result(result)

    def execute_land_action(
        self,
        *,
        command_timeout_ms: int | None = None,
        observe_timeout_ms: int | None = None,
        landing_site: dict[str, Any] | None = None,
        ground_reference: dict[str, Any] | None = None,
        translation_scene_ned_m: dict[str, float] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        rejected = self._ensure_sitl_action_allowed("land")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("land")
        if rejected is not None:
            return rejected
        command_timeout_s = float(command_timeout_ms or self.config.command_timeout_ms) / 1000.0
        observe_timeout_s = float(observe_timeout_ms or self.config.observe_timeout_ms) / 1000.0
        result = self._base_action_result("land")
        result["completion_contract_version"] = "1.1"
        result["completion_mode"] = "scene_ground_landed_disarmed"
        result["site_completion"] = {"state": "not_requested" if not landing_site else "unknown"}
        try:
            result["heartbeat_connected"] = True
            result["gcs_heartbeat_started"] = True
            # LAND has safety priority: send it before any best-effort request
            # that could consume the command timeout budget.
            result["autonomous_execution_may_continue"] = True
            cursor_getter = getattr(self.session, "observation_cursor", None)
            result["autonomous_execution_after_sequence"] = cursor_getter() if callable(cursor_getter) else None
            result["land_ack"] = self.session.land(timeout_s=command_timeout_s)
            result["autonomous_execution_after_sequence"] = result["land_ack"].get("observation_cursor")
            result["ack_evidence"].append({"stage": "land", **result["land_ack"]})
            if not self._ack_accepted(result["land_ack"]):
                result["autonomous_execution_may_continue"] = bool(result["land_ack"].get("timeout"))
                result["failure_reason"] = "land_rejected_or_timeout"
                result["completion_state"] = "timed_out" if result["land_ack"].get("timeout") else "failed"
                return self._finish_smoke_result(result)
            result["autonomous_execution_may_continue"] = True
            try:
                stream_ack = self.session.request_landing_state_stream(
                    rate_hz=5.0,
                    timeout_s=command_timeout_s,
                )
            except Exception as exc:
                # Configuring evidence is best-effort for LAND. A stream setup
                # failure must not suppress the controlled landing command.
                stream_ack = {
                    "command": 511,
                    "command_name": "MAV_CMD_SET_MESSAGE_INTERVAL",
                    "message_name": "EXTENDED_SYS_STATE",
                    "result": None,
                    "result_name": "UNKNOWN",
                    "timeout": False,
                    "code": "landing_state_stream_exception",
                    "error_class": type(exc).__name__,
                }
            result["landing_state_stream_ack"] = stream_ack
            result["ack_evidence"].append({"stage": "landing_state_stream", **stream_ack})
            if ground_reference and translation_scene_ned_m:
                try:
                    position_ack = self.session.request_local_position_stream(rate_hz=10.0, timeout_s=command_timeout_s)
                except Exception as exc:
                    position_ack = {"command": 511, "result": None, "code": "local_position_stream_exception", "error_class": type(exc).__name__}
                result["ack_evidence"].append({"stage": "local_position_stream", **position_ack})
                observation = self.session.observe_ground_landing(
                    timeout_s=observe_timeout_s, after_sequence=int(result["land_ack"]["observation_cursor"]),
                    ground_reference=ground_reference, translation_scene_ned_m=translation_scene_ned_m,
                    expected_position_epoch=result["land_ack"].get("position_epoch"),
                    cancel_event=cancel_event,
                )
                result["completion_evidence"] = observation
                result["completion_state"] = str(observation.get("status") or "unknown")
                result["autonomous_execution_may_continue"] = not observation.get("physical_landed_disarmed", False)
                if observation.get("completion_reached"):
                    result["result"] = "pass"
                    if landing_site:
                        scene = observation["ground_check"]["scene_position_ned_m"]
                        center = landing_site["center_scene_ned_m"]
                        error = math.hypot(scene["north"] - center["north"], scene["east"] - center["east"])
                        on_site = error <= landing_site["horizontal_tolerance_m"]
                        result["site_completion"] = {"state": "succeeded" if on_site else "failed", "horizontal_error_m": error}
                        if not on_site:
                            result.update(result="fail", failure_reason="landing_outside_allowed_site", completion_state="failed")
                else:
                    result["failure_reason"] = observation.get("failure_reason") or "landing_completion_timeout"
                return self._finish_smoke_result(result)
            observation_args: dict[str, Any] = {
                "timeout_s": observe_timeout_s,
                "after_sequence": int(result["land_ack"]["observation_cursor"]),
                "cancel_event": cancel_event,
            }
            observation = self.session.observe_landed_and_disarmed(**observation_args)
            result["completion_evidence"] = observation
            result["autonomous_execution_may_continue"] = not observation.get("completion_reached", False)
            result["completion_state"] = "unknown"
            result["failure_reason"] = "ground_reference_unavailable"
            # Physical contact is separate evidence, never the operational ground goal.
            observation["physical_landed_disarmed"] = bool(observation.get("completion_reached"))
            observation["completion_reached"] = False
            if not observation["physical_landed_disarmed"]:
                result["completion_state"] = str(observation.get("status") or "unknown")
                result["failure_reason"] = "landing_completion_timeout"
                self._classify_completion_timeout(result, "land")
            return self._finish_smoke_result(result)
        except Exception as exc:
            result["failure_reason"] = f"px4_land_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            return self._finish_smoke_result(result)

    def execute_goto_action(
        self,
        *,
        scene_north_m: float,
        scene_east_m: float,
        scene_down_m: float,
        translation_scene_ned_m: dict[str, float],
        altitude_tolerance_m: float = 1.0,
        hold_s: float = 1.0,
        command_timeout_ms: int | None = None,
        observe_timeout_ms: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """飞到共享 scene_ned 坐标系下的指定点（OFFBOARD 位置控制）。

        为什么必须传入 ``translation_scene_ned_m``
        ----------------------------------------
        SET_POSITION_TARGET_LOCAL_NED 收的是**本机 vehicle_local_ned**，而操作者
        给的目标通常是共享 scene_ned。两者相差一个由仿真标定测得的平移量::

            vehicle_local_ned = scene_ned - translation_scene_ned_m

        **没有这个平移量就不能执行。** 若把 scene_ned 当成本机坐标直接发出，飞机
        会飞向一个相差该平移量的错误位置 —— 对 UAV-02/UAV-03 而言偏差达 8 米，
        足以撞上起降坪之外的物体。因此调用方必须先确认标定有效再调用本方法，
        本方法也会校验平移量的数值合法性。
        """
        rejected = self._ensure_sitl_action_allowed("goto")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("goto")
        if rejected is not None:
            return rejected

        result = self._base_action_result("goto")
        result["completion_mode"] = "offboard_position_arrival"

        # 平移量必须是三个有限数。缺失或非法一律拒绝，绝不用 0 顶替 ——
        # 用 0 顶替等于假装 scene 就是 local，正是要避免的那种静默错误。
        try:
            offset = (
                float(translation_scene_ned_m["north"]),
                float(translation_scene_ned_m["east"]),
                float(translation_scene_ned_m["down"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            result["failure_reason"] = "calibration_translation_invalid"
            result["detail"] = f"{type(exc).__name__}: {exc}"
            return self._finish_smoke_result(result)
        if not all(math.isfinite(value) for value in offset):
            result["failure_reason"] = "calibration_translation_not_finite"
            return self._finish_smoke_result(result)

        target_scene = (float(scene_north_m), float(scene_east_m), float(scene_down_m))
        local = (
            target_scene[0] - offset[0],
            target_scene[1] - offset[1],
            target_scene[2] - offset[2],
        )
        result["target_scene_ned_m"] = {
            "north": target_scene[0], "east": target_scene[1], "down": target_scene[2],
        }
        result["target_vehicle_local_ned_m"] = {
            "north": local[0], "east": local[1], "down": local[2],
        }
        result["calibration_translation_scene_ned_m"] = {
            "north": offset[0], "east": offset[1], "down": offset[2],
        }

        # goto 是位置控制，时长由“飞行距离 + 到达保持”决定，不能用固定 observe 超时。
        timeout_s = float(observe_timeout_ms or self.config.observe_timeout_ms) / 1000.0
        try:
            outcome = self.session.goto(
                north_m=local[0], east_m=local[1], down_m=local[2],
                tolerance_m=float(altitude_tolerance_m),
                hold_s=float(hold_s),
                timeout_s=timeout_s,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            result["failure_reason"] = f"px4_goto_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            return self._finish_smoke_result(result)

        # --- 证据展开 -------------------------------------------------------
        mode_result = outcome.get("mode_result") or {}
        arrival = outcome.get("arrival") or {}
        stream = outcome.get("stream") or {}
        restored = outcome.get("restored") or {}

        result["mode_ack"] = mode_result.get("ack")
        result["mode_confirmed"] = bool(mode_result.get("confirmed"))
        result["observed_main_mode"] = mode_result.get("observed_main_mode")
        result["arrival"] = arrival
        result["arrival_observed"] = bool(arrival.get("observed"))
        result["stream_setpoints"] = stream.get("setpoints")
        result["stream_errors"] = stream.get("errors")
        result["restored"] = restored
        result["completion_evidence"] = arrival
        result["completion_state"] = str(arrival.get("reason") or "unknown")

        # **安全不变量**：无论成功失败，都必须已切回安全模式。
        # 若收敛失败，即使到达了目标也不能报 pass —— 载具被留在 OFFBOARD
        # 属于比“没飞到”更严重的问题，必须让上层看见。
        if not restored.get("restored"):
            result["failure_reason"] = "mode_restore_failed"
            return self._finish_smoke_result(result)

        if outcome.get("failure_reason"):
            result["failure_reason"] = str(outcome["failure_reason"])
            # 到达超时要区分"还在接近"与"完全没动" —— 实测中 350 m 航线
            # 只因时间不够就报了 arrival_timeout，与"被挡住飞不过去"同码。
            self._classify_completion_timeout(result, "goto")
            return self._finish_smoke_result(result)

        result["result"] = "pass"
        return self._finish_smoke_result(result)

    def execute_hold_position_action(
        self,
        *,
        tolerance_m: float = 2.0,
        hold_s: float = 3.0,
        timeout_s: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """让载具保持当前位置悬停（HOLD），并验证它真的没动。

        与 ``goto`` 共用同一套模式机制（``AUTO + LOITER``），但**不需要坐标**：
        HOLD 的语义就是"待在现在这里"。因此也不需要标定平移量 —— 没有坐标换算。

        ⚠️ 判据是位置而不是模式
        ----------------------
        与 ``goto`` 一样，这里只接受**位置证据**。模式切换成功只说明飞控接受了
        指令；风、估计器漂移、控制器问题都可能让它在 LOITER 下缓慢移动。
        只报模式会让"动作报 pass 而飞机在飘"通过。
        """
        rejected = self._ensure_sitl_action_allowed("hold_position")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("hold_position")
        if rejected is not None:
            return rejected

        result = self._base_action_result("hold_position")
        result["completion_mode"] = "loiter_position_hold"

        effective_timeout_s = (
            float(timeout_s)
            if timeout_s is not None
            else float(self.config.observe_timeout_ms) / 1000.0
        )
        try:
            outcome = self.session.hold_position(
                tolerance_m=float(tolerance_m),
                hold_s=float(hold_s),
                timeout_s=effective_timeout_s,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            result["failure_reason"] = f"px4_hold_position_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            return self._finish_smoke_result(result)

        result["mode"] = outcome.get("mode")
        result["mode_confirmed"] = bool((outcome.get("mode") or {}).get("confirmed"))
        result["held"] = bool(outcome.get("held"))
        result["hold_reason"] = outcome.get("reason")
        result["max_drift_m"] = outcome.get("max_drift_m")
        result["hold_samples"] = outcome.get("samples")
        result["held_s"] = outcome.get("held_s")
        result["completion_evidence"] = {
            "held": outcome.get("held"),
            "reason": outcome.get("reason"),
            "max_drift_m": outcome.get("max_drift_m"),
            "samples": outcome.get("samples"),
            # 容差必须在这里 —— 它是对外暴露的完成证据的一部分，也是分类判断
            # "漂移是否在容差内"的依据。最初漏了它，于是分类拿不到判据、
            # 而说明文案却**假定**漂移在容差内，对"漂了 30 m"给出"位置在容差内"。
            "tolerance_m": outcome.get("tolerance_m"),
            "hold_s": outcome.get("hold_s"),
        }
        result["completion_state"] = str(outcome.get("reason") or "unknown")

        if outcome.get("failure_reason"):
            result["failure_reason"] = str(outcome["failure_reason"])
            self._classify_completion_timeout(result, "hold_position")
            return self._finish_smoke_result(result)

        result["result"] = "pass"
        return self._finish_smoke_result(result)

    def execute_return_home_action(
        self,
        *,
        timeout_s: float | None = None,
        min_progress_m: float = 5.0,
        home_local_north_m: float | None = None,
        home_local_east_m: float | None = None,
        home_tolerance_m: float = 0.75,
        stable_duration_s: float = 1.0,
        landing_site_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Require real PX4 home arrival; site identity is an independent goal."""
        rejected = self._ensure_sitl_action_allowed("return_home")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("return_home")
        if rejected is not None:
            return rejected

        result = self._base_action_result("return_home")
        result["completion_contract_version"] = "1.1"
        result["completion_mode"] = "auto_rtl_px4_home_arrival"
        cursor_getter = getattr(self.session, "observation_cursor", None)
        result["autonomous_execution_after_sequence"] = cursor_getter() if callable(cursor_getter) else None

        effective_timeout_s = (
            float(timeout_s)
            if timeout_s is not None
            else float(self.config.observe_timeout_ms) / 1000.0
        )
        try:
            outcome = self.session.return_home(
                timeout_s=effective_timeout_s,
                min_progress_m=float(min_progress_m),
                home_local_north_m=home_local_north_m,
                home_local_east_m=home_local_east_m,
                home_tolerance_m=float(home_tolerance_m),
                stable_duration_s=float(stable_duration_s),
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            result["failure_reason"] = f"px4_return_home_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            result["autonomous_execution_may_continue"] = True
            return self._finish_smoke_result(result)

        result["mode"] = outcome.get("mode")
        result["mode_confirmed"] = bool((outcome.get("mode") or {}).get("confirmed"))
        result["returning"] = bool(outcome.get("returning"))
        result["return_reason"] = outcome.get("reason")
        result["initial_distance_m"] = outcome.get("initial_distance_m")
        result["final_distance_m"] = outcome.get("final_distance_m")
        result["distance_reduction_m"] = outcome.get("distance_reduction_m")
        result["landing_site_id"] = landing_site_id
        result["autonomous_execution_may_continue"] = bool(outcome.get("autonomous_execution_may_continue"))
        result["autonomous_execution_after_sequence"] = outcome.get("autonomous_execution_after_sequence")
        result["home_evidence"] = outcome.get("home_evidence")
        result["rtl_destination_evidence"] = outcome.get("rtl_destination_evidence")
        result["ack_evidence"] = [{"stage": "home_request", **outcome["home_evidence"]["request_ack"]}] if (outcome.get("home_evidence") or {}).get("request_ack") else []
        if (outcome.get("mode") or {}).get("ack"):
            result["ack_evidence"].append({"stage": "rtl_mode", **outcome["mode"]["ack"]})
        result["completion_evidence"] = {**outcome,
            "returning": outcome.get("returning"),
            "reason": outcome.get("reason"),
            "initial_distance_m": outcome.get("initial_distance_m"),
            "final_distance_m": outcome.get("final_distance_m"),
            "distance_reduction_m": outcome.get("distance_reduction_m"),
            # 收敛要求同样要暴露 —— 分类与说明文案都读它。
            "min_progress_m": outcome.get("min_progress_m"),
            "samples": outcome.get("samples"),
            "home_local_north_m": (outcome.get("home_evidence") or {}).get("x"),
            "home_local_east_m": (outcome.get("home_evidence") or {}).get("y"),
            "home_tolerance_m": home_tolerance_m,
            "stable_duration_s": stable_duration_s,
            "landing_site_id": landing_site_id,
        }
        result["completion_state"] = "timed_out" if outcome.get("reason") in {"in_progress", "no_convergence"} else str(outcome.get("reason") or "unknown")

        if outcome.get("failure_reason"):
            result["failure_reason"] = str(outcome["failure_reason"])
            self._classify_completion_timeout(result, "return_home")
            return self._finish_smoke_result(result)

        if outcome.get("reason") != "arrived_at_home":
            result["failure_reason"] = "return_home_in_progress"
            return self._finish_smoke_result(result)
        result["result"] = "pass"
        return self._finish_smoke_result(result)

    def _classify_completion_timeout(self, result: dict[str, Any], action: str) -> None:
        """给"观测超时"补上分类，让调用方能区分"接近过"与"没反应"。

        背景（实测，不是假设）
        ----------------------
        原先所有超时都报同一个原因码，而它把三种完全不同的情况混成了一种：

          · 350 m 航线没飞完 → `arrival_timeout`，但飞机在正常飞行、越来越近
          · RTL 后降落超时   → `landing_completion_timeout`，而飞机**已经落地**
          · 坠机后降落超时   → `landing_completion_timeout`，飞机坠了、永远等不到条件

        调用方只看 `result: fail` 会得出错误结论：第一种该"再等等"，后两种该"出事了"。

        ⚠️ 分类**不改变** `result`，超时仍然报 `fail`。
        它只让失败更可读 —— 放松任何判据都不是这里该做的事。

        写入的字段：
          completion_state          partial_evidence / insufficient_evidence
          completion_timeout_detail 人类可读的"卡在哪"，便于日志与前端直接显示
        """
        # 仅处理"因为等不到完成条件而超时"的情况。ACK 超时（命令没被接受）
        # 与观测超时是两回事，不该混用同一套分类。
        if result.get("failure_reason") not in {
            "takeoff_completion_timeout",
            "landing_completion_timeout",
            "arrival_timeout",
            "hold_timeout",
            "return_home_not_converging",
        }:
            return
        try:
            classification = self.session.classify_incomplete(action)
        except Exception:  # noqa: BLE001 - 分类失败绝不能掩盖原始失败原因
            return
        if not classification:
            return

        result["completion_state"] = classification
        evidence = getattr(self.session, "_last_completion_evidence", None)
        result["completion_timeout_detail"] = self._describe_incomplete(
            action, classification, evidence if isinstance(evidence, dict) else {}
        )

    @staticmethod
    def _describe_incomplete(action: str, classification: str, evidence: dict[str, Any]) -> str:
        """把分类翻译成一句人话，说清"最后看到的是什么状态"。

        为什么单独写：原因码再细也需要一句可读的说明。实测中"降落在 RTL 之后超时"
        那次的证据里其实已经写着 `landed_state=on_ground`、`armed=true`，
        但没有人会去读那一长串 JSON —— 于是"飞机其实已经落地"这件事被淹没了。
        """
        if action == "land":
            landed = evidence.get("landed_state_name") or "unknown"
            armed = evidence.get("armed")
            if classification == "not_on_ground_after_land":
                # 与下一条**刻意不同**：这里没有"别只看本结果"的安抚。
                # 飞控明确报不在空中/不在地面，且仍 armed —— 再等下去也不会变。
                return (
                    f"超时前最后观测：落地状态={landed}、armed={armed}。"
                    "飞控明确未报告 on_ground，载具无法通过继续等待完成降落 —— "
                    "通常意味着载具已不在正常飞行状态（例如坠机或卡死），"
                    "**建议人工确认载具实际状态**，不要把它当作正常降落中的等待。"
                )
            if classification == "partial_evidence":
                return (
                    f"超时前最后观测：落地状态={landed}、armed={armed}。"
                    "两个完成条件里已有一个成立 —— 载具可能已经落地但未解除解锁，"
                    "或已解除解锁但飞控仍未报告 on_ground。"
                    "**这不代表降落失败**：请据遥测确认实际状态，不要只看本结果。"
                )
            return (
                f"超时前最后观测：落地状态={landed}、armed={armed}、"
                f"遥测={evidence.get('telemetry_state')}。"
                "没有取得可用于判断完成度的新鲜证据，无法说明卡在哪一步。"
            )

        if action == "takeoff":
            last = evidence.get("last_altitude_m")
            target = evidence.get("target_altitude_m")
            peak = evidence.get("max_altitude_m")
            if classification == "partial_evidence":
                return (
                    f"超时前最后观测：高度={last} m（目标 {target} m），过程最高={peak} m。"
                    "高度证据可判定 —— 载具在爬升或已接近目标高度，只是未满足"
                    "「进入容差并稳定保持」的完整条件。"
                )
            return "超时前没有取得可用高度样本，无法说明载具是否离地。"

        if action == "goto":
            last = evidence.get("last_error_m")
            nearest = evidence.get("min_error_m")
            tol = evidence.get("target_error_m")
            if classification == "partial_evidence":
                return (
                    f"超时前最后观测：距目标 {last} m，全过程最近 {nearest} m"
                    f"（到达容差 {tol} m）。载具接近过目标 —— 可能只是飞行时间不够，"
                    "也可能被障碍挡住无法继续靠近，请结合位置判断。"
                )
            return "超时前没有取得可用的位置样本，无法说明载具是否在接近目标。"

        if action in ("hold_position", "hold"):
            drift = evidence.get("max_drift_m")
            tol = evidence.get("tolerance_m")
            if classification != "partial_evidence":
                return "超时前没有取得可用的位置样本，无法说明载具是否稳定。"
            # ⚠️ 必须按实际数值分两种说法。最初这里无条件写"位置在容差内"，
            # 那是在**假定**结果；对"漂了 30 m"的场景给出了与事实相反的话。
            # 文案不能比判据更乐观。
            if isinstance(drift, (int, float)) and isinstance(tol, (int, float)) and drift <= tol:
                return (
                    f"超时前最后观测：最大漂移 {drift} m（容差 {tol} m）。"
                    "位置在容差内，缺的只是「持续保持」的时长。"
                )
            return (
                f"超时前最后观测：最大漂移 {drift} m，超出容差 {tol} m。"
                "载具没有稳定在容差内 —— 可能仍在移动（风、控制器或估计器漂移），"
                "也可能是保持时长尚未满足。"
            )

        if action == "return_home":
            # 键名用 final_distance_m / initial_distance_m —— 与契约里对外暴露的
            # 完成证据字段一致。最初这里写的是自造的 last_distance_m，于是永远
            # 读到 None，对真实失败给出"距 home None m"这种没有信息的话。
            last = evidence.get("final_distance_m")
            first = evidence.get("initial_distance_m")
            if classification == "partial_evidence":
                return (
                    f"超时前最后观测：距 home {last} m（起始 {first} m）。"
                    "距离可判定，但没有达到要求的收敛量。"
                )
            return "超时前没有取得可用的位置样本，无法说明载具是否在返航。"

        return f"分类={classification}（无更详细的说明）"

    @staticmethod
    def _ack_accepted(ack: dict[str, Any]) -> bool:        return not bool(ack.get("timeout")) and int(
            ack.get("result") if ack.get("result") is not None else -1
        ) == 0

    def _finish_smoke_result(self, result: dict[str, Any]) -> dict[str, Any]:
        result.update(
            {
                "accepted": result.get("result") == "pass",
                "code": "px4_sitl_action_pass" if result.get("result") == "pass" else "px4_sitl_action_failed",
                "message": "px4_sitl_action_v0_1",
                "detail": result.get("failure_reason") or result.get("result"),
                "adapter": "mavlink",
                "evidence_ref": f"sitl://px4/{result.get('action')}/{result.get('result')}",
                "execution_trace": {
                    "backend_impl": self.name,
                    "backend_mode": self.config.backend_mode,
                    "backend_enabled": bool(self.config.backend_enabled),
                    "transport_endpoint": self.config.transport_endpoint,
                    "command_timeout_ms": self.config.command_timeout_ms,
                    "observe_timeout_ms": self.config.observe_timeout_ms,
                    "integration_stage": "px4_sitl_action_v0_1",
                },
            }
        )
        return result

    def execute_mapped_action(self, action: str, mapping: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        # Runtime smoke actions must opt into real SITL command execution explicitly.
        # Existing submit-action mavlink paths keep placeholder semantics unless the
        # CLI/runtime passes __real_sitl_action=True after Policy Gate approval.
        if bool(args.get("__real_sitl_action")) and action == "takeoff":
            return self.execute_takeoff_smoke(
                altitude_m=float(args.get("altitude_m", 3.0) or 3.0),
                auto_land=bool(args.get("auto_land", True)),
                command_timeout_ms=int(args.get("command_timeout_ms", self.config.command_timeout_ms) or self.config.command_timeout_ms),
                observe_timeout_ms=int(args.get("observe_timeout_ms", self.config.observe_timeout_ms) or self.config.observe_timeout_ms),
                threshold_ratio=float(args.get("threshold_ratio", 0.70) or 0.70),
            )
        if bool(args.get("__real_sitl_action")) and action == "land":
            return self.execute_land_action(
                command_timeout_ms=int(
                    args.get("command_timeout_ms", self.config.command_timeout_ms)
                    or self.config.command_timeout_ms
                ),
                landing_site=args.get("landing_site"),
                ground_reference=args.get("ground_reference"),
                translation_scene_ned_m=args.get("translation_scene_ned_m"),
            )

        probe = self.connect_probe()
        code = str(probe.get("code", "backend_probe_failed"))
        status = str(probe.get("status", self.session.status()))

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
