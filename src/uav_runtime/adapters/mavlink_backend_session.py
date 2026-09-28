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
from datetime import datetime, timezone
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


# --- PX4 自定义飞行模式 ---------------------------------------------------
#
# MAVLink 的公共枚举里没有 PX4 的主模式号 —— 它们是 PX4 自己的约定，定义在
# PX4-Autopilot 的 src/modules/commander/px4_custom_mode.h。要切模式必须自己
# 带这些常量，不能指望 pymavlink 提供（实测 getattr 取不到）。
#
# 值必须与 PX4 源码逐字一致。源码里是自动递增的枚举，**不是** 1/2/3/6/7 这样
# 跳着的 —— ACRO=5 就夹在 AUTO(4) 和 OFFBOARD(6) 之间。所以每次 PX4 升级后
# 都要重新核对。tests/unit/test_px4_custom_mode_constants.py 会直接从
# PX4 头文件解析真实值来校验本表，不一致就会失败。
#
# 用法：MAV_CMD_DO_SET_MODE，param1 = MAV_MODE_FLAG_CUSTOM_MODE_ENABLED(1)，
#       param2 = 主模式号，param3 = 子模式号（无子模式时 0）。
PX4_CUSTOM_MAIN_MODE_MANUAL = 1
PX4_CUSTOM_MAIN_MODE_ALTCTL = 2
PX4_CUSTOM_MAIN_MODE_POSCTL = 3
PX4_CUSTOM_MAIN_MODE_AUTO = 4
PX4_CUSTOM_MAIN_MODE_ACRO = 5
PX4_CUSTOM_MAIN_MODE_OFFBOARD = 6
PX4_CUSTOM_MAIN_MODE_STABILIZED = 7
PX4_CUSTOM_MAIN_MODE_RATTITUDE_LEGACY = 8
PX4_CUSTOM_MAIN_MODE_SIMPLE = 9
PX4_CUSTOM_MAIN_MODE_TERMINATION = 10
PX4_CUSTOM_MAIN_MODE_ALTITUDE_CRUISE = 11

#: 主模式 -> 名称，便于证据与日志可读
PX4_MAIN_MODE_NAMES = {
    PX4_CUSTOM_MAIN_MODE_MANUAL: "MANUAL",
    PX4_CUSTOM_MAIN_MODE_ALTCTL: "ALTCTL",
    PX4_CUSTOM_MAIN_MODE_POSCTL: "POSCTL",
    PX4_CUSTOM_MAIN_MODE_AUTO: "AUTO",
    PX4_CUSTOM_MAIN_MODE_ACRO: "ACRO",
    PX4_CUSTOM_MAIN_MODE_OFFBOARD: "OFFBOARD",
    PX4_CUSTOM_MAIN_MODE_STABILIZED: "STABILIZED",
    PX4_CUSTOM_MAIN_MODE_RATTITUDE_LEGACY: "RATTITUDE_LEGACY",
    PX4_CUSTOM_MAIN_MODE_SIMPLE: "SIMPLE",
    PX4_CUSTOM_MAIN_MODE_TERMINATION: "TERMINATION",
    PX4_CUSTOM_MAIN_MODE_ALTITUDE_CRUISE: "ALTITUDE_CRUISE",
}


# --- SET_POSITION_TARGET_LOCAL_NED 的 type_mask ---------------------------
#
# type_mask 的语义是"**忽略哪些字段**"（1 = 忽略，0 = 使用）。这个语义极易搞反，
# 一旦搞反不会报错，只会表现为"命令被接受但载具不动"。
#
# 位置控制（goto）要的是纯位置指令：位置字段生效，其余全部忽略。
#
#   X_IGNORE|Y_IGNORE|Z_IGNORE      = 1|2|4       = 7      ← 0，位置生效
#   VX_IGNORE|VY_IGNORE|VZ_IGNORE   = 8|16|32     = 56     ← 1，忽略速度
#   AX_IGNORE|AY_IGNORE|AZ_IGNORE   = 64|128|256  = 448    ← 1，忽略加速度
#   YAW_IGNORE|YAW_RATE_IGNORE      = 1024|2048   = 3072   ← 1，忽略偏航
#   ---------------------------------------------------------
#   合计                                  56+448+3072 = 3576
#
# **速度位必须是 1。** 若遗漏（掩码变成 3520），语义就从"使用位置"变成
# "使用速度"，而速度字段填的是 0,0,0 —— PX4 会理解为"以 0 速度飞行"即原地
# 悬停。实测症状：setpoint 流 10Hz 正常发出、PX4 接受 OFFBOARD、载具位置
# 一动不动、误差恒定不变、直到超时。
#
# 该值由单元测试逐位校验（见 tests/unit/test_mavlink_set_mode.py）。
POSITION_TARGET_TYPEMASK_IGNORE_ALL_BUT_POSITION = 3576

