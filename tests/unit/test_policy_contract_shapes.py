"""policy 合同形状测试（对齐当前 gate/context/profile skeleton）。

说明：
- 这是 gate 内部 skeleton shape test，不是最终 protocol-level contract test。
- 当前仍基于 RuntimeActionContext skeleton 输入；后续 gate 输入若收敛到 ActionRequest，可同步收敛测试。
"""
from __future__ import annotations

import pytest

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.policy.gate import DECISION_REQUIRE_CONFIRM, unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState

# 冻结 registry 正式 reason code
POLICY_REASON_CONFIRMATION_REQUIRED = "POLICY_REASON_CONFIRMATION_REQUIRED"
POLICY_REASON_RISK_LIMIT_EXCEEDED = "POLICY_REASON_RISK_LIMIT_EXCEEDED"
POLICY_REASON_PREEMPT_REQUIRED = "POLICY_REASON_PREEMPT_REQUIRED"


def _to_final_reason_code(code: str | None) -> str | None:
    if code is None:
        return None
    mapping = {
        "REASON_CODE_CONFIRMATION_REQUIRED": POLICY_REASON_CONFIRMATION_REQUIRED,
        "REASON_CODE_RISK_LEVEL_EXCEEDED": POLICY_REASON_RISK_LIMIT_EXCEEDED,
        "REASON_CODE_PREEMPT_REQUIRED": POLICY_REASON_PREEMPT_REQUIRED,
    }
    return mapping.get(code, code)


def _ctx(link_state: LinkState = LinkState.HEALTHY) -> PolicyContext:
    return PolicyContext(
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        link_state=link_state,
        mission_id="m-1",
        current_phase="nominal",
        active_controller_source=CommandSource.SELF_LOCAL.value,
        active_delegations=[],
        running_actions=[],
        pending_takeovers=[],
        runtime_limits={"max_queue": 64, "max_concurrency": 1},
        active_profile="default_profile",
        flags={"test": True},
    )


def _profile(allow_without_confirm: bool = False, max_risk_when_link_lost: int = 1) -> PolicyProfile:
    return PolicyProfile(
        name="default_profile",
        allowed_skill_groups=["flight_core"],
        denied_skill_groups=[],
        max_risk_when_link_lost=max_risk_when_link_lost,
        require_confirm_for_risk_ge=3,
        allow_without_confirm=allow_without_confirm,
        max_concurrent_actions=1,
        confirm_rules=[],
        degradation_behavior={},
        fallback_behavior={},
        recovery_behavior={},
        runtime_constraints={},
    )


def test_policy_basic_allow_path_shape() -> None:
    out = unified_policy_gate(
        _ctx(),
        RuntimeActionContext(task_id="t-allow", action="hover", risk_level=1, require_confirm=False),
        _profile(allow_without_confirm=True),
    )
    assert out.decision_code == DecisionCode.ALLOW
    assert out.primary_reason_code is None
    assert out.effective_scope == AuthorityScope.SELF_ONLY
    assert out.effective_profile_id == "default_profile"


def test_policy_require_confirm_path_shape() -> None:
    out = unified_policy_gate(
        _ctx(),
        RuntimeActionContext(task_id="t-confirm", action="goto", risk_level=2, require_confirm=True),
        _profile(allow_without_confirm=False),
    )
    assert out.decision_code == DECISION_REQUIRE_CONFIRM
    assert _to_final_reason_code(out.primary_reason_code) == POLICY_REASON_CONFIRMATION_REQUIRED
    assert out.effective_scope == AuthorityScope.SELF_ONLY
    assert out.effective_profile_id == "default_profile"


def test_policy_link_lost_deny_path_shape() -> None:
    out = unified_policy_gate(
        _ctx(link_state=LinkState.LOST),
        RuntimeActionContext(task_id="t-deny", action="goto", risk_level=5, require_confirm=False),
        _profile(max_risk_when_link_lost=1),
    )
    assert out.decision_code == DecisionCode.DENY
    assert _to_final_reason_code(out.primary_reason_code) == POLICY_REASON_RISK_LIMIT_EXCEEDED
    assert out.effective_scope == "self_only"
    assert out.effective_profile_id == "default_profile"


def test_preempt_contract_shape_path() -> None:
    env = PolicyDecisionEnvelope(
        decision_code=DecisionCode.PREEMPT,
        primary_reason_code=POLICY_REASON_PREEMPT_REQUIRED,
        handover_plan=HandoverPlan(mode="none"),
    )
    with pytest.raises(ValueError):
        env.validate_preempt_contract()
