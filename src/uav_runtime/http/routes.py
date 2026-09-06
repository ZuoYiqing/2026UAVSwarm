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
from uav_runtime.http.schemas import (
    BackendRequest,
    LandRequest,
    PlanMissionRequest,
    RequestValidationError,
    SmokeTakeoffRequest,
    TakeoffRequest,
)
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
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.replay import replay_last
from uav_runtime.http.state_store import ActionLifecycleError, RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleHandle, VehicleRegistry, VehicleRegistryError

AUDIT_PATH = os.environ.get("UAV_RUNTIME_AUDIT_PATH", "audit/runtime.audit.jsonl")
BRIDGE_VERSION = "0.1"
_DEFAULT_VEHICLE_CONFIG = (
    Path(__file__).resolve().parents[3]
    / "simulation"
    / "px4_gazebo"
    / "config"
    / "three_uav_sitl.json"
)
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
    # Establish/reuse the Registry-owned persistent transport.  If the external
    # endpoint is unavailable start_vehicle records a per-node offline reason;
    # the backend diagnostic may then use its strictly temporary closed probe.
    VEHICLE_REGISTRY.start_vehicle(handle.config.node_id)
    cfg = handle.config.to_mavlink_config()
    backend = Px4SitlBackend(cfg, handle.session)
    result = backend.readiness_diagnostic()
    result["backend"] = handle.config.backend
    result["backend_mode"] = handle.config.backend_mode
    result["transport_endpoint"] = cfg.transport_endpoint
    result.update({
        "node_id": handle.config.node_id,
        "resolved_node_id": handle.config.node_id,
        "node_selection": selection,
        "system_id": handle.config.system_id,
        "component_id": handle.config.component_id,
    })
    RUNTIME_STATE_STORE.update_backend_status(result, node_id=handle.config.node_id)
    event = {
        "type": "backend_probe_result", "timestamp": _utc_now(),
        "backend": handle.config.backend, "backend_mode": handle.config.backend_mode,
        "endpoint": cfg.transport_endpoint, "node_id": handle.config.node_id,
        "system_id": handle.config.system_id, "component_id": handle.config.component_id,
        "readiness": result.get("readiness"),
        "connect_probe": result.get("connect_probe"),
    }
    AuditLog(AUDIT_PATH).append(event)
    RUNTIME_STATE_STORE.record_event(event)
    return result


def _resolve_vehicle(req: BackendRequest, *, require_online: bool = False) -> tuple[VehicleHandle, str]:
    return VEHICLE_REGISTRY.resolve_vehicle(
        req.node_id,
        requested_endpoint=req.transport_endpoint or None,
        requested_system_id=req.system_id,
        requested_component_id=req.component_id,
        require_online=require_online,
    )


def _policy_checked_sitl_action(
    req: BackendRequest,
    handle: VehicleHandle,
    *,
    action: str,
    action_id: str | None = None,
    skill_group: str = "flight_core",
) -> tuple[str, dict[str, Any], RuntimeOrchestrator, ActionRequest]:
    cfg = handle.config.to_mavlink_config()
    rt = RuntimeOrchestrator(audit_path=AUDIT_PATH, adapter_name="mavlink", mavlink_backend_config=cfg)
    action_req = ActionRequest(
        action=action,
        params={},
        source=(
            CommandSource.GROUND_STATION
            if req.command_source == "ground_station"
            else CommandSource.SELF_LOCAL
        ),
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
        request_id=req.request_id or "",
        action_id=action_id or "",
        trace_id=req.trace_id or "",
        idempotency_key=req.idempotency_key,
    )
    request_event = {
        "type": "action_request", "timestamp": _utc_now(), "node_id": handle.config.node_id,
        "mission_id": action_req.mission_id, "action_type": action,
        "action_id": action_id, "request_id": action_req.request_id,
        "trace_id": req.trace_id, "command_source": req.command_source,
        "backend": handle.config.backend, "backend_mode": handle.config.backend_mode,
        "endpoint": handle.config.endpoint, "system_id": handle.config.system_id,
        "component_id": handle.config.component_id,
        "source": "runtime_http_bridge",
    }
    rt.audit.append(request_event)
    RUNTIME_STATE_STORE.record_event(request_event)
    decision_code, policy_event = rt.evaluate_policy_request(action_req)
    RUNTIME_STATE_STORE.record_policy_decision(policy_event)
    return decision_code, policy_event, rt, action_req


