"""HOLD（hold_position）与 RETURN_HOME 的 schema、适配器分发与执行器接线测试。

本文件覆盖的是**接口层**：请求体校验、适配器把参数送到哪里、执行器把动作映射到
哪个端点。*行为*判据（位置是否真的稳定、是否真的在收敛）在
``test_mavlink_hold_and_return_home.py`` 里，通过会话层的假 MAV 验证。

两者分开是有意的：会话层测"飞控行为判定对不对"，本文件测"参数有没有送错地方"。
只测其中一层会漏掉典型的接线错误 —— 例如参数名拼错、动作名没进映射表、
或者端点注册了但路径写错。
"""
from __future__ import annotations

import pytest

from uav_runtime.adapters.px4_runtime_adapter import Px4RuntimeActionAdapter
from uav_runtime.agent.executor import (
    IMPLEMENTED_ACTIONS,
    KNOWN_UNIMPLEMENTED_ACTIONS,
    RealActionExecutor,
)
from uav_runtime.http.schemas import (
    HoldPositionRequest,
    RequestValidationError,
    ReturnHomeRequest,
)


# --- HoldPositionRequest ---------------------------------------------------


def test_hold_request_applies_defaults() -> None:
    req = HoldPositionRequest.from_json({"node_id": "UAV-01"})
    assert req.tolerance_m == 2.0
    assert req.hold_s == 3.0
    assert req.timeout_s == 20.0


def test_hold_request_parses_explicit_values() -> None:
    req = HoldPositionRequest.from_json(
        {"node_id": "UAV-02", "tolerance_m": 0.5, "hold_s": 10.0, "timeout_s": 60.0}
    )
    assert (req.tolerance_m, req.hold_s, req.timeout_s) == (0.5, 10.0, 60.0)


@pytest.mark.parametrize(
    "payload",
    [
        {"tolerance_m": "不是数字"},
        {"tolerance_m": None},
        {"tolerance_m": True},            # bool 不是数字
        {"tolerance_m": 0},               # 容差为 0 永远无法满足
        {"tolerance_m": -1},
        {"tolerance_m": float("nan")},
        {"tolerance_m": float("inf")},
        {"hold_s": 0},                    # 保持 0 秒没有意义
        {"hold_s": -5},
        {"timeout_s": 0},
        {"timeout_s": float("nan")},
    ],
)
def test_hold_request_rejects_invalid_parameters(payload: dict) -> None:
    with pytest.raises(RequestValidationError):
        HoldPositionRequest.from_json({"node_id": "UAV-01", **payload})


# --- ReturnHomeRequest -----------------------------------------------------


def test_return_home_request_applies_defaults() -> None:
    req = ReturnHomeRequest.from_json({"node_id": "UAV-01"})
    assert req.timeout_s == 60.0
    assert req.min_progress_m == 5.0


@pytest.mark.parametrize(
    "payload",
    [
        {"timeout_s": "不是数字"},
        {"timeout_s": None},
        {"timeout_s": True},
        {"timeout_s": 0},
        {"timeout_s": -1},
        {"timeout_s": float("nan")},
        {"min_progress_m": 0},            # 要求"至少靠近 0 米"等于不要求收敛
        {"min_progress_m": -1},
        {"min_progress_m": float("inf")},
    ],
)
def test_return_home_request_rejects_invalid_parameters(payload: dict) -> None:
    with pytest.raises(RequestValidationError):
        ReturnHomeRequest.from_json({"node_id": "UAV-01", **payload})


# --- 动作映射：HOLD / RETURN_HOME 现在必须算"已实现" ------------------------


@pytest.mark.parametrize("action", ["hold_position", "hold", "return_home"])
def test_hold_and_return_home_are_implemented_actions(action: str) -> None:
    """这三个名字都必须映射到端点。

    ``hold`` 是别名：算法侧的提案 schema 用大写 ``HOLD``，而动作注册表里叫
    ``hold_position``。两者指同一件事，都必须能用，否则调用方会因为命名差异
    被拒 —— 而它并没有做错什么。
    """
    assert action in IMPLEMENTED_ACTIONS, f"{action} 应已实现"
    assert action not in KNOWN_UNIMPLEMENTED_ACTIONS, f"{action} 不应再列为未实现"


def test_hold_alias_points_to_the_same_endpoint() -> None:
    assert IMPLEMENTED_ACTIONS["hold"] == IMPLEMENTED_ACTIONS["hold_position"]


