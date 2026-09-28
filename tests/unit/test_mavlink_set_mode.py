"""PX4 飞行模式切换与确认的单元测试。

覆盖 mavlink_backend_session.set_mode() / wait_mode() / current_mode()。
这些方法是 goto（OFFBOARD 位置控制）的前置：进不了 OFFBOARD 就谈不上 goto。

重点验证的是"**不只看 ACK**"这个设计：PX4 可能接受命令但不真的切模式，
所以必须回看 HEARTBEAT 里的 custom_mode。
"""
from __future__ import annotations

import threading
import time
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import (
    PX4_CUSTOM_MAIN_MODE_AUTO,
    PX4_CUSTOM_MAIN_MODE_OFFBOARD,
    PX4_CUSTOM_MAIN_MODE_POSCTL,
    MavlinkBackendSession,
)

DO_SET_MODE = 176


# --- 测试替身 -------------------------------------------------------------


class _FakeMav:
    def __init__(self) -> None:
        self.commands: list[tuple[int, tuple[float, ...]]] = []
        self.heartbeats = 0

    def heartbeat_send(self, *args) -> None:
        self.heartbeats += 1

    def command_long_send(self, target_system, target_component, command, confirmation, *params) -> None:
        self.commands.append((int(command), tuple(float(p) for p in params)))


class _FakeConnection:
    target_system = 1
    target_component = 1

    def __init__(self) -> None:
        self.mav = _FakeMav()

    def recv_match(self, *args, **kwargs) -> Any:
        """接收循环会真的起线程调用这个方法。

        若不提供，线程会抛 AttributeError，而接收循环的异常处理会
        **把 session.connected 置为 False**，后续发送即报 connection_required。
        这里返回 None 表示"暂时没有消息"，让循环安静地空转。
        """
        time.sleep(0.01)
        return None

    def close(self) -> None:
        return None


class _FakeHeartbeat:
    """最小 HEARTBEAT 替身。"""

    def __init__(self, *, custom_mode: int, base_mode: int = 0) -> None:
        self.custom_mode = custom_mode
        self.base_mode = base_mode

    def get_type(self) -> str:
        return "HEARTBEAT"


class _FakeAck:
    def __init__(self, command: int, result: int = 0) -> None:
        self.command = command
        self.result = result

    def get_type(self) -> str:
        return "COMMAND_ACK"


def make_session() -> MavlinkBackendSession:
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint="udpin:127.0.0.1:14540",
            target_system=1,
            target_component=1,
        )
    )
    session.connection = _FakeConnection()
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()
    return session


def pack_mode(main: int, sub: int = 0) -> int:
    """按 PX4 的位布局打包 custom_mode。"""
    return ((sub & 0xFF) << 24) | ((main & 0xFF) << 16)


def feed_heartbeat(session: MavlinkBackendSession, *, main: int, sub: int = 0, base_mode: int = 0) -> None:
    session.dispatch_message(_FakeHeartbeat(custom_mode=pack_mode(main, sub), base_mode=base_mode))


# --- current_mode / 位提取 -------------------------------------------------


def test_current_mode_is_empty_before_any_heartbeat() -> None:
    session = make_session()
    mode = session.current_mode()
    assert mode["sequence"] is None
    assert mode["custom_mode"] is None
    assert mode["main_mode"] is None


def test_current_mode_reads_main_mode_from_custom_mode() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
    mode = session.current_mode()
    assert mode["main_mode"] == PX4_CUSTOM_MAIN_MODE_OFFBOARD
    assert mode["main_mode_name"] == "OFFBOARD"


def test_sub_mode_and_reserved_bits_do_not_corrupt_main_mode() -> None:
    """子模式（bit 24-31）与保留位（bit 0-15）都不能污染主模式。"""
    session = make_session()
    # AUTO + MISSION(4)，并把保留位全部置 1
    session.dispatch_message(_FakeHeartbeat(custom_mode=pack_mode(PX4_CUSTOM_MAIN_MODE_AUTO, 4) | 0xFFFF))
    assert session.current_mode()["main_mode"] == PX4_CUSTOM_MAIN_MODE_AUTO


# --- set_mode 命令格式 -----------------------------------------------------


def test_set_mode_sends_do_set_mode_with_custom_mode_enabled() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
    session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=0.2, confirm_timeout_s=0.5)

    sent = session.connection.mav.commands
    assert len(sent) == 1
    command, params = sent[0]
    assert command == DO_SET_MODE
    assert params[0] == 1.0, "param1 必须是 MAV_MODE_FLAG_CUSTOM_MODE_ENABLED"
    assert params[1] == float(PX4_CUSTOM_MAIN_MODE_OFFBOARD), "param2 是主模式"
    assert params[2] == 0.0, "param3 是子模式，默认 0"
    assert len(params) == 7


