"""Runtime HTTP Bridge route handlers.

The functions in this module are a local-dev HTTP bridge, not a second runtime.
They map a fixed REST allowlist to existing uav_runtime components and never
accept arbitrary shell commands from the browser.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from uav_runtime.adapters.mavlink_backend_session import MavlinkBackendSession
from uav_runtime.adapters.px4_sitl_backend import Px4SitlBackend
from uav_runtime.agent.planner import MissionIntent, TemplateAgentPlanner
from uav_runtime.http.schemas import BackendRequest, LandRequest, PlanMissionRequest, SmokeTakeoffRequest
from uav_runtime.policy.action_registry import capability_manifest
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator
from uav_runtime.runtime.replay import replay_last

AUDIT_PATH = "audit/runtime.audit.jsonl"
BRIDGE_VERSION = "0.1"


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _query_bool(values: dict[str, list[str]], key: str, default: bool = False) -> bool:
    raw = values.get(key, [str(default).lower()])[0]
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def health() -> dict[str, Any]:
    return {"status": "ok", "service": "uav_runtime_http_bridge", "version": BRIDGE_VERSION, "mode": "local_dev"}


def check_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """Bridge /api/backend/check to existing PX4 SITL readiness diagnostics."""
    req = BackendRequest.from_json(payload)
    cfg = req.to_mavlink_config()
    backend = Px4SitlBackend(cfg, MavlinkBackendSession.from_config(cfg))
    result = backend.readiness_diagnostic()
    result["backend"] = req.backend
    result["transport_endpoint"] = req.transport_endpoint
    return result


def _policy_checked_sitl_action(req: BackendRequest, *, action: str, skill_group: str = "flight_core") -> tuple[str, dict[str, Any], RuntimeOrchestrator]:
    cfg = req.to_mavlink_config()
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
    )
    decision_code, policy_event = rt.evaluate_policy_request(action_req)
    return decision_code, policy_event, rt


def smoke_takeoff(payload: dict[str, Any]) -> dict[str, Any]:
    """SITL-only bridge for the existing smoke-takeoff runtime capability.

    This route intentionally performs a Policy Gate check first and then uses
    Px4SitlBackend's own SITL-only preflight guard.  It never exposes a browser
    parameter that can invoke arbitrary CLI/shell behavior.
    """
    req = SmokeTakeoffRequest.from_json(payload)
    decision_code, policy_event, rt = _policy_checked_sitl_action(req, action="takeoff")
    cfg = req.to_mavlink_config()
    if decision_code != "allow":
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
        backend = Px4SitlBackend(cfg, MavlinkBackendSession.from_config(cfg))
        out = backend.execute_takeoff_smoke(
            altitude_m=req.altitude_m,
            auto_land=req.auto_land,
            command_timeout_ms=req.command_timeout_ms,
            observe_timeout_ms=req.observe_timeout_ms,
            threshold_ratio=req.threshold_ratio,
        )
        out["policy_decision"] = policy_event
    rt.audit.append(_action_audit_event("http_smoke_takeoff", out, cfg))
    return out


def land(payload: dict[str, Any]) -> dict[str, Any]:
    """SITL-only land bridge for local development.

    LAND is exposed only through the same Policy Gate + Px4SitlBackend SITL guard
    used by smoke-takeoff.  Non-SITL requests are rejected before any real command
    path can run.
    """
    req = LandRequest.from_json(payload)
    decision_code, policy_event, rt = _policy_checked_sitl_action(req, action="land")
    cfg = req.to_mavlink_config()
    if decision_code != "allow":
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
        backend = Px4SitlBackend(cfg, MavlinkBackendSession.from_config(cfg))
        out = backend.execute_land_action(command_timeout_ms=req.command_timeout_ms)
        out["policy_decision"] = policy_event
    rt.audit.append(_action_audit_event("http_land", out, cfg))
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
    return planner.plan(intent).to_dict()


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
    try:
        n = int(values.get("n", ["20"])[0])
    except ValueError:
        n = 20
    return replay_last(AUDIT_PATH, n=max(0, min(n, 200)))


def dispatch(method: str, path: str, *, body: dict[str, Any] | None = None, query: str = "") -> tuple[int, Any]:
    """Dispatch a fixed HTTP allowlist; no route maps to arbitrary commands."""
    normalized = path.rstrip("/") or "/"
    payload = body or {}
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
    return 404, {"error": "not_found", "path": path, "method": method}


def _action_audit_event(event_type: str, out: dict[str, Any], cfg: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "timestamp": _utc_now(),
        "action": out.get("action"),
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
