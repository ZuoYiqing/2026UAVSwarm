from __future__ import annotations

from pathlib import Path
import json
import threading

import pytest

from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry, VehicleRegistryError


class FakeSession:
    def __init__(self, config: object) -> None:
        self.config = config
        self.closed = 0
        self.connected = False
        self.target_system = config.target_system
        self.target_component = config.target_component
        self.connect_calls = 0
        self.rx_alive = False
        self.rx_start_calls = 0
        self.heartbeat_alive = False
        self.heartbeat_start_calls = 0
        self.heartbeat_stop_calls = 0
        self.heartbeat_thread_names: list[str | None] = []
        self.last_send_error: str | None = None

    def connect(self, *, timeout_s: float) -> object:
        del timeout_s
        self.connect_calls += 1
        self.connected = True
        return object()

    def status(self) -> str:
        return "connected" if self.connected else "not_connected"

    def start_receive_loop(self, *, thread_name: str | None = None) -> bool:
        del thread_name
        if self.rx_alive:
            return False
        self.rx_start_calls += 1
        self.rx_alive = True
        return True

    def receive_thread_alive(self) -> bool:
        return self.rx_alive

    def start_gcs_heartbeat(self, *, thread_name: str | None = None) -> bool:
        if self.heartbeat_alive:
            return False
        self.heartbeat_start_calls += 1
        self.heartbeat_thread_names.append(thread_name)
        self.heartbeat_alive = True
        return True

    def heartbeat_thread_alive(self) -> bool:
        return self.heartbeat_alive

    def stop_gcs_heartbeat(self) -> None:
        self.heartbeat_stop_calls += 1
        self.heartbeat_alive = False

    def request_local_position_stream(self, **_: object) -> dict[str, object]:
        return {"result": 0, "timeout": False}

    def request_landing_state_stream(self, **_: object) -> dict[str, object]:
        return {"result": 0, "timeout": False}

    def arm(self, **_: object) -> dict[str, object]:
        return {"result": 0, "timeout": False}

    def takeoff(self, **_: object) -> dict[str, object]:
        return {"result": 0, "timeout": False, "local_position_cursor": 0, "observation_cursor": 0}

    def observe_local_position_altitude(self, **_: object) -> dict[str, object]:
        return {"max_altitude_m": 2.0, "threshold_reached": True}

    def land(self, **_: object) -> dict[str, object]:
        return {"result": 0, "timeout": False, "observation_cursor": 0}

    def observe_landed_and_disarmed(self, **_: object) -> dict[str, object]:
        return {"status": "succeeded", "telemetry_state": "fresh", "landed_state": 1, "armed": False, "completion_reached": True}

    def close(self) -> None:
        self.closed += 1
        self.stop_gcs_heartbeat()
        self.rx_alive = False
        self.connected = False


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


def install_lifecycle_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    class LifecycleCollector:
        def __init__(self, store: object, **kwargs: object) -> None:
            del store
            self.session = kwargs["session"]
            self.node_id = str(kwargs["node_id"])
            self.running = False

        def start(self) -> bool:
            self.session.start_receive_loop(
                thread_name=f"mavlink-rx-{self.node_id}"
            )
            self.running = True
            return True

        def stop(self) -> None:
            self.running = False

        def is_running(self) -> bool:
            return self.running and self.session.receive_thread_alive()

    monkeypatch.setattr(
        "uav_runtime.adapters.px4_telemetry_collector.Px4TelemetryCollector",
        LifecycleCollector,
    )


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


@pytest.mark.parametrize("system_id", [0, 256, None, True, 1.0])
def test_concrete_vehicle_system_id_must_be_integer_1_through_255(system_id: object) -> None:
    with pytest.raises(VehicleRegistryError) as caught:
        registry().register_vehicle(VehicleConfig(node_id="UAV-01", endpoint="udp:1", system_id=system_id))  # type: ignore[arg-type]
    assert caught.value.code == "invalid_system_id"


