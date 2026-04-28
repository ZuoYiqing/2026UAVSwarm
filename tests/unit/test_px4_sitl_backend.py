"""PX4 SITL backend placeholder tests (no real PX4/MAVLink dependency)."""
from __future__ import annotations

from uav_runtime.adapters.mavlink_backend import MavlinkBackend
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend


def test_px4_sitl_backend_conforms_to_mavlink_backend_interface() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    assert isinstance(backend, MavlinkBackend)


def test_px4_sitl_backend_returns_stable_placeholder_semantics() -> None:
    cfg = MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    session = MavlinkBackendSession.from_config(cfg)
    backend = Px4SitlBackend(cfg, session)

    raw = backend.execute_mapped_action(
        action="takeoff",
        mapping={"mavlink_action": "NAV_TAKEOFF"},
        args={"altitude_m": 10},
    )

    assert raw["accepted"] is False
    assert raw["code"] == "backend_probe_failed"
    assert raw["message"] == "px4_sitl_backend_placeholder"
    assert raw["detail"] == "not_implemented"
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