def test_set_mode_reports_ack_metadata() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
    result = session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=0.2, confirm_timeout_s=0.5)

    assert result["ack"]["command"] == DO_SET_MODE
    assert result["ack"]["command_name"] == "MAV_CMD_DO_SET_MODE"
    assert result["ack"]["requested_main_mode"] == PX4_CUSTOM_MAIN_MODE_OFFBOARD
    assert result["ack"]["requested_main_mode_name"] == "OFFBOARD"


# --- 核心：必须确认模式真的变了 -------------------------------------------


def test_set_mode_confirms_when_heartbeat_reports_target_mode() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_POSCTL)

    acked = threading.Event()

    def ack_then_switch() -> None:
        # 等到命令发出后，模拟 PX4 的 ACK 与随后的模式切换
        deadline = time.monotonic() + 1.0
        while not session.connection.mav.commands and time.monotonic() < deadline:
            time.sleep(0.005)
        session.dispatch_message(_FakeAck(DO_SET_MODE, 0))
        time.sleep(0.02)
        feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
        acked.set()

    worker = threading.Thread(target=ack_then_switch)
    worker.start()
    result = session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=1.0, confirm_timeout_s=1.0)
    worker.join(timeout=2.0)

    assert acked.is_set()
    assert result["ack"]["result_name"] == "MAV_RESULT_ACCEPTED"
    assert result["confirmed"] is True, "心跳报告了目标模式，应判定为已确认"
    assert result["observed_main_mode"] == PX4_CUSTOM_MAIN_MODE_OFFBOARD
    assert result["observed_main_mode_name"] == "OFFBOARD"


def test_set_mode_not_confirmed_when_mode_never_changes() -> None:
    """ACK 接受了，但模式始终没变 —— 必须报 confirmed=False。

    这正是"只看 ACK 就会误判"的场景：PX4 可能因为缺少 setpoint 流
    而拒绝真正进入 OFFBOARD。
    """
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_POSCTL)

    def ack_only() -> None:
        deadline = time.monotonic() + 1.0
        while not session.connection.mav.commands and time.monotonic() < deadline:
            time.sleep(0.005)
        session.dispatch_message(_FakeAck(DO_SET_MODE, 0))
        # 之后继续报 POSCTL，绝不切到 OFFBOARD
        for _ in range(20):
            feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_POSCTL)
            time.sleep(0.02)

    worker = threading.Thread(target=ack_only)
    worker.start()
    result = session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=1.0, confirm_timeout_s=0.3)
    worker.join(timeout=2.0)

    assert result["ack"]["result_name"] == "MAV_RESULT_ACCEPTED", "ACK 本身是成功的"
    assert result["confirmed"] is False, "模式没变，不能算成功"
    assert result["observed_main_mode"] == PX4_CUSTOM_MAIN_MODE_POSCTL


def test_set_mode_not_confirmed_when_no_heartbeat_arrives() -> None:
    session = make_session()

    def ack_only() -> None:
        deadline = time.monotonic() + 1.0
        while not session.connection.mav.commands and time.monotonic() < deadline:
            time.sleep(0.005)
        session.dispatch_message(_FakeAck(DO_SET_MODE, 0))

    worker = threading.Thread(target=ack_only)
    worker.start()
    result = session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=1.0, confirm_timeout_s=0.2)
    worker.join(timeout=2.0)

    assert result["confirmed"] is False
    assert result["observed_main_mode"] is None


# --- wait_mode 单独行为 ----------------------------------------------------


def test_wait_mode_returns_immediately_when_already_in_target_mode() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
    started = time.monotonic()
    confirmed, observed = session.wait_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=1.0)
    elapsed = time.monotonic() - started
    assert confirmed is True
    assert observed == PX4_CUSTOM_MAIN_MODE_OFFBOARD
    assert elapsed < 0.5, "已达目标模式时不应等满超时"


def test_wait_mode_times_out_and_reports_last_observed() -> None:
    session = make_session()
    feed_heartbeat(session, main=PX4_CUSTOM_MAIN_MODE_POSCTL)
    confirmed, observed = session.wait_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD, timeout_s=0.15)
    assert confirmed is False
    assert observed == PX4_CUSTOM_MAIN_MODE_POSCTL, "超时也要报告最后观测到的模式，便于排障"


def test_set_mode_requires_connection() -> None:
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    )
    try:
        session.set_mode(main_mode=PX4_CUSTOM_MAIN_MODE_OFFBOARD)
    except RuntimeError as exc:
        assert "connection_required" in str(exc)
    else:
        raise AssertionError("未连接时应抛 RuntimeError")


