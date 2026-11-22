"""Full Runtime/Policy/lifecycle chain; only backend IO and self-HTTP are fake."""
from copy import deepcopy
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from uav_runtime.agent.executor import RealActionExecutor
from uav_runtime.http import routes
from uav_runtime.http.schemas import PlanExecuteRequest, RequestValidationError
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from tests.unit.test_runtime_action_lifecycle import install_registry, successful_takeoff, successful_land
from tests.unit.test_runtime_ground_completion import publish_context


def candidate():
    waypoints = [(0, 25), (30, 25), (30, 15), (30, 25), (0, 25)]
    return {
        "plan_id": "fake-target-001-patrol-v1",
        "intent_id": "equipment-inspection-fixture",
        "mission_type": "equipment_inspection_navigation_only",
        "scene_id": "simple_recon_v0_1", "map_version": "simple_recon_v0_1-map-1",
        "explanation": "Fake navigation to target-001 visual marker; NOT sensor inspection.",
        "steps": [
            {"step_id": "takeoff", "node_id": "UAV-02", "action_type": "takeoff", "params": {"altitude_m": 6}},
            *[{"step_id": f"goto-{i}", "node_id": "UAV-02", "action_type": "goto",
               "params": {"north_m": n, "east_m": e, "down_m": -6, "arrival_tolerance_m": 0.5, "hold_s": 0.5}}
              for i, (n, e) in enumerate(waypoints)],
            {"step_id": "land", "node_id": "UAV-02", "action_type": "land", "params": {}},
        ],
    }


@pytest.fixture
def chain(monkeypatch, tmp_path):
    # Not even an accidental real loopback/UDP connection is allowed.
    def forbid(*args, **kwargs):
        raise AssertionError("network IO forbidden in Fake plan acceptance")
    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "bind", forbid)
    monkeypatch.setattr(socket.socket, "sendto", forbid)
    registry, store = install_registry(monkeypatch)
    registry.scene = json.loads((Path(__file__).resolve().parents[2] /
                                 "scenarios/simple_recon_v0_1/scene.json").read_text(encoding="utf-8"))
    for handle in registry.list_vehicles():
        handle.config.metadata["initial_pose"] = {"x_m": 0, "y_m": handle.config.system_id * 8, "z_m": 0}
    registry.get_vehicle("UAV-02").session._position_epoch = 0
    publish_context(store)
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", None)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "fake-plan.audit.jsonl"))
    monkeypatch.delenv("UAV_RUNTIME_COVERAGE_AREA_ID", raising=False)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", None)
    captures, action_responses, posted = [], [], []

    def capture():
        captures.append(routes.dispatch("GET", "/api/mission/progress")[1])
        assert len(store.runtime_snapshot()["active_actions"]) == 1

    def takeoff(backend, **kwargs):
        capture()
        return successful_takeoff(backend, **kwargs)

    def goto(backend, **kwargs):
        capture()
        backend.session.calls.append("goto")
        seq = len(captures)
        offset = kwargs["translation_scene_ned_m"]
        return {"action": "goto", "result": "pass", "arrival_observed": True,
                "mode_confirmed": True, "completion_state": "succeeded",
                "ack_evidence": [{"command": 176, "result": 0}],
                "completion_evidence": {"telemetry_state": "fresh", "completion_reached": True,
                    "start_sequence": seq - 1, "position_sample": {
                        "north": kwargs["scene_north_m"] - offset["north"],
                        "east": kwargs["scene_east_m"] - offset["east"],
                        "down": -6, "sequence": seq, "position_epoch": 0}}}

    def land(backend, **kwargs):
        capture()
        assert kwargs["ground_reference"]["surface_id"] == "ground_plane"
        return successful_land(backend, **kwargs)

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", takeoff)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_goto_action", goto)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", land)

    def post(url, body, timeout):
        posted.append((urlsplit(url).path, deepcopy(body)))
        status, payload = routes.dispatch("POST", urlsplit(url).path, body=body)
        action_responses.append(deepcopy(payload))
        return status, payload

    monkeypatch.setattr(routes, "RealActionExecutor",
                        lambda **kwargs: RealActionExecutor(post=post, **kwargs))
    return SimpleNamespace(registry=registry, store=store, captures=captures, posted=posted,
                           responses=action_responses, goto=goto, capture=capture)


