"""Opt-in fake-only CLI process check. Never start PX4, a model, WSL or flight tasks."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

from uav_runtime.platform.contract import canonical, stamp
from uav_runtime.platform.transport import JsonClient


def memory_admission(available_gib, measured_at, *, now=None):
    now = time.time() if now is None else now
    if (not all(math.isfinite(v) for v in (available_gib, measured_at, now))
            or available_gib < 3 or not 0 <= now - measured_at <= 60):
        raise RuntimeError("fresh_host_memory_measurement_required_minimum_3gib")


def assert_offline_projections(snapshot, telemetry, simulation, evidence):
    rows = snapshot["vehicles"]
    if ({row["id"] for row in rows} != {"UAV-01", "UAV-02", "UAV-03"} or len(rows) != 3
            or any(row.get("connected") is not False or row["telemetry"].get("stale") is not True
                   or row["spatial"].get("public_position_usable") is not False for row in rows)
            or telemetry.get("fresh") is not False or simulation.get("status") == "ready"
            or len(evidence["vehicles"]) != 3
            or any(row.get("heartbeat_fresh") is not False or row.get("telemetry_fresh") is not False
                   for row in evidence["vehicles"])
            or evidence.get("execution_authorized") is not False or evidence.get("flight_command_sent") is not False):
        raise RuntimeError("fake_or_offline_projection_became_live")


def port_listening(port):
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_for(check, processes, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("owned_child_exited_early")
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise RuntimeError("bounded_process_check_timeout")


def stop_owned(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()  # Only a handle created below, always fake/no MAVLink.
            process.wait(timeout=5)


def verify(output, *, runtime_commit):
    if any(port_listening(port) for port in (8765, 8766)):
        raise RuntimeError("application_port_already_owned")
    # Probe only the two application ports, never 14540/14541/14542.
    for port in (8765, 8766):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    token = secrets.token_urlsafe(48)
    token_path = output / "local-token"
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    run_id = "fake-process-smoke-" + secrets.token_hex(8)
    environment = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONNOUSERSITE": "1",
                   "PYTHONDONTWRITEBYTECODE": "1", "UAV_RUNTIME_TELEMETRY_ENABLED": "false",
                   "UAV_RUNTIME_AUDIT_PATH": str(output / "actions.audit.jsonl")}
    commands = {
        "platform": [sys.executable, "-B", "-m", "uav_runtime.platform.server", "--node-id", "UAV-02",
                     "--execution-mode", "fake", "--port", "8766", "--store-dir", str(output / "agent-store"),
                     "--token-file", str(token_path), "--run-id", run_id],
        "ground": [sys.executable, "-B", "-m", "uav_runtime.http.server", "--exclude-node", "UAV-02",
                   "--platform-url", "http://127.0.0.1:8766", "--platform-token-file", str(token_path),
                   "--run-id", run_id],
    }
    processes, logs = [], []
    report = {"started_at": stamp(time.time()), "runtime_commit": runtime_commit, "run_id": run_id,
              "execution_mode": "fake", "flight_command_sent": False, "task_submitted": False,
              "px4_started": False, "model_started": False, "managed_simulation_run": False,
              "telemetry_enabled": False, "verification_passed": False, "processes": [], "checks": {}}

    def spawn(role):
        log = (output / f"{role}-{len(processes)}.log").open("ab", buffering=0)
        logs.append(log)
        process = subprocess.Popen(commands[role], cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)
        report["processes"].append({"role": role, "pid": process.pid})
        return process

    platform_client = JsonClient("http://127.0.0.1:8766", token, timeout=1)
    ground_client = JsonClient("http://127.0.0.1:8765", timeout=1)

    def platform_status():
        code, value = platform_client.request("GET", "/api/platform/status")
        if code != 200 or value.get("execution_mode") != "fake" or value.get("run_id") != run_id:
            raise RuntimeError("wrong_platform_process_or_mode")
        return value

    def link_is(state):
        value = platform_status()
        return value if value["ground_link"]["state"] == state else None

    try:
        platform = spawn("platform")
        initial = wait_for(platform_status, [platform])
        if JsonClient("http://127.0.0.1:8766", timeout=1).request("GET", "/api/platform/status")[0] != 401:
            raise RuntimeError("platform_authentication_not_enforced")
        ground = spawn("ground")
        wait_for(lambda: ground_client.request("GET", "/api/health")[0] == 200, [ground, platform])
        healthy = wait_for(lambda: link_is("healthy"), [ground, platform])
        if ground.pid == platform.pid:
            raise RuntimeError("runtime_roles_are_not_independent_processes")
        paths = ("/api/vehicle-snapshot", "/api/telemetry/latest", "/api/simulation/status", "/api/simulation/runtime-telemetry")
        responses = {}
        for path in paths:
            code, value = ground_client.request("GET", path)
            if code != 200:
                raise RuntimeError("read_only_projection_failed")
            responses[path] = value
        assert_offline_projections(*(responses[path] for path in paths))
        report["responses"] = responses
        report["checks"].update({"independent_cli_processes": True, "authentication": True,
                                 "ground_heartbeat_received": True, "fake_never_px4_live": True})
        stop_owned(ground)
        lost = wait_for(lambda: link_is("lost"), [platform], timeout=10)
        restarted_ground = spawn("ground")
        restored = wait_for(lambda: link_is("healthy"), [platform, restarted_ground])
        identities = ("boot_id", "store_id", "event_seq")
        if (any(any(value[field] != initial[field] for field in identities) for value in (healthy, lost, restored))
                or any(value.get("active_task") is not None for value in (initial, healthy, lost, restored))):
            raise RuntimeError("platform_restarted_or_executed_task")
        report["platform_statuses"] = {"initial": initial, "healthy": healthy, "lost": lost, "restored": restored}
        report["checks"].update({"ground_stop_does_not_stop_platform": True, "link_loss_observed": True,
                                 "ground_restart_restores_link": True, "platform_identity_and_events_unchanged": True})
        report["verification_passed"] = True
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "reason": str(exc)}
    finally:
        cleanup_errors = []
        for process in reversed(processes):
            try:
                stop_owned(process)
            except Exception as exc:
                cleanup_errors.append({"pid": process.pid, "error_class": type(exc).__name__})
        for log in logs:
            log.close()
        report["owned_processes_stopped"] = all(p.poll() is not None for p in processes)
        report["application_ports_released"] = not any(port_listening(port) for port in (8765, 8766))
        report["cleanup_errors"] = cleanup_errors
        report["verification_passed"] &= report["owned_processes_stopped"] and report["application_ports_released"] and not cleanup_errors
        report["finished_at"] = stamp(time.time())
        (output / "report.json").write_text(canonical(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-commit", required=True)
    parser.add_argument("--host-available-gib", type=float, required=True)
    parser.add_argument("--host-measured-at", type=float, required=True)
    args = parser.parse_args(argv)
    memory_admission(args.host_available_gib, args.host_measured_at)
    report = verify(args.output.resolve(), runtime_commit=args.runtime_commit)
    print(json.dumps({key: report[key] for key in ("verification_passed", "flight_command_sent", "checks", "owned_processes_stopped", "application_ports_released")}))
    return 0 if report["verification_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
