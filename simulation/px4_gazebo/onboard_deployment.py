"""Manage one platform Agent and its application-only link proxy.

SITL stop requires fresh landed/disarmed proof from the sole Runtime receiver.
No command in this module binds a MAVLink endpoint or sends a flight action.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    from . import app_link_proxy, harness, onboard_topology
    from .evidence import atomic_json, timestamp_seconds
    from .runtime_evidence import NoRedirect
except ImportError:  # Direct script execution.
    import app_link_proxy  # type: ignore
    import harness  # type: ignore
    import onboard_topology  # type: ignore
    from evidence import atomic_json, timestamp_seconds  # type: ignore
    from runtime_evidence import NoRedirect  # type: ignore


STATE_PATH = harness.RUNTIME_ROOT / "onboard_deployment_state.json"
AGENT_DIR = harness.RUNTIME_ROOT / "UAV-02-agent"
PROXY_DIR = harness.RUNTIME_ROOT / "UAV-02-ground-link"
AGENT_PORT = 8766
PROXY_PORT = 8767
RUNTIME_VEHICLE_CONFIG = harness.REPO_ROOT / "config/vehicles.sitl.json"


class DeploymentError(RuntimeError):
    pass


def _available_tcp(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _listening_tcp(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_ports(processes: list[subprocess.Popen[Any]], *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise DeploymentError("agent_or_proxy_exited_during_start")
        if _listening_tcp(AGENT_PORT) and _listening_tcp(PROXY_PORT):
            return
        time.sleep(.1)
    raise DeploymentError("agent_or_proxy_application_port_not_ready")


def _managed_harness() -> tuple[dict[str, Any], dict[str, Any]]:
    state = harness.read_state()
    if not state or not state.get("run_id"):
        raise DeploymentError("managed_simulation_run_missing")
    manifest_path = harness.resolve_repo_path(onboard_topology.SIMULATION_MANIFEST).resolve()
    if Path(str(state.get("manifest_path", ""))).resolve() != manifest_path:
        raise DeploymentError("running_simulation_manifest_mismatch")
    manifest = harness.load_manifest(manifest_path)
    runtime_vehicles = json.loads(RUNTIME_VEHICLE_CONFIG.read_text(encoding="utf-8"))
    harness.validate_runtime_mapping(manifest, runtime_vehicles)
    onboard_topology.load_topology()
    decisions = harness._validate_processes(state.get("processes", []), run_id=state["run_id"])
    if len(decisions) != 3 or any(row.code != harness.IDENTITY_MATCH for row in decisions):
        raise DeploymentError("managed_px4_process_identity_invalid")
    return state, manifest


def _validate_token_file(token_file: Path) -> None:
    if not token_file.is_file():
        raise DeploymentError("platform_token_file_missing_or_invalid")
    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32 or any(character.isspace() for character in token):
        raise DeploymentError("platform_token_file_missing_or_invalid")


def _agent_command(token_file: Path, run_id: str, mode: str = "fake") -> list[str]:
    return [
        sys.executable, "-m", "uav_runtime.platform.server",
        "--node-id", "UAV-02", "--port", str(AGENT_PORT),
        "--store-dir", str(AGENT_DIR.resolve()),
        "--token-file", str(token_file.resolve()),
        "--execution-mode", mode,
        "--vehicle-config", str(RUNTIME_VEHICLE_CONFIG.resolve()),
        "--run-id", run_id,
    ]


def _entry(kind: str, process: subprocess.Popen[Any], runtime_dir: Path,
           run_id: str) -> dict[str, Any]:
    observed = harness.read_process_identity(process.pid)
    for _ in range(9):
        if observed.code == harness.IDENTITY_OBSERVED or process.poll() is not None:
            break
        time.sleep(.05)
        observed = harness.read_process_identity(process.pid)
    identity = observed.identity
    if (observed.code != harness.IDENTITY_OBSERVED or identity is None
            or identity.pgid != process.pid or identity.run_id != run_id
            or identity.cwd != str(runtime_dir.resolve())):
        raise DeploymentError(f"{kind}_process_identity_not_captured")
    return {
        "kind": kind, "node_id": f"UAV-02-{kind}", "pid": process.pid,
        "pgid": identity.pgid, "run_id": run_id,
        "runtime_dir": str(runtime_dir.resolve()),
        "process_identity": identity.to_dict(),
    }


def _spawn(command: list[str], *, runtime_dir: Path, run_id: str,
           environment: dict[str, str]) -> subprocess.Popen[Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with (runtime_dir / "stdout.log").open("ab", buffering=0) as stdout, \
            (runtime_dir / "stderr.log").open("ab", buffering=0) as stderr:
        return subprocess.Popen(
            command, cwd=runtime_dir,
            env={**environment, harness.HARNESS_RUN_ID_ENV: run_id},
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            start_new_session=True,
        )


def inspect(state_path: Path = STATE_PATH) -> dict[str, Any]:
    if not state_path.is_file():
        return {"status": "not_started", "process_identity_valid": False}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        processes = state["processes"]
        decisions = harness._validate_processes(processes, run_id=str(state["run_id"]))
        current = harness.read_state() or {}
        run_matches = bool(current.get("run_id") == state["run_id"])
        link_path = Path(state["link_state_path"]).resolve()
        if link_path != (PROXY_DIR / f"link_state.{state['run_id']}.json").resolve():
            raise ValueError("link_state_path_mismatch")
        link = app_link_proxy.read_state(link_path, state["run_id"])
        ports_open = _listening_tcp(AGENT_PORT) and _listening_tcp(PROXY_PORT)
        roles_match = (state.get("node_id") == "UAV-02" and
                       {(row.get("node_id"), row.get("kind")) for row in processes} ==
                       {("UAV-02-agent", "agent"), ("UAV-02-link", "link")})
        valid = (run_matches and roles_match and ports_open and len(decisions) == 2
                 and all(row.code == harness.IDENTITY_MATCH for row in decisions))
        return {
            "status": "process_ready" if valid else "not_ready",
            "run_id": state["run_id"], "node_id": "UAV-02",
            "execution_mode": state["execution_mode"],
            "process_identity_valid": valid,
            "application_ports_open": ports_open,
            "agent_api_validated": False,
            "system_readiness": "unverified",
            "agent_port": AGENT_PORT, "ground_proxy_port": PROXY_PORT,
            "ground_link_mode": link["mode"],
            "processes": [row.to_dict() for row in decisions],
            "reason": "ok" if valid else "run_or_process_identity_mismatch",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"status": "not_ready", "process_identity_valid": False,
                "reason": f"deployment_state_invalid:{type(exc).__name__}:{exc}"}


def _start(*, token_file: Path, mode: str, state_path: Path) -> dict[str, Any]:
    if mode not in {"fake", "sitl"}:
        raise DeploymentError("unsupported_execution_mode")
    if state_path.exists():
        raise DeploymentError("deployment_state_already_exists")
    simulation, _manifest = _managed_harness()
    run_id = str(simulation["run_id"])
    _validate_token_file(token_file)
    if not _available_tcp(AGENT_PORT) or not _available_tcp(PROXY_PORT):
        raise DeploymentError("application_port_in_use")
    # Fake mode never opens MAVLink. Do not bind even briefly to probe 14541;
    # the sole receiver's ownership is checked in the exclusive SITL window.
    if not (harness.REPO_ROOT / "src/uav_runtime/platform/server.py").is_file():
        raise DeploymentError("runtime_platform_module_missing")

    agent_command = _agent_command(token_file, run_id, mode)
    link_state_path = PROXY_DIR / f"link_state.{run_id}.json"
    proxy_command = [
        sys.executable, str(Path(app_link_proxy.__file__).resolve()), "serve",
        "--state-path", str(link_state_path.resolve()), "--run-id", run_id,
        "--listen-port", str(PROXY_PORT), "--target-port", str(AGENT_PORT),
    ]
    environment = {**os.environ, "PYTHONPATH": str(harness.REPO_ROOT / "src")}
    state: dict[str, Any] = {
        "version": "0.1", "run_id": run_id, "node_id": "UAV-02",
        "execution_mode": mode, "link_state_path": str(link_state_path.resolve()),
        "token_file": str(token_file.resolve()), "processes": [],
    }
    spawned: list[subprocess.Popen[Any]] = []
    try:
        app_link_proxy.set_state(link_state_path, run_id=run_id, mode="down")
        agent = _spawn(agent_command, runtime_dir=AGENT_DIR, run_id=run_id,
                       environment=environment)
        spawned.append(agent)
        state["processes"].append(_entry("agent", agent, AGENT_DIR, run_id))
        atomic_json(state_path, state)
        proxy = _spawn(proxy_command, runtime_dir=PROXY_DIR, run_id=run_id,
                       environment=environment)
        spawned.append(proxy)
        state["processes"].append(_entry("link", proxy, PROXY_DIR, run_id))
        atomic_json(state_path, state)
        _wait_for_ports(spawned)
        app_link_proxy.set_state(link_state_path, run_id=run_id, mode="up")
        return inspect(state_path)
    except Exception:
        if mode == "sitl" and spawned:
            # Never signal a SITL receiver on startup failure without a fresh
            # landed/disarmed proof. Preserve captured identity for recovery.
            state["unverified_pids"] = [process.pid for process in spawned[len(state["processes"]):]]
            atomic_json(state_path, state)
            raise DeploymentError("sitl_startup_failed_manual_intervention")
        if len(spawned) != len(state["processes"]):
            state["unverified_pids"] = [process.pid for process in spawned[len(state["processes"]):]]
            atomic_json(state_path, state)
            raise DeploymentError("startup_process_identity_unverified_manual_intervention")
        if state["processes"]:
            decisions = harness._terminate_process_groups(state["processes"], run_id=run_id)
            if any(row.code != harness.PROCESS_EXITED for row in decisions):
                atomic_json(state_path, state)
                raise DeploymentError("startup_cleanup_identity_or_exit_failure")
        state_path.unlink(missing_ok=True)
        raise


def start_fake(*, token_file: Path, state_path: Path = STATE_PATH) -> dict[str, Any]:
    return _start(token_file=token_file, mode="fake", state_path=state_path)


def start_sitl(*, token_file: Path, state_path: Path = STATE_PATH) -> dict[str, Any]:
    return _start(token_file=token_file, mode="sitl", state_path=state_path)


def _read_agent_status(token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{AGENT_PORT}/api/platform/status", method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=2) as response:
        data = response.read(65537)
        if len(data) > 65536:
            raise DeploymentError("sitl_stop_status_too_large")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise DeploymentError("sitl_stop_status_invalid")
        return response.status, value


def _sitl_safe_to_stop(state: dict[str, Any], *, sleep=time.sleep) -> None:
    if state.get("unverified_pids"):
        raise DeploymentError("unverified_process_requires_manual_intervention")
    run_id = state.get("run_id")
    current = harness.read_state() or {}
    if not run_id or current.get("run_id") != run_id:
        raise DeploymentError("managed_simulation_run_mismatch")
    processes = state.get("processes", [])
    if (not isinstance(processes, list) or len(processes) != 2
            or any(not isinstance(row, dict) for row in processes)
            or {(row.get("node_id"), row.get("kind")) for row in processes}
            != {("UAV-02-agent", "agent"), ("UAV-02-link", "link")}):
        raise DeploymentError("deployment_process_roles_invalid")
    decisions = harness._validate_processes(processes, run_id=run_id)
    if len(decisions) != 2 or any(row.code != harness.IDENTITY_MATCH for row in decisions):
        raise DeploymentError("deployment_process_identity_invalid")
    link_path = Path(state["link_state_path"]).resolve()
    if link_path != (PROXY_DIR / f"link_state.{run_id}.json").resolve():
        raise DeploymentError("link_state_path_mismatch")
    app_link_proxy.set_state(link_path, run_id=run_id, mode="down")
    sleep(3.2)  # Ground lease must expire before observing the final stop state.
    token_file = Path(state["token_file"])
    _validate_token_file(token_file)
    try:
        code, status = _read_agent_status(token_file.read_text(encoding="utf-8").strip())
    except Exception as exc:
        raise DeploymentError("sitl_stop_status_unavailable") from exc
    observation = status.get("platform_observation") or {}
    try:
        sample_age = time.time() - timestamp_seconds(observation.get("sample_timestamp"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise DeploymentError("sitl_stop_requires_fresh_landed_disarmed_evidence") from exc
    if (code != 200 or status.get("contract_version") != "1.0"
            or status.get("node_id") != "UAV-02" or status.get("run_id") != run_id
            or status.get("execution_mode") != "sitl" or status.get("safe_to_stop") is not True
            or (status.get("ground_link") or {}).get("state") != "lost"
            or status.get("active_task") is not None or observation.get("source") != "px4_telemetry"
            or observation.get("stale") is not False or observation.get("landed_fresh") is not True
            or observation.get("armed") is not False
            or type(observation.get("landed_state")) is not int or observation["landed_state"] != 1
            or not -0.1 <= sample_age <= 1.5):
        raise DeploymentError("sitl_stop_requires_fresh_landed_disarmed_evidence")


def stop_sitl(state_path: Path = STATE_PATH, *, sleep=time.sleep) -> dict[str, Any]:
    if not state_path.is_file():
        return {"status": "stopped", "idempotent": True}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("execution_mode") != "sitl":
        raise DeploymentError("not_a_sitl_deployment")
    _sitl_safe_to_stop(state, sleep=sleep)
    decisions = harness._terminate_process_groups(state["processes"], run_id=state["run_id"])
    if any(row.code != harness.PROCESS_EXITED for row in decisions):
        raise DeploymentError("stop_refused_process_identity_or_exit_failure")
    state_path.unlink()
    return {"status": "stopped", "idempotent": False, "run_id": state["run_id"]}


def stop_fake(state_path: Path = STATE_PATH) -> dict[str, Any]:
    if not state_path.is_file():
        return {"status": "stopped", "idempotent": True}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("execution_mode") != "fake":
        raise DeploymentError("sitl_stop_requires_fresh_landed_disarmed_evidence")
    if state.get("unverified_pids"):
        raise DeploymentError("unverified_process_requires_manual_intervention")
    processes = state["processes"]
    decisions = harness._terminate_process_groups(processes, run_id=state["run_id"])
    if any(row.code != harness.PROCESS_EXITED for row in decisions):
        raise DeploymentError("stop_refused_process_identity_or_exit_failure")
    state_path.unlink()
    return {"status": "stopped", "idempotent": False, "run_id": state["run_id"]}


def set_link(*, mode: str, delay_ms: int = 0, state_path: Path = STATE_PATH) -> dict[str, Any]:
    health = inspect(state_path)
    if health.get("status") != "process_ready":
        raise DeploymentError("managed_agent_or_proxy_not_ready")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    link = app_link_proxy.set_state(Path(state["link_state_path"]),
                                    run_id=state["run_id"], mode=mode, delay_ms=delay_ms)
    return {"status": "process_ready", "run_id": state["run_id"],
            "ground_link_mode": link["mode"], "delay_ms": link["delay_ms"],
            "generation": link["generation"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start-fake")
    start_parser.add_argument("--token-file", type=Path, required=True)
    sitl_parser = subparsers.add_parser("start-sitl")
    sitl_parser.add_argument("--token-file", type=Path, required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("stop-fake")
    subparsers.add_parser("stop-sitl")
    link_parser = subparsers.add_parser("link")
    link_parser.add_argument("--mode", choices=sorted(app_link_proxy.MODES), required=True)
    link_parser.add_argument("--delay-ms", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "start-fake":
            result = start_fake(token_file=args.token_file)
        elif args.command == "start-sitl":
            result = start_sitl(token_file=args.token_file)
        elif args.command == "stop-sitl":
            result = stop_sitl()
        elif args.command == "link":
            result = set_link(mode=args.mode, delay_ms=args.delay_ms)
        elif args.command == "status":
            result = inspect()
        else:
            result = stop_fake()
    except (DeploymentError, OSError, ValueError) as exc:
        result = {"status": "error", "reason": f"{type(exc).__name__}:{exc}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"process_ready", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