@pytest.mark.parametrize("system_id", [1, 255])
def test_concrete_vehicle_system_id_boundaries_are_valid(system_id: int) -> None:
    handle = registry().register_vehicle(VehicleConfig(node_id="UAV-01", endpoint="udp:1", system_id=system_id))
    assert handle.session.config.target_system == system_id


@pytest.mark.parametrize("component_id", [0, 256, True, 1.0])
def test_explicit_component_id_must_be_integer_1_through_255(component_id: object) -> None:
    with pytest.raises(VehicleRegistryError) as caught:
        registry().register_vehicle(VehicleConfig(
            node_id="UAV-01", endpoint="udp:1", system_id=1, component_id=component_id,  # type: ignore[arg-type]
        ))
    assert caught.value.code == "invalid_component_id"


@pytest.mark.parametrize("component_id", [None, 1, 255])
def test_component_id_none_and_boundaries_preserve_mapping(component_id: int | None) -> None:
    handle = registry().register_vehicle(VehicleConfig(
        node_id="UAV-01", endpoint="udp:1", system_id=1, component_id=component_id,
    ))
    assert handle.session.config.target_component == component_id


@pytest.mark.parametrize(("first", "second"), [
    ("udp:1", "udp:1"),
    ("udp:101", "udp:101"),
])
def test_receive_endpoint_ownership_is_cross_node_unique(first: str, second: str) -> None:
    reg = registry()
    reg.register_vehicle(VehicleConfig(node_id="UAV-01", endpoint=first, telemetry_endpoint=first, system_id=1))
    with pytest.raises(VehicleRegistryError) as caught:
        reg.register_vehicle(VehicleConfig(node_id="UAV-02", endpoint=second, telemetry_endpoint=second, system_id=2))
    assert caught.value.code == "endpoint_role_conflict"
    assert {"endpoint", "conflicting_node_id", "requested_role", "existing_role"} <= caught.value.details.keys()


def test_same_node_command_and_telemetry_endpoint_share_one_session() -> None:
    handle = registry().register_vehicle(
        VehicleConfig(
            node_id="UAV-01", endpoint="udp:1", telemetry_endpoint="udp:1", system_id=1
        )
    )
    assert handle.config.endpoint == handle.config.telemetry_endpoint


def test_unverified_dual_endpoint_configuration_is_rejected() -> None:
    with pytest.raises(VehicleRegistryError, match="shared_transport_endpoint_mismatch"):
        registry().register_vehicle(
            VehicleConfig(
                node_id="UAV-01", endpoint="udp:1", telemetry_endpoint="udp:101", system_id=1
            )
        )


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
    assert [h.config.endpoint for h in reg.list_vehicles()] == [
        "udpin:127.0.0.1:14540",
        "udpin:127.0.0.1:14541",
        "udpin:127.0.0.1:14542",
    ]
    assert reg.get_vehicle("UAV-02").config.enabled is True
    assert reg.get_vehicle("UAV-02").config.metadata["initial_pose"]["y_m"] == 8


def test_registry_reads_authoritative_simulation_manifest_directly() -> None:
    reg = VehicleRegistry.from_json(
        Path("simulation/px4_gazebo/config/three_uav_sitl.json"),
        session_factory=FakeSession,
    )

    assert reg.default_node_id == "UAV-01"
    assert [handle.config.endpoint for handle in reg.list_vehicles()] == [
        "udpin:127.0.0.1:14540",
        "udpin:127.0.0.1:14541",
        "udpin:127.0.0.1:14542",
    ]
    assert all(
        handle.config.endpoint == handle.config.telemetry_endpoint
        for handle in reg.list_vehicles()
    )


