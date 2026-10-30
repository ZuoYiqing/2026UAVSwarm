"""Projection-only fixtures: never open a MAVLink session, model or PX4 socket."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.http import routes
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.platform.contract import PlatformError, stamp
from uav_runtime.platform.gateway import PlatformGateway
from uav_runtime.platform.server import PlatformHttpServer
from uav_runtime.platform.service import PlatformService
from uav_runtime.platform.store import TaskStore
from uav_runtime.platform.transport import JsonClient
from uav_runtime.platform.view import VIEW_PATHS, produce_view
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "docs/fixtures/platform_view_v1.json").read_text())


class NoTransport:
    def __init__(self, _): pass


def state(numbers, clock, *, telemetry=True):
    registry = VehicleRegistry(scene_id="simple_recon_v0_1", session_factory=NoTransport, clock=lambda: clock[0])
    for number in numbers:
        config = VehicleConfig(node_id=f"UAV-0{number}", system_id=number, component_id=1,
                               endpoint=f"udpin:127.0.0.1:{14539 + number}",
                               metadata={"initial_pose": {"x_m": 0, "y_m": number * 8, "z_m": 0}})
        registry.register_vehicle(config)
        if telemetry:
            snap = new_snapshot(endpoint=config.endpoint, connected=True)
            snap.system_id, snap.component_id = number, 1
            message = SimpleNamespace(get_type=lambda: "LOCAL_POSITION_NED", x=1, y=2, z=-3, vx=0, vy=0, vz=0)
            apply_mavlink_message(snap, message)
            registry.update_telemetry(config.node_id, snap, received_at=clock[0])
    store = RuntimeStateStore(vehicle_registry=registry, clock=lambda: clock[0], monotonic=lambda: clock[0])
    return registry, store


@pytest.fixture
def packet(monkeypatch):
    clock = [1000.0]
    registry, store = state([2], clock)
    store.update_coordinate_calibration(FIXTURE["calibration_request"])
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", None)
    service = SimpleNamespace(mode="sitl", node_id="UAV-02", run_id="run-fixture", clock=lambda: clock[0],
                              store=SimpleNamespace(store_id="store-fixture"),
                              observe=lambda: {"source": "px4_telemetry", "sample_timestamp": stamp(clock[0]), "stale": False,
                                               "local_position": {"x_m": 1, "y_m": 2, "z_down_m": -3}})
    return produce_view(service, routes.dispatch)


def gateway(packet, clock=None, defaults=None):
    clock = clock or [1000.0]
    result = PlatformGateway("http://127.0.0.1:1", "t" * 40, monotonic=lambda: clock[0], clock=lambda: clock[0],
                             default_projections=defaults)
    result.client.request = lambda *a, **k: (200, deepcopy(packet))
    return result, clock


def assert_subset(expected, actual):
    if isinstance(expected, dict):
        for key, value in expected.items(): assert_subset(value, actual[key])
    elif isinstance(expected, list):
        assert len(expected) == len(actual)
        for left, right in zip(expected, actual): assert_subset(left, right)
    else:
        assert expected == actual


def test_producer_matches_versioned_fixture_and_single_transform(packet):
    assert_subset(FIXTURE["response_projection"], packet)
    assert packet["source_timestamp"] == stamp(1000)


def test_ground_feeds_include_remote_without_extra_receiver(packet, monkeypatch):
    clock = [1000.0]
    registry, store = state([1, 3], clock)
    bridge, _ = gateway(packet, clock)
    bridge.refresh_view()
    bridge.client.request = lambda *a, **k: (_ for _ in ()).throw(AssertionError("public GET must use cache only"))
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", bridge)
    assert [r["node_id"] for r in routes.telemetry_latest()["nodes"]] == ["UAV-01", "UAV-02", "UAV-03"]
    selected = routes.telemetry_latest("node_id=UAV-02")
    assert [r["node_id"] for r in selected["nodes"]] == ["UAV-02"]
    assert selected["stale_after_ms"] == 2000 and selected["backend"] == "px4_sitl"
    assert selected["endpoint"] == "udpin:127.0.0.1:14541" and selected["source"] == "vehicle_registry"
    assert [r["node_id"] for r in routes.telemetry_latest("node_id=UAV-01")["nodes"]] == ["UAV-01"]
    assert len(routes.vehicles()["vehicles"]) == 3
    snapshot = routes.runtime_snapshot()
    assert snapshot["fleet_summary"]["total_nodes"] == 3
    assert snapshot["simulation_status"]["total_registered_nodes"] == 3
    assert snapshot["simulation_status"]["status"] == "unknown"
    row = routes.vehicle_snapshot()["vehicles"][1]
    assert row["spatial"]["scene_pose"]["position_m"]["y"] == 10
    assert len(registry.list_vehicles()) == 2
    assert all(isinstance(h.session, NoTransport) for h in registry.list_vehicles())
    schema = Path("frontend/swarm-console/simulation-3d/public/contracts/vehicle-snapshot.schema.json")
    if schema.exists():
        pytest.importorskip("jsonschema").validate(routes.vehicle_snapshot(), json.loads(schema.read_text()))


def test_startup_fallback_retains_registered_stale_node(packet):
    _, store = state([2], [1000.0], telemetry=False)
    bridge, _ = gateway(packet, defaults={"vehicle_snapshot": store.vehicle_snapshot()})
    row = bridge.cached_view()["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert row["id"] == "UAV-02" and not row["connected"]
    assert row["pose_source"] == "scenario_initial"
    assert not row["spatial"]["public_position_usable"]


def test_link_failure_retains_pose_and_running_action_unknown(packet):
    packet["projections"]["runtime_snapshot"]["active_actions"] = [{"node_id": "UAV-02", "status": "executing"}]
    bridge, _ = gateway(packet)
    bridge.refresh_view()
    bridge.client.request = lambda *a, **k: (_ for _ in ()).throw(ConnectionError())
    with pytest.raises(ConnectionError): bridge.refresh_view()
    result = bridge.cached_view()
    row = result["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert not result["fresh"] and not row["connected"] and row["telemetry"]["stale"]
    assert row["spatial"]["scene_pose"]["position_m"]["y"] == 10
    assert not row["spatial"]["public_position_usable"]
    assert result["projections"]["runtime_snapshot"]["active_actions"][0]["status"] == "executing"


def test_repeated_old_view_cannot_refresh_source_or_telemetry_age(packet):
    bridge, clock = gateway(packet)
    bridge.refresh_view()
    clock[0] += 4
    bridge.refresh_view()
    view = bridge.cached_view()
    assert not view["fresh"] and view["age_ms"] == 4000
    assert view["projections"]["telemetry"]["nodes"][0]["age_ms"] == 4000


def test_telemetry_and_calibration_expiry_age_independently(packet):
    packet["projections"]["vehicle_snapshot"]["vehicles"][0]["spatial"]["calibration_valid_for_ms"] = 100
    bridge, clock = gateway(packet)
    bridge.refresh_view()
    clock[0] += 0.2
    view = bridge.cached_view()
    row = view["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert view["fresh"] and row["connected"]
    assert row["spatial"]["calibration_status"] == "stale" and not row["spatial"]["public_position_usable"]
    clock[0] += 2
    row = bridge.cached_view()["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert row["telemetry"]["stale"] and not row["connected"]


@pytest.mark.parametrize("mutation", ["node", "mode", "foreign_row", "sysid", "endpoint", "future", "ttl", "nan", "fake_source", "telemetry_sysid"])
def test_invalid_views_never_replace_cache(packet, mutation):
    bridge, _ = gateway(packet)
    bridge.refresh_view()
    if mutation == "node": packet["node_id"] = "UAV-01"
    if mutation == "mode": packet["execution_mode"] = "fake"
    if mutation == "foreign_row": packet["projections"]["telemetry"]["nodes"][0]["node_id"] = "UAV-03"
    if mutation == "sysid": packet["projections"]["vehicles"]["vehicles"][0]["system_id"] = 1
    if mutation == "endpoint": packet["projections"]["vehicles"]["vehicles"][0]["endpoint"] = "udpin:127.0.0.1:14540"
    if mutation == "future": packet["source_timestamp"] = stamp(1002)
    if mutation == "ttl": packet["valid_for_ms"] = 9999999
    if mutation == "nan": packet["projections"]["telemetry"]["nodes"][0]["age_ms"] = float("nan")
    if mutation == "fake_source": packet["projections"]["telemetry"]["nodes"][0]["source"] = "fake"
    if mutation == "telemetry_sysid": packet["projections"]["runtime_snapshot"]["nodes"][0]["system_id"] = 1
    with pytest.raises((PlatformError, ValueError)): bridge.refresh_view()
    assert bridge.cached_view()["projections"]["vehicles"]["vehicles"][0]["system_id"] == 2
    assert not bridge.cached_view()["fresh"]


def test_preflight_forwards_uav02_and_rechecks_local_peer_isolation(monkeypatch):
    upstream = {"contract_version": "1.0", "node_id": "UAV-02", "nodes": {"UAV-02": {}},
                "status": "ready", "reason_codes": [], "execution_authorized": False, "flight_command_sent": False}
    bridge = SimpleNamespace(read_preflight=lambda: (200, deepcopy(upstream)))
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", bridge)
    monkeypatch.setattr(routes, "check_peer_isolation", lambda _: ({"UAV-01": {}, "UAV-03": {}}, ["fresh_disarmed_evidence_unavailable:UAV-01"]))
    result = routes.preflight("node_id=UAV-02")
    assert result["status"] == "not_ready" and len(result["nodes"]) == 3
    assert result["flight_command_sent"] is False
    bridge.read_preflight = lambda: (_ for _ in ()).throw(ConnectionError())
    assert routes.preflight("node_id=UAV-02")["reason_codes"] == ["platform_link_unavailable"]


def test_authenticated_view_get_does_not_refresh_ground_lease(packet, tmp_path):
    clock = [1000.0]
    store = TaskStore(tmp_path / "view")
    service = PlatformService(store, mode="sitl", execute=lambda *a: {}, observe=lambda: {},
                              clock=lambda: clock[0], monotonic=lambda: clock[0], run_id="fixture-run")
    service.heartbeat()
    def dispatch(method, path, **kw):
        return 200, deepcopy(packet["projections"][next(k for k, v in VIEW_PATHS.items() if v == path)])
    server = PlatformHttpServer(("127.0.0.1", 0), service, "x" * 40, dispatch)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        clock[0] += 4
        url = f"http://127.0.0.1:{server.server_port}"
        assert JsonClient(url).request("GET", "/api/platform/view")[0] == 401
        code, view = JsonClient(url, "x" * 40).request("GET", "/api/platform/view")
        assert code == 200 and view["node_id"] == "UAV-02"
        assert service.link()["state"] == "lost"
        assert store.events()["checkpoint_seq"] == 0
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2); store.close()


def test_slow_view_polling_does_not_block_ground_heartbeats():
    bridge = PlatformGateway("http://127.0.0.1:1", "t" * 40)
    release, entered, two_beats = threading.Event(), threading.Event(), threading.Event()
    beats = []
    def send(*a, **k):
        beats.append(True)
        if len(beats) >= 2: two_beats.set()
        return 200, {}
    def slow_view():
        entered.set()
        release.wait(timeout=3)
    bridge.client.request, bridge.refresh_view = send, slow_view
    bridge.start()
    try:
        assert entered.wait(timeout=1)
        assert two_beats.wait(timeout=2)
    finally:
        release.set()
        bridge.close()
    assert not bridge.thread.is_alive() and not bridge.view_thread.is_alive()


def test_old_position_cannot_be_refreshed_by_new_heartbeat_projection(packet):
    service = SimpleNamespace(mode="sitl", node_id="UAV-02", run_id="run-fixture", clock=lambda: 1000,
                              store=SimpleNamespace(store_id="store-fixture"),
                              observe=lambda: {"source": "px4_telemetry", "sample_timestamp": stamp(996), "stale": True,
                                               "local_position": {"x_m": 1, "y_m": 2, "z_down_m": -3}})
    def dispatch(method, path):
        return 200, deepcopy(packet["projections"][next(k for k, v in VIEW_PATHS.items() if v == path)])
    result = produce_view(service, dispatch)
    row = result["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert result["source_timestamp"] == stamp(1000)
    assert row["spatial"]["sample_timestamp"] == stamp(996)
    assert not row["spatial"]["public_position_usable"] and row["telemetry"]["stale"]


def test_fake_service_never_promotes_fake_coordinates_to_sitl(packet):
    service = SimpleNamespace(mode="fake", node_id="UAV-02", run_id=None, clock=lambda: 1000,
                              store=SimpleNamespace(store_id="fake-store"))
    result = produce_view(service, lambda *a: (_ for _ in ()).throw(AssertionError("fake has no PX4 projection")))
    assert result["projections"] is None
    bridge, _ = gateway(result, defaults=packet["projections"])
    bridge.refresh_view()
    assert not bridge.cached_view()["fresh"]
    assert not bridge.cached_view()["projections"]["vehicle_snapshot"]["vehicles"][0]["spatial"]["public_position_usable"]


@pytest.mark.parametrize("changed", ["timestamp", "coordinates"])
def test_projection_never_attaches_new_sample_time_to_old_pose(packet, changed):
    first = {"source": "px4_telemetry", "sample_timestamp": stamp(1000), "stale": False,
             "local_position": {"x_m": 1, "y_m": 2, "z_down_m": -3}}
    last = deepcopy(first)
    if changed == "timestamp": last["sample_timestamp"] = stamp(1000.001)
    else: last["local_position"]["x_m"] = 100
    samples = iter([first, last])
    service = SimpleNamespace(mode="sitl", node_id="UAV-02", run_id="run-fixture", clock=lambda: 1000,
                              store=SimpleNamespace(store_id="store-fixture"), observe=lambda: next(samples))
    def dispatch(method, path):
        return 200, deepcopy(packet["projections"][next(k for k, v in VIEW_PATHS.items() if v == path)])
    result = produce_view(service, dispatch)
    row = result["projections"]["vehicle_snapshot"]["vehicles"][0]
    assert not row["spatial"]["public_position_usable"]
    assert row["spatial"]["sample_timestamp"] is None
    bridge, _ = gateway(result)
    bridge.refresh_view()
    assert bridge.cached_view()["projections"]["vehicle_snapshot"]["vehicles"][0]["spatial"]["sample_age_ms"] is None


def test_cross_scene_merge_does_not_publish_usable_public_position(packet, monkeypatch):
    registry, store = state([1, 3], [1000.0])
    bridge, _ = gateway(packet)
    bridge.refresh_view()
    registry.scene_id = "another-scene"
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", bridge)
    row = routes.vehicle_snapshot()["vehicles"][1]
    assert not row["spatial"]["public_position_usable"]
    assert row["spatial"]["calibration_status"] == "scene_mismatch"


@pytest.mark.parametrize("remote_model_status,expected", [("ready", "ready"), ("failed", "degraded")])
def test_simulation_health_cannot_ignore_platform_owned_model(packet, monkeypatch, remote_model_status, expected):
    clock = [1000.0]
    registry, store = state([1, 3], clock)
    store.update_simulation_evidence({"contract_version": "1.0", "scene_id": "simple_recon_v0_1",
                                     "map_version": "map-fixture-1", "source_timestamp": stamp(1000),
                                     "valid_for_ms": 3000, "clock_advancing": True, "world": {"status": "ready"},
                                     "models": [{"node_id": f"UAV-0{i}", "status": remote_model_status if i == 2 else "ready"}
                                                for i in (1, 2, 3)]})
    bridge, _ = gateway(packet, clock)
    bridge.refresh_view()
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", bridge)
    assert routes.simulation_status()["status"] == expected
    clock[0] += 4
    assert routes.simulation_status()["status"] == "unknown"
