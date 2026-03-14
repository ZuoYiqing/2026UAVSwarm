"""本轮修补点：对齐 handover mode 术语，并保留 PREEMPT 合同校验入口。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from uav_runtime.protocol.enums import AuthorityScope, DecisionCode


@dataclass(slots=True)
class HandoverPlan:
    mode: Literal[
        "none",
        "abort",
        "suspend",
        "enqueue_after",
        "wait_until_safe_handover",
    ] = "none"
    takeover_target_request_id: str | None = None
    resume_policy: str | None = None
    wait_condition: str | None = None


@dataclass(slots=True)
class PolicyDecisionEnvelope:
    decision_code: DecisionCode | str
    primary_reason_code: str | None = None
    secondary_reason_codes: list[str] = field(default_factory=list)
    error_code: str | None = None
    effective_scope: AuthorityScope | str | None = None
    effective_profile_id: str | None = None
    effective_risk_level: int | None = None
    enforced_constraints: list[str] = field(default_factory=list)
    handover_plan: HandoverPlan = field(default_factory=HandoverPlan)
    policy_trace_id: str = ""
    audit_tags: list[str] = field(default_factory=list)

    @property
    def decision(self) -> DecisionCode | str:
        return self.decision_code

    @property
    def reason(self) -> str | None:
        return self.primary_reason_code

    def validate_preempt_contract(self) -> None:
        decision = self.decision_code.value if isinstance(self.decision_code, DecisionCode) else self.decision_code
        if decision == DecisionCode.PREEMPT.value and self.handover_plan.mode == "none":
            raise ValueError("PREEMPT requires non-none handover_plan.mode")
