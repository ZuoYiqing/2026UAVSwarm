from __future__ import annotations

import pytest

from uav_runtime.adapters.px4_telemetry import (
    altitude_from_ned_z,
    apply_mavlink_message,
    new_snapshot,
    snapshot_to_dict,
    telemetry_summary,
)


class FakeMsg:
    def __init__(self, msg_type: str, **fields):
        self._msg_type = msg_type
        for key, value in fields.items():
            setattr(self, key, value)

    def get_type(self) -> str:
        return self._msg_type


def test_ned_positive_down_z_converts_to_altitude():
    assert altitude_from_ned_z(-2.13) == pytest.approx(2.13)
    assert altitude_from_ned_z(0.0) == pytest.approx(0.0)
    assert altitude_from_ned_z(0.02) == pytest.approx(0.0)


def test_local_position_updates_altitude_from_negative_z():
    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14540")
    apply_mavlink_message(snapshot, FakeMsg("LOCAL_POSITION_NED", x=1.0, y=2.0, z=-2.12, vx=0.1, vy=0.2, vz=-0.3))

    assert snapshot.local_position.z_down_m == pytest.approx(-2.12)
    assert snapshot.local_position.altitude_m == pytest.approx(2.12)
    assert snapshot.source_message_counts["LOCAL_POSITION_NED"] == 1


def test_message_counts_and_attitude_snapshot_fields():
    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14030")
    apply_mavlink_message(snapshot, FakeMsg("HEARTBEAT", type=2, autopilot=12, base_mode=128, custom_mode=0, system_status=4))
    apply_mavlink_message(snapshot, FakeMsg("ATTITUDE", roll=0.1, pitch=-0.2, yaw=0.3))
    apply_mavlink_message(snapshot, FakeMsg("COMMAND_ACK", command=22, result=0))

    data = snapshot_to_dict(snapshot)
    assert data["endpoint"] == "udpin:127.0.0.1:14030"
    assert data["connected"] is True
    assert data["armed"] is True
    assert data["source_message_counts"]["HEARTBEAT"] == 1
    assert data["source_message_counts"]["ATTITUDE"] == 1
    assert data["last_command_ack"]["result_name"] == "MAV_RESULT_ACCEPTED"
    assert data["attitude"]["roll_deg"] == pytest.approx(5.7295779)


def test_telemetry_summary_contains_altitude_and_z_fields():
    samples = []
    for z in [0.0, -1.0, -2.1]:
        snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14540", connected=True)
        apply_mavlink_message(snapshot, FakeMsg("LOCAL_POSITION_NED", x=0, y=0, z=z, vx=0, vy=0, vz=0))
        samples.append(snapshot_to_dict(snapshot))

    summary = telemetry_summary(samples, endpoint="udpin:127.0.0.1:14540", connected=True, duration_s=3.0, message_counts={"LOCAL_POSITION_NED": 3})

    assert summary["endpoint"] == "udpin:127.0.0.1:14540"
    assert summary["sample_count"] == 3
    assert summary["max_altitude_m"] == pytest.approx(2.1)
    assert summary["min_z_down_m"] == pytest.approx(-2.1)
    assert summary["first_timestamp"] is not None
    assert summary["last_timestamp"] is not None


def test_positive_down_z_never_becomes_positive_altitude():
    assert altitude_from_ned_z(1.0) == pytest.approx(0.0)


def test_sys_status_updates_sensor_health_fields():
    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14540")
    apply_mavlink_message(
        snapshot,
        FakeMsg(
            "SYS_STATUS",
            voltage_battery=12000,
            current_battery=345,
            battery_remaining=88,
            onboard_control_sensors_present=1,
            onboard_control_sensors_enabled=2,
            onboard_control_sensors_health=3,
        ),
    )

    assert snapshot.battery.voltage_v == pytest.approx(12.0)
    assert snapshot.battery.current_a == pytest.approx(3.45)
    assert snapshot.battery.battery_remaining == 88
    assert snapshot.battery.onboard_control_sensors_present == 1
    assert snapshot.battery.onboard_control_sensors_enabled == 2
    assert snapshot.battery.onboard_control_sensors_health == 3


def test_console_view_model_and_event_envelope_fields_exist():
    from uav_runtime.adapters.px4_telemetry import (
        to_event_envelope,
        to_node_state_view,
        to_runtime_snapshot_fragment,
        to_telemetry_latest_view,
        validate_observe_parameters,
    )

    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14540", connected=True)
    apply_mavlink_message(snapshot, FakeMsg("LOCAL_POSITION_NED", x=0, y=0, z=-2.12, vx=3.0, vy=4.0, vz=-0.5))
    apply_mavlink_message(snapshot, FakeMsg("ATTITUDE", roll=0.1, pitch=0.2, yaw=0.3))

    node = to_node_state_view(snapshot)
    latest = to_telemetry_latest_view(snapshot)
    fragment = to_runtime_snapshot_fragment(snapshot)
    event = to_event_envelope(
        event_type="telemetry_sample",
        backend="px4_sitl",
        backend_mode="sitl",
        endpoint="udpin:127.0.0.1:14540",
        summary="sample",
        payload={"altitude_m": 2.12},
    )

    assert node.altitude_m == pytest.approx(2.12)
    assert node.velocity["ground_speed_mps"] == pytest.approx(5.0)
    assert latest["nodes"][0]["node_id"] == "UAV-01"
    assert fragment["connected"] is True
    assert event["event_type"] == "telemetry_sample"
    assert event["trace_id"].startswith("trc-")
    assert validate_observe_parameters(
        backend_mode="sitl",
        backend_enabled=True,
        endpoint="udpin:127.0.0.1:14540",
        duration_s=30,
        rate_hz=5,
    ) == []


def test_observe_parameter_validation_rejects_disabled_and_bad_ranges():
    from uav_runtime.adapters.px4_telemetry import validate_observe_parameters

    errors = validate_observe_parameters(
        backend_mode="stub",
        backend_enabled=False,
        endpoint="udp://127.0.0.1:14540",
        duration_s=0.5,
        rate_hz=100,
    )

    assert "backend_mode_must_be_sitl" in errors
    assert "backend_enabled_required" in errors
    assert "transport_endpoint_must_use_udpin" in errors
    assert "duration_s_out_of_range" in errors
    assert "rate_hz_out_of_range" in errors
