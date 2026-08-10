"""Managed PX4 telemetry receive loop for RuntimeStateStore.

The collector uses a dedicated receive endpoint (14030 by default) so the
existing command/smoke session can retain 14540.  It sends no message interval
or vehicle-control commands; it only publishes messages PX4 already emits.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_telemetry import TRACKED_MESSAGE_TYPES, apply_mavlink_message, new_snapshot
if TYPE_CHECKING:
    from uav_runtime.http.state_store import RuntimeStateStore


class Px4TelemetryCollector:
    """One managed receiver with clean start/stop and retry cleanup semantics."""

    def __init__(
        self,
        store: RuntimeStateStore,
        *,
        node_id: str | None = None,
        expected_system_id: int | None = None,
        expected_component_id: int | None = None,
        endpoint: str = "udpin:127.0.0.1:14030",
        connect_timeout_s: float = 1.0,
        retry_delay_s: float = 1.0,
        session_factory: Callable[[MavlinkBackendConfig], Any] | None = None,
    ) -> None:
        self.store = store
        self.node_id = node_id
        self.expected_system_id = expected_system_id
        self.expected_component_id = expected_component_id
        self.endpoint = endpoint
        self.connect_timeout_s = connect_timeout_s
        self.retry_delay_s = retry_delay_s
        self.session_factory = session_factory or (lambda cfg: MavlinkBackendSession.from_config(cfg))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session: Any = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        if self.node_id is None:
            self.store.mark_collector_started(endpoint=self.endpoint)
        else:
            self.store.mark_collector_started(endpoint=self.endpoint, node_id=self.node_id)
        self._thread = threading.Thread(target=self._run, name="px4-telemetry-collector", daemon=True)
        self._thread.start()
        return True

    def stop(self, *, join_timeout_s: float = 2.0) -> None:
        self._stop.set()
        session = self._session
        if session is not None:
            session.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=join_timeout_s)
        self._thread = None
        self._session = None
        if self.node_id is None:
            self.store.mark_collector_stopped()
        else:
            self.store.mark_collector_stopped(node_id=self.node_id)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        cfg = MavlinkBackendConfig(
            backend_mode="sitl", backend_enabled=True,
            transport_endpoint=self.endpoint,
            target_system=self.expected_system_id,
            target_component=self.expected_component_id,
            connect_timeout_ms=max(100, int(self.connect_timeout_s * 1000)),
        )
        while not self._stop.is_set():
            session = self.session_factory(cfg)
            self._session = session
            try:
                conn = session.connect(timeout_s=self.connect_timeout_s)
                snapshot = new_snapshot(endpoint=self.endpoint, connected=True)
                snapshot.node_id = self.node_id
                # connect() has already validated the heartbeat-derived target
                # against Registry configuration, so identity is known before a
                # position message is allowed into a node-specific cache.
                snapshot.system_id = int(getattr(conn, "target_system", 0) or 0) or None
                snapshot.component_id = int(getattr(conn, "target_component", 0) or 0) or None
                while not self._stop.is_set():
                    msg = conn.recv_match(type=list(TRACKED_MESSAGE_TYPES), blocking=True, timeout=0.25)
                    if msg is None:
                        continue
                    msg_type = str(msg.get_type()) if callable(getattr(msg, "get_type", None)) else None
                    apply_mavlink_message(snapshot, msg, flight_mode=getattr(conn, "flightmode", None))
                    if self.node_id is None:
                        self.store.update_telemetry(snapshot)
                    else:
                        self.store.update_telemetry(self.node_id, snapshot, message_type=msg_type)
            except Exception:
                if not self._stop.is_set():
                    if self.node_id is None:
                        self.store.mark_collector_stopped("telemetry_connection_failed")
                    else:
                        self.store.mark_collector_stopped("telemetry_connection_failed", node_id=self.node_id)
            finally:
                session.close()
                self._session = None
            if not self._stop.wait(max(self.retry_delay_s, 0.01)):
                if self.node_id is None:
                    self.store.mark_collector_started(endpoint=self.endpoint)
                else:
                    self.store.mark_collector_started(endpoint=self.endpoint, node_id=self.node_id)
