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
