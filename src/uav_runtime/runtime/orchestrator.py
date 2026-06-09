"""本轮最后修补点：非 ALLOW 路径严格消费 gate 主因；若缺失主因则触发 contract violation。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter
from uav_runtime.adapters.payload_adapter import PayloadAdapter
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import DECISION_DEFER, DECISION_REQUIRE_CONFIRM, unified_policy_gate
from uav_runtime.policy.profile import PolicyProfile, build_policy_profile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, DecisionCode, LinkState
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME
from uav_runtime.runtime.event_bus import EventBus
from uav_runtime.runtime.mission_context import PendingTakeover, RunningAction


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
    def __init__(
        self,
        audit_path: str = "audit/runtime.audit.jsonl",
        adapter_name: str = DEFAULT_ADAPTER_NAME,
        mavlink_backend_config: MavlinkBackendConfig | None = None,
        policy_profile_name: str | None = None,
    ) -> None:
        self.bus = EventBus()
        self.audit = AuditLog(audit_path)
        self.adapter_name = adapter_name
        self.policy_profile_name = policy_profile_name
        self.mavlink_backend_config = mavlink_backend_config or MavlinkBackendConfig()
        self.gateway = AdapterGateway(
            {
                "fake": FakeAdapter(),
                "mavlink": MavlinkAdapter(config=self.mavlink_backend_config),
                "payload": PayloadAdapter(),
            }
        )
        self.running_actions: list[RunningAction] = []
        self.pending_takeovers: list[PendingTakeover] = []

    def _active_controller_source(self, fallback: CommandSource) -> str:
        if not self.running_actions:
            return fallback.value
        return self.running_actions[0].source.value

    def _current_phase(self) -> str:
        if any(action.non_preemptible for action in self.running_actions):
            return "non_preemptible"
        return "nominal"

    def _build_policy_context(self, req: ActionRequest, *, phase_override: str | None = None) -> PolicyContext:
        return PolicyContext(
            source=req.source,
            scope=req.requested_scope or req.scope,
            link_state=_demo_link_state_from_request(req),
            mission_id=req.mission_id,
            current_phase=phase_override or self._current_phase(),
            active_controller_source=self._active_controller_source(req.source),
            active_delegations=[req.delegation_id] if req.delegation_id else [],
            running_actions=[action.request_id for action in self.running_actions],
            pending_takeovers=[takeover.takeover_id for takeover in self.pending_takeovers if takeover.status == "pending"],
            runtime_limits={"max_queue": 64, "max_concurrency": 1},
            active_profile=self.policy_profile_name or "default_profile",
            flags={"context_skeleton_ready": True},
        )

    def _build_profile(self) -> PolicyProfile:
        if self.policy_profile_name:
            profile = build_policy_profile(self.policy_profile_name)
            constraints = dict(profile.runtime_constraints)
            constraints.setdefault("non_preemptible_phases", ["non_preemptible"])
            profile.runtime_constraints = constraints
            return profile
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
            runtime_constraints={"non_preemptible_phases": ["non_preemptible"]},
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


    def add_running_action(
        self,
        request_id: str,
        action_type: str = "hover",
        source: CommandSource = CommandSource.SELF_LOCAL,
        priority: int = 50,
        non_preemptible: bool = False,
    ) -> RunningAction:
        running = RunningAction(
            request_id=request_id,
            action_type=action_type,
            source=source,
            priority=priority,
            non_preemptible=non_preemptible,
        )
        self.running_actions.append(running)
        return running

    def _append_takeover_event(self, event_type: str, takeover: PendingTakeover, **extra: object) -> None:
        event = {
            "type": event_type,
            **takeover.to_audit_event(),
            "timestamp": _utc_now_iso(),
            **extra,
        }
        self.bus.publish(event_type, event)
        self.audit.append(event)

    def _create_pending_takeover(self, req: ActionRequest, reason_code: str) -> PendingTakeover:
        now = time.time()
        ttl_s = 30.0
        if isinstance(req.params, dict) and "takeover_ttl_s" in req.params:
            ttl_s = float(req.params.get("takeover_ttl_s") or ttl_s)
        takeover = PendingTakeover(
            takeover_id=f"takeover-{uuid.uuid4().hex[:8]}",
            request_id=req.request_id,
            mission_id=req.mission_id,
            action_type=req.action_type or req.action,
            source=req.source,
            priority=int(req.priority_hint),
            created_at=now,
            ttl_s=ttl_s,
            status="pending",
            reason_code=reason_code,
            request=req,
        )
        self.pending_takeovers.append(takeover)
        self._append_takeover_event("pending_takeover_created", takeover)
        return takeover

    def drop_expired_pending_takeovers(self, *, now: float | None = None) -> list[PendingTakeover]:
        current = time.time() if now is None else now
        dropped: list[PendingTakeover] = []
        for takeover in self.pending_takeovers:
            if takeover.status != "pending" or not takeover.is_expired(current):
                continue
            takeover.status = "expired"
            self._append_takeover_event("pending_takeover_expired", takeover)
            takeover.status = "dropped"
            self._append_takeover_event("pending_takeover_dropped", takeover)
            dropped.append(takeover)
        return dropped

    def handle_phase_exit(self, mission_id: str | None = None) -> dict:
        self.audit.append({"type": "phase_exit", "mission_id": mission_id, "timestamp": _utc_now_iso()})
        self.drop_expired_pending_takeovers()
        candidates = [
            takeover
            for takeover in self.pending_takeovers
            if takeover.status == "pending" and (mission_id is None or takeover.mission_id == mission_id)
        ]
        if not candidates:
            return {"status": "no_pending_takeover", "activated": False}

        selected = sorted(candidates, key=lambda item: (-item.priority, item.created_at))[0]
        req = selected.request
        if req is None:
            selected.status = "dropped"
            self._append_takeover_event("pending_takeover_dropped", selected, reason="missing_request")
            return {"status": "dropped", "activated": False, "takeover_id": selected.takeover_id}

        actx = RuntimeActionContext(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            action=req.action_type,
            risk_level=max(0, int(req.risk_hint)),
            require_confirm=bool(req.requires_confirmation_hint),
        )
        decision = unified_policy_gate(self._build_policy_context(req, phase_override="nominal"), actx, self._build_profile())
        decision_code = decision.decision_code.value if isinstance(decision.decision_code, DecisionCode) else decision.decision_code
        if decision_code not in {DecisionCode.ALLOW.value, DecisionCode.PREEMPT.value}:
            selected.status = "dropped"
            self._append_takeover_event(
                "pending_takeover_dropped",
                selected,
                reason="recheck_failed",
                decision_code=decision_code,
                primary_reason_code=decision.primary_reason_code,
            )
            return {"status": "dropped", "activated": False, "takeover_id": selected.takeover_id}

        selected.status = "admitted"
        self._append_takeover_event("pending_takeover_admitted", selected, decision_code=decision_code)
        selected.status = "activated"
        self._append_takeover_event("pending_takeover_activated", selected, decision_code=decision_code)
        return {"status": "activated", "activated": True, "takeover_id": selected.takeover_id, "request_id": selected.request_id}

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
            takeover = self._create_pending_takeover(req, reason)
            result = self._blocked_like_result(request_id, "deferred", reason)
            result["takeover_status"] = takeover.status
            result["takeover_id"] = takeover.takeover_id
            return result
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
            "execution_trace": result.get("execution_trace"),
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
