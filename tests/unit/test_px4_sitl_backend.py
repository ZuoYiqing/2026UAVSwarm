"""PX4 SITL backend placeholder tests (no real PX4/MAVLink dependency)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from uav_runtime.adapters.mavlink_backend import MavlinkBackend
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend


def test_px4_sitl_backend_conforms_to_mavlink_backend_interface() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    assert isinstance(backend, MavlinkBackend)


def test_px4_sitl_backend_returns_stable_placeholder_semantics(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    # Unit tests never probe a developer's live PX4 UDP listener.
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: False))

    raw = backend.execute_mapped_action(
        action="takeoff",
        mapping={"mavlink_action": "NAV_TAKEOFF"},
        args={"altitude_m": 10},
    )

    assert raw["accepted"] is False
    assert raw["code"] in {"dependency_missing", "backend_probe_failed"}
    assert raw["message"] == "px4_sitl_backend_placeholder"
    assert raw["detail"] in {"pymavlink_not_installed", "heartbeat_timeout", "connection_failed", "probe_exception"}
    assert raw["evidence_ref"].startswith("sitl://px4/")
    assert raw["execution_trace"]["backend_impl"] == "px4_sitl_backend"
    assert raw["execution_trace"]["integration_stage"] == "placeholder"


def test_px4_sitl_backend_not_configured_probe_is_stable() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=False)
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    probe = backend.connect_probe()

    assert probe["ok"] is False
    assert probe["code"] == "sitl_not_configured"
    assert probe["reason"] == "sitl_backend_disabled"


def test_px4_sitl_backend_dependency_missing_probe_is_stable(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: False))

    probe = backend.connect_probe()
    raw = backend.execute_mapped_action(
        action="takeoff",
        mapping={"mavlink_action": "NAV_TAKEOFF"},
        args={"altitude_m": 10},
    )

    assert probe["ok"] is False
    assert probe["code"] == "dependency_missing"
    assert probe["reason"] == "pymavlink_not_installed"
    assert raw["accepted"] is False
    assert raw["code"] == "dependency_missing"
    assert raw["detail"] == "pymavlink_not_installed"
    assert raw["execution_trace"]["probe_code"] == "dependency_missing"


def test_px4_sitl_backend_readiness_diagnostic_dependency_missing(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: False))

    diag = backend.readiness_diagnostic()

    assert diag["backend"] == "px4_sitl"
    assert diag["dependency"]["name"] == "pymavlink"
    assert diag["dependency"]["present"] is False
    assert diag["backend_enabled"] is True
    assert diag["backend_mode"] == "sitl"
    assert diag["transport_endpoint_configured"] is True
    assert diag["connect_timeout_ms"] == 3000
    assert diag["connect_probe"]["code"] == "dependency_missing"
    assert diag["connect_probe"]["reason"] == "pymavlink_not_installed"
    assert diag["readiness"] == "not_ready"


def test_px4_sitl_backend_readiness_diagnostic_endpoint_missing(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))

    diag = backend.readiness_diagnostic()

    assert diag["transport_endpoint"] == ""
    assert diag["transport_endpoint_configured"] is False
    assert diag["connect_probe"]["code"] == "backend_not_configured"
    assert diag["connect_probe"]["reason"] == "transport_endpoint_missing"
    assert diag["readiness"] == "not_ready"


def test_px4_sitl_backend_probe_maps_timeout_reason(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))
    monkeypatch.setattr(Px4SitlBackend, "_probe_via_pymavlink", lambda self: (False, "heartbeat_timeout"))

    probe = backend.connect_probe()
    diag = backend.readiness_diagnostic()

    assert probe["ok"] is False
    assert probe["code"] == "backend_probe_failed"
    assert probe["reason"] == "heartbeat_timeout"
    assert diag["readiness"] == "not_ready"


def test_px4_sitl_backend_probe_maps_exception_reason(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))
    monkeypatch.setattr(Px4SitlBackend, "_probe_via_pymavlink", lambda self: (False, "probe_exception"))

    probe = backend.connect_probe()
    diag = backend.readiness_diagnostic()

    assert probe["ok"] is False
    assert probe["code"] == "backend_probe_failed"
    assert probe["reason"] == "probe_exception"
    assert diag["readiness"] == "not_ready"


def test_px4_sitl_backend_probe_success_returns_backend_connected(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))
    monkeypatch.setattr(Px4SitlBackend, "_probe_via_pymavlink", lambda self: (True, "backend_connected"))

    probe = backend.connect_probe()
    diag = backend.readiness_diagnostic()

    assert probe["ok"] is True
    assert probe["code"] == "backend_connected"
    assert probe["status"] == "connected"
    assert diag["connect_probe"]["code"] == "backend_connected"
    assert diag["readiness"] == "ready"


def test_temporary_probe_validates_identity_and_always_closes(monkeypatch) -> None:
    class Heartbeat:
        def get_srcSystem(self) -> int: return 2
        def get_srcComponent(self) -> int: return 1

    class Connection:
        target_system = 2
        target_component = 1
        closed = False
        def wait_heartbeat(self, *, timeout: float): return Heartbeat()
        def close(self) -> None: self.closed = True

    connection = Connection()
    fake_mavutil = SimpleNamespace(
        mavlink_connection=lambda *args, **kwargs: connection
    )
    monkeypatch.setitem(
        sys.modules,
        "pymavlink",
        SimpleNamespace(mavutil=fake_mavutil),
    )
    cfg = MavlinkBackendConfig(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udpin:127.0.0.1:14540",
        target_system=1,
        target_component=1,
    )
    backend = Px4SitlBackend(cfg, MavlinkBackendSession.from_config(cfg))

    ok, reason, details = backend._probe_via_pymavlink()

    assert ok is False
    assert reason == "target_system_mismatch"
    assert details["expected_system_id"] == 1
    assert details["observed_system_id"] == 2
    assert connection.closed is True

class _FakePx4ActionSession:
    def __init__(self) -> None:
        self.stopped = False
        self.connected = True
        self.rx_alive = True
        self.heartbeat_alive = True

    def status(self) -> str:
        return "connected" if self.connected else "not_connected"

    def receive_thread_alive(self) -> bool:
        return self.rx_alive

    def heartbeat_thread_alive(self) -> bool:
        return self.heartbeat_alive

    def connect(self, *, timeout_s: float):
        return object()

    def start_gcs_heartbeat(self) -> bool:
        return True

    def stop_gcs_heartbeat(self, **kwargs) -> None:
        self.stopped = True

    def request_local_position_stream(self, *, rate_hz: float, timeout_s: float) -> dict:
        return {"command": 511, "command_name": "MAV_CMD_SET_MESSAGE_INTERVAL", "result": 0, "result_name": "MAV_RESULT_ACCEPTED", "timeout": False}

    def arm(self, *, timeout_s: float) -> dict:
        return {"command": 400, "command_name": "MAV_CMD_COMPONENT_ARM_DISARM", "result": 0, "result_name": "MAV_RESULT_ACCEPTED", "timeout": False}

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict:
        return {"command": 22, "command_name": "MAV_CMD_NAV_TAKEOFF", "result": 0, "result_name": "MAV_RESULT_ACCEPTED", "timeout": False, "local_position_cursor": 17}

    def land(self, *, timeout_s: float) -> dict:
        return {"command": 21, "command_name": "MAV_CMD_NAV_LAND", "result": 0, "result_name": "MAV_RESULT_ACCEPTED", "timeout": False}

    def observe_local_position_altitude(self, *, timeout_s: float, threshold_altitude_m: float | None = None, after_sequence: int | None = None) -> dict:
        assert after_sequence == 17
        return {"observed": True, "samples": 3, "sample_count": 3, "first_z": 0.0, "last_z": -2.13, "min_z": -2.13, "max_z": 0.0, "max_altitude_m": 2.13, "threshold_altitude_m": threshold_altitude_m, "threshold_reached": True}


def test_px4_sitl_takeoff_smoke_rejects_non_sitl_mode(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="stub", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    backend = Px4SitlBackend(cfg, _FakePx4ActionSession())
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))

    result = backend.execute_takeoff_smoke()

    assert result["accepted"] is False
    assert result["failure_reason"] == "sitl_only_required"


def test_px4_sitl_takeoff_smoke_result_contains_ack_and_threshold_fields(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = _FakePx4ActionSession()
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))

    result = backend.execute_takeoff_smoke(altitude_m=3.0, auto_land=True)

    assert result["action"] == "takeoff"
    assert result["endpoint"] == "udpin:127.0.0.1:14540"
    assert result["arm_ack"]["result"] == 0
    assert result["takeoff_ack"]["result"] == 0
    assert result["land_ack"]["result"] == 0
    assert result["max_altitude_m"] == 2.13
    assert result["threshold_altitude_m"] == 2.1
    assert result["threshold_reached"] is True
    assert result["result"] == "pass"
    assert session.stopped is False
    assert session.heartbeat_thread_alive() is True


def test_takeoff_and_land_actions_never_stop_persistent_heartbeat(monkeypatch) -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14541")
    session = _FakePx4ActionSession()
    backend = Px4SitlBackend(cfg, session)
    monkeypatch.setattr(Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: True))

    takeoff = backend.execute_takeoff_smoke(altitude_m=2.0, auto_land=False)
    landed = backend.execute_land_action()

    assert takeoff["result"] == landed["result"] == "pass"
    assert session.stopped is False
    assert session.connected is True
    assert session.receive_thread_alive() is True
    assert session.heartbeat_thread_alive() is True
