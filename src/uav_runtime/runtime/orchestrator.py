"""本轮最后修补点：非 ALLOW 路径严格消费 gate 主因；若缺失主因则触发 contract violation。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import DECISION_DEFER, DECISION_REQUIRE_CONFIRM, unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME
from uav_runtime.runtime.event_bus import EventBus


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _to_canonical_str(value: object | None) -> str | None:
    """v0.1 baseline payload shape: enum -> value, str -> itself."""
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return str(value)


def _demo_link_state_from_request(req: ActionRequest) -> LinkState:
    """Demo-only: optional control-plane state input carried in params."""
    raw = req.params.get("demo_link_state") if isinstance(req.params, dict) else None
    if not isinstance(raw, str):
        return LinkState.HEALTHY
    v = raw.strip().lower()
    if v == LinkState.LOST.value:
        return LinkState.LOST
    if v == LinkState.DEGRADED.value:
        return LinkState.DEGRADED
    return LinkState.HEALTHY


class RuntimeOrchestrator:
    def __init__(self, audit_path: str = "audit/runtime.audit.jsonl", adapter_name: str = DEFAULT_ADAPTER_NAME) -> None:
        self.bus = EventBus()
        self.audit = AuditLog(audit_path)
        self.adapter_name = adapter_name
        self.gateway = AdapterGateway({"fake": FakeAdapter(), "mavlink": MavlinkAdapter()})

    def _build_policy_context(self, req: ActionRequest) -> PolicyContext:
        return PolicyContext(
            source=req.source,
            scope=req.requested_scope or req.scope,
            link_state=_demo_link_state_from_request(req),
            mission_id=req.mission_id,
            current_phase="nominal",
            active_controller_source=req.source.value,
            active_delegations=[req.delegation_id] if req.delegation_id else [],
            running_actions=[],
            pending_takeovers=[],
            runtime_limits={"max_queue": 64, "max_concurrency": 1},
            active_profile="default_profile",
            flags={"context_skeleton_ready": True},
        )

    def _build_profile(self) -> PolicyProfile:
        return PolicyProfile(
            name="default_profile",
            allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
            denied_skill_groups=[],
            max_risk_when_link_lost=1,
            require_confirm_for_risk_ge=3,
            allow_without_confirm=False,
            max_concurrent_actions=1,
            confirm_rules=[],
            degradation_behavior={},
            fallback_behavior={},
            recovery_behavior={},
            runtime_constraints={},
        )

    def _blocked_like_result(self, request_id: str, status: str, code: str) -> dict:
        return {
            "request_id": request_id,
            "status": status,
            "code": code,
            "message": code,
            "evidence_ref": None,
            "timestamps": {"decision_time": _utc_now_iso()},
            "accepted": False,
            "detail": code,
            "adapter": "",
        }

    def _require_primary_reason(self, decision_code: str, primary_reason_code: str | None) -> str:
        if not primary_reason_code:
            raise AssertionError(f"contract violation: primary_reason_code missing for decision {decision_code}")
        return primary_reason_code

    def handle_action_request(self, req: ActionRequest) -> dict:
        request_id = req.request_id or f"req-{uuid.uuid4().hex[:10]}"
        req.request_id = request_id
        if not req.action_type:
            req.action_type = req.action
        if not req.mission_id:
            req.mission_id = "mission-default"
        if not req.idempotency_key:
            req.idempotency_key = request_id

        ctx = self._build_policy_context(req)
        actx = RuntimeActionContext(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            action=req.action_type,
            risk_level=max(0, int(req.risk_hint)),
            require_confirm=bool(req.requires_confirmation_hint),
        )
        profile = self._build_profile()

        decision = unified_policy_gate(ctx, actx, profile)
        decision_code = decision.decision_code.value if isinstance(decision.decision_code, DecisionCode) else decision.decision_code

        policy_decision_event = {
            "type": "policy_decision_event",
            "request_id": request_id,
            "mission_id": req.mission_id,
            "decision_code": decision_code,
            "primary_reason_code": decision.primary_reason_code,
            "secondary_reason_codes": decision.secondary_reason_codes,
            "effective_scope": _to_canonical_str(decision.effective_scope),
            "effective_profile_id": _to_canonical_str(decision.effective_profile_id),
            "effective_risk_level": decision.effective_risk_level,
            "enforced_constraints": decision.enforced_constraints,
            "handover_plan": {
                "mode": decision.handover_plan.mode,
                "takeover_target_request_id": decision.handover_plan.takeover_target_request_id,
            },
            "policy_trace_id": decision.policy_trace_id,
            "audit_tags": decision.audit_tags,
            "timestamp": _utc_now_iso(),
        }
        self.bus.publish("policy_decision_event", policy_decision_event)
        self.audit.append(policy_decision_event)

        if decision_code == DecisionCode.DENY.value:
            reason = self._require_primary_reason(decision_code, decision.primary_reason_code)
            return self._blocked_like_result(request_id, "blocked", reason)
        if decision_code == DECISION_DEFER:
            reason = self._require_primary_reason(decision_code, decision.primary_reason_code)
            return self._blocked_like_result(request_id, "deferred", reason)
        if decision_code == DECISION_REQUIRE_CONFIRM:
            reason = self._require_primary_reason(decision_code, decision.primary_reason_code)
            return self._blocked_like_result(request_id, "waiting_confirmation", reason)
        if decision_code == DecisionCode.PREEMPT.value:
            reason = self._require_primary_reason(decision_code, decision.primary_reason_code)
            return self._blocked_like_result(request_id, "handover_pending", reason)

        # ALLOW -> execute selected adapter
        result = self.gateway.execute(self.adapter_name, req)
        normalized = {
            "request_id": request_id,
            "status": result.get("status", "accepted" if result.get("accepted") else "rejected"),
            "code": result.get("code", result.get("detail", "")),
            "message": result.get("message", result.get("detail", "")),
            "evidence_ref": result.get("evidence_ref"),
            "timestamps": {"result_time": _utc_now_iso()},
            "accepted": result.get("accepted", False),
            "detail": result.get("detail", ""),
            "adapter": result.get("adapter", ""),
        }
        self.audit.append({"type": "action_result", **normalized})
        return normalized


def build_demo_request() -> ActionRequest:
    return ActionRequest(
        action="hover",
        params={"duration_s": 5},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        mission_id="mission-demo",
        action_type="hover",
        skill_group="flight_core",
        target_set=["self"],
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
        idempotency_key="demo-hover-001",
    )
