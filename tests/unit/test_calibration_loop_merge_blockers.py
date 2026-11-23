"""Extra tests for the two merge blockers the Runtime lead found.

Both are behaviour regressions that a "tests pass" claim would have hidden:

* ``start_three_uav.sh`` used to return; an ``exec`` into the refresh loop made
  it block forever, so "start, then launch Runtime" scripts hung.
* the refresh loop published before re-checking the run id, so a simulation
  replaced mid-capture still had its *old* transform posted.
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


class TestStartScriptReturns:
    """The shell entry point must not block after starting the simulation."""

    @staticmethod
    def _script_text() -> str:
        return (SCRIPTS_DIR / "start_three_uav.sh").read_text(encoding="utf-8")

    def test_does_not_exec_the_loop(self) -> None:
        # ``exec`` replaces the shell, so anything after it never runs and the
        # caller waits on a process that no longer exists as "start".
        for line in self._script_text().splitlines():
            stripped = line.strip()
            assert not stripped.startswith("exec "), (
                "start_three_uav.sh must not exec; it has to return so the "
                "caller can start Runtime afterwards"
            )

    def test_detaches_the_loop(self) -> None:
        text = self._script_text()
        assert "calibration_loop.py" in text
        # Detached, not foreground: nohup + background plus setsid so closing
        # the terminal does not take the refresher with it.
        assert "setsid" in text
        assert "nohup" in text
        assert text.rstrip().endswith('echo "start_three_uav: calibration loop detached; log ${LOG}"')

    def test_has_an_escape_hatch(self) -> None:
        assert "UAV_SIM_NO_AUTOCALIB" in self._script_text()


class TestRunChangeIsDiscardedBeforePublish:
    """A world replaced during the capture window must not have its old
    transform posted, even though the captured bytes look perfectly valid."""

    @staticmethod
    def _state(path: Path, run_id: str) -> Path:
        path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        return path

    def test_publish_is_skipped_when_run_changed_mid_capture(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda path: {})
        state = self._state(tmp_path / "s.json", "run-NEW")
        published: list[Any] = []

        def capture_then_switch(*args: Any, **kwargs: Any) -> Any:
            # The simulation restarts while bytes are being sampled.
            return [{"node_id": "UAV-01"}]

        monkeypatch.setattr(
            calibration_loop, "capture_readonly_calibrations", capture_then_switch
        )
        monkeypatch.setattr(
            calibration_loop,
            "publish",
            lambda *a, **k: published.append(a) or {"http_status": 200},
        )

        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json",
            "http://127.0.0.1:8765/api",
            10.0,
            state_path=state,
            expected_run="run-OLD",
        )

        assert ok is False
        assert detail.startswith("run changed")
        assert published == [], "stale calibration must never reach the Runtime"

    def test_publish_proceeds_when_run_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda path: {})
        state = self._state(tmp_path / "s.json", "run-SAME")
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: [{"node_id": "UAV-01"}],
        )
        monkeypatch.setattr(
            calibration_loop, "publish", lambda *a, **k: {"http_status": 200}
        )

        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json",
            "http://127.0.0.1:8765/api",
            10.0,
            state_path=state,
            expected_run="run-SAME",
        )

        assert ok is True
        assert "1/1" in detail

    def test_loop_retires_immediately_on_run_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # No point sleeping the full interval once we know the world is gone.
        monkeypatch.setattr(
            calibration_loop,
            "refresh_once",
            lambda *a, **k: (False, "run changed during capture; discarded before publish"),
        )
        slept: list[float] = []
        monkeypatch.setattr(
            calibration_loop, "_sleep_watching", lambda s, p, r: slept.append(s) or True
        )
        state = self._state(tmp_path / "s.json", "run-1")

        code = calibration_loop.main(
            [
                "--state", str(state),
                "--config", str(tmp_path / "m.json"),
                "--pid-file", str(tmp_path / "loop.pid"),
            ]
        )

        assert code == 0
        assert slept == []


class TestSingleInstancePerRun:
    @staticmethod
    def _state(path: Path, run_id: str) -> Path:
        path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        return path

    def test_second_loop_for_same_run_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = self._state(tmp_path / "s.json", "run-1")
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 4242, "run-1")
        monkeypatch.setattr(calibration_loop, "pid_alive", lambda pid: True)
        started: list[int] = []
        monkeypatch.setattr(
            calibration_loop, "_run", lambda *a, **k: started.append(1) or 0
        )

        code = calibration_loop.main(
            [
                "--state", str(state),
                "--config", str(tmp_path / "m.json"),
                "--pid-file", str(pid_file),
            ]
        )

        assert code == 0
        assert started == [], "a second refresher for the same run must not start"

    def test_dead_pid_is_replaced(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = self._state(tmp_path / "s.json", "run-1")
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 4242, "run-1")
        monkeypatch.setattr(calibration_loop, "pid_alive", lambda pid: False)
        ran: list[int] = []
        monkeypatch.setattr(
            calibration_loop, "_run", lambda *a, **k: ran.append(1) or 0
        )

        calibration_loop.main(
            [
                "--state", str(state),
                "--config", str(tmp_path / "m.json"),
                "--pid-file", str(pid_file),
            ]
        )

        assert ran == [1]

    def test_stale_run_is_taken_over(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = self._state(tmp_path / "s.json", "run-NEW")
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 4242, "run-OLD")
        monkeypatch.setattr(calibration_loop, "pid_alive", lambda pid: True)
        ran: list[int] = []
        monkeypatch.setattr(
            calibration_loop, "_run", lambda *a, **k: ran.append(1) or 0
        )

        calibration_loop.main(
            [
                "--state", str(state),
                "--config", str(tmp_path / "m.json"),
                "--pid-file", str(pid_file),
            ]
        )

        assert ran == [1], "a refresher from a dead run must not block the new one"
        # The pid file is cleaned up on exit, and only if it is still ours.
        assert not pid_file.exists()

    def test_cleanup_does_not_steal_another_processes_pid_file(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 9999, "run-1")
        calibration_loop.clear_pid_file(pid_file, 4242)
        assert pid_file.exists(), "a newer loop's pid file must survive old cleanup"
