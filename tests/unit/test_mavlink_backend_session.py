"""Persistent MAVLink backend session and completion-evidence tests."""
from __future__ import annotations

import threading
import time

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
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    assert session.start_gcs_heartbeat(
        period_s=0.01,
        thread_name="px4-gcs-heartbeat-UAV-02",
    ) is True
    assert session.heartbeat_thread_alive() is True
    thread = session._heartbeat_thread
    assert thread is not None
    assert thread.name == "px4-gcs-heartbeat-UAV-02"
    assert session.start_gcs_heartbeat(period_s=0.01) is False
    assert session._heartbeat_thread is thread

    session.stop_gcs_heartbeat(join_timeout_s=1.0)

    assert session.heartbeat_thread_alive() is False
    assert session.connection.mav.heartbeats >= 1


def test_heartbeat_and_command_writes_share_per_session_tx_lock() -> None:
    heartbeat_entered = threading.Event()
    release_heartbeat = threading.Event()
    command_attempted = threading.Event()
    command_sent = threading.Event()

    class SerializedMav(_FakeMav):
        def heartbeat_send(self, *args) -> None:
            del args
            heartbeat_entered.set()
            assert release_heartbeat.wait(timeout=1)

        def command_long_send(self, *args) -> None:
            del args
            command_sent.set()

    connection = _FakeConnection()
    connection.mav = SerializedMav()
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:2",
    )
    session.connection = connection
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    heartbeat_start = threading.Thread(
        target=session.start_gcs_heartbeat,
        kwargs={"period_s": 1.0},
    )
    heartbeat_start.start()
    assert heartbeat_entered.wait(timeout=1)

    def send_command() -> None:
        command_attempted.set()
        session.send_command_long(22)

    command = threading.Thread(target=send_command)
    command.start()
    assert command_attempted.wait(timeout=1)
    assert command_sent.wait(timeout=0.05) is False

    release_heartbeat.set()
    heartbeat_start.join(timeout=1)
    command.join(timeout=1)

    assert not heartbeat_start.is_alive()
    assert not command.is_alive()
    assert command_sent.is_set()
    session.close()


def test_ack_result_name_mapping_is_stable() -> None:
    from uav_runtime.adapters.mavlink_backend_session import ack_dict, mav_result_name

    assert mav_result_name(0) == "MAV_RESULT_ACCEPTED"
    assert mav_result_name(1) == "MAV_RESULT_TEMPORARILY_REJECTED"
    assert ack_dict("MAV_CMD_NAV_TAKEOFF", None, timeout=True)["result_name"] == "MAV_RESULT_TIMEOUT"


class _FakeLocalPositionMsg:
    def __init__(self, z: float) -> None:
        self.z = z

    def get_type(self) -> str:
        return "LOCAL_POSITION_NED"


class _FakeAckMsg:
    def __init__(self, command: int = 22, result: int = 0) -> None:
        self.command = command
        self.result = result

    def get_type(self) -> str:
        return "COMMAND_ACK"


class _FakeHeartbeatMsg:
    def __init__(self, *, armed: bool) -> None:
        self.base_mode = 128 if armed else 0

    def get_type(self) -> str:
        return "HEARTBEAT"


class _FakeExtendedStateMsg:
    def __init__(self, landed_state: int) -> None:
        self.landed_state = landed_state

    def get_type(self) -> str:
        return "EXTENDED_SYS_STATE"


class _FakeSequenceConnection(_FakeConnection):
    def __init__(self, zs: list[float], *, ack_once: bool = False) -> None:
        super().__init__()
        self._msgs = [_FakeLocalPositionMsg(z) for z in zs]
        self._ack_once = ack_once

    def recv_match(self, type, blocking: bool, timeout: float):
        del type, blocking
        if self._ack_once and self.mav.commands:
            self._ack_once = False
            return _FakeAckMsg()
        if self._msgs:
            return self._msgs.pop(0)
        time.sleep(min(timeout, 0.005))
        return None

    def close(self) -> None:
        pass


