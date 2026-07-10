"""Agent Plan Lifecycle + Operator Approval controller tests."""
from __future__ import annotations

import json
from pathlib import Path

from uav_runtime.agent.lifecycle import (
    PlanApproval,
    PlanExecutionController,
    PlanStatus,
    StepStatus,
)
from uav_runtime.agent.planner import IntentRouter, MissionIntent, TemplateAgentPlanner, TemplateStep
from uav_runtime.runtime.audit_log import AuditLog


def _controller(tmp_path: Path) -> PlanExecutionController:
    return PlanExecutionController(audit=AuditLog(str(tmp_path / "agent.lifecycle.audit.jsonl")))


def _plan(tmp_path: Path, mission_type: str = "status_only"):
    planner = TemplateAgentPlanner(audit=AuditLog(str(tmp_path / "agent.plan.audit.jsonl")))
    result = planner.plan(MissionIntent(intent_id=f"intent-{mission_type}", mission_type=mission_type))
    assert result.plan is not None
    return result.plan


def test_plan_with_all_allow_steps_loads_as_validated_ready(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "status_only")
    controller = _controller(tmp_path)

    loaded = controller.load_plan(plan)

    assert loaded.status == PlanStatus.VALIDATED
    assert all(step.status in {StepStatus.READY, "dry_run_only"} for step in loaded.steps)
    assert all(step.final_policy_check_required is True for step in loaded.steps)


class _ConfirmRouter(IntentRouter):
    def route(self, intent: MissionIntent) -> tuple[TemplateStep, ...] | None:
        return (TemplateStep("speaker_play_message"),)


def test_plan_with_require_confirm_step_enters_awaiting_confirmation(tmp_path: Path) -> None:
    planner = TemplateAgentPlanner(router=_ConfirmRouter(), audit=AuditLog(str(tmp_path / "plan.audit.jsonl")))
    result = planner.plan(MissionIntent(intent_id="intent-confirm", mission_type="confirm_template"))
    assert result.plan is not None
    assert result.result == PlanStatus.AWAITING_CONFIRMATION

    loaded = _controller(tmp_path).load_plan(result.plan)

    assert loaded.status == PlanStatus.AWAITING_CONFIRMATION
    assert loaded.steps[0].status == StepStatus.NEEDS_OPERATOR_CONFIRM


def test_approve_plan_moves_status_to_approved(tmp_path: Path) -> None:
    plan = _controller(tmp_path).load_plan(_plan(tmp_path, "status_only"))
    approval = PlanApproval.create(plan_id=plan.plan_id, operator_id="operator_001", decision="approve")

    approved = _controller(tmp_path).approve_plan(plan, approval)

    assert approved.status == PlanStatus.APPROVED


def test_reject_plan_moves_status_to_cancelled(tmp_path: Path) -> None:
    plan = _controller(tmp_path).load_plan(_plan(tmp_path, "status_only"))
    approval = PlanApproval.create(
        plan_id=plan.plan_id,
        operator_id="operator_001",
        decision="reject",
        reason="operator rejected dry-run plan",
    )

    rejected = _controller(tmp_path).approve_plan(plan, approval)

    assert rejected.status == PlanStatus.CANCELLED


def test_execute_approved_plan_in_dry_run_succeeds_and_completes(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    plan = controller.load_plan(_plan(tmp_path, "status_only"))
    plan = controller.approve_plan(
        plan,
        PlanApproval.create(plan_id=plan.plan_id, operator_id="operator_001", decision="approve"),
    )

    result = controller.start_execution(plan, mode="dry_run")

    assert result["result"] == "completed"
    assert plan.status == PlanStatus.COMPLETED
    assert all(step.status == StepStatus.SUCCEEDED for step in plan.steps)


class _BlockedRouter(IntentRouter):
    def route(self, intent: MissionIntent) -> tuple[TemplateStep, ...] | None:
        return (TemplateStep("payload_release"),)


def test_execute_plan_with_blocked_step_refuses_execution_and_approval_cannot_bypass_policy(tmp_path: Path) -> None:
    planner = TemplateAgentPlanner(router=_BlockedRouter(), audit=AuditLog(str(tmp_path / "plan.audit.jsonl")))
    result = planner.plan(MissionIntent(intent_id="intent-blocked", mission_type="blocked_template"))
    assert result.plan is not None
    controller = _controller(tmp_path)
    plan = controller.load_plan(result.plan)
    assert plan.status == PlanStatus.BLOCKED

    approved = controller.approve_plan(
        plan,
        PlanApproval.create(plan_id=plan.plan_id, operator_id="operator_001", decision="approve"),
    )
    execution = controller.start_execution(approved, mode="dry_run")

    assert approved.status == PlanStatus.BLOCKED
    assert execution["result"] == "blocked"
    assert execution["failure_reason"] == "plan_not_approved"


def test_cancel_plan_sets_cancelled_status(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    plan = controller.load_plan(_plan(tmp_path, "status_only"))

    cancelled = controller.cancel_plan(plan, reason="operator_cancelled")

    assert cancelled.status == PlanStatus.CANCELLED


def test_unsupported_execution_mode_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    plan = controller.load_plan(_plan(tmp_path, "status_only"))
    plan = controller.approve_plan(
        plan,
        PlanApproval.create(plan_id=plan.plan_id, operator_id="operator_001", decision="approve"),
    )

    result = controller.start_execution(plan, mode="px4_real")

    assert result["result"] == "unsupported"
    assert result["failure_reason"] == "unsupported_execution_mode"


def test_lifecycle_audit_events_are_written(tmp_path: Path) -> None:
    audit_path = tmp_path / "agent.lifecycle.audit.jsonl"
    controller = PlanExecutionController(audit=AuditLog(str(audit_path)))
    plan = controller.load_plan(_plan(tmp_path, "status_only"))
    plan = controller.approve_plan(
        plan,
        PlanApproval.create(plan_id=plan.plan_id, operator_id="operator_001", decision="approve"),
    )
    controller.start_execution(plan, mode="dry_run")

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["type"] for event in events]

    assert "agent_plan_validated" in event_types
    assert "agent_plan_approved" in event_types
    assert "agent_plan_execution_started" in event_types
    assert "agent_plan_step_started" in event_types
    assert "agent_plan_step_succeeded" in event_types
    assert "agent_plan_completed" in event_types
    assert all("plan_id" in event for event in events)
    assert all("status" in event for event in events)
