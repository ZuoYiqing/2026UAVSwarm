"""HTTP producer replay of the pinned synthetic algorithm corpus."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uav_runtime.agent._vendor_intent_recognizer_v0 import TEMPLATE_KEYS
from uav_runtime.agent.planner import MISSION_TEMPLATES, TemplateAgentPlanner
from uav_runtime.http import routes
from uav_runtime.http.intent_resolution import resolve_preview_intent
from uav_runtime.http.schemas import PlanExecuteRequest, RequestValidationError
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"
GOLDEN = json.loads((FIXTURES / "runtime_intent_recognition_v0.json").read_text(encoding="utf-8"))
VENDOR = json.loads((FIXTURES / "runtime_intent_recognition_vendor_v0.json").read_text(encoding="utf-8"))
RESOLUTION_STATES = {"bound": "resolved", "clarify": "needs_clarification", "unknown": "unsupported"}


@pytest.mark.parametrize("pin", VENDOR["files"], ids=["recognizer", "golden-corpus"])
def test_vendor_matches_algorithm_source_pin(pin) -> None:
    def lf(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    contents = lf(ROOT / pin["vendored_path"])
    assert hashlib.sha256(contents).hexdigest() == pin["sha256_lf"]
    # Algorithm owns the original; the Runtime copy must match it byte-for-byte
    # after checkout newline normalization, even when both paths are present.
    upstream = ROOT / pin["upstream_path"]
    if upstream.is_file():
        assert contents == lf(upstream)


def test_vendored_keys_match_explicit_runtime_templates() -> None:
    assert TEMPLATE_KEYS == set(MISSION_TEMPLATES)


def synthetic_scene() -> dict:
    return {
        "scene_id": "test-only-synthetic-campus",
        "map_version": "test-only-map-v0",
        "targets": [{"target_id": entry["entity_id"]} for entry in GOLDEN["catalog"]],
        "intent_catalog": {
            "contract_version": "1.0",
            "scene_id": "test-only-synthetic-campus",
            "map_version": "test-only-map-v0",
            "catalog_id": GOLDEN["catalog_id"],
            "entries": deepcopy(GOLDEN["catalog"]),
        },
    }


@pytest.fixture
def preview(monkeypatch: pytest.MonkeyPatch) -> VehicleRegistry:
    scene = synthetic_scene()
    registry = VehicleRegistry(scene_id=scene["scene_id"])
    registry.scene = scene
    planner = TemplateAgentPlanner(audit=SimpleNamespace(append=lambda _: None))

    def forbidden(*_args, **_kwargs):
        pytest.fail("a read-only preview reached the execution or session startup path")

    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", RuntimeStateStore(vehicle_registry=registry))
    monkeypatch.setattr(routes, "TemplateAgentPlanner", lambda: planner)
    monkeypatch.setattr(routes, "plans_execute", forbidden)
    monkeypatch.setattr(routes, "_execute_flight_action", forbidden)
    monkeypatch.setattr(VehicleRegistry, "start_vehicle", forbidden)
    return registry


def request(objective: str, **fields) -> dict:
    code, body = routes.dispatch("POST", "/api/planner/plan-mission", body={"objective": objective, **fields})
    assert code == 200 and body["contract_version"] == "1.0"
    assert body["execution_authorized"] is False and body["fallback_reason"] is None
    assert "objective" not in body
    return body


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[case["id"] for case in GOLDEN["cases"]])
@pytest.mark.parametrize("selector", [None, "", "auto"], ids=["objective-only", "empty-key", "auto"])
def test_golden_objectives_at_plan_mission(preview, case, selector) -> None:
    fields = {} if selector is None else {"mission_type": selector}
    body = request(case["objective"], **fields)
    resolution = body["intent_resolution"]
    assert body["intent_source"] == "rules"
    assert resolution["status"] == RESOLUTION_STATES[case["status"]]
    assert resolution["mission_type"] == case.get("mission_type")
    assert resolution["reason_code"] == case.get("reason_code", "INTENT_BOUND")
    assert resolution["catalog"] == {
        "scene_id": preview.scene_id, "map_version": preview.scene["map_version"], "catalog_id": GOLDEN["catalog_id"],
    }
    bindings = resolution["bindings"]
    for role in ("targets", "reference_only", "excluded_targets"):
        assert [item["entity_id"] for item in bindings[role]] == case.get(role, [])
    assert bindings["only_listed_targets"] is case.get("only_listed_targets", False)
    assert bindings["status_scope"] == case.get("status_scope")
    if "evidence" in case:
        assert [item["evidence"] for item in bindings["targets"]] == case["evidence"]
    for phrase in case.get("question_includes", ()):
        assert phrase in resolution["question"]

    if case["status"] == "bound":
        plan = body["plan"]
        assert body["plan_source"] == "template"
        assert plan["mission_type"] == case["mission_type"]
        assert plan["preview_binding"] == {
            "steps_are_outline": True, "catalog": resolution["catalog"], "bindings": bindings,
        }
        # Even with approved-looking labels it does not satisfy the execution IR.
        with pytest.raises(RequestValidationError, match="scene_id"):
            PlanExecuteRequest.from_json({"plan": plan, "operator_id": "test", "decision": "approve"})
    else:
        assert body["result"] == "blocked"
        assert body["plan"] is None and body["plan_source"] == "none"
        assert not bindings["targets"] and resolution["question"]


def test_same_template_different_target_keeps_distinct_saved_bindings(preview) -> None:
    pv = request("巡检西侧光伏区。", dry_run=False, execution_authorized=True)
    heat = request("巡检热泵机房。", intent_source="local_model", plan_source="algorithm")
    assert pv["plan"]["mission_type"] == heat["plan"]["mission_type"] == "inspection_snapshot"
    assert pv["plan"]["preview_binding"]["bindings"]["targets"][0]["entity_id"] == "S-PV-W"
    assert heat["plan"]["preview_binding"]["bindings"]["targets"][0]["entity_id"] == "S-THERM"
    saved = routes.RUNTIME_STATE_STORE.agent_status()["latest_plan"]
    assert saved["preview_binding"] == heat["plan"]["preview_binding"]


def test_catalog_survives_normal_registry_scene_loading(tmp_path: Path) -> None:
    scene = json.loads((ROOT / "scenarios/simple_recon_v0_1/scene.json").read_text(encoding="utf-8"))
    target_shape = scene["targets"][0]
    scene.update(synthetic_scene())
    scene["targets"] = [{**target_shape, **row} for row in scene["targets"]]
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    config = json.loads((ROOT / "simulation/px4_gazebo/config/three_uav_sitl.json").read_text(encoding="utf-8"))
    config.update(scene_id=scene["scene_id"], map_version=scene["map_version"], scene_path=str(scene_path))
    config_path = tmp_path / "vehicles.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    loaded = VehicleRegistry.from_json(config_path)
    result = resolve_preview_intent("巡检西侧光伏区。", scene_id=loaded.scene_id, scene=loaded.scene)
    assert result.status == "resolved"
    assert result.bindings()["targets"][0]["entity_id"] == "S-PV-W"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("absent", "INTENT_CATALOG_UNAVAILABLE"),
        ("scene", "INTENT_CATALOG_IDENTITY_MISMATCH"),
        ("map", "INTENT_CATALOG_IDENTITY_MISMATCH"),
        ("unknown-id", "INTENT_CATALOG_ENTITY_NOT_IN_SCENE"),
        ("duplicate-id", "INTENT_CATALOG_INVALID"),
        ("untyped-alias", "INTENT_CATALOG_INVALID"),
    ],
)
def test_untrusted_or_missing_catalog_never_binds(preview, change, reason) -> None:
    supplied = deepcopy(preview.scene["intent_catalog"])
    catalog = preview.scene["intent_catalog"]
    if change == "absent":
        preview.scene.pop("intent_catalog")
    elif change == "scene":
        catalog["scene_id"] = "different-scene"
    elif change == "map":
        catalog["map_version"] = "different-map"
    elif change == "unknown-id":
        catalog["entries"][0]["entity_id"] = "not-in-scene"
    elif change == "duplicate-id":
        catalog["entries"].append(catalog["entries"][0])
    else:
        catalog["entries"][0]["aliases"] = "wrong-shape"

    body = request("巡检西侧光伏区。", intent_catalog=supplied, scene=synthetic_scene())
    assert body["intent_source"] == body["plan_source"] == "none"
    assert body["plan"] is None and body["intent_resolution"]["catalog"] is None
    assert body["intent_resolution"]["reason_code"] == reason
    assert body["intent_resolution"]["status"] == "unsupported"


def test_explicit_template_skips_rules_and_keeps_legacy_shape(preview, monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("an explicit selector must not be treated as natural language")

    monkeypatch.setattr(routes, "resolve_preview_intent", forbidden)
    explicit = request("北仓只作参照", mission_type="inspection_snapshot")
    assert explicit["plan_source"] == "template" and explicit["intent_source"] == "explicit"
    assert "intent_resolution" not in explicit and "preview_binding" not in explicit["plan"]
    unknown_key = request("巡检热泵机房。", mission_type="unknown")
    assert unknown_key["intent_source"] == "explicit" and unknown_key["plan"] is None


def test_auto_still_requires_the_active_catalog(preview) -> None:
    supplied = preview.scene.pop("intent_catalog")
    body = request("巡检热泵机房。", mission_type="auto", intent_catalog=supplied)
    assert body["intent_source"] == body["plan_source"] == "none"
    assert body["plan"] is None
    assert body["intent_resolution"]["reason_code"] == "INTENT_CATALOG_UNAVAILABLE"


def test_bound_shape_that_cannot_be_represented_never_drops_constraints(preview, monkeypatch) -> None:
    real = resolve_preview_intent("巡检热泵机房。", scene_id=preview.scene_id, scene=preview.scene)
    bad = replace(real, mission_type="safe_stop")
    monkeypatch.setattr(routes, "resolve_preview_intent", lambda *_args, **_kwargs: bad)
    body = request("巡检热泵机房。")
    assert body["failure_reason"] == "intent_not_representable_by_template"
    assert body["plan_source"] == "none" and body["plan"] is None
    assert body["intent_resolution"]["bindings"]["targets"][0]["entity_id"] == "S-THERM"
