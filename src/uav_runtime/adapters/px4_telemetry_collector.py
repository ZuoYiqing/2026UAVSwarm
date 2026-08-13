"""Telemetry subscriber for a Registry-owned shared MAVLink session."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot

if TYPE_CHECKING:
    from uav_runtime.http.state_store import RuntimeStateStore


class Px4TelemetryCollector:
    """Normalize dispatcher messages without owning a socket or RX thread."""

    def __init__(
        self,
        store: RuntimeStateStore,
        *,
        session: MavlinkBackendSession,
        node_id: str | None = None,
        endpoint: str,
    ) -> None:
        self.store = store
        self.session = session
        self.node_id = node_id
        self.endpoint = endpoint
        self._lock = threading.RLock()
        self._subscription: int | None = None
        self._running = False
        self._snapshot = new_snapshot(endpoint=endpoint, connected=True)
        self._snapshot.node_id = node_id
        self._snapshot.system_id = session.target_system
        self._snapshot.component_id = session.target_component

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            if self.node_id is None:
                self.store.mark_collector_started(endpoint=self.endpoint)
            else:
                self.store.mark_collector_started(endpoint=self.endpoint, node_id=self.node_id)
            self._subscription = self.session.subscribe(self._on_message)
            try:
                self.session.start_receive_loop(
                    thread_name=f"mavlink-rx-{self.node_id or 'legacy'}"
                )
            except Exception:
                self.session.unsubscribe(self._subscription)
                self._subscription = None
                raise
            self._running = True
            return True

    def stop(self, *, join_timeout_s: float = 2.0) -> None:
        del join_timeout_s  # Session lifecycle owner performs the thread join.
        with self._lock:
            token = self._subscription
            self._subscription = None
            self._running = False
        if token is not None:
            self.session.unsubscribe(token)
        if self.node_id is None:
            self.store.mark_collector_stopped()
        else:
            self.store.mark_collector_stopped(node_id=self.node_id)

    def is_running(self) -> bool:
        with self._lock:
            return self._running and self.session.receive_thread_alive()

    def _on_message(self, message: Any) -> None:
        kind_getter = getattr(message, "get_type", None)
        message_type = str(kind_getter()) if callable(kind_getter) else None
        with self._lock:
            apply_mavlink_message(
                self._snapshot,
                message,
                flight_mode=getattr(self.session.connection, "flightmode", None),
            )
            if self.node_id is None:
                self.store.update_telemetry(self._snapshot)
            else:
                self.store.update_telemetry(
                    self.node_id,
                    self._snapshot,
                    message_type=message_type,
                )
