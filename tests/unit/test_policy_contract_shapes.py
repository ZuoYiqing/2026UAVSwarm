"""policy 合同形状测试骨架（allow/deny TODO）。"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState


def test_policy_allow_basic() -> None:
    ctx = PolicyContext(CommandSource.SELF_LOCAL, AuthorityScope.SELF_ONLY, LinkState.HEALTHY)
    actx = RuntimeActionContext(task_id="t1", action="hover", risk_level=1)
    profile = PolicyProfile(name="p1", allow_without_confirm=True)
    out = unified_policy_gate(ctx, actx, profile)
    assert out.decision == DecisionCode.ALLOW
