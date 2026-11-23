"""Cross-worktree OBSERVE handoff proof. Not imported by production Runtime.

Run with UAVSWARM_OBSERVE_SIM_FIXTURE and (for L2) UAVSWARM_OBSERVE_REVIEW_FIXTURE
set to the checked-out, reviewed producer files. Until both land, ordinary
test runs may skip this optional cross-worktree suite.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import socket
from types import SimpleNamespace

import pytest

from uav_runtime.agent.executor import StepOutcome
from uav_runtime.agent.lifecycle import PlanApproval, PlanExecutionController
from uav_runtime.agent.planner import MissionPlan, MissionPlanStep
from uav_runtime.http.mission_progress import MissionProgress
from uav_runtime.observation.review_record import ReviewValidationError, build_review, record_sha256, validate_review
from uav_runtime.runtime.audit_log import AuditLog


_BINDING_KEYS = (
    "plan_id", "runtime_run_id", "step_id", "arrival_step_id", "node_id",
    "scene_id", "map_version", "target_id", "request_id",
)
_SIM_COMMIT = "6952513e8ee8482d7cf48e364603b2893909dbfe"
_SIM_PATH = "docs/simulation/fixtures/simple_recon_v0_1_target_001_capture_v1.json"


class FakeObservation:
    """Reference handshake for one Fake step; never completes a plan."""

    def __init__(self, binding, l1, clock, *, task_id="TASK-target-001",
                 criterion_version="target-001-green-disk-pixels-v0.1"):
        self.binding, self.l1, self.clock = binding, l1, clock
        self.task_id, self.criterion_version = task_id, criterion_version
        self.capture = None
        self.review = None
        self.l1_attempts = 0

    def accept_capture(self, binding, case, sample, payload, *, approved, policy_allowed):
        if not approved or not policy_allowed:
            return "not_authorized"
        if binding != self.binding:
            return "observation_binding_mismatch"
        if sample is None or not payload:
            return "observation_capture_missing"
        if (case["arrival"]["arrival_observed"] is not True
                or any(case["arrival"][k] != binding[k] for k in ("plan_id", "runtime_run_id", "node_id"))
                or case["arrival"]["step_id"] != binding["arrival_step_id"]
                or any(case[k] != binding[k] for k in ("scene_id", "map_version", "target_id"))
                or case["capture_request"]["request_id"] != binding["request_id"]):
            return "observation_binding_mismatch"

        fingerprint = (deepcopy(sample), sha256(payload).hexdigest())
        if self.capture is not None:
            return "capture_replay" if self.capture["fingerprint"] == fingerprint else "capture_conflict"

        self.l1_attempts += 1
        fresh_sample = {**sample, "checked_monotonic_ns": self.clock()}
        result = self.l1(case, fresh_sample, payload)
        if result["capture"] != "fixture_valid":
            return result["capture"]
        self.capture = {"fingerprint": fingerprint, "image": fresh_sample, "capture_id": self.capture_id(sample)}
        return "captured_only"

    def capture_id(self, sample):
        # Deterministic join ID for the shared offline fixture, not production
        # capture identity, attestation or a reusable execution credential.
        key = {k: self.binding[k] for k in ("plan_id", "runtime_run_id", "request_id")}
        return "cap-" + record_sha256({**key, "image_ref": sample["image_ref"]})[:16]

    def apply_review(self, binding, record):
        if self.capture is None:
            return "observation_capture_missing"
        if binding != self.binding:
            return "observation_binding_mismatch"
        if record is None:
            return "observation_review_missing"
        try:
            record = validate_review(record)
        except ReviewValidationError:
            return "observation_review_invalid"
        image, sample = record["image"], self.capture["image"]
        if (record["capture_id"] != self.capture["capture_id"] or record["task_id"] != self.task_id
                or record["criterion_version"] != self.criterion_version
                or record["target_id"] != binding["target_id"] or image["vehicle_id"] != binding["node_id"]
                or image["ref"] != sample["image_ref"] or image["sha256"] != sample["payload_sha256"]
                or image["camera_id"] != sample["image_topic"].removesuffix("/image")
                or any(image[k] != sample[k] for k in ("width", "height", "encoding"))):
            return "observation_review_binding_mismatch"
        if self.review is not None:
            return "review_replay" if self.review == record else "review_conflict"
        self.review = record
        return record["outcome"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline evidence replay must never use a socket")

    for name in ("bind", "connect", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)


@pytest.fixture
def capture_fixture():
    filename = os.getenv("UAVSWARM_OBSERVE_SIM_FIXTURE")
    if not filename:
        pytest.skip("requires the pinned Simulation capture fixture")
    path = Path(filename).resolve(strict=True)
    case = json.loads(path.read_text(encoding="utf-8"))
    assert case["evidence_origin"] == "synthetic_test_fixture"
    assert case["source_baseline"] == "2d01ffc889d70e64f74391a5dce6f8eadd77ce38"
    sim_replay = path.parents[3] / "tests/unit/test_target_001_capture_fixture.py"
    verify_l1 = runpy.run_path(str(sim_replay))["replay_fixture"]
    capture = case["sample"]
    rows = [bytes(rgb) * capture["width"] for rgb in capture["synthetic_rows_rgb"]]
    pixels = b"".join(rows) * (capture["height"] // len(rows))
    arrival = case["arrival"]
    binding = {
        **{k: arrival[k] for k in ("plan_id", "runtime_run_id", "node_id")},
        **{k: case[k] for k in ("scene_id", "map_version", "target_id")},
        "step_id": "observe-01", "arrival_step_id": arrival["step_id"],
        "request_id": case["capture_request"]["request_id"],
    }
    assert tuple(sorted(binding)) == tuple(sorted(_BINDING_KEYS))
    now = [capture["checked_monotonic_ns"]]
    gate = FakeObservation(binding, verify_l1, lambda: now[0])
    return SimpleNamespace(case=case, binding=binding, sample=capture, pixels=pixels, now=now, gate=gate)


def receive(fixture, *, binding=None, sample=None, pixels=None, **auth):
    # Fixture inputs only; neither flag represents an external grant.
    decision = {"approved": True, "policy_allowed": True, **auth}
    return fixture.gate.accept_capture(
        fixture.binding if binding is None else binding, fixture.case,
        fixture.sample if sample is None else sample, fixture.pixels if pixels is None else pixels, **decision,
    )


@pytest.fixture
def shared_review(capture_fixture):
    filename = os.getenv("UAVSWARM_OBSERVE_REVIEW_FIXTURE")
    if not filename:
        pytest.skip("requires the pinned Algorithm review fixture")
    f = capture_fixture
    example = json.loads(Path(filename).read_text(encoding="utf-8"))
    assert example["scope"] == "fake_adapter_only" and example["execution_authorized"] is False
    assert example["evidence_origin"] == f.case["evidence_origin"]
    assert example["baseline"] == f.case["source_baseline"]
    assert example["capture_source"] == {
        "commit": _SIM_COMMIT, "path": _SIM_PATH, "content_sha256": record_sha256(f.case),
    }
    binding = example["binding"]
    aliases = {"step_id": "proposed_observe_step_id", "request_id": "capture_request_id"}
    assert f.binding == {key: binding[aliases.get(key, key)] for key in _BINDING_KEYS}
    assert binding["gazebo_run_id"] == f.case["capture_request"]["gazebo_run_id"]
    assert binding["image_sim_stamp_ns"] == f.sample["image_sim_stamp_ns"]
    assert example["expected"] == {
        "capture": "fixture_valid", "observation": "undetermined",
        "advance_observe_step": False, "linked_task_completion": "not_asserted",
    }
    return example["review"]


def test_l1_admits_the_common_capture_once_without_asserting_l2(capture_fixture):
    f = capture_fixture
    assert receive(f) == "captured_only"
    assert receive(f) == "capture_replay"
    assert receive(f, pixels=f.pixels[:-1]) == "capture_conflict"
    assert f.gate.l1_attempts == 1
    assert f.gate.review is None


@pytest.mark.parametrize("field", _BINDING_KEYS)
def test_mismatched_observation_binding_rejects_before_capture(capture_fixture, field):
    f = capture_fixture
    assert receive(f, binding={**f.binding, field: "different"}) == "observation_binding_mismatch"
    assert f.gate.capture is None and f.gate.l1_attempts == 0


@pytest.mark.parametrize("option", ["approved", "policy_allowed"])
def test_human_approval_and_policy_are_required_by_fake_gate(capture_fixture, option):
    assert receive(capture_fixture, **{option: False}) == "not_authorized"
    assert capture_fixture.gate.l1_attempts == 0


@pytest.mark.parametrize("failure", ["wrong-topic", "wrong-gazebo-run", "old-frame", "stale-receipt",
                                     "unaligned-pose", "tampered-image", "missing-image"])
def test_l1_failure_is_not_a_review(capture_fixture, failure):
    f = capture_fixture
    sample, pixels = dict(f.sample), f.pixels
    expected = {
        "wrong-topic": "image_source_mismatch", "wrong-gazebo-run": "capture_context_mismatch",
        "old-frame": "frame_stale", "stale-receipt": "frame_stale",
        "unaligned-pose": "capture_samples_unaligned", "tampered-image": "image_integrity_mismatch",
        "missing-image": "observation_capture_missing",
    }
    if failure == "wrong-topic":
        sample.update(f.case["negative_case"]["override_sample"])
    elif failure == "wrong-gazebo-run":
        sample["gazebo_run_id"] = "other-gazebo-run"
    elif failure == "old-frame":
        sample["image_sim_stamp_ns"] = f.case["capture_request"]["after_sim_stamp_ns"]
    elif failure == "stale-receipt":
        f.now[0] += f.case["proposal_limits"]["max_receive_age_wall_ns"]
    elif failure == "unaligned-pose":
        sample["pose_sim_stamp_ns"] -= 500_000_000
    elif failure == "tampered-image":
        pixels = bytes([pixels[0] ^ 1]) + pixels[1:]
    else:
        pixels = b""
    assert receive(f, sample=sample, pixels=pixels) == expected[failure]
    assert f.gate.capture is None and f.gate.review is None


def _navigation_progress(fixture):
    arrival = fixture.case["arrival"]
    step = SimpleNamespace(action_type="goto", node_id=arrival["node_id"])
    plan = SimpleNamespace(plan_id=arrival["plan_id"], steps=[step])
    executor = SimpleNamespace(execute_step=lambda _step: StepOutcome(
        ok=True, action_type="goto", node_id=step.node_id,
        raw={"result": "pass", "arrival_observed": True},
    ))
    progress = MissionProgress(executor, plan, scene_id=fixture.binding["scene_id"],
                               map_version=fixture.binding["map_version"])
    # This is a fixed test identity, not an actual Runtime execution UUID.
    progress.run_id = arrival["runtime_run_id"]
    progress.execute_step(step)
    return progress


def _fake_review(fixture, **changes):
    f = fixture
    sample = f.sample
    return build_review(
        task_id=f.gate.task_id, target_id=f.binding["target_id"], capture_id=f.gate.capture_id(sample),
        image={
            "ref": sample["image_ref"], "sha256": sample["payload_sha256"],
            "width": sample["width"], "height": sample["height"], "encoding": sample["encoding"],
            "captured_at": "2026-11-22T00:00:00Z", "vehicle_id": f.binding["node_id"],
            "camera_id": sample["image_topic"].removesuffix("/image"),
        },
        criterion_version=f.gate.criterion_version, reviewer="human:fixture",
        created_at="2026-11-22T00:00:03Z", reviewed_at="2026-11-22T00:00:03Z",
        outcome=changes.get("outcome", "undetermined"),
        note=changes.get("note", "Synthetic striped image does not establish target visibility."),
    )


def test_missing_and_unclear_review_do_not_change_mission_progress(capture_fixture):
    f = capture_fixture
    progress = _navigation_progress(f)
    before = progress.snapshot()
    assert before["completion_pct"] == 100 and before["status"] == "running"

    record = _fake_review(f)
    assert f.gate.apply_review(f.binding, record) == "observation_capture_missing"
    assert receive(f) == "captured_only"
    assert f.gate.apply_review(f.binding, None) == "observation_review_missing"
    assert f.gate.apply_review(f.binding, record) == "undetermined"
    assert f.gate.apply_review(f.binding, record) == "review_replay"
    assert f.gate.apply_review(f.binding, _fake_review(f, note="Different finding.")) == "review_conflict"
    assert progress.snapshot() == before


@pytest.mark.parametrize("failure", ["wrong-run", "wrong-capture", "wrong-task", "wrong-node",
                                     "wrong-hash", "fabricated-confidence", "not-observed"])
def test_invalid_or_unsuccessful_review_never_completes_a_step(capture_fixture, failure):
    f = capture_fixture
    progress = _navigation_progress(f)
    before = progress.snapshot()
    assert receive(f) == "captured_only"
    result = _fake_review(f, outcome="not_observed", note="No target can be confirmed in this image."
                          ) if failure == "not-observed" else _fake_review(f)
    binding, expected = dict(f.binding), "observation_review_binding_mismatch"
    if failure == "wrong-run":
        binding["runtime_run_id"] = "different-runtime-run"
        expected = "observation_binding_mismatch"
    elif failure == "wrong-capture":
        result["capture_id"] = "cap-foreign"
    elif failure == "wrong-task":
        result["task_id"] = "foreign-task"
    elif failure == "wrong-node":
        result["image"]["vehicle_id"] = "UAV-01"
    elif failure == "wrong-hash":
        result["image"].update(sha256="0" * 64, ref="sha256:" + "0" * 64)
    elif failure == "fabricated-confidence":
        result["confidence"] = 0.9
        expected = "observation_review_invalid"
    else:
        expected = "not_observed"
    assert f.gate.apply_review(binding, result) == expected
    assert progress.snapshot() == before


@pytest.mark.parametrize("failure", ["missing-image", "expired-frame", "undetermined"])
def test_fake_failed_observation_closes_plan_without_claiming_completion(capture_fixture, tmp_path, failure):
    _assert_failed_observation(capture_fixture, tmp_path, failure)


def test_shared_algorithm_review_cannot_complete_the_same_valid_capture(capture_fixture, shared_review, tmp_path):
    f = capture_fixture
    assert shared_review["capture_id"] == f.gate.capture_id(f.sample)
    assert shared_review["linked_task_completion"] == "not_asserted"
    _assert_failed_observation(f, tmp_path, "undetermined", review=shared_review)
    assert f.gate.apply_review(f.binding, shared_review) == "review_replay"
    assert f.gate.l1_attempts == 1


def _assert_failed_observation(f, tmp_path, failure, *, review=None):
    node = f.binding["node_id"]
    steps = [MissionPlanStep(step_id, action, node_id=node) for step_id, action in (
        (f.binding["arrival_step_id"], "goto"), (f.binding["step_id"], "observe"), ("not-dispatched", "land"),
    )]
    plan = MissionPlan(f.binding["plan_id"], "fake-intent", "fake-only-evidence", steps,
                       "draft", "Offline observation handoff", "2026-11-22T00:00:00Z")
    calls = []

    def execute(step):
        calls.append(step.step_id)
        if step.action_type == "goto":
            return StepOutcome(ok=True, action_type="goto", node_id=node,
                               raw={"result": "pass", "arrival_observed": True})
        assert step.action_type == "observe", "unexpected dispatch after failed observation"
        if failure == "expired-frame":
            f.now[0] += f.case["proposal_limits"]["max_receive_age_wall_ns"]
        result = receive(f, pixels=b"" if failure == "missing-image" else f.pixels)
        if result == "captured_only":
            result = f.gate.apply_review(f.binding, _fake_review(f) if review is None else review)
        return StepOutcome(ok=False, action_type="observe", node_id=node,
                           result="fail", failure_reason=result)

    progress = MissionProgress(SimpleNamespace(execute_step=execute), plan, scene_id=f.binding["scene_id"],
                               map_version=f.binding["map_version"])
    progress.run_id = f.binding["runtime_run_id"]
    ctl = PlanExecutionController(audit=AuditLog(tmp_path / "fake-observe.audit.jsonl"), action_executor=progress)
    loaded = ctl.load_plan(plan)
    approval = PlanApproval.create(plan_id=plan.plan_id, operator_id="fake-operator", decision="approve")
    result = ctl.execute_plan_real(ctl.approve_plan(loaded, approval), operator_id=approval.operator_id)
    progress.finish(result["result"])
    assert result["result"] == "failed" and result["aborted_at_step"] == f.binding["step_id"]
    assert result["remaining_steps_pending"] == ["not-dispatched"]
    assert result["failure_reason"] == {
        "missing-image": "observation_capture_missing", "expired-frame": "frame_stale",
        "undetermined": "undetermined",
    }[failure]
    assert calls == [f.binding["arrival_step_id"], f.binding["step_id"]]
    assert steps[1].status == "failed" and steps[2].status == "ready"
    snapshot = progress.snapshot()
    assert snapshot["status"] == "failed" and snapshot["waypoints_reached"] == 1
    assert snapshot["completion_pct"] == 100 and snapshot["targets_found"] is None