# --- send_position_target 单次 setpoint -----------------------------------


class _RecordingMav(_FakeMav):
    """额外记录 set_position_target_local_ned_send 的调用参数。"""

    def __init__(self) -> None:
        super().__init__()
        self.position_targets: list[tuple[float, ...]] = []

    def set_position_target_local_ned_send(self, *args) -> None:
        self.position_targets.append(tuple(args))


def make_session_with_recorder() -> MavlinkBackendSession:
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint="udpin:127.0.0.1:14540",
            target_system=1,
            target_component=1,
        )
    )
    connection = _FakeConnection()
    connection.mav = _RecordingMav()
    session.connection = connection
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": _RecordingMav()})()
    return session


def test_type_mask_ignores_everything_except_position() -> None:
    """逐位校验 type_mask。

    这个掩码我先后搞错过两次（3527 <-> 3576），而且**写错不会报错**：
    只会表现为"OFFBOARD 被接受、setpoint 正常发出、但载具一动不动，
    直到超时"。所以必须逐位断言，而不是只比对总数。

    语义关键：置 1 = **忽略**该字段。
    位置要生效 -> 位置位为 0；速度/加速度/偏航不要 -> 对应位为 1。
    """
    from uav_runtime.adapters.mavlink_backend_session import (
        POSITION_TARGET_TYPEMASK_IGNORE_ALL_BUT_POSITION as MASK,
    )

    # 必须置 0：位置三轴要生效
    for name, bit in (("X", 1), ("Y", 2), ("Z", 4)):
        assert not MASK & bit, f"{name}({bit}) 必须为 0，否则位置不生效"

    # 必须置 1：速度三轴要忽略。
    # 这是最关键的三个位 —— 漏掉它们会让指令退化为"以 0 速度飞行"（原地悬停）。
    for name, bit in (("VX", 8), ("VY", 16), ("VZ", 32)):
        assert MASK & bit, f"{name}({bit}) 必须为 1，否则退化成速度控制（0 速度=不动）"

    # 必须置 1：加速度与偏航同样忽略
    for name, bit in (
        ("AX", 64), ("AY", 128), ("AZ", 256),
        ("YAW", 1024), ("YAW_RATE", 2048),
    ):
        assert MASK & bit, f"{name}({bit}) 必须为 1"

    # 56(速度) + 448(加速度) + 3072(偏航) = 3576
    assert MASK == 3576, f"掩码应为 3576，实际 {MASK}"
    # bit 48 属于 DO_REPOSITION 的 CHANGE_MODE 语义，与 SET_POSITION_TARGET 无关
    assert not MASK & (1 << 48)


def test_send_position_target_uses_local_ned_frame_and_exact_position() -> None:
    session = make_session_with_recorder()
    session.send_position_target(north_m=1.5, east_m=-2.25, down_m=-3.0)

    sent = session.connection.mav.position_targets
    assert len(sent) == 1
    (
        time_boot_ms, target_system, target_component,
        coordinate_frame, type_mask,
        north, east, down,
        vx, vy, vz, afx, afy, afz, yaw, yaw_rate,
    ) = sent[0]

    assert target_system == 1
    assert target_component == 1
    assert coordinate_frame == 1, "必须是 MAV_FRAME_LOCAL_NED"
    assert type_mask == 3576
    assert (north, east, down) == (1.5, -2.25, -3.0), "位置必须原样送达，不得做任何换算"
    assert (vx, vy, vz) == (0.0, 0.0, 0.0)
    assert (afx, afy, afz) == (0.0, 0.0, 0.0)
    assert (yaw, yaw_rate) == (0.0, 0.0)
    assert isinstance(time_boot_ms, int) and time_boot_ms >= 0


def test_send_position_target_time_boot_ms_is_monotonic() -> None:
    session = make_session_with_recorder()
    session.send_position_target(north_m=0.0, east_m=0.0, down_m=-3.0)
    time.sleep(0.02)
    session.send_position_target(north_m=0.1, east_m=0.0, down_m=-3.0)

    stamps = [row[0] for row in session.connection.mav.position_targets]
    assert len(stamps) == 2
    assert stamps[0] <= stamps[1], "time_boot_ms 必须单调不减"


def test_send_position_target_accepts_explicit_time_boot_ms() -> None:
    session = make_session_with_recorder()
    session.send_position_target(north_m=0.0, east_m=0.0, down_m=0.0, time_boot_ms=12345)
    assert session.connection.mav.position_targets[0][0] == 12345


