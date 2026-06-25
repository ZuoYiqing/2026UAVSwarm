from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import (
    DECISION_DEFER,
    DECISION_REQUIRE_CONFIRM,
    REASON_CODE_CONFIRMATION_REQUIRED,
    REASON_CODE_DEGRADED_CONFIRM_REQUIRED,
    REASON_CODE_DELEGATION_INVALID,
    REASON_CODE_DELEGATION_REQUIRED,
    REASON_CODE_PREEMPT_NON_PREEMPTIBLE,
    REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED,
    REASON_CODE_PREEMPT_GRANTED,
    REASON_CODE_RISK_LEVEL_EXCEEDED,
    REASON_CODE_SKILL_GROUP_DENIED,
    REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
    unified_policy_gate,
)
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState


def _profile() -> PolicyProfile:
    return PolicyProfile(
        name="p-default",
        max_risk_when_link_lost=1,
        require_confirm_for_risk_ge=3,
        allow_without_confirm=False,
        runtime_constraints={"non_preemptible_phases": ["critical"], "max_risk_allow": 4},
    )


def _act(
    risk: int = 1,
    require_confirm: bool = False,
    action: str = "hover",
    skill_group: str = "flight_core",
) -> RuntimeActionContext:
    return RuntimeActionContext(
        task_id="t1",
        action=action,
        risk_level=risk,
        require_confirm=require_confirm,
        skill_group=skill_group,
    )


def _ctx(source: CommandSource, *, link: LinkState = LinkState.HEALTHY, scope: AuthorityScope = AuthorityScope.SELF_ONLY) -> PolicyContext:
    return PolicyContext(
        source=source,
        scope=scope,
        link_state=link,
        mission_id="m1",
        current_phase="nominal",
        active_controller_source=CommandSource.SELF_LOCAL.value,
        active_delegations=[],
        flags={},
    )


def test_ground_station_can_preempt_self_local() -> None:
    ctx = _ctx(CommandSource.GROUND_STATION)
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DecisionCode.PREEMPT
    assert out.primary_reason_code == REASON_CODE_PREEMPT_GRANTED


def test_delegated_peer_without_delegation_is_denied() -> None:
    ctx = _ctx(CommandSource.DELEGATED_PEER, scope=AuthorityScope.PEER_CONTROL_LIMITED)
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_DELEGATION_REQUIRED


def test_delegation_expired_is_denied() -> None:
    ctx = _ctx(CommandSource.DELEGATED_PEER, scope=AuthorityScope.PEER_CONTROL_LIMITED)
    ctx.active_delegations = ["dg-1"]
    ctx.flags["delegation_expired"] = True
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_DELEGATION_INVALID


def test_link_lost_non_fallback_source_denied() -> None:
    ctx = _ctx(CommandSource.CLUSTER_HEAD, link=LinkState.LOST)
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED


def test_link_lost_self_local_fallback_allow() -> None:
    ctx = _ctx(CommandSource.SELF_LOCAL, link=LinkState.LOST)
    out = unified_policy_gate(ctx, _act(risk=1, action="hold_position"), _profile())
    assert out.decision_code == DecisionCode.ALLOW


def test_non_preemptible_phase_causes_defer() -> None:
    ctx = _ctx(CommandSource.GROUND_STATION)
    ctx.current_phase = "critical"
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DECISION_DEFER
    assert out.primary_reason_code == REASON_CODE_PREEMPT_NON_PREEMPTIBLE


def test_high_risk_over_profile_is_denied() -> None:
    ctx = _ctx(CommandSource.SELF_LOCAL)
    out = unified_policy_gate(ctx, _act(risk=5), _profile())
    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_RISK_LEVEL_EXCEEDED


def test_require_confirm_reason_code_is_stable() -> None:
    ctx = _ctx(CommandSource.SELF_LOCAL)
    out = unified_policy_gate(ctx, _act(risk=1, require_confirm=True), _profile())
    assert out.decision_code == DECISION_REQUIRE_CONFIRM
    assert out.primary_reason_code == REASON_CODE_CONFIRMATION_REQUIRED


def test_reverse_hierarchy_preempt_is_denied() -> None:
    ctx = _ctx(CommandSource.SELF_LOCAL)
    ctx.active_controller_source = CommandSource.GROUND_STATION.value
    out = unified_policy_gate(ctx, _act(), _profile())
    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED


def test_degraded_high_risk_requires_confirm() -> None:
    ctx = _ctx(CommandSource.SELF_LOCAL, link=LinkState.DEGRADED)
    out = unified_policy_gate(ctx, _act(risk=3), _profile())
    assert out.decision_code == DECISION_REQUIRE_CONFIRM
    assert out.primary_reason_code == REASON_CODE_DEGRADED_CONFIRM_REQUIRED


def test_profile_allowed_skill_groups_denies_unknown_operational_lane() -> None:
    profile = _profile()
    profile.allowed_skill_groups = ["flight_core"]
    ctx = _ctx(CommandSource.SELF_LOCAL)

    out = unified_policy_gate(ctx, _act(action="health_query", skill_group="payload"), profile)

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_SKILL_GROUP_DENIED


def test_profile_denied_skill_groups_blocks_payload_lane() -> None:
    profile = _profile()
    profile.denied_skill_groups = ["payload"]
    ctx = _ctx(CommandSource.SELF_LOCAL)

    out = unified_policy_gate(ctx, _act(action="health_query", skill_group="payload"), profile)

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_SKILL_GROUP_DENIED
