#!/usr/bin/env python3
"""Deterministic three-UAV patrol acceptance logic.

This module is a short-lived SITL acceptance validator, not a production
mission controller. Integrated operation must send actions through Runtime.
"""
from __future__ import annotations

import json
import math
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from . import harness
except ImportError:  # Direct script execution adds this directory to sys.path.
    import harness  # type: ignore


DEFAULT_PATROL_PATH = (
    harness.REPO_ROOT
    / "scenarios"
    / "simple_recon_v0_1"
    / "missions"
    / "three_uav_patrol_v0_1.json"
)
POSITION_ONLY_TYPE_MASK = 3576
PX4_CUSTOM_MAIN_MODE_OFFBOARD = 6
TELEMETRY_STALE_AFTER_S = 2.0


class PatrolError(RuntimeError):
    """Raised when standalone patrol validation cannot safely continue."""


@dataclass(frozen=True, slots=True)
class PositionNED:
    x_m: float
    y_m: float
    z_m: float

    @property
    def altitude_m(self) -> float:
        return max(0.0, -self.z_m)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def vehicle_local_to_scene_ned(
    position: PositionNED,
    vehicle_spawn_ned: dict[str, Any],
) -> PositionNED:
    """Transform one PX4-local NED position into the shared scene NED frame."""
    yaw_rad = math.radians(float(vehicle_spawn_ned.get("yaw_deg", 0.0)))
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    return PositionNED(
        x_m=(
            float(vehicle_spawn_ned["x_m"])
            + cos_yaw * position.x_m
            - sin_yaw * position.y_m
        ),
        y_m=(
            float(vehicle_spawn_ned["y_m"])
            + sin_yaw * position.x_m
            + cos_yaw * position.y_m
        ),
        z_m=float(vehicle_spawn_ned["z_m"]) + position.z_m,
    )


def scene_to_vehicle_local_ned(
    position: PositionNED,
    vehicle_spawn_ned: dict[str, Any],
) -> PositionNED:
    """Transform one shared scene NED position into a PX4-local NED frame."""
    yaw_rad = math.radians(float(vehicle_spawn_ned.get("yaw_deg", 0.0)))
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    delta_x = position.x_m - float(vehicle_spawn_ned["x_m"])
    delta_y = position.y_m - float(vehicle_spawn_ned["y_m"])
    return PositionNED(
        x_m=cos_yaw * delta_x + sin_yaw * delta_y,
        y_m=-sin_yaw * delta_x + cos_yaw * delta_y,
        z_m=position.z_m - float(vehicle_spawn_ned["z_m"]),
    )


def framed_position_report(
    *,
    scene_position: PositionNED | None,
    vehicle_local_position: PositionNED | None,
) -> dict[str, Any]:
    return {
        "scene_position": (
            None
            if scene_position is None
            else {"frame": "scene_ned", **scene_position.to_dict()}
        ),
        "vehicle_local_position": (
            None
            if vehicle_local_position is None
            else {"frame": "vehicle_local_ned", **vehicle_local_position.to_dict()}
        ),
    }


def enu_to_ned(*, east_m: float, north_m: float, up_m: float) -> PositionNED:
    return PositionNED(x_m=float(north_m), y_m=float(east_m), z_m=-float(up_m))


def ned_to_enu(position: PositionNED) -> dict[str, float]:
    return {
        "east_m": position.y_m,
        "north_m": position.x_m,
        "up_m": -position.z_m,
    }


def distance_m(left: PositionNED, right: PositionNED) -> float:
    return math.dist(
        (left.x_m, left.y_m, left.z_m),
        (right.x_m, right.y_m, right.z_m),
    )


def waypoint_reached(
    position: PositionNED,
    waypoint: PositionNED,
    *,
    radius_m: float,
) -> tuple[bool, float]:
    error_m = distance_m(position, waypoint)
    return error_m <= float(radius_m), error_m


def minimum_pairwise_distance(
    positions: dict[str, PositionNED],
) -> tuple[float | None, tuple[str, str] | None]:
    minimum: float | None = None
    pair: tuple[str, str] | None = None
    node_ids = sorted(positions)
    for index, left_id in enumerate(node_ids):
        for right_id in node_ids[index + 1 :]:
            candidate = distance_m(positions[left_id], positions[right_id])
            if minimum is None or candidate < minimum:
                minimum = candidate
                pair = (left_id, right_id)
    return minimum, pair


