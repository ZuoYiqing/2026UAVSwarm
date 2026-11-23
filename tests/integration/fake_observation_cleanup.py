"""Offline-only contract for supervision after a failed observation.

This reference is test support, not a Runtime API, policy, adapter, recovery
procedure, durable task store, or permission to issue any flight action.
"""
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable


# Fake timing values for deterministic deadline/age/skew tests only.
TIMEOUT_NS = 2_000_000_000
MAX_AGE_NS = 500_000_000
MAX_SKEW_NS = 200_000_000
SOURCES = {
    "landed": "EXTENDED_SYS_STATE",
    "armed": "HEARTBEAT",
    "at_ground": "calibrated_ground_check",
}
EXPECTED = {"landed": "on_ground", "armed": False, "at_ground": True}
FAILURE_CAUSES = {"observation_failed", "observation_timed_out"}


@dataclass(frozen=True)
class Binding:
    plan_id: str
    run_id: str
    node_id: str
    session_epoch: str
    scene_id: str
    map_version: str
    world_sha256: str
    calibration_id: str


@dataclass(frozen=True)
class Evidence:
    binding: Binding
    kind: str
    source: str
    rx_sequence: int
    received_ns: int
    value: str | bool


@dataclass(frozen=True)
class FakeCleanupRequest:
    """In-memory notification, not a transport command."""

    cleanup_id: int
    binding: Binding
    failed_step_id: str
    trigger: str
    rx_watermark: int
    started_ns: int
    deadline_ns: int


@dataclass
class _Case:
    request: FakeCleanupRequest
    samples: dict[str, Evidence] = field(default_factory=dict)
    ack_accepted: bool | None = None
    terminal: str | None = None
    reasons: tuple[str, ...] = ()


class FakeCleanupSupervisor:
    """One bounded evidence window per failed task run and node."""

    def __init__(self, monotonic_ns: Callable[[], int]):
        self._now = monotonic_ns
        self._cases: dict[tuple[str, str], _Case] = {}
        self._lock = Lock()

    @staticmethod
    def _key(binding: Binding) -> tuple[str, str]:
        return binding.run_id, binding.node_id

    def start_after_failure(
        self, binding: Binding, *, task_status: str, failed_step_id: str,
        cause: str, rx_watermark: int, approved: bool, policy_allowed: bool,
    ) -> FakeCleanupRequest | None:
        if task_status != "failed" or cause not in FAILURE_CAUSES or not failed_step_id:
            return None
        with self._lock:
            key = self._key(binding)
            if key in self._cases:
                return None  # Same run/node gets no second notification, even after timeout.
            now = self._now()
            req = FakeCleanupRequest(len(self._cases) + 1, binding, failed_step_id, cause,
                                     rx_watermark, now, now + TIMEOUT_NS)
            case = self._cases[key] = _Case(req)
            if approved is not True or policy_allowed is not True:
                case.terminal, case.reasons = "unconfirmed", ("cleanup_not_authorized",)
                return None
            return req

    def note_ack(self, request: FakeCleanupRequest, accepted: bool) -> None:
        with self._lock:
            case = self._cases.get(self._key(request.binding))
            if case is not None and case.request == request and case.ack_accepted is None:
                case.ack_accepted = accepted
            # Never establishes landed, disarmed, or ground location.

    @staticmethod
    def _missing(case: _Case, now: int) -> tuple[str, ...]:
        reasons = []
        for kind, expected in EXPECTED.items():
            row = case.samples.get(kind)
            if row is None:
                reasons.append(f"missing_{kind}")
            elif now - row.received_ns > MAX_AGE_NS:
                reasons.append(f"stale_{kind}")
            elif type(row.value) is not type(expected) or row.value != expected:
                reasons.append(f"{kind}_not_confirmed")
        if not reasons:
            times = [row.received_ns for row in case.samples.values()]
            if max(times) - min(times) > MAX_SKEW_NS:
                reasons.append("evidence_not_time_aligned")
        return tuple(reasons)

    def _finish_if_due(self, case: _Case, now: int) -> None:
        if case.terminal is not None:
            return
        reasons = self._missing(case, now)
        if now >= case.request.deadline_ns:
            case.terminal = "unconfirmed"
            case.reasons = ("cleanup_timeout", *reasons)
        elif not reasons:
            case.terminal = "safe_ended"

    def ingest(self, evidence: Evidence) -> bool:
        with self._lock:
            case = self._cases.get(self._key(evidence.binding))
            if case is None or case.request.binding != evidence.binding:
                return False
            now = self._now()
            self._finish_if_due(case, now)
            if case.terminal is not None or SOURCES.get(evidence.kind) != evidence.source:
                return False
            req = case.request
            previous = case.samples.get(evidence.kind)
            if (evidence.rx_sequence <= req.rx_watermark
                    or not req.started_ns < evidence.received_ns <= now
                    or now - evidence.received_ns > MAX_AGE_NS
                    or any(row.rx_sequence == evidence.rx_sequence for row in case.samples.values())
                    or (previous is not None and (evidence.rx_sequence <= previous.rx_sequence
                                                  or evidence.received_ns < previous.received_ns))):
                return False
            case.samples[evidence.kind] = evidence
            self._finish_if_due(case, now)
            return True

    def invalidate_binding(self, binding: Binding) -> None:
        """A trusted owner reports session/calibration/run context invalidation."""
        with self._lock:
            case = self._cases.get(self._key(binding))
            if case is not None and case.request.binding == binding and case.terminal is None:
                case.terminal, case.reasons = "unconfirmed", ("evidence_binding_invalidated",)

    def tick(self) -> tuple[int, ...]:
        """Fake supervisor poll; deadlines do not depend on UI reads or a plan step."""
        with self._lock:
            now = self._now()
            expired = []
            for case in self._cases.values():
                if case.terminal is None and now >= case.request.deadline_ns:
                    self._finish_if_due(case, now)
                    expired.append(case.request.cleanup_id)
            return tuple(expired)

    def snapshot(self, binding: Binding) -> dict:
        with self._lock:
            case = self._cases[self._key(binding)]
            if case.request.binding != binding:
                raise KeyError("cleanup_binding_mismatch")
            now = self._now()
            self._finish_if_due(case, now)
            # Keep task failure independent from the outcome of this window.
            return {
                "plan_id": case.request.binding.plan_id,
                "run_id": case.request.binding.run_id,
                "node_id": case.request.binding.node_id,
                "task_status": "failed",
                "safety_status": case.terminal or "pending",
                "cleanup_id": case.request.cleanup_id,
                "failed_step_id": case.request.failed_step_id,
                "ack_accepted": case.ack_accepted,
                "reasons": case.reasons if case.terminal else self._missing(case, now),
                "evidence_sequences": {kind: row.rx_sequence for kind, row in case.samples.items()},
            }
