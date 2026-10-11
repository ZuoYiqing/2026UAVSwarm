"""Read-only preflight contract: deterministic fake producers, never sockets."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
import uav_runtime.http.routes as routes
from tests.unit.test_runtime_action_lifecycle import install_registry
from tests.unit.test_runtime_ground_completion import GROUND, publish_context


@pytest.fixture
def preflight_environment(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install factory-created fake sessions and hard-fail every write/start path."""
    registry, store = install_registry(monkeypatch)
    forbidden_calls: list[str] = []
    query_calls: list[tuple[str, str, dict[str, Any]]] = []
    states: dict[str, dict[str, Any]] = {}

    def forbidden(name: str):
        def fail(*_args: Any, **_kwargs: Any) -> None:
            forbidden_calls.append(name)
            raise AssertionError(f"preflight attempted forbidden operation: {name}")
        return fail

    for name in ("connect", "start_receive_loop", "start_gcs_heartbeat", "arm", "set_mode",
                 "takeoff", "land", "return_home", "goto", "hold_position",
                 "send_command_long", "request_local_position_stream", "request_landing_state_stream"):
        monkeypatch.setattr(MavlinkBackendSession, name, forbidden(f"real_session.{name}"))
    for name in ("start_vehicle", "start_all", "stop_vehicle", "stop_all"):
        monkeypatch.setattr(registry, name, forbidden(f"registry.{name}"))

    home = {"verified": True, "x": 12.0, "y": -4.0, "position_epoch": 0,
            "verification": "global_local_xy_crosscheck", "crosscheck_error_m": 0.1,
            "sample_timestamp": "fake-home-stamp", "request_ack": {"command": 512, "result": 0}}
    rtl = {"verified": True, "failure_reason": None,
           "rtl_type": {"param_id": "RTL_TYPE", "param_value": 0.0},
           "rally_points": {"mission_type": 2, "count": 0}}

    for handle in registry.list_vehicles():
        node_id = handle.config.node_id
        handle.config.endpoint = f"fake://{node_id}/owned-session"
        handle.config.telemetry_endpoint = handle.config.endpoint
        session = handle.session
        assert not isinstance(session, MavlinkBackendSession)
        session.connected = True
        session._position_epoch = 0
        session._position_epoch_changed_timestamp = None
        session.command_lock = threading.RLock()
        session._rx_owners = 1
        session._heartbeat_alive = True
        session.connection = SimpleNamespace(mav=SimpleNamespace(**{
            name: forbidden(f"{node_id}.mav.{name}")
            for name in ("param_set_send", "param_ext_set_send", "set_mode_send", "command_long_send",
                         "mission_count_send", "mission_item_send", "mission_item_int_send", "mission_clear_all_send")
        }))
        states[node_id] = {"fresh": True, "landed_fresh": True, "armed": False,
                           "landed_state": 1, "active": False, "stop_sequence": 10,
                           "mode": {"main_mode": 3, "sub_mode": 0}}
        monkeypatch.setattr(session, "autonomous_state", lambda node=node_id: deepcopy(states[node]), raising=False)
        monkeypatch.setattr(session, "receive_owner_count", lambda owner=session: owner._rx_owners, raising=False)
        monkeypatch.setattr(session, "heartbeat_thread_alive", lambda owner=session: owner._heartbeat_alive, raising=False)
        for name in ("connect", "start_receive_loop", "start_gcs_heartbeat", "arm", "set_mode",
                     "takeoff", "land", "return_home", "goto", "hold_position", "send_command_long"):
            monkeypatch.setattr(session, name, forbidden(f"{node_id}.{name}"), raising=False)

        def read_home(*, node=node_id, **kwargs: Any) -> dict[str, Any]:
            query_calls.append((node, "home", kwargs))
            return deepcopy(home)

        def read_rtl(*, node=node_id, **kwargs: Any) -> dict[str, Any]:
            query_calls.append((node, "rtl", kwargs))
            return deepcopy(rtl)

        monkeypatch.setattr(session, "request_home_position", read_home, raising=False)
        monkeypatch.setattr(session, "verify_home_rtl_destination", read_rtl, raising=False)

    calibration, health = publish_context(store)
    environment = SimpleNamespace(registry=registry, store=store, states=states, home=home, rtl=rtl,
                                  calls=query_calls, forbidden_calls=forbidden_calls,
                                  calibration=calibration, health=health)
    yield environment
    assert forbidden_calls == []


