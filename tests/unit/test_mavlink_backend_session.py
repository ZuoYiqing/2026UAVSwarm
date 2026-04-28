"""MAVLink backend session placeholder tests."""
from __future__ import annotations

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession


def test_session_status_stub_mode() -> None:
    session = MavlinkBackendSession.from_config(MavlinkBackendConfig(backend_mode="stub", backend_enabled=False))

    assert session.status() == "stub"
    assert session.availability_description() == "stub_mode"


def test_session_status_sitl_not_configured() -> None:
    session = MavlinkBackendSession.from_config(MavlinkBackendConfig(backend_mode="sitl", backend_enabled=False))

    assert session.status() == "not_configured"
    assert session.availability_description() == "sitl_backend_disabled"


def test_session_status_sitl_not_connected() -> None:
    session = MavlinkBackendSession.from_config(MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True))

    assert session.status() == "not_connected"
    assert session.availability_description() == "sitl_backend_not_connected"
