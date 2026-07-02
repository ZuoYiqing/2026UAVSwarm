"""Mission Runtime orchestration entry point.

给新同学的阅读提示：
- 这个文件不是“飞控驱动”，而是控制面 runtime glue。
- 所有 ActionRequest 先进入 Policy Gate；只有 ALLOW 才会走 AdapterGateway。
- DENY / REQUIRE_CONFIRM / DEFER / PREEMPT 都在这里被转成稳定 action_result 形状，
  并写入 audit/replay，方便事后解释“为什么执行/为什么没执行”。
- pending_takeover 也属于 runtime 状态，不属于 adapter/backend；adapter 只负责执行已获准的命令。
"""
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
    """Demo-only link-state override carried in params.

    生产系统里 link state 应来自链路监测/遥测模块；当前项目为了让测试和演示不依赖真实
    通信链路，把 `demo_link_state` 放在 request.params 中。新同学不要把它理解成最终协议字段。
    """
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
    """Small runtime coordinator used by CLI/tests/demo flows.

    Responsibilities:
    1. Build policy context from request + runtime state.
    2. Call unified_policy_gate.
    3. Persist policy_decision_event into audit.
    4. Convert non-ALLOW decisions into blocked/deferred/confirmation results.
    5. Dispatch ALLOW requests to the selected adapter through AdapterGateway.
    6. Maintain minimal Mission Runtime v0.2 pending_takeover state.

    Non-responsibilities:
    - It does not talk to PX4 directly.
    - It does not enforce hardware-specific policy inside adapters.
    - It does not implement a full scheduler or multi-vehicle optimizer.
    """

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
        # PolicyContext is the compact view Policy Gate needs.  Keep vendor/hardware
        # details out of this object so protocol/policy do not drift when hardware changes.
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
        # Profiles are intentionally built here as data objects.  If a team member
        # adds a new profile, prefer editing policy/profile.py and tests instead of
        # adding ad-hoc if/else checks in adapters.
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
        # Non-ALLOW decisions still return action_result-shaped payloads so callers
        # and replay tooling can handle DENY/DEFER/REQUIRE_CONFIRM/PREEMPT uniformly.
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
        # Contract rule: every non-ALLOW policy decision must explain itself with
        # primary_reason_code.  This makes audit/replay useful for reviews.
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
        # DEFER from Policy Gate means "not now, but remember the takeover request".
        # Runtime owns that memory because adapter/backend should not know about
        # command hierarchy, phase_exit, or takeover TTL.
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
        # Expiry is two-step in audit: expired -> dropped.  The explicit chain makes
        # replay timelines easier for new operators to understand.
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
        # phase_exit is the minimal hook that says a non-preemptible phase ended.
        # We re-check pending takeover under a nominal phase before admitting it.
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
        # Highest priority wins; created_at is the deterministic tie-breaker.
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

    def evaluate_policy_request(self, req: ActionRequest) -> tuple[str, dict]:
        """Normalize request, run Policy Gate, and append policy_decision_event.

        This helper lets explicit SITL smoke commands share the same Policy Gate
        and audit path as normal submit-action without dispatching an adapter first.
        """
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
        return decision_code, policy_decision_event

    def handle_action_request(self, req: ActionRequest) -> dict:
        decision_code, policy_decision_event = self.evaluate_policy_request(req)
        request_id = req.request_id

        if decision_code == DecisionCode.DENY.value:
            # Policy blocked the request.  Do not call adapters.
            reason = self._require_primary_reason(decision_code, policy_decision_event.get("primary_reason_code"))
            return self._blocked_like_result(request_id, "blocked", reason)
        if decision_code == DECISION_DEFER:
            # Runtime records a pending takeover for later phase_exit re-evaluation.
            reason = self._require_primary_reason(decision_code, policy_decision_event.get("primary_reason_code"))
            takeover = self._create_pending_takeover(req, reason)
            result = self._blocked_like_result(request_id, "deferred", reason)
            result["takeover_status"] = takeover.status
            result["takeover_id"] = takeover.takeover_id
            return result
        if decision_code == DECISION_REQUIRE_CONFIRM:
            # Current MVP does not implement an interactive confirmation workflow;
            # it returns a stable waiting_confirmation result for callers/tests.
            reason = self._require_primary_reason(decision_code, policy_decision_event.get("primary_reason_code"))
            return self._blocked_like_result(request_id, "waiting_confirmation", reason)
        if decision_code == DecisionCode.PREEMPT.value:
            # PREEMPT is currently control-plane intent only; no real abort/suspend
            # command is sent to hardware in this project stage.
            reason = self._require_primary_reason(decision_code, policy_decision_event.get("primary_reason_code"))
            return self._blocked_like_result(request_id, "handover_pending", reason)

        # ALLOW -> execute selected adapter
        result = self.gateway.execute(self.adapter_name, req)
        normalized = {
            # Normalize adapter-specific raw output back to the shared action_result
            # shape expected by tests, CLI, audit, and replay.
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
