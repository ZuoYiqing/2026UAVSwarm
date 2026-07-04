"""Intent Router + Template Agent Planner v0.1 tests."""
from __future__ import annotations

import json
from pathlib import Path

from uav_runtime.agent.planner import (
    IntentRouter,
    MissionIntent,
    PLAN_BLOCKED,
    PLAN_NEEDS_CONFIRM,
    PLAN_READY,
    TemplateAgentPlanner,
    TemplateStep,
)
from uav_runtime.runtime.audit_log import AuditLog


def _planner(tmp_path: Path) -> TemplateAgentPlanner:
    return TemplateAgentPlanner(audit=AuditLog(str(tmp_path / "agent.audit.jsonl")))


def _actions(result) -> list[str]:
    assert result.plan is not None
    return [step.action_type for step in result.plan.steps]


def test_simple_takeoff_land_generates_takeoff_land_steps(tmp_path: Path) -> None:
    result = _planner(tmp_path).plan(MissionIntent(intent_id="intent-1", mission_type="simple_takeoff_land"))
    assert result.result == PLAN_READY
    assert _actions(result) == ["takeoff", "land"]


def test_inspection_snapshot_generates_expected_steps(tmp_path: Path) -> None:
    result = _planner(tmp_path).plan(MissionIntent(intent_id="intent-2", mission_type="inspection_snapshot"))
    assert result.result == PLAN_READY
    assert _actions(result) == ["takeoff", "report_status", "camera_capture", "land"]


def test_status_only_generates_health_sensor_status_steps(tmp_path: Path) -> None:
    result = _planner(tmp_path).plan(MissionIntent(intent_id="intent-3", mission_type="status_only"))
    assert result.result == PLAN_READY
    assert _actions(result) == ["health_query", "sensor_read", "report_status"]


def test_safe_stop_and_fallback_hold_generate_safe_fallback_steps(tmp_path: Path) -> None:
    safe_stop = _planner(tmp_path).plan(MissionIntent(intent_id="intent-4", mission_type="safe_stop"))
    fallback_hold = _planner(tmp_path).plan(MissionIntent(intent_id="intent-5", mission_type="fallback_hold"))
    assert _actions(safe_stop) == ["land_safe"]
    assert _actions(fallback_hold) == ["hold_position"]


def test_unknown_mission_type_returns_blocked_unsupported(tmp_path: Path) -> None:
    result = _planner(tmp_path).plan(MissionIntent(intent_id="intent-6", mission_type="free_text_guess_me"))
    assert result.result == PLAN_BLOCKED
    assert result.failure_reason == "unsupported_mission_type"
    assert result.plan is None


class _DangerousRouter(IntentRouter):
    def route(self, intent: MissionIntent) -> tuple[TemplateStep, ...] | None:
        return (TemplateStep("payload_release"),)


def test_dangerous_action_is_blocked_before_plan_can_be_ready(tmp_path: Path) -> None:
    result = TemplateAgentPlanner(router=_DangerousRouter(), audit=AuditLog(str(tmp_path / "audit.jsonl"))).plan(
        MissionIntent(intent_id="intent-7", mission_type="dangerous_template")
    )
    assert result.result == PLAN_BLOCKED
    assert result.plan is not None
    assert result.plan.steps[0].status == PLAN_BLOCKED
    assert result.plan.steps[0].required_capability["dangerous"] is True


class _SpeakerRouter(IntentRouter):
    def route(self, intent: MissionIntent) -> tuple[TemplateStep, ...] | None:
        return (TemplateStep("speaker_play_message"),)


def test_require_confirm_step_is_marked_needs_operator_confirm(tmp_path: Path) -> None:
    result = TemplateAgentPlanner(router=_SpeakerRouter(), audit=AuditLog(str(tmp_path / "audit.jsonl"))).plan(
        MissionIntent(intent_id="intent-8", mission_type="speaker_template")
    )
    assert result.result == PLAN_READY
    assert result.plan is not None
    step = result.plan.steps[0]
    assert step.status == PLAN_NEEDS_CONFIRM
    assert step.policy_precheck["decision_code"] == "require_confirm"
    assert result.validation_summary["require_confirm_steps"] == [step.step_id]


class _PolicyDenyPlanner(TemplateAgentPlanner):
    def _policy_precheck(self, intent, capability, step_id):  # type: ignore[no-untyped-def]
        return {
            "decision_code": "deny",
            "primary_reason_code": "TEST_DENY",
            "secondary_reason_codes": [],
            "effective_profile_id": intent.requested_profile,
            "effective_scope": "self_only",
            "policy_trace_id": "test",
            "audit_tags": ["policy", "deny"],
        }


def test_policy_deny_step_blocks_plan(tmp_path: Path) -> None:
    result = _PolicyDenyPlanner(audit=AuditLog(str(tmp_path / "audit.jsonl"))).plan(
        MissionIntent(intent_id="intent-9", mission_type="simple_takeoff_land")
    )
    assert result.result == PLAN_BLOCKED
    assert result.plan is not None
    assert all(step.status == PLAN_BLOCKED for step in result.plan.steps)
    assert result.policy_summary["denied_steps"] == 2


def test_agent_plan_created_audit_event_is_written(tmp_path: Path) -> None:
    audit_path = tmp_path / "agent.audit.jsonl"
    planner = TemplateAgentPlanner(audit=AuditLog(str(audit_path)))
    result = planner.plan(MissionIntent(intent_id="intent-10", mission_type="status_only", source="ground_station"))
    event = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "agent_plan_created"
    assert event["mission_type"] == "status_only"
    assert event["plan_id"] == result.plan.plan_id
    assert event["step_count"] == 3
    assert event["result"] == PLAN_READY
