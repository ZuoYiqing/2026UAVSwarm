"""PX4 SITL backend placeholder tests (no real PX4/MAVLink dependency)."""
from __future__ import annotations

from uav_runtime.adapters.mavlink_backend import MavlinkBackend
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend


def test_px4_sitl_backend_conforms_to_mavlink_backend_interface() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    assert isinstance(backend, MavlinkBackend)


def test_px4_sitl_backend_returns_stable_placeholder_semantics() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

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
