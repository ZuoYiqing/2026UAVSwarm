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

    def execute_takeoff_smoke(
        self,
        *,
        altitude_m: float = 3.0,
        auto_land: bool = True,
        command_timeout_ms: int | None = None,
        observe_timeout_ms: int | None = None,
        threshold_ratio: float = 0.70,
    ) -> dict[str, Any]:
        rejected = self._ensure_sitl_action_allowed("takeoff")
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
            self.session.connect(timeout_s=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1))
            result["heartbeat_connected"] = True
            self.session.start_gcs_heartbeat()
            result["gcs_heartbeat_started"] = True

            interval_ack = self.session.request_local_position_stream(rate_hz=10.0, timeout_s=command_timeout_s)
            result["local_position_stream_ack"] = interval_ack
            result["local_position_stream_requested"] = not bool(interval_ack.get("timeout")) and int(interval_ack.get("result") if interval_ack.get("result") is not None else -1) == 0

            arm_ack = self.session.arm(timeout_s=command_timeout_s)
            result["arm_ack"] = arm_ack
            if bool(arm_ack.get("timeout")) or int(arm_ack.get("result") if arm_ack.get("result") is not None else -1) != 0:
                result["failure_reason"] = "arm_rejected_or_timeout"
                return self._finish_smoke_result(result)

            takeoff_ack = self.session.takeoff(altitude_m=target_altitude, timeout_s=command_timeout_s)
            result["takeoff_ack"] = takeoff_ack
            if bool(takeoff_ack.get("timeout")) or int(takeoff_ack.get("result") if takeoff_ack.get("result") is not None else -1) != 0:
                result["failure_reason"] = "takeoff_rejected_or_timeout"
                return self._finish_smoke_result(result)

            observation = self.session.observe_local_position_altitude(timeout_s=observe_timeout_s)
            result["altitude_observation"] = observation
            result["max_altitude_m"] = float(observation.get("max_altitude_m", 0.0) or 0.0)
            result["threshold_reached"] = result["max_altitude_m"] >= threshold_altitude
            if not result["threshold_reached"]:
                result["failure_reason"] = "altitude_threshold_not_reached"

            if auto_land:
                result["land_ack"] = self.session.land(timeout_s=command_timeout_s)

            if result["threshold_reached"]:
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
        finally:
            self.session.stop_gcs_heartbeat()

    def execute_land_action(self, *, command_timeout_ms: int | None = None) -> dict[str, Any]:
        rejected = self._ensure_sitl_action_allowed("land")
        if rejected is not None:
            return rejected
        command_timeout_s = float(command_timeout_ms or self.config.command_timeout_ms) / 1000.0
        result = self._base_action_result("land")
        try:
            self.session.connect(timeout_s=max(float(self.config.connect_timeout_ms) / 1000.0, 0.1))
            result["heartbeat_connected"] = True
            self.session.start_gcs_heartbeat()
            result["gcs_heartbeat_started"] = True
            result["land_ack"] = self.session.land(timeout_s=command_timeout_s)
            if not bool(result["land_ack"].get("timeout")) and int(result["land_ack"].get("result") if result["land_ack"].get("result") is not None else -1) == 0:
                result["result"] = "pass"
            else:
                result["failure_reason"] = "land_rejected_or_timeout"
            return self._finish_smoke_result(result)
        except Exception as exc:
            result["failure_reason"] = f"px4_land_exception:{type(exc).__name__}"
            return self._finish_smoke_result(result)
        finally:
            self.session.stop_gcs_heartbeat()

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
