"""Intent Router + Template Agent Planner v0.1.

This module is intentionally plan-only.  It converts an explicitly supplied
``mission_type`` into a deterministic Mission Plan IR, validates every step
against the Action / Capability Registry, and performs a Policy Gate precheck.
It does not parse free-form natural language, call an LLM, execute runtime
actions, or send MAVLink / adapter commands.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from uav_runtime.policy.action_registry import ActionCapability, get_action_capability
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import build_policy_profile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState
from uav_runtime.runtime.audit_log import AuditLog

PLAN_DRAFT = "draft"
PLAN_READY = "ready"
PLAN_VALIDATED = "validated"
PLAN_AWAITING_CONFIRMATION = "awaiting_confirmation"
PLAN_APPROVED = "approved"
PLAN_EXECUTING = "executing"
PLAN_COMPLETED = "completed"
PLAN_BLOCKED = "blocked"
PLAN_FAILED = "failed"
PLAN_CANCELLED = "cancelled"
PLAN_EXPIRED = "expired"
PLAN_UNSUPPORTED = "unsupported"
PLAN_NEEDS_CONFIRM = "needs_operator_confirm"
PLAN_DRY_RUN_ONLY = "dry_run_only"


@dataclass(slots=True)
class MissionIntent:
    """Operator-provided mission intent for the agent planning layer.

    v0.1 deliberately treats ``mission_type`` as an explicit controlled input
    from an operator, CLI, or upstream system.  It is not natural-language
    understanding and is not an execution request; it is only the starting point
    for dry-run plan generation.
    """

    intent_id: str
    mission_type: str
    source: str = "operator"
    objective: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    requested_profile: str = "standard"
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MissionPlanStep:
    """One planned action in the Mission Plan IR, not a runtime execution record.

    The step captures capability metadata and policy precheck output so humans
    can explain why a template plan is ready, blocked, confirmation-gated, or
    dry-run-only before Runtime ever receives an executable action.
    """

    step_id: str
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)
    expected_adapter: str = ""
    required_capability: dict[str, Any] | None = None
    risk_level: int | None = None
    fallback_allowed: bool = False
    policy_precheck: dict[str, Any] | None = None
    # Planner precheck is not final authorization.  Runtime must perform a
    # fresh Policy Gate check immediately before any future real action execution.
    final_policy_check_required: bool = True
    status: str = PLAN_READY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MissionPlan:
    """Serializable dry-run Mission Plan IR produced by TemplateAgentPlanner.

    The plan belongs to the agent planning layer.  Runtime state such as
    running_actions, pending_takeovers, adapter sessions, and action_result is
    intentionally outside this structure.
    """

    plan_id: str
    intent_id: str
    mission_type: str
    steps: list[MissionPlanStep]
    status: str
    explanation: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


@dataclass(slots=True)
class PlanResult:
    """Result envelope for dry-run planning, validation, and policy precheck.

    ``result`` describes plan readiness only.  Even an ``allowed`` plan must be
    submitted to Runtime later, where Policy Gate and adapters run again under
    live runtime context.
    """

    result: str
    failure_reason: str | None
    plan: MissionPlan | None
    validation_summary: dict[str, Any]
    policy_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "failure_reason": self.failure_reason,
            "plan": self.plan.to_dict() if self.plan else None,
            "validation_summary": self.validation_summary,
            "policy_summary": self.policy_summary,
        }


@dataclass(frozen=True, slots=True)
class TemplateStep:
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)


MISSION_TEMPLATES: dict[str, tuple[TemplateStep, ...]] = {
    "simple_takeoff_land": (TemplateStep("takeoff"), TemplateStep("land")),
    "inspection_snapshot": (
        TemplateStep("takeoff"),
        TemplateStep("report_status"),
        TemplateStep("camera_capture"),
        TemplateStep("land"),
    ),
    "status_only": (TemplateStep("health_query"), TemplateStep("sensor_read"), TemplateStep("report_status")),
    "safe_stop": (TemplateStep("land_safe"),),
    "fallback_hold": (TemplateStep("hold_position"),),
}


class IntentRouter:
    """Route explicit mission_type values to deterministic templates.

    v0.1 does not perform free-form natural-language understanding.  Unsupported
    mission_type values are blocked instead of guessed.  TODO: a future LLM
    Intent Parser may propose mission_type/params, but it must still pass this
    router, capability validation, policy precheck, operator confirmation, and
    Runtime authorization.
    """

    def route(self, intent: MissionIntent) -> tuple[TemplateStep, ...] | None:
        return MISSION_TEMPLATES.get(intent.mission_type)


class TemplateAgentPlanner:
    """Deterministic template planner for plan-only mission expansion.

    This is not LLM reasoning and not a scheduler.  It maps a supported
    mission_type to fixed steps, rejects dangerous/unknown capabilities early,
    and annotates each step with Policy Gate precheck output.
    """

    def __init__(self, *, router: IntentRouter | None = None, audit: AuditLog | None = None) -> None:
        self.router = router or IntentRouter()
        self.audit = audit or AuditLog()

    def plan(self, intent: MissionIntent) -> PlanResult:
        template = self.router.route(intent)
        if template is None:
            result = PlanResult(
                result=PLAN_BLOCKED,
                failure_reason="unsupported_mission_type",
                plan=None,
                validation_summary={"unsupported_mission_type": intent.mission_type, "blocked_steps": 0},
                policy_summary={"checked_steps": 0, "denied_steps": 0, "require_confirm_steps": 0},
            )
            self._audit_plan(intent=intent, result=result)
            return result

        steps: list[MissionPlanStep] = []
        blocked_steps: list[str] = []
        require_confirm_steps: list[str] = []
        dry_run_only_steps: list[str] = []

        for index, template_step in enumerate(template, start=1):
            step = self._build_step(intent, index, template_step)
            steps.append(step)
            if step.status in {PLAN_BLOCKED, PLAN_UNSUPPORTED}:
                blocked_steps.append(step.step_id)
            elif step.status == PLAN_NEEDS_CONFIRM:
                require_confirm_steps.append(step.step_id)
            elif step.status == PLAN_DRY_RUN_ONLY:
                dry_run_only_steps.append(step.step_id)

        if blocked_steps:
            status = PLAN_BLOCKED
            explanation = "Plan blocked by capability validation or policy precheck."
        elif require_confirm_steps:
            status = PLAN_AWAITING_CONFIRMATION
            explanation = "Plan requires operator confirmation before lifecycle approval."
        else:
            status = PLAN_READY
            explanation = "Plan generated for dry-run validation only; Runtime must re-authorize before execution."
        plan = MissionPlan(
            plan_id=f"plan-{uuid4().hex[:12]}",
            intent_id=intent.intent_id,
            mission_type=intent.mission_type,
            steps=steps,
            status=status,
            explanation=explanation,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        result = PlanResult(
            result=status,
            failure_reason="blocked_step" if blocked_steps else None,
            plan=plan,
            validation_summary={
                "step_count": len(steps),
                "blocked_steps": blocked_steps,
                "require_confirm_steps": require_confirm_steps,
                "dry_run_only_steps": dry_run_only_steps,
            },
            policy_summary={
                "checked_steps": len([s for s in steps if s.policy_precheck is not None]),
                "denied_steps": len(blocked_steps),
                "require_confirm_steps": len(require_confirm_steps),
            },
        )
        self._audit_plan(intent=intent, result=result)
        return result

    def _build_step(self, intent: MissionIntent, index: int, template_step: TemplateStep) -> MissionPlanStep:
        capability = get_action_capability(template_step.action_type)
        step_id = f"step-{index:02d}-{template_step.action_type}"
        if capability is None:
            return MissionPlanStep(
                step_id=step_id,
                action_type=template_step.action_type,
                params=dict(template_step.params),
                required_capability=None,
                policy_precheck=None,
                status=PLAN_UNSUPPORTED,
                final_policy_check_required=True,
            )

        # Capability validation is the earliest safety boundary in planning:
        # dangerous actions are rejected before any template can become executable.
        cap_dict = self._capability_dict(capability)
        if capability.dangerous:
            return MissionPlanStep(
                step_id=step_id,
                action_type=capability.action_type,
                params=dict(template_step.params),
                expected_adapter="",
                required_capability=cap_dict,
                risk_level=capability.risk_level,
                fallback_allowed=capability.fallback_allowed,
                policy_precheck=None,
                status=PLAN_BLOCKED,
                final_policy_check_required=True,
            )

        policy_precheck = self._policy_precheck(intent, capability, step_id)
        decision = str(policy_precheck.get("decision_code", "")).lower()
        status = PLAN_READY
        if decision == "deny":
            status = PLAN_BLOCKED
        elif decision == "require_confirm":
            # Precheck is advisory for planning. It marks operator-confirm-needed,
            # but Runtime/Policy Gate must make the final decision at execution time.
            status = PLAN_NEEDS_CONFIRM
        elif not capability.supported_adapters:
            status = PLAN_DRY_RUN_ONLY

        return MissionPlanStep(
            step_id=step_id,
            action_type=capability.action_type,
            params=dict(template_step.params),
            expected_adapter=capability.supported_adapters[0] if capability.supported_adapters else "",
            required_capability=cap_dict,
            risk_level=capability.risk_level,
            fallback_allowed=capability.fallback_allowed,
            policy_precheck=policy_precheck,
            final_policy_check_required=True,
            status=status,
        )

    def _policy_precheck(self, intent: MissionIntent, capability: ActionCapability, step_id: str) -> dict[str, Any]:
        profile = build_policy_profile(intent.requested_profile)
        source = self._source_from_string(intent.source)
        ctx = PolicyContext(
            source=source,
            scope=AuthorityScope.SELF_ONLY,
            link_state=LinkState.HEALTHY,
            mission_id=intent.intent_id,
            active_profile=profile.name,
            active_controller_source=source.value,
        )
        actx = RuntimeActionContext(
            task_id=f"{intent.intent_id}-{step_id}",
            action=capability.action_type,
            risk_level=capability.risk_level,
            require_confirm=capability.requires_confirmation_by_default,
        )
        decision = unified_policy_gate(ctx, actx, profile)
        code = decision.decision_code.value if isinstance(decision.decision_code, DecisionCode) else str(decision.decision_code)
        return {
            "decision_code": code.lower(),
            "primary_reason_code": decision.primary_reason_code,
            "secondary_reason_codes": list(decision.secondary_reason_codes),
            "effective_profile_id": decision.effective_profile_id,
            "effective_scope": decision.effective_scope.value if isinstance(decision.effective_scope, AuthorityScope) else decision.effective_scope,
            "policy_trace_id": decision.policy_trace_id,
            "audit_tags": list(decision.audit_tags),
        }

    def _audit_plan(self, *, intent: MissionIntent, result: PlanResult) -> None:
        plan = result.plan
        self.audit.append(
            {
                "type": "agent_plan_created",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "mission_type": intent.mission_type,
                "plan_id": plan.plan_id if plan else None,
                "source": intent.source,
                "profile": intent.requested_profile,
                "dry_run": intent.dry_run,
                "step_count": len(plan.steps) if plan else 0,
                "blocked_steps": result.validation_summary.get("blocked_steps", []),
                "require_confirm_steps": result.validation_summary.get("require_confirm_steps", []),
                "result": result.result,
                "failure_reason": result.failure_reason,
            }
        )

    @staticmethod
    def _source_from_string(source: str) -> CommandSource:
        normalized = (source or "operator").strip().lower()
        if normalized in {"ground_station", "operator", "cli"}:
            return CommandSource.GROUND_STATION
        if normalized == "higher_command":
            return CommandSource.HIGHER_COMMAND
        if normalized == "cluster_head":
            return CommandSource.CLUSTER_HEAD
        if normalized == "delegated_peer":
            return CommandSource.DELEGATED_PEER
        return CommandSource.SELF_LOCAL

    @staticmethod
    def _capability_dict(capability: ActionCapability) -> dict[str, Any]:
        return {
            "action_type": capability.action_type,
            "domain": capability.domain,
            "skill_group": capability.skill_group,
            "risk_level": capability.risk_level,
            "supported_adapters": list(capability.supported_adapters),
            "fallback_allowed": capability.fallback_allowed,
            "allowed_link_states": list(capability.allowed_link_states),
            "requires_confirmation_by_default": capability.requires_confirmation_by_default,
            "dangerous": capability.dangerous,
            "policy_default": capability.policy_default,
            "notes": capability.notes,
        }
