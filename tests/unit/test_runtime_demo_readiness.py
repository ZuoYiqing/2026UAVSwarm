"""Deterministic rehearsal and passive progress checks; no PX4 endpoints."""

from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from uav_runtime.adapters import mavlink_backend_session as mav
from uav_runtime.agent.executor import StepOutcome
from uav_runtime.http import routes
from uav_runtime.http.demo import DemoRehearsal
from uav_runtime.http.mission_progress import MissionProgress
from uav_runtime.http.server import create_server
from uav_runtime.runtime.audit_log import AuditLog


class Sample:
    x = 1.0
    y = 2.0
    z = -3.0
    time_boot_ms = 100
    base_mode = 0

    def __init__(self, kind, system=2):
        self.kind, self.system = kind, system

    def get_type(self):
        return self.kind

    def get_srcSystem(self):
        return self.system

    def get_srcComponent(self):
        return 1


def test_link_quality_uses_two_independent_matched_rx_clocks(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(mav, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(mav.MavlinkBackendSession, "receive_thread_alive", lambda self: True)
    session = mav.MavlinkBackendSession("sitl", True, "unused", expected_target_system=2,
                                       expected_target_component=1, connected=True)
    session.dispatch_message(Sample("HEARTBEAT"))
    assert session.link_quality() == 0
    session.dispatch_message(Sample("LOCAL_POSITION_NED"))
    assert session.link_quality() == 100
    now[0] += 0.3
    assert 80 <= session.link_quality() < 100
    now[0] += 1.8
    session.dispatch_message(Sample("HEARTBEAT"))
    session.dispatch_message(Sample("LOCAL_POSITION_NED", system=1))
    assert session.link_quality() == 0
    session.dispatch_message(Sample("LOCAL_POSITION_NED"))
    assert session.link_quality() == 100
    now[0] += 4.5
    session.dispatch_message(Sample("LOCAL_POSITION_NED"))
    assert session.link_quality() == 0
    session.connected = False
    assert session.link_quality() == 0


def test_demo_default_disabled(monkeypatch):
    monkeypatch.setattr(routes, "DEMO_REHEARSAL", None)
    assert routes.dispatch("GET", "/api/demo/state")[1]["enabled"] is False
    assert routes.dispatch("POST", "/api/demo/inject", body={"node_id": "UAV-02"}) == (
        404, {"error": "demo_disabled"},
    )
    snapshot = routes.dispatch("GET", "/api/vehicle-snapshot")[1]
    assert all(row["link_quality_mode"] == "LIVE" for row in snapshot["vehicles"])


@pytest.fixture
def demo(monkeypatch, tmp_path):
    now, scores, events = [10.0], {"UAV-01": 91, "UAV-02": 92, "UAV-03": 93}, []
    path = str(tmp_path / "demo.audit.jsonl")
    audit = AuditLog(path)

    def append(row):
        audit.append(row)
        events.append(row)

    demo = DemoRehearsal(lambda: list(scores), scores.__getitem__, append, clock=lambda: now[0])
    monkeypatch.setattr(routes, "DEMO_REHEARSAL", demo)
    monkeypatch.setattr(routes, "AUDIT_PATH", path)
    monkeypatch.setattr(routes, "_execute_flight_action",
                        lambda *a, **kw: pytest.fail("demo reached real flight action"))
    return demo, now, scores, events


def test_demo_hold_clear_and_audit_are_idempotent(demo):
    _, now, _, events = demo
    before = routes.vehicle_snapshot()
    body = {"node_id": "UAV-02", "kind": "link_degraded", "value": 18, "duration_s": 60}
    code, payload = routes.dispatch("POST", "/api/demo/inject", body=body)
    assert code == 200 and payload["changed"] and payload["held_out"] == ["UAV-02"]
    assert next(row for row in payload["assignments"] if row["work_id"] == "demo-work:UAV-02")["node_id"] == "UAV-01"
    assert [event["type"] for event in events] == [
        "demo_inject", "policy_decision_event", "adapter_execution_started", "action_result", "demo_reassignment",
    ]
    assert len({event["trace_id"] for event in events}) == 1
    assert all(row["mode"] == "DEMO" and row["flight_command_sent"] is False for row in events)
    assert routes.dispatch("GET", "/api/policy/decisions")[1][0]["rule_name"] == "degraded_link_hold"
    recent = routes.dispatch("GET", "/api/actions/recent")[1][0]
    assert (recent["adapter"], recent["status"], recent["result"]) == ("fake", "simulated", "simulated")
    assert recent["execution_authorized"] is False
    now[0] += 1
    _, payload = routes.dispatch("POST", "/api/demo/inject", body=body)
    assert not payload["changed"] and payload["overrides"][0]["remaining_ms"] == 59000
    assert len(events) == 5
    after = routes.vehicle_snapshot()
    for prev, current in zip(before["vehicles"], after["vehicles"]):
        for field in ("telemetry", "pose", "connected", "link_quality_measured", "control"):
            assert prev[field] == current[field]
        if current["id"] == "UAV-02":
            assert (current["link_quality"], current["link_quality_mode"]) == (18, "DEMO")
        else:
            assert prev == current
    code, payload = routes.dispatch("POST", "/api/demo/clear", body={"node_id": "UAV-02"})
    assert code == 200 and payload["changed"] and not payload["overrides"] and not payload["held_out"]
    assert events[-1]["type"] == "demo_recovered"
    assert not routes.dispatch("POST", "/api/demo/clear", body={"node_id": "UAV-02"})[1]["changed"]
    assert sum(row["type"] == "demo_clear" for row in events) == 1


def test_expiry_without_polling_and_rejoin_threshold(demo):
    state, now, scores, events = demo
    scores["UAV-02"] = 59
    routes.dispatch("POST", "/api/demo/inject", body={"node_id": "UAV-02", "kind": "link_lost", "duration_s": 1})
    assert [row["action"] for row in events if row["type"] == "action_result"] == ["return_home"]
    now[0] += 1
    state.tick()
    assert events[-1]["type"] == "demo_clear" and events[-1]["reason"] == "expired"
    assert state.state()["held_out"] == ["UAV-02"]
    scores["UAV-02"] = 60
    state.tick()
    assert not state.state()["held_out"]
    assert events[-1]["type"] == "demo_recovered"


@pytest.mark.parametrize("data", [
    {"kind": "reboot"},
    {"kind": "link_degraded", "value": True},
    {"kind": "link_degraded", "duration_s": float("nan")},
    {"kind": "link_lost", "value": 1},
    {"kind": "link_lost", "duration_s": 301},
    {"kind": "recover", "duration_s": 1},
    {"kind": "link_lost", "node_id": "UNKNOWN"},
])
def test_demo_rejects_invalid_requests(demo, data):
    code, _ = routes.dispatch("POST", "/api/demo/inject", body={"node_id": "UAV-02", **data})
    assert code == 400 and not demo[3]


def test_demo_rejects_fake_execution_when_policy_denies(demo, monkeypatch):
    from uav_runtime.http import demo as module
    monkeypatch.setattr(module, "unified_policy_gate", lambda *_: SimpleNamespace(
        decision_code="deny", primary_reason_code="test_denial", secondary_reason_codes=[],
        effective_profile_id="test", audit_tags=[],
    ))
    monkeypatch.setattr(module.FakeAdapter, "execute", lambda *_: pytest.fail("denied command executed"))
    routes.dispatch("POST", "/api/demo/inject", body={"node_id": "UAV-02", "kind": "link_lost"})
    assert [row["type"] for row in demo[3]] == ["demo_inject", "policy_decision_event"]


def test_http_demo_boundary_and_timer_without_get(demo):
    state, now, _, events = demo
    expired = Event()
    append = state.append

    def notify(row):
        append(row)
        if row["type"] == "demo_clear":
            expired.set()

    state.append = notify
    server = create_server(port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.start()
    connection = HTTPConnection(*server.server_address, timeout=2)
    try:
        path = "/api/demo/inject"
        body = json.dumps({"node_id": "UAV-02", "kind": "link_degraded", "duration_s": 1})
        for headers, expected in (
            ({"Origin": "http://outside.invalid", "Content-Type": "application/json"}, 403),
            ({"Content-Type": "text/plain"}, 415),
        ):
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            assert response.status == expected
            response.read()
        assert not events
        connection.request("POST", path, body, {"Content-Type": "application/json",
                                              "Origin": "http://127.0.0.1:5178"})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["flight_command_sent"] is False
        now[0] += 1
        assert expired.wait(1.5)
        connection.request("GET", "/api/vehicle-snapshot")
        response = connection.getresponse()
        assert response.status == 200
        assert all(row["link_quality_mode"] == "LIVE" for row in json.loads(response.read())["vehicles"])
    finally:
        connection.close()
        state.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_demo_contract_fixture_matches_route_projections(demo, monkeypatch):
    from uav_runtime.http import mission_progress

    fixture = json.loads((Path(__file__).resolve().parents[2] / "docs" / "fixtures"
                          / "runtime_demo_readiness_v1.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", None)
    assert routes.mission_progress() == fixture["mission_progress_unavailable"]
    request = fixture["inject_request"]
    code, result = routes.dispatch("POST", "/api/demo/inject", body=request)
    assert code == 200
    for key, expected in fixture["inject_response_fields"].items():
        assert result[key] == expected
    snapshot = routes.vehicle_snapshot()
    row = next(row for row in snapshot["vehicles"] if row["id"] == request["node_id"])
    assert {key: row[key] for key in fixture["vehicle_fields"]} == fixture["vehicle_fields"]
    event = routes.policy_decisions()[0]
    for key, expected in fixture["policy_decision_fields"].items():
        assert event[key] == expected
    assert mission_progress.unavailable_progress()["vehicles_active"] is None


def test_goto_observation_exposes_only_the_matched_arrival_sample(monkeypatch):
    now = [20.0]
    session = mav.MavlinkBackendSession("sitl", True, "unused", expected_target_system=2,
                                       expected_target_component=1, connected=True)
    def advance(_):
        now[0] += 0.1
        session.dispatch_message(Sample("LOCAL_POSITION_NED"))
    monkeypatch.setattr(mav, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=advance))
    session.dispatch_message(Sample("LOCAL_POSITION_NED"))
    arrival = session.observe_arrival(north_m=1, east_m=2, down_m=-3, tolerance_m=0.1, hold_s=0.05,
                                      timeout_s=1, after_sequence=0)
    assert arrival["observed"] and arrival["position_sample"]["sequence"] == 2
    assert arrival["position_sample"]["north"] == 1


def test_land_failure_classification_survives_replay(monkeypatch, tmp_path):
    from tests.unit.test_runtime_action_lifecycle import action_body, install_registry
    from tests.unit.test_runtime_ground_completion import publish_context

    registry, store = install_registry(monkeypatch)
    publish_context(store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "land.audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))

    session = registry.get_vehicle("UAV-02").session
    session.status = lambda: "connected"
    session.receive_thread_alive = lambda: True
    session.heartbeat_thread_alive = lambda: True
    session.land = lambda **kwargs: {"command": 21, "result": 0, "timeout": False, "observation_cursor": 10}

    def timeout(**kwargs):
        evidence = {"completion_reached": False, "physical_landed_disarmed": False,
                    "landed_state": 1, "landed_state_name": "on_ground", "armed": True,
                    "telemetry_state": "incomplete", "failure_reason": "landing_completion_timeout"}
        session._last_completion_evidence = evidence
        return evidence

    monkeypatch.setattr(session, "observe_ground_landing", timeout, raising=False)
    monkeypatch.setattr(session, "classify_incomplete",
                        lambda action: mav.classify_incomplete_evidence(action, session._last_completion_evidence),
                        raising=False)
    _, result = routes.dispatch("POST", "/api/actions/land", body=action_body("UAV-02", key="timeout"))
    assert result["lifecycle_status"] == "timed_out"
    assert result["completion_state"] == "partial_evidence"
    replay = next(row for row in routes.replay() if row.get("type") == "action_result")
    recent = routes.actions_recent()[0]
    for row in (replay, recent):
        assert row["completion_state"] == result["completion_state"]
        assert row["completion_timeout_detail"] == result["completion_timeout_detail"]


def test_mission_progress_is_passive_and_bound_to_verified_arrivals(monkeypatch):
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", None)
    assert routes.dispatch("GET", "/api/mission/progress")[1]["completion_pct"] is None
    steps = [SimpleNamespace(action_type="goto", node_id="UAV-01"),
             SimpleNamespace(action_type="goto", node_id="UAV-02"),
             SimpleNamespace(action_type="return_home", node_id="UAV-02")]
    raw = {"result": "pass", "arrival_observed": True, "completion_evidence": {
        "start_sequence": 4, "position_sample": {"north": 1, "east": 2, "sequence": 5, "position_epoch": 1}},
        "arrival_calibration": {"scene_id": "scene", "map_version": "map", "session_position_epoch": 1,
                                "translation_scene_ned_m": {"north": 10, "east": 20}}}
    points = []
    coverage = SimpleNamespace(observe=lambda **kw: points.append(kw),
                               report=lambda: {"area_total_km2": 0.002, "area_covered_km2": 0.001 if points else 0,
                                               "completion_pct": 50 if points else 0, "sample_count": len(points)})
    results = iter([StepOutcome(ok=True, action_type="goto", node_id="UAV-01", raw=raw),
                    StepOutcome(ok=True, action_type="goto", node_id="UAV-01", raw=raw),
                    StepOutcome(ok=True, action_type="goto", node_id="UAV-02", raw={"result": "pass"}),
                    StepOutcome(ok=True, action_type="return_home", node_id="UAV-02", raw={"result": "pass"})])
    progress = MissionProgress(SimpleNamespace(execute_step=lambda step: next(results)),
                               SimpleNamespace(plan_id="mission", steps=steps), scene_id="scene",
                               map_version="map", coverage=coverage)
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", progress)
    assert routes.mission_progress()["completion_pct"] == 0
    progress.execute_step(steps[0])
    progress.execute_step(steps[0])
    progress.execute_step(steps[1])
    assert routes.mission_progress()["completion_pct"] == 50
    assert points == [{"north_m": 11, "east_m": 22}]
    progress.execute_step(steps[2])
    snapshot = routes.mission_progress()
    assert snapshot["degraded"] and snapshot["vehicles_active"] == 1
    assert snapshot["targets_found"] is None and snapshot["coverage_pct"] == 50
    progress.finish("completed")
    assert routes.mission_progress()["status"] == "completed"
    assert routes.mission_progress()["completion_pct"] == 50


def test_plan_route_publishes_progress_between_existing_steps(monkeypatch, tmp_path):
    from tests.unit.test_runtime_action_lifecycle import install_registry
    from tests.unit.test_runtime_ground_completion import GROUND, publish_context

    _, store = install_registry(monkeypatch)
    publish_context(store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "plan.audit.jsonl"))
    monkeypatch.setattr(routes, "_MISSION_PROGRESS", None)
    monkeypatch.delenv("UAV_RUNTIME_COVERAGE_AREA_ID", raising=False)
    observed = []

    def execute(step):
        observed.append(routes.dispatch("GET", "/api/mission/progress")[1]["completion_pct"])
        return StepOutcome(ok=True, action_type="goto", node_id=step.node_id,
                           raw={"result": "pass", "arrival_observed": True})

    monkeypatch.setattr(routes, "RealActionExecutor", lambda **kw: SimpleNamespace(execute_step=execute))
    plan = {
        "plan_id": "observed-mission", "scene_id": GROUND["scene_id"], "map_version": GROUND["map_version"],
        "steps": [{"step_id": f"wp{i}", "action_type": "goto", "node_id": "UAV-02", "params": {}}
                  for i in range(2)],
    }
    code, result = routes.dispatch("POST", "/api/plans/execute",
                                  body={"plan": plan, "operator_id": "fixture-operator", "decision": "approve"})
    assert code == 200 and result["result"] == "completed"
    assert observed == [0, 50]
    progress = routes.mission_progress()
    assert (progress["status"], progress["completion_pct"]) == ("completed", 100)
    assert progress["coverage_reason"] == "coverage_not_configured"
    assert progress["area_covered_km2"] is None and progress["targets_found"] is None


def test_optional_simulation_area_coverage_contract(monkeypatch):
    pytest.importorskip("simulation.px4_gazebo.area_coverage")
    from uav_runtime.http.mission_progress import configured_coverage

    monkeypatch.setenv("UAV_RUNTIME_COVERAGE_AREA_ID", "test-area")
    monkeypatch.setenv("UAV_RUNTIME_COVERAGE_FOOTPRINT_M", "1")
    polygon = [{"north_m": n, "east_m": e} for n, e in [(0, 0), (4, 0), (4, 4), (0, 4)]]
    scene = {"scene_id": "scene", "map_version": "map", "coverage_areas": [{
        "area_id": "test-area", "frame": "scene_ned", "cell_size_m": 1, "polygon": polygon,
    }]}
    provider, reason, boundary = configured_coverage(scene, "map")
    assert reason is None and boundary == polygon
    provider.observe(north_m=1, east_m=1)
    first = provider.report()["area_covered_km2"]
    assert first == pytest.approx(4e-6)
    provider.observe(north_m=1, east_m=1)
    assert provider.report()["area_covered_km2"] == first
    assert configured_coverage(scene, "wrong-map") == (None, "coverage_map_mismatch", None)
