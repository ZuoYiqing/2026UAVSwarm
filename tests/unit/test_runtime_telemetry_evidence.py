"""Health producer tests use dispatcher fixtures only: no PX4 sockets or model."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uav_runtime.adapters import mavlink_backend_session as session_module
from uav_runtime.http import routes
from uav_runtime.http import telemetry_evidence as evidence_module
from uav_runtime.http.telemetry_evidence import PATH, local_evidence, remote_evidence
from uav_runtime.platform.contract import stamp
from uav_runtime.platform.view import produce_view
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "docs/fixtures/runtime_telemetry_evidence_v1.json").read_text())


def message(kind, number, **fields):
    return SimpleNamespace(get_type=lambda: kind, get_srcSystem=lambda: number, get_srcComponent=lambda: 1, **fields)


class MAVLink_unknown:
    """No-wire fixture for pymavlink's negative-ID undecoded wrapper."""
    def get_type(self): return "UNKNOWN_291"
    def get_msgId(self): return -2
    def get_srcSystem(self): return 0
    def get_srcComponent(self): return 0


@pytest.fixture
def fleet(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(evidence_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(session_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(session_module, "datetime", SimpleNamespace(now=lambda tz: datetime.fromtimestamp(clock[0], tz)))
    registry = VehicleRegistry(scene_id="simple_recon_v0_1")
    for number in (1, 2, 3):
        handle = registry.register_vehicle(VehicleConfig(node_id=f"UAV-0{number}", system_id=number, component_id=1,
                                                        endpoint=f"udpin:127.0.0.1:{14539 + number}"))
        handle.session.connected = True
        handle.session._rx_thread = SimpleNamespace(is_alive=lambda: True, join=lambda **kwargs: None)
        handle.session.dispatch_message(message("HEARTBEAT", number, base_mode=0))
        handle.session.dispatch_message(message("LOCAL_POSITION_NED", number, x=0, y=0, z=0))
    def forbidden(*args, **kwargs):
        raise AssertionError("health GET must never perform transport/action I/O")
    for method in ("connect", "start_receive_loop", "send_command_long", "request_local_position_stream"):
        monkeypatch.setattr(session_module.MavlinkBackendSession, method, forbidden)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", None)
    monkeypatch.setattr(routes, "RUNTIME_RUN_ID", "run-fixture")
    return registry, clock


def packet(registry, clock):
    result = local_evidence(registry, "run-fixture", clock=lambda: clock[0])
    result["vehicles"] = [row for row in result["vehicles"] if row["node_id"] == "UAV-02"]
    return {"fresh": True, "run_id": "run-fixture", "age_ms": 0, "runtime_telemetry": result}


def remote(view, clock):
    return remote_evidence(view, scene_id="simple_recon_v0_1", run_id="run-fixture", clock=lambda: clock[0])


def test_fixture_matches_real_producer_exactly(fleet):
    registry, clock = fleet
    assert local_evidence(registry, "run-fixture", clock=lambda: clock[0]) == FIXTURE


def test_actual_simulation_consumer_accepts_producer_and_rejects_independent_stale(fleet, monkeypatch):
    from simulation.px4_gazebo import health
    from simulation.px4_gazebo.evidence import freshness
    registry, clock = fleet
    manifest = {"scene_id": registry.scene_id, "vehicles": [
        {"node_id": h.config.node_id, "command_endpoint": h.config.endpoint} for h in registry.list_vehicles()]}
    monkeypatch.setattr(health, "freshness", lambda payload: freshness(payload, now=clock[0]))
    evidence = local_evidence(registry, "run-fixture")
    result = health._runtime_telemetry_probes(manifest, evidence, run_id="run-fixture")
    assert all(row["heartbeat_fresh"] and row["telemetry_fresh"] for row in result.values())
    clock[0] += 2
    registry.get_vehicle("UAV-02").session.dispatch_message(message("HEARTBEAT", 2, base_mode=0))
    result = health._runtime_telemetry_probes(manifest, local_evidence(registry, "run-fixture"), run_id="run-fixture")
    assert result["UAV-02"]["heartbeat_fresh"] and not result["UAV-02"]["telemetry_fresh"]


def test_read_only_route_and_explicit_run_identity(fleet, monkeypatch):
    code, body = routes.dispatch("GET", PATH)
    assert code == 200 and len(body["vehicles"]) == 3
    assert body["execution_authorized"] is False and body["flight_command_sent"] is False
    assert routes.dispatch("GET", PATH, query="run_id=spoofed")[0] == 400
    monkeypatch.setattr(routes, "RUNTIME_RUN_ID", None)
    assert routes.dispatch("GET", PATH) == (503, {"error": "runtime_run_id_required", "flight_command_sent": False})


def test_independent_samples_and_node_ownership(fleet):
    registry, clock = fleet
    clock[0] += 2
    registry.get_vehicle("UAV-02").session.dispatch_message(message("HEARTBEAT", 2, base_mode=0))
    rows = local_evidence(registry, "run-fixture", clock=lambda: clock[0])["vehicles"]
    assert rows[1]["heartbeat_fresh"] is True and rows[1]["telemetry_fresh"] is False
    assert rows[1]["heartbeat_timestamp"] == "1970-01-01T00:16:42Z"
    assert rows[1]["position_timestamp"] == "1970-01-01T00:16:40Z"
    registry.get_vehicle("UAV-03").session.dispatch_message(message("LOCAL_POSITION_NED", 3, x=0, y=0, z=0))
    clock[0] += 1
    rows = local_evidence(registry, "run-fixture", clock=lambda: clock[0])["vehicles"]
    assert rows[0]["heartbeat_fresh"] is False and rows[0]["telemetry_fresh"] is False
    assert rows[2]["heartbeat_fresh"] is False and rows[2]["telemetry_fresh"] is True


@pytest.mark.parametrize("condition", ["disconnected", "rx_stopped", "wrong_source", "missing_source", "nonfinite", "rx_error", "reboot"])
def test_bad_session_never_becomes_fresh(fleet, condition):
    registry, clock = fleet
    session = registry.get_vehicle("UAV-02").session
    if condition == "disconnected": session.connected = False
    elif condition == "rx_stopped": session._rx_thread = None
    elif condition == "rx_error": session.last_receive_error = "fixture"
    elif condition == "wrong_source": session.dispatch_message(message("HEARTBEAT", 3, base_mode=0))
    elif condition == "missing_source":
        session.dispatch_message(SimpleNamespace(get_type=lambda: "HEARTBEAT", base_mode=0))
    elif condition == "nonfinite":
        session.dispatch_message(message("LOCAL_POSITION_NED", 2, x=float("nan"), y=0, z=0))
    else:
        session.dispatch_message(message("LOCAL_POSITION_NED", 2, x=0, y=0, z=0, time_boot_ms=100))
        session.dispatch_message(message("LOCAL_POSITION_NED", 2, x=0, y=0, z=0, time_boot_ms=1))
    row = session.telemetry_health_evidence()
    assert not (row["heartbeat_fresh"] and row["telemetry_fresh"])
    diagnostic = row["session_diagnostics"]
    assert diagnostic["rx_alive"] is (condition != "rx_stopped")
    if condition == "wrong_source":
        assert diagnostic["identity_error"]["observed_system_id"] == 3
    elif condition == "rx_error":
        assert diagnostic["last_receive_error"] == "fixture"


def test_new_envelope_cannot_rejuvenate_old_samples(fleet):
    registry, clock = fleet
    first = local_evidence(registry, "run-fixture", clock=lambda: clock[0])
    clock[0] += 30
    last = local_evidence(registry, "run-fixture", clock=lambda: clock[0])
    assert first["source_timestamp"] != last["source_timestamp"]
    assert last["vehicles"][1]["position_timestamp"] == first["vehicles"][1]["position_timestamp"]
    assert not any(row["heartbeat_fresh"] or row["telemetry_fresh"] for row in last["vehicles"])


def test_parser_bad_data_is_not_a_foreign_vehicle_or_sample(fleet):
    registry, clock = fleet
    session = registry.get_vehicle("UAV-02").session
    before = session.telemetry_health_evidence()
    cursor = session.observation_cursor()
    session.dispatch_message(message("BAD_DATA", 0))
    after = session.telemetry_health_evidence()
    assert session.identity_error is None
    assert session.observation_cursor() == cursor
    assert after["heartbeat_timestamp"] == before["heartbeat_timestamp"]
    assert after["position_timestamp"] == before["position_timestamp"]
    assert after["heartbeat_fresh"] and after["telemetry_fresh"]
    assert after["session_diagnostics"]["parser_error_count"] == 1
    assert after["session_diagnostics"]["last_parser_error_timestamp"] is not None


def test_parser_noise_cannot_refresh_old_or_missing_samples(fleet):
    registry, clock = fleet
    clock[0] += 4
    session = registry.get_vehicle("UAV-02").session
    session.dispatch_message(message("BAD_DATA", 0))
    row = session.telemetry_health_evidence()
    assert not row["heartbeat_fresh"] and not row["telemetry_fresh"]
    assert row["position_timestamp"] == "1970-01-01T00:16:40Z"
    session._armed_states.clear()
    session._local_positions.clear()
    session.dispatch_message(message("BAD_DATA", 0))
    row = session.telemetry_health_evidence()
    assert row["heartbeat_timestamp"] is None and row["position_timestamp"] is None
    assert not row["heartbeat_fresh"] and not row["telemetry_fresh"]


@pytest.mark.parametrize("kind", ["HEARTBEAT", "LOCAL_POSITION_NED", "COMMAND_ACK", "UNKNOWN_291"])
def test_real_system_zero_messages_still_fail_closed(fleet, kind):
    registry, _ = fleet
    session = registry.get_vehicle("UAV-02").session
    session.dispatch_message(message(kind, 0))
    assert session.identity_error["observed_system_id"] == 0
    assert session.identity_error["message_type"] == kind
    prior_error = dict(session.identity_error)
    session.dispatch_message(message("BAD_DATA", 0))
    assert session.identity_error == prior_error  # Never clear a real fault with parser noise.
    row = session.telemetry_health_evidence()
    assert not row["heartbeat_fresh"] and not row["telemetry_fresh"]


def test_installed_pymavlink_bad_data_has_synthetic_zero_source(fleet):
    mavutil = pytest.importorskip("pymavlink.mavutil")
    parser_error = mavutil.mavlink.MAVLink_bad_data(b"fixture", "fixture-only")
    assert parser_error.get_type() == "BAD_DATA"
    assert parser_error.get_srcSystem() == 0 and parser_error.get_srcComponent() == 0
    registry, _ = fleet
    session = registry.get_vehicle("UAV-02").session
    session.dispatch_message(parser_error)
    assert session.identity_error is None
    unsupported = mavutil.mavlink.MAVLink_unknown(291, b"fixture-only")
    assert unsupported.get_msgId() == -2
    assert unsupported.get_srcSystem() == unsupported.get_srcComponent() == 0
    session.dispatch_message(unsupported)
    assert session.identity_error is None


def test_undecoded_wrapper_is_counted_not_identity_or_telemetry(fleet):
    registry, _ = fleet
    session = registry.get_vehicle("UAV-02").session
    before = session.telemetry_health_evidence()
    cursor = session.observation_cursor()
    observed = []
    session.subscribe(observed.append)
    session.dispatch_message(MAVLink_unknown())
    after = session.telemetry_health_evidence()
    assert session.identity_error is None
    assert session.observation_cursor() == cursor and observed == []
    assert after["position_timestamp"] == before["position_timestamp"]
    assert after["heartbeat_fresh"] and after["telemetry_fresh"]
    assert after["session_diagnostics"]["unsupported_message_count"] == 1
    assert after["session_diagnostics"]["last_unsupported_message_type"] == "UNKNOWN_291"


def test_undecoded_only_cannot_refresh_or_clear_fault(fleet):
    registry, clock = fleet
    session = registry.get_vehicle("UAV-02").session
    clock[0] += 4
    session.dispatch_message(MAVLink_unknown())
    row = session.telemetry_health_evidence()
    assert not row["heartbeat_fresh"] and not row["telemetry_fresh"]
    session.dispatch_message(message("HEARTBEAT", 3, base_mode=0))
    error = dict(session.identity_error)
    session.dispatch_message(MAVLink_unknown())
    assert session.identity_error == error


def test_unknown_wrapper_without_negative_sentinel_is_not_ignored(fleet):
    registry, _ = fleet
    candidate = MAVLink_unknown()
    candidate.get_msgId = lambda: 291
    session = registry.get_vehicle("UAV-02").session
    session.dispatch_message(candidate)
    assert session.identity_error["observed_system_id"] == 0
    assert session.identity_error["message_type"] == "UNKNOWN_291"


@pytest.mark.parametrize("change", ["run", "scene", "version", "ttl", "future", "old", "duplicate", "node", "endpoint", "source", "bool", "missing_time", "stale_hb", "stale_pos", "unavailable", "old_ui"])
def test_remote_bad_evidence_fails_closed(fleet, change):
    registry, clock = fleet
    view = packet(registry, clock)
    evidence, row = view["runtime_telemetry"], view["runtime_telemetry"]["vehicles"][0]
    if change == "run": evidence["run_id"] = "another-run"
    elif change == "scene": evidence["scene_id"] = "another-scene"
    elif change == "version": evidence["contract_version"] = "2.0"
    elif change == "ttl": evidence["valid_for_ms"] = 60000
    elif change == "future": evidence["source_timestamp"] = stamp(1001)
    elif change == "old": evidence["source_timestamp"] = stamp(990)
    elif change == "duplicate": evidence["vehicles"].append(deepcopy(row))
    elif change == "node": row["node_id"] = "UAV-01"
    elif change == "endpoint": row["endpoint"] = "udpin:127.0.0.1:14540"
    elif change == "source": row["source"] = "fake"
    elif change == "bool": row["heartbeat_fresh"] = "true"
    elif change == "missing_time": row["position_timestamp"] = None
    elif change == "stale_hb": row["heartbeat_timestamp"] = stamp(997)
    elif change == "stale_pos": row["position_timestamp"] = stamp(998)
    elif change == "unavailable": view["fresh"] = False
    else: view["runtime_telemetry"] = {"version": "1.0", "nodes": []}
    result = remote(view, clock)
    assert not (result["heartbeat_fresh"] and result["telemetry_fresh"])


def test_gateway_monotonic_age_and_read_only_three_node_merge(fleet, monkeypatch):
    registry, clock = fleet
    view = packet(registry, clock)
    assert remote(view, clock)["telemetry_fresh"] is True
    view["age_ms"] = 1600  # Wall clock may not have moved, but transport/cache age has.
    assert remote(view, clock)["telemetry_fresh"] is False
    view["age_ms"] = 0
    registry.unregister_vehicle("UAV-02")
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", SimpleNamespace(cached_view=lambda: deepcopy(view)))
    body = routes.dispatch("GET", PATH)[1]
    assert [row["node_id"] for row in body["vehicles"]] == ["UAV-01", "UAV-02", "UAV-03"]
    assert body["vehicles"][1]["telemetry_fresh"] is True
    view["fresh"] = False
    assert routes.dispatch("GET", PATH)[1]["vehicles"][1]["telemetry_fresh"] is False
    assert len(registry.list_vehicles()) == 2


def test_view_extension_reaches_ground_cache_without_changing_ui_projections(fleet, monkeypatch):
    from test_platform_view import state, gateway
    registry, clock = fleet
    _, store = state([2], clock)
    evidence = packet(registry, clock)["runtime_telemetry"]
    service = SimpleNamespace(mode="sitl", node_id="UAV-02", run_id="run-fixture", clock=lambda: clock[0],
                              store=SimpleNamespace(store_id="store-fixture"),
                              observe=lambda: {"source": "px4_telemetry", "sample_timestamp": stamp(clock[0]), "stale": False,
                                               "local_position": {"x_m": 1, "y_m": 2, "z_down_m": -3}})
    projections = {"/api/telemetry/latest": store.telemetry_latest(), "/api/vehicles": {"vehicles": [{
        "node_id": "UAV-02", "system_id": 2, "component_id": 1, "endpoint": "udpin:127.0.0.1:14541"}]},
        "/api/snapshot": store.runtime_snapshot(), "/api/vehicle-snapshot": store.vehicle_snapshot(), PATH: evidence}
    result = produce_view(service, lambda method, path: (200, deepcopy(projections[path])))
    bridge, _ = gateway(result, clock)
    bridge.refresh_view()
    assert remote(bridge.cached_view(), clock)["telemetry_fresh"] is True
    assert bridge.cached_view()["projections"]["telemetry"] == result["projections"]["telemetry"]
    clock[0] += 4
    assert remote(bridge.cached_view(), clock)["telemetry_fresh"] is False


def test_exporter_atomic_file_preserves_source_age_and_previous_on_failure(fleet, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("runtime_telemetry_exporter", Path(__file__).resolve().parents[2] / "scripts/export_runtime_telemetry.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    payload = deepcopy(FIXTURE)
    client = SimpleNamespace(request=lambda method, path: (200, deepcopy(payload)))
    target = tmp_path / "evidence.json"
    result = exporter.export_once(client, target, scene_id="simple_recon_v0_1", run_id="run-fixture")
    assert json.loads(target.read_text()) == result == FIXTURE
    assert list(tmp_path.iterdir()) == [target]
    payload["run_id"] = "old-run"
    with pytest.raises(Exception, match="runtime_telemetry_binding_mismatch"):
        exporter.export_once(client, target, scene_id="simple_recon_v0_1", run_id="run-fixture")
    assert json.loads(target.read_text()) == FIXTURE


def test_exporter_cannot_accept_legacy_ui_projection(fleet, tmp_path):
    import runpy
    exporter = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/export_runtime_telemetry.py"))
    with pytest.raises(Exception, match="runtime_telemetry_binding_mismatch"):
        exporter["export_once"](SimpleNamespace(request=lambda *args: (200, {"version": "1.0", "nodes": []})),
                                tmp_path / "no.json", scene_id="simple_recon_v0_1", run_id="run-fixture")
    assert not (tmp_path / "no.json").exists()
