"""会话级证据记录的测试。

为什么单独特测这一层
--------------------
``classify_incomplete_evidence`` 是纯函数，已单独测过。但它依赖会话里
``_last_completion_evidence`` 存的是**产生该失败的那一份证据**。

若记录逻辑写错，症状是**静默的**：分类函数照样返回一个值，只是那个值是基于
**别的动作的旧证据**算出来的 —— 调用方会看到一个看起来合理、实际错误的分类。
这类"读到别人的数据"的错法不会抛异常，所以必须专门测。

本文件锁定三件事：
  1. 观测返回时确实记录了证据；
  2. ``classify_incomplete`` 读到的就是那一份（不是上一份）；
  3. 没有观测过的会话返回 None，而不是拿默认值硬编一个分类。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from uav_runtime.adapters.mavlink_backend_session import (  # noqa: E402
    PX4_CUSTOM_MAIN_MODE_AUTO,
    PX4_CUSTOM_SUB_MODE_AUTO_LOITER,
)
from tests.unit.test_mavlink_set_mode import (  # noqa: E402
    _FakeLocalPositionMsg,
    make_goto_session,
)


def _feed(session, *, x, y, z) -> None:
    session.dispatch_message(_FakeLocalPositionMsg(z, x=x, y=y))


def _feed_stream(session, sampler, *, stop: threading.Event, interval_s: float = 0.02):
    """持续喂位置样本，直到 stop（理由见 test_mavlink_hold_and_return_home.py）。"""

    def run() -> None:
        while not stop.is_set():
            x, y, z = sampler()
            _feed(session, x=x, y=y, z=z)
            time.sleep(interval_s)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_session_without_any_observation_does_not_invent_a_classification() -> None:
    """没观测过就不能给分类 —— 返回 None，而不是凭默认值硬编一个。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])
    assert session.classify_incomplete("goto") is None
    assert session.classify_incomplete("land") is None


def test_arrival_timeout_records_evidence_with_error_readings() -> None:
    """到达超时后，证据里必须有误差读数（分类靠它判断"接近过没有"）。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])

    stop = threading.Event()
    state = {"north": 0.0}

    def creeping():
        # 慢慢接近但永远进不了 0.1 m 容差
        state["north"] += 0.05
        return (state["north"], 0.0, -5.0)

    feeder = _feed_stream(session, creeping, stop=stop)
    try:
        arrival = session.observe_arrival(
            north_m=100.0, east_m=0.0, down_m=-5.0,
            tolerance_m=0.1, hold_s=0.1, timeout_s=1.0,
        )
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert arrival["observed"] is False
    assert arrival["reason"] == "arrival_timeout"
    # 新增的三个字段是分类的依据
    assert arrival["last_error_m"] is not None
    assert arrival["min_error_m"] is not None
    assert arrival["target_error_m"] == 0.1
    # 距离目标 100 m，从未接近
    assert arrival["min_error_m"] > 50.0

    # 会话记录的必须是这一份
    classification = session.classify_incomplete("goto")
    assert classification == "partial_evidence", "有位置样本即视为可判定"


def test_hold_timeout_records_evidence_and_classifies() -> None:
    """HOLD 超时：证据里要有漂移与容差，分类据此判断漂移是否在容差内。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])
    _feed(session, x=0.0, y=0.0, z=-10.0)

    stop = threading.Event()
    state = {"north": 0.0}

    def drifting():
        state["north"] += 1.0
        return (state["north"], 0.0, -10.0)

    feeder = _feed_stream(session, drifting, stop=stop)
    try:
        outcome = session.hold_position(tolerance_m=0.5, hold_s=0.2, timeout_s=1.5)
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert outcome["held"] is False
    assert outcome["max_drift_m"] is not None
    # 容差必须随证据一起返回 —— 分类要用它，且必须是实际执行的那一份
    assert outcome["tolerance_m"] == 0.5
    assert session.classify_incomplete("hold_position") == "partial_evidence"


def test_evidence_is_replaced_by_the_latest_observation() -> None:
    """后一次观测必须覆盖前一次 —— 否则分类会基于别的动作的旧证据。

    这是本文件存在的理由：读错证据不会报错，只会给出一个看起来合理的错误分类。
    """
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])

    # 第一次：完全拿不到样本 → insufficient
    session.observe_arrival(
        north_m=100.0, east_m=0.0, down_m=-5.0,
        tolerance_m=0.1, hold_s=0.1, timeout_s=0.4,
    )
    assert session.classify_incomplete("goto") == "insufficient_evidence"

    # 第二次：持续喂样本 → 证据被覆盖，分类随之改变
    stop = threading.Event()
    state = {"north": 0.0}

    def creeping():
        state["north"] += 0.1
        return (state["north"], 0.0, -5.0)

    feeder = _feed_stream(session, creeping, stop=stop)
    try:
        session.observe_arrival(
            north_m=100.0, east_m=0.0, down_m=-5.0,
            tolerance_m=0.1, hold_s=0.1, timeout_s=1.0,
        )
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert session.classify_incomplete("goto") == "partial_evidence", (
        "第二次观测的证据必须覆盖第一次；若仍是 insufficient，说明记录没被替换"
    )


def test_completed_observation_is_not_classified_as_incomplete() -> None:
    """成功到达的观测不该被分类成"未完成"。"""
    session, _ = make_goto_session(mode_plan=[(PX4_CUSTOM_MAIN_MODE_AUTO, PX4_CUSTOM_SUB_MODE_AUTO_LOITER)])

    stop = threading.Event()
    state = {"north": 0.0}

    def approaching():
        state["north"] = min(state["north"] + 2.0, 100.0)
        return (state["north"], 0.0, -5.0)

    feeder = _feed_stream(session, approaching, stop=stop)
    try:
        arrival = session.observe_arrival(
            north_m=100.0, east_m=0.0, down_m=-5.0,
            tolerance_m=2.0, hold_s=0.2, timeout_s=5.0,
        )
    finally:
        stop.set()
        feeder.join(timeout=1.0)

    assert arrival["observed"] is True
    assert session.classify_incomplete("goto") is None, "已完成的观测不该被归类"
