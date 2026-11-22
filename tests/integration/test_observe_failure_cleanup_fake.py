"""No-flight acceptance: independent, bounded cleanup reporting after OBSERVE failure."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import socket
from types import SimpleNamespace

import pytest

from tests.integration.fake_observation_cleanup import (
    MAX_AGE_NS, MAX_SKEW_NS, Binding, Evidence, FakeCleanupSupervisor,
)
from uav_runtime.agent.executor import StepOutcome
from uav_runtime.agent.lifecycle import PlanApproval, PlanExecutionController
from uav_runtime.agent.planner import MissionPlan, MissionPlanStep
from uav_runtime.http.mission_progress import MissionProgress
from uav_runtime.runtime.audit_log import AuditLog


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Fake cleanup must never open a network/flight transport")
    for name in ("bind", "connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)


@pytest.fixture
def fake():
    now = [1_000_000_000]
    binding = Binding(
        "fake-target-001-patrol-v1", "fixture-runtime-run-1", "UAV-02", "fixture-session-2",
        "simple_recon_v0_1", "simple_recon_v0_1-map-1",
        "9086de5bea22ae0470fe76f6b06cf9e73b6ac9bdf96477c2171ae304a7b575fa", "fixture-calibration-2",
    )
    supervisor = FakeCleanupSupervisor(lambda: now[0])

    def start(cause="observation_failed", task_status="failed", **decisions):
        auth = {"approved": True, "policy_allowed": True, **decisions}  # Controlled Fake decisions.
        return supervisor.start_after_failure(binding, task_status=task_status,
                                              failed_step_id="observe-01", cause=cause, rx_watermark=40, **auth)

    def rows():
        return [
            Evidence(binding, "landed", "EXTENDED_SYS_STATE", 41, now[0] - 2, "on_ground"),
            Evidence(binding, "armed", "HEARTBEAT", 42, now[0] - 1, False),
            Evidence(binding, "at_ground", "calibrated_ground_check", 43, now[0], True),
        ]

    return SimpleNamespace(binding=binding, now=now, start=start, supervisor=supervisor,
                           rows=rows, snapshot=lambda: supervisor.snapshot(binding))


@pytest.mark.parametrize("cause", ["observation_failed", "observation_timed_out"])
def test_failed_plan_dispatches_one_independent_fake_request_and_keeps_task_failed(fake, tmp_path, cause):
    node, plan_id = fake.binding.node_id, fake.binding.plan_id
    steps = [MissionPlanStep(step_id, action, node_id=node) for step_id, action in (
        ("goto-1", "goto"), ("observe-01", "observe"), ("ordinary-land", "land"),
    )]
    plan = MissionPlan(plan_id, "fake-intent", "fake-cleanup-proof", steps, "draft",
                       "Test-only; not an approved flight", "2026-11-22T00:00:00Z")
    calls = []

    def fake_step(step):
        calls.append(step.step_id)
        if step.action_type == "goto":
            return StepOutcome(ok=True, action_type="goto", node_id=node,
                               raw={"result": "pass", "arrival_observed": True})
        assert step.action_type == "observe"
        return StepOutcome(ok=False, action_type="observe", node_id=node, failure_reason=cause)

    progress = MissionProgress(SimpleNamespace(execute_step=fake_step), plan,
                               scene_id=fake.binding.scene_id, map_version=fake.binding.map_version)
    progress.run_id = fake.binding.run_id
    audit = AuditLog(tmp_path / "fake-plan.audit.jsonl")
    controller = PlanExecutionController(audit=audit, action_executor=progress)
    approval = PlanApproval.create(plan_id=plan_id, operator_id="fake-operator", decision="approve")
    approved = controller.approve_plan(controller.load_plan(plan), approval)
    result = controller.execute_plan_real(approved, operator_id=approval.operator_id)
    progress.finish(result["result"])
    assert result["aborted_at_step"] == "observe-01"
    assert result["remaining_steps_pending"] == ["ordinary-land"]

    ticket = fake.supervisor.start_after_failure(
        fake.binding, task_status=result["result"], failed_step_id=result["aborted_at_step"],
        cause=result["failure_reason"], rx_watermark=40, approved=True, policy_allowed=True,
    )
    assert ticket is not None and ticket.trigger == cause
    fake_outbox = [ticket]
    assert fake.start(cause) is None
    assert fake.snapshot()["safety_status"] == "pending"
    fake.supervisor.note_ack(ticket, True)
    assert fake.snapshot()["safety_status"] == "pending"

    fake.now[0] += 150_000_000
    for row in fake.rows():
        assert fake.supervisor.ingest(row) is True
    safety = fake.snapshot()
    assert safety["safety_status"] == "safe_ended"
    assert safety["task_status"] == progress.snapshot()["status"] == "failed"
    assert safety["run_id"] == progress.snapshot()["run_id"]
    assert safety["plan_id"] == progress.snapshot()["mission_id"]
    assert safety["evidence_sequences"] == {"landed": 41, "armed": 42, "at_ground": 43}
    assert progress.snapshot()["completion_pct"] == 100
    assert calls == ["goto-1", "observe-01"] and fake_outbox == [ticket]
    assert fake.start(cause) is None


@pytest.mark.parametrize("cause", ["undetermined", "not_observed", "observed"])
def test_l2_label_alone_never_requests_cleanup_or_completes_task(fake, cause):
    assert fake.start(cause, task_status="running") is None
    assert fake.start(cause, task_status="failed") is None
    assert fake.start("observation_failed", task_status="completed") is None


@pytest.mark.parametrize("decision", ["approved", "policy_allowed"])
def test_fake_cleanup_cannot_bypass_explicit_authorization(fake, decision):
    assert fake.start(**{decision: False}) is None
    assert fake.snapshot()["task_status"] == "failed"
    assert fake.snapshot()["safety_status"] == "unconfirmed"
    assert fake.snapshot()["reasons"] == ("cleanup_not_authorized",)
    assert fake.start() is None


def test_same_run_node_claim_is_atomic(fake):
    with ThreadPoolExecutor(max_workers=4) as workers:
        claimed = [r for r in workers.map(lambda _: fake.start(), range(12)) if r is not None]
    assert len(claimed) == 1
    assert fake.snapshot()["cleanup_id"] == claimed[0].cleanup_id


@pytest.mark.parametrize("ack", [True, False, None])
def test_ack_only_or_no_ack_times_out_permanently_without_retry(fake, ack):
    request = fake.start()
    if ack is not None:
        fake.supervisor.note_ack(request, ack)
    assert fake.snapshot()["safety_status"] == "pending"
    fake.now[0] = request.deadline_ns
    result = fake.snapshot()
    assert result["ack_accepted"] is ack
    assert result["task_status"] == "failed" and result["safety_status"] == "unconfirmed"
    assert set(result["reasons"]) == {"cleanup_timeout", "missing_landed", "missing_armed", "missing_at_ground"}
    assert not any(fake.supervisor.ingest(row) for row in fake.rows())
    assert fake.start() is None and fake.snapshot() == result


def test_independent_tick_reports_timeout_once_without_telemetry_or_reads(fake):
    ticket = fake.start()
    fake.now[0] = ticket.deadline_ns - 1
    assert fake.supervisor.tick() == ()
    fake.now[0] += 1
    assert fake.supervisor.tick() == (ticket.cleanup_id,)
    assert fake.supervisor.tick() == ()
    assert fake.snapshot()["safety_status"] == "unconfirmed"
    assert fake.start() is None


@pytest.mark.parametrize("change", [
    "wrong-run", "wrong-node", "wrong-epoch", "wrong-plan", "wrong-scene", "wrong-map",
    "wrong-world", "wrong-calibration", "wrong-source", "watermark", "before-start",
    "stale", "future-time", "reused-rx-sequence",
])
def test_mismatched_or_expired_ground_evidence_cannot_end_cleanup(fake, change):
    request = fake.start()
    fake.now[0] += MAX_AGE_NS + 10
    landed, armed, ground = fake.rows()
    assert fake.supervisor.ingest(landed) and fake.supervisor.ingest(armed)
    fields = {
        "wrong-run": "run_id", "wrong-node": "node_id", "wrong-epoch": "session_epoch",
        "wrong-plan": "plan_id", "wrong-scene": "scene_id", "wrong-map": "map_version",
        "wrong-world": "world_sha256", "wrong-calibration": "calibration_id",
    }
    if change in fields:
        ground = replace(ground, binding=replace(ground.binding, **{fields[change]: "other"}))
    else:
        kwargs = {
            "wrong-source": {"source": "ACK"},
            "watermark": {"rx_sequence": request.rx_watermark},
            "before-start": {"received_ns": request.started_ns},
            "stale": {"received_ns": fake.now[0] - MAX_AGE_NS - 1},
            "future-time": {"received_ns": fake.now[0] + 1},
            "reused-rx-sequence": {"rx_sequence": armed.rx_sequence},
        }
        ground = replace(ground, **kwargs[change])
    assert not fake.supervisor.ingest(ground)
    assert fake.snapshot()["safety_status"] == "pending"
    fake.now[0] = request.deadline_ns
    assert "missing_at_ground" in fake.snapshot()["reasons"]
    assert fake.snapshot()["safety_status"] == "unconfirmed"


@pytest.mark.parametrize(("kind", "value"), [
    ("landed", "in_air"), ("armed", True), ("armed", 0), ("at_ground", False),
])
def test_fresh_contradicting_evidence_never_confirms_safe_end(fake, kind, value):
    request = fake.start()
    fake.now[0] += 10
    for row in fake.rows():
        assert fake.supervisor.ingest(replace(row, value=value) if row.kind == kind else row)
    assert fake.snapshot()["reasons"] == (f"{kind}_not_confirmed",)
    fake.now[0] = request.deadline_ns
    assert fake.snapshot()["safety_status"] == "unconfirmed"


def test_out_of_order_landed_cannot_override_newer_airborne_evidence(fake):
    fake.start()
    fake.now[0] += 10
    landed, armed, ground = fake.rows()
    assert fake.supervisor.ingest(replace(landed, rx_sequence=45, value="in_air"))
    assert not fake.supervisor.ingest(landed)
    assert fake.supervisor.ingest(armed) and fake.supervisor.ingest(ground)
    assert fake.snapshot()["reasons"] == ("landed_not_confirmed",)


def test_distinct_fresh_but_unaligned_samples_do_not_confirm(fake):
    fake.start()
    fake.now[0] += MAX_SKEW_NS + 10
    landed, armed, ground = fake.rows()
    assert fake.supervisor.ingest(replace(landed, received_ns=fake.now[0] - MAX_SKEW_NS - 1))
    assert fake.supervisor.ingest(armed) and fake.supervisor.ingest(ground)
    assert fake.snapshot()["reasons"] == ("evidence_not_time_aligned",)


def test_session_invalidation_rejects_even_late_old_context_evidence(fake):
    request = fake.start()
    fake.supervisor.invalidate_binding(fake.binding)
    fake.now[0] += 10
    assert not any(fake.supervisor.ingest(row) for row in fake.rows())
    invalidated = fake.snapshot()
    assert invalidated["safety_status"] == "unconfirmed"
    assert invalidated["reasons"] == ("evidence_binding_invalidated",)
    other_epoch = replace(fake.binding, session_epoch="after-reconnect")
    with pytest.raises(KeyError, match="cleanup_binding_mismatch"):
        fake.supervisor.snapshot(other_epoch)
    assert fake.supervisor.start_after_failure(other_epoch, task_status="failed",
        failed_step_id=request.failed_step_id, cause=request.trigger, rx_watermark=0,
        approved=True, policy_allowed=True) is None


def test_complete_telemetry_without_ack_can_confirm_physical_safe_end(fake):
    fake.start()
    fake.now[0] += 10
    assert all(fake.supervisor.ingest(row) for row in fake.rows())
    assert fake.snapshot()["safety_status"] == "safe_ended"
    assert fake.snapshot()["ack_accepted"] is None


def test_final_ground_sample_at_deadline_is_too_late(fake):
    request = fake.start()
    fake.now[0] = request.deadline_ns - 10
    landed, armed, _ = fake.rows()
    assert fake.supervisor.ingest(landed) and fake.supervisor.ingest(armed)
    fake.now[0] = request.deadline_ns
    assert not fake.supervisor.ingest(fake.rows()[-1])
    assert fake.snapshot()["reasons"] == ("cleanup_timeout", "missing_at_ground")
