"""Deterministic four-module acceptance without opening real PX4 endpoints.

This test exercises Registry -> HTTP snapshots/actions -> Audit/Replay. The two
browser consumers use the same payload fixtures in their Node test suites; the
real Gazebo/PX4 overlay remains opt-in in test_px4_multi_vehicle_runtime.py.
"""
from __future__ import annotations

from typing import Any

import pytest

import uav_runtime.http.routes as routes
from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


class _Message:
    def __init__(self, kind: str, **values: object) -> None:
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self) -> str:
        return self.kind


class _Session:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.target_system = config.target_system
        self.target_component = config.target_component
        self.calls: list[str] = []

    def close(self) -> None:
        pass


def _update_telemetry(
    registry: VehicleRegistry,
    node_id: str,
    *,
    altitude_m: float,
    armed: bool,
    received_at: float,
) -> None:
    handle = registry.get_vehicle(node_id)
    snapshot = new_snapshot(endpoint=handle.config.endpoint, connected=True)
    snapshot.node_id = node_id
    snapshot.system_id = handle.config.system_id
    snapshot.component_id = handle.config.component_id
    snapshot.armed = armed
    snapshot.flight_mode = "AUTO.TAKEOFF" if armed else "AUTO.LAND"
    apply_mavlink_message(
        snapshot,
        _Message(
            "LOCAL_POSITION_NED",
            x=float(handle.config.system_id),
            y=float(handle.config.system_id * 2),
            z=-altitude_m,
            vx=0.0,
            vy=0.0,
            vz=0.0,
        ),
    )
    registry.update_telemetry(node_id, snapshot, received_at=received_at)


def _request(registry: VehicleRegistry, node_id: str) -> dict[str, Any]:
    config = registry.get_vehicle(node_id).config
    return {
        "node_id": node_id,
        "backend": "px4_sitl",
        "backend_mode": "sitl",
        "backend_enabled": True,
        "transport_endpoint": config.endpoint,
        "system_id": config.system_id,
        "component_id": config.component_id,
    }


