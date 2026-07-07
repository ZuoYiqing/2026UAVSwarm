"""Agent Plan Lifecycle + Operator Approval + Execution Controller v0.1.

The lifecycle layer sits between TemplateAgentPlanner and Mission Runtime.  It
tracks human approval and dry-run/fake step progression for a MissionPlan, but
it does not execute PX4/MAVLink commands and does not replace execution-time
Policy Gate checks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from uav_runtime.agent.planner import MissionPlan, MissionPlanStep
from uav_runtime.runtime.audit_log import AuditLog


class PlanStatus:
    """Serializable agent-level plan states, not flight-controller states.

    These values describe the lifecycle of a generated plan as it moves through
    validation, human approval, and dry-run/fake execution control.  They do not
    mean a vehicle is armed, airborne, landing, or otherwise controlled by PX4.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class StepStatus:
    """Serializable agent-level step states for controller bookkeeping.

    Step status tracks plan-control progress only.  ``succeeded`` in dry_run or
    fake mode means the controller accepted and simulated the step transition;
    it does not mean Runtime executed an adapter command or PX4 completed a
    physical action.
    """

    PENDING = "pending"
    READY = "ready"
    NEEDS_OPERATOR_CONFIRM = "needs_operator_confirm"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


APPROVAL_APPROVE = "approve"
APPROVAL_REJECT = "reject"
SUPPORTED_EXECUTION_MODES = {"dry_run", "fake"}


