"""Runtime HTTP Bridge route handlers.

The functions in this module are a local-dev HTTP bridge, not a second runtime.
They map a fixed REST allowlist to existing uav_runtime components and never
accept arbitrary shell commands from the browser.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend
from uav_runtime.adapters.px4_runtime_adapter import Px4RuntimeActionAdapter
from uav_runtime.agent.planner import MissionIntent, TemplateAgentPlanner
from uav_runtime.http.schemas import BackendRequest, LandRequest, PlanMissionRequest, SmokeTakeoffRequest
from uav_runtime.http.contracts import (
    capability_to_skill_manifest,
    event_to_action_result_view,
    event_to_envelope,
    event_to_policy_decision_view,
)
from uav_runtime.policy.action_registry import capability_manifest
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleHandle, VehicleRegistry, VehicleRegistryError

AUDIT_PATH = "audit/runtime.audit.jsonl"
BRIDGE_VERSION = "0.1"
_DEFAULT_VEHICLE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "vehicles.sitl.json"
VEHICLE_REGISTRY = VehicleRegistry.from_json(os.environ.get("UAV_RUNTIME_VEHICLE_CONFIG", _DEFAULT_VEHICLE_CONFIG))
RUNTIME_STATE_STORE = RuntimeStateStore(vehicle_registry=VEHICLE_REGISTRY)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _query_bool(values: dict[str, list[str]], key: str, default: bool = False) -> bool:
    raw = values.get(key, [str(default).lower()])[0]
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _query_int(values: dict[str, list[str]], key: str, default: int, *, minimum: int = 0, maximum: int = 200) -> int:
    try:
        parsed = int(values.get(key, [str(default)])[0])
    except ValueError:
        parsed = default
    return max(minimum, min(parsed, maximum))


def health() -> dict[str, Any]:
    return {"status": "ok", "service": "uav_runtime_http_bridge", "version": BRIDGE_VERSION, "mode": "local_dev"}


def check_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """Bridge /api/backend/check to existing PX4 SITL readiness diagnostics."""
    req = BackendRequest.from_json(payload)
    handle, selection = _resolve_vehicle(req)
    cfg = handle.config.to_mavlink_config()
    backend = Px4SitlBackend(cfg, handle.session)
    result = backend.readiness_diagnostic()
    result["backend"] = req.backend
    result["transport_endpoint"] = cfg.transport_endpoint
    result.update({"node_id": handle.config.node_id, "resolved_node_id": handle.config.node_id, "node_selection": selection})
    RUNTIME_STATE_STORE.update_backend_status(result, node_id=handle.config.node_id)
    RUNTIME_STATE_STORE.record_event({
        "type": "backend_probe_result", "timestamp": _utc_now(),
        "backend": req.backend, "backend_mode": req.backend_mode,
        "endpoint": cfg.transport_endpoint, "node_id": handle.config.node_id, "readiness": result.get("readiness"),
        "connect_probe": result.get("connect_probe"),
    })
    return result


def _resolve_vehicle(req: BackendRequest, *, require_online: bool = False) -> tuple[VehicleHandle, str]:
    return VEHICLE_REGISTRY.resolve_vehicle(
        req.node_id,
        requested_endpoint=req.transport_endpoint or None,
        requested_system_id=req.system_id,
        require_online=require_online,
    )


def _policy_checked_sitl_action(req: BackendRequest, handle: VehicleHandle, *, action: str, skill_group: str = "flight_core") -> tuple[str, dict[str, Any], RuntimeOrchestrator, ActionRequest]:
    cfg = handle.config.to_mavlink_config()
    rt = RuntimeOrchestrator(audit_path=AUDIT_PATH, adapter_name="mavlink", mavlink_backend_config=cfg)
    action_req = ActionRequest(
        action=action,
        params={},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        mission_id=f"mission-http-{action}",
        action_type=action,
        skill_group=skill_group,
        target_set=["self"],
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
        node_id=handle.config.node_id,
        backend_mode=handle.config.backend_mode,
        connection_state=handle.runtime_state.connection_status,
    )
    request_event = {
        "type": "action_request", "timestamp": _utc_now(), "node_id": handle.config.node_id,
        "mission_id": action_req.mission_id, "action_type": action,
        "backend": handle.config.backend, "backend_mode": handle.config.backend_mode,
        "endpoint": handle.config.endpoint, "source": "runtime_http_bridge",
    }
    rt.audit.append(request_event)
    RUNTIME_STATE_STORE.record_event(request_event)
    decision_code, policy_event = rt.evaluate_policy_request(action_req)
    RUNTIME_STATE_STORE.record_policy_decision(policy_event)
    return decision_code, policy_event, rt, action_req


def smoke_takeoff(payload: dict[str, Any]) -> dict[str, Any]:
    """SITL-only bridge for the existing smoke-takeoff runtime capability.

    This route intentionally performs a Policy Gate check first and then uses
    Px4SitlBackend's own SITL-only preflight guard.  It never exposes a browser
    parameter that can invoke arbitrary CLI/shell behavior.
    """
    req = SmokeTakeoffRequest.from_json(payload)
    handle, selection = _resolve_vehicle(req, require_online=True)
    cfg = handle.config.to_mavlink_config()
    action_id = RUNTIME_STATE_STORE.begin_action("takeoff", backend=handle.config.backend, backend_mode=handle.config.backend_mode, node_id=handle.config.node_id)
    decision_code, policy_event, rt, action_req = _policy_checked_sitl_action(req, handle, action="takeoff")
    VEHICLE_REGISTRY.mark_action_started(handle.config.node_id, "takeoff")
    if req.backend_mode != "sitl":
        out = {"action": "takeoff", "backend": req.backend, "backend_mode": req.backend_mode,
               "endpoint": req.transport_endpoint, "policy_decision": policy_event,
               "result": "fail", "failure_reason": "sitl_only_required"}
    elif decision_code != "allow":
        out = {
            "action": "takeoff",
            "backend": req.backend,
            "backend_mode": cfg.backend_mode,
            "endpoint": cfg.transport_endpoint,
            "policy_decision": policy_event,
            "result": "fail",
            "failure_reason": f"policy_{decision_code}",
        }
    else:
        backend = Px4SitlBackend(cfg, handle.session)
        rt.gateway.register(Px4RuntimeActionAdapter(backend))
        started_event = _adapter_event("adapter_execution_started", handle, "takeoff")
        rt.audit.append(started_event)
        RUNTIME_STATE_STORE.record_event(started_event)
        try:
            with handle.command_lock:
                action_req.params = {
                    "altitude_m": req.altitude_m, "auto_land": req.auto_land,
                    "command_timeout_ms": req.command_timeout_ms,
                    "observe_timeout_ms": req.observe_timeout_ms,
                    "threshold_ratio": req.threshold_ratio,
                }
                gateway_result = rt.gateway.execute("mavlink", action_req)
                out = dict(gateway_result.get("raw_result") or {
                    "action": "takeoff", "result": "fail",
                    "failure_reason": gateway_result.get("code") or "adapter_execution_failed",
                })
        except Exception:
            VEHICLE_REGISTRY.mark_action_finished(handle.config.node_id, error="adapter_execution_exception")
            raise
        out["policy_decision"] = policy_event
        result_event = _adapter_event("adapter_execution_result", handle, "takeoff", result=out)
        rt.audit.append(result_event)
        RUNTIME_STATE_STORE.record_event(result_event)
    out.update({"node_id": handle.config.node_id, "resolved_node_id": handle.config.node_id, "node_selection": selection})
    rt.audit.append(_action_audit_event("http_smoke_takeoff", out, cfg, handle.config.node_id))
    RUNTIME_STATE_STORE.finish_action(action_id, out)
    RUNTIME_STATE_STORE.record_event(_action_audit_event("http_smoke_takeoff", out, cfg, handle.config.node_id))
    action_result_event = _action_audit_event("action_result", out, cfg, handle.config.node_id)
    rt.audit.append(action_result_event)
    RUNTIME_STATE_STORE.record_event(action_result_event)
    VEHICLE_REGISTRY.mark_action_finished(handle.config.node_id, error=out.get("failure_reason"))
    return out


def land(payload: dict[str, Any]) -> dict[str, Any]:
    """SITL-only land bridge for local development.

    LAND is exposed only through the same Policy Gate + Px4SitlBackend SITL guard
    used by smoke-takeoff.  Non-SITL requests are rejected before any real command
    path can run.
    """
    req = LandRequest.from_json(payload)
    handle, selection = _resolve_vehicle(req, require_online=True)
    cfg = handle.config.to_mavlink_config()
    action_id = RUNTIME_STATE_STORE.begin_action("land", backend=handle.config.backend, backend_mode=handle.config.backend_mode, node_id=handle.config.node_id)
    decision_code, policy_event, rt, action_req = _policy_checked_sitl_action(req, handle, action="land")
    VEHICLE_REGISTRY.mark_action_started(handle.config.node_id, "land")
    if req.backend_mode != "sitl":
        out = {"action": "land", "backend": req.backend, "backend_mode": req.backend_mode,
               "endpoint": req.transport_endpoint, "policy_decision": policy_event,
               "result": "fail", "failure_reason": "sitl_only_required"}
    elif decision_code != "allow":
        out = {
            "action": "land",
            "backend": req.backend,
            "backend_mode": cfg.backend_mode,
            "endpoint": cfg.transport_endpoint,
            "policy_decision": policy_event,
            "result": "fail",
            "failure_reason": f"policy_{decision_code}",
        }
    else:
        backend = Px4SitlBackend(cfg, handle.session)
        rt.gateway.register(Px4RuntimeActionAdapter(backend))
        started_event = _adapter_event("adapter_execution_started", handle, "land")
        rt.audit.append(started_event)
        RUNTIME_STATE_STORE.record_event(started_event)
        try:
            with handle.command_lock:
                action_req.params = {"command_timeout_ms": req.command_timeout_ms}
                gateway_result = rt.gateway.execute("mavlink", action_req)
                out = dict(gateway_result.get("raw_result") or {
                    "action": "land", "result": "fail",
                    "failure_reason": gateway_result.get("code") or "adapter_execution_failed",
                })
        except Exception:
            VEHICLE_REGISTRY.mark_action_finished(handle.config.node_id, error="adapter_execution_exception")
            raise
        out["policy_decision"] = policy_event
        result_event = _adapter_event("adapter_execution_result", handle, "land", result=out)
        rt.audit.append(result_event)
        RUNTIME_STATE_STORE.record_event(result_event)
    out.update({"node_id": handle.config.node_id, "resolved_node_id": handle.config.node_id, "node_selection": selection})
    rt.audit.append(_action_audit_event("http_land", out, cfg, handle.config.node_id))
    RUNTIME_STATE_STORE.finish_action(action_id, out)
    RUNTIME_STATE_STORE.record_event(_action_audit_event("http_land", out, cfg, handle.config.node_id))
    action_result_event = _action_audit_event("action_result", out, cfg, handle.config.node_id)
    rt.audit.append(action_result_event)
    RUNTIME_STATE_STORE.record_event(action_result_event)
    VEHICLE_REGISTRY.mark_action_finished(handle.config.node_id, error=out.get("failure_reason"))
    return out


def plan_mission(payload: dict[str, Any]) -> dict[str, Any]:
    """Dry-run / plan-only bridge to TemplateAgentPlanner.

    The planner endpoint returns Mission Plan IR only.  It does not execute
    action steps, does not call PX4, and does not call adapters.
    """
    req = PlanMissionRequest.from_json(payload)
    intent = MissionIntent(
        intent_id=f"intent-http-{uuid4().hex[:10]}",
        mission_type=req.mission_type,
        source=req.source,
        objective=req.objective,
        requested_profile=req.profile,
        dry_run=req.dry_run,
    )
    planner = TemplateAgentPlanner()
    result = planner.plan(intent).to_dict()
    RUNTIME_STATE_STORE.record_plan_result(result)
    plan = result.get("plan") or {}
    RUNTIME_STATE_STORE.record_event({
        "type": "agent_plan_created", "timestamp": _utc_now(),
        "plan_id": plan.get("plan_id"), "mission_type": req.mission_type,
        "status": plan.get("status"), "result": result.get("result"),
    })
    return result


def telemetry_latest(query: str = "") -> dict[str, Any]:
    """Return a cached telemetry snapshot without opening a MAVLink session."""
    node_id = parse_qs(query, keep_blank_values=True).get("node_id", [None])[0] or None
    return RUNTIME_STATE_STORE.telemetry_latest(node_id=node_id)


def vehicles() -> dict[str, Any]:
    """List registered nodes; reading registry state cannot execute commands."""
    return {"version": "1.0", "timestamp": _utc_now(), "scene_id": VEHICLE_REGISTRY.scene_id,
            "vehicles": VEHICLE_REGISTRY.vehicle_rows(), "source": "vehicle_registry"}


def runtime_snapshot() -> dict[str, Any]:
    """Return the non-blocking console snapshot assembled from owned state."""
    return RUNTIME_STATE_STORE.runtime_snapshot()


def vehicle_snapshot() -> dict[str, Any]:
    """Return the Cesium vehicle feed projection from cached telemetry only."""
    return RUNTIME_STATE_STORE.vehicle_snapshot()


def agent_status() -> dict[str, Any]:
    """Describe the real deterministic Template Planner and stored plans."""
    return RUNTIME_STATE_STORE.agent_status()


def simulation_status() -> dict[str, Any]:
    """Report Gazebo as unknown until independent simulator evidence exists."""
    return RUNTIME_STATE_STORE.simulation_status()


def capabilities(query: str = "") -> dict[str, Any]:
    """Return capability manifest rows; dangerous actions are hidden by default."""
    values = parse_qs(query, keep_blank_values=True)
    domain = values.get("domain", [None])[0] or None
    adapter = values.get("adapter", [None])[0] or None
    return {
        "capabilities": capability_manifest(
            domain=domain,  # type: ignore[arg-type]
            adapter=adapter,
            fallback_only=_query_bool(values, "fallback_only", False),
            include_dangerous=_query_bool(values, "include_dangerous", False),
        )
    }


def replay(query: str = "") -> list[dict[str, Any]]:
    values = parse_qs(query, keep_blank_values=True)
    return replay_last(AUDIT_PATH, n=_query_int(values, "n", 20))


def events(query: str = "") -> list[dict[str, Any]]:
    """Read-only console event stream derived from audit/replay JSONL.

    This route normalizes old audit rows into EventEnvelope so the frontend can
    render a timeline without knowing every historical event shape.
    """
    values = parse_qs(query, keep_blank_values=True)
    n = _query_int(values, "n", 50)
    raw_events = replay_last(AUDIT_PATH, n=n)
    return [event_to_envelope(event, index=i).to_dict() for i, event in enumerate(raw_events)]


def actions_recent(query: str = "") -> list[dict[str, Any]]:
    """Read-only recent action views derived from audit/replay events."""
    values = parse_qs(query, keep_blank_values=True)
    n = _query_int(values, "n", 20)
    raw_events = replay_last(AUDIT_PATH, n=max(n * 5, n))
    action_events = [event for event in raw_events if _is_action_result_event(event)]
    return [event_to_action_result_view(event, index=i).to_dict() for i, event in enumerate(action_events[-n:])]


def policy_decisions(query: str = "") -> list[dict[str, Any]]:
    """Read-only PolicyDecisionView list derived from policy audit events."""
    values = parse_qs(query, keep_blank_values=True)
    n = _query_int(values, "n", 20)
    raw_events = replay_last(AUDIT_PATH, n=max(n * 5, n))
    policy_events = [event for event in raw_events if str(event.get("type") or event.get("event_type")) == "policy_decision_event"]
    return [event_to_policy_decision_view(event, index=i).to_dict() for i, event in enumerate(policy_events[-n:])]


def skills(query: str = "") -> dict[str, Any]:
    """Return console SkillManifest projections; this is not execution authorization."""
    values = parse_qs(query, keep_blank_values=True)
    domain = values.get("domain", [None])[0] or None
    adapter = values.get("adapter", [None])[0] or None
    rows = capability_manifest(
        domain=domain,  # type: ignore[arg-type]
        adapter=adapter,
        fallback_only=_query_bool(values, "fallback_only", False),
        include_dangerous=_query_bool(values, "include_dangerous", False),
    )
    return {"skills": [capability_to_skill_manifest(row).to_dict() for row in rows]}


def _is_action_result_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or event.get("event_type") or "")
    if event_type in {"action_result", "adapter_execution_result", "px4_sitl_smoke_takeoff", "http_smoke_takeoff", "http_land"}:
        return True
    return any(key in event for key in ("arm_ack", "takeoff_ack", "land_ack", "altitude_observation"))


def dispatch(method: str, path: str, *, body: dict[str, Any] | None = None, query: str = "") -> tuple[int, Any]:
    """Dispatch a fixed HTTP allowlist; no route maps to arbitrary commands."""
    normalized = path.rstrip("/") or "/"
    payload = body or {}
    try:
        return _dispatch_known(method, normalized, path=path, payload=payload, query=query)
    except VehicleRegistryError as exc:
        return exc.status, {"version": "1.0", "timestamp": _utc_now(), **exc.to_dict(), "source": "vehicle_registry"}


def _dispatch_known(method: str, normalized: str, *, path: str, payload: dict[str, Any], query: str) -> tuple[int, Any]:
    if method == "GET" and normalized == "/api/health":
        return 200, health()
    if method == "POST" and normalized == "/api/backend/check":
        return 200, check_backend(payload)
    if method == "POST" and normalized == "/api/actions/smoke-takeoff":
        return 200, smoke_takeoff(payload)
    if method == "POST" and normalized == "/api/actions/land":
        return 200, land(payload)
    if method == "POST" and normalized == "/api/planner/plan-mission":
        return 200, plan_mission(payload)
    if method == "GET" and normalized == "/api/replay":
        return 200, replay(query)
    if method == "GET" and normalized == "/api/capabilities":
        return 200, capabilities(query)
    if method == "GET" and normalized == "/api/events":
        return 200, events(query)
    if method == "GET" and normalized == "/api/actions/recent":
        return 200, actions_recent(query)
    if method == "GET" and normalized == "/api/policy/decisions":
        return 200, policy_decisions(query)
    if method == "GET" and normalized == "/api/skills":
        return 200, skills(query)
    if method == "GET" and normalized == "/api/telemetry/latest":
        return 200, telemetry_latest(query)
    if method == "GET" and normalized == "/api/vehicles":
        return 200, vehicles()
    if method == "GET" and normalized == "/api/snapshot":
        return 200, runtime_snapshot()
    if method == "GET" and normalized == "/api/vehicle-snapshot":
        return 200, vehicle_snapshot()
    if method == "GET" and normalized == "/api/agent/status":
        return 200, agent_status()
    if method == "GET" and normalized == "/api/simulation/status":
        return 200, simulation_status()
    return 404, {"error": "not_found", "path": path, "method": method}


def _action_audit_event(event_type: str, out: dict[str, Any], cfg: Any, node_id: str) -> dict[str, Any]:
    return {
        "type": event_type,
        "timestamp": _utc_now(),
        "action": out.get("action"),
        "node_id": node_id,
        "backend": out.get("backend", "px4_sitl"),
        "backend_mode": out.get("backend_mode", cfg.backend_mode),
        "endpoint": out.get("endpoint", cfg.transport_endpoint),
        "policy_decision": out.get("policy_decision"),
        "ack": {"arm_ack": out.get("arm_ack"), "takeoff_ack": out.get("takeoff_ack"), "land_ack": out.get("land_ack")},
        "altitude_observation": out.get("altitude_observation"),
        "max_altitude_m": out.get("max_altitude_m"),
        "threshold_reached": out.get("threshold_reached"),
        "result": out.get("result"),
        "failure_reason": out.get("failure_reason"),
    }


def _adapter_event(
    event_type: str,
    handle: VehicleHandle,
    action_type: str,
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build node-specific adapter audit without granting execution authority."""
    return {
        "type": event_type,
        "timestamp": _utc_now(),
        "node_id": handle.config.node_id,
        "action_type": action_type,
        "adapter": "mavlink",
        "backend": handle.config.backend,
        "backend_mode": handle.config.backend_mode,
        "endpoint": handle.config.endpoint,
        "result": result.get("result") if result else None,
        "failure_reason": result.get("failure_reason") if result else None,
    }
