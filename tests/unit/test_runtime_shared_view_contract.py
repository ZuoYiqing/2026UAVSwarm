from __future__ import annotations

import json
from pathlib import Path

import pytest

import uav_runtime.http.routes as routes
from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


class FakeSession:
    def __init__(self, config: object) -> None:
        self.config = config

    def close(self) -> None:
        pass


class FakeMessage:
    def __init__(self, kind: str, **values: object) -> None:
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self) -> str:
        return self.kind


def build_store(now: list[float], *, nodes: int = 1) -> tuple[VehicleRegistry, RuntimeStateStore]:
    registry = VehicleRegistry(
        scene_id="simple_recon_v0_1",
        session_factory=FakeSession,
        clock=lambda: now[0],
    )
    for index in range(1, nodes + 1):
        registry.register_vehicle(VehicleConfig(
            node_id=f"UAV-0{index}",
            endpoint=f"udp:{index}",
            telemetry_endpoint=f"udp:{index}",
            system_id=index,
            component_id=1,
            metadata={"initial_pose": {"x_m": 0.0, "y_m": float((index - 1) * 8), "z_m": 0.0}},
        ))
    return registry, RuntimeStateStore(vehicle_registry=registry, monotonic=lambda: now[0], clock=lambda: now[0])


def update_local(registry: VehicleRegistry, node_id: str, *, x: float, y: float, z: float, now: float) -> None:
    index = int(node_id[-1])
    snapshot = new_snapshot(endpoint=f"udp:{index}", connected=True)
    snapshot.node_id = node_id
    snapshot.system_id = index
    snapshot.component_id = 1
    apply_mavlink_message(snapshot, FakeMessage("LOCAL_POSITION_NED", x=x, y=y, z=z, vx=0, vy=0, vz=0))
    registry.update_telemetry(node_id, snapshot, received_at=now)


def calibration(*, node_id: str = "UAV-01", east: float = 8.0, valid_for_ms: int = 5000) -> dict:
    return {
        "contract_version": "1.0",
        "scene_id": "simple_recon_v0_1",
        "map_version": "map-v1",
        "node_id": node_id,
        "status": "calibrated",
        "calibration_version": "cal-v1",
        "local_origin_id": "ekf-origin-v1",
        "origin_continuity": "verified",
        "axis_alignment": "ned_aligned",
        "scene_origin": {"kind": "gazebo_world_ned", "north_m": 0.0, "east_m": 0.0, "down_m": 0.0},
        "altitude_reference": "scene_origin_z_down",
        "translation_scene_ned_m": {"north": 10.0, "east": east, "down": -1.0},
        "source_timestamp": "2026-09-06T10:00:00Z",
        "valid_for_ms": valid_for_ms,
    }


def test_uncalibrated_local_pose_is_diagnostic_not_public_scene_position() -> None:
    now = [10.0]
    registry, store = build_store(now)
    update_local(registry, "UAV-01", x=1.0, y=2.0, z=-3.0, now=10.0)

    vehicle = store.vehicle_snapshot()["vehicles"][0]

    assert vehicle["spatial"]["calibration_status"] == "unavailable"
    assert vehicle["spatial"]["public_position_usable"] is False
    assert "scene_pose" not in vehicle["spatial"]
    assert vehicle["spatial"]["raw_vehicle_local_pose"]["frame"] == "vehicle_local_ned"
    assert vehicle["pose_source"] == "px4_telemetry"


def test_runtime_applies_explicit_translation_once_without_yaw_rotation() -> None:
    now = [10.0]
    registry, store = build_store(now)
    update_local(registry, "UAV-01", x=1.0, y=2.0, z=-3.0, now=10.0)
    store.update_coordinate_calibration(calibration())

    vehicle = store.vehicle_snapshot()["vehicles"][0]
    position = vehicle["spatial"]["scene_pose"]["position_m"]

    assert position == {"x": 11.0, "y": 10.0, "z": -4.0}
    assert vehicle["pose"]["position_m"] == position
    assert vehicle["spatial"]["public_position_usable"] is True
    assert vehicle["spatial"]["local_origin_id"] == "ekf-origin-v1"
    assert vehicle["spatial"]["altitude_reference"] == "scene_origin_z_down"
    assert vehicle["spatial"]["sample_timestamp"]
    assert vehicle["spatial"]["calibration_source_timestamp"] == "2026-09-06T10:00:00Z"
    assert vehicle["spatial"]["calibration_age_ms"] == 0
    assert vehicle["spatial"]["calibration_valid_for_ms"] == 5000


def test_calibration_expires_and_origin_continuity_must_be_verified() -> None:
    now = [10.0]
    registry, store = build_store(now)
    update_local(registry, "UAV-01", x=1.0, y=2.0, z=-3.0, now=10.0)
    unverified = calibration(valid_for_ms=100)
    unverified["origin_continuity"] = "unknown"
    accepted = store.update_coordinate_calibration(unverified)
    assert accepted["status"] == "unavailable"
    assert store.vehicle_snapshot()["vehicles"][0]["spatial"]["public_position_usable"] is False

    store.update_coordinate_calibration(calibration(valid_for_ms=100))
    now[0] = 10.2
    vehicle = store.vehicle_snapshot()["vehicles"][0]
    assert vehicle["spatial"]["calibration_status"] == "stale"
    assert vehicle["spatial"]["public_position_usable"] is False


