"""最小 runtime 集成链路测试（对齐当前 ActionRequest 与 decision 分支语义）。"""
from __future__ import annotations

import json

from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator


def _read_audit_events(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    assert last.get("decision_code") == "allow"
    assert last.get("policy_trace_id")


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
    assert res["code"] is not None
    assert res["code"].endswith("CONFIRMATION_REQUIRED")
    assert audit.exists()

    events = _read_audit_events(audit)
    decision_events = [e for e in events if e.get("type") == "policy_decision_event"]
    assert decision_events
    last = decision_events[-1]
    assert last.get("decision_code") == "REQUIRE_CONFIRM"
    assert last.get("primary_reason_code") is not None
    assert last.get("primary_reason_code").endswith("CONFIRMATION_REQUIRED")
    assert last.get("effective_scope")