def test_registry_rejects_invalid_authoritative_scene_before_registration(tmp_path: Path) -> None:
    root = tmp_path / "project"
    config_dir = root / "config"
    scene_dir = root / "scenarios" / "simple_recon_v0_1"
    config_dir.mkdir(parents=True)
    scene_dir.mkdir(parents=True)
    config = json.loads(Path("config/vehicles.sitl.json").read_text(encoding="utf-8"))
    scene = json.loads(Path("scenarios/simple_recon_v0_1/scene.json").read_text(encoding="utf-8"))
    scene["vehicles"][0]["initial_pose"]["x_m"] = float("nan")
    config_path = config_dir / "vehicles.sitl.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (scene_dir / "scene.json").write_text(json.dumps(scene), encoding="utf-8")

    with pytest.raises(VehicleRegistryError) as caught:
        VehicleRegistry.from_json(config_path, session_factory=FakeSession)
    assert caught.value.code == "authoritative_scene_invalid"
    assert "must be finite" in caught.value.details["reason"]


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
        node_id="UAV-02", endpoint="udp:2", telemetry_endpoint="udp:2",
        system_id=2, component_id=7,
    ))
    reg.start_vehicle("UAV-02")
    assert captured == {
        "node_id": "UAV-02", "endpoint": "udp:2",
        "session": reg.get_vehicle("UAV-02").session,
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
            del store
            self.running = False
            self.session = kwargs["session"]
            instances.append(self)

        def start(self) -> bool:
            starts.append(self)
            if len(starts) == 1:
                first_start_entered.set()
                assert allow_first_start.wait(timeout=2)
            self.session.start_receive_loop(thread_name="mavlink-rx-UAV-01")
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
            telemetry_endpoint="udp:1",
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


def test_stop_waits_only_for_selected_node_command_lock() -> None:
    reg = registry()
    first, second = [reg.register_vehicle(config) for config in configs()[:2]]
    second.command_lock.acquire()
    blocked = threading.Thread(target=reg.stop_vehicle, args=("UAV-02",))
    unrelated = threading.Thread(target=reg.stop_vehicle, args=("UAV-01",))
    try:
        blocked.start()
        unrelated.start()
        unrelated.join(timeout=1)
        assert not unrelated.is_alive()
        assert blocked.is_alive()
        assert first.session.closed == 1
        assert second.session.closed == 0
    finally:
        second.command_lock.release()
        blocked.join(timeout=1)
        unrelated.join(timeout=1)
    assert not blocked.is_alive()
    assert second.session.closed == 1


def test_vehicle_lifecycle_owns_heartbeat_across_takeoff_and_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_lifecycle_collector(monkeypatch)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))
    reg = registry()
    handle = reg.register_vehicle(configs()[1])

    reg.start_vehicle("UAV-02")

    assert handle.session.connected is True
    assert handle.session.receive_thread_alive() is True
    assert handle.session.heartbeat_thread_alive() is True
    assert handle.session.heartbeat_thread_names == ["px4-gcs-heartbeat-UAV-02"]

    backend = Px4SitlBackend(handle.config.to_mavlink_config(), handle.session)  # type: ignore[arg-type]
    takeoff = backend.execute_takeoff_smoke(altitude_m=2.0, auto_land=False)
    assert takeoff["result"] == "pass"
    assert handle.session.connected is True
    assert handle.session.receive_thread_alive() is True
    assert handle.session.heartbeat_thread_alive() is True
    assert handle.session.heartbeat_stop_calls == 0

    landed = backend.execute_land_action()
    assert landed["result"] == "pass"
    assert handle.session.connected is True
    assert handle.session.receive_thread_alive() is True
    assert handle.session.heartbeat_thread_alive() is True
    assert handle.session.heartbeat_stop_calls == 0

    reg.stop_vehicle("UAV-02")
    assert handle.session.heartbeat_thread_alive() is False
    assert handle.session.receive_thread_alive() is False
    assert handle.session.connected is False


