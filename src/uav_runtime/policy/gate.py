"""Policy Gate v0.2 rule set.

给新同学的阅读提示：
- Policy Gate 只做“是否允许/拒绝/确认/延后/抢占”的控制面裁决。
- 它不连接飞控、不发送 MAVLink、不操作 payload，也不关心硬件厂商 SDK。
- 所有 DENY / DEFER / REQUIRE_CONFIRM / PREEMPT 必须带 primary_reason_code，
  因为 runtime 会把它写进 policy_decision_event，供 audit/replay 复盘。
- 本文件里的规则顺序很重要：先挡住授权/危险/失联边界，再处理抢占、风险和确认。
"""
from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.decision import HandoverPlan, PolicyDecisionEnvelope
from uav_runtime.policy.fallback_actions import (
    DEGRADED_REQUIRE_CONFIRM_ACTIONS,
    is_lost_link_fallback_action,
    is_unsafe_payload_action,
)
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState


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
REASON_CODE_PROFILE_RISK_EXCEEDS_MAX = "REASON_CODE_PROFILE_RISK_EXCEEDS_MAX"
REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED = "REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED"

SOURCE_PRIORITY: dict[CommandSource, int] = {
    CommandSource.GROUND_STATION: 100,
    CommandSource.HIGHER_COMMAND: 95,
    CommandSource.CLUSTER_HEAD: 80,
    CommandSource.DELEGATED_PEER: 60,
    CommandSource.SELF_LOCAL: 50,
}


def unified_policy_gate(ctx: PolicyContext, actx: RuntimeActionContext, profile: PolicyProfile) -> PolicyDecisionEnvelope:
    # 1) 身份与来源检查
    # 当前 MVP 的 CommandSource 已由调用方构造；真实系统应在进入这里前完成身份认证。
    # TODO: validate source identity / authn / authz

    # 2) 请求结构与时效检查
    # 当前 schema 已有 request_id/idempotency_key/ttl 的雏形；完整 replay-window 校验留给后续。
    # TODO: validate request shape, ttl, replay/idempotency window

    # 3) delegation 有效性检查
    # delegated_peer 不能天然控制 peer/subcluster；必须有 active delegation，且未过期/撤销/错目标。
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

    action_type = (actx.action or "").strip()

    # 危险 payload-like action 在 policy 层提前挡住。这样即使未来某个 adapter
    # 误加了映射，也不会绕过控制面禁止边界。
    if is_unsafe_payload_action(action_type):
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED,
            effective_scope=ctx.scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny", "unsafe_payload"],
        )

    # 6) scope 收缩
    # link_lost 是最强收缩：只允许 self_local + self_only + fallback allowlist。
    # 注意：这里的 ALLOW 只代表 policy 允许，不代表真实飞控动作已实现。
    effective_scope = ctx.scope
    secondary: list[str] = []
    if ctx.link_state == LinkState.LOST:
        effective_scope = "self_only"
        secondary.append(REASON_CODE_LINK_LOST_SCOPE_RESTRICTED)
        if ctx.source != CommandSource.SELF_LOCAL or ctx.scope != AuthorityScope.SELF_ONLY:
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
                secondary_reason_codes=secondary,
                effective_scope=effective_scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "link_lost", "scope"],
            )
        if not is_lost_link_fallback_action(action_type):
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
                secondary_reason_codes=secondary,
                effective_scope=effective_scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "link_lost", "fallback_required"],
            )

    # 4) source priority 计算
    # 优先级是 v0.2 最小层级：ground_station/higher_command > cluster_head >
    # delegated_peer > self_local。active_controller_source 用于判断是否反向抢占。
    source_priority = SOURCE_PRIORITY.get(ctx.source, 0)
    active_source_raw = (ctx.active_controller_source or "").strip().lower()
    active_source = next((s for s in SOURCE_PRIORITY if s.value == active_source_raw), CommandSource.SELF_LOCAL)
    active_priority = SOURCE_PRIORITY.get(active_source, 0)

    # 5) preemption 判定
    # 高优先级可以抢占低优先级；但 non_preemptible phase 只能 DEFER，由 runtime
    # 记录 pending_takeover 并等待 phase_exit 后重新评估。
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

    if ctx.link_state == LinkState.DEGRADED and (
        actx.risk_level >= profile.require_confirm_for_risk_ge or action_type in DEGRADED_REQUIRE_CONFIRM_ACTIONS
    ):
        # degraded 不等于完全失联。标准 profile 通常 require_confirm；保守 profile 可直接 deny。
        degraded_behavior = str(profile.runtime_constraints.get("degraded_high_risk", "require_confirm"))
        if degraded_behavior == "deny":
            return PolicyDecisionEnvelope(
                decision_code=DecisionCode.DENY,
                primary_reason_code=REASON_CODE_PROFILE_RISK_EXCEEDS_MAX,
                secondary_reason_codes=secondary,
                effective_scope=effective_scope,
                effective_profile_id=profile.name,
                effective_risk_level=actx.risk_level,
                policy_trace_id=f"policy-{actx.task_id}",
                audit_tags=["policy", "deny", "degraded", "profile"],
            )
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
        # recovering 阶段避免立即接管，先 DEFER 等待 handover/链路状态稳定。
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
        # lost-link 下即使是 fallback action，也不能超过 profile 允许风险上限。
        return PolicyDecisionEnvelope(
            decision_code=DecisionCode.DENY,
            primary_reason_code=REASON_CODE_PROFILE_RISK_EXCEEDS_MAX,
            secondary_reason_codes=secondary,
            effective_scope=effective_scope,
            effective_profile_id=profile.name,
            effective_risk_level=actx.risk_level,
            policy_trace_id=f"policy-{actx.task_id}",
            audit_tags=["policy", "deny"],
        )

    # 7) profile 约束检查
    # 目前只落地最小 profile 字段；如果新增 profile 行为，优先补 tests/unit/test_policy_profile_v2.py。
    # TODO: check allowed/denied skill groups, concurrency, profile policy

    # 8) target 验证
    # 目标所有权、可见性、多机范围属于后续多平台能力，不应塞进 adapter。
    # TODO: validate target_set/target ownership and scope visibility

    # 9) risk/confirmation 判定
    # max_risk_allow 是 profile 级硬上限；require_confirm 是软门槛。
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
        # 调用方主动声明需要确认时，除非 profile 明确允许免确认，否则返回 REQUIRE_CONFIRM。
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
    # 队列压力、冷却时间、deadline 等运行时限制由 RuntimeOrchestrator 更适合处理。
    # TODO: runtime queue pressure / deadline / cooldown checks

    # 11) 生成最终 decision
    # ALLOW 可以没有 primary_reason_code；非 ALLOW 必须有，这个规则在 runtime 中强校验。
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