def request_preflight(query: str = "node_id=UAV-02") -> tuple[int, dict[str, Any]]:
    return routes.dispatch("GET", "/api/preflight", query=query)


def assert_not_ready(result: dict[str, Any], reason: str) -> None:
    assert result["status"] == "not_ready"
    assert reason in result["reason_codes"]
    assert result["execution_authorized"] is False
    assert result["flight_command_sent"] is False


@pytest.mark.parametrize("query", [
    "", "node_id=", "node_id=%20", "node_id=UAV-02&node_id=UAV-02",
    "node_id=UAV-02&node_id=UAV-03", "node_id=UAV-02&endpoint=fake%3A%2F%2Foverride",
    "node_id=UAV-02&transport_endpoint=fake%3A%2F%2Foverride",
    "node_id=UAV-02&system_id=3", "node_id=UAV-02&component_id=2",
])
def test_preflight_requires_one_explicit_node_and_rejects_overrides(preflight_environment, query):
    status, result = request_preflight(query)
    assert status == 400
    assert result["error"] == "invalid_parameter"
    assert result["field"] == "node_id"
    assert preflight_environment.calls == []


def test_unknown_node_never_queries_a_default_vehicle(preflight_environment):
    status, result = request_preflight("node_id=UAV-99")
    assert status == 404
    assert result["error"] == "unknown_node"
    assert preflight_environment.calls == []


def test_success_queries_only_the_selected_existing_session_and_preserves_contract(preflight_environment):
    env = preflight_environment
    status, result = request_preflight()
    assert status == 200
    assert result["status"] == "ready"
    assert result["reason_codes"] == []
    assert result["contract_version"] == "1.0"
    assert result["preflight_id"].startswith("preflight-")
    assert result["timestamp"]
    assert result["node_id"] == "UAV-02"
    assert result["source"] == "runtime_persistent_session"
    assert result["execution_authorized"] is False
    assert result["flight_command_sent"] is False
    assert result["home_evidence"] == env.home
    assert result["rtl_destination_evidence"] == env.rtl
    assert result["ground_context"] == {"calibration_version": "cal-2", "local_origin_id": "origin-2",
                                         "run_id": "run-2", "ground_reference": GROUND}
    assert result["error_class"] is None
    assert env.calls == [("UAV-02", "home", {"timeout_s": 2.0}), ("UAV-02", "rtl", {"timeout_s": 2.0})]
    assert set(result["nodes"]) == {"UAV-01", "UAV-02", "UAV-03"}
    for node_id, node in result["nodes"].items():
        assert node["system_id"] == int(node_id[-1])
        assert node["component_id"] == 1
        assert node["endpoint"].startswith("fake://")
        assert node["persistent_session"] is True
        assert node["fresh_disarmed"] is True
        assert node["busy"] is False
        assert node["state_evidence"]["armed"] is False
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("node_id", ["UAV-02", "UAV-03"])
@pytest.mark.parametrize("missing", ["connected", "connection", "rx_owner", "heartbeat"])
def test_unavailable_persistent_session_never_connects_or_queries(preflight_environment, node_id, missing):
    env = preflight_environment
    session = env.registry.get_vehicle(node_id).session
    if missing == "connected":
        session.connected = False
    elif missing == "connection":
        session.connection = None
    elif missing == "rx_owner":
        session._rx_owners = 0
    else:
        session._heartbeat_alive = False
    status, result = request_preflight()
    assert status == 200
    assert_not_ready(result, f"persistent_session_unavailable:{node_id}")
    assert env.calls == []


@pytest.mark.parametrize("node_id", ["UAV-02", "UAV-03"])
@pytest.mark.parametrize("busy_kind", ["active", "autonomous"])
def test_busy_fleet_node_prevents_all_diagnostic_queries(preflight_environment, node_id, busy_kind):
    env = preflight_environment
    state = env.registry.get_vehicle(node_id).runtime_state
    if busy_kind == "active":
        state.active_action = "takeoff"
        state.active_action_id = "fake-active-action"
    else:
        state.autonomous_action = "return_home"
        state.autonomous_action_id = "fake-autonomous-action"
    _, result = request_preflight()
    assert_not_ready(result, f"node_busy:{node_id}")
    assert env.calls == []


