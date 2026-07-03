"""Mission Runtime v0.2 pending takeover / phase exit integration tests."""
from __future__ import annotations

import json

from uav_runtime.policy.gate import REASON_CODE_PREEMPT_NON_PREEMPTIBLE
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last


def _read_audit_events(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _takeover_request(*, request_id: str = "req-takeover-001", ttl_s: float = 30.0) -> ActionRequest:
    return ActionRequest(
        action="goto",
        params={"x": 1, "y": 2, "takeover_ttl_s": ttl_s},
        source=CommandSource.GROUND_STATION,
        scope=AuthorityScope.SELF_ONLY,
        request_id=request_id,
        mission_id="mission-takeover-001",
        action_type="goto",
        skill_group="flight_core",
        target_set=["self"],
        requested_scope=AuthorityScope.SELF_ONLY,
        risk_hint=1,
        priority_hint=90,
        requires_confirmation_hint=False,
        idempotency_key=f"idem-{request_id}",
    )


def test_non_preemptible_defer_creates_pending_takeover_and_audit_event(tmp_path) -> None:
    audit = tmp_path / "runtime_takeover_defer.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))
    rt.add_running_action(
        request_id="running-self-001",
        action_type="land",
        source=CommandSource.SELF_LOCAL,
        priority=50,
        non_preemptible=True,
    )

    res = rt.handle_action_request(_takeover_request())

    assert res["status"] == "deferred"
    assert res["accepted"] is False
    assert res["code"] == REASON_CODE_PREEMPT_NON_PREEMPTIBLE
    assert res["takeover_status"] == "pending"
    assert len(rt.pending_takeovers) == 1
    assert rt.pending_takeovers[0].status == "pending"

    events = _read_audit_events(audit)
    assert [event["type"] for event in events] == ["policy_decision_event", "pending_takeover_created"]
    assert events[-1]["request_id"] == "req-takeover-001"
    assert events[-1]["status"] == "pending"
    assert events[-1]["reason_code"] == REASON_CODE_PREEMPT_NON_PREEMPTIBLE


def test_phase_exit_admits_and_activates_pending_takeover_in_audit_order(tmp_path) -> None:
    audit = tmp_path / "runtime_takeover_phase_exit.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))
    rt.add_running_action(
        request_id="running-self-001",
        action_type="land",
        source=CommandSource.SELF_LOCAL,
        priority=50,
        non_preemptible=True,
    )
    first = rt.handle_action_request(_takeover_request())

    rt.running_actions[0].non_preemptible = False
    out = rt.handle_phase_exit("mission-takeover-001")

    assert out["status"] == "activated"
    assert out["activated"] is True
    assert out["takeover_id"] == first["takeover_id"]
    assert rt.pending_takeovers[0].status == "activated"

    event_types = [event["type"] for event in _read_audit_events(audit)]
    assert event_types == [
        "policy_decision_event",
        "pending_takeover_created",
        "phase_exit",
        "pending_takeover_admitted",
        "pending_takeover_activated",
    ]

    replayed = replay_last(str(audit), n=5)
    assert [event["type"] for event in replayed][-2:] == ["pending_takeover_admitted", "pending_takeover_activated"]


def test_expired_pending_takeover_is_dropped_and_auditable(tmp_path) -> None:
    audit = tmp_path / "runtime_takeover_expired.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))
    rt.add_running_action(
        request_id="running-self-001",
        action_type="land",
        source=CommandSource.SELF_LOCAL,
        priority=50,
        non_preemptible=True,
    )
    rt.handle_action_request(_takeover_request(request_id="req-takeover-expire-001", ttl_s=0.001))

    created_at = rt.pending_takeovers[0].created_at
    dropped = rt.drop_expired_pending_takeovers(now=created_at + 1.0)

    assert len(dropped) == 1
    assert dropped[0].status == "dropped"
    assert rt.pending_takeovers[0].status == "dropped"

    event_types = [event["type"] for event in _read_audit_events(audit)]
    assert event_types == [
        "policy_decision_event",
        "pending_takeover_created",
        "pending_takeover_expired",
        "pending_takeover_dropped",
    ]
