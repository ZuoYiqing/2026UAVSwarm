"""Deterministic dispatcher evidence only: no socket or PX4 connection."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import uav_runtime.adapters.mavlink_backend_session as session_module
import uav_runtime.http.routes as routes
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from tests.unit.test_runtime_action_lifecycle import install_registry, action_body, successful_land


GROUND = {
    "contract_version": "1.0", "scene_id": "simple_recon_v0_1", "map_version": "simple_recon_v0_1-map-1",
    "world_sha256": "a" * 64, "frame": "scene_ned", "kind": "horizontal_plane",
    "ground_down_m": 0.0, "source": "world_collision_geometry", "surface_id": "ground_plane",
    "xy_bounds_m": {"north_min_m": -1000, "north_max_m": 1000, "east_min_m": -1000, "east_max_m": 1000},
}
ZERO = {"north": 0.0, "east": 0.0, "down": 0.0}


@pytest.fixture
def evidence_session(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(MavlinkBackendSession, "start_receive_loop", lambda self: False)
    session = MavlinkBackendSession("sitl", True, "fake://no-network", connected=True, connection=object())
    session._rx_condition.wait = lambda timeout=None: clock.__setitem__(0, clock[0] + (timeout or 0.05))
    return session, clock


def ground_history(session, rows, *, armed=False, landed=1):
    session._armed_states = [(1, armed, 99.3, "armed-stamp")]
    session._landed_states = [(2, landed, 99.3, "landed-stamp")]
    session._local_positions = [(3 + i, x, y, z, stamp, f"position-{i}") for i, (x, y, z, stamp) in enumerate(rows)]


def observe(session, **kwargs):
    return session.observe_ground_landing(timeout_s=0.15, after_sequence=0, ground_reference=GROUND,
                                          translation_scene_ned_m=ZERO, **kwargs)


def test_ground_completion_needs_stable_post_command_samples(evidence_session):
    session, _ = evidence_session
    ground_history(session, [(15, 8, 0.02, 99.4), (15, 8, 0.01, 99.7), (15, 8, 0, 100)])
    result = observe(session)
    assert result["completion_reached"] is True
    assert result["ground_stable_samples"] == 3
    assert result["ground_stable_ms"] >= 500
    assert result["ground_check"]["scene_position_ned_m"]["east"] == 8


@pytest.mark.parametrize("rows", [
    [(15.6, -.7, -9.98, 99.4), (15.6, -.7, -9.98, 99.7), (15.6, -.7, -9.98, 100)],
    [(0, 0, 0, 99.4), (0, 0, -10, 99.7), (0, 0, 0, 100)],
    [(0, 0, 0, 99.0), (0, 0, 0, 99.1), (0, 0, 0, 100)],
    [(0, 0, 0, 98.0), (0, 0, 0, 98.3), (0, 0, 0, 98.6)],
    [(2000, 0, 0, 99.4), (2000, 0, 0, 99.7), (2000, 0, 0, 100)],
])
def test_roof_outlier_gap_stale_or_outside_reference_never_complete(evidence_session, rows):
    session, _ = evidence_session
    ground_history(session, rows)
    result = observe(session)
    assert result["completion_reached"] is False


def test_old_ground_cache_is_not_this_land_evidence(evidence_session):
    session, _ = evidence_session
    ground_history(session, [(0, 0, 0, 99.4), (0, 0, 0, 99.7), (0, 0, 0, 100)])
    result = session.observe_ground_landing(timeout_s=.1, after_sequence=10,
                                            ground_reference=GROUND, translation_scene_ned_m=ZERO)
    assert result["completion_reached"] is False
    assert result["ground_stable_samples"] == 0


def test_per_vehicle_offset_applied_exactly_once(evidence_session):
    session, _ = evidence_session
    ground_history(session, [(0, 0, -.5, 99.4), (0, 0, -.5, 99.7), (0, 0, -.5, 100)])
    result = session.observe_ground_landing(timeout_s=.1, after_sequence=0, ground_reference=GROUND,
                                            translation_scene_ned_m={"north": 0., "east": 8., "down": .5})
    assert result["completion_reached"] is True
    assert result["ground_check"]["scene_position_ned_m"] == {"north": 0., "east": 8., "down": 0.}


def publish_context(store, *, node_id="UAV-02"):
    stamp = datetime.now(timezone.utc).isoformat()
    store.vehicle_registry.scene_id = GROUND["scene_id"]
    calibration = {
        "contract_version": "1.0", "node_id": node_id, "scene_id": GROUND["scene_id"],
        "map_version": GROUND["map_version"], "local_origin_id": "origin-2", "calibration_version": "cal-2",
        "scene_origin": {"kind": "gazebo_world", "north_m": 0., "east_m": 0., "down_m": 0.},
        "altitude_reference": "scene_origin_z_down", "source_timestamp": stamp, "valid_for_ms": 60000,
        "axis_alignment": "ned_aligned", "origin_continuity": "verified", "context": {"run_id": "run-2"},
        "translation_scene_ned_m": {"north": 0., "east": 8., "down": 0.},
    }
    health = {"contract_version": "1.0", "scene_id": GROUND["scene_id"], "map_version": GROUND["map_version"],
              "run_id": "run-2", "world_sha256": GROUND["world_sha256"], "source_timestamp": stamp, "valid_for_ms": 60000,
              "world": {"status": "ready"}, "clock_advancing": True,
              "models": [{"node_id": node_id, "status": "ready"}], "ground_reference": GROUND}
    store.update_coordinate_calibration(calibration)
    store.update_simulation_evidence(health)
    return calibration, health


def test_plain_land_can_succeed_without_a_validated_pad(monkeypatch, tmp_path):
    registry, store = install_registry(monkeypatch)
    publish_context(store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    seen = {}
    def ground_land(self, **kwargs):
        seen.update(kwargs)
        return successful_land(self)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", ground_land)
    body = action_body("UAV-02", key="ground-land")
    _, first = routes.dispatch("POST", "/api/actions/land", body=body)
    _, retry = routes.dispatch("POST", "/api/actions/land", body=body)
    assert first["status"] == "succeeded"
    assert retry["action_id"] == first["action_id"] and retry["idempotent_replay"]
    assert seen["ground_reference"] == GROUND
    assert "landing_site" not in seen or not seen["landing_site"]
    assert registry.get_vehicle("UAV-02").session.calls == ["land"]


@pytest.mark.parametrize("change", ["no_reference", "wrong_run", "wrong_map", "wrong_world", "stale_source", "invalid_bounds"])
def test_ground_context_rejects_missing_mismatched_or_replayed_evidence(monkeypatch, change):
    _, store = install_registry(monkeypatch)
    _, health = publish_context(store)
    if change == "no_reference":
        health.pop("ground_reference")
    elif change == "wrong_run":
        health["run_id"] = "different-run"
    elif change == "wrong_map":
        health["map_version"] = "other-map"
    elif change == "wrong_world":
        health["world_sha256"] = "b" * 64
    elif change == "stale_source":
        health["source_timestamp"] = "2000-01-01T00:00:00Z"
    else:
        health["ground_reference"] = {**GROUND, "xy_bounds_m": {"north_min_m": float("nan")}}
    store.update_simulation_evidence(health)
    assert store.ground_landing_context("UAV-02") is None


def test_calibration_expires_during_land_cannot_report_success(monkeypatch, tmp_path):
    _, store = install_registry(monkeypatch)
    publish_context(store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    def changing(self, **kwargs):
        store._coordinate_calibrations["UAV-02"]["calibration_version"] = "changed"
        return successful_land(self)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", changing)
    _, result = routes.dispatch("POST", "/api/actions/land", body=action_body("UAV-02", key="changed"))
    assert result["result"] == "fail"
    assert result["failure_reason"] == "ground_reference_changed_or_stale"


def message(kind, *, system=2, **fields):
    return SimpleNamespace(get_type=lambda: kind, get_srcSystem=lambda: system,
                           get_srcComponent=lambda: 1, **fields)


def feed_home(session, *, home_x=0., local_x=0., global_lat=470000000, boot=1000):
    session.dispatch_message(message("LOCAL_POSITION_NED", x=local_x, y=0., z=-3., time_boot_ms=boot))
    session.dispatch_message(message("GLOBAL_POSITION_INT", lat=global_lat, lon=80000000, time_boot_ms=boot))
    session.dispatch_message(message("HOME_POSITION", x=home_x, y=0., z=0., latitude=470000000,
                                     longitude=80000000, altitude=500000))


@pytest.mark.parametrize("home_x,local_x,valid", [(0., 0., True), (12., 12., True), (0., 12., False)])
def test_home_query_verifies_actual_xy_and_never_defaults_missing_local_to_zero(evidence_session, monkeypatch, home_x, local_x, valid):
    session, _ = evidence_session
    def query(self, command, params, **kwargs):
        assert command == 512 and params[0] == 242
        feed_home(self, home_x=home_x, local_x=local_x)
        return {"command": command, "result": 0}
    monkeypatch.setattr(MavlinkBackendSession, "_send_and_wait_ack", query)
    result = session.request_home_position(timeout_s=.1)
    assert result["verified"] is valid
    if valid:
        assert result["x"] == home_x and result["request_ack"]["result"] == 0
    else:
        assert result["failure_reason"] == "home_position_unverified"


def test_cached_home_is_not_this_request_evidence(evidence_session, monkeypatch):
    session, _ = evidence_session
    feed_home(session)
    monkeypatch.setattr(MavlinkBackendSession, "_send_and_wait_ack", lambda *a, **kw: {"result": 0})
    assert session.request_home_position(timeout_s=.1)["verified"] is False


@pytest.mark.parametrize("change", ["stale", "unsynced", "wrong_node", "origin_reset"])
def test_home_query_rejects_stale_wrong_node_or_origin_change(evidence_session, monkeypatch, change):
    session, clock = evidence_session
    session.expected_target_system = 2
    session._last_position_boot_ms = 1000
    def query(self, *a, **kw):
        feed_home(self, boot=100 if change == "origin_reset" else 1000)
        if change == "stale":
            clock[0] += 3
        elif change == "unsynced":
            self._global_position["time_boot_ms"] = 500
        elif change == "wrong_node":
            self._home_position = None
            self.dispatch_message(message("HOME_POSITION", system=1, x=0., y=0., latitude=470000000, longitude=80000000))
        return {"command": 512, "result": 0}
    monkeypatch.setattr(MavlinkBackendSession, "_send_and_wait_ack", query)
    result = session.request_home_position(timeout_s=.1)
    assert result["verified"] is False
    if change == "origin_reset":
        assert result["failure_reason"] == "home_reference_changed"


def test_ack_interval_origin_reset_invalidates_land_evidence(evidence_session):
    session, _ = evidence_session
    ground_history(session, [(0, 0, 0, 99.4), (0, 0, 0, 99.7), (0, 0, 0, 100)])
    session._position_epoch = 1
    result = session.observe_ground_landing(timeout_s=.1, after_sequence=0, ground_reference=GROUND,
                                            translation_scene_ned_m=ZERO, expected_position_epoch=0)
    assert result["completion_reached"] is False and result["failure_reason"] == "local_origin_changed"


def test_return_home_idempotency_includes_completion_tolerance(monkeypatch):
    _, store = install_registry(monkeypatch)
    def no_home(self, **kw):
        return {"result": "fail", "failure_reason": "home_position_unavailable", "completion_state": "unknown"}
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_return_home_action", no_home)
    body = action_body("UAV-02", key="rtl-fingerprint")
    _, first = routes.dispatch("POST", "/api/actions/return-home", body=body)
    status, conflict = routes.dispatch("POST", "/api/actions/return-home", body={**body, "home_tolerance_m": 1.0})
    assert first["failure_reason"] == "home_position_unavailable"
    assert status == 409 and conflict["error"] == "idempotency_conflict"


def test_origin_reset_invalidates_calibration_and_old_republication(monkeypatch):
    registry, store = install_registry(monkeypatch)
    handle = registry.get_vehicle("UAV-02")
    for vehicle in registry.list_vehicles():
        vehicle.config.metadata["initial_pose"] = {"x_m": 0., "y_m": 0., "z_m": 0.}
    handle.session._position_epoch = 0
    calibration, _ = publish_context(store)
    assert store.ground_landing_context("UAV-02") is not None
    handle.session._position_epoch = 1
    handle.session._position_epoch_changed_timestamp = "2099-01-01T00:00:00Z"
    assert store.ground_landing_context("UAV-02") is None
    store.update_coordinate_calibration(calibration)
    assert store.ground_landing_context("UAV-02") is None
    assert store.vehicle_snapshot()["vehicles"][1]["spatial"]["public_position_usable"] is False


def test_home_crosscheck_error_cannot_exceed_arrival_tolerance(evidence_session, monkeypatch):
    session, _ = evidence_session
    monkeypatch.setattr(MavlinkBackendSession, "start_gcs_heartbeat", lambda *a, **kw: False)
    monkeypatch.setattr(MavlinkBackendSession, "request_home_position", lambda *a, **kw: {
        "verified": True, "x": 0., "y": 0., "crosscheck_error_m": 1.0})
    sent = []
    monkeypatch.setattr(MavlinkBackendSession, "set_mode", lambda *a, **kw: sent.append(kw))
    result = session.return_home(timeout_s=.1, home_tolerance_m=.75)
    assert result["failure_reason"] == "home_position_uncertainty_exceeds_tolerance"
    assert not sent


@pytest.mark.parametrize("action", ["land", "return_home"])
def test_gateway_exception_keeps_autonomous_guard_and_terminal_failure(monkeypatch, action):
    registry, store = install_registry(monkeypatch)
    method = "execute_land_action" if action == "land" else "execute_return_home_action"
    def fail(self, **kw):
        raise RuntimeError("ambiguous_transport_failure")
    monkeypatch.setattr(routes.Px4SitlBackend, method, fail)
    route = "land" if action == "land" else "return-home"
    _, result = routes.dispatch("POST", f"/api/actions/{route}", body=action_body("UAV-02", key=action))
    assert result["status"] == "failed" and result["code"] == "adapter_execution_exception"
    assert result["autonomous_execution_may_continue"] is True
    assert store.action(result["action_id"])["status"] == "failed"
    assert registry.get_vehicle("UAV-02").runtime_state.autonomous_action_id == result["action_id"]


def test_delivery_fixture_matches_runtime_requests_and_produces_roof_rejection(evidence_session, monkeypatch):
    from uav_runtime.http.schemas import BackendRequest, ReturnHomeRequest
    fixture = json.loads((Path(__file__).resolve().parents[2] / "docs/fixtures/runtime_ground_completion_v1_1.json").read_text(encoding="utf-8"))
    assert BackendRequest.from_json(fixture["land_request"]).node_id == "UAV-02"
    assert ReturnHomeRequest.from_json(fixture["return_home_request"]).home_tolerance_m == .75
    session, _ = evidence_session
    rows = [(15.6, -.7, -9.98, stamp) for stamp in (99.4, 99.7, 100.)]
    ground_history(session, rows)
    result = session.observe_ground_landing(timeout_s=.15, after_sequence=0,
                                            ground_reference=fixture["ground_reference"], translation_scene_ned_m=ZERO)
    example = fixture["roof_land_completion_evidence"]
    for key in ("status", "completion_reached", "physical_landed_disarmed", "armed", "landed_state", "failure_reason", "ground_check"):
        assert result[key] == example[key]


def test_vehicle_view_reports_autonomous_guard_after_http_observation(monkeypatch):
    registry, store = install_registry(monkeypatch)
    for handle in registry.list_vehicles():
        handle.config.metadata["initial_pose"] = {"x_m": 0., "y_m": 0., "z_m": 0.}
    registry.admit_action("UAV-02", "return_home", "rtl-observation-ended")
    registry.retain_autonomous_action("UAV-02", "rtl-observation-ended", "return_home")
    registry.release_action("UAV-02", "rtl-observation-ended")
    view = store.vehicle_snapshot()["vehicles"]
    assert view[1]["control"]["autonomous_execution_may_continue"] is True
    assert view[1]["control"].get("active_action_id") is None
    assert view[0]["control"]["autonomous_execution_may_continue"] is False
    assert view[2]["control"]["autonomous_execution_may_continue"] is False


def test_set_mode_cannot_confirm_from_old_heartbeat(evidence_session, monkeypatch):
    session, _ = evidence_session
    session.dispatch_message(message("HEARTBEAT", base_mode=128, custom_mode=(4 << 16) | (5 << 24)))
    monkeypatch.setattr(MavlinkBackendSession, "send_command_long", lambda *a, **kw: None)
    monkeypatch.setattr(MavlinkBackendSession, "wait_command_ack", lambda *a, **kw: {"command": 176, "result": 0})
    # wait_mode uses sleep rather than condition; advance the deterministic clock.
    clock = evidence_session[1]
    monkeypatch.setattr(session_module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    result = session.set_mode(main_mode=4, sub_mode=5, timeout_s=.1, confirm_timeout_s=.1)
    assert result["ack"]["result"] == 0 and result["confirmed"] is False


def test_land_cancel_during_home_query_prevents_late_rtl(evidence_session, monkeypatch):
    session, _ = evidence_session
    cancel = threading.Event()
    monkeypatch.setattr(MavlinkBackendSession, "start_gcs_heartbeat", lambda *a, **kw: False)
    def home(*a, **kw):
        cancel.set()
        return {"verified": True, "x": 0., "y": 0., "crosscheck_error_m": 0.}
    monkeypatch.setattr(MavlinkBackendSession, "request_home_position", home)
    sent = []
    monkeypatch.setattr(MavlinkBackendSession, "set_mode", lambda *a, **kw: sent.append(kw))
    result = session.return_home(timeout_s=.1, cancel_event=cancel)
    assert result["failure_reason"] == "cancelled" and not sent


def test_return_home_http_routes_without_pad_and_replays_verified_arrival(monkeypatch):
    registry, store = install_registry(monkeypatch)
    def arrived(self, **kwargs):
        self.session.calls.append("return_home")
        assert "home_local_north_m" not in kwargs and "landing_site_id" not in kwargs
        return {"action": "return_home", "result": "pass", "completion_state": "arrived_at_home",
                "home_evidence": {"verified": True, "x": 12., "y": -4.},
                "completion_evidence": {"reason": "arrived_at_home", "arrival_samples": 12},
                "autonomous_execution_may_continue": True}
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_return_home_action", arrived)
    body = action_body("UAV-02", key="rtl-arrival")
    _, first = routes.dispatch("POST", "/api/actions/return-home", body=body)
    _, replay = routes.dispatch("POST", "/api/actions/return-home", body=body)
    assert first["status"] == "succeeded" and first["home_evidence"]["x"] == 12.
    assert replay["action_id"] == first["action_id"] and replay["idempotent_replay"]
    assert registry.get_vehicle("UAV-02").session.calls == ["return_home"]
    assert registry.get_vehicle("UAV-01").session.calls == []
    assert registry.get_vehicle("UAV-03").session.calls == []


@pytest.mark.parametrize("rtl_type,rally_count,verified", [(0., 0, True), (1., 0, False), (0., 1, False), (float("nan"), 0, False)])
def test_rtl_destination_requires_actual_home_only_configuration(evidence_session, rtl_type, rally_count, verified):
    session, _ = evidence_session
    sent = []
    def parameter(*args):
        sent.append(("parameter_read", args))
        session.dispatch_message(message("PARAM_VALUE", param_id=b"RTL_TYPE\x00", param_value=rtl_type, param_type=6))
    def rally(*args):
        sent.append(("mission_list", args))
        session.dispatch_message(message("MISSION_COUNT", mission_type=2, count=rally_count, target_system=255, target_component=0))
    session.connection = SimpleNamespace(mav=SimpleNamespace(
        srcSystem=255, srcComponent=0, param_request_read_send=parameter,
        mission_request_list_send=rally, mission_ack_send=lambda *args: sent.append(("mission_ack", args))))
    result = session.verify_home_rtl_destination(timeout_s=.1)
    assert result["verified"] is verified
    assert sent[0][0] == "parameter_read" and sent[1][0] == "mission_list"
    if not verified:
        assert result["failure_reason"] == "rtl_home_configuration_unsupported"


def test_old_or_other_gcs_rally_evidence_cannot_verify_current_request(evidence_session):
    session, _ = evidence_session
    session._rtl_type_evidence = {"sequence": 0, "param_value": 0., "received_monotonic": 100.}
    session._rally_count_evidence = {"sequence": 0, "count": 0, "received_monotonic": 100.}
    session.connection = SimpleNamespace(mav=SimpleNamespace(
        srcSystem=255, srcComponent=0, param_request_read_send=lambda *args: None,
        mission_request_list_send=lambda *args: session.dispatch_message(message(
            "MISSION_COUNT", mission_type=2, count=0, target_system=254, target_component=0))))
    result = session.verify_home_rtl_destination(timeout_s=.1)
    assert result["verified"] is False and result["failure_reason"] == "rtl_destination_unverified"


def test_unknown_rtl_configuration_does_not_send_mode(evidence_session, monkeypatch):
    session, _ = evidence_session
    monkeypatch.setattr(MavlinkBackendSession, "start_gcs_heartbeat", lambda *args, **kw: False)
    monkeypatch.setattr(MavlinkBackendSession, "request_home_position", lambda *args, **kw: {
        "verified": True, "x": 0., "y": 0., "latitude": 470000000, "longitude": 80000000})
    monkeypatch.setattr(MavlinkBackendSession, "verify_home_rtl_destination", lambda *args, **kw: {
        "verified": False, "failure_reason": "rtl_destination_unverified"})
    sent = []
    monkeypatch.setattr(MavlinkBackendSession, "set_mode", lambda *args, **kw: sent.append(kw))
    result = session.return_home(timeout_s=.1)
    assert result["failure_reason"] == "rtl_destination_unverified"
    assert result["autonomous_execution_may_continue"] is False and not sent
