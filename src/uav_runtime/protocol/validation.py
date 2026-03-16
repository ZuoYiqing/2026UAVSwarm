"""协议形状校验、PREEMPT 约束、ALLOW 主因可空约束入口。"""
from __future__ import annotations

from .enums import DecisionCode
from .schema import Envelope, PolicyDecision


REQUIRED_ENVELOPE_KEYS = {"message_type", "trace_id", "timestamp", "payload"}


def validate_envelope_shape(raw: dict) -> None:
    missing = REQUIRED_ENVELOPE_KEYS - set(raw.keys())
    if missing:
        raise ValueError(f"missing envelope keys: {sorted(missing)}")


def validate_policy_decision(decision: PolicyDecision) -> None:
    if decision.decision == DecisionCode.PREEMPT:
        if not decision.preempt_target_task_id:
            raise ValueError("PREEMPT requires preempt_target_task_id")
        if not decision.handover_plan:
            raise ValueError("PREEMPT requires handover_plan")
    if decision.decision == DecisionCode.ALLOW:
        return
    if not decision.primary_reason:
        raise ValueError("DENY/PREEMPT requires primary_reason")


def validate_envelope_instance(env: Envelope) -> None:
    validate_envelope_shape(env.to_dict())
