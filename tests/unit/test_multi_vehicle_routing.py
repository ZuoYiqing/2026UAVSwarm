from __future__ import annotations

from typing import Any

import uav_runtime.http.routes as routes
from uav_runtime.http.schemas import BackendRequest, SmokeTakeoffRequest
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


def test_px4_adapter_exception_cleans_only_selected_node(monkeypatch: Any, tmp_path: Any) -> None:
    reg = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def explode(self: Any, **_: Any) -> dict[str, Any]:
        raise RuntimeError("private backend detail")

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", explode)
    status, result = routes.dispatch("POST", "/api/actions/land", body={
        "node_id": "UAV-02", "backend_enabled": True, "transport_endpoint": "udp:2",
    })
    assert status == 200
    assert result["accepted"] is False
    assert result["status"] == "failed"
    assert result["code"] == "adapter_execution_exception"
    assert reg.get_vehicle("UAV-02").runtime_state.active_action is None
    assert reg.get_vehicle("UAV-02").runtime_state.last_error == "adapter_execution_exception"
    assert reg.get_vehicle("UAV-01").runtime_state.last_error is None
    assert reg.get_vehicle("UAV-03").runtime_state.last_error is None
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert '"node_id": "UAV-02"' in audit
    assert '"code": "adapter_execution_exception"' in audit
    assert "private backend detail" not in audit


def test_http_rejects_backend_spoofing_and_invalid_parameters(monkeypatch: Any) -> None:
    install_registry(monkeypatch, default="UAV-01")
    cases = [
        ({"backend": "hardware"}, "unsupported_backend"),
        ({"backend": "mavlink"}, "unsupported_backend"),
        ({"backend": "fake"}, "unsupported_backend"),
        ({"backend_mode": "hardware"}, "unsupported_backend_mode"),
        ({"backend_mode": "physical"}, "unsupported_backend_mode"),
        ({"altitude_m": -1}, "invalid_parameter"),
        ({"altitude_m": float("nan")}, "invalid_parameter"),
        ({"altitude_m": float("inf")}, "invalid_parameter"),
        ({"altitude_m": 121}, "invalid_parameter"),
        ({"threshold_ratio": 0}, "invalid_parameter"),
        ({"threshold_ratio": 1.01}, "invalid_parameter"),
        ({"threshold_ratio": float("nan")}, "invalid_parameter"),
        ({"system_id": 0}, "invalid_parameter"),
        ({"system_id": 256}, "invalid_parameter"),
        ({"backend_enabled": "sometimes"}, "invalid_parameter"),
        ({"auto_land": "sometimes"}, "invalid_parameter"),
        ({"timeout_ms": 0}, "invalid_parameter"),
        ({"observe_timeout_ms": 120001}, "invalid_parameter"),
        ({"retry_count": 11}, "invalid_parameter"),
    ]
    for body, error in cases:
        status, result = routes.dispatch("POST", "/api/actions/smoke-takeoff", body=body)
        assert status == 400 and result["error"] == error


def test_http_valid_boundaries_and_backend_identity() -> None:
    low = SmokeTakeoffRequest.from_json({
        "backend": "px4_sitl", "backend_mode": "sitl", "altitude_m": 0.01,
        "threshold_ratio": 0.01, "connect_timeout_ms": 1000,
        "command_timeout_ms": 1000, "observe_timeout_ms": 1000,
        "timeout_ms": 1000, "retry_count": 0,
    })
    high = SmokeTakeoffRequest.from_json({
        "altitude_m": 120, "threshold_ratio": 1, "connect_timeout_ms": 60000,
        "command_timeout_ms": 60000, "observe_timeout_ms": 120000,
        "timeout_ms": 120000, "retry_count": 10,
    })
    assert (low.altitude_m, low.threshold_ratio) == (0.01, 0.01)
    assert (high.altitude_m, high.threshold_ratio) == (120.0, 1.0)
    assert BackendRequest.from_json({}).backend == "px4_sitl"
    assert BackendRequest.from_json({"system_id": 255}).system_id == 255
    assert SmokeTakeoffRequest.from_json({"auto_land": "false"}).auto_land is False
