"""为什么要这样修：把 unified_policy_gate 对齐为固定步骤 skeleton，并输出 registry 风格 reason code。"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import DecisionCode, LinkState


# frozen-style reason code skeletons (registry-backed in later phase)
RC_OK = "POLICY.OK"
RC_LINK_LOST_SCOPE_SHRUNK = "POLICY.LINK.LOST.SCOPE_SHRUNK"
RC_CONFIRM_REQUIRED = "POLICY.CONFIRM.REQUIRED"
RC_RISK_EXCEEDED = "POLICY.RISK.EXCEEDED"
RC_PREEMPT_APPLIED = "POLICY.PREEMPT.APPLIED"


def unified_policy_gate(ctx: PolicyContext, actx: RuntimeActionContext, profile: PolicyProfile) -> PolicyDecisionEnvelope:
    # 1) 身份与来源检查
    # TODO: validate source identity / authn / authz

    # 2) 请求结构与时效检查
    # TODO: validate request shape, ttl, replay/idempotency window

    # 3) delegation 有效性检查
    # TODO: validate delegation grant and revocation status

    # 4) source priority 计算
    # TODO: map source->priority and produce comparable rank

    # 5) preemption 判定
    # TODO: decide whether preempt is required/permitted

    # 6) scope 收缩
    effective_scope = ctx.scope
    secondary: list[str] = []
    if ctx.link_state == LinkState.LOST:
        effective_scope = "self_only"
        secondary.append(RC_LINK_LOST_SCOPE_SHRUNK)

    # 7) profile 约束检查
    # TODO: check allowed/denied skill groups, concurrency, profile policy

    # 8) target 验证
    # TODO: validate target_set/target ownership and scope visibility

    # 9) risk/confirmation 判定
    if actx.risk_level > profile.max_risk_when_link_lost and ctx.link_state == LinkState.LOST:
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=RC_RISK_EXCEEDED,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny"],
        )

    if actx.require_confirm and not profile.allow_without_confirm:
        return PolicyDecisionEnvelope(
            decision_code="require_confirm",
            primary_reason_code=RC_CONFIRM_REQUIRED,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "require_confirm"],
        )

    # 10) runtime constraints
    # TODO: runtime queue pressure / deadline / cooldown checks

    # 11) 生成最终 decision
    decision = PolicyDecisionEnvelope(
        decision_code=DecisionCode.ALLOW,
        primary_reason_code=RC_OK,
        secondary_reason_codes=secondary,
        effective_scope=effective_scope,
        effective_profile_id=profile.name,
        effective_risk_level=actx.risk_level,
        enforced_constraints=["deterministic_adapter_path"],
        handover_plan=HandoverPlan(mode="none"),
        policy_trace_id=f"policy-{actx.task_id}",
        audit_tags=["policy", "allow"],
    )

    # 12) 审计封装
    # TODO: include registry refs + normalized audit envelope
    return decision
