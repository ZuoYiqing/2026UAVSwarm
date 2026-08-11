from __future__ import annotations

from pathlib import Path
import json
import threading

import pytest

from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry, VehicleRegistryError


class FakeSession:
    def __init__(self, config: object) -> None:
        self.config = config
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FakeMessage:
    def __init__(self, kind: str, **values: object) -> None:
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self) -> str:
        return self.kind


def registry(clock=lambda: 10.0) -> VehicleRegistry:  # type: ignore[no-untyped-def]
    return VehicleRegistry(scene_id="scene", session_factory=FakeSession, clock=clock)


def configs() -> list[VehicleConfig]:
    return [VehicleConfig(node_id=f"UAV-0{i}", endpoint=f"udp:{i}", system_id=i) for i in range(1, 4)]


def test_three_nodes_have_independent_sessions_and_stop_isolated() -> None:
    reg = registry()
    handles = [reg.register_vehicle(config) for config in configs()]
    assert len({id(handle.session) for handle in handles}) == 3
    reg.stop_vehicle("UAV-02")
    assert handles[1].session.closed == 1
    assert handles[0].session.closed == handles[2].session.closed == 0


def test_duplicate_and_unknown_nodes_are_structured_rejections() -> None:
    reg = registry()
    reg.register_vehicle(configs()[0])
    with pytest.raises(VehicleRegistryError, match="duplicate_node_id"):
        reg.register_vehicle(configs()[0])
    with pytest.raises(VehicleRegistryError, match="unknown_node"):
        reg.get_vehicle("UAV-99")


def test_duplicate_system_id_is_rejected() -> None:
    reg = registry()
    reg.register_vehicle(VehicleConfig(node_id="UAV-01", endpoint="udp:1", system_id=1))
    with pytest.raises(VehicleRegistryError, match="duplicate_system_id"):
        reg.register_vehicle(VehicleConfig(node_id="UAV-02", endpoint="udp:2", system_id=1))


@pytest.mark.parametrize(("first", "second"), [
    (("udp:1", "udp:101"), ("udp:1", "udp:102")),
    (("udp:1", "udp:101"), ("udp:2", "udp:101")),
    (("udp:1", "udp:101"), ("udp:2", "udp:1")),
])
def test_receive_endpoint_ownership_is_cross_role_unique(first: tuple[str, str], second: tuple[str, str]) -> None:
    reg = registry()
    reg.register_vehicle(VehicleConfig(node_id="UAV-01", endpoint=first[0], telemetry_endpoint=first[1], system_id=1))
    with pytest.raises(VehicleRegistryError) as caught:
        reg.register_vehicle(VehicleConfig(node_id="UAV-02", endpoint=second[0], telemetry_endpoint=second[1], system_id=2))
    assert caught.value.code == "endpoint_role_conflict"
    assert {"endpoint", "conflicting_node_id", "requested_role", "existing_role"} <= caught.value.details.keys()


def test_same_node_command_and_telemetry_endpoint_conflict() -> None:
    with pytest.raises(VehicleRegistryError, match="endpoint_role_conflict"):
        registry().register_vehicle(VehicleConfig(node_id="UAV-01", endpoint="udp:1", telemetry_endpoint="udp:1", system_id=1))


def test_per_node_locks_are_independent() -> None:
    reg = registry()
    handles = [reg.register_vehicle(config) for config in configs()]
    assert len({id(h.command_lock) for h in handles}) == 3
    assert len({id(h.state_lock) for h in handles}) == 3
    handles[1].state_lock.acquire()
    try:
        assert handles[0].command_lock.acquire(blocking=False)
        handles[0].command_lock.release()
    finally:
        handles[1].state_lock.release()


