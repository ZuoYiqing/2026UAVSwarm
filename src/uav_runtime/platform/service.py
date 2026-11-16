"""A platform owns its accepted task independently of ground HTTP sessions."""
from __future__ import annotations

import threading
import time
import queue
from typing import Any, Callable
from uuid import uuid4

from uav_runtime.policy.action_registry import get_action_capability
from uav_runtime.policy.context import PolicyContext, RuntimeActionContext
from uav_runtime.policy.gate import unified_policy_gate
from uav_runtime.policy.profile import build_policy_profile
from uav_runtime.protocol.enums import AuthorityScope, CommandSource, LinkState

from .contract import PlatformError, stamp, timestamp, validate_task, fingerprint, canonical
from .store import TaskStore

IDENTITY = ("node_id", "task_id", "task_version", "execution_id", "step_id", "request_id", "trace_id")


class PlatformService:
    def __init__(self, store: TaskStore, *, node_id: str = "UAV-02", mode: str = "fake",
                 execute: Callable | None = None, observe: Callable | None = None,
                 candidate: Callable | None = None, clock=time.time, monotonic=time.monotonic, run_id: str | None = None):
        self.store, self.node_id, self.mode = store, node_id, mode
        if mode not in {"fake", "sitl"} or (mode == "sitl" and (execute is None or observe is None)):
            raise PlatformError("explicit_sitl_adapter_required")
        store.bind(node_id, mode)
        self.clock, self.monotonic = clock, monotonic
        self.execute = execute or self._fake_execute
        self.observe = observe or (lambda: {"source": "fake", "sample_timestamp": stamp(clock()), "stale": False,
                                           "local_position": {}, "armed": False, "landed_state": 1, "landed_fresh": True})
        self.candidate = candidate
        self.boot_id = str(uuid4())
        self.run_id = run_id
        self.last_link: float | None = None
        self.last_link_timestamp: str | None = None
        self.worker: threading.Thread | None = None
        self.stop = threading.Event()
        self.control = threading.RLock()
        self._run_lock = threading.Lock()
        self._model_thread: threading.Thread | None = None
        store.recover(stamp(clock()))

    def heartbeat(self) -> dict[str, Any]:
        with self.control:
            self.last_link, self.last_link_timestamp = self.monotonic(), stamp(self.clock())
        return self.link()

    def link(self) -> dict[str, Any]:
        with self.control:
            age = None if self.last_link is None else max(0, self.monotonic() - self.last_link)
            return {"state": "healthy" if age is not None and age <= 3 else "lost",
                    "last_received_at": self.last_link_timestamp, "age_ms": None if age is None else int(age * 1000)}

    def status(self) -> dict[str, Any]:
        with self.store.lock:
            checkpoint = self.store.events()["checkpoint_seq"]
            task = self.store.active()
        observation = self.observe()
        safe = (task is None and observation.get("stale") is False and observation.get("landed_fresh") is True
                and observation.get("armed") is False and observation.get("landed_state") == 1)
        return {"contract_version": "1.0", "node_id": self.node_id, "boot_id": self.boot_id,
                "store_id": self.store.store_id, "run_id": self.run_id, "execution_mode": self.mode, "ground_link": self.link(),
                "active_task": task, "event_seq": checkpoint, "platform_observation": observation, "safe_to_stop": safe,
                "model_configured": self.candidate is not None, "execution_authorized": False}

    def submit(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        # Replays remain queryable after expiry/loss; only a new task needs a
        # fresh authorization. Comparing the full immutable body prevents edits.
        with self.control:
            try:
                existing = self.store.task(body.get("task_id", ""))
            except PlatformError:
                existing = None
            if existing is not None:
                return self.store.accept(body, stamp(self.clock()), self.mode)
            if self.link()["state"] != "healthy":
                raise PlatformError("ground_link_unavailable", 409)
            task = validate_task(body, self.node_id, self.clock())
            result = self.store.accept(task, stamp(self.clock()), self.mode)
        return result

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self.control:
            task = self.store.task(task_id)
            if task["status"] in {"succeeded", "failed", "cancelled"}:
                return task
            if task["status"] == "recovery_required":
                raise PlatformError("operator_reconciliation_required", 409)
            return self.store.update(task_id, stamp(self.clock()), "task_cancel_requested", cancel_requested=True)

    def reconcile(self, task_id: str, operator_id: str, execution_id: str) -> dict[str, Any]:
        from .contract import identifier
        identifier(operator_id)
        with self.control:
            task = self.store.task(task_id)
            obs = self.observe()
            if (task["execution_id"] != execution_id or task["status"] != "recovery_required"
                    or obs.get("stale") is not False or obs.get("landed_fresh") is not True
                    or obs.get("armed") is not False or obs.get("landed_state") != 1):
                raise PlatformError("fresh_ground_reconciliation_required", 409)
            return self.store.update(task_id, stamp(self.clock()), "task_reconciled", status="failed",
                                     failure_reason="operator_reconciled_after_uncertain_execution", data={"operator_id": operator_id, "observation": obs})

    def start(self) -> None:
        if self.worker is None:
            self.worker = threading.Thread(target=self._loop, name=f"platform-{self.node_id}", daemon=True)
            self.worker.start()

    def _loop(self) -> None:
        while not self.stop.is_set():
            task = self.store.active()
            if task and task["status"] == "accepted":
                try:
                    self.run_task(task["task_id"])
                except Exception as exc:
                    self.store.update(task["task_id"], stamp(self.clock()), "task_recovery_required",
                                      status="recovery_required", failure_reason="worker_exception",
                                      data={"error_class": type(exc).__name__})
            with self.store.changed:
                self.store.changed.wait(timeout=0.1)

    def _policy(self, task: dict[str, Any], step: dict[str, Any], *, recovery: bool = False):
        action = step["action"]
        observation = self.observe()
        if action != "land" and (observation.get("stale") is not False
                or not 0 <= self.clock() - timestamp(observation.get("sample_timestamp")) <= 3):
            raise PlatformError("local_observation_stale", 409)
        if action != "land" and timestamp(task["authorization"]["expires_at"]) <= self.clock():
            raise PlatformError("authorization_expired", 409)
        if action == "takeoff" and self.link()["state"] != "healthy":
            raise PlatformError("takeoff_requires_ground_link", 409)
        profile = build_policy_profile("standard")
        profile.name = "platform_task_v1"
        profile.max_risk_when_link_lost = 2
        profile.fallback_behavior["preauthorized_land"] = True
        # The immutable accepted sequence explicitly includes controlled LAND
        # as its expiry/cancel/failure recovery. It never includes DISARM.
        context = PolicyContext(source=CommandSource.SELF_LOCAL, scope=AuthorityScope.SELF_ONLY,
                                link_state=LinkState(self.link()["state"]), mission_id=task["task_id"],
                                node_id=self.node_id, flags={"offline_landing_authorized": action == "land"})
        capability = get_action_capability(action)
        decision = unified_policy_gate(context, RuntimeActionContext(task_id=task["task_id"], action=action,
                                                                      risk_level=capability.risk_level), profile)
        code = decision.decision_code.value if hasattr(decision.decision_code, "value") else decision.decision_code
        self.store.update(task["task_id"], stamp(self.clock()), "platform_policy_decision",
                          data={"step_id": step["step_id"], "action": action, "decision_code": code,
                                "reason": decision.primary_reason_code, "ground_link": self.link(), "recovery": recovery})
        if str(code).lower() != "allow":
            raise PlatformError("platform_policy_rejected", 409)

    def _model(self, task: dict[str, Any], step: dict[str, Any]) -> str:
        if self.candidate is None:
            return "execute_authorized_step"
        request = {"contract_version": "1.0", **{k: task[k] for k in IDENTITY if k not in {"step_id", "request_id"}},
                   "step_id": step["step_id"], "request_id": str(uuid4()), "next_step": step,
                   "authorization": task["authorization"], "ground_link": self.link(), "observation": self.observe(),
                   "decision_timeout_ms": 2000}
        request["snapshot_id"] = request["request_id"]
        request["allowed_options"] = [{"option_id": "execute_authorized_step", "action_type": step["action"], "params": step["params"]},
                                      {"option_id": "abort_to_land", "action_type": "land", "params": {}}]
        self.store.update(task["task_id"], stamp(self.clock()), "model_request",
                          data={"request": request, "input_sha256": fingerprint(request)})
        try:
            if self._model_thread is not None and self._model_thread.is_alive():
                raise PlatformError("model_previous_request_pending")
            started = self.monotonic()
            result_queue = queue.Queue(maxsize=1)
            def query():
                try:
                    result_queue.put((True, self.candidate(request)))
                except Exception as exc:
                    result_queue.put((False, exc))
            self._model_thread = threading.Thread(target=query, daemon=True, name="platform-model-query")
            self._model_thread.start()
            try:
                ok, answer = result_queue.get(timeout=2)
            except queue.Empty:
                raise PlatformError("model_deadline_exceeded") from None
            if not ok:
                raise answer
            status, reply = answer
            if self.monotonic() - started > 2:
                raise PlatformError("model_deadline_exceeded")
            if (status != 200 or reply.get("contract_version") != "1.0" or reply.get("status") != "candidate"
                    or reply.get("execution_authorized") is not False
                    or any(reply.get(k) != request[k] for k in IDENTITY)
                    or reply.get("decision") not in {"execute_authorized_step", "abort_to_land"}
                    or not isinstance(reply.get("evidence"), dict)
                    or len(canonical(reply.get("evidence")).encode()) > 8192):
                raise PlatformError("model_response_invalid")
            event, decision = "model_candidate", reply["decision"]
            data = {"request_id": request["request_id"], "step_id": step["step_id"], "response": reply,
                    "input_sha256": fingerprint(request)}
        except Exception as exc:
            event, decision = "model_unavailable", "execute_authorized_step"
            data = {"request_id": request["request_id"], "step_id": step["step_id"],
                    "reason": str(exc) if isinstance(exc, PlatformError) else type(exc).__name__,
                    "fallback": "authorized_sequence", "input_sha256": fingerprint(request)}
        self.store.update(task["task_id"], stamp(self.clock()), event, data=data)
        return decision

    @staticmethod
    def _completed(result: dict[str, Any]) -> bool:
        return result.get("status") == "succeeded" and result.get("result") == "pass"

    def _step(self, task: dict[str, Any], step: dict[str, Any], *, recovery=False) -> dict[str, Any]:
        if not recovery and self.store.task(task["task_id"])["cancel_requested"]:
            raise PlatformError("operator_cancelled", 409)
        self._policy(task, step, recovery=recovery)
        self.store.update(task["task_id"], stamp(self.clock()), "step_started", current_step=step["step_id"],
                          data={"step_id": step["step_id"], "action": step["action"], "recovery": recovery})
        # The durable step_started is committed before touching the adapter.
        # A crash/ambiguous ACK never permits automatic action replay.
        result = self.execute(task, step)
        current = self.store.task(task["task_id"])
        outcome = {"step_id": step["step_id"], "action": step["action"], "recovery": recovery, "result": result}
        self.store.update(task["task_id"], stamp(self.clock()), "step_finished",
                          step_outcomes=current["step_outcomes"] + [outcome], data=outcome)
        return result

    def run_task(self, task_id: str) -> None:
        # One scheduler owns this task, even if two callers race to claim it.
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            self._run_task(task_id)
        finally:
            self._run_lock.release()

    def _run_task(self, task_id: str) -> None:
        task = self.store.task(task_id)
        if task["status"] != "accepted":
            return
        self.store.update(task_id, stamp(self.clock()), "task_execution_started", status="executing")
        failure, cancelled, attempted_takeoff, land_attempted = None, False, False, False
        for step in task["steps"]:
            current = self.store.task(task_id)
            cancelled = current["cancel_requested"]
            if cancelled:
                failure = "operator_cancelled"
                break
            try:
                if self._model(task, step) == "abort_to_land":
                    failure = "model_requested_recovery"
                    break
                self._policy(task, step)
                attempted_takeoff |= step["action"] == "takeoff"
                land_attempted |= step["action"] == "land"
                result = self._step(task, step)
                if not self._completed(result):
                    failure = str(result.get("failure_reason") or "action_incomplete")
                    break
            except Exception as exc:
                failure = str(exc) if isinstance(exc, PlatformError) else "action_execution_exception"
                break
        if failure and land_attempted:
            self.store.update(task_id, stamp(self.clock()), "task_recovery_required", status="recovery_required", failure_reason=failure)
            return
        if failure and attempted_takeoff:
            # Controlled recovery is preauthorized even after task expiry.
            # Never turn a failed task into success just because LAND succeeds.
            try:
                recovery = self._step(task, task["steps"][-1], recovery=True)
                if not self._completed(recovery):
                    self.store.update(task_id, stamp(self.clock()), "task_recovery_required", status="recovery_required", failure_reason=failure)
                    return
            except Exception:
                self.store.update(task_id, stamp(self.clock()), "task_recovery_required", status="recovery_required", failure_reason=failure)
                return
        cancelled = cancelled or self.store.task(task_id)["cancel_requested"]
        self.store.update(task_id, stamp(self.clock()), "task_finished",
                          status="cancelled" if cancelled else "failed" if failure else "succeeded", failure_reason=failure)

    @staticmethod
    def _fake_execute(task, step):
        return {"status": "succeeded", "result": "pass", "execution_mode": "fake",
                "flight_command_sent": False, "completion_evidence": {"completion_reached": True, "source": "fake"}}