class _AckWindowConnection(_FakeSequenceConnection):
    """Emit a new position after TAKEOFF send but before its ACK."""

    def __init__(self, z: float) -> None:
        super().__init__([])
        self._z = z
        self._position_sent = False
        self._ack_sent = False

    def recv_match(self, type, blocking: bool, timeout: float):
        del type, blocking
        if self.mav.commands and not self._position_sent:
            self._position_sent = True
            return _FakeLocalPositionMsg(self._z)
        if self.mav.commands and not self._ack_sent:
            self._ack_sent = True
            return _FakeAckMsg()
        time.sleep(min(timeout, 0.005))
        return None


class _LandAckWindowConnection(_FakeSequenceConnection):
    """Emit landed/disarmed evidence after LAND send and before its ACK."""

    def __init__(self) -> None:
        super().__init__([])
        self._events = [
            _FakeExtendedStateMsg(1),
            _FakeHeartbeatMsg(armed=False),
            _FakeAckMsg(command=21),
        ]

    def recv_match(self, type, blocking: bool, timeout: float):
        del type, blocking
        if self.mav.commands and self.mav.commands[-1][0] == 21 and self._events:
            return self._events.pop(0)
        time.sleep(min(timeout, 0.005))
        return None


def test_ned_down_z_to_altitude_conversion() -> None:
    from uav_runtime.adapters.mavlink_backend_session import ned_down_z_to_altitude_m

    assert ned_down_z_to_altitude_m(-2.13) == 2.13
    assert ned_down_z_to_altitude_m(0.0) == 0.0
    assert ned_down_z_to_altitude_m(0.02) == 0.0


def test_observe_local_position_uses_negative_z_for_max_altitude() -> None:
    session = MavlinkBackendSession(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session.connection = _FakeSequenceConnection([0.02, 0.0, -1.0, -2.13])
    session.connected = True

    observation = session.observe_local_position_altitude(timeout_s=0.2, threshold_altitude_m=2.1)

    assert observation["sample_count"] == 4
    assert observation["first_z"] == 0.02
    assert observation["last_z"] == -2.13
    assert observation["min_z"] == -2.13
    assert observation["max_z"] == 0.02
    assert observation["max_altitude_m"] == 2.13
    assert observation["threshold_altitude_m"] == 2.1
    assert observation["threshold_reached"] is True


def test_old_cached_high_altitude_is_not_current_takeoff_evidence() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:1",
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    session.dispatch_message(_FakeLocalPositionMsg(-9.0))
    cursor = session.local_position_cursor()

    observation = session.observe_local_position_altitude(
        timeout_s=0.01,
        threshold_altitude_m=2.0,
        after_sequence=cursor,
    )

    assert observation["sample_count"] == 0
    assert observation["max_altitude_m"] == 0.0
    assert observation["threshold_reached"] is False
    session.close()


def test_takeoff_ack_wait_window_samples_are_observed_after_command_cursor() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:1",
    )
    session.connection = _AckWindowConnection(-2.5)
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    takeoff_ack = session.takeoff(altitude_m=3.0, timeout_s=0.2)
    observation = session.observe_local_position_altitude(
        timeout_s=0.1,
        threshold_altitude_m=2.0,
        after_sequence=takeoff_ack["local_position_cursor"],
    )

    assert takeoff_ack["result"] == 0
    assert takeoff_ack["timestamp"].endswith("Z")
    assert observation["sample_count"] == 1
    assert observation["max_altitude_m"] == 2.5
    assert observation["threshold_reached"] is True
    session.close()


def test_three_sessions_keep_local_position_cursors_and_samples_isolated() -> None:
    sessions: list[MavlinkBackendSession] = []
    cursors: list[int] = []
    for index in range(3):
        session = MavlinkBackendSession(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint=f"udp:{index + 1}",
        )
        session.connection = _FakeSequenceConnection([])
        session.connected = True
        for _ in range(index + 1):
            session.dispatch_message(_FakeLocalPositionMsg(-8.0))
        cursors.append(session.local_position_cursor())
        sessions.append(session)

    sessions[0].dispatch_message(_FakeLocalPositionMsg(-2.5))
    sessions[2].dispatch_message(_FakeLocalPositionMsg(-1.0))

    observations = [
        session.observe_local_position_altitude(
            timeout_s=0.01,
            threshold_altitude_m=2.0,
            after_sequence=cursor,
        )
        for session, cursor in zip(sessions, cursors)
    ]

    assert cursors == [1, 2, 3]
    assert [item["sample_count"] for item in observations] == [1, 0, 1]
    assert [item["threshold_reached"] for item in observations] == [True, False, False]
    assert [item["max_altitude_m"] for item in observations] == [2.5, 0.0, 1.0]
    for session in sessions:
        session.close()


