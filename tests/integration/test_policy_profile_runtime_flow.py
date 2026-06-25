"""Policy Profile v0.2 runtime/audit/replay integration tests."""
from __future__ import annotations

import json

from uav_runtime.policy.gate import (
    REASON_CODE_DEGRADED_CONFIRM_REQUIRED,
    REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED,
    REASON_CODE_LINK_LOST_SCOPE_RESTRICTED,
    REASON_CODE_PROFILE_RISK_EXCEEDS_MAX,
    REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED,
)
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last


def _read_audit_events(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize(value: str | None) -> str | None:
    return value.upper() if isinstance(value, str) else value


def _request(
    action: str,
    *,
    link_state: str = "healthy",
    risk_hint: int = 1,
    skill_group: str = "flight_core",
) -> ActionRequest:
    return ActionRequest(
        action=action,
        params={"demo_link_state": link_state},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id=f"req-profile-{action}-{link_state}-{risk_hint}",
        mission_id="mission-profile-v2",
        action_type=action,
        skill_group=skill_group,
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=risk_hint,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key=f"idem-profile-{action}-{link_state}-{risk_hint}",
    )


def _latest_policy_event(path) -> dict:
    events = _read_audit_events(path)
    decision_events = [event for event in events if event.get("type") == "policy_decision_event"]
    assert decision_events
    return decision_events[-1]


def test_lost_link_fallback_hold_position_allow_is_visible_in_runtime_audit_replay(tmp_path) -> None:
    audit = tmp_path / "profile_lost_link_hold.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), policy_profile_name="lost_link")

    res = rt.handle_action_request(_request("hold_position", link_state="lost"))

    assert res["accepted"] is True
    assert res["status"] == "accepted"
    assert res["adapter"] == "fake"

    decision = _latest_policy_event(audit)
    assert _normalize(decision["decision_code"]) == "ALLOW"
    assert decision["primary_reason_code"] is None
    assert decision["effective_profile_id"] == "lost_link"
    assert decision["effective_scope"] == "self_only"
    assert REASON_CODE_LINK_LOST_SCOPE_RESTRICTED in decision["secondary_reason_codes"]
    assert decision["policy_trace_id"]
    assert "allow" in decision["audit_tags"]

    replayed = replay_last(str(audit), n=5)
    assert any(event.get("type") == "policy_decision_event" and event.get("effective_profile_id") == "lost_link" for event in replayed)


def test_lost_link_non_fallback_goto_deny_is_visible_in_runtime_audit_replay(tmp_path) -> None:
    audit = tmp_path / "profile_lost_link_goto.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), policy_profile_name="lost_link")

    res = rt.handle_action_request(_request("goto", link_state="lost"))

    assert res["accepted"] is False
    assert res["status"] == "blocked"
    assert res["code"] == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED

    events = _read_audit_events(audit)
    decision = _latest_policy_event(audit)
    assert _normalize(decision["decision_code"]) == "DENY"
    assert decision["primary_reason_code"] == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED
    assert decision["effective_profile_id"] == "lost_link"
    assert decision["effective_scope"] == "self_only"
    assert REASON_CODE_LINK_LOST_SCOPE_RESTRICTED in decision["secondary_reason_codes"]
    assert [event for event in events if event.get("type") == "action_result"] == []

    replayed = replay_last(str(audit), n=5)
    assert replayed[-1]["primary_reason_code"] == REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED


def test_unsafe_payload_like_action_deny_is_visible_and_skips_adapter(tmp_path) -> None:
    audit = tmp_path / "profile_unsafe_payload.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), adapter_name="payload", policy_profile_name="standard")

    res = rt.handle_action_request(_request("payload_release", skill_group="payload"))

    assert res["accepted"] is False
    assert res["status"] == "blocked"
    assert res["code"] == REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED
    assert res["adapter"] == ""

    events = _read_audit_events(audit)
    decision = _latest_policy_event(audit)
    assert _normalize(decision["decision_code"]) == "DENY"
    assert decision["primary_reason_code"] == REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED
    assert decision["effective_profile_id"] == "standard"
    assert [event for event in events if event.get("type") == "action_result"] == []


def test_degraded_high_risk_standard_profile_requires_confirm_in_runtime(tmp_path) -> None:
    audit = tmp_path / "profile_degraded_standard.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), policy_profile_name="standard")

    res = rt.handle_action_request(_request("goto", link_state="degraded", risk_hint=3))

    assert res["accepted"] is False
    assert res["status"] == "waiting_confirmation"
    assert res["code"] == REASON_CODE_DEGRADED_CONFIRM_REQUIRED

    decision = _latest_policy_event(audit)
    assert _normalize(decision["decision_code"]) == "REQUIRE_CONFIRM"
    assert decision["primary_reason_code"] == REASON_CODE_DEGRADED_CONFIRM_REQUIRED
    assert decision["effective_profile_id"] == "standard"
    assert decision["effective_scope"] == "self_only"


def test_degraded_high_risk_conservative_profile_denies_in_runtime(tmp_path) -> None:
    audit = tmp_path / "profile_degraded_conservative.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), policy_profile_name="conservative")

    res = rt.handle_action_request(_request("goto", link_state="degraded", risk_hint=3))

    assert res["accepted"] is False
    assert res["status"] == "blocked"
    assert res["code"] == REASON_CODE_PROFILE_RISK_EXCEEDS_MAX

    decision = _latest_policy_event(audit)
    assert _normalize(decision["decision_code"]) == "DENY"
    assert decision["primary_reason_code"] == REASON_CODE_PROFILE_RISK_EXCEEDS_MAX
    assert decision["effective_profile_id"] == "conservative"
    assert decision["effective_scope"] == "self_only"
