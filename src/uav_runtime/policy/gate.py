"""本轮修补点：reason/decision code 风格对齐 registry 形态，ALLOW 主因置空，REQUIRE_CONFIRM 常量化。"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import DecisionCode, LinkState


# decision-code constants for non-enum contract branches
DECISION_REQUIRE_CONFIRM = "REQUIRE_CONFIRM"
DECISION_DEFER = "DEFER"

# registry-style reason code skeletons (no free-form strings)
REASON_LINK_LOST_SCOPE_RESTRICTED = "REASON.LINK.LOST.SCOPE_RESTRICTED"
REASON_CONFIRM_REQUIRED = "REASON.CONFIRMATION.REQUIRED"
REASON_RISK_EXCEEDED = "REASON.RISK.EXCEEDED"


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
        secondary.append(REASON_LINK_LOST_SCOPE_RESTRICTED)

    # 7) profile 约束检查
    # TODO: check allowed/denied skill groups, concurrency, profile policy

    # 8) target 验证
    # TODO: validate target_set/target ownership and scope visibility

    # 9) risk/confirmation 判定
    if actx.risk_level > profile.max_risk_when_link_lost and ctx.link_state == LinkState.LOST:
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_RISK_EXCEEDED,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny"],
        )

    if actx.require_confirm and not profile.allow_without_confirm:
        return PolicyDecisionEnvelope(
            decision_code=DECISION_REQUIRE_CONFIRM,
            primary_reason_code=REASON_CONFIRM_REQUIRED,
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
        primary_reason_code=None,
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
