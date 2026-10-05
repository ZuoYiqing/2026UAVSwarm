"""hold_position（HOLD）与 return_home（RETURN_HOME）的单元测试。

这两个动作直接作用于飞行中的载具，因此**先写测试再写实现**。

本文件重点守住的判据（都是位置上可证伪的，不是"命令发出去了"）
----------------------------------------------------------------
1. **模式切换成功 ≠ 动作成功。** 这是本项目已经踩过的坑：收尾阶段曾把
   "任意非 OFFBOARD 模式"当成安全悬停，于是接受了 RTL —— 飞机自主返航，
   而动作报 pass。所以：
     * HOLD 必须在**持续时间内位置稳定**才算成功，模式对了但飞机在飘 = 失败
     * RETURN_HOME 必须**看到到 home 的距离在缩小**才算成功
2. **只认目标子模式。** AUTO 主模式下子模式决定行为：LOITER(3) 是悬停，
   RTL(5) 是自主返航。只比主模式会把两者混为一谈。
3. **只用新模式切换之后的样本。** 切换前的旧位置不能当作新模式生效的证据。
4. **RTL 只能被显式请求，不得进入安全回退白名单。** PINNED_MODES 里没有 RTL
   是刻意的（见 mavlink_backend_session.PINNED_MODES 的注释与本次改动）。

脚手架复用 test_mavlink_set_mode.py 的假连接与心跳注入器，避免维护两套。
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from uav_runtime.adapters.mavlink_backend_session import (
    PINNED_MODES,
    PX4_CUSTOM_MAIN_MODE_AUTO,
    PX4_CUSTOM_MAIN_MODE_OFFBOARD,
    PX4_CUSTOM_MAIN_MODE_POSCTL,
    PX4_CUSTOM_SUB_MODE_AUTO_LOITER,
    PX4_CUSTOM_SUB_MODE_AUTO_RTL,
)

from tests.unit.test_mavlink_set_mode import (
    DO_SET_MODE,
    feed_plan_entry,
    make_goto_session,
    _FakeLocalPositionMsg,
)


def _feed(session, *, x: float, y: float, z: float) -> None:
    session.dispatch_message(_FakeLocalPositionMsg(z, x=x, y=y))


def _feed_stream(session, sampler, *, stop: threading.Event, interval_s: float = 0.02) -> threading.Thread:
    """持续喂位置样本，直到 stop 被设置。

    ⚠️ 必须"持续"而不是"跑完一个有限列表"。踩过的坑：用有限列表循环喂数时，
    样本会在判定开始前就被耗尽，于是被测代码确立参考点后再无新样本，
    `max_drift_m` 恒为 0、看起来像"实现接受了漂移"，实际是**测试没有持续供数**。

    sampler 是一个无参函数，每次调用返回 (north, east, down)。
    """

    def run() -> None:
        while not stop.is_set():
            x, y, z = sampler()
            _feed(session, x=x, y=y, z=z)
            time.sleep(interval_s)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _feed_plan(session, *, positions, repeats: int, stop: threading.Event,
               interval_s: float = 0.02) -> threading.Thread:
    """按固定剧本喂位置，每个点重复 repeats 次。

    仅适用于"剧本够短、判定能在剧本内完成"的场景。**需要跨越整个判定窗口
    供数时请用 _feed_stream**，否则样本会提前耗尽。
    """

    def run() -> None:
        for x, y, z in positions:
            for _ in range(repeats):
                if stop.is_set():
                    return
                _feed(session, x=x, y=y, z=z)
                time.sleep(interval_s)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# =========================================================================
# PINNED_MODES：RTL 不得进入安全回退白名单
# =========================================================================


def test_rtl_is_not_in_pinned_modes() -> None:
    """RTL 绝不能被当作"安全悬停回退"接受。

    这正是 2026-09-28 那次事故的形状：收尾检查放宽成"任意非 OFFBOARD"，
    于是 AUTO_RTL 被当成安全状态接受，飞机开始自主返航，而动作报 pass。

    即使本次为 return_home 实现了 RTL 支持，它也必须是**仅可被显式请求**的模式，
    不能进入 PINNED_MODES（那个集合的语义是"确认安全、可以作为回退目标"）。
    """
    assert (PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_RTL) not in PINNED_MODES
    # 同时确认 LOITER 仍在（它是真正的安全回退目标）
    assert (PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER) in PINNED_MODES


# =========================================================================
# hold_position
# =========================================================================


def test_hold_position_succeeds_when_the_aircraft_stays_put() -> None:
    """位置稳定保持：应成功，并报告采样数与最大偏移。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])
    _feed(session, x=5.0, y=-2.0, z=-10.0)

    stop = threading.Event()
    feeder = _feed_plan(
        session,
        positions=[(5.0, -2.0, -10.0), (5.05, -2.02, -10.01), (5.02, -1.98, -9.99)],
        repeats=20, stop=stop,
    )
    try:
        result = session.hold_position(tolerance_m=0.5, hold_s=0.2, timeout_s=5.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["held"] is True, f"应判定保持成功，实际 {result}"
    assert result["reason"] == "stable_within_tolerance"
    assert result["samples"] > 0
    assert result["max_drift_m"] is not None and result["max_drift_m"] <= 0.5
    assert result["failure_reason"] is None


def test_hold_position_fails_when_the_aircraft_drifts() -> None:
    """模式对但飞机在漂：**必须失败**。

    这条是本文件的核心。模式切换成功只能说明"飞控接受了指令"，
    不能说明飞机停住了。若这里判成功，就会产生"动作报 pass 而飞机在移动"
    的假成功 —— 正是本项目反复想避免的那类失败。
    """
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])
    _feed(session, x=0.0, y=0.0, z=-10.0)

    stop = threading.Event()
    state = {"north": 0.0}

    def drifting():
        """持续向北漂移，每步 1 米，远超 0.5 m 容差。"""
        state["north"] += 1.0
        return (state["north"], 0.0, -10.0)

    feeder = _feed_stream(session, drifting, stop=stop)
    try:
        result = session.hold_position(tolerance_m=0.5, hold_s=0.2, timeout_s=2.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["held"] is False, f"飞机在漂，不该判成功：{result}"
    assert result["reason"] == "hold_timeout"
    assert result["failure_reason"] == "hold_timeout"
    assert result["max_drift_m"] is not None and result["max_drift_m"] > 0.5


def test_hold_position_fails_when_mode_is_not_loiter() -> None:
    """切不进 LOITER（心跳始终报 POSCTL）：必须失败，不得谎报保持成功。"""
    session, _ = make_goto_session(mode_plan=[PX4_CUSTOM_MAIN_MODE_POSCTL] * 8)
    _feed(session, x=0.0, y=0.0, z=-10.0)

    result = session.hold_position(tolerance_m=1.0, hold_s=0.1, timeout_s=1.0)

    assert result["held"] is False
    assert result["failure_reason"] == "hold_mode_not_confirmed"
    assert result["mode"]["confirmed"] is False


def test_hold_position_counts_only_samples_after_the_mode_switch() -> None:
    """切换前的旧位置不能当作"新模式已生效"的证据。

    为什么必须有这条：飞控接受模式切换前，载具可能正好停在容差中心。若判定
    把那条**切换前**的样本算进来，就会出现"飞机已经飘走、却因为旧样本而判成功"。

    注意喂样本的方式：必须**持续**喂（模拟真实的连续位置流），否则样本会在
    判定开始前就被喂完，测试就测不到漂移了 —— 这一点我踩过：最初用有限的
    样本列表循环，结果判定开始前样本已耗尽，看起来像"实现接受了漂移"，
    实际是测试没有持续供数。
    """
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])
    # 切换前：正好在容差中心
    _feed(session, x=0.0, y=0.0, z=-10.0)

    stop = threading.Event()

    def drift_continuously() -> None:
        """切换后持续向北漂移，直到 stop —— 模拟真实的连续位置流。"""
        north = 5.0
        while not stop.is_set():
            _feed(session, x=north, y=0.0, z=-10.0)
            north += 1.0
            time.sleep(0.02)

    feeder = threading.Thread(target=drift_continuously, daemon=True)
    feeder.start()
    try:
        result = session.hold_position(tolerance_m=0.5, hold_s=0.2, timeout_s=2.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["held"] is False, (
        "切换后飞机持续漂移，不该因为切换前那条样本而判成功"
    )
    assert result["max_drift_m"] is not None and result["max_drift_m"] > 0.5
    assert result["reference"] is not None and abs(result["reference"][0]) < 10.0, (
        f"参考点应取切换后的最初位置，而不是漂移后的位置：{result['reference']}"
    )


def test_hold_position_requires_connection() -> None:
    session, _ = make_goto_session(mode_plan=[])
    session.connection = None
    with pytest.raises(RuntimeError, match="connection_required"):
        session.hold_position(tolerance_m=1.0, hold_s=0.1, timeout_s=1.0)


# =========================================================================
# return_home
# =========================================================================


def test_return_home_succeeds_only_when_distance_to_home_shrinks() -> None:
    """看到到 home 的距离在缩小：应成功，并报告收敛证据。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_RTL)])
    _feed(session, x=50.0, y=0.0, z=-30.0)

    stop = threading.Event()
    feeder = _feed_plan(
        session,
        positions=[(50.0, 0.0, -30.0), (35.0, 0.0, -25.0), (20.0, 0.0, -18.0),
                   (10.0, 0.0, -12.0), (4.0, 0.0, -6.0)],
        repeats=12, stop=stop,
    )
    try:
        result = session.return_home(timeout_s=6.0, min_progress_m=1.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["returning"] is True, f"距离在缩小，应判成功：{result}"
    assert result["reason"] == "converging_on_home"
    assert result["initial_distance_m"] == pytest.approx(50.0, abs=1.0)
    assert result["final_distance_m"] < result["initial_distance_m"]
    assert result["distance_reduction_m"] >= 1.0
    assert result["failure_reason"] is None


def test_return_home_fails_when_it_only_switches_mode() -> None:
    """**只切模式、位置没动 = 失败。**

    这条直接对应那次事故：模式变成 RTL 就报成功的写法会在这里判错。
    飞控接受了 RTL 不等于飞机在返航（可能被拒绝执行、被其它模式抢占、
    或 home 点未定义）。
    """
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_RTL)])
    _feed(session, x=50.0, y=0.0, z=-30.0)

    stop = threading.Event()
    # 位置完全不动（或缓慢漂移），距离没有实质缩小
    feeder = _feed_plan(
        session,
        positions=[(50.0, 0.0, -30.0), (49.9, 0.0, -30.0), (50.1, 0.0, -30.0)],
        repeats=20, stop=stop,
    )
    try:
        result = session.return_home(timeout_s=2.0, min_progress_m=5.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["returning"] is False, (
        "模式切成了 RTL 但飞机没动，不得判为成功 —— 这正是之前那次事故的形状"
    )
    assert result["reason"] == "no_convergence"
    assert result["failure_reason"] == "return_home_not_converging"


def test_return_home_fails_when_mode_is_not_rtl() -> None:
    """切不进 RTL：必须失败，即使位置碰巧在靠近 home。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)] * 8)
    _feed(session, x=50.0, y=0.0, z=-30.0)

    stop = threading.Event()
    feeder = _feed_plan(session, positions=[(40.0, 0.0, -20.0), (30.0, 0.0, -10.0)],
                        repeats=15, stop=stop)
    try:
        result = session.return_home(timeout_s=2.0, min_progress_m=1.0)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert result["returning"] is False
    assert result["failure_reason"] == "return_home_mode_not_confirmed"
    assert result["mode"]["confirmed"] is False
    # 而且必须如实报告实际观察到的子模式（LOITER 而非 RTL）
    assert result["mode"]["observed_sub_mode"] == PX4_CUSTOM_SUB_MODE_AUTO_LOITER


def test_return_home_requires_connection() -> None:
    session, _ = make_goto_session(mode_plan=[])
    session.connection = None
    with pytest.raises(RuntimeError, match="connection_required"):
        session.return_home(timeout_s=1.0)