def test_takeoff_command_uses_nan_yaw_lat_lon_params() -> None:
    import math

    session = MavlinkBackendSession(backend_mode="sitl", backend_enabled=True, transport_endpoint="udpin:127.0.0.1:14540")
    session.connection = _FakeSequenceConnection([], ack_once=True)
    session.connected = True
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
    session.close()


def test_one_session_has_exactly_one_receive_owner_and_multiple_subscribers() -> None:
    connection = _FakeSequenceConnection([])
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = connection
    session.connected = True
    observed: list[str] = []
    session.subscribe(lambda message: observed.append(message.get_type()))

    assert session.start_receive_loop(thread_name="mavlink-rx-UAV-01") is True
    assert session.start_receive_loop(thread_name="duplicate") is False
    assert session.receive_owner_count() == 1
    session.dispatch_message(_FakeLocalPositionMsg(-1.0))
    assert observed == ["LOCAL_POSITION_NED"]
    session.close()
    assert session.receive_owner_count() == 0


def test_ack_dispatch_is_command_scoped_and_drops_stale_unclaimed_ack() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    session.start_receive_loop()
    # No waiter exists, so this old ACK is intentionally discarded.
    session.dispatch_message(_FakeAckMsg(command=22, result=2))
    generation = session._begin_ack_wait(22)
    session.dispatch_message(_FakeAckMsg(command=21, result=0))
    session.dispatch_message(_FakeAckMsg(command=22, result=0))

    ack = session.wait_command_ack(22, timeout_s=0.1, generation=generation)

    assert ack["result"] == 0
    assert ack["timeout"] is False
    session.close()


def test_three_sessions_keep_receive_owners_and_dispatch_isolated() -> None:
    sessions = []
    observed = [[], [], []]
    for index in range(3):
        session = MavlinkBackendSession(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint=f"udp:{index + 1}",
            expected_target_system=index + 1,
        )
        session.connection = _FakeSequenceConnection([])
        session.connected = True
        session.subscribe(lambda message, i=index: observed[i].append(message.z))
        session.start_receive_loop(thread_name=f"mavlink-rx-UAV-0{index + 1}")
        sessions.append(session)

    sessions[1].dispatch_message(_FakeLocalPositionMsg(-2.0))
    assert observed == [[], [-2.0], []]
    assert sum(session.receive_owner_count() for session in sessions) == 3
    for session in sessions:
        session.close()


def test_operational_takeoff_requires_fresh_samples_stable_for_hold_window() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    cursor = session.observation_cursor()
    result: dict[str, object] = {}

    def observe() -> None:
        result.update(session.observe_takeoff_completion(
            timeout_s=0.5,
            target_altitude_m=3.0,
            tolerance_m=0.2,
            stable_duration_s=0.03,
            after_sequence=cursor,
        ))

    thread = threading.Thread(target=observe)
    thread.start()
    session.dispatch_message(_FakeLocalPositionMsg(-3.0))
    time.sleep(0.04)
    session.dispatch_message(_FakeLocalPositionMsg(-3.1))
    thread.join(timeout=1)

    assert result["status"] == "succeeded"
    assert result["completion_reached"] is True
    assert result["stable_sample_count"] == 2
    assert str(result["first_sample_timestamp"]).endswith("Z")
    assert str(result["last_sample_timestamp"]).endswith("Z")
    session.close()


def test_land_ack_wait_window_evidence_is_observed_after_command_cursor() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:1",
    )
    session.connection = _LandAckWindowConnection()
    session.connected = True
    session._mavutil = type("FakeMavutil", (), {"mavlink": object()})()

    land_ack = session.land(timeout_s=0.2)
    observation = session.observe_landed_and_disarmed(
        timeout_s=0.1,
        after_sequence=land_ack["observation_cursor"],
    )

    assert land_ack["result"] == 0
    assert observation["completion_reached"] is True
    assert observation["landed_state_name"] == "on_ground"
    assert observation["armed"] is False
    session.close()


