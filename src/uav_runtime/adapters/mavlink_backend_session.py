"""MAVLink backend session for SITL readiness and minimal PX4 smoke actions.

The real pymavlink dependency stays optional: importing this module must work in
CI without PX4 or pymavlink installed.  Real network/MAVLink objects are created
only when connect() is called by explicit SITL smoke commands.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig


MAV_RESULT_NAMES = {
    0: "MAV_RESULT_ACCEPTED",
    1: "MAV_RESULT_TEMPORARILY_REJECTED",
    2: "MAV_RESULT_DENIED",
    3: "MAV_RESULT_UNSUPPORTED",
    4: "MAV_RESULT_FAILED",
    5: "MAV_RESULT_IN_PROGRESS",
    6: "MAV_RESULT_CANCELLED",
    7: "MAV_RESULT_COMMAND_LONG_ONLY",
    8: "MAV_RESULT_COMMAND_INT_ONLY",
    9: "MAV_RESULT_COMMAND_UNSUPPORTED_MAV_FRAME",
}


def mav_result_name(result: int | None) -> str:
    if result is None:
        return "MAV_RESULT_TIMEOUT"
    return MAV_RESULT_NAMES.get(int(result), f"MAV_RESULT_UNKNOWN_{int(result)}")


def ack_dict(command: int | str, result: int | None, *, timeout: bool = False) -> dict[str, Any]:
    return {
        "command": command,
        "result": result,
        "result_name": mav_result_name(result),
        "timeout": bool(timeout),
    }


@dataclass(slots=True)
class MavlinkBackendSession:
    backend_mode: str
    backend_enabled: bool
    transport_endpoint: str
    connected: bool = False
    connection: Any = None
    target_system: int = 1
    target_component: int = 1
    _mavutil: Any = None
    _heartbeat_stop: threading.Event = field(default_factory=threading.Event)
    _heartbeat_thread: threading.Thread | None = None

    @classmethod
    def from_config(cls, config: MavlinkBackendConfig) -> "MavlinkBackendSession":
        return cls(
            backend_mode=config.backend_mode,
            backend_enabled=bool(config.backend_enabled),
            transport_endpoint=config.transport_endpoint,
            connected=False,
        )

    def status(self) -> str:
        if self.backend_mode != "sitl":
            return "stub"
        if not self.backend_enabled:
            return "not_configured"
        if not self.connected:
            return "not_connected"
        return "connected"

    def availability_description(self) -> str:
        status = self.status()
        if status == "not_configured":
            return "sitl_backend_disabled"
        if status == "not_connected":
            return "sitl_backend_not_connected"
        if status == "connected":
            return "sitl_backend_connected"
        return "stub_mode"

    def connect(self, *, timeout_s: float, mavutil_module: Any | None = None) -> Any:
        """Create/reuse a pymavlink connection and wait for PX4 heartbeat."""
        if self.connection is not None and self.connected:
            return self.connection
        if self.backend_mode != "sitl" or not self.backend_enabled:
            raise RuntimeError("sitl_backend_disabled")
        if not self.transport_endpoint:
            raise RuntimeError("transport_endpoint_missing")

        if mavutil_module is None:
            from pymavlink import mavutil as mavutil_module  # type: ignore

        self._mavutil = mavutil_module
        conn = mavutil_module.mavlink_connection(self.transport_endpoint, timeout=max(timeout_s, 0.1))
        hb = conn.wait_heartbeat(timeout=max(timeout_s, 0.1))
        if hb is None:
            raise TimeoutError("heartbeat_timeout")
        self.connection = conn
        self.connected = True
        self.target_system = int(getattr(conn, "target_system", 1) or 1)
        self.target_component = int(getattr(conn, "target_component", 1) or 1)
        return conn

    def start_gcs_heartbeat(self, *, period_s: float = 1.0) -> bool:
        """Start a lightweight GCS heartbeat loop required before PX4 ARM."""
        if self.connection is None:
            raise RuntimeError("connection_required")
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return True
        self._heartbeat_stop.clear()

        def _loop() -> None:
            mavlink = getattr(self._mavutil, "mavlink", None)
            mav_type = getattr(mavlink, "MAV_TYPE_GCS", 6)
            autopilot = getattr(mavlink, "MAV_AUTOPILOT_INVALID", 8)
            mode_flag = getattr(mavlink, "MAV_MODE_FLAG_CUSTOM_MODE_ENABLED", 1)
            state = getattr(mavlink, "MAV_STATE_ACTIVE", 4)
            while not self._heartbeat_stop.is_set():
                self.connection.mav.heartbeat_send(mav_type, autopilot, 0, 0, state, mode_flag)
                self._heartbeat_stop.wait(max(period_s, 0.05))

        self._heartbeat_thread = threading.Thread(target=_loop, name="px4-gcs-heartbeat", daemon=True)
        self._heartbeat_thread.start()
        return True

    def stop_gcs_heartbeat(self, *, join_timeout_s: float = 2.0) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None:
            thread.join(timeout=join_timeout_s)
        self._heartbeat_thread = None

    def heartbeat_thread_alive(self) -> bool:
        return self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()

    def close(self) -> None:
        self.stop_gcs_heartbeat()
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()
        self.connected = False
        self.connection = None

    def _mavlink_const(self, name: str, default: int) -> int:
        mavlink = getattr(self._mavutil, "mavlink", None)
        return int(getattr(mavlink, name, default))

    def send_command_long(self, command: int, params: list[float] | None = None) -> None:
        if self.connection is None:
            raise RuntimeError("connection_required")
        p = list(params or [])[:7]
        p.extend([0.0] * (7 - len(p)))
        self.connection.mav.command_long_send(
            self.target_system,
            self.target_component,
            int(command),
            0,
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            p[6],
        )

    def wait_command_ack(self, command: int, *, timeout_s: float) -> dict[str, Any]:
        if self.connection is None:
            raise RuntimeError("connection_required")
        deadline = time.time() + max(timeout_s, 0.1)
        while time.time() < deadline:
            msg = self.connection.recv_match(type="COMMAND_ACK", blocking=True, timeout=max(min(deadline - time.time(), 0.5), 0.01))
            if msg is None:
                continue
            if int(getattr(msg, "command", command)) != int(command):
                continue
            result = int(getattr(msg, "result", -1))
            return ack_dict(command, result, timeout=False)
        return ack_dict(command, None, timeout=True)

    def request_local_position_stream(self, *, rate_hz: float, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_SET_MESSAGE_INTERVAL", 511)
        msg_id = self._mavlink_const("MAVLINK_MSG_ID_LOCAL_POSITION_NED", 32)
        interval_us = int(1_000_000 / max(rate_hz, 0.1))
        self.send_command_long(command, [float(msg_id), float(interval_us), 0.0, 0.0, 0.0, 0.0, 0.0])
        ack = self.wait_command_ack(command, timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_SET_MESSAGE_INTERVAL"
        return ack

    def arm(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_COMPONENT_ARM_DISARM", 400)
        self.send_command_long(command, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        ack = self.wait_command_ack(command, timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_COMPONENT_ARM_DISARM"
        return ack

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_TAKEOFF", 22)
        self.send_command_long(command, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, float(altitude_m)])
        ack = self.wait_command_ack(command, timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_NAV_TAKEOFF"
        return ack

    def land(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_LAND", 21)
        self.send_command_long(command, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        ack = self.wait_command_ack(command, timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_NAV_LAND"
        return ack

    def observe_local_position_altitude(self, *, timeout_s: float) -> dict[str, Any]:
        if self.connection is None:
            raise RuntimeError("connection_required")
        deadline = time.time() + max(timeout_s, 0.1)
        max_altitude = 0.0
        count = 0
        while time.time() < deadline:
            msg = self.connection.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=max(min(deadline - time.time(), 0.5), 0.01))
            if msg is None:
                continue
            count += 1
            z = float(getattr(msg, "z", 0.0))
            # PX4 LOCAL_POSITION_NED uses positive-down z, so altitude above takeoff is -z.
            max_altitude = max(max_altitude, -z)
        return {"observed": count > 0, "samples": count, "max_altitude_m": round(max_altitude, 2)}
