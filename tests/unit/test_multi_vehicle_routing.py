from __future__ import annotations

from typing import Any

import uav_runtime.http.routes as routes
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


class FakeSession:
    def __init__(self, config: object) -> None:
        self.config = config
        self.calls: list[str] = []
    def close(self) -> None: pass


def install_registry(monkeypatch: Any, *, default: str | None = None) -> VehicleRegistry:
    reg = VehicleRegistry(default_node_id=default, session_factory=FakeSession)
    for i in range(1, 4):
        reg.register_vehicle(VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i))
        reg.mark_connected(f"UAV-0{i}")
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", reg)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", RuntimeStateStore(vehicle_registry=reg))
    return reg


def test_land_routes_only_to_explicit_node_session(monkeypatch: Any, tmp_path: Any) -> None:
    reg = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def fake_land(self: Any, **_: Any) -> dict[str, Any]:
        self.session.calls.append("land")
        return {"action": "land", "result": "pass", "backend_mode": "sitl"}

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", fake_land)
    status, result = routes.dispatch("POST", "/api/actions/land", body={
        "node_id": "UAV-03", "backend_enabled": True, "transport_endpoint": "udp:3",
    })
    assert status == 200 and result["resolved_node_id"] == "UAV-03"
    assert reg.get_vehicle("UAV-03").session.calls == ["land"]
    assert reg.get_vehicle("UAV-01").session.calls == reg.get_vehicle("UAV-02").session.calls == []
    assert result["policy_decision"]["node_id"] == "UAV-03"


def test_missing_node_requires_explicit_default(monkeypatch: Any) -> None:
    install_registry(monkeypatch)
    status, result = routes.dispatch("POST", "/api/backend/check", body={"backend_enabled": True})
    assert status == 400 and result["error"] == "ambiguous_node_request"


def test_unknown_node_and_endpoint_conflict_are_not_silently_rerouted(monkeypatch: Any) -> None:
    install_registry(monkeypatch, default="UAV-01")
    status, result = routes.dispatch("GET", "/api/telemetry/latest", query="node_id=UAV-99")
    assert status == 404 and result["error"] == "unknown_node"
    status, result = routes.dispatch("POST", "/api/backend/check", body={
        "node_id": "UAV-02", "transport_endpoint": "udp:3", "backend_enabled": True,
    })
    assert status == 409 and result["error"] == "node_endpoint_conflict"


def test_vehicles_dispatch_lists_all_registered_nodes(monkeypatch: Any) -> None:
    install_registry(monkeypatch)
    status, result = routes.dispatch("GET", "/api/vehicles")
    assert status == 200
    assert [row["node_id"] for row in result["vehicles"]] == ["UAV-01", "UAV-02", "UAV-03"]


def test_explicit_default_is_reported_in_action_response(monkeypatch: Any, tmp_path: Any) -> None:
    reg = install_registry(monkeypatch, default="UAV-01")
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def fake_land(self: Any, **_: Any) -> dict[str, Any]:
        self.session.calls.append("land")
        return {"action": "land", "result": "pass", "backend_mode": "sitl"}

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", fake_land)
    status, result = routes.dispatch("POST", "/api/actions/land", body={"backend_enabled": True})
    assert status == 200
    assert result["node_selection"] == "default"
    assert result["resolved_node_id"] == "UAV-01"
    assert reg.get_vehicle("UAV-01").session.calls == ["land"]


def test_smoke_takeoff_routes_only_to_uav02_and_records_node_events(monkeypatch: Any, tmp_path: Any) -> None:
    reg = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def fake_takeoff(self: Any, **_: Any) -> dict[str, Any]:
        self.session.calls.append("takeoff")
        return {"action": "takeoff", "result": "pass", "backend_mode": "sitl"}

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_smoke", fake_takeoff)
    status, result = routes.dispatch("POST", "/api/actions/smoke-takeoff", body={
        "node_id": "UAV-02", "backend_enabled": True, "transport_endpoint": "udp:2",
    })
    assert status == 200 and result["node_id"] == "UAV-02"
    assert reg.get_vehicle("UAV-02").session.calls == ["takeoff"]
    assert reg.get_vehicle("UAV-01").session.calls == reg.get_vehicle("UAV-03").session.calls == []
    assert reg.get_vehicle("UAV-02").runtime_state.active_action is None
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert all(event_type in audit for event_type in (
        "action_request", "policy_decision_event", "adapter_execution_started",
        "adapter_execution_result", "action_result",
    ))
    assert '"node_id": "UAV-02"' in audit