def test_three_node_heartbeat_and_rx_stop_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_lifecycle_collector(monkeypatch)
    reg = registry()
    handles = [reg.register_vehicle(config) for config in configs()]
    reg.start_all()

    reg.stop_vehicle("UAV-02")

    assert [handle.session.heartbeat_thread_alive() for handle in handles] == [
        True,
        False,
        True,
    ]
    assert [handle.session.receive_thread_alive() for handle in handles] == [
        True,
        False,
        True,
    ]
    assert [handle.session.connected for handle in handles] == [True, False, True]
    reg.stop_all()


def test_repeated_start_vehicle_is_idempotent_for_all_transport_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_lifecycle_collector(monkeypatch)
    reg = registry()
    handle = reg.register_vehicle(configs()[1])

    reg.start_vehicle("UAV-02")
    collector = handle.collector
    reg.start_vehicle("UAV-02")

    assert handle.collector is collector
    assert handle.session.connect_calls == 1
    assert handle.session.rx_start_calls == 1
    assert handle.session.heartbeat_start_calls == 1
    reg.stop_vehicle("UAV-02")


def test_heartbeat_start_failure_fails_closed_and_cleans_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_lifecycle_collector(monkeypatch)

    class FailingHeartbeatSession(FakeSession):
        def start_gcs_heartbeat(self, *, thread_name: str | None = None) -> bool:
            del thread_name
            raise OSError("heartbeat tx failed")

    reg = VehicleRegistry(
        scene_id="scene",
        session_factory=FailingHeartbeatSession,
        clock=lambda: 10.0,
    )
    handle = reg.register_vehicle(configs()[1])

    reg.start_vehicle("UAV-02")

    state = handle.runtime_state
    assert handle.collector is None
    assert handle.session.closed == 1
    assert handle.session.connected is False
    assert handle.session.receive_thread_alive() is False
    assert handle.session.heartbeat_thread_alive() is False
    assert state.connected is False
    assert state.connection_status == "offline"
    assert state.last_error == (
        "vehicle_start_failed:OSError:heartbeat tx failed"
    )


def test_dead_persistent_heartbeat_is_not_reported_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_lifecycle_collector(monkeypatch)
    reg = registry()
    handle = reg.register_vehicle(configs()[1])
    reg.start_vehicle("UAV-02")
    handle.session.heartbeat_alive = False
    handle.session.connected = False
    handle.session.last_send_error = "OSError: heartbeat tx failed"

    state = reg.refresh_state(handle)

    assert state.connected is False
    assert state.stale is True
    assert state.connection_status == "offline"
    assert state.last_error == (
        "gcs_heartbeat_send_failed:OSError: heartbeat tx failed"
    )


def test_action_admission_is_per_node_and_reports_busy() -> None:
    reg = registry()
    for config in configs()[:2]:
        reg.register_vehicle(config)

    reg.admit_action("UAV-01", "takeoff", "act-1")
    with pytest.raises(VehicleRegistryError) as caught:
        reg.admit_action("UAV-01", "takeoff", "act-2")
    other = reg.admit_action("UAV-02", "takeoff", "act-3")

    assert caught.value.code == "node_busy"
    assert caught.value.status == 409
    assert caught.value.details == {"active_action": "takeoff", "active_action_id": "act-1"}
    assert other["preempted_action_id"] is None


def test_land_preempts_non_land_and_old_release_cannot_clear_land() -> None:
    reg = registry()
    handle = reg.register_vehicle(configs()[0])
    takeoff = reg.admit_action("UAV-01", "takeoff", "act-takeoff")

    landing = reg.admit_action("UAV-01", "land", "act-land")

    assert takeoff["cancel_event"].is_set() is True
    assert landing["preempted_action"] == "takeoff"
    assert landing["preempted_action_id"] == "act-takeoff"
    assert reg.release_action("UAV-01", "act-takeoff") is False
    assert handle.runtime_state.active_action == "land"
    assert handle.runtime_state.active_action_id == "act-land"
    assert reg.release_action("UAV-01", "act-land") is True
    assert handle.runtime_state.active_action is None
