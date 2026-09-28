"""Real plan execution: executor mapping + abort-on-failure lifecycle.

These tests cover the piece that turns the agent plan lifecycle from a dry-run
skeleton into something that can actually move aircraft.  The behaviours worth
locking down are the ones that were previously *wrong* in this project:

* a step whose action has no endpoint must be **refused**, not silently
  "succeeded" (the position-setpoint bug: accepted, streamed, moved nothing);
* a step with no target vehicle must be refused (there is no safe default);
* an accepted-but-failed action must count as failure (the RTL bug: reported
  pass while the aircraft flew away);
* the first failed step aborts the plan, and the remaining steps stay pending.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from uav_runtime.agent.executor import (
    IMPLEMENTED_ACTIONS,
    KNOWN_UNIMPLEMENTED_ACTIONS,
    RealActionExecutor,
    StepOutcome,
)
from uav_runtime.agent.lifecycle import (
    PlanApproval,
    PlanExecutionController,
    PlanStatus,
    StepStatus,
)
from uav_runtime.agent.planner import MissionPlan, MissionPlanStep


# --- helpers ---------------------------------------------------------------


class _RecordingPost:
    """Fake transport that records calls and returns scripted responses."""

    def __init__(self, responder=None) -> None:
        self.calls: list[tuple[str, dict, float]] = []
        self._responder = responder or (lambda url, body: (200, {"accepted": True, "result": "pass"}))

    def __call__(self, url: str, body: dict, timeout_s: float):
        self.calls.append((url, body, timeout_s))
        return self._responder(url, body)


def _executor(responder=None, timeout_s: float = 5.0):
    post = _RecordingPost(responder)
    return RealActionExecutor(api_base="http://127.0.0.1:8765/api", post=post, timeout_s=timeout_s), post


def _step(action_type: str, *, node_id: str = "UAV-01", step_id: str = "step-1", **params) -> MissionPlanStep:
    return MissionPlanStep(step_id=step_id, action_type=action_type, node_id=node_id, params=dict(params))


def _plan(*steps: MissionPlanStep, plan_id: str = "plan-1") -> MissionPlan:
    return MissionPlan(
        plan_id=plan_id,
        intent_id="intent-1",
        mission_type="test",
        steps=list(steps),
        status=PlanStatus.APPROVED,
        explanation="test plan",
        created_at="2026-09-28T00:00:00+00:00",
    )


def _approve(controller: PlanExecutionController, plan: MissionPlan) -> MissionPlan:
    approval = PlanApproval.create(plan_id=plan.plan_id, operator_id="op-1", decision="approve")
    return controller.approve_plan(plan, approval)


# --- executor: mapping -----------------------------------------------------


def test_takeoff_maps_to_takeoff_endpoint_with_altitude() -> None:
    executor, post = _executor()
    outcome = executor.execute_step(_step("takeoff", altitude_m=4.5))

    assert outcome.ok is True
    url, body, _ = post.calls[0]
    assert url == "http://127.0.0.1:8765/api/actions/takeoff"
    assert body["node_id"] == "UAV-01"
    assert body["altitude_m"] == 4.5


def test_goto_maps_scene_ned_coordinates() -> None:
    executor, post = _executor()
    outcome = executor.execute_step(
        _step("goto", north_m=12.5, east_m=-3.0, down_m=-6.0, arrival_tolerance_m=0.5, hold_s=1.5)
    )

    assert outcome.ok is True
    url, body, _ = post.calls[0]
    assert url.endswith("/actions/goto")
    assert body == {
        "node_id": "UAV-01",
        "north_m": 12.5,
        "east_m": -3.0,
        "down_m": -6.0,
        "arrival_tolerance_m": 0.5,
        "hold_s": 1.5,
    }


def test_land_sends_only_node_id() -> None:
    executor, post = _executor()
    executor.execute_step(_step("land"))
    _, body, _ = post.calls[0]
    assert body == {"node_id": "UAV-01"}


def test_unknown_parameters_are_dropped_not_forwarded() -> None:
    """规划层的拼写错误不该变成 Runtime 静默忽略的未知字段。"""
    executor, post = _executor()
    executor.execute_step(_step("land", nonsense="x", altitude_m=99))
    _, body, _ = post.calls[0]
    assert "nonsense" not in body
    assert "altitude_m" not in body


# --- executor: refusals ----------------------------------------------------


@pytest.mark.parametrize("action_type", sorted(KNOWN_UNIMPLEMENTED_ACTIONS))
def test_unimplemented_actions_are_refused_not_skipped(action_type: str) -> None:
    """声明了但没端点的动作必须被拒绝 —— 静默跳过会产生假成功。"""
    executor, post = _executor()
    outcome = executor.execute_step(_step(action_type))

    assert outcome.ok is False
    assert outcome.failure_reason == "action_endpoint_not_implemented"
    assert post.calls == [], "被拒绝的步骤不得发出任何请求"


def test_unknown_action_type_is_refused() -> None:
    executor, post = _executor()
    outcome = executor.execute_step(_step("teleport"))
    assert outcome.ok is False
    assert outcome.failure_reason == "unknown_action_type"
    assert post.calls == []


def test_step_without_target_vehicle_is_refused() -> None:
    executor, post = _executor()
    outcome = executor.execute_step(_step("takeoff", node_id=""))
    assert outcome.ok is False
    assert outcome.failure_reason == "step_target_vehicle_missing"
    assert post.calls == [], "没有目标载具时绝不能猜测"


def test_implemented_actions_all_have_endpoints() -> None:
    """已实现列表必须与真实端点一致，防止把没端点的动作写进去。"""
    for action, endpoint in IMPLEMENTED_ACTIONS.items():
        assert endpoint.startswith("/actions/"), action
    assert set(IMPLEMENTED_ACTIONS) & set(KNOWN_UNIMPLEMENTED_ACTIONS) == set()


# --- executor: failure detection ------------------------------------------


def test_http_200_with_accepted_false_is_a_failure() -> None:
    """HTTP 成功但 accepted=false 必须算失败。"""
    executor, _ = _executor(lambda url, body: (200, {
        "accepted": False,
        "result": "fail",
        "failure_reason": "coordinate_calibration_unavailable",
    }))
    outcome = executor.execute_step(_step("goto", north_m=1, east_m=0, down_m=-3))
    assert outcome.ok is False
    assert outcome.failure_reason == "coordinate_calibration_unavailable"


def test_http_200_with_result_fail_is_a_failure() -> None:
    executor, _ = _executor(lambda url, body: (200, {
        "accepted": True, "result": "fail", "failure_reason": "arrival_timeout",
    }))
    outcome = executor.execute_step(_step("goto", north_m=50, east_m=0, down_m=-3))
    assert outcome.ok is False
    assert outcome.failure_reason == "arrival_timeout"


def test_transport_error_is_reported_not_raised() -> None:
    def boom(url, body):
        raise OSError("connection refused")

    executor, _ = _executor(boom)
    outcome = executor.execute_step(_step("land"))
    assert outcome.ok is False
    assert outcome.failure_reason == "transport_error"


# --- executor: completion evidence ----------------------------------------


def test_goto_evidence_exposes_mode_arrival_and_restore() -> None:
    """goto 完成证据必须带上区分真成功与假成功的字段。"""
    executor, _ = _executor(lambda url, body: (200, {
        "accepted": True,
        "result": "pass",
        "mode_confirmed": True,
        "arrival_observed": True,
        "arrival": {"last_error_m": 0.144, "reason": "stable_within_tolerance"},
        "restored": {"restored": True, "still_in_offboard": False, "observed_sub_mode": 3},
    }))
    outcome = executor.execute_step(_step("goto", north_m=4, east_m=0, down_m=-3))

    assert outcome.ok is True
    assert outcome.evidence["mode_confirmed"] is True
    assert outcome.evidence["arrival_observed"] is True
    assert outcome.evidence["arrival_error_m"] == 0.144
    assert outcome.evidence["still_in_offboard"] is False
    assert outcome.evidence["observed_sub_mode"] == 3


def test_takeoff_evidence_exposes_arm_and_completion() -> None:
    executor, _ = _executor(lambda url, body: (200, {
        "accepted": True,
        "result": "pass",
        "arm_ack": {"result_name": "MAV_RESULT_ACCEPTED"},
        "takeoff_ack": {"result_name": "MAV_RESULT_ACCEPTED"},
        "completion_state": "succeeded",
        "completion_evidence": {"completion_reached": True, "last_altitude_m": 2.74},
    }))
    outcome = executor.execute_step(_step("takeoff", altitude_m=3))
    assert outcome.evidence["arm_result_name"] == "MAV_RESULT_ACCEPTED"
    assert outcome.evidence["completion_reached"] is True
    assert outcome.evidence["last_altitude_m"] == 2.74


# --- lifecycle: real mode --------------------------------------------------


class _FakeExecutor:
    """Scripted executor: returns queued outcomes in order."""

    def __init__(self, outcomes: list[StepOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.seen: list[str] = []

    def execute_step(self, step) -> StepOutcome:
        self.seen.append(step.step_id)
        if not self._outcomes:
            return StepOutcome(ok=True, action_type=step.action_type, node_id=step.node_id)
        return self._outcomes.pop(0)


def _ok(step: MissionPlanStep) -> StepOutcome:
    return StepOutcome(ok=True, action_type=step.action_type, node_id=step.node_id, result="pass")


def _fail(step: MissionPlanStep, reason: str) -> StepOutcome:
    return StepOutcome(
        ok=False, action_type=step.action_type, node_id=step.node_id, failure_reason=reason,
    )


def test_real_execution_completes_when_all_steps_succeed(tmp_path: Path) -> None:
    steps = [_step("takeoff", step_id="s1"), _step("goto", step_id="s2", north_m=4, down_m=-3), _step("land", step_id="s3")]
    plan = _plan(*steps)
    controller = PlanExecutionController(
        audit=None, action_executor=_FakeExecutor([_ok(s) for s in steps])
    )
    _approve(controller, plan)

    result = controller.execute_plan_real(plan, operator_id="op-1")

    assert result["result"] == "completed"
    assert result["failure_reason"] is None
    assert plan.status == PlanStatus.COMPLETED
    assert [s.status for s in plan.steps] == [StepStatus.SUCCEEDED] * 3


def test_first_failure_aborts_plan_and_leaves_rest_pending(tmp_path: Path) -> None:
    """用户指定的失败策略：失败即中止整个计划。"""
    steps = [_step("takeoff", step_id="s1"), _step("goto", step_id="s2"), _step("land", step_id="s3")]
    plan = _plan(*steps)
    executor = _FakeExecutor([_ok(steps[0]), _fail(steps[1], "action_endpoint_not_implemented")])
    controller = PlanExecutionController(audit=None, action_executor=executor)
    _approve(controller, plan)

    result = controller.execute_plan_real(plan, operator_id="op-1")

    assert result["result"] == "failed"
    assert result["failure_reason"] == "action_endpoint_not_implemented"
    assert result["aborted_at_step"] == "s2"
    assert result["remaining_steps_pending"] == ["s3"]
    assert plan.status == PlanStatus.FAILED
    assert plan.steps[0].status == StepStatus.SUCCEEDED
    assert plan.steps[1].status == StepStatus.FAILED
    # 第 3 步既没执行也没被标成成功；它保持 approve 之后的就绪态。
    # 这里断言"未开始执行"而不是某个具体字面量，因为它可以是 ready 或 pending，
    # 真正要保证的是：它没有被执行、也没有被误标为成功。
    assert plan.steps[2].status not in {StepStatus.RUNNING, StepStatus.SUCCEEDED, StepStatus.FAILED}
    assert executor.seen == ["s1", "s2"], "中止后不得再调用第 3 步"


def test_real_execution_requires_an_executor(tmp_path: Path) -> None:
    plan = _plan(_step("takeoff"))
    controller = PlanExecutionController(audit=None)
    _approve(controller, plan)
    result = controller.execute_plan_real(plan, operator_id="op-1")
    assert result["result"] == "blocked"
    assert result["failure_reason"] == "no_action_executor_configured"


def test_real_execution_requires_operator_id(tmp_path: Path) -> None:
    plan = _plan(_step("takeoff"))
    controller = PlanExecutionController(audit=None, action_executor=_FakeExecutor([]))
    _approve(controller, plan)
    result = controller.execute_plan_real(plan, operator_id="")
    assert result["result"] == "blocked"
    assert result["failure_reason"] == "operator_id_required_for_real_execution"


def test_real_execution_blocked_when_plan_not_approved(tmp_path: Path) -> None:
    plan = _plan(_step("takeoff"))
    plan.status = PlanStatus.VALIDATED
    controller = PlanExecutionController(audit=None, action_executor=_FakeExecutor([]))
    result = controller.execute_plan_real(plan, operator_id="op-1")
    assert result["result"] == "blocked"
    assert result["failure_reason"] == "plan_not_approved"


def test_plan_with_any_untargeted_step_is_blocked_before_flying(tmp_path: Path) -> None:
    """只要有一个步骤缺目标，整份计划在起飞前就被挡下。"""
    steps = [_step("takeoff", step_id="s1"), _step("goto", step_id="s2", node_id="")]
    plan = _plan(*steps)
    executor = _FakeExecutor([])
    controller = PlanExecutionController(audit=None, action_executor=executor)
    _approve(controller, plan)

    result = controller.execute_plan_real(plan, operator_id="op-1")

    assert result["result"] == "blocked"
    assert result["failure_reason"] == "step_target_vehicle_missing"
    assert result["detail"]["steps_without_target"] == ["s2"]
    assert executor.seen == [], "不得先飞第 1 步再报第 2 步的问题"


def test_multi_vehicle_plan_targets_are_preserved(tmp_path: Path) -> None:
    """多机计划：不同步骤指向不同载具，执行器必须原样收到。"""
    steps = [
        _step("takeoff", step_id="s1", node_id="UAV-01"),
        _step("takeoff", step_id="s2", node_id="UAV-02"),
        _step("goto", step_id="s3", node_id="UAV-03", north_m=5, down_m=-3),
    ]
    plan = _plan(*steps)
    recorded = []

    class _Recorder:
        def execute_step(self, step):
            recorded.append(step.node_id)
            return _ok(step)

    controller = PlanExecutionController(audit=None, action_executor=_Recorder())
    _approve(controller, plan)
    result = controller.execute_plan_real(plan, operator_id="op-1")

    assert result["result"] == "completed"
    assert recorded == ["UAV-01", "UAV-02", "UAV-03"]


# --- regression: dry_run semantics unchanged ------------------------------


def test_dry_run_still_simulates_and_never_calls_the_executor(tmp_path: Path) -> None:
    """dry_run 必须保持"纯模拟"，不得因为引入真实执行而被改掉。"""
    steps = [_step("takeoff", step_id="s1"), _step("land", step_id="s2")]
    plan = _plan(*steps)
    executor = _FakeExecutor([_fail(s, "should_not_be_called") for s in steps])
    controller = PlanExecutionController(audit=None, action_executor=executor)
    _approve(controller, plan)

    result = controller.start_execution(plan, mode="dry_run")

    assert result["result"] == "completed"
    assert executor.seen == [], "dry_run 不得触碰真实执行器"
    assert [s.status for s in plan.steps] == [StepStatus.SUCCEEDED] * 2
