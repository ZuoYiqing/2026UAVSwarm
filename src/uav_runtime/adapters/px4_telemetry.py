"""PX4 SITL telemetry snapshot helpers.

This module normalizes MAVLink messages into runtime-owned telemetry data.  It
intentionally contains no frontend-specific fields and never sends ARM, TAKEOFF,
or LAND; command execution remains under Runtime/Policy control.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import asdict, dataclass, field
from uuid import uuid4
from pathlib import Path
from typing import Any

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession, mav_result_name, ned_down_z_to_altitude_m

TRACKED_MESSAGE_TYPES = (
    "HEARTBEAT",
    "LOCAL_POSITION_NED",
    "ATTITUDE",
    "GLOBAL_POSITION_INT",
    "SYS_STATUS",
    "BATTERY_STATUS",
    "VFR_HUD",
    "COMMAND_ACK",
)


@dataclass(slots=True)
class LocalPositionTelemetry:
    x_m: float | None = None
    y_m: float | None = None
    z_down_m: float | None = None
    altitude_m: float | None = None
    vx_m_s: float | None = None
    vy_m_s: float | None = None
    vz_m_s: float | None = None


@dataclass(slots=True)
class AttitudeTelemetry:
    roll_rad: float | None = None
    pitch_rad: float | None = None
    yaw_rad: float | None = None
    roll_deg: float | None = None
    pitch_deg: float | None = None
    yaw_deg: float | None = None


@dataclass(slots=True)
class GlobalPositionTelemetry:
    lat_deg: float | None = None
    lon_deg: float | None = None
    relative_alt_m: float | None = None
    heading_deg: float | None = None


@dataclass(slots=True)
class BatteryTelemetry:
    voltage_v: float | None = None
    current_a: float | None = None
    battery_remaining: int | None = None
    onboard_control_sensors_present: int | None = None
    onboard_control_sensors_enabled: int | None = None
    onboard_control_sensors_health: int | None = None


@dataclass(slots=True)
class CommandAckTelemetry:
    command: int | None = None
    command_name: str | None = None
    result: int | None = None
    result_name: str | None = None
    timeout: bool = False




@dataclass(slots=True)
class NodeStateView:
    """Console-facing node view derived from PX4 telemetry, not a control grant."""

    node_id: str
    backend: str
    status: str
    battery_percent: int | None
    altitude_m: float | None
    attitude: dict[str, float | None]
    velocity: dict[str, float | None]
    last_seen: str
    source: str = "telemetry"


@dataclass(slots=True)
class TelemetryLatest:
    """Latest telemetry view for HTTP/console consumers without requiring WebSocket."""

    timestamp: str
    backend: str
    nodes: list[NodeStateView]
    source: str = "telemetry"


@dataclass(slots=True)
class RuntimeSnapshotFragment:
    """Small runtime snapshot fragment that can be merged into RuntimeSnapshot later."""

    timestamp: str
    backend: str
    backend_mode: str
    endpoint: str
    connected: bool
    node: NodeStateView
    source: str = "telemetry"


@dataclass(slots=True)
class Px4TelemetrySnapshot:
    """Runtime-level PX4 telemetry view, not a frontend DTO or execution result."""

    timestamp: str
    backend: str = "px4_sitl"
    backend_mode: str = "sitl"
    endpoint: str = "udpin:127.0.0.1:14540"
    connected: bool = False
    system_id: int | None = None
    component_id: int | None = None
    armed: bool | None = None
    vehicle_type: int | None = None
    autopilot: int | None = None
    flight_mode: str | None = None
    custom_mode: int | None = None
    system_status: int | None = None
    local_position: LocalPositionTelemetry = field(default_factory=LocalPositionTelemetry)
    attitude: AttitudeTelemetry = field(default_factory=AttitudeTelemetry)
    global_position: GlobalPositionTelemetry = field(default_factory=GlobalPositionTelemetry)
    battery: BatteryTelemetry = field(default_factory=BatteryTelemetry)
    last_command_ack: CommandAckTelemetry | None = None
    source_message_counts: dict[str, int] = field(default_factory=lambda: {name: 0 for name in TRACKED_MESSAGE_TYPES})


def altitude_from_ned_z(z_down_m: float) -> float:
    """Convert PX4 LOCAL_POSITION_NED positive-down z into positive altitude."""
    return ned_down_z_to_altitude_m(float(z_down_m))


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _finite_or_zero(value: Any) -> float:
    numeric = _finite_or_none(value)
    return 0.0 if numeric is None else numeric


def validate_observe_parameters(*, backend_mode: str, backend_enabled: bool, endpoint: str, duration_s: float, rate_hz: float) -> list[str]:
    errors: list[str] = []
    if backend_mode != "sitl":
        errors.append("backend_mode_must_be_sitl")
    if not backend_enabled:
        errors.append("backend_enabled_required")
    if not endpoint:
        errors.append("transport_endpoint_missing")
    elif not endpoint.startswith("udpin:"):
        errors.append("transport_endpoint_must_use_udpin")
    if not (1.0 <= float(duration_s) <= 3600.0):
        errors.append("duration_s_out_of_range")
    if not (0.2 <= float(rate_hz) <= 50.0):
        errors.append("rate_hz_out_of_range")
    return errors


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()


def new_snapshot(*, endpoint: str, backend_mode: str = "sitl", connected: bool = False) -> Px4TelemetrySnapshot:
    return Px4TelemetrySnapshot(timestamp=_utc_now(), endpoint=endpoint, backend_mode=backend_mode, connected=connected)


def snapshot_to_dict(snapshot: Px4TelemetrySnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def message_type(msg: Any) -> str:
    getter = getattr(msg, "get_type", None)
    if callable(getter):
        return str(getter())
    return str(getattr(msg, "type", msg.__class__.__name__))


def _src_ids(msg: Any) -> tuple[int | None, int | None]:
    header = getattr(msg, "_header", None)
    return getattr(header, "srcSystem", None), getattr(header, "srcComponent", None)


def apply_mavlink_message(snapshot: Px4TelemetrySnapshot, msg: Any, *, flight_mode: str | None = None) -> Px4TelemetrySnapshot:
    """Merge one MAVLink message into a snapshot and update source counts.

    The important safety detail is LOCAL_POSITION_NED.z: PX4 uses NED
    positive-down coordinates, so climb produces negative z and altitude is -z.
    """
    msg_type = message_type(msg)
    if msg_type in snapshot.source_message_counts:
        snapshot.source_message_counts[msg_type] += 1
    snapshot.timestamp = _utc_now()

    if msg_type == "HEARTBEAT":
        system_id, component_id = _src_ids(msg)
        snapshot.connected = True
        snapshot.system_id = int(system_id) if system_id is not None else snapshot.system_id
        snapshot.component_id = int(component_id) if component_id is not None else snapshot.component_id
        snapshot.vehicle_type = int(getattr(msg, "type", snapshot.vehicle_type) or 0)
        snapshot.autopilot = int(getattr(msg, "autopilot", snapshot.autopilot) or 0)
        base_mode = getattr(msg, "base_mode", None)
        snapshot.armed = bool(int(base_mode) & 128) if base_mode is not None else snapshot.armed
        snapshot.custom_mode = int(getattr(msg, "custom_mode", snapshot.custom_mode) or 0)
        snapshot.system_status = int(getattr(msg, "system_status", snapshot.system_status) or 0)
        snapshot.flight_mode = flight_mode or snapshot.flight_mode
    elif msg_type == "LOCAL_POSITION_NED":
        z_down = _finite_or_zero(getattr(msg, "z", 0.0))
        snapshot.local_position = LocalPositionTelemetry(
            x_m=_finite_or_none(getattr(msg, "x", 0.0)),
            y_m=_finite_or_none(getattr(msg, "y", 0.0)),
            z_down_m=z_down,
            altitude_m=altitude_from_ned_z(z_down),
            vx_m_s=_finite_or_none(getattr(msg, "vx", 0.0)),
            vy_m_s=_finite_or_none(getattr(msg, "vy", 0.0)),
            vz_m_s=_finite_or_none(getattr(msg, "vz", 0.0)),
        )
    elif msg_type == "ATTITUDE":
        roll = _finite_or_zero(getattr(msg, "roll", 0.0))
        pitch = _finite_or_zero(getattr(msg, "pitch", 0.0))
        yaw = _finite_or_zero(getattr(msg, "yaw", 0.0))
        snapshot.attitude = AttitudeTelemetry(
            roll_rad=roll,
            pitch_rad=pitch,
            yaw_rad=yaw,
            roll_deg=math.degrees(roll),
            pitch_deg=math.degrees(pitch),
            yaw_deg=math.degrees(yaw),
        )
    elif msg_type == "GLOBAL_POSITION_INT":
        hdg = getattr(msg, "hdg", None)
        snapshot.global_position = GlobalPositionTelemetry(
            lat_deg=_finite_or_zero(getattr(msg, "lat", 0.0)) / 1e7,
            lon_deg=_finite_or_zero(getattr(msg, "lon", 0.0)) / 1e7,
            relative_alt_m=_finite_or_zero(getattr(msg, "relative_alt", 0.0)) / 1000.0,
            heading_deg=None if hdg in (None, 65535) else _finite_or_zero(hdg) / 100.0,
        )
    elif msg_type == "SYS_STATUS":
        voltage = getattr(msg, "voltage_battery", None)
        current = getattr(msg, "current_battery", None)
        snapshot.battery = BatteryTelemetry(
            voltage_v=None if voltage in (None, 65535) else _finite_or_zero(voltage) / 1000.0,
            current_a=None if current in (None, -1) else _finite_or_zero(current) / 100.0,
            battery_remaining=getattr(msg, "battery_remaining", None),
            onboard_control_sensors_present=getattr(msg, "onboard_control_sensors_present", None),
            onboard_control_sensors_enabled=getattr(msg, "onboard_control_sensors_enabled", None),
            onboard_control_sensors_health=getattr(msg, "onboard_control_sensors_health", None),
        )
    elif msg_type == "BATTERY_STATUS":
        voltages = getattr(msg, "voltages", []) or []
        valid = [v for v in voltages if v not in (0, 65535)]
        snapshot.battery.voltage_v = (sum(valid) / 1000.0) if valid else snapshot.battery.voltage_v
        current = getattr(msg, "current_battery", None)
        snapshot.battery.current_a = None if current in (None, -1) else float(current) / 100.0
        snapshot.battery.battery_remaining = getattr(msg, "battery_remaining", snapshot.battery.battery_remaining)
    elif msg_type == "COMMAND_ACK":
        result = getattr(msg, "result", None)
        command = getattr(msg, "command", None)
        snapshot.last_command_ack = CommandAckTelemetry(
            command=None if command is None else int(command),
            command_name=str(command) if command is not None else None,
            result=None if result is None else int(result),
            result_name=mav_result_name(result),
            timeout=False,
        )
    return snapshot


def telemetry_summary(samples: list[dict[str, Any]], *, endpoint: str, connected: bool, duration_s: float, message_counts: dict[str, int]) -> dict[str, Any]:
    altitudes = [s.get("local_position", {}).get("altitude_m") for s in samples]
    altitudes = [float(v) for v in altitudes if v is not None and math.isfinite(float(v))]
    z_values = [s.get("local_position", {}).get("z_down_m") for s in samples]
    z_values = [float(v) for v in z_values if v is not None and math.isfinite(float(v))]
    result = {
        "endpoint": endpoint,
        "connected": bool(connected),
        "duration_s": float(duration_s),
        "sample_count": len(samples),
        "max_altitude_m": max(altitudes) if altitudes else None,
        "min_altitude_m": min(altitudes) if altitudes else None,
        "first_altitude_m": altitudes[0] if altitudes else None,
        "last_altitude_m": altitudes[-1] if altitudes else None,
        "first_z_down_m": z_values[0] if z_values else None,
        "last_z_down_m": z_values[-1] if z_values else None,
        "min_z_down_m": min(z_values) if z_values else None,
        "max_z_down_m": max(z_values) if z_values else None,
        "message_counts": dict(message_counts),
        "first_timestamp": samples[0].get("timestamp") if samples else None,
        "last_timestamp": samples[-1].get("timestamp") if samples else None,
    }
    result["event_envelope"] = to_event_envelope(
        event_type="telemetry_summary",
        backend="px4_sitl",
        backend_mode="sitl",
        endpoint=endpoint,
        summary=f"Telemetry summary: {len(samples)} samples",
        payload={k: v for k, v in result.items() if k != "event_envelope"},
    )
    return result


def to_event_envelope(*, event_type: str, backend: str, backend_mode: str, endpoint: str, summary: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": f"evt-{uuid4().hex[:12]}",
        "trace_id": f"trc-{uuid4().hex[:12]}",
        "mission_id": None,
        "session_id": f"sess-{uuid4().hex[:12]}",
        "parent_event_id": None,
        "event_type": event_type,
        "severity": "info",
        "source": "px4_telemetry_bridge",
        "node_id": "UAV-01",
        "timestamp": _utc_now(),
        "summary": summary,
        "payload": {"backend": backend, "backend_mode": backend_mode, "endpoint": endpoint, **payload},
    }


def to_node_state_view(snapshot: Px4TelemetrySnapshot, *, node_id: str = "UAV-01") -> NodeStateView:
    return NodeStateView(
        node_id=node_id,
        backend=snapshot.backend,
        status="online" if snapshot.connected else "offline",
        battery_percent=snapshot.battery.battery_remaining,
        altitude_m=snapshot.local_position.altitude_m,
        attitude={
            "roll_deg": snapshot.attitude.roll_deg,
            "pitch_deg": snapshot.attitude.pitch_deg,
            "yaw_deg": snapshot.attitude.yaw_deg,
        },
        velocity={
            "ground_speed_mps": None if snapshot.local_position.vx_m_s is None or snapshot.local_position.vy_m_s is None else math.hypot(snapshot.local_position.vx_m_s, snapshot.local_position.vy_m_s),
            "vertical_speed_mps": snapshot.local_position.vz_m_s,
        },
        last_seen=snapshot.timestamp,
    )


def to_telemetry_latest_view(snapshot: Px4TelemetrySnapshot, *, node_id: str = "UAV-01") -> dict[str, Any]:
    return asdict(TelemetryLatest(timestamp=snapshot.timestamp, backend=snapshot.backend, nodes=[to_node_state_view(snapshot, node_id=node_id)]))


def to_runtime_snapshot_fragment(snapshot: Px4TelemetrySnapshot, *, node_id: str = "UAV-01") -> dict[str, Any]:
    node = to_node_state_view(snapshot, node_id=node_id)
    return asdict(RuntimeSnapshotFragment(
        timestamp=snapshot.timestamp,
        backend=snapshot.backend,
        backend_mode=snapshot.backend_mode,
        endpoint=snapshot.endpoint,
        connected=snapshot.connected,
        node=node,
    ))


def _request_message_intervals(conn: Any, mavutil: Any, *, rate_hz: float) -> None:
    """Best-effort telemetry-rate request; failures must not turn observation into control."""
    mavlink = getattr(mavutil, "mavlink", None)
    command = int(getattr(mavlink, "MAV_CMD_SET_MESSAGE_INTERVAL", 511))
    message_ids = [
        int(getattr(mavlink, "MAVLINK_MSG_ID_LOCAL_POSITION_NED", 32)),
        int(getattr(mavlink, "MAVLINK_MSG_ID_ATTITUDE", 30)),
        int(getattr(mavlink, "MAVLINK_MSG_ID_GLOBAL_POSITION_INT", 33)),
        int(getattr(mavlink, "MAVLINK_MSG_ID_SYS_STATUS", 1)),
        int(getattr(mavlink, "MAVLINK_MSG_ID_BATTERY_STATUS", 147)),
    ]
    interval_us = int(1_000_000 / max(rate_hz, 0.1))
    target_system = int(getattr(conn, "target_system", 1) or 1)
    target_component = int(getattr(conn, "target_component", 1) or 1)
    for message_id in message_ids:
        try:
            conn.mav.command_long_send(
                target_system,
                target_component,
                command,
                0,
                float(message_id),
                float(interval_us),
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )
        except Exception:
            # Some endpoints may be receive-only or omit optional streams.  The
            # bridge remains read-only and reports whatever telemetry arrives.
            continue

def _write_outputs(samples: list[dict[str, Any]], summary: dict[str, Any], *, output_json: str | None, output_jsonl: str | None, output_csv: str | None) -> None:
    if output_json:
        path = Path(output_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if output_jsonl:
        path = Path(output_jsonl).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for sample in samples:
                fh.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
    if output_csv:
        path = Path(output_csv).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["timestamp", "connected", "altitude_m", "z_down_m", "x_m", "y_m", "roll_deg", "pitch_deg", "yaw_deg"]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for sample in samples:
                local = sample.get("local_position", {})
                attitude = sample.get("attitude", {})
                writer.writerow({
                    "timestamp": sample.get("timestamp"),
                    "connected": sample.get("connected"),
                    "altitude_m": local.get("altitude_m"),
                    "z_down_m": local.get("z_down_m"),
                    "x_m": local.get("x_m"),
                    "y_m": local.get("y_m"),
                    "roll_deg": attitude.get("roll_deg"),
                    "pitch_deg": attitude.get("pitch_deg"),
                    "yaw_deg": attitude.get("yaw_deg"),
                })


def observe_telemetry(
    *,
    backend_mode: str,
    backend_enabled: bool,
    endpoint: str,
    duration_s: float,
    rate_hz: float,
    connect_timeout_s: float = 5.0,
    output_json: str | None = None,
    output_jsonl: str | None = None,
    output_csv: str | None = None,
) -> dict[str, Any]:
    """Observe PX4 SITL telemetry without issuing vehicle control commands."""
    validation_errors = validate_observe_parameters(backend_mode=backend_mode, backend_enabled=backend_enabled, endpoint=endpoint, duration_s=duration_s, rate_hz=rate_hz)
    if validation_errors:
        return {"result": "unsupported", "failure_reason": ",".join(validation_errors), "validation_errors": validation_errors, "endpoint": endpoint}

    from pymavlink import mavutil  # type: ignore

    cfg = MavlinkBackendConfig(backend_mode=backend_mode, backend_enabled=backend_enabled, transport_endpoint=endpoint, connect_timeout_ms=int(connect_timeout_s * 1000))
    session = MavlinkBackendSession.from_config(cfg)
    conn = session.connect(timeout_s=max(connect_timeout_s, 0.1), mavutil_module=mavutil)
    snapshot = new_snapshot(endpoint=endpoint, backend_mode=backend_mode)
    samples: list[dict[str, Any]] = []
    start = time.time()
    hb = conn.wait_heartbeat(timeout=max(connect_timeout_s, 0.1))
    if hb is not None:
        apply_mavlink_message(snapshot, hb, flight_mode=getattr(conn, "flightmode", None))
    _request_message_intervals(conn, mavutil, rate_hz=rate_hz)
    period_s = 1.0 / max(rate_hz, 0.1)
    next_sample = time.time()
    deadline = start + max(duration_s, 0.1)
    wanted = ["HEARTBEAT", "LOCAL_POSITION_NED", "ATTITUDE", "GLOBAL_POSITION_INT", "SYS_STATUS", "BATTERY_STATUS", "VFR_HUD", "COMMAND_ACK"]
    while time.time() < deadline:
        msg = conn.recv_match(type=wanted, blocking=True, timeout=min(period_s, 0.25))
        if msg is not None:
            apply_mavlink_message(snapshot, msg, flight_mode=getattr(conn, "flightmode", None))
        if time.time() >= next_sample:
            samples.append(snapshot_to_dict(snapshot))
            next_sample += period_s
    summary = telemetry_summary(
        samples,
        endpoint=endpoint,
        connected=snapshot.connected,
        duration_s=max(time.time() - start, 0.0),
        message_counts=snapshot.source_message_counts,
    )
    summary["result"] = "pass" if snapshot.connected else "fail"
    _write_outputs(samples, summary, output_json=output_json, output_jsonl=output_jsonl, output_csv=output_csv)
    latest_snapshot = snapshot_to_dict(snapshot)
    out = {
        "summary": summary,
        "latest_snapshot": latest_snapshot,
        "telemetry_latest": to_telemetry_latest_view(snapshot),
        "runtime_snapshot_fragment": to_runtime_snapshot_fragment(snapshot),
        "event_envelope": to_event_envelope(
            event_type="telemetry_summary",
            backend=snapshot.backend,
            backend_mode=snapshot.backend_mode,
            endpoint=snapshot.endpoint,
            summary=f"Observed {len(samples)} telemetry samples",
            payload={k: v for k, v in summary.items() if k != "event_envelope"},
        ),
    }
    session.close()
    return out