def test_simulation_status_requires_fresh_integrated_evidence_not_heartbeat() -> None:
    now = [10.0]
    registry, store = build_store(now)
    update_local(registry, "UAV-01", x=0.0, y=0.0, z=0.0, now=10.0)

    without_evidence = store.simulation_status()
    assert without_evidence["any_px4_connected"] is True
    assert without_evidence["status"] == "unknown"

    evidence = {
        "contract_version": "1.0",
        "scene_id": "simple_recon_v0_1",
        "map_version": "map-v1",
        "source_timestamp": "2026-09-06T10:00:00Z",
        "valid_for_ms": 100,
        "clock_advancing": True,
        "world": {"name": "simple_recon_v0_1", "status": "ready"},
        "models": [{"node_id": "UAV-01", "name": "x500_0", "status": "ready"}],
    }
    store.update_simulation_evidence(evidence)
    assert store.simulation_status()["status"] == "ready"
    now[0] = 10.2
    expired = store.simulation_status()
    assert expired["status"] == "unknown"
    assert expired["reason"] == "simulation_evidence_stale"
    assert expired["evidence_fresh"] is False
    assert expired["evidence_valid_for_ms"] == 100


def test_simulation_ready_requires_model_evidence_for_each_enabled_node() -> None:
    now = [10.0]
    _registry, store = build_store(now, nodes=3)
    store.update_simulation_evidence({
        "contract_version": "1.0",
        "scene_id": "simple_recon_v0_1",
        "map_version": "map-v1",
        "source_timestamp": "2026-09-06T10:00:00Z",
        "valid_for_ms": 1000,
        "clock_advancing": True,
        "world": {"name": "simple_recon_v0_1", "status": "ready"},
        "models": [
            {"node_id": "UAV-01", "name": "x500_0", "status": "ready"},
            {"node_id": "UAV-01", "name": "duplicate", "status": "ready"},
            {"node_id": "UAV-03", "name": "x500_2", "status": "ready"},
        ],
    })

    status = store.simulation_status()

    assert status["status"] == "degraded"
    assert status["reason"] == "simulation_evidence_incomplete"


def test_shipped_contract_fixture_is_accepted_by_runtime_producers() -> None:
    fixture = json.loads(
        Path("docs/fixtures/runtime_control_contract_v1.json").read_text(encoding="utf-8")
    )
    now = [10.0]
    registry, store = build_store(now, nodes=3)
    for index in range(1, 4):
        update_local(registry, f"UAV-0{index}", x=1.0, y=2.0, z=-3.0, now=10.0)

    calibration_result = store.update_coordinate_calibration(fixture["coordinate_calibration_request"])
    simulation_result = store.update_simulation_evidence(fixture["simulation_evidence_request"])

    assert calibration_result["status"] == "calibrated"
    assert simulation_result["contract_version"] == "1.0"
    simulation_status = store.simulation_status()
    simulation_example = fixture["simulation_status_response_example"]
    assert simulation_status["status"] == simulation_example["status"] == "ready"
    assert simulation_status["scene_id"] == simulation_example["scene_id"]
    assert simulation_status["map_version"] == simulation_example["map_version"]
    vehicle = next(item for item in store.vehicle_snapshot()["vehicles"] if item["id"] == "UAV-02")
    assert vehicle["spatial"]["public_position_usable"] is True
    assert (
        vehicle["spatial"]["scene_pose"]["position_m"]
        == fixture["vehicle_snapshot_spatial_example"]["spatial"]["scene_pose"]["position_m"]
    )
    assert fixture["waypoint_execution_proposal"]["implemented"] is False


def test_shared_contract_fixture_is_accepted_through_http_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = json.loads(
        Path("docs/fixtures/runtime_control_contract_v1.json").read_text(encoding="utf-8")
    )
    now = [10.0]
    registry, store = build_store(now, nodes=3)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)

    calibration_status, calibration_result = routes.dispatch(
        "POST",
        "/api/coordinates/calibration",
        body=fixture["coordinate_calibration_request"],
    )
    evidence_status, evidence_result = routes.dispatch(
        "POST",
        "/api/simulation/evidence",
        body=fixture["simulation_evidence_request"],
    )
    status_status, simulation_status = routes.dispatch("GET", "/api/simulation/status")

    assert calibration_status == evidence_status == status_status == 200
    assert calibration_result["accepted"] is True
    assert evidence_result["accepted"] is True
    assert simulation_status["status"] == "ready"


def test_shared_contract_http_routes_reject_scene_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    registry, store = build_store(now)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)

    invalid = calibration()
    invalid["scene_id"] = "wrong-scene"
    status, result = routes.dispatch(
        "POST",
        "/api/coordinates/calibration",
        body=invalid,
    )

    assert status == 400
    assert result["error"] == "invalid_coordinate_calibration"
