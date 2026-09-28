"""POST /api/plans/execute — plan submission contract for the algorithm side.

This endpoint is the boundary the algorithm layer produces against, so the
important properties are contractual rather than algorithmic:

* a plan with no operator identity is refused (real execution must be
  attributable), and so is a step with no target vehicle;
* a ``reject`` decision is a valid request that flies nothing;
* a step whose action has no Runtime endpoint is refused, never skipped;
* failure aborts the plan and reports which step failed and which never ran.

The heavy state-machine coverage lives in ``test_plan_real_execution.py``; here
we cover the HTTP-facing contract: validation, the decline path, and the fact
that step/action/target data survives the JSON round trip intact.
"""
from __future__ import annotations

import pytest

from uav_runtime.http.schemas import PlanExecuteRequest, RequestValidationError


def _plan_payload(**overrides) -> dict:
    plan = {
        "plan_id": "plan-http-1",
        "intent_id": "intent-1",
        "mission_type": "inspection_snapshot",
        "created_at": "2026-09-28T00:00:00+00:00",
        "explanation": "http contract test",
        "steps": [
            {"step_id": "s1", "action_type": "takeoff", "node_id": "UAV-01", "params": {"altitude_m": 3}},
            {"step_id": "s2", "action_type": "goto", "node_id": "UAV-01", "params": {"north_m": 4, "down_m": -3}},
            {"step_id": "s3", "action_type": "land", "node_id": "UAV-01", "params": {}},
        ],
    }
    plan.update(overrides.pop("plan", {}))
    payload = {"plan": plan, "operator_id": "op-1"}
    payload.update(overrides)
    return payload


# --- schema ---------------------------------------------------------------


def test_valid_plan_parses_and_preserves_steps() -> None:
    req = PlanExecuteRequest.from_json(_plan_payload())
    assert req.operator_id == "op-1"
    assert req.decision == "approve"
    assert [s["step_id"] for s in req.plan["steps"]] == ["s1", "s2", "s3"]
    assert req.plan["steps"][0]["node_id"] == "UAV-01"


def test_reject_decision_is_accepted_by_the_schema() -> None:
    req = PlanExecuteRequest.from_json(_plan_payload(decision="reject"))
    assert req.decision == "reject"


@pytest.mark.parametrize(
    "payload",
    [
        {},                                              # 完全没有 plan
        {"plan": "not-an-object", "operator_id": "op"},
        {"plan": {"steps": [{"step_id": "s", "action_type": "takeoff"}]}, "operator_id": "op"},   # 缺 plan_id
        {"plan": {"plan_id": "p", "steps": []}, "operator_id": "op"},                             # 空 steps
        {"plan": {"plan_id": "p"}, "operator_id": "op"},                                          # 缺 steps
        {"plan": {"plan_id": "p", "steps": [{"action_type": "takeoff"}]}, "operator_id": "op"},    # 缺 step_id
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s"}]}, "operator_id": "op"},              # 缺 action_type
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s", "action_type": "t", "params": []}]}, "operator_id": "op"},
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s", "action_type": "t", "node_id": 5}]}, "operator_id": "op"},
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s", "action_type": "t"}]}},               # 缺 operator_id
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s", "action_type": "t"}]}, "operator_id": "  "},
        {"plan": {"plan_id": "p", "steps": [{"step_id": "s", "action_type": "t"}]}, "operator_id": "op", "decision": "maybe"},
    ],
)
def test_invalid_payloads_are_rejected(payload: dict) -> None:
    with pytest.raises(RequestValidationError):
        PlanExecuteRequest.from_json(payload)


def test_step_without_node_id_is_allowed_by_schema_but_execution_refuses_it() -> None:
    """schema 允许空的 node_id（便于报出清晰原因），但执行器必须拒绝。

    这一分工是刻意的：校验层负责"结构是否合法"，执行层负责"能不能飞"。
    在 schema 层直接拒绝会让算法侧拿不到"哪个步骤缺目标"的信息。
    """
    payload = _plan_payload()
    payload["plan"]["steps"][1]["node_id"] = ""
    req = PlanExecuteRequest.from_json(payload)
    assert req.plan["steps"][1]["node_id"] == ""

    from uav_runtime.agent.executor import RealActionExecutor
    from uav_runtime.agent.planner import MissionPlanStep

    executor = RealActionExecutor(post=lambda url, body, timeout: (200, {"accepted": True}))
    step = MissionPlanStep(
        step_id="s2", action_type="goto", node_id="", params={"north_m": 1, "down_m": -3}
    )
    outcome = executor.execute_step(step)
    assert outcome.ok is False
    assert outcome.failure_reason == "step_target_vehicle_missing"


def test_unimplemented_action_reaches_the_executor_and_is_refused() -> None:
    """模板里声明过但没端点的动作，必须能带着清晰原因被拒绝。"""
    payload = _plan_payload()
    payload["plan"]["steps"][1] = {
        "step_id": "s2", "action_type": "camera_capture", "node_id": "UAV-01", "params": {},
    }
    req = PlanExecuteRequest.from_json(payload)   # 结构合法
    assert req.plan["steps"][1]["action_type"] == "camera_capture"

    from uav_runtime.agent.executor import RealActionExecutor
    from uav_runtime.agent.planner import MissionPlanStep

    calls = []
    executor = RealActionExecutor(post=lambda url, body, timeout: calls.append(url) or (200, {}))
    step = MissionPlanStep(step_id="s2", action_type="camera_capture", node_id="UAV-01")
    outcome = executor.execute_step(step)

    assert outcome.ok is False
    assert outcome.failure_reason == "action_endpoint_not_implemented"
    assert calls == [], "被拒绝的动作不得发出请求"


def test_multi_vehicle_plan_round_trips_distinct_targets() -> None:
    payload = _plan_payload()
    payload["plan"]["steps"] = [
        {"step_id": "s1", "action_type": "takeoff", "node_id": "UAV-01", "params": {}},
        {"step_id": "s2", "action_type": "takeoff", "node_id": "UAV-02", "params": {}},
        {"step_id": "s3", "action_type": "goto", "node_id": "UAV-03", "params": {"north_m": 5}},
    ]
    req = PlanExecuteRequest.from_json(payload)
    assert [s["node_id"] for s in req.plan["steps"]] == ["UAV-01", "UAV-02", "UAV-03"]


# --- endpoint wiring ------------------------------------------------------


def test_route_is_registered_and_dispatches() -> None:
    """端点必须真的接进分发逻辑，而不是只存在于文件里。

    用一个必然被 schema 拦下的请求去分发：如果路由**存在**，会得到 400
    （参数校验）；如果**不存在**，会得到 404。这既能确认注册、又不会触发
    任何真实动作 —— 不能用空 body 探测，那会真的执行默认参数的动作。
    """
    from uav_runtime.http import routes

    status, body = routes.dispatch("POST", "/api/plans/execute", body={})
    assert status == 400, f"路由应存在并返回参数校验失败，实际 {status}: {body}"
    assert "operator_id" in str(body) or "plan" in str(body)


def test_unknown_plan_route_still_404s() -> None:
    """对照：不存在的路由仍是 404，说明上面的 400 确实来自本端点。"""
    from uav_runtime.http import routes

    status, _ = routes.dispatch("POST", "/api/plans/nonexistent", body={})
    assert status == 404


def test_self_api_base_points_at_loopback() -> None:
    """执行器调用自己的动作端点，必须走本机回环，不能对外。"""
    from uav_runtime.http.routes import _self_api_base

    base = _self_api_base()
    assert base.startswith("http://127.0.0.1:")
    assert base.endswith("/api")
