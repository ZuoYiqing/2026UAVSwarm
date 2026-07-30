"""Thread-safe, read-only state projection for the local Runtime HTTP bridge.

The store owns cached observations and planning state; it never opens MAVLink,
sends commands, probes Gazebo, or grants execution authority.  HTTP handlers can
therefore poll it frequently without contending for a UDP receive socket.
"""
from __future__ import annotations

import copy
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from uav_runtime.adapters.px4_telemetry import Px4TelemetrySnapshot, snapshot_to_dict
from uav_runtime.http.contracts import event_to_envelope, event_to_policy_decision_view
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def finite_json(value: Any) -> Any:
    """Deep-copy a value while replacing non-finite floats with JSON null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(item) for item in value]
    return copy.deepcopy(value)


def without_none(value: Any) -> Any:
    """Remove unavailable optional fields from strict external feed objects."""
    if isinstance(value, dict):
        return {key: without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_none(item) for item in value]
    return value


def vehicle_type_name(mav_type: Any) -> str:
    """Map MAV_TYPE values into the stable Cesium vehicle type vocabulary."""
    try:
        value = int(mav_type)
    except (TypeError, ValueError):
        return "unknown"
    if value in {2, 3, 4, 13, 14, 15, 29, 35}:
        return "multirotor"
    if value == 1:
        return "fixed_wing"
    if value in {19, 20, 21, 22}:
        return "vtol"
    if value == 10:
        return "ugv"
    if value == 11:
        return "usv"
    if value == 12:
        return "uuv"
    return "unknown"


class RuntimeStateStore:
    """In-memory source of truth for non-blocking console status reads.

    Cached telemetry is observational only.  Plan storage tracks the deterministic
    Template Planner and lifecycle state, but does not make a plan executable.
    """

    def __init__(
        self,
        *,
        stale_after_ms: int = 2000,
        backend: str = "px4_sitl",
        backend_mode: str = "sitl",
        telemetry_endpoint: str = "udpin:127.0.0.1:14030",
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        vehicle_registry: VehicleRegistry | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self._monotonic = monotonic
        self._started_monotonic = monotonic()
        self.vehicle_registry = vehicle_registry
        self.stale_after_ms = int(stale_after_ms)
        self.backend = backend
        self.backend_mode = backend_mode
        self.telemetry_endpoint = telemetry_endpoint
        self._telemetry: dict[str, Any] | None = None
        self._telemetry_received_at: float | None = None
        self._telemetry_reason = "telemetry_not_started"
        self._collector_running = False
        self._backend_status: dict[str, Any] = {
            "backend": backend,
            "backend_mode": backend_mode,
            "endpoint": telemetry_endpoint,
            "readiness": "unknown",
            "connect_probe_code": None,
            "connected": False,
            "last_probe_at": None,
        }
        self._backend_status_by_node: dict[str, dict[str, Any]] = {}
        self._latest_plan: dict[str, Any] | None = None
        self._plans: dict[str, dict[str, Any]] = {}
        self._recent_events: list[dict[str, Any]] = []
        self._recent_policy: list[dict[str, Any]] = []
        self._actions: list[dict[str, Any]] = []

    def mark_collector_started(self, *, endpoint: str) -> None:
        with self._lock:
            self.telemetry_endpoint = endpoint
            self._collector_running = True
            self._telemetry_reason = "telemetry_waiting_for_data"

    def mark_collector_stopped(self, reason: str = "telemetry_collector_stopped") -> None:
        with self._lock:
            self._collector_running = False
            self._telemetry_reason = reason

    def update_telemetry(self, snapshot: Px4TelemetrySnapshot | dict[str, Any], *, received_at: float | None = None) -> None:
        raw = snapshot_to_dict(snapshot) if isinstance(snapshot, Px4TelemetrySnapshot) else snapshot
        with self._lock:
            self._telemetry = finite_json(raw)
            self._telemetry_received_at = self._clock() if received_at is None else float(received_at)
            self.telemetry_endpoint = str(raw.get("endpoint") or self.telemetry_endpoint)
            self._telemetry_reason = "telemetry_available"
            self._collector_running = True
            self._backend_status["connected"] = bool(raw.get("connected"))
            self._backend_status["endpoint"] = self.telemetry_endpoint

    def update_backend_status(self, diagnostic: dict[str, Any], *, node_id: str | None = None) -> None:
        probe = diagnostic.get("connect_probe") if isinstance(diagnostic.get("connect_probe"), dict) else {}
        with self._lock:
            status = finite_json({
                "backend": diagnostic.get("backend", self.backend),
                "backend_mode": diagnostic.get("backend_mode", self.backend_mode),
                "endpoint": diagnostic.get("transport_endpoint", self.telemetry_endpoint),
                "readiness": diagnostic.get("readiness", "unknown"),
                "connect_probe_code": probe.get("code"),
                "connected": probe.get("code") == "backend_connected",
                "last_probe_at": utc_now(),
            })
            self._backend_status = status
            if node_id:
                self._backend_status_by_node[node_id] = {"node_id": node_id, **status}

    def record_plan_result(self, result: dict[str, Any]) -> None:
        plan = result.get("plan")
        if not isinstance(plan, dict):
            return
        view = finite_json({
            **plan,
            "validation_summary": result.get("validation_summary", {}),
            "policy_summary": result.get("policy_summary", {}),
        })
        with self._lock:
            self._latest_plan = view
            self._plans[str(view.get("plan_id"))] = view

    def update_plan(self, plan: Any, *, validation_summary: dict[str, Any] | None = None, policy_summary: dict[str, Any] | None = None) -> None:
        raw = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan)
        plan_id = str(raw.get("plan_id") or "")
        if not plan_id:
            return
        with self._lock:
            previous = self._plans.get(plan_id, {})
            view = finite_json({
                **raw,
                "validation_summary": validation_summary if validation_summary is not None else previous.get("validation_summary", {}),
                "policy_summary": policy_summary if policy_summary is not None else previous.get("policy_summary", {}),
            })
            self._plans[plan_id] = view
            self._latest_plan = view

    def record_event(self, event: dict[str, Any], *, limit: int = 100) -> None:
        with self._lock:
            envelope = event_to_envelope(event, index=len(self._recent_events)).to_dict()
            self._recent_events = (self._recent_events + [finite_json(envelope)])[-limit:]

    def record_policy_decision(self, event: dict[str, Any], *, limit: int = 50) -> None:
        with self._lock:
            view = event_to_policy_decision_view(event, index=len(self._recent_policy)).to_dict()
            self._recent_policy = (self._recent_policy + [finite_json(view)])[-limit:]
        self.record_event(event)

    def record_action_result(self, action: dict[str, Any], *, limit: int = 50) -> None:
        with self._lock:
            self._actions = (self._actions + [finite_json(action)])[-limit:]

    def begin_action(self, action_type: str, *, backend: str, backend_mode: str, node_id: str | None = None) -> str:
        action_id = f"act_{uuid4().hex[:12]}"
        self.record_action_result({
            "action_id": action_id, "action_type": action_type, "backend": backend,
            "backend_mode": backend_mode, "status": "running", "started_at": utc_now(),
            "node_id": node_id, "source": "runtime_http_bridge",
        })
        return action_id

    def finish_action(self, action_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            for action in reversed(self._actions):
                if action.get("action_id") != action_id:
                    continue
                action.update(finite_json(result))
                action["status"] = "succeeded" if result.get("result") == "pass" else "failed"
                action["finished_at"] = utc_now()
                return

    def telemetry_latest(self, node_id: str | None = None) -> dict[str, Any]:
        if self.vehicle_registry is not None:
            return self._registry_telemetry_latest(node_id)
        with self._lock:
            raw = copy.deepcopy(self._telemetry)
            received_at = self._telemetry_received_at
            reason = self._telemetry_reason
            endpoint = self.telemetry_endpoint
            collector_running = self._collector_running
        now = self._clock()
        timestamp = utc_now()
        if raw is None or received_at is None:
            return {
                "version": "1.0", "timestamp": timestamp, "status": "unavailable",
                "fresh": False, "age_ms": None, "stale_after_ms": self.stale_after_ms,
                "backend": self.backend, "backend_mode": self.backend_mode,
                "endpoint": endpoint, "nodes": [], "reason": reason,
                "source": "runtime_state_store",
            }
        age_ms = max(0, int(round((now - received_at) * 1000)))
        fresh = age_ms <= self.stale_after_ms and collector_running
        node = self._telemetry_node(raw, node_id=str(raw.get("node_id") or "UAV-01"))
        node["connected"] = bool(node.get("connected")) and fresh
        return finite_json({
            "version": "1.0", "timestamp": timestamp,
            "status": "ok" if fresh and bool(raw.get("connected")) else "unavailable" if not collector_running else "stale" if not fresh else "unavailable",
            "fresh": fresh, "age_ms": age_ms, "stale_after_ms": self.stale_after_ms,
            "backend": raw.get("backend", self.backend),
            "backend_mode": raw.get("backend_mode", self.backend_mode),
            "endpoint": raw.get("endpoint", endpoint), "nodes": [node],
            "reason": None if fresh and bool(raw.get("connected")) else reason if not collector_running else "telemetry_stale" if not fresh else "px4_not_connected",
            "source": "runtime_state_store",
        })

    def _telemetry_node(self, raw: dict[str, Any], *, node_id: str) -> dict[str, Any]:
        local = raw.get("local_position") or {}
        attitude = raw.get("attitude") or {}
        global_position = raw.get("global_position") or {}
        battery = raw.get("battery") or {}
        vx, vy = local.get("vx_m_s"), local.get("vy_m_s")
        ground_speed = math.hypot(vx, vy) if isinstance(vx, (int, float)) and isinstance(vy, (int, float)) else None
        return finite_json({
            "node_id": node_id, "vehicle_type": vehicle_type_name(raw.get("vehicle_type")),
            "connected": bool(raw.get("connected")), "armed": raw.get("armed"),
            "flight_mode": raw.get("flight_mode"), "system_id": raw.get("system_id"),
            "component_id": raw.get("component_id"),
            "local_position": {"frame": "NED", "x_m": local.get("x_m"), "y_m": local.get("y_m"),
                               "z_down_m": local.get("z_down_m"), "altitude_m": local.get("altitude_m")},
            "global_position": {"latitude_deg": global_position.get("lat_deg"), "longitude_deg": global_position.get("lon_deg"),
                                "relative_altitude_m": global_position.get("relative_alt_m"), "heading_deg": global_position.get("heading_deg")},
            "attitude_deg": {"roll": attitude.get("roll_deg"), "pitch": attitude.get("pitch_deg"), "yaw": attitude.get("yaw_deg")},
            "velocity_mps": {"north": vx, "east": vy, "down": local.get("vz_m_s"), "ground_speed": ground_speed},
            "battery": {"percent": battery.get("battery_remaining"), "voltage_v": battery.get("voltage_v"), "current_a": battery.get("current_a")},
            "last_command_ack": raw.get("last_command_ack"), "last_seen": raw.get("timestamp"), "source": "px4_telemetry",
        })

    def _registry_telemetry_latest(self, node_id: str | None) -> dict[str, Any]:
        """Project independent node snapshots; never opens a MAVLink socket."""
        registry = self.vehicle_registry
        assert registry is not None
        handles = [registry.get_vehicle(node_id)] if node_id else registry.list_vehicles()
        nodes: list[dict[str, Any]] = []
        ages: list[int] = []
        for handle in handles:
            state = registry.refresh_state(handle)
            raw = finite_json(snapshot_to_dict(handle.telemetry))
            if handle.telemetry_received_at is None:
                continue
            node = self._telemetry_node(raw, node_id=handle.config.node_id)
            node["connected"] = state.connected and not state.stale
            node["stale"] = state.stale
            node["age_ms"] = state.telemetry_freshness_ms
            nodes.append(node)
            if state.telemetry_freshness_ms is not None:
                ages.append(state.telemetry_freshness_ms)
        fresh = bool(nodes) and all(not node.get("stale") for node in nodes)
        status = "ok" if fresh else "stale" if nodes else "unavailable"
        selected = handles[0] if len(handles) == 1 else None
        return finite_json({
            "version": "1.0", "timestamp": utc_now(), "status": status,
            "fresh": fresh, "age_ms": max(ages) if ages else None,
            "stale_after_ms": registry.stale_after_ms,
            "backend": selected.config.backend if selected else "mixed" if handles else None,
            "backend_mode": selected.config.backend_mode if selected else "sitl",
            "endpoint": selected.config.telemetry_endpoint or selected.config.endpoint if selected else None,
            "nodes": nodes,
            "reason": None if fresh else "telemetry_stale" if nodes else "telemetry_not_started",
            "source": "vehicle_registry",
        })

    def agent_status(self) -> dict[str, Any]:
        with self._lock:
            latest = copy.deepcopy(self._latest_plan)
            active = [copy.deepcopy(plan) for plan in self._plans.values() if plan.get("status") in {"draft", "ready", "validated", "awaiting_confirmation", "approved", "executing"}]
            plan_events = [copy.deepcopy(event) for event in self._recent_events if str(event.get("event_type", "")).startswith("agent_plan")]
        return {
            "version": "1.0", "timestamp": utc_now(), "planner_kind": "template_agent_planner",
            "planner_version": "0.1", "llm_enabled": False, "real_execution_enabled": False,
            "supported_execution_modes": ["dry_run", "fake"], "latest_plan": latest,
            "active_plans": active, "recent_plan_events": plan_events, "source": "runtime_state_store",
        }

    def simulation_status(self) -> dict[str, Any]:
        telemetry = self.telemetry_latest()
        # PX4 heartbeat is recorded separately.  It is never treated as evidence
        # that Gazebo, its clock, world, or models are healthy.
        return {
            "version": "1.0", "timestamp": utc_now(), "simulator": "gazebo",
            "status": "unknown", "clock_advancing": None, "world": None, "models": [],
            "px4_sitl_connected": bool(telemetry.get("nodes") and telemetry["nodes"][0].get("connected")),
            "last_seen": None, "evidence": [], "reason": "gazebo_probe_not_implemented",
            "source": "runtime_state_store",
        }

    def vehicle_snapshot(self) -> dict[str, Any]:
        telemetry = self.telemetry_latest()
        telemetry_by_node = {node["node_id"]: node for node in telemetry.get("nodes", [])}
        if self.vehicle_registry is not None:
            node_rows = self.vehicle_registry.vehicle_rows()
        else:
            node_rows = [{"node_id": node_id, "connected": node.get("connected", False), "stale": not node.get("connected", False)}
                         for node_id, node in telemetry_by_node.items()]
        vehicles: list[dict[str, Any]] = []
        for row in node_rows:
            node_id = str(row["node_id"])
            node = telemetry_by_node.get(node_id, {})
            local = node.get("local_position") or {}
            attitude = node.get("attitude_deg") or {}
            velocity = node.get("velocity_mps") or {}
            battery = node.get("battery") or {}
            pose: dict[str, Any] | None = None
            if all(isinstance(local.get(key), (int, float)) for key in ("x_m", "y_m", "z_down_m")):
                pose = {
                    "frame": "NED",
                    "position_m": {"x": local["x_m"], "y": local["y_m"], "z": local["z_down_m"]},
                }
                if all(isinstance(attitude.get(key), (int, float)) for key in ("roll", "pitch", "yaw")):
                    pose["attitude_deg"] = attitude
            vehicles.append(without_none(finite_json({
                "id": node_id, "display_name": node_id,
                "vehicle_type": (node.get("vehicle_type") if node.get("vehicle_type") != "unknown" else None)
                                or (self.vehicle_registry.get_vehicle(node_id).config.metadata.get("vehicle_type", "unknown")
                                    if self.vehicle_registry is not None else "unknown"),
                "model": (self.vehicle_registry.get_vehicle(node_id).config.metadata.get("model", "x500")
                          if self.vehicle_registry is not None else "x500"),
                "source": {"id": f"px4-sitl-{row.get('system_id') or node_id}", "kind": "simulation", "label": "PX4 SITL"},
                "connected": bool(row.get("connected")) and not bool(row.get("stale")),
                "pose": pose,
                "velocity_mps": {"north": velocity.get("north"), "east": velocity.get("east"),
                                 "up": -velocity["down"] if isinstance(velocity.get("down"), (int, float)) else None},
                "telemetry": {"armed": node.get("armed"), "mode": node.get("flight_mode"),
                              "battery_percent": battery.get("percent"), "ground_speed_mps": velocity.get("ground_speed"),
                              "stale": bool(row.get("stale", True)), "age_ms": row.get("telemetry_freshness_ms")},
            })))
        return {
            "version": "1.0", "timestamp": utc_now(), "full_state": True,
            "source": {"id": "runtime-fusion", "kind": "simulation", "label": "PX4 SITL / Runtime"},
            "scene_id": self.vehicle_registry.scene_id if self.vehicle_registry is not None else None,
            "frame": {"type": "NED"}, "vehicles": vehicles,
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        telemetry = self.telemetry_latest()
        nodes = telemetry.get("nodes", [])
        registered_count = len(self.vehicle_registry.list_vehicles()) if self.vehicle_registry is not None else len(nodes)
        agent = self.agent_status()
        simulation = self.simulation_status()
        with self._lock:
            backend = copy.deepcopy(self._backend_status)
            backend_by_node = copy.deepcopy(list(self._backend_status_by_node.values()))
            events = copy.deepcopy(self._recent_events[-20:])
            decisions = copy.deepcopy(self._recent_policy[-20:])
            active_actions = [copy.deepcopy(action) for action in self._actions if action.get("status") == "running"]
        return finite_json({
            "version": "1.0", "snapshot_id": f"snap_{uuid4().hex[:12]}", "timestamp": utc_now(),
            "runtime_status": {"service": "uav_runtime_http_bridge", "status": "ok", "mode": "local_dev",
                               "uptime_s": max(0.0, self._monotonic() - self._started_monotonic)},
            "backend_status": backend, "backend_statuses": backend_by_node, "simulation_status": simulation,
            "fleet_summary": {"total_nodes": registered_count, "online_nodes": sum(bool(n.get("connected")) for n in nodes),
                              "armed_nodes": sum(bool(n.get("armed")) for n in nodes), "warning_nodes": None},
            "nodes": nodes,
            "agent_runtime": {key: value for key, value in agent.items() if key not in {"version", "timestamp", "source", "recent_plan_events"}}
                             | {"active_sessions": [], "queue": {"supported": False, "depth": None}},
            "missions": [], "active_actions": active_actions,
            "policy_summary": {"latest_decision": decisions[-1] if decisions else None, "recent_decisions": decisions},
            "recent_events": events, "source": "runtime_state_store",
        })
