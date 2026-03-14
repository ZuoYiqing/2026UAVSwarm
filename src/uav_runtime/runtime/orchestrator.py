"""本轮修补点：细分 decision 返回路径，并补齐 context/profile 合同字段占位（骨架）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import DECISION_DEFER, DECISION_REQUIRE_CONFIRM, unified_policy_gate
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
        # skeleton placeholder aligned to future contract keys
        context_ext = {
            "mission_id": req.mission_id,
            "current_phase": "nominal",
            "active_controller_source": req.source.value,
            "active_delegations": [req.delegation_id] if req.delegation_id else [],
            "running_actions": [],
            "pending_takeovers": [],
            "runtime_limits": {"max_queue": 64, "max_concurrency": 1},
        }
        return PolicyContext(
            source=req.source,
            scope=req.requested_scope or req.scope,
            link_state=LinkState.HEALTHY,
            active_profile="default_profile",
            flags={"contract_context_ext": bool(context_ext)},
        )

    def _build_profile(self) -> PolicyProfile:
        profile = PolicyProfile(
            name="default_profile",
            allowed_skill_groups=["flight_core", "payload", "coordination", "generic"],
            denied_skill_groups=[],
            max_risk_when_link_lost=1,
            require_confirm_for_risk_ge=3,
            allow_without_confirm=False,
            max_concurrent_actions=1,
        )
        # skeleton placeholder aligned to future contract keys
        profile_ext = {
            "confirm_rules": [],
            "degradation_behavior": {},
            "fallback_behavior": {},
            "recovery_behavior": {},
            "runtime_constraints": {},
        }
        _ = profile_ext
        return profile

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
            return self._blocked_like_result(request_id, "blocked", decision.primary_reason_code or "REASON.DENY")
        if decision_code == DECISION_DEFER:
            return self._blocked_like_result(request_id, "deferred", decision.primary_reason_code or "REASON.DEFER")
        if decision_code == DECISION_REQUIRE_CONFIRM:
            return self._blocked_like_result(
                request_id,
                "waiting_confirmation",
                decision.primary_reason_code or "REASON.CONFIRMATION.REQUIRED",
            )
        if decision_code == DecisionCode.PREEMPT.value:
            return self._blocked_like_result(request_id, "handover_pending", decision.primary_reason_code or "REASON.PREEMPT")

        # ALLOW -> execute adapter
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
