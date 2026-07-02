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


class _FakeLocalPositionMsg:
    def __init__(self, z: float) -> None:
        self.z = z


class _FakeAckMsg:
    command = 22
    result = 0


class _FakeSequenceConnection(_FakeConnection):
    def __init__(self, zs: list[float], *, ack_once: bool = False) -> None:
        super().__init__()
        self._msgs = [_FakeLocalPositionMsg(z) for z in zs]
        self._ack_once = ack_once

    def recv_match(self, type: str, blocking: bool, timeout: float):
        if type == "COMMAND_ACK" and self._ack_once:
            self._ack_once = False
            return _FakeAckMsg()
        if type == "LOCAL_POSITION_NED" and self._msgs:
            return self._msgs.pop(0)
        return None


def test_ned_down_z_to_altitude_conversion() -> None:
    from uav_runtime.adapters.mavlink_backend_session import ned_down_z_to_altitude_m

    assert ned_down_z_to_altitude_m(-2.13) == 2.13
    assert ned_down_z_to_altitude_m(0.0) == 0.0
    assert ned_down_z_to_altitude_m(0.02) == 0.0


def test_observe_local_position_uses_negative_z_for_max_altitude() -> None:
    session = MavlinkBackendSession(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session.connection = _FakeSequenceConnection([0.02, 0.0, -1.0, -2.13])

    observation = session.observe_local_position_altitude(timeout_s=0.01, threshold_altitude_m=2.1)

    assert observation["sample_count"] == 4
    assert observation["first_z"] == 0.02
    assert observation["last_z"] == -2.13
    assert observation["min_z"] == -2.13
    assert observation["max_z"] == 0.02
    assert observation["max_altitude_m"] == 2.13
    assert observation["threshold_altitude_m"] == 2.1
    assert observation["threshold_reached"] is True


def test_takeoff_command_uses_nan_yaw_lat_lon_params() -> None:
    import math

    session = MavlinkBackendSession(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session.connection = _FakeSequenceConnection([], ack_once=True)
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    ack = session.takeoff(altitude_m=3.0, timeout_s=1.0)

    assert ack["result"] == 0

    command, params = session.connection.mav.commands[-1]
    assert command == 22
    assert math.isnan(params[0])
    assert params[1] == 0.0
    assert params[2] == 0.0
    assert math.isnan(params[3])
    assert math.isnan(params[4])
    assert math.isnan(params[5])
    assert params[6] == 3.0