def submit(plan=None, **overrides):
    return routes.dispatch("POST", "/api/plans/execute", body={
        "plan": plan or candidate(), "operator_id": "fake-acceptance-operator", "decision": "approve", **overrides})


def test_approved_plan_policy_lifecycle_and_same_run_progress(chain):
    assert routes.mission_progress()["reason"] == "no_runtime_plan_execution"
    status, result = submit()
    assert status == 200 and result["result"] == "completed", result
    after = routes.mission_progress()
    assert after["mission_id"] == result["plan"]["plan_id"] == candidate()["plan_id"]
    assert after["run_id"] == result["run_id"]
    assert all(row["run_id"] == after["run_id"] and row["status"] == "running" for row in chain.captures)
    assert [row["waypoints_reached"] for row in chain.captures] == [0, 0, 1, 2, 3, 4, 5]
    assert after["status"] == "completed" and after["completion_pct"] == 100 and after["vehicles_active"] == 0
    assert after["coverage"] is None  # No imaging or continuous coverage proof invented.
    assert chain.store.runtime_snapshot()["active_actions"] == []
    actions = chain.store.recent_actions(limit=100)
    assert len(actions) == 7 and all(row["status"] == "succeeded" for row in actions)
    assert all(row["node_id"] == "UAV-02" and row["policy_decision"]["decision_code"] == "allow" for row in actions)
    assert all(row["source"] == "agent" for row in actions)
    assert chain.registry.get_vehicle("UAV-01").session.calls == chain.registry.get_vehicle("UAV-03").session.calls == []
    assert len({row["request_id"] for row in actions}) == 7 and len({row["trace_id"] for row in actions}) == 1
    assert all(item["evidence"]["action_id"] for item in result["step_outcomes"])

    original_actions, original_progress = deepcopy(actions), deepcopy(after)
    code, repeated = submit()
    assert code == 200 and repeated["idempotent_replay"] and repeated["result"] == "completed"
    assert repeated["run_id"] == after["run_id"]
    assert chain.store.recent_actions(limit=100) == original_actions
    assert routes.mission_progress() == original_progress and len(chain.posted) == 7
    changed = candidate()
    changed["steps"][1]["params"]["east_m"] = 24
    code, conflict = submit(changed)
    assert code == 409 and conflict["error"] == "plan_id_conflict" and len(chain.posted) == 7


@pytest.mark.parametrize("change", ["scene", "map", "unknown-node", "missing-node", "reject", "missing-decision",
                                     "missing-calibration", "unsupported-action", "missing-coordinate"])
def test_invalid_or_unapproved_plans_send_no_actions(chain, change):
    plan, override = candidate(), {}
    if change == "scene": plan["scene_id"] = "other-scene"
    if change == "map": plan["map_version"] = "other-map"
    if change == "unknown-node": plan["steps"][-1]["node_id"] = "UAV-99"
    if change == "missing-node": plan["steps"][-1]["node_id"] = ""
    if change == "reject": override["decision"] = "reject"
    if change == "missing-decision": override["decision"] = None
    if change == "missing-calibration": chain.store._coordinate_calibrations.clear()
    if change == "unsupported-action": plan["steps"][-1]["action_type"] = "observe"
    if change == "missing-coordinate": plan["steps"][1]["params"].pop("east_m")
    _, result = submit(plan, **override)
    assert result.get("result") != "completed"
    assert chain.posted == [] and chain.captures == []