def test_operational_takeoff_ack_height_without_stable_hold_times_out() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    cursor = session.observation_cursor()
    session.dispatch_message(_FakeLocalPositionMsg(-3.0))

    observation = session.observe_takeoff_completion(
        timeout_s=0.02,
        target_altitude_m=3.0,
        tolerance_m=0.2,
        stable_duration_s=0.01,
        after_sequence=cursor,
    )

    assert observation["status"] == "timed_out"
    assert observation["sample_count"] == 1
    assert observation["completion_reached"] is False
    session.close()


def test_old_landed_and_disarmed_cache_is_not_new_land_completion_evidence() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    session.dispatch_message(_FakeExtendedStateMsg(1))
    session.dispatch_message(_FakeHeartbeatMsg(armed=False))
    cursor = session.observation_cursor()

    observation = session.observe_landed_and_disarmed(
        timeout_s=0.02,
        after_sequence=cursor,
    )

    assert observation["status"] == "timed_out"
    assert observation["telemetry_state"] == "unknown"
    assert observation["completion_reached"] is False
    session.close()


def test_fresh_landed_without_disarm_is_incomplete_not_success() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    cursor = session.observation_cursor()
    session.dispatch_message(_FakeExtendedStateMsg(1))
    session.dispatch_message(_FakeHeartbeatMsg(armed=True))

    observation = session.observe_landed_and_disarmed(
        timeout_s=0.02,
        after_sequence=cursor,
    )

    assert observation["status"] == "timed_out"
    assert observation["telemetry_state"] == "incomplete"
    assert observation["landed_state_name"] == "on_ground"
    assert observation["armed"] is True
    assert observation["completion_reached"] is False
    session.close()


def test_land_completion_rejects_post_command_but_expired_samples() -> None:
    session = MavlinkBackendSession(
        backend_mode="sitl", backend_enabled=True, transport_endpoint="udp:1"
    )
    session.connection = _FakeSequenceConnection([])
    session.connected = True
    cursor = session.observation_cursor()
    session.dispatch_message(_FakeExtendedStateMsg(1))
    time.sleep(0.02)
    session.dispatch_message(_FakeHeartbeatMsg(armed=False))

    observation = session.observe_landed_and_disarmed(
        timeout_s=0.02,
        after_sequence=cursor,
        freshness_window_s=0.01,
    )

    assert observation["status"] == "timed_out"
    assert observation["telemetry_state"] == "stale"
    assert observation["landed_sample_age_ms"] > observation["freshness_window_ms"]
    assert observation["completion_reached"] is False
    session.close()


def test_wrong_source_identity_is_not_dispatched_to_node_subscribers() -> None:
    class Header:
        srcSystem = 2
        srcComponent = 1

    message = _FakeLocalPositionMsg(-3.0)
    message._header = Header()
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:1",
        expected_target_system=1,
        expected_target_component=1,
    )
    observed: list[float] = []
    session.subscribe(lambda msg: observed.append(msg.z))

    session.dispatch_message(message)

    assert observed == []
    assert session.identity_error["code"] == "target_system_mismatch"


def test_connect_validates_heartbeat_identity_and_closes_mismatch() -> None:
    class Heartbeat:
        def get_srcSystem(self) -> int: return 2
        def get_srcComponent(self) -> int: return 1

    class Connection(_FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False
        def wait_heartbeat(self, *, timeout: float): return Heartbeat()
        def close(self) -> None: self.closed = True

    connection = Connection()
    mavutil = type(
        "Mavutil",
        (),
        {"mavlink_connection": staticmethod(lambda *args, **kwargs: connection)},
    )()
    session = MavlinkBackendSession(
        backend_mode="sitl",
        backend_enabled=True,
        transport_endpoint="udp:1",
        expected_target_system=1,
        expected_target_component=1,
    )

    import pytest
    with pytest.raises(RuntimeError, match="target_system_mismatch"):
        session.connect(timeout_s=0.1, mavutil_module=mavutil)

    assert connection.closed is True
    assert session.connection is None
    assert session.connected is False