def _request_fingerprint(req: BackendRequest, *, action: str, smoke: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "action": action,
        "node_id": req.node_id,
        "system_id": req.system_id,
        "component_id": req.component_id,
        "command_source": req.command_source,
        "smoke": smoke,
    }
    for name in (
        "altitude_m",
        "auto_land",
        "threshold_ratio",
        "altitude_tolerance_m",
        "stable_duration_ms",
        "command_timeout_ms",
        "observe_timeout_ms",
    ):
        if hasattr(req, name):
            fields[name] = getattr(req, name)
    return fields


def _idempotent_response(action: dict[str, Any]) -> dict[str, Any]:
    return {
        **action,
        "idempotent_replay": True,
        "_http_status": 202 if action.get("status") in {"requested", "accepted", "executing"} else 200,
    }


def _finalize_action(
    *,
    action_id: str,
    out: dict[str, Any],
    handle: VehicleHandle,
    rt: RuntimeOrchestrator,
    cfg: Any,
    event_type: str,
) -> dict[str, Any]:
    correlated_ack_evidence = []
    for ack in out.get("ack_evidence") or []:
        correlated_ack_evidence.append({
            **ack,
            "timestamp": ack.get("timestamp") or _utc_now(),
            "action": out.get("action"),
            "action_id": action_id,
            "request_id": out.get("request_id"),
            "trace_id": out.get("trace_id"),
            "node_id": handle.config.node_id,
        })
    out["ack_evidence"] = correlated_ack_evidence
    current = RUNTIME_STATE_STORE.action(action_id)
    if current.get("status") in {"policy_rejected", "succeeded", "failed", "timed_out"}:
        current = RUNTIME_STATE_STORE.attach_terminal_evidence(
            action_id,
            ack_evidence=correlated_ack_evidence,
            completion_evidence=out.get("completion_evidence"),
            completion_state=out.get("completion_state"),
        )
        # A concurrent LAND preemption (or any other terminal transition) is
        # authoritative over a late result from the superseded adapter call.
        out = {**out, **current, "lifecycle_status": current["status"]}
        VEHICLE_REGISTRY.release_action(
            handle.config.node_id,
            action_id,
            error=out.get("failure_reason"),
        )
        for audit_type in (event_type, "action_result"):
            event = _action_audit_event(audit_type, out, cfg, handle.config.node_id)
            rt.audit.append(event)
            RUNTIME_STATE_STORE.record_event(event)
        return out
    failure_reason = str(out.get("failure_reason") or "")
    completion_state = str(out.get("completion_state") or "")
    if out.get("result") == "pass":
        lifecycle_status = "succeeded"
    elif completion_state == "timed_out" or "timeout" in failure_reason:
        lifecycle_status = "timed_out"
    else:
        lifecycle_status = "failed"
    out["status"] = lifecycle_status
    out["lifecycle_status"] = lifecycle_status
    if lifecycle_status != "succeeded" and out.get("code") in {None, "", "px4_sitl_action_failed"}:
        out["code"] = failure_reason or "action_failed"
    RUNTIME_STATE_STORE.finish_action(action_id, out)
    VEHICLE_REGISTRY.release_action(
        handle.config.node_id,
        action_id,
        error=out.get("failure_reason"),
    )
    for audit_type in (event_type, "action_result"):
        event = _action_audit_event(audit_type, out, cfg, handle.config.node_id)
        rt.audit.append(event)
        RUNTIME_STATE_STORE.record_event(event)
    return out


