"""POST /api/actions/goto —— scene_ned -> vehicle_local_ned 换算与安全拒绝。

这个端点的核心风险不是"飞不到"，而是**飞错位置**：SET_POSITION_TARGET_LOCAL_NED
收的是载具本机 local NED，而操作者给的是共享 scene_ned 目标，两者相差一个由仿真
标定测得的平移量。若把 scene 坐标当本机坐标直接发出，UAV-02/UAV-03 会偏差约 8 米。

因此这里重点断言两件事：
  1. 平移量被正确减掉（换算方向不能反）；
  2. 标定缺失/过期时**拒绝执行**，且不产生任何 MAVLink 命令。
"""
from __future__ import annotations

import pytest

from uav_runtime.adapters.px4_runtime_adapter import Px4RuntimeActionAdapter
from uav_runtime.http.schemas import GotoRequest, RequestValidationError


# --- schema 校验 -----------------------------------------------------------


def test_goto_request_applies_defaults() -> None:
    req = GotoRequest.from_json({"node_id": "UAV-01"})
    assert req.north_m == 0.0
    assert req.east_m == 0.0
    assert req.down_m == -3.0
    assert req.arrival_tolerance_m == 1.0
    assert req.hold_s == 1.0


def test_goto_request_parses_explicit_target() -> None:
    req = GotoRequest.from_json(
        {"node_id": "UAV-02", "north_m": 12.5, "east_m": -3.0, "down_m": -8.0,
         "arrival_tolerance_m": 0.5, "hold_s": 2.0}
    )
    assert (req.north_m, req.east_m, req.down_m) == (12.5, -3.0, -8.0)
    assert req.arrival_tolerance_m == 0.5
    assert req.hold_s == 2.0


@pytest.mark.parametrize(
    "payload",
    [
        {"north_m": "不是数字"},
        {"north_m": None},
        {"north_m": True},          # bool 不是数字，必须拒绝
        {"east_m": float("nan")},
        {"east_m": float("inf")},
        {"down_m": 999.0},          # 超出 ±500
        {"north_m": 99999.0},       # 超出 ±5000
        {"arrival_tolerance_m": 0.0},   # 容差下限 0.05
        {"arrival_tolerance_m": 999.0},
        {"hold_s": -1.0},
    ],
)
def test_goto_request_rejects_invalid_parameters(payload: dict) -> None:
    with pytest.raises(RequestValidationError):
        GotoRequest.from_json({"node_id": "UAV-01", **payload})


def test_goto_request_accepts_boundary_values() -> None:
    req = GotoRequest.from_json(
        {"node_id": "UAV-01", "north_m": -5000.0, "down_m": 500.0,
         "arrival_tolerance_m": 0.05, "hold_s": 0.0}
    )
    assert req.north_m == -5000.0
    assert req.down_m == 500.0
    assert req.arrival_tolerance_m == 0.05
    assert req.hold_s == 0.0


# --- 适配器分支：参数必须原样传到后端 ---------------------------------------


class _RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_result: dict = {"result": "pass"}

    def execute_goto_action(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.next_result)


def test_adapter_routes_goto_to_backend_with_exact_arguments() -> None:
    backend = _RecordingBackend()
    adapter = Px4RuntimeActionAdapter(backend)  # type: ignore[arg-type]
    adapter.execute({
        "command": "goto",
        "arguments": {
            "scene_north_m": 12.0,
            "scene_east_m": -4.0,
            "scene_down_m": -6.0,
            "translation_scene_ned_m": {"north": 0.0, "east": 8.0, "down": 0.0},
            "altitude_tolerance_m": 0.75,
            "hold_s": 1.5,
            "command_timeout_ms": 3000,
            "observe_timeout_ms": 45000,
        },
    })

    assert len(backend.calls) == 1
    call = backend.calls[0]
    # 适配器**不做**换算，原样转交；换算只发生在后端一处，避免两处算法分歧
    assert call["scene_north_m"] == 12.0
    assert call["scene_east_m"] == -4.0
    assert call["scene_down_m"] == -6.0
    assert call["translation_scene_ned_m"] == {"north": 0.0, "east": 8.0, "down": 0.0}
    assert call["altitude_tolerance_m"] == 0.75
    assert call["hold_s"] == 1.5
    assert call["observe_timeout_ms"] == 45000


