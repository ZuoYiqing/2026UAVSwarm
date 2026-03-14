"""unified_policy_gate 唯一裁决入口（固定步骤 TODO + skeleton 路径）。"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import PolicyDecisionEnvelope
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import DecisionCode, LinkState


def unified_policy_gate(ctx: PolicyContext, actx: RuntimeActionContext, profile: PolicyProfile) -> PolicyDecisionEnvelope:
    # 1) 基础授权检查（source/scope/delegation）
    # 2) 链路状态约束收缩（degraded/lost）
    # 3) 风险与确认策略
    # 4) 抢占合法性检查
    # 5) 形成标准化决策输出
    if ctx.link_state == LinkState.LOST and actx.risk_level > profile.max_risk_when_link_lost:
        return PolicyDecisionEnvelope(DecisionCode.DENY, reason="link_lost_risk_exceeded")
    if actx.require_confirm and not profile.allow_without_confirm:
        return PolicyDecisionEnvelope(DecisionCode.DENY, reason="confirm_required")
    return PolicyDecisionEnvelope(DecisionCode.ALLOW, reason=None)
