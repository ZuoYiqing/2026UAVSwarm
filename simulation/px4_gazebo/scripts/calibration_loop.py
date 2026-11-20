#!/usr/bin/env python3
"""Keep public-origin calibration fresh for as long as the simulator runs.

Why this exists
---------------
The 3D view refuses to draw a vehicle until it holds *fresh* public coordinate
evidence: it must know how Gazebo's world coordinates and each PX4 instance's
local origin relate.  That mapping is measured, not computed, and the published
evidence carries a TTL (currently 60 s).  Before this script the operator had to
remember to run ``sample_calibration.py`` again every minute; forgetting it made
the aircraft disappear mid-demonstration, which looks like a software fault but
is the documented safety behaviour.

What it does **not** do
-----------------------
It never sends a flight command.  It only reads Gazebo poses and each PX4
instance's ``vehicle_local_position`` and posts the resulting transform to the
loopback Runtime, exactly like one manual ``sample_calibration.py`` run.

Lifetime
--------
The loop stops on its own as soon as the harness state disappears or reports a
different ``run_id``, so ``stop_three_uav.sh`` retires it without needing a
signal, and a restart can never leave a stale loop publishing for a dead world.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibration import capture_readonly_calibrations
from harness import RUNTIME_ROOT, load_manifest
from runtime_evidence import publish
from sample_calibration import resolve_manifest_path

STATE_PATH = RUNTIME_ROOT / "harness_state.json"

#: How many consecutive "the PX4 processes are gone" rounds to tolerate before
#: giving up.  A *stale* ``harness_state.json`` (left behind by a crash or a
#: manual kill) still carries a valid-looking ``run_id``, so the run-id check
#: alone cannot tell "same world, still flying" from "the world file outlived
#: its processes".  This counter closes that gap: after three misses (≈ two
#: minutes) the loop retires instead of retrying forever.
MAX_PROCESS_MISSES = 3

#: Substring the sampler raises when it cannot find the PX4 processes described
#: by the state file.  Treated as "simulation is gone", not as "try again".
PROCESS_GONE_MARKER = "calibration_process_missing"


def is_process_gone(detail: str) -> bool:
    """True when a failed round failed because the simulation is not there."""
    return PROCESS_GONE_MARKER in detail



def state_run_id(state_path: Path) -> str | None:
    """Return the ``run_id`` recorded by the currently running harness.

    ``None`` means "no live simulation": the file is missing, unreadable, or
    carries no run id.  Callers treat that as "stop", never as "keep going" —
    a loop that outlives its simulation would publish evidence for a world that
    no longer exists.
    """
    try:
        payload = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id")
    return str(run_id) if run_id else None


def should_continue(state_path: Path, run_id: str) -> bool:
    """True while the same simulation that started this loop is still live."""
    return state_run_id(state_path) == run_id


def refresh_once(config: Path, runtime_base: str, duration_s: float) -> tuple[bool, str]:
    """Capture and publish one round of calibration evidence.

    Returns ``(ok, detail)`` instead of raising: a single failed round must not
    end the loop, because the next round usually succeeds once the Runtime or a
    vehicle stops being busy.
    """
    try:
        calibrations = capture_readonly_calibrations(
            load_manifest(config), duration_s=duration_s
        )
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return False, f"capture failed: {type(exc).__name__}:{exc}"
    try:
        publications = [
            publish(runtime_base, row, kind="calibration") for row in calibrations
        ]
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return False, f"publish failed: {type(exc).__name__}:{exc}"
    accepted = sum(1 for row in publications if row.get("http_status") == 200)
    if accepted != len(publications):
        return False, f"published {accepted}/{len(publications)}"
    return True, f"published {accepted}/{len(publications)}"


def _sleep_watching(seconds: float, state_path: Path, run_id: str) -> bool:
    """Sleep in short slices so a stopped simulation ends the loop promptly."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not should_continue(state_path, run_id):
            return False
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    return should_continue(state_path, run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="manifest 路径；省略时采用 harness state 记录的、当前正在跑的那一份",
    )
    parser.add_argument("--runtime", default="http://127.0.0.1:8765/api")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=45.0)
    parser.add_argument(
        "--once",
        action="store_true",
        help="只刷新一轮就退出（等价于跑一次 sample_calibration.py）",
    )
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    args = parser.parse_args(argv)

    if not 2 <= args.duration <= 10:
        parser.error("--duration must be in 2..10")
    if args.interval < 0:
        parser.error("--interval must be >= 0")

    run_id = state_run_id(args.state)
    if run_id is None and not args.once:
        print(
            f"calibration_loop: no live harness state at {args.state}; "
            "start the simulation first",
            file=sys.stderr,
        )
        return 2

    config = resolve_manifest_path(args.config, state_path=args.state)
    print(
        f"calibration_loop: manifest={config} runtime={args.runtime} "
        f"duration={args.duration}s interval={args.interval}s run_id={run_id}",
        flush=True,
    )

    try:
        misses = 0
        while True:
            ok, detail = refresh_once(config, args.runtime, args.duration)
            stamp = time.strftime("%H:%M:%S")
            print(
                f"[{stamp}] {'ok' if ok else 'retry'}: {detail}",
                flush=True,
            )
            if args.once:
                return 0 if ok else 1
            # A round that cannot even find the PX4 processes means the world
            # is gone while its state file survives.  Retire rather than spin.
            if not ok and is_process_gone(detail):
                misses += 1
                if misses >= MAX_PROCESS_MISSES:
                    print(
                        "calibration_loop: PX4 processes are gone; "
                        "the recorded simulation has ended. Stopping.",
                        flush=True,
                    )
                    return 0
            else:
                misses = 0
            if not _sleep_watching(args.interval, args.state, run_id or ""):
                print("calibration_loop: simulation stopped; exiting", flush=True)
                return 0
    except KeyboardInterrupt:
        print("\ncalibration_loop: interrupted", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
