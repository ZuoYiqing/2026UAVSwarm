"""Explicit Windows→WSL transport smoke. Uses synthetic UDP heartbeats, not SITL."""
from contextlib import ExitStack, closing
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep


ROOT = Path(__file__).resolve().parents[2]
ALIAS = "qwen3.5-4b-q4-lab"
MODEL_PORT = 18116
RUNTIME_PORT = 8765


def request(host, port, path, *, token=None, data=None, timeout=3):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection = HTTPConnection(host, port, timeout=timeout)
    with closing(connection):
        connection.request("GET" if data is None else "POST", path,
                           json.dumps(data) if data is not None else None, headers)
        with connection.getresponse() as response:
            return response.status, json.load(response)


def stop_owned(proc):
    if proc.poll() is None:
        proc.terminate() if os.name == "nt" else proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def wsl_probe(gateway, token_file):
    from pymavlink import mavutil

    token = Path(token_file).read_text(encoding="ascii").strip()
    deadline = monotonic() + 12
    while True:
        try:
            assert request(gateway, MODEL_PORT, "/health", token=token) == (200, {"status": "ok"})
            break
        except OSError:
            if monotonic() >= deadline:
                raise
            sleep(0.2)
    assert request(gateway, MODEL_PORT, "/health")[0] == 401
    assert ALIAS in {item["id"] for item in request(gateway, MODEL_PORT, "/v1/models", token=token)[1]["data"]}
    with closing(socket.socket()) as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", RUNTIME_PORT)) != 0, "Existing WSL Runtime was not changed"

    # Only the temporary probe uses these randomly selected loopback UDP ports.
    # The tracked deployment manifest and production 14540–14542 are not touched.
    manifest = ROOT / "simulation/px4_gazebo/config/three_uav_sitl.json"
    config = json.loads(manifest.read_text(encoding="utf-8"))
    config["scene_path"] = str(ROOT / config["scene_path"])
    with TemporaryDirectory(prefix="uav-wsl-model-runtime-") as temp, ExitStack() as resources:
        with ExitStack() as reserves:
            receivers = [reserves.enter_context(closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))
                         for _ in config["vehicles"]]
            for receiver in receivers:
                receiver.bind(("127.0.0.1", 0))
            for vehicle, receiver in zip(config["vehicles"], receivers):
                endpoint = f"127.0.0.1:{receiver.getsockname()[1]}"
                vehicle["command_endpoint"] = vehicle["telemetry_endpoint"] = f"udpin:{endpoint}"
        senders = [
            resources.enter_context(closing(mavutil.mavlink_connection(
                vehicle["telemetry_endpoint"].replace("udpin:", "udpout:", 1),
                source_system=vehicle["system_id"], source_component=vehicle["component_id"],
            )))
            for vehicle in config["vehicles"]
        ]
        stop_sending = Event()

        def heartbeats():
            while not stop_sending.is_set():
                for sender in senders:
                    sender.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                              mavutil.mavlink.MAV_AUTOPILOT_PX4, 0, 0,
                                              mavutil.mavlink.MAV_STATE_STANDBY)
                stop_sending.wait(0.15)

        worker = Thread(target=heartbeats, daemon=True)
        worker.start()

        def finish_heartbeats():
            stop_sending.set()
            worker.join(timeout=2)

        resources.callback(finish_heartbeats)
        temp = Path(temp)
        vehicles = temp / "vehicle-config.json"
        vehicles.write_text(json.dumps(config), encoding="utf-8")
        log = resources.enter_context((temp / "runtime.log").open("wb"))
        env = {key: value for key, value in os.environ.items() if not key.startswith("UAV_RUNTIME_")}
        env.update(
            PYTHONPATH=str(ROOT / "src"), UAV_RUNTIME_AUDIT_PATH=str(temp / "audit.jsonl"),
            UAV_RUNTIME_LOCAL_MODEL_ENABLED="1", UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S="18",
            UAV_RUNTIME_TELEMETRY_ENABLED="true", UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE=token_file,
            UAV_RUNTIME_LOCAL_MODEL_URL=f"http://{gateway}:{MODEL_PORT}/v1",
        )
        proc = subprocess.Popen([sys.executable, "-B", "-m", "uav_runtime.http.server",
                                 "--vehicle-config", str(vehicles)], cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        resources.callback(stop_owned, proc)
        deadline = monotonic() + 15
        while monotonic() < deadline and proc.poll() is None:
            try:
                if request("127.0.0.1", RUNTIME_PORT, "/api/health")[1]["status"] == "ok":
                    break
            except OSError:
                sleep(0.15)
        else:
            raise RuntimeError((temp / "runtime.log").read_text(encoding="utf-8", errors="replace"))
        before = request("127.0.0.1", RUNTIME_PORT, "/api/vehicle-snapshot")[1]["vehicles"]
        now = monotonic()
        status, preview = request("127.0.0.1", RUNTIME_PORT, "/api/planner/plan-mission", timeout=20,
                                  data={"objective": "\u5de1\u68c0\u897f\u5317\u533a\u57df\u3002", "dry_run": True})
        elapsed_ms = round((monotonic() - now) * 1000)
        after = request("127.0.0.1", RUNTIME_PORT, "/api/vehicle-snapshot")[1]["vehicles"]
        assert proc.poll() is None
        signals = {key: preview[key] for key in ("intent_source", "fallback_reason", "execution_authorized")}
        evidence = {"runtime_pid": proc.pid, "relay_health": "ok", "unauthenticated_health_status": 401,
                    "mode": "normal", "telemetry_source": "synthetic_heartbeats_not_sitl",
                    "connected_before": sorted(row["id"] for row in before if row["connected"]),
                    "connected_after": sorted(row["id"] for row in after if row["connected"]),
                    "usable_after": sorted(row["id"] for row in after if row["spatial"]["public_position_usable"]),
                    "preview_http_status": status, "elapsed_ms": elapsed_ms, **signals}
        print(json.dumps(evidence), flush=True)
        assert evidence["connected_before"] == evidence["connected_after"] == sorted(
            vehicle["node_id"] for vehicle in config["vehicles"]
        )
        assert status == 200 and signals == {
            "intent_source": "local_model", "fallback_reason": None, "execution_authorized": False,
        }


def windows_probe(distro, wsl_python):
    def wsl(*args):
        proc = subprocess.run(["wsl.exe", "-d", distro, "--exec", *args], check=True, timeout=12,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc.stdout.decode("utf-8").strip()

    assert request("127.0.0.1", MODEL_PORT, "/health") == (200, {"status": "ok"})
    gateway, = {row["gateway"] for row in json.loads(wsl("ip", "-j", "-4", "route", "show", "default"))}
    peer = json.loads(wsl("ip", "-j", "-4", "route", "get", gateway))[0]["prefsrc"]
    script = wsl("wslpath", "-a", str(Path(__file__).resolve()))
    with TemporaryDirectory(prefix="uav-wsl-model-relay-") as temp, ExitStack() as resources:
        token_file = Path(temp) / "token"
        token_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
        wsl_token = wsl("wslpath", "-a", str(token_file))
        log_path = Path(temp) / "relay.log"
        log = resources.enter_context(log_path.open("wb"))
        relay = subprocess.Popen(
            [sys.executable, "-B", "-m", "uav_runtime.http.wsl_model_relay", "--gateway", gateway,
             "--wsl-peer", peer, "--token-file", str(token_file)],
            cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
            stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        resources.callback(stop_owned, relay)
        try:
            result = subprocess.run(["wsl.exe", "-d", distro, "--exec", wsl_python, "-B", script,
                                     "--wsl-probe", gateway, wsl_token], timeout=75)
        finally:
            print(log_path.read_text(encoding="utf-8", errors="replace").strip(), flush=True)
        return result.returncode


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python optimization so verification assertions are active")
    if len(sys.argv) == 4 and sys.argv[1] == "--wsl-probe":
        wsl_probe(sys.argv[2], sys.argv[3])
    elif os.name == "nt" and len(sys.argv) == 3:
        raise SystemExit(windows_probe(sys.argv[1], sys.argv[2]))
    else:
        raise SystemExit("Run on Windows: python -B verify_wsl_runtime_model_route.py DISTRO WSL_PYTHON_PATH")
