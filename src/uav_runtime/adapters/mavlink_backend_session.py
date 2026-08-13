"""Shared MAVLink transport session for one PX4 Runtime vehicle.

Exactly one receive loop owns ``recv_match`` for a session.  Command ACK
waiters, altitude observers, and telemetry subscribers consume dispatcher
state instead of competing for the UDP stream.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

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


def ned_down_z_to_altitude_m(z: float) -> float:
    """Convert PX4 LOCAL_POSITION_NED positive-down z into altitude."""
    return max(0.0, -float(z))


def _message_type(message: Any) -> str:
    getter = getattr(message, "get_type", None)
    return str(getter()) if callable(getter) else str(getattr(message, "type", ""))


def _source_ids(message: Any) -> tuple[int | None, int | None]:
    system_getter = getattr(message, "get_srcSystem", None)
    component_getter = getattr(message, "get_srcComponent", None)
    header = getattr(message, "_header", None)
    system_id = system_getter() if callable(system_getter) else getattr(header, "srcSystem", None)
    component_id = component_getter() if callable(component_getter) else getattr(header, "srcComponent", None)
    return (
        None if system_id is None else int(system_id),
        None if component_id is None else int(component_id),
    )


@dataclass(slots=True)
class MavlinkBackendSession:
    """One connection, one RX owner, and one dispatcher for one node."""

    backend_mode: str
    backend_enabled: bool
    transport_endpoint: str
    connected: bool = False
    connection: Any = None
    target_system: int = 1
    target_component: int = 1
    expected_target_system: int | None = None
    expected_target_component: int | None = None
    command_lock: threading.RLock = field(default_factory=threading.RLock)
    _connect_lock: threading.RLock = field(default_factory=threading.RLock)
    _mavutil: Any = None
    _heartbeat_stop: threading.Event = field(default_factory=threading.Event)
    _heartbeat_thread: threading.Thread | None = None
    _rx_stop: threading.Event = field(default_factory=threading.Event)
    _rx_thread: threading.Thread | None = None
    _rx_condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )
    _rx_sequence: int = 0
    _local_positions: list[tuple[int, float]] = field(default_factory=list)
    _subscribers: dict[int, Callable[[Any], None]] = field(default_factory=dict)
    _next_subscriber_id: int = 1
    _ack_generations: dict[int, int] = field(default_factory=dict)
    _active_ack_waiters: dict[int, int] = field(default_factory=dict)
    _ack_mailbox: dict[int, tuple[int, int]] = field(default_factory=dict)
    last_receive_error: str | None = None
    identity_error: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: MavlinkBackendConfig) -> "MavlinkBackendSession":
        return cls(
            backend_mode=config.backend_mode,
            backend_enabled=bool(config.backend_enabled),
            transport_endpoint=config.transport_endpoint,
            expected_target_system=config.target_system,
            expected_target_component=config.target_component,
        )

    def status(self) -> str:
        if self.backend_mode != "sitl":
            return "stub"
        if not self.backend_enabled:
            return "not_configured"
        return "connected" if self.connected else "not_connected"

    def availability_description(self) -> str:
        return {
            "not_configured": "sitl_backend_disabled",
            "not_connected": "sitl_backend_not_connected",
            "connected": "sitl_backend_connected",
        }.get(self.status(), "stub_mode")

    def connect(self, *, timeout_s: float, mavutil_module: Any | None = None) -> Any:
        """Create the persistent connection and validate heartbeat identity."""
        with self._connect_lock:
            if self.connection is not None and self.connected:
                return self.connection
            if self.backend_mode != "sitl" or not self.backend_enabled:
                raise RuntimeError("sitl_backend_disabled")
            if not self.transport_endpoint:
                raise RuntimeError("transport_endpoint_missing")
            if mavutil_module is None:
                from pymavlink import mavutil as mavutil_module  # type: ignore

            conn = None
            try:
                conn = mavutil_module.mavlink_connection(
                    self.transport_endpoint,
                    timeout=max(timeout_s, 0.1),
                )
                heartbeat = conn.wait_heartbeat(timeout=max(timeout_s, 0.1))
                if heartbeat is None:
                    raise TimeoutError("heartbeat_timeout")
                observed_system, observed_component = _source_ids(heartbeat)
                self.target_system = int(
                    observed_system
                    if observed_system is not None
                    else (getattr(conn, "target_system", 1) or 1)
                )
                self.target_component = int(
                    observed_component
                    if observed_component is not None
                    else (getattr(conn, "target_component", 1) or 1)
                )
                self._validate_identity(self.target_system, self.target_component)
                self._mavutil = mavutil_module
                self.connection = conn
                self.connected = True
                self.identity_error = None
                self.last_receive_error = None
                return conn
            except Exception:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
                self.connected = False
                self.connection = None
                raise

    def _validate_identity(self, system_id: int, component_id: int) -> None:
        if self.expected_target_system is not None and system_id != self.expected_target_system:
            self.identity_error = {
                "code": "target_system_mismatch",
                "expected_system_id": self.expected_target_system,
                "observed_system_id": system_id,
            }
            raise RuntimeError("target_system_mismatch")
        if self.expected_target_component is not None and component_id != self.expected_target_component:
            self.identity_error = {
                "code": "target_component_mismatch",
                "expected_component_id": self.expected_target_component,
                "observed_component_id": component_id,
            }
            raise RuntimeError("target_component_mismatch")

    def start_receive_loop(self, *, thread_name: str | None = None) -> bool:
        """Start the sole ``recv_match`` owner for this vehicle session."""
        if self.connection is None or not self.connected:
            raise RuntimeError("connection_required")
        with self._rx_condition:
            if self._rx_thread is not None and self._rx_thread.is_alive():
                return False
            self._rx_stop.clear()
            self._rx_thread = threading.Thread(
                target=self._receive_loop,
                name=thread_name or f"mavlink-rx-{self.target_system}",
                daemon=True,
            )
            self._rx_thread.start()
            return True

    def stop_receive_loop(self, *, join_timeout_s: float = 2.0) -> None:
        self._rx_stop.set()
        with self._rx_condition:
            self._rx_condition.notify_all()
        thread = self._rx_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=join_timeout_s)
        self._rx_thread = None

    def receive_thread_alive(self) -> bool:
        return self._rx_thread is not None and self._rx_thread.is_alive()

    def receive_owner_count(self) -> int:
        return 1 if self.receive_thread_alive() else 0

    def subscribe(self, callback: Callable[[Any], None]) -> int:
        with self._rx_condition:
            token = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[token] = callback
            return token

    def unsubscribe(self, token: int) -> None:
        with self._rx_condition:
            self._subscribers.pop(token, None)

    def _receive_loop(self) -> None:
        try:
            while not self._rx_stop.is_set():
                try:
                    message = self.connection.recv_match(
                        type=None,
                        blocking=True,
                        timeout=0.25,
                    )
                except Exception as exc:
                    if not self._rx_stop.is_set():
                        self.last_receive_error = f"{type(exc).__name__}: {exc}"
                        self.connected = False
                    break
                if message is not None:
                    self.dispatch_message(message)
        finally:
            with self._rx_condition:
                self._rx_condition.notify_all()

    def dispatch_message(self, message: Any) -> None:
        """Route one already-received message; public for deterministic tests."""
        msg_system, msg_component = _source_ids(message)
        if msg_system is not None and self.expected_target_system is not None and msg_system != self.expected_target_system:
            self.identity_error = {
                "code": "target_system_mismatch",
                "expected_system_id": self.expected_target_system,
                "observed_system_id": msg_system,
            }
            return
        if msg_component is not None and self.expected_target_component is not None and msg_component != self.expected_target_component:
            self.identity_error = {
                "code": "target_component_mismatch",
                "expected_component_id": self.expected_target_component,
                "observed_component_id": msg_component,
            }
            return

        callbacks: list[Callable[[Any], None]]
        with self._rx_condition:
            self._rx_sequence += 1
            sequence = self._rx_sequence
            kind = _message_type(message)
            if kind == "COMMAND_ACK":
                command = int(getattr(message, "command", -1))
                generation = self._active_ack_waiters.get(command)
                if generation is not None:
                    self._ack_mailbox[command] = (
                        generation,
                        int(getattr(message, "result", -1)),
                    )
            elif kind == "LOCAL_POSITION_NED":
                self._local_positions.append((sequence, float(getattr(message, "z", 0.0))))
                if len(self._local_positions) > 1024:
                    del self._local_positions[:-512]
            callbacks = list(self._subscribers.values())
            self._rx_condition.notify_all()
        for callback in callbacks:
            try:
                callback(message)
            except Exception:
                # A telemetry consumer cannot terminate the transport owner.
                continue

    def start_gcs_heartbeat(self, *, period_s: float = 1.0) -> bool:
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
        self.stop_receive_loop()
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()
        with self._rx_condition:
            self.connected = False
            self.connection = None
            self._active_ack_waiters.clear()
            self._ack_mailbox.clear()
            self._subscribers.clear()
            self._rx_condition.notify_all()

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
            p[0], p[1], p[2], p[3], p[4], p[5], p[6],
        )

    def _begin_ack_wait(self, command: int) -> int:
        with self._rx_condition:
            generation = self._ack_generations.get(command, 0) + 1
            self._ack_generations[command] = generation
            self._active_ack_waiters[command] = generation
            self._ack_mailbox.pop(command, None)
            return generation

    def wait_command_ack(
        self,
        command: int,
        *,
        timeout_s: float,
        generation: int | None = None,
    ) -> dict[str, Any]:
        if self.connection is None:
            raise RuntimeError("connection_required")
        self.start_receive_loop()
        generation = generation if generation is not None else self._begin_ack_wait(command)
        deadline = time.monotonic() + max(timeout_s, 0.1)
        try:
            with self._rx_condition:
                while time.monotonic() < deadline:
                    queued = self._ack_mailbox.get(command)
                    if queued is not None and queued[0] == generation:
                        self._ack_mailbox.pop(command, None)
                        return ack_dict(command, queued[1], timeout=False)
                    if not self.connected and self.last_receive_error:
                        break
                    self._rx_condition.wait(timeout=max(min(deadline - time.monotonic(), 0.5), 0.01))
            return ack_dict(command, None, timeout=True)
        finally:
            with self._rx_condition:
                if self._active_ack_waiters.get(command) == generation:
                    self._active_ack_waiters.pop(command, None)
                queued = self._ack_mailbox.get(command)
                if queued is not None and queued[0] == generation:
                    self._ack_mailbox.pop(command, None)

    def _send_and_wait_ack(self, command: int, params: list[float], *, timeout_s: float) -> dict[str, Any]:
        with self.command_lock:
            self.start_receive_loop()
            generation = self._begin_ack_wait(command)
            self.send_command_long(command, params)
            return self.wait_command_ack(command, timeout_s=timeout_s, generation=generation)

    def request_local_position_stream(self, *, rate_hz: float, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_SET_MESSAGE_INTERVAL", 511)
        msg_id = self._mavlink_const("MAVLINK_MSG_ID_LOCAL_POSITION_NED", 32)
        interval_us = int(1_000_000 / max(rate_hz, 0.1))
        ack = self._send_and_wait_ack(command, [float(msg_id), float(interval_us), 0.0, 0.0, 0.0, 0.0, 0.0], timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_SET_MESSAGE_INTERVAL"
        return ack

    def arm(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_COMPONENT_ARM_DISARM", 400)
        ack = self._send_and_wait_ack(command, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_COMPONENT_ARM_DISARM"
        return ack

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_TAKEOFF", 22)
        with self.command_lock:
            self.start_receive_loop()
            observation_cursor = self.local_position_cursor()
            generation = self._begin_ack_wait(command)
            self.send_command_long(
                command,
                [math.nan, 0.0, 0.0, math.nan, math.nan, math.nan, float(altitude_m)],
            )
            ack = self.wait_command_ack(
                command,
                timeout_s=timeout_s,
                generation=generation,
            )
        ack["command_name"] = "MAV_CMD_NAV_TAKEOFF"
        ack["local_position_cursor"] = observation_cursor
        return ack

    def land(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_LAND", 21)
        ack = self._send_and_wait_ack(command, [0.0] * 7, timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_NAV_LAND"
        return ack

    def observe_local_position_altitude(
        self,
        *,
        timeout_s: float,
        threshold_altitude_m: float | None = None,
        after_sequence: int | None = None,
    ) -> dict[str, Any]:
        if self.connection is None:
            raise RuntimeError("connection_required")
        if after_sequence is None:
            after_sequence = self.local_position_cursor()
        self.start_receive_loop()
        deadline = time.monotonic() + max(timeout_s, 0.1)
        max_altitude = 0.0
        samples: list[float] = []
        seen_sequence = int(after_sequence)
        with self._rx_condition:
            while time.monotonic() < deadline:
                fresh = [(seq, z) for seq, z in self._local_positions if seq > seen_sequence]
                for sequence, z in fresh:
                    seen_sequence = max(seen_sequence, sequence)
                    samples.append(z)
                    max_altitude = max(max_altitude, ned_down_z_to_altitude_m(z))
                if threshold_altitude_m is not None and max_altitude >= float(threshold_altitude_m):
                    break
                if not self.connected and self.last_receive_error:
                    break
                self._rx_condition.wait(timeout=max(min(deadline - time.monotonic(), 0.5), 0.01))
        return {
            "observed": bool(samples),
            "samples": len(samples),
            "sample_count": len(samples),
            "first_z": samples[0] if samples else None,
            "last_z": samples[-1] if samples else None,
            "min_z": min(samples) if samples else None,
            "max_z": max(samples) if samples else None,
            "max_altitude_m": round(max_altitude, 2),
            "threshold_altitude_m": threshold_altitude_m,
            "threshold_reached": (
                max_altitude >= float(threshold_altitude_m)
                if threshold_altitude_m is not None
                else None
            ),
        }

    def local_position_cursor(self) -> int:
        """Return the RX sequence after which a new observation may consume samples."""
        with self._rx_condition:
            return self._rx_sequence
