"""SITL backend stub minimal contract tests."""
from __future__ import annotations

from uav_runtime.adapters.mavlink_backend import MavlinkBackend
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.sitl_backend_stub import SitlBackendStub


def test_sitl_backend_stub_describe_contains_minimal_fields() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = SitlBackendStub(cfg, session)

    desc = backend.describe()

    assert desc["backend"] == "sitl_backend_stub"
    assert desc["mode"] == "sitl"
    assert desc["enabled"] is True
    assert desc["status"] == "not_connected"


def test_sitl_backend_stub_execute_returns_placeholder_not_connected() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True)
    session = MavlinkBackendSession.from_config(cfg)
    backend = SitlBackendStub(cfg, session)

    raw = backend.execute_mapped_action(
        action="takeoff",
        mapping={"mavlink_action": "NAV_TAKEOFF", "param_hints": ["altitude_m"]},
        args={"altitude_m": 10},
    )

    assert raw["accepted"] is False
    assert raw["code"] == "smoke_not_connected"
    assert raw["message"] == "mavlink_sitl_smoke_not_connected"
    assert raw["detail"] == "not_connected"
    assert raw["execution_trace"]["backend_impl"] == "sitl_backend_stub"


def test_sitl_backend_stub_conforms_to_backend_interface() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True)
    session = MavlinkBackendSession.from_config(cfg)
    backend = SitlBackendStub(cfg, session)
    assert isinstance(backend, MavlinkBackend)
