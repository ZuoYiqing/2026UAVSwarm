"""本轮最后修补点：reason code 全量切换为冻结 registry 正式 code 形态，移除 POLICY_REASON_* 临时命名。"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import CommandSource, DecisionCode, LinkState


# decision-code constants for non-enum contract branches
DECISION_REQUIRE_CONFIRM = "REQUIRE_CONFIRM"
DECISION_DEFER = "DEFER"

# frozen registry reason codes (authoritative naming style)
REASON_CODE_LINK_LOST_SCOPE_RESTRICTED = "REASON_CODE_LINK_LOST_SCOPE_RESTRICTED"
REASON_CODE_CONFIRMATION_REQUIRED = "REASON_CODE_CONFIRMATION_REQUIRED"
REASON_CODE_RISK_LEVEL_EXCEEDED = "REASON_CODE_RISK_LEVEL_EXCEEDED"
REASON_CODE_DELEGATION_REQUIRED = "REASON_CODE_DELEGATION_REQUIRED"
REASON_CODE_DELEGATION_INVALID = "REASON_CODE_DELEGATION_INVALID"
REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED = "REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED"
REASON_CODE_PREEMPT_NON_PREEMPTIBLE = "REASON_CODE_PREEMPT_NON_PREEMPTIBLE"
REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED = "REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED"
REASON_CODE_PREEMPT_GRANTED = "REASON_CODE_PREEMPT_GRANTED"
REASON_CODE_DEGRADED_CONFIRM_REQUIRED = "REASON_CODE_DEGRADED_CONFIRM_REQUIRED"
REASON_CODE_RECOVERING_DEFER = "REASON_CODE_RECOVERING_DEFER"

SOURCE_PRIORITY: dict[CommandSource, int] = {
    CommandSource.GROUND_STATION: 100,
    CommandSource.HIGHER_COMMAND: 95,
    CommandSource.CLUSTER_HEAD: 80,
    CommandSource.DELEGATED_PEER: 60,
    CommandSource.SELF_LOCAL: 50,
}


def unified_policy_gate(ctx: PolicyContext, actx: RuntimeActionContext, profile: PolicyProfile) -> PolicyDecisionEnvelope:
    # 1) 身份与来源检查
    # TODO: validate source identity / authn / authz

    # 2) 请求结构与时效检查
    # TODO: validate request shape, ttl, replay/idempotency window

    # 3) delegation 有效性检查
    if ctx.source == CommandSource.DELEGATED_PEER and ctx.scope != "self_only":
        if not ctx.active_delegations:
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_DELEGATION_REQUIRED,
                effective_scope=ctx.scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "delegation"],
            )
        if (
            bool(ctx.flags.get("delegation_expired"))
            or bool(ctx.flags.get("delegation_revoked"))
            or bool(ctx.flags.get("delegation_target_mismatch"))
        ):
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_DELEGATION_INVALID,
                effective_scope=ctx.scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "delegation"],
            )

    # 6) scope 收缩
    effective_scope = ctx.scope
    secondary: list[str] = []
    if ctx.link_state == LinkState.LOST:
        effective_scope = "self_only"
        secondary.append(REASON_CODE_LINK_LOST_SCOPE_RESTRICTED)
        if ctx.source != CommandSource.SELF_LOCAL:
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
                secondary_reason_codes=secondary,
                effective_scope=effective_scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "link_lost"],
            )

    # 4) source priority 计算
    source_priority = SOURCE_PRIORITY.get(ctx.source, 0)
    active_source_raw = (ctx.active_controller_source or "").strip().lower()
    active_source = next((s for s in SOURCE_PRIORITY if s.value == active_source_raw), CommandSource.SELF_LOCAL)
    active_priority = SOURCE_PRIORITY.get(active_source, 0)

    # 5) preemption 判定
    if source_priority > active_priority:
        non_preemptible = tuple(profile.runtime_constraints.get("non_preemptible_phases", ()))
        if ctx.current_phase in non_preemptible:
            return PolicyDecisionEnvelope(
                decision_code=DECISION_DEFER,
                primary_reason_code=REASON_CODE_PREEMPT_NON_PREEMPTIBLE,
                effective_scope=ctx.scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "defer", "preempt"],
            )
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.PREEMPT,
            primary_reason_code=REASON_CODE_PREEMPT_GRANTED,
            effective_scope=ctx.scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            handover_plan=HandoverPlan(mode="suspend"),
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "preempt"],
        )
    if source_priority < active_priority and ctx.source != active_source:
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED,
            effective_scope=ctx.scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny", "preempt"],
        )

    if ctx.link_state == LinkState.DEGRADED and actx.risk_level >= profile.require_confirm_for_risk_ge:
        return PolicyDecisionEnvelope(
            decision_code=DECISION_REQUIRE_CONFIRM,
            primary_reason_code=REASON_CODE_DEGRADED_CONFIRM_REQUIRED,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "require_confirm", "degraded"],
        )

    if bool(ctx.flags.get("recovering")) or ctx.current_phase == "recovering":
        return PolicyDecisionEnvelope(
            decision_code=DECISION_DEFER,
            primary_reason_code=REASON_CODE_RECOVERING_DEFER,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "defer", "recovering"],
        )

    if ctx.link_state == LinkState.LOST and actx.risk_level > profile.max_risk_when_link_lost:
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_CODE_RISK_LEVEL_EXCEEDED,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny"],
        )

    # 7) profile 约束检查
    # TODO: check allowed/denied skill groups, concurrency, profile policy

    # 8) target 验证
    # TODO: validate target_set/target ownership and scope visibility

    # 9) risk/confirmation 判定
    max_risk = int(profile.runtime_constraints.get("max_risk_allow", 10))
    if actx.risk_level > max_risk:
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_CODE_RISK_LEVEL_EXCEEDED,
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
            primary_reason_code=REASON_CODE_CONFIRMATION_REQUIRED,
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