@pytest.mark.parametrize("failure", ["adapter", "timeout", "policy"])
def test_failed_action_stops_remaining_steps_and_finishes_progress(chain, monkeypatch, failure):
    if failure == "policy":
        original = RuntimeOrchestrator._build_profile
        def restrictive(self):
            profile = original(self)
            profile.runtime_constraints["max_risk_allow"] = 0
            return profile
        monkeypatch.setattr(RuntimeOrchestrator, "_build_profile", restrictive)
    else:
        def fail(backend, **kwargs):
            chain.capture()
            if failure == "adapter":
                raise RuntimeError("fake adapter failure")
            return {"action": "goto", "result": "fail", "failure_reason": "arrival_timeout",
                    "completion_state": "timed_out", "arrival_observed": False,
                    "ack_evidence": [{"command": 176, "result": 0}]}
        monkeypatch.setattr(routes.Px4SitlBackend, "execute_goto_action", fail)
    _, result = submit()
    assert result["result"] == "failed" and result["remaining_steps_pending"]
    after = routes.mission_progress()
    assert after["status"] == "failed" and after["waypoints_reached"] == 0
    assert chain.store.runtime_snapshot()["active_actions"] == []
    assert chain.store.recent_actions(limit=100)[-1]["status"] == (
        "policy_rejected" if failure == "policy" else "failed" if failure == "adapter" else "timed_out")
    assert "land" not in chain.registry.get_vehicle("UAV-02").session.calls
    if failure == "policy":
        assert chain.registry.get_vehicle("UAV-02").session.calls == []


def test_concurrent_repeat_returns_pending_without_restarting(chain, monkeypatch):
    response = []
    original = routes.Px4SitlBackend.execute_takeoff_action
    def nested(backend, **kwargs):
        response.append(submit())
        return original(backend, **kwargs)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", nested)
    _, result = submit()
    assert result["result"] == "completed"
    assert response[0][0] == 202 and response[0][1]["result"] == "running"
    assert response[0][1]["run_id"] == result["run_id"]
    assert response[0][1]["idempotent_replay"] and len(chain.posted) == 7


@pytest.mark.parametrize("body", [
    {"accepted": True},
    {"accepted": True, "result": "pass", "status": "executing"},
    {"accepted": True, "result": "pass", "lifecycle_status": "timed_out"},
    {"accepted": True, "result": "pass", "completion_evidence": {"completion_reached": False}},
])
def test_ack_or_nonterminal_response_is_not_step_success(body):
    step = SimpleNamespace(action_type="goto", node_id="UAV-02", step_id="s1", params={})
    result = RealActionExecutor(post=lambda *args: (200, body)).execute_step(step)
    assert not result.ok and result.failure_reason == "action_completion_unconfirmed"


def test_runtime_plan_requires_confirmed_goto_arrival_with_terminal_lifecycle():
    step = SimpleNamespace(action_type="goto", node_id="UAV-02", step_id="s1", params={})
    response = {"accepted": True, "result": "pass", "lifecycle_status": "succeeded",
                "completion_state": "arrival_observed", "arrival_observed": True}
    executor = RealActionExecutor(plan_id="p", post=lambda *args: (200, response))
    assert executor.execute_step(step).ok
    response["arrival_observed"] = False
    assert not executor.execute_step(step).ok


@pytest.mark.parametrize("bad", ["missing", None, "", False])
def test_approval_cannot_be_inferred(bad):
    request = {"plan": candidate(), "operator_id": "operator"}
    if bad != "missing":
        request["decision"] = bad
    with pytest.raises(RequestValidationError):
        PlanExecuteRequest.from_json(request)


@pytest.mark.parametrize("mutation", ["duplicate-step", "already-succeeded"])
def test_invalid_step_state_cannot_skip_execution(mutation):
    plan = candidate()
    if mutation == "duplicate-step":
        plan["steps"][1]["step_id"] = plan["steps"][0]["step_id"]
    else:
        plan["steps"][0]["status"] = "succeeded"
    with pytest.raises(RequestValidationError):
        PlanExecuteRequest.from_json({"plan": plan, "operator_id": "operator", "decision": "approve"})
