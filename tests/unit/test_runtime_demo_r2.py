"""Composition checks for R6/R7, with no PX4 transport or service startup."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from uav_runtime.http import routes, server
from uav_runtime.http.demo import DemoRehearsal
from uav_runtime.platform import gateway, ownership
from uav_runtime.platform.deployment import select_registry
from tests.unit.test_platform_view import gateway as make_gateway, packet, state


def test_platform_node_rehearsal_is_read_only_and_does_not_taint_cache(packet, monkeypatch, tmp_path):
    clock = [1000.0]
    registry, store = state([1, 3], clock)
    remote_row = packet["projections"]["vehicle_snapshot"]["vehicles"][0]
    remote_row.update(link_quality=89, link_quality_measured=89, link_quality_mode="LIVE")
    bridge, _ = make_gateway(packet, clock)
    bridge.refresh_view()
    cached = bridge.cached_view()
    original = deepcopy(cached)
    # Use the same cache object every time to exercise merge_projection's copy.
    monkeypatch.setattr(bridge, "cached_view", lambda: cached)
    monkeypatch.setattr(bridge, "relay", lambda *a, **k: pytest.fail("rehearsal relayed a platform request"))
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", bridge)
    monkeypatch.setattr(routes, "DEMO_REHEARSAL", None)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "r2.audit.jsonl"))
    monkeypatch.setenv("UAV_RUNTIME_DEMO_ENABLED", "1")
    monkeypatch.setattr(DemoRehearsal, "start", lambda self: None)
    demo = routes.configure_demo()
    assert demo is not None and demo.nodes() == ["UAV-01", "UAV-02", "UAV-03"]
    assert demo.measured("UAV-02") == 89
    status, payload = routes.dispatch("POST", "/api/demo/inject",
                                      body={"node_id": "UAV-02", "kind": "link_degraded", "value": 18})
    assert status == 200 and payload["flight_command_sent"] is False
    row = next(row for row in routes.vehicle_snapshot()["vehicles"] if row["id"] == "UAV-02")
    assert (row["link_quality"], row["link_quality_measured"], row["link_quality_mode"]) == (18, 89, "DEMO")
    assert cached == original
    assert {h.config.node_id for h in registry.list_vehicles()} == {"UAV-01", "UAV-03"}
    assert routes.dispatch("POST", "/api/demo/clear", body={"node_id": "UAV-02"})[0] == 200
    assert routes.vehicle_snapshot()["vehicles"][1]["link_quality"] == 89
    cached["fresh"] = False
    assert demo.measured("UAV-02") == 0
    assert routes.vehicle_snapshot()["vehicles"][1]["link_quality"] == 0
    assert cached["projections"]["vehicle_snapshot"]["vehicles"][0]["link_quality"] == 89


@pytest.mark.parametrize(("path", "client", "headers", "expected"), [
    ("/api/demo/inject", "192.0.2.1", {"Content-Type": "application/json"}, 403),
    ("/api/demo/clear", "127.0.0.1", {"Content-Type": "application/json", "Content-Length": "4097"}, 400),
    ("/api/simulation/evidence/", "127.0.0.1", {"Origin": "http://outside.invalid"}, 403),
    ("/api/coordinates/calibration/", "127.0.0.1", {"Content-Type": "text/plain"}, 415),
])
def test_merged_write_guards_return_before_body_or_dispatch(path, client, headers, expected):
    replies = []
    handler = SimpleNamespace(path=path, command="POST", headers=headers, client_address=(client, 0),
                              _read_json_body=lambda: pytest.fail("rejected write read its body"),
                              _send_json=lambda status, body: replies.append(status))
    server.RuntimeHttpBridgeHandler._handle_json_request(handler)
    assert replies == [expected]


@pytest.mark.parametrize("failure", [None, "gateway_start", "demo_close"])
def test_filtered_startup_and_reverse_cleanup(monkeypatch, tmp_path, failure):
    calls = []
    registry, store = state([1, 2, 3], [1000], telemetry=False)
    registry.scene = {"scene_id": registry.scene_id, "map_version": "scene-v1"}
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", None)
    monkeypatch.setattr(routes, "RUNTIME_RUN_ID", None)
    monkeypatch.setenv("UAV_RUNTIME_TELEMETRY_ENABLED", "1")
    token = tmp_path / "fixture.token"
    token.write_text("x" * 40)

    def step(name):
        calls.append(name)
        if failure == name:
            raise RuntimeError(name)

    def start_registry(self):
        assert {h.config.node_id for h in self.list_vehicles()} == {"UAV-01", "UAV-03"}
        assert self is routes.VEHICLE_REGISTRY and self is routes.RUNTIME_STATE_STORE.vehicle_registry
        assert self.scene == registry.scene
        step("registry_start")

    def lease(endpoint):
        port = endpoint.rsplit(":", 1)[1]
        step("lease_" + port)
        return SimpleNamespace(close=lambda: step("release_" + port))

    monkeypatch.setattr(type(registry), "start_all", start_registry)
    monkeypatch.setattr(type(registry), "stop_all", lambda self: step("registry_stop"))
    monkeypatch.setattr(ownership, "TransportLease", lease)
    monkeypatch.setattr(gateway, "PlatformGateway", lambda *a, **k: SimpleNamespace(
        start=lambda: step("gateway_start"), close=lambda: step("gateway_close")))
    monkeypatch.setattr(server, "configure_demo", lambda: (
        step("demo_start") or SimpleNamespace(close=lambda: step("demo_close"))))
    monkeypatch.setattr(server, "create_server", lambda: SimpleNamespace(
        serve_forever=lambda: step("serve"), server_close=lambda: step("server_close")))
    args = ["--exclude-node", "UAV-02", "--platform-url", "http://127.0.0.1:1",
            "--platform-token-file", str(token)]
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            server.main(args)
    else:
        assert server.main(args) == 0
    expected = ["lease_14540", "lease_14542", "registry_start", "gateway_start"]
    if failure != "gateway_start":
        expected += ["demo_start", "serve", "demo_close"]
    assert calls == expected + ["gateway_close", "registry_stop", "release_14542", "release_14540", "server_close"]


def test_simulated_marker_survives_projected_and_raw_replay(monkeypatch, tmp_path):
    audit = tmp_path / "r7.audit.jsonl"
    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit))
    monkeypatch.setattr(routes, "DEMO_REHEARSAL", None)
    monkeypatch.setenv("UAV_RUNTIME_DEMO_ENABLED", "1")
    monkeypatch.setattr(DemoRehearsal, "start", lambda self: None)
    routes.configure_demo()
    assert routes.dispatch("POST", "/api/demo/inject",
                           body={"node_id": "UAV-02", "kind": "link_degraded", "value": 18})[0] == 200
    assert routes.dispatch("POST", "/api/demo/clear", body={"node_id": "UAV-02"})[0] == 200
    decisions = routes.dispatch("GET", "/api/policy/decisions", query="n=5")[1]
    assert decisions and decisions[0]["mode"] == "DEMO" and decisions[0]["simulated"] is True
    recent = routes.dispatch("GET", "/api/actions/recent")[1][0]
    assert recent["simulated"] is True and recent["flight_command_sent"] is False
    replay = routes.dispatch("GET", "/api/replay")[1]
    assert {"demo_inject", "demo_clear"} <= {event["type"] for event in replay}
    assert all(event["simulated"] is True and event["execution_authorized"] is False for event in replay)
