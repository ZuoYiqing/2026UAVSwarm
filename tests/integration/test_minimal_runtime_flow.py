"""最小 runtime 集成链路测试（对齐当前 ActionRequest 与 decision 分支语义）。"""
from __future__ import annotations

import json

from uav_runtime.policy.gate import REASON_CODE_CONFIRMATION_REQUIRED, REASON_CODE_RISK_LEVEL_EXCEEDED
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator


def _read_audit_events(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize_decision_code(value: str | None) -> str | None:
    if value is None:
        return None
    # 待收敛点：当前代码里 enum 路径为小写("allow")，常量路径为大写("REQUIRE_CONFIRM")。
    # 测试先按最终推荐形式统一到大写比较。
    return value.upper()


def test_minimal_runtime_allow_flow(tmp_path) -> None:
    audit = tmp_path / "runtime.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))

    req = ActionRequest(
        action="hover",
        params={"duration_s": 3},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id="req-allow-001",
        mission_id="mission-allow-001",
        action_type="hover",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key="idem-allow-001",
    )

    res = rt.handle_action_request(req)

    assert res["request_id"] == "req-allow-001"
    assert res["accepted"] is True
    assert res["status"] in {"accepted", "executed"}
    assert audit.exists()

    events = _read_audit_events(audit)
    decision_events = [e for e in events if e.get("type") == "policy_decision_event"]
    assert decision_events
    last = decision_events[-1]
    assert _normalize_decision_code(last.get("decision_code")) == "ALLOW"
    assert last.get("policy_trace_id")
    assert last.get("effective_profile_id") == "default_profile"
    assert last.get("effective_scope") == "self_only"


def test_minimal_runtime_require_confirm_flow(tmp_path) -> None:
    audit = tmp_path / "runtime_confirm.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))

    req = ActionRequest(
        action="goto",
        params={"x": 1, "y": 2},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id="req-confirm-001",
        mission_id="mission-confirm-001",
        action_type="goto",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=True,
        idempotency_key="idem-confirm-001",
    )

    res = rt.handle_action_request(req)

    assert res["request_id"] == "req-confirm-001"
    assert res["status"] == "waiting_confirmation"
    assert res["accepted"] is False
    assert res["code"] == REASON_CODE_CONFIRMATION_REQUIRED
    assert audit.exists()

    events = _read_audit_events(audit)
    decision_events = [e for e in events if e.get("type") == "policy_decision_event"]
    assert decision_events
    last = decision_events[-1]
    assert _normalize_decision_code(last.get("decision_code")) == "REQUIRE_CONFIRM"
    assert last.get("primary_reason_code") == REASON_CODE_CONFIRMATION_REQUIRED
    assert last.get("effective_scope") == "self_only"


def test_minimal_runtime_deny_flow_link_lost_high_risk(tmp_path) -> None:
    audit = tmp_path / "runtime_deny.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))

    req = ActionRequest(
        action="goto",
        params={"x": 1, "y": 2, "demo_link_state": "lost"},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id="req-deny-001",
        mission_id="mission-deny-001",
        action_type="goto",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=5,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key="idem-deny-001",
    )

    res = rt.handle_action_request(req)

    assert res["request_id"] == "req-deny-001"
    assert res["status"] == "blocked"
    assert res["accepted"] is False
    assert res["code"] == REASON_CODE_RISK_LEVEL_EXCEEDED

    events = _read_audit_events(audit)
    decision_events = [e for e in events if e.get("type") == "policy_decision_event"]
    action_results = [e for e in events if e.get("type") == "action_result"]

    assert decision_events
    last = decision_events[-1]
    assert _normalize_decision_code(last.get("decision_code")) == "DENY"
    assert last.get("effective_scope") == "self_only"
    assert action_results == []


def test_runtime_with_explicit_mavlink_adapter_returns_unavailable(tmp_path) -> None:
    audit = tmp_path / "runtime_mavlink.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), adapter_name="mavlink")

    req = ActionRequest(
        action="takeoff",
        params={},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id="req-mavlink-001",
        mission_id="mission-mavlink-001",
        action_type="takeoff",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key="idem-mavlink-001",
    )

    res = rt.handle_action_request(req)

    assert res["request_id"] == "req-mavlink-001"
    assert res["accepted"] is False
    assert res["status"] == "rejected"
    assert res["adapter"] == "mavlink"
    assert res["code"] in {"exec_unavailable", "exec_unsupported"}


def test_runtime_with_unregistered_adapter_returns_adapter_not_found(tmp_path) -> None:
    audit = tmp_path / "runtime_missing_adapter.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit), adapter_name="unknown")

    req = ActionRequest(
        action="hover",
        params={"duration_s": 3},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        request_id="req-missing-adapter-001",
        mission_id="mission-missing-adapter-001",
        action_type="hover",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key="idem-missing-adapter-001",
    )

    res = rt.handle_action_request(req)

    assert res["accepted"] is False
    assert res["status"] == "rejected"
    assert res["adapter"] == "unknown"
    assert res["code"] == "adapter_not_found"
