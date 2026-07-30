"""Console-facing DTOs for read-only Runtime API routes.

These ViewModels are presentation contracts for the local swarm-console.  They
are deliberately separated from runtime execution objects: returning a ViewModel
never authorizes an action, bypasses Policy Gate, or opens a PX4/adapter path.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _stable_id(prefix: str, seed: Any) -> str:
    encoded = repr(seed).encode("utf-8", errors="replace")
    return f"{prefix}_{hashlib.sha1(encoded).hexdigest()[:12]}"


@dataclass(slots=True)
class EventEnvelope:
    """Unified console event envelope for Audit, Replay, Timeline, and pipelines."""

    event_id: str
    trace_id: str | None
    mission_id: str | None
    session_id: str | None
    parent_event_id: str | None
    event_type: str
    severity: str
    source: str
    node_id: str | None
    timestamp: str | None
    summary: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActionResultView:
    """Console projection of an action result; display-only, not execution state."""

    action_id: str
    trace_id: str | None
    request_id: str | None
    mission_id: str | None
    node_id: str | None
    action_type: str | None
    backend: str | None
    backend_mode: str | None
    adapter: str | None
    status: str
    result: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    policy_decision: dict[str, Any] | None
    command_results: list[dict[str, Any]]
    observations: dict[str, Any]
    cleanup: dict[str, Any]
    failure_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PolicyDecisionView:
    """Console projection of Policy Gate output for review and audit display."""

    decision_id: str
    trace_id: str | None
    request_id: str | None
    node_id: str | None
    mission_id: str | None
    action_type: str | None
    decision_code: str | None
    primary_reason_code: str | None
    secondary_reason_codes: list[str]
    effective_profile_id: str | None
    requested_scope: str | None
    effective_scope: str | None
    risk: dict[str, Any]
    constraints: list[dict[str, Any]]
    explanation: str | None
    audit_tags: list[str]
    timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillManifest:
    """Capability Registry projection for the Skills UI, not an execution grant."""

    skill_id: str
    action_type: str
    display_name: str
    description: str
    domain: str
    skill_group: str
    risk_level: int | str
    enabled: bool
    supported_backends: list[str]
    supported_adapters: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    usage: dict[str, Any]
    safety: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MissionPlanView:
    """Console planning view derived from planner IR, not a runtime executor."""

    plan_id: str
    mission_type: str
    status: str
    steps: list[dict[str, Any]]
    graph: dict[str, Any]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimePipelineView:
    """Read-only console pipeline metrics; initially derived from audit/replay."""

    trace_id: str | None
    session_id: str | None
    status: str
    stages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NodeState:
    """Console entity state for map/detail views; display-only and source-tagged."""

    node_id: str
    node_type: str
    status: str
    backend: str | None
    current_task: str | None
    battery_percent: int | None
    link_quality: str | None
    rssi_dbm: int | None
    position: dict[str, Any]
    attitude: dict[str, Any]
    velocity: dict[str, Any]
    health: dict[str, Any]
    capabilities: list[str]
    last_seen: str | None
    source: str = "derived"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TelemetryLatest:
    """Latest telemetry response contract for polling before WebSocket exists."""

    timestamp: str | None
    backend: str | None
    nodes: list[dict[str, Any]]
    source: str = "derived"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeSnapshot:
    """Top-level console snapshot for overview and 3D status pages."""

    snapshot_id: str
    timestamp: str
    runtime_status: dict[str, Any]
    fleet_summary: dict[str, Any]
    nodes: list[dict[str, Any]]
    missions: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    source: str = "derived"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def event_to_envelope(event: dict[str, Any], *, index: int = 0) -> EventEnvelope:
    """Convert old or new audit events into EventEnvelope without failing on gaps.

    Existing audit JSONL records predate the console contract and may miss IDs,
    trace fields, node IDs, or timestamps.  The raw event is preserved in payload
    so future replay tools can still inspect original data.
    """
    event_type = str(event.get("event_type") or event.get("type") or "replay_marker")
    timestamp = event.get("timestamp")
    summary = str(event.get("summary") or event.get("message") or f"{event_type} event")
    if timestamp is None:
        summary = f"{summary} (unknown timestamp)"
    return EventEnvelope(
        event_id=str(event.get("event_id") or _stable_id("evt", {"index": index, "event": event})),
        trace_id=event.get("trace_id") or event.get("request_id"),
        mission_id=event.get("mission_id"),
        session_id=event.get("session_id"),
        parent_event_id=event.get("parent_event_id"),
        event_type=event_type,
        severity=str(event.get("severity") or _severity_for_event(event)),
        source=str(event.get("source") or _source_for_event(event_type)),
        node_id=event.get("node_id"),
        timestamp=str(timestamp) if timestamp is not None else None,
        summary=summary,
        payload=dict(event),
    )


def _severity_for_event(event: dict[str, Any]) -> str:
    if event.get("failure_reason") or event.get("result") == "fail":
        return "error"
    if event.get("decision_code") in {"deny", "blocked"}:
        return "warning"
    return "info"


def _source_for_event(event_type: str) -> str:
    if "policy" in event_type:
        return "policy_gate"
    if "telemetry" in event_type:
        return "telemetry"
    if "backend" in event_type or "px4" in event_type:
        return "backend"
    if "agent" in event_type or "plan" in event_type:
        return "agent_planner"
    if "action" in event_type or "adapter" in event_type:
        return "runtime"
    return "audit"


def event_to_action_result_view(event: dict[str, Any], *, index: int = 0) -> ActionResultView:
    ack = event.get("ack") if isinstance(event.get("ack"), dict) else {}
    command_results = _flatten_ack_dict(ack)
    observations = dict(event.get("altitude_observation") or {})
    if event.get("max_altitude_m") is not None:
        observations.setdefault("max_altitude_m", event.get("max_altitude_m"))
    if event.get("threshold_reached") is not None:
        observations.setdefault("threshold_reached", event.get("threshold_reached"))
    return ActionResultView(
        action_id=str(event.get("action_id") or _stable_id("act", {"index": index, "event": event})),
        trace_id=event.get("trace_id") or event.get("request_id"),
        request_id=event.get("request_id"),
        mission_id=event.get("mission_id"),
        node_id=event.get("node_id"),
        action_type=event.get("action") or event.get("action_type"),
        backend=event.get("backend"),
        backend_mode=event.get("backend_mode"),
        adapter=event.get("adapter") or _adapter_from_backend(event.get("backend")),
        status="failed" if event.get("result") == "fail" or event.get("failure_reason") else "succeeded",
        result=event.get("result"),
        started_at=event.get("started_at") or event.get("timestamp"),
        finished_at=event.get("finished_at") or event.get("timestamp"),
        duration_ms=event.get("duration_ms"),
        policy_decision=event.get("policy_decision"),
        command_results=command_results,
        observations=observations,
        cleanup={"auto_land": event.get("auto_land"), "land_ack": ack.get("land_ack")},
        failure_reason=event.get("failure_reason"),
    )


def _flatten_ack_dict(ack: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for key, value in ack.items():
        if not isinstance(value, dict):
            continue
        results.append({
            "command": value.get("command_name") or value.get("command") or key,
            "accepted": value.get("result") == 0 or value.get("result_name") == "MAV_RESULT_ACCEPTED",
            "result": value.get("result"),
            "result_name": value.get("result_name"),
            "timeout": bool(value.get("timeout", False)),
        })
    return results


def _adapter_from_backend(backend: Any) -> str | None:
    if backend == "px4_sitl":
        return "mavlink"
    return None


def event_to_policy_decision_view(event: dict[str, Any], *, index: int = 0) -> PolicyDecisionView:
    return PolicyDecisionView(
        decision_id=str(event.get("decision_id") or _stable_id("pd", {"index": index, "event": event})),
        trace_id=event.get("trace_id") or event.get("request_id"),
        request_id=event.get("request_id"),
        node_id=event.get("node_id"),
        mission_id=event.get("mission_id"),
        action_type=event.get("action_type") or event.get("action"),
        decision_code=event.get("decision_code"),
        primary_reason_code=event.get("primary_reason_code"),
        secondary_reason_codes=list(event.get("secondary_reason_codes") or []),
        effective_profile_id=event.get("effective_profile_id"),
        requested_scope=event.get("requested_scope"),
        effective_scope=event.get("effective_scope"),
        risk=dict(event.get("risk") or {"level": None, "score": None, "factors": []}),
        constraints=list(event.get("constraints") or []),
        explanation=event.get("explanation"),
        audit_tags=list(event.get("audit_tags") or []),
        timestamp=event.get("timestamp"),
    )


def capability_to_skill_manifest(row: dict[str, Any]) -> SkillManifest:
    action_type = str(row.get("action_type") or "")
    dangerous = bool(row.get("dangerous", False))
    supported_adapters = list(row.get("supported_adapters") or [])
    return SkillManifest(
        skill_id=action_type,
        action_type=action_type,
        display_name=_display_name(action_type),
        description=str(row.get("notes") or f"{action_type} capability"),
        domain=str(row.get("domain") or "system"),
        skill_group=str(row.get("skill_group") or "generic"),
        risk_level=row.get("risk_level", 1),
        enabled=not dangerous and str(row.get("policy_default", "allow")) != "deny",
        supported_backends=_supported_backends(supported_adapters),
        supported_adapters=supported_adapters,
        input_schema=_default_input_schema(action_type),
        output_schema={"type": "object", "additionalProperties": True},
        usage={"total_calls": 0, "success_rate": None, "avg_duration_s": None, "last_used_at": None, "source": "default"},
        safety={
            "requires_policy_check": True,
            "requires_operator_confirm": bool(row.get("requires_confirmation_by_default", False)),
            "dangerous": dangerous,
            "sitl_only": "mavlink" in supported_adapters and "payload" not in supported_adapters,
            "fallback_allowed": bool(row.get("fallback_allowed", False)),
        },
    )


def _display_name(action_type: str) -> str:
    return action_type.replace("_", " ").title()


def _supported_backends(adapters: list[str]) -> list[str]:
    backends = []
    if "mavlink" in adapters:
        backends.append("px4_sitl")
    if "fake" in adapters:
        backends.append("fake")
    if "payload" in adapters:
        backends.append("payload")
    return backends


def _default_input_schema(action_type: str) -> dict[str, Any]:
    if action_type == "takeoff":
        return {"type": "object", "properties": {"altitude_m": {"type": "number", "minimum": 1, "maximum": 120}}, "required": ["altitude_m"]}
    return {"type": "object", "additionalProperties": True}
