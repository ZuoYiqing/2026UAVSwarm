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
        result["completion_mode"] = "landed_and_disarmed"
        try:
            result["heartbeat_connected"] = True
            result["gcs_heartbeat_started"] = True
            # LAND has safety priority: send it before any best-effort request
            # that could consume the command timeout budget.
            result["land_ack"] = self.session.land(timeout_s=command_timeout_s)
            result["ack_evidence"].append({"stage": "land", **result["land_ack"]})
            if not self._ack_accepted(result["land_ack"]):
                result["failure_reason"] = "land_rejected_or_timeout"
                result["completion_state"] = "timed_out" if result["land_ack"].get("timeout") else "failed"
                return self._finish_smoke_result(result)
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
            observation = self.session.observe_landed_and_disarmed(
                timeout_s=observe_timeout_s,
                after_sequence=int(result["land_ack"]["observation_cursor"]),
                cancel_event=cancel_event,
            )
            result["completion_evidence"] = observation
            result["completion_state"] = str(observation.get("status") or "unknown")
            if observation.get("completion_reached"):
                result["result"] = "pass"
            else:
                result["failure_reason"] = "landing_completion_timeout"
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
        }
        result["completion_state"] = str(outcome.get("reason") or "unknown")

        if outcome.get("failure_reason"):
            result["failure_reason"] = str(outcome["failure_reason"])
            return self._finish_smoke_result(result)

        result["result"] = "pass"
        return self._finish_smoke_result(result)

    def execute_return_home_action(
        self,
        *,
        timeout_s: float | None = None,
        min_progress_m: float = 5.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """让载具自主返航（RETURN_HOME / ``AUTO + RTL``），并验证它真的在收敛。

        ⚠️ 与那次事故的区别
        -------------------
        2026-09-28 的事故形状是：收尾阶段把"任意非 OFFBOARD 模式"当作安全悬停，
        于是 **AUTO_RTL 被当成安全状态接受** —— 飞机开始自主返航，而动作报 pass。

        这里做的是**完全相反**的事：RTL 是被**显式请求**的动作，而且**只有看到
        到 home 的距离确实缩小**才算成功。模式切换本身不算成功。

        RTL 仍然不在 ``mavlink_backend_session.PINNED_MODES`` 里 —— 那个集合的
        语义是"确认安全、可作为回退目标"，RTL 是自主机动，不应被当作静止状态接受。
        """
        rejected = self._ensure_sitl_action_allowed("return_home")
        if rejected is not None:
            return rejected
        rejected = self._ensure_persistent_session_ready("return_home")
        if rejected is not None:
            return rejected

        result = self._base_action_result("return_home")
        result["completion_mode"] = "auto_rtl_convergence"

        effective_timeout_s = (
            float(timeout_s)
            if timeout_s is not None
            else float(self.config.observe_timeout_ms) / 1000.0
        )
        try:
            outcome = self.session.return_home(
                timeout_s=effective_timeout_s,
                min_progress_m=float(min_progress_m),
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            result["failure_reason"] = f"px4_return_home_exception:{type(exc).__name__}"
            result["completion_state"] = "failed"
            return self._finish_smoke_result(result)

        result["mode"] = outcome.get("mode")
        result["mode_confirmed"] = bool((outcome.get("mode") or {}).get("confirmed"))
        result["returning"] = bool(outcome.get("returning"))
        result["return_reason"] = outcome.get("reason")
        result["initial_distance_m"] = outcome.get("initial_distance_m")
        result["final_distance_m"] = outcome.get("final_distance_m")
        result["distance_reduction_m"] = outcome.get("distance_reduction_m")
        result["completion_evidence"] = {
            "returning": outcome.get("returning"),
            "reason": outcome.get("reason"),
            "initial_distance_m": outcome.get("initial_distance_m"),
            "final_distance_m": outcome.get("final_distance_m"),
            "distance_reduction_m": outcome.get("distance_reduction_m"),
        }
        result["completion_state"] = str(outcome.get("reason") or "unknown")

        if outcome.get("failure_reason"):
            result["failure_reason"] = str(outcome["failure_reason"])
            return self._finish_smoke_result(result)

        result["result"] = "pass"
        return self._finish_smoke_result(result)

    @staticmethod
    def _ack_accepted(ack: dict[str, Any]) -> bool:
        return not bool(ack.get("timeout")) and int(
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
            return self.execute_land_action(command_timeout_ms=int(args.get("command_timeout_ms", self.config.command_timeout_ms) or self.config.command_timeout_ms))

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