@pytest.mark.parametrize("node_id", ["UAV-01", "UAV-02", "UAV-03"])
@pytest.mark.parametrize("change", [{"armed": True}, {"armed": None}, {"fresh": False}])
def test_armed_unknown_or_stale_fleet_node_prevents_queries(preflight_environment, node_id, change):
    env = preflight_environment
    env.states[node_id].update(change)
    _, result = request_preflight()
    assert_not_ready(result, f"fresh_disarmed_evidence_unavailable:{node_id}")
    assert env.calls == []


@pytest.mark.parametrize("change", [{"landed_fresh": False}, {"landed_state": 2}, {"landed_state": None}])
def test_selected_landed_evidence_must_be_fresh_and_on_ground(preflight_environment, change):
    env = preflight_environment
    env.states["UAV-02"].update(change)
    _, result = request_preflight()
    assert_not_ready(result, "fresh_landed_evidence_unavailable")
    assert env.calls == []


def test_missing_ground_reference_prevents_queries(preflight_environment):
    env = preflight_environment
    env.health.pop("ground_reference")
    env.store.update_simulation_evidence(env.health)
    _, result = request_preflight()
    assert_not_ready(result, "ground_reference_unavailable")
    assert env.calls == []
    assert result["home_evidence"] is None and result["rtl_destination_evidence"] is None


def test_unverified_home_never_reports_ready(preflight_environment):
    env = preflight_environment
    env.home.update(verified=False, failure_reason="home_position_unverified")
    _, result = request_preflight()
    assert_not_ready(result, "home_position_unverified")
    assert result["home_evidence"]["verified"] is False


@pytest.mark.parametrize("error", [None, True, -0.1, 0.75, 0.9, float("nan"), float("inf")])
def test_home_uncertainty_must_be_finite_and_strictly_below_arrival_tolerance(preflight_environment, error):
    env = preflight_environment
    env.home["crosscheck_error_m"] = error
    _, result = request_preflight()
    assert_not_ready(result, "home_position_uncertainty_exceeds_tolerance")
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("reason", ["rtl_destination_unverified", "rtl_home_configuration_unsupported"])
def test_unverified_or_unsupported_rtl_configuration_never_reports_ready(preflight_environment, reason):
    env = preflight_environment
    env.rtl.update(verified=False, failure_reason=reason)
    _, result = request_preflight()
    assert_not_ready(result, reason)
    assert result["rtl_destination_evidence"]["verified"] is False


@pytest.mark.parametrize("change", ["expired", "calibration_changed", "ground_changed"])
def test_context_expiring_or_changing_during_queries_invalidates_report(preflight_environment, monkeypatch, change):
    env = preflight_environment
    session = env.registry.get_vehicle("UAV-02").session

    def read_rtl(**kwargs):
        env.calls.append(("UAV-02", "rtl", kwargs))
        if change == "expired":
            env.store._coordinate_calibrations["UAV-02"]["received_monotonic"] -= 61.0
        elif change == "calibration_changed":
            env.store._coordinate_calibrations["UAV-02"]["calibration_version"] = "changed"
        else:
            env.health["ground_reference"] = {**GROUND, "surface_id": "replacement-ground"}
            env.store.update_simulation_evidence(env.health)
        return deepcopy(env.rtl)

    monkeypatch.setattr(session, "verify_home_rtl_destination", read_rtl)
    _, result = request_preflight()
    reason = "ground_reference_unavailable" if change == "expired" else "ground_reference_changed_or_stale"
    assert_not_ready(result, reason)
    assert [stage for _, stage, _ in env.calls] == ["home", "rtl"]


@pytest.mark.parametrize("stage", ["home", "rtl"])
def test_query_exceptions_are_structured_not_ready_reports(preflight_environment, monkeypatch, stage):
    env = preflight_environment
    session = env.registry.get_vehicle("UAV-02").session

    def fail(**kwargs):
        env.calls.append(("UAV-02", stage, kwargs))
        raise RuntimeError("fake diagnostic failure")

    method = "request_home_position" if stage == "home" else "verify_home_rtl_destination"
    monkeypatch.setattr(session, method, fail)
    status, result = request_preflight()
    assert status == 200
    assert_not_ready(result, "preflight_query_exception")
    assert result["error_class"] == "RuntimeError"