def test_telemetry_is_node_isolated_and_ned_altitude_is_preserved() -> None:
    reg = registry()
    for config in configs()[:2]:
        reg.register_vehicle(config)
    snap = new_snapshot(endpoint="udp:1")
    snap.node_id, snap.system_id = "UAV-01", 1
    apply_mavlink_message(snap, FakeMessage("LOCAL_POSITION_NED", x=1, y=2, z=-2.5, vx=0, vy=0, vz=0))
    reg.update_telemetry("UAV-01", snap, received_at=10.0)
    assert reg.get_vehicle("UAV-01").telemetry.local_position.altitude_m == 2.5
    assert reg.get_vehicle("UAV-02").telemetry.local_position.altitude_m is None


def test_stale_node_remains_until_explicit_unregister() -> None:
    now = [10.0]
    reg = registry(clock=lambda: now[0])
    reg.stale_after_ms = 100
    handle = reg.register_vehicle(configs()[0])
    snap = new_snapshot(endpoint="udp:1", connected=True)
    snap.system_id = 1
    reg.update_telemetry("UAV-01", snap, received_at=10.0)
    now[0] = 11.0
    assert reg.refresh_state(handle).stale is True
    assert reg.has_vehicle("UAV-01") is True
    reg.unregister_vehicle("UAV-01")
    assert reg.has_vehicle("UAV-01") is False


def test_shipped_config_registers_three_identity_mappings_without_guessed_ports() -> None:
    reg = VehicleRegistry.from_json(Path("config/vehicles.sitl.json"), session_factory=FakeSession)
    assert [(h.config.node_id, h.config.system_id) for h in reg.list_vehicles()] == [
        ("UAV-01", 1), ("UAV-02", 2), ("UAV-03", 3)
    ]
    assert reg.get_vehicle("UAV-02").config.enabled is False
    assert reg.get_vehicle("UAV-02").config.metadata["initial_pose"]["y_m"] == 8


def test_registry_binds_collector_to_expected_mavlink_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeCollector:
        def __init__(self, store: object, **kwargs: object) -> None:
            captured.update(kwargs)
        def start(self) -> bool: return True
        def stop(self) -> None: pass
        def is_running(self) -> bool: return False

    monkeypatch.setattr("uav_runtime.adapters.px4_telemetry_collector.Px4TelemetryCollector", FakeCollector)
    reg = registry()
    reg.register_vehicle(VehicleConfig(
        node_id="UAV-02", endpoint="udp:2", telemetry_endpoint="udp:102",
        system_id=2, component_id=7,
    ))
    reg.start_vehicle("UAV-02")
    assert captured == {
        "node_id": "UAV-02", "endpoint": "udp:102",
        "expected_system_id": 2, "expected_component_id": 7,
    }


def test_concurrent_start_creates_only_one_running_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_start_entered = threading.Event()
    allow_first_start = threading.Event()
    instances: list[FakeCollector] = []
    starts: list[FakeCollector] = []

    class FakeCollector:
        def __init__(self, store: object, **kwargs: object) -> None:
            self.running = False
            instances.append(self)

        def start(self) -> bool:
            starts.append(self)
            if len(starts) == 1:
                first_start_entered.set()
                assert allow_first_start.wait(timeout=2)
            self.running = True
            return True

        def stop(self) -> None:
            self.running = False

        def is_running(self) -> bool:
            return self.running

    monkeypatch.setattr(
        "uav_runtime.adapters.px4_telemetry_collector.Px4TelemetryCollector",
        FakeCollector,
    )
    reg = registry()
    reg.register_vehicle(
        VehicleConfig(
            node_id="UAV-01",
            endpoint="udp:1",
            telemetry_endpoint="udp:101",
            system_id=1,
        )
    )

    first = threading.Thread(target=reg.start_vehicle, args=("UAV-01",))
    second = threading.Thread(target=reg.start_vehicle, args=("UAV-01",))
    first.start()
    assert first_start_entered.wait(timeout=2)
    second.start()
    assert second.is_alive()
    assert len(instances) == 1
    allow_first_start.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(instances) == 1
    assert len(starts) == 1
    assert reg.get_vehicle("UAV-01").collector is starts[0]