def test_send_position_target_requires_connection() -> None:
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    )
    try:
        session.send_position_target(north_m=0.0, east_m=0.0, down_m=0.0)
    except RuntimeError as exc:
        assert "connection_required" in str(exc)
    else:
        raise AssertionError("未连接时应抛 RuntimeError")


# --- goto(): 完整流程与收敛保证 -------------------------------------------


class _GotoMav(_RecordingMav):
    """可脚本化的假 MAV：按命令号返回预设 ACK 结果。"""

    def __init__(self) -> None:
        super().__init__()
        self.ack_by_command: dict[int, int] = {}   # command -> result
        self.stop_mode_command: int | None = None  # 一旦发出该命令就不再自动 ACK

    def command_long_send(self, target_system, target_component, command, confirmation, *params) -> None:
        super().command_long_send(target_system, target_component, command, confirmation, *params)
        command = int(command)
        if self.stop_mode_command is not None and command == self.stop_mode_command:
            return  # 模拟"这条命令永远不被 ACK"
        result = self.ack_by_command.get(command, 0)


class _FakeLocalPositionMsg:
    def __init__(self, z: float, x: float = 0.0, y: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z

    def get_type(self) -> str:
        return "LOCAL_POSITION_NED"


class _AutoAckConnection(_FakeConnection):
    """发命令后自动回 ACK，并按每次 DO_SET_MODE 推进一次模式剧本。

    关键点：必须**按 DO_SET_MODE 命令**推进，而不是一看到有命令就推进。
    否则预置 setpoint 阶段就会把整个模式剧本放完，等真正切 OFFBOARD 时
    心跳早已变成别的模式 —— 这是测试脚手架自身的时序错误，不是被测代码的问题。
    """

    def __init__(self, session_holder: dict) -> None:
        super().__init__()
        self.mav = _GotoMav()
        self._holder = session_holder
        self._mode_plan: list[int] = []
        self._handled_mode_commands = 0

    def recv_match(self, *args, **kwargs) -> Any:
        time.sleep(0.005)
        session = self._holder.get("session")
        if session is None:
            return None

        mode_commands = [c for c in self.mav.commands if c[0] == DO_SET_MODE]
        if len(mode_commands) > self._handled_mode_commands:
            self._handled_mode_commands = len(mode_commands)
            index = self._handled_mode_commands - 1
            session.dispatch_message(_FakeAck(DO_SET_MODE, self.mav.ack_by_command.get(DO_SET_MODE, 0)))
            if index < len(self._mode_plan):
                mode = self._mode_plan[index]
                # 直接在当前线程喂心跳：测试要的是确定性时序，不需要额外线程。
                feed_heartbeat(session, main=mode)
        return None


def make_goto_session(*, mode_plan: list[int], offboard_ack_result: int = 0):
    holder: dict[str, Any] = {}
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(
            backend_mode="sitl", backend_enabled=True,
            transport_endpoint="udpin:127.0.0.1:14540",
            target_system=1, target_component=1,
        )
    )
    connection = _AutoAckConnection(holder)
    connection.mav.ack_by_command[DO_SET_MODE] = offboard_ack_result
    connection._mode_plan = mode_plan
    session.connection = connection
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": connection.mav})()
    holder["session"] = session
    return session, connection


def _feed_local_position(session: MavlinkBackendSession, *, x: float, y: float, z: float) -> None:
    session.dispatch_message(_FakeLocalPositionMsg(z, x=x, y=y))


def test_goto_reaches_target_logs_stream_and_restores_mode() -> None:
    # 剧本按"第 N 次 DO_SET_MODE"推进：第 1 次进 OFFBOARD，第 2 次（收尾）切回 POSCTL。
    session, connection = make_goto_session(
        mode_plan=[PX4_CUSTOM_MAIN_MODE_OFFBOARD, PX4_CUSTOM_MAIN_MODE_POSCTL]
    )
    # 起点：原点；目标：北 2 米、高度 3 米（down = -3）
    _feed_local_position(session, x=0.0, y=0.0, z=0.0)

    # 用"固定次数 + 每轮多喂几条"的方式推进位置，避免后台线程与收尾阶段赛跑。
    # 位置喂到目标点后就停，且不在 goto 返回后继续写入。
    stop = threading.Event()

    def feed_positions() -> None:
        seq = [(0.0, 0.0, 0.0), (1.0, 0.0, -1.5), (2.0, 0.0, -3.0), (2.0, 0.0, -3.0)]
        for x, y, z in seq:
            for _ in range(15):
                if stop.is_set():
                    return
                _feed_local_position(session, x=x, y=y, z=z)
                time.sleep(0.02)

    feeder = threading.Thread(target=feed_positions, daemon=True)
    feeder.start()

    result = session.goto(
        north_m=2.0, east_m=0.0, down_m=-3.0,
        tolerance_m=0.3, hold_s=0.15, timeout_s=5.0, rate_hz=20.0,
        preset_setpoints=2, preset_interval_s=0.0,
    )
    stop.set()
    feeder.join(timeout=1.0)

    # 到达判定
    assert result["arrival"] is not None
    assert result["arrival"]["observed"] is True, f"应判定到达，实际 {result['arrival']}"
    # 流确实在持续发送
    assert result["stream"]["setpoints"] > 10, f"setpoint 流太少：{result['stream']}"
    # 模式：先确认进 OFFBOARD
    assert result["mode_result"]["confirmed"] is True
    assert result["mode_result"]["observed_main_mode"] == PX4_CUSTOM_MAIN_MODE_OFFBOARD
    # **关键**：收尾必须切回安全模式
    assert result["restored"] is not None
    assert result["restored"]["restored"] is True, "goto 结束后必须切回 POSCTL"
    assert result["restored"]["main_mode"] == PX4_CUSTOM_MAIN_MODE_POSCTL
    assert result["failure_reason"] is None


