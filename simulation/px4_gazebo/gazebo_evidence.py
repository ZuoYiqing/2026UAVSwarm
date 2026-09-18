"""Read-only Gazebo clock, pose and managed server identity evidence."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import harness
    from .evidence import json_messages, proto_time
except ImportError:
    import harness
    from evidence import json_messages, proto_time


def clock_summary(messages: list[dict[str, Any]], *, minimum_window_s: float = 1.0, minimum_rtf: float = 0.2) -> dict[str, Any]:
    samples = [(proto_time(row["sim"]), proto_time(row["real"]))
               for row in messages if "sim" in row and "real" in row]
    reason = "ok"
    sim_span = real_span = rtf = 0.0
    if len(samples) < 3:
        reason = "gazebo_clock_insufficient_samples"
    else:
        sim_span = samples[-1][0] - samples[0][0]
        real_span = samples[-1][1] - samples[0][1]
        rtf = sim_span / real_span if real_span > 0 else 0.0
        if any(b[0] < a[0] or b[1] <= a[1] for a, b in zip(samples, samples[1:])):
            reason = "gazebo_clock_reset"
        elif real_span < minimum_window_s:
            reason = "gazebo_clock_insufficient_window"
        elif sim_span <= 0:
            reason = "gazebo_clock_stalled"
        elif any(b[1] - a[1] > 1.0 for a, b in zip(samples, samples[1:])):
            reason = "gazebo_clock_sample_gap"
        elif rtf < minimum_rtf:
            reason = "gazebo_clock_slow"
    return {"clock_advancing": reason == "ok", "reason": reason, "evidence": {
        "sample_count": len(samples), "sim_span_s": sim_span, "real_span_s": real_span,
        "real_time_factor": rtf, "minimum_real_time_factor": minimum_rtf,
        "minimum_window_s": minimum_window_s,
        "first_sim_s": samples[0][0] if samples else None,
        "last_sim_s": samples[-1][0] if samples else None,
    }}


def probe_clock(world: str, timeout_s: float, *, duration_s: float = 2.0) -> dict[str, Any]:
    topic = f"/world/{world}/clock"
    started = time.monotonic()
    try:
        result = subprocess.run(["gz", "topic", "-e", "-t", topic, "-d", str(duration_s), "--json-output"],
                                capture_output=True, text=True, timeout=duration_s + max(3.0, timeout_s), check=False)
        if result.returncode:
            raise ValueError(f"gz_exit:{result.returncode}:{result.stderr.strip()}")
        messages = json_messages(result.stdout)
        summary = clock_summary(messages)
        if messages:
            summary["source_timestamp"] = datetime.fromtimestamp(proto_time(messages[-1]["system"]), timezone.utc).isoformat()
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        summary = {"clock_advancing": False, "reason": "gazebo_clock_probe_failed",
                   "evidence": {"error": f"{type(exc).__name__}:{exc}"}}
    summary["evidence"].update(topic=topic, wall_elapsed_s=time.monotonic() - started)
    return summary


def capture_server_processes(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Capture only servers in this run's already-owned PX4 process group."""
    owners = {int(row["pgid"]): row for row in state["processes"] if row.get("owns_gazebo")}
    rows = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        observed = harness.read_process_identity(int(proc.name))
        identity = observed.identity
        if identity is None or identity.pgid not in owners or identity.run_id != state["run_id"]:
            continue
        command = " ".join(identity.cmdline)
        if "gz sim" not in command and "gz-sim-server" not in command:
            continue
        if str(state["world_name"]) not in command:
            continue
        owner = owners[identity.pgid]
        rows.append({"kind": "gazebo", "node_id": owner["node_id"], "pid": identity.pid,
                     "pgid": identity.pgid, "run_id": identity.run_id,
                     "runtime_dir": identity.cwd, "process_identity": identity.to_dict()})
    if not rows:
        raise harness.HarnessError("gazebo_process_identity_missing")
    return rows


def server_identity(state: dict[str, Any], *, identity_reader=None) -> dict[str, Any]:
    rows = state.get("gazebo_processes", [])
    decisions = [harness.validate_process_identity(row, run_id=str(state.get("run_id", "")),
                                                  identity_reader=identity_reader) for row in rows]
    valid = bool(decisions) and all(row.code == harness.IDENTITY_MATCH for row in decisions)
    return {"process_identity_valid": valid,
            "reason": "ok" if valid else "gazebo_process_identity_invalid",
            "processes": [row.to_dict() for row in decisions]}


def capture_poses(world: str, duration_s: float) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(["gz", "topic", "-e", "-t", f"/world/{world}/dynamic_pose/info",
                                 "-d", str(duration_s), "--json-output"],
                                capture_output=True, text=True, timeout=duration_s + 5, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("gazebo_pose_probe_timeout") from exc
    if result.returncode:
        raise ValueError(f"gazebo_pose_probe_failed:{result.stderr}")
    return json_messages(result.stdout)
