"""Deterministic tests for the auto-refreshing calibration loop.

The loop itself is deliberately thin: decide whether the simulation is still
alive, capture one round, publish it, wait.  These tests pin the two decisions
that would otherwise fail silently in a demonstration:

* an absent or unreadable state file must mean **stop**, never "keep going" —
  a loop outliving its world publishes evidence for aircraft that no longer fly;
* a failed round must be reported but must not end the loop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path("simulation/px4_gazebo/scripts").resolve()
sys.path.insert(0, str(SCRIPTS_DIR))

import calibration_loop  # noqa: E402


def _write_state(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestStateRunId:
    def test_reads_run_id_from_live_state(self, tmp_path: Path) -> None:
        state = _write_state(tmp_path / "s.json", {"run_id": "abc123"})
        assert calibration_loop.state_run_id(state) == "abc123"

    def test_missing_file_means_no_simulation(self, tmp_path: Path) -> None:
        assert calibration_loop.state_run_id(tmp_path / "absent.json") is None

    def test_corrupt_file_means_no_simulation(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert calibration_loop.state_run_id(broken) is None

    def test_state_without_run_id_means_no_simulation(self, tmp_path: Path) -> None:
        # A state file exists but carries no identity: we cannot prove it is the
        # same world, so treat it as gone rather than publish into the unknown.
        state = _write_state(tmp_path / "s.json", {"vehicles": []})
        assert calibration_loop.state_run_id(state) is None

    def test_non_object_payload_means_no_simulation(self, tmp_path: Path) -> None:
        state = _write_state(tmp_path / "s.json", ["not", "a", "dict"])
        assert calibration_loop.state_run_id(state) is None


class TestShouldContinue:
    def test_same_run_id_continues(self, tmp_path: Path) -> None:
        state = _write_state(tmp_path / "s.json", {"run_id": "r1"})
        assert calibration_loop.should_continue(state, "r1") is True

    def test_different_run_id_stops(self, tmp_path: Path) -> None:
        # A restart produces a new run id; the old loop must retire so it cannot
        # publish coordinates measured against the previous world.
        state = _write_state(tmp_path / "s.json", {"run_id": "r2"})
        assert calibration_loop.should_continue(state, "r1") is False

    def test_removed_state_stops(self, tmp_path: Path) -> None:
        state = _write_state(tmp_path / "s.json", {"run_id": "r1"})
        state.unlink()
        assert calibration_loop.should_continue(state, "r1") is False


class TestRefreshOnce:
    """``refresh_once`` must classify a round, never raise out of the loop.

    ``load_manifest`` is stubbed in every case: these tests are about the
    failure classification, not about reading a manifest off disk.
    """

    @staticmethod
    def _stub_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            calibration_loop, "load_manifest", lambda path: {"vehicles": []}
        )

    def test_capture_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._stub_manifest(monkeypatch)

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("calibration_insufficient_samples")

        monkeypatch.setattr(calibration_loop, "capture_readonly_calibrations", boom)
        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0
        )
        assert ok is False
        assert "insufficient_samples" in detail

    def test_publish_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._stub_manifest(monkeypatch)
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: [{"node_id": "UAV-01"}],
        )

        def unreachable(*args: Any, **kwargs: Any) -> Any:
            raise OSError("connection refused")

        monkeypatch.setattr(calibration_loop, "publish", unreachable)
        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0
        )
        assert ok is False
        assert "publish failed" in detail

    def test_partial_publish_is_not_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._stub_manifest(monkeypatch)
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: [{"node_id": "UAV-01"}, {"node_id": "UAV-02"}],
        )
        responses = iter([{"http_status": 200}, {"http_status": 503}])
        monkeypatch.setattr(calibration_loop, "publish", lambda *a, **k: next(responses))
        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0
        )
        # One vehicle without coordinates is still "somebody cannot be drawn",
        # so the round is reported as failed even though HTTP itself worked.
        assert ok is False
        assert "1/2" in detail

    def test_all_published_is_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._stub_manifest(monkeypatch)
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: [
                {"node_id": "UAV-01"},
                {"node_id": "UAV-02"},
                {"node_id": "UAV-03"},
            ],
        )
        monkeypatch.setattr(
            calibration_loop, "publish", lambda *a, **k: {"http_status": 200}
        )
        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0
        )
        assert ok is True
        assert "3/3" in detail


class TestProcessGone:
    """A stale ``harness_state.json`` must not keep the loop alive forever.

    The run-id check cannot distinguish "same world, still flying" from "the
    world file outlived its processes", because a manually killed simulation
    leaves the file behind with an unchanged run id.  The sampler reports
    ``calibration_process_missing`` in exactly that case; the loop counts those
    rounds and retires after ``MAX_PROCESS_MISSES``.
    """

    def test_marker_is_recognised(self) -> None:
        assert calibration_loop.is_process_gone(
            "capture failed: ValueError:calibration_process_missing"
        )

    def test_other_failures_are_not_mistaken_for_a_dead_world(self) -> None:
        for detail in (
            "capture failed: ValueError:calibration_insufficient_samples",
            "publish failed: OSError:connection refused",
            "published 2/3",
        ):
            assert calibration_loop.is_process_gone(detail) is False

    def test_give_up_threshold_is_a_small_positive_number(self) -> None:
        # Three rounds at the default 45 s interval is ≈ two minutes: long
        # enough to ride out a slow first round, short enough to notice.
        assert 2 <= calibration_loop.MAX_PROCESS_MISSES <= 5


class TestMainGuards:
    def test_duration_outside_measured_range_is_rejected(self, tmp_path: Path) -> None:
        # Below 2 s the sampler cannot reach the 10-pair / 1 s evidence floor;
        # above 10 s it exceeds the 60 s validity budget once the interval is added.
        for bad in (0.5, 1.0, 11.0, 30.0):
            with pytest.raises(SystemExit):
                calibration_loop.main(
                    ["--duration", str(bad), "--state", str(tmp_path / "s.json")]
                )

    def test_no_live_state_exits_without_looping(self, tmp_path: Path) -> None:
        code = calibration_loop.main(["--state", str(tmp_path / "absent.json")])
        assert code == 2