@pytest.mark.parametrize("producer", ["state", "ground"])
def test_observation_producer_exceptions_fail_closed_without_http_crash(preflight_environment, monkeypatch, producer):
    env = preflight_environment

    def fail(*_args, **_kwargs):
        raise RuntimeError("fake producer failure")

    if producer == "state":
        monkeypatch.setattr(env.registry.get_vehicle("UAV-03").session, "autonomous_state", fail)
    else:
        monkeypatch.setattr(env.store, "ground_landing_context", fail)
    status, result = request_preflight()
    assert status == 200
    assert result["status"] == "not_ready"
    assert result["error_class"] == "RuntimeError"
    assert result["reason_codes"]
    assert result["execution_authorized"] is False
    assert result["flight_command_sent"] is False
    assert env.calls == []


def test_isolation_change_after_home_skips_rtl_query(preflight_environment, monkeypatch):
    env = preflight_environment
    session = env.registry.get_vehicle("UAV-02").session

    def read_home(**kwargs):
        env.calls.append(("UAV-02", "home", kwargs))
        env.states["UAV-03"]["armed"] = True
        return deepcopy(env.home)

    monkeypatch.setattr(session, "request_home_position", read_home)
    _, result = request_preflight()
    assert_not_ready(result, "fresh_disarmed_evidence_unavailable:UAV-03")
    assert [stage for _, stage, _ in env.calls] == ["home"]


@pytest.mark.parametrize("lock_name", ["handle", "session"])
def test_lock_contention_returns_without_waiting_behind_an_action(preflight_environment, lock_name):
    env = preflight_environment
    handle = env.registry.get_vehicle("UAV-02")
    lock = handle.command_lock if lock_name == "handle" else handle.session.command_lock
    completed = threading.Event()
    responses: list[tuple[int, dict[str, Any]]] = []
    failures: list[BaseException] = []

    def check():
        try:
            responses.append(request_preflight())
        except BaseException as exc:
            failures.append(exc)
        finally:
            completed.set()

    lock.acquire()
    worker = threading.Thread(target=check, daemon=True)
    try:
        worker.start()
        assert completed.wait(timeout=1.0), "preflight queued behind a held command lock"
    finally:
        lock.release()
        worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert failures == []
    assert responses[0][0] == 200
    assert_not_ready(responses[0][1], "node_busy:UAV-02")
    assert env.calls == []
    # A failed second acquire must release the already-acquired first lock.
    assert handle.command_lock.acquire(blocking=False)
    handle.command_lock.release()


@pytest.mark.parametrize("producer", ["state", "ground"])
def test_final_producer_failure_cannot_turn_successful_queries_into_ready(preflight_environment, monkeypatch, producer):
    env = preflight_environment

    def fail(*_args, **_kwargs):
        raise RuntimeError("fake final producer failure")

    def read_rtl(**kwargs):
        env.calls.append(("UAV-02", "rtl", kwargs))
        if producer == "state":
            monkeypatch.setattr(env.registry.get_vehicle("UAV-03").session, "autonomous_state", fail)
        else:
            monkeypatch.setattr(env.store, "ground_landing_context", fail)
        return deepcopy(env.rtl)

    monkeypatch.setattr(env.registry.get_vehicle("UAV-02").session, "verify_home_rtl_destination", read_rtl)
    status, result = request_preflight()
    assert status == 200
    assert_not_ready(result, "preflight_query_exception")
    assert result["error_class"] == "RuntimeError"
    assert [stage for _, stage, _ in env.calls] == ["home", "rtl"]


def test_checked_in_fixture_projections_match_producer(preflight_environment):
    fixture = json.loads((Path(__file__).resolve().parents[2] / "docs/fixtures/runtime_preflight_v1.json").read_text(encoding="utf-8"))
    request = fixture["request"]
    status, ready = routes.dispatch(request["method"], request["path"], query=request["query"])
    assert status == 200
    for key, value in fixture["ready_response_projection"].items():
        assert ready[key] == value
    assert set(fixture["dynamic_fields"]) <= ready.keys()
    preflight_environment.states["UAV-03"]["armed"] = True
    _, not_ready = routes.dispatch(request["method"], request["path"], query=request["query"])
    for key, value in fixture["not_ready_response_projection"].items():
        assert not_ready[key] == value
