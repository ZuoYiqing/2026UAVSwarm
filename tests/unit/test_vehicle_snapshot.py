from __future__ import annotations

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
        reg.register_vehicle(VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i))
    result = RuntimeStateStore(vehicle_registry=reg, clock=lambda: 1.0).vehicle_snapshot()
    assert [vehicle["id"] for vehicle in result["vehicles"]] == ["UAV-01", "UAV-02", "UAV-03"]
    assert all(vehicle["connected"] is False for vehicle in result["vehicles"])
    assert all(vehicle["vehicle_type"] == "unknown" for vehicle in result["vehicles"])
    assert all("pose" not in vehicle for vehicle in result["vehicles"])
    assert all(vehicle["telemetry"]["stale"] is True for vehicle in result["vehicles"])
