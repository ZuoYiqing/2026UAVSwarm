from __future__ import annotations

from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.fallback_actions import LOST_LINK_FALLBACK_ACTIONS, is_lost_link_fallback_action
from uav_runtime.policy.gate import (
    DECISION_REQUIRE_CONFIRM,
    REASON_CODE_DEGRADED_CONFIRM_REQUIRED,
    REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
    REASON_CODE_PROFILE_RISK_EXCEEDS_MAX,
    REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED,
    unified_policy_gate,
)
from uav_runtime.policy.profile import build_policy_profile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState


def _ctx(*, link: LinkState = LinkState.LOST, scope: AuthorityScope = AuthorityScope.SELF_ONLY) -> PolicyContext:
    return PolicyContext(
        source=CommandSource.SELF_LOCAL,
        scope=scope,
        link_state=link,
        mission_id="m-profile-v2",
        current_phase="nominal",
        active_controller_source=CommandSource.SELF_LOCAL.value,
        active_delegations=[],
        flags={},
    )


def _act(action: str, risk: int = 1) -> RuntimeActionContext:
    return RuntimeActionContext(task_id="profile-v2", action=action, risk_level=risk, require_confirm=False)


def test_lost_link_profile_hold_position_self_local_allows() -> None:
    out = unified_policy_gate(_ctx(), _act("hold_position"), build_policy_profile("lost_link"))

    assert out.decision_code == DecisionCode.ALLOW
    assert out.primary_reason_code is None
    assert out.effective_profile_id == "lost_link"


def test_lost_link_profile_return_home_self_local_allows() -> None:
    out = unified_policy_gate(_ctx(), _act("return_home"), build_policy_profile("lost_link"))

    assert out.decision_code == DecisionCode.ALLOW
    assert out.primary_reason_code is None


def test_lost_link_profile_goto_denies_non_fallback() -> None:
    out = unified_policy_gate(_ctx(), _act("goto"), build_policy_profile("lost_link"))

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED


def test_lost_link_peer_control_scope_denied() -> None:
    out = unified_policy_gate(
        _ctx(scope=AuthorityScope.PEER_CONTROL_LIMITED),
        _act("hold_position"),
        build_policy_profile("lost_link"),
    )

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED


def test_standard_degraded_high_risk_requires_confirm() -> None:
    out = unified_policy_gate(
        _ctx(link=LinkState.DEGRADED),
        _act("goto", risk=3),
        build_policy_profile("standard"),
    )

    assert out.decision_code == DECISION_REQUIRE_CONFIRM
    assert out.primary_reason_code == REASON_CODE_DEGRADED_CONFIRM_REQUIRED


def test_conservative_degraded_high_risk_denies() -> None:
    out = unified_policy_gate(
        _ctx(link=LinkState.DEGRADED),
        _act("goto", risk=3),
        build_policy_profile("conservative"),
    )

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_PROFILE_RISK_EXCEEDS_MAX


def test_unknown_action_under_lost_link_denied() -> None:
    out = unified_policy_gate(_ctx(), _act("unknown_action"), build_policy_profile("lost_link"))

    assert out.decision_code == DecisionCode.DENY
    assert out.primary_reason_code == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED


def test_unsafe_payload_actions_denied_before_adapter() -> None:
    for action in ["payload_release", "drop", "strike", "attack", "deploy"]:
        out = unified_policy_gate(_ctx(link=LinkState.HEALTHY), _act(action), build_policy_profile("standard"))
        assert out.decision_code == DecisionCode.DENY
        assert out.primary_reason_code == REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED


def test_lost_link_fallback_taxonomy_has_expected_minimal_actions() -> None:
    assert {"hold_position", "return_home", "land_safe", "health_query", "sensor_read", "camera_capture"}.issubset(
        LOST_LINK_FALLBACK_ACTIONS
    )
    assert is_lost_link_fallback_action("goto") is False
    assert is_lost_link_fallback_action("payload_release") is False