def test_goto_returns_failure_when_offboard_not_confirmed() -> None:
    """心跳始终报 POSCTL —— 进不了 OFFBOARD，必须报失败且不谎报到达。"""
    session, _ = make_goto_session(mode_plan=[PX4_CUSTOM_MAIN_MODE_POSCTL] * 8)
    _feed_local_position(session, x=0.0, y=0.0, z=0.0)

    result = session.goto(
        north_m=5.0, east_m=0.0, down_m=-3.0,
        tolerance_m=0.5, hold_s=0.1, timeout_s=1.0, rate_hz=20.0,
        preset_setpoints=2, preset_interval_s=0.0,
    )

    assert result["mode_result"]["confirmed"] is False
    assert result["failure_reason"] == "offboard_not_confirmed"
    assert result["arrival"] is None, "没进 OFFBOARD 就不该去等到达"
    # 即便失败也必须尝试收敛
    assert result["restored"] is not None


def test_goto_reports_arrival_timeout_but_still_restores_mode() -> None:
    """始终到不了目标 —— 必须报超时，且仍然切回安全模式。"""
    session, _ = make_goto_session(
        mode_plan=[PX4_CUSTOM_MAIN_MODE_OFFBOARD, PX4_CUSTOM_MAIN_MODE_POSCTL]
    )
    _feed_local_position(session, x=0.0, y=0.0, z=0.0)

    # 确定性投递：固定条数 + 每条后短休眠。
    # 不能用 `while not stop` 无限循环 —— 那样在 goto 返回后的收尾阶段仍会持续
    # 投递，把刚恢复的模式覆盖掉，造成测试自身的竞态（曾因此误判为代码缺陷）。
    stop = threading.Event()

    def feed_far_positions() -> None:
        for _ in range(120):
            if stop.is_set():
                return
            _feed_local_position(session, x=0.0, y=0.0, z=0.0)
            time.sleep(0.01)

    feeder = threading.Thread(target=feed_far_positions, daemon=True)
    feeder.start()
    try:
        result = session.goto(
            north_m=50.0, east_m=0.0, down_m=-10.0,
            tolerance_m=0.5, hold_s=0.1, timeout_s=0.4, rate_hz=20.0,
            preset_setpoints=2, preset_interval_s=0.0,
        )
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["arrival"]["observed"] is False
    assert result["failure_reason"] == "arrival_timeout"
    assert result["restored"]["restored"] is True, "超时也必须切回安全模式"


def test_goto_requires_local_position_before_starting() -> None:
    """还没收到任何 LOCAL_POSITION_NED 时不能起飞位控制。"""
    session, _ = make_goto_session(mode_plan=[PX4_CUSTOM_MAIN_MODE_OFFBOARD])
    result = session.goto(
        north_m=1.0, east_m=0.0, down_m=-2.0,
        tolerance_m=0.5, hold_s=0.1, timeout_s=0.5, rate_hz=20.0,
        preset_setpoints=2, preset_interval_s=0.0,
    )
    assert result["failure_reason"] is not None
    assert "local_position_required_before_goto" in str(result["failure_reason"])


def test_goto_requires_connection() -> None:
    session = MavlinkBackendSession.from_config(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    )
    try:
        session.goto(north_m=0.0, east_m=0.0, down_m=-1.0)
    except RuntimeError as exc:
        assert "connection_required" in str(exc)
    else:
        raise AssertionError("未连接时应抛 RuntimeError")
