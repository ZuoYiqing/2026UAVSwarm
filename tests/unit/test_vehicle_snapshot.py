from __future__ import annotations

import json
from pathlib import Path

import pytest

from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


class FakeSession:
    def __init__(self, _: object) -> None: pass
    def close(self) -> None: pass


class Msg:
    def __init__(self, kind: str, **values: object) -> None:
        self.kind = kind; self.__dict__.update(values)
    def get_type(self) -> str: return self.kind


def test_three_vehicle_snapshot_and_removed_semantics() -> None:
    reg = VehicleRegistry(scene_id="simple_recon_v0_1", session_factory=FakeSession, clock=lambda: 1.0)
    for i in range(1, 4):
        cfg = VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i)
        reg.register_vehicle(cfg)
        snap = new_snapshot(endpoint=cfg.endpoint, connected=True); snap.system_id = i
        apply_mavlink_message(snap, Msg("LOCAL_POSITION_NED", x=i, y=0, z=-i, vx=0, vy=0, vz=0))
        reg.update_telemetry(cfg.node_id, snap, received_at=1.0)
    store = RuntimeStateStore(vehicle_registry=reg, clock=lambda: 1.0)
    result = store.vehicle_snapshot()
    assert result["version"] == "1.0" and result["full_state"] is True
    assert result["scene_id"] == "simple_recon_v0_1"
    assert result["source"]["kind"] == "simulation"
    assert [v["id"] for v in result["vehicles"]] == ["UAV-01", "UAV-02", "UAV-03"]
    assert all(v["pose"]["frame"] == "NED" for v in result["vehicles"])
    reg.mark_offline("UAV-02", reason="heartbeat_timeout")
    assert any(v["id"] == "UAV-02" for v in store.vehicle_snapshot()["vehicles"])
    reg.unregister_vehicle("UAV-02")
    assert all(v["id"] != "UAV-02" for v in store.vehicle_snapshot()["vehicles"])


def test_node_specific_telemetry_never_returns_another_node() -> None:
    reg = VehicleRegistry(session_factory=FakeSession, clock=lambda: 1.0)
    for i in (1, 2):
        cfg = VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i)
        reg.register_vehicle(cfg)
        snap = new_snapshot(endpoint=cfg.endpoint, connected=True); snap.system_id = i
        reg.update_telemetry(cfg.node_id, snap, received_at=1.0)
    response = RuntimeStateStore(vehicle_registry=reg, clock=lambda: 1.0).telemetry_latest("UAV-02")
    assert [node["node_id"] for node in response["nodes"]] == ["UAV-02"]


def test_full_snapshot_keeps_registered_nodes_without_telemetry() -> None:
    reg = VehicleRegistry(scene_id="simple_recon_v0_1", session_factory=FakeSession, clock=lambda: 1.0)
    for i in range(1, 4):
        reg.register_vehicle(VehicleConfig(
            node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i,
            metadata={"initial_pose": {"x_m": i, "y_m": 0, "z_m": 0, "yaw_deg": 0}},
        ))
    result = RuntimeStateStore(vehicle_registry=reg, clock=lambda: 1.0).vehicle_snapshot()
    assert [vehicle["id"] for vehicle in result["vehicles"]] == ["UAV-01", "UAV-02", "UAV-03"]
    assert all(vehicle["connected"] is False for vehicle in result["vehicles"])
    assert all(vehicle["vehicle_type"] == "unknown" for vehicle in result["vehicles"])
    assert all(vehicle["pose"]["frame"] == "NED" for vehicle in result["vehicles"])
    assert all(vehicle["pose_source"] == "scenario_initial" for vehicle in result["vehicles"])
    assert all(vehicle["telemetry"]["stale"] is True for vehicle in result["vehicles"])


def test_snapshot_never_fabricates_missing_authoritative_pose() -> None:
    reg = VehicleRegistry(session_factory=FakeSession)
    reg.register_vehicle(VehicleConfig(node_id="UAV-01", endpoint="udp:1", system_id=1))
    with pytest.raises(ValueError, match="authoritative_initial_pose_required"):
        RuntimeStateStore(vehicle_registry=reg).vehicle_snapshot()


@pytest.mark.parametrize("connected_count", [0, 1, 2, 3])
def test_simulation_status_is_fleet_aggregation(connected_count: int) -> None:
    reg = VehicleRegistry(session_factory=FakeSession)
    for i in range(1, 4):
        reg.register_vehicle(VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i))
    for i in range(1, connected_count + 1):
        snap = new_snapshot(endpoint=f"udp:{i}", connected=True); snap.system_id = i
        reg.update_telemetry(f"UAV-0{i}", snap)
    status = RuntimeStateStore(vehicle_registry=reg).simulation_status()
    assert status["connected_nodes"] == connected_count
    assert status["any_px4_connected"] is (connected_count > 0)
    assert status["all_enabled_px4_connected"] is (connected_count == 3)
    assert status["status"] == status["gazebo_probe_status"] == "unknown"


def test_snapshot_validates_against_authoritative_frontend_schema() -> None:
    schema_path = Path("frontend/swarm-console/simulation-3d/public/contracts/vehicle-snapshot.schema.json")
    if not schema_path.is_file():
        pytest.skip("BLOCKED_AUTHORITATIVE_SCHEMA_NOT_PRESENT_BRANCH_BASE_DRIFT")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    reg = VehicleRegistry(scene_id="simple_recon_v0_1", session_factory=FakeSession, clock=lambda: 1.0)
    for i in range(1, 4):
        cfg = VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i,
                            metadata={"initial_pose": {"x_m": i, "y_m": 0, "z_m": 0, "yaw_deg": 0}})
        reg.register_vehicle(cfg)
        snap = new_snapshot(endpoint=cfg.endpoint, connected=True); snap.system_id = i
        apply_mavlink_message(snap, Msg("LOCAL_POSITION_NED", x=i, y=0, z=-i, vx=0, vy=0, vz=0.5))
        reg.update_telemetry(cfg.node_id, snap, received_at=1.0)
    store = RuntimeStateStore(vehicle_registry=reg, clock=lambda: 1.0)
    live = store.vehicle_snapshot()
    jsonschema.validate(live, schema)
    assert live["source"]["kind"] == "simulation"
    assert all(vehicle["pose"]["frame"] == "NED" for vehicle in live["vehicles"])
    reg.mark_offline("UAV-02", reason="heartbeat_timeout")
    stale = store.vehicle_snapshot()
    jsonschema.validate(stale, schema)
    assert next(v for v in stale["vehicles"] if v["id"] == "UAV-02")["pose_source"] == "last_known_telemetry"
    reg.unregister_vehicle("UAV-02")
    removed = store.vehicle_snapshot()
    jsonschema.validate(removed, schema)
    assert "UAV-02" not in {v["id"] for v in removed["vehicles"]}

    initial_only = VehicleRegistry(scene_id="simple_recon_v0_1", session_factory=FakeSession)
    for i in range(1, 4):
        initial_only.register_vehicle(VehicleConfig(
            node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i,
            metadata={"initial_pose": {"x_m": i, "y_m": 0, "z_m": 0, "yaw_deg": 0}},
        ))
    never_observed = RuntimeStateStore(vehicle_registry=initial_only).vehicle_snapshot()
    jsonschema.validate(never_observed, schema)
    assert all(vehicle["pose_source"] == "scenario_initial" for vehicle in never_observed["vehicles"])
