"""Planner provenance fixtures; no sockets, model or live executor."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uav_runtime.agent.planner import MissionIntent, TemplateAgentPlanner
from uav_runtime.http import routes
from uav_runtime.http.planner_preview import PlanPreviewProvenance, serialize_plan_preview
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "docs/fixtures/runtime_planner_preview_v1.json"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def preview_planner(monkeypatch: pytest.MonkeyPatch) -> TemplateAgentPlanner:
    planner = TemplateAgentPlanner(audit=SimpleNamespace(append=lambda _: None))
    registry = VehicleRegistry(scene_id="planner-preview-fixture")
    identity = {"scene_id": registry.scene_id, "map_version": "fixture-map-v1"}
    # Exercise rules on both a standalone Runtime branch and an integrated tree.
    # The published unresolved case retains its ID; a mounted empty catalog
    # lets the recognizer run without inventing a binding for its objective.
    registry.scene = {
        **identity,
        "targets": [],
        "intent_catalog": {**identity, "contract_version": "1.0", "catalog_id": "fixture-catalog-v1", "entries": []},
    }

    def forbidden(*_args, **_kwargs):
        pytest.fail("plan preview reached the flight execution path")

    monkeypatch.setattr(routes, "TemplateAgentPlanner", lambda: planner)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", RuntimeStateStore(vehicle_registry=registry))
    monkeypatch.setattr(routes, "plans_execute", forbidden)
    monkeypatch.setattr(routes, "_execute_flight_action", forbidden)
    return planner


@pytest.mark.parametrize("case", CASES, ids=[row["case"] for row in CASES])
def test_published_fixture_matches_http_response(preview_planner, case) -> None:
    status, body = routes.dispatch("POST", "/api/planner/plan-mission", body=case["request"])

    assert status == case["http_status"]
    assert {key: body[key] for key in case["response_fields"]} == case["response_fields"]
    assert [step["action_type"] for step in (body["plan"] or {}).get("steps", [])] == case["step_action_types"]
    assert isinstance(body["validation_summary"], dict)
    assert isinstance(body["policy_summary"], dict)


def test_named_fallback_template_is_not_a_downgrade_or_authorization(preview_planner) -> None:
    status, body = routes.dispatch("POST", "/api/planner/plan-mission", body={
        "mission_type": "fallback_hold",
        "dry_run": False,
        "intent_source": "local_model",
        "plan_source": "algorithm",
        "fallback_reason": "model_unavailable",
        "execution_authorized": True,
        "decision": "approve",
    })

    assert status == 200
    assert body["intent_source"] == "explicit" and body["plan_source"] == "template"
    assert body["fallback_reason"] is None and body["execution_authorized"] is False
    assert [step["action_type"] for step in body["plan"]["steps"]] == ["hold_position"]


def test_rejected_explicit_type_keeps_intent_source_but_has_no_plan(preview_planner) -> None:
    status, body = routes.dispatch("POST", "/api/planner/plan-mission", body={"mission_type": "unknown"})

    assert status == 200 and body["result"] == "blocked"
    assert body["intent_source"] == "explicit"
    assert body["plan_source"] == "none" and body["plan"] is None
    assert body["fallback_reason"] is None and body["execution_authorized"] is False


def test_internal_serializer_distinguishes_algorithm_from_template(preview_planner) -> None:
    # Serializer-only fixture; there is no HTTP algorithm producer yet.
    candidate = preview_planner.plan(MissionIntent("test", "status_only"))
    template = serialize_plan_preview(candidate, PlanPreviewProvenance("rules", "template"))
    algorithm = serialize_plan_preview(candidate, PlanPreviewProvenance("rules", "algorithm"))

    assert template["plan_source"] == "template" and algorithm["plan_source"] == "algorithm"
    assert algorithm["intent_source"] == template["intent_source"] == "rules"
    assert algorithm["fallback_reason"] is template["fallback_reason"] is None
    assert algorithm["execution_authorized"] is template["execution_authorized"] is False


@pytest.mark.parametrize("reason", ["model_unavailable", "model_invalid_output", "model_abstained", "model_low_confidence"])
def test_internal_fallback_requires_real_source_and_cause(preview_planner, reason) -> None:
    candidate = preview_planner.plan(MissionIntent("test", "status_only"))
    body = serialize_plan_preview(candidate, PlanPreviewProvenance.after_model_fallback(
        intent_source="rules", plan_source="template", reason=reason,
    ))
    assert body["intent_source"] == "rules" and body["plan_source"] == "template"
    assert body["fallback_reason"] == reason and body["execution_authorized"] is False

    blocked = preview_planner.plan(MissionIntent("test", ""))
    no_plan = serialize_plan_preview(blocked, PlanPreviewProvenance.after_model_fallback(
        intent_source="none", plan_source="none", reason=reason,
    ))
    assert no_plan["plan"] is None and no_plan["fallback_reason"] == reason


def test_serializer_rejects_inconsistent_provenance(preview_planner) -> None:
    with pytest.raises(ValueError, match="preview_fallback_reason_required"):
        PlanPreviewProvenance.after_model_fallback(intent_source="rules", plan_source="template", reason=None)
    with pytest.raises(ValueError, match="invalid_preview_fallback_reason"):
        PlanPreviewProvenance.after_model_fallback(intent_source="rules", plan_source="template", reason="")
    with pytest.raises(ValueError, match="invalid_preview_fallback_intent_source"):
        PlanPreviewProvenance("local_model", "algorithm", "model_low_confidence")
    with pytest.raises(ValueError, match="preview_plan_requires_resolved_intent"):
        PlanPreviewProvenance("none", "template")

    blocked = preview_planner.plan(MissionIntent("test", ""))
    with pytest.raises(ValueError, match="preview_plan_source_mismatch"):
        serialize_plan_preview(blocked, PlanPreviewProvenance("rules", "algorithm"))