def _position(value: dict[str, Any], *, context: str) -> PositionNED:
    try:
        position = PositionNED(
            x_m=float(value["x_m"]),
            y_m=float(value["y_m"]),
            z_m=float(value["z_m"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PatrolError(f"{context} must contain numeric x_m/y_m/z_m") from exc
    if not all(math.isfinite(value) for value in asdict(position).values()):
        raise PatrolError(f"{context} must contain finite coordinates")
    return position


def _point_conflict_reason(
    point: PositionNED,
    scene: dict[str, Any],
) -> str | None:
    for obstacle in scene.get("obstacles", []):
        center = obstacle["position"]
        size = obstacle["size_m"]
        if all(
            abs(value - float(center[axis])) <= float(size[size_axis]) / 2.0
            for value, axis, size_axis in (
                (point.x_m, "x_m", "x"),
                (point.y_m, "y_m", "y"),
                (point.z_m, "z_m", "z"),
            )
        ):
            return f"obstacle:{obstacle['obstacle_id']}"
    altitude_m = point.altitude_m
    for zone in scene.get("no_fly_zones", []):
        center = zone["center"]
        horizontal_distance = math.dist(
            (point.x_m, point.y_m),
            (float(center["x_m"]), float(center["y_m"])),
        )
        if (
            horizontal_distance < float(zone["radius_m"])
            and float(zone["min_alt_m"])
            <= altitude_m
            <= float(zone["max_alt_m"])
        ):
            return f"no_fly_zone:{zone['zone_id']}"
    return None


def _segment_samples(
    start: PositionNED,
    end: PositionNED,
    *,
    step_m: float = 1.0,
) -> list[PositionNED]:
    steps = max(1, math.ceil(distance_m(start, end) / max(step_m, 0.1)))
    return [
        PositionNED(
            x_m=start.x_m + (end.x_m - start.x_m) * index / steps,
            y_m=start.y_m + (end.y_m - start.y_m) * index / steps,
            z_m=start.z_m + (end.z_m - start.z_m) * index / steps,
        )
        for index in range(1, steps + 1)
    ]


def _validate_sequential_entry_separation(
    plan: dict[str, Any],
    manifest_by_node: dict[str, dict[str, Any]],
) -> None:
    """Prove the ordered corridor-entry phase stays above its threshold."""
    positions = {
        node_id: PositionNED(
            x_m=float(vehicle["spawn_ned"]["x_m"]),
            y_m=float(vehicle["spawn_ned"]["y_m"]),
            z_m=float(vehicle["spawn_ned"]["z_m"]) - float(
                next(
                    row["takeoff_altitude_m"]
                    for row in plan["vehicles"]
                    if str(row["node_id"]) == node_id
                )
            ),
        )
        for node_id, vehicle in manifest_by_node.items()
    }
    threshold_m = float(plan["minimum_separation_m"])
    initial_minimum, initial_pair = minimum_pairwise_distance(positions)
    if initial_minimum is None or initial_minimum < threshold_m:
        raise PatrolError(
            "takeoff separation below configured minimum: "
            f"{initial_pair}={initial_minimum}"
        )

    for row in plan["vehicles"]:
        node_id = str(row["node_id"])
        previous = positions[node_id]
        for index, raw_waypoint in enumerate(row.get("entry_waypoints", [])):
            waypoint = _position(
                raw_waypoint,
                context=f"{node_id} entry waypoint {index + 1}",
            )
            for sample in _segment_samples(previous, waypoint, step_m=0.25):
                for other_node_id, other_position in positions.items():
                    if other_node_id == node_id:
                        continue
                    separation_m = distance_m(sample, other_position)
                    if separation_m < threshold_m:
                        raise PatrolError(
                            "entry separation below configured minimum: "
                            f"{node_id}/{other_node_id}={separation_m:.3f}m"
                        )
            positions[node_id] = waypoint
            previous = waypoint


def load_patrol_plan(
    path: Path,
    *,
    manifest: dict[str, Any],
    scene: dict[str, Any],
) -> dict[str, Any]:
    plan = harness.load_json(path.resolve())
    if plan.get("purpose") != "standalone_acceptance_validator":
        raise PatrolError("patrol purpose must be standalone_acceptance_validator")
    if plan.get("scene_id") != manifest.get("scene_id"):
        raise PatrolError("patrol scene_id does not match harness manifest")
    if plan.get("frame") != "scene_ned":
        raise PatrolError("patrol frame must be scene_ned")
    for field in (
        "arrival_radius_m",
        "arrival_hold_samples",
        "waypoint_timeout_s",
        "minimum_separation_m",
        "corridor_separation_m",
        "arm_stagger_s",
        "takeoff_stagger_s",
    ):
        try:
            value = float(plan[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise PatrolError(f"patrol field must be numeric: {field}") from exc
        if value <= 0:
            raise PatrolError(f"patrol field must be positive: {field}")

    manifest_by_node = {
        str(vehicle["node_id"]): vehicle for vehicle in manifest["vehicles"]
    }
    plan_rows = plan.get("vehicles")
    if not isinstance(plan_rows, list):
        raise PatrolError("patrol vehicles must be a list")
    plan_by_node = {str(row.get("node_id")): row for row in plan_rows}
    if set(plan_by_node) != set(manifest_by_node):
        raise PatrolError("patrol and harness vehicle IDs differ")
    if len(plan_by_node) != len(plan_rows):
        raise PatrolError("patrol node_id values must be unique")

    corridor_y_values: list[float] = []
    for node_id, row in plan_by_node.items():
        entry_waypoints = row.get("entry_waypoints")
        if not isinstance(entry_waypoints, list) or not entry_waypoints:
            raise PatrolError(f"{node_id} requires corridor entry waypoints")
        waypoints = row.get("waypoints")
        if not isinstance(waypoints, list) or len(waypoints) < 3:
            raise PatrolError(f"{node_id} requires at least three waypoints")
        parsed_entries = [
            _position(value, context=f"{node_id} entry waypoint {index + 1}")
            for index, value in enumerate(entry_waypoints)
        ]
        parsed_route = [
            _position(value, context=f"{node_id} waypoint {index + 1}")
            for index, value in enumerate(waypoints)
        ]
        altitude_m = float(row.get("takeoff_altitude_m", 0.0))
        if altitude_m <= 0:
            raise PatrolError(f"{node_id} takeoff_altitude_m must be positive")
        spawn = manifest_by_node[node_id]["spawn_ned"]
        spawn_z_m = float(spawn["z_m"])
        all_waypoints = parsed_entries + parsed_route
        if any(point.z_m >= spawn_z_m for point in all_waypoints):
            raise PatrolError(f"{node_id} waypoint must be above its scene spawn")
        if any(
            abs((spawn_z_m - point.z_m) - altitude_m) > 0.01
            for point in all_waypoints
        ):
            raise PatrolError(f"{node_id} waypoint altitude differs from takeoff altitude")
        corridor_y = {round(point.y_m, 6) for point in parsed_route}
        if len(corridor_y) != 1:
            raise PatrolError(f"{node_id} waypoints must remain on one y corridor")
        corridor_y_m = next(iter(corridor_y))
        if round(parsed_entries[-1].y_m, 6) != corridor_y_m:
            raise PatrolError(f"{node_id} entry must finish on its patrol corridor")
        corridor_y_values.append(corridor_y_m)

        previous = PositionNED(
            x_m=float(spawn["x_m"]),
            y_m=float(spawn["y_m"]),
            z_m=float(spawn["z_m"]) - altitude_m,
        )
        for point in all_waypoints:
            for sample in _segment_samples(previous, point):
                conflict = _point_conflict_reason(sample, scene)
                if conflict:
                    raise PatrolError(
                        f"{node_id} route intersects {conflict} at {sample.to_dict()}"
                    )
            previous = point

    corridor_y_values.sort()
    minimum_corridor_gap = min(
        right - left
        for left, right in zip(corridor_y_values, corridor_y_values[1:])
    )
    if minimum_corridor_gap < float(plan["corridor_separation_m"]):
        raise PatrolError("patrol corridor separation is below configured minimum")
    _validate_sequential_entry_separation(plan, manifest_by_node)
    return plan


def endpoint_available(endpoint: str) -> bool:
    host, port = harness.parse_udpin_endpoint(endpoint)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def require_standalone_endpoints(
    manifest: dict[str, Any],
    *,
    availability_probe: Callable[[str], bool] = endpoint_available,
) -> None:
    conflicts = [
        {
            "node_id": vehicle["node_id"],
            "endpoint": vehicle["command_endpoint"],
        }
        for vehicle in manifest["vehicles"]
        if not availability_probe(str(vehicle["command_endpoint"]))
    ]
    if conflicts:
        raise PatrolError(
            "runtime_session_active:endpoint_in_use:"
            + json.dumps(conflicts, sort_keys=True)
        )


def ack_accepted(ack: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(ack, dict)
        and not ack.get("timeout", False)
        and int(ack.get("result", -1)) == 0
    )


class MavlinkPatrolController:
    """One short-lived standalone controller bound to one MAVLink session."""

    def __init__(self, vehicle: dict[str, Any], session: Any) -> None:
        self.vehicle = vehicle
        self.session = session
        self.node_id = str(vehicle["node_id"])
        self.vehicle_spawn_ned = dict(vehicle["spawn_ned"])
        self.spawn_scene_position = _position(
            self.vehicle_spawn_ned,
            context=f"{self.node_id} scene spawn",
        )
        self._condition = threading.Condition(threading.RLock())
        self._scene_position: PositionNED | None = None
        self._vehicle_local_position: PositionNED | None = None
        self._position_sequence = 0
        self._armed: bool | None = None
        self._custom_mode: int | None = None
        self._max_altitude_m = 0.0
        self._last_telemetry_at: float | None = None
        self._subscription: int | None = None
        self._setpoint: PositionNED | None = None
        self._setpoint_stop = threading.Event()
        self._setpoint_thread: threading.Thread | None = None
        self._setpoint_error: str | None = None
        self.connected = False

    @property
    def max_altitude_m(self) -> float:
        with self._condition:
            return self._max_altitude_m

    @property
    def armed(self) -> bool | None:
        with self._condition:
            return self._armed

    def position(self) -> PositionNED | None:
        with self._condition:
            return self._scene_position

    def vehicle_local_position(self) -> PositionNED | None:
        with self._condition:
            return self._vehicle_local_position

    def _positions(self) -> tuple[PositionNED | None, PositionNED | None]:
        with self._condition:
            return self._scene_position, self._vehicle_local_position

    def _observe(self, message: Any) -> None:
        message_type = getattr(message, "get_type", lambda: "")()
        with self._condition:
            if message_type == "LOCAL_POSITION_NED":
                self._vehicle_local_position = PositionNED(
                    x_m=float(getattr(message, "x", 0.0)),
                    y_m=float(getattr(message, "y", 0.0)),
                    z_m=float(getattr(message, "z", 0.0)),
                )
                self._scene_position = vehicle_local_to_scene_ned(
                    self._vehicle_local_position,
                    self.vehicle_spawn_ned,
                )
                self._position_sequence += 1
                self._max_altitude_m = max(
                    self._max_altitude_m,
                    self._vehicle_local_position.altitude_m,
                )
                self._last_telemetry_at = time.monotonic()
            elif message_type == "HEARTBEAT":
                armed_flag = self.session._mavlink_const(
                    "MAV_MODE_FLAG_SAFETY_ARMED", 128
                )
                self._armed = bool(int(getattr(message, "base_mode", 0)) & armed_flag)
                self._custom_mode = int(getattr(message, "custom_mode", 0))
            self._condition.notify_all()

    def connect(self, *, timeout_s: float) -> dict[str, Any]:
        self.session.connect(timeout_s=timeout_s)
        if self.session.target_system != int(self.vehicle["system_id"]):
            raise PatrolError(f"{self.node_id} system_id mismatch")
        if self.session.target_component != int(self.vehicle.get("component_id", 1)):
            raise PatrolError(f"{self.node_id} component_id mismatch")
        self.session.start_gcs_heartbeat()
        self._subscription = self.session.subscribe(self._observe)
        stream_ack = self.session.request_local_position_stream(
            rate_hz=10.0,
            timeout_s=timeout_s,
        )
        if not ack_accepted(stream_ack):
            raise PatrolError(f"{self.node_id} LOCAL_POSITION_NED stream request failed")
        self.connected = True
        return stream_ack

    def arm(self, *, timeout_s: float) -> dict[str, Any]:
        ack = self.session.arm(timeout_s=timeout_s)
        if not ack_accepted(ack):
            raise PatrolError(f"{self.node_id} ARM ACK failed")
        return ack

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict[str, Any]:
        ack = self.session.takeoff(altitude_m=altitude_m, timeout_s=timeout_s)
        if not ack_accepted(ack):
            raise PatrolError(f"{self.node_id} TAKEOFF ACK failed")
        return ack

    def wait_for_altitude(
        self,
        *,
        threshold_m: float,
        timeout_s: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while time.monotonic() < deadline:
                if (
                    self._vehicle_local_position is not None
                    and self._vehicle_local_position.altitude_m >= threshold_m
                ):
                    return {
                        "threshold_reached": True,
                        "threshold_m": threshold_m,
                        **framed_position_report(
                            scene_position=self._scene_position,
                            vehicle_local_position=self._vehicle_local_position,
                        ),
                        "max_altitude_m": round(self._max_altitude_m, 3),
                    }
                self._condition.wait(timeout=max(min(deadline - time.monotonic(), 0.5), 0.01))
        scene_position, vehicle_local_position = self._positions()
        return {
            "threshold_reached": False,
            "threshold_m": threshold_m,
            **framed_position_report(
                scene_position=scene_position,
                vehicle_local_position=vehicle_local_position,
            ),
            "max_altitude_m": round(self.max_altitude_m, 3),
        }

    def _send_setpoint(self, scene_target: PositionNED) -> None:
        vehicle_local_target = scene_to_vehicle_local_ned(
            scene_target,
            self.vehicle_spawn_ned,
        )
        mavlink = getattr(self.session._mavutil, "mavlink", None)
        frame = int(getattr(mavlink, "MAV_FRAME_LOCAL_NED", 1))
        with self.session.tx_lock:
            connection = self.session.connection
            if connection is None or not self.session.connected:
                raise PatrolError(f"{self.node_id} MAVLink connection is closed")
            connection.mav.set_position_target_local_ned_send(
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                self.session.target_system,
                self.session.target_component,
                frame,
                POSITION_ONLY_TYPE_MASK,
                vehicle_local_target.x_m,
                vehicle_local_target.y_m,
                vehicle_local_target.z_m,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )

    def _stream_setpoints(self) -> None:
        while not self._setpoint_stop.wait(0.1):
            with self._condition:
                target = self._setpoint
            if target is None:
                continue
            try:
                self._send_setpoint(target)
            except Exception as exc:
                self._setpoint_error = f"{type(exc).__name__}: {exc}"
                self._setpoint_stop.set()
                return

    def start_offboard(
        self,
        scene_target: PositionNED,
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        with self._condition:
            self._setpoint = scene_target
        self._setpoint_stop.clear()
        self._send_setpoint(scene_target)
        self._setpoint_thread = threading.Thread(
            target=self._stream_setpoints,
            name=f"patrol-setpoint-{self.node_id}",
            daemon=True,
        )
        self._setpoint_thread.start()
        time.sleep(1.0)
        connection = self.session.connection
        if connection is None:
            raise PatrolError(f"{self.node_id} connection closed before OFFBOARD")
        connection.set_mode("OFFBOARD")
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while time.monotonic() < deadline:
                main_mode = (
                    None
                    if self._custom_mode is None
                    else (self._custom_mode >> 16) & 0xFF
                )
                if main_mode == PX4_CUSTOM_MAIN_MODE_OFFBOARD:
                    vehicle_local_target = scene_to_vehicle_local_ned(
                        scene_target,
                        self.vehicle_spawn_ned,
                    )
                    return {
                        "offboard_observed": True,
                        "custom_main_mode": main_mode,
                        "scene_target": {
                            "frame": "scene_ned",
                            **scene_target.to_dict(),
                        },
                        "vehicle_local_target": {
                            "frame": "vehicle_local_ned",
                            **vehicle_local_target.to_dict(),
                        },
                    }
                if self._setpoint_error:
                    break
                self._condition.wait(timeout=max(min(deadline - time.monotonic(), 0.25), 0.01))
        raise PatrolError(
            f"{self.node_id} OFFBOARD not observed: {self._setpoint_error or 'timeout'}"
        )

    def goto(
        self,
        scene_waypoint: PositionNED,
        *,
        radius_m: float,
        hold_samples: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        with self._condition:
            self._setpoint = scene_waypoint
        vehicle_local_target = scene_to_vehicle_local_ned(
            scene_waypoint,
            self.vehicle_spawn_ned,
        )
        deadline = time.monotonic() + timeout_s
        consecutive = 0
        seen_sequence = -1
        best_error_m: float | None = None
        final_error_m: float | None = None
        failure_reason: str | None = None
        while time.monotonic() < deadline:
            if self._setpoint_error:
                failure_reason = self._setpoint_error
                break
            with self._condition:
                scene_position = self._scene_position
                vehicle_local_position = self._vehicle_local_position
                sequence = self._position_sequence
                last_telemetry_at = self._last_telemetry_at
            if (
                last_telemetry_at is None
                or time.monotonic() - last_telemetry_at > TELEMETRY_STALE_AFTER_S
            ):
                failure_reason = "telemetry_stale"
                break
            if scene_position is not None and sequence > seen_sequence:
                seen_sequence = sequence
                reached, final_error_m = waypoint_reached(
                    scene_position,
                    scene_waypoint,
                    radius_m=radius_m,
                )
                best_error_m = (
                    final_error_m
                    if best_error_m is None
                    else min(best_error_m, final_error_m)
                )
                consecutive = consecutive + 1 if reached else 0
                if consecutive >= hold_samples:
                    return {
                        "reached": True,
                        "frame": "scene_ned",
                        "scene_target": {
                            "frame": "scene_ned",
                            **scene_waypoint.to_dict(),
                        },
                        "vehicle_local_target": {
                            "frame": "vehicle_local_ned",
                            **vehicle_local_target.to_dict(),
                        },
                        **framed_position_report(
                            scene_position=scene_position,
                            vehicle_local_position=vehicle_local_position,
                        ),
                        "arrival_error_m": round(final_error_m, 3),
                        "best_error_m": round(best_error_m, 3),
                        "hold_samples": consecutive,
                    }
            time.sleep(0.1)
        scene_position, vehicle_local_position = self._positions()
        return {
            "reached": False,
            "frame": "scene_ned",
            "scene_target": {
                "frame": "scene_ned",
                **scene_waypoint.to_dict(),
            },
            "vehicle_local_target": {
                "frame": "vehicle_local_ned",
                **vehicle_local_target.to_dict(),
            },
            **framed_position_report(
                scene_position=scene_position,
                vehicle_local_position=vehicle_local_position,
            ),
            "arrival_error_m": (
                None if final_error_m is None else round(final_error_m, 3)
            ),
            "best_error_m": None if best_error_m is None else round(best_error_m, 3),
            "hold_samples": consecutive,
            "reason": failure_reason or "waypoint_timeout",
        }

    def land(self, *, timeout_s: float) -> dict[str, Any]:
        ack = self.session.land(timeout_s=timeout_s)
        if ack_accepted(ack):
            self.stop_setpoints()
        else:
            raise PatrolError(f"{self.node_id} LAND ACK failed")
        return ack

    def wait_landed_disarmed(self, *, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        low_samples = 0
        seen_sequence = -1
        reason = "landing_timeout"
        with self._condition:
            while time.monotonic() < deadline:
                if (
                    self._last_telemetry_at is None
                    or time.monotonic() - self._last_telemetry_at
                    > TELEMETRY_STALE_AFTER_S
                ):
                    reason = "telemetry_stale"
                    break
                if self._position_sequence > seen_sequence:
                    seen_sequence = self._position_sequence
                    if (
                        self._vehicle_local_position is not None
                        and self._vehicle_local_position.altitude_m <= 0.3
                    ):
                        low_samples += 1
                    else:
                        low_samples = 0
                if low_samples >= 3 and self._armed is False:
                    return {
                        "landed": True,
                        "disarmed": True,
                        **framed_position_report(
                            scene_position=self._scene_position,
                            vehicle_local_position=self._vehicle_local_position,
                        ),
                    }
                self._condition.wait(timeout=max(min(deadline - time.monotonic(), 0.5), 0.01))
        scene_position, vehicle_local_position = self._positions()
        return {
            "landed": False,
            "disarmed": self._armed is False,
            **framed_position_report(
                scene_position=scene_position,
                vehicle_local_position=vehicle_local_position,
            ),
            "reason": reason,
        }

    def stop_setpoints(self) -> None:
        self._setpoint_stop.set()
        thread = self._setpoint_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._setpoint_thread = None

    def close(self) -> None:
        self.stop_setpoints()
        if self._subscription is not None:
            self.session.unsubscribe(self._subscription)
            self._subscription = None
        self.session.close()
        self.connected = False


def run_patrol(
    plan: dict[str, Any],
    controllers: list[MavlinkPatrolController],
    *,
    command_timeout_s: float = 10.0,
    landing_timeout_s: float = 45.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute and report one deterministic standalone three-UAV patrol."""
    by_node = {controller.node_id: controller for controller in controllers}
    plan_rows = list(plan["vehicles"])
    if set(by_node) != {str(row["node_id"]) for row in plan_rows}:
        raise PatrolError("controller and patrol node IDs differ")
    started_at = harness.utc_now()
    results: dict[str, dict[str, Any]] = {
        str(row["node_id"]): {
            "node_id": row["node_id"],
            "corridor": row["corridor"],
            "task_frame": "scene_ned",
            "px4_frame": "vehicle_local_ned",
            "entry_waypoints": [],
            "waypoints": [],
        }
        for row in plan_rows
    }
    stop_monitor = threading.Event()
    separation: dict[str, Any] = {
        "minimum_distance_m": None,
        "pair": None,
        "sample_count": 0,
    }

    def monitor_separation() -> None:
        while not stop_monitor.wait(0.1):
            positions = {
                node_id: position
                for node_id, controller in by_node.items()
                if (position := controller.position()) is not None
            }
            candidate, pair = minimum_pairwise_distance(positions)
            if candidate is None:
                continue
            separation["sample_count"] += 1
            current = separation["minimum_distance_m"]
            if current is None or candidate < current:
                separation["minimum_distance_m"] = candidate
                separation["pair"] = list(pair) if pair else None

    monitor_thread = threading.Thread(
        target=monitor_separation,
        name="three-uav-separation-monitor",
        daemon=True,
    )
    monitor_thread.start()
    error: str | None = None
    try:
        for row in plan_rows:
            node_id = str(row["node_id"])
            results[node_id]["stream_ack"] = by_node[node_id].connect(
                timeout_s=command_timeout_s
            )

        for index, row in enumerate(plan_rows):
            node_id = str(row["node_id"])
            results[node_id]["arm_ack"] = by_node[node_id].arm(
                timeout_s=command_timeout_s
            )
            if index < len(plan_rows) - 1:
                sleep(float(plan["arm_stagger_s"]))

        # Send all takeoff commands within PX4's preflight auto-disarm window,
        # then observe their altitude thresholds concurrently. Waiting for one
        # climb before commanding the next can leave the final vehicle armed on
        # the ground long enough for PX4 to disarm it automatically.
        for index, row in enumerate(plan_rows):
            node_id = str(row["node_id"])
            altitude_m = float(row["takeoff_altitude_m"])
            controller = by_node[node_id]
            results[node_id]["takeoff_ack"] = controller.takeoff(
                altitude_m=altitude_m,
                timeout_s=command_timeout_s,
            )
            if index < len(plan_rows) - 1:
                sleep(float(plan["takeoff_stagger_s"]))

        def observe_takeoff(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            node_id = str(row["node_id"])
            altitude_m = float(row["takeoff_altitude_m"])
            observation = by_node[node_id].wait_for_altitude(
                threshold_m=altitude_m * 0.85,
                timeout_s=max(command_timeout_s, 30.0),
            )
            return node_id, observation

        with ThreadPoolExecutor(max_workers=len(plan_rows)) as executor:
            takeoff_futures = [
                executor.submit(observe_takeoff, row) for row in plan_rows
            ]
            for future in takeoff_futures:
                node_id, observation = future.result()
                results[node_id]["takeoff_observation"] = observation
                if not observation["threshold_reached"]:
                    raise PatrolError(
                        f"{node_id} takeoff altitude threshold not reached"
                    )

        for row in plan_rows:
            node_id = str(row["node_id"])
            controller = by_node[node_id]
            current = controller.position()
            if current is None:
                raise PatrolError(f"{node_id} has no LOCAL_POSITION_NED")
            hold_target = PositionNED(
                x_m=current.x_m,
                y_m=current.y_m,
                z_m=(
                    controller.spawn_scene_position.z_m
                    - float(row["takeoff_altitude_m"])
                ),
            )
            results[node_id]["offboard"] = controller.start_offboard(
                hold_target,
                timeout_s=command_timeout_s,
            )

        # Enter separated corridors one vehicle at a time while all other
        # controllers continue streaming their current hold setpoints.
        for row in plan_rows:
            node_id = str(row["node_id"])
            controller = by_node[node_id]
            for index, raw_waypoint in enumerate(row["entry_waypoints"]):
                waypoint = _position(
                    raw_waypoint,
                    context=f"{node_id} entry waypoint {index + 1}",
                )
                outcome = controller.goto(
                    waypoint,
                    radius_m=float(plan["arrival_radius_m"]),
                    hold_samples=int(plan["arrival_hold_samples"]),
                    timeout_s=float(plan["waypoint_timeout_s"]),
                )
                outcome["index"] = index + 1
                results[node_id]["entry_waypoints"].append(outcome)
                if not outcome["reached"]:
                    raise PatrolError(
                        f"{node_id} entry waypoint {index + 1} timeout"
                    )

        def execute_route(row: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            node_id = str(row["node_id"])
            controller = by_node[node_id]
            waypoint_results: list[dict[str, Any]] = []
            for index, raw_waypoint in enumerate(row["waypoints"]):
                waypoint = _position(
                    raw_waypoint,
                    context=f"{node_id} waypoint {index + 1}",
                )
                outcome = controller.goto(
                    waypoint,
                    radius_m=float(plan["arrival_radius_m"]),
                    hold_samples=int(plan["arrival_hold_samples"]),
                    timeout_s=float(plan["waypoint_timeout_s"]),
                )
                outcome["index"] = index + 1
                waypoint_results.append(outcome)
                if not outcome["reached"]:
                    raise PatrolError(f"{node_id} waypoint {index + 1} timeout")
            return node_id, waypoint_results

        with ThreadPoolExecutor(max_workers=len(plan_rows)) as executor:
            futures = [executor.submit(execute_route, row) for row in plan_rows]
            for future in futures:
                node_id, waypoint_results = future.result()
                results[node_id]["waypoints"] = waypoint_results

        for row in plan_rows:
            node_id = str(row["node_id"])
            controller = by_node[node_id]
            results[node_id]["land_ack"] = controller.land(
                timeout_s=command_timeout_s
            )
            landing = controller.wait_landed_disarmed(timeout_s=landing_timeout_s)
            results[node_id]["landing_observation"] = landing
            if not landing["landed"] or not landing["disarmed"]:
                raise PatrolError(f"{node_id} landing/disarm not observed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        for row in plan_rows:
            node_id = str(row["node_id"])
            controller = by_node[node_id]
            if not controller.connected:
                continue
            vehicle_local_position = controller.vehicle_local_position()
            if (
                getattr(controller, "armed", None) is False
                and vehicle_local_position is not None
                and vehicle_local_position.altitude_m <= 0.3
            ):
                results[node_id]["recovery"] = "already_grounded_disarmed"
                continue
            try:
                results[node_id]["recovery_land_ack"] = controller.land(
                    timeout_s=command_timeout_s
                )
                results[node_id]["recovery_landing_observation"] = (
                    controller.wait_landed_disarmed(timeout_s=landing_timeout_s)
                )
            except Exception as recovery_exc:
                results[node_id]["recovery_error"] = (
                    f"{type(recovery_exc).__name__}: {recovery_exc}"
                )
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout=2.0)
        for controller in controllers:
            results[controller.node_id]["max_altitude_m"] = round(
                controller.max_altitude_m,
                3,
            )
            results[controller.node_id]["final_position"] = framed_position_report(
                scene_position=controller.position(),
                vehicle_local_position=controller.vehicle_local_position(),
            )
            controller.close()

    minimum_distance = separation["minimum_distance_m"]
    if minimum_distance is not None:
        separation["minimum_distance_m"] = round(float(minimum_distance), 3)
    separation["threshold_m"] = float(plan["minimum_separation_m"])
    separation["threshold_met"] = bool(
        minimum_distance is not None
        and float(minimum_distance) >= float(plan["minimum_separation_m"])
    )
    if error is None and not separation["threshold_met"]:
        error = "PatrolError: minimum_separation_below_threshold"
    status = "PASS" if error is None else "FAIL"
    return {
        "status": status,
        "scope": "SITL_STANDALONE_ACCEPTANCE",
        "mission_id": plan["mission_id"],
        "scene_id": plan["scene_id"],
        "frame": "scene_ned",
        "frames": {
            "task_and_safety": "scene_ned",
            "px4_setpoint_and_telemetry": "vehicle_local_ned",
        },
        "started_at": started_at,
        "completed_at": harness.utc_now(),
        "vehicles": [results[str(row["node_id"])] for row in plan_rows],
        "separation": separation,
        "error": error,
    }
