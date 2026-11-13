"""Opt-in rehearsal state. No real adapter, receiver or network changes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.demo_degradation import disposition
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import build_policy_profile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, LinkState
from uav_runtime.protocol.schema import ActionRequest


@dataclass(frozen=True)
class Override:
    kind: str
    value: int
    duration_s: float
    deadline: float
    trace_id: str


def parse_injection(body: dict[str, Any]) -> tuple[str, int, float]:
    kind = body.get("kind")
    if kind not in ("link_degraded", "link_lost", "recover"):
        raise ValueError("invalid_demo_kind")
    expected = {"node_id", "kind"}
    if kind != "recover":
        expected.add("duration_s")
    if kind == "link_degraded":
        expected.add("value")
    if set(body) - expected:
        raise ValueError("unexpected_demo_field")
    value = body.get("value", 18 if kind == "link_degraded" else 0)
    if kind == "link_degraded" and (type(value) is not int or not 1 <= value <= 59):
        raise ValueError("invalid_demo_value")
    duration = body.get("duration_s", 60)
    if type(duration) not in (int, float) or not 0.1 <= duration <= 300:
        raise ValueError("invalid_demo_duration")
    return kind, value, float(duration)


class DemoRehearsal:
    """Rehearse only explicitly injected faults and fictional work assignments."""

    def __init__(self, nodes: Callable[[], list[str]], measured: Callable[[str], int],
                 append: Callable[[dict[str, Any]], None], *, clock=time.monotonic) -> None:
        self.nodes, self.measured, self.append, self.clock = nodes, measured, append, clock
        self._lock = threading.RLock()
        self._overrides: dict[str, Override] = {}
        self._held_out: set[str] = set()
        self._assignments: dict[str, str | None] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="runtime-demo-expiry", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            try:
                self.tick()
            except OSError:
                # Expiry must remain available even after a local audit I/O failure.
                continue

    def _event(self, event_type: str, node: str, trace: str, **fields: Any) -> None:
        self.append({
            "type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": node, "trace_id": trace, "mission_id": "demo-rehearsal",
            "source": "runtime_demo", "mode": "DEMO", "execution_authorized": False,
            "flight_command_sent": False, **fields,
        })

    def _policy(self, node: str, trace: str, action: str, quality: int,
                rule: str, reason: str, state: LinkState) -> bool:
        source = CommandSource.SELF_LOCAL
        decision = unified_policy_gate(
            PolicyContext(source=source, scope=AuthorityScope.SELF_ONLY, link_state=state,
                          node_id=node, active_controller_source=source.value, mission_id="demo-rehearsal"),
            RuntimeActionContext(task_id=trace, action=action, risk_level=1),
            build_policy_profile("standard"),
        )
        code = getattr(decision.decision_code, "value", decision.decision_code)
        self._event("policy_decision_event", node, trace, action_type=action, request_id=trace,
                    decision_code=code, rule_name=rule, reason=reason, explanation=reason,
                    link_quality=quality, primary_reason_code=decision.primary_reason_code or rule,
                    secondary_reason_codes=decision.secondary_reason_codes,
                    effective_profile_id=decision.effective_profile_id, audit_tags=decision.audit_tags)
        return code == "allow"

    def _rebalance(self, node: str, trace: str) -> None:
        peers = sorted(n for n in self.nodes()
                       if n not in self._held_out and self._quality(n) >= 60)
        changes = []
        for task_id, owner in sorted(self._assignments.items()):
            if owner is not None and owner not in self._held_out:
                continue
            replacement = min(peers, key=lambda n: (list(self._assignments.values()).count(n), n)) if peers else None
            if replacement != owner:
                self._assignments[task_id] = replacement
                changes.append({"work_id": task_id, "from": owner, "to": replacement})
        if changes:
            self._event("demo_reassignment", node, trace, assignments=changes, severity="warning")

    def _quality(self, node: str) -> int:
        override = self._overrides.get(node)
        return override.value if override is not None else self.measured(node)

    def tick(self) -> None:
        with self._lock:
            for node, override in list(self._overrides.items()):
                if self.clock() >= override.deadline:
                    self._clear(node, "expired")
            for node in sorted(self._held_out):
                quality = self._quality(node)
                if node not in self._overrides and quality >= 60:
                    self._rejoin(node, quality, uuid4().hex)

    def _rejoin(self, node: str, quality: int, trace: str) -> None:
        reason = f"真实接收新鲜度分 {quality} ≥ 60，允许重新加入演习队列"
        if self._policy(node, trace, "report_status", quality, "degraded_link_rejoin", reason, LinkState.HEALTHY):
            self._held_out.discard(node)
            self._event("demo_recovered", node, trace, rule_name="degraded_link_rejoin",
                        link_quality=quality, reason=reason)
            self._rebalance(node, trace)

    def _clear(self, node: str, reason: str) -> bool:
        prior = self._overrides.pop(node, None)
        if prior is None:
            return False
        measured = self.measured(node)
        self._event("demo_clear", node, prior.trace_id, reason=reason, link_quality=measured)
        if node in self._held_out and measured >= 60:
            self._rejoin(node, measured, prior.trace_id)
        return True

    def clear(self, node: str) -> bool:
        with self._lock:
            self.tick()
            return self._clear(node, "manual")

    def inject(self, node: str, kind: str, value: int, duration: float) -> bool:
        if kind == "recover":
            return self.clear(node)
        with self._lock:
            self.tick()
            old = self._overrides.get(node)
            if old and (old.kind, old.value, old.duration_s) == (kind, value, duration):
                return False
            trace = uuid4().hex
            self._event("demo_inject", node, trace, kind=kind, link_quality=value,
                        duration_s=duration, severity="warning")
            for candidate in self.nodes():
                self._assignments.setdefault(f"demo-work:{candidate}", candidate)
            self._overrides[node] = Override(kind, value, duration, self.clock() + duration, trace)
            proposal = disposition(value)
            previous = disposition(old.value) if old else None
            if proposal and (previous is None or proposal[0] != previous[0]):
                action, rule, reason = proposal
                state = LinkState.LOST if value < 10 else LinkState.DEGRADED
                if self._policy(node, trace, action, value, rule, reason, state):
                    req = ActionRequest(action=action, params={}, source=CommandSource.SELF_LOCAL,
                                        scope=AuthorityScope.SELF_ONLY, node_id=node, request_id=trace)
                    self._event("adapter_execution_started", node, trace, action_id=f"demo-{trace}",
                                request_id=trace, action_type=action, adapter="fake", rule_name=rule)
                    result = AdapterGateway({"fake": FakeAdapter()}).execute("fake", req)
                    accepted = result.get("accepted") is True
                    self._event("action_result", node, trace, action_id=f"demo-{trace}", request_id=trace,
                                action=action, adapter="fake", result="simulated" if accepted else "fail",
                                status="simulated" if accepted else "failed", rule_name=rule, reason=reason,
                                accepted=accepted, execution_trace=result.get("execution_trace"))
                    if accepted:
                        self._held_out.add(node)
                        self._rebalance(node, trace)
            return True

    def state(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            return {
                "contract_version": "1.0", "enabled": True, "mode": "DEMO",
                "execution_authorized": False, "flight_command_sent": False,
                "overrides": [{"node_id": node, "kind": row.kind, "value": row.value,
                               "remaining_ms": math.ceil((row.deadline - now) * 1000),
                               "trace_id": row.trace_id} for node, row in sorted(self._overrides.items())
                              if row.deadline > now],
                "held_out": sorted(self._held_out),
                "assignments": [{"work_id": work_id, "node_id": node}
                                for work_id, node in sorted(self._assignments.items())],
            }