def _execute_flight_action(
    req: BackendRequest,
    *,
    action: str,
    smoke: bool = False,
) -> dict[str, Any]:
    handle, selection = _resolve_vehicle(req, require_online=True)
    cfg = handle.config.to_mavlink_config()
    action_record, created = RUNTIME_STATE_STORE.request_action(
        action,
        backend=handle.config.backend,
        backend_mode=handle.config.backend_mode,
        node_id=handle.config.node_id,
        system_id=handle.config.system_id,
        component_id=handle.config.component_id,
        request_id=req.request_id,
        trace_id=req.trace_id,
        idempotency_key=req.idempotency_key,
        request_fingerprint=_request_fingerprint(req, action=action, smoke=smoke),
        source=req.command_source,
    )
    if not created:
        return _idempotent_response(action_record)
    action_id = str(action_record["action_id"])
    req.request_id = str(action_record["request_id"])
    req.trace_id = str(action_record["trace_id"])
    req.idempotency_key = str(action_record["idempotency_key"])
    identity = {
        "action_id": action_id,
        "request_id": req.request_id,
        "trace_id": req.trace_id,
        "idempotency_key": req.idempotency_key,
        "node_id": handle.config.node_id,
        "resolved_node_id": handle.config.node_id,
        "node_selection": selection,
        "backend": handle.config.backend,
        "backend_mode": handle.config.backend_mode,
        "endpoint": handle.config.endpoint,
        "system_id": handle.config.system_id,
        "component_id": handle.config.component_id,
        "command_source": req.command_source,
    }
    try:
        decision_code, policy_event, rt, action_req = _policy_checked_sitl_action(
            req,
            handle,
            action=action,
            action_id=action_id,
        )
    except Exception as exc:
        failure = {
            **identity,
            "action": action,
            "result": "fail",
            "accepted": False,
            "execution_admitted": False,
            "lifecycle_status": "failed",
            "failure_reason": "policy_evaluation_exception",
            "code": "policy_evaluation_exception",
            "error_class": type(exc).__name__,
            "ack_evidence": [],
            "completion_evidence": None,
        }
        RUNTIME_STATE_STORE.finish_action(action_id, failure)
        RUNTIME_STATE_STORE.record_event(
            _action_audit_event("action_result", failure, cfg, handle.config.node_id)
        )
        raise
    if decision_code != "allow":
        out = {
            **identity,
            "action": action,
            "result": "fail",
            "accepted": False,
            "execution_admitted": False,
            "status": "policy_rejected",
            "lifecycle_status": "policy_rejected",
            "failure_reason": f"policy_{decision_code}",
            "code": f"policy_{decision_code}",
            "policy_decision": policy_event,
            "ack_evidence": [],
            "completion_evidence": None,
        }
        RUNTIME_STATE_STORE.transition_action(action_id, "policy_rejected", **out)
        event = _action_audit_event("action_result", out, cfg, handle.config.node_id)
        rt.audit.append(event)
        RUNTIME_STATE_STORE.record_event(event)
        return out

    RUNTIME_STATE_STORE.transition_action(
        action_id,
        "accepted",
        policy_decision=policy_event,
        execution_admitted=True,
    )
    try:
        admission = VEHICLE_REGISTRY.admit_action(handle.config.node_id, action, action_id)
    except VehicleRegistryError as exc:
        out = {
            **identity,
            "action": action,
            "result": "fail",
            "accepted": False,
            "execution_admitted": False,
            "failure_reason": exc.code,
            "code": exc.code,
            "policy_decision": policy_event,
            "details": exc.details,
            "ack_evidence": [],
            "completion_evidence": None,
            "lifecycle_status": "failed",
        }
        RUNTIME_STATE_STORE.finish_action(action_id, out)
        out["status"] = "failed"
        out["_http_status"] = exc.status
        event = _action_audit_event("action_result", out, cfg, handle.config.node_id)
        rt.audit.append(event)
        RUNTIME_STATE_STORE.record_event(event)
        return out
    preempted_action_id = admission.get("preempted_action_id")
    if preempted_action_id:
        try:
            RUNTIME_STATE_STORE.finish_action(
                str(preempted_action_id),
                {
                    "action": admission.get("preempted_action"),
                    "result": "fail",
                    "failure_reason": "action_preempted_by_land",
                    "code": "action_preempted_by_land",
                    "preempted_by_action_id": action_id,
                    "lifecycle_status": "failed",
                },
            )
            preempted = RUNTIME_STATE_STORE.action(str(preempted_action_id))
        except ActionLifecycleError as exc:
            # Registry admission is the safety authority. An orphaned old lease
            # must not prevent a controlled LAND from continuing.
            RUNTIME_STATE_STORE.record_event({
                "type": "action_preemption_orphan",
                "timestamp": _utc_now(),
                "node_id": handle.config.node_id,
                "action_id": preempted_action_id,
                "preempted_by_action_id": action_id,
                "code": exc.code,
            })
        else:
            event = _action_audit_event(
                "action_preempted",
                preempted,
                cfg,
                handle.config.node_id,
            )
            rt.audit.append(event)
            RUNTIME_STATE_STORE.record_event(event)
    cancel_event = admission["cancel_event"]
    RUNTIME_STATE_STORE.transition_action(action_id, "executing")
    try:
        backend = Px4SitlBackend(cfg, handle.session)
        rt.gateway.register(Px4RuntimeActionAdapter(backend))
        started_event = {
            **_adapter_event("adapter_execution_started", handle, action),
            "action_id": action_id,
            "request_id": req.request_id,
            "trace_id": req.trace_id,
        }
        rt.audit.append(started_event)
        RUNTIME_STATE_STORE.record_event(started_event)
        if action == "takeoff" and smoke:
            assert isinstance(req, SmokeTakeoffRequest)
            action_req.params = {
                "altitude_m": req.altitude_m,
                "auto_land": req.auto_land,
                "command_timeout_ms": req.command_timeout_ms,
                "observe_timeout_ms": req.observe_timeout_ms,
                "threshold_ratio": req.threshold_ratio,
                "_cancel_event": cancel_event,
            }
        elif action == "takeoff":
            assert isinstance(req, TakeoffRequest)
            action_req.params = {
                "altitude_m": req.altitude_m,
                "altitude_tolerance_m": req.altitude_tolerance_m,
                "stable_duration_ms": req.stable_duration_ms,
                "command_timeout_ms": req.command_timeout_ms,
                "observe_timeout_ms": req.observe_timeout_ms,
                "completion_mode": "operational_stable_altitude",
                "_cancel_event": cancel_event,
            }
        else:
            action_req.params = {
                "command_timeout_ms": req.command_timeout_ms,
                "observe_timeout_ms": req.observe_timeout_ms,
                "_cancel_event": cancel_event,
            }
        gateway_result = rt.gateway.execute("mavlink", action_req)
        out = dict(gateway_result.get("raw_result") or {
            "action": action,
            "result": "fail",
            "failure_reason": gateway_result.get("code") or "adapter_execution_failed",
            "accepted": False,
            "code": gateway_result.get("code") or "adapter_execution_failed",
            "error_class": gateway_result.get("error_class"),
        })
        out.setdefault("accepted", gateway_result.get("accepted", False))
        out.setdefault("code", gateway_result.get("code"))
        out.update(identity)
        out["execution_admitted"] = True
        out["policy_decision"] = policy_event
        result_event = {
            **_adapter_event("adapter_execution_result", handle, action, result=out),
            "action_id": action_id,
            "request_id": req.request_id,
            "trace_id": req.trace_id,
        }
        rt.audit.append(result_event)
        RUNTIME_STATE_STORE.record_event(result_event)
    except Exception as exc:
        out = {
            **identity,
            "action": action,
            "result": "fail",
            "accepted": False,
            "execution_admitted": True,
            "status": "failed",
            "lifecycle_status": "failed",
            "failure_reason": "adapter_execution_exception",
            "code": "adapter_execution_exception",
            "error_class": type(exc).__name__,
            "policy_decision": policy_event,
            "ack_evidence": [],
            "completion_evidence": None,
        }
        RUNTIME_STATE_STORE.finish_action(action_id, out)
        VEHICLE_REGISTRY.release_action(
            handle.config.node_id,
            action_id,
            error="adapter_execution_exception",
        )
        event = _action_audit_event("action_result", out, cfg, handle.config.node_id)
        rt.audit.append(event)
        RUNTIME_STATE_STORE.record_event(event)
        raise
    return _finalize_action(
        action_id=action_id,
        out=out,
        handle=handle,
        rt=rt,
        cfg=cfg,
        event_type="http_smoke_takeoff" if smoke else f"http_{action}",
    )


