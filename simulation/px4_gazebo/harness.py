#!/usr/bin/env python3
"""Manifest-driven PX4/Gazebo multi-instance harness.

The module contains only simulation process and binding logic. It does not
authorize Runtime actions or replace PX4's flight-control implementation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent.parent
DEFAULT_MANIFEST_PATH = HARNESS_DIR / "config" / "three_uav_sitl.json"
RUNTIME_ROOT = REPO_ROOT / ".runtime" / "px4_gazebo"
STATE_PATH = RUNTIME_ROOT / "harness_state.json"
MINIMUM_VEHICLE_COUNT = 3


class HarnessError(RuntimeError):
    """Raised when the harness cannot start or its configuration is unsafe."""


@dataclass(frozen=True, slots=True)
class GazeboPose:
    x_m: float
    y_m: float
    z_m: float
    roll_rad: float
    pitch_rad: float
    yaw_rad: float

    def px4_env_value(self) -> str:
        return ",".join(
            f"{value:.6f}"
            for value in (
                self.x_m,
                self.y_m,
                self.z_m,
                self.roll_rad,
                self.pitch_rad,
                self.yaw_rad,
            )
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise HarnessError(f"JSON root must be an object: {path}")
    return value


def resolve_repo_path(value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_px4_dir(manifest: dict[str, Any]) -> Path:
    configured = os.environ.get(
        "PX4_AUTOPILOT_DIR",
        str(manifest.get("px4_autopilot_dir", "~/PX4-Autopilot")),
    )
    return Path(os.path.expandvars(os.path.expanduser(configured))).resolve()


def normalize_angle_rad(value: float) -> float:
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


def ned_to_gazebo_pose(spawn_ned: dict[str, Any]) -> GazeboPose:
    """Convert local NED position/yaw to Gazebo ENU/Z-up."""
    yaw_ned_rad = math.radians(float(spawn_ned.get("yaw_deg", 0.0)))
    return GazeboPose(
        x_m=float(spawn_ned["y_m"]),
        y_m=float(spawn_ned["x_m"]),
        z_m=-float(spawn_ned["z_m"]),
        roll_rad=0.0,
        pitch_rad=0.0,
        yaw_rad=normalize_angle_rad((math.pi / 2.0) - yaw_ned_rad),
    )


def parse_udpin_endpoint(endpoint: str) -> tuple[str, int]:
    prefix = "udpin:"
    if not endpoint.startswith(prefix):
        raise HarnessError(f"endpoint must use udpin: syntax: {endpoint}")
    host_port = endpoint[len(prefix) :]
    try:
        host, raw_port = host_port.rsplit(":", 1)
        port = int(raw_port)
    except (ValueError, TypeError) as exc:
        raise HarnessError(f"invalid endpoint: {endpoint}") from exc
    if not host or not 1 <= port <= 65535:
        raise HarnessError(f"invalid endpoint: {endpoint}")
    return host, port


def validate_manifest(
    manifest: dict[str, Any],
    *,
    scene: dict[str, Any] | None = None,
) -> None:
    required = {
        "version",
        "px4_autopilot_dir",
        "build_target",
        "scene_id",
        "scene_path",
        "world_name",
        "world_path",
        "airframe_autostart",
        "px4_sim_model",
        "origin",
        "vehicles",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise HarnessError(f"manifest missing fields: {', '.join(missing)}")
    vehicles = manifest["vehicles"]
    if not isinstance(vehicles, list) or len(vehicles) < MINIMUM_VEHICLE_COUNT:
        raise HarnessError(f"manifest must define at least {MINIMUM_VEHICLE_COUNT} vehicles")

    unique_fields = (
        "node_id",
        "px4_instance",
        "system_id",
        "gazebo_model_name",
        "command_endpoint",
        "runtime_dir",
    )
    for field in unique_fields:
        values = [vehicle.get(field) for vehicle in vehicles]
        if any(value is None or value == "" for value in values):
            raise HarnessError(f"vehicle field is required: {field}")
        if len(set(values)) != len(values):
            raise HarnessError(f"vehicle field must be unique: {field}")

    for vehicle in vehicles:
        instance = int(vehicle["px4_instance"])
        system_id = int(vehicle["system_id"])
        expected_model = f"{str(manifest['px4_sim_model']).removeprefix('gz_')}_{instance}"
        if system_id != instance + 1:
            raise HarnessError(
                f"{vehicle['node_id']} system_id must equal px4_instance + 1 "
                f"for this PX4 build"
            )
        if vehicle["gazebo_model_name"] != expected_model:
            raise HarnessError(
                f"{vehicle['node_id']} expected Gazebo model {expected_model}"
            )
        if vehicle.get("command_endpoint") != vehicle.get("telemetry_endpoint"):
            raise HarnessError(
                f"{vehicle['node_id']} command and telemetry endpoints must share "
                "the PX4 offboard link in v0.1"
            )
        _, endpoint_port = parse_udpin_endpoint(str(vehicle["command_endpoint"]))
        expected_remote_port = 14540 + instance if instance <= 9 else 14549
        if endpoint_port != expected_remote_port:
            raise HarnessError(
                f"{vehicle['node_id']} endpoint port must be {expected_remote_port}"
            )
        if int(vehicle["px4_mavlink_local_port"]) != 14580 + instance:
            raise HarnessError(
                f"{vehicle['node_id']} px4_mavlink_local_port does not match PX4 rule"
            )
        if int(vehicle["gcs_local_port"]) != 18570 + instance:
            raise HarnessError(
                f"{vehicle['node_id']} gcs_local_port does not match PX4 rule"
            )
        ned_to_gazebo_pose(vehicle["spawn_ned"])

    if scene is not None:
        validate_scene_binding(manifest, scene)


def validate_scene_binding(
    manifest: dict[str, Any],
    scene: dict[str, Any],
) -> None:
    if manifest["scene_id"] != scene.get("scene_id"):
        raise HarnessError("manifest scene_id does not match scene.json")
    if scene.get("frame") != "local_ned":
        raise HarnessError("three-UAV harness requires scene frame local_ned")
    if manifest.get("origin") != scene.get("origin"):
        raise HarnessError("manifest origin does not match scene.json origin")

    scene_vehicles = {
        str(vehicle["node_id"]): vehicle for vehicle in scene.get("vehicles", [])
    }
    manifest_vehicles = {
        str(vehicle["node_id"]): vehicle for vehicle in manifest["vehicles"]
    }
    if set(scene_vehicles) != set(manifest_vehicles):
        raise HarnessError("manifest and scene.json vehicle IDs differ")
    for node_id, binding in manifest_vehicles.items():
        if scene_vehicles[node_id].get("initial_pose") != binding.get("spawn_ned"):
            raise HarnessError(f"{node_id} spawn differs between manifest and scene.json")


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest = load_json(path.resolve())
    scene = load_json(resolve_repo_path(str(manifest["scene_path"])))
    validate_manifest(manifest, scene=scene)
    return manifest


def mapping_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vehicle in manifest["vehicles"]:
        gazebo_pose = ned_to_gazebo_pose(vehicle["spawn_ned"])
        rows.append(
            {
                "node_id": vehicle["node_id"],
                "px4_instance": int(vehicle["px4_instance"]),
                "system_id": int(vehicle["system_id"]),
                "gazebo_model_name": vehicle["gazebo_model_name"],
                "command_endpoint": vehicle["command_endpoint"],
                "telemetry_endpoint": vehicle["telemetry_endpoint"],
                "spawn_ned": vehicle["spawn_ned"],
                "spawn_gazebo": {
                    "x_m": gazebo_pose.x_m,
                    "y_m": gazebo_pose.y_m,
                    "z_m": gazebo_pose.z_m,
                    "yaw_rad": gazebo_pose.yaw_rad,
                },
                "runtime_dir": vehicle["runtime_dir"],
            }
        )
    return rows


def print_mapping_table(manifest: dict[str, Any]) -> None:
    header = (
        "node_id  instance  sysid  gazebo_model  endpoint                    "
        "spawn NED (m)      runtime_dir"
    )
    print(header)
    print("-" * len(header))
    for row in mapping_rows(manifest):
        spawn = row["spawn_ned"]
        spawn_text = f"({spawn['x_m']},{spawn['y_m']},{spawn['z_m']})"
        print(
            f"{row['node_id']:<8} "
            f"{row['px4_instance']:<9} "
            f"{row['system_id']:<6} "
            f"{row['gazebo_model_name']:<13} "
            f"{row['command_endpoint']:<27} "
            f"{spawn_text:<18} "
            f"{row['runtime_dir']}"
        )


def udp_port_available(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def required_udp_ports(manifest: dict[str, Any]) -> list[tuple[str, int, str]]:
    ports: list[tuple[str, int, str]] = []
    for vehicle in manifest["vehicles"]:
        instance = int(vehicle["px4_instance"])
        host, endpoint_port = parse_udpin_endpoint(str(vehicle["command_endpoint"]))
        ports.extend(
            (
                (host, endpoint_port, f"{vehicle['node_id']} runtime listener"),
                ("127.0.0.1", 14580 + instance, f"{vehicle['node_id']} offboard local"),
                ("127.0.0.1", 18570 + instance, f"{vehicle['node_id']} GCS local"),
                ("127.0.0.1", 14280 + instance, f"{vehicle['node_id']} payload local"),
                ("127.0.0.1", 13030 + instance, f"{vehicle['node_id']} gimbal local"),
            )
        )
    return ports


def process_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ProcessLookupError, ValueError):
        return False
    return True


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        return load_json(STATE_PATH)
    except (OSError, json.JSONDecodeError, HarnessError):
        return None


def gazebo_models() -> set[str]:
    try:
        result = subprocess.run(
            ["gz", "model", "--list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {
        line.strip().lstrip("-").strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("available models")
    }


def wait_for_model(model_name: str, process: subprocess.Popen[Any], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HarnessError(
                f"PX4 exited before Gazebo model {model_name} became ready "
                f"(exit={process.returncode})"
            )
        if model_name in gazebo_models():
            return
        time.sleep(1.0)
    raise HarnessError(f"timed out waiting for Gazebo model {model_name}")


def command_output(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _foreign_px4_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-x", "px4"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _running_gazebo_worlds() -> list[str]:
    try:
        result = subprocess.run(
            ["gz", "topic", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    worlds = []
    for line in result.stdout.splitlines():
        if line.startswith("/world/") and line.endswith("/clock"):
            worlds.append(line.removeprefix("/world/").removesuffix("/clock"))
    return sorted(set(worlds))


def preflight(manifest: dict[str, Any]) -> dict[str, Any]:
    if os.name != "posix":
        raise HarnessError("PX4/Gazebo multi-vehicle harness must run inside Linux/WSL")

    px4_dir = resolve_px4_dir(manifest)
    build_dir = px4_dir / "build" / str(manifest["build_target"])
    binary = build_dir / "bin" / "px4"
    etc_dir = build_dir / "etc"
    world_path = resolve_repo_path(str(manifest["world_path"]))
    if not px4_dir.is_dir():
        raise HarnessError(f"PX4_AUTOPILOT_DIR not found: {px4_dir}")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise HarnessError(
            f"PX4 SITL binary missing: {binary}; run 'make px4_sitl' first"
        )
    if not etc_dir.is_dir():
        raise HarnessError(f"PX4 etc directory missing: {etc_dir}")
    if not world_path.is_file():
        raise HarnessError(f"Gazebo world missing: {world_path}")

    current_state = read_state()
    if current_state and any(
        process_alive(int(item["pid"])) for item in current_state.get("processes", [])
    ):
        raise HarnessError("this harness is already running; stop it first")
    foreign_px4 = _foreign_px4_pids()
    if foreign_px4:
        raise HarnessError(
            "other PX4 processes are running; stop them explicitly before starting "
            f"the harness: {foreign_px4}"
        )
    worlds = _running_gazebo_worlds()
    if worlds:
        raise HarnessError(
            "another Gazebo world is running; stop it explicitly before starting "
            f"the harness: {worlds}"
        )

    occupied = [
        f"{label} {host}:{port}"
        for host, port, label in required_udp_ports(manifest)
        if not udp_port_available(host, port)
    ]
    if occupied:
        raise HarnessError("UDP ports are already occupied: " + ", ".join(occupied))

    try:
        px4_commit = command_output(["git", "-C", str(px4_dir), "rev-parse", "HEAD"])
        gazebo_version = command_output(["gz", "sim", "--versions"]).splitlines()[0]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HarnessError(f"failed to inspect PX4/Gazebo environment: {exc}") from exc
    return {
        "px4_dir": px4_dir,
        "build_dir": build_dir,
        "binary": binary,
        "etc_dir": etc_dir,
        "world_path": world_path,
        "px4_commit": px4_commit,
        "gazebo_version": gazebo_version,
    }


def px4_environment(
    manifest: dict[str, Any],
    vehicle: dict[str, Any],
    *,
    environment: dict[str, Any],
    headless: bool,
    standalone: bool,
) -> dict[str, str]:
    px4_dir = Path(environment["px4_dir"])
    build_dir = Path(environment["build_dir"])
    world_path = Path(environment["world_path"])
    origin = manifest["origin"]
    gazebo_pose = ned_to_gazebo_pose(vehicle["spawn_ned"])
    env = os.environ.copy()
    env.update(
        {
            "PX4_SYS_AUTOSTART": str(manifest["airframe_autostart"]),
            "PX4_SIM_MODEL": str(manifest["px4_sim_model"]),
            "PX4_GZ_MODEL_POSE": gazebo_pose.px4_env_value(),
            "PX4_GZ_WORLD": str(manifest["world_name"]),
            "PX4_HOME_LAT": str(origin["lat_deg"]),
            "PX4_HOME_LON": str(origin["lon_deg"]),
            "PX4_HOME_ALT": str(origin["alt_m"]),
            "PX4_GZ_MODELS": str(px4_dir / "Tools" / "simulation" / "gz" / "models"),
            "PX4_GZ_WORLDS": str(world_path.parent),
            "PX4_GZ_PLUGINS": str(
                build_dir / "src" / "modules" / "simulation" / "gz_plugins"
            ),
            "PX4_GZ_SERVER_CONFIG": str(
                px4_dir / "src" / "modules" / "simulation" / "gz_bridge" / "server.config"
            ),
            "GZ_SIM_SERVER_CONFIG_PATH": str(
                px4_dir / "src" / "modules" / "simulation" / "gz_bridge" / "server.config"
            ),
            "GZ_IP": "127.0.0.1",
        }
    )
    resource_paths = [
        env["PX4_GZ_MODELS"],
        str(world_path.parent),
        os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
    ]
    plugin_paths = [
        env["PX4_GZ_PLUGINS"],
        os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
    ]
    env["GZ_SIM_RESOURCE_PATH"] = ":".join(path for path in resource_paths if path)
    env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = ":".join(
        path for path in plugin_paths if path
    )
    if standalone:
        env["PX4_GZ_STANDALONE"] = "1"
    else:
        env.pop("PX4_GZ_STANDALONE", None)
    if headless:
        env["HEADLESS"] = "1"
    else:
        env.pop("HEADLESS", None)
    return env


def _write_state(state: dict[str, Any]) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def _terminate_process_groups(processes: list[dict[str, Any]]) -> None:
    for item in reversed(processes):
        pgid = int(item.get("pgid") or item["pid"])
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not any(process_alive(int(item["pid"])) for item in processes):
            return
        time.sleep(0.25)
    for item in reversed(processes):
        pgid = int(item.get("pgid") or item["pid"])
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            continue


def start_harness(manifest_path: Path, *, headless: bool) -> None:
    manifest = load_manifest(manifest_path)
    environment = preflight(manifest)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "version": "1.0",
        "manifest_path": str(manifest_path.resolve()),
        "started_at": utc_now(),
        "mode": "headless" if headless else "gui",
        "px4_commit": environment["px4_commit"],
        "gazebo_version": environment["gazebo_version"],
        "world_name": manifest["world_name"],
        "processes": [],
    }
    opened_logs: list[Any] = []
    try:
        for index, vehicle in enumerate(manifest["vehicles"]):
            runtime_dir = resolve_repo_path(str(vehicle["runtime_dir"]))
            runtime_dir.mkdir(parents=True, exist_ok=True)
            stdout_handle = (runtime_dir / "stdout.log").open("ab", buffering=0)
            stderr_handle = (runtime_dir / "stderr.log").open("ab", buffering=0)
            opened_logs.extend((stdout_handle, stderr_handle))
            command = [
                str(environment["binary"]),
                "-i",
                str(vehicle["px4_instance"]),
                "-d",
                str(environment["etc_dir"]),
            ]
            process = subprocess.Popen(
                command,
                cwd=runtime_dir,
                env=px4_environment(
                    manifest,
                    vehicle,
                    environment=environment,
                    headless=headless,
                    standalone=index > 0,
                ),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            process_row = {
                "kind": "px4",
                "node_id": vehicle["node_id"],
                "pid": process.pid,
                "pgid": os.getpgid(process.pid),
                "owns_gazebo": index == 0,
                "runtime_dir": str(runtime_dir),
            }
            state["processes"].append(process_row)
            (runtime_dir / "px4.pid").write_text(str(process.pid), encoding="ascii")
            _write_state(state)
            wait_for_model(
                str(vehicle["gazebo_model_name"]),
                process,
                timeout_s=75.0 if index == 0 else 45.0,
            )
            print(f"{vehicle['node_id']} ready: pid={process.pid}")
        print()
        print_mapping_table(manifest)
        print(f"\nHarness state: {STATE_PATH}")
    except Exception:
        _terminate_process_groups(state["processes"])
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        raise
    finally:
        for handle in opened_logs:
            handle.close()


def stop_harness() -> None:
    state = read_state()
    if not state:
        print("No harness state found; nothing to stop.")
        return
    processes = list(state.get("processes", []))
    _terminate_process_groups(processes)
    for item in processes:
        runtime_dir = Path(str(item.get("runtime_dir", "")))
        pid_path = runtime_dir / "px4.pid"
        if pid_path.exists():
            pid_path.unlink()
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    alive = [item for item in processes if process_alive(int(item["pid"]))]
    if alive:
        raise HarnessError(f"failed to stop harness processes: {alive}")
    print("Three-UAV PX4/Gazebo harness stopped.")


def probe_heartbeat(endpoint: str, timeout_s: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        from pymavlink import mavutil  # type: ignore
    except ImportError:
        return {
            "heartbeat_received": False,
            "observed_system_id": None,
            "last_heartbeat_age_s": None,
            "error": "pymavlink_missing",
        }
    connection = None
    try:
        connection = mavutil.mavlink_connection(endpoint, timeout=max(timeout_s, 0.1))
        heartbeat = connection.wait_heartbeat(timeout=max(timeout_s, 0.1))
        if heartbeat is None:
            raise TimeoutError("heartbeat_timeout")
        return {
            "heartbeat_received": True,
            "observed_system_id": int(heartbeat.get_srcSystem()),
            "last_heartbeat_age_s": round(time.monotonic() - started, 3),
            "error": None,
        }
    except Exception as exc:
        return {
            "heartbeat_received": False,
            "observed_system_id": None,
            "last_heartbeat_age_s": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()


def collect_health(
    manifest: dict[str, Any],
    *,
    timeout_s: float,
    heartbeat_probe: Callable[[str, float], dict[str, Any]] = probe_heartbeat,
    process_probe: Callable[[int], bool] = process_alive,
    model_probe: Callable[[], set[str]] = gazebo_models,
) -> dict[str, Any]:
    state = read_state() or {}
    pid_by_node = {
        str(item.get("node_id")): int(item["pid"])
        for item in state.get("processes", [])
        if item.get("node_id") and item.get("pid")
    }
    models = model_probe()
    vehicles = []
    for vehicle in manifest["vehicles"]:
        heartbeat = heartbeat_probe(str(vehicle["telemetry_endpoint"]), timeout_s)
        expected_system_id = int(vehicle["system_id"])
        observed_system_id = heartbeat.get("observed_system_id")
        pid = pid_by_node.get(str(vehicle["node_id"]))
        row = {
            "node_id": vehicle["node_id"],
            "expected_system_id": expected_system_id,
            "observed_system_id": observed_system_id,
            "heartbeat_received": bool(heartbeat.get("heartbeat_received")),
            "endpoint": vehicle["telemetry_endpoint"],
            "gazebo_model_name": vehicle["gazebo_model_name"],
            "model_binding": vehicle["gazebo_model_name"] in models,
            "process_pid": pid,
            "process_alive": bool(pid and process_probe(pid)),
            "last_heartbeat_age_s": heartbeat.get("last_heartbeat_age_s"),
            "error": heartbeat.get("error"),
        }
        row["readiness"] = (
            row["heartbeat_received"]
            and observed_system_id == expected_system_id
            and row["process_alive"]
            and row["model_binding"]
        )
        vehicles.append(row)
    observed_ids = [
        row["observed_system_id"]
        for row in vehicles
        if row["observed_system_id"] is not None
    ]
    unique_system_ids = len(observed_ids) == len(set(observed_ids))
    ready = all(row["readiness"] for row in vehicles) and unique_system_ids
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "scene_id": manifest["scene_id"],
        "world_name": manifest["world_name"],
        "unique_system_ids": unique_system_ids,
        "checked_at": utc_now(),
        "vehicles": vehicles,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-config", "mapping", "start"):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--config",
            type=Path,
            default=DEFAULT_MANIFEST_PATH,
        )
        if name == "start":
            mode = command.add_mutually_exclusive_group()
            mode.add_argument("--headless", action="store_true")
            mode.add_argument("--gui", action="store_true")
    subparsers.add_parser("stop")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            manifest = load_manifest(args.config)
            print(json.dumps({"status": "valid", "vehicles": mapping_rows(manifest)}, indent=2))
        elif args.command == "mapping":
            print_mapping_table(load_manifest(args.config))
        elif args.command == "start":
            start_harness(args.config, headless=bool(args.headless))
        elif args.command == "stop":
            stop_harness()
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
