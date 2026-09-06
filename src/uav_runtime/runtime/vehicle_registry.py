"""VehicleRegistry v0.1: node-keyed ownership of per-vehicle runtime resources.

``node_id`` is the Runtime identity because endpoint and MAVLink system_id are
deployment details that can change.  Each handle owns an independent command
session, lock, telemetry snapshot, and lifecycle state so one failed PX4 cannot
invalidate or block unrelated nodes.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_telemetry import Px4TelemetrySnapshot, new_snapshot, snapshot_to_dict
from uav_runtime.scenario.scene_schema import SceneValidationError, load_and_validate_scene


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class VehicleRegistryError(LookupError):
    """Structured registry failure suitable for HTTP/API translation."""

    def __init__(self, code: str, *, node_id: str | None = None, status: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.node_id = node_id
        self.status = status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.code, "field": None, "node_id": self.node_id, "details": self.details}


@dataclass(slots=True)
class VehicleConfig:
    """Stable node identity and deployment-specific PX4 connection mapping."""

    node_id: str
    backend: str = "px4_sitl"
    backend_mode: str = "sitl"
    endpoint: str = ""
    telemetry_endpoint: str = ""
    system_id: int = 1
    component_id: int | None = 1
    enabled: bool = True
    scene_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    connect_timeout_ms: int = 3000
    command_timeout_ms: int = 10000
    observe_timeout_ms: int = 25000

    def to_mavlink_config(self) -> MavlinkBackendConfig:
        return MavlinkBackendConfig(
            backend_mode=self.backend_mode,
            backend_enabled=self.enabled,
            transport_endpoint=self.endpoint,
            target_system=self.system_id,
            target_component=self.component_id,
            connect_timeout_ms=self.connect_timeout_ms,
            command_timeout_ms=self.command_timeout_ms,
            observe_timeout_ms=self.observe_timeout_ms,
        )


@dataclass(slots=True)
class VehicleRuntimeState:
    """Per-node connection/action/fault state; offline is distinct from removed."""

    node_id: str
    connection_status: str = "not_started"
    connected: bool = False
    stale: bool = True
    last_heartbeat_at: str | None = None
    last_telemetry_at: str | None = None
    last_action_at: str | None = None
    active_action: str | None = None
    active_action_id: str | None = None
    fault_state: str | None = None
    last_error: str | None = None
    telemetry_freshness_ms: int | None = None
    collector_running: bool = False


@dataclass(slots=True)
class VehicleHandle:
    """Own all mutable resources for exactly one Runtime node."""

    config: VehicleConfig
    session: MavlinkBackendSession
    telemetry: Px4TelemetrySnapshot
    runtime_state: VehicleRuntimeState
    command_lock: threading.RLock = field(default_factory=threading.RLock)
    action_lock: threading.RLock = field(default_factory=threading.RLock)
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    action_cancel_event: threading.Event | None = None
    collector: Any = None
    telemetry_received_at: float | None = None
    start_in_progress: bool = False


class VehicleRegistry:
    """Thread-safe node registry and lifecycle owner.

    The registry never selects ``list_vehicles()[0]``. Legacy requests can use a
    node only when ``default_node_id`` is explicitly configured.
    """

    def __init__(
        self,
        *,
        scene_id: str = "",
        default_node_id: str | None = None,
        stale_after_ms: int = 2000,
        session_factory: Callable[[MavlinkBackendConfig], MavlinkBackendSession] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.scene_id = scene_id
        self.default_node_id = default_node_id
        self.stale_after_ms = stale_after_ms
        self._session_factory = session_factory or MavlinkBackendSession.from_config
        self._clock = clock
        self._lock = threading.RLock()
        self._vehicles: dict[str, VehicleHandle] = {}

    @classmethod
    def from_json(cls, path: str | Path, **kwargs: Any) -> "VehicleRegistry":
        config_path = Path(path)
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if any("command_endpoint" in row for row in data.get("vehicles", [])):
            # The simulation manifest is the deployment source of truth.  Convert
            # its transport binding in memory instead of maintaining a second
            # hand-authored Runtime mapping.
            data = {
                "scene_id": data.get("scene_id"),
                "scene_path": data.get("scene_path"),
                "default_node_id": data.get("default_node_id", "UAV-01"),
                "vehicles": [
                    {
                        "node_id": row["node_id"],
                        "backend": "px4_sitl",
                        "backend_mode": "sitl",
                        "endpoint": row["command_endpoint"],
                        "telemetry_endpoint": row["telemetry_endpoint"],
                        "system_id": int(row["system_id"]),
                        "component_id": int(row.get("component_id", 1)),
                        "enabled": bool(row.get("enabled", True)),
                        "scene_id": data.get("scene_id", ""),
                        "metadata": {
                            "px4_instance": int(row["px4_instance"]),
                            "gazebo_model_name": row["gazebo_model_name"],
                            "runtime_dir": row["runtime_dir"],
                            "deployment_source": str(config_path),
                        },
                    }
                    for row in data.get("vehicles", [])
                ],
            }
        scene_id = str(data.get("scene_id") or "")
        scene_poses: dict[str, dict[str, Any]] = {}
        if scene_id:
            if data.get("scene_path"):
                repo_root = next(
                    (parent for parent in config_path.resolve().parents if (parent / "pyproject.toml").exists()),
                    config_path.resolve().parent,
                )
                scene_path = repo_root / str(data["scene_path"])
            else:
                scene_path = config_path.resolve().parents[1] / "scenarios" / scene_id / "scene.json"
            if not scene_path.exists():
                raise VehicleRegistryError("authoritative_scene_not_found", status=409, details={"scene_id": scene_id, "scene_path": str(scene_path)})
            try:
                scene, _ = load_and_validate_scene(scene_path)
            except SceneValidationError as exc:
                raise VehicleRegistryError(
                    "authoritative_scene_invalid",
                    status=409,
                    details={"scene_id": scene_id, "reason": str(exc)},
                ) from exc
            scene_rows = list(scene.get("vehicles") or [])
            scene_ids = [str(row.get("node_id") or "") for row in scene_rows]
            if len(scene_ids) != len(set(scene_ids)):
                raise VehicleRegistryError("duplicate_scene_node_id", status=409)
            missing_pose = [node for node, row in zip(scene_ids, scene_rows) if not isinstance(row.get("initial_pose"), dict)]
            if missing_pose:
                raise VehicleRegistryError("scenario_initial_pose_required", status=409, details={"node_ids": missing_pose})
            scene_poses = {node: dict(row["initial_pose"]) for node, row in zip(scene_ids, scene_rows) if node}
            config_ids = {str(row.get("node_id")) for row in data.get("vehicles", []) if row.get("node_id")}
            if config_ids != set(scene_poses):
                raise VehicleRegistryError("scene_vehicle_mapping_mismatch", status=409, details={
                    "missing_from_scene": sorted(config_ids - set(scene_poses)),
                    "missing_from_runtime_config": sorted(set(scene_poses) - config_ids),
                })
        registry = cls(
            scene_id=scene_id,
            default_node_id=data.get("default_node_id"),
            **kwargs,
        )
        for row in data.get("vehicles", []):
            row = dict(row)
            metadata = dict(row.get("metadata") or {})
            if row.get("node_id") in scene_poses:
                metadata["initial_pose"] = scene_poses[str(row["node_id"])]
            row["metadata"] = metadata
            registry.register_vehicle(VehicleConfig(**row))
        return registry

    def register_vehicle(self, config: VehicleConfig) -> VehicleHandle:
        if not config.node_id:
            raise VehicleRegistryError("node_id_required")
        self._validate_mavlink_id(config.system_id, field="system_id", node_id=config.node_id)
        self._validate_mavlink_id(config.component_id, field="component_id", node_id=config.node_id, allow_none=True)
        if config.telemetry_endpoint and config.telemetry_endpoint != config.endpoint:
            raise VehicleRegistryError(
                "shared_transport_endpoint_mismatch",
                node_id=config.node_id,
                status=409,
                details={
                    "command_endpoint": config.endpoint,
                    "telemetry_endpoint": config.telemetry_endpoint,
                },
            )
        with self._lock:
            if config.node_id in self._vehicles:
                raise VehicleRegistryError("duplicate_node_id", node_id=config.node_id, status=409)
            if any(handle.config.system_id == config.system_id for handle in self._vehicles.values()):
                raise VehicleRegistryError("duplicate_system_id", node_id=config.node_id, status=409)
            # One node may name the same endpoint for both roles because its
            # shared session owns one socket.  No endpoint may belong to two nodes.
            owners = {
                endpoint: (handle.config.node_id, role)
                for handle in self._vehicles.values()
                for endpoint, role in ((handle.config.endpoint, "command"), (handle.config.telemetry_endpoint, "telemetry"))
                if endpoint
            }
            requested: dict[str, str] = {}
            for endpoint, role in ((config.endpoint, "command"), (config.telemetry_endpoint, "telemetry")):
                if not endpoint:
                    continue
                existing = owners.get(endpoint)
                if existing:
                    conflicting_node, existing_role = existing
                    raise VehicleRegistryError("endpoint_role_conflict", node_id=config.node_id, status=409, details={
                        "endpoint": endpoint, "conflicting_node_id": conflicting_node,
                        "requested_role": role, "existing_role": existing_role,
                    })
                requested.setdefault(endpoint, role)
            session = self._session_factory(config.to_mavlink_config())
            endpoint = config.telemetry_endpoint or config.endpoint
            handle = VehicleHandle(
                config=config,
                session=session,
                telemetry=new_snapshot(endpoint=endpoint, backend_mode=config.backend_mode),
                runtime_state=VehicleRuntimeState(node_id=config.node_id),
            )
            self._vehicles[config.node_id] = handle
            return handle

    def unregister_vehicle(self, node_id: str) -> VehicleHandle:
        with self._lock:
            handle = self._vehicles.pop(node_id, None)
        if handle is None:
            raise VehicleRegistryError("unknown_node", node_id=node_id, status=404)
        self._stop_handle(handle)
        return handle

    def get_vehicle(self, node_id: str) -> VehicleHandle:
        with self._lock:
            handle = self._vehicles.get(node_id)
        if handle is None:
            raise VehicleRegistryError("unknown_node", node_id=node_id, status=404)
        return handle

    def has_vehicle(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self._vehicles

    def list_vehicles(self) -> list[VehicleHandle]:
        with self._lock:
            return list(self._vehicles.values())

    def resolve_vehicle(
        self,
        node_id: str | None,
        *,
        requested_endpoint: str | None = None,
        requested_system_id: int | None = None,
        requested_component_id: int | None = None,
        require_online: bool = False,
    ) -> tuple[VehicleHandle, str]:
        selection = "explicit"
        resolved = node_id
        if not resolved:
            resolved = self.default_node_id
            selection = "default"
        if not resolved:
            raise VehicleRegistryError("ambiguous_node_request")
        handle = self.get_vehicle(resolved)
        if requested_endpoint and requested_endpoint != handle.config.endpoint:
            raise VehicleRegistryError("node_endpoint_conflict", node_id=resolved, status=409)
        if requested_system_id is not None and requested_system_id != handle.config.system_id:
            raise VehicleRegistryError("node_system_id_conflict", node_id=resolved, status=409)
        if requested_component_id is not None and requested_component_id != handle.config.component_id:
            raise VehicleRegistryError("node_component_id_conflict", node_id=resolved, status=409)
        if not handle.config.enabled:
            raise VehicleRegistryError("node_disabled", node_id=resolved, status=409)
        if handle.config.backend != "px4_sitl":
            raise VehicleRegistryError("unsupported_node_backend", node_id=resolved, status=409)
        self.refresh_state(handle)
        # A never-started node may be connected on demand by a command route.
        # A node explicitly marked offline must not silently receive commands.
        with handle.state_lock:
            connection_status = handle.runtime_state.connection_status
        if require_online and connection_status == "offline":
            raise VehicleRegistryError("node_offline", node_id=resolved, status=503)
        return handle, selection

    def start_vehicle(self, node_id: str) -> None:
        handle = self.get_vehicle(node_id)
        if not handle.config.enabled:
            return
        endpoint = handle.config.endpoint
        if not endpoint:
            self.mark_offline(node_id, reason="transport_endpoint_not_configured")
            return
        from uav_runtime.adapters.px4_telemetry_collector import Px4TelemetryCollector

        with handle.state_lock:
            if handle.start_in_progress:
                return
            if handle.collector is not None:
                if (
                    handle.session.connected
                    and handle.session.receive_thread_alive()
                    and handle.session.heartbeat_thread_alive()
                ):
                    return
                stale_collector = handle.collector
                handle.collector = None
                try:
                    stale_collector.stop()
                finally:
                    with handle.command_lock:
                        handle.session.close()
            handle.start_in_progress = True
            handle.runtime_state.connection_status = "connecting"
            handle.runtime_state.last_error = None
            collector = None
            try:
                with handle.command_lock:
                    handle.session.connect(
                        timeout_s=max(handle.config.connect_timeout_ms / 1000.0, 0.1)
                    )
                collector = Px4TelemetryCollector(
                    self,
                    session=handle.session,
                    node_id=node_id,
                    endpoint=endpoint,
                )
                handle.collector = collector
                collector.start()
                handle.session.start_gcs_heartbeat(
                    thread_name=f"px4-gcs-heartbeat-{node_id}"
                )
                if not handle.session.heartbeat_thread_alive():
                    raise RuntimeError("gcs_heartbeat_not_running")
                heartbeat_at = _utc_now()
                handle.telemetry.connected = True
                handle.telemetry.system_id = handle.session.target_system
                handle.telemetry.component_id = handle.session.target_component
                handle.telemetry.timestamp = heartbeat_at
                handle.telemetry_received_at = self._clock()
                handle.runtime_state.connected = True
                handle.runtime_state.stale = False
                handle.runtime_state.connection_status = "connected"
                handle.runtime_state.last_heartbeat_at = heartbeat_at
            except Exception as exc:
                handle.collector = None
                if collector is not None:
                    try:
                        collector.stop()
                    except Exception:
                        # Preserve the lifecycle startup failure while close()
                        # remains the authoritative transport cleanup.
                        pass
                with handle.command_lock:
                    handle.session.close()
                handle.runtime_state.connected = False
                handle.runtime_state.stale = True
                handle.runtime_state.connection_status = "offline"
                handle.runtime_state.last_error = f"vehicle_start_failed:{type(exc).__name__}:{exc}"
            finally:
                handle.start_in_progress = False

    def stop_vehicle(self, node_id: str) -> None:
        self._stop_handle(self.get_vehicle(node_id))

    def start_all(self) -> None:
        for handle in self.list_vehicles():
            self.start_vehicle(handle.config.node_id)

    def stop_all(self) -> None:
        for handle in self.list_vehicles():
            self._stop_handle(handle)

    def _stop_handle(self, handle: VehicleHandle) -> None:
        # Never hold the registry membership lock across thread joins or I/O.
        # Each handle protects its own pointer/state, keeping nodes independent.
        with handle.state_lock:
            collector = handle.collector
            handle.collector = None
        if collector is not None:
            collector.stop()
        # Closing the command transport is part of the selected node's command
        # sequence. It must not race an ACK wait, but it also must not block any
        # unrelated vehicle because each handle owns an independent lock.
        with handle.command_lock:
            # Session.close() is the selected node's single heartbeat/RX/
            # connection lifecycle terminator.
            handle.session.close()
        with handle.state_lock:
            handle.runtime_state.active_action = None
            handle.runtime_state.active_action_id = None
            handle.action_cancel_event = None
            handle.runtime_state.connected = False
            handle.runtime_state.stale = True
            handle.runtime_state.connection_status = "offline"
            handle.runtime_state.last_error = "vehicle_stopped"

    def mark_collector_started(self, *, endpoint: str, node_id: str | None = None) -> None:
        if node_id is None:
            return
        handle = self.get_vehicle(node_id)
        with handle.state_lock:
            handle.runtime_state.collector_running = True
            handle.runtime_state.connection_status = "connecting"

    def mark_collector_stopped(self, reason: str = "telemetry_collector_stopped", *, node_id: str | None = None) -> None:
        if node_id is None:
            return
        try:
            handle = self.get_vehicle(node_id)
        except VehicleRegistryError:
            # unregister removes membership before a collector join; a late
            # lifecycle callback must not recreate or mutate a removed node.
            return
        with handle.state_lock:
            handle.runtime_state.collector_running = False
            handle.runtime_state.connected = False
            handle.runtime_state.stale = True
            handle.runtime_state.connection_status = "offline"
            handle.runtime_state.last_error = reason

    def update_telemetry(
        self,
        node_id: str,
        snapshot: Px4TelemetrySnapshot,
        *,
        message_type: str | None = None,
        received_at: float | None = None,
    ) -> None:
        handle = self.get_vehicle(node_id)
        if snapshot.system_id is not None and snapshot.system_id != handle.config.system_id:
            self.mark_offline(node_id, reason="telemetry_system_id_mismatch")
            return
        now = self._clock() if received_at is None else received_at
        with handle.state_lock:
            handle.telemetry = snapshot
            handle.telemetry_received_at = now
            state = handle.runtime_state
            state.connected = bool(snapshot.connected)
            state.stale = False
            state.connection_status = "connected" if state.connected else "offline"
            state.last_telemetry_at = snapshot.timestamp
            state.last_error = None
            state.collector_running = True
            if message_type == "HEARTBEAT":
                state.last_heartbeat_at = snapshot.timestamp

    def mark_connected(self, node_id: str, *, at: str | None = None) -> None:
        handle = self.get_vehicle(node_id)
        with handle.state_lock:
            state = handle.runtime_state
            state.connected = True
            state.stale = False
            state.connection_status = "connected"
            state.last_heartbeat_at = at or _utc_now()

    def mark_offline(self, node_id: str, *, reason: str) -> None:
        handle = self.get_vehicle(node_id)
        with handle.state_lock:
            state = handle.runtime_state
            state.connected = False
            state.stale = True
            state.connection_status = "offline"
            state.last_error = reason

    def admit_action(self, node_id: str, action_type: str, action_id: str) -> dict[str, Any]:
        """Atomically admit one per-node action; LAND may preempt a non-LAND action."""
        handle = self.get_vehicle(node_id)
        with handle.action_lock, handle.state_lock:
            state = handle.runtime_state
            if state.active_action is not None:
                if action_type != "land" or state.active_action == "land":
                    raise VehicleRegistryError(
                        "node_busy",
                        node_id=node_id,
                        status=409,
                        details={
                            "active_action": state.active_action,
                            "active_action_id": state.active_action_id,
                        },
                    )
                preempted_action = state.active_action
                preempted_action_id = state.active_action_id
                if handle.action_cancel_event is not None:
                    handle.action_cancel_event.set()
            else:
                preempted_action = None
                preempted_action_id = None
            cancel_event = threading.Event()
            handle.action_cancel_event = cancel_event
            state.active_action = action_type
            state.active_action_id = action_id
            state.last_action_at = _utc_now()
            return {
                "cancel_event": cancel_event,
                "preempted_action": preempted_action,
                "preempted_action_id": preempted_action_id,
            }

    def release_action(
        self,
        node_id: str,
        action_id: str,
        *,
        error: str | None = None,
        at: str | None = None,
    ) -> bool:
        """Release only the matching lease so a preempted action cannot clear LAND."""
        handle = self.get_vehicle(node_id)
        with handle.action_lock, handle.state_lock:
            if handle.runtime_state.active_action_id != action_id:
                return False
            handle.runtime_state.active_action = None
            handle.runtime_state.active_action_id = None
            handle.action_cancel_event = None
            handle.runtime_state.last_action_at = at or _utc_now()
            handle.runtime_state.last_error = error
            return True

    def mark_action_started(
        self,
        node_id: str,
        action_type: str,
        *,
        action_id: str | None = None,
        at: str | None = None,
    ) -> None:
        """Mark only the selected node busy; unrelated handles remain untouched."""
        handle = self.get_vehicle(node_id)
        with handle.state_lock:
            handle.runtime_state.active_action = action_type
            handle.runtime_state.active_action_id = action_id
            handle.runtime_state.last_action_at = at or _utc_now()

    def mark_action_finished(
        self,
        node_id: str,
        *,
        action_id: str | None = None,
        error: str | None = None,
        at: str | None = None,
    ) -> None:
        """Clear a node action and retain its completion/error timestamp."""
        handle = self.get_vehicle(node_id)
        with handle.state_lock:
            if action_id is not None and handle.runtime_state.active_action_id != action_id:
                return
            handle.runtime_state.active_action = None
            handle.runtime_state.active_action_id = None
            handle.action_cancel_event = None
            handle.runtime_state.last_action_at = at or _utc_now()
            if error:
                handle.runtime_state.last_error = error

    def refresh_state(self, handle: VehicleHandle) -> VehicleRuntimeState:
        with handle.state_lock:
            state = handle.runtime_state
            if handle.collector is not None and (
                not handle.session.connected
                or not handle.session.heartbeat_thread_alive()
            ):
                state.connected = False
                state.stale = True
                state.connection_status = "offline"
                if handle.session.last_send_error:
                    state.last_error = (
                        "gcs_heartbeat_send_failed:"
                        f"{handle.session.last_send_error}"
                    )
                return state
            if handle.telemetry_received_at is None:
                state.telemetry_freshness_ms = None
                state.stale = True
                return state
            age = max(0, int((self._clock() - handle.telemetry_received_at) * 1000))
            state.telemetry_freshness_ms = age
            if age > self.stale_after_ms:
                # Stale nodes remain in full snapshots with last-known pose;
                # only explicit unregister removes Runtime identity.
                state.stale = True
                state.connected = False
                state.connection_status = "offline"
            return state

    def vehicle_rows(self) -> list[dict[str, Any]]:
        rows = []
        for handle in self.list_vehicles():
            self.refresh_state(handle)
            with handle.state_lock:
                rows.append({
                    "node_id": handle.config.node_id,
                    "backend": handle.config.backend,
                    "backend_mode": handle.config.backend_mode,
                    "endpoint": handle.config.endpoint,
                    "telemetry_endpoint": handle.config.telemetry_endpoint,
                    "system_id": handle.config.system_id,
                    "component_id": handle.config.component_id,
                    "enabled": handle.config.enabled,
                    **asdict(handle.runtime_state),
                })
        return rows

    def telemetry_dict(self, node_id: str) -> dict[str, Any]:
        handle = self.get_vehicle(node_id)
        self.refresh_state(handle)
        with handle.state_lock:
            return snapshot_to_dict(handle.telemetry)

    @staticmethod
    def _validate_mavlink_id(
        value: int | None,
        *,
        field: str,
        node_id: str,
        allow_none: bool = False,
    ) -> None:
        """Reject broadcast/out-of-range values for a concrete Registry node."""
        if allow_none and value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 255:
            raise VehicleRegistryError(
                f"invalid_{field}",
                node_id=node_id,
                details={"field": field, "minimum": 1, "maximum": 255},
            )
