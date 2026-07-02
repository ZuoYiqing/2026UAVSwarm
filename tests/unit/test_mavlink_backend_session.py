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

class _FakeMav:
    def __init__(self) -> None:
        self.heartbeats = 0
        self.commands: list[tuple[int, tuple[float, ...]]] = []

    def heartbeat_send(self, *args) -> None:
        self.heartbeats += 1

    def command_long_send(self, target_system, target_component, command, confirmation, *params) -> None:
        self.commands.append((int(command), tuple(float(p) for p in params)))


class _FakeConnection:
    target_system = 1
    target_component = 1

    def __init__(self) -> None:
        self.mav = _FakeMav()


def test_gcs_heartbeat_manager_start_stop_does_not_leave_thread() -> None:
    session = MavlinkBackendSession(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session.connection = _FakeConnection()
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    assert session.start_gcs_heartbeat(period_s=0.01) is True
    assert session.heartbeat_thread_alive() is True

    session.stop_gcs_heartbeat(join_timeout_s=1.0)

    assert session.heartbeat_thread_alive() is False
    assert session.connection.mav.heartbeats >= 1


def test_ack_result_name_mapping_is_stable() -> None:
    from uav_runtime.adapters.mavlink_backend_session import ack_dict, mav_result_name

    assert mav_result_name(0) == "MAV_RESULT_ACCEPTED"
    assert mav_result_name(1) == "MAV_RESULT_TEMPORARILY_REJECTED"
    assert ack_dict("MAV_CMD_NAV_TAKEOFF", None, timeout=True)["result_name"] == "MAV_RESULT_TIMEOUT"