def test_registry_http_actions_telemetry_and_audit_replay_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    now = [100.0]
    registry = VehicleRegistry(
        scene_id="e2e-three-uav",
        session_factory=_Session,
        clock=lambda: now[0],
    )
    for system_id in range(1, 4):
        node_id = f"UAV-0{system_id}"
        registry.register_vehicle(
            VehicleConfig(
                node_id=node_id,
                endpoint=f"udp:{system_id}",
                telemetry_endpoint=f"udp:{system_id}",
                system_id=system_id,
                component_id=1,
                metadata={
                    "vehicle_type": "multirotor",
                    "initial_pose": {
                        "x_m": float(system_id),
                        "y_m": float(system_id * 2),
                        "z_m": 0.0,
                    },
                },
            )
        )
        _update_telemetry(
            registry,
            node_id,
            altitude_m=0.0,
            armed=False,
            received_at=now[0],
        )

    audit_path = tmp_path / "four-module.audit.jsonl"
    store = RuntimeStateStore(vehicle_registry=registry, clock=lambda: now[0])
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit_path))

    def fake_takeoff(backend: Any, **_: Any) -> dict[str, Any]:
        backend.session.calls.append("takeoff")
        return {
            "action": "takeoff",
            "result": "pass",
            "accepted": True,
            "status": "accepted",
            "max_altitude_m": 4.0,
            "threshold_reached": True,
        }

    def fake_land(backend: Any, **_: Any) -> dict[str, Any]:
        backend.session.calls.append("land")
        return {
            "action": "land",
            "result": "pass",
            "accepted": True,
            "status": "accepted",
            "land_ack": {"result": 0, "timeout": False},
        }

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_smoke", fake_takeoff)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", fake_land)

    status, vehicles = routes.dispatch("GET", "/api/vehicles")
    assert status == 200
    assert [
        (row["node_id"], row["system_id"], row["component_id"])
        for row in vehicles["vehicles"]
    ] == [("UAV-01", 1, 1), ("UAV-02", 2, 1), ("UAV-03", 3, 1)]

    for path in ("/api/snapshot", "/api/vehicle-snapshot"):
        status, payload = routes.dispatch("GET", path)
        assert status == 200
        identity_rows = payload["nodes"] if path.endswith("snapshot") and path == "/api/snapshot" else payload["vehicles"]
        identity_key = "node_id" if path == "/api/snapshot" else "id"
        assert {row[identity_key] for row in identity_rows} == {
            "UAV-01",
            "UAV-02",
            "UAV-03",
        }

    status, takeoff = routes.dispatch(
        "POST",
        "/api/actions/smoke-takeoff",
        body=_request(registry, "UAV-01")
        | {"altitude_m": 4.0, "auto_land": False},
    )
    assert status == 200
    assert takeoff["result"] == "pass"
    assert takeoff["resolved_node_id"] == "UAV-01"
    assert takeoff["action_id"].startswith("act_")
    assert registry.get_vehicle("UAV-01").session.calls == ["takeoff"]
    assert registry.get_vehicle("UAV-02").session.calls == []
    assert registry.get_vehicle("UAV-03").session.calls == []

    now[0] += 0.1
    _update_telemetry(
        registry,
        "UAV-01",
        altitude_m=4.0,
        armed=True,
        received_at=now[0],
    )
    _, telemetry = routes.dispatch("GET", "/api/telemetry/latest")
    _, airborne_snapshot = routes.dispatch("GET", "/api/vehicle-snapshot")
    airborne_node = next(node for node in telemetry["nodes"] if node["node_id"] == "UAV-01")
    airborne_vehicle = next(vehicle for vehicle in airborne_snapshot["vehicles"] if vehicle["id"] == "UAV-01")
    assert airborne_node["local_position"]["altitude_m"] == pytest.approx(4.0)
    assert airborne_node["armed"] is True
    assert airborne_vehicle["pose"]["position_m"]["z"] == pytest.approx(-4.0)
    assert airborne_vehicle["telemetry"]["armed"] is True

    for node_id in ("UAV-01", "UAV-02", "UAV-03"):
        before = {
            candidate: list(registry.get_vehicle(candidate).session.calls)
            for candidate in ("UAV-01", "UAV-02", "UAV-03")
        }
        status, landed = routes.dispatch(
            "POST", "/api/actions/land", body=_request(registry, node_id)
        )
        assert status == 200
        assert landed["result"] == "pass"
        assert landed["resolved_node_id"] == node_id
        assert landed["action_id"].startswith("act_")
        for candidate in ("UAV-01", "UAV-02", "UAV-03"):
            calls = registry.get_vehicle(candidate).session.calls
            expected = before[candidate] + (["land"] if candidate == node_id else [])
            assert calls == expected
        now[0] += 0.1
        _update_telemetry(
            registry,
            node_id,
            altitude_m=0.0,
            armed=False,
            received_at=now[0],
        )

    _, grounded = routes.dispatch("GET", "/api/telemetry/latest")
    assert all(
        node["armed"] is False
        and node["local_position"]["altitude_m"] == pytest.approx(0.0)
        for node in grounded["nodes"]
    )

    registry.mark_offline("UAV-02", reason="e2e_link_loss")
    _, simulation = routes.dispatch("GET", "/api/simulation/status")
    _, runtime_snapshot = routes.dispatch("GET", "/api/snapshot")
    assert simulation["connected_nodes"] == 2
    assert simulation["all_enabled_px4_connected"] is False
    assert runtime_snapshot["fleet_summary"]["online_nodes"] == 2

    status, replay = routes.dispatch("GET", "/api/replay", query="n=200")
    assert status == 200
    action_results = [row for row in replay if row.get("type") == "action_result"]
    assert action_results
    assert {row["node_id"] for row in action_results} == {
        "UAV-01",
        "UAV-02",
        "UAV-03",
    }
    for event in action_results:
        assert event["system_id"] in {1, 2, 3}
        assert str(event["action_id"]).startswith("act_")
        assert event["result"] == "pass"