#: MAV_FRAME_LOCAL_NED：绝对位置，原点为载具自己的 EKF 原点
MAV_FRAME_LOCAL_NED = 1


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
        "timestamp": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
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
    tx_lock: threading.RLock = field(default_factory=threading.RLock)
    _connect_lock: threading.RLock = field(default_factory=threading.RLock)
    _mavutil: Any = None
    _heartbeat_lock: threading.RLock = field(default_factory=threading.RLock)
    _heartbeat_stop: threading.Event = field(default_factory=threading.Event)
    _heartbeat_thread: threading.Thread | None = None
    _rx_stop: threading.Event = field(default_factory=threading.Event)
    _rx_thread: threading.Thread | None = None
    _rx_condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )
    _rx_sequence: int = 0
    #: LOCAL_POSITION_NED 样本：(sequence, x_north, y_east, z_down, received_monotonic, received_timestamp)。
    #: 早期的实现只存了 z（起飞高度观测只需要垂直分量），但 goto 的位置到达判据
    #: 需要完整三维坐标，因此改为全量保留。
    _local_positions: list[tuple[int, float, float, float, float, str]] = field(default_factory=list)
    _armed_states: list[tuple[int, bool, float, str]] = field(default_factory=list)
    _landed_states: list[tuple[int, int, float, str]] = field(default_factory=list)
    _subscribers: dict[int, Callable[[Any], None]] = field(default_factory=dict)
    _next_subscriber_id: int = 1
    _ack_generations: dict[int, int] = field(default_factory=dict)
    _active_ack_waiters: dict[int, int] = field(default_factory=dict)
    _ack_mailbox: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: 最后一次收到的 HEARTBEAT 里的模式信息：(sequence, base_mode, custom_mode)。
    #: 只保留最新一条 —— 心跳可达 500Hz，堆队列会无界增长。模式确认只需要"当前值"。
    _last_heartbeat_mode: tuple[int, int, int] | None = None
    #: 会话起点，用于生成 SET_POSITION_TARGET 的 time_boot_ms。
    #: PX4 不强依赖该值，但按规范应单调递增。
    _session_started_monotonic: float = field(default_factory=time.monotonic)
    last_receive_error: str | None = None
    last_send_error: str | None = None
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
                self.last_send_error = None
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
            received_monotonic = time.monotonic()
            received_timestamp = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if kind == "HEARTBEAT":
                armed_flag = self._mavlink_const("MAV_MODE_FLAG_SAFETY_ARMED", 128)
                base_mode = int(getattr(message, "base_mode", 0) or 0)
                self._armed_states.append((sequence, bool(base_mode & armed_flag), received_monotonic, received_timestamp))
                if len(self._armed_states) > 1024:
                    del self._armed_states[:-512]
                # 记录当前模式，供 set_mode() 确认切换是否真正生效。
                # ACK 只表示"命令被接受"，不代表模式已经变了 —— 必须回头看心跳。
                self._last_heartbeat_mode = (
                    sequence,
                    base_mode,
                    int(getattr(message, "custom_mode", 0) or 0),
                )
            elif kind == "EXTENDED_SYS_STATE":
                self._landed_states.append(
                    (sequence, int(getattr(message, "landed_state", 0) or 0), received_monotonic, received_timestamp)
                )
                if len(self._landed_states) > 1024:
                    del self._landed_states[:-512]
            elif kind == "LOCAL_POSITION_NED":
                self._local_positions.append(
                    (
                        sequence,
                        float(getattr(message, "x", 0.0)),
                        float(getattr(message, "y", 0.0)),
                        float(getattr(message, "z", 0.0)),
                        received_monotonic,
                        received_timestamp,
                    )
                )
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

    def _send_gcs_heartbeat(self) -> None:
        mavlink = getattr(self._mavutil, "mavlink", None)
        mav_type = getattr(mavlink, "MAV_TYPE_GCS", 6)
        autopilot = getattr(mavlink, "MAV_AUTOPILOT_INVALID", 8)
        mode_flag = getattr(mavlink, "MAV_MODE_FLAG_CUSTOM_MODE_ENABLED", 1)
        state = getattr(mavlink, "MAV_STATE_ACTIVE", 4)
        with self.tx_lock:
            connection = self.connection
            if connection is None or not self.connected:
                raise RuntimeError("connection_required")
            connection.mav.heartbeat_send(
                mav_type,
                autopilot,
                0,
                0,
                state,
                mode_flag,
            )

    def start_gcs_heartbeat(
        self,
        *,
        period_s: float = 1.0,
        thread_name: str | None = None,
    ) -> bool:
        """Start the persistent per-session heartbeat owner idempotently."""
        with self._heartbeat_lock:
            if self.connection is None or not self.connected:
                raise RuntimeError("connection_required")
            if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
                return False
            self._heartbeat_stop.clear()
            self.last_send_error = None
            # Prove that the transport can send before reporting the vehicle
            # online. A startup send failure is therefore fail-closed.
            self._send_gcs_heartbeat()

            def _loop() -> None:
                while not self._heartbeat_stop.wait(max(period_s, 0.05)):
                    try:
                        self._send_gcs_heartbeat()
                    except Exception as exc:
                        self.last_send_error = f"{type(exc).__name__}: {exc}"
                        self.connected = False
                        break

            thread = threading.Thread(
                target=_loop,
                name=thread_name or f"px4-gcs-heartbeat-sysid-{self.target_system}",
                daemon=True,
            )
            thread.start()
            self._heartbeat_thread = thread
            return True

    def stop_gcs_heartbeat(self, *, join_timeout_s: float = 2.0) -> None:
        with self._heartbeat_lock:
            self._heartbeat_stop.set()
            thread = self._heartbeat_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=join_timeout_s)
            self._heartbeat_thread = None

    def heartbeat_thread_alive(self) -> bool:
        with self._heartbeat_lock:
            return self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()

    def close(self) -> None:
        self.stop_gcs_heartbeat()
        self.stop_receive_loop()
        with self.tx_lock:
            connection = self.connection
            close = getattr(connection, "close", None)
            if callable(close):
                close()
            self.connected = False
            self.connection = None
        with self._rx_condition:
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
        with self.tx_lock:
            connection = self.connection
            if connection is None or not self.connected:
                raise RuntimeError("connection_required")
            connection.mav.command_long_send(
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

    def request_landing_state_stream(self, *, rate_hz: float, timeout_s: float) -> dict[str, Any]:
        """Request EXTENDED_SYS_STATE on the already-owned vehicle session."""
        command = self._mavlink_const("MAV_CMD_SET_MESSAGE_INTERVAL", 511)
        msg_id = self._mavlink_const("MAVLINK_MSG_ID_EXTENDED_SYS_STATE", 245)
        interval_us = int(1_000_000 / max(rate_hz, 0.1))
        ack = self._send_and_wait_ack(
            command,
            [float(msg_id), float(interval_us), 0.0, 0.0, 0.0, 0.0, 0.0],
            timeout_s=timeout_s,
        )
        ack["command_name"] = "MAV_CMD_SET_MESSAGE_INTERVAL"
        ack["message_name"] = "EXTENDED_SYS_STATE"
        return ack

    def set_mode(
        self,
        *,
        main_mode: int,
        sub_mode: int = 0,
        timeout_s: float = 3.0,
        confirm_timeout_s: float = 3.0,
    ) -> dict[str, Any]:
        """切换 PX4 主飞行模式，并**确认它真的生效**。

        为什么不能只看 ACK：``MAV_CMD_DO_SET_MODE`` 的 ACK 只表示 PX4 接受了这条
        命令，不表示模式已经切换。PX4 可能因为当前状态（例如 OFFBOARD 缺少
        setpoint 流、或未解锁）而拒绝实际切换。因此这里在 ACK 之后再回看
        HEARTBEAT 里的 ``custom_mode``，只有观测到目标模式才算成功。

        Returns:
            含 ``ack``、``confirmed``、``observed_main_mode`` 的字典。

        Raises:
            RuntimeError: 连接未建立。
        """
        if self.connection is None:
            raise RuntimeError("connection_required")

        command = self._mavlink_const("MAV_CMD_DO_SET_MODE", 176)
        custom_enabled = self._mavlink_const("MAV_MODE_FLAG_CUSTOM_MODE_ENABLED", 1)

        with self.command_lock:
            self.start_receive_loop()
            generation = self._begin_ack_wait(command)
            self.send_command_long(
                command,
                [float(custom_enabled), float(main_mode), float(sub_mode), 0.0, 0.0, 0.0, 0.0],
            )
            ack = self.wait_command_ack(command, timeout_s=timeout_s, generation=generation)

        ack["command_name"] = "MAV_CMD_DO_SET_MODE"
        ack["requested_main_mode"] = int(main_mode)
        ack["requested_main_mode_name"] = PX4_MAIN_MODE_NAMES.get(int(main_mode), f"MAIN_{int(main_mode)}")

        confirmed, observed = self.wait_mode(
            main_mode=main_mode,
            timeout_s=confirm_timeout_s,
        )
        return {
            "ack": ack,
            "confirmed": bool(confirmed),
            "observed_main_mode": observed,
            "observed_main_mode_name": (
                None if observed is None else PX4_MAIN_MODE_NAMES.get(int(observed), f"MAIN_{int(observed)}")
            ),
        }

    @staticmethod
    def px4_main_mode_from_custom_mode(custom_mode: int | None) -> int | None:
        """从 PX4 HEARTBEAT 的 custom_mode 里取出主模式号。

        位布局来自 PX4 源码 ``src/modules/commander/px4_custom_mode.h``::

            union px4_custom_mode {
                struct {
                    uint16_t reserved;      // bit 0-15
                    uint8_t  main_mode;     // bit 16-23
                    uint8_t  sub_mode;      // bit 24-31
                };
                uint32_t data;
            };

        所以主模式是 ``(data >> 16) & 0xFF``。
        """
        if custom_mode is None:
            return None
        return (int(custom_mode) >> 16) & 0xFF

    def wait_mode(self, *, main_mode: int, timeout_s: float) -> tuple[bool, int | None]:
        """等待 HEARTBEAT 报告的目标主模式；返回 (是否确认, 观测到的主模式)。"""
        deadline = time.monotonic() + max(timeout_s, 0.1)
        observed: int | None = None
        while time.monotonic() < deadline:
            with self._rx_condition:
                latest = self._last_heartbeat_mode
            if latest is not None:
                observed = self.px4_main_mode_from_custom_mode(latest[2])
                if observed == int(main_mode):
                    return True, observed
            time.sleep(0.02)
        return False, observed

    def current_mode(self) -> dict[str, Any]:
        """返回最近一次 HEARTBEAT 观测到的模式（可能是 None，表示还没收到）。"""
        with self._rx_condition:
            latest = self._last_heartbeat_mode
        if latest is None:
            return {"sequence": None, "base_mode": None, "custom_mode": None, "main_mode": None}
        sequence, base_mode, custom_mode = latest
        main = self.px4_main_mode_from_custom_mode(custom_mode)
        return {
            "sequence": sequence,
            "base_mode": base_mode,
            "custom_mode": custom_mode,
            "main_mode": main,
            "main_mode_name": None if main is None else PX4_MAIN_MODE_NAMES.get(main, f"MAIN_{main}"),
        }

    def send_position_target(
        self,
        *,
        north_m: float,
        east_m: float,
        down_m: float,
        time_boot_ms: int | None = None,
    ) -> None:
        """发送一条本地位置 setpoint（``vehicle_local_ned``，原点为本机 EKF 原点）。

        ⚠️ 坐标语义：这里的 north/east/down 是**本机 local NED**，不是共享
        ``scene_ned``。调用方必须先做反向平移转换::

            vehicle_local_ned = scene_ned - translation_scene_ned_m

        该平移量由仿真标定测得，经 ``/api/coordinates/calibration`` 发布，
        Runtime 在 ``spatial.translation_scene_ned_m`` 中暴露。少这一步会把
        场景坐标当成本机坐标发出去，飞机将飞向完全错误的位置。

        可单次调用；但 OFFBOARD 模式要求持续流，单次发送不足以维持 ——
        真正的位置控制见 ``stream_position_target``。
        """
        with self.tx_lock:
            connection = self.connection
            if connection is None or not self.connected:
                raise RuntimeError("connection_required")
            if time_boot_ms is None:
                time_boot_ms = int((time.monotonic() - self._session_started_monotonic) * 1000) & 0xFFFFFFFF
            connection.mav.set_position_target_local_ned_send(
                int(time_boot_ms),
                self.target_system,
                self.target_component,
                MAV_FRAME_LOCAL_NED,
                POSITION_TARGET_TYPEMASK_IGNORE_ALL_BUT_POSITION,
                float(north_m),
                float(east_m),
                float(down_m),
                0.0,  # vx —— 被 type_mask 忽略
                0.0,  # vy —— 被 type_mask 忽略
                0.0,  # vz —— 被 type_mask 忽略
                0.0,  # afx
                0.0,  # afy
                0.0,  # afz
                0.0,  # yaw
                0.0,  # yaw_rate
            )

    def arm(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_COMPONENT_ARM_DISARM", 400)
        ack = self._send_and_wait_ack(command, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], timeout_s=timeout_s)
        ack["command_name"] = "MAV_CMD_COMPONENT_ARM_DISARM"
        return ack

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_TAKEOFF", 22)
        with self.command_lock:
            self.start_receive_loop()
            observation_cursor = self.observation_cursor()
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
        ack["observation_cursor"] = observation_cursor
        return ack

    def goto(
        self,
        *,
        north_m: float,
        east_m: float,
        down_m: float,
        tolerance_m: float = 1.0,
        hold_s: float = 1.0,
        timeout_s: float = 60.0,
        rate_hz: float = 10.0,
        restore_mode: int = PX4_CUSTOM_MAIN_MODE_POSCTL,
        cancel_event: threading.Event | None = None,
        preset_setpoints: int = 10,
        preset_interval_s: float = 0.05,
    ) -> dict[str, Any]:
        """飞到本机 local NED 的指定位置并稳定悬停，然后切回 restore_mode。

        ⚠️ 坐标语义：north/east/down 是**本机 vehicle_local_ned**。调用方若拿到的是
        共享 scene_ned 目标，必须先做反向平移::

            vehicle_local_ned = scene_ned - translation_scene_ned_m

        该平移量取自 Runtime 的 ``/api/vehicle-snapshot`` → ``spatial.translation_scene_ned_m``。

        安全性设计（OFFBOARD 的两个已知陷阱）
        ------------------------------------
        1. **setpoint 断流会让 PX4 退出 OFFBOARD。** PX4 在 OFFBOARD 下若约 0.5 秒
           收不到 setpoint 就会退出该模式（通常转 POSCTL/高度保持悬停，但行为
           取决于参数）。因此：
             * 流式循环本身就是 try 体，任何异常都会走 finally；
             * finally 里**必定**尝试切回 restore_mode，绝不把载具留在 OFFBOARD；
             * 流循环加锁，避免与命令通道并发写同一 socket。

        2. **必须先有 setpoint 再切 OFFBOARD。** PX4 要求进入 OFFBOARD 前已经收到
           过位置设定点，否则会拒绝切入。这里先以当前位置预发若干条（保持不动），
           再切模式并继续流式发送。

        Returns:
            含 ``mode_result``、``arrival``、``stream``、``restored`` 的证据字典。
        """
        if self.connection is None:
            raise RuntimeError("connection_required")

        target = (float(north_m), float(east_m), float(down_m))
        rate_hz = max(float(rate_hz), 1.0)
        period = 1.0 / rate_hz
        tolerance = max(float(tolerance_m), 0.0)

        # 起飞/悬停阶段维持 GCS 心跳：与现有 takeoff/land 路径一致。
        # 这也是本方法最后不主动停它的原因（见下方 finally 的说明）。
        self.start_gcs_heartbeat()

        stop_stream = threading.Event()
        stream_stats = {"setpoints": 0, "last_error": None, "errors": 0}
        mode_result: dict[str, Any] | None = None
        arrival: dict[str, Any] | None = None
        restored: dict[str, Any] | None = None
        cancelled = False
        # 先给初值：虽然目前所有分支都会赋值，但显式初始化可避免后续改动
        # 引入 UnboundLocalError（这类错误只在特定分支才暴露，很难查）。
        failure_reason: str | None = "not_attempted"

        def stream_loop() -> None:
            """10Hz 位置 setpoint 流。持有 tx_lock 整段，避免与命令通道交错。"""
            while not stop_stream.is_set():
                if cancel_event is not None and cancel_event.is_set():
                    return
                try:
                    # 传入显式 time_boot_ms=None 让 send_position_target 自行计算
                    self.send_position_target(
                        north_m=target[0], east_m=target[1], down_m=target[2]
                    )
                    stream_stats["setpoints"] += 1
                except Exception as exc:  # noqa: BLE001 - 流线程不能因单次失败退出
                    stream_stats["errors"] += 1
                    stream_stats["last_error"] = f"{type(exc).__name__}: {exc}"
                    return
                stop_stream.wait(period)

        try:
            # --- 1) 预置 setpoint（用当前位置），让 PX4 接受 OFFBOARD ---
            current = self.latest_local_position()
            if current is None:
                raise RuntimeError("local_position_required_before_goto")
            for _ in range(max(int(preset_setpoints), 1)):
                self.send_position_target(
                    north_m=current[0], east_m=current[1], down_m=current[2]
                )
                time.sleep(max(float(preset_interval_s), 0.0))

            # --- 2) 启动流，再切 OFFBOARD ---
            arrival_start_sequence = self.local_position_cursor()
            stream_thread = threading.Thread(
                target=stream_loop, name="mavlink-position-stream", daemon=True
            )
            stream_thread.start()
            time.sleep(0.05)  # 让流先跑起来，避免切模式后出现空档

            mode_result = self.set_mode(
                main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=3.0, confirm_timeout_s=3.0
            )
            if mode_result["confirmed"]:
                # --- 3) 等待到达 ---
                arrival = self.observe_arrival(
                    north_m=target[0], east_m=target[1], down_m=target[2],
                    tolerance_m=tolerance, hold_s=hold_s, timeout_s=timeout_s,
                    after_sequence=arrival_start_sequence, cancel_event=cancel_event,
                )
                cancelled = arrival.get("reason") == "cancelled"
                failure_reason = None if arrival.get("observed") else str(arrival.get("reason"))
            else:
                failure_reason = "offboard_not_confirmed"
        except Exception as exc:  # noqa: BLE001 - 任何异常都要走统一收敛
            failure_reason = f"goto_exception:{type(exc).__name__}:{exc}"
        finally:
            # --- 4) 无论成功、超时还是异常，都必须收敛 ---
            # 顺序很重要：先停流，再切回模式。反过来的话，切模式期间流仍在发
            # OFFBOARD setpoint，会把载具又拉回位置控制。
            stop_stream.set()
            try:
                restore_result = self.set_mode(
                    main_mode=restore_mode, timeout_s=3.0, confirm_timeout_s=3.0
                )
                restored = {
                    "restored": bool(restore_result["confirmed"]),
                    "main_mode": restore_mode,
                    "main_mode_name": PX4_MAIN_MODE_NAMES.get(restore_mode, str(restore_mode)),
                    "observed_main_mode": restore_result.get("observed_main_mode"),
                    "attempted": True,
                }
            except Exception as exc:  # noqa: BLE001
                restored = {
                    "restored": False,
                    "main_mode": restore_mode,
                    "attempted": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        # 返回值在 finally 之后构造 —— 否则 dict 会在 finally 执行前就被求值，
        # restored 永远是 None，调用方就拿不到"是否已切回安全模式"这个关键信息。
        return {
            "mode_result": mode_result,
            "arrival": arrival,
            "stream": dict(stream_stats),
            "restored": restored,
            "cancelled": cancelled,
            "failure_reason": failure_reason,
        }

    def latest_local_position(self) -> tuple[float, float, float] | None:
        """最近一次 LOCAL_POSITION_NED 的 (north, east, down)；还没收到则 None。"""
        with self._rx_condition:
            if not self._local_positions:
                return None
            _, x, y, z, _received, _timestamp = self._local_positions[-1]
        return (float(x), float(y), float(z))

    def land(self, *, timeout_s: float) -> dict[str, Any]:
        command = self._mavlink_const("MAV_CMD_NAV_LAND", 21)
        with self.command_lock:
            self.start_receive_loop()
            observation_cursor = self.observation_cursor()
            generation = self._begin_ack_wait(command)
            self.send_command_long(command, [0.0] * 7)
            ack = self.wait_command_ack(
                command,
                timeout_s=timeout_s,
                generation=generation,
            )
        ack["command_name"] = "MAV_CMD_NAV_LAND"
        ack["observation_cursor"] = observation_cursor
        return ack

    def observe_local_position_altitude(
        self,
        *,
        timeout_s: float,
        threshold_altitude_m: float | None = None,
        after_sequence: int | None = None,
        cancel_event: threading.Event | None = None,
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
                if cancel_event is not None and cancel_event.is_set():
                    break
                fresh = [
                    (sequence, z)
                    for sequence, _x, _y, z, _received, _timestamp in self._local_positions
                    if sequence > seen_sequence
                ]
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
            "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
        }

    def observe_takeoff_completion(
        self,
        *,
        timeout_s: float,
        target_altitude_m: float,
        tolerance_m: float,
        stable_duration_s: float,
        after_sequence: int,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Require fresh, in-tolerance LOCAL_POSITION_NED samples over a hold window."""
        if self.connection is None:
            raise RuntimeError("connection_required")
        self.start_receive_loop()
        deadline = time.monotonic() + max(timeout_s, 0.1)
        seen_sequence = int(after_sequence)
        samples: list[float] = []
        sample_timestamps: list[str] = []
        stable_since: float | None = None
        stable_sample_count = 0
        completed = False
        cancelled = False
        lower = float(target_altitude_m) - float(tolerance_m)
        upper = float(target_altitude_m) + float(tolerance_m)
        with self._rx_condition:
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                fresh = [row for row in self._local_positions if row[0] > seen_sequence]
                for sequence, _x, _y, z, received_at, received_timestamp in fresh:
                    seen_sequence = max(seen_sequence, sequence)
                    altitude = ned_down_z_to_altitude_m(z)
                    samples.append(altitude)
                    sample_timestamps.append(received_timestamp)
                    if lower <= altitude <= upper:
                        if stable_since is None:
                            stable_since = received_at
                            stable_sample_count = 1
                        else:
                            stable_sample_count += 1
                        if (
                            stable_sample_count >= 2
                            and received_at - stable_since >= max(stable_duration_s, 0.0)
                        ) or stable_duration_s <= 0:
                            completed = True
                            break
                    else:
                        stable_since = None
                        stable_sample_count = 0
                if completed:
                    break
                if not self.connected and self.last_receive_error:
                    break
                self._rx_condition.wait(timeout=max(min(deadline - time.monotonic(), 0.25), 0.01))
        return {
            "status": "cancelled" if cancelled else "succeeded" if completed else "timed_out",
            "observed": bool(samples),
            "sample_count": len(samples),
            "after_sequence": int(after_sequence),
            "last_sequence": seen_sequence,
            "target_altitude_m": float(target_altitude_m),
            "tolerance_m": float(tolerance_m),
            "stable_duration_ms": int(round(max(stable_duration_s, 0.0) * 1000)),
            "stable_sample_count": stable_sample_count,
            "first_altitude_m": round(samples[0], 3) if samples else None,
            "last_altitude_m": round(samples[-1], 3) if samples else None,
            "max_altitude_m": round(max(samples), 3) if samples else None,
            "first_sample_timestamp": sample_timestamps[0] if sample_timestamps else None,
            "last_sample_timestamp": sample_timestamps[-1] if sample_timestamps else None,
            "telemetry_state": "fresh" if samples else "unknown",
            "completion_reached": completed,
            "cancelled": cancelled,
        }

    def observe_landed_and_disarmed(
        self,
        *,
        timeout_s: float,
        after_sequence: int,
        freshness_window_s: float = 2.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Require fresh ON_GROUND and disarmed evidence after the LAND command cursor."""
        if self.connection is None:
            raise RuntimeError("connection_required")
        self.start_receive_loop()
        deadline = time.monotonic() + max(timeout_s, 0.1)
        seen_sequence = int(after_sequence)
        armed: bool | None = None
        armed_sequence: int | None = None
        landed_state: int | None = None
        landed_sequence: int | None = None
        armed_timestamp: str | None = None
        landed_timestamp: str | None = None
        armed_received_at: float | None = None
        landed_received_at: float | None = None
        cancelled = False
        on_ground = self._mavlink_const("MAV_LANDED_STATE_ON_GROUND", 1)
        with self._rx_condition:
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                for sequence, value, received_at, received_timestamp in self._armed_states:
                    if sequence > seen_sequence and (armed_sequence is None or sequence > armed_sequence):
                        armed = value
                        armed_sequence = sequence
                        armed_timestamp = received_timestamp
                        armed_received_at = received_at
                for sequence, value, received_at, received_timestamp in self._landed_states:
                    if sequence > seen_sequence and (landed_sequence is None or sequence > landed_sequence):
                        landed_state = value
                        landed_sequence = sequence
                        landed_timestamp = received_timestamp
                        landed_received_at = received_at
                newest = [value for value in (armed_sequence, landed_sequence) if value is not None]
                if newest:
                    seen_sequence = max(seen_sequence, *newest)
                now = time.monotonic()
                samples_fresh = (
                    armed_received_at is not None
                    and landed_received_at is not None
                    and now - armed_received_at <= max(freshness_window_s, 0.0)
                    and now - landed_received_at <= max(freshness_window_s, 0.0)
                )
                if armed is False and landed_state == on_ground and samples_fresh:
                    break
                if not self.connected and self.last_receive_error:
                    break
                self._rx_condition.wait(timeout=max(min(deadline - time.monotonic(), 0.25), 0.01))
        completed_at = time.monotonic()
        armed_age_ms = (
            max(0, int(round((completed_at - armed_received_at) * 1000)))
            if armed_received_at is not None
            else None
        )
        landed_age_ms = (
            max(0, int(round((completed_at - landed_received_at) * 1000)))
            if landed_received_at is not None
            else None
        )
        freshness_window_ms = int(round(max(freshness_window_s, 0.0) * 1000))
        samples_fresh = (
            armed_age_ms is not None
            and landed_age_ms is not None
            and armed_age_ms <= freshness_window_ms
            and landed_age_ms <= freshness_window_ms
        )
        complete = armed is False and landed_state == on_ground and samples_fresh
        evidence_count = int(armed is not None) + int(landed_state is not None)
        any_sample_stale = (
            (armed_age_ms is not None and armed_age_ms > freshness_window_ms)
            or (landed_age_ms is not None and landed_age_ms > freshness_window_ms)
        )
        evidence_state = (
            "fresh"
            if complete
            else "stale"
            if any_sample_stale
            else "incomplete"
            if evidence_count
            else "unknown"
        )
        return {
            "status": "cancelled" if cancelled else "succeeded" if complete else "timed_out",
            "after_sequence": int(after_sequence),
            "last_sequence": seen_sequence,
            "telemetry_state": evidence_state,
            "landed_state": landed_state,
            "landed_state_name": "on_ground" if landed_state == on_ground else "unknown" if landed_state is None else "not_on_ground",
            "landed_sequence": landed_sequence,
            "armed": armed,
            "armed_sequence": armed_sequence,
            "armed_sample_timestamp": armed_timestamp,
            "landed_sample_timestamp": landed_timestamp,
            "armed_sample_age_ms": armed_age_ms,
            "landed_sample_age_ms": landed_age_ms,
            "freshness_window_ms": freshness_window_ms,
            "completion_reached": complete,
            "cancelled": cancelled,
        }

    def observe_arrival(
        self,
        *,
        north_m: float,
        east_m: float,
        down_m: float,
        tolerance_m: float,
        hold_s: float,
        timeout_s: float,
        after_sequence: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """等待载具**持续**处在目标点容差内，返回到达证据。

        为什么要求"持续"而不是"某一刻在容差内"：载具在接近目标时会过冲并来回
        摆动，单次采样落在容差内不代表已经稳定悬停在目标点。要求连续 hold_s
        秒说明控制器已经收敛。

        只用**新增**的样本（sequence 大于起点），避免把飞向目标途中的旧位置
        误当成到达。
        """
        start_sequence = self.local_position_cursor() if after_sequence is None else int(after_sequence)
        deadline = time.monotonic() + max(timeout_s, 0.1)
        hold_s = max(float(hold_s), 0.0)
        tolerance = max(float(tolerance_m), 0.0)
        inside_since: float | None = None
        last_error: float | None = None
        samples = 0

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "observed": False, "reason": "cancelled", "samples": samples,
                    "last_error_m": last_error, "start_sequence": start_sequence,
                }
            with self._rx_condition:
                fresh = [row for row in self._local_positions if row[0] > start_sequence]
            if fresh:
                _, x, y, z, received_monotonic, _ = fresh[-1]
                samples = len(fresh)
                # 三维欧氏距离。三个分量都要算 —— 只比高度会把"高度对了但水平
                # 还差很远"误判为到达。
                error = math.sqrt(
                    (float(x) - float(north_m)) ** 2
                    + (float(y) - float(east_m)) ** 2
                    + (float(z) - float(down_m)) ** 2
                )
                last_error = error
                if error <= tolerance:
                    if inside_since is None:
                        inside_since = received_monotonic
                    elif received_monotonic - inside_since >= hold_s:
                        return {
                            "observed": True, "reason": "stable_within_tolerance",
                            "samples": samples, "last_error_m": error,
                            "hold_s": received_monotonic - inside_since,
                            "start_sequence": start_sequence,
                        }
                else:
                    inside_since = None
            if not self.connected and self.last_receive_error:
                return {
                    "observed": False, "reason": "receive_loop_failed", "samples": samples,
                    "last_error_m": last_error, "start_sequence": start_sequence,
                }
            time.sleep(0.02)

        return {
            "observed": False, "reason": "arrival_timeout", "samples": samples,
            "last_error_m": last_error, "start_sequence": start_sequence,
        }

    def local_position_cursor(self) -> int:
        """Return the RX sequence after which a new observation may consume samples."""
        with self._rx_condition:
            return self._rx_sequence

    def observation_cursor(self) -> int:
        """Return the per-session RX cursor used by all completion evidence."""
        with self._rx_condition:
            return self._rx_sequence