def test_actions_still_not_implemented_are_refused_honestly() -> None:
    """OBSERVE 仍未实现，必须仍然如实报"未实现"。

    这条防止"为了让巡检计划跑通"而把 OBSERVE 也算成已实现 ——
    那会产生"计划显示完成、实际没拍照"的假成功。
    """
    assert "observe" not in IMPLEMENTED_ACTIONS
    assert "observe" in KNOWN_UNIMPLEMENTED_ACTIONS


# --- 执行器：端点与请求体 ---------------------------------------------------


class _RecordingExecutor:
    """把 HTTP 调用换成本地记录，用来断言"参数送到了哪个端点、内容是什么"。

    注意：``RealActionExecutor`` 的传输层是**注入的**（``post=`` 参数），
    不是可覆盖的方法。最初我试着子类化并覆盖 ``_post``，结果请求根本没发出去 ——
    实例属性 ``self._post`` 会遮蔽方法，所以覆盖没生效。用注入才是对的接法。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.executor = RealActionExecutor(
            api_base="http://127.0.0.1:9",
            post=self._record,
            timeout_s=5.0,
        )

    def _record(self, url: str, body: dict, timeout_s: float):
        self.calls.append((url, body))
        # 返回一个"成功"形状，让 execute_step 走到 ok=True
        return 200, {
            "action": url.rsplit("/", 1)[-1],
            "result": "pass",
            "accepted": True,
            "held": True,
            "returning": True,
        }

    def execute_step(self, step):
        return self.executor.execute_step(step)


class _Step:
    def __init__(self, action_type: str, node_id: str = "UAV-01", params=None, step_id: str = "s1") -> None:
        self.step_id = step_id
        self.action_type = action_type
        self.node_id = node_id
        self.params = params or {}


def test_executor_posts_hold_position_to_its_endpoint() -> None:
    executor = _RecordingExecutor()
    outcome = executor.execute_step(
        _Step("HOLD", params={"tolerance_m": 1.5, "hold_s": 4.0, "timeout_s": 30.0})
    )
    assert len(executor.calls) == 1, f"应只发一次请求，实际 {executor.calls}"
    url, body = executor.calls[0]
    assert url.endswith("/actions/hold-position"), url
    assert body["node_id"] == "UAV-01"
    assert body["tolerance_m"] == 1.5
    assert body["hold_s"] == 4.0
    assert body["timeout_s"] == 30.0
    # HOLD 不需要坐标，绝不能出现坐标字段（出现就说明接线错了）
    for unexpected in ("north_m", "east_m", "down_m"):
        assert unexpected not in body, f"HOLD 请求体不该含 {unexpected}"
    assert outcome.ok is True


def test_executor_posts_return_home_to_its_endpoint() -> None:
    executor = _RecordingExecutor()
    executor.execute_step(_Step("RETURN_HOME", params={"timeout_s": 90.0, "min_progress_m": 8.0}))
    assert len(executor.calls) == 1
    url, body = executor.calls[0]
    assert url.endswith("/actions/return-home"), url
    assert body["node_id"] == "UAV-01"
    assert body["timeout_s"] == 90.0
    assert body["min_progress_m"] == 8.0
    for unexpected in ("north_m", "east_m", "down_m"):
        assert unexpected not in body, f"RETURN_HOME 请求体不该含 {unexpected}"


def test_executor_accepts_hold_position_spelling_too() -> None:
    """注册表拼写（hold_position）与算法拼写（HOLD）都要能用。"""
    executor = _RecordingExecutor()
    executor.execute_step(_Step("hold_position"))
    assert executor.calls[0][0].endswith("/actions/hold-position")


def test_executor_drops_unknown_params_instead_of_forwarding_them() -> None:
    """未知参数必须丢弃，不能原样传下去。

    否则规划层的一个笔误会变成"端点忽略的未知字段"，而调用方以为它生效了。
    """
    executor = _RecordingExecutor()
    executor.execute_step(_Step("HOLD", params={"tolerance_m": 1.0, "打错了的字段": 42}))
    _, body = executor.calls[0]
    assert "打错了的字段" not in body
    assert "tolerance_m" in body


def test_executor_still_refuses_observe_with_a_clear_reason() -> None:
    """OBSERVE 必须仍被拒，且原因码要说明是"未实现"而不是"拼写错误"。"""
    executor = _RecordingExecutor()
    outcome = executor.execute_step(_Step("OBSERVE"))
    assert outcome.ok is False
    assert executor.calls == [], "被拒的动作不该产生任何 HTTP 调用"
    assert outcome.failure_reason == "action_endpoint_not_implemented", outcome.failure_reason
