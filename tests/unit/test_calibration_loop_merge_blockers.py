"""Extra tests for the two merge blockers the Runtime lead found.

Both are behaviour regressions that a "tests pass" claim would have hidden:

* ``start_three_uav.sh`` used to return; an ``exec`` into the refresh loop made
  it block forever, so "start, then launch Runtime" scripts hung.
* the refresh loop published before re-checking the run id, so a simulation
  replaced mid-capture still had its *old* transform posted.
"""
from __future__ import annotations

import json
import subprocess
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
    """Mutual exclusion must be an OS lock, not a pid file.

    A pid file cannot make claim-and-cleanup atomic: two workers can both read
    "absent" and both start.  These tests exercise the lock directly, including
    one genuine race between two real processes.
    """

    @staticmethod
    def _state(path: Path, run_id: str) -> Path:
        path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        return path

    def test_lock_is_exclusive_within_one_process(self, tmp_path: Path) -> None:
        lock = tmp_path / "w.lock"
        with calibration_loop.exclusive_worker(lock) as first:
            assert first is True
            # A second open file description of the same file must not win,
            # even in the same process — that is what makes claim atomic.
            with calibration_loop.exclusive_worker(lock) as second:
                assert second is False

    def test_lock_is_released_when_the_block_exits(self, tmp_path: Path) -> None:
        lock = tmp_path / "w.lock"
        with calibration_loop.exclusive_worker(lock) as owned:
            assert owned is True
        with calibration_loop.exclusive_worker(lock) as again:
            assert again is True

    def test_exactly_one_of_two_real_processes_wins(self, tmp_path: Path) -> None:
        # Real concurrency, not sequential starts: both processes are launched
        # against the same lock and the winner holds it long enough that the
        # loser cannot miss it.
        lock = tmp_path / "race.lock"
        here = str(SCRIPTS_DIR)
        code = (
            "import sys, time\n"
            f"sys.path.insert(0, {here!r})\n"
            "import calibration_loop\n"
            "from pathlib import Path\n"
            f"with calibration_loop.exclusive_worker(Path({str(lock)!r})) as owned:\n"
            "    print('OWNED' if owned else 'BUSY')\n"
            "    if owned:\n"
            "        time.sleep(1.5)\n"
        )
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        outputs = [p.communicate(timeout=30)[0].strip() for p in procs]
        assert outputs.count("OWNED") == 1, outputs
        assert outputs.count("BUSY") == 1, outputs

    def test_duplicate_start_for_same_run_exits_without_waiting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = self._state(tmp_path / "s.json", "run-1")
        pid_file = tmp_path / "loop.pid"
        lock = tmp_path / "w.lock"
        started: list[int] = []
        monkeypatch.setattr(
            calibration_loop, "_run", lambda *a, **k: started.append(1) or 0
        )
        calibration_loop.write_pid_file(pid_file, 4242, "run-1")

        with calibration_loop.exclusive_worker(lock) as owned:
            assert owned is True
            code = calibration_loop.main(
                [
                    "--state", str(state),
                    "--config", str(tmp_path / "m.json"),
                    "--pid-file", str(pid_file),
                    "--lock-file", str(lock),
                    "--lock-wait", "30",
                ]
            )

        assert code == 0
        assert started == [], "a duplicate for the same run must not start"
        # And it must not have waited the full 30 s either.

    def test_new_run_waits_for_the_old_worker_to_finish(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The old worker may still be finishing a 10 s capture when the new
        # simulation starts.  Refusing outright would leave nobody refreshing,
        # so a new worker waits for the handover instead.
        import threading

        state = self._state(tmp_path / "s.json", "run-NEW")
        pid_file = tmp_path / "loop.pid"
        lock = tmp_path / "w.lock"
        ran: list[int] = []
        monkeypatch.setattr(
            calibration_loop, "_run", lambda *a, **k: ran.append(1) or 0
        )
        calibration_loop.write_pid_file(pid_file, 4242, "run-OLD")

        holder = calibration_loop.exclusive_worker(lock)
        assert holder.__enter__() is True
        threading.Timer(0.8, holder.__exit__, (None, None, None)).start()

        code = calibration_loop.main(
            [
                "--state", str(state),
                "--config", str(tmp_path / "m.json"),
                "--pid-file", str(pid_file),
                "--lock-file", str(lock),
                "--lock-wait", "10",
            ]
        )

        assert code == 0
        assert ran == [1], "the new run must take over once the old worker lets go"

    def test_gives_up_loudly_when_lock_never_released(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = self._state(tmp_path / "s.json", "run-NEW")
        pid_file = tmp_path / "loop.pid"
        lock = tmp_path / "w.lock"
        monkeypatch.setattr(calibration_loop, "_run", lambda *a, **k: 0)
        calibration_loop.write_pid_file(pid_file, 4242, "run-OLD")

        with calibration_loop.exclusive_worker(lock) as owned:
            assert owned is True
            code = calibration_loop.main(
                [
                    "--state", str(state),
                    "--config", str(tmp_path / "m.json"),
                    "--pid-file", str(pid_file),
                    "--lock-file", str(lock),
                    "--lock-wait", "0.6",
                ]
            )

        assert code == 1, "a permanently stuck lock must surface, not hang"

    def test_pid_file_is_only_diagnostic(self, tmp_path: Path) -> None:
        # A stale pid file must never block a worker: the lock decides.
        lock = tmp_path / "w.lock"
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 999999, "run-OLD")
        with calibration_loop.exclusive_worker(lock) as owned:
            assert owned is True

    def test_cleanup_does_not_steal_another_processes_pid_file(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "loop.pid"
        calibration_loop.write_pid_file(pid_file, 9999, "run-1")
        calibration_loop.clear_pid_file(pid_file, 4242)
        assert pid_file.exists(), "a newer worker's pid file must survive"


class TestPerRowRunCheck:
    """Publishing is three POSTs, not one.  Each one must be re-checked.

    Checking the run once before the batch lets row 2 and 3 of a dead world go
    out while the call still reports success.
    """

    @staticmethod
    def _state(path: Path, run_id: str) -> Path:
        path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        return path

    @staticmethod
    def _rows(*run_ids: str) -> list[dict[str, Any]]:
        return [{"node_id": f"UAV-0{i}", "context": {"run_id": r}} for i, r in enumerate(run_ids, 1)]

    def test_evidence_from_a_retired_run_stops_the_batch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda p: {})
        state = self._state(tmp_path / "s.json", "run-2")
        # Row 2 was captured against the previous world.
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: self._rows("run-1", "run-1", "run-1"),
        )
        sent: list[str] = []
        monkeypatch.setattr(
            calibration_loop,
            "publish",
            lambda base, row, **k: sent.append(row["node_id"]) or {"http_status": 200},
        )

        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0,
            state_path=state, expected_run="run-1",
        )

        assert ok is False
        assert sent == [], "no row of a retired run may be published"

    def test_run_switch_between_rows_stops_the_batch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda p: {})
        state = tmp_path / "s.json"
        self._state(state, "run-1")
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: self._rows("run-1", "run-1", "run-1"),
        )
        sent: list[str] = []

        def publish_and_restart(base: str, row: dict, **k: Any) -> dict:
            sent.append(row["node_id"])
            if len(sent) == 1:
                # The simulation restarts right after the first POST.
                self._state(state, "run-2")
            return {"http_status": 200}

        monkeypatch.setattr(calibration_loop, "publish", publish_and_restart)

        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0,
            state_path=state, expected_run="run-1",
        )

        assert ok is False, "a batch cut short is not a successful round"
        assert sent == ["UAV-01"], "only the row already in flight may go out"
        assert "run changed while publishing" in detail

    def test_failure_mid_batch_is_not_reported_as_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda p: {})
        state = self._state(tmp_path / "s.json", "run-1")
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: self._rows("run-1", "run-1"),
        )
        calls: list[str] = []

        def flaky(base: str, row: dict, **k: Any) -> dict:
            calls.append(row["node_id"])
            if len(calls) == 2:
                raise OSError("connection refused")
            return {"http_status": 200}

        monkeypatch.setattr(calibration_loop, "publish", flaky)

        ok, detail = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0,
            state_path=state, expected_run="run-1",
        )

        assert ok is False
        assert "publish failed at 2/2" in detail

    def test_evidence_without_a_run_context_still_gets_the_state_check(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Older evidence payloads carry no context; the state check must still
        # gate them rather than silently letting them through.
        monkeypatch.setattr(calibration_loop, "load_manifest", lambda p: {})
        state = self._state(tmp_path / "s.json", "run-2")
        monkeypatch.setattr(
            calibration_loop,
            "capture_readonly_calibrations",
            lambda *a, **k: [{"node_id": "UAV-01"}, {"node_id": "UAV-02"}],
        )
        sent: list[str] = []
        monkeypatch.setattr(
            calibration_loop,
            "publish",
            lambda base, row, **k: sent.append(row["node_id"]) or {"http_status": 200},
        )

        ok, _ = calibration_loop.refresh_once(
            tmp_path / "m.json", "http://127.0.0.1:8765/api", 10.0,
            state_path=state, expected_run="run-1",
        )

        assert ok is False
        assert sent == []
