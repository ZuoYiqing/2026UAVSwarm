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


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class VehicleRegistryError(LookupError):
    """Structured registry failure suitable for HTTP/API translation."""

    def __init__(self, code: str, *, node_id: str | None = None, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.node_id = node_id
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "node_id": self.node_id}


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
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    collector: Any = None
    telemetry_received_at: float | None = None


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
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        registry = cls(
            scene_id=str(data.get("scene_id") or ""),
            default_node_id=data.get("default_node_id"),
            **kwargs,
        )
        for row in data.get("vehicles", []):
            registry.register_vehicle(VehicleConfig(**row))
        return registry

    def register_vehicle(self, config: VehicleConfig) -> VehicleHandle:
        if not config.node_id:
            raise VehicleRegistryError("node_id_required")
        with self._lock:
            if config.node_id in self._vehicles:
                raise VehicleRegistryError("duplicate_node_id", node_id=config.node_id, status=409)
            if any(handle.config.system_id == config.system_id for handle in self._vehicles.values()):
                raise VehicleRegistryError("duplicate_system_id", node_id=config.node_id, status=409)
            if config.endpoint and any(handle.config.endpoint == config.endpoint for handle in self._vehicles.values()):
                raise VehicleRegistryError("duplicate_endpoint", node_id=config.node_id, status=409)
            if config.telemetry_endpoint and any(
                handle.config.telemetry_endpoint == config.telemetry_endpoint for handle in self._vehicles.values()
            ):
                raise VehicleRegistryError("duplicate_telemetry_endpoint", node_id=config.node_id, status=409)
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
        if not handle.config.enabled:
            raise VehicleRegistryError("node_disabled", node_id=resolved, status=409)
        if handle.config.backend != "px4_sitl":
            raise VehicleRegistryError("unsupported_node_backend", node_id=resolved, status=409)
        self.refresh_state(handle)
        # A never-started node may be connected on demand by a command route.
        # A node explicitly marked offline must not silently receive commands.
        if require_online and handle.runtime_state.connection_status == "offline":
            raise VehicleRegistryError("node_offline", node_id=resolved, status=503)
        return handle, selection

    def start_vehicle(self, node_id: str) -> None:
        handle = self.get_vehicle(node_id)
        if not handle.config.enabled:
            return
        telemetry_endpoint = handle.config.telemetry_endpoint
        if not telemetry_endpoint:
            handle.runtime_state.last_error = "telemetry_endpoint_not_configured"
            return
        if handle.collector is not None and handle.collector.is_running():
            return
        from uav_runtime.adapters.px4_telemetry_collector import Px4TelemetryCollector

        handle.collector = Px4TelemetryCollector(
            self,
            node_id=node_id,
            endpoint=telemetry_endpoint,
            expected_system_id=handle.config.system_id,
            expected_component_id=handle.config.component_id,
        )
        handle.collector.start()

    def stop_vehicle(self, node_id: str) -> None:
        self._stop_handle(self.get_vehicle(node_id))

    def start_all(self) -> None:
        for handle in self.list_vehicles():
            self.start_vehicle(handle.config.node_id)

    def stop_all(self) -> None:
        for handle in self.list_vehicles():
            self._stop_handle(handle)

    def _stop_handle(self, handle: VehicleHandle) -> None:
        if handle.collector is not None:
            handle.collector.stop()
            handle.collector = None
        handle.session.close()
        handle.runtime_state.connected = False
        handle.runtime_state.stale = True
        handle.runtime_state.connection_status = "offline"
        handle.runtime_state.last_error = "vehicle_stopped"

    def mark_collector_started(self, *, endpoint: str, node_id: str | None = None) -> None:
        if node_id is None:
            return
        handle = self.get_vehicle(node_id)
        handle.runtime_state.collector_running = True
        handle.runtime_state.connection_status = "connecting"

    def mark_collector_stopped(self, reason: str = "telemetry_collector_stopped", *, node_id: str | None = None) -> None:
        if node_id is None:
            return
        handle = self.get_vehicle(node_id)
        handle.runtime_state.collector_running = False
        self.mark_offline(node_id, reason=reason)

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
        state = self.get_vehicle(node_id).runtime_state
        state.connected = True
        state.stale = False
        state.connection_status = "connected"
        state.last_heartbeat_at = at or _utc_now()

    def mark_offline(self, node_id: str, *, reason: str) -> None:
        state = self.get_vehicle(node_id).runtime_state
        state.connected = False
        state.stale = True
        state.connection_status = "offline"
        state.last_error = reason

    def mark_action_started(self, node_id: str, action_type: str, *, at: str | None = None) -> None:
        """Mark only the selected node busy; unrelated handles remain untouched."""
        state = self.get_vehicle(node_id).runtime_state
        state.active_action = action_type
        state.last_action_at = at or _utc_now()

    def mark_action_finished(self, node_id: str, *, error: str | None = None, at: str | None = None) -> None:
        """Clear a node action and retain its completion/error timestamp."""
        state = self.get_vehicle(node_id).runtime_state
        state.active_action = None
        state.last_action_at = at or _utc_now()
        if error:
            state.last_error = error

    def refresh_state(self, handle: VehicleHandle) -> VehicleRuntimeState:
        state = handle.runtime_state
        if handle.telemetry_received_at is None:
            state.telemetry_freshness_ms = None
            state.stale = True
            return state
        age = max(0, int((self._clock() - handle.telemetry_received_at) * 1000))
        state.telemetry_freshness_ms = age
        if age > self.stale_after_ms:
            # A timeout is retained as stale/offline so Cesium keeps the last pose;
            # only explicit unregister removes the node from a full snapshot.
            state.stale = True
            state.connected = False
            state.connection_status = "offline"
        return state

    def vehicle_rows(self) -> list[dict[str, Any]]:
        rows = []
        for handle in self.list_vehicles():
            state = self.refresh_state(handle)
            rows.append({
                "node_id": handle.config.node_id,
                "backend": handle.config.backend,
                "backend_mode": handle.config.backend_mode,
                "endpoint": handle.config.endpoint,
                "telemetry_endpoint": handle.config.telemetry_endpoint,
                "system_id": handle.config.system_id,
                "component_id": handle.config.component_id,
                "enabled": handle.config.enabled,
                **asdict(state),
            })
        return rows

    def telemetry_dict(self, node_id: str) -> dict[str, Any]:
        handle = self.get_vehicle(node_id)
        self.refresh_state(handle)
        return snapshot_to_dict(handle.telemetry)
