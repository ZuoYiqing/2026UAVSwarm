"""协议与决策数据模型对齐测试（按当前冻结 contract 字段命名）。

说明：
- PolicyDecisionEnvelope 是当前 policy 层权威对象。
- schema.PolicyDecision 是协议/兼容视图；后续可收敛到单一权威对象。
"""
from __future__ import annotations

import pytest

from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.protocol.enums import DecisionCode, MessageType
from uav_runtime.protocol.schema import Envelope, PolicyDecision
from uav_runtime.protocol.validation import validate_envelope_instance


def test_minimal_valid_envelope_contains_contract_fields() -> None:
    env = Envelope(
        message_type=MessageType.ACTION_REQUEST,
        protocol_version="1.0",
        schema_id="uav_runtime.envelope.v1",
        message_id="msg-001",
        trace_id="trace-001",
        mission_id="mission-001",
        source="ground_station",
        target="runtime",
        payload={"k": "v"},
    )
    validate_envelope_instance(env)
    d = env.to_dict()
    assert d["protocol_version"] == "1.0"
    assert d["schema_id"] == "uav_runtime.envelope.v1"
    assert d["message_id"] == "msg-001"
    assert d["trace_id"] == "trace-001"
    assert d["mission_id"] == "mission-001"
    assert d["source"] == "ground_station"
    assert d["target"] == "runtime"
    assert isinstance(d["timestamp"], str)
    assert d["payload"] == {"k": "v"}


def test_policy_decision_uses_new_field_names() -> None:
    d = PolicyDecision(
        decision_code=DecisionCode.DENY,
        primary_reason_code="REASON_CODE_RISK_LEVEL_EXCEEDED",
        secondary_reason_codes=["REASON_CODE_LINK_LOST_SCOPE_RESTRICTED"],
        handover_plan={"mode": "none"},
    )
    assert d.decision_code == DecisionCode.DENY
    assert d.primary_reason_code == "REASON_CODE_RISK_LEVEL_EXCEEDED"
    assert d.secondary_reason_codes == ["REASON_CODE_LINK_LOST_SCOPE_RESTRICTED"]


def test_preempt_without_handover_plan_fails() -> None:
    env = PolicyDecisionEnvelope(
        decision_code=DecisionCode.PREEMPT,
        primary_reason_code="REASON_CODE_PREEMPT_REQUIRED",
        handover_plan=HandoverPlan(mode="none"),
    )
    with pytest.raises(ValueError):
        env.validate_preempt_contract()


def test_preempt_with_valid_handover_modes_passes() -> None:
    for mode in ["abort", "suspend", "enqueue_after", "wait_until_safe_handover"]:
        env = PolicyDecisionEnvelope(
            decision_code=DecisionCode.PREEMPT,
            primary_reason_code="REASON_CODE_PREEMPT_REQUIRED",
            handover_plan=HandoverPlan(mode=mode),
        )
        env.validate_preempt_contract()