def test_adapter_reports_failure_when_backend_fails() -> None:
    backend = _RecordingBackend()
    backend.next_result = {"result": "fail", "failure_reason": "arrival_timeout"}
    adapter = Px4RuntimeActionAdapter(backend)  # type: ignore[arg-type]
    out = adapter.execute({"command": "goto", "arguments": {}})
    assert out["accepted"] is False
    assert out["code"] == "arrival_timeout"


def test_adapter_defaults_translation_to_empty_when_missing() -> None:
    """缺少平移量时必须传空 dict（后端据此拒绝），不能伪造 0 平移量。"""
    backend = _RecordingBackend()
    adapter = Px4RuntimeActionAdapter(backend)  # type: ignore[arg-type]
    adapter.execute({"command": "goto", "arguments": {"scene_north_m": 1.0}})
    assert backend.calls[0]["translation_scene_ned_m"] == {}


# --- 后端换算方向与安全不变量 ----------------------------------------------


class _FakeSession:
    def __init__(self, *, outcome: dict | None = None) -> None:
        self.goto_calls: list[dict] = []
        self._outcome = outcome or {
            "mode_result": {"confirmed": True, "observed_main_mode": 6},
            "arrival": {"observed": True, "reason": "stable_within_tolerance"},
            "stream": {"setpoints": 42, "errors": 0},
            "restored": {"restored": True, "main_mode": 3},
            "failure_reason": None,
        }

    def goto(self, **kwargs):
        self.goto_calls.append(kwargs)
        return dict(self._outcome)


class _AllowedBackend:
    """绕过 SITL 前置检查，只测换算与结果整形。"""

    def __init__(self, session: _FakeSession) -> None:
        from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend

        self._impl = Px4SitlBackend.__new__(Px4SitlBackend)
        self._impl.session = session  # type: ignore[attr-defined]

    def __getattr__(self, name):
        return getattr(self._impl, name)


def _make_backend(session: _FakeSession):
    from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
    from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend

    backend = _AllowedBackend(session)
    # 用 __new__ 跳过了构造，需要自己补 config（observe_timeout_ms 从这里取）
    backend._impl.config = MavlinkBackendConfig(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udpin:127.0.0.1:14540",
    )
    # 关掉前置门，聚焦换算逻辑
    backend._impl._ensure_sitl_action_allowed = lambda action: None  # type: ignore[method-assign]
    backend._impl._ensure_persistent_session_ready = lambda action: None  # type: ignore[method-assign]
    backend._impl._base_action_result = lambda action: {"action": action, "result": "fail", "ack_evidence": []}  # type: ignore[method-assign]
    backend._impl._finish_smoke_result = lambda result: result  # type: ignore[method-assign]
    return backend._impl


def test_backend_subtracts_translation_to_get_local_target() -> None:
    """换算方向必须是 scene - translation = local，反过来就是灾难。"""
    session = _FakeSession()
    backend = _make_backend(session)

    backend.execute_goto_action(
        scene_north_m=12.0,
        scene_east_m=-4.0,
        scene_down_m=-6.0,
        # UAV-02 的典型偏移：原点在东 8 米
        translation_scene_ned_m={"north": 0.0, "east": 8.0, "down": 0.0},
        altitude_tolerance_m=0.5,
        hold_s=1.0,
    )

    assert len(session.goto_calls) == 1
    call = session.goto_calls[0]
    # 本机坐标 = 场景坐标 - 平移量
    assert call["north_m"] == 12.0
    assert call["east_m"] == -12.0, "east: -4 - 8 = -12（若写成 +12 就是方向反了）"
    assert call["down_m"] == -6.0
    assert call["tolerance_m"] == 0.5
    assert call["hold_s"] == 1.0


