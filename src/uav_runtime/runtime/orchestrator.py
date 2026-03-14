"""最小链路编排（action_request -> policy_decision_event -> adapter -> result）。"""
from __future__ import annotations

import uuid

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.event_bus import EventBus


class RuntimeOrchestrator:
    def __init__(self, audit_path: str = "audit/runtime.audit.jsonl") -> None:
        self.bus = EventBus()
        self.audit = AuditLog(audit_path)
        self.gateway = AdapterGateway({"fake": FakeAdapter()})

    def handle_action_request(self, req: ActionRequest) -> dict:
        ctx = PolicyContext(source=req.source, scope=req.scope, link_state=LinkState.HEALTHY)
        actx = RuntimeActionContext(task_id=f"task-{uuid.uuid4().hex[:8]}", action=req.action, risk_level=1)
        profile = PolicyProfile(name="default", allow_without_confirm=True)
        decision = unified_policy_gate(ctx, actx, profile)
        d_event = {"type": "policy_decision_event", "decision": decision.decision.value, "reason": decision.reason}
        self.bus.publish("policy_decision_event", d_event)
        self.audit.append(d_event)
        if decision.decision != DecisionCode.ALLOW:
            return {"accepted": False, "detail": decision.reason}
        result = self.gateway.execute("fake", req)
        self.audit.append({"type": "action_result", **result})
        return result


def build_demo_request() -> ActionRequest:
    return ActionRequest(
        action="hover",
        params={"duration_s": 5},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
    )
