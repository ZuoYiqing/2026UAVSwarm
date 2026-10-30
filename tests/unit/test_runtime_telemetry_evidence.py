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


def test_new_envelope_cannot_rejuvenate_old_samples(fleet):
    registry, clock = fleet
    first = local_evidence(registry, "run-fixture", clock=lambda: clock[0])
    clock[0] += 30
    last = local_evidence(registry, "run-fixture", clock=lambda: clock[0])
    assert first["source_timestamp"] != last["source_timestamp"]
    assert last["vehicles"][1]["position_timestamp"] == first["vehicles"][1]["position_timestamp"]
    assert not any(row["heartbeat_fresh"] or row["telemetry_fresh"] for row in last["vehicles"])


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
