"""为什么要这样修：把最小链路编排对齐到 contract 字段与事件形状，同时保持 skeleton 与纯本地 stub。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.event_bus import EventBus


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class RuntimeOrchestrator:
    def __init__(self, audit_path: str = "audit/runtime.audit.jsonl") -> None:
        self.bus = EventBus()
        self.audit = AuditLog(audit_path)
        self.gateway = AdapterGateway({"fake": FakeAdapter()})

    def _build_policy_context(self, req: ActionRequest) -> PolicyContext:
        return PolicyContext(
            source=req.source,
            scope=req.requested_scope or req.scope,
            link_state=LinkState.HEALTHY,
            active_profile="default_profile",
            flags={"delegation_present": bool(req.delegation_id)},
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
        )

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
            "effective_scope": str(decision.effective_scope),
            "effective_profile_id": decision.effective_profile_id,
            "effective_risk_level": decision.effective_risk_level,
            "enforced_constraints": decision.enforced_constraints,
            "handover_plan": {"mode": decision.handover_plan.mode},
            "policy_trace_id": decision.policy_trace_id,
            "audit_tags": decision.audit_tags,
            "timestamp": _utc_now_iso(),
        }
        self.bus.publish("policy_decision_event", policy_decision_event)
        self.audit.append(policy_decision_event)

        if decision_code != DecisionCode.ALLOW.value:
            return {
                "request_id": request_id,
                "status": "blocked",
                "code": decision.primary_reason_code or "POLICY.BLOCKED",
                "message": decision.primary_reason_code or "blocked_by_policy",
                "evidence_ref": None,
                "timestamps": {"decision_time": _utc_now_iso()},
                "accepted": False,
                "detail": decision.primary_reason_code or "blocked_by_policy",
                "adapter": "",
            }

        result = self.gateway.execute("fake", req)
        normalized = {
            "request_id": request_id,
            "status": result.get("status", "accepted" if result.get("accepted") else "rejected"),
            "code": result.get("code", result.get("detail", "")),
            "message": result.get("message", result.get("detail", "")),
            "evidence_ref": None,
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