@dataclass(slots=True)
class PlanApproval:
    """Human-in-the-loop approval record for a MissionPlan.

    Approval records operator intent; they do not replace Policy Gate.  Every
    future real execution step must still be routed through Runtime and receive
    an execution-time policy decision using live context.
    """

    approval_id: str
    plan_id: str
    operator_id: str
    decision: Literal["approve", "reject"]
    approved_steps: list[str] = field(default_factory=list)
    rejected_steps: list[str] = field(default_factory=list)
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        operator_id: str,
        decision: Literal["approve", "reject"],
        approved_steps: list[str] | None = None,
        rejected_steps: list[str] | None = None,
        reason: str = "",
    ) -> "PlanApproval":
        return cls(
            approval_id=f"approval-{uuid4().hex[:12]}",
            plan_id=plan_id,
            operator_id=operator_id,
            decision=decision,
            approved_steps=list(approved_steps or []),
            rejected_steps=list(rejected_steps or []),
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanExecutionController:
    """Minimal controller for approved MissionPlan lifecycle transitions.

    v0.1 only supports dry_run/fake execution skeletons.  It never creates a
    MAVLink session, never sends PX4 commands, and never calls real adapters.
    TODO: wire approved plan steps into RuntimeOrchestrator action execution in
    a later phase, preserving final Policy Gate checks before each action.
    """

    def __init__(self, *, audit: AuditLog | None = None) -> None:
        self.audit = audit or AuditLog()

    def load_plan(self, plan: MissionPlan) -> MissionPlan:
        """Validate plan lifecycle state after planning and before approval."""
        if self._has_blocked_step(plan):
            plan.status = PlanStatus.BLOCKED
            self._append_event("agent_plan_validated", plan, status=plan.status, reason="blocked_step")
            return plan
        if self._has_confirm_step(plan):
            plan.status = PlanStatus.AWAITING_CONFIRMATION
            self._append_event(
                "agent_plan_awaiting_confirmation",
                plan,
                status=plan.status,
                reason="operator_confirmation_required",
            )
            return plan
        plan.status = PlanStatus.VALIDATED
        self._append_event("agent_plan_validated", plan, status=plan.status, reason="all_steps_ready")
        return plan

    def approve_plan(self, plan: MissionPlan, approval: PlanApproval) -> MissionPlan:
        """Apply operator approval without bypassing policy/capability blocks."""
        if approval.plan_id != plan.plan_id:
            plan.status = PlanStatus.BLOCKED
            self._append_event(
                "agent_plan_rejected",
                plan,
                operator_id=approval.operator_id,
                status=plan.status,
                reason="approval_plan_id_mismatch",
            )
            return plan

        if approval.decision == APPROVAL_REJECT:
            plan.status = PlanStatus.CANCELLED
            self._append_event(
                "agent_plan_rejected",
                plan,
                operator_id=approval.operator_id,
                status=plan.status,
                reason=approval.reason or "operator_rejected",
            )
            return plan

        if self._has_blocked_step(plan):
            # Human approval can acknowledge risk, but it cannot turn a blocked
            # capability or denied policy precheck into an executable step.
            plan.status = PlanStatus.BLOCKED
            self._append_event(
                "agent_plan_rejected",
                plan,
                operator_id=approval.operator_id,
                status=plan.status,
                reason="blocked_step_requires_replan",
            )
            return plan

        approved_set = set(approval.approved_steps)
        for step in plan.steps:
            if step.status == StepStatus.NEEDS_OPERATOR_CONFIRM and (not approved_set or step.step_id in approved_set):
                step.status = StepStatus.READY
        plan.status = PlanStatus.APPROVED
        self._append_event(
            "agent_plan_approved",
            plan,
            operator_id=approval.operator_id,
            status=plan.status,
            reason=approval.reason or "operator_approved",
        )
        return plan

    def start_execution(self, plan: MissionPlan, mode: str = "disabled") -> dict[str, Any]:
        """Start dry-run/fake execution and advance steps sequentially.

        ``disabled`` or any mode outside dry_run/fake returns unsupported.  This
        keeps real PX4 execution impossible by default and makes tests/demo use
        an explicit non-real mode.
        """
        if mode not in SUPPORTED_EXECUTION_MODES:
            return {
                "result": "unsupported",
                "failure_reason": "unsupported_execution_mode",
                "plan": plan.to_dict(),
                "execution_mode": mode,
            }
        if plan.status != PlanStatus.APPROVED:
            return {
                "result": "blocked",
                "failure_reason": "plan_not_approved",
                "plan": plan.to_dict(),
                "execution_mode": mode,
            }
        if self._has_blocked_step(plan) or self._has_confirm_step(plan):
            plan.status = PlanStatus.BLOCKED
            return {
                "result": "blocked",
                "failure_reason": "step_not_executable",
                "plan": plan.to_dict(),
                "execution_mode": mode,
            }

        plan.status = PlanStatus.EXECUTING
        self._append_event("agent_plan_execution_started", plan, execution_mode=mode, status=plan.status)
        while any(step.status in {StepStatus.PENDING, StepStatus.READY, "dry_run_only"} for step in plan.steps):
            self.advance_next_step(plan, mode=mode)
        if all(step.status == StepStatus.SUCCEEDED for step in plan.steps):
            plan.status = PlanStatus.COMPLETED
            self._append_event("agent_plan_completed", plan, execution_mode=mode, status=plan.status)
            return {"result": "completed", "failure_reason": None, "plan": plan.to_dict(), "execution_mode": mode}
        plan.status = PlanStatus.FAILED
        return {"result": "failed", "failure_reason": "step_failed", "plan": plan.to_dict(), "execution_mode": mode}

    def advance_next_step(self, plan: MissionPlan, mode: str = "dry_run") -> MissionPlanStep | None:
        """Advance the next ready/pending step by simulation only."""
        for step in plan.steps:
            if step.status in {StepStatus.PENDING, StepStatus.READY, "dry_run_only"}:
                step.status = StepStatus.RUNNING
                self._append_event(
                    "agent_plan_step_started",
                    plan,
                    step=step,
                    execution_mode=mode,
                    status=step.status,
                    reason="final_policy_check_required_before_real_execution",
                )
                return self.mark_step_succeeded(plan, step, mode=mode, reason="simulated_success")
        return None

    def mark_step_succeeded(
        self,
        plan: MissionPlan,
        step: MissionPlanStep,
        *,
        mode: str = "dry_run",
        reason: str = "",
    ) -> MissionPlanStep:
        step.status = StepStatus.SUCCEEDED
        self._append_event(
            "agent_plan_step_succeeded",
            plan,
            step=step,
            execution_mode=mode,
            status=step.status,
            reason=reason,
        )
        return step

    def mark_step_failed(
        self,
        plan: MissionPlan,
        step: MissionPlanStep,
        *,
        mode: str = "dry_run",
        reason: str = "",
    ) -> MissionPlanStep:
        step.status = StepStatus.FAILED
        plan.status = PlanStatus.FAILED
        self._append_event(
            "agent_plan_step_failed",
            plan,
            step=step,
            execution_mode=mode,
            status=step.status,
            reason=reason,
        )
        return step

    def cancel_plan(self, plan: MissionPlan, *, reason: str = "operator_cancelled") -> MissionPlan:
        plan.status = PlanStatus.CANCELLED
        self._append_event("agent_plan_cancelled", plan, status=plan.status, reason=reason)
        return plan

    @staticmethod
    def _has_blocked_step(plan: MissionPlan) -> bool:
        return any(step.status == StepStatus.BLOCKED or step.status == "unsupported" for step in plan.steps)

    @staticmethod
    def _has_confirm_step(plan: MissionPlan) -> bool:
        return any(step.status == StepStatus.NEEDS_OPERATOR_CONFIRM for step in plan.steps)

    def _append_event(
        self,
        event_type: str,
        plan: MissionPlan,
        *,
        step: MissionPlanStep | None = None,
        operator_id: str | None = None,
        execution_mode: str | None = None,
        status: str = "",
        reason: str = "",
    ) -> None:
        self.audit.append(
            {
                "type": event_type,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "plan_id": plan.plan_id,
                "mission_type": plan.mission_type,
                "step_id": step.step_id if step else None,
                "action_type": step.action_type if step else None,
                "operator_id": operator_id,
                "execution_mode": execution_mode,
                "status": status,
                "reason": reason,
            }
        )
