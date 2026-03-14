"""协议形状与决策校验（含 PREEMPT 约束）单测骨架。"""
from __future__ import annotations

import pytest

from uav_runtime.protocol.enums import DecisionCode, MessageType
from uav_runtime.protocol.schema import Envelope, PolicyDecision
from uav_runtime.protocol.validation import validate_envelope_instance, validate_policy_decision


def test_envelope_shape_ok() -> None:
    env = Envelope(message_type=MessageType.ACTION_REQUEST, trace_id="t-1")
    validate_envelope_instance(env)


def test_preempt_requires_target() -> None:
    with pytest.raises(ValueError):
        validate_policy_decision(PolicyDecision(decision=DecisionCode.PREEMPT, primary_reason="prio"))


def test_preempt_requires_handover_plan() -> None:
    with pytest.raises(ValueError):
        validate_policy_decision(
            PolicyDecision(
                decision=DecisionCode.PREEMPT,
                primary_reason="prio",
                preempt_target_task_id="task-1",
            )
        )


def test_preempt_with_handover_plan_ok() -> None:
    validate_policy_decision(
        PolicyDecision(
            decision=DecisionCode.PREEMPT,
            primary_reason="prio",
            preempt_target_task_id="task-1",
            handover_plan={"mode": "suspend_then_takeover"},
        )
    )