def test_backend_rejects_invalid_translation_instead_of_assuming_zero() -> None:
    """平移量缺失/非法必须拒绝 —— 用 0 顶替等于假装 scene 就是 local。"""
    for bad in ({}, {"north": 0.0}, {"north": 0.0, "east": "x", "down": 0.0},
                {"north": float("nan"), "east": 0.0, "down": 0.0},
                {"north": float("inf"), "east": 0.0, "down": 0.0}):
        session = _FakeSession()
        backend = _make_backend(session)
        result = backend.execute_goto_action(
            scene_north_m=1.0, scene_east_m=1.0, scene_down_m=-3.0,
            translation_scene_ned_m=bad,
        )
        assert result["result"] == "fail", f"非法平移量 {bad} 应被拒绝"
        assert "calibration_translation" in str(result["failure_reason"])
        assert session.goto_calls == [], "被拒绝时不得发出任何 setpoint"


def test_backend_requires_mode_restore_even_when_arrival_succeeded() -> None:
    """已到达但没收敛回安全模式 -> 必须报失败，不能报 pass。

    把载具留在 OFFBOARD 比"没飞到"更严重，上层必须看见。
    """
    session = _FakeSession(outcome={
        "mode_result": {"confirmed": True, "observed_main_mode": 6},
        "arrival": {"observed": True, "reason": "stable_within_tolerance"},
        "stream": {"setpoints": 10, "errors": 0},
        "restored": {"restored": False, "error": "timeout"},
        "failure_reason": None,
    })
    backend = _make_backend(session)
    result = backend.execute_goto_action(
        scene_north_m=1.0, scene_east_m=1.0, scene_down_m=-3.0,
        translation_scene_ned_m={"north": 0.0, "east": 0.0, "down": 0.0},
    )
    assert result["result"] == "fail"
    assert result["failure_reason"] == "mode_restore_failed"
    assert result["arrival_observed"] is True, "证据里仍要保留确实到达过"


def test_backend_reports_pass_with_full_evidence_on_success() -> None:
    session = _FakeSession()
    backend = _make_backend(session)
    result = backend.execute_goto_action(
        scene_north_m=2.0, scene_east_m=3.0, scene_down_m=-4.0,
        translation_scene_ned_m={"north": 1.0, "east": 1.0, "down": 0.0},
    )
    assert result["result"] == "pass"
    assert result["mode_confirmed"] is True
    assert result["arrival_observed"] is True
    assert result["stream_setpoints"] == 42
    assert result["restored"]["restored"] is True
    # 场景与本机两套坐标都要留证据，便于事后核对换算
    assert result["target_scene_ned_m"] == {"north": 2.0, "east": 3.0, "down": -4.0}
    assert result["target_vehicle_local_ned_m"] == {"north": 1.0, "east": 2.0, "down": -4.0}


def test_backend_propagates_arrival_timeout_as_failure() -> None:
    session = _FakeSession(outcome={
        "mode_result": {"confirmed": True, "observed_main_mode": 6},
        "arrival": {"observed": False, "reason": "arrival_timeout"},
        "stream": {"setpoints": 100, "errors": 0},
        "restored": {"restored": True, "main_mode": 3},
        "failure_reason": "arrival_timeout",
    })
    backend = _make_backend(session)
    result = backend.execute_goto_action(
        scene_north_m=50.0, scene_east_m=0.0, scene_down_m=-10.0,
        translation_scene_ned_m={"north": 0.0, "east": 0.0, "down": 0.0},
    )
    assert result["result"] == "fail"
    assert result["failure_reason"] == "arrival_timeout"
    assert result["arrival_observed"] is False