def smoke_takeoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility smoke route; its loose threshold is not operational success."""
    return _execute_flight_action(SmokeTakeoffRequest.from_json(payload), action="takeoff", smoke=True)


def takeoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Operator/Agent takeoff using stable target-altitude completion evidence."""
    return _execute_flight_action(TakeoffRequest.from_json(payload), action="takeoff")


def land(payload: dict[str, Any]) -> dict[str, Any]:
    """Controlled LAND requiring fresh landed-state and disarmed evidence."""
    return _execute_flight_action(LandRequest.from_json(payload), action="land")


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


def publish_simulation_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept Simulation-owned integrated health evidence; never infer it from PX4."""
    try:
        evidence = RUNTIME_STATE_STORE.update_simulation_evidence(payload)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            "invalid_simulation_evidence",
            "body",
            str(exc),
        ) from exc
    return {"accepted": True, "evidence": evidence, "status": RUNTIME_STATE_STORE.simulation_status()}


def publish_coordinate_calibration(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept Simulation-produced local-origin calibration for Runtime fusion."""
    try:
        calibration = RUNTIME_STATE_STORE.update_coordinate_calibration(payload)
    except VehicleRegistryError:
        raise
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            "invalid_coordinate_calibration",
            "body",
            str(exc),
        ) from exc
    return {"accepted": True, "calibration": calibration}


