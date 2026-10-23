"""Reuse existing Registry/Policy/actions with a single transport owner."""
from __future__ import annotations

from typing import Any

from uav_runtime.runtime.vehicle_registry import VehicleRegistry
from .contract import PlatformError, fingerprint


def select_registry(registry: VehicleRegistry, node_ids: list[str]) -> VehicleRegistry:
    selected = VehicleRegistry(scene_id=registry.scene_id,
                               default_node_id=registry.default_node_id if registry.default_node_id in node_ids else None,
                               session_factory=registry._session_factory)
    for node_id in node_ids:
        selected.register_vehicle(registry.get_vehicle(node_id).config)
    return selected


class SitlActions:
    def __init__(self, node_id: str, config_path: str, audit_path: str):
        from .ownership import TransportLease
        if node_id != "UAV-02":
            raise PlatformError("companion_profile_requires_uav02")
        from uav_runtime.http import routes
        from uav_runtime.http.state_store import RuntimeStateStore
        self.routes, self.node_id = routes, node_id
        source = VehicleRegistry.from_json(config_path)
        handle = source.get_vehicle(node_id)
        expected = {"UAV-01": (1, "udpin:127.0.0.1:14540"), "UAV-02": (2, "udpin:127.0.0.1:14541"),
                    "UAV-03": (3, "udpin:127.0.0.1:14542")}
        if (node_id not in expected or (handle.config.system_id, handle.config.endpoint) != expected[node_id]
                or handle.config.component_id != 1):
            raise PlatformError("companion_transport_binding_mismatch", 409)
        self.registry = select_registry(source, [node_id])
        self.lease = TransportLease(handle.config.endpoint)
        routes.VEHICLE_REGISTRY = self.registry
        routes.RUNTIME_STATE_STORE = RuntimeStateStore(vehicle_registry=self.registry)
        routes.AUDIT_PATH = audit_path

    def observe(self) -> dict[str, Any]:
        handle = self.registry.get_vehicle(self.node_id)
        raw = self.registry.telemetry_dict(self.node_id)
        state = handle.session.autonomous_state()
        position = handle.session.local_position_evidence()
        return {"source": "px4_telemetry", "sample_timestamp": position.get("sample_timestamp"),
                "stale": state.get("fresh") is not True or position["stale"], "local_position": position["local_position"],
                "armed": state.get("armed"), "landed_state": state.get("landed_state"),
                "landed_fresh": state.get("landed_fresh"), "battery": raw.get("battery", {})}

    def execute(self, task, step):
        action = step["action"]
        path = {"takeoff": "/api/actions/takeoff", "hold_position": "/api/actions/hold-position", "land": "/api/actions/land"}[action]
        key = f"{task['execution_id']}.{fingerprint(step)[:16]}"
        body = {"node_id": self.node_id, "backend_enabled": True, "command_source": "agent",
                "request_id": key, "trace_id": task["trace_id"], "idempotency_key": key,
                "observe_timeout_ms": 120000, **step["params"]}
        status, result = self.routes.dispatch("POST", path, body=body)
        if status >= 400:
            return {**result, "status": "failed", "result": "fail"}
        return result
