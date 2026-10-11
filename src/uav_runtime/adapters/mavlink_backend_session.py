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


# --- PX4 AUTO 子模式 ------------------------------------------------------
#
# 同样是 PX4 自己的约定，MAVLink 公共枚举里没有。
# 源码：px4_custom_mode.h 的 enum PX4_CUSTOM_SUB_MODE_AUTO。
#
# **为什么必须区分主模式与子模式**：AUTO(4) 主模式下的子模式行为差异极大 ——
# MISSION 会飞航线、RTL 会爬升后自主返航并降落。它们都是 main_mode=4，
# 只看主模式会把"RTL 正在飞"误判成"稳定悬停"。实测踩过这个坑。
PX4_CUSTOM_SUB_MODE_AUTO_READY = 1
PX4_CUSTOM_SUB_MODE_AUTO_TAKEOFF = 2
PX4_CUSTOM_SUB_MODE_AUTO_LOITER = 3
PX4_CUSTOM_SUB_MODE_AUTO_MISSION = 4
PX4_CUSTOM_SUB_MODE_AUTO_RTL = 5
PX4_CUSTOM_SUB_MODE_AUTO_LAND = 6
PX4_CUSTOM_SUB_MODE_AUTO_FOLLOW_TARGET = 8

PX4_AUTO_SUB_MODE_NAMES = {
    PX4_CUSTOM_SUB_MODE_AUTO_READY: "AUTO_READY",
    PX4_CUSTOM_SUB_MODE_AUTO_TAKEOFF: "AUTO_TAKEOFF",
    PX4_CUSTOM_SUB_MODE_AUTO_LOITER: "AUTO_LOITER",
    PX4_CUSTOM_SUB_MODE_AUTO_MISSION: "AUTO_MISSION",
    PX4_CUSTOM_SUB_MODE_AUTO_RTL: "AUTO_RTL",
    PX4_CUSTOM_SUB_MODE_AUTO_LAND: "AUTO_LAND",
    PX4_CUSTOM_SUB_MODE_AUTO_FOLLOW_TARGET: "AUTO_FOLLOW_TARGET",
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


def classify_incomplete_evidence(action: str, evidence: dict[str, Any]) -> str | None:
    """把"超时但没完成"分类，让调用方能区分"接近过"与"没反应"。

    为什么需要这个
    --------------
    原先所有超时都报同一个原因码。实测中它把三种**完全不同**的情况混成了一种：

      · 350 m 航线没飞完 → `arrival_timeout`，但飞机在正常飞行、越来越近
      · RTL 后降落超时   → `landing_completion_timeout`，而飞机**已经落地**
      · 坠机后降落超时   → `landing_completion_timeout`，飞机坠了、永远等不到条件

    调用方只看 `result: fail` 会得出错误结论 —— 第一种该"再等等"，后两种该"出事了"。

    ⚠️ 判据刻意**不**是"数值还在不在变"
    ------------------------------------
    最初设想用"高度还在变 / 位置不再变"来区分。**实测证明那条判据不可靠**：
    "不再变化"无法区分"载具卡住"、"稳稳悬停等条件"、"遥测采样停了"三种情况，
    而且需要在观测循环里跨时间记录趋势。

    改用**观测循环本来就在记录的分量**，因此不需要猜"有没有在动"：

      partial_evidence      —— 至少一个完成条件是**可判定的**（该分量有新鲜样本）。
                               说明看到了部分满足，卡在中间。
      insufficient_evidence —— 完成条件**都没有可判定依据**（无样本、或样本陈旧）。
                               连"卡在哪"都无从判断。

    这个区分正好命中上面第 2、3 种：降落时 `landed_state == on_ground` 而
    `armed == true` 属 partial（落地了但没 disarm）；完全没有遥测则属 insufficient。

    Returns:
        分类字符串；若证据已显示完成、或动作类型不认识，返回 ``None``
        （表示"不该改原因码"）。
    """
    if not isinstance(evidence, dict):
        return None

    # 已完成的不该被归类 —— 调用方只在失败路径上调这个函数。
    if evidence.get("completion_reached") is True:
        return None
    # ⚠️ 刻意**不**检查 `observed`：在 observe_takeoff_completion 里它是
    # `bool(samples)` —— "有没有拿到样本"，**不是**"有没有完成"。
    # 最初把它当完成标志，结果所有"拿到样本但没满足条件"的失败都被跳过分类，
    # 分类函数在最需要它的场景下静默失效。这类字段同名不同义是很容易踩的。
    if evidence.get("held") is True or evidence.get("returning") is True:
        return None

    def has_number(key: str) -> bool:
        value = evidence.get(key)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    if action == "land":
        # 完成条件 = on_ground **且** disarmed，两者都要新鲜样本。
        #
        # ⚠️ 这里只把 "unknown" 当作无依据：
        # `telemetry_state == "incomplete"` 的含义是"**部分样本存在但不新鲜**"，
        # 那是**可判定**的情形（比如拿到了 landed_state 但没拿到 armed）——
        # 实测中坠机卡死报的正是 incomplete。最初把它也算作 insufficient，
        # 恰好废掉了最需要分类的那一次。
        telemetry_state = str(evidence.get("telemetry_state") or "")
        if telemetry_state == "unknown":
            return "insufficient_evidence"
        on_ground = evidence.get("landed_state") == 1
        disarmed = evidence.get("armed") is False
        if on_ground or disarmed:
            # 半个完成条件**成立** —— 这是可判定的。
            # `landed_state=on_ground` 即使来自陈旧样本，也真实说明"某个时刻曾在
            # 地面"，那是有效信息，不该被"陈旧"抹掉。
            return "partial_evidence"
        # 两个完成条件都不成立。再分两种，因为它们的**含义完全不同**：
        #   · 有读数但不满足（如飞控明确报 not_on_ground）→ 卡住，且不会自己好
        #   · 完全没有读数 → 无从判断
        #
        # ⚠️ 这一支最初被写成 `partial_evidence`（只要 `landed_state is not None`
        # 就算），那是错的：读数的**存在**不等于条件的**成立**。后果是坠机卡死
        # 与"正常降落中"拿到同一句话"这不代表降落失败"，而前者需要人工介入。
        has_reading = evidence.get("landed_state") is not None or evidence.get("armed") is not None
        if not has_reading:
            return "insufficient_evidence"
        if telemetry_state == "stale":
            # 陈旧读数说明的是"过去某时刻"，不能用来判断"现在卡在哪"。
            return "insufficient_evidence"
        # 有新鲜读数，且明确不在地面 —— 载具无法靠"再等等"完成降落。
        return "not_on_ground_after_land"

    if action == "takeoff":
        # 完成条件 = 高度进入容差并稳定保持。有高度样本就说明这一项可判定。
        if not has_number("last_altitude_m"):
            return "insufficient_evidence"
        lower = evidence.get("target_altitude_m")
        tolerance = evidence.get("tolerance_m")
        if has_number(lower) and has_number(tolerance):
            target = float(lower)
            band = float(tolerance)
            last = float(evidence["last_altitude_m"])
            if target - band <= last <= target + band:
                # 高度已在容差内，缺的只是"稳定保持"这一段时长。
                return "partial_evidence"
        # 高度有读数但没进容差：接近过没有？
        if has_number("max_altitude_m"):
            target = float(evidence.get("target_altitude_m") or 0.0)
            if float(evidence["max_altitude_m"]) >= target * 0.5:
                return "partial_evidence"
        return "partial_evidence" if evidence.get("sample_count") else "insufficient_evidence"

    if action == "goto":
        # 完成条件 = 三维误差持续落在容差内。有误差读数就说明这一项可判定。
        if not has_number("last_error_m") and not has_number("min_error_m"):
            return "insufficient_evidence"
        tolerance = evidence.get("target_error_m")
        if has_number("min_error_m") and has_number(tolerance):
            if float(evidence["min_error_m"]) <= float(tolerance) * 2.0:
                # 最近时已经很接近（两倍容差内），只是没能"持续"停在容差里。
                return "partial_evidence"
        return "partial_evidence" if evidence.get("samples") else "insufficient_evidence"

    if action in ("hold_position", "hold"):
        if not has_number("max_drift_m"):
            return "insufficient_evidence"
        tolerance = evidence.get("tolerance_m")
        if has_number(tolerance) and float(evidence["max_drift_m"]) <= float(tolerance):
            # 漂移在容差内，缺的只是"持续"这段时长。
            return "partial_evidence"
        return "partial_evidence" if evidence.get("samples") else "insufficient_evidence"

    if action == "return_home":
        # 完成条件 = 到 home 的距离收敛足够。距离有读数就说明这一项可判定。
        # 字段名用 final_distance_m —— 它是契约里对外暴露的名字（见
        # docs/algorithm_runtime_execution_contract_v0_1.md 3.1）。
        # 这里刻意**不**另造一个 last_distance_m：同一份证据有两个名字，
        # 迟早会有一处读错。
        if not has_number("final_distance_m") and not has_number("initial_distance_m"):
            return "insufficient_evidence"
        return "partial_evidence" if evidence.get("samples") else "insufficient_evidence"

    return None


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


PINNED_MODES: frozenset[tuple[int, int]] = frozenset({
    (PX4_CUSTOM_MAIN_MODE_POSCTL, 0),
    (PX4_CUSTOM_MAIN_MODE_ALTCTL, 0),
    (PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER),
})


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
    _home_position: dict[str, Any] | None = None
    _global_position: dict[str, Any] | None = None
    _last_position_boot_ms: int | None = None
    _position_epoch: int = 0
    _position_epoch_changed_timestamp: str | None = None
    _odometry_reset_counter: int | None = None
    _rtl_type_evidence: dict[str, Any] | None = None
    _rally_count_evidence: dict[str, Any] | None = None
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
    #: 最近一次完成度观测的证据字典。
    #:
    #: 存在的理由：超时后要判断"卡在哪"，而判断必须基于**产生该失败的那份证据**。
    #: 若事后另传一份参数来判断，就可能出现"判据与实际执行的不是同一份" ——
    #: 那样的分类会撒谎。因此观测循环把证据留在这里，分类只读它。
    _last_completion_evidence: dict[str, Any] = field(default_factory=dict)
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
                boot_ms = getattr(message, "time_boot_ms", None)
                if isinstance(boot_ms, int):
                    if self._last_position_boot_ms is not None and boot_ms < self._last_position_boot_ms:
                        self._position_epoch += 1
                        self._position_epoch_changed_timestamp = received_timestamp
                        self._home_position = None
                        self._global_position = None
                        self._local_positions.clear()
                        self._armed_states.clear()
                        self._landed_states.clear()
                        self._last_heartbeat_mode = None
                    self._last_position_boot_ms = boot_ms
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
            elif kind == "HOME_POSITION":
                self._home_position = {
                    "sequence": sequence, "received_monotonic": received_monotonic,
                    "sample_timestamp": received_timestamp, "position_epoch": self._position_epoch,
                    **{name: getattr(message, name, None) for name in ("x", "y", "z", "latitude", "longitude", "altitude")},
                }
            elif kind == "GLOBAL_POSITION_INT":
                self._global_position = {
                    "received_monotonic": received_monotonic,
                    "time_boot_ms": getattr(message, "time_boot_ms", None),
                    "lat": getattr(message, "lat", None), "lon": getattr(message, "lon", None),
                }
            elif kind == "PARAM_VALUE":
                param_id = getattr(message, "param_id", "")
                if isinstance(param_id, bytes):
                    param_id = param_id.decode("ascii", errors="replace")
                if isinstance(param_id, str) and param_id.rstrip("\x00") == "RTL_TYPE":
                    self._rtl_type_evidence = {
                        "sequence": sequence, "received_monotonic": received_monotonic,
                        "sample_timestamp": received_timestamp,
                        "param_id": "RTL_TYPE", "param_value": getattr(message, "param_value", None),
                        "param_type": getattr(message, "param_type", None),
                    }
            elif kind == "MISSION_COUNT" and getattr(message, "mission_type", None) == 2:
                mav = getattr(self.connection, "mav", None)
                if (getattr(message, "target_system", None) == getattr(mav, "srcSystem", 255)
                        and getattr(message, "target_component", None) == getattr(mav, "srcComponent", 0)):
                    self._rally_count_evidence = {
                        "sequence": sequence, "received_monotonic": received_monotonic,
                        "sample_timestamp": received_timestamp,
                        "mission_type": 2, "count": getattr(message, "count", None),
                    }
            elif kind == "ODOMETRY":
                counter = getattr(message, "reset_counter", None)
                if isinstance(counter, int):
                    if self._odometry_reset_counter is not None and counter != self._odometry_reset_counter:
                        self._position_epoch += 1
                        self._position_epoch_changed_timestamp = received_timestamp
                        self._home_position = None
                        self._global_position = None
                        self._local_positions.clear()
                    self._odometry_reset_counter = counter
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

    def autonomous_state(self) -> dict[str, Any]:
        """Current per-node stop evidence; absence/staleness never means stopped."""
        with self._rx_condition:
            now = time.monotonic()
            armed = self._armed_states[-1] if self._armed_states else None
            landed = self._landed_states[-1] if self._landed_states else None
            heartbeat_fresh = armed is not None and now - armed[2] <= 2.0
            landed_fresh = landed is not None and now - landed[2] <= 2.0
            mode = self._last_heartbeat_mode
            main = (mode[2] >> 16) & 0xff if mode else None
            sub = (mode[2] >> 24) & 0xff if mode else None
            stopped = bool(heartbeat_fresh and (
                (main, sub) in PINNED_MODES
                or (landed_fresh and armed[1] is False and landed[1] == 1)
            ))
            stop_sequence = (armed[0] if (main, sub) in PINNED_MODES else
                             min(armed[0], landed[0]) if armed and landed else None)
            return {"fresh": heartbeat_fresh, "landed_fresh": landed_fresh,
                    "active": False if stopped else True if heartbeat_fresh else None,
                    "stop_sequence": stop_sequence,
                    "mode": {"main_mode": main, "sub_mode": sub},
                    "armed": armed[1] if armed else None, "landed_state": landed[1] if landed else None}

    def request_home_position(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Request HOME through the sole RX owner and corroborate local XY with GPS.

        PX4 may encode invalid local home as zero. Zero is accepted only when a
        fresh, time-aligned global/local pair independently agrees with it.
        """
        cursor = self.local_position_cursor()
        epoch = self._position_epoch
        ack = self._send_and_wait_ack(512, [242.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], timeout_s=timeout_s)
        deadline = time.monotonic() + max(timeout_s, 0.1)
        reason = "home_position_unavailable"
        with self._rx_condition:
            while time.monotonic() < deadline:
                home = dict(self._home_position or {})
                global_pos = dict(self._global_position or {})
                local = self._local_positions[-1] if self._local_positions else None
                now = time.monotonic()
                if self._position_epoch != epoch:
                    return {"verified": False, "failure_reason": "home_reference_changed", "request_ack": ack}
                if home.get("sequence", -1) > cursor:
                    reason = "home_position_unverified"
                    numbers = [home.get(k) for k in ("x", "y", "latitude", "longitude")]
                    numbers += [global_pos.get("lat"), global_pos.get("lon")]
                    valid = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in numbers)
                    if (valid and local and all(math.isfinite(v) for v in local[1:4])
                            and home.get("position_epoch") == self._position_epoch
                            and now - home["received_monotonic"] <= 2.0
                            and now - global_pos["received_monotonic"] <= 2.0
                            and now - local[4] <= 2.0
                            and abs(global_pos["received_monotonic"] - local[4]) <= 0.25
                            and isinstance(global_pos.get("time_boot_ms"), int)
                            and self._last_position_boot_ms is not None
                            and abs(global_pos["time_boot_ms"] - self._last_position_boot_ms) <= 250
                            and abs(home["latitude"]) <= 900000000 and abs(global_pos["lat"]) <= 900000000
                            and abs(home["longitude"]) <= 1800000000 and abs(global_pos["lon"]) <= 1800000000):
                        lat = math.radians(global_pos["lat"] / 1e7)
                        north = local[1] + math.radians((home["latitude"] - global_pos["lat"]) / 1e7) * 6378137.0
                        east = local[2] + math.radians((home["longitude"] - global_pos["lon"]) / 1e7) * 6378137.0 * math.cos(lat)
                        error = math.hypot(north - home["x"], east - home["y"])
                        if error <= 2.0:
                            return {**home, "verified": True, "verification": "global_local_xy_crosscheck",
                                    "crosscheck_error_m": error, "request_ack": ack}
                self._rx_condition.wait(timeout=0.05)
        return {"verified": False, "failure_reason": reason, "request_ack": ack}

    def verify_home_rtl_destination(self, *, timeout_s: float = 3.0,
                                    cancel_event: threading.Event | None = None) -> dict[str, Any]:
        """Read-only configuration proof: RTL_TYPE=0 with no rally points.

        Other RTL modes can select a mission landing or rally destination.
        There is no assumed default, parameter write, or second receiver.
        """
        self.start_receive_loop()
        with self.command_lock:
            cursor = self.observation_cursor()
            epoch = self._position_epoch
            with self.tx_lock:
                self.connection.mav.param_request_read_send(self.target_system, self.target_component, b"RTL_TYPE", -1)
                self.connection.mav.mission_request_list_send(self.target_system, self.target_component, 2)
            deadline = time.monotonic() + max(float(timeout_s), 0.1)
            with self._rx_condition:
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        return {"verified": False, "failure_reason": "cancelled"}
                    if self._position_epoch != epoch:
                        return {"verified": False, "failure_reason": "home_reference_changed"}
                    param, rally = self._rtl_type_evidence, self._rally_count_evidence
                    if (param and rally and param["sequence"] > cursor and rally["sequence"] > cursor
                            and time.monotonic() - param["received_monotonic"] <= 2.0
                            and time.monotonic() - rally["received_monotonic"] <= 2.0):
                        value, count = param["param_value"], rally["count"]
                        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                                 and math.isfinite(value) and value == 0
                                 and isinstance(count, int) and not isinstance(count, bool) and count == 0)
                        if isinstance(count, int) and count == 0:
                            with self.tx_lock:
                                self.connection.mav.mission_ack_send(self.target_system, self.target_component, 0, 2)
                        return {"verified": valid, "rtl_type": dict(param), "rally_points": dict(rally),
                                "failure_reason": None if valid else "rtl_home_configuration_unsupported"}
                    self._rx_condition.wait(timeout=0.05)
        return {"verified": False, "failure_reason": "rtl_destination_unverified"}

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
            mode_cursor = self.observation_cursor()
            generation = self._begin_ack_wait(command)
            self.send_command_long(
                command,
                [float(custom_enabled), float(main_mode), float(sub_mode), 0.0, 0.0, 0.0, 0.0],
            )
            ack = self.wait_command_ack(command, timeout_s=timeout_s, generation=generation)

        ack["command_name"] = "MAV_CMD_DO_SET_MODE"
        ack["requested_main_mode"] = int(main_mode)
        ack["requested_main_mode_name"] = PX4_MAIN_MODE_NAMES.get(int(main_mode), f"MAIN_{int(main_mode)}")
        ack["requested_sub_mode"] = int(sub_mode)

        # AUTO 主模式必须连子模式一起确认：LOITER(3) 与 RTL(5) 的 main_mode 都是
        # AUTO(4)，只比主模式会把"正在返航"当成"稳定悬停"。
        match_sub = int(main_mode) == PX4_CUSTOM_MAIN_MODE_AUTO
        confirmed, observed_main, observed_sub = self.wait_mode(
            main_mode=main_mode,
            sub_mode=sub_mode,
            match_sub_mode=match_sub,
            timeout_s=confirm_timeout_s,
            after_sequence=mode_cursor,
        )
        if ack.get("timeout") or ack.get("result") != 0:
            confirmed = False
        observed_name = (
            None if observed_main is None
            else PX4_MAIN_MODE_NAMES.get(int(observed_main), f"MAIN_{int(observed_main)}")
        )
        if observed_main == PX4_CUSTOM_MAIN_MODE_AUTO and observed_sub is not None:
            observed_name = PX4_AUTO_SUB_MODE_NAMES.get(int(observed_sub), f"AUTO_SUB_{int(observed_sub)}")
        return {
            "ack": ack,
            "confirmed": bool(confirmed),
            "observed_main_mode": observed_main,
            "observed_sub_mode": observed_sub,
            "observed_main_mode_name": observed_name,
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

    @staticmethod
    def px4_sub_mode_from_custom_mode(custom_mode: int | None) -> int | None:
        """从 custom_mode 里取出子模式号（bit 24-31）。

        AUTO 主模式下必须看这个值：MISSION(4) 与 RTL(5) 的主模式都是 AUTO，
        只看主模式无法区分"在飞航线"和"稳定悬停"。
        """
        if custom_mode is None:
            return None
        return (int(custom_mode) >> 24) & 0xFF

    def wait_mode(
        self,
        *,
        main_mode: int,
        sub_mode: int = 0,
        match_sub_mode: bool = False,
        timeout_s: float,
        after_sequence: int | None = None,
    ) -> tuple[bool, int | None, int | None]:
        """等待 HEARTBEAT 报告的目标模式。

        Returns:
            ``(是否确认, 观测到的主模式, 观测到的子模式)``

        ``match_sub_mode=True`` 时要求主模式与子模式都相符。对 AUTO 主模式必须
        这样做 —— AUTO 下的子模式决定实际行为（LOITER 悬停 vs RTL 返航），
        只比主模式会把 RTL 误判成安全悬停。
        """
        deadline = time.monotonic() + max(timeout_s, 0.1)
        observed_main: int | None = None
        observed_sub: int | None = None
        while time.monotonic() < deadline:
            with self._rx_condition:
                latest = self._last_heartbeat_mode
                heartbeat_at = self._armed_states[-1][2] if self._armed_states else None
            if (latest is not None and (after_sequence is None or latest[0] > after_sequence)
                    and heartbeat_at is not None and time.monotonic() - heartbeat_at <= 2.0):
                observed_main = self.px4_main_mode_from_custom_mode(latest[2])
                observed_sub = self.px4_sub_mode_from_custom_mode(latest[2])
                if observed_main == int(main_mode):
                    if not match_sub_mode or observed_sub == int(sub_mode):
                        return True, observed_main, observed_sub
            time.sleep(0.02)
        return False, observed_main, observed_sub

    def current_mode(self) -> dict[str, Any]:
        """返回最近一次 HEARTBEAT 观测到的模式（可能是 None，表示还没收到）。"""
        with self._rx_condition:
            latest = self._last_heartbeat_mode
        if latest is None:
            return {"sequence": None, "base_mode": None, "custom_mode": None,
                    "main_mode": None, "sub_mode": None}
        sequence, base_mode, custom_mode = latest
        main = self.px4_main_mode_from_custom_mode(custom_mode)
        sub = self.px4_sub_mode_from_custom_mode(custom_mode)
        name = None if main is None else PX4_MAIN_MODE_NAMES.get(main, f"MAIN_{main}")
        if main == PX4_CUSTOM_MAIN_MODE_AUTO and sub is not None:
            name = PX4_AUTO_SUB_MODE_NAMES.get(sub, f"AUTO_SUB_{sub}")
        return {
            "sequence": sequence,
            "base_mode": base_mode,
            "custom_mode": custom_mode,
            "main_mode": main,
            "sub_mode": sub,
            "main_mode_name": name,
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
        # 收尾目标模式：AUTO + LOITER（自主定点悬停）。
        #
        # 为什么不用 POSCTL：停流后 PX4 自己也会退出 OFFBOARD，两条模式切换
        # 路径互相竞争，POSCTL 的切换经常拿不到确认（实测两次都如此）。
        # AUTO_LOITER 是既明确又稳定的悬停状态，且与 takeoff 收尾后载具所停的
        # 模式一致，因此作为默认值更可靠。
        #
        # 注意必须带子模式：AUTO 主模式下子模式决定行为，LOITER(3) 是悬停，
        # 而 RTL(5) 是自主返航。只给 main_mode=4 而 sub_mode=0 会让 PX4 落到
        # 未定义子模式（实测会变成 RTL 行为）。
        restore_mode: int = PX4_CUSTOM_MAIN_MODE_AUTO,
        restore_sub_mode: int = PX4_CUSTOM_SUB_MODE_AUTO_LOITER,
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
            # 顺序很重要：先停流，再切模式。反过来的话，切模式期间流仍在发
            # OFFBOARD setpoint，会把载具又拉回位置控制。
            stop_stream.set()
            try:
                restore_result = self.set_mode(
                    main_mode=restore_mode,
                    sub_mode=restore_sub_mode,
                    timeout_s=3.0,
                    confirm_timeout_s=3.0,
                )
                observed_main = restore_result.get("observed_main_mode")
                observed_sub = restore_result.get("observed_sub_mode")
                confirmed = bool(restore_result["confirmed"])

                # ⚠️ 这里**刻意不做**"任意非 OFFBOARD 就算安全"的宽松判定。
                #
                # 曾经这样做过，结果是错的：AUTO(4) 主模式下，LOITER(3) 是悬停，
                # 但 **RTL(5) 是自主返航**（会爬升、飞回原点、降落）。两者
                # main_mode 都是 4，只看主模式会把"正在返航"判成"稳定悬停"。
                # 实测踩过：goto 报 pass，随后载具自行爬升到 8.5 米飞回原点。
                #
                # 因此只接受两种情况：
                #   a) 目标模式被精确确认（含 AUTO 的子模式匹配）；
                #   b) 观测到的是**白名单内的自主悬停模式**且子模式正确。
                safe_fallback = (
                    not confirmed
                    and (observed_main, observed_sub) in PINNED_MODES
                )
                if safe_fallback:
                    confirmed = True

                restored = {
                    "restored": confirmed,
                    "main_mode": restore_mode,
                    "main_mode_name": PX4_MAIN_MODE_NAMES.get(restore_mode, str(restore_mode)),
                    "sub_mode": restore_sub_mode,
                    "observed_main_mode": observed_main,
                    "observed_sub_mode": observed_sub,
                    "observed_main_mode_name": restore_result.get("observed_main_mode_name"),
                    # 仍停在 OFFBOARD 是最危险的结果，必须显式标出
                    "still_in_offboard": observed_main == PX4_CUSTOM_MAIN_MODE_OFFBOARD,
                    "accepted_fallback": bool(safe_fallback),
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
            position_epoch = self._position_epoch
            generation = self._begin_ack_wait(command)
            self.send_command_long(command, [0.0] * 7)
            ack = self.wait_command_ack(
                command,
                timeout_s=timeout_s,
                generation=generation,
            )
        ack["command_name"] = "MAV_CMD_NAV_LAND"
        ack["observation_cursor"] = observation_cursor
        ack["position_epoch"] = position_epoch
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
        evidence = {
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
        # 留证据给 classify_incomplete：分类必须基于产生该结果的那份证据。
        self._record_completion_evidence(evidence)
        return evidence

    def classify_incomplete(self, action: str) -> str | None:
        """按动作类型，用本会话最近一次观测证据做"未完成"分类。

        观测循环返回的证据字典本身带有判据（目标值、容差、实际读数），因此这里
        不需要调用方额外拼装参数 —— 分类读的就是**产生该失败的那份证据**。

        这很重要：若另传一份参数来分类，就可能出现"判据与实际执行的不是同一份"，
        那样的分类会撒谎。所以本方法只按 ``self._last_completion_evidence`` 判断。

        Returns:
            分类字符串，或 ``None``（无证据 / 已完成 / 动作类型不认识）。

        ⚠️ "没有证据" 与 "证据不足" 是两件事：
        前者是**没观测过**（返回 None，不该凭空给分类），后者是观测过了、但读数
        不足以判断卡在哪（返回 ``insufficient_evidence``）。最初把两者混为一谈，
        于是任何没观测过的会话都会得到一个看起来合理的分类 —— 那是编出来的。
        """
        if not self._last_completion_evidence:
            return None
        return classify_incomplete_evidence(action, self._last_completion_evidence)

    def _record_completion_evidence(self, evidence: dict[str, Any]) -> None:
        """记录最近一次观测证据，供 ``classify_incomplete`` 使用。"""
        self._last_completion_evidence = dict(evidence) if isinstance(evidence, dict) else {}

    def observe_ground_landing(
        self, *, timeout_s: float, after_sequence: int,
        ground_reference: dict[str, Any], translation_scene_ned_m: dict[str, float],
        stable_duration_s: float = 0.5, max_sample_gap_s: float = 0.5,
        expected_position_epoch: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Confirm the stated scene plane, not merely contact with any surface."""
        self.start_receive_loop()
        deadline = time.monotonic() + max(timeout_s, 0.1)
        epoch = self._position_epoch if expected_position_epoch is None else expected_position_epoch
        seen = int(after_sequence)
        armed = landed = position = None
        armed_at = landed_at = last_position_at = stable_since = None
        armed_seq = landed_seq = position_seq = None
        position_stamp = armed_stamp = landed_stamp = None
        stable_samples = 0
        complete = False
        reason = "landing_completion_timeout"
        check: dict[str, Any] | None = None
        bounds = ground_reference["xy_bounds_m"]
        with self._rx_condition:
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    reason = "cancelled"
                    break
                if epoch != self._position_epoch:
                    reason = "local_origin_changed"
                    break
                events = [(row[0], "armed", row) for row in self._armed_states if row[0] > seen]
                events += [(row[0], "landed", row) for row in self._landed_states if row[0] > seen]
                events += [(row[0], "position", row) for row in self._local_positions if row[0] > seen]
                for sequence, kind, row in sorted(events):
                    seen = sequence
                    if kind == "armed":
                        armed_seq, armed, armed_at, armed_stamp = row
                        if armed:
                            stable_samples, stable_since = 0, None
                    elif kind == "landed":
                        landed_seq, landed, landed_at, landed_stamp = row
                        if landed != 1:
                            stable_samples, stable_since = 0, None
                    else:
                        position_seq, north, east, down, received, position_stamp = row
                        position = {"north": north, "east": east, "down": down}
                        scene = {axis: position[axis] + translation_scene_ned_m[axis] for axis in position}
                        finite = all(math.isfinite(v) for v in scene.values())
                        in_bounds = finite and (bounds["north_min_m"] <= scene["north"] <= bounds["north_max_m"]
                                               and bounds["east_min_m"] <= scene["east"] <= bounds["east_max_m"])
                        error = abs(scene["down"] - ground_reference["ground_down_m"]) if finite else None
                        on_plane = in_bounds and error <= 0.3
                        check = {"scene_position_ned_m": scene, "vertical_error_m": error,
                                 "in_reference_bounds": in_bounds, "on_scene_ground": on_plane,
                                 "ground_down_m": ground_reference["ground_down_m"], "vertical_tolerance_m": 0.3}
                        fresh_states = (armed_at is not None and landed_at is not None
                                        and 0 <= received - armed_at <= 2.0 and 0 <= received - landed_at <= 2.0)
                        if (last_position_at is None or received - last_position_at > max_sample_gap_s
                                or not on_plane or armed is not False or landed != 1 or not fresh_states):
                            stable_samples, stable_since = 0, None
                        if on_plane and armed is False and landed == 1 and fresh_states:
                            stable_since = received if stable_since is None else stable_since
                            stable_samples += 1
                        last_position_at = received
                now = time.monotonic()
                fresh = (armed_at is not None and landed_at is not None and last_position_at is not None
                         and now - armed_at <= 2.0 and now - landed_at <= 2.0
                         and now - last_position_at <= max_sample_gap_s)
                if not fresh:
                    stable_samples, stable_since = 0, None
                complete = bool(fresh and armed is False and landed == 1 and stable_samples >= 3
                                and stable_since is not None and last_position_at - stable_since >= stable_duration_s)
                if complete:
                    reason = "scene_ground_landed"
                    break
                self._rx_condition.wait(timeout=0.05)
        now = time.monotonic()
        physical = bool(armed is False and landed == 1 and armed_at is not None and landed_at is not None
                        and now - armed_at <= 2.0 and now - landed_at <= 2.0)
        if not complete and reason == "landing_completion_timeout" and physical:
            reason = "scene_ground_not_reached" if check and not check["on_scene_ground"] else "landing_ground_stability_timeout"
        evidence = {
            "status": "succeeded" if complete else "cancelled" if reason == "cancelled" else "timed_out",
            "telemetry_state": "fresh" if complete or physical else "incomplete" if armed_at or landed_at else "unknown",
            "after_sequence": after_sequence, "last_sequence": seen, "completion_reached": complete,
            "physical_landed_disarmed": physical, "landed_state": landed, "armed": armed,
            "landed_state_name": "on_ground" if landed == 1 else "unknown" if landed is None else "not_on_ground",
            "position_vehicle_local_ned_m": position, "position_sequence": position_seq,
            "position_sample_timestamp": position_stamp, "armed_sample_timestamp": armed_stamp,
            "landed_sample_timestamp": landed_stamp, "armed_sequence": armed_seq, "landed_sequence": landed_seq,
            "position_fresh": last_position_at is not None and now - last_position_at <= max_sample_gap_s,
            "ground_check": check, "ground_reference": ground_reference,
            "ground_stable_samples": stable_samples, "stable_duration_ms": int(stable_duration_s * 1000),
            "ground_stable_ms": int((last_position_at - stable_since) * 1000) if stable_since is not None else 0,
            "failure_reason": None if complete else reason, "cancelled": reason == "cancelled",
            "position_epoch": epoch,
        }
        self._record_completion_evidence(evidence)
        return evidence

    def observe_landed_and_disarmed(
        self,
        *,
        timeout_s: float,
        after_sequence: int,
        freshness_window_s: float = 2.0,
        require_local_position: bool = False,
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
        position: dict[str, float] | None = None
        position_sequence: int | None = None
        position_timestamp: str | None = None
        position_received_at: float | None = None
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
                for sequence, north, east, down, received_at, received_timestamp in self._local_positions:
                    if sequence > after_sequence and (position_sequence is None or sequence > position_sequence):
                        position = {"north": north, "east": east, "down": down}
                        position_sequence = sequence
                        position_timestamp = received_timestamp
                        position_received_at = received_at
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
                position_fresh = (
                    position_received_at is not None
                    and now - position_received_at <= max(freshness_window_s, 0.0)
                )
                position_after_landing = (
                    position_sequence is not None and armed_sequence is not None
                    and landed_sequence is not None
                    and position_sequence > max(armed_sequence, landed_sequence)
                )
                if (armed is False and landed_state == on_ground and samples_fresh
                        and (not require_local_position or (position_fresh and position_after_landing))):
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
        position_age_ms = (
            max(0, int(round((completed_at - position_received_at) * 1000)))
            if position_received_at is not None else None
        )
        freshness_window_ms = int(round(max(freshness_window_s, 0.0) * 1000))
        samples_fresh = (
            armed_age_ms is not None
            and landed_age_ms is not None
            and armed_age_ms <= freshness_window_ms
            and landed_age_ms <= freshness_window_ms
        )
        position_fresh = position_age_ms is not None and position_age_ms <= freshness_window_ms
        position_after_landing = (
            position_sequence is not None and armed_sequence is not None
            and landed_sequence is not None
            and position_sequence > max(armed_sequence, landed_sequence)
        )
        complete = (armed is False and landed_state == on_ground and samples_fresh
                    and (not require_local_position or (position_fresh and position_after_landing)))
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
        evidence = {
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
            "position_vehicle_local_ned_m": position,
            "position_sequence": position_sequence,
            "position_sample_timestamp": position_timestamp,
            "position_sample_age_ms": position_age_ms,
            "position_fresh": position_fresh,
            "position_after_landing": position_after_landing,
            "freshness_window_ms": freshness_window_ms,
            "completion_reached": complete,
            "cancelled": cancelled,
        }
        # 留证据给 classify_incomplete。降落尤其需要：实测中"落地了但没 disarm"
        # 与"坠机后永远等不到条件"原先报同一个原因码，调用方无法区分。
        self._record_completion_evidence(evidence)
        return evidence

    # --- hold_position（HOLD）与 return_home（RETURN_HOME）-----------------
    #
    # 这两个动作直接作用于飞行中的载具，因此判据必须是**位置行为**，
    # 不能是"命令发出去了"或"模式变了"。本项目已经因此出过事故：
    # 收尾阶段曾把"任意非 OFFBOARD 模式"当成安全悬停，于是接受了 AUTO_RTL ——
    # 飞机开始自主返航，而动作报 pass。
    #
    # 因此：
    #   * HOLD 要求位置在容差内**持续** hold_s 秒（模式对但飞机在飘 = 失败）
    #   * RETURN_HOME 要求到 home 的距离**确实缩小**（只切模式 = 失败）
    # 两者都只采信模式切换**之后**的新样本，避免把切换前的旧位置当证据。

    def hold_position(
        self,
        *,
        tolerance_m: float = 2.0,
        hold_s: float = 3.0,
        timeout_s: float = 20.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """让载具保持当前位置悬停，并**验证它真的没动**。

        实现上是切到 ``AUTO + LOITER``（PX4 的定点悬停），然后连续采样确认位置
        稳定。为什么不能只确认模式：模式切换成功只说明飞控接受了指令，不说明
        飞机停住了 —— 风、估计器漂移、控制器问题都可能让它在 LOITER 下缓慢移动。

        参考点与"持续"判据
        ------------------
        参考点 = **模式生效后的第一个新位置样本**，即切换那一刻载具所在处。
        随后要求它在容差内**连续**保持 ``hold_s`` 秒，期间任何一次出容差都重新计时。

        这里**刻意不设**"先等一会儿稳定"的阶段。最初写过 ``settle_s``：切换后先
        丢弃一段时间的样本再确立参考点。那是错的 —— 它等于把切换瞬间的位移
        **当作正常并接受**：实测中飞机从 30 m 漂到 60 m，而参考点被定在了 60 m，
        于是 ``max_drift_m`` 报 0.0、动作判成功。而那次漂移是真实发生的。

        "持续 hold_s 秒在容差内"这条判据本身就处理了过渡：若切换后载具还在动，
        它就进不了容差，计时不会开始。因此不需要、也不应该丢弃样本。

        Returns:
            含 ``held``、``reason``、``samples``、``max_drift_m``、``mode``、
            ``failure_reason`` 的证据字典。

        Raises:
            RuntimeError: 连接未建立。
        """
        if self.connection is None:
            raise RuntimeError("connection_required")

        tolerance = max(float(tolerance_m), 0.0)
        hold_s = max(float(hold_s), 0.0)

        self.start_gcs_heartbeat()

        mode_result = self.set_mode(
            main_mode=PX4_CUSTOM_MAIN_MODE_AUTO,
            sub_mode=PX4_CUSTOM_SUB_MODE_AUTO_LOITER,
        )
        mode_evidence = {
            "confirmed": bool(mode_result.get("confirmed")),
            "observed_main_mode": mode_result.get("observed_main_mode"),
            "observed_sub_mode": mode_result.get("observed_sub_mode"),
            "observed_main_mode_name": mode_result.get("observed_main_mode_name"),
        }
        if not mode_evidence["confirmed"]:
            # 连悬停模式都没进，谈"保持"没有意义。不得谎报成功。
            return {
                "held": False,
                "reason": "mode_not_confirmed",
                "samples": 0,
                "max_drift_m": None,
                "reference": None,
                "mode": mode_evidence,
                "failure_reason": "hold_mode_not_confirmed",
            }

        # 只采信模式切换**之后**的样本：切换前的旧位置不能作为新模式生效的证据。
        start_sequence = self.local_position_cursor()
        deadline = time.monotonic() + max(float(timeout_s), 0.1)

        reference: tuple[float, float, float] | None = None
        max_drift: float | None = None
        inside_since: float | None = None
        samples = 0

        def finish(evidence: dict[str, Any]) -> dict[str, Any]:
            """统一出口：先留证据，再返回。

            三条退出路径（取消 / 保持成功 / 超时）都必须留证据 —— 否则
            ``classify_incomplete`` 会读到**上一次动作**的旧证据，从而给出错误分类。
            这种"读到别的动作的证据"的错法是静默的，所以用单一出口结构避免它。
            """
            self._record_completion_evidence(evidence)
            return evidence

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return finish({
                    "held": False, "reason": "cancelled", "samples": samples,
                    "max_drift_m": max_drift, "reference": reference,
                    "tolerance_m": tolerance, "hold_s": hold_s,
                    "mode": mode_evidence, "failure_reason": "cancelled",
                })
            with self._rx_condition:
                fresh = [row for row in self._local_positions if row[0] > start_sequence]
            if fresh:
                _, x, y, z, received_monotonic, _ = fresh[-1]
                samples = len(fresh)
                if reference is None:
                    # 切换后第一个样本 = 切换那一刻的位置。**不跳过任何样本**：
                    # 跳过就等于接受那段位移（见文档字符串里的实测教训）。
                    reference = (float(x), float(y), float(z))
                    inside_since = received_monotonic
                    max_drift = 0.0
                else:
                    drift = math.sqrt(
                        (float(x) - reference[0]) ** 2
                        + (float(y) - reference[1]) ** 2
                        + (float(z) - reference[2]) ** 2
                    )
                    max_drift = drift if max_drift is None else max(max_drift, drift)
                    if drift <= tolerance:
                        if inside_since is None:
                            inside_since = received_monotonic
                        elif received_monotonic - inside_since >= hold_s:
                            return finish({
                                "held": True, "reason": "stable_within_tolerance",
                                "samples": samples, "max_drift_m": max_drift,
                                "reference": reference, "held_s": received_monotonic - inside_since,
                                "tolerance_m": tolerance, "hold_s": hold_s,
                                "mode": mode_evidence, "failure_reason": None,
                            })
                    else:
                        # 出容差就重新计时：要求的是"连续"在容差内，
                        # 不是"累计够久"。
                        inside_since = None
            time.sleep(0.02)

        return finish({
            "held": False,
            "reason": "hold_timeout",
            "samples": samples,
            "max_drift_m": max_drift,
            "reference": reference,
            # 容差随证据一起返回：分类要判断"漂移是否在容差内"，判据必须与
            # 实际执行的那一份是同一个值，不能事后另传。
            "tolerance_m": tolerance,
            "hold_s": hold_s,
            "mode": mode_evidence,
            "failure_reason": "hold_timeout",
        })

    def return_home(
        self,
        *,
        timeout_s: float = 60.0,
        min_progress_m: float = 5.0,
        home_local_north_m: float | None = None,
        home_local_east_m: float | None = None,
        home_tolerance_m: float = 0.75,
        stable_duration_s: float = 1.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Observe real PX4 HOME arrival; RTL progress is never completion.

        RTL remains autonomous after HTTP returns. Its configured destination
        can differ from home; that never satisfies this action's home goal.
        """
        if self.connection is None:
            raise RuntimeError("connection_required")
        if not all(math.isfinite(value) for value in (home_tolerance_m, stable_duration_s, timeout_s, min_progress_m)):
            raise ValueError("return_home_target_invalid")
        if any(value is not None and not math.isfinite(value) for value in (home_local_north_m, home_local_east_m)):
            raise ValueError("return_home_target_invalid")
        if home_tolerance_m <= 0 or stable_duration_s <= 0:
            raise ValueError("return_home_target_invalid")

        self.start_gcs_heartbeat()
        home = self.request_home_position(timeout_s=min(float(timeout_s), 3.0))
        if not home.get("verified"):
            return {"returning": False, "reason": "home_unavailable", "home_evidence": home,
                    "failure_reason": home.get("failure_reason", "home_position_unverified"),
                    "autonomous_execution_may_continue": False}
        if ((home_local_north_m is not None and abs(home_local_north_m - home["x"]) > 0.1)
                or (home_local_east_m is not None and abs(home_local_east_m - home["y"]) > 0.1)):
            return {"returning": False, "reason": "home_target_mismatch", "home_evidence": home,
                    "failure_reason": "home_target_mismatch", "autonomous_execution_may_continue": False}
        home_local_north_m, home_local_east_m = float(home["x"]), float(home["y"])
        # Cross-check uncertainty consumes the arrival tolerance; a 2 m
        # verification envelope must not manufacture a 0.75 m arrival claim.
        home_error = float(home.get("crosscheck_error_m", 0.0))
        if not math.isfinite(home_error) or home_error >= home_tolerance_m:
            return {"returning": False, "reason": "home_unverified", "home_evidence": home,
                    "failure_reason": "home_position_uncertainty_exceeds_tolerance",
                    "autonomous_execution_may_continue": False}
        effective_tolerance = home_tolerance_m - home_error
        epoch = self._position_epoch
        start_sequence = self.local_position_cursor()
        try:
            with self.command_lock:
                if cancel_event is not None and cancel_event.is_set():
                    return {"returning": False, "reason": "cancelled", "home_evidence": home,
                            "failure_reason": "cancelled", "autonomous_execution_may_continue": False}
                try:
                    destination = self.verify_home_rtl_destination(timeout_s=min(float(timeout_s), 3.0), cancel_event=cancel_event)
                except Exception as exc:
                    destination = {"verified": False, "failure_reason": "rtl_destination_unverified",
                                   "error_class": type(exc).__name__}
                if not destination.get("verified"):
                    return {"returning": False, "reason": "rtl_destination_unverified", "home_evidence": home,
                            "rtl_destination_evidence": destination, "failure_reason": destination.get("failure_reason"),
                            "autonomous_execution_may_continue": False}
                if (epoch != self._position_epoch or time.monotonic() - home.get("received_monotonic", time.monotonic()) > 2.0):
                    return {"returning": False, "reason": "home_reference_changed", "home_evidence": home,
                            "failure_reason": "home_reference_changed", "autonomous_execution_may_continue": False}
                # The configuration read can be cancelled by LAND too.
                if cancel_event is not None and cancel_event.is_set():
                    return {"returning": False, "reason": "cancelled", "failure_reason": "cancelled",
                            "home_evidence": home, "autonomous_execution_may_continue": False}
                start_sequence = self.local_position_cursor()
                mode_result = self.set_mode(
                    main_mode=PX4_CUSTOM_MAIN_MODE_AUTO,
                    sub_mode=PX4_CUSTOM_SUB_MODE_AUTO_RTL,
                )
        except Exception as exc:
            # A transport/confirmation exception does not retract a sent RTL.
            return {"returning": False, "reason": "mode_exception", "home_evidence": home,
                    "failure_reason": f"return_home_mode_exception:{type(exc).__name__}",
                    "autonomous_execution_after_sequence": start_sequence,
                    "autonomous_execution_may_continue": True}
        mode_evidence = {
            "ack": mode_result.get("ack"),
            "confirmed": bool(mode_result.get("confirmed")),
            "observed_main_mode": mode_result.get("observed_main_mode"),
            "observed_sub_mode": mode_result.get("observed_sub_mode"),
            "observed_main_mode_name": mode_result.get("observed_main_mode_name"),
        }
        if not mode_evidence["confirmed"]:
            return {
                "returning": False,
                "reason": "mode_not_confirmed",
                "initial_distance_m": None,
                "final_distance_m": None,
                "distance_reduction_m": None,
                "samples": 0,
                "mode": mode_evidence,
                "home_evidence": home,
                "rtl_destination_evidence": destination,
                "autonomous_execution_may_continue": True,
                "autonomous_execution_after_sequence": start_sequence,
                "failure_reason": "return_home_mode_not_confirmed",
            }

        # The PX4 EKF origin is not assumed to be the physical home pad.
        deadline = time.monotonic() + max(float(timeout_s), 0.1)

        first_distance: float | None = None
        max_distance: float | None = None
        last_distance: float | None = None
        last_down: float | None = None
        samples = 0
        arrival_started_at: float | None = None
        arrival_samples = 0
        last_sample_sequence = start_sequence
        last_sample_at: float | None = None

        def finish(evidence: dict[str, Any]) -> dict[str, Any]:
            """统一出口：先留证据，再返回（理由同 hold_position.finish）。"""
            evidence["home_evidence"] = home
            evidence["rtl_destination_evidence"] = destination
            stop = self.autonomous_state()
            evidence["autonomous_execution_may_continue"] = not (
                stop.get("active") is False and isinstance(stop.get("stop_sequence"), int)
                and stop["stop_sequence"] > start_sequence
            )
            evidence["autonomous_execution_after_sequence"] = start_sequence
            evidence["completion_goal"] = "px4_home_horizontal_arrival"
            self._record_completion_evidence(evidence)
            return evidence

        while time.monotonic() < deadline:
            if epoch != self._position_epoch or (self._home_position and (
                    self._home_position.get("x") != home["x"] or self._home_position.get("y") != home["y"]
                    or self._home_position.get("latitude") != home["latitude"]
                    or self._home_position.get("longitude") != home["longitude"])):
                return finish({"returning": False, "reason": "home_reference_changed",
                               "failure_reason": "home_reference_changed", "samples": samples})
            if cancel_event is not None and cancel_event.is_set():
                return finish({
                    "returning": False, "reason": "cancelled", "samples": samples,
                    "initial_distance_m": first_distance, "final_distance_m": last_distance,
                    "distance_reduction_m": None, "mode": mode_evidence,
                    "failure_reason": "cancelled",
                })
            with self._rx_condition:
                fresh = [row for row in self._local_positions if row[0] > last_sample_sequence]
            for sequence, x, y, z, received_at, _ in fresh:
                samples += 1
                distance = math.hypot(float(x) - home_local_north_m, float(y) - home_local_east_m)
                last_down = float(z)
                if first_distance is None:
                    first_distance = distance
                    max_distance = distance
                max_distance = max(max_distance or distance, distance)
                last_distance = distance
                if sequence > last_sample_sequence:
                    last_sample_sequence = sequence
                    if last_sample_at is not None and received_at - last_sample_at > 0.5:
                        arrival_started_at, arrival_samples = None, 0
                    last_sample_at = received_at
                    if math.isfinite(distance) and distance <= effective_tolerance and time.monotonic() - received_at <= 0.5:
                        if arrival_started_at is None:
                            arrival_started_at = received_at
                        arrival_samples += 1
                    else:
                        arrival_started_at = None
                        arrival_samples = 0
            if last_sample_at is not None and time.monotonic() - last_sample_at > 0.5:
                arrival_started_at, arrival_samples = None, 0
            if (arrival_started_at is not None and arrival_samples >= 3
                        and last_sample_at - arrival_started_at >= stable_duration_s
                        and time.monotonic() - last_sample_at <= 0.5):
                    return finish({
                        "returning": False, "reason": "arrived_at_home",
                        "samples": samples,
                        "initial_distance_m": first_distance,
                        "max_distance_m": max_distance,
                        "final_distance_m": distance,
                        "distance_reduction_m": max_distance - distance,
                        "min_progress_m": float(min_progress_m),
                        "last_down_m": last_down,
                        "arrival_samples": arrival_samples,
                        "home_tolerance_m": home_tolerance_m,
                        "effective_home_tolerance_m": effective_tolerance,
                        "stable_duration_s": stable_duration_s,
                        "mode": mode_evidence,
                        "failure_reason": None,
                    })
            time.sleep(0.05)

        progressed = (max_distance is not None and last_distance is not None
                      and max_distance - last_distance >= max(float(min_progress_m), 0.0))
        return finish({
            "returning": bool(progressed),
            "reason": "in_progress" if progressed else "no_convergence",
            "samples": samples,
            "initial_distance_m": first_distance,
            "max_distance_m": max_distance,
            "final_distance_m": last_distance,
            "distance_reduction_m": (
                None if (max_distance is None or last_distance is None)
                else max_distance - last_distance
            ),
            # 收敛要求随证据一起返回：分类要判断"是否接近过"，判据必须与
            # 实际执行的那一份是同一个值。
            "min_progress_m": float(min_progress_m),
            "last_down_m": last_down,
            "arrival_samples": arrival_samples,
            "home_tolerance_m": home_tolerance_m,
            "effective_home_tolerance_m": effective_tolerance,
            "stable_duration_s": stable_duration_s,
            "mode": mode_evidence,
            "failure_reason": "return_home_in_progress" if progressed else "return_home_not_converging",
        })

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
        # 最小误差用于超时后的判读：它区分"接近过但没进容差"与"根本没靠近"。
        # 只看 last_error_m 会把"曾经飞到目标附近又飘走"误报成"从没靠近"。
        min_error: float | None = None
        samples = 0

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "observed": False, "reason": "cancelled", "samples": samples,
                    "last_error_m": last_error, "min_error_m": min_error,
                    "target_error_m": tolerance, "start_sequence": start_sequence,
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
                min_error = error if min_error is None else min(min_error, error)
                if error <= tolerance:
                    if inside_since is None:
                        inside_since = received_monotonic
                    elif received_monotonic - inside_since >= hold_s:
                        return {
                            "observed": True, "reason": "stable_within_tolerance",
                            "samples": samples, "last_error_m": error,
                            "min_error_m": min_error, "target_error_m": tolerance,
                            "hold_s": received_monotonic - inside_since,
                            "start_sequence": start_sequence,
                        }
                else:
                    inside_since = None
            if not self.connected and self.last_receive_error:
                failed = {
                    "observed": False, "reason": "receive_loop_failed", "samples": samples,
                    "last_error_m": last_error, "min_error_m": min_error,
                    "target_error_m": tolerance, "start_sequence": start_sequence,
                }
                self._record_completion_evidence(failed)
                return failed
            time.sleep(0.02)

        timed_out = {
            "observed": False, "reason": "arrival_timeout", "samples": samples,
            "last_error_m": last_error, "min_error_m": min_error,
            "target_error_m": tolerance, "start_sequence": start_sequence,
        }
        # 留证据给 classify_incomplete —— 与 hold_position / return_home 一致。
        self._record_completion_evidence(timed_out)
        return timed_out

    def local_position_cursor(self) -> int:
        """Return the RX sequence after which a new observation may consume samples."""
        with self._rx_condition:
            return self._rx_sequence

    def observation_cursor(self) -> int:
        """Return the per-session RX cursor used by all completion evidence."""
        with self._rx_condition:
            return self._rx_sequence