def action_status(action_id: str) -> dict[str, Any]:
    return RUNTIME_STATE_STORE.action(action_id)


def action_lifecycle_recent(query: str = "") -> list[dict[str, Any]]:
    values = parse_qs(query, keep_blank_values=True)
    return RUNTIME_STATE_STORE.recent_actions(limit=_query_int(values, "n", 20))


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
    except ActionLifecycleError as exc:
        return exc.status, {"version": "1.1", "timestamp": _utc_now(), **exc.to_dict(), "source": "runtime_state_store"}
    except RequestValidationError as exc:
        return 400, {"version": "1.0", "timestamp": _utc_now(), **exc.to_dict(), "source": "runtime_http_bridge"}


def _dispatch_known(method: str, normalized: str, *, path: str, payload: dict[str, Any], query: str) -> tuple[int, Any]:
    if method == "GET" and normalized == "/api/health":
        return 200, health()
    if method == "POST" and normalized == "/api/backend/check":
        return 200, check_backend(payload)
    if method == "POST" and normalized == "/api/actions/smoke-takeoff":
        result = smoke_takeoff(payload)
        return int(result.pop("_http_status", 200)), result
    if method == "POST" and normalized == "/api/actions/takeoff":
        result = takeoff(payload)
        return int(result.pop("_http_status", 200)), result
    if method == "POST" and normalized == "/api/actions/land":
        result = land(payload)
        return int(result.pop("_http_status", 200)), result
    if method == "POST" and normalized == "/api/simulation/evidence":
        return 200, publish_simulation_evidence(payload)
    if method == "POST" and normalized == "/api/coordinates/calibration":
        return 200, publish_coordinate_calibration(payload)
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
    if method == "GET" and normalized == "/api/actions/lifecycle":
        return 200, action_lifecycle_recent(query)
    if method == "GET" and normalized.startswith("/api/actions/"):
        return 200, action_status(normalized.rsplit("/", 1)[-1])
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
        "action_id": out.get("action_id"),
        "request_id": out.get("request_id"),
        "trace_id": out.get("trace_id"),
        "idempotency_key": out.get("idempotency_key"),
        "action": out.get("action"),
        "node_id": node_id,
        "backend": out.get("backend", "px4_sitl"),
        "backend_mode": out.get("backend_mode", cfg.backend_mode),
        "endpoint": out.get("endpoint", cfg.transport_endpoint),
        "system_id": out.get("system_id", cfg.target_system),
        "component_id": out.get("component_id", cfg.target_component),
        "resolved_node_id": out.get("resolved_node_id", node_id),
        "node_selection": out.get("node_selection"),
        "policy_decision": out.get("policy_decision"),
        "ack": {"arm_ack": out.get("arm_ack"), "takeoff_ack": out.get("takeoff_ack"), "land_ack": out.get("land_ack")},
        "altitude_observation": out.get("altitude_observation"),
        "ack_evidence": out.get("ack_evidence"),
        "completion_evidence": out.get("completion_evidence"),
        "completion_state": out.get("completion_state"),
        "max_altitude_m": out.get("max_altitude_m"),
        "threshold_reached": out.get("threshold_reached"),
        "result": out.get("result"),
        "failure_reason": out.get("failure_reason"),
        "accepted": out.get("accepted"), "status": out.get("status"),
        "code": out.get("code"), "error_class": out.get("error_class"),
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
        "system_id": handle.config.system_id,
        "component_id": handle.config.component_id,
        "result": result.get("result") if result else None,
        "failure_reason": result.get("failure_reason") if result else None,
        "accepted": result.get("accepted") if result else None,
        "status": result.get("status") if result else None,
        "code": result.get("code") if result else None,
        "error_class": result.get("error_class") if result else None,
    }
