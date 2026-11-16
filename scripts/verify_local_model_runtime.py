"""Opt-in Linux CPU model + Runtime verification; fake observations/actions only.

Never imports a MAVLink adapter or starts the legacy three-vehicle HTTP server.
The bundle is read-only. Logs, SQLite and reports go to a new output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from uav_runtime.platform.contract import stamp
from uav_runtime.platform.server import PlatformHttpServer
from uav_runtime.platform.service import PlatformService
from uav_runtime.platform.store import TaskStore
from uav_runtime.platform.transport import JsonClient, NoRedirect


MODEL_HASH = "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517"
OPENER = build_opener(ProxyHandler({}), NoRedirect())


def available_memory(host_gib=None, host_measured_at=None):
    linux = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    result = {"linux_available_gib": int(linux["MemAvailable"].split()[0]) / 1024**2}
    if "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower():
        if (host_gib is None or host_measured_at is None or not math.isfinite(host_gib)
                or not math.isfinite(host_measured_at) or not 0 <= time.time() - host_measured_at <= 60):
            raise RuntimeError("WSL requires Windows host memory measured externally within 60 seconds")
        result["windows_available_gib"] = host_gib
        result["host_measured_at"] = stamp(host_measured_at)
    if min(v for k, v in result.items() if k.endswith("_gib")) < 3:
        raise RuntimeError(f"available RAM below existing 3 GiB guard: {result}")
    return result


def request(url, body=None, token=None, timeout=5):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, headers=headers, data=None if body is None else json.dumps(body).encode())
    started = time.perf_counter()
    try:
        response = OPENER.open(req, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise RuntimeError("verification response too large")
        return response.status, json.loads(data), round((time.perf_counter() - started) * 1000, 3)


def wait_ready(process, url, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"owned child exited: {process.returncode}; inspect output logs")
        try:
            code, body, _ = request(url, timeout=1)
            if code == 200:
                return body
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("service readiness timeout")


def ensure_ports_available(ports):
    for port in ports:
        with socket.socket() as probe:
            # Linux TIME_WAIT from our completed HTTP experiment is not a
            # listener. Reuse does not permit binding an actively listening
            # TCP address, and no process is ever killed on a failed probe.
            if os.name == "posix":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))


def task(name):
    return {"contract_version": "1.0", "node_id": "UAV-02", "task_id": name, "task_version": 1,
            "request_id": "request-" + name, "trace_id": "trace-" + name,
            "authorization": {"operator_id": "synthetic-local-verification", "expires_at": stamp(time.time() + 600),
                              "offline_policy": "continue_authorized", "max_altitude_m": 3, "max_hold_s": 10},
            "steps": [{"step_id": "takeoff-1", "action": "takeoff", "params": {"altitude_m": 3}},
                      {"step_id": "hold-1", "action": "hold_position", "params": {"hold_s": 3}},
                      {"step_id": "land-1", "action": "land", "params": {}}]}


def observation(armed=False):
    return {"source": "fake", "sample_timestamp": stamp(time.time()), "stale": False,
            "local_position": {"x_m": 0, "y_m": 0, "z_down_m": -3 if armed else 0},
            "armed": armed, "landed_state": 2 if armed else 1, "landed_fresh": True}


def candidate_request(index, action="takeoff"):
    body = task(f"synthetic-{index}")
    step = next(s for s in body["steps"] if s["action"] == action)
    return {"contract_version": "1.0", **{k: body[k] for k in ("node_id", "task_id", "task_version", "request_id", "trace_id")},
            "execution_id": "execution-" + str(index), "step_id": step["step_id"], "snapshot_id": body["request_id"],
            "decision_timeout_ms": 2000, "ground_link": {"state": "healthy"}, "authorization": body["authorization"],
            "next_step": step, "observation": observation(action != "takeoff"),
            "allowed_options": [{"option_id": "execute_authorized_step", "action_type": action, "params": step["params"]},
                                {"option_id": "abort_to_land", "action_type": "land", "params": {}}]}


def platform_case(output, name, *, disconnect=False):
    """Exercise the real authenticated HTTP/task/policy store with fake execution."""
    store = TaskStore(output / name)
    calls, armed, candidate_calls = [], [False], []
    heartbeat_enabled = threading.Event()
    heartbeat_enabled.set()
    stop = threading.Event()
    client = JsonClient("http://127.0.0.1:8872/candidate")

    def execute(t, step):
        calls.append(step["action"])
        if step["action"] == "takeoff":
            armed[0] = True
            if disconnect:
                heartbeat_enabled.clear()
                time.sleep(3.3)  # Expire only the ground lease; sensor samples remain fresh.
        elif step["action"] == "land":
            armed[0] = False
        return PlatformService._fake_execute(t, step)

    def query_candidate(body):
        started = time.perf_counter()
        try:
            code, reply = client.request("POST", body=body)
            candidate_calls.append({"step_id": body["step_id"], "http_status": code,
                                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "response": reply})
            return code, reply
        except Exception as exc:
            candidate_calls.append({"step_id": body["step_id"], "error_class": type(exc).__name__,
                                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)})
            raise

    service = PlatformService(store, execute=execute, observe=lambda: observation(armed[0]), candidate=query_candidate)
    token = secrets.token_hex(24)
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def heartbeat():
        while not stop.is_set():
            if heartbeat_enabled.is_set():
                request(base + "/api/platform/link/heartbeat", {}, token)
            stop.wait(0.4)

    request(base + "/api/platform/link/heartbeat", {}, token)
    heartbeats = threading.Thread(target=heartbeat, daemon=True)
    heartbeats.start()
    service.start()
    body = task(name)
    try:
        unauthorized = request(base + "/api/platform/status")[0]
        code, accepted, _ = request(base + "/api/platform/tasks", body, token)
        assert code == 202, accepted
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            _, queried, _ = request(base + "/api/platform/tasks/" + name, token=token)
            if queried["task"]["status"] not in {"accepted", "executing"}:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("fake task did not finish within verification budget")
        _, replay, _ = request(base + "/api/platform/tasks", body, token)
        _, events, _ = request(base + "/api/platform/events", token=token)
        result = {"task": queried["task"], "events": events, "fake_actions": list(calls),
                  "unauthenticated_status": unauthorized, "ground_link_after": service.link(),
                  "same_execution_on_replay": replay["task"]["execution_id"] == accepted["task"]["execution_id"],
                  "idempotent_replay": replay["idempotent_replay"], "flight_command_sent": False,
                  "candidate_calls": candidate_calls}
        assert unauthorized == 401
        assert result["same_execution_on_replay"] and result["idempotent_replay"]
        assert len(calls) == len(set(calls))
        return result
    finally:
        stop.set()
        heartbeats.join(timeout=6)
        service.stop.set()
        with store.changed:
            store.changed.notify_all()
        if service.worker:
            service.worker.join(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if service._model_thread:
            service._model_thread.join(timeout=5)
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-commit", required=True,
                        help="Verified full SHA from the checkout's owning Windows Git; WSL cannot resolve its gitdir")
    parser.add_argument("--host-available-gib", type=float)
    parser.add_argument("--host-measured-at", type=float, help="UTC Unix seconds from the external Windows memory check")
    parser.add_argument("--context-size", type=int, choices=[512, 2048], default=512)
    parser.add_argument("--candidate-source", type=Path,
                        help="Optional version-verified algorithm_lab root; original bundle stays read-only")
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    source = (args.candidate_source or bundle / "algorithm_lab").resolve()
    if os.name != "posix" or not Path("/proc/meminfo").exists():
        parser.error("requires Linux; this script does not prepare Windows or ARM64 engines")
    if re.fullmatch(r"[0-9a-f]{40}", args.runtime_commit) is None:
        parser.error("--runtime-commit requires a verified full commit SHA")
    output.mkdir(parents=True, exist_ok=False)
    report = {"started_at": stamp(time.time()), "flight_command_sent": False, "observation_source": "fake",
              "context_size": args.context_size, "runtime_commit": args.runtime_commit,
              "verification_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "candidate_source": str(source),
              "candidate_source_sha256": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in sorted((source / "platform_candidate_lab").rglob("*.py"))
                                          if "tests" not in p.parts},
              "samples": [], "platform_cases": {}}
    children, logs = [], []
    try:
        report["memory_before"] = available_memory(args.host_available_gib, args.host_measured_at)
        ensure_ports_available((18080, 8872))
        model = bundle / "models/Qwen3.5-0.8B-Q4_K_M.gguf"
        h = hashlib.sha256()
        with model.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        digest = h.hexdigest()
        if digest != MODEL_HASH:
            raise RuntimeError("pinned model hash mismatch")
        report["model_sha256"] = digest
        engine = bundle / "runtime/llama-b10964"
        env = {**os.environ, "LD_LIBRARY_PATH": str(engine), "PYTHONDONTWRITEBYTECODE": "1"}
        report["engine_version"] = subprocess.check_output([str(engine / "llama-server"), "--version"],
                                                           env=env, stderr=subprocess.STDOUT, timeout=10, text=True).strip()
        report["engine_binary_sha256"] = hashlib.sha256((engine / "llama-server").read_bytes()).hexdigest()
        report["python_version"] = os.sys.version
        commands = [[str(engine / "llama-server"), "-m", str(model), "--alias", "qwen3.5-0.8b-q4-lab",
                     "--host", "127.0.0.1", "--port", "18080", "--offline", "--no-webui", "--no-agent",
                     "--no-ui-mcp-proxy", "--ctx-size", str(args.context_size), "--parallel", "1", "--threads", "4",
                     "--threads-batch", "4", "--gpu-layers", "0", "--reasoning", "off", "--no-context-shift"],
                    [os.sys.executable, "-B", "-m", "platform_candidate_lab", "serve", "--model-url",
                     "http://127.0.0.1:18080/v1/chat/completions", "--model-id", "qwen3.5-0.8b-q4-lab",
                     "--port", "8872", "--allow-fake"]]
        report["commands"] = commands
        started = time.perf_counter()
        for name, command, url in zip(("model", "candidate"), commands,
                                     ("http://127.0.0.1:18080/health", "http://127.0.0.1:8872/health")):
            log = (output / (name + ".log")).open("wb")
            logs.append(log)
            child_env = dict(env)
            if name == "candidate":
                child_env["PYTHONPATH"] = str(source)
            child = subprocess.Popen(command, cwd=bundle, env=child_env, stdout=log, stderr=subprocess.STDOUT)
            children.append(child)
            report[name + "_health"] = wait_ready(child, url)
        report["load_and_service_ready_ms"] = round((time.perf_counter() - started) * 1000, 3)
        print("model_loaded_and_candidate_alive", flush=True)
        for index, action in enumerate(("takeoff", "takeoff", "takeoff", "hold_position", "hold_position", "land")):
            body = candidate_request(index, action)
            code, reply, elapsed = request("http://127.0.0.1:8872/candidate", body, timeout=5)
            report["samples"].append({"index": index, "kind": "cold" if index == 0 else "warm_not_independent",
                                      "request": body, "http_status": code, "elapsed_ms": elapsed, "response": reply})
            print(f"sample={index} status={reply.get('status')} reason={reply.get('failure_reason_code')} elapsed_ms={elapsed}", flush=True)
            time.sleep(0.15)
        stale = candidate_request("stale")
        stale["observation"]["stale"] = True
        lost = candidate_request("lost")
        lost["ground_link"]["state"] = "lost"
        for name, body in (("stale", stale), ("lost_takeoff", lost)):
            code, reply, elapsed = request("http://127.0.0.1:8872/candidate", body)
            report[name] = {"http_status": code, "response": reply, "elapsed_ms": elapsed}
            assert reply["status"] == "no_candidate" and reply["execution_authorized"] is False
        for name, disconnect in (("healthy", False), ("lost_after_takeoff", True)):
            report["platform_cases"][name] = platform_case(output, name, disconnect=disconnect)
            print(f"platform={name} status={report['platform_cases'][name]['task']['status']}", flush=True)
        children[0].terminate()
        children[0].wait(timeout=10)
        report["platform_cases"]["model_unavailable"] = platform_case(output, "model_unavailable")
        report["model_candidate_integration_passed"] = all(
            case["task"]["status"] == "succeeded" and len([
                e for e in case["events"]["events"] if e["event_type"] == "model_candidate"]) == 3
            for name, case in report["platform_cases"].items() if name != "model_unavailable")
        report["verification_completed"] = True
    except Exception as exc:
        report["error"] = {"class": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in logs:
            log.close()
        report["finished_at"] = stamp(time.time())
        report["owned_children_stopped"] = all(child.poll() is not None for child in children)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(output / "report.json"), flush=True)
    return 0 if report["model_candidate_integration_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
